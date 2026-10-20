"""Stream quality: what to pull from the camera and at what size.

The Wyze Cam V3 serves its main stream at 1920x1080 (``/stream0``) and a
low-bandwidth substream at 640x360 (``/stream1``). There's no native 720p,
so "720p" means the main stream scaled down as soon as it's decoded — every
later step (picture adjustments, display, recording) then handles 44% of
the pixels, which keeps slower PCs smooth. Only the 360p substream reduces
network traffic, so that's where **Auto** falls back when frames arrive too
slowly, retrying HD later.

Qt-free so the decisions are unit tested.
"""
from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import cv2
import numpy as np

AUTO, FULL_HD, HD720, LOW = "auto", "1080p", "720p", "360p"
QUALITIES = (AUTO, FULL_HD, HD720, LOW)
LABELS = {
    AUTO: "Auto (recommended)",
    FULL_HD: "Full HD 1080p",
    HD720: "Smooth 720p",
    LOW: "Low bandwidth 360p",
}
TARGET_HEIGHT = {HD720: 720, LOW: 360}


def normalize(quality: str | None) -> str:
    return quality if quality in QUALITIES else AUTO


def substream_url(url: str) -> str | None:
    """The camera's low-bandwidth stream for ``url``, if we know how to
    address it (Wyze: ``.../stream0`` -> ``.../stream1``); else None."""
    if not url:
        return None
    parts = urlsplit(url)
    path = parts.path
    if not path.rstrip("/").endswith("stream0"):
        return None
    trimmed = path.rstrip("/")
    new_path = trimmed[: -len("stream0")] + "stream1" + path[len(trimmed):]
    return urlunsplit((parts.scheme, parts.netloc, new_path, parts.query, parts.fragment))


def scale_to_height(frame: np.ndarray, height: int) -> np.ndarray:
    """Downscale ``frame`` to ``height`` rows (keeping its aspect); never
    upscales. INTER_AREA: the fast, alias-free choice for shrinking."""
    h, w = frame.shape[:2]
    if h <= height:
        return frame
    width = max(int(round(w * height / h)), 1)
    return cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)


class AutoQuality:
    """Auto quality as a ladder: 1080p -> 720p -> 360p (if the camera has a
    low-bandwidth stream).

    Fed the effective frame rate every couple of seconds — the lower of
    frames received and frames actually shown, so a busy CPU counts as much
    as a slow network. Below ``LOW_FPS`` for ~6 s it steps down one level
    (720p first: it more than halves the app's per-frame work; then the 360p
    stream, which also cuts decoding and network). After a while it tries
    one level up again, waiting longer each time that fails.
    """

    LOW_FPS = 10.0          # below this, the current level isn't keeping up
    SLOW_SAMPLES = 3        # ~6 s of consecutive slow samples (2 s each)
    RETRY_UP_S = 300.0      # first try one level up after 5 min
    MAX_RETRY_S = 1800.0    # back off up to 30 min if it keeps failing
    STABLE_S = 600.0        # 10 min at a level without trouble resets the back-off

    def __init__(self, has_substream: bool) -> None:
        self.levels = [FULL_HD, HD720] + ([LOW] if has_substream else [])
        self.index = 0
        self._slow = 0
        self._since = 0.0
        self._probing = False  # just stepped up: a quick failure means back off
        self._retry_after = self.RETRY_UP_S

    @property
    def level(self) -> str:
        return self.levels[self.index]

    def drop_substream(self) -> None:
        """The low-bandwidth stream turned out to be unavailable."""
        if LOW in self.levels:
            self.levels.remove(LOW)
            self.index = min(self.index, len(self.levels) - 1)

    def update(self, fps: float, now: float) -> str | None:
        """Returns the new level when it should change, else None."""
        if not self._since:
            self._since = now
        if fps < self.LOW_FPS:
            self._slow += 1
        else:
            self._slow = 0
            if now - self._since >= self.STABLE_S:
                self._retry_after = self.RETRY_UP_S  # proven stable again
                self._probing = False
        if self._slow >= self.SLOW_SAMPLES and self.index < len(self.levels) - 1:
            if self._probing:  # the level above failed again: wait longer next time
                self._retry_after = min(self._retry_after * 2, self.MAX_RETRY_S)
            self._probing = False
            self.index += 1
            self._slow = 0
            self._since = now
            return self.level
        if self.index > 0 and self._slow == 0 and now - self._since >= self._retry_after:
            self.index -= 1
            self._probing = True
            self._since = now
            return self.level
        return None
