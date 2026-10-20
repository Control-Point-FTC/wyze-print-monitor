"""Tests for stream quality decisions (no Qt, no network)."""
import numpy as np

from wyze_print_monitor.quality import AutoQuality, normalize, scale_to_height, substream_url


def test_substream_url_for_wyze_paths():
    assert substream_url("rtsps://u:p%40x@192.168.1.121:322/stream0") == "rtsps://u:p%40x@192.168.1.121:322/stream1"
    assert substream_url("rtsp://cam/stream0/") == "rtsp://cam/stream1/"
    assert substream_url("rtsp://u:p@cam/live") is None  # older Wyze RTSP firmware
    assert substream_url("") is None


def test_scale_to_height_shrinks_only():
    hd = np.zeros((1080, 1920, 3), np.uint8)
    assert scale_to_height(hd, 720).shape == (720, 1280, 3)
    small = np.zeros((360, 640, 3), np.uint8)
    assert scale_to_height(small, 720) is small


def test_normalize_unknown_values_to_auto():
    assert normalize("720p") == "720p"
    assert normalize("4k") == "auto"
    assert normalize(None) == "auto"


def _feed(auto, fps, start, samples):
    """Feed `samples` readings 2 s apart; return the decisions."""
    return [auto.update(fps, start + i * 2.0) for i in range(samples)]


def test_steps_down_to_720p_first_then_360p():
    auto = AutoQuality(has_substream=True)
    assert auto.level == "1080p"
    assert _feed(auto, 15.0, 0, 3) == [None, None, None]
    assert _feed(auto, 8.0, 6, 3)[-1] == "720p"          # ~6 s under 10 fps
    assert _feed(auto, 8.0, 12, 3)[-1] == "360p"          # still slow -> low stream
    assert _feed(auto, 8.0, 18, 5) == [None] * 5          # nowhere lower to go


def test_one_good_sample_resets_the_slow_count():
    auto = AutoQuality(has_substream=True)
    decisions = [auto.update(f, t) for f, t in ((8, 0), (8, 2), (15, 4), (8, 6), (8, 8))]
    assert decisions == [None] * 5 and auto.level == "1080p"


def test_tries_one_level_up_later_and_backs_off_after_a_failed_try():
    auto = AutoQuality(has_substream=True)
    _feed(auto, 8.0, 0, 3)                                # -> 720p at t=4
    assert auto.level == "720p"
    assert auto.update(20.0, 100) is None                 # too soon
    assert auto.update(20.0, 4 + 300) == "1080p"          # retry after 5 min
    assert _feed(auto, 8.0, 306, 3)[-1] == "720p"         # 1080p still too slow
    t = 310
    assert auto.update(20.0, t + 300) is None             # back-off doubled to 10 min
    assert auto.update(20.0, t + 600) == "1080p"


def test_without_a_substream_the_floor_is_720p():
    auto = AutoQuality(has_substream=False)
    _feed(auto, 5.0, 0, 3)
    assert auto.level == "720p"
    assert _feed(auto, 5.0, 6, 6) == [None] * 6


def test_drop_substream_when_it_turns_out_unavailable():
    auto = AutoQuality(has_substream=True)
    _feed(auto, 5.0, 0, 6)
    assert auto.level == "360p"
    auto.drop_substream()
    assert auto.level == "720p"


def test_failed_step_up_returns_to_the_working_level_and_backs_off():
    auto = AutoQuality(has_substream=True)
    _feed(auto, 5.0, 0, 6)                      # -> 360p at t=10
    assert auto.level == "360p"
    assert auto.update(20.0, 10 + 300) == "720p"  # tries one level up
    assert auto.probe_failed(312) is True      # ...but it won't open
    assert auto.level == "360p"                # back to what worked
    assert auto.update(20.0, 312 + 300) is None  # and waits longer (doubled)
    assert auto.update(20.0, 312 + 600) == "720p"
    assert AutoQuality(True).probe_failed(0) is False  # only after a step up


def test_display_width_accounts_for_fill_and_tall_views():
    from wyze_print_monitor.quality import display_width_for

    wide, tall = (1600, 700), (640, 720)
    assert display_width_for(*wide, 16 / 9, fill=False) == 1244   # fit: limited by height
    assert display_width_for(*wide, 16 / 9, fill=True) == 1600    # fill: full width
    assert display_width_for(*tall, 16 / 9, fill=False) == 640
    assert display_width_for(*tall, 16 / 9, fill=True) == 1280    # fill in a tall view needs more
    assert display_width_for(0, 100, 16 / 9, fill=True) == 0
