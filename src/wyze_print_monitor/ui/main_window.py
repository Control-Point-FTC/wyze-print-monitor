"""Main window: live monitor on the left, camera control panel on the right."""
from __future__ import annotations

import datetime
import os

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..async_runner import AsyncRunner
from ..capture import ClipRecorder, StreamReader, snapshot_path
from ..config import (
    SECRET_API_KEY,
    SECRET_KEY_ID,
    SECRET_PASSWORD,
    Settings,
    effective_rtsp_url,
    get_secret,
    load_settings,
    save_settings,
)
from ..timelapse import TimelapseCollector, compile_timelapse
from ..wyze_control import CameraInfo, WyzeController
from .settings_dialog import SettingsDialog, forget_secrets


class TimelapseCompileWorker(QThread):
    """Compiles saved JPEG frames into an MP4 off the GUI thread."""

    done = Signal(str, int)  # output path, frame count
    failed = Signal(str)

    def __init__(self, frames_dir: str, output_path: str, parent=None) -> None:
        super().__init__(parent)
        self._frames_dir = frames_dir
        self._output_path = output_path

    def run(self) -> None:
        try:
            count = compile_timelapse(self._frames_dir, self._output_path)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, not swallowed
            self.failed.emit(f"Could not compile timelapse: {exc}")
        else:
            self.done.emit(self._output_path, count)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Wyze Print Monitor")
        self.resize(1180, 720)

        self.settings = load_settings()
        self.runner = AsyncRunner(self)
        self.runner.start()
        self.controller = WyzeController(self.runner)

        self._reader: StreamReader | None = None
        self._recorder: ClipRecorder | None = None
        self._timelapse: TimelapseCollector | None = None
        self._timelapse_frames_dir = ""
        self._compile_worker: TimelapseCompileWorker | None = None
        self._cameras: list[CameraInfo] = []
        self._last_frame: np.ndarray | None = None

        self._build_ui()
        self._apply_always_on_top()
        if self.settings.rtsp_url:
            self._start_stream()
        QTimer.singleShot(500, self._auto_connect)

    # ------------------------------------------------------------------ UI build
    def _build_ui(self) -> None:
        self._build_menus()

        splitter = QSplitter(Qt.Horizontal)

        # ---- left: monitor (eufyMake-style full-width header bar + body) ----
        monitor = QWidget()
        monitor_layout = QVBoxLayout(monitor)
        monitor_layout.setContentsMargins(0, 0, 0, 0)
        monitor_layout.setSpacing(0)

        monitor_header = QLabel("Monitor")
        monitor_header.setObjectName("paneHeader")
        monitor_layout.addWidget(monitor_header)

        monitor_body = QWidget()
        body_layout = QVBoxLayout(monitor_body)
        body_layout.setContentsMargins(8, 8, 8, 8)

        self.video_label = QLabel("No signal — set your RTSP URL in Settings.")
        self.video_label.setObjectName("videoLabel")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(480, 270)
        body_layout.addWidget(self.video_label, 1)

        info_row = QHBoxLayout()
        self.status_pill = QLabel("Idle")
        self.status_pill.setObjectName("statusPill")
        self._set_pill("idle")
        self.stream_info_label = QLabel("")
        self.stream_info_label.setStyleSheet("color: #9a9ea5;")
        info_row.addWidget(self.status_pill)
        info_row.addWidget(self.stream_info_label, 1)
        body_layout.addLayout(info_row)

        btn_row = QHBoxLayout()
        self.snapshot_btn = QPushButton("Snapshot")
        self.snapshot_btn.clicked.connect(self._on_snapshot)
        self.record_btn = QPushButton("Record")
        self.record_btn.setCheckable(True)
        self.record_btn.clicked.connect(self._on_record_toggled)
        self.timelapse_btn = QPushButton("Timelapse")
        self.timelapse_btn.setCheckable(True)
        self.timelapse_btn.clicked.connect(self._on_timelapse_toggled)
        self.fullscreen_btn = QPushButton("Fullscreen")
        self.fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        for b in (self.snapshot_btn, self.record_btn, self.timelapse_btn, self.fullscreen_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        body_layout.addLayout(btn_row)
        monitor_layout.addWidget(monitor_body, 1)
        splitter.addWidget(monitor)

        # ---- right: control panel ----
        right = QWidget()
        right.setFixedWidth(340)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        control_header = QLabel("Control")
        control_header.setObjectName("paneHeader")
        right_layout.addWidget(control_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.addStretch(0)

        panel_layout.addWidget(self._connection_group())
        panel_layout.addWidget(self._camera_group())
        panel_layout.addWidget(self._siren_spotlight_group())
        panel_layout.addWidget(self._detection_group())
        panel_layout.addWidget(self._device_info_group())
        panel_layout.addStretch(1)

        scroll.setWidget(panel)
        right_layout.addWidget(scroll, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        self.setCentralWidget(splitter)

        self.statusBar().showMessage("Ready")
        self._set_controls_enabled(False)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        forget_action = QAction("Forget Wyze credentials", self)
        forget_action.triggered.connect(self._forget_credentials)
        file_menu.addAction(forget_action)

        file_menu.addSeparator()
        snaps_action = QAction("Open snapshot folder", self)
        snaps_action.triggered.connect(
            lambda: self._open_folder(self.settings.resolved_snapshot_dir())
        )
        file_menu.addAction(snaps_action)
        vids_action = QAction("Open video folder", self)
        vids_action.triggered.connect(
            lambda: self._open_folder(self.settings.resolved_video_dir())
        )
        file_menu.addAction(vids_action)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = self.menuBar().addMenu("View")
        self.on_top_action = QAction("Always on top", self, checkable=True)
        self.on_top_action.setChecked(self.settings.always_on_top)
        self.on_top_action.triggered.connect(self._toggle_always_on_top)
        view_menu.addAction(self.on_top_action)

    def _connection_group(self) -> QGroupBox:
        box = QGroupBox("Connection")
        layout = QVBoxLayout(box)
        self.camera_combo = QComboBox()
        self.camera_combo.currentIndexChanged.connect(self._on_camera_selected)
        layout.addWidget(self.camera_combo)
        row = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("accentButton")
        self.connect_btn.clicked.connect(self._on_connect)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._on_refresh_cameras)
        row.addWidget(self.connect_btn)
        row.addWidget(self.refresh_btn)
        layout.addLayout(row)
        self.conn_label = QLabel("Not connected to Wyze.")
        self.conn_label.setWordWrap(True)
        self.conn_label.setStyleSheet("color: #9a9ea5;")
        layout.addWidget(self.conn_label)
        return box

    def _camera_group(self) -> QGroupBox:
        box = QGroupBox("Camera")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        self.power_on_btn = QPushButton("Turn on")
        self.power_off_btn = QPushButton("Turn off")
        self.power_on_btn.clicked.connect(lambda: self._cam_action("Power on", self.controller.set_power, True))
        self.power_off_btn.clicked.connect(lambda: self._cam_action("Power off", self.controller.set_power, False))
        row.addWidget(self.power_on_btn)
        row.addWidget(self.power_off_btn)
        layout.addLayout(row)
        self.restart_btn = QPushButton("Restart camera")
        self.restart_btn.clicked.connect(self._on_restart)
        layout.addWidget(self.restart_btn)
        return box

    def _siren_spotlight_group(self) -> QGroupBox:
        box = QGroupBox("Siren && spotlight")
        layout = QVBoxLayout(box)
        self.siren_btn = QPushButton("Siren: off")
        self.siren_btn.setCheckable(True)
        self.siren_btn.clicked.connect(self._on_siren_toggled)
        self.spotlight_btn = QPushButton("Spotlight: off")
        self.spotlight_btn.setCheckable(True)
        self.spotlight_btn.clicked.connect(self._on_spotlight_toggled)
        layout.addWidget(self.siren_btn)
        layout.addWidget(self.spotlight_btn)
        hint = QLabel("Siren and spotlight toggle on the camera itself.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9a9ea5;")
        layout.addWidget(hint)
        return box

    def _detection_group(self) -> QGroupBox:
        box = QGroupBox("Detection")
        layout = QVBoxLayout(box)
        self.motion_check = QCheckBox("Motion detection")
        self.motion_check.stateChanged.connect(self._on_motion_changed)
        self.notify_check = QCheckBox("Push notifications")
        self.notify_check.stateChanged.connect(self._on_notify_changed)
        layout.addWidget(self.motion_check)
        layout.addWidget(self.notify_check)
        return box

    def _device_info_group(self) -> QGroupBox:
        box = QGroupBox("Device info")
        layout = QFormLayout(box)
        self.info_model = QLabel("—")
        self.info_status = QLabel("—")
        self.info_firmware = QLabel("—")
        self.info_ip = QLabel("—")
        layout.addRow("Model", self.info_model)
        layout.addRow("Status", self.info_status)
        layout.addRow("Firmware", self.info_firmware)
        layout.addRow("IP", self.info_ip)
        return box

    # ------------------------------------------------------------------ helpers
    def _set_pill(self, state: str) -> None:
        colors = {
            "idle": ("#3d4148", "#d7d9dc"),
            "connecting": ("#8a6d2f", "#ffffff"),
            "live": ("#2f7d3a", "#ffffff"),
            "reconnecting": ("#8a6d2f", "#ffffff"),
            "error": ("#8a2f2f", "#ffffff"),
            "stopped": ("#3d4148", "#d7d9dc"),
        }
        bg, fg = colors.get(state, colors["idle"])
        self.status_pill.setStyleSheet(
            f"QLabel#statusPill {{ background-color: {bg}; color: {fg}; }}"
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.power_on_btn,
            self.power_off_btn,
            self.restart_btn,
            self.siren_btn,
            self.spotlight_btn,
            self.motion_check,
            self.notify_check,
        ):
            widget.setEnabled(enabled)

    def _open_folder(self, path: str) -> None:
        os.makedirs(path, exist_ok=True)
        # QDesktopServices handles Windows/macOS/Linux without shelling out.
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------ stream
    def _start_stream(self) -> None:
        self._stop_stream()
        self._reader = StreamReader(effective_rtsp_url(self.settings), self)
        self._reader.frame_ready.connect(self._on_frame)
        self._reader.state_changed.connect(self._on_stream_state)
        self._reader.start()

    def _stop_stream(self) -> None:
        if self._reader is not None:
            self._reader.frame_ready.disconnect(self._on_frame)
            self._reader.state_changed.disconnect(self._on_stream_state)
            self._reader.stop()
            self._reader = None

    def _on_stream_state(self, state: str, detail: str) -> None:
        labels = {
            "connecting": "Connecting",
            "live": "Live",
            "reconnecting": "Reconnecting",
            "stopped": "Stopped",
            "error": "Error",
        }
        self.status_pill.setText(labels.get(state, state))
        self._set_pill(state)
        self.statusBar().showMessage(detail, 5000)

    def _on_frame(self, frame: np.ndarray) -> None:
        self._last_frame = frame
        if self._reader is not None:
            w, h = self._reader.frame_size
            fps = self._reader.measured_fps
            if w and h:
                self.stream_info_label.setText(f"{w}×{h}  •  {fps:.0f} fps")

        if self._recorder is not None:
            try:
                self._recorder.write(frame)
            except IOError as exc:
                # e.g. folder became unwritable mid-recording: stop cleanly
                # instead of claiming a good clip at the end.
                self._recorder.close()
                self._recorder = None
                self.record_btn.setChecked(False)
                self.record_btn.setText("Record")
                QMessageBox.warning(self, "Recording failed", str(exc))
        if self._timelapse is not None:
            self._timelapse.maybe_capture(frame)

        label_w = self.video_label.width()
        label_h = self.video_label.height()
        if label_w < 2 or label_h < 2:
            return
        h, w = frame.shape[:2]
        scale = min(label_w / w, label_h / h)
        new_w, new_h = int(w * scale), int(h * scale)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.video_label.setPixmap(pixmap)

    # ------------------------------------------------------------------ capture actions
    def _on_snapshot(self) -> None:
        if self._last_frame is None:
            QMessageBox.information(self, "Snapshot", "No video frame available yet.")
            return
        path = snapshot_path(self.settings.resolved_snapshot_dir())
        cv2.imwrite(path, self._last_frame)
        self.statusBar().showMessage(f"Snapshot saved: {path}", 5000)

    def _on_record_toggled(self, checked: bool) -> None:
        if checked:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            path = os.path.join(
                self.settings.resolved_video_dir(), f"clip_{stamp}.mp4"
            )
            # Record at the stream's measured rate so clips play back in real
            # time instead of a fixed (wrong) 20 fps.
            fps = self._reader.measured_fps if self._reader is not None else 0.0
            self._recorder = ClipRecorder(path, fps=fps or 20.0)
            self.record_btn.setText("Stop recording")
            self.statusBar().showMessage("Recording…", 3000)
        else:
            if self._recorder is not None:
                path = self._recorder.output_path
                count = self._recorder.frames_written
                self._recorder.close()
                self._recorder = None
                self.statusBar().showMessage(
                    f"Saved clip ({count} frames): {path}", 8000
                )
            self.record_btn.setText("Record")

    def _on_timelapse_toggled(self, checked: bool) -> None:
        if checked:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            self._timelapse_frames_dir = os.path.join(
                self.settings.resolved_video_dir(), f"timelapse_{stamp}_frames"
            )
            self._timelapse = TimelapseCollector(
                self._timelapse_frames_dir,
                interval_sec=self.settings.timelapse_interval_sec,
            )
            self._timelapse.start()
            self.timelapse_btn.setText("Stop timelapse")
            self.statusBar().showMessage(
                f"Timelapse capturing every {self.settings.timelapse_interval_sec}s…",
                4000,
            )
        else:
            collector = self._timelapse
            self._timelapse = None
            self.timelapse_btn.setText("Timelapse")
            if collector is None or collector.saved == 0:
                self.statusBar().showMessage("Timelapse stopped, no frames captured.", 5000)
                return
            output = os.path.join(
                self.settings.resolved_video_dir(),
                f"timelapse_{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.mp4",
            )
            # Compile off the GUI thread: a long print leaves thousands of
            # frames to encode, which would freeze the live view.
            self.timelapse_btn.setEnabled(False)
            self.statusBar().showMessage("Compiling timelapse…", 3000)
            self._compile_worker = TimelapseCompileWorker(collector.frames_dir, output, self)
            self._compile_worker.done.connect(self._on_timelapse_compiled)
            self._compile_worker.failed.connect(self._on_timelapse_failed)
            self._compile_worker.start()

    def _on_timelapse_compiled(self, path: str, count: int) -> None:
        self.timelapse_btn.setEnabled(True)
        self.statusBar().showMessage(f"Timelapse saved ({count} frames): {path}", 8000)
        self._compile_worker = None

    def _on_timelapse_failed(self, error: str) -> None:
        self.timelapse_btn.setEnabled(True)
        QMessageBox.warning(self, "Timelapse", error)
        self._compile_worker = None

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    # ------------------------------------------------------------------ wyze
    def _auto_connect(self) -> None:
        email = self.settings.wyze_email
        if email and get_secret(SECRET_PASSWORD) and get_secret(SECRET_KEY_ID) and get_secret(SECRET_API_KEY):
            self._on_connect(silent=True)

    def _on_connect(self, silent: bool = False) -> None:
        email = self.settings.wyze_email or ""
        password = get_secret(SECRET_PASSWORD) or ""
        key_id = get_secret(SECRET_KEY_ID) or ""
        api_key = get_secret(SECRET_API_KEY) or ""
        if not (email and password and key_id and api_key):
            if not silent:
                QMessageBox.information(
                    self,
                    "Wyze not configured",
                    "Open File → Settings… and enter your Wyze email, password, "
                    "API key ID and API key first.",
                )
            return
        self.conn_label.setText("Connecting to Wyze…")
        self.connect_btn.setEnabled(False)

        def done(ok: bool, _result, error: str) -> None:
            self.connect_btn.setEnabled(True)
            if not ok:
                if "NeedTwoFactor" in error:
                    self._ask_2fa()
                else:
                    self.conn_label.setText("Login failed.")
                    if not silent:
                        QMessageBox.critical(self, "Wyze login failed", error)
                return
            self._on_refresh_cameras()

        self.controller.login(email, password, key_id, api_key, done)

    def _ask_2fa(self) -> None:
        code, accepted = QInputDialog.getText(
            self,
            "Two-factor authentication",
            "Enter the verification code Wyze sent you:",
        )
        if not accepted or not code.strip():
            self.conn_label.setText("2FA cancelled.")
            return

        def done(ok: bool, _result, error: str) -> None:
            if not ok:
                self.conn_label.setText("2FA failed.")
                QMessageBox.critical(self, "2FA failed", error)
                return
            self._on_refresh_cameras()

        self.controller.submit_2fa(code.strip(), done)

    def _on_refresh_cameras(self) -> None:
        def done(ok: bool, result, error: str) -> None:
            if not ok:
                self.conn_label.setText("Could not list cameras.")
                QMessageBox.critical(self, "Camera list failed", error)
                return
            self._cameras = result or []
            # Block signals while rebuilding: adding the first item would
            # otherwise fire currentIndexChanged, which overwrites the saved
            # camera_mac with the first camera before we restore the selection.
            self.camera_combo.blockSignals(True)
            try:
                self.camera_combo.clear()
                for cam in self._cameras:
                    self.camera_combo.addItem(
                        f"{cam.nickname} ({cam.product_model})", cam.mac
                    )
                if self.settings.camera_mac:
                    index = self.camera_combo.findData(self.settings.camera_mac)
                    if index >= 0:
                        self.camera_combo.setCurrentIndex(index)
            finally:
                self.camera_combo.blockSignals(False)
            self._update_connection_ui()

        self.controller.list_cameras(done)

    def _on_camera_selected(self) -> None:
        self._update_connection_ui()

    def _update_connection_ui(self) -> None:
        mac = self.camera_combo.currentData()
        cam = next((c for c in self._cameras if c.mac == mac), None)
        if cam is None:
            self.conn_label.setText("Not connected to Wyze.")
            self._set_controls_enabled(False)
            return
        self.settings.camera_mac = cam.mac
        self.settings.camera_nickname = cam.nickname
        save_settings(self.settings)
        self.conn_label.setText(f"Connected: {cam.nickname}")
        self.info_model.setText(cam.product_model or "—")
        self.info_status.setText("Online" if cam.is_online else "Offline")
        self.info_firmware.setText(cam.firmware or "—")
        self.info_ip.setText(cam.ip or "—")
        # The toggle states below reflect the previously selected camera (or
        # nothing on first run). Reset them to a neutral off display so the new
        # camera never appears to have a state we haven't read. Signals are
        # blocked so the reset doesn't fire commands at the camera.
        for widget in (self.siren_btn, self.spotlight_btn, self.motion_check, self.notify_check):
            widget.blockSignals(True)
        try:
            self.siren_btn.setChecked(False)
            self.siren_btn.setText("Siren: off")
            self.spotlight_btn.setChecked(False)
            self.spotlight_btn.setText("Spotlight: off")
            self.motion_check.setChecked(False)
            self.notify_check.setChecked(False)
        finally:
            for widget in (self.siren_btn, self.spotlight_btn, self.motion_check, self.notify_check):
                widget.blockSignals(False)
        self._set_controls_enabled(True)

    def _cam_action(self, label: str, fn, *args) -> None:
        mac = self.settings.camera_mac
        if not self.controller.logged_in or not mac:
            QMessageBox.information(
                self, label, "Connect to Wyze and select a camera first."
            )
            return
        self.statusBar().showMessage(f"{label}…")

        def done(ok: bool, _result, error: str) -> None:
            if ok:
                self.statusBar().showMessage(f"{label}: done", 4000)
            else:
                self.statusBar().showMessage(f"{label}: failed", 4000)
                QMessageBox.warning(self, label, error)

        fn(mac, *args, done)

    def _on_restart(self) -> None:
        answer = QMessageBox.question(
            self,
            "Restart camera",
            "Restart the camera? The stream will drop for about a minute.",
        )
        if answer == QMessageBox.Yes:
            self._cam_action("Restart", self.controller.restart)

    def _on_siren_toggled(self, checked: bool) -> None:
        self.siren_btn.setText(f"Siren: {'on' if checked else 'off'}")

        def done(ok: bool, _result, error: str) -> None:
            if not ok:
                self.siren_btn.setChecked(not checked)
                self.siren_btn.setText(f"Siren: {'off' if checked else 'on'}")
                QMessageBox.warning(self, "Siren", error)

        mac = self.settings.camera_mac
        if not self.controller.logged_in or not mac:
            self.siren_btn.setChecked(False)
            self.siren_btn.setText("Siren: off")
            QMessageBox.information(self, "Siren", "Connect to Wyze and select a camera first.")
            return
        self.controller.set_siren(mac, checked, done)

    def _on_spotlight_toggled(self, checked: bool) -> None:
        self.spotlight_btn.setText(f"Spotlight: {'on' if checked else 'off'}")

        def done(ok: bool, _result, error: str) -> None:
            if not ok:
                self.spotlight_btn.setChecked(not checked)
                self.spotlight_btn.setText(f"Spotlight: {'off' if checked else 'on'}")
                QMessageBox.warning(self, "Spotlight", error)

        mac = self.settings.camera_mac
        if not self.controller.logged_in or not mac:
            self.spotlight_btn.setChecked(False)
            self.spotlight_btn.setText("Spotlight: off")
            QMessageBox.information(self, "Spotlight", "Connect to Wyze and select a camera first.")
            return
        self.controller.set_spotlight(mac, checked, done)

    def _on_motion_changed(self, state: int) -> None:
        on = state == Qt.Checked
        self._cam_action(
            "Motion detection " + ("on" if on else "off"),
            self.controller.set_motion_detection,
            on,
        )

    def _on_notify_changed(self, state: int) -> None:
        on = state == Qt.Checked
        self._cam_action(
            "Notifications " + ("on" if on else "off"),
            self.controller.set_notifications,
            on,
        )

    # ------------------------------------------------------------------ misc
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.controller, self)
        if dialog.exec() == QDialog.Accepted:
            save_settings(self.settings)
            self._apply_always_on_top()
            self.on_top_action.setChecked(self.settings.always_on_top)
            if effective_rtsp_url(self.settings):
                self._start_stream()
            # The dialog may have completed a fresh login, in which case the
            # main window's camera list is still empty — repopulate it so the
            # controls don't stay disabled after setup.
            if self.controller.logged_in:
                self._on_refresh_cameras()
            else:
                self._refresh_camera_combo_from_settings()

    def _refresh_camera_combo_from_settings(self) -> None:
        if not self._cameras or not self.settings.camera_mac:
            return
        index = self.camera_combo.findData(self.settings.camera_mac)
        if index >= 0:
            self.camera_combo.setCurrentIndex(index)

    def _forget_credentials(self) -> None:
        answer = QMessageBox.question(
            self,
            "Forget credentials",
            "Remove your Wyze password, API key ID and API key from the OS keyring?",
        )
        if answer == QMessageBox.Yes:
            forget_secrets()
            self.statusBar().showMessage("Wyze credentials removed from keyring.", 5000)

    def _apply_always_on_top(self) -> None:
        # Capture visibility BEFORE changing flags: setWindowFlag can hide the
        # window on some platforms, which would make a later isVisible() check
        # lie and leave the app hidden.
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, self.settings.always_on_top)
        # Toggling the flag needs the window to be re-shown on some platforms.
        if was_visible:
            self.show()

    def _toggle_always_on_top(self, checked: bool) -> None:
        self.settings.always_on_top = checked
        save_settings(self.settings)
        self._apply_always_on_top()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._recorder is not None:
            self._recorder.close()
        self._stop_stream()
        self.runner.stop()
        save_settings(self.settings)
        super().closeEvent(event)
