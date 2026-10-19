"""Tests for capture helpers (Qt stubbed — no GUI needed)."""
import re
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _stub_qt(monkeypatch):
    """capture.py subclasses QThread at import time; stub just enough Qt
    to import the pure helpers without a GUI toolkit installed."""
    qtcore = types.ModuleType("PySide6.QtCore")

    class QThread:
        wait_result = True

        def __init__(self, *a, **k): ...

        def wait(self, *a, **k):
            return self.wait_result

    qtcore.QThread = QThread
    qtcore.Signal = lambda *a, **k: None
    pyside = types.ModuleType("PySide6")
    pyside.QtCore = qtcore
    monkeypatch.setitem(sys.modules, "PySide6", pyside)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", qtcore)


def test_snapshot_paths_are_unique(tmp_path):
    """Two snapshots taken in the same second must not share a path."""
    from wyze_print_monitor.capture import snapshot_path

    first = snapshot_path(str(tmp_path))
    second = snapshot_path(str(tmp_path))
    assert first != second
    assert re.search(r"\d{8}-\d{6}-\d{6}\.png$", first)


def test_stop_reports_a_thread_that_did_not_exit():
    """stop() must tell the caller when the reader is still blocked, so the
    owner never destroys a running QThread."""
    from wyze_print_monitor.capture import StreamReader

    reader = StreamReader("rtsp://example/live")
    reader.wait_result = False
    assert reader.stop(timeout_ms=1) is False
    assert reader._stop_requested is True

    reader.wait_result = True
    assert reader.stop() is True


def test_open_prefers_tcp_with_timeouts_and_falls_back(monkeypatch):
    """RTSP over TCP first (UDP drops frames on Wi-Fi), timeouts passed at
    open time, and FFmpeg's default transport if the camera refuses TCP."""
    import os

    from wyze_print_monitor import capture

    attempts = []

    class FakeCap:
        def __init__(self, url, backend, params):
            attempts.append((os.environ.get(capture.FFMPEG_OPTIONS_ENV), list(params)))
            self._ok = len(attempts) == 2  # TCP refused, default works

        def isOpened(self):
            return self._ok

        def release(self):
            pass

    monkeypatch.setattr(capture.cv2, "VideoCapture", FakeCap)
    monkeypatch.delenv(capture.FFMPEG_OPTIONS_ENV, raising=False)
    cap = capture.StreamReader("rtsps://cam/stream0")._open()

    assert cap.isOpened()
    assert [opts for opts, _ in attempts] == [capture.RTSP_OVER_TCP, None]
    params = attempts[0][1]
    assert params[params.index(capture.cv2.CAP_PROP_OPEN_TIMEOUT_MSEC) + 1] == capture.OPEN_TIMEOUT_MS
    assert params[params.index(capture.cv2.CAP_PROP_READ_TIMEOUT_MSEC) + 1] == capture.READ_TIMEOUT_MS
