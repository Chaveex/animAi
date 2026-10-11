"""Reusable pixel invariants for a sequence of frames.

Independent from ``animai.core`` on purpose: these are the tester's own
reference checks, recomputed from docs/schemas.md ("report.json" section) with
nothing but the frame images and, where the contract says so, ``frames.json``.

Every ``check_*`` function returns a list of :class:`Violation` (empty = pass)
and never raises on bad pixels; ``assert_no_violations`` turns a list into a
readable ``AssertionError``. Violation ids are the ``report.json`` check ids,
plus two tester-side ones: ``ground_line`` and ``enclosed``.

Frames are RGBA uint8 arrays of shape (H, W, 4). ``as_rgba`` accepts a path, a
PIL image or an array. Pixel coordinates in violations are (x, y), origin
top-left, canvas coordinates.

Definitions (docs/schemas.md unless noted):

* palette        every pixel with alpha > 0 has an RGB present in the source palette
* alpha_binary   every alpha value is exactly 0 or 255
* orphans        a frame has more opaque pixels without any opaque 8-neighbour
                 than the source sprite (``allowed``, 0 for the fixtures)
* holes          defined by their CAUSE, from ``frames.json``:
                 1. open joint: a pixel of the tracked disk ``joints.<bone>``
                    around the bone's world joint is transparent or off canvas;
                 2. unfilled disocclusion: a transparent pixel maps back, in the
                    rest pose of a part, onto one of its ``missing`` pixels;
                 3. dislocated joint (kinematic, frames.json alone): the joint of
                    a bone sits more than ``joints[bone] + 2`` px (Chebyshev) from
                    the point where its parent holds it.
                 A closed empty area between two limbs is legitimate negative
                 space: see ``check_enclosed_regions`` (tester-side, used on the
                 source sprites only, never a QA failure on animated frames).
* canvas_constant all frames have the same (width, height)
* pivot_stable   the per-frame pivot is the same pair of integers on every
                 frame and lies inside the canvas
* loop_closed    for a looping animation, the wrap step (last -> first) is
                 neither zero (last frame = copy of the first) nor bigger than
                 the biggest in-loop step plus 10 %. Step = number of pixels
                 that differ
* parts_assigned every opaque source pixel is owned by a part
* ground_line    (docs/animation-guide.md D5/D7, tester-side) the bottom edge of
                 the lowest opaque row sits on the pivot's y, within a tolerance
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image

CHECK_IDS = (
    "palette", "alpha_binary", "orphans", "holes",
    "pivot_stable", "canvas_constant", "loop_closed", "parts_assigned",
)
MAX_REPORTED = 10  # per frame and per check, to keep failure messages readable
LOOP_TOLERANCE = 1.10   # docs/schemas.md: biggest in-loop step "majore de 10 %"


@dataclass(frozen=True)
class Violation:
    check: str
    detail: str
    frame: int | None = None
    pixel: tuple[int, int] | None = None

    def __str__(self) -> str:
        where = []
        if self.frame is not None:
            where.append(f"frame {self.frame}")
        if self.pixel is not None:
            where.append(f"pixel {self.pixel}")
        return f"[{self.check}] {self.detail}" + (f" ({', '.join(where)})" if where else "")


def assert_no_violations(violations: Iterable[Violation], context: str = "") -> None:
    violations = list(violations)
    if violations:
        head = f"{len(violations)} invariant violation(s)" + (f" in {context}" if context else "")
        raise AssertionError(head + ":\n  " + "\n  ".join(str(v) for v in violations[:40]))


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def as_rgba(image) -> np.ndarray:
    """Path / PIL image / array -> RGBA uint8 array (H, W, 4)."""
    if isinstance(image, (str, Path)):
        with Image.open(image) as opened:
            return np.array(opened.convert("RGBA"), dtype=np.uint8)
    if isinstance(image, Image.Image):
        return np.array(image.convert("RGBA"), dtype=np.uint8)
    array = np.asarray(image)
    if array.ndim != 3 or array.shape[2] != 4:
        raise ValueError(f"expected an RGBA array (H, W, 4), got shape {array.shape}")
    if array.dtype != np.uint8:
        raise ValueError(f"expected uint8, got {array.dtype}")
    return array


def as_frames(frames) -> list[np.ndarray]:
    return [as_rgba(f) for f in frames]


def palette_of(image) -> frozenset[tuple[int, int, int]]:
    """RGB colours of every non fully transparent pixel."""
    rgba = as_rgba(image)
    visible = rgba[rgba[..., 3] > 0][:, :3]
    return frozenset(map(tuple, np.unique(visible, axis=0).tolist())) if len(visible) else frozenset()


def canonical(image) -> np.ndarray:
    """Copy with the RGB of fully transparent pixels zeroed (invisible data)."""
    rgba = as_rgba(image).copy()
    rgba[rgba[..., 3] == 0] = 0
    return rgba


def crop_to_content(image) -> np.ndarray:
    """Crop to the bounding box of non transparent pixels (canonical RGBA)."""
    rgba = canonical(image)
    ys, xs = np.nonzero(rgba[..., 3])
    if len(ys) == 0:
        return rgba[:0, :0]
    return rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def split_grid(sheet, frame_w: int, frame_h: int) -> list[np.ndarray]:
    """Cut a spritesheet laid out as a regular grid, row-major."""
    rgba = as_rgba(sheet)
    height, width = rgba.shape[:2]
    if frame_w <= 0 or frame_h <= 0 or width % frame_w or height % frame_h:
        raise ValueError(f"sheet {width}x{height} is not a grid of {frame_w}x{frame_h} cells")
    return [rgba[y:y + frame_h, x:x + frame_w]
            for y in range(0, height, frame_h) for x in range(0, width, frame_w)]


# --------------------------------------------------------------------------- #
# Connected components (no scipy dependency)
# --------------------------------------------------------------------------- #

_N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_N8 = _N4 + ((1, 1), (1, -1), (-1, 1), (-1, -1))


def connected_components(mask: np.ndarray, connectivity: int = 8) -> list[list[tuple[int, int]]]:
    """Components of a boolean mask as lists of (x, y), in scan order."""
    if connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")
    neighbours = _N8 if connectivity == 8 else _N4
    mask = np.asarray(mask, dtype=bool)
    height, width = mask.shape
    seen = np.zeros_like(mask)
    components = []
    for y0, x0 in zip(*np.nonzero(mask)):
        if seen[y0, x0]:
            continue
        seen[y0, x0] = True
        stack, component = [(int(x0), int(y0))], []
        while stack:
            x, y = stack.pop()
            component.append((x, y))
            for dx, dy in neighbours:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((nx, ny))
        components.append(sorted(component, key=lambda p: (p[1], p[0])))
    return components


def enclosed_mask(image) -> np.ndarray:
    """Boolean mask of transparent pixels enclosed by the silhouette.

    Not a "hole" in the contract's sense: on an animated frame this is usually
    legitimate negative space (between the legs, between an arm and the body).
    """
    transparent = as_rgba(image)[..., 3] == 0
    padded = np.pad(transparent, 1, constant_values=True)
    outside = np.zeros_like(padded)
    outside[0, 0] = True
    stack = [(0, 0)]
    height, width = padded.shape
    while stack:
        x, y = stack.pop()
        for dx, dy in _N4:
            nx, ny = x + dx, y + dy
            if 0 <= nx < width and 0 <= ny < height and padded[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                stack.append((nx, ny))
    return (padded & ~outside)[1:-1, 1:-1]


# --------------------------------------------------------------------------- #
# Per-frame invariants
# --------------------------------------------------------------------------- #

def _pixel_violations(check, mask, frame_index, describe) -> list[Violation]:
    ys, xs = np.nonzero(mask)
    found = [Violation(check, describe(int(x), int(y)), frame_index, (int(x), int(y)))
             for y, x in list(zip(ys, xs))[:MAX_REPORTED]]
    if len(ys) > MAX_REPORTED:
        found.append(Violation(check, f"... {len(ys) - MAX_REPORTED} more pixel(s)", frame_index))
    return found


def check_palette(frames, source_palette) -> list[Violation]:
    """No visible colour outside ``source_palette`` (iterable of (r, g, b))."""
    allowed = {tuple(int(c) for c in colour) for colour in source_palette}
    if not allowed:
        raise ValueError("source palette is empty")
    allowed_codes = np.array(sorted((r << 16) | (g << 8) | b for r, g, b in allowed))
    violations = []
    for index, frame in enumerate(as_frames(frames)):
        rgb = frame[..., :3].astype(np.int64)
        codes = (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]
        bad = (frame[..., 3] > 0) & ~np.isin(codes, allowed_codes)
        violations += _pixel_violations(
            "palette", bad, index,
            lambda x, y, f=frame: f"colour {tuple(int(c) for c in f[y, x, :3])} not in source palette",
        )
    return violations


def check_alpha_binary(frames) -> list[Violation]:
    violations = []
    for index, frame in enumerate(as_frames(frames)):
        alpha = frame[..., 3]
        bad = (alpha != 0) & (alpha != 255)
        violations += _pixel_violations(
            "alpha_binary", bad, index, lambda x, y, a=alpha: f"alpha {int(a[y, x])} is not 0/255")
    return violations


def check_orphans(frames, allowed: int = 0) -> list[Violation]:
    """More opaque pixels without any opaque 8-neighbour than ``allowed``.

    ``allowed`` is the count measured on the source sprite
    (``frames.json`` -> ``source.orphans``); 0 for a clean sprite.
    """
    violations = []
    for index, frame in enumerate(as_frames(frames)):
        found = [c for c in connected_components(frame[..., 3] > 0, 8) if len(c) == 1]
        if len(found) > allowed:
            violations.append(Violation(
                "orphans", f"{len(found)} isolated pixel(s), source sprite has {allowed}",
                index, found[0][0]))
    return violations


def check_enclosed_regions(frames, min_area: int = 1) -> list[Violation]:
    """Transparent regions enclosed by opaque pixels (one violation per region).

    Tester-side check for SOURCE sprites (a fixture must not have any). It is
    not the contract's ``holes`` check and must not be applied to animated
    frames as a failure: see ``check_holes``.
    """
    violations = []
    for index, frame in enumerate(as_frames(frames)):
        found = [c for c in connected_components(enclosed_mask(frame), 4) if len(c) >= min_area]
        violations += [Violation("enclosed", f"enclosed transparent region of {len(c)} pixel(s)",
                                 index, c[0]) for c in found[:MAX_REPORTED]]
        if len(found) > MAX_REPORTED:
            violations.append(Violation("enclosed", f"... {len(found) - MAX_REPORTED} more", index))
    return violations


# --------------------------------------------------------------------------- #
# Holes, by cause (docs/schemas.md "Definition d'un trou"), from frames.json
# --------------------------------------------------------------------------- #

def disk_offsets(radius: int) -> list[tuple[int, int]]:
    """Every integer (dx, dy) with dx^2 + dy^2 <= radius^2, in scan order."""
    radius = int(radius)
    return [(dx, dy) for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)
            if dx * dx + dy * dy <= radius * radius]


def _trig(angle_degrees: float) -> tuple[float, float]:
    """(cos, sin), exact on multiples of 90 so that floor() below is stable."""
    quarter, rest = divmod(float(angle_degrees), 90.0)
    if rest == 0.0:
        return ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))[int(quarter) % 4]
    radians = np.deg2rad(float(angle_degrees))
    return float(np.cos(radians)), float(np.sin(radians))


def open_joint_pixels(frame, manifest: dict, frame_index: int) -> dict[str, list[tuple[int, int]]]:
    """Cause 1. {bone: [(x, y) canvas pixels of its tracked disk that are
    transparent or outside the canvas]} for one frame; bones without any are omitted."""
    alpha = as_rgba(frame)[..., 3]
    height, width = alpha.shape
    ox, oy = manifest["origin"]
    pose = manifest["frames"][frame_index]["bones"]
    found: dict[str, list[tuple[int, int]]] = {}
    for bone, radius in manifest.get("joints", {}).items():
        if bone not in pose:
            found[bone] = []          # tracked but not posed: reported by the caller
            continue
        jx, jy = pose[bone]["joint"]
        cx, cy = int(jx) - int(ox), int(jy) - int(oy)
        bad = [(cx + dx, cy + dy) for dx, dy in disk_offsets(radius)
               if not (0 <= cx + dx < width and 0 <= cy + dy < height)
               or alpha[cy + dy, cx + dx] == 0]
        if bad:
            found[bone] = bad
    return found


def missing_data_pixels(frame, manifest: dict, frame_index: int) -> dict[str, list[tuple[int, int]]]:
    """Cause 2. {part: [(x, y) transparent canvas pixels that fall, once brought
    back to the rest pose of the part, on one of its ``missing`` pixels]}."""
    alpha = as_rgba(frame)[..., 3]
    ox, oy = manifest["origin"]
    pose = manifest["frames"][frame_index]["bones"]
    rest = manifest.get("rest", {}).get("bones", {})
    ys, xs = np.nonzero(alpha == 0)
    found: dict[str, list[tuple[int, int]]] = {}
    for part, spec in manifest.get("parts", {}).items():
        missing = {(int(x), int(y)) for x, y in spec.get("missing") or []}
        if not missing or len(ys) == 0:
            continue
        bone = spec["bone"]
        jx, jy = rest[bone]["joint"]
        world_x, world_y = pose[bone]["joint"]
        cos_a, sin_a = _trig(pose[bone]["angle"])
        dx = xs + ox - world_x
        dy = ys + oy - world_y
        rest_x = np.floor(jx + 0.5 + dx * cos_a - dy * sin_a).astype(np.int64)
        rest_y = np.floor(jy + 0.5 + dx * sin_a + dy * cos_a).astype(np.int64)
        bad = [(int(x), int(y)) for x, y, rx, ry in zip(xs, ys, rest_x, rest_y)
               if (int(rx), int(ry)) in missing]
        if bad:
            found[part] = bad
    return found


DISLOCATION_MARGIN = 2   # docs/schemas.md: gap > joints[B] + 2


def joint_gaps(manifest: dict, frame_index: int) -> dict[str, float]:
    """Cause 3, raw measure. {bone: Chebyshev distance between its world joint and
    the point where its parent holds the articulation}, for every non-root bone
    that carries a part. Computed from ``frames.json`` alone."""
    rest = manifest["rest"]["bones"]
    pose = manifest["frames"][frame_index]["bones"]
    carrying = {part["bone"] for part in manifest.get("parts", {}).values()}
    gaps = {}
    for bone in rest:
        parent = rest[bone].get("parent")
        if bone not in carrying or parent is None or parent not in rest:
            continue
        dx = rest[bone]["joint"][0] - rest[parent]["joint"][0]
        dy = rest[bone]["joint"][1] - rest[parent]["joint"][1]
        cos_a, sin_a = _trig(pose[parent]["angle"])
        held_x = pose[parent]["joint"][0] + dx * cos_a + dy * sin_a
        held_y = pose[parent]["joint"][1] - dx * sin_a + dy * cos_a
        gaps[bone] = max(abs(pose[bone]["joint"][0] - held_x), abs(pose[bone]["joint"][1] - held_y))
    return gaps


def dislocated_joints(manifest: dict, frame_index: int) -> dict[str, float]:
    """Cause 3. {bone: gap} for the bones whose gap exceeds ``joints[bone] + 2``."""
    radii = manifest.get("joints", {})
    return {bone: gap for bone, gap in joint_gaps(manifest, frame_index).items()
            if gap > radii.get(bone, 0) + DISLOCATION_MARGIN}


def check_holes(frames, manifest: dict) -> list[Violation]:
    """The contract's ``holes`` check, recomputed from ``frames.json`` + images.

    One violation per (frame, cause, bone or part), with the pixel count and the
    first faulty pixel in canvas coordinates (possibly off canvas for a joint
    that leaves the frame).
    """
    frames = as_frames(frames)
    entries = manifest.get("frames", [])
    if len(entries) != len(frames):
        return [Violation("holes", f"frames.json lists {len(entries)} frame(s), got {len(frames)} image(s)")]
    violations = []
    for index, frame in enumerate(frames):
        for bone, pixels in open_joint_pixels(frame, manifest, index).items():
            if not pixels:
                violations.append(Violation(
                    "holes", f"open joint '{bone}': tracked in 'joints' but absent from the frame pose", index))
                continue
            violations.append(Violation(
                "holes", f"open joint '{bone}': {len(pixels)} pixel(s) of its disk "
                         f"(radius {manifest['joints'][bone]}) are transparent or off canvas",
                index, pixels[0]))
        for part, pixels in missing_data_pixels(frame, manifest, index).items():
            violations.append(Violation(
                "holes", f"part '{part}' has no data under its front neighbour: {len(pixels)} pixel(s)",
                index, pixels[0]))
        ox, oy = manifest["origin"]
        for bone, gap in dislocated_joints(manifest, index).items():
            jx, jy = manifest["frames"][index]["bones"][bone]["joint"]
            violations.append(Violation(
                "holes", f"dislocated joint '{bone}' ({gap:.2f} px from where its parent holds it, "
                         f"limit {manifest.get('joints', {}).get(bone, 0) + DISLOCATION_MARGIN})",
                index, (int(jx) - int(ox), int(jy) - int(oy))))
    return violations


def silhouette_border(image) -> np.ndarray:
    """Opaque pixels with a transparent 4-neighbour (outside the canvas = transparent)."""
    opaque = as_rgba(image)[..., 3] > 0
    padded = np.pad(opaque, 1, constant_values=False)
    inner = padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    return opaque & ~inner


def bare_border_count(image, outline_rgb) -> int:
    """Silhouette border pixels that do not have the outline colour."""
    rgba = as_rgba(image)
    is_outline = (rgba[..., :3] == np.array(outline_rgb, dtype=np.uint8)).all(axis=2)
    return int((silhouette_border(rgba) & ~is_outline).sum())


def hex_to_rgb(text: str) -> tuple[int, int, int]:
    return int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16)


def hole_frames(frames, manifest: dict) -> list[int]:
    """Indices of the frames that have at least one hole pixel."""
    return sorted({v.frame for v in check_holes(frames, manifest) if v.frame is not None})


# --------------------------------------------------------------------------- #
# Sequence invariants
# --------------------------------------------------------------------------- #

def check_canvas_constant(frames, expected_size: tuple[int, int] | None = None) -> list[Violation]:
    """All frames share one (width, height); optionally a given one."""
    frames = as_frames(frames)
    if not frames:
        return [Violation("canvas_constant", "no frame at all")]
    reference = expected_size or (frames[0].shape[1], frames[0].shape[0])
    return [
        Violation("canvas_constant", f"size {(f.shape[1], f.shape[0])} != {tuple(reference)}", index)
        for index, f in enumerate(frames) if (f.shape[1], f.shape[0]) != tuple(reference)
    ]


def check_pivot_stable(pivots: Sequence[Sequence[float]],
                       canvas_size: tuple[int, int] | None = None) -> list[Violation]:
    """Per-frame pivots are one same pair of integers (inside the canvas if given).

    The pivot is a grid-corner coordinate: 0..width and 0..height are inside.
    """
    pivots = [tuple(p) for p in pivots]
    if not pivots:
        return [Violation("pivot_stable", "no pivot at all")]
    violations = []
    for index, pivot in enumerate(pivots):
        if len(pivot) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, np.integer))
                                  for v in pivot):
            violations.append(Violation("pivot_stable", f"pivot {pivot} is not a pair of integers", index))
        elif pivot != pivots[0]:
            violations.append(Violation("pivot_stable", f"pivot {pivot} != frame 0 pivot {pivots[0]}", index))
        elif canvas_size is not None and not (0 <= pivot[0] <= canvas_size[0]
                                              and 0 <= pivot[1] <= canvas_size[1]):
            violations.append(Violation(
                "pivot_stable", f"pivot {pivot} outside canvas {canvas_size[0]}x{canvas_size[1]}", index))
    return violations


def ground_offsets(frames, ground_y: int) -> list[int | None]:
    """Per frame: (bottom edge of the lowest opaque row) - ground_y.

    0 = feet exactly on the ground line, > 0 = below it (sunk), < 0 = floating.
    None for a fully transparent frame. ``ground_y`` is a grid-corner coordinate
    (the pivot's y): a pixel of row ``ground_y - 1`` stands on the line.
    """
    offsets = []
    for frame in as_frames(frames):
        rows = np.nonzero((frame[..., 3] > 0).any(axis=1))[0]
        offsets.append(None if len(rows) == 0 else int(rows.max()) + 1 - int(ground_y))
    return offsets


def check_ground_line(frames, ground_y: int, tolerance=0) -> list[Violation]:
    """Feet on the ground line, within ``tolerance`` px (an int, or one int per frame)."""
    offsets = ground_offsets(frames, ground_y)
    tolerances = [tolerance] * len(offsets) if isinstance(tolerance, int) else list(tolerance)
    if len(tolerances) != len(offsets):
        raise ValueError("one tolerance per frame is required")
    violations = []
    for index, (offset, allowed) in enumerate(zip(offsets, tolerances)):
        if offset is None:
            violations.append(Violation("ground_line", "frame is fully transparent", index))
        elif abs(offset) > allowed:
            where = "below" if offset > 0 else "above"
            violations.append(Violation(
                "ground_line", f"lowest pixels are {abs(offset)} px {where} the ground line "
                               f"y={ground_y} (tolerance {allowed} px)", index))
    return violations


def frame_distance(a, b) -> int:
    """Number of pixels that differ between two frames of the same size."""
    a, b = canonical(a), canonical(b)
    if a.shape != b.shape:
        raise ValueError(f"frames differ in size: {a.shape} vs {b.shape}")
    return int((a != b).any(axis=2).sum())


def check_loop_closed(frames, tolerance: float = LOOP_TOLERANCE) -> list[Violation]:
    """Wrap step (last -> first) neither zero nor above ``tolerance`` x the biggest in-loop step.

    Call it for looping animations only. A single frame always passes.
    """
    frames = as_frames(frames)
    if not frames:
        return [Violation("loop_closed", "no frame at all")]
    if len({f.shape for f in frames}) != 1:
        return [Violation("loop_closed", "frames differ in size, loop cannot be compared")]
    if len(frames) == 1:
        return []
    wrap = frame_distance(frames[-1], frames[0])
    if wrap == 0:
        return [Violation("loop_closed", "last frame is a copy of the first one (pose held twice)",
                          len(frames) - 1)]
    steps = [frame_distance(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    if wrap > max(steps) * tolerance:
        return [Violation(
            "loop_closed",
            f"wrap step changes {wrap} px, more than {tolerance:g} x the biggest "
            f"in-loop step ({max(steps)} px)",
            len(frames) - 1)]
    return []


# --------------------------------------------------------------------------- #
# Part assignment (rig.json regions vs sprite)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Rasterized:
    labels: np.ndarray                   # (H, W) int, 0 = unassigned, i = parts[i - 1]
    parts: tuple[str, ...]
    duplicates: tuple[tuple[int, int, str, str], ...]   # (x, y, previous part, new part)
    out_of_bounds: tuple[tuple[str, tuple[int, ...]], ...]


def rasterize_rig(rig: dict, size: tuple[int, int]) -> Rasterized:
    """Reference label map from ``rig["parts"]``.

    Contract reading: rects ``[x, y, w, h]`` then ``pixels`` ``[x, y]`` are
    *added* to the part; parts are applied in file order and the last one
    wins. Anything outside the canvas is recorded, not drawn.
    """
    width, height = size
    labels = np.zeros((height, width), dtype=np.int32)
    names, duplicates, outside = [], [], []

    def claim(x, y, label, part):
        previous = labels[y, x]
        if previous and previous != label:
            duplicates.append((x, y, names[previous - 1], part))
        labels[y, x] = label

    for label, (part, spec) in enumerate(rig["parts"].items(), start=1):
        names.append(part)
        region = spec.get("region", {})
        for rect in region.get("rects", []):
            x, y, w, h = rect
            if x < 0 or y < 0 or x + w > width or y + h > height:
                outside.append((part, tuple(rect)))
            for yy in range(max(y, 0), min(y + h, height)):
                for xx in range(max(x, 0), min(x + w, width)):
                    claim(xx, yy, label, part)
        for pixel in region.get("pixels", []):
            x, y = pixel
            if not (0 <= x < width and 0 <= y < height):
                outside.append((part, tuple(pixel)))
                continue
            claim(x, y, label, part)
    return Rasterized(labels, tuple(names), tuple(duplicates), tuple(outside))


def check_all_pixels_assigned(sprite, labels: np.ndarray) -> list[Violation]:
    """Every opaque pixel of ``sprite`` has a non-zero label."""
    rgba = as_rgba(sprite)
    labels = np.asarray(labels)
    if labels.shape != rgba.shape[:2]:
        return [Violation("parts_assigned",
                          f"label map {labels.shape[::-1]} != sprite {rgba.shape[1::-1]}")]
    lost = (rgba[..., 3] > 0) & (labels == 0)
    return _pixel_violations("parts_assigned", lost, None,
                             lambda x, y: "opaque source pixel belongs to no part")


def check_rig_covers_sprite(sprite, rig: dict, allow_duplicates: bool = False) -> list[Violation]:
    """Opaque pixels all assigned, none claimed twice, no region off-canvas."""
    rgba = as_rgba(sprite)
    raster = rasterize_rig(rig, (rgba.shape[1], rgba.shape[0]))
    violations = check_all_pixels_assigned(rgba, raster.labels)
    if not allow_duplicates:
        violations += [
            Violation("parts_assigned", f"pixel claimed by '{a}' then '{b}'", None, (x, y))
            for x, y, a, b in raster.duplicates[:MAX_REPORTED]
        ]
    violations += [
        Violation("parts_assigned", f"part '{part}' region {shape} leaves the canvas")
        for part, shape in raster.out_of_bounds[:MAX_REPORTED]
    ]
    used = set(np.unique(raster.labels).tolist())
    violations += [
        Violation("parts_assigned", f"part '{name}' owns no pixel")
        for index, name in enumerate(raster.parts, start=1) if index not in used
    ]
    return violations


# --------------------------------------------------------------------------- #
# Everything at once
# --------------------------------------------------------------------------- #

def check_frames(frames, source_palette, *, manifest: dict | None = None, loop: bool = False,
                 source_orphans: int = 0) -> list[Violation]:
    """Frame-level invariants: canvas, alpha, palette, orphans.

    With ``manifest`` (the ``frames.json`` of these frames): also ``holes`` and
    ``pivot_stable``, and the canvas must be the declared one. ``loop`` adds
    ``loop_closed``. The ground line has its own ``check_ground_line``.
    """
    frames = as_frames(frames)
    expected = tuple(manifest["canvas"]) if manifest is not None else None
    violations = check_canvas_constant(frames, expected)
    violations += check_alpha_binary(frames)
    violations += check_palette(frames, source_palette)
    violations += check_orphans(frames, source_orphans)
    if manifest is not None:
        violations += check_holes(frames, manifest)
        violations += check_pivot_stable([f.get("pivot") or () for f in manifest["frames"]],
                                         tuple(manifest["canvas"]))
    if loop:
        violations += check_loop_closed(frames)
    return violations
