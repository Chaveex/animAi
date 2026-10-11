"""Pixel-art rotation of a rigid part. Never creates a colour, never blends.

* multiples of 90 degrees: exact pixel permutation;
* ``rotsprite``: Scale2x applied three times (x8), rotation sampled back at the
  original resolution (one sample per destination pixel centre);
* ``nearest``: plain nearest-neighbour sampling.

All three only copy existing pixels, so the palette is preserved by construction.
"""
from __future__ import annotations

import math

import numpy as np

from .errors import AnimaiError
from .kinematics import cos_sin
from .sprite import pack_rgba, unpack_rgba

METHODS = ("rotsprite", "nearest")
_EPS = 1e-7


def scale2x(packed: np.ndarray) -> np.ndarray:
    """Scale2x / EPX on a packed-colour image (transparent = 0 is a colour like another)."""
    p = np.pad(packed, 1)
    a, b = p[:-2, 1:-1], p[1:-1, 2:]     # up, right
    c, d = p[1:-1, :-2], p[2:, 1:-1]     # left, down
    h, w = packed.shape
    out = np.empty((h * 2, w * 2), dtype=packed.dtype)
    out[0::2, 0::2] = np.where((c == a) & (c != d) & (a != b), a, packed)
    out[0::2, 1::2] = np.where((a == b) & (a != c) & (b != d), b, packed)
    out[1::2, 0::2] = np.where((d == c) & (d != b) & (c != a), c, packed)
    out[1::2, 1::2] = np.where((b == d) & (b != a) & (d != c), d, packed)
    return out


def rotate_part(image: np.ndarray, origin: tuple[int, int], joint: tuple[int, int],
                angle: float, method: str = "rotsprite") -> tuple[np.ndarray, tuple[int, int]]:
    """Rotate an RGBA crop around ``joint`` (centre of that pixel), counter-clockwise on screen.

    ``origin`` is the sprite position of the crop's top-left corner. Returns the
    rotated RGBA patch and the sprite position of its top-left corner; the joint
    itself does not move.
    """
    if method not in METHODS:
        raise AnimaiError(f"unknown rotation method '{method}' ({'|'.join(METHODS)})")
    angle = angle % 360.0
    if angle == 0.0:
        return image.copy(), (int(origin[0]), int(origin[1]))
    h, w = image.shape[:2]
    packed = pack_rgba(image)
    factor = 1
    if angle % 90.0 != 0.0 and method == "rotsprite":
        for _ in range(3):
            packed = scale2x(packed)
        factor = 8

    c, s = cos_sin(angle)
    jcx, jcy = joint[0] + 0.5, joint[1] + 0.5
    x0, y0 = origin
    # Destination bounding box = rotated corners of the crop.
    xs, ys = [], []
    for cx, cy in ((x0, y0), (x0 + w, y0), (x0, y0 + h), (x0 + w, y0 + h)):
        dx, dy = cx - jcx, cy - jcy
        xs.append(jcx + dx * c + dy * s)
        ys.append(jcy - dx * s + dy * c)
    dx0, dy0 = math.floor(min(xs) + _EPS), math.floor(min(ys) + _EPS)
    dx1, dy1 = math.ceil(max(xs) - _EPS), math.ceil(max(ys) - _EPS)
    dw, dh = max(1, dx1 - dx0), max(1, dy1 - dy0)

    # Inverse mapping: destination pixel centre -> source point.
    gx = (np.arange(dw, dtype=np.float64) + dx0 + 0.5 - jcx)[None, :]
    gy = (np.arange(dh, dtype=np.float64) + dy0 + 0.5 - jcy)[:, None]
    sx = jcx + gx * c - gy * s - x0
    sy = jcy + gx * s + gy * c - y0
    ix = np.floor(sx * factor + _EPS).astype(np.int64)
    iy = np.floor(sy * factor + _EPS).astype(np.int64)
    valid = (ix >= 0) & (ix < w * factor) & (iy >= 0) & (iy < h * factor)
    out = np.zeros((dh, dw), dtype=packed.dtype)
    out[valid] = packed[iy[valid], ix[valid]]
    return unpack_rgba(out), (dx0, dy0)
