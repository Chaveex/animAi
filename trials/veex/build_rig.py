"""Build rig.json for the veex boxer (126 x 134, guard stance facing right).

The parts are cut by rules (colour class + position) written after looking at
the zoomed sprite; the result is checked on the label map of ``animai rig``.
Run from the repository root: ``python trials/veex/build_rig.py``.
"""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
a = np.asarray(Image.open(HERE / "sprite.png").convert("RGBA")).astype(int)
H, W = a.shape[:2]


def cls(p) -> str:
    r, g, b, al = p
    if al == 0:
        return " "
    lum = (r * 3 + g * 6 + b) / 10
    if lum < 38:
        return "#"                        # dark / outline
    if b > r + 8 and b >= g - 5:
        return "b"                        # denim
    if r > 150 and g > 110 and b > 80 and r - b > 50 and g > b:
        return "s"                        # skin
    if r > g * 1.7 and r > 90:
        return "r"                        # glove red
    if min(r, g, b) > 170:
        return "w"
    if r > g > b and r - b > 25:
        return "h"                        # hair / tan
    return "g"


C = [[cls(a[y, x]) for x in range(W)] for y in range(H)]

# near glove (drawn in front of the chest): [x0, x1] per row
GLOVE_R = {36: (63, 69), 37: (62, 68), 38: (61, 69), 39: (61, 70), 40: (60, 71), 41: (60, 71), 42: (59, 71),
           43: (59, 71), 44: (57, 70), 45: (56, 69), 46: (55, 66), 47: (54, 65), 48: (55, 63), 49: (56, 63),
           50: (57, 63), 51: (57, 59), 52: (57, 59)}
# bottom of the near sleeve (the elbow is a wedge pointing down)
ARM_R_BOTTOM = {43: 57, 44: 58, 45: 59, 46: 60, 47: 61, 48: 61, 49: 60, 50: 60, 51: 59}


def part_of(x: int, y: int) -> str | None:
    c = C[y][x]
    if c == " ":
        return None
    # --- legs and feet
    if y >= 77:
        left = x < 57
        if y <= 90:
            return "thigh_r" if left else "thigh_l"
        if left:
            foot = y >= 113 or (y >= 111 and x <= 34 and c != "b")
            return "foot_r" if foot else "shin_r"
        foot = y >= 115 or (y >= 112 and x >= 78 and c != "b")
        return "foot_l" if foot else "shin_l"
    if y >= 68:
        return "hips"
    # --- gloves
    if y in GLOVE_R and GLOVE_R[y][0] <= x <= GLOVE_R[y][1] and c != "b":
        return "hand_r"
    if x >= 80 and c != "b":
        if y <= 47 or (y == 48 and x >= 82) or (y == 49 and x >= 83) or (y == 50 and x >= 84):
            return "hand_l"
    # --- forearms (bare skin)
    if 48 <= y <= 56 and 52 <= x <= 56 and c in "sh":
        return "forearm_r"
    if 47 <= y <= 57 and x >= 78 and c in "shr":
        return "forearm_l"
    # --- head: hair, face, chin
    if y <= 32 and x <= 76:
        return "head"
    if y <= 39 and 51 <= x <= 69 and (c in "shr" or (c == "#" and y <= 36 and x <= 62)):
        return "head"
    # --- arms (denim sleeves)
    if y >= 33 and x <= 51 and y <= ARM_R_BOTTOM.get(x, 56):
        return "arm_r"
    if (x >= 72 and y >= 35) or (x >= 70 and 35 <= y <= 39):
        return "arm_l"
    return "torso"


labels: dict[tuple[int, int], str] = {}
loose = []
for y in range(H):
    for x in range(W):
        p = part_of(x, y)
        if p:
            labels[(x, y)] = p
        elif C[y][x] != " ":
            loose.append((x, y))

# Small islands cut off from the rest of their part (a stray pixel on the wrong side of a rule)
# go to the neighbouring part that touches them most.
for _ in range(3):
    seen: set = set()
    for start, name in list(labels.items()):
        if start in seen:
            continue
        comp, queue = [start], deque([start])
        seen.add(start)
        while queue:
            x, y = queue.popleft()
            for n in ((x, y - 1), (x - 1, y), (x + 1, y), (x, y + 1)):
                if n not in seen and labels.get(n) == name:
                    seen.add(n)
                    comp.append(n)
                    queue.append(n)
        if len(comp) > 5:
            continue
        around: dict[str, int] = {}
        for x, y in comp:
            for n in ((x, y - 1), (x - 1, y), (x + 1, y), (x, y + 1)):
                other = labels.get(n)
                if other and other != name:
                    around[other] = around.get(other, 0) + 1
        if around:
            best = max(sorted(around), key=around.get)
            for p in comp:
                labels[p] = best

