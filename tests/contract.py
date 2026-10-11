"""Structural validators for the documents defined in docs/schemas.md.

Each ``validate_*`` returns a list of human readable problems (empty = valid).
They only encode what the contract states; anything the contract leaves open
is deliberately not enforced here.
"""
from __future__ import annotations

import re

from tests.invariants import CHECK_IDS

CANONICAL_BONES = (
    "hips", "spine", "head",
    "arm_r", "forearm_r", "hand_r",
    "arm_l", "forearm_l", "hand_l",
    "thigh_r", "shin_r", "foot_r",
    "thigh_l", "shin_l", "foot_l",
)
VIEWS = ("side", "front", "3/4", "top-down")
FILL_MODES = ("own", "copy", "none", True, False)
CLI_KEYS = ("ok", "outputs", "warnings", "error")
RETURN_CODES = (0, 1, 2)
MAX_FAILED_ENTRIES = 20          # report.json: entries per failing check
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# docs/schemas.md, "Sortie CLI": keys every successful command must return.
CLI_OUTPUT_KEYS = {
    "prepare": ("sprite", "palette", "inspect", "size", "bbox", "scale_detected", "background",
                "background_pixels_removed", "colors"),
    "inspect": ("inspect", "size", "bbox", "zoom", "colors", "palette"),
    "rig": ("overlay", "labelmap", "parts_sheet", "report", "parts", "unassigned_count",
            "multi_assigned_count", "rest_pose_exact", "pivot", "unmonitored_joints", "thin_parts",
            "outline", "bone_numbers"),
    "animate": ("frames_dir", "manifest", "frames", "contact_sheet", "preview", "name",
                "frame_count", "duration_ms", "durations_ms", "fps", "loop", "canvas", "pivot",
                "mirror", "outline"),
    "validate": ("report", "checks", "failed", "metrics"),
    "export": ("spritesheet", "json", "gif", "format", "frame_count", "frame_size", "sheet_size",
               "pivot", "duration_ms", "mirror"),
}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int_list(value, length: int) -> bool:
    return isinstance(value, list) and len(value) == length and all(_is_int(v) for v in value)


# --------------------------------------------------------------------------- #
# CLI stdout
# --------------------------------------------------------------------------- #

def validate_cli_payload(payload) -> list[str]:
    """``{"ok": bool, "outputs": {...}, "warnings": [...], "error": null|str}``"""
    if not isinstance(payload, dict):
        return [f"stdout JSON must be an object, got {type(payload).__name__}"]
    problems = [f"missing key '{key}'" for key in CLI_KEYS if key not in payload]
    if "ok" in payload and not isinstance(payload["ok"], bool):
        problems.append("'ok' must be a boolean")
    if "outputs" in payload and not isinstance(payload["outputs"], dict):
        problems.append("'outputs' must be an object")
    if "warnings" in payload:
        if not isinstance(payload["warnings"], list):
            problems.append("'warnings' must be a list")
        elif not all(isinstance(w, str) for w in payload["warnings"]):
            problems.append("'warnings' items must be strings")
    if "error" in payload and not (payload["error"] is None or isinstance(payload["error"], str)):
        problems.append("'error' must be null or a string")
    if not problems:
        if payload["ok"] and payload["error"] is not None:
            problems.append("'error' must be null when ok is true")
        if not payload["ok"] and not payload["error"]:
            problems.append("'error' must be a non-empty string when ok is false")
        texts = list(payload["warnings"]) + ([payload["error"]] if payload["error"] else [])
        if any(not text.isascii() for text in texts):
            problems.append("messages must be ASCII")
    return problems


def missing_output_keys(command: str, outputs: dict) -> list[str]:
    """Contract keys of a successful ``command`` that are absent from ``outputs``."""
    return [key for key in CLI_OUTPUT_KEYS[command] if key not in outputs]


# --------------------------------------------------------------------------- #
# rig.json
# --------------------------------------------------------------------------- #

def _region_problems(region, label: str) -> list[str]:
    if not isinstance(region, dict):
        return [f"{label} must be an object"]
    problems = []
    rects = region.get("rects", [])
    if not isinstance(rects, list) or not all(_is_int_list(r, 4) for r in rects):
        problems.append(f"{label}.rects must be a list of [x, y, w, h] integers")
    elif any(r[2] <= 0 or r[3] <= 0 for r in rects):
        problems.append(f"{label}: rect with non positive width/height")
    pixels = region.get("pixels", [])
    if not isinstance(pixels, list) or not all(_is_int_list(p, 2) for p in pixels):
        problems.append(f"{label}.pixels must be a list of [x, y] integers")
    polygons = region.get("polygons", [])
    if not isinstance(polygons, list) or not all(
            isinstance(poly, list) and len(poly) >= 3 and all(_is_int_list(pt, 2) for pt in poly)
            for poly in polygons):
        problems.append(f"{label}.polygons must be a list of lists of at least 3 [x, y] points")
    return problems


