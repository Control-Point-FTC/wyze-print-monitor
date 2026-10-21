"""Connect a VideoView + CameraPanel pair to the MainWindow.

MainWindow owns all behavior: its control widgets (buttons, toggles, labels)
carry the handlers, confirmations, error rollbacks and Wyze state. Every
visible surface — the full window and the panels docked inside eufyMake
Studio — is bound to those controls by a ``PanelBinder``: a click on a view
clicks the matching control, and a short timer copies the controls' state
back into the view. One code path, however many surfaces.
"""
from __future__ import annotations

import os
import time
from dataclasses import replace

from PySide6.QtCore import QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QAbstractButton, QMenu

from ..adjust import LIMITS, screen_to_source_delta
from .adjust_panel import ImageAdjustPanel
from ..quality import LABELS as QUALITY_LABELS
from ..quality import QUALITIES
from ..wyze_control import friendly_model
from .views import CHIP_STYLES, CameraPanel, ToggleTile, VideoView, set_chip

SYNC_MS = 200
CAPTURES_EVERY_S = 20.0
HOLD_LAST_FRAME_S = 5.0  # keep the last picture through a reconnect this short


def _forward(view_button: QAbstractButton, control: QAbstractButton) -> None:
    """Clicking the view's button clicks the MainWindow control (same handlers,
    same confirmations); the view then mirrors whatever state results."""

    def forward() -> None:
        if view_button.isCheckable() and not isinstance(view_button, ToggleTile):
            # Undo the view's own toggle: the next sync copies the control's
            # real state, which a failed command may roll back.
            view_button.blockSignals(True)
            view_button.setChecked(not view_button.isChecked())
            view_button.blockSignals(False)
        control.click()

    view_button.clicked.connect(forward)


def _mirror(view_button: QAbstractButton, control: QAbstractButton) -> None:
    if view_button.isEnabled() != control.isEnabled():
        view_button.setEnabled(control.isEnabled())
    if view_button.isCheckable() and view_button.isChecked() != control.isChecked():
        view_button.blockSignals(True)
        view_button.setChecked(control.isChecked())
        view_button.blockSignals(False)


def _show_fill(view: VideoView, fill: bool) -> None:
    """Apply Fit/Fill to a view and its button, without re-triggering it."""
    view.set_fill(fill)
    if view.fit_btn.isChecked() != fill:
        view.fit_btn.blockSignals(True)
        view.fit_btn.setChecked(fill)
        view.fit_btn.blockSignals(False)


def _toggle_state(control: QAbstractButton) -> str:
    """'On' / 'Off' / 'Unknown' / '…' from a MainWindow toggle's label."""
    text = control.text()
    if ": " in text:
        state = text.split(": ", 1)[1].strip()
        return {"on": "On", "off": "Off", "unknown": "Unknown"}.get(state.lower(), state)
    return "On" if control.isChecked() else "Off"


def view_alert_snapshot(main) -> None:
    alert = main.print_watch.alert
    if alert is not None and alert.snapshot and os.path.exists(alert.snapshot):
        QDesktopServices.openUrl(QUrl.fromLocalFile(alert.snapshot))


def wire_alert_bar(bar, main) -> None:
    """Connect an AlertBar's buttons (video banner or pop-up) to Print watch."""
    watch = main.print_watch
    bar.fine_btn.clicked.connect(
        lambda: watch.looks_fine()
        if watch.alert and watch.alert.severity in ("warning", "failure", "sound")
        else watch.dismiss()
    )
    bar.pause_btn.clicked.connect(
        lambda: watch.pause_print()
        or main.status_message.emit("Couldn't pause: Studio isn't showing this printer's Pause button.")
    )
    bar.resume_btn.clicked.connect(watch.resume_print)
    bar.silence_btn.clicked.connect(watch.silence)
    bar.stop_btn.clicked.connect(lambda: watch.stop_print(bar.window()))
    bar.view_btn.clicked.connect(lambda: view_alert_snapshot(main))


