"""Update checks against the project's GitHub releases.

The latest release is read from GitHub's public API (no token needed; the
unauthenticated limit of 60 requests/hour per IP is far above what a few
checks a day use). A release is offered when its version is newer than the
running one and it carries a Windows installer asset. Downloads are verified
against the size GitHub reports and, when GitHub provides one, the asset's
SHA-256 digest before anything is run.

Qt-free and network-injectable so the parsing and comparison logic is unit
tested; the UI (``ui.update_ui``) runs these calls off the GUI thread.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from . import __version__

GITHUB_REPO = "Control-Point-FTC/wyze-print-monitor"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
INSTALLER_PATTERN = re.compile(r"^WyzePrintMonitor-.*-setup\.exe$", re.IGNORECASE)
USER_AGENT = f"WyzePrintMonitor/{__version__}"
# Inno Setup flags: no wizard pages, no prompts, close the app if still open.
INSTALLER_ARGS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")
EXIT_WAIT_SECONDS = 120


class UpdateError(Exception):
    """A check or download failed (network, bad response, bad file)."""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str           # "1.2.0" (tag without the leading v)
    page_url: str          # human release page
    notes: str = ""
    installer_url: str = ""
    installer_name: str = ""
    installer_size: int = 0
    installer_sha256: str = ""  # hex, if GitHub reported a digest


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' / '1.2' / '1.2.3-beta' -> (1, 2, 3) / (1, 2) / (1, 2, 3).

    Anything after the numeric dotted part is ignored; nothing numeric -> ().
    """
    match = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate: str, current: str = __version__) -> bool:
    """True if ``candidate`` is a strictly higher version than ``current``.
    Missing trailing parts count as zero (1.2 == 1.2.0)."""
    a, b = parse_version(candidate), parse_version(current)
    if not a:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def release_from_json(data: dict) -> ReleaseInfo | None:
    """Build a ReleaseInfo from GitHub's 'latest release' JSON, or None for
    drafts / pre-releases / payloads without a version."""
    if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name") or "")
    if not parse_version(tag):
        return None
    info = {
        "version": tag.lstrip("vV"),
        "page_url": str(data.get("html_url") or RELEASES_PAGE),
        "notes": str(data.get("body") or ""),
    }
    for asset in data.get("assets") or []:
        name = str(asset.get("name") or "")
        if INSTALLER_PATTERN.match(name):
            digest = str(asset.get("digest") or "")
            info.update(
                installer_url=str(asset.get("browser_download_url") or ""),
                installer_name=name,
                installer_size=int(asset.get("size") or 0),
                installer_sha256=digest[7:].lower() if digest.lower().startswith("sha256:") else "",
            )
            break
    return ReleaseInfo(**info)


def _open(url: str, timeout: float, accept: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - fixed https URLs


def fetch_latest(timeout: float = 15.0, opener=_open) -> ReleaseInfo | None:
    """The latest published release, or None if there is none yet."""
    try:
        with opener(LATEST_RELEASE_API, timeout, "application/vnd.github+json") as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # no releases published yet
            return None
        raise UpdateError(f"GitHub returned HTTP {exc.code} while checking for updates.") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise UpdateError(f"Couldn't check for updates: {exc}") from exc
    return release_from_json(data)


def download_installer(
    release: ReleaseInfo,
    dest_dir: str,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    timeout: float = 30.0,
    opener=_open,
) -> str:
    """Download the release's installer into ``dest_dir`` and verify it.
    Returns the file path. Raises UpdateError on failure or cancellation."""
    if not release.installer_url or not release.installer_name:
        raise UpdateError("This release has no Windows installer to download.")
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, os.path.basename(release.installer_name))
    partial = path + ".part"
    sha = hashlib.sha256()
    received = 0
    try:
        with opener(release.installer_url, timeout, "application/octet-stream") as response, open(partial, "wb") as fh:
            total = int(response.headers.get("Content-Length") or release.installer_size or 0)
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateError("Download cancelled.")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                sha.update(chunk)
                received += len(chunk)
                if progress is not None:
                    progress(received, total)
    except UpdateError:
        _remove(partial)
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        _remove(partial)
        raise UpdateError(f"Download failed: {exc}") from exc
    if release.installer_size and received != release.installer_size:
        _remove(partial)
        raise UpdateError("The downloaded installer is incomplete; please try again.")
    if release.installer_sha256 and sha.hexdigest() != release.installer_sha256:
        _remove(partial)
        raise UpdateError("The downloaded installer failed its integrity check; it was deleted.")
    os.replace(partial, path)
    return path


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def installer_launch_command(pid: int, installer: str) -> list[str]:
    """A hidden PowerShell helper that waits for process ``pid`` (this app)
    to exit, then runs the installer silently.

    Starting setup while the app is still shutting down would let Inno
    Setup's AppMutex check see it running and, with prompts suppressed,
    cancel the update. The script is passed base64-encoded, so no path can
    break its quoting.
    """
    quoted = installer.replace("'", "''")
    args = ",".join(f"'{a}'" for a in INSTALLER_ARGS)
    script = (
        "$ErrorActionPreference = 'SilentlyContinue'\n"
        f"Wait-Process -Id {int(pid)} -Timeout {EXIT_WAIT_SECONDS}\n"
        f"Start-Process -FilePath '{quoted}' -ArgumentList {args}\n"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return [
        "powershell.exe", "-NoProfile", "-NonInteractive",
        "-WindowStyle", "Hidden", "-EncodedCommand", encoded,
    ]
