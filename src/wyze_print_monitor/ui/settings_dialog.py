"""Settings dialog: RTSP URL, Wyze credentials, camera picker, folders."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import autostart
from ..config import (
    SECRET_API_KEY,
    SECRET_KEY_ID,
    SECRET_PASSWORD,
    SECRET_RTSP_URL,
    Settings,
    delete_secret,
    effective_rtsp_url,
    get_secret,
    save_secret,
)
from ..wyze_control import CameraInfo, WyzeController


class SettingsDialog(QDialog):
    """Edits Settings; tests the Wyze login and fills the camera picker."""

    def __init__(
        self,
        settings: Settings,
        controller: WyzeController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(480, 520)
        self._settings = settings
        self._controller = controller
        self._cameras: list[CameraInfo] = []

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # Show the real URL (from the keyring when present); the settings file
        # only ever holds a redacted copy.
        self.rtsp_edit = QLineEdit(effective_rtsp_url(settings))
        self.rtsp_edit.setPlaceholderText("rtsp://user:pass@192.168.x.x/live")
        form.addRow("RTSP URL", self.rtsp_edit)

        self.email_edit = QLineEdit(settings.wyze_email)
        self.email_edit.setPlaceholderText("you@example.com")
        form.addRow("Wyze email", self.email_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Stored in OS keyring")
        if get_secret(SECRET_PASSWORD):
            self.password_edit.setPlaceholderText("Saved in keyring (leave blank to keep)")
        form.addRow("Wyze password", self.password_edit)

        self.key_id_edit = QLineEdit()
        self.key_id_edit.setPlaceholderText("Wyze API key ID")
        if get_secret(SECRET_KEY_ID):
            self.key_id_edit.setPlaceholderText("Saved in keyring (leave blank to keep)")
        form.addRow("API key ID", self.key_id_edit)

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("Wyze API key")
        if get_secret(SECRET_API_KEY):
            self.api_key_edit.setPlaceholderText("Saved in keyring (leave blank to keep)")
        form.addRow("API key", self.api_key_edit)

        help_label = QLabel(
            "Create the API key ID + key at Wyze's developer portal, then paste them here. "
            "Credentials are kept in your OS keyring, never in the settings file."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #9a9ea5;")
        form.addRow(help_label)

        self.test_button = QPushButton("Connect && list cameras")
        self.test_button.clicked.connect(self._on_test)
        form.addRow(self.test_button)

        self.camera_combo = QComboBox()
        self._refresh_camera_combo()
        form.addRow("Camera", self.camera_combo)

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(2, 300)
        self.interval_spin.setValue(settings.timelapse_interval_sec)
        self.interval_spin.setSuffix(" s")
        form.addRow("Timelapse interval", self.interval_spin)

        self.snapshot_edit = QLineEdit(settings.resolved_snapshot_dir())
        snap_btn = QPushButton("Browse…")
        snap_btn.clicked.connect(lambda: self._browse(self.snapshot_edit))
        snap_row = QHBoxLayout()
        snap_row.addWidget(self.snapshot_edit)
        snap_row.addWidget(snap_btn)
        form.addRow("Snapshot folder", snap_row)

        self.video_edit = QLineEdit(settings.resolved_video_dir())
        vid_btn = QPushButton("Browse…")
        vid_btn.clicked.connect(lambda: self._browse(self.video_edit))
        vid_row = QHBoxLayout()
        vid_row.addWidget(self.video_edit)
        vid_row.addWidget(vid_btn)
        form.addRow("Video folder", vid_row)

        self.on_top_check = QCheckBox("Keep window always on top")
        self.on_top_check.setChecked(settings.always_on_top)
        form.addRow(self.on_top_check)

        self.autostart_check = QCheckBox("Launch at startup")
        if autostart.supported():
            try:
                self.autostart_check.setChecked(autostart.is_enabled())
            except (NotImplementedError, OSError):
                self.autostart_check.setEnabled(False)
        else:
            self.autostart_check.setEnabled(False)
            self.autostart_check.setToolTip("Not supported on this platform")
        form.addRow(self.autostart_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------------ slots
    def _browse(self, edit: QLineEdit) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Choose folder", edit.text())
        if directory:
            edit.setText(directory)

    def _refresh_camera_combo(self) -> None:
        self.camera_combo.clear()
        for cam in self._cameras:
            label = f"{cam.nickname} ({cam.product_model})"
            self.camera_combo.addItem(label, cam.mac)
        if self._settings.camera_mac:
            index = self.camera_combo.findData(self._settings.camera_mac)
            if index >= 0:
                self.camera_combo.setCurrentIndex(index)

    def _on_test(self) -> None:
        email = self.email_edit.text().strip()
        password = self.password_edit.text() or get_secret(SECRET_PASSWORD) or ""
        key_id = self.key_id_edit.text().strip() or get_secret(SECRET_KEY_ID) or ""
        api_key = self.api_key_edit.text() or get_secret(SECRET_API_KEY) or ""
        if not (email and password and key_id and api_key):
            QMessageBox.warning(
                self,
                "Missing credentials",
                "Fill in email, password, API key ID and API key first.",
            )
            return
        self.test_button.setEnabled(False)
        self.test_button.setText("Connecting…")

        def done(ok: bool, _result, error: str) -> None:
            self.test_button.setEnabled(True)
            self.test_button.setText("Connect && list cameras")
            if not ok:
                if "NeedTwoFactor" in error:
                    QMessageBox.information(
                        self,
                        "2FA required",
                        "Wyze asked for a verification code. Save these settings, "
                        "then use Connect in the main window and enter the code when asked.",
                    )
                else:
                    QMessageBox.critical(self, "Login failed", error)
                return
            self._controller.list_cameras(self._on_cameras)

        self._controller.login(email, password, key_id, api_key, done)

    def _on_cameras(self, ok: bool, result, error: str) -> None:
        if not ok:
            QMessageBox.critical(self, "Could not list cameras", error)
            return
        self._cameras = result or []
        self._refresh_camera_combo()
        QMessageBox.information(
            self, "Connected", f"Found {len(self._cameras)} camera(s) on your account."
        )

    def _on_save(self) -> None:
        s = self._settings
        rtsp_url = self.rtsp_edit.text().strip()
        s.rtsp_url = rtsp_url  # save_settings() redacts credentials on write
        if rtsp_url:
            save_secret(SECRET_RTSP_URL, rtsp_url)
        else:
            delete_secret(SECRET_RTSP_URL)
        s.wyze_email = self.email_edit.text().strip()
        s.timelapse_interval_sec = self.interval_spin.value()
        s.snapshot_dir = self.snapshot_edit.text().strip()
        s.video_dir = self.video_edit.text().strip()
        s.always_on_top = self.on_top_check.isChecked()
        mac = self.camera_combo.currentData()
        if mac:
            s.camera_mac = mac
            s.camera_nickname = self.camera_combo.currentText()
        # Only overwrite secrets the user actually typed.
        if self.password_edit.text():
            save_secret(SECRET_PASSWORD, self.password_edit.text())
        if self.key_id_edit.text().strip():
            save_secret(SECRET_KEY_ID, self.key_id_edit.text().strip())
        if self.api_key_edit.text():
            save_secret(SECRET_API_KEY, self.api_key_edit.text())
        if autostart.supported() and self.autostart_check.isEnabled():
            try:
                autostart.set_enabled(self.autostart_check.isChecked())
            except (NotImplementedError, OSError) as exc:
                QMessageBox.warning(
                    self,
                    "Launch at startup",
                    f"Could not change the startup setting:\n{exc}",
                )
        self.accept()


def forget_secrets() -> None:
    for name in (SECRET_PASSWORD, SECRET_KEY_ID, SECRET_API_KEY):
        delete_secret(name)
