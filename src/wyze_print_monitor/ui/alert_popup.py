"""The pop-up alert: a card in the corner of the screen, above everything.

Windows notifications can be hidden by Do Not Disturb / Focus and fade
after a few seconds; this stays until the user responds. It shows the
snapshot and the same actions as the banner on the video, and it never
takes keyboard focus (you can keep typing wherever you were).
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget

from .binder import wire_alert_bar
from .views import VIEWS_QSS, AlertBar

WIDTH = 420
MARGIN = 16
PICTURE_MAX_H = 230  # a 16:9 camera frame at the card's width


class AlertPopup(QWidget):
    def __init__(self, main) -> None:
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus,
        )
        self.main = main
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("surface")
        self.setStyleSheet(VIEWS_QSS + "QWidget#surface { border: 1px solid #555; border-radius: 10px; }")
        self.setWindowTitle("Print watch alert")
        self.setFixedWidth(WIDTH)

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        head = QHBoxLayout()
        name = QLabel("Wyze Print Monitor · Print watch")
        name.setObjectName("dim")
        head.addWidget(name, 1)
        self.open_btn = QToolButton()
        self.open_btn.setText("Open")
        self.open_btn.setObjectName("flat")
        self.open_btn.setToolTip("Open the app")
        self.open_btn.clicked.connect(main.show_window)
        self.close_btn = QToolButton()
        self.close_btn.setText("✕")
        self.close_btn.setObjectName("flat")
        self.close_btn.setToolTip("Hide this pop-up (the alert stays in the app)")
        self.close_btn.clicked.connect(self.hide)
        head.addWidget(self.open_btn)
        head.addWidget(self.close_btn)
        column.addLayout(head)
        self.picture = QLabel()
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.hide()
        column.addWidget(self.picture)
        self.bar = AlertBar(self, compact=True)
        column.addWidget(self.bar)
        wire_alert_bar(self.bar, main)

        watch = main.print_watch
        watch.popup_requested.connect(self.show_alert)
        watch.alert_changed.connect(self._follow)
        self._silence = QTimer(self)
        self._silence.timeout.connect(self._sync_silence)

    # ------------------------------------------------------------------ alerts
    def show_alert(self, alert) -> None:
        self._fill(alert)
        self.adjustSize()
        self._place()
        self.show()
        self.raise_()
        self._silence.start(400)
        self._sync_silence()

    def _follow(self, alert) -> None:
        """Keep a shown pop-up in step with the alert (buttons, or gone)."""
        if alert is None:
            self.hide()
        elif self.isVisible():
            self._fill(alert)
            self.adjustSize()
            self._place()

    def _fill(self, alert) -> None:
        self.bar.show_alert(alert)
        pixmap = QPixmap(alert.snapshot) if alert.snapshot and os.path.exists(alert.snapshot) else QPixmap()
        if pixmap.isNull():
            self.picture.hide()
        else:
            self.picture.setPixmap(
                pixmap.scaled(WIDTH - 16, PICTURE_MAX_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.picture.show()

    def _place(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.right() - self.width() - MARGIN, area.bottom() - self.height() - MARGIN)

    def _sync_silence(self) -> None:
        playing = self.main.print_watch.alarm.playing
        if self.bar.silence_btn.isVisible() != playing:
            self.bar.silence_btn.setVisible(playing)
            self.adjustSize()
            self._place()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._silence.stop()
        super().hideEvent(event)
