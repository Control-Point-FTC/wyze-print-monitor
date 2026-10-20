"""Icons drawn from Windows' built-in icon font (no image assets needed).

Segoe Fluent Icons ships with Windows 11, Segoe MDL2 Assets with Windows 10;
elsewhere the icons are simply empty and buttons fall back to their text.
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPixmap

ICON_CAMERA = chr(0xE722)
ICON_RECORD = chr(0xE7C8)
ICON_TIMER = chr(0xE916)
ICON_FOLDER = chr(0xE838)
ICON_FULLSCREEN = chr(0xE740)
ICON_WINDOW = chr(0xE8A7)
ICON_SETTINGS = chr(0xE713)
ICON_ADJUST = chr(0xE706)  # brightness
ICON_ROTATE_LEFT = chr(0xE7AD)
ICON_ROTATE_RIGHT = chr(0xE7AD)  # same glyph, mirrored when drawn
ICON_RESET = chr(0xE72C)  # refresh arrow
ICON_POWER = chr(0xE7E8)
ICON_SIREN = chr(0xE789)  # megaphone
ICON_LIGHT = chr(0xEA80)  # lightbulb
ICON_MOTION = chr(0xE805)  # walking figure
ICON_BELL = chr(0xEA8F)
ICON_WATCH = chr(0xE890)  # eye
ICON_FIT = chr(0xE9A6)
ICON_CLOSE = chr(0xE711)
ICON_VIDEO = chr(0xE714)
ICON_PHOTO = chr(0xEB9F)

_family: str | None = None


def icon_font_family() -> str:
    global _family
    if _family is None:
        families = set(QFontDatabase.families())
        _family = next((f for f in ("Segoe Fluent Icons", "Segoe MDL2 Assets") if f in families), "")
    return _family


def glyph_icon(glyph: str, color: str = "#e6e7e9", size: int = 16, mirror: bool = False) -> QIcon:
    """Render an icon-font glyph into a QIcon (empty icon if no icon font)."""
    family = icon_font_family()
    if not family:
        return QIcon()
    ratio = 2  # render at 2x so it stays crisp at 125-200% scaling
    pix = QPixmap(size * ratio, size * ratio)
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    if mirror:
        painter.translate(size, 0)
        painter.scale(-1, 1)
    font = QFont(family)
    font.setPixelSize(size - 2)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(QRect(0, 0, size, size), Qt.AlignCenter, glyph)
    painter.end()
    return QIcon(pix)


# Shown instead when the icon font is missing (Linux/macOS), so an
# icon-only button never renders blank.
FALLBACK_TEXT = {
    ICON_CAMERA: "Snapshot",
    ICON_RECORD: "Record",
    ICON_TIMER: "Timelapse",
    ICON_FOLDER: "Folders",
    ICON_FULLSCREEN: "Fullscreen",
    ICON_WINDOW: "Window",
    ICON_SETTINGS: "Settings",
    ICON_ADJUST: "Adjust",
    ICON_FIT: "Fit",
    ICON_RESET: "Refresh",
    ICON_POWER: "Power",
}


def tool_button(glyph: str, text: str, tip: str, checkable: bool = False):
    """A flat toolbar button: icon (+ optional text), or text alone when the
    icon font isn't available."""
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QToolButton

    button = QToolButton()
    icon = glyph_icon(glyph)
    if icon.isNull():
        button.setText(text or FALLBACK_TEXT.get(glyph, tip))
        button.setToolButtonStyle(Qt.ToolButtonTextOnly)
    else:
        button.setIcon(icon)
        button.setIconSize(QSize(16, 16))
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if text else Qt.ToolButtonIconOnly)
    button.setToolTip(tip)
    button.setCheckable(checkable)
    button.setCursor(Qt.PointingHandCursor)
    return button
