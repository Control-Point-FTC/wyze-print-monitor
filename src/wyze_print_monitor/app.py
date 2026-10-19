"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow
from .ui.styles import DARK_QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Wyze Print Monitor")
    app.setOrganizationName("Control-Point-FTC")
    app.setStyleSheet(DARK_QSS)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
