"""Tests for the live-stream picture adjustments (pure numpy/OpenCV)."""
import numpy as np
import pytest

from wyze_print_monitor.adjust import IDENTITY, ImageAdjustments, apply_adjustments


def _frame(value=128, w=64, h=36):
    return np.full((h, w, 3), value, np.uint8)


def test_identity_is_a_no_op():
    frame = _frame()
    assert apply_adjustments(frame, IDENTITY) is frame


def test_never_modifies_the_input_frame():
    frame = _frame()
    before = frame.copy()
    apply_adjustments(frame, ImageAdjustments(brightness=50, sharpness=40, flip_h=True))
    assert np.array_equal(frame, before)


@pytest.mark.parametrize(
    "adj, brighter",
    [
        (ImageAdjustments(brightness=50), True),
        (ImageAdjustments(brightness=-50), False),
        (ImageAdjustments(exposure=1.0), True),
        (ImageAdjustments(exposure=-1.0), False),
        (ImageAdjustments(gamma=2.0), True),
        (ImageAdjustments(gamma=0.5), False),
    ],
)
def test_tone_controls_move_brightness_the_right_way(adj, brighter):
    out = apply_adjustments(_frame(100), adj)
    assert bool(out.mean() > 100) is brighter


def test_contrast_spreads_or_squeezes_tones():
    frame = np.zeros((10, 10, 3), np.uint8)
    frame[:5] = 64
    frame[5:] = 192
    spread = apply_adjustments(frame, ImageAdjustments(contrast=60))
    squeezed = apply_adjustments(frame, ImageAdjustments(contrast=-60))
    assert np.ptp(spread) > np.ptp(frame) > np.ptp(squeezed)


def test_saturation_minus_100_is_grayscale():
    frame = _frame()
    frame[..., 2] = 220  # strong red
    out = apply_adjustments(frame, ImageAdjustments(saturation=-100))
    assert np.allclose(out[..., 0], out[..., 2], atol=1)


def test_temperature_warms_red_and_cools_blue():
    warm = apply_adjustments(_frame(), ImageAdjustments(temperature=100))
    b, _g, r = warm[0, 0]
    assert r > 128 > b


def test_rotation_swaps_dimensions_and_flips_mirror():
    frame = np.zeros((36, 64, 3), np.uint8)
    frame[:, :8] = 255  # bright left edge
    assert apply_adjustments(frame, ImageAdjustments(rotation=90)).shape == (64, 36, 3)
    flipped = apply_adjustments(frame, ImageAdjustments(flip_h=True))
    assert flipped[:, -1].mean() == 255 and flipped[:, 0].mean() == 0


def test_zoom_keeps_frame_size_and_pans():
    frame = np.zeros((40, 80, 3), np.uint8)
    frame[:, 70:] = 255  # bright right edge
    centered = apply_adjustments(frame, ImageAdjustments(zoom=2.0))
    right = apply_adjustments(frame, ImageAdjustments(zoom=2.0, pan_x=1.0))
    assert centered.shape == frame.shape
    assert centered.mean() < right.mean()  # panning right brings the edge in


def test_from_dict_clamps_and_ignores_garbage():
    adj = ImageAdjustments.from_dict(
        {"brightness": 500, "gamma": "1.5", "rotation": 450, "zoom": "x", "nope": 1, "flip_h": 1}
    )
    assert adj.brightness == 100
    assert adj.gamma == 1.5
    assert adj.rotation == 90
    assert adj.zoom == 1.0  # bad value dropped -> default
    assert adj.flip_h is True
    assert ImageAdjustments.from_dict(None) == IDENTITY


def test_round_trips_through_dict():
    adj = ImageAdjustments(brightness=10, exposure=-0.5, rotation=270, flip_v=True, zoom=1.5, pan_y=-0.3)
    assert ImageAdjustments.from_dict(adj.to_dict()) == adj
