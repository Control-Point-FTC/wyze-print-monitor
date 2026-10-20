"""Unusual-sound alerts from the camera's microphone (no Qt).

There's no model of "bad printer sounds" — every printer, room and camera
spot sounds different. Instead this learns what *this* print normally
sounds like (loudness in a few frequency bands, a slow running mean and
spread) and flags sound that stands well outside it for several seconds —
grinding, a skipping extruder's clicking, a crash — or a single very loud
bang. It only ever alerts; sound alone never pauses a print.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

WINDOW_S = 1.0
LEARN_S = 90  # listen this long before judging anything
BANDS_HZ = (100, 300, 700, 1500, 2500, 3600)  # edges; 8 kHz audio tops out at 4 kHz
MIN_SPREAD_DB = 3.0  # a very steady room shouldn't make tiny changes look huge
UNUSUAL_Z = 4.5
UNUSUAL_DB = 8.0  # ...and it has to be actually louder, not just different
SUSTAIN_WINDOWS = 4  # unusual in this many...
SUSTAIN_OF = 6  # ...of the last this many seconds
BANG_DB = 24.0  # one second this much louder than normal
COOLDOWN_S = 300.0
LEARN_ALPHA = 1 / 120  # running stats follow ~2 minutes of normal sound


def band_levels(samples: np.ndarray, rate: int) -> np.ndarray:
    """dB level of each band of one window of mono samples (-1..1)."""
    x = samples.astype(np.float32)
    if x.size < 64:
        return np.full(len(BANDS_HZ) - 1, -100.0, np.float32)
    x = (x - x.mean()) * np.hanning(x.size).astype(np.float32)
    power = np.abs(np.fft.rfft(x)) ** 2 / x.size
    freqs = np.fft.rfftfreq(x.size, 1.0 / rate)
    levels = []
    for lo, hi in zip(BANDS_HZ[:-1], BANDS_HZ[1:]):
        band = power[(freqs >= lo) & (freqs < hi)]
        levels.append(10 * np.log10(band.mean() + 1e-12) if band.size else -100.0)
    return np.asarray(levels, np.float32)


@dataclass
class SoundEvent:
    kind: str  # "unusual" or "bang"
    louder_db: float  # how much louder than normal, at the worst band


@dataclass
class SoundAnomaly:
    """Feed one level vector per second; returns a SoundEvent when to alert."""

    mean: np.ndarray | None = None
    var: np.ndarray | None = None
    seconds: int = 0
    recent: list = field(default_factory=list)
    last_alert: float = -1e9

    def reset(self, new_print: bool = False) -> None:
        """Re-learn from scratch. A reconnect keeps the alert cooldown; a new
        print doesn't inherit the last print's."""
        self.mean = self.var = None
        self.seconds = 0
        self.recent.clear()
        if new_print:
            self.last_alert = -1e9

    def update(self, levels: np.ndarray, now: float) -> SoundEvent | None:
        levels = np.asarray(levels, np.float32)
        if self.mean is None:
            self.mean, self.var = levels.copy(), np.full_like(levels, MIN_SPREAD_DB**2)
            self.seconds = 1
            return None
        self.seconds += 1
        spread = np.sqrt(np.maximum(self.var, MIN_SPREAD_DB**2))
        louder = levels - self.mean
        unusual = bool(np.any((louder / spread > UNUSUAL_Z) & (louder > UNUSUAL_DB)))
        learning = self.seconds <= LEARN_S
        if not unusual or learning:
            # Learn only from normal sound, so a long noise can't become "normal".
            alpha = max(LEARN_ALPHA, 1.0 / self.seconds) if learning else LEARN_ALPHA
            delta = levels - self.mean
            self.mean = self.mean + alpha * delta
            self.var = (1 - alpha) * (self.var + alpha * delta * delta)
        if learning:
            return None
        self.recent.append(unusual)
        del self.recent[:-SUSTAIN_OF]
        if now - self.last_alert < COOLDOWN_S:
            return None
        worst = float(louder.max())
        if worst > BANG_DB:
            kind = "bang"
        elif sum(self.recent) >= SUSTAIN_WINDOWS:
            kind = "unusual"
        else:
            return None
        self.last_alert = now
        self.recent.clear()
        return SoundEvent(kind, worst)


def describe(event: SoundEvent) -> str:
    if event.kind == "bang":
        return f"A sudden loud noise from the printer (~{event.louder_db:.0f} dB above normal)."
    return f"The printer has sounded unusual for a few seconds (~{event.louder_db:.0f} dB above normal)."
