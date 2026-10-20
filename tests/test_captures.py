"""Tests for the recent-captures scanner and thumbnails (no Qt)."""
import os

import cv2
import numpy as np

from wyze_print_monitor.captures import describe_age, recent_captures, thumbnail


def _touch_png(path, mtime, color=128):
    cv2.imwrite(str(path), np.full((90, 160, 3), color, np.uint8))
    os.utime(path, (mtime, mtime))


def test_recent_captures_merges_folders_newest_first(tmp_path):
    snaps, videos = tmp_path / "snaps", tmp_path / "videos"
    snaps.mkdir()
    videos.mkdir()
    _touch_png(snaps / "snapshot_1.png", 1000)
    _touch_png(snaps / "snapshot_2.png", 3000)
    (videos / "clip_1.mp4").write_bytes(b"x")
    os.utime(videos / "clip_1.mp4", (2000, 2000))
    (videos / "timelapse_1.mp4").write_bytes(b"x")
    os.utime(videos / "timelapse_1.mp4", (4000, 4000))
    (videos / "timelapse_1_frames").mkdir()  # frame folders are not captures
    (snaps / "notes.txt").write_text("ignored")

    found = recent_captures(str(snaps), str(videos))
    assert [os.path.basename(c.path) for c in found] == [
        "timelapse_1.mp4", "snapshot_2.png", "clip_1.mp4", "snapshot_1.png",
    ]
    assert [c.kind for c in found] == ["timelapse", "snapshot", "clip", "snapshot"]
    assert len(recent_captures(str(snaps), str(videos), limit=2)) == 2


def test_missing_folders_are_fine(tmp_path):
    assert recent_captures(str(tmp_path / "nope"), str(tmp_path / "also-nope")) == []


def test_same_folder_for_both_is_not_double_counted(tmp_path):
    _touch_png(tmp_path / "snapshot_1.png", 1000)
    assert len(recent_captures(str(tmp_path), str(tmp_path))) == 1


def test_thumbnail_of_image_and_video(tmp_path):
    png = tmp_path / "snapshot_1.png"
    _touch_png(png, 1000)
    thumb = thumbnail(str(png), width=80)
    assert thumb.shape[1] == 80 and thumb.shape[0] == 45

    mp4 = tmp_path / "clip_1.mp4"
    writer = cv2.VideoWriter(str(mp4), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 90))
    for _ in range(20):
        writer.write(np.full((90, 160, 3), 200, np.uint8))
    writer.release()
    assert thumbnail(str(mp4), width=80) is not None
    assert thumbnail(str(tmp_path / "missing.mp4")) is None


def test_describe_age():
    assert describe_age(5) == "just now"
    assert describe_age(5 * 60) == "5 min ago"
    assert describe_age(3 * 3600) == "3 h ago"
    assert describe_age(2 * 86400) == "2 d ago"
