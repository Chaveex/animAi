"""Integration: the `holes` check, third cause (dislocated joint), against the tool,
and the two known limits of the QA, written down as tests of the CURRENT behaviour.

The dislocation is recomputed from frames.json alone by tests/invariants.py
(``joint_gaps``); the tool's verdict is then compared with it.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from tests import cli_adapter as cli, contract, invariants as inv
from tests.conftest import make_project, preset_document, write_anim

pytestmark = pytest.mark.integration


def walk_with_forearm_offset(project, tmp_path, offset, name):
    """Reference repro: hero64, walk, frames[1].bones.forearm_r = {"pos": [offset, 0]}."""
    walk = preset_document("walk")
    walk["frames"][1]["bones"]["forearm_r"] = {"pos": [offset, 0]}
    anim = project / f"walk_{name}.json"
    anim.write_text(json.dumps(walk), encoding="utf-8")
    result = cli.animate(project / "rig.json", tmp_path / f"frames_{name}", tmp_path, keyframes=anim).expect_ok()
    return result, cli.validate(result.frames_dir(), tmp_path)


def test_reference_dislocation_fails_for_the_tool_and_for_the_tester(project, tmp_path):
    result, verdict = walk_with_forearm_offset(project, tmp_path, 9, "nine")
    manifest = result.manifest()
    assert manifest["joints"]["forearm_r"] == 0, "test premise: untracked joint, threshold 0 + 2"
    gaps = inv.joint_gaps(manifest, 1)
    assert 8 <= gaps["forearm_r"] <= 10
    mine = [v for v in inv.check_holes(result.frames(), manifest)]
    assert [(v.frame, v.detail.split(" (")[0]) for v in mine] == [(1, "dislocated joint 'forearm_r'")]
    verdict.expect_user_error()
    report = cli.report(verdict)
    failing = [c for c in report["checks"] if c["id"] == "holes" and not c["pass"]]
    assert [c["frame"] for c in failing] == [1]
    assert "dislocated joint 'forearm_r'" in failing[0]["detail"]
    assert tuple(failing[0]["pixel"]) == mine[0].pixel, "pixel = the bone's joint, canvas coordinates"
    assert verdict.payload["outputs"]["failed"] == ["holes"]


def test_untouched_walk_has_no_dislocation(project, tmp_path):
    result, verdict = walk_with_forearm_offset(project, tmp_path, 0, "zero")
    manifest = result.manifest()
    verdict.expect_ok()
    for index in range(len(manifest["frames"])):
        assert inv.dislocated_joints(manifest, index) == {}
        worst = max(inv.joint_gaps(manifest, index).values())
        assert worst <= 2, f"frame {index}: a clean pose stays within the rounding margin, got {worst}"


@pytest.mark.parametrize("offset, dislocated", [(1, False), (2, False), (3, True), (4, True), (-3, True)])
def test_dislocation_threshold_is_the_documented_one(offset, dislocated, project, tmp_path):
    """gap > joints[B] + 2, with joints[forearm_r] = 0 on hero64: 2 px passes, 3 px fails.
    The tool and the independent computation must draw the line at the same place."""
    result, verdict = walk_with_forearm_offset(project, tmp_path, offset, f"o{offset}".replace("-", "m"))
    manifest = result.manifest()
    mine = inv.hole_frames(result.frames(), manifest)
    theirs = contract.failing_frames(cli.report(verdict), "holes")
    assert mine == theirs, (f"offset {offset}: tester sees a gap of "
                            f"{inv.joint_gaps(manifest, 1)['forearm_r']:.2f} px on frame 1")
    assert (mine == [1]) is dislocated


def test_dislocation_in_front_of_the_body_makes_no_transparent_pixel(project, tmp_path):
    """Why the third cause exists: here causes 1 and 2 see nothing."""
    result, verdict = walk_with_forearm_offset(project, tmp_path, -5, "front")
    manifest = result.manifest()
    frame = result.frames()[1]
    assert inv.open_joint_pixels(frame, manifest, 1) == {}
    assert inv.missing_data_pixels(frame, manifest, 1) == {}
    assert list(inv.dislocated_joints(manifest, 1)) == ["forearm_r"]
    verdict.expect_user_error()


def test_tampered_manifest_joint_is_caught_from_frames_json_alone(project, tmp_path):
    """Images untouched, one joint moved in frames.json: cause 3 needs nothing else."""
    result = cli.animate(project / "rig.json", tmp_path / "frames", tmp_path, preset="walk").expect_ok()
    path = result.path(cli.KEY_MANIFEST)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["frames"][4]["bones"]["shin_l"]["joint"][0] += 12
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert "shin_l" in inv.dislocated_joints(manifest, 4)
    verdict = cli.validate(result.frames_dir(), tmp_path).expect_user_error()
    details = [c["detail"] for c in cli.report(verdict)["checks"] if c["id"] == "holes" and c["frame"] == 4]
    assert details and "dislocated joint 'shin_l'" in details[0]


# --------------------------------------------------------------------------- #
# Known limits of the QA: tests of the current, documented behaviour
# --------------------------------------------------------------------------- #

def test_limit_a_dislocation_at_or_under_the_threshold_is_not_seen(project, hero, tmp_path):
    """LIMIT (docs/schemas.md, 'Limites'): cause 3 does not see a limb moved by joints[B] + 2 px
    or less. The forearm really is 2 px away from the elbow, and the QA is green."""
    clean, _ = walk_with_forearm_offset(project, tmp_path, 0, "clean")
    moved, verdict = walk_with_forearm_offset(project, tmp_path, 2, "two")
    manifest = moved.manifest()
    limit = manifest["joints"]["forearm_r"] + inv.DISLOCATION_MARGIN
    assert limit == 2
    assert not np.array_equal(inv.canonical(clean.frames()[1]), inv.canonical(moved.frames()[1])), \
        "the 2 px shift is visible in the picture"
    assert (manifest["frames"][1]["bones"]["forearm_r"]["joint"][0]
            - clean.manifest()["frames"][1]["bones"]["forearm_r"]["joint"][0]) == 2
    verdict.expect_ok()                                              # current behaviour: not reported
    assert cli.report(verdict)["ok"] is True
    assert inv.check_holes(moved.frames(), manifest) == [], "the independent check has the same limit"


def synthetic_case(tmp_path, far_bone: str):
    """A 64x64 sprite where a front part ('badge', on bone head) hangs between a far limb on
    its left and the near thigh on its right, with nothing drawn behind it.

        far limb | badge | thigh_r        row 36..45

    Frame 0 is the rest pose; in frame 1 the badge turns by 180 degrees around its joint
    (28, 36) and goes up in front of the body: rows 37..45 of its rest place are uncovered.
    Returns (animate result, manifest, the uncovered 8x9 area of frame 1, colours).
    """
    colours = {"torso": (60, 90, 200), "hips": (200, 60, 60), "thigh_r": (60, 160, 60),
               "far": (120, 60, 160), "badge": (240, 220, 80)}
    boxes = {"far": (18, 12, 6, 34), "torso": (24, 10, 16, 20), "hips": (24, 30, 16, 6),
             "thigh_r": (32, 36, 8, 20), "badge": (24, 36, 8, 10)}
    sprite = np.zeros((64, 64, 4), np.uint8)
    for name, (x, y, w, h) in boxes.items():
        sprite[y:y + h, x:x + w] = (*colours[name], 255)
    far_parent = {"arm_l": "spine", "thigh_l": "hips"}[far_bone]
    rig = {
        "version": 1, "sprite": "sprite.png", "view": "side", "template": "humanoid",
        "bones": {"hips": {"parent": None, "joint": [32, 33]}, "spine": {"parent": "hips", "joint": [32, 29]},
                  "head": {"parent": "spine", "joint": [28, 36]},
                  far_bone: {"parent": far_parent, "joint": [21, 14 if far_bone == "arm_l" else 34]},
                  "thigh_r": {"parent": "hips", "joint": [36, 37]}},
        "parts": {"far": {"bone": far_bone, "z": -2, "overlap": 0, "region": {"rects": [list(boxes["far"])]}},
                  "hips": {"bone": "hips", "z": 0, "overlap": 0, "region": {"rects": [list(boxes["hips"])]}},
                  "torso": {"bone": "spine", "z": 1, "overlap": 0, "region": {"rects": [list(boxes["torso"])]}},
                  "thigh_r": {"bone": "thigh_r", "z": 2, "overlap": 0,
                              "region": {"rects": [list(boxes["thigh_r"])]}},
                  "badge": {"bone": "head", "z": 5, "overlap": 0, "region": {"rects": [list(boxes["badge"])]}}},
    }
    assert contract.validate_rig(rig) == []
    project = tmp_path / f"synthetic_{far_bone}"
    project.mkdir()
    Image.fromarray(sprite, "RGBA").save(project / "sprite.png")
    (project / "rig.json").write_text(json.dumps(rig), encoding="utf-8")
    anim = write_anim(project / "anim.json", [{"duration_ms": 100, "bones": {}},
                                              {"duration_ms": 100, "bones": {"head": {"rot": 180}}}])
    result = cli.animate(project / "rig.json", project / "frames", tmp_path, keyframes=anim).expect_ok()
    manifest = result.manifest()
    ox, oy = manifest["origin"]
    uncovered = result.frames()[1][37 - oy:46 - oy, 24 - ox:32 - ox]      # where the badge was
    return result, manifest, uncovered, colours


def test_limit_an_uncovered_area_no_pair_of_parts_frames_is_not_seen(tmp_path):
    """LIMIT: the far limb is a child of spine, the thigh a child of hips: they do not depend
    on the same bone, so nothing is filled under the badge (rule 3) and nothing is listed as
    missing. When the badge leaves, 72 transparent pixels open inside the character and the
    QA stays green: it is 'legitimate negative space' for the tool."""
    result, manifest, uncovered, _ = synthetic_case(tmp_path, "arm_l")
    assert uncovered.shape[:2] == (9, 8)
    assert (uncovered[..., 3] == 0).all(), "current behaviour: nothing was drawn under the badge"
    assert all(part["missing"] == [] for part in manifest["parts"].values())
    assert inv.check_holes(result.frames(), manifest) == []
    verdict = cli.validate(result.frames_dir(), tmp_path).expect_ok()   # current behaviour: green
    report = cli.report(verdict)
    assert report["ok"] is True
    assert not any("hole" in w for w in report["warnings"]), "not even a pinhole warning (72 px is too big)"
