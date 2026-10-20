"""Picture adjustment controls (brightness, exposure, zoom, rotate…).

One panel class, used in two places: the full window's "Image" tab and the
popup behind the Studio dock's Adjust button. Every panel edits the same
:class:`MainWindow` state through ``set_adjustments`` and re-syncs from its
``adjustments_changed`` signal, so they always agree. Changes apply to the
live stream immediately (see ``capture.StreamReader.adjustments``).
"""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..adjust import IDENTITY, ImageAdjustments
from .styles import SLIDER_QSS, TEXT_DIM

# field, label, slider min, slider max, slider→value scale, display format
TONE_ROWS = (
    ("brightness", "Brightness", -100, 100, 1, "{:+.0f}"),
    ("contrast", "Contrast", -100, 100, 1, "{:+.0f}"),
    ("exposure", "Exposure", -20, 20, 10, "{:+.1f} EV"),
    ("gamma", "Gamma", 40, 250, 100, "{:.2f}"),
    ("saturation", "Saturation", -100, 100, 1, "{:+.0f}"),
    ("temperature", "Warmth", -100, 100, 1, "{:+.0f}"),
    ("sharpness", "Sharpness", 0, 100, 1, "{:.0f}"),
)
LABEL_WIDTH = 78
ZOOM_ROWS = (
    ("zoom", "Zoom", 100, 400, 100, "{:.1f}×"),
    ("pan_x", "Pan ←→", -100, 100, 100, "{:+.2f}"),
    ("pan_y", "Pan ↑↓", -100, 100, 100, "{:+.2f}"),
)


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("section")
    label.setStyleSheet(
        f"color: {TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;"
    )
    return label


class ImageAdjustPanel(QWidget):
    def __init__(self, main, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.main = main
        self.setStyleSheet(SLIDER_QSS)
        self._sliders: dict[str, tuple[QSlider, QLabel, float, str]] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        layout.addWidget(_section("PICTURE"))
        layout.addLayout(self._slider_grid(TONE_ROWS))

        layout.addSpacing(4)
        layout.addWidget(_section("ORIENTATION"))
        orient = QHBoxLayout()
        orient.setSpacing(6)
        self.rotate_left_btn = QPushButton("⟲ 90°")
        self.rotate_right_btn = QPushButton("⟳ 90°")
        self.flip_h_btn = QPushButton("Flip ↔")
        self.flip_v_btn = QPushButton("Flip ↕")
        for button in (self.rotate_left_btn, self.rotate_right_btn, self.flip_h_btn, self.flip_v_btn):
            button.setObjectName("plain")
            orient.addWidget(button)
        self.flip_h_btn.setCheckable(True)
        self.flip_v_btn.setCheckable(True)
        self.rotate_left_btn.setToolTip("Rotate counter-clockwise")
        self.rotate_right_btn.setToolTip("Rotate clockwise")
        self.rotate_left_btn.clicked.connect(lambda: self._rotate(-90))
        self.rotate_right_btn.clicked.connect(lambda: self._rotate(90))
        self.flip_h_btn.clicked.connect(self._changed)
        self.flip_v_btn.clicked.connect(self._changed)
        layout.addLayout(orient)
        self.rotation_label = QLabel()
        self.rotation_label.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        layout.addWidget(self.rotation_label)

        layout.addSpacing(4)
        layout.addWidget(_section("DIGITAL ZOOM"))
        layout.addLayout(self._slider_grid(ZOOM_ROWS))

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.reset_btn = QPushButton("Reset all")
        self.reset_btn.setObjectName("plain")
        self.reset_btn.setToolTip("Back to the camera's original picture")
        self.reset_btn.clicked.connect(lambda: self.main.set_adjustments(IDENTITY))
        footer.addWidget(self.reset_btn)
        layout.addSpacing(4)
        layout.addLayout(footer)
        layout.addStretch(1)

        main.adjustments_changed.connect(self.refresh)
        self.refresh(main.adjustments)

    # ------------------------------------------------------------------ build
    def _slider_grid(self, rows) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(1, 1)
        for row, (name, text, lo, hi, scale, fmt) in enumerate(rows):
            label = QLabel(text)
            label.setFixedWidth(LABEL_WIDTH)  # same column in every grid
            slider = QSlider(Qt.Horizontal)
            slider.setRange(lo, hi)
            slider.setPageStep(max((hi - lo) // 20, 1))
            slider.setToolTip("Double-click the value to reset")
            value = QLabel()
            value.setMinimumWidth(56)
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            value.setStyleSheet(f"color: {TEXT_DIM};")
            value.mouseDoubleClickEvent = lambda _e, n=name: self._reset_one(n)
            slider.valueChanged.connect(self._changed)
            grid.addWidget(label, row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(value, row, 2)
            self._sliders[name] = (slider, value, scale, fmt)
        return grid

    # ------------------------------------------------------------------ sync
    def current(self) -> ImageAdjustments:
        values = {name: slider.value() / scale for name, (slider, _v, scale, _f) in self._sliders.items()}
        for name in ("brightness", "contrast", "saturation", "temperature", "sharpness"):
            values[name] = int(values[name])
        return replace(
            self.main.adjustments,
            **values,
            flip_h=self.flip_h_btn.isChecked(),
            flip_v=self.flip_v_btn.isChecked(),
        )

    def refresh(self, adj: ImageAdjustments) -> None:
        """Show ``adj`` without echoing a change back."""
        for name, (slider, value, scale, fmt) in self._sliders.items():
            number = getattr(adj, name)
            slider.blockSignals(True)
            slider.setValue(round(number * scale))
            slider.blockSignals(False)
            value.setText(fmt.format(number))
        for button, checked in ((self.flip_h_btn, adj.flip_h), (self.flip_v_btn, adj.flip_v)):
            button.blockSignals(True)
            button.setChecked(checked)
            button.blockSignals(False)
        self.rotation_label.setText(f"Rotation: {adj.rotation}°")
        zoomed = adj.zoom > 1.0
        for name in ("pan_x", "pan_y"):
            self._sliders[name][0].setEnabled(zoomed)
        self.reset_btn.setEnabled(not adj.is_identity())

    def _changed(self) -> None:
        self.main.set_adjustments(self.current())
        # Values the main window rejected as unchanged still need labels.
        self.refresh(self.main.adjustments)

    def _rotate(self, degrees: int) -> None:
        adj = self.main.adjustments
        self.main.set_adjustments(replace(adj, rotation=(adj.rotation + degrees) % 360))

    def _reset_one(self, name: str) -> None:
        self.main.set_adjustments(replace(self.main.adjustments, **{name: getattr(IDENTITY, name)}))
