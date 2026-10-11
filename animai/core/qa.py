"""QA validation of rendered frames -> report.json (pass/fail)."""
from __future__ import annotations

import numpy as np

from .kinematics import cos_sin
from .morph import components, dilate4, enclosed_transparent, neighbor_count8
from .sprite import hex_color, pack_rgb

CHECK_IDS = ["palette", "alpha_binary", "orphans", "holes", "pivot_stable",
             "canvas_constant", "loop_closed", "parts_assigned"]
MAX_ENTRIES_PER_CHECK = 20
LOOP_TOLERANCE_PERCENT = 10      # the closing step may exceed the largest step by this much


def find_orphans(rgba: np.ndarray) -> list[tuple[int, int]]:
    """Opaque pixels with no opaque 8-neighbour, as ``(x, y)`` in raster order."""
    opaque = rgba[..., 3] > 0
    ys, xs = np.nonzero(opaque & (neighbor_count8(opaque) == 0))
    return [(int(x), int(y)) for x, y in zip(xs, ys)]


def disc_offsets(radius: int) -> list[tuple[int, int]]:
    """Pixel offsets ``(dx, dy)`` with ``dx*dx + dy*dy <= radius*radius``, raster order."""
    return [(dx, dy) for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)
            if dx * dx + dy * dy <= radius * radius]


JOINT_MARGIN = 1     # pixel of play: a 1 px notch on the rim of an articulation is tolerated


def joint_radii(rig: dict, parts: list, shape: tuple[int, int]) -> dict[str, int]:
    """Radius of the disc that must stay opaque around each articulation: ``max(r0 - 1, 0)``."""
    return {b: max(r0 - JOINT_MARGIN, 0) for b, r0 in joint_rest_radii(rig, parts, shape).items()}


def joint_rest_radii(rig: dict, parts: list, shape: tuple[int, int]) -> dict[str, int]:
    """Rest radius ``r0`` of each articulation (largest disc of limb material around the joint).

    For every non-root bone that carries at least one part: the *limb material*
    is the union of the data (own pixels + filled hidden zone) of the parts
    attached to the bone and of those attached to its parent bone. ``r0`` =
    largest integer such that every pixel of the disc of radius ``r0`` centred
    on the joint belongs to the limb material at rest. The bone is listed with
    radius ``max(r0 - JOINT_MARGIN, 0)``; it is skipped when the joint pixel
    itself is not limb material.
    """
    h, w = shape
    material: dict[str, np.ndarray] = {}
    for part in parts:
        mask = material.setdefault(part.bone, np.zeros((h, w), dtype=bool))
        ph, pw = part.image.shape[:2]
        x0, y0 = part.origin
        mask[y0:y0 + ph, x0:x0 + pw] |= part.image[..., 3] > 0
    out: dict[str, int] = {}
    for name, bone in rig["bones"].items():
        parent = bone.get("parent")
        if parent is None or name not in material:
            continue
        limb = material[name] | material.get(parent, False)
        jx, jy = bone["joint"]
        if not (0 <= jx < w and 0 <= jy < h) or not limb[jy, jx]:
            continue
        r0 = 0
        while all(0 <= jx + dx < w and 0 <= jy + dy < h and limb[jy + dy, jx + dx]
                  for dx, dy in disc_offsets(r0 + 1)):
            r0 += 1
        out[name] = r0
    return out


DISLOCATION_SLACK = 2      # px: 1 for the two roundings, 1 for a deliberate 1 px offset (breathing)


