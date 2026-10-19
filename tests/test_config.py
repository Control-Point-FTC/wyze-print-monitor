"""Tests for settings persistence (no Qt, no keyring needed)."""
import json
import os

from wyze_print_monitor.config import (
    Settings,
    load_settings,
    redact_credentials_in_url,
    save_settings,
)


def test_round_trip(tmp_path):
    path = str(tmp_path / "settings.json")
    original = Settings(
        rtsp_url="rtsp://user:pass@192.168.1.10/live",
        camera_mac="AABBCCDDEEFF",
        camera_nickname="Printer Cam",
        wyze_email="sushil@example.com",
        timelapse_interval_sec=15,
        snapshot_dir=str(tmp_path / "snaps"),
        video_dir=str(tmp_path / "vids"),
        always_on_top=False,
    )
    save_settings(original, path)
    loaded = load_settings(path)
    # The RTSP URL is redacted on save (credentials live in the keyring).
    assert loaded.rtsp_url == "rtsp://***@192.168.1.10/live"
    original.rtsp_url = loaded.rtsp_url
    assert loaded == original


def test_missing_file_gives_defaults(tmp_path):
    loaded = load_settings(str(tmp_path / "does-not-exist.json"))
    assert loaded == Settings()


def test_unknown_keys_are_ignored(tmp_path):
    path = str(tmp_path / "settings.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"rtsp_url": "rtsp://x", "bogus_key": 123}, fh)
    loaded = load_settings(path)
    assert loaded.rtsp_url == "rtsp://x"


def test_corrupt_file_gives_defaults(tmp_path):
    path = str(tmp_path / "settings.json")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not valid json")
    assert load_settings(path) == Settings()


def test_resolved_dirs_fall_back_to_defaults():
    settings = Settings()
    snaps, vids = settings.resolved_snapshot_dir(), settings.resolved_video_dir()
    assert snaps.endswith(os.path.join("Pictures", "wyze-print-monitor"))
    assert vids.endswith(os.path.join("Videos", "wyze-print-monitor"))


def test_resolved_dirs_honor_overrides(tmp_path):
    settings = Settings(snapshot_dir="/tmp/a", video_dir="/tmp/b")
    assert settings.resolved_snapshot_dir() == "/tmp/a"
    assert settings.resolved_video_dir() == "/tmp/b"


def test_redact_credentials_in_url():
    assert (
        redact_credentials_in_url("rtsp://user:s3cret@192.168.1.10/live")
        == "rtsp://***@192.168.1.10/live"
    )
    assert (
        redact_credentials_in_url("rtsp://192.168.1.10/live")
        == "rtsp://192.168.1.10/live"
    )
    assert redact_credentials_in_url("") == ""


def test_save_redacts_rtsp_credentials(tmp_path):
    """Camera credentials must never land in the settings JSON on disk."""
    path = str(tmp_path / "settings.json")
    save_settings(
        Settings(rtsp_url="rtsp://user:s3cret@192.168.1.10/live"), path
    )
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["rtsp_url"] == "rtsp://***@192.168.1.10/live"
    assert "s3cret" not in json.dumps(data)


def test_secrets_fail_soft_without_keyring_backend(monkeypatch):
    """On machines with no keyring backend (e.g. headless Linux) the secret
    helpers must not raise — secrets simply don't persist there."""
    import sys
    import types

    import wyze_print_monitor.config as config

    class NoKeyringError(Exception):
        pass

    fake_errors = types.SimpleNamespace(NoKeyringError=NoKeyringError, InitError=NoKeyringError)
    fake_keyring = types.SimpleNamespace(
        errors=fake_errors,
        get_password=lambda *a, **k: (_ for _ in ()).throw(NoKeyringError("no backend")),
        set_password=lambda *a, **k: (_ for _ in ()).throw(NoKeyringError("no backend")),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)
    monkeypatch.setitem(sys.modules, "keyring.errors", fake_errors)

    assert config.get_secret("anything") is None
    assert config.save_secret("anything", "value") is False  # reports failure
