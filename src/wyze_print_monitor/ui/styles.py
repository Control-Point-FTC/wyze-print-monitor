"""Dark theme stylesheet (in the spirit of eufyMake Studio's Device tab)."""

DARK_QSS = """
QWidget {
    background-color: #1b1d20;
    color: #d7d9dc;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow::separator { background: #2a2d31; }
QGroupBox {
    border: 1px solid #33363b;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 8px;
    font-weight: 600;
    color: #e8eaed;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QLabel { background: transparent; }
QLabel#videoLabel {
    background-color: #000;
    border: 1px solid #33363b;
    border-radius: 6px;
}
QLabel#statusPill {
    border-radius: 10px;
    padding: 3px 10px;
    font-weight: 600;
}
QPushButton {
    background-color: #2e3136;
    border: 1px solid #3d4148;
    border-radius: 6px;
    padding: 7px 12px;
}
QPushButton:hover { background-color: #3a3e44; border-color: #4a4f57; }
QPushButton:pressed { background-color: #26292d; }
QPushButton:disabled { color: #6b6f76; background-color: #24262a; }
QPushButton#accentButton {
    background-color: #2f7d3a;
    border-color: #2f7d3a;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#accentButton:hover { background-color: #379045; }
QPushButton#accentButton:checked { background-color: #1f5c28; }
QPushButton#dangerButton {
    background-color: #8a2f2f;
    border-color: #8a2f2f;
    color: #ffffff;
}
QPushButton#dangerButton:hover { background-color: #a03838; }
QPushButton#toggleOn {
    background-color: #2f7d3a;
    border-color: #2f7d3a;
    color: #ffffff;
    font-weight: 600;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #24262a;
    border: 1px solid #3d4148;
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: #2f7d3a;
}
QComboBox QAbstractItemView {
    background-color: #24262a;
    border: 1px solid #3d4148;
    selection-background-color: #2f7d3a;
}
QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid #3d4148;
    border-radius: 4px;
    background: #24262a;
}
QCheckBox::indicator:checked { background: #2f7d3a; border-color: #2f7d3a; }
QStatusBar { background-color: #141518; color: #9a9ea5; }
QMenuBar { background-color: #141518; }
QMenuBar::item:selected { background: #2e3136; }
QMenu { background-color: #24262a; border: 1px solid #3d4148; }
QMenu::item:selected { background-color: #2f7d3a; }
QToolTip { background-color: #24262a; color: #d7d9dc; border: 1px solid #3d4148; }
QScrollBar:vertical { background: #1b1d20; width: 10px; }
QScrollBar::handle:vertical { background: #3d4148; border-radius: 5px; min-height: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
