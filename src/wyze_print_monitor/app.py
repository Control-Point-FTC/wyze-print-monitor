"""Application entry point."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .ui.main_window import MainWindow
from .ui.styles import DARK_QSS


def _make_tray(app: QApplication, window: MainWindow) -> QSystemTrayIcon | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    from .ui.studio_dock import ICON_CAMERA, glyph_icon

    tray = QSystemTrayIcon(glyph_icon(ICON_CAMERA, "#62d361", 32), app)
    tray.setToolTip("Wyze Print Monitor")
    menu = QMenu()
    menu.addAction("Open Wyze Print Monitor", window.show_window)
    menu.addAction("Settings…", window._open_settings)
    menu.addSeparator()
    menu.addAction("Exit", window.quit_app)
    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: window.show_window()
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick)
        else None
    )
    tray._menu = menu  # keep the menu alive with the tray
    tray.show()
    return tray


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Wyze Print Monitor")
    app.setOrganizationName("Control-Point-FTC")
    app.setStyleSheet(DARK_QSS)
    window = MainWindow()

    dock = None
    if sys.platform == "win32":
        from .ui.studio_dock import StudioDock

        # The panels live inside eufyMake Studio's Device tab; this window and
        # the tray icon are the way back to the full app.
        dock = StudioDock(window)
        app.setQuitOnLastWindowClosed(False)
        window._tray = _make_tray(app, window)

    if dock is not None and window.settings.dock_in_studio and dock.studio_running():
        window._status("Showing the camera inside eufyMake Studio's Device tab.", 5000)
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
