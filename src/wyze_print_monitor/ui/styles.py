"""Dark theme in the design language of eufyMake Studio's Device tab.

Colors are sampled from the running Studio app so the full window and the
panels docked inside Studio look the same: near-black app background,
#292a2d cards separated by gaps, thin dividers, and Studio's green accent
(dark-green buttons with green text, like its Retract / Extrude buttons).

Widgets are transparent by default; only containers (window, cards,
dialogs, menus, inputs) paint a background. That keeps every control
sitting cleanly on the card it lives in.
"""

# eufyMake Studio palette, sampled from the app.
APP_BG = "#18191b"       # window background / gaps between cards
CARD = "#292a2d"         # card surface (Monitor, Control, Others…)
DIVIDER = "#3e3f42"      # header underline, separators
INPUT_BG = "#1f2023"
VIDEO_BG = "#000000"
TEXT = "#e6e7e9"
TEXT_DIM = "#9ea1a6"
TEXT_FAINT = "#63666b"
GREEN = "#62d361"        # accent (Start Printing)
GREEN_BTN = "#263229"    # Retract / Extrude button fill
GREEN_BTN_HOVER = "#2e3d31"
SELECTED = "#354138"     # selected row (My Printer list)
RED = "#e05a5a"
AMBER = "#e0a84a"

# Status chip colors (background, text).
CHIP_LIVE = ("#2f7d3a", "#ffffff")
CHIP_BUSY = ("#8a6d2f", "#ffffff")
CHIP_ERROR = ("#8a2f2f", "#ffffff")
CHIP_IDLE = ("#3d4148", "#d7d9dc")

SLIDER_QSS = f"""
QSlider::groove:horizontal {{ height: 4px; background: {DIVIDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {GREEN}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: #ffffff; }}
QSlider::groove:horizontal:disabled {{ background: #34363a; }}
QSlider::sub-page:horizontal:disabled {{ background: #3f5a40; }}
QSlider::handle:horizontal:disabled {{ background: {TEXT_FAINT}; }}
"""