BONES = {
    "hips": (None, [57, 72]),
    "spine": ("hips", [57, 66]),
    "head": ("spine", [59, 36]),
    "arm_r": ("spine", [45, 40]),
    "forearm_r": ("arm_r", [52, 54]),
    "hand_r": ("forearm_r", [57, 49]),
    "arm_l": ("spine", [75, 39]),
    "forearm_l": ("arm_l", [77, 56]),
    "hand_l": ("forearm_l", [85, 47]),
    "thigh_r": ("hips", [48, 76]),
    "shin_r": ("thigh_r", [42, 91]),
    "foot_r": ("shin_r", [32, 112]),
    "thigh_l": ("hips", [66, 76]),
    "shin_l": ("thigh_l", [74, 91]),
    "foot_l": ("shin_l", [76, 113]),
}
# name: (bone, z, overlap). The lead arm (screen right) is behind the torso, the rear arm in front.
PARTS = {
    "thigh_l": ("thigh_l", -10, 2), "shin_l": ("shin_l", -9, 2), "foot_l": ("foot_l", -8, 1),
    "arm_l": ("arm_l", -6, 2), "forearm_l": ("forearm_l", -5, 2), "hand_l": ("hand_l", -4, 1),
    "hips": ("hips", 0, 2),
    "thigh_r": ("thigh_r", 2, 2), "shin_r": ("shin_r", 3, 2), "foot_r": ("foot_r", 4, 1),
    "torso": ("spine", 10, 2), "head": ("head", 12, 1),
    "arm_r": ("arm_r", 20, 2), "forearm_r": ("forearm_r", 21, 1), "hand_r": ("hand_r", 22, 1),
}


def runs(points: list[tuple[int, int]]) -> list[list[int]]:
    """Horizontal runs [x, y, w, 1] covering the points."""
    out = []
    for x, y in sorted(points, key=lambda p: (p[1], p[0])):
        if out and out[-1][1] == y and out[-1][0] + out[-1][2] == x:
            out[-1][2] += 1
        else:
            out.append([x, y, 1, 1])
    return out




# --- Replacement image: the lead arm stretched out for the impact of the jab -------------------
# A draft assembled from the sprite's own pixels, all by exact quarter turns (no resampling):
# the sleeve turned 90 degrees, a bare forearm drawn with the skin tones, the glove turned 90
# degrees. Meant to be redrawn by hand; the file is only written when it does not exist yet.
def crop(name: str, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    out = np.zeros((y1 - y0 + 1, x1 - x0 + 1, 4), dtype=np.uint8)
    for (x, y), v in labels.items():
        if v == name and x0 <= x <= x1 and y0 <= y <= y1:
            out[y - y0, x - x0] = a[y, x]
    return out


def paste(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
    h, w = src.shape[:2]
    mask = src[..., 3] > 0
    dst[y:y + h, x:x + w][mask] = src[mask]


def lum(c) -> float:
    return (int(c[0]) * 3 + int(c[1]) * 6 + int(c[2])) / 10


sleeve = np.rot90(crop("arm_l", 70, 35, 79, 55), 1)            # shoulder on the left, elbow on the right
glove = np.rot90(crop("hand_l", 80, 34, 93, 50), -1)           # cuff on the left, fist on the right
skin = sorted({tuple(a[y, x]) for (x, y), v in labels.items() if v == "forearm_l" and C[y][x] == "s"}, key=lum)
dark = min((tuple(a[y, x]) for (x, y), v in labels.items() if v == "hand_l"), key=lum)
tones = [dark, skin[-1], skin[len(skin) // 2], skin[len(skin) // 2], skin[0], dark]
forearm = np.array([[t] * 9 for t in tones], dtype=np.uint8)
arm = np.zeros((glove.shape[0], sleeve.shape[1] + 5 + glove.shape[1], 4), dtype=np.uint8)
mid = arm.shape[0] // 2
paste(arm, forearm, sleeve.shape[1] - 2, mid - 3)
paste(arm, sleeve, 0, mid - sleeve.shape[0] // 2)
paste(arm, glove, sleeve.shape[1] + 5, 0)
SWAP = HERE / "swaps" / "arm_l_jab.png"
SWAP.parent.mkdir(exist_ok=True)
if not SWAP.exists():
    Image.fromarray(arm).save(SWAP)
# the shoulder joint (75, 39) of the sleeve crop, after the quarter turn
ANCHOR = [39 - 35, mid - sleeve.shape[0] // 2 + (79 - 75)]

rig = {
    "swaps": {"arm_l_jab": {"image": "swaps/arm_l_jab.png", "bone": "arm_l", "anchor": ANCHOR,
                            "hides": ["arm_l", "forearm_l", "hand_l"]}},
    "version": 1, "sprite": "sprite.png", "view": "3/4", "template": "humanoid", "pivot": [0.5, 1.0],
    "_comment": "generated by build_rig.py",
    "bones": {n: {"parent": p, "joint": j} for n, (p, j) in BONES.items()},
    "parts": {n: {"bone": b, "z": z, "overlap": o,
                  "region": {"rects": runs([p for p, v in labels.items() if v == n])}}
              for n, (b, z, o) in PARTS.items()},
}
(HERE / "rig.json").write_text(json.dumps(rig, separators=(",", ":")).replace('},"', '},\n"'), encoding="utf-8")
counts = {n: sum(1 for v in labels.values() if v == n) for n in PARTS}
print(counts, "loose", len(loose))
