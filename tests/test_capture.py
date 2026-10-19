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
