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

    def stop(self) -> None:
        self._stop_requested = True
        # Reads are bounded by CAP_PROP_READ_TIMEOUT_MSEC, so 12s is ample.
        self.wait(12000)

    def run(self) -> None:
        if not self._url:
            self.state_changed.emit("error", "No RTSP URL configured.")
            return
        backoff = 1.0
        self.state_changed.emit("connecting", "Opening RTSP stream…")
        while not self._stop_requested:
            cap = cv2.VideoCapture(self._url, cv2.CAP_FFMPEG)
            # Keep the decode buffer tiny so the view stays close to live.
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            # Bound blocking opens/reads so stop() can always join the thread.
            # (Supported by the FFmpeg backend; harmless no-ops otherwise.)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
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
                    self.frame_size = (w, h)
                self.frame_ready.emit(frame)
            cap.release()
            if not self._stop_requested:
                self.state_changed.emit("reconnecting", "Stream dropped, reconnecting…")
                self._sleep(1.0)
        self.state_changed.emit("stopped", "Stream stopped.")

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
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    os.makedirs(snapshot_dir, exist_ok=True)
    return os.path.join(snapshot_dir, f"{prefix}_{stamp}.png")
