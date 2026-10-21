"""The generated alert sounds are valid WAVs (no audio device needed)."""
import io
import wave

import pytest

pytest.importorskip("PySide6.QtCore")
from wyze_print_monitor.ui.alarm import make_wav  # noqa: E402


@pytest.mark.parametrize("kind, low, high", [("alarm", 1.2, 2.0), ("chime", 0.3, 0.6)])
def test_sounds_are_short_mono_wavs(kind, low, high):
    with wave.open(io.BytesIO(make_wav(kind))) as w:
        assert (w.getnchannels(), w.getsampwidth()) == (1, 2)
        assert low < w.getnframes() / w.getframerate() < high
