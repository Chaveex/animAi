"""Deterministic file I/O: RGBA arrays <-> PNG, JSON with stable formatting.

Every array handled by the core is ``uint8`` of shape ``(H, W, 4)`` (RGBA).
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .errors import AnimaiError


def normalize_rgba(rgba: np.ndarray) -> np.ndarray:
    """Zero the RGB of fully transparent pixels (stable bytes, clean palette)."""
    out = np.ascontiguousarray(rgba, dtype=np.uint8).copy()
    out[out[..., 3] == 0] = 0
    return out


def load_rgba(path: str | Path) -> np.ndarray:
    """Load any image file as an RGBA uint8 array (no cleaning applied)."""
    p = Path(path)
    if not p.is_file():
        raise AnimaiError(f"image not found: {p}")
    try:
        with Image.open(p) as im:
            return np.array(im.convert("RGBA"), dtype=np.uint8)
    except AnimaiError:
        raise
    except Exception as exc:  # unreadable / not an image
        raise AnimaiError(f"cannot read image {p}: {exc}") from exc


def encode_png(arr: np.ndarray) -> bytes:
    """PNG bytes of an RGBA or RGB uint8 array: no metadata, no colour profile, deterministic.

    Single encoder of the whole tool: a frame served by the server and the same
    frame written by the CLI are the same bytes.
    """
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    mode = "RGBA" if arr.shape[2] == 4 else "RGB"
    buf = io.BytesIO()
    Image.fromarray(arr, mode).save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()


def decode_rgba(data: bytes) -> np.ndarray:
    """RGBA uint8 array from the bytes of any image file."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            return np.array(im.convert("RGBA"), dtype=np.uint8)
    except Exception as exc:
        raise AnimaiError(f"cannot read image: {exc}") from exc


def save_png(path: str | Path, arr: np.ndarray) -> None:
    """Save an RGBA or RGB uint8 array as PNG (no metadata, deterministic)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(encode_png(arr))


def read_json(path: str | Path) -> dict:
    p = Path(path)
    if not p.is_file():
        raise AnimaiError(f"file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise AnimaiError(f"invalid JSON in {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise AnimaiError(f"{p}: top-level JSON value must be an object")
    return data


def dumps_json(obj) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=True) + "\n"


def write_json(path: str | Path, obj) -> None:
    """Write JSON with fixed formatting and LF line endings on every OS."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(dumps_json(obj).encode("utf-8"))
