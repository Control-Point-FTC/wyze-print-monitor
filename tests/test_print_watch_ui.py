"""The print watcher's rules: alert freely, pause only when sure, never stop
without asking. Studio is faked; needs PySide6 (skipped without it)."""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QObject, Signal  # noqa: E402

from wyze_print_monitor.config import Settings  # noqa: E402
from wyze_print_monitor.failure_detect import FAILURE, OK, WARNING  # noqa: E402
from wyze_print_monitor.print_watch import VisionResult  # noqa: E402
from wyze_print_monitor.ui import print_watch_ui as pw  # noqa: E402


class FakeMain(QObject):
    status_message = Signal(str)
    capture_saved = Signal(str)

    def __init__(self, tmp_path):
        super().__init__()
        self.settings = Settings(snapshot_dir=str(tmp_path), ai_watch=True)
        self._reader = None


@pytest.fixture
def watch(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(pw, "save_settings", lambda s: None)
    monkeypatch.setattr(pw, "_beep", lambda urgent: None)
    pressed = []
    controls = {"pause": 101, "stop": 102}
    monkeypatch.setattr(pw.studio_win32, "find_studio", lambda: 1)
    monkeypatch.setattr(pw.studio_win32, "find_print_controls", lambda top: dict(controls))
    monkeypatch.setattr(pw.studio_win32, "press", lambda hwnd: pressed.append(hwnd) or True)
    main = FakeMain(tmp_path)
    w = pw.PrintWatch(main)
    w._poll_studio()  # Studio shows a print running
    notes = []
    w.notify.connect(lambda title, msg: notes.append(title))
    yield w, main, pressed, controls, notes
    w.shutdown()
    app.processEvents()


def _result(level):
    return VisionResult(level, 0.9 if level == FAILURE else 0.5, [], np.zeros((90, 160, 3), np.uint8))


def test_warning_alerts_but_never_presses_anything(watch):
    w, _main, pressed, _c, notes = watch
    w._on_checked(_result(WARNING))
    assert w.alert.severity == "warning" and notes == ["Possible print problem"]
    assert os.path.exists(w.alert.snapshot)
    assert pressed == []


def test_sure_failure_pauses_through_studio(watch):
    w, _main, pressed, _c, notes = watch
    w._on_checked(_result(FAILURE))
    assert pressed == [101]  # Pause, and only Pause
    assert w.alert.severity == "paused"
    w._on_checked(_result(FAILURE))  # still failing: doesn't press again
    assert pressed == [101]


def test_auto_pause_off_only_alerts(watch):
    w, main, pressed, _c, _n = watch
    main.settings.ai_auto_pause = False
    w._on_checked(_result(FAILURE))
    assert pressed == [] and w.alert.severity == "failure"
    assert "auto-pause is off" in w.alert.message


def test_without_studio_failure_alerts_and_cannot_pause(watch, monkeypatch):
    w, _main, pressed, controls, _n = watch
    controls.clear()
    w._poll_studio()
    w._on_checked(_result(FAILURE))
    assert pressed == [] and w.alert.severity == "failure"


def test_stop_asks_first(watch, monkeypatch):
    w, _main, pressed, _c, _n = watch
    answers = iter([QtWidgets.QMessageBox.Cancel, QtWidgets.QMessageBox.Yes])
    monkeypatch.setattr(pw.QMessageBox, "warning", lambda *a, **k: next(answers))
    assert w.stop_print() is False and pressed == []
    assert w.stop_print() is True and pressed == [102]


def test_looks_fine_snoozes_warnings(watch):
    w, _main, _p, _c, notes = watch
    w._on_checked(_result(WARNING))
    w.looks_fine()
    assert w.alert is None
    w._last_warning = -1e9
    w._on_checked(_result(WARNING))
    assert w.alert is None and len(notes) == 1


def test_watching_idles_when_no_print_runs(watch):
    w, _main, _p, controls, _n = watch
    assert w._printing is True
    controls.clear()
    controls["stop"] = 102  # no pause/resume: not printing
    w._poll_studio()
    assert w._printing is False