def validate_rig(rig) -> list[str]:
    if not isinstance(rig, dict):
        return ["rig must be an object"]
    problems = []
    if rig.get("version") != 1 or not _is_int(rig.get("version")):
        problems.append("'version' must be 1")
    for key in ("sprite", "template"):
        if not isinstance(rig.get(key), str) or not rig.get(key):
            problems.append(f"'{key}' must be a non-empty string")
    if rig.get("view") not in VIEWS:
        problems.append(f"'view' must be one of {', '.join(VIEWS)}")
    outline = rig.get("outline", "auto")
    if not (outline in ("auto", "none") or outline is False
            or (isinstance(outline, str) and _HEX.match(outline))):
        problems.append("'outline' must be \"auto\", \"none\", false or \"#RRGGBB\"")
    if rig.get("outline_mode", "outside") not in ("outside", "inside"):
        problems.append("'outline_mode' must be \"outside\" or \"inside\"")
    pivot = rig.get("pivot", [0.5, 1.0])
    if not (isinstance(pivot, list) and len(pivot) == 2 and all(_is_number(v) for v in pivot)
            and all(0 <= v <= 1 for v in pivot)):
        problems.append("'pivot' must be [fx, fy], each in 0..1")

    bones = rig.get("bones")
    if not isinstance(bones, dict) or not bones:
        return problems + ["'bones' must be a non-empty object"]
    if "hips" not in bones:
        problems.append("bone 'hips' is mandatory")
    for name, bone in bones.items():
        if not isinstance(bone, dict):
            problems.append(f"bone '{name}' must be an object")
            continue
        parent = bone.get("parent", "<missing>")
        # a canonical parent absent from the rig is re-attached (warning), not an error
        if parent is not None and parent not in bones and parent not in CANONICAL_BONES:
            problems.append(f"bone '{name}': unknown parent {parent!r}")
        if parent == name:
            problems.append(f"bone '{name}' is its own parent")
        if not _is_int_list(bone.get("joint"), 2):
            problems.append(f"bone '{name}': 'joint' must be [x, y] integers")
    if isinstance(bones.get("hips"), dict) and bones["hips"].get("parent", "<missing>") is not None:
        problems.append("bone 'hips' is the root, its parent must be null")
    for name in bones:  # every chain must end at a root without looping
        seen, current = set(), name
        while isinstance(bones.get(current), dict) and bones[current].get("parent") in bones:
            if current in seen:
                problems.append(f"bone '{name}': cycle in the parent chain")
                break
            seen.add(current)
            current = bones[current]["parent"]

    parts = rig.get("parts")
    if not isinstance(parts, dict) or not parts:
        return problems + ["'parts' must be a non-empty object"]
    for name, part in parts.items():
        if not isinstance(part, dict):
            problems.append(f"part '{name}' must be an object")
            continue
        if part.get("bone") not in bones:
            problems.append(f"part '{name}': unknown bone {part.get('bone')!r}")
        if not _is_int(part.get("z", 0)):
            problems.append(f"part '{name}': 'z' must be an integer")
        if not _is_int(part.get("overlap", 0)) or part.get("overlap", 0) < 0:
            problems.append(f"part '{name}': 'overlap' must be an integer >= 0")
        fill = part.get("fill", "own")
        if not any(fill is mode or (isinstance(fill, str) and fill == mode) for mode in FILL_MODES):
            problems.append(f"part '{name}': 'fill' must be \"own\", \"copy\" or \"none\"")
        if "fill_color" in part and not (isinstance(part["fill_color"], str)
                                         and _HEX.match(part["fill_color"])):
            problems.append(f"part '{name}': 'fill_color' must be \"#RRGGBB\"")
        region = part.get("region")
        if not isinstance(region, dict):
            problems.append(f"part '{name}': 'region' must be an object")
            continue
        problems += _region_problems(region, f"part '{name}': region")
        if "exclude" in region:
            problems += _region_problems(region["exclude"], f"part '{name}': region.exclude")

    ik = rig.get("ik", {})
    if not isinstance(ik, dict):
        problems.append("'ik' must be an object")
    else:
        for name, chain in ik.items():
            if not isinstance(chain, dict):
                problems.append(f"ik '{name}' must be an object")
                continue
            links = chain.get("chain")
            target = chain.get("target_bone")
            if not isinstance(links, list) or len(links) != 2 or any(b not in bones for b in links):
                problems.append(f"ik '{name}': 'chain' must list two existing bones")
            elif (isinstance(bones.get(links[1]), dict) and bones[links[1]].get("parent") != links[0]) \
                    or (isinstance(bones.get(target), dict) and bones[target].get("parent") != links[1]):
                problems.append(f"ik '{name}': hierarchy chain[0] > chain[1] > target_bone is mandatory")
            if target not in bones:
                problems.append(f"ik '{name}': unknown target_bone {target!r}")
            if chain.get("bend", -1) not in (-1, 1) or isinstance(chain.get("bend", -1), bool):
                problems.append(f"ik '{name}': 'bend' must be -1 or 1")
    return problems


