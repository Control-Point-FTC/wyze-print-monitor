"""Camera control through the Wyze cloud API (via ``wyzeapy``).

Works with stock Wyze firmware, including the RTSP firmware on the Cam v3:
the camera stays fully usable in the Wyze app while this module sends it
commands. All coroutines run on the :class:`AsyncRunner` event loop; public
methods are non-blocking and report back through ``on_done`` callbacks on
the GUI thread.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from wyzeapy import Wyzeapy
from wyzeapy.exceptions import TwoFactorAuthenticationEnabled
from wyzeapy.services.camera_service import CameraService

from .async_runner import AsyncRunner, OnDone


# Automatic re-login after a temporary failure (rate limit, network): 1, 5
# and 15 minutes. Never for rejected credentials — repeated bad logins can
# get a Wyze account locked.
LOGIN_RETRY_DELAYS_S = (60, 300, 900)


RATE_LIMITED = re.compile(r"(?:contenttypeerror|status|http|error)\W{0,3}429\b")


class SupersededLogin(Exception):
    """A newer login started before this one finished; its result is dropped."""


def describe_login_error(error: str) -> tuple[str, bool]:
    """A user-facing reason for a failed Wyze login, and whether trying
    again later can help (True) or the user has to fix something (False)."""
    text = (error or "").lower()
    # Rejected credentials first: a rejection must never be retried, even if
    # some other part of the message (a request id...) happens to look like
    # a rate limit.
    if "invalid credentials" in text or "'errorcode': 1000" in text or "access denied" in text:
        return "Wyze rejected the login. Check your email, password and API key in Settings.", False
    # Rate limit: HTTP 429 as the status (e.g. "ContentTypeError: 429, ..."),
    # not any "429" anywhere in the text.
    if RATE_LIMITED.search(text) or "too many requests" in text or "rate limit" in text:
        return "Wyze is temporarily limiting logins (too many attempts).", True
    if any(
        marker in text
        for marker in (
            "cannot connect", "clientconnector", "timeout", "timed out", "name resolution",
            "getaddrinfo", "network is unreachable", "connection reset", "server disconnected",
            "502", "503", "504",
        )
    ):
        return "Couldn't reach Wyze. Check the internet connection.", True
    return f"Wyze login failed: {error.strip()[:140]}", False


class NeedTwoFactor(Exception):
    """Raised (as an on_done error) when Wyze asks for a 2FA verification code."""


@dataclass
class CameraInfo:
    mac: str
    nickname: str
    product_model: str
    is_online: bool
    firmware: str = ""
    ip: str = ""


@dataclass
class CameraState:
    """Live toggle states read from the Wyze cloud. ``None`` = not reported."""

    power: Optional[bool] = None
    siren: Optional[bool] = None
    spotlight: Optional[bool] = None
    motion: Optional[bool] = None
    notifications: Optional[bool] = None


def _opt_bool(camera: Any, attr: str) -> Optional[bool]:
    value = getattr(camera, attr, None)
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on")
    return bool(value)


def _camera_state(camera: Any) -> CameraState:
    # Attribute names are wyzeapy's; motion/notify only exist once update()
    # has read them, so a missing attribute stays None ("unknown").
    return CameraState(
        power=_opt_bool(camera, "on"),
        siren=_opt_bool(camera, "siren"),
        spotlight=_opt_bool(camera, "floodlight"),
        motion=_opt_bool(camera, "motion"),
        notifications=_opt_bool(camera, "notify"),
    )


def _camera_info(camera: Any) -> CameraInfo:
    raw = getattr(camera, "raw_dict", {}) or {}
    params = getattr(camera, "device_params", {}) or {}
    return CameraInfo(
        mac=str(getattr(camera, "mac", "")),
        nickname=str(getattr(camera, "nickname", "") or "Camera"),
        product_model=str(getattr(camera, "product_model", "")),
        is_online=bool(getattr(camera, "available", True)),
        firmware=str(
            getattr(camera, "firmware_ver", "")
            or params.get("firmware_ver", "")
            or raw.get("firmware_ver", "")
        ),
        ip=str(params.get("ip", "") or raw.get("ip", "")),
    )


class WyzeController:
    """Non-blocking facade over wyzeapy's async CameraService."""

    def __init__(self, runner: AsyncRunner) -> None:
        self._runner = runner
        self._client: Optional[Wyzeapy] = None
        self._pending_client: Optional[Wyzeapy] = None
        self._login_seq = 0
        self._cameras: dict[str, Any] = {}

    # ------------------------------------------------------------------ login
    async def _do_login(
        self, email: str, password: str, key_id: str, api_key: str, seq: int
    ) -> bool:
        client = Wyzeapy()
        try:
            await client.login(email, password, key_id, api_key)
        except TwoFactorAuthenticationEnabled:
            if seq != self._login_seq:
                raise SupersededLogin("A newer login replaced this one.")
            self._pending_client = client
            raise NeedTwoFactor(
                "Wyze requires a 2FA verification code for this login."
            )
        # Newest login wins: an older attempt (e.g. a background retry with
        # the previously saved credentials) finishing late must not replace
        # the account the user just signed in with.
        if seq != self._login_seq:
            raise SupersededLogin("A newer login replaced this one.")
        self._client = client
        self._pending_client = None
        return True

    def login(
        self,
        email: str,
        password: str,
        key_id: str,
        api_key: str,
        on_done: OnDone,
    ) -> None:
        self._login_seq += 1
        self._runner.submit(
            "login", self._do_login(email, password, key_id, api_key, self._login_seq), on_done
        )

    async def _do_login_2fa(self, code: str) -> bool:
        client = self._pending_client
        if client is None:
            raise RuntimeError("No pending login waiting for a 2FA code.")
        await client.login_with_2fa(code)
        self._client = client
        self._pending_client = None
        return True

    def submit_2fa(self, code: str, on_done: OnDone) -> None:
        self._runner.submit("login-2fa", self._do_login_2fa(code), on_done)

    @property
    def logged_in(self) -> bool:
        return self._client is not None

    # ----------------------------------------------------------------- cameras
    async def _service(self) -> CameraService:
        if self._client is None:
            raise RuntimeError("Not logged in to Wyze.")
        return await self._client.camera_service

    async def _do_list_cameras(self) -> list[CameraInfo]:
        service = await self._service()
        cameras = await service.get_cameras()
        self._cameras = {str(c.mac): c for c in cameras}
        return [_camera_info(c) for c in cameras]

    def list_cameras(self, on_done: OnDone) -> None:
        self._runner.submit("list-cameras", self._do_list_cameras(), on_done)

    def _get_camera(self, mac: str) -> Any:
        camera = self._cameras.get(mac)
        if camera is None:
            raise ValueError("Camera not found — refresh the camera list first.")
        return camera

    async def _do_get_state(self, mac: str) -> CameraState:
        service = await self._service()
        camera = await service.update(self._get_camera(mac))
        return _camera_state(camera)

    def get_state(self, mac: str, on_done: OnDone) -> None:
        self._runner.submit("camera-state", self._do_get_state(mac), on_done)

    # ----------------------------------------------------------------- actions
    async def _do_set_power(self, mac: str, on: bool) -> bool:
        service = await self._service()
        camera = self._get_camera(mac)
        if on:
            await service.turn_on(camera)
        else:
            await service.turn_off(camera)
        return True

    def set_power(self, mac: str, on: bool, on_done: OnDone) -> None:
        self._runner.submit("power", self._do_set_power(mac, on), on_done)

    async def _do_restart(self, mac: str) -> bool:
        # Same run_action mechanism the official integrations use for restart.
        service = await self._service()
        camera = self._get_camera(mac)
        await service._run_action(camera, "restart")  # noqa: SLF001 - no public API
        return True

    def restart(self, mac: str, on_done: OnDone) -> None:
        self._runner.submit("restart", self._do_restart(mac), on_done)

    async def _do_siren(self, mac: str, on: bool) -> bool:
        service = await self._service()
        camera = self._get_camera(mac)
        if on:
            await service.siren_on(camera)
        else:
            await service.siren_off(camera)
        return True

    def set_siren(self, mac: str, on: bool, on_done: OnDone) -> None:
        self._runner.submit("siren", self._do_siren(mac, on), on_done)

    async def _do_spotlight(self, mac: str, on: bool) -> bool:
        # wyzeapy maps this to the V3's spotlight accessory (P1056).
        service = await self._service()
        camera = self._get_camera(mac)
        if on:
            await service.floodlight_on(camera)
        else:
            await service.floodlight_off(camera)
        return True

    def set_spotlight(self, mac: str, on: bool, on_done: OnDone) -> None:
        self._runner.submit("spotlight", self._do_spotlight(mac, on), on_done)

    async def _do_motion_detection(self, mac: str, on: bool) -> bool:
        service = await self._service()
        camera = self._get_camera(mac)
        if on:
            await service.turn_on_motion_detection(camera)
        else:
            await service.turn_off_motion_detection(camera)
        return True

    def set_motion_detection(self, mac: str, on: bool, on_done: OnDone) -> None:
        self._runner.submit(
            "motion-detection", self._do_motion_detection(mac, on), on_done
        )

    async def _do_notifications(self, mac: str, on: bool) -> bool:
        service = await self._service()
        camera = self._get_camera(mac)
        if on:
            await service.turn_on_notifications(camera)
        else:
            await service.turn_off_notifications(camera)
        return True

    def set_notifications(self, mac: str, on: bool, on_done: OnDone) -> None:
        self._runner.submit(
            "notifications", self._do_notifications(mac, on), on_done
        )
