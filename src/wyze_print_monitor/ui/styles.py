"""Dark theme in the design language of eufyMake Studio's Device tab.

Near-black app background, slightly lifted panel surfaces, full-width
section header bars ("Monitor" / "Control"), and eufyMake's medium green
as the single accent color.
"""

# eufyMake Studio Device-tab palette, sampled from the app.
BG_APP = "#141518"      # app background
BG_PANEL = "#1d1f22"    # panel surface
BG_HEADER = "#26282d"   # section header bar
BG_INPUT = "#24262a"
BORDER = "#33363b"
TEXT = "#d7d9dc"
TEXT_DIM = "#9a9ea5"
TEXT_HEADER = "#c9ccd1"
GREEN = "#6fbf5f"       # accent: buttons, toggles, active states
GREEN_DARK = "#4e8a44"
GREEN_TEXT = "#7cc47f"  # accent text on dark (Retract/Extrude style)
RED = "#8a2f2f"

DARK_QSS = f"""
QWidget {{
    background-color: {BG_APP};
    color: {TEXT};
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}}
QMainWindow::separator {{ background: {BORDER}; }}

/* Full-width section header bars, eufyMake "Monitor"/"Control" style. */
QLabel#paneHeader {{
    background-color: {BG_HEADER};
    color: {TEXT_HEADER};
    font-size: 14px;
    padding: 8px 12px;
    border: none;
}}

QGroupBox {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
    color: {TEXT_HEADER};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    background-color: transparent;
}}
QLabel {{ background: transparent; }}
QLabel#videoLabel {{
    background-color: #000;
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QLabel#statusPill {{
    border-radius: 10px;
    padding: 3px 10px;
    font-weight: 600;
}}
QPushButton {{
    background-color: #2e3136;
    border: 1px solid #3d4148;
    border-radius: 6px;
    padding: 7px 12px;
}}
QPushButton:hover {{ background-color: #3a3e44; border-color: #4a4f57; }}
QPushButton:pressed {{ background-color: #26292d; }}
QPushButton:disabled {{ color: #6b6f76; background-color: #24262a; }}
QPushButton#accentButton {{
    background-color: {GREEN};
    border-color: {GREEN};
    color: #10240f;
    font-weight: 700;
}}
QPushButton#accentButton:hover {{ background-color: {GREEN_TEXT}; }}
QPushButton#accentButton:checked {{ background-color: {GREEN_DARK}; color: #ffffff; }}
QPushButton#dangerButton {{
    background-color: {RED};
    border-color: {RED};
    color: #ffffff;
}}
QPushButton#dangerButton:hover {{ background-color: #a03838; }}
QPushButton#toggleOn {{
    background-color: {GREEN};
    border-color: {GREEN};
    color: #10240f;
    font-weight: 700;
}}
QLineEdit, QComboBox, QSpinBox {{
    background-color: {BG_INPUT};
    border: 1px solid #3d4148;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {GREEN_DARK};
}}
QComboBox QAbstractItemView {{
    background-color: {BG_INPUT};
    border: 1px solid #3d4148;
    selection-background-color: {GREEN_DARK};
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid #3d4148;
    border-radius: 4px;
    background: {BG_INPUT};
}}
QCheckBox::indicator:checked {{ background: {GREEN}; border-color: {GREEN}; }}
QStatusBar {{ background-color: {BG_APP}; color: {TEXT_DIM}; }}
QMenuBar {{ background-color: {BG_APP}; }}
QMenuBar::item:selected {{ background: #2e3136; }}
QMenu {{ background-color: {BG_INPUT}; border: 1px solid #3d4148; }}
QMenu::item:selected {{ background-color: {GREEN_DARK}; }}
QToolTip {{ background-color: {BG_INPUT}; color: {TEXT}; border: 1px solid #3d4148; }}
QScrollArea {{ border: none; background-color: {BG_APP}; }}
QScrollBar:vertical {{ background: {BG_APP}; width: 10px; }}
QScrollBar::handle:vertical {{ background: #3d4148; border-radius: 5px; min-height: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

/* eufyMake-style view tab bar ("Monitor" active, green underline). */
QTabBar {{ background: {BG_APP}; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    font-size: 14px;
    padding: 10px 28px;
    margin: 0 8px;
    border: none;
}}
QTabBar::tab:selected {{
    color: {GREEN_TEXT};
    border-bottom: 2px solid {GREEN};
}}
QTabBar::tab:!selected:hover {{ color: {TEXT}; }}

/* Left device sidebar, eufyMake "My Printer" style. */
QListWidget#cameraList {{
    background: {BG_PANEL};
    border: none;
    outline: none;
}}
QListWidget#cameraList::item {{
    padding: 10px 12px;
    border: none;
    border-left: 3px solid transparent;
}}
QListWidget#cameraList::item:hover {{ background: {BG_HEADER}; }}
QListWidget#cameraList::item:selected {{
    background: rgba(111, 191, 95, 0.16);
    color: {TEXT};
    border-left: 3px solid {GREEN};
}}

/* Big readout cards, eufyMake temperature-card style. */
QFrame#statCard {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QLabel#statValue {{
    background: transparent;
    font-size: 26px;
    font-weight: 700;
    color: #e8eaec;
}}
QLabel#statCaption {{
    background: transparent;
    font-size: 12px;
    color: {TEXT_DIM};
}}

/* Thin video info bar under the picture, eufyMake player-bar style. */
QWidget#playerBar {{
    background: {BG_HEADER};
    border: none;
}}
QLabel#sessionValue {{ color: {TEXT}; font-weight: 600; }}
QLabel#sessionCaption {{ color: {TEXT_DIM}; }}
"""
