"""Tests for autostart helpers (no registry/filesystem side effects)."""
import sys

import pytest

from wyze_print_monitor import autostart


def test_build_desktop_entry():
    entry = autostart.build_desktop_entry("/usr/local/bin/wyze-print-monitor")
    assert entry.startswith("[Desktop Entry]\n")
    assert "Type=Application" in entry
    assert "Name=Wyze Print Monitor" in entry
    assert "Exec=/usr/local/bin/wyze-print-monitor" in entry
    assert "X-GNOME-Autostart-enabled=true" in entry


def test_launch_command():
    cmd = autostart.launch_command()
    # The executable path itself is quoted (it may contain spaces); module
    # args follow unquoted, e.g. "\"C:\\Python\\python.exe\" -m wyze_print_monitor".
    assert cmd.startswith('"')
    assert "wyze" in cmd.lower()


def test_supported_matches_platform():
    assert autostart.supported() == (
        sys.platform.startswith("win") or sys.platform.startswith("linux")
    )


@pytest.mark.skipif(
    autostart.supported(), reason="only on unsupported platforms"
)
def test_unsupported_platform_raises():
    with pytest.raises(NotImplementedError):
        autostart.is_enabled()
    with pytest.raises(NotImplementedError):
        autostart.set_enabled(True)
