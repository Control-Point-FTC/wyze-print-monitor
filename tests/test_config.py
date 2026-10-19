"""Tests for settings persistence (no Qt, no keyring needed)."""
import json
import os

from wyze_print_monitor.config import Settings, load_settings, save_settings


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
