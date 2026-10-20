"""Tests for the model download (fake HTTP; never touches the network)."""
import hashlib
import io

import pytest

from wyze_print_monitor import failure_model as fm

PAYLOAD = b"model-bytes" * 50_000


class _Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _opener(data=PAYLOAD):
    return lambda request, timeout: _Response(data)


def test_download_verifies_and_installs(tmp_path):
    dest = tmp_path / "m.onnx"
    seen = []
    path = fm.download_model(
        progress=lambda done, total: seen.append((done, total)),
        url="https://example.invalid/m.onnx",
        expected_sha256=hashlib.sha256(PAYLOAD).hexdigest(),
        dest=str(dest),
        opener=_opener(),
    )
    assert path == str(dest) and dest.read_bytes() == PAYLOAD
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))
    assert not (tmp_path / "m.onnx.part").exists()


def test_checksum_mismatch_installs_nothing(tmp_path):
    dest = tmp_path / "m.onnx"
    with pytest.raises(IOError, match="checksum"):
        fm.download_model(expected_sha256="0" * 64, dest=str(dest), opener=_opener())
    assert list(tmp_path.iterdir()) == []


def test_cancel_cleans_up(tmp_path):
    dest = tmp_path / "m.onnx"
    with pytest.raises(fm.DownloadCancelled):
        fm.download_model(cancelled=lambda: True, dest=str(dest), opener=_opener())
    assert list(tmp_path.iterdir()) == []


def test_installed_means_present_with_the_right_size(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, "model_path", lambda: str(tmp_path / "x.onnx"))
    assert not fm.is_installed()
    (tmp_path / "x.onnx").write_bytes(b"short")
    assert not fm.is_installed()
    fm.remove_model()
    assert not (tmp_path / "x.onnx").exists()
    fm.remove_model()  # removing twice is fine


def test_pinned_model_matches_obico():
    assert fm.MODEL_URL.startswith("https://www.obico.io/")
    assert len(fm.MODEL_SHA256) == 64
