"""Tests for the GitHub-release update checker (no network)."""
import hashlib
import io
import json
import urllib.error

import pytest

from wyze_print_monitor import updater
from wyze_print_monitor.updater import (
    ReleaseInfo,
    UpdateError,
    download_installer,
    fetch_latest,
    is_newer,
    parse_version,
    release_from_json,
)

INSTALLER = b"MZ fake installer bytes" * 100


def _release_json(tag="v1.2.0", **extra):
    data = {
        "tag_name": tag,
        "html_url": f"https://github.com/x/y/releases/tag/{tag}",
        "body": "Notes",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "checksums.txt", "browser_download_url": "https://x/checksums.txt", "size": 10},
            {
                "name": f"WyzePrintMonitor-{tag.lstrip('v')}-setup.exe",
                "browser_download_url": "https://x/setup.exe",
                "size": len(INSTALLER),
                "digest": "sha256:" + hashlib.sha256(INSTALLER).hexdigest(),
            },
        ],
    }
    data.update(extra)
    return data


class _Response(io.BytesIO):
    def __init__(self, payload: bytes):
        super().__init__(payload)
        self.headers = {"Content-Length": str(len(payload))}


def _opener(payload: bytes):
    return lambda url, timeout, accept: _Response(payload)


def test_parse_version():
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("1.2") == (1, 2)
    assert parse_version("1.2.3-beta.1") == (1, 2, 3)
    assert parse_version("nightly") == ()


def test_is_newer():
    assert is_newer("1.0.1", "1.0.0")
    assert is_newer("v2.0", "1.9.9")
    assert is_newer("1.10.0", "1.9.0")  # numeric, not string, comparison
    assert not is_newer("1.0", "1.0.0")
    assert not is_newer("0.9.0", "1.0.0")
    assert not is_newer("garbage", "1.0.0")


def test_release_from_json_picks_the_installer():
    info = release_from_json(_release_json())
    assert info.version == "1.2.0"
    assert info.installer_name == "WyzePrintMonitor-1.2.0-setup.exe"
    assert info.installer_size == len(INSTALLER)
    assert info.installer_sha256 == hashlib.sha256(INSTALLER).hexdigest()


def test_release_from_json_skips_drafts_and_prereleases():
    assert release_from_json(_release_json(draft=True)) is None
    assert release_from_json(_release_json(prerelease=True)) is None
    assert release_from_json({"tag_name": "latest"}) is None


def test_fetch_latest_parses_and_handles_no_releases():
    info = fetch_latest(opener=_opener(json.dumps(_release_json("v3.0.0")).encode()))
    assert info.version == "3.0.0"

    def not_found(url, timeout, accept):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    assert fetch_latest(opener=not_found) is None

    def offline(url, timeout, accept):
        raise urllib.error.URLError("no network")

    with pytest.raises(UpdateError):
        fetch_latest(opener=offline)


def test_download_verifies_and_reports_progress(tmp_path):
    info = release_from_json(_release_json())
    seen = []
    path = download_installer(info, str(tmp_path), progress=lambda r, t: seen.append((r, t)), opener=_opener(INSTALLER))
    assert open(path, "rb").read() == INSTALLER
    assert seen[-1] == (len(INSTALLER), len(INSTALLER))


def test_download_rejects_tampered_file(tmp_path):
    info = release_from_json(_release_json())
    tampered = b"X" * len(INSTALLER)
    with pytest.raises(UpdateError):
        download_installer(info, str(tmp_path), opener=_opener(tampered))
    assert list(tmp_path.iterdir()) == []  # nothing left behind


def test_download_can_be_cancelled(tmp_path):
    info = release_from_json(_release_json())
    with pytest.raises(UpdateError):
        download_installer(info, str(tmp_path), cancelled=lambda: True, opener=_opener(INSTALLER))
    assert list(tmp_path.iterdir()) == []


def test_release_without_installer_cannot_download(tmp_path):
    info = ReleaseInfo(version="9.9.9", page_url=updater.RELEASES_PAGE)
    with pytest.raises(UpdateError):
        download_installer(info, str(tmp_path))
