"""Entry point PyInstaller freezes into WyzePrintMonitor.exe.

Kept tiny and import-light on purpose: an update replaces the app's files,
and if the app is opened while that's happening, the heavy imports (Qt...)
would fail with a confusing traceback. So first check whether Setup is
running, and turn a failed import into a plain message.
"""
import sys

# Must match SetupMutex in installer/wyze-print-monitor.iss.
SETUP_MUTEX = "WyzePrintMonitorSetup"
RELEASES_URL = "https://github.com/ZOGWORK/wyze-print-monitor/releases/latest"


def _message(text: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, "Wyze Print Monitor", 0x40)  # MB_ICONINFORMATION
    except Exception:  # noqa: BLE001 - nothing else we can do
        print(text, file=sys.stderr)


def setup_running() -> bool:
    """True while the installer (an update) is running."""
    if sys.platform != "win32":
        return False
    import ctypes

    synchronize = 0x00100000
    handle = ctypes.windll.kernel32.OpenMutexW(synchronize, False, SETUP_MUTEX)
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def run() -> int:
    try:
        updating = setup_running()
    except Exception:  # noqa: BLE001 - e.g. _ctypes itself mid-replacement
        updating = True
    if updating:
        _message("Wyze Print Monitor is being updated.\n\nIt will open by itself in a moment, when the update finishes.")
        return 0
    try:
        from wyze_print_monitor.app import main
    except ImportError as exc:
        _message(
            "Wyze Print Monitor couldn't start: some of its files are missing.\n\n"
            "If an update just ran, wait a minute and open it again. If this keeps "
            f"happening, reinstall it from:\n{RELEASES_URL}\n\n({exc})"
        )
        return 1
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