def find_dislocations(manifest: dict, index: int) -> list[tuple[int, int, str, float]]:
    """Articulations pulled out of their socket in frame ``index``, whatever the limb width.

    Purely kinematic, so it also sees a limb detached *in front of the body*,
    where no pixel becomes transparent. For every non-root bone ``B`` that
    carries a part, with parent ``P``, rest joints ``jB`` / ``jP`` (``rest.bones``)
    and the frame's world joints ``JB`` / ``JP`` and world angle ``aP`` of the
    parent (``frames[i].bones``)::

        (dx, dy) = jB - jP
        A = JP + (dx*cos aP + dy*sin aP, -dx*sin aP + dy*cos aP)     # where the parent holds the joint
        gap = max(|JBx - Ax|, |JBy - Ay|)

    ``B`` is dislocated when ``gap > joints[B] + 2`` (``joints[B]`` = 0 when the
    bone is not listed). When the manifest has ``rest_offsets[B]``, that offset
    is added to ``A`` first: a rest offset is a wanted displacement. Returns ``(x, y, bone, gap)`` with ``(x, y)`` = ``JB``
    in canvas coordinates.
    """
    rest = manifest.get("rest", {}).get("bones", {})
    pose = manifest["frames"][index].get("bones", {})
    origin = manifest.get("origin", [0, 0])
    radii = manifest.get("joints", {})
    with_parts = {p.get("bone") for p in manifest.get("parts", {}).values()}
    out = []
    for bone, spec in rest.items():
        parent = spec.get("parent")
        if parent is None or bone not in with_parts or bone not in pose or parent not in pose \
                or parent not in rest:
            continue
        dx = spec["joint"][0] - rest[parent]["joint"][0]
        dy = spec["joint"][1] - rest[parent]["joint"][1]
        c, s_ = cos_sin(float(pose[parent]["angle"]))
        shift = (manifest.get("rest_offsets") or {}).get(bone, [0, 0])
        ax = pose[parent]["joint"][0] + dx * c + dy * s_ + shift[0]
        ay = pose[parent]["joint"][1] - dx * s_ + dy * c + shift[1]
        jx, jy = pose[bone]["joint"]
        gap = max(abs(jx - ax), abs(jy - ay))
        if gap > int(radii.get(bone, 0)) + DISLOCATION_SLACK + 1e-6:
            out.append((jx - origin[0], jy - origin[1], bone, gap))
    return out


def find_joint_holes(frame: np.ndarray, origin, pose: dict, radii: dict) -> list[tuple[int, int, str]]:
    """Open articulations: transparent pixels inside a joint disc.

    ``pose`` = ``frames[i].bones`` of the manifest (world ``joint`` in sprite
    coordinates), ``radii`` = manifest ``joints``. A pixel outside the canvas
    counts as transparent. Returns ``(x, y, bone)`` in canvas coordinates.
    """
    h, w = frame.shape[:2]
    out = []
    for bone in radii:
        if bone not in pose:
            continue
        cx, cy = pose[bone]["joint"][0] - origin[0], pose[bone]["joint"][1] - origin[1]
        for dx, dy in disc_offsets(int(radii[bone])):
            x, y = cx + dx, cy + dy
            if not (0 <= x < w and 0 <= y < h) or frame[y, x, 3] == 0:
                out.append((x, y, bone))
    return out


def find_discovery_holes(frame: np.ndarray, origin, parts: dict, rest_bones: dict,
                         pose: dict) -> list[tuple[int, int, str]]:
    """Uncovered hidden zones: transparent pixels where a part should continue but has no data.

    For every part with a non-empty ``missing`` list (rest pixels of its hidden
    zone left unfilled), each transparent pixel ``t`` of the frame is mapped back
    to the rest pose of the part's bone::

        x = jx + 0.5 + dx*cos(a) - dy*sin(a)
        y = jy + 0.5 + dx*sin(a) + dy*cos(a)

    with ``(dx, dy) = t + origin - J``, ``j`` / ``J`` the rest / world joint of the
    part's bone and ``a`` its world angle (pixel centres cancel out); the rest pixel
    is ``(floor(x), floor(y))``. ``t`` is a hole when that pixel is in ``missing``.
    Returns ``(x, y, part)`` in canvas coordinates.
    """
    out = []
    ys, xs = np.nonzero(frame[..., 3] == 0)
    if xs.size == 0:
        return out
    for name, meta in parts.items():
        missing = {(int(x), int(y)) for x, y in meta.get("missing", [])}
        bone = meta.get("bone")
        if not missing or bone not in pose or bone not in rest_bones:
            continue
        jx, jy = rest_bones[bone]["joint"]
        wx, wy = pose[bone]["joint"]
        c, s_ = cos_sin(float(pose[bone]["angle"]))
        dx = xs + origin[0] - wx
        dy = ys + origin[1] - wy
        rx = np.floor(jx + 0.5 + dx * c - dy * s_ + 1e-7).astype(np.int64)
        ry = np.floor(jy + 0.5 + dx * s_ + dy * c + 1e-7).astype(np.int64)
        for x, y, qx, qy in zip(xs.tolist(), ys.tolist(), rx.tolist(), ry.tolist()):
            if (qx, qy) in missing:
                out.append((x, y, name))
    out.sort(key=lambda t: (t[1], t[0], t[2]))
    return out


