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


@pytest.mark.parametrize(
    "error, retry, says",
    [
        # Real errors seen from Wyze / the app:
        ("ContentTypeError: 429, message='Attempt to decode JSON with unexpected mimetype: ', "
         "url='https://auth-prod.api.wyze.com/api/user/login'", True, "limiting"),
        ("Unable to login with response from Wyze: {'description': 'Invalid credentials, please check "
         "username, password, keyid or apikey', 'requestId': 'x', 'errorCode': 1000}", False, "rejected"),
        ("ClientConnectorError: Cannot connect to host auth-prod.api.wyze.com:443", True, "reach"),
        ("FileNotFoundError: [Errno 2] No such file or directory", False, "failed"),
    ],
)
def test_login_errors_are_explained_and_only_transient_ones_retried(error, retry, says):
    from wyze_print_monitor.wyze_control import describe_login_error

    message, transient = describe_login_error(error)
    assert transient is retry
    assert says in message.lower()


def test_rejected_login_is_never_retried_even_if_429_appears_elsewhere():
    from wyze_print_monitor.wyze_control import describe_login_error

    rejected = (
        "Unable to login with response from Wyze: {'description': 'Invalid credentials, please check "
        "username, password, keyid or apikey', 'requestId': 'ab-429-cd', 'errorCode': 1000}"
    )
    assert describe_login_error(rejected)[1] is False
    # A stray 429 in an id is not a rate limit either.
    assert describe_login_error("Unexpected response {'requestId': 'x-429-y', 'errorCode': 2001}")[1] is False


def test_newest_login_wins_over_a_late_older_one():
    """A background retry finishing after a newer login must not replace it."""
    import asyncio

    from wyze_print_monitor import wyze_control

    class FakeClient:
        async def login(self, *args):
            return None

    wyze_control.Wyzeapy = FakeClient
    controller = wyze_control.WyzeController(runner=None)
    controller._login_seq = 2  # a newer login (seq 2) has started
    with pytest.raises(wyze_control.SupersededLogin):
        asyncio.run(controller._do_login("e", "p", "k", "a", seq=1))
    assert controller._client is None
    assert asyncio.run(controller._do_login("e", "p", "k", "a", seq=2)) is True
    assert isinstance(controller._client, FakeClient)
