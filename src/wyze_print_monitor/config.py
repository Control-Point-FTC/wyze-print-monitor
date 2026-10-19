"""Persistent settings and secret storage.

Non-secret settings live in a small JSON file under the per-user config dir.
Secrets (Wyze password, API key id/secret) live in the OS credential store
via ``keyring`` and are never written to disk by this module.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

APP_NAME = "wyze-print-monitor"
KEYRING_SERVICE = "wyze-print-monitor"

# Secret names stored in the OS keyring under KEYRING_SERVICE.
SECRET_PASSWORD = "wyze_password"
SECRET_KEY_ID = "wyze_key_id"
SECRET_API_KEY = "wyze_api_key"
# The full RTSP URL (it embeds the camera username/password) is a secret too:
# settings.json only ever stores a redacted copy.
SECRET_RTSP_URL = "rtsp_url"


def redact_credentials_in_url(url: str) -> str:
    """Return *url* with any embedded userinfo replaced by ``***``.

    ``rtsp://user:pass@192.168.1.10/live`` becomes ``rtsp://***@192.168.1.10/live``.
    """
    if "@" not in url:
        return url
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        if not parts.username and not parts.password:
            return url
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit(parts._replace(netloc=f"***@{host}"))
    except Exception:
        return url


def effective_rtsp_url(settings: "Settings") -> str:
    """The real RTSP URL: keyring secret wins, settings file is the fallback."""
    return get_secret(SECRET_RTSP_URL) or settings.rtsp_url


def config_dir() -> str:
    """Per-user config directory for this app."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".config", APP_NAME)


def settings_path() -> str:
    return os.path.join(config_dir(), "settings.json")


def default_media_dirs() -> tuple[str, str]:
    """Default snapshot / video folders (Pictures/Videos under home)."""
    home = os.path.expanduser("~")
    return (
        os.path.join(home, "Pictures", APP_NAME),
        os.path.join(home, "Videos", APP_NAME),
    )


@dataclass
class Settings:
    rtsp_url: str = ""
    camera_mac: str = ""
    camera_nickname: str = ""
    wyze_email: str = ""
    timelapse_interval_sec: int = 10
    snapshot_dir: str = ""
    video_dir: str = ""
    always_on_top: bool = True

    def resolved_snapshot_dir(self) -> str:
        if self.snapshot_dir:
            return self.snapshot_dir
        return default_media_dirs()[0]

    def resolved_video_dir(self) -> str:
        if self.video_dir:
            return self.video_dir
        return default_media_dirs()[1]


def load_settings(path: str | None = None) -> Settings:
    """Load settings from JSON; unknown keys are ignored, missing file -> defaults."""
    path = path or settings_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    valid = {f.name for f in Settings.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return Settings(**{k: v for k, v in data.items() if k in valid})


def save_settings(settings: Settings, path: str | None = None) -> None:
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = asdict(settings)
    # Never persist camera credentials to disk: the settings file keeps only a
    # redacted copy, the real URL lives in the OS keyring (see SECRET_RTSP_URL).
    data["rtsp_url"] = redact_credentials_in_url(data.get("rtsp_url", ""))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def _keyring_exc():
    import keyring.errors

    return (keyring.errors.NoKeyringError, keyring.errors.InitError)


def save_secret(name: str, value: str) -> bool:
    """Best-effort: returns False on machines with no keyring backend, so
    callers can warn instead of silently losing the secret on restart."""
    import keyring

    try:
        keyring.set_password(KEYRING_SERVICE, name, value)
    except _keyring_exc():
        return False
    return True


def get_secret(name: str) -> str | None:
    import keyring

    try:
        return keyring.get_password(KEYRING_SERVICE, name)
    except _keyring_exc():
        return None


def delete_secret(name: str) -> None:
    import keyring

    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except Exception:
        pass