def find_holes(frame: np.ndarray, manifest: dict, index: int) -> list[tuple[int, int, str]]:
    """Every hole of frame ``index``: ``(x, y, cause)``, canvas coordinates, raster order."""
    origin = manifest.get("origin", [0, 0])
    pose = manifest["frames"][index].get("bones", {})
    holes = [(x, y, f"open joint '{b}'") for x, y, b in
             find_joint_holes(frame, origin, pose, manifest.get("joints", {}))]
    holes += [(x, y, f"part '{p}' has no data under its front neighbour") for x, y, p in
              find_discovery_holes(frame, origin, manifest.get("parts", {}),
                                   manifest.get("rest", {}).get("bones", {}), pose)]
    holes += [(x, y, f"dislocated joint '{b}' ({gap:.0f} px from where its parent holds it)")
              for x, y, b, gap in find_dislocations(manifest, index)]
    holes.sort(key=lambda t: (t[1], t[0], t[2]))
    return holes


def source_stats(rgba: np.ndarray) -> dict:
    """Baselines measured on the source sprite, stored in the frames manifest."""
    return {"orphans": len(find_orphans(rgba))}


MAX_PIXELS_PER_ENTRY = 500


def _entry(check_id: str, ok: bool, detail: str = "", frame=None, pixel=None, pixels=None) -> dict:
    entry = {"id": check_id, "pass": bool(ok), "detail": detail, "frame": frame,
             "pixel": None if pixel is None else [int(pixel[0]), int(pixel[1])]}
    if pixels is not None:      # only when validate_frames(with_pixels=True)
        entry["pixels"] = [[int(p[0]), int(p[1])] for p in pixels[:MAX_PIXELS_PER_ENTRY]]
    return entry


def _group(check_id: str, failures: list[dict], ok_detail: str = "") -> list[dict]:
    if not failures:
        return [_entry(check_id, True, ok_detail)]
    if len(failures) > MAX_ENTRIES_PER_CHECK:
        extra = len(failures) - MAX_ENTRIES_PER_CHECK
        failures = failures[:MAX_ENTRIES_PER_CHECK]
        failures[-1] = {**failures[-1], "detail": failures[-1]["detail"] + f" (+{extra} more failing frames)"}
    return failures


