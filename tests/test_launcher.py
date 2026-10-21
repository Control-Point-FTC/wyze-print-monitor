"""The frozen app's launcher: never start (or crash) mid-update."""
import importlib.util
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).parents[1]


def _launcher():
    spec = importlib.util.spec_from_file_location("launcher", ROOT / "packaging" / "launcher.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_setup_mutex_matches_the_installer():
    iss = (ROOT / "installer" / "wyze-print-monitor.iss").read_text(encoding="utf-8")
    name = re.search(r'#define SetupMutexName "([^"]+)"', iss).group(1)
    assert name == _launcher().SETUP_MUTEX
    assert "SetupMutex={#SetupMutexName}" in iss


@pytest.mark.skipif(sys.platform != "win32", reason="Windows named mutexes")
def test_detects_a_running_setup():
    import ctypes

    launcher = _launcher()
    assert launcher.setup_running() is False
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, launcher.SETUP_MUTEX)
    try:
        assert launcher.setup_running() is True
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
    assert launcher.setup_running() is False


def test_mid_update_launch_says_so_instead_of_starting(monkeypatch):
    launcher = _launcher()
    shown = []
    monkeypatch.setattr(launcher, "setup_running", lambda: True)
    monkeypatch.setattr(launcher, "_message", shown.append)
    assert launcher.run() == 0
    assert "being updated" in shown[0]


def test_missing_files_give_a_plain_message(monkeypatch):
    launcher = _launcher()
    shown = []
    monkeypatch.setattr(launcher, "setup_running", lambda: False)
    monkeypatch.setattr(launcher, "_message", shown.append)
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def broken(name, *args, **kwargs):
        if name == "wyze_print_monitor.app":
            raise ImportError("shiboken6 does not exist")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", broken)
    assert launcher.run() == 1
    assert "files are missing" in shown[0] and "releases" in shown[0]


def test_updates_show_progress():
    from wyze_print_monitor.updater import INSTALLER_ARGS

    assert "/SILENT" in INSTALLER_ARGS and "/VERYSILENT" not in INSTALLER_ARGS