# --------------------------------------------------------------------------- #
# anim.json
# --------------------------------------------------------------------------- #

def validate_anim(anim) -> list[str]:
    if not isinstance(anim, dict):
        return ["anim must be an object"]
    problems = []
    if anim.get("version") != 1 or not _is_int(anim.get("version")):
        problems.append("'version' must be 1")
    if "name" in anim and (not isinstance(anim["name"], str) or not anim["name"]):
        problems.append("'name' must be a non-empty string")
    if "loop" in anim and not isinstance(anim["loop"], bool):
        problems.append("'loop' must be a boolean")
    if "fps" in anim and (not _is_number(anim["fps"]) or anim["fps"] <= 0):
        problems.append("'fps' must be a number > 0")
    frames = anim.get("frames")
    if not isinstance(frames, list) or not frames:
        return problems + ["'frames' must be a non-empty list"]
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            problems.append(f"frame {index} must be an object")
            continue
        if "duration_ms" in frame and (not _is_number(frame["duration_ms"]) or frame["duration_ms"] <= 0):
            problems.append(f"frame {index}: 'duration_ms' must be a number > 0")
        key = frame.get("key", False)
        if not (isinstance(key, bool) or (_is_number(key) and key >= 0)):
            problems.append(f"frame {index}: 'key' must be a boolean or a number >= 0")
        if "label" in frame and not isinstance(frame["label"], str):
            problems.append(f"frame {index}: 'label' must be a string")
        for block in ("bones", "ik"):
            poses = frame.get(block, {})
            if not isinstance(poses, dict):
                problems.append(f"frame {index}: '{block}' must be an object")
                continue
            for name, pose in poses.items():
                label = f"frame {index}: {block} '{name}'"
                if not isinstance(pose, dict):
                    problems.append(f"{label} must be an object")
                    continue
                if "rot" in pose and not _is_number(pose["rot"]):
                    problems.append(f"{label}: 'rot' must be a number")
                if "pos" in pose and not _is_int_list(pose["pos"], 2):
                    problems.append(f"{label}: 'pos' must be [dx, dy] integers")
        z = frame.get("z", {})
        if not isinstance(z, dict) or not all(_is_int(v) for v in z.values()):
            problems.append(f"frame {index}: 'z' must map bone names to integers")
    return problems


def total_duration_ms(anim: dict) -> float:
    return sum(frame["duration_ms"] for frame in anim["frames"])


# --------------------------------------------------------------------------- #
# frames.json
# --------------------------------------------------------------------------- #