DARK_QSS = f"""
QWidget {{
    background: transparent;
    color: {TEXT};
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{ background: {APP_BG}; }}
QStatusBar {{ background: {APP_BG}; color: {TEXT_DIM}; }}
QStatusBar::item {{ border: none; }}
QMenuBar {{ background: {APP_BG}; }}
QMenuBar::item {{ padding: 4px 10px; }}
QMenuBar::item:selected {{ background: {CARD}; }}
QMenu {{ background: {CARD}; border: 1px solid {DIVIDER}; padding: 4px 0; }}
QMenu::item {{ padding: 5px 22px; }}
QMenu::item:selected {{ background: {SELECTED}; }}
QMenu::separator {{ height: 1px; background: {DIVIDER}; margin: 4px 8px; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {DIVIDER}; padding: 4px; }}

/* Cards: Studio's panels. Header bar + divider, body below. */
QFrame#card {{ background: {CARD}; border: none; }}
QWidget#cardHeader {{ border-bottom: 1px solid {DIVIDER}; }}
QLabel#cardTitle {{ font-size: 15px; }}
QLabel#section {{ color: {TEXT_DIM}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
QLabel#dim {{ color: {TEXT_DIM}; }}
QLabel#chip, QLabel#statusPill {{
    border-radius: 11px; padding: 0 10px; min-height: 22px; font-size: 11px; font-weight: 600;
}}

/* Monitor picture + toolbar under it. */
QLabel#videoLabel {{ background: {VIDEO_BG}; color: {TEXT_DIM}; font-size: 14px; }}
QWidget#toolbar {{ border-top: 1px solid {DIVIDER}; }}
QToolButton {{ border: none; border-radius: 4px; padding: 4px 8px; }}
QToolButton:hover {{ background: #34363a; }}
QToolButton:checked {{ background: {SELECTED}; color: {GREEN}; }}
QToolButton:disabled {{ color: {TEXT_FAINT}; }}
QToolButton::menu-indicator {{ image: none; width: 0; }}

/* Buttons: Studio's dark-green style; the primary one is solid green. */
QPushButton {{
    background: {GREEN_BTN}; color: {GREEN}; border: none; border-radius: 6px;
    padding: 7px 12px; min-height: 18px;
}}
QPushButton:hover {{ background: {GREEN_BTN_HOVER}; }}
QPushButton:checked {{ background: {GREEN}; color: #10240f; }}
QPushButton:disabled {{ background: #2f3033; color: {TEXT_FAINT}; }}
QPushButton#accentButton {{ background: {GREEN}; color: #10240f; font-weight: 600; }}
QPushButton#accentButton:hover {{ background: #74dc73; }}
QPushButton#danger {{ background: #6b2a2a; color: #ffd6d6; }}
QPushButton#danger:hover {{ background: #803232; }}
QPushButton#danger:checked {{ background: {RED}; color: #2a0f0f; }}
QPushButton#danger:disabled {{ background: #2f3033; color: {TEXT_FAINT}; }}
QPushButton#plain {{ background: #34363a; color: {TEXT}; }}
QPushButton#plain:hover {{ background: #3d4044; }}
QPushButton#plain:checked {{ background: {SELECTED}; color: {GREEN}; }}

QLineEdit, QComboBox, QSpinBox {{
    background: {INPUT_BG}; border: 1px solid {DIVIDER}; border-radius: 6px;
    padding: 5px 8px; selection-background-color: {SELECTED};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {GREEN}; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {DIVIDER}; selection-background-color: {SELECTED};
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 3px;
    border: 1px solid #5d6066; background: {APP_BG};
}}
QCheckBox::indicator:checked {{ background: {GREEN}; border-color: {GREEN}; }}
QCheckBox:disabled {{ color: {TEXT_FAINT}; }}

QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #4a4d52; border-radius: 3px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

/* Camera / Image tabs in the right card. */
QTabWidget::pane {{ border: none; border-top: 1px solid {DIVIDER}; }}
QTabBar::tab {{
    background: transparent; color: {TEXT_DIM}; padding: 8px 16px; border: none;
    border-bottom: 2px solid transparent; font-size: 14px;
}}
QTabBar::tab:selected {{ color: {GREEN}; border-bottom: 2px solid {GREEN}; }}
QTabBar::tab:!selected:hover {{ color: {TEXT}; }}

/* "My Camera" list, Studio "My Printer" style. */
QListWidget#cameraList {{ border: none; outline: none; }}
QListWidget#cameraList::item {{ padding: 10px 12px; border: none; }}
QListWidget#cameraList::item:hover {{ background: #303134; }}
QListWidget#cameraList::item:selected {{ background: {SELECTED}; color: {TEXT}; }}

/* Big readouts, Studio temperature style. */
QLabel#statValue {{ font-size: 28px; font-weight: 700; color: {TEXT}; }}
QLabel#statCaption {{ font-size: 12px; color: {TEXT_DIM}; }}
QLabel#sessionValue {{ font-weight: 600; }}
QLabel#sessionCaption {{ color: {TEXT_DIM}; }}
""" + SLIDER_QSS


# Overlay pills on the video (status chips, zoom, AI...): one look for all —
# a see-through dark pill; status is only ever a small colored dot.
PILL_BG = "rgba(20, 21, 23, 200)"
PILL_BG_HOVER = "rgba(60, 62, 66, 220)"
PILL_TEXT = "#e6e7e9"
DOT_GREEN = "#62d361"
DOT_AMBER = "#e0a040"
DOT_RED = "#e8574a"
DOT_BLUE = "#6f9cf0"
DOT_GREY = "#8b8f95"


def checkmark_qss(folder: str) -> str:
    """Stylesheet rule giving checked boxes a real check mark (drawn once
    into ``folder``; Qt stylesheets can only use image files). Returns ""
    if it can't be written: boxes then fall back to a solid green fill."""
    import os

    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

    path = os.path.join(folder, "check.png")
    try:
        os.makedirs(folder, exist_ok=True)
        image = QImage(32, 32, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor("#10240f"), 4.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        tick = QPainterPath(QPointF(7.5, 16.5))
        tick.lineTo(13.5, 22.5)
        tick.lineTo(24.5, 10.0)
        painter.drawPath(tick)
        painter.end()
        if not image.save(path):
            return ""
    except OSError:
        return ""
    url = path.replace("\\", "/")
    return f'QCheckBox::indicator:checked {{ image: url("{url}"); }}\n'
