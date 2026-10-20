"""The print-failure model: where it lives, and downloading it (no Qt).

The model isn't shipped with the app (it's ~200 MB and AGPL-licensed, by
Obico): the user downloads it from Settings, straight from Obico, and it's
only used once its SHA-256 matches the published one.
"""
from __future__ import annotations

import hashlib
import os
import urllib.request
from typing import Callable

from .config import config_dir

MODEL_URL = "https://www.obico.io/static_pub/ml-models/model-weights-5a6b1be1fa.onnx"
# From obico-server ml_api/model/model-weights.onnx.sha256
MODEL_SHA256 = "0a6ebd8e30dbf6a450c50f9c0a5406f04ba7eb1c99fd5996e888c78bb383b9aa"
MODEL_SIZE = 202_223_918
MODEL_FILE = "obico-failure-detection.onnx"
MODEL_LICENSE_URL = "https://github.com/TheSpaghettiDetective/obico-server/blob/release/LICENSE"

_CHUNK = 1 << 20


class DownloadCancelled(Exception):
    pass


def model_dir() -> str:
    return os.path.join(config_dir(), "models")


def model_path() -> str:
    return os.path.join(model_dir(), MODEL_FILE)


def is_installed() -> bool:
    """Present with the right size (the hash was checked when it arrived)."""
    try:
        return os.path.getsize(model_path()) == MODEL_SIZE
    except OSError:
        return False


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_model(
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    url: str = MODEL_URL,
    expected_sha256: str = MODEL_SHA256,
    dest: str | None = None,
    opener=urllib.request.urlopen,
) -> str:
    """Download, verify, and move the model into place; returns its path.

    Writes to a ``.part`` file first, so a cancelled or corrupt download
    never leaves a model that looks installed.
    """
    dest = dest or model_path()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    digest = hashlib.sha256()
    done = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "wyze-print-monitor"})
        with opener(request, timeout=30) as response, open(part, "wb") as out:
            total = int(response.headers.get("Content-Length") or MODEL_SIZE)
            while True:
                if cancelled is not None and cancelled():
                    raise DownloadCancelled()
                chunk = response.read(_CHUNK)
                if not chunk:
                    break
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total)
        if digest.hexdigest() != expected_sha256:
            raise IOError("The downloaded model didn't match its checksum; nothing was installed.")
        os.replace(part, dest)
        return dest
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass


def remove_model() -> None:
    try:
        os.remove(model_path())
    except FileNotFoundError:
        pass
