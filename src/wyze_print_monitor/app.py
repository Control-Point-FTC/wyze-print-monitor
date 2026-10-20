"""Application entry point."""
from __future__ import annotations

import getpass
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .ui.main_window import MainWindow
from .ui.styles import DARK_QSS


ICON_PATH = Path(__file__).parent / "assets" / "icon.png"
APP_USER_MODEL_ID = "ControlPointFTC.WyzePrintMonitor"
INSTALLER_MUTEX = "WyzePrintMonitorRunning"  # must match AppMutex in installer/*.iss


def app_icon() -> QIcon:
    """The app logo, or a green camera glyph if the asset is missing."""
    if ICON_PATH.is_file():
        icon = QIcon(str(ICON_PATH))
        if not icon.isNull():
            return icon
    from .ui.icons import ICON_CAMERA, glyph_icon

    return glyph_icon(ICON_CAMERA, "#62d361", 32)


def _set_windows_app_id() -> None:
    """Give the process its own taskbar identity, so Windows shows our icon
    (and groups our windows) instead of python.exe's."""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass


def _instance_name() -> str:
    return f"WyzePrintMonitor-{getpass.getuser()}"


def _signal_running_instance() -> bool:
    """If the app is already running, ask it to come forward. True if so."""
    socket = QLocalSocket()
    socket.connectToServer(_instance_name())
    if not socket.waitForConnected(500):
        return False
    socket.write(b"show")
    socket.flush()
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def _listen_for_other_launches(app: QApplication, window: MainWindow) -> QLocalServer:
    """Opening the app again (Start menu, desktop icon) brings this one up
    instead of starting a second copy that would fight over the camera."""
    server = QLocalServer(app)
    QLocalServer.removeServer(_instance_name())
    server.listen(_instance_name())

    def on_connection() -> None:
        connection = server.nextPendingConnection()
        if connection is not None:
            connection.disconnected.connect(connection.deleteLater)
        window.show_window()

    server.newConnection.connect(on_connection)
    return server


def _hold_installer_mutex():
    """A named mutex the installer's AppMutex checks, so setup/uninstall
    knows the app is running and closes it first."""
    try:
        import ctypes

        return ctypes.windll.kernel32.CreateMutexW(None, False, INSTALLER_MUTEX)
    except (AttributeError, OSError):
        return None


def _make_tray(app: QApplication, window: MainWindow) -> QSystemTrayIcon | None:
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(app.windowIcon(), app)
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
    window.update_manager.available.connect(
        lambda info: tray.showMessage(
            "Update available",
            f"Wyze Print Monitor {info.version} is ready to install. Click Update in the app.",
            QSystemTrayIcon.Information,
            8000,
        )
    )
    tray.messageClicked.connect(window.update_manager.install)
    return tray


def self_test(report_path: str) -> int:
    """Check a packaged build can do its job, without opening a window.

    ``WyzePrintMonitor.exe --self-test report.txt`` writes what it found and
    exits 0 only if video decoding, the OS credential store, Qt networking,
    the Wyze client and the app icon are all usable. Run by the release
    workflow on every build.
    """
    from . import __version__

    lines = [f"Wyze Print Monitor {__version__}", f"frozen: {bool(getattr(sys, 'frozen', False))}"]
    ok = True

    def check(label: str, fn) -> None:
        nonlocal ok
        try:
            result, good = fn()
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            result, good = f"{type(exc).__name__}: {exc}", False
        lines.append(f"{'OK  ' if good else 'FAIL'} {label}: {result}")
        ok = ok and good

    def opencv():
        import cv2

        has_ffmpeg = cv2.videoio_registry.hasBackend(cv2.CAP_FFMPEG)
        return f"{cv2.__version__}, FFmpeg backend {'present' if has_ffmpeg else 'MISSING'}", has_ffmpeg

    def credentials():
        import keyring

        backend = keyring.get_keyring()
        name = f"{type(backend).__module__}.{type(backend).__name__}"
        return name, "fail" not in name and "null" not in name.lower()

    def qt():
        import PySide6
        from PySide6.QtNetwork import QLocalServer  # noqa: F401

        return PySide6.__version__, True

    def wyze():
        import wyzeapy  # noqa: F401

        from .wyze_control import WyzeController  # noqa: F401

        return "wyzeapy importable", True

    check("OpenCV", opencv)
    check("Credential store", credentials)
    check("Qt", qt)
    check("Wyze client", wyze)
    check("App icon", lambda: (str(ICON_PATH), ICON_PATH.is_file()))
    lines.append("RESULT: " + ("PASS" if ok else "FAIL"))
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0 if ok else 1


def main() -> int:
    if "--self-test" in sys.argv:
        index = sys.argv.index("--self-test")
        report = sys.argv[index + 1] if len(sys.argv) > index + 1 else "self-test.txt"
        return self_test(report)
    if sys.platform == "win32":
        _set_windows_app_id()  # must happen before any window exists
    app = QApplication(sys.argv)
    app.setApplicationName("Wyze Print Monitor")
    app.setOrganizationName("Control-Point-FTC")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(DARK_QSS)
    if _signal_running_instance():
        return 0
    mutex = _hold_installer_mutex() if sys.platform == "win32" else None  # noqa: F841 - held for the app's lifetime
    window = MainWindow()
    server = _listen_for_other_launches(app, window)  # noqa: F841 - kept alive by app parent

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
