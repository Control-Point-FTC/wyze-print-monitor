"""Alert sounds: a chime for "take a look", an alarm for "it failed".

The alarm loops until the user responds (any button on the alert, or
Silence), with a safety cut-off so a PC left alone doesn't beep all night.
Sounds are generated once into the app's data folder: no files to ship.
"""
from __future__ import annotations

import io
import os
import wave

import numpy as np
from PySide6.QtCore import QObject, QTimer

from ..config import config_dir

RATE = 22050
ALARM_MAX_MS = 5 * 60 * 1000  # stop looping after 5 minutes regardless

SOUND_ALARM, SOUND_BEEP, SOUND_OFF = "alarm", "beep", "off"
SOUNDS = (SOUND_ALARM, SOUND_BEEP, SOUND_OFF)


def _tone(freq: float, seconds: float, volume: float = 0.55) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    tone = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(4 * np.pi * freq * t)
    fade = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.01)  # no clicks
    return (tone / 1.25 * fade * volume).astype(np.float32)


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(RATE * seconds), np.float32)


def make_wav(kind: str) -> bytes:
    """16-bit mono WAV: "alarm" (urgent two-tone, ~1.6 s, loops) or "chime"."""
    if kind == "alarm":
        beat = [_tone(1050, 0.16), _silence(0.05), _tone(1400, 0.16), _silence(0.05)]
        samples = np.concatenate(beat * 3 + [_silence(0.35)])
    else:
        samples = np.concatenate([_tone(880, 0.14, 0.4), _silence(0.04), _tone(1320, 0.22, 0.4)])
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out.getvalue()


def _sound_file(kind: str) -> str | None:
    path = os.path.join(config_dir(), "sounds", f"{kind}.wav")
    try:
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(make_wav(kind))
        return path
    except OSError:
        return None


class Alarm(QObject):
    """Plays alert sounds (Windows: winsound; elsewhere: the system beep)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.playing = False
        self._cutoff = QTimer(self)
        self._cutoff.setSingleShot(True)
        self._cutoff.timeout.connect(self.stop)

    def play(self, sound: str, urgent: bool) -> None:
        """``sound`` is the user's choice; urgent alerts loop as an alarm."""
        self.stop()
        if sound == SOUND_OFF:
            return
        try:
            import winsound
        except ImportError:
            from PySide6.QtWidgets import QApplication

            QApplication.beep()
            return
        if sound == SOUND_BEEP or not urgent:
            path = _sound_file("chime")
            if path:
                winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            return
        path = _sound_file("alarm")
        if not path:
            winsound.MessageBeep(winsound.MB_ICONHAND)
            return
        winsound.PlaySound(
            path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP | winsound.SND_NODEFAULT
        )
        self.playing = True
        self._cutoff.start(ALARM_MAX_MS)

    def stop(self) -> None:
        self._cutoff.stop()
        if not self.playing:
            return
        self.playing = False
        try:
            import winsound

            winsound.PlaySound(None, winsound.SND_PURGE)
        except (ImportError, RuntimeError):
            pass
