"""Launch-at-startup support.

Windows: a value under HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run
(per-user, no admin rights needed). Linux: an XDG autostart ``.desktop`` file.
macOS is not implemented yet and raises :class:`NotImplementedError` honestly
instead of pretending.
"""
from __future__ import annotations

import os
import shutil
import sys

APP_NAME = "Wyze Print Monitor"
RUN_VALUE_NAME = "WyzePrintMonitor"


def supported() -> bool:
    """Whether autostart can be managed on this platform."""
    return os.name == "nt" or sys.platform.startswith("linux")


def launch_command() -> str:
    """Quoted command line registered for autostart."""
    if getattr(sys, "frozen", False):
        # Installed build (PyInstaller): the app is its own executable.
        return f'"{sys.executable}"'
    exe = shutil.which("wyze-print-monitor")
    if exe:
        return f'"{exe}"'
    # Fallback: the package is installed (pip install -e .), run as a module.
    return f'"{sys.executable}" -m wyze_print_monitor'


def is_enabled() -> bool:
    if os.name == "nt":
        return _windows_is_enabled()
    if sys.platform.startswith("linux"):
        return os.path.isfile(_linux_desktop_path())
    raise NotImplementedError("Autostart is not implemented on this platform.")


def set_enabled(enabled: bool) -> None:
    if os.name == "nt":
        if enabled:
            _windows_enable()
        else:
            _windows_disable()
    elif sys.platform.startswith("linux"):
        if enabled:
            _linux_enable()
        else:
            _linux_disable()
    else:
        raise NotImplementedError("Autostart is not implemented on this platform.")


# ------------------------------------------------------------------ Windows
def _windows_run_key(access: int, create: bool = False):
    import winreg

    opener = winreg.CreateKeyEx if create else winreg.OpenKey
    return opener(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        access,
    )


def _windows_is_enabled() -> bool:
    import winreg

    try:
        with _windows_run_key(winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False


def _windows_enable() -> None:
    import winreg

    # CreateKeyEx (not OpenKey): the per-user Run key may not exist yet on a
    # fresh profile, and enable must work there too.
    with _windows_run_key(winreg.KEY_SET_VALUE, create=True) as key:
        winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, launch_command())


def _windows_disable() -> None:
    import winreg

    try:
        with _windows_run_key(winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        pass


# ------------------------------------------------------------------ Linux
def _linux_desktop_path() -> str:
    # Honor XDG_CONFIG_HOME: the desktop session reads autostart entries from
    # there when it is set, not from ~/.config.
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(config_home, "autostart", "wyze-print-monitor.desktop")


def build_desktop_entry(exec_cmd: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={exec_cmd}\n"
        "X-GNOME-Autostart-enabled=true\n"
        "NoDisplay=false\n"
    )


def _linux_enable() -> None:
    path = _linux_desktop_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build_desktop_entry(launch_command()))


def _linux_disable() -> None:
    try:
        os.remove(_linux_desktop_path())
    except FileNotFoundError:
        pass
