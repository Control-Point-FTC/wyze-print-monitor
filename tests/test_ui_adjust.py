"""UI tests: the picture controls open in the camera panel, beside the video.

These drive the real MainWindow headless (Qt "offscreen" platform), so they
need PySide6 and are skipped where it isn't installed.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def window(tmp_path, monkeypatch):
    # Keep settings out of the real profile.
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from wyze_print_monitor.ui.main_window import MainWindow

    w = MainWindow()
    w.resize(1200, 700)
    w.show()
    app.processEvents()
    yield w, app
    w.hide_on_close = False
    w._shutdown()
    w.close()
    w.deleteLater()
    app.processEvents()


def _state(w):
    """(adjust page open, Adjust button lit, camera column visible)"""
    return w.camera_panel.adjusting(), w.view.adjust_btn.isChecked(), w._side_card.isVisible()


def test_adjust_button_opens_and_closes_the_picture_controls(window):
    w, app = window
    assert _state(w) == (False, False, True)
    w.view.adjust_btn.click()
    app.processEvents()
    assert _state(w) == (True, True, True)
    w.view.adjust_btn.click()  # Adjust again closes it
    app.processEvents()
    assert _state(w) == (False, False, True)


def test_all_adjustments_link_and_done_button(window):
    w, app = window
    w.camera_panel.more_picture_btn.click()
    app.processEvents()
    assert _state(w) == (True, True, True)
    w.camera_panel.adjust_done_btn.click()
    app.processEvents()
    assert _state(w) == (False, False, True)


def test_fullscreen_shows_the_column_only_while_adjusting(window):
    w, app = window
    w.showFullScreen()
    app.processEvents()
    assert w.isFullScreen()
    assert _state(w) == (False, False, False)  # fullscreen: just the picture

    w.view.adjust_btn.click()  # adjusting in fullscreen brings the column in
    app.processEvents()
    assert _state(w) == (True, True, True)

    w.camera_panel.adjust_done_btn.click()  # ...and tucks it away after
    app.processEvents()
    assert _state(w) == (False, False, False)


def test_entering_fullscreen_with_adjustments_open_keeps_them_reachable(window):
    w, app = window
    w.view.adjust_btn.click()
    app.processEvents()
    w.showFullScreen()
    app.processEvents()
    assert _state(w) == (True, True, True)
    w.showNormal()
    app.processEvents()
    assert _state(w) == (True, True, True)
    w.view.adjust_btn.click()
    app.processEvents()
    assert _state(w) == (False, False, True)
