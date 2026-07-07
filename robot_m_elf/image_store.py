"""Atomic JPEG writing helpers shared by camera processes."""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np


def write_jpeg_atomic(path: Path, image: np.ndarray, quality: int = 85) -> bool:
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return False
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded.tobytes())
    os.replace(temporary, path)
    return True
