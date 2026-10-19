"""Tests for reading camera toggle states (Qt and wyzeapy stubbed)."""
import sys
import types

import pytest


@pytest.fixture(autouse=True)
def _stub_deps(monkeypatch):
    """wyze_control imports wyzeapy and (via async_runner) Qt at import time;
    stub just enough of both to test the pure state mapping."""
    qtcore = types.ModuleType("PySide6.QtCore")

    class _Base:
        def __init__(self, *a, **k): ...

    qtcore.QObject = _Base
    qtcore.QThread = _Base
    qtcore.Signal = lambda *a, **k: None
    pyside = types.ModuleType("PySide6")
    pyside.QtCore = qtcore

    wyzeapy = types.ModuleType("wyzeapy")
    wyzeapy.Wyzeapy = object
    exceptions = types.ModuleType("wyzeapy.exceptions")
    exceptions.TwoFactorAuthenticationEnabled = type("TwoFactorAuthenticationEnabled", (Exception,), {})
    services = types.ModuleType("wyzeapy.services")
    camera_service = types.ModuleType("wyzeapy.services.camera_service")
    camera_service.CameraService = object

    for name, module in {
        "PySide6": pyside,
        "PySide6.QtCore": qtcore,
        "wyzeapy": wyzeapy,
        "wyzeapy.exceptions": exceptions,
        "wyzeapy.services": services,
        "wyzeapy.services.camera_service": camera_service,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delitem(sys.modules, "wyze_print_monitor.wyze_control", raising=False)
    monkeypatch.delitem(sys.modules, "wyze_print_monitor.async_runner", raising=False)


def test_camera_state_maps_wyzeapy_attributes():
    from wyze_print_monitor.wyze_control import _camera_state

    camera = types.SimpleNamespace(on=True, siren=False, floodlight=True, motion="1", notify="0")
    state = _camera_state(camera)
    assert state.power is True
    assert state.siren is False
    assert state.spotlight is True
    assert state.motion is True
    assert state.notifications is False


def test_unreported_states_are_unknown_not_off():
    """A camera that never reported motion/notify must not appear 'off'."""
    from wyze_print_monitor.wyze_control import _camera_state

    state = _camera_state(types.SimpleNamespace(on=True, siren=False, floodlight=False))
    assert state.motion is None
    assert state.notifications is None
