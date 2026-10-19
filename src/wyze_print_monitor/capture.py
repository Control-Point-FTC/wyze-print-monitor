"""RTSP stream reading, clip recording, and snapshot capture.

:class:`StreamReader` runs on its own thread, reconnects with backoff when
the camera drops, and emits decoded BGR frames. :class:`ClipRecorder`
writes frames to an MP4 file.
"""
from __future__ import annotations

import datetime
import os
import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal

from .adjust import IDENTITY, ImageAdjustments, apply_adjustments

# Every blocking FFmpeg call is bounded so stop() can always join the thread.
OPEN_TIMEOUT_MS = 5000
READ_TIMEOUT_MS = 5000
FFMPEG_OPTIONS_ENV = "OPENCV_FFMPEG_CAPTURE_OPTIONS"
RTSP_OVER_TCP = "rtsp_transport;tcp"
# Options the user set themselves (captured once, before any reader thread
# touches the variable): we add to them and always restore them.
_USER_FFMPEG_OPTIONS = os.environ.get(FFMPEG_OPTIONS_ENV)


def transport_attempts(user_options: str | None) -> list[str | None]:
    """FFmpeg option strings to try, in order (``None`` = no options).

    TCP first, then the user's own options / FFmpeg's default. A user who
    already picked an ``rtsp_transport`` keeps exactly their setting.
    """
    if user_options and "rtsp_transport" in user_options:
        return [user_options]
    tcp = f"{user_options}|{RTSP_OVER_TCP}" if user_options else RTSP_OVER_TCP
    return [tcp, user_options or None]


def _set_ffmpeg_options(options: str | None) -> None:
    if options:
        os.environ[FFMPEG_OPTIONS_ENV] = options
    else:
        os.environ.pop(FFMPEG_OPTIONS_ENV, None)


class StreamReader(QThread):
    """Reads an RTSP stream with OpenCV, emitting frames and state changes."""

    frame_ready = Signal(object)  # np.ndarray (BGR)
    state_changed = Signal(str, str)  # state, detail message
    # states: "connecting" | "live" | "reconnecting" | "stopped" | "error"

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._stop_requested = False
        self.measured_fps = 0.0
        self.frame_size: tuple[int, int] = (0, 0)
        # Picture adjustments, applied on this thread to every frame before
        # it's emitted (so view, snapshots, clips and timelapses all match).
        # Immutable, so the GUI thread can swap it in with one assignment.
        self.adjustments: ImageAdjustments = IDENTITY

    def request_stop(self) -> None:
        self._stop_requested = True

    def stop(self, timeout_ms: int = 12000) -> bool:
        """Ask the thread to exit and wait for it. Returns True once it has.

        Reads are bounded by CAP_PROP_READ_TIMEOUT_MSEC, so 12s is normally
        ample — but a backend that ignores the timeout can overrun it, so the
        caller must check the result before letting the thread be destroyed.
        """
        self.request_stop()
        return self.wait(timeout_ms)

    def run(self) -> None:
        if not self._url:
            self.state_changed.emit("error", "No RTSP URL configured.")
            return
        backoff = 1.0
        self.state_changed.emit("connecting", "Opening RTSP stream…")
        while not self._stop_requested:
            cap = self._open()
            # Keep the decode buffer tiny so the view stays close to live.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                cap.release()
                self.state_changed.emit(
                    "reconnecting", f"Cannot open stream, retrying in {backoff:.0f}s…"
                )
                self._sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            self.state_changed.emit("live", "Streaming")
            backoff = 1.0
            frames = 0
            t_start = time.monotonic()
            while not self._stop_requested:
                ok, frame = cap.read()
                if not ok:
                    break  # stream dropped -> reconnect
                frames += 1
                elapsed = time.monotonic() - t_start
                if elapsed >= 2.0:
                    self.measured_fps = frames / elapsed
                    frames, t_start = 0, time.monotonic()
                    h, w = frame.shape[:2]
                    self.frame_size = (w, h)  # the camera's own resolution
                adjustments = self.adjustments  # one read: the GUI may swap it
                if not adjustments.is_identity():
                    try:
                        frame = apply_adjustments(frame, adjustments)
                    except cv2.error:
                        pass  # never let a bad setting stop the stream
                self.frame_ready.emit(frame)
            cap.release()
            if not self._stop_requested:
                self.state_changed.emit("reconnecting", "Stream dropped, reconnecting…")
                self._sleep(1.0)
        self.state_changed.emit("stopped", "Stream stopped.")

    def _open(self) -> "cv2.VideoCapture":
        """Open the stream, preferring RTSP over TCP.

        FFmpeg defaults to RTP over UDP, which drops packets on Wi-Fi (and is
        often blocked by firewalls): each loss ended the read loop and made
        the picture blink while we reconnected. Interleaved TCP is far
        steadier; fall back to FFmpeg's default for cameras that refuse it.

        The timeouts must be passed at construction — VideoCapture(url)
        opens immediately, so setting them afterwards never bounded the open
        (it waited FFmpeg's 30 s default instead).
        """
        params = [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS,
        ]
        cap = None
        try:
            for options in transport_attempts(_USER_FFMPEG_OPTIONS):
                # OpenCV's FFmpeg backend only takes demuxer options from this
                # environment variable, read at open time.
                _set_ffmpeg_options(options)
                cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG, params)
                if cap.isOpened() or self._stop_requested:
                    return cap
                cap.release()
            return cap
        finally:
            _set_ffmpeg_options(_USER_FFMPEG_OPTIONS)

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self._stop_requested and time.monotonic() < deadline:
            time.sleep(0.1)


class ClipRecorder:
    """Writes BGR frames to an MP4 file. Not thread-safe by itself."""

    def __init__(self, output_path: str, fps: float = 20.0) -> None:
        self.output_path = output_path
        self._writer: cv2.VideoWriter | None = None
        self._fps = fps
        self._size: tuple[int, int] | None = None
        self.frames_written = 0

    def write(self, frame: np.ndarray) -> None:
        if self._writer is None:
            h, w = frame.shape[:2]
            os.makedirs(os.path.dirname(os.path.abspath(self.output_path)), exist_ok=True)
            self._writer = cv2.VideoWriter(
                self.output_path,
                cv2.VideoWriter_fourcc(*"mp4v"),
                self._fps,
                (w, h),
            )
            if not self._writer.isOpened():
                self._writer.release()
                self._writer = None
                raise IOError(
                    f"Could not open video writer for {self.output_path} "
                    "(folder unwritable or mp4v encoder unavailable)."
                )
            self._size = (w, h)
        # If the stream resolution changed mid-recording (e.g. RTSP URL
        # switched), resize into the original frame size instead of dropping.
        assert self._size is not None
        if (frame.shape[1], frame.shape[0]) != self._size:
            frame = cv2.resize(frame, self._size)
        self._writer.write(frame)
        self.frames_written += 1

    def close(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None


def snapshot_path(snapshot_dir: str, prefix: str = "snapshot") -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    os.makedirs(snapshot_dir, exist_ok=True)
    return os.path.join(snapshot_dir, f"{prefix}_{stamp}.png")
