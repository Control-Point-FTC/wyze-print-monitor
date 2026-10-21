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


def test_a_new_print_gets_a_fresh_cooldown_but_a_reconnect_doesnt():
    a = SoundAnomaly()
    a.last_alert = 500.0
    a.reset()
    assert a.last_alert == 500.0  # reconnect: same print
    a.reset(new_print=True)
    assert a.last_alert < 0


def test_looks_fine_makes_this_print_more_tolerant():
    a = SoundAnomaly()
    _run(a, sw.LEARN_S + 30, 0)
    a.teach()
    assert a.extra_db == sw.TEACH_DB
    t = sw.LEARN_S + 30
    once = [e for e in _run(a, 20, t, tone_hz=2000, tone=0.04) if e]
    assert len(once) == 1  # ~15 dB grinding still beats 8 + 6 dB
    a.teach()  # "Looks fine" again
    a.last_alert = -1e9
    twice = [e for e in _run(a, 20, t + 400, tone_hz=2000, tone=0.04) if e]
    assert twice == []  # 8 + 12 dB: now it's tolerated
    for _ in range(5):
        a.teach()
    assert a.extra_db == sw.TEACH_MAX_DB
    a.reset()
    assert a.extra_db == sw.TEACH_MAX_DB  # a reconnect keeps it
    a.reset(new_print=True)
    assert a.extra_db == 0.0  # the next print starts fresh
