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


def test_print_watch_switch_needs_the_model_first(window, monkeypatch):
    w, app = window
    from wyze_print_monitor import failure_model

    opened = []
    monkeypatch.setattr(w, "_open_settings", lambda tab="": opened.append(tab))
    monkeypatch.setattr(failure_model, "is_installed", lambda: False)
    w.camera_panel.watch_tile.click()
    app.processEvents()
    assert opened == ["watch"] and not w.settings.ai_watch
    assert not w.print_watch_action.isChecked()

    monkeypatch.setattr(failure_model, "is_installed", lambda: True)
    monkeypatch.setattr(w.print_watch, "apply_settings", lambda: None)
    w.print_watch_action.trigger()
    assert w.settings.ai_watch is True
    w.binder.sync()
    assert w.camera_panel.watch_tile.isChecked()
    w.camera_panel.watch_tile.click()  # and off again from the tile
    assert w.settings.ai_watch is False and not w.print_watch_action.isChecked()


def test_settings_sound_warning_follows_the_live_state(window):
    w, app = window
    from wyze_print_monitor.ui.settings_dialog import SettingsDialog

    w.print_watch._sound_status = "unavailable: the camera stream has no audio"
    d = SettingsDialog(w.settings, w.controller, w)
    assert not d.sound_note.isHidden() and "no audio" in d.sound_note.text()
    w.print_watch._sound_status = "listening"
    w.print_watch.status_changed.emit()
    assert d.sound_note.isHidden()
    d.reject()
    w.print_watch.status_changed.emit()  # disconnected: no error after close


def test_popup_alert_follows_the_setting_and_the_alert(window, monkeypatch):
    w, app = window
    watch = w.print_watch
    monkeypatch.setattr(watch.alarm, "play", lambda sound, urgent: None)
    w.settings.ai_popup = True
    watch.test_alert()
    app.processEvents()
    assert w.alert_popup.isVisible() and "Test alert" in w.alert_popup.bar.title.text()
    w.alert_popup.bar.fine_btn.click()  # "Dismiss" from the pop-up
    app.processEvents()
    assert watch.alert is None and not w.alert_popup.isVisible()
    w.settings.ai_popup = False
    watch.test_alert()
    app.processEvents()
    assert watch.alert is not None and not w.alert_popup.isVisible()
    watch.dismiss()


def test_settings_test_alert_can_be_stopped_and_popup_choice_saves(window, monkeypatch):
    w, app = window
    from wyze_print_monitor.ui.settings_dialog import SettingsDialog

    monkeypatch.setattr(w.print_watch.alarm, "play", lambda sound, urgent: None)
    d = SettingsDialog(w.settings, w.controller, w)
    d.test_alert_btn.click()
    assert w.print_watch.alert.severity == "test" and d.test_alert_btn.text() == "Stop test alert"
    d.test_alert_btn.click()
    assert w.print_watch.alert is None and d.test_alert_btn.text() == "Test alert"
    d.test_alert_btn.click()
    d.popup_check.setChecked(False)
    monkeypatch.setattr("wyze_print_monitor.ui.settings_dialog.save_secret", lambda *a: True)
    d._on_save()  # closing Settings also ends the test
    assert w.settings.ai_popup is False and w.print_watch.alert is None


def test_settings_has_a_check_for_updates_button(window, monkeypatch):
    w, app = window
    from wyze_print_monitor.ui.settings_dialog import SettingsDialog

    checks = []
    monkeypatch.setattr(w.update_manager, "check", lambda silent: checks.append(silent))
    d = SettingsDialog(w.settings, w.controller, w)
    d.check_now_btn.click()
    assert checks == [False]
    d.reject()