def validate_frames_manifest(manifest) -> list[str]:
    """``frames.json`` written by ``animate`` (what the holes check relies on)."""
    if not isinstance(manifest, dict):
        return ["frames.json must be an object"]
    problems = []
    if not isinstance(manifest.get("name"), str) or not manifest.get("name"):
        problems.append("'name' must be a non-empty string")
    if not isinstance(manifest.get("loop"), bool):
        problems.append("'loop' must be a boolean")
    if not _is_number(manifest.get("fps")) or manifest.get("fps") <= 0:
        problems.append("'fps' must be a number > 0")
    for key in ("canvas", "origin", "pivot"):
        if not _is_int_list(manifest.get(key), 2):
            problems.append(f"'{key}' must be a pair of integers")
    source = manifest.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("palette"), list) \
            or not all(isinstance(c, str) and _HEX.match(c) for c in source.get("palette", [])):
        problems.append("'source.palette' must be a list of \"#RRGGBB\"")
    elif not _is_int(source.get("orphans")):
        problems.append("'source.orphans' must be an integer")

    rest = (manifest.get("rest") or {}).get("bones") if isinstance(manifest.get("rest"), dict) else None
    if not isinstance(rest, dict) or not rest:
        problems.append("'rest.bones' must be a non-empty object")
        rest = {}
    else:
        problems += [f"rest bone '{name}': 'joint' must be [x, y] integers"
                     for name, bone in rest.items()
                     if not isinstance(bone, dict) or not _is_int_list(bone.get("joint"), 2)]

    parts = manifest.get("parts")
    if not isinstance(parts, dict):
        problems.append("'parts' must be an object")
    else:
        for name, part in parts.items():
            if not isinstance(part, dict) or part.get("bone") not in rest:
                problems.append(f"part '{name}': 'bone' must be a bone of rest.bones")
            elif not isinstance(part.get("missing"), list) \
                    or not all(_is_int_list(p, 2) for p in part["missing"]):
                problems.append(f"part '{name}': 'missing' must be a list of [x, y] integers")

    joints = manifest.get("joints")
    if not isinstance(joints, dict):
        problems.append("'joints' must be an object")
    else:
        problems += [f"joints '{name}': radius must be an integer >= 0 on a bone of rest.bones"
                     for name, radius in joints.items()
                     if not _is_int(radius) or radius < 0 or name not in rest]
        rest_radii = manifest.get("joints_rest")
        if not isinstance(rest_radii, dict) or set(rest_radii) != set(joints):
            problems.append("'joints_rest' must give the rest radius r0 of every bone of 'joints'")
        else:
            problems += [f"joints '{name}': must be max(joints_rest - 1, 0)"
                         for name, radius in joints.items()
                         if _is_int(rest_radii[name]) and radius != max(rest_radii[name] - 1, 0)]
    if not isinstance(manifest.get("mirror"), bool):
        problems.append("'mirror' must be a boolean")
    for key, fields in (("outline", ("color", "mode", "inner_parts", "source_bare", "source_border")),
                        ("outline_detected", ("color", "source_bare", "source_border"))):
        if key not in manifest:
            problems.append(f"'{key}' must be present (null or an object)")
        elif manifest[key] is not None and (not isinstance(manifest[key], dict)
                                            or any(f not in manifest[key] for f in fields)):
            problems.append(f"'{key}' must be null or an object with {', '.join(fields)}")

    frames = manifest.get("frames")
    if not isinstance(frames, list) or not frames:
        return problems + ["'frames' must be a non-empty list"]
    for index, frame in enumerate(frames):
        label = f"frame {index}"
        if not isinstance(frame, dict):
            problems.append(f"{label} must be an object")
            continue
        if not isinstance(frame.get("file"), str):
            problems.append(f"{label}: 'file' must be a string")
        if not _is_number(frame.get("duration_ms")) or frame.get("duration_ms") <= 0:
            problems.append(f"{label}: 'duration_ms' must be a number > 0")
        if not _is_int_list(frame.get("pivot"), 2):
            problems.append(f"{label}: 'pivot' must be a pair of integers")
        if not _is_int(frame.get("source_frame")) or frame.get("source_frame") < 0:
            problems.append(f"{label}: 'source_frame' must be an integer >= 0")
        bones = frame.get("bones")
        if not isinstance(bones, dict):
            problems.append(f"{label}: 'bones' must be an object")
            continue
        for name in rest:
            pose = bones.get(name)
            if not isinstance(pose, dict) or not _is_int_list(pose.get("joint"), 2) \
                    or not _is_number(pose.get("angle")):
                problems.append(f"{label}: bone '{name}' needs a world 'angle' and an integer 'joint'")
            elif not -180 < pose["angle"] <= 180:
                problems.append(f"{label}: bone '{name}': angle {pose['angle']} not in ]-180, 180]")
    if not problems and manifest.get("duration_ms") != sum(f["duration_ms"] for f in frames):
        problems.append("'duration_ms' must be the sum of the frame durations")
    return problems


# --------------------------------------------------------------------------- #
# report.json
# --------------------------------------------------------------------------- #

