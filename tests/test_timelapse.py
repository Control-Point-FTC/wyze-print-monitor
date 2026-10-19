"""Tests for timelapse capture + compilation (no Qt needed)."""
import os

import cv2
import numpy as np
import pytest

from wyze_print_monitor.timelapse import TimelapseCollector, compile_timelapse


def _frame(color: int = 128) -> np.ndarray:
    return np.full((120, 160, 3), color, dtype=np.uint8)


def test_collector_respects_interval(tmp_path):
    collector = TimelapseCollector(str(tmp_path), interval_sec=10)
    collector.start()
    assert collector.maybe_capture(_frame(), now=1000.0) is True  # first frame immediate
    assert collector.maybe_capture(_frame(), now=1005.0) is False  # too soon
    assert collector.maybe_capture(_frame(), now=1010.0) is True  # due
    assert collector.saved == 2
    assert len(collector.frame_paths()) == 2


def test_compile_produces_video(tmp_path):
    frames_dir = str(tmp_path / "frames")
    collector = TimelapseCollector(frames_dir, interval_sec=5)
    collector.start()
    for i in range(5):
        assert collector.maybe_capture(_frame(color=i * 40), now=1000.0 + i * 5)

    output = str(tmp_path / "out" / "timelapse.mp4")
    written = compile_timelapse(frames_dir, output, fps=30)
    assert written == 5
    assert os.path.isfile(output)
    assert os.path.getsize(output) > 0

    # The compiled video actually contains the frames.
    cap = cv2.VideoCapture(output)
    count = 0
    while True:
        ok, _ = cap.read()
        if not ok:
            break
        count += 1
    cap.release()
    assert count == 5


def test_compile_empty_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        compile_timelapse(str(tmp_path / "empty"), str(tmp_path / "out.mp4"))


def test_collector_creates_dir_on_start(tmp_path):
    frames_dir = str(tmp_path / "new-dir")
    TimelapseCollector(frames_dir).start()
    assert os.path.isdir(frames_dir)


def test_collector_write_failure_not_counted(tmp_path, monkeypatch):
    """A failed cv2.imwrite must not count as a saved frame: the next
    success reuses the slot so the video has no silent gaps."""
    collector = TimelapseCollector(str(tmp_path), interval_sec=10)
    collector.start()
    monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: False)
    assert collector.maybe_capture(_frame(), now=1000.0) is False
    assert collector.saved == 0
    assert collector.write_errors == 1
    # Next success reuses frame_000000.jpg (no gap in numbering).
    monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: True)
    assert collector.maybe_capture(_frame(), now=1010.0) is True
    assert collector.saved == 1
    assert collector.write_errors == 1
