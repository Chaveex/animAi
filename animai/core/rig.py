"""rig.json: validation, label map construction, cutting the sprite into rigid parts."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .errors import AnimaiError
from .imageio import read_json
from .morph import dilate4
from .sprite import pack_rgb, parse_hex_color

CANONICAL_BONES = [
    "hips", "spine", "head",
    "arm_r", "forearm_r", "hand_r", "arm_l", "forearm_l", "hand_l",
    "thigh_r", "shin_r", "foot_r", "thigh_l", "shin_l", "foot_l",
]
CANONICAL_PARENTS = {
    "hips": None, "spine": "hips", "head": "spine",
    "arm_r": "spine", "forearm_r": "arm_r", "hand_r": "forearm_r",
    "arm_l": "spine", "forearm_l": "arm_l", "hand_l": "forearm_l",
    "thigh_r": "hips", "shin_r": "thigh_r", "foot_r": "shin_r",
    "thigh_l": "hips", "shin_l": "thigh_l", "foot_l": "shin_l",
}
VIEWS = ("side", "front", "3/4", "top-down")
UNASSIGNED = -1


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _int_pair(v) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 2 and all(_is_int(c) for c in v)


def _check_shapes(where: str, region: dict) -> None:
    for key in ("rects", "pixels", "polygons"):
        if not isinstance(region.get(key, []), list):
            raise AnimaiError(f"{where}.{key} must be a list")
    for r in region.get("rects", []):
        if not (isinstance(r, list) and len(r) == 4 and all(_is_int(c) for c in r)
                and r[2] >= 0 and r[3] >= 0):
            raise AnimaiError(f"{where}.rects: expected [x, y, w, h] integers, got {r}")
    for p in region.get("pixels", []):
        if not _int_pair(p):
            raise AnimaiError(f"{where}.pixels: expected [x, y] integers, got {p}")
    for poly in region.get("polygons", []):
        if not (isinstance(poly, list) and len(poly) >= 3 and all(_int_pair(p) for p in poly)):
            raise AnimaiError(f"{where}.polygons: expected a list of >= 3 [x, y] integer points")


RIG_KEYS = {"version", "sprite", "view", "template", "pivot", "bones", "parts", "ik", "outline", "outline_mode",
            "rest_offsets", "fill_holes", "swaps"}
SWAP_KEYS = {"image", "bone", "anchor", "z", "hides"}
BONE_KEYS = {"parent", "joint", "rest_offset"}
# Limb roots that "rest_offsets": "auto" brings onto the axis of their near twin.
REST_OFFSET_PAIRS = (("thigh_l", "thigh_r"), ("arm_l", "arm_r"))
PART_KEYS = {"bone", "z", "region", "overlap", "fill", "fill_color"}
REGION_KEYS = {"rects", "pixels", "polygons", "exclude"}
SHAPE_KEYS = {"rects", "pixels", "polygons"}
IK_KEYS = {"chain", "target_bone", "bend"}
OUTLINE_MODES = ("outside", "inside")      # first = default


def unknown_keys(obj, allowed: set, where: str) -> list[str]:
    """One warning per key of ``obj`` that the format does not define (``_``-prefixed keys are comments)."""
    if not isinstance(obj, dict):
        return []
    return [f"unknown key '{k}' in {where}: ignored" for k in obj
            if k not in allowed and not str(k).startswith("_")]


def outline_setting(rig: dict) -> str | None:
    """Normalized ``rig["outline"]``: ``"auto"`` (default), ``None`` (disabled) or ``"#rrggbb"``."""
    value = rig.get("outline", "auto")
    if value is True or value == "auto":
        return "auto"
    if value is False or value is None or value == "none":
        return None
    return str(value)


def validate_rig(rig: dict) -> list[str]:
    """Check the structure of a rig. Raises AnimaiError; returns warnings."""
    warnings: list[str] = unknown_keys(rig, RIG_KEYS, "rig")
    setting = outline_setting(rig)
    if setting not in ("auto", None):
        text = setting.strip().lstrip("#")
        if not isinstance(rig.get("outline"), str) or len(text) != 6 or \
                any(ch not in "0123456789abcdefABCDEF" for ch in text):
            raise AnimaiError(f"rig.outline: invalid value {rig.get('outline')!r} "
                              "(expected \"auto\", \"none\" or \"#RRGGBB\")")
    if rig.get("outline_mode", OUTLINE_MODES[0]) not in OUTLINE_MODES:
        raise AnimaiError(f"rig.outline_mode must be one of: {', '.join(OUTLINE_MODES)}")
    if rig.get("version", 1) != 1:
        raise AnimaiError(f"unsupported rig version {rig.get('version')!r} (expected 1)")
    view = rig.get("view", "side")
    if view not in VIEWS:
        raise AnimaiError(f"rig.view '{view}' invalid (one of: {', '.join(VIEWS)})")
    if view != "side":
        warnings.append(f"view '{view}' is outside the v1 scope (side view only)")

    pivot = rig.get("pivot", [0.5, 1.0])
    if not (isinstance(pivot, list) and len(pivot) == 2 and all(_is_num(c) and 0 <= c <= 1 for c in pivot)):
        raise AnimaiError("rig.pivot must be [fx, fy] with values in 0..1")

    bones = rig.get("bones")
    if not isinstance(bones, dict) or not bones:
        raise AnimaiError("rig.bones must be a non-empty object")
    for name, bone in bones.items():
        if not isinstance(bone, dict):
            raise AnimaiError(f"bone '{name}' must be an object")
        parent = bone.get("parent")
        if parent is not None and parent not in bones:
            raise AnimaiError(f"bone '{name}': unknown parent '{parent}'")
        if not _int_pair(bone.get("joint")):
            raise AnimaiError(f"bone '{name}': joint must be [x, y] integers")
        warnings += unknown_keys(bone, BONE_KEYS, f"bone '{name}'")
        if "rest_offset" in bone and not _int_pair(bone["rest_offset"]):
            raise AnimaiError(f"bone '{name}': rest_offset must be [dx, dy] integers")
    if not isinstance(rig.get("fill_holes", True), bool):
        raise AnimaiError("rig.fill_holes must be true or false")
    swaps = rig.get("swaps", {})
    if not isinstance(swaps, dict):
        raise AnimaiError("rig.swaps must be an object")
    for name, swap in swaps.items():
        where = f"swap '{name}'"
        if not isinstance(swap, dict):
            raise AnimaiError(f"{where} must be an object")
        warnings += unknown_keys(swap, SWAP_KEYS, where)
        if not (isinstance(swap.get("image"), str) and swap["image"]):
            raise AnimaiError(f"{where}: image must be the path of a PNG file")
        if swap.get("bone") not in bones:
            raise AnimaiError(f"{where}: unknown bone '{swap.get('bone')}'")
        if not _int_pair(swap.get("anchor")):
            raise AnimaiError(f"{where}: anchor must be [x, y] integers (the pixel of the image placed on the joint)")
        if "z" in swap and not (isinstance(swap["z"], int) and not isinstance(swap["z"], bool)):
            raise AnimaiError(f"{where}: z must be an integer")
        hides = swap.get("hides", [])
        if not (isinstance(hides, list) and all(isinstance(h, str) for h in hides)):
            raise AnimaiError(f"{where}: hides must be a list of part names")
        parts_map = rig.get("parts") if isinstance(rig.get("parts"), dict) else {}
        for part in hides:
            if part not in parts_map:
                raise AnimaiError(f"{where}: hides unknown part '{part}'")
        if not swap_hides(rig, name):
            raise AnimaiError(f"{where}: nothing to replace (bone '{swap['bone']}' has no part, and hides is empty)")
    if rig.get("rest_offsets", "none") not in ("none", "auto"):
        raise AnimaiError("rig.rest_offsets must be \"none\" or \"auto\"")
    if rig.get("template", "humanoid") == "humanoid" and "hips" not in bones:
        raise AnimaiError("humanoid rig requires the bone 'hips'")
    if not any(b.get("parent") is None for b in bones.values()):
        raise AnimaiError("rig has no root bone (parent: null)")
    bone_order(rig)  # raises on cycles

    parts = rig.get("parts")
    if not isinstance(parts, dict) or not parts:
        raise AnimaiError("rig.parts must be a non-empty object")
    for name, part in parts.items():
        if not isinstance(part, dict):
            raise AnimaiError(f"part '{name}' must be an object")
        if part.get("bone") not in bones:
            raise AnimaiError(f"part '{name}': unknown bone '{part.get('bone')}'")
        if not _is_int(part.get("z", 0)):
            raise AnimaiError(f"part '{name}': z must be an integer")
        if not (_is_int(part.get("overlap", 0)) and part.get("overlap", 0) >= 0):
            raise AnimaiError(f"part '{name}': overlap must be an integer >= 0")
        if part.get("fill", "own") not in ("own", "copy", "none", True, False):
            raise AnimaiError(f"part '{name}': fill must be 'own', 'copy' or 'none'")
        if part.get("fill_color") is not None:
            if not isinstance(part["fill_color"], str):
                raise AnimaiError(f"part '{name}': fill_color must be a '#RRGGBB' string")
            parse_hex_color(part["fill_color"])
        warnings += unknown_keys(part, PART_KEYS, f"part '{name}'")
        region = part.get("region")
        if not isinstance(region, dict):
            raise AnimaiError(f"part '{name}': region is required and must be an object "
                              "(use {} for a part without pixels yet)")
        _check_shapes(f"part '{name}'.region", region)
        warnings += unknown_keys(region, REGION_KEYS, f"part '{name}'.region")
        exclude = region.get("exclude", {})
        if not isinstance(exclude, dict):
            raise AnimaiError(f"part '{name}'.region.exclude must be an object")
        _check_shapes(f"part '{name}'.region.exclude", exclude)
        warnings += unknown_keys(exclude, SHAPE_KEYS, f"part '{name}'.region.exclude")

    ik = rig.get("ik", {})
    if not isinstance(ik, dict):
        raise AnimaiError("rig.ik must be an object")
    for name, spec in ik.items():
        chain = spec.get("chain") if isinstance(spec, dict) else None
        target = spec.get("target_bone") if isinstance(spec, dict) else None
        if not (isinstance(chain, list) and len(chain) == 2):
            raise AnimaiError(f"ik '{name}': chain must list exactly 2 bones")
        for b in (*chain, target):
            if b not in bones:
                raise AnimaiError(f"ik '{name}': unknown bone '{b}'")
        if bones[chain[1]].get("parent") != chain[0] or bones[target].get("parent") != chain[1]:
            raise AnimaiError(f"ik '{name}': expected the hierarchy {chain[0]} > {chain[1]} > {target}")
        if bones[chain[0]]["joint"] == bones[chain[1]]["joint"] or \
                bones[chain[1]]["joint"] == bones[target]["joint"]:
            raise AnimaiError(f"ik '{name}': chain bones have zero length (identical joints)")
        if spec.get("bend", 1) not in (1, -1):
            raise AnimaiError(f"ik '{name}': bend must be 1 or -1")
        warnings += unknown_keys(spec, IK_KEYS, f"ik '{name}'")
    return warnings


def normalize_rig(rig: dict) -> tuple[dict, list[str]]:
    """Copy of the rig where a bone whose parent is a canonical bone absent from
    the rig is re-attached to its first present canonical ancestor (warning)."""
    bones = rig.get("bones")
    if not isinstance(bones, dict):
        return rig, []
    warnings: list[str] = []
    new_bones = {}
    for name, bone in bones.items():
        if isinstance(bone, dict):
            parent = bone.get("parent")
            if isinstance(parent, str) and parent not in bones and parent in CANONICAL_PARENTS:
                ancestor = parent
                while ancestor is not None and ancestor not in bones:
                    ancestor = CANONICAL_PARENTS.get(ancestor)
                if ancestor is not None and ancestor != name:
                    warnings.append(f"bone '{name}': parent '{parent}' is not in the rig, "
                                    f"attached to '{ancestor}'")
                    bone = {**bone, "parent": ancestor}
        new_bones[name] = bone
    return {**rig, "bones": new_bones}, warnings


def swap_hides(rig: dict, name: str) -> list[str]:
    """Parts a swap replaces: its ``hides`` list, or every part of its bone when the list is absent or empty."""
    swap = rig["swaps"][name]
    hides = list(swap.get("hides") or [])
    if not hides:
        parts = rig.get("parts") if isinstance(rig.get("parts"), dict) else {}
        hides = [n for n, p in parts.items() if isinstance(p, dict) and p.get("bone") == swap.get("bone")]
    return hides


def load_rig(path: str | Path) -> tuple[dict, list[str]]:
    """Read, normalize and validate a rig.json. Returns ``(rig, warnings)``."""
    rig, warnings = normalize_rig(read_json(path))
    return rig, warnings + validate_rig(rig)


def bone_order(rig: dict) -> list[str]:
    """Bone names with every parent before its children (stable, definition order)."""
    bones = rig["bones"]
    order: list[str] = []
    done: set[str] = set()
    remaining = list(bones)
    while remaining:
        progressed = False
        for name in list(remaining):
            parent = bones[name].get("parent")
            if parent is None or parent in done:
                order.append(name)
                done.add(name)
                remaining.remove(name)
                progressed = True
        if not progressed:
            raise AnimaiError(f"cycle in bone hierarchy: {', '.join(remaining)}")
    return order


def _shapes_mask(shapes: dict, shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    mask = np.zeros((h, w), dtype=bool)
    for x, y, rw, rh in shapes.get("rects", []):
        mask[max(0, y):max(0, y + rh), max(0, x):max(0, x + rw)] = True
    polygons = shapes.get("polygons", [])
    if polygons:
        im = Image.new("1", (w, h), 0)
        draw = ImageDraw.Draw(im)
        for poly in polygons:
            draw.polygon([tuple(p) for p in poly], fill=1, outline=1)
        mask |= np.array(im, dtype=bool)
    for x, y in shapes.get("pixels", []):
        if 0 <= x < w and 0 <= y < h:
            mask[y, x] = True
    return mask


def region_mask(region: dict, shape: tuple[int, int]) -> np.ndarray:
    """Boolean ``(H, W)`` mask of a region: rects + polygons + pixels, minus ``exclude``."""
    mask = _shapes_mask(region, shape)
    exclude = region.get("exclude")
    if exclude:
        mask &= ~_shapes_mask(exclude, shape)
    return mask


@dataclass
class LabelMap:
    labels: np.ndarray               # (H, W) int16, index into part_names, UNASSIGNED elsewhere
    part_names: list[str]
    unassigned: list[list[int]]      # opaque pixels owned by no part, [x, y], raster order
    multi_assigned: int              # opaque pixels claimed by more than one part
    warnings: list[str]


def build_label_map(rig: dict, rgba: np.ndarray) -> LabelMap:
    """One part per opaque pixel. Parts are applied in definition order: last one wins."""
    h, w = rgba.shape[:2]
    opaque = rgba[..., 3] > 0
    labels = np.full((h, w), UNASSIGNED, dtype=np.int16)
    claims = np.zeros((h, w), dtype=np.int16)
    names = list(rig["parts"])
    warnings: list[str] = []
    covered: list[bool] = []
    for index, name in enumerate(names):
        mask = region_mask(rig["parts"][name].get("region", {}), (h, w)) & opaque
        covered.append(bool(mask.any()))
        labels[mask] = index
        claims[mask] += 1
    for index, name in enumerate(names):
        if not covered[index]:
            warnings.append(f"part '{name}' covers no opaque pixel")
        elif not (labels == index).any():
            warnings.append(f"part '{name}' is entirely overridden by later parts")
    multi = int((claims > 1).sum())
    if multi:
        warnings.append(f"{multi} pixels claimed by several parts (last defined part wins)")
    ys, xs = np.nonzero(opaque & (labels == UNASSIGNED))
    unassigned = [[int(x), int(y)] for x, y in zip(xs, ys)]
    if unassigned:
        warnings.append(f"{len(unassigned)} opaque pixels are not assigned to any part "
                        f"(first at {unassigned[0]})")
    for name, bone in rig["bones"].items():
        jx, jy = bone["joint"]
        if not (0 <= jx < w and 0 <= jy < h):
            warnings.append(f"bone '{name}': joint {bone['joint']} is outside the sprite ({w}x{h})")
    return LabelMap(labels, names, unassigned, multi, warnings)


@dataclass
class Part:
    name: str
    bone: str
    z: int
    index: int                 # definition order, tie-breaker for equal z
    image: np.ndarray          # RGBA crop: own pixels + hidden zone (filled)
    origin: tuple[int, int]    # sprite coordinates of the crop's top-left corner
    own_mask: np.ndarray       # bool crop: pixels the label map gives to this part
    own_count: int
    extended_count: int        # pixels of the hidden zone that received data
    fill: str = "own"          # fill mode of the hidden zone
    missing: list = field(default_factory=list)   # hidden-zone pixels left without data, [x, y]


def fill_mode(spec: dict) -> str:
    """Normalized ``fill`` of a part: ``own`` (default) | ``copy`` | ``none``."""
    value = spec.get("fill", "own")
    if value is True:
        return "own"
    if value is False:
        return "none"
    return value


def silhouette_border(rgba: np.ndarray) -> np.ndarray:
    """Opaque pixels with a transparent 4-neighbour (the image edge counts as transparent)."""
    opaque = rgba[..., 3] > 0
    return opaque & dilate4(np.pad(~opaque, 1, constant_values=True))[1:-1, 1:-1]


def detect_outline_color(rgba: np.ndarray) -> int | None:
    """Packed ``0xRRGGBB`` of the sprite's outline, or None when it has none.

    The sprite has an outline when one colour covers at least 60 % of its
    silhouette border (``silhouette_border``).
    """
    border = silhouette_border(rgba)
    if not border.any():
        return None
    values, counts = np.unique(pack_rgb(rgba)[border], return_counts=True)
    best = int(np.argmax(counts))            # np.unique sorts: ties go to the smallest colour
    if int(counts[best]) * 10 < int(border.sum()) * 6:
        return None
    return int(values[best])


def span_closure(mask: np.ndarray) -> np.ndarray:
    """Cells lying between two set cells of the same row, or of the same column (inclusive)."""
    acc = np.logical_or.accumulate
    rows = acc(mask, axis=1) & acc(mask[:, ::-1], axis=1)[:, ::-1]
    cols = acc(mask, axis=0) & acc(mask[::-1, :], axis=0)[::-1, :]
    return rows | cols


def hidden_zone(own: np.ndarray, front_owned: np.ndarray, overlap: int,
                extra: np.ndarray | None = None) -> np.ndarray:
    """Pixels where a part continues under the parts drawn in front of it.

    = pixels owned by front parts that lie between two own pixels of the part on
    their row or on their column, plus ``extra`` (pixels given to the part by
    ``shared_enclosure``), grown by ``overlap`` 4-connected steps (still inside
    front-owned pixels only).
    """
    ext = own | (span_closure(own) & front_owned)
    if extra is not None:
        ext = ext | (extra & front_owned)
    for _ in range(overlap):
        ext = ext | (dilate4(ext) & front_owned)
    return ext & ~own


def _shift(arr: np.ndarray, dy: int, dx: int, fill) -> np.ndarray:
    """``out[y, x] = arr[y - dy, x - dx]``, cells shifted in from outside set to ``fill``."""
    out = np.full_like(arr, fill)
    h, w = arr.shape
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = \
        arr[max(-dy, 0):h + min(-dy, 0), max(-dx, 0):w + min(-dx, 0)]
    return out


def fill_own_colors(rgb: np.ndarray, own: np.ndarray, hidden: np.ndarray,
                    outline: int | None, border: np.ndarray) -> np.ndarray:
    """Colours (packed RGB, full image) for the hidden zone of a part, taken from the part itself.

    Breadth-first propagation over ``own | hidden`` starting from the part's own
    pixels that are not outline-coloured (all own pixels if there is no other):
    each hidden pixel receives the colour of the nearest such pixel (4-connected
    distance inside the part; ties: from the neighbour above, then left, right,
    below). Hidden pixels that cannot be reached get the part's most frequent
    source colour. Hidden pixels on the silhouette border take the outline
    colour when the sprite has one.
    """
    domain = own | hidden
    if not domain.any():
        return np.zeros(rgb.shape, dtype=np.uint32)
    # Work on the bounding box of the part only: nothing propagates outside the domain.
    rows, cols = np.nonzero(domain.any(axis=1))[0], np.nonzero(domain.any(axis=0))[0]
    box = (slice(int(rows[0]), int(rows[-1]) + 1), slice(int(cols[0]), int(cols[-1]) + 1))
    full_shape = rgb.shape
    rgb, own, hidden, border, domain = rgb[box], own[box], hidden[box], border[box], domain[box]
    sources = own & (rgb != outline) if outline is not None else own.copy()
    if not sources.any():
        sources = own.copy()
    carried = np.where(sources, rgb, 0).astype(np.uint32)
    known = sources.copy()
    while True:
        todo = domain & ~known
        if not todo.any():
            break
        new_known = known.copy()
        for dy, dx in ((1, 0), (0, 1), (0, -1), (-1, 0)):
            take = todo & _shift(known, dy, dx, False) & ~new_known
            carried[take] = _shift(carried, dy, dx, 0)[take]
            new_known |= take
        if int(new_known.sum()) == int(known.sum()):
            values, counts = np.unique(rgb[sources], return_counts=True)
            carried[todo] = values[int(np.argmax(counts))]
            break
        known = new_known
    if outline is not None:
        carried[hidden & border] = outline
    out = np.zeros(full_shape, dtype=np.uint32)
    out[box] = carried
    return out


def shared_enclosure(rig: dict, labelmap: LabelMap, covered: np.ndarray,
                     no_data: frozenset = frozenset()) -> dict[int, np.ndarray]:
    """Hidden pixels that no single rear part encloses but that two rear parts enclose together.

    Typical case: the hand hanging in front of the hips, between the two thighs.
    A pixel owned by part F and not in ``covered`` (no rear part has data
    there) is examined on its row, then on its column: walking away from it in
    both directions (through pixels of F and of parts in front of F, stopping
    at a transparent or unassigned pixel) must meet, on each side, a pixel of a
    part drawn behind F whose bone is neither F's bone, its parent nor one of
    its children. Call ``A`` and ``B`` the bones of the two parts met.

    The pixel is body, not limb: it is only filled when ``A`` and ``B`` hang
    from the same bone ``P`` (``A`` and ``B`` are siblings of parent ``P``, or
    one of them is ``P`` and the other its child), and it is given to **a part
    of P** drawn behind F (the one closest to the front), never to a limb met
    on the way. If P has no such part and A, B are siblings, the nearer of the
    two parts met receives it (tie: the one drawn closer to the front). In
    every other case (for instance a far hand on one side and a thigh on the
    other) nothing is filled: no part has to exist there.

    Parts listed in ``no_data`` (indices, ``fill: "none"``) never receive anything.
    Returns ``{part index: bool mask}``.
    """
    labels = labelmap.labels
    names = labelmap.part_names
    h, w = labels.shape
    key = [(int(rig["parts"][n].get("z", 0)), i) for i, n in enumerate(names)]
    bone = [rig["parts"][n]["bone"] for n in names]
    parent = {b: spec.get("parent") for b, spec in rig["bones"].items()}
    has_pixels = [bool((labels == i).any()) for i in range(len(names))]

    def related(a: str, b: str) -> bool:
        return a == b or parent.get(a) == b or parent.get(b) == a

    missing = object()

    def walk(x: int, y: int, dx: int, dy: int, f: int, seen: dict):
        # ``seen`` holds the answers already found for this direction: on a pixel of the
        # same part the rest of the walk is the same, so its answer is reused (the cost
        # stays linear on large sprites instead of one full walk per pixel).
        dist = 0
        while True:
            x, y, dist = x + dx, y + dy, dist + 1
            if not (0 <= x < w and 0 <= y < h):
                return None
            g = int(labels[y, x])
            if g == UNASSIGNED:
                return None
            if g == f:
                hit = seen.get(y * w + x, missing)
                if hit is not missing:
                    return None if hit is None else (hit[0] + dist, hit[1])
                continue
            if key[g] > key[f]:
                continue
            return None if related(bone[g], bone[f]) else (dist, g)

    def receiver(a, b, f: int):
        ba, bb = bone[a[1]], bone[b[1]]
        siblings = ba != bb and parent.get(ba) is not None and parent.get(ba) == parent.get(bb)
        if siblings:
            common = parent[ba]
        elif parent.get(ba) == bb:
            common = bb
        elif parent.get(bb) == ba:
            common = ba
        else:
            return None
        owners = [i for i in range(len(names)) if bone[i] == common and has_pixels[i]
                  and key[i] < key[f] and i not in no_data and not related(common, bone[f])]
        if owners:
            return max(owners, key=lambda i: key[i])
        if siblings:
            flanks = [t for t in (a, b) if t[1] not in no_data]
            if flanks:      # nearer part wins; tie: the one drawn closer to the front
                return min(flanks, key=lambda t: (t[0], [-k for k in key[t[1]]]))[1]
        return None

    out: dict[int, np.ndarray] = {}
    ys, xs = np.nonzero((labels != UNASSIGNED) & ~covered)
    cells = list(zip(xs.tolist(), ys.tolist()))      # row-major: left and up neighbours come first
    found: dict[tuple[int, int], dict] = {}
    for dx, dy in ((-1, 0), (0, -1), (1, 0), (0, 1)):
        seen = found[(dx, dy)] = {}
        for x, y in (cells if dx + dy < 0 else reversed(cells)):
            seen[y * w + x] = walk(x, y, dx, dy, int(labels[y, x]), seen)
    for x, y in cells:
        f = int(labels[y, x])
        for axis in ((1, 0), (0, 1)):
            a = found[(-axis[0], -axis[1])][y * w + x]
            b = found[axis][y * w + x]
            if a and b:
                g = receiver(a, b, f)
                if g is not None:
                    out.setdefault(g, np.zeros((h, w), dtype=bool))[y, x] = True
                    break
    return out


def cut_parts(rig: dict, rgba: np.ndarray, labelmap: LabelMap) -> list[Part]:
    """Cut the sprite into rigid parts and complete each one under its front neighbours.

    Hidden zone of a part: see ``hidden_zone``. It only contains pixels owned by
    parts drawn in front at rest (larger z, or same z and defined later), so the
    rest pose always reproduces the sprite exactly. Its content depends on the
    part's ``fill``: ``"own"`` (default) = the part's own colours
    (``fill_own_colors``, or the single ``fill_color`` when given), ``"copy"`` =
    the sprite pixels of the front parts, ``"none"`` = nothing (the pixels of the
    enclosed zone are then listed in ``Part.missing`` and ``overlap`` is unused).
    Parts without any pixel are skipped.
    """
    names = labelmap.part_names
    draw_key = [(int(rig["parts"][n].get("z", 0)), i) for i, n in enumerate(names)]
    opaque = rgba[..., 3] > 0
    rgb = pack_rgb(rgba)
    palette = set(np.unique(rgb[opaque]).tolist())
    outline = detect_outline_color(rgba)
    border = silhouette_border(rgba)
    # First pass: what every part covers on its own; then the zones only several parts enclose together.
    fronts = [np.isin(labelmap.labels, [i for i in range(len(names)) if draw_key[i] > draw_key[index]])
              for index in range(len(names))]
    covered = np.zeros(opaque.shape, dtype=bool)
    for index, name in enumerate(names):
        spec = rig["parts"][name]
        own = labelmap.labels == index
        if own.any() and fill_mode(spec) != "none":
            covered |= hidden_zone(own, fronts[index], int(spec.get("overlap", 0)))
    no_data = frozenset(i for i, n in enumerate(names) if fill_mode(rig["parts"][n]) == "none")
    shared = shared_enclosure(rig, labelmap, covered, no_data)
    parts: list[Part] = []
    for index, name in enumerate(names):
        spec = rig["parts"][name]
        own = labelmap.labels == index
        own_count = int(own.sum())
        if own_count == 0:
            continue
        mode = fill_mode(spec)
        front_owned = fronts[index]
        missing: list = []
        colors = rgb
        if mode == "none":
            hidden = np.zeros_like(own)
            ys, xs = np.nonzero(hidden_zone(own, front_owned, 0))
            missing = [[int(x), int(y)] for x, y in zip(xs, ys)]
        else:
            hidden = hidden_zone(own, front_owned, int(spec.get("overlap", 0)), shared.get(index))
            if mode == "own" and spec.get("fill_color") is not None:
                r, g, b = parse_hex_color(spec["fill_color"])
                forced = (r << 16) | (g << 8) | b
                if forced not in palette:
                    raise AnimaiError(f"part '{name}': fill_color {spec['fill_color']} is not in the "
                                      "sprite palette")
                colors = np.where(hidden, np.uint32(forced), rgb)
            elif mode == "own":
                colors = fill_own_colors(rgb, own, hidden, outline, border)
        ext = own | hidden
        ys, xs = np.nonzero(ext)
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
        crop = np.where(own, rgb, colors)[y0:y1, x0:x1]
        image = np.zeros((y1 - y0, x1 - x0, 4), dtype=np.uint8)
        image[..., 0] = (crop >> 16) & 0xFF
        image[..., 1] = (crop >> 8) & 0xFF
        image[..., 2] = crop & 0xFF
        image[..., 3] = 255
        image[~ext[y0:y1, x0:x1]] = 0
        parts.append(Part(name, spec["bone"], int(spec.get("z", 0)), index, image,
                          (x0, y0), own[y0:y1, x0:x1].copy(), own_count,
                          int(hidden.sum()), mode, missing))
    return parts


def labels_to_regions(labels: np.ndarray, part_count: int) -> list[dict]:
    """Encode a label map as one ``{"rects": [...], "pixels": [...]}`` region per part.

    Exact and deterministic: horizontal runs of each part are merged downwards
    while the next row has a run with the same x-span; a 1x1 result becomes a
    pixel. The regions of different parts never overlap, so decoding them with
    ``build_label_map`` gives back ``labels`` (on the opaque pixels).
    """
    h, w = labels.shape
    regions: list[dict] = []
    for index in range(part_count):
        mask = labels == index
        open_rects: dict[tuple[int, int], list[int]] = {}      # (x0, x1) -> [x, y, w, h]
        done: list[list[int]] = []
        for y in range(h):
            row = mask[y]
            spans = []
            if row.any():
                edges = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
                spans = [(int(a), int(b)) for a, b in zip(edges[0::2], edges[1::2])]
            still_open = {}
            for span in spans:
                if span in open_rects:
                    rect = open_rects.pop(span)
                    rect[3] += 1
                else:
                    rect = [span[0], y, span[1] - span[0], 1]
                still_open[span] = rect
            done.extend(open_rects.values())
            open_rects = still_open
        done.extend(open_rects.values())
        done.sort(key=lambda r: (r[1], r[0]))
        regions.append({"rects": [r for r in done if r[2] * r[3] > 1],
                        "pixels": [[r[0], r[1]] for r in done if r[2] * r[3] == 1]})
    return regions


def apply_labelmap_delta(rig: dict, rgba: np.ndarray, target: np.ndarray) -> tuple[dict, list[str], bool]:
    """Edit the regions of a rig so that its label map becomes ``target``, touching as little as possible.

    Only the parts whose pixel set differs are modified, and by a delta: a
    pixel gained goes to ``region.pixels`` (and leaves ``exclude.pixels``), a
    pixel lost leaves ``region.pixels`` and, if a rect or a polygon still
    covers it, goes to ``region.exclude.pixels``. ``rects``, ``polygons`` and
    the ``exclude`` shapes written by hand are kept. Because the last defined
    part wins, removing a pixel from one part can reveal a claim of another
    part: the result is recomputed and corrected until it matches. If it
    cannot match (a pixel wanted by a part is excluded by one of its own
    exclude rects or polygons), every region is re-encoded from scratch.

    ``target``: ``(H, W)`` indices in ``rig["parts"]`` order, UNASSIGNED
    elsewhere; transparent pixels are ignored. Returns
    ``(new_rig, changed part names, full_reencode)``.
    """
    import copy

    h, w = rgba.shape[:2]
    opaque = rgba[..., 3] > 0
    target = np.where(opaque, target, UNASSIGNED).astype(np.int16)
    new = copy.deepcopy(rig)
    names = list(new["parts"])
    changed: set[str] = set()
    for _ in range(len(names) + 3):
        current = build_label_map(new, rgba).labels
        if np.array_equal(current, target):
            return new, [n for n in names if n in changed], False
        for index, name in enumerate(names):
            gained = (target == index) & (current != index)
            lost = (current == index) & (target != index)
            if not gained.any() and not lost.any():
                continue
            changed.add(name)
            region = new["parts"][name].setdefault("region", {})
            pixels = {(int(x), int(y)) for x, y in region.get("pixels", [])}
            exclude = region.get("exclude") or {}
            ex_pixels = {(int(x), int(y)) for x, y in exclude.get("pixels", [])}
            shapes = _shapes_mask({k: v for k, v in region.items() if k in ("rects", "polygons")}, (h, w))
            for y, x in zip(*np.nonzero(gained)):
                x, y = int(x), int(y)
                ex_pixels.discard((x, y))
                if not shapes[y, x]:
                    pixels.add((x, y))
            for y, x in zip(*np.nonzero(lost)):
                x, y = int(x), int(y)
                pixels.discard((x, y))
                if shapes[y, x]:
                    ex_pixels.add((x, y))
            region["pixels"] = [[x, y] for x, y in sorted(pixels, key=lambda p: (p[1], p[0]))]
            if ex_pixels or "exclude" in region:
                region["exclude"] = {**exclude, "pixels": [[x, y] for x, y in
                                                         sorted(ex_pixels, key=lambda p: (p[1], p[0]))]}
    new = copy.deepcopy(rig)
    for name, region in zip(names, labels_to_regions(target, len(names))):
        new["parts"][name]["region"] = region
    return new, names, True


def rest_offsets(rig: dict) -> dict[str, list[int]]:
    """Rest offset of each bone that has one: ``{bone: [dx, dy]}`` (zero offsets omitted).

    Explicit ``bones.<name>.rest_offset`` first. With ``rig["rest_offsets"] ==
    "auto"``, each far limb root of ``REST_OFFSET_PAIRS`` that has no explicit
    value gets ``joint(near twin) - joint(itself)``, which puts both limbs of
    the pair on the same axis.
    """
    bones = rig["bones"]
    out: dict[str, list[int]] = {}
    for name, bone in bones.items():
        if "rest_offset" in bone:
            out[name] = [int(bone["rest_offset"][0]), int(bone["rest_offset"][1])]
    if rig.get("rest_offsets") == "auto":
        for far, near in REST_OFFSET_PAIRS:
            if far in bones and near in bones and "rest_offset" not in bones[far]:
                out[far] = [bones[near]["joint"][0] - bones[far]["joint"][0],
                            bones[near]["joint"][1] - bones[far]["joint"][1]]
    return {b: o for b, o in out.items() if o != [0, 0]}
