"""Tests for unusual-sound detection (synthetic audio, no camera)."""
import numpy as np

from wyze_print_monitor import sound_watch as sw
from wyze_print_monitor.sound_watch import SoundAnomaly, band_levels

RATE = 8000
rng = np.random.default_rng(0)


def _second(noise=0.01, tone_hz=None, tone=0.0):
    t = np.arange(RATE) / RATE
    x = rng.normal(0, noise, RATE)
    if tone_hz:
        x = x + tone * np.sin(2 * np.pi * tone_hz * t)
    return band_levels(x.astype(np.float32), RATE)


def _run(anomaly, seconds, start, **kw):
    return [anomaly.update(_second(**kw), start + i) for i in range(seconds)]


def test_band_levels_shape_and_tone_placement():
    levels = _second(noise=0.0001, tone_hz=1000, tone=0.5)
    assert levels.shape == (len(sw.BANDS_HZ) - 1,)
    assert int(np.argmax(levels)) == 2  # 1000 Hz is in the 700-1500 band


def test_learns_quietly_then_stays_quiet_on_normal_sound():
    a = SoundAnomaly()
    events = _run(a, sw.LEARN_S + 120, 0)
    assert [e for e in events if e] == []


def test_sustained_grinding_alerts_once_then_cools_down():
    a = SoundAnomaly()
    _run(a, sw.LEARN_S + 30, 0)
    t = sw.LEARN_S + 30
    events = [e for e in _run(a, 20, t, tone_hz=2000, tone=0.04) if e]
    assert len(events) == 1 and events[0].kind == "unusual"
    assert events[0].louder_db > sw.UNUSUAL_DB


def test_a_short_blip_is_not_enough():
    a = SoundAnomaly()
    _run(a, sw.LEARN_S + 30, 0)
    t = sw.LEARN_S + 30
    blip = _run(a, 2, t, tone_hz=2000, tone=0.05)  # moderately louder, 2 s
    calm = _run(a, 10, t + 2)
    assert [e for e in blip + calm if e] == []


def test_a_loud_bang_alerts_at_once():
    a = SoundAnomaly()
    _run(a, sw.LEARN_S + 30, 0)
    (event,) = [e for e in _run(a, 1, sw.LEARN_S + 30, noise=0.6) if e]
    assert event.kind == "bang"
    assert "loud" in sw.describe(event)


def test_nothing_during_learning_even_if_loud():
    a = SoundAnomaly()
    assert [e for e in _run(a, sw.LEARN_S, 0, noise=0.5) if e] == []
