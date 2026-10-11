"""Starting rig for a freshly imported sprite: canonical bones placed from the bounding box.

It is only a starting point for the rigger (Claude or the human in the editor):
joints are proportional guesses and every part is created empty.
"""
from __future__ import annotations

import numpy as np

from .errors import AnimaiError
from .rig import CANONICAL_PARENTS
from .sprite import opaque_bbox

# bone -> (fraction of the bbox height for the joint, z of its part), side view facing right
_HUMANOID = {
    "hips": (0.56, 0), "spine": (0.52, 20), "head": (0.24, 30),
    "arm_r": (0.30, 40), "forearm_r": (0.41, 41), "hand_r": (0.52, 42),
    "arm_l": (0.30, -20), "forearm_l": (0.41, -19), "hand_l": (0.52, -18),
    "thigh_r": (0.60, 10), "shin_r": (0.77, 11), "foot_r": (0.93, 12),
    "thigh_l": (0.60, -10), "shin_l": (0.77, -9), "foot_l": (0.93, -8),
}


def humanoid_template(rgba: np.ndarray, view: str = "side", sprite: str = "sprite.png") -> dict:
    """A valid ``rig.json`` with the 15 canonical bones and one empty part per bone."""
    bbox = opaque_bbox(rgba)
    if bbox is None:
        raise AnimaiError("sprite has no opaque pixel")
    x, y, w, h = bbox
    cx = x + w // 2
    bones, parts = {}, {}
    for name, (fy, z) in _HUMANOID.items():
        jy = min(y + h - 1, y + int(h * fy))
        bones[name] = {"parent": CANONICAL_PARENTS[name], "joint": [cx, jy]}
        parts[name] = {"bone": name, "z": z, "region": {"rects": [], "pixels": []}, "overlap": 2}
    return {"version": 1, "sprite": sprite, "view": view, "template": "humanoid", "pivot": [0.5, 1.0],
            "bones": bones, "parts": parts}
