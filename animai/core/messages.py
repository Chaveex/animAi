"""Stable identifiers for the messages of the core.

The core writes its warnings as English sentences. ``classify`` gives each one
a stable ``code`` and its parameters, so an interface can translate it without
parsing prose. A message that matches no family gets the code ``"other"``; the
sentence itself is always kept in ``message``.
"""
from __future__ import annotations

import re

# (code, pattern with named groups). Order matters: first match wins.
_FAMILIES: list[tuple[str, str]] = [
    ("unknown_key", r"unknown key '(?P<key>.+)' in (?P<where>.+): ignored"),
    ("bone_not_in_rig", r"bone '(?P<bone>.+)' is not in the rig: ignored"),
    ("z_override_unknown", r"z override '(?P<bone>.+)': no part attached to a bone of that name: ignored"),
    ("ik_not_in_rig", r"ik '(?P<ik>.+)' is not defined in the rig: ignored"),
    ("ik_out_of_reach", r"(?:frame (?P<frame>\d+): )?ik '(?P<ik>.+)': target (?P<target>\[.*\]) out of reach, "
                        r"clamped to (?P<reached>\[.*\])"),
    ("bone_reparented", r"bone '(?P<bone>.+)': parent '(?P<parent>.+)' is not in the rig, attached to '(?P<to>.+)'"),
    ("joint_outside_sprite", r"bone '(?P<bone>.+)': joint (?P<joint>\[.*\]) is outside the sprite .*"),
    ("part_empty", r"part '(?P<part>.+)' covers no opaque pixel"),
    ("part_overridden", r"part '(?P<part>.+)' is entirely overridden by later parts"),
    ("pixels_multi_assigned", r"(?P<count>\d+) pixels claimed by several parts .*"),
    ("pixels_unassigned", r"(?P<count>\d+) opaque pixels are not assigned to any part \(first at (?P<first>\[.*\])\)"),
    ("view_out_of_scope", r"view '(?P<view>.+)' is outside the v1 scope .*"),
    ("duration_off_grid", r"duration_ms of frames (?P<frames>\[.*\]) is not a whole number of ticks .*"),
    ("resample_key_poses_dropped", r"only (?P<frames>\d+) frames: key poses dropped: (?P<dropped>.+)"),
    ("resample_drops_frames", r"resampling to (?P<frames>\d+) frames drops source frames (?P<dropped>\[.*\])"),
    ("resample_changes_holds", r"resampling to (?P<frames>\d+) equal frames changes the holds of source frames "
                               r"(?P<changed>\[.*\]): (?P<expected>\[.*\]) ms would be proportional, "
                               r"got (?P<got>\[.*\]) ms"),
    ("too_many_frames", r"(?P<frames>\d+) frames: more than (?P<max>\d+) is hard to read in pixel art"),
    ("gif_durations_rounded", r"GIF durations rounded to 10 ms steps \(min 20 ms\): (?P<durations>\[.*\])"),
    ("gif_quantized", r"(?P<colors>\d+) colours: GIF preview quantized to 255 .*"),
    ("pinhole", r"frame (?P<frame>\d+): pinhole of (?P<count>\d+) px at (?P<pixel>\[.*\]) .*"),
    ("outline_bare", r"outline: up to (?P<bare>\d+) of (?P<border>\d+) border pixels without outline "
                     r"\(frame (?P<frame>\d+); the source sprite has (?P<source>\d+)\)"),
    ("ground_offset", r"ground: frames more than 1 px away from the ground line \(frame, offset\): (?P<frames>.+)"),
    ("joints_on_edge", r"joints placed on the edge of their limb \(move them inside\): (?P<bones>.+)"),
    ("not_validated", r"frames were not validated: .*"),
    ("qa_failing", r"QA report is failing: .*"),
    ("rest_pose_differs", r"rest pose does not reproduce the sprite exactly"),
    ("semi_transparent_binarized", r"(?P<count>\d+) semi-transparent pixels binarized \(threshold (?P<threshold>\d+)\)"),
    ("no_background_detected", r"no transparency and no uniform background detected: .*"),
    ("background_not_found", r"background colour not found on the image border: nothing removed"),
    ("background_remains", r"(?P<count>\d+) pixels of the background colour remain inside the sprite .*"),
    ("sprite_small", r"the character is (?P<width>\d+)x(?P<height>\d+) px: .*"),
    ("rig_invalid_on_disk", r"rig\.json invalide : (?P<core_message>.*)"),
    ("doc_invalid_on_disk", r"(?P<file>\S+) modifié sur le disque mais invalide, ignoré : (?P<core_message>.*)"),
]
_COMPILED = [(code, re.compile(pattern, re.S)) for code, pattern in _FAMILIES]
CODES = [code for code, _ in _FAMILIES] + ["other"]


def classify(message: str) -> dict:
    """``{"code", "params", "message"}`` for one message of the core."""
    for code, pattern in _COMPILED:
        m = pattern.fullmatch(message)
        if m:
            return {"code": code, "params": {k: v for k, v in m.groupdict().items() if v is not None},
                    "message": message}
    return {"code": "other", "params": {}, "message": message}


def classify_all(messages) -> list[dict]:
    return [classify(m) for m in messages]