def validate_report(report, require_all_checks: bool = True, require_metrics: bool = False) -> list[str]:
    if not isinstance(report, dict):
        return ["report must be an object"]
    problems = []
    if not isinstance(report.get("ok"), bool):
        problems.append("'ok' must be a boolean")
    checks = report.get("checks")
    if not isinstance(checks, list):
        return problems + ["'checks' must be a list"]
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            problems.append(f"check {index} must be an object")
            continue
        label = f"check {index} ({check.get('id')!r})"
        for key in ("id", "pass", "detail", "frame", "pixel"):
            if key not in check:
                problems.append(f"{label}: missing key '{key}'")
        if check.get("id") not in CHECK_IDS:
            problems.append(f"{label}: unknown id, expected one of {', '.join(CHECK_IDS)}")
        if not isinstance(check.get("pass"), bool):
            problems.append(f"{label}: 'pass' must be a boolean")
        if not isinstance(check.get("detail"), str):
            problems.append(f"{label}: 'detail' must be a string")
        frame = check.get("frame")
        if frame is not None and (not _is_int(frame) or frame < 0):
            problems.append(f"{label}: 'frame' must be null or an integer >= 0")
        pixel = check.get("pixel")
        if pixel is not None and not _is_int_list(pixel, 2):
            problems.append(f"{label}: 'pixel' must be null or [x, y] integers")
    entries = [c for c in checks if isinstance(c, dict)]
    if require_all_checks:
        present = {c.get("id") for c in entries}
        problems += [f"check '{cid}' is missing" for cid in CHECK_IDS if cid not in present]
    for cid in CHECK_IDS:   # one entry when passing, one per faulty frame (<= 20) when failing
        mine = [c for c in entries if c.get("id") == cid]
        failed = [c for c in mine if c.get("pass") is False]
        if failed and len(failed) != len(mine):
            problems.append(f"check '{cid}' mixes passing and failing entries")
        elif not failed and len(mine) > 1:
            problems.append(f"check '{cid}' passes but has {len(mine)} entries")
        elif len(failed) > MAX_FAILED_ENTRIES:
            problems.append(f"check '{cid}' has more than {MAX_FAILED_ENTRIES} failing entries")
    if isinstance(report.get("ok"), bool) and len(entries) == len(checks):
        if report["ok"] != all(c.get("pass") is True for c in checks):
            problems.append("'ok' must be true exactly when every check passes")
    if require_metrics:
        problems += validate_report_metrics(report)
    return problems


def validate_report_metrics(report: dict) -> list[str]:
    """``metrics`` and ``warnings`` of report.json ("Mesures et avertissements")."""
    problems = []
    warnings = report.get("warnings")
    if not isinstance(warnings, list) or not all(isinstance(w, str) for w in warnings):
        problems.append("'warnings' must be a list of strings")
    metrics = report.get("metrics")
    if not isinstance(metrics, dict):
        return problems + ["'metrics' must be an object"]
    unmonitored = metrics.get("unmonitored_joints")
    if not isinstance(unmonitored, list) or not all(isinstance(b, str) for b in unmonitored):
        problems.append("'metrics.unmonitored_joints' must be a list of bone names")
    outline = metrics.get("outline", "<missing>")
    if outline is not None and not (isinstance(outline, dict) and isinstance(outline.get("applied"), bool)
                                    and isinstance(outline.get("color"), str)
                                    and _is_int(outline.get("source_bare"))):
        problems.append("'metrics.outline' must be null or {applied, color, source_bare}")
    frames = metrics.get("frames")
    if not isinstance(frames, list):
        return problems + ["'metrics.frames' must be a list"]
    for index, frame in enumerate(frames):
        label = f"metrics.frames[{index}]"
        if not isinstance(frame, dict):
            problems.append(f"{label} must be an object")
            continue
        if not _is_int(frame.get("border")) or frame.get("border") < 0:
            problems.append(f"{label}: 'border' must be an integer >= 0")
        bare = frame.get("outline_bare", "<missing>")
        if outline is None and bare is not None:
            problems.append(f"{label}: 'outline_bare' must be null when the sprite has no outline")
        if outline is not None and not _is_int(bare):
            problems.append(f"{label}: 'outline_bare' must be an integer when the sprite has an outline")
        offset = frame.get("ground_offset", "<missing>")
        if offset is not None and not _is_int(offset):
            problems.append(f"{label}: 'ground_offset' must be an integer or null")
        pinholes = frame.get("pinholes")
        if not isinstance(pinholes, list) or not all(_is_int_list(p, 2) for p in pinholes):
            problems.append(f"{label}: 'pinholes' must be a list of [x, y] integers")
    return problems


def failing_frames(report: dict, check_id: str) -> list[int]:
    """Frames named by the failing entries of ``check_id``."""
    return sorted({c["frame"] for c in report["checks"]
                   if c["id"] == check_id and not c["pass"] and c["frame"] is not None})
