"""anim.json: validation, presets, retargeting on a rig."""
from __future__ import annotations

import copy
import re
from pathlib import Path

from .errors import AnimaiError
from .imageio import read_json
from .sprite import parse_hex_color
from .timing import DEFAULT_FPS

PRESETS_DIR = Path(__file__).resolve().parent.parent / "presets"


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_pos(where: str, pos) -> None:
    if not (isinstance(pos, list) and len(pos) == 2 and all(_is_int(c) for c in pos)):
        raise AnimaiError(f"{where}: pos must be [dx, dy] with integer pixels, got {pos}")


ANIM_KEYS = {"version", "name", "loop", "fps", "frames", "rest_offsets"}
FRAME_KEYS = {"duration_ms", "bones", "z", "ik", "key", "label", "paint", "swap"}
POSE_KEYS = {"rot", "pos"}
IK_TARGET_KEYS = {"pos", "rot"}


def _unknown(obj: dict, allowed: set, where: str) -> list[str]:
    return [f"unknown key '{k}' in {where}: ignored" for k in obj
            if k not in allowed and not str(k).startswith("_")]


def validate_anim(anim: dict) -> list[str]:
    """Check the structure of an animation. Raises AnimaiError; returns warnings."""
    warnings: list[str] = _unknown(anim, ANIM_KEYS, "anim")
    if anim.get("version", 1) != 1:
        raise AnimaiError(f"unsupported anim version {anim.get('version')!r} (expected 1)")
    fps = anim.get("fps", DEFAULT_FPS)
    if not (_is_num(fps) and fps > 0):
        raise AnimaiError("anim.fps must be a number > 0")
    if not isinstance(anim.get("loop", True), bool):
        raise AnimaiError("anim.loop must be true or false")
    if not isinstance(anim.get("rest_offsets", False), bool):
        raise AnimaiError("anim.rest_offsets must be true or false")
    frames = anim.get("frames")
    if not isinstance(frames, list) or not frames:
        raise AnimaiError("anim.frames must be a non-empty list")
    tick = 1000.0 / fps
    off_grid = []
    for i, frame in enumerate(frames):
        where = f"frame {i}"
        if not isinstance(frame, dict):
            raise AnimaiError(f"{where} must be an object")
        if "duration_ms" in frame:
            d = frame["duration_ms"]
            if not (_is_num(d) and d > 0):
                raise AnimaiError(f"{where}: duration_ms must be a number > 0")
            ticks = d / tick
            if abs(ticks - round(ticks)) > 1e-6:
                off_grid.append(i)
        warnings += _unknown(frame, FRAME_KEYS, where)
        key = frame.get("key", False)
        if not (isinstance(key, bool) or (_is_num(key) and key >= 0)):
            raise AnimaiError(f"{where}: key must be true/false or a number >= 0")
        if not isinstance(frame.get("label", ""), str):
            raise AnimaiError(f"{where}: label must be a string")
        bones = frame.get("bones", {})
        if not isinstance(bones, dict):
            raise AnimaiError(f"{where}: bones must be an object")
        for name, pose in bones.items():
            if not isinstance(pose, dict):
                raise AnimaiError(f"{where}, bone '{name}': expected an object")
            warnings += _unknown(pose, POSE_KEYS, f"{where}, bone '{name}'")
            if not _is_num(pose.get("rot", 0)):
                raise AnimaiError(f"{where}, bone '{name}': rot must be a number (degrees)")
            _check_pos(f"{where}, bone '{name}'", pose.get("pos", [0, 0]))
        z = frame.get("z", {})
        if not isinstance(z, dict) or not all(_is_int(v) for v in z.values()):
            raise AnimaiError(f"{where}: z must map bone names to integers")
        ik = frame.get("ik", {})
        if not isinstance(ik, dict):
            raise AnimaiError(f"{where}: ik must be an object")
        for name, target in ik.items():
            if not isinstance(target, dict):
                raise AnimaiError(f"{where}, ik '{name}': expected an object")
            warnings += _unknown(target, IK_TARGET_KEYS, f"{where}, ik '{name}'")
            _check_pos(f"{where}, ik '{name}'", target.get("pos", [0, 0]))
            if not _is_num(target.get("rot", 0)):
                raise AnimaiError(f"{where}, ik '{name}': rot must be a number (degrees)")
        swap = frame.get("swap", [])
        if not (isinstance(swap, list) and all(isinstance(s, str) for s in swap)):
            raise AnimaiError(f"{where}: swap must be a list of swap names defined in rig.json")
        paint = frame.get("paint", [])
        if not isinstance(paint, list):
            raise AnimaiError(f"{where}: paint must be a list of [x, y, \"#RRGGBB\"] or [x, y, null]")
        for entry in paint:
            if not (isinstance(entry, list) and len(entry) == 3 and _is_int(entry[0]) and _is_int(entry[1])
                    and (entry[2] is None or isinstance(entry[2], str))):
                raise AnimaiError(f"{where}: paint entries must be [x, y, \"#RRGGBB\"] or [x, y, null] "
                                  f"with integer pixels, got {entry}")
            if entry[2] is not None:
                parse_hex_color(entry[2])
    if off_grid:
        warnings.append(f"duration_ms of frames {off_grid} is not a whole number of ticks "
                        f"(1000/fps = {tick:g} ms)")
    return warnings