def validate_frames(frames: list[np.ndarray], manifest: dict, with_pixels: bool = False) -> dict:
    """Run every QA check on rendered frames.

    ``with_pixels`` adds to every entry a ``pixels`` list (all faulty pixels of
    the entry, at most 500, same coordinates as ``pixel``; empty when the check
    passes). The CLI does not use it: ``report.json`` on disk is unchanged.

    ``manifest`` is the content of ``frames.json`` (see docs/schemas.md). Returns
    ``{"ok": bool, "checks": [...]}``. A passing check has one entry; a failing
    check has one entry per failing frame (first faulty pixel of that frame).
    """
    source = manifest.get("source", {})
    canvas = manifest.get("canvas")
    meta = manifest.get("frames", [])
    checks: list[dict] = []

    def _px(points):
        return list(points) if with_pixels else None

    # palette: no colour outside the source palette
    palette = np.array(sorted(int(c.lstrip("#"), 16) for c in source.get("palette", [])), dtype=np.uint32)
    fails = []
    used: set[int] = set()
    for i, f in enumerate(frames):
        opaque = f[..., 3] > 0
        packed = pack_rgb(f)
        used.update(np.unique(packed[opaque]).tolist())
        bad = opaque & ~np.isin(packed, palette)
        if bad.any():
            ys, xs = np.nonzero(bad)
            new = sorted(set(packed[bad].tolist()))
            fails.append(_entry("palette", False,
                                f"{int(bad.sum())} pixels use {len(new)} colours absent from the source "
                                f"palette (first: {hex_color(new[0])})", i, (xs[0], ys[0]),
                                _px(zip(xs.tolist(), ys.tolist()))))
    checks += _group("palette", fails, f"{len(used)} colours used, source palette has {len(palette)}")

    # alpha_binary
    fails = []
    for i, f in enumerate(frames):
        bad = (f[..., 3] != 0) & (f[..., 3] != 255)
        if bad.any():
            ys, xs = np.nonzero(bad)
            fails.append(_entry("alpha_binary", False, f"{int(bad.sum())} semi-transparent pixels",
                                i, (xs[0], ys[0]), _px(zip(xs.tolist(), ys.tolist()))))
    checks += _group("alpha_binary", fails)

    # orphans: no more isolated pixels than the source sprite has
    base = int(source.get("orphans", 0))
    fails = []
    for i, f in enumerate(frames):
        orphans = find_orphans(f)
        if len(orphans) > base:
            fails.append(_entry("orphans", False,
                                f"{len(orphans)} isolated pixels (source sprite has {base})", i, orphans[0],
                                _px(orphans)))
    checks += _group("orphans", fails, f"source sprite has {base} isolated pixels")

    # holes: open articulation, or hidden zone uncovered without data (see docs/schemas.md)
    fails = []
    for i, f in enumerate(frames):
        if i >= len(meta):
            break
        holes = find_holes(f, manifest, i)
        if holes:
            causes = sorted({h[2] for h in holes})
            fails.append(_entry("holes", False, f"{len(holes)} hole pixels: " + "; ".join(causes),
                                i, holes[0][:2], _px(h[:2] for h in holes)))
    checks += _group("holes", fails, f"{len(manifest.get('joints', {}))} articulations checked")

    # pivot_stable: same integer pivot on every frame, inside the canvas
    fails = []
    ref = manifest.get("pivot")
    valid_ref = (isinstance(ref, list) and len(ref) == 2
                 and all(isinstance(c, int) and not isinstance(c, bool) for c in ref))
    if not valid_ref:
        fails.append(_entry("pivot_stable", False, f"manifest pivot {ref!r} is not an integer pair"))
    else:
        if canvas and not (0 <= ref[0] <= canvas[0] and 0 <= ref[1] <= canvas[1]):
            fails.append(_entry("pivot_stable", False, f"pivot {ref} is outside the canvas {canvas}"))
        for i, m in enumerate(meta):
            if m.get("pivot", ref) != ref:
                fails.append(_entry("pivot_stable", False,
                                    f"pivot {m.get('pivot')} differs from {ref}", i, None))
    checks += _group("pivot_stable", fails, f"pivot {ref}" if valid_ref else "")

    # canvas_constant: every frame has the manifest canvas size, and nothing is cropped
    fails = []
    if len(frames) != len(meta):
        fails.append(_entry("canvas_constant", False,
                            f"{len(frames)} frame images for {len(meta)} manifest frames"))
    for i, f in enumerate(frames):
        size = [int(f.shape[1]), int(f.shape[0])]
        if canvas is None or size != list(canvas):
            fails.append(_entry("canvas_constant", False, f"frame is {size}, canvas is {canvas}", i, None))
    checks += _group("canvas_constant", fails, f"canvas {canvas}")

    # loop_closed: the last -> first step is neither null nor larger than the largest step of the cycle
    checks.append(_loop_check(frames, bool(manifest.get("loop", False)), with_pixels))

    # parts_assigned: every opaque source pixel belongs to a part
    unassigned = int(source.get("unassigned", 0))
    multi = int(source.get("multi_assigned", 0))
    if unassigned:
        checks.append(_entry("parts_assigned", False,
                             f"{unassigned} opaque source pixels belong to no part (lost in every frame)",
                             None, source.get("unassigned_first"),
                             _px(source.get("unassigned_pixels") or
                                 ([source["unassigned_first"]] if source.get("unassigned_first") else []))))
    else:
        checks.append(_entry("parts_assigned", True,
                             f"{multi} pixels claimed by several parts (last wins)" if multi else ""))

    if with_pixels:
        for c in checks:
            c.setdefault("pixels", [])
    metrics, warnings = frame_metrics(frames, manifest)
    return {"ok": all(c["pass"] for c in checks), "checks": checks, "metrics": metrics, "warnings": warnings}


def frame_diff(a: np.ndarray, b: np.ndarray) -> int:
    """Number of pixels that differ between two frames of the same size."""
    if a.shape != b.shape:
        return -1
    return int(np.any(a != b, axis=2).sum())


def _loop_check(frames: list[np.ndarray], loop: bool, with_pixels: bool = False) -> dict:
    if not loop:
        return _entry("loop_closed", True, "not a loop")
    n = len(frames)
    if n < 2:
        return _entry("loop_closed", True, "single frame")
    steps = [frame_diff(frames[i], frames[i + 1]) for i in range(n - 1)]
    closing = frame_diff(frames[-1], frames[0])
    if closing < 0 or min(steps) < 0:
        return _entry("loop_closed", False, "frames have different sizes", n - 1, None)
    if closing == 0:
        return _entry("loop_closed", False,
                      "last frame is identical to the first one (the pose would be held twice)", n - 1, None)
    largest = max(steps)
    limit = largest + (largest * LOOP_TOLERANCE_PERCENT + 99) // 100
    if closing > limit:
        diff = np.any(frames[-1] != frames[0], axis=2)
        ys, xs = np.nonzero(diff)
        return _entry("loop_closed", False,
                      f"last -> first changes {closing} pixels, more than the largest step "
                      f"of the cycle ({largest}, +{LOOP_TOLERANCE_PERCENT}% allowed)", n - 1, (xs[0], ys[0]),
                      list(zip(xs.tolist(), ys.tolist())) if with_pixels else None)
    return _entry("loop_closed", True, f"last -> first changes {closing} pixels, largest step {largest}")


