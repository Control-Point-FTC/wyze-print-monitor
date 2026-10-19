"""Print timelapse helpers (no Qt dependency — unit testable).

A :class:`TimelapseCollector` saves one JPEG frame every ``interval_sec``
while a print runs; :func:`compile_timelapse` later stitches the saved
frames into an MP4.
"""
from __future__ import annotations

import os
import time

import cv2
import numpy as np


class TimelapseCollector:
    """Saves periodic JPEG snapshots of BGR frames into ``frames_dir``."""

    def __init__(self, frames_dir: str, interval_sec: int = 10) -> None:
        self.frames_dir = frames_dir
        self.interval_sec = max(1, interval_sec)
        self._next_due = 0.0
        self.saved = 0
        self.write_errors = 0

    def start(self) -> None:
        os.makedirs(self.frames_dir, exist_ok=True)
        self._next_due = 0.0  # capture the first frame immediately
        self.saved = 0
        self.write_errors = 0

    def maybe_capture(self, frame: np.ndarray, now: float | None = None) -> bool:
        """Save *frame* if the interval has elapsed. Returns True when saved."""
        now = time.monotonic() if now is None else now
        if now < self._next_due:
            return False
        self._next_due = now + self.interval_sec
        path = os.path.join(self.frames_dir, f"frame_{self.saved:06d}.jpg")
        if not cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 90]):
            # Don't count failed writes: the next success reuses this slot,
            # so the compiled video has no silent gaps.
            self.write_errors += 1
            return False
        self.saved += 1
        return True

    def frame_paths(self) -> list[str]:
        if not os.path.isdir(self.frames_dir):
            return []
        names = sorted(
            n for n in os.listdir(self.frames_dir) if n.lower().endswith(".jpg")
        )
        return [os.path.join(self.frames_dir, n) for n in names]


def compile_timelapse(
    frames_dir: str, output_path: str, fps: int = 30
) -> int:
    """Stitch saved JPEG frames into an MP4. Returns the frame count written.

    Raises FileNotFoundError when there are no frames, ValueError when a
    frame cannot be decoded.
    """
    collector = TimelapseCollector(frames_dir)
    paths = collector.frame_paths()
    if not paths:
        raise FileNotFoundError(f"No timelapse frames found in {frames_dir}")

    first = cv2.imread(paths[0])
    if first is None:
        raise ValueError(f"Could not decode frame: {paths[0]}")
    height, width = first.shape[:2]

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    writer = cv2.VideoWriter(
        output_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        writer.release()
        raise IOError(
            f"Could not open video writer for {output_path} "
            "(folder unwritable or mp4v encoder unavailable)."
        )
    written = 0
    try:
        for path in paths:
            frame = cv2.imread(path)
            if frame is None:
                continue
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height))
            writer.write(frame)
            written += 1
    finally:
        writer.release()
    if written == 0:
        raise ValueError("No decodable frames found.")
    return written