def load_anim(path: str | Path) -> tuple[dict, list[str]]:
    """Read and validate an anim.json. ``name`` defaults to the file stem."""
    anim = read_json(path)
    anim.setdefault("name", Path(path).stem)
    return anim, validate_anim(anim)


def list_presets() -> list[str]:
    if not PRESETS_DIR.is_dir():
        return []
    return sorted(p.stem for p in PRESETS_DIR.glob("*.json"))


def load_preset(name: str) -> tuple[dict, list[str]]:
    """Load ``animai/presets/<name>.json``."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name or ""):
        raise AnimaiError(f"invalid preset name '{name}'")
    path = PRESETS_DIR / f"{name}.json"
    if not path.is_file():
        available = ", ".join(list_presets()) or "none"
        raise AnimaiError(f"unknown preset '{name}' (available: {available})")
    return load_anim(path)


def retarget(anim: dict, rig: dict) -> tuple[dict, list[str]]:
    """Copy of the animation restricted to what the rig has.

    Bones, z keys (bone names) and IK names missing from the rig are dropped,
    with one warning per name.
    """
    bones = rig["bones"]
    bones_with_parts = {p["bone"] for p in rig["parts"].values()}
    ik_specs = rig.get("ik", {})
    out = copy.deepcopy(anim)
    missing_bones: list[str] = []
    missing_z: list[str] = []
    missing_ik: list[str] = []
    missing_swaps: list[str] = []
    swaps = rig.get("swaps", {})
    for frame in out["frames"]:
        if "swap" in frame:
            for name in frame["swap"]:
                if name not in swaps and name not in missing_swaps:
                    missing_swaps.append(name)
            frame["swap"] = [n for n in frame["swap"] if n in swaps]
            if not frame["swap"]:
                del frame["swap"]
        for key, known, missing in (("bones", bones, missing_bones),
                                    ("z", bones_with_parts, missing_z),
                                    ("ik", ik_specs, missing_ik)):
            if key not in frame:
                continue
            for name in list(frame[key]):
                if name not in known:
                    del frame[key][name]
                    if name not in missing:
                        missing.append(name)
    warnings = [f"bone '{n}' is not in the rig: ignored" for n in missing_bones]
    warnings += [f"z override '{n}': no part attached to a bone of that name: ignored" for n in missing_z]
    warnings += [f"ik '{n}' is not defined in the rig: ignored" for n in missing_ik]
    warnings += [f"swap '{n}' is not defined in the rig: ignored" for n in missing_swaps]
    return out, warnings