PINHOLE_MAX_AREA = 2


def frame_metrics(frames: list[np.ndarray], manifest: dict) -> tuple[dict, list[str]]:
    """Measures that do not fail the QA but that the tool must show, with their warnings.

    Per frame: ``border`` (silhouette-border pixels), ``outline_bare`` (border
    pixels that are not outline-coloured; null when the sprite has no outline),
    ``ground_offset`` (lowest opaque row + 1 - pivot y: 0 = standing on the
    ground line, > 0 = below it, < 0 = floating; null for an empty frame) and
    ``pinholes`` (pixels of enclosed transparent regions of at most 2 pixels
    that are not holes: legitimate negative space, but worth a look).
    """
    applied = bool(manifest.get("outline"))
    outline = manifest.get("outline") or manifest.get("outline_detected") or None
    color = int(outline["color"].lstrip("#"), 16) if outline else None
    pivot = manifest.get("pivot") or [0, 0]
    per_frame, warnings = [], []
    meta = manifest.get("frames", [])
    for i, f in enumerate(frames):
        opaque = f[..., 3] > 0
        border = opaque & dilate4(np.pad(~opaque, 1, constant_values=True))[1:-1, 1:-1]
        bare = None if color is None else int((border & (pack_rgb(f) != color)).sum())
        rows = np.flatnonzero(opaque.any(axis=1))
        ground = None if rows.size == 0 else int(rows[-1]) + 1 - int(pivot[1])
        holes = {h[:2] for h in find_holes(f, manifest, i)} if i < len(meta) else set()
        pin = [p for comp in components(enclosed_transparent(opaque)) if len(comp) <= PINHOLE_MAX_AREA
               for p in comp if p not in holes]
        per_frame.append({"border": int(border.sum()), "outline_bare": bare, "ground_offset": ground,
                          "pinholes": [[x, y] for x, y in pin]})
        if pin:
            warnings.append(f"frame {i}: pinhole of {len(pin)} px at {list(pin[0])} "
                            "(enclosed negative space, not a hole)")
    if color is not None:
        base = int(outline.get("source_bare", 0))
        worst = max(range(len(per_frame)), key=lambda k: per_frame[k]["outline_bare"], default=None)
        if worst is not None and per_frame[worst]["outline_bare"] > base:
            m = per_frame[worst]
            warnings.append(f"outline: up to {m['outline_bare']} of {m['border']} border pixels without outline "
                            f"(frame {worst}; the source sprite has {base})")
    sunk = [(i, m["ground_offset"]) for i, m in enumerate(per_frame)
            if m["ground_offset"] is not None and abs(m["ground_offset"]) > 1]
    if sunk:
        warnings.append("ground: frames more than 1 px away from the ground line (frame, offset): "
                        + ", ".join(f"({i}, {o:+d})" for i, o in sunk))
    blind = sorted(b for b, r in (manifest.get("joints") or {}).items() if int(r) == 0)
    # Radius 0 is unavoidable on a 3 or 4 px limb: listed in the metrics, no warning. A rest radius
    # of 0 means the joint sits on the very edge of the limb: that one is worth a warning.
    edge = sorted(b for b, r0 in (manifest.get("joints_rest") or {}).items() if int(r0) == 0)
    if edge:
        warnings.append("joints placed on the edge of their limb (move them inside): " + ", ".join(edge))
    metrics = {"unmonitored_joints": blind,
               "outline": None if not outline else {"applied": applied, "color": outline["color"],
                                                    "source_bare": int(outline.get("source_bare", 0))},
               "frames": per_frame}
    return metrics, warnings


def unrigged_report(unassigned: list, with_pixels: bool = False) -> dict:
    """Report of a rig whose parts own no pixel yet (nothing can be rendered).

    ``parts_assigned`` fails and lists the unassigned pixels (sprite
    coordinates); the seven render checks pass with the detail
    ``not applicable: no part has pixels yet``.
    """
    checks = []
    for check_id in CHECK_IDS:
        if check_id == "parts_assigned":
            entry = _entry(check_id, False, f"{len(unassigned)} opaque source pixels belong to no part "
                                            "(no part has pixels yet)", None,
                           unassigned[0] if unassigned else None, list(unassigned) if with_pixels else None)
        else:
            entry = _entry(check_id, True, "not applicable: no part has pixels yet", None, None,
                           [] if with_pixels else None)
        checks.append(entry)
    return {"ok": False, "checks": checks,
            "metrics": {"unmonitored_joints": [], "outline": None, "frames": []}, "warnings": []}
