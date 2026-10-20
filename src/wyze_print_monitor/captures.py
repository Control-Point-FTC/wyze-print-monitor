"""Find and preview the user's recent snapshots, clips and timelapses.

Feeds the "Recent captures" strip. Qt-free (thumbnails are BGR arrays), so
it's unit tested and safe to run on a worker thread.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np

KINDS = {
    "snapshot": "Snapshot",
    "clip": "Clip",
    "timelapse": "Timelapse",
}


@dataclass(frozen=True)
class Capture:
    path: str
    kind: str  # "snapshot" | "clip" | "timelapse"
    mtime: float

    @property
    def label(self) -> str:
        return KINDS.get(self.kind, "File")


def _kind(filename: str) -> str | None:
    name = filename.lower()
    if name.endswith(".png") and name.startswith("snapshot_"):
        return "snapshot"
    if name.endswith(".mp4") and name.startswith("clip_"):
        return "clip"
    if name.endswith(".mp4") and name.startswith("timelapse_"):
        return "timelapse"
    return None


def recent_captures(snapshot_dir: str, video_dir: str, limit: int = 6) -> list[Capture]:
    """The newest captures across both folders, newest first. Missing or
    unreadable folders simply contribute nothing."""
    found: dict[str, Capture] = {}
    for folder in {snapshot_dir, video_dir}:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            kind = _kind(entry.name)
            if kind is None:
                continue
            try:
                if not entry.is_file():
                    continue
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            found[entry.path] = Capture(entry.path, kind, mtime)
    return sorted(found.values(), key=lambda c: c.mtime, reverse=True)[:limit]


def thumbnail(path: str, width: int = 240) -> np.ndarray | None:
    """A small BGR preview: the image itself, or a frame ~10% into a video.
    None if the file can't be read."""
    frame = None
    if path.lower().endswith(".png"):
        frame = cv2.imread(path, cv2.IMREAD_COLOR)
    else:
        cap = cv2.VideoCapture(path)
        try:
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if count > 10:
                cap.set(cv2.CAP_PROP_POS_FRAMES, count // 10)
            ok, frame = cap.read()
            if not ok:
                frame = None
        finally:
            cap.release()
    if frame is None or frame.size == 0:
        return None
    h, w = frame.shape[:2]
    if w > width:
        frame = cv2.resize(frame, (width, max(int(h * width / w), 1)), interpolation=cv2.INTER_AREA)
    return frame


def describe_age(seconds: float) -> str:
    """'just now', '5 min ago', '3 h ago', '2 d ago'."""
    seconds = max(seconds, 0)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} d ago"
