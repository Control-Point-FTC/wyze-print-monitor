"""The print watcher's rules, against a fake Studio. Needs PySide6.

Alert freely; pause only when sure, only the camera's printer, and only
count it once Studio confirms; never stop without asking.
"""
import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QObject, Signal  # noqa: E402

from wyze_print_monitor.config import Settings  # noqa: E402
from wyze_print_monitor.failure_detect import FAILURE, WARNING  # noqa: E402
from wyze_print_monitor.print_watch import VisionResult  # noqa: E402
from wyze_print_monitor.ui import print_watch_ui as pw  # noqa: E402

PAUSE, STOP, RESUME = 101, 102, 103
PRINTING = {"pause": PAUSE, "stop": STOP}
PAUSED = {"resume": RESUME, "stop": STOP}


class FakeMain(QObject):
    status_message = Signal(str)
    capture_saved = Signal(str)

    def __init__(self, tmp_path):
        super().__init__()
        self.settings = Settings(snapshot_dir=str(tmp_path), ai_watch=True)
        self._reader = None


class FakeStudio:
    """What the observer sees; obeys Pause clicks unless told not to."""

    def __init__(self):
        self.running, self.ours, self.controls = True, True, dict(PRINTING)
        self.obeys = True
        self.pressed = []

    def view(self, _row):
        return pw.StudioView(self.running, self.running and self.ours, dict(self.controls) if self.ours else {})

    def press(self, hwnd):
        self.pressed.append(hwnd)
        if self.obeys and hwnd == PAUSE:
            self.controls = dict(PAUSED)
        elif self.obeys and hwnd == RESUME:
            self.controls = dict(PRINTING)
        return True


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def env(tmp_path, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = FakeStudio()
    clock = Clock()
    monkeypatch.setattr(pw, "save_settings", lambda s: None)
    monkeypatch.setattr(pw, "_beep", lambda urgent: None)
    monkeypatch.setattr(pw.StudioObserver, "observe", lambda self, row: studio.view(row))
    monkeypatch.setattr(pw.studio_win32, "press", studio.press)
    monkeypatch.setattr(pw.time, "monotonic", clock)
    main = FakeMain(tmp_path)
    w = pw.PrintWatch(main)
    notes = []
    w.notify.connect(lambda title, msg: notes.append(title))
    w._poll_studio()  # Studio shows the camera printer printing
    yield w, main, studio, clock, notes
    w.shutdown()
    app.processEvents()


def _result(level):
    return VisionResult(level, 0.9 if level == FAILURE else 0.5, [], np.zeros((90, 160, 3), np.uint8))


def test_warning_alerts_but_never_presses_anything(env):
    w, _main, studio, _clock, notes = env
    w._on_checked(_result(WARNING))
    assert w.alert.severity == "warning" and notes == ["Possible print problem"]
    assert os.path.exists(w.alert.snapshot)
    assert studio.pressed == []


def test_sure_failure_pauses_and_waits_for_studio_to_confirm(env):
    w, _main, studio, _clock, _n = env
    studio.obeys = False  # Studio hasn't reacted yet
    w._on_checked(_result(FAILURE))
    assert studio.pressed == [PAUSE]
    assert w.alert.severity == "pausing" and w.pausing()
    assert "pausing" in w.status_text()
    studio.controls = dict(PAUSED)  # now Studio shows Resume
    w._poll_studio()
    assert w.alert.severity == "paused" and not w.pausing()
    assert w.alert.can_resume and w.alert.can_stop
    w._on_checked(_result(FAILURE))  # still failing: nothing more to do
    assert studio.pressed == [PAUSE]


def test_pause_is_retried_once_then_reported_if_studio_ignores_it(env):
    w, _main, studio, clock, notes = env
    studio.obeys = False
    w._on_checked(_result(FAILURE))
    clock.now += pw.PAUSE_RETRY_S
    w._poll_studio()
    assert studio.pressed == [PAUSE, PAUSE]
    clock.now += pw.PAUSE_RETRY_S
    w._poll_studio()
    assert studio.pressed == [PAUSE, PAUSE]  # only one retry
    clock.now += pw.PAUSE_GIVE_UP_S
    w._poll_studio()
    assert w.alert.severity == "pause_failed" and not w.pausing()
    assert notes[-1].startswith("Couldn't pause")
    assert w.alert.can_pause  # the user can still try
    w._on_checked(_result(FAILURE))
    assert studio.pressed == [PAUSE, PAUSE]  # no silent loop of presses


def test_never_presses_another_printers_pause(env):
    w, _main, studio, _clock, _n = env
    studio.ours = False  # the user selected another (running) printer in Studio
    w._on_checked(_result(FAILURE))
    assert studio.pressed == []
    assert w.alert.severity == "failure" and "isn't showing" in w.alert.message
    assert not w.alert.can_pause and not w.alert.can_stop


def test_user_buttons_are_also_verified(env):
    w, _main, studio, _clock, _n = env
    studio.ours = False
    assert w.pause_print() is False and w.resume_print() is False and w.stop_print() is False
    assert studio.pressed == []


def test_switching_studio_tabs_doesnt_end_the_print(env):
    w, _main, studio, _clock, _n = env
    for _ in range(40):
        w._scorer.update([])
    w._on_checked(_result(WARNING))
    studio.ours = False  # Studio on its Slice tab (or another printer)
    w._poll_studio()
    studio.ours = True
    w._poll_studio()
    assert w._printing is True
    assert w._scorer.frames == 40  # same print, history kept
    assert w.alert is not None and w.alert.severity == "warning"


def test_print_end_clears_alerts_and_a_new_print_starts_fresh(env):
    w, _main, studio, _clock, notes = env
    w._on_checked(_result(WARNING))
    studio.controls = {}  # print finished
    w._poll_studio()
    assert w._printing is False and w.alert is None
    studio.controls = dict(PRINTING)  # next print, within 15 minutes
    w._poll_studio()
    w._on_checked(_result(WARNING))
    assert notes.count("Possible print problem") == 2  # no leftover cooldown


def test_looks_fine_quiets_failures_too(env):
    w, _main, studio, clock, notes = env
    w._on_checked(_result(WARNING))
    w.looks_fine()
    clock.now += 60
    w._on_checked(_result(FAILURE))
    assert w.alert is None and studio.pressed == [] and len(notes) == 1
    clock.now += pw.LOOKS_FINE_SNOOZE_S
    w._on_checked(_result(FAILURE))
    assert studio.pressed == [PAUSE]


def test_auto_pause_off_only_alerts(env):
    w, main, studio, _clock, _n = env
    main.settings.ai_auto_pause = False
    w._on_checked(_result(FAILURE))
    assert studio.pressed == [] and w.alert.severity == "failure"
    assert "auto-pause is off" in w.alert.message


def test_without_studio_failure_alerts_and_explains(env):
    w, _main, studio, _clock, _n = env
    studio.running = False
    w._poll_studio()
    w._on_checked(_result(FAILURE))
    assert studio.pressed == [] and w.alert.severity == "failure"
    assert "Device tab" in w.alert.message


def test_resume_clears_the_pause_and_watches_afresh(env):
    w, _main, studio, _clock, _n = env
    w._on_checked(_result(FAILURE))
    w._poll_studio()
    assert w.alert.severity == "paused"
    assert w.resume_print() is True and studio.pressed == [PAUSE, RESUME]
    w._poll_studio()
    assert w.alert is None and not w._print_paused and not w._paused_by_us


def test_stop_asks_first_and_rechecks(env, monkeypatch):
    w, _main, studio, _clock, _n = env
    answers = iter([QtWidgets.QMessageBox.Cancel, QtWidgets.QMessageBox.Yes, QtWidgets.QMessageBox.Yes])
    monkeypatch.setattr(pw.QMessageBox, "warning", lambda *a, **k: next(answers))
    assert w.stop_print() is False and studio.pressed == []
    assert w.stop_print() is True and studio.pressed == [STOP]

    def switch_printer_while_asking(*_a, **_k):
        studio.ours = False
        return QtWidgets.QMessageBox.Yes

    monkeypatch.setattr(pw.QMessageBox, "warning", switch_printer_while_asking)
    assert w.stop_print() is False and studio.pressed == [STOP]


def test_sound_reset_is_handed_to_the_worker(env):
    w, _main, studio, _clock, _n = env

    class FakeSound:
        reset_requested = False
        paused = False

    w._sound = FakeSound()
    studio.controls = {}
    w._poll_studio()
    studio.controls = dict(PRINTING)
    w._poll_studio()  # a new print
    assert w._sound.reset_requested is True
    w._sound = None
