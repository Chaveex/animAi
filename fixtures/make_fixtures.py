"""Generate the reference sprites (and their rig.json) used by the test suite.

Fully deterministic: no randomness at all, every pixel comes from integer
geometry declared in ``SPECS``.

    python fixtures/make_fixtures.py            # (re)write every fixture
    python fixtures/make_fixtures.py --check    # exit 1 if files on disk are stale
    python fixtures/make_fixtures.py --preview out.png   # x4 contact sheet to look at

Layout, one directory per fixture::

    fixtures/<name>/source.png   raw input given to ``animai prepare``
                                 (may be upscaled, or have a flat background)
    fixtures/<name>/sprite.png   the cleaned sprite ``prepare`` is expected to
                                 produce: native resolution, binary alpha
    fixtures/<name>/rig.json     valid rig (docs/schemas.md), coordinates in
                                 ``sprite.png`` space, canonical bone names
    fixtures/<name>/meta.json    facts the tests rely on (sizes, scale, palette)
    fixtures/manifest.json       list of fixtures

Every character is a side-view humanoid facing right. The far-side limbs
(``*_l``) are darker and sit behind the body, the near-side limbs (``*_r``) in
front. Each opaque pixel belongs to exactly one part; the regions written in
rig.json are the exact, non-overlapping decomposition of that label map.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent

CANONICAL_BONES = (
    "hips", "spine", "head",
    "arm_r", "forearm_r", "hand_r",
    "arm_l", "forearm_l", "hand_l",
    "thigh_r", "shin_r", "foot_r",
    "thigh_l", "shin_l", "foot_l",
)

# Back-to-front paint order. A part painted later hides the earlier ones.
PART_ORDER = (
    "arm_l", "forearm_l", "hand_l",
    "thigh_l", "shin_l", "foot_l",
    "hips", "torso", "head",
    "thigh_r", "shin_r", "foot_r",
    "arm_r", "forearm_r", "hand_r",
)
PART_BONE = {name: ("spine" if name == "torso" else name) for name in PART_ORDER}
# Unique z per part (hips = 0) so the draw order never depends on a tie-break.
PART_Z = {name: i - PART_ORDER.index("hips") for i, name in enumerate(PART_ORDER)}
PART_OVERLAP = {"hips": 2, "torso": 2}  # every other part: 1 (unless Spec.overlaps says so)

BONE_PARENT = {
    "hips": None, "spine": "hips", "head": "spine",
    "arm_r": "spine", "forearm_r": "arm_r", "hand_r": "forearm_r",
    "arm_l": "spine", "forearm_l": "arm_l", "hand_l": "forearm_l",
    "thigh_r": "hips", "shin_r": "thigh_r", "foot_r": "shin_r",
    "thigh_l": "hips", "shin_l": "thigh_l", "foot_l": "shin_l",
}


@dataclass(frozen=True)
class Spec:
    name: str
    description: str
    canvas: tuple[int, int]          # native (w, h)
    ground_margin: int               # transparent rows under the feet
    head: tuple[int, int]            # (w, h)
    torso_w: int                     # even; each leg is torso_w // 2 wide
    torso_h: int
    hips_h: int
    thigh_h: int
    shin_h: int
    foot_h: int
    toe: int                         # how far the near foot sticks out forward
    arm_w: int
    upper_h: int
    fore_h: int
    hand_h: int                      # 0 = no hand part / no hand bones
    colors: dict
    outline: bool = False            # 1 px dark outline around the silhouette
    background: tuple[int, int, int] | None = None  # flat opaque bg in source.png
    scale: int = 1                   # source.png = sprite.png upscaled NN by this
    use_pixels: bool = False         # put single-row runs in region.pixels, not rects
    overlaps: tuple = ()             # ((part, overlap), ...) overriding PART_OVERLAP


HERO_COLORS = {
    "skin": (238, 195, 154), "hair": (102, 57, 49), "eye": (34, 32, 52),
    "shirt": (91, 110, 225), "sleeve": (99, 155, 255), "shirt_far": (48, 60, 130),
    "belt": (138, 111, 48), "pants": (75, 105, 47), "pants_far": (50, 60, 57),
    "shoe": (69, 40, 60), "hand": (238, 195, 154),
}
KNIGHT_COLORS = {
    "skin": (217, 160, 102), "hair": (155, 173, 183), "eye": (24, 20, 37),
    "shirt": (132, 126, 135), "sleeve": (203, 219, 252), "shirt_far": (89, 86, 82),
    "belt": (172, 50, 50), "pants": (105, 106, 106), "pants_far": (63, 63, 116),
    "shoe": (50, 60, 57), "hand": (143, 86, 59),
}
ROGUE_COLORS = {
    "skin": (215, 123, 186), "hair": (118, 66, 138), "eye": (251, 242, 54),
    "shirt": (55, 148, 110), "sleeve": (106, 190, 48), "shirt_far": (36, 82, 59),
    "belt": (223, 113, 38), "pants": (143, 86, 59), "pants_far": (102, 57, 49),
    "shoe": (238, 195, 154), "hand": (217, 87, 99), "outline": (20, 12, 28),
}
MAGE_COLORS = {
    "skin": (255, 219, 172), "hair": (223, 113, 38), "eye": (0, 0, 0),
    "shirt": (118, 66, 138), "sleeve": (166, 100, 190), "shirt_far": (69, 40, 60),
    "belt": (251, 242, 54), "pants": (63, 63, 116), "pants_far": (34, 32, 52),
    "shoe": (172, 50, 50), "hand": (255, 219, 172),
}

_HERO64 = Spec(
    name="hero64",
    description="64x64, flat colours, no outline, transparent background",
    canvas=(64, 64), ground_margin=4, head=(12, 12),
    torso_w=10, torso_h=12, hips_h=4, thigh_h=8, shin_h=8, foot_h=3, toe=3,
    arm_w=4, upper_h=8, fore_h=7, hand_h=0, colors=HERO_COLORS,
)

SPECS: tuple[Spec, ...] = (
    _HERO64,
    Spec(
        name="knight96",
        description="96x96, bulky proportions, separate hand parts, transparent background",
        canvas=(96, 96), ground_margin=6, head=(18, 16),
        torso_w=16, torso_h=20, hips_h=6, thigh_h=13, shin_h=13, foot_h=5, toe=5,
        arm_w=6, upper_h=12, fore_h=10, hand_h=5, colors=KNIGHT_COLORS,
        # 8 px wide legs: with overlap 1 the knee opens by 2 px on the walk (measured
        # by the lead dev, wave 2); the thigh needs a 3 px margin under the shin, and the
        # shin 2 px under the foot (the ankle opened by 1 px on walk frames 1 and 5).
        overlaps=(("thigh_l", 3), ("thigh_r", 3), ("shin_l", 2), ("shin_r", 2)),
    ),
    Spec(
        name="rogue80_outline",
        description="80x80, 1 px dark outline around the silhouette, uses region.pixels",
        canvas=(80, 80), ground_margin=5, head=(14, 13),
        torso_w=12, torso_h=15, hips_h=5, thigh_h=10, shin_h=10, foot_h=4, toe=4,
        arm_w=5, upper_h=10, fore_h=8, hand_h=4, colors=ROGUE_COLORS,
        outline=True, use_pixels=True,
    ),
    Spec(
        name="mage64x80_bg",
        description="64x80 (non square), slim, flat opaque magenta background to key out",
        canvas=(64, 80), ground_margin=6, head=(12, 12),
        torso_w=8, torso_h=16, hips_h=4, thigh_h=11, shin_h=11, foot_h=3, toe=3,
        arm_w=4, upper_h=10, fore_h=9, hand_h=0, colors=MAGE_COLORS,
        background=(255, 0, 255),
    ),
    replace(
        _HERO64,
        name="hero64_x4",
        description="hero64 upscaled x4 nearest-neighbour (256x256 file, real grid 64x64)",
        scale=4,
    ),
)
FIXTURE_NAMES = tuple(s.name for s in SPECS)


# --------------------------------------------------------------------------- #
# Drawing
# --------------------------------------------------------------------------- #

def _geometry(spec: Spec) -> dict:
    w, h = spec.canvas
    leg_w = spec.torso_w // 2
    ground = h - spec.ground_margin          # first transparent row under the feet
    foot_top = ground - spec.foot_h
    shin_top = foot_top - spec.shin_h
    hip_y = shin_top - spec.thigh_h          # top of the thighs
    hips_top = hip_y - spec.hips_h
    torso_top = hips_top - spec.torso_h
    head_top = torso_top - spec.head[1]
    tx = w // 2 - spec.torso_w // 2 - 1      # left edge of torso / far leg
    near_x = tx + leg_w                      # left edge of near leg
    head_x = tx + spec.torso_w // 2 - spec.head[0] // 2 + 1
    arm_r_x = tx + (spec.torso_w - spec.arm_w) // 2
    arm_l_x = tx + spec.torso_w - 1          # far arm peeks out in front of the torso
    arm_top = torso_top + 1
    elbow_y = arm_top + spec.upper_h
    wrist_y = elbow_y + spec.fore_h
    assert head_top >= 1 and tx >= 1, f"{spec.name}: character does not fit the canvas"
    assert arm_l_x + spec.arm_w < w and near_x + leg_w + spec.toe < w

    rects = {  # part -> (x, y, w, h)
        "arm_l": (arm_l_x, arm_top, spec.arm_w, spec.upper_h),
        "forearm_l": (arm_l_x, elbow_y, spec.arm_w, spec.fore_h),
        "thigh_l": (tx, hip_y, leg_w, spec.thigh_h),
        "shin_l": (tx, shin_top, leg_w, spec.shin_h),
        "foot_l": (tx, foot_top, leg_w + spec.toe, spec.foot_h),
        "hips": (tx, hips_top, spec.torso_w, spec.hips_h),
        "torso": (tx, torso_top, spec.torso_w, spec.torso_h),
        "head": (head_x, head_top, spec.head[0], spec.head[1]),
        "thigh_r": (near_x, hip_y, leg_w, spec.thigh_h),
        "shin_r": (near_x, shin_top, leg_w, spec.shin_h),
        "foot_r": (near_x, foot_top, leg_w + spec.toe, spec.foot_h),
        "arm_r": (arm_r_x, arm_top, spec.arm_w, spec.upper_h),
        "forearm_r": (arm_r_x, elbow_y, spec.arm_w, spec.fore_h),
    }
    if spec.hand_h:
        rects["hand_l"] = (arm_l_x, wrist_y, spec.arm_w, spec.hand_h)
        rects["hand_r"] = (arm_r_x, wrist_y, spec.arm_w, spec.hand_h)

    cx = tx + spec.torso_w // 2
    arm_r_cx = arm_r_x + spec.arm_w // 2
    arm_l_cx = arm_l_x + spec.arm_w // 2
    near_cx = near_x + leg_w // 2
    far_cx = tx + leg_w // 2
    joints = {
        "hips": (cx, hips_top + spec.hips_h // 2),
        "spine": (cx, hips_top),
        "head": (head_x + spec.head[0] // 2, torso_top),
        "arm_r": (arm_r_cx, arm_top + spec.arm_w // 2),
        "forearm_r": (arm_r_cx, elbow_y),
        "arm_l": (arm_l_cx, arm_top + spec.arm_w // 2),
        "forearm_l": (arm_l_cx, elbow_y),
        "thigh_r": (near_cx, hip_y),
        "shin_r": (near_cx, shin_top),
        "foot_r": (near_cx, foot_top),
        "thigh_l": (far_cx, hip_y),
        "shin_l": (far_cx, shin_top),
        "foot_l": (far_cx, foot_top),
    }
    if spec.hand_h:
        joints["hand_r"] = (arm_r_cx, wrist_y)
        joints["hand_l"] = (arm_l_cx, wrist_y)
    return {"rects": rects, "joints": joints}


_PART_COLOR = {
    "arm_l": "shirt_far", "forearm_l": "skin", "hand_l": "hand",
    "thigh_l": "pants_far", "shin_l": "pants_far", "foot_l": "shoe",
    "hips": "belt", "torso": "shirt",
    "thigh_r": "pants", "shin_r": "pants", "foot_r": "shoe",
    "arm_r": "sleeve", "forearm_r": "skin", "hand_r": "hand",
}


def _paint_head(spec: Spec, rgb: np.ndarray, labels: np.ndarray, rect, label: int) -> None:
    x0, y0, w, h = rect
    corner = 1 if w < 16 else 2
    hair_rows = max(2, h // 4)
    hair_cols = max(2, w // 4)
    eye_x, eye_y = w - 3, h // 2 - 1
    eye_h = 1 if h < 16 else 2
    for dy in range(h):
        for dx in range(w):
            ex, ey = min(dx, w - 1 - dx), min(dy, h - 1 - dy)
            if ex + ey < corner:
                continue  # rounded corner
            if dy < hair_rows or (dx < hair_cols and dy < (2 * h) // 3):
                key = "hair"
            elif dx == eye_x and eye_y <= dy < eye_y + eye_h:
                key = "eye"
            else:
                key = "skin"
            rgb[y0 + dy, x0 + dx] = spec.colors[key]
            labels[y0 + dy, x0 + dx] = label


def build(spec: Spec):
    """Return (sprite RGBA uint8 HxWx4, labels int HxW (0 = none), geometry)."""
    w, h = spec.canvas
    geo = _geometry(spec)
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    labels = np.zeros((h, w), dtype=np.int16)
    for index, part in enumerate(PART_ORDER, start=1):
        rect = geo["rects"].get(part)
        if rect is None:
            continue
        if part == "head":
            _paint_head(spec, rgb, labels, rect, index)
            continue
        x, y, rw, rh = rect
        rgb[y:y + rh, x:x + rw] = spec.colors[_PART_COLOR[part]]
        labels[y:y + rh, x:x + rw] = index

    opaque = labels > 0
    if spec.outline:
        padded = np.pad(opaque, 1, constant_values=False)
        inner = (padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
        rgb[opaque & ~inner] = spec.colors["outline"]

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., :3][opaque] = rgb[opaque]
    rgba[..., 3][opaque] = 255
    return rgba, labels, geo


def _source_image(spec: Spec, rgba: np.ndarray) -> Image.Image:
    if spec.background is not None:
        flat = np.empty(rgba.shape[:2] + (3,), dtype=np.uint8)
        flat[:] = spec.background
        mask = rgba[..., 3] == 255
        flat[mask] = rgba[..., :3][mask]
        image = Image.fromarray(flat, "RGB")
    else:
        image = Image.fromarray(rgba, "RGBA")
    if spec.scale != 1:
        image = image.resize(
            (image.width * spec.scale, image.height * spec.scale), Image.NEAREST
        )
    return image


# --------------------------------------------------------------------------- #
# rig.json
# --------------------------------------------------------------------------- #

def _decompose(mask: np.ndarray):
    """Exact cover of a boolean mask by disjoint [x, y, w, h] rects.

    Horizontal runs, merged with the identical run of the previous row.
    """
    done, active = [], {}
    for y in range(mask.shape[0]):
        row = mask[y]
        runs, x, width = [], 0, mask.shape[1]
        while x < width:
            if row[x]:
                start = x
                while x < width and row[x]:
                    x += 1
                runs.append((start, x - start))
            else:
                x += 1
        current = {}
        for run in runs:
            if run in active:
                y0, height = active.pop(run)
                current[run] = (y0, height + 1)
            else:
                current[run] = (y, 1)
        done.extend([rx, y0, rw, rh] for (rx, rw), (y0, rh) in active.items())
        active = current
    done.extend([rx, y0, rw, rh] for (rx, rw), (y0, rh) in active.items())
    return sorted(done, key=lambda r: (r[1], r[0]))


def build_rig(spec: Spec, labels: np.ndarray, geo: dict) -> dict:
    present = [p for p in PART_ORDER if p in geo["rects"]]
    overlaps = {**PART_OVERLAP, **dict(spec.overlaps)}
    bones = {
        bone: {"parent": BONE_PARENT[bone], "joint": [int(v) for v in geo["joints"][bone]]}
        for bone in CANONICAL_BONES if bone in geo["joints"]
    }
    parts = {}
    for part in present:
        rects = _decompose(labels == PART_ORDER.index(part) + 1)
        pixels = []
        if spec.use_pixels:
            # single-row runs (rounded head, outline steps...) go pixel by pixel
            pixels = [[r[0] + dx, r[1]] for r in rects if r[3] == 1 for dx in range(r[2])]
            rects = [r for r in rects if r[3] != 1]
        parts[part] = {
            "bone": PART_BONE[part],
            "z": PART_Z[part],
            "region": {"rects": rects, "pixels": pixels},
            "overlap": overlaps.get(part, 1),
        }
    ik = {
        "foot_r": {"chain": ["thigh_r", "shin_r"], "target_bone": "foot_r"},
        "foot_l": {"chain": ["thigh_l", "shin_l"], "target_bone": "foot_l"},
    }
    if spec.hand_h:
        ik["hand_r"] = {"chain": ["arm_r", "forearm_r"], "target_bone": "hand_r"}
        ik["hand_l"] = {"chain": ["arm_l", "forearm_l"], "target_bone": "hand_l"}
    return {
        "version": 1,
        "sprite": "sprite.png",
        "view": "side",
        "template": "humanoid",
        "pivot": [0.5, 1.0],
        "bones": bones,
        "parts": parts,
        "ik": ik,
    }


def _compact_json(doc) -> bytes:
    """Stable, readable JSON: indent 2 but number lists kept on one line."""
    def is_flat(value):
        return isinstance(value, list) and all(isinstance(v, (int, float)) for v in value)

    def is_rows(value):
        return isinstance(value, list) and value and all(is_flat(v) for v in value)

    def dump(value, indent):
        pad, inner = "  " * indent, "  " * (indent + 1)
        if isinstance(value, dict):
            if not value:
                return "{}"
            items = [f"{inner}{json.dumps(k)}: {dump(v, indent + 1)}" for k, v in value.items()]
            return "{\n" + ",\n".join(items) + "\n" + pad + "}"
        if is_flat(value):
            return json.dumps(value)
        if is_rows(value):
            return "[" + ", ".join(json.dumps(v) for v in value) + "]"
        if isinstance(value, list):
            if not value:
                return "[]"
            items = [inner + dump(v, indent + 1) for v in value]
            return "[\n" + ",\n".join(items) + "\n" + pad + "]"
        return json.dumps(value)

    return (dump(doc, 0) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False, compress_level=9)
    return buffer.getvalue()


def _palette(rgba: np.ndarray) -> list[list[int]]:
    colours = np.unique(rgba[rgba[..., 3] == 255][:, :3], axis=0)
    return [[int(c) for c in colour] for colour in colours]


def generate() -> dict[str, bytes]:
    """Every fixture file as {path relative to fixtures/: bytes}."""
    files: dict[str, bytes] = {}
    manifest = []
    for spec in SPECS:
        rgba, labels, geo = build(spec)
        source = _source_image(spec, rgba)
        rig = build_rig(spec, labels, geo)
        palette = _palette(rgba)
        if spec.background is not None:
            assert list(spec.background) not in palette, "background colour is used by the sprite"
        meta = {
            "name": spec.name,
            "description": spec.description,
            "source": "source.png",
            "source_size": [source.width, source.height],
            "source_mode": source.mode,
            "sprite": "sprite.png",
            "native_size": [spec.canvas[0], spec.canvas[1]],
            "scale": spec.scale,
            "background": list(spec.background) if spec.background else None,
            "outline": spec.outline,
            "outline_color": list(spec.colors["outline"]) if spec.outline else None,
            "uses_region_pixels": spec.use_pixels,
            "opaque_pixels": int((rgba[..., 3] == 255).sum()),
            "palette": palette,
            "parts": list(rig["parts"]),
            "bones": list(rig["bones"]),
        }
        files[f"{spec.name}/source.png"] = _png_bytes(source)
        files[f"{spec.name}/sprite.png"] = _png_bytes(Image.fromarray(rgba, "RGBA"))
        files[f"{spec.name}/rig.json"] = _compact_json(rig)
        files[f"{spec.name}/meta.json"] = _compact_json(meta)
        manifest.append({
            "name": spec.name, "description": spec.description,
            "source_size": meta["source_size"], "native_size": meta["native_size"],
            "colors": len(palette),
        })
    files["manifest.json"] = _compact_json({"fixtures": manifest})
    return files


def _same(path: str, expected: bytes, actual: bytes) -> bool:
    if expected == actual:
        return True
    if not path.endswith(".png"):
        return False
    # PNG bytes may differ across Pillow/zlib versions: compare decoded content.
    a, b = Image.open(io.BytesIO(expected)), Image.open(io.BytesIO(actual))
    return a.mode == b.mode and a.size == b.size and a.tobytes() == b.tobytes()


def stale_files(root: Path = ROOT) -> list[str]:
    """Paths whose on-disk content differs from what the script generates."""
    stale = []
    for rel, data in generate().items():
        target = root / rel
        if not target.is_file() or not _same(rel, data, target.read_bytes()):
            stale.append(rel)
    return stale


def write_all(root: Path = ROOT) -> list[str]:
    files = generate()
    for rel, data in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return sorted(files)


def write_preview(path: Path, zoom: int = 4) -> None:
    """Side-by-side contact sheet (sprite.png of each fixture, NN-zoomed)."""
    tiles = []
    for spec in SPECS:
        rgba, _, _ = build(spec)
        tile = Image.new("RGBA", (spec.canvas[0], spec.canvas[1]), (128, 128, 128, 255))
        tile.alpha_composite(Image.fromarray(rgba, "RGBA"))
        tiles.append(tile.resize((tile.width * zoom, tile.height * zoom), Image.NEAREST))
    sheet = Image.new("RGBA", (sum(t.width for t in tiles) + 8 * (len(tiles) + 1),
                               max(t.height for t in tiles) + 16), (40, 40, 40, 255))
    x = 8
    for tile in tiles:
        sheet.paste(tile, (x, 8))
        x += tile.width + 8
    sheet.save(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if files on disk are stale")
    parser.add_argument("--preview", type=Path, help="also write a zoomed contact sheet here")
    args = parser.parse_args(argv)
    if args.preview:
        write_preview(args.preview)
    if args.check:
        stale = stale_files()
        for rel in stale:
            print(f"stale: {rel}")
        return 1 if stale else 0
    for rel in write_all():
        print(f"wrote fixtures/{rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
