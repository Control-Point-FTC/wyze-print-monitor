"""Main window: eufyMake Studio Device-tab layout — camera sidebar on the left,
live monitor in the center, Control + Camera panels on the right."""
from __future__ import annotations

import datetime
import os
import time

import cv2
import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabBar,
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
        self._timelapse_write_warned = False
        self._timelapse_frames_dir = ""
        self._compile_worker: TimelapseCompileWorker | None = None
        self._cameras: list[CameraInfo] = []
        self._last_frame: np.ndarray | None = None
        self._rec_start: float | None = None
        self._stream_state = "idle"

        self._build_ui()
        self._apply_always_on_top()
        if self.settings.rtsp_url:
            self._start_stream()
        QTimer.singleShot(500, self._auto_connect)

    # ------------------------------------------------------------------ UI build
    def _build_ui(self) -> None:
        self._build_menus()

        # View tab bar, eufyMake "Slice | Device" style (single Monitor view).
        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.addTab("Monitor")

        main = QWidget()
        main_layout = QVBoxLayout(main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(self.tab_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_sidebar())
        splitter.addWidget(self._build_monitor_pane())
        splitter.addWidget(self._build_right_pane())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        main_layout.addWidget(splitter, 1)

        self.setCentralWidget(main)
        self.statusBar().showMessage("Ready")
        self._set_controls_enabled(False)

    def _build_sidebar(self) -> QWidget:
        """Left device list, eufyMake "My Printer" style. Selects the camera."""
        side = QWidget()
        side.setFixedWidth(210)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title = QLabel("My Camera")
        title.setObjectName("paneHeader")
        layout.addWidget(title)

        self.camera_list = QListWidget()
        self.camera_list.setObjectName("cameraList")
        self.camera_list.currentRowChanged.connect(self._on_sidebar_camera_selected)
        layout.addWidget(self.camera_list, 1)
        return side

    def _build_monitor_pane(self) -> QWidget:
        """Center: Monitor video panel + Session stats, eufyMake style."""
        monitor = QWidget()
        layout = QVBoxLayout(monitor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel("Monitor")
        header.setObjectName("paneHeader")
        layout.addWidget(header)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.setSpacing(0)

        self.video_label = QLabel("No signal — set your RTSP URL in Settings.")
        self.video_label.setObjectName("videoLabel")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(480, 270)
        body_layout.addWidget(self.video_label, 1)

        # Thin player bar under the picture: status pill left, info right.
        player_bar = QWidget()
        player_bar.setObjectName("playerBar")
        bar = QHBoxLayout(player_bar)
        bar.setContentsMargins(8, 4, 8, 4)
        self.status_pill = QLabel("Idle")
        self.status_pill.setObjectName("statusPill")
        self._set_pill("idle")
        self.stream_info_label = QLabel("")
        self.stream_info_label.setStyleSheet("color: #9a9ea5;")
        self.stream_info_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bar.addWidget(self.status_pill)
        bar.addWidget(self.stream_info_label, 1)
        body_layout.addWidget(player_bar)
        layout.addWidget(body, 1)

        # Session panel, eufyMake "Progress" style: live capture stats.
        session_header = QLabel("Session")
        session_header.setObjectName("paneHeader")
        layout.addWidget(session_header)
        session = QWidget()
        form = QFormLayout(session)
        form.setContentsMargins(12, 8, 12, 8)
        self.session_stream = QLabel("Idle")
        self.session_stream.setObjectName("sessionValue")
        self.session_rec = QLabel("—")
        self.session_rec.setObjectName("sessionValue")
        self.session_timelapse = QLabel("—")
        self.session_timelapse.setObjectName("sessionValue")
        stream_cap = QLabel("Stream")
        stream_cap.setObjectName("sessionCaption")
        rec_cap = QLabel("Recording")
        rec_cap.setObjectName("sessionCaption")
        tl_cap = QLabel("Timelapse")
        tl_cap.setObjectName("sessionCaption")
        form.addRow(stream_cap, self.session_stream)
        form.addRow(rec_cap, self.session_rec)
        form.addRow(tl_cap, self.session_timelapse)
        layout.addWidget(session)
        return monitor

    def _stat_card(self, caption: str) -> tuple[QLabel, QLabel, QFrame]:
        """Big readout card, eufyMake temperature-card style."""
        card = QFrame()
        card.setObjectName("statCard")
        vbox = QVBoxLayout(card)
        vbox.setContentsMargins(12, 10, 12, 10)
        value = QLabel("—")
        value.setObjectName("statValue")
        value.setAlignment(Qt.AlignCenter)
        cap = QLabel(caption)
        cap.setObjectName("statCaption")
        cap.setAlignment(Qt.AlignCenter)
        vbox.addWidget(value)
        vbox.addWidget(cap)
        return value, cap, card

    def _build_right_pane(self) -> QWidget:
        """Right column: Control panel, then the Camera panel where eufyMake
        puts its "Others" section."""
        right = QWidget()
        right.setFixedWidth(340)
        layout = QVBoxLayout(right)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        control_header = QLabel("Control")
        control_header.setObjectName("paneHeader")
        layout.addWidget(control_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(8, 8, 8, 8)

        # Big readout cards, eufyMake temperature-card style.
        cards = QHBoxLayout()
        self.stat_stream_value, self.stat_stream_cap, stream_card = self._stat_card("Stream")
        self.stat_video_value, self.stat_video_cap, video_card = self._stat_card("Video")
        self.stat_stream_cap.setText("State")
        cards.addWidget(stream_card)
        cards.addWidget(video_card)
        content_layout.addLayout(cards)

        # Capture actions, 2x2 grid.
        cap_grid = QGridLayout()
        cap_grid.setSpacing(8)
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
        cap_grid.addWidget(self.snapshot_btn, 0, 0)
        cap_grid.addWidget(self.record_btn, 0, 1)
        cap_grid.addWidget(self.timelapse_btn, 1, 0)
        cap_grid.addWidget(self.fullscreen_btn, 1, 1)
        content_layout.addLayout(cap_grid)
        panel_layout.addWidget(content)

        # Camera device controls, in eufyMake's "Others" position.
        camera_header = QLabel("Camera")
        camera_header.setObjectName("paneHeader")
        panel_layout.addWidget(camera_header)

        content2 = QWidget()
        content2_layout = QVBoxLayout(content2)
        content2_layout.setContentsMargins(8, 8, 8, 8)
        content2_layout.addWidget(self._connection_group())
        content2_layout.addWidget(self._camera_group())
        content2_layout.addWidget(self._siren_spotlight_group())
        content2_layout.addWidget(self._detection_group())
        content2_layout.addWidget(self._device_info_group())
        content2_layout.addStretch(1)
        panel_layout.addWidget(content2)

        scroll.setWidget(panel)
        layout.addWidget(scroll, 1)
        return right

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
        self.fullscreen_action = QAction("Fullscreen", self, checkable=True)
        self.fullscreen_action.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(self.fullscreen_action)

        settings_menu = self.menuBar().addMenu("Settings")
        settings_menu.addAction(settings_action)

        help_menu = self.menuBar().addMenu("Help")
        about_action = QAction("About Wyze Print Monitor", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About Wyze Print Monitor",
            "Wyze Print Monitor v1\n\nLive RTSP view plus Wyze camera controls "
            "for 3D-print monitoring.\nSecrets live in the OS keyring, never on disk.",
        )

    def _connection_group(self) -> QGroupBox:
        # Camera selection lives in the left sidebar; this group only connects.
        box = QGroupBox("Connection")
        layout = QVBoxLayout(box)
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
        self.motion_check.toggled.connect(self._on_motion_changed)
        self.notify_check = QCheckBox("Push notifications")
        self.notify_check.toggled.connect(self._on_notify_changed)
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
        self._stream_state = state
        self.status_pill.setText(labels.get(state, state))
        self._set_pill(state)
        self.session_stream.setText(labels.get(state, state))
        self._update_stat_cards()
        # Frames stop arriving on disconnect/error, so refresh the session
        # panel here too — otherwise it keeps showing a stale active state.
        self._update_session_panel()
        self.statusBar().showMessage(detail, 5000)

    def _update_stat_cards(self) -> None:
        state_labels = {
            "connecting": "…",
            "live": "LIVE",
            "reconnecting": "…",
            "stopped": "Idle",
            "error": "Error",
            "idle": "Idle",
        }
        self.stat_stream_value.setText(state_labels.get(self._stream_state, "Idle"))
        if self._reader is not None:
            w, h = self._reader.frame_size
            fps = self._reader.measured_fps
            if w and h:
                self.stat_video_value.setText(f"{fps:.0f} fps")
                self.stat_video_cap.setText(f"{w} × {h}")
                return
        self.stat_video_value.setText("—")
        self.stat_video_cap.setText("Video")

    def _update_session_panel(self) -> None:
        if self._recorder is not None and self._rec_start is not None:
            elapsed = int(time.monotonic() - self._rec_start)
            self.session_rec.setText(
                f"● {elapsed // 60:02d}:{elapsed % 60:02d}"
                f" · {self._recorder.frames_written} frames"
            )
        else:
            self.session_rec.setText("—")
        if self._timelapse is not None:
            self.session_timelapse.setText(
                f"{self._timelapse.saved} frames · every {self._timelapse.interval_sec}s"
            )
        else:
            self.session_timelapse.setText("—")

    def _on_frame(self, frame: np.ndarray) -> None:
        self._last_frame = frame
        if self._reader is not None:
            w, h = self._reader.frame_size
            fps = self._reader.measured_fps
            if w and h:
                self.stream_info_label.setText(f"{w}×{h}  •  {fps:.0f} fps")
        self._update_stat_cards()
        self._update_session_panel()

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
            collector = self._timelapse
            collector.maybe_capture(frame)
            if collector.write_errors and not self._timelapse_write_warned:
                self._timelapse_write_warned = True
                self.statusBar().showMessage(
                    "Timelapse: couldn't save a frame — check disk space.", 8000
                )

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
        if cv2.imwrite(path, self._last_frame):
            self.statusBar().showMessage(f"Snapshot saved: {path}", 5000)
        else:
            QMessageBox.warning(self, "Snapshot", f"Couldn't save snapshot to:\n{path}")

    def _on_record_toggled(self, checked: bool) -> None:
        if checked:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            path = os.path.join(
                self.settings.resolved_video_dir(), f"clip_{stamp}.mp4"
            )
            # Record at the stream's measured rate so clips play back in real
            # time instead of a fixed (wrong) 20 fps.
            fps = self._reader.measured_fps if self._reader is not None else 0.0
            self._recorder = ClipRecorder(path, fps=fps or 20.0)
            self._rec_start = time.monotonic()
            self.record_btn.setText("Stop recording")
            self._update_session_panel()
            self.statusBar().showMessage("Recording…", 3000)
        else:
            if self._recorder is not None:
                path = self._recorder.output_path
                count = self._recorder.frames_written
                self._recorder.close()
                self._recorder = None
                self._rec_start = None
                self.statusBar().showMessage(
                    f"Saved clip ({count} frames): {path}", 8000
                )
            self.record_btn.setText("Record")
            self._update_session_panel()

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
            self._timelapse_write_warned = False
            self.timelapse_btn.setText("Stop timelapse")
            self._update_session_panel()
            self.statusBar().showMessage(
                f"Timelapse capturing every {self.settings.timelapse_interval_sec}s…",
                4000,
            )
        else:
            collector = self._timelapse
            self._timelapse = None
            self.timelapse_btn.setText("Timelapse")
            self._update_session_panel()
            if collector is None or collector.saved == 0:
                self.statusBar().showMessage("Timelapse stopped, no frames captured.", 5000)
                return
            output = os.path.join(
                self.settings.resolved_video_dir(),
                f"timelapse_{datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.mp4",
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
        self.fullscreen_action.setChecked(self.isFullScreen())

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
            # Block signals while rebuilding: selecting the first row would
            # otherwise fire currentRowChanged, which overwrites the saved
            # camera_mac before we restore the selection.
            self.camera_list.blockSignals(True)
            try:
                self.camera_list.clear()
                for cam in self._cameras:
                    item = QListWidgetItem(f"{cam.nickname}\n{cam.product_model}")
                    item.setData(Qt.UserRole, cam.mac)
                    self.camera_list.addItem(item)
                self._select_sidebar_camera_from_settings()
            finally:
                self.camera_list.blockSignals(False)
            self._update_connection_ui()

        self.controller.list_cameras(done)

    def _select_sidebar_camera_from_settings(self) -> None:
        if not self._cameras or not self.settings.camera_mac:
            return
        for row in range(self.camera_list.count()):
            if self.camera_list.item(row).data(Qt.UserRole) == self.settings.camera_mac:
                self.camera_list.setCurrentRow(row)
                return

    def _on_sidebar_camera_selected(self) -> None:
        self._update_connection_ui()

    def _selected_camera(self) -> CameraInfo | None:
        row = self.camera_list.currentRow()
        if row < 0:
            return None
        mac = self.camera_list.item(row).data(Qt.UserRole)
        return next((c for c in self._cameras if c.mac == mac), None)

    def _update_connection_ui(self) -> None:
        cam = self._selected_camera()
        if cam is None:
            if self.controller.logged_in:
                self.conn_label.setText("Select a camera on the left.")
            else:
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

    def _on_motion_changed(self, on: bool) -> None:
        self._cam_action(
            "Motion detection " + ("on" if on else "off"),
            self.controller.set_motion_detection,
            on,
        )

    def _on_notify_changed(self, on: bool) -> None:
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
            else:
                # URL was cleared: stop the old camera instead of letting it
                # keep streaming (and recording) with the stale URL.
                self._stop_stream()
            # The dialog may have completed a fresh login, in which case the
            # main window's camera list is still empty — repopulate it so the
            # controls don't stay disabled after setup.
            if self.controller.logged_in:
                self._on_refresh_cameras()
            else:
                self._select_sidebar_camera_from_settings()

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
        if self._compile_worker is not None and self._compile_worker.isRunning():
            # The window owns the QThread: never tear down a running encoder.
            self.statusBar().showMessage("Finishing timelapse compile before exit…")
            self._compile_worker.wait(60000)
        if self._recorder is not None:
            self._recorder.close()
        self._stop_stream()
        self.runner.stop()
        save_settings(self.settings)
        super().closeEvent(event)