class PanelBinder(QObject):
    def __init__(self, main, video: VideoView, camera: CameraPanel, parent: QObject | None = None) -> None:
        super().__init__(parent or main)
        self.main = main
        self.video = video
        self.camera = camera
        self._not_live_since: float | None = None
        self._last_captures = 0.0
        self._wire()
        main.video_views.append(video)
        main.status_message.connect(self._on_status)
        main.adjustments_changed.connect(self._on_adjustments)
        main.capture_saved.connect(self._on_capture_saved)
        main.print_watch.alert_changed.connect(self.video.show_alert)
        self.video.show_alert(main.print_watch.alert)
        self._on_adjustments(main.adjustments)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.sync)
        self._timer.start(SYNC_MS)
        self.sync()

    def close(self) -> None:
        """Stop updating (the views are about to be destroyed)."""
        self._timer.stop()
        if self.video in self.main.video_views:
            self.main.video_views.remove(self.video)
        for signal, slot in (
            (self.main.status_message, self._on_status),
            (self.main.adjustments_changed, self._on_adjustments),
            (self.main.capture_saved, self._on_capture_saved),
            (self.main.print_watch.alert_changed, self.video.show_alert),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self.camera.captures.shutdown()

    # ------------------------------------------------------------------ wiring
    def _wire(self) -> None:
        m, v, c = self.main, self.video, self.camera
        _forward(v.snapshot_btn, m.snapshot_btn)
        _forward(v.record_btn, m.record_btn)
        _forward(v.timelapse_btn, m.timelapse_btn)
        v.fullscreen_btn.clicked.connect(m._toggle_fullscreen)
        v.fullscreen_requested.connect(m._toggle_fullscreen)
        v.window_btn.clicked.connect(m.show_window)
        v.settings_btn.clicked.connect(m._open_settings)
        v.update_btn.clicked.connect(m.update_manager.install)
        # Adjusting opens in the camera panel beside the video, not over it.
        c.set_adjust_widget(ImageAdjustPanel(m))
        v.adjust_btn.setCheckable(True)
        v.adjust_btn.clicked.connect(self._toggle_adjust)
        c.pages.currentChanged.connect(lambda _index: self._sync_adjust_state())
        v.fit_btn.toggled.connect(self._on_fit_toggled)
        v.zoom_by.connect(self._zoom_by)
        v.pan_by.connect(self._pan_by)
        v.zoom_chip.clicked.connect(lambda: m.set_adjustments(replace(m.adjustments, zoom=1.0, pan_x=0.0, pan_y=0.0)))
        quality_menu = QMenu(v.quality_btn)
        self._quality_actions = {}
        for key in QUALITIES:
            action = quality_menu.addAction(QUALITY_LABELS[key])
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, k=key: m.set_stream_quality(k))
            self._quality_actions[key] = action
        v.quality_btn.setMenu(quality_menu)
        folders = QMenu(v.folder_btn)
        folders.addAction("Open snapshot folder", lambda: m._open_folder(m.settings.resolved_snapshot_dir()))
        folders.addAction("Open video folder", lambda: m._open_folder(m.settings.resolved_video_dir()))
        v.folder_btn.setMenu(folders)
        _show_fill(v, bool(m.settings.video_fill))
        wire_alert_bar(v.alert, m)

        c.settings_btn.clicked.connect(m._open_settings)
        c.more_picture_btn.clicked.connect(self._open_adjust)
        c.open_folder_btn.clicked.connect(lambda: m._open_folder(m.settings.resolved_snapshot_dir()))
        for view_button, control in (
            (c.siren_tile, m.siren_btn),
            (c.spotlight_tile, m.spotlight_btn),
            (c.motion_tile, m.motion_check),
            (c.notify_tile, m.notify_check),
            (c.power_on_btn, m.power_on_btn),
            (c.power_off_btn, m.power_off_btn),
            (c.restart_btn, m.restart_btn),
            (c.connect_btn, m.connect_btn),
            (c.refresh_btn, m.refresh_btn),
        ):
            _forward(view_button, control)
        c.camera_combo.activated.connect(m.camera_list.setCurrentRow)
        c.watch_tile.clicked.connect(lambda: m.set_print_watch_enabled(not m.settings.ai_watch))
        for name, (slider, _value) in c.quick_sliders.items():
            slider.valueChanged.connect(lambda value, n=name: self._on_quick_slider(n, value))

    def _toggle_adjust(self) -> None:
        if self.camera.adjusting():
            self.camera.show_controls()
        else:
            self._open_adjust()

    def _open_adjust(self) -> None:
        self.camera.show_adjust()
        self._sync_adjust_state()

    def _sync_adjust_state(self) -> None:
        adjusting = self.camera.adjusting()
        if self.video.adjust_btn.isChecked() != adjusting:
            self.video.adjust_btn.setChecked(adjusting)
        # In fullscreen the camera column is hidden; bring it in while
        # adjusting so the controls are reachable, and tuck it away after.
        main = self.main
        if self.video.window() is main and main.isFullScreen():
            main.set_side_panel_visible(adjusting)

    def _on_fit_toggled(self, fill: bool) -> None:
        self.main.settings.video_fill = fill
        self.main.save_settings_soon()
        for view in self.main.video_views:
            _show_fill(view, fill)

    def _zoom_by(self, factor: float) -> None:
        adj = self.main.adjustments
        lo, hi = LIMITS["zoom"]
        zoom = min(max(adj.zoom * factor, lo), hi)
        if abs(zoom - adj.zoom) < 1e-3:
            return
        if zoom <= lo + 1e-3:
            self.main.set_adjustments(replace(adj, zoom=lo, pan_x=0.0, pan_y=0.0))
        else:
            self.main.set_adjustments(replace(adj, zoom=round(zoom, 2)))

    def _pan_by(self, dx: float, dy: float) -> None:
        adj = self.main.adjustments
        # Pan is applied before rotate/flip: map the on-screen drag back.
        dx, dy = screen_to_source_delta(dx, dy, adj.rotation, adj.flip_h, adj.flip_v)
        lo, hi = LIMITS["pan_x"]
        self.main.set_adjustments(
            replace(
                adj,
                pan_x=round(min(max(adj.pan_x + dx, lo), hi), 3),
                pan_y=round(min(max(adj.pan_y + dy, lo), hi), 3),
            )
        )

    _QUICK_SCALE = {"brightness": 1, "exposure": 10, "zoom": 100}
    _QUICK_FORMAT = {"brightness": "{:+.0f}", "exposure": "{:+.1f} EV", "zoom": "{:.1f}×"}

    def _on_quick_slider(self, name: str, raw: int) -> None:
        value = raw / self._QUICK_SCALE[name]
        if name == "brightness":
            value = int(value)
        changes = {name: value}
        if name == "zoom" and value <= 1.0:
            changes.update(pan_x=0.0, pan_y=0.0)
        self.main.set_adjustments(replace(self.main.adjustments, **changes))

    def _on_adjustments(self, adj) -> None:
        for name, (slider, label) in self.camera.quick_sliders.items():
            number = getattr(adj, name)
            slider.blockSignals(True)
            slider.setValue(round(number * self._QUICK_SCALE[name]))
            slider.blockSignals(False)
            label.setText(self._QUICK_FORMAT[name].format(number))
        self.video.set_zoom(adj.zoom)

    def _on_status(self, message: str, timeout: int) -> None:
        if message and message != "Ready":  # startup noise, not news
            self.video.show_toast(message, timeout)

    def _on_capture_saved(self, _path: str) -> None:
        self._refresh_captures(force=True)

    def _refresh_captures(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_captures < CAPTURES_EVERY_S:
            self.camera.captures.refresh_ages()
            return
        self._last_captures = now
        s = self.main.settings
        # Scanned on the grid's worker thread: big or slow folders must not
        # stall the video.
        self.camera.captures.request_scan(s.resolved_snapshot_dir(), s.resolved_video_dir())

    # ------------------------------------------------------------------ sync
    def sync(self) -> None:
        if not (self.video.isVisible() or self.camera.isVisible()):
            return
        self._sync_video()
        self._sync_camera()
        self._refresh_captures()

    def _sync_video(self) -> None:
        m, v = self.main, self.video
        state = getattr(m, "_stream_state", "idle")
        text, bg, fg = CHIP_STYLES.get(state, CHIP_STYLES["idle"])
        set_chip(v.state_chip, text, bg, fg)
        info = m.stream_info_label.text() if state == "live" else ""
        if v.info.text() != info:
            v.info.setText(info)
        if m._recorder is not None and m._rec_start is not None:
            elapsed = int(time.monotonic() - m._rec_start)
            set_chip(v.rec_chip, f"● REC {elapsed // 60:02d}:{elapsed % 60:02d}", "#a33a3a")
        else:
            set_chip(v.rec_chip, "")
        if m._timelapse is not None:
            set_chip(v.timelapse_chip, f"Timelapse · {m._timelapse.saved} frames", "#3a4f7a")
        elif m._compile_worker is not None:
            set_chip(v.timelapse_chip, "Compiling timelapse…", "#3a4f7a")
        else:
            set_chip(v.timelapse_chip, "")
        silence = m.print_watch.alarm.playing and not v.alert.isHidden()
        if v.alert.silence_btn.isVisible() != silence:
            v.alert.silence_btn.setVisible(silence)
        watch_text = m.print_watch.status_text()
        if watch_text:
            word = watch_text.split(": ", 1)[-1]
            risky = m.print_watch.risk >= 1 / 3 and word not in ("model not downloaded",)
            set_chip(v.watch_chip, f"AI · {word}", "#7a3a2f" if risky else "#2f4a5a")
            v.watch_chip.setToolTip(watch_text)
        else:
            set_chip(v.watch_chip, "")
        v.set_live(state == "live")
        _show_fill(v, bool(m.settings.video_fill))

        # Hold the last frame through a short reconnect; afterwards explain.
        if state == "live":
            self._not_live_since = None
        elif self._not_live_since is None:
            self._not_live_since = time.monotonic()
        holding = (
            self._not_live_since is not None
            and time.monotonic() - self._not_live_since < HOLD_LAST_FRAME_S
            and v.has_image()
        )
        if state != "live" and not holding:
            if not m.settings.rtsp_url:
                v.show_placeholder("No camera stream yet.\nAdd your RTSP URL in Settings (gear icon).")
            elif state in ("connecting", "reconnecting"):
                v.show_placeholder("Connecting to the camera…")
            else:
                v.show_placeholder("Camera stream unavailable.\nIf the Wyze app shows it offline, unplug it for 10 seconds.")

        chosen = m.settings.stream_quality
        for key, action in self._quality_actions.items():
            if action.isChecked() != (key == chosen):
                action.setChecked(key == chosen)
        shown = m.active_quality or ("Auto" if chosen == "auto" else chosen)
        if v.quality_btn.text() != shown:
            v.quality_btn.setText(shown)
            v.quality_btn.setToolTip(f"Stream quality: {QUALITY_LABELS[chosen]}")
            v._place_overlays()
        _mirror(v.snapshot_btn, m.snapshot_btn)
        _mirror(v.record_btn, m.record_btn)
        _mirror(v.timelapse_btn, m.timelapse_btn)
        v.record_btn.setToolTip("Stop recording" if m.record_btn.isChecked() else "Record an MP4 clip")
        v.timelapse_btn.setToolTip("Stop the timelapse (saves the video)" if m.timelapse_btn.isChecked() else "Print timelapse")
        latest = m.update_manager.latest
        if (latest is not None) != v.update_btn.isVisible():
            v.update_btn.setVisible(latest is not None)
            v._place_overlays()
        if latest is not None and v.update_btn.text() != f"Update to {latest.version}":
            v.update_btn.setText(f"Update to {latest.version}")
            v._place_overlays()
        # The full window doesn't need a button that opens the full window.
        in_main = v.window() is m
        if v.window_btn.isVisible() == in_main:
            v.window_btn.setVisible(not in_main)
            v._place_overlays()

    def _sync_camera(self) -> None:
        m, c = self.main, self.camera
        connected = m.controller.logged_in
        selected = m._selected_camera()

        # Header
        names = [m.camera_list.item(i).text().split("\n")[0] for i in range(m.camera_list.count())]
        many = len(names) > 1
        c.camera_combo.setVisible(many)
        c.name_label.setVisible(not many)
        if many:
            current = [c.camera_combo.itemText(i) for i in range(c.camera_combo.count())]
            if current != names:
                c.camera_combo.blockSignals(True)
                c.camera_combo.clear()
                c.camera_combo.addItems(names)
                c.camera_combo.blockSignals(False)
            if c.camera_combo.currentIndex() != m.camera_list.currentRow():
                c.camera_combo.blockSignals(True)
                c.camera_combo.setCurrentIndex(m.camera_list.currentRow())
                c.camera_combo.blockSignals(False)
        name = selected.nickname if selected else (m.settings.camera_nickname or "Wyze camera")
        if c.name_label.text() != name:
            c.name_label.setText(name)
        if connected and selected is not None:
            status = "<span style='color:#62d361'>●</span> Connected to Wyze"
        elif connected:
            status = "<span style='color:#e0a84a'>●</span> Signed in — pick a camera"
        else:
            status = "<span style='color:#8a8d93'>●</span> Not connected to Wyze"
        if c.status_label.text() != status:
            c.status_label.setText(status)
        c.refresh_btn.setVisible(connected)

        # Banner: only when there's something to do or wait for.
        message = m.conn_label.text()
        needs_attention = not (connected and selected is not None)
        c.banner.setVisible(needs_attention)
        if needs_attention:
            if not message or message.startswith("Connected"):
                message = "Connect to Wyze to use the siren, spotlight and alerts."
            if c.banner_text.text() != message:
                c.banner_text.setText(message)
            _mirror(c.connect_btn, m.connect_btn)
            c.connect_btn.setText("Retry now" if "Retrying" in message else "Connect")

        # Tiles and power
        for tile, control in (
            (c.siren_tile, m.siren_btn),
            (c.spotlight_tile, m.spotlight_btn),
            (c.motion_tile, m.motion_check),
            (c.notify_tile, m.notify_check),
        ):
            _mirror(tile, control)
            tile.set_state(_toggle_state(control) if control.isEnabled() else "—")
        watch_on = bool(m.settings.ai_watch) and m.print_watch.model_ready()
        if c.watch_tile.isChecked() != watch_on:
            c.watch_tile.setChecked(watch_on)
        if watch_on:
            c.watch_tile.set_state(m.print_watch.status_text().split(": ", 1)[-1].capitalize() or "On")
        else:
            c.watch_tile.set_state("Off" if m.print_watch.model_ready() else "Off · model not downloaded")
        for button, control in (
            (c.power_on_btn, m.power_on_btn),
            (c.power_off_btn, m.power_off_btn),
            (c.restart_btn, m.restart_btn),
        ):
            _mirror(button, control)

        # Details
        if selected is not None:
            # A friendly model name and the firmware; no device codes, MAC or
            # network address on screen.
            parts = [friendly_model(m.info_model.text())]
            firmware = m.info_firmware.text()
            if firmware and firmware != "—":
                parts.append(f"firmware {firmware}")
            details = " · ".join(p for p in parts if p)
        else:
            details = "Camera details appear once connected."
        if c.details_label.text() != details:
            c.details_label.setText(details)
