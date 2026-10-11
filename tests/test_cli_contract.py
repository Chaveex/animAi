"""Integration: each CLI command, run alone in a subprocess, honours the contract.

These need the lead dev's implementation. With the placeholder CLI they fail
("not implemented", return code 2): that is expected, they are not skipped.
All CLI spelling assumptions live in tests/cli_adapter.py.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from tests import cli_adapter as cli, contract, invariants as inv

pytestmark = pytest.mark.integration


def files_under(directory):
    return sorted(p for p in directory.rglob("*") if p.is_file()) if directory.exists() else []


# --------------------------------------------------------------------------- #
# stdout / return code, for every command
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("command", cli.COMMANDS)
def test_every_command_prints_one_contract_object_even_on_failure(command, tmp_path):
    """Called on a path that does not exist: still a single JSON object, rc 1."""
    result = cli.run([command, tmp_path / "does_not_exist"], tmp_path, tmp_path / "out")
    result.expect_user_error()
    assert result.payload["outputs"] == {} or isinstance(result.payload["outputs"], dict)


# --------------------------------------------------------------------------- #
# prepare
# --------------------------------------------------------------------------- #

def test_prepare_outputs_clean_sprite_and_palette(case, tmp_path):
    result = cli.prepare(case.source, tmp_path / "out", tmp_path).expect_ok()
    clean = result.image(cli.KEY_SPRITE)
    assert (clean.shape[1], clean.shape[0]) == case.native_size, "real pixel grid, no cropping (H7)"
    inv.assert_no_violations(inv.check_alpha_binary([clean]) + inv.check_palette([clean], case.palette),
                             f"prepare {case.name}")
    assert inv.palette_of(clean) == case.palette, "palette must be exactly the source colours"
    palette_document = result.json(cli.KEY_PALETTE)
    assert palette_document, "palette.json must not be empty"


def test_prepare_result_is_pixel_identical_to_the_expected_clean_sprite(case, tmp_path):
    """Covers downscale of the x4 fixture and keying of the flat background."""
    result = cli.prepare(case.source, tmp_path / "out", tmp_path).expect_ok()
    actual, expected = inv.canonical(result.image(cli.KEY_SPRITE)), inv.canonical(case.sprite)
    assert actual.shape == expected.shape
    differing = int((actual != expected).any(axis=2).sum())
    assert differing == 0, f"{differing} pixel(s) differ from fixtures/{case.name}/sprite.png"


def test_prepare_is_idempotent_on_an_already_clean_sprite(hero, tmp_path):
    result = cli.prepare(hero.sprite, tmp_path / "out", tmp_path).expect_ok()
    assert np.array_equal(inv.canonical(result.image(cli.KEY_SPRITE)), inv.canonical(hero.sprite))


def test_prepare_binarises_semi_transparent_input(hero, tmp_path):
    soft = hero.sprite_rgba().copy()
    soft[..., 3][soft[..., 3] == 255] = 200          # a "soft" export of the same sprite
    Image.fromarray(soft, "RGBA").save(tmp_path / "soft.png")
    result = cli.prepare(tmp_path / "soft.png", tmp_path / "out", tmp_path).expect_ok()
    clean = result.image(cli.KEY_SPRITE)
    inv.assert_no_violations(inv.check_alpha_binary([clean]), "prepare soft alpha")
    assert inv.palette_of(clean) <= hero.palette, "binarising alpha must not invent colours"


def test_prepare_does_not_touch_its_input_and_writes_only_in_out(hero, tmp_path):
    source = tmp_path / "in" / "source.png"
    source.parent.mkdir()
    source.write_bytes(hero.source.read_bytes())
    result = cli.prepare(source, tmp_path / "out", tmp_path).expect_ok()
    assert source.read_bytes() == hero.source.read_bytes()
    assert files_under(tmp_path / "in") == [source]
    assert result.path(cli.KEY_SPRITE).is_relative_to(tmp_path / "out")


# --------------------------------------------------------------------------- #
# inspect
# --------------------------------------------------------------------------- #

def test_inspect_outputs_a_zoomed_control_image(case, tmp_path):
    result = cli.inspect(case.sprite, tmp_path / "out", tmp_path).expect_ok()
    image = result.image(cli.KEY_INSPECT_IMAGE)
    width, height = case.native_size
    assert image.shape[1] >= 8 * width and image.shape[0] >= 8 * height, "NN x8 at least"


# --------------------------------------------------------------------------- #
# rig
# --------------------------------------------------------------------------- #

def test_rig_outputs_control_images_and_no_warning_on_a_clean_rig(case, tmp_path):
    result = cli.rig(case.sprite, case.rig_path, tmp_path / "out", tmp_path).expect_ok()
    width, height = case.native_size
    for key in (cli.KEY_OVERLAY, cli.KEY_LABEL_MAP):
        image = result.image(key)
        assert image.shape[1] >= width and image.shape[0] >= height
    assert result.warnings == [], "fixture rigs assign every pixel exactly once: nothing to warn about"


def test_rig_reports_rest_pose_pivot_and_tracked_joints(case, tmp_path):
    result = cli.rig(case.sprite, case.rig_path, tmp_path / "out", tmp_path).expect_ok()
    outputs = result.payload["outputs"]
    assert outputs["unassigned_count"] == 0 and outputs["multi_assigned_count"] == 0
    assert outputs["rest_pose_exact"] is True
    opaque = case.sprite_rgba()[..., 3] == 255
    ys, xs = np.nonzero(opaque)
    # docs/schemas.md "Pivot et canvas": [0.5, 1.0] of the rest bbox, grid-corner coordinate
    width = int(xs.max() - xs.min() + 1)
    expected = [int(xs.min()) + int(np.floor(width * 0.5 + 0.5)), int(ys.max()) + 1]
    assert outputs["pivot"] == expected
    report = result.json(cli.KEY_RIG_REPORT)
    assert report["pivot"] == expected and report["sprite_size"] == list(case.native_size)
    # Independent bound on the tracked disks: limb matter is made of opaque sprite pixels
    # only, so at rest the whole disk of radius joints[bone] must be opaque.
    for bone, radius in report["joints"].items():
        jx, jy = case.rig["bones"][bone]["joint"]
        for dx, dy in inv.disk_offsets(radius):
            assert opaque[jy + dy, jx + dx], f"joints['{bone}'] = {radius} reaches outside the sprite"


def test_rig_signals_unassigned_pixels(project, hero, tmp_path):
    """docs/schemas.md: warning at rig time, and the QA check parts_assigned fails."""
    rig = json.loads((project / "rig.json").read_text(encoding="utf-8"))
    del rig["parts"]["head"]
    (project / "rig.json").write_text(json.dumps(rig), encoding="utf-8")
    result = cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "out", tmp_path).expect_ok()
    expected = len(inv.check_rig_covers_sprite(hero.sprite, rig)) and int(
        ((inv.rasterize_rig(rig, hero.native_size).labels == 0) & (hero.sprite_rgba()[..., 3] > 0)).sum())
    assert result.payload["outputs"]["unassigned_count"] == expected > 0
    assert result.warnings, "unassigned source pixels must give a warning"
    frames = cli.animate(project / "rig.json", tmp_path / "frames", tmp_path, preset="idle").expect_ok()
    verdict = cli.validate(frames.frames_dir(), tmp_path).expect_user_error()
    report = verdict.json(cli.KEY_REPORT)
    assert contract.validate_report(report) == []
    assert [c["pass"] for c in report["checks"] if c["id"] == "parts_assigned"] == [False]


def test_rig_warns_when_two_parts_claim_the_same_pixel(project, tmp_path):
    """docs/schemas.md: 'la derniere definie gagne, avertissement' -> still ok."""
    rig = json.loads((project / "rig.json").read_text(encoding="utf-8"))
    rig["parts"]["head"]["region"]["rects"].append(rig["parts"]["torso"]["region"]["rects"][0])
    (project / "rig.json").write_text(json.dumps(rig), encoding="utf-8")
    result = cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "out", tmp_path).expect_ok()
    assert result.warnings, "overlapping regions must produce a warning"


# --------------------------------------------------------------------------- #
# animate
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("preset", cli.MVP_PRESETS)
def test_animate_preset_outputs_frames_anim_and_contact_sheet(preset, project, hero, tmp_path):
    result = cli.animate(project / "rig.json", tmp_path / "out", tmp_path,
                         preset=preset, frames=8, fps=10).expect_ok()
    frames = result.frames()
    assert len(frames) == 8
    anim = result.anim()
    assert anim["name"] == preset and len(anim["frames"]) == 8
    assert anim["loop"] is (preset in cli.LOOPING_PRESETS)
    result.image(cli.KEY_CONTACT_SHEET)
    manifest = result.manifest()
    assert manifest["source"]["palette"] == sorted("#%02x%02x%02x" % c for c in hero.palette)
    inv.assert_no_violations(cli.animation_violations(frames, hero.palette, manifest), f"animate {preset}")


@pytest.mark.parametrize("preset", cli.MVP_PRESETS)
def test_animate_preset_actually_moves(preset, project, tmp_path):
    result = cli.animate(project / "rig.json", tmp_path / "out", tmp_path,
                         preset=preset, frames=8, fps=10).expect_ok()
    frames = [inv.canonical(f) for f in result.frames()]
    distinct = {f.tobytes() for f in frames}
    assert len(distinct) >= 2, "an animation with identical frames is not an animation"


def test_animate_preset_ignores_missing_optional_bones_with_a_warning(project, tmp_path):
    """Rig without arms: presets still work, the skipped bones are reported."""
    rig = json.loads((project / "rig.json").read_text(encoding="utf-8"))
    arms = [b for b in rig["bones"] if b.startswith(("arm_", "forearm_", "hand_"))]
    for bone in arms:
        del rig["bones"][bone]
    for part in [p for p, spec in rig["parts"].items() if spec["bone"] in arms]:
        rig["parts"][part]["bone"] = "spine"         # arm pixels now move with the torso
    rig["ik"] = {k: v for k, v in rig["ik"].items() if v["target_bone"] in rig["bones"]}
    assert contract.validate_rig(rig) == []
    full = cli.animate(project / "rig.json", tmp_path / "full", tmp_path,
                       preset="walk", frames=8, fps=10).expect_ok()
    (project / "rig.json").write_text(json.dumps(rig), encoding="utf-8")
    result = cli.animate(project / "rig.json", tmp_path / "out", tmp_path,
                         preset="walk", frames=8, fps=10).expect_ok()
    extra = [w for w in result.warnings if w not in full.warnings]
    assert extra, "docs/schemas.md: a preset bone absent from the rig = warning"
    assert len(result.frames()) == 8


# --------------------------------------------------------------------------- #
# animate --keyframes (rigid-motion ground truths)
# --------------------------------------------------------------------------- #

def write_anim(path, frames, name="custom", loop=False, fps=10):
    document = {"version": 1, "name": name, "loop": loop, "fps": fps, "frames": frames}
    assert contract.validate_anim(document) == []
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_keyframes_rest_pose_reproduces_the_sprite_pixel_for_pixel(case, tmp_path):
    """No rotation, no offset: the frame content IS the source sprite."""
    anim = write_anim(tmp_path / "anim.json", [{"duration_ms": 100, "bones": {}}])
    result = cli.animate(case.rig_path, tmp_path / "out", tmp_path, keyframes=anim).expect_ok()
    frames = result.frames()
    assert len(frames) == 1
    assert np.array_equal(inv.crop_to_content(frames[0]), inv.crop_to_content(case.sprite)), \
        "rest pose lost, added or moved source pixels"


def test_keyframes_root_translation_moves_everything_rigidly(case, tmp_path):
    anim = write_anim(tmp_path / "anim.json", [
        {"duration_ms": 100, "bones": {}},
        {"duration_ms": 100, "bones": {"hips": {"pos": [3, -2]}}},
    ])
    result = cli.animate(case.rig_path, tmp_path / "out", tmp_path, keyframes=anim).expect_ok()
    rest, moved = result.frames()
    assert rest.shape == moved.shape, "canvas must be constant across frames"
    assert np.array_equal(inv.crop_to_content(moved), inv.crop_to_content(case.sprite))
    ys0, xs0 = np.nonzero(rest[..., 3])
    ys1, xs1 = np.nonzero(moved[..., 3])
    assert (int(xs1.min() - xs0.min()), int(ys1.min() - ys0.min())) == (3, -2), \
        "pos is an integer pixel offset, +x right, +y down (image coordinates)"


def test_keyframes_root_rotation_of_90_degrees_is_lossless(case, tmp_path):
    """90 degrees is one of the allowed discrete angles and maps the grid onto itself."""
    anim = write_anim(tmp_path / "anim.json",
                      [{"duration_ms": 100, "bones": {"hips": {"rot": 90}}}])
    result = cli.animate(case.rig_path, tmp_path / "out", tmp_path, keyframes=anim).expect_ok()
    rotated = inv.crop_to_content(result.frames()[0])
    source = inv.crop_to_content(case.sprite)
    expected = np.rot90(source, k=1)        # anti-clockwise on screen: the feet end up in front
    assert expected.shape == rotated.shape and np.array_equal(expected, rotated), \
        "rot +90 on the root must be an exact anti-clockwise quarter turn (docs/schemas.md)"
    assert result.manifest()["frames"][0]["bones"]["hips"]["angle"] == 90


def test_keyframes_limb_rotation_keeps_all_invariants(case, tmp_path):
    frames_spec = [
        {"duration_ms": 120, "bones": {}},
        {"duration_ms": 80, "bones": {"thigh_r": {"rot": 30}, "thigh_l": {"rot": -30},
                                      "arm_r": {"rot": -15}, "arm_l": {"rot": 15},
                                      "hips": {"pos": [0, -1]}},
         "z": {"arm_l": 9}},
        {"duration_ms": 200, "bones": {"head": {"rot": 15}, "forearm_r": {"rot": 45}}},
    ]
    anim = write_anim(tmp_path / "anim.json", frames_spec)
    result = cli.animate(case.rig_path, tmp_path / "out", tmp_path, keyframes=anim).expect_ok()
    frames = result.frames()
    assert len(frames) == 3
    assert [f["duration_ms"] for f in result.anim()["frames"]] == [120, 80, 200], \
        "per-frame durations of a custom anim.json are kept as written"
    inv.assert_no_violations(cli.animation_violations(frames, case.palette, result.manifest()),
                             f"keyframes {case.name}")
    assert not np.array_equal(inv.canonical(frames[0]), inv.canonical(frames[1]))


def test_keyframes_z_override_changes_draw_order(project, hero, tmp_path):
    """Same pose, far arm pulled in front of everything: its colour must appear more."""
    pose = {"arm_l": {"rot": 90}, "forearm_l": {"rot": 0}}
    anim = write_anim(tmp_path / "anim.json", [
        {"duration_ms": 100, "bones": pose},
        {"duration_ms": 100, "bones": pose, "z": {"arm_l": 50, "forearm_l": 51}},
    ])
    result = cli.animate(project / "rig.json", tmp_path / "out", tmp_path, keyframes=anim).expect_ok()
    behind, in_front = (inv.canonical(f) for f in result.frames())
    assert not np.array_equal(behind, in_front), "a per-frame z override must change the picture"
    inv.assert_no_violations(
        cli.animation_violations([behind, in_front], hero.palette, result.manifest()), "z override")


def test_keyframes_fill_none_uncovered_flank_is_a_hole_for_the_tool_and_for_the_tester(
        project, tmp_path):
    """Cause 2 of docs/schemas.md: the torso has no data under the near arm; raising the arm
    uncovers it. The tool's QA and the independent check must name the same frames."""
    rig = json.loads((project / "rig.json").read_text(encoding="utf-8"))
    rig["parts"]["torso"]["fill"] = "none"
    (project / "rig.json").write_text(json.dumps(rig), encoding="utf-8")
    anim = write_anim(tmp_path / "anim.json", [
        {"duration_ms": 100, "bones": {}},
        {"duration_ms": 100, "bones": {"arm_r": {"rot": 90}}},
        {"duration_ms": 100, "bones": {"arm_r": {"rot": 180}}},
    ])
    result = cli.animate(project / "rig.json", tmp_path / "out", tmp_path, keyframes=anim).expect_ok()
    manifest = result.manifest()
    assert manifest["parts"]["torso"]["missing"], "fill 'none' must list the pixels left without data"
    mine = inv.hole_frames(result.frames(), manifest)
    assert 0 not in mine, "at rest the arm still covers the missing pixels"
    assert mine, "the raised arm uncovers pixels that have no data: this is a hole"
    verdict = cli.validate(result.frames_dir(), tmp_path).expect_user_error()
    assert contract.failing_frames(verdict.json(cli.KEY_REPORT), "holes") == mine


def test_keyframes_same_pose_with_default_fill_has_no_hole(project, hero, tmp_path):
    anim = write_anim(tmp_path / "anim.json", [
        {"duration_ms": 100, "bones": {"arm_r": {"rot": 90}}},
        {"duration_ms": 100, "bones": {"arm_r": {"rot": 180}}},
    ])
    result = cli.animate(project / "rig.json", tmp_path / "out", tmp_path, keyframes=anim).expect_ok()
    manifest = result.manifest()
    assert all(part["missing"] == [] for part in manifest["parts"].values())
    inv.assert_no_violations(cli.animation_violations(result.frames(), hero.palette, manifest),
                             "raised arm, fill own")
    cli.validate(result.frames_dir(), tmp_path).expect_ok()


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #

@pytest.fixture
def walk_frames(project, tmp_path):
    result = cli.animate(project / "rig.json", tmp_path / "frames", tmp_path,
                         preset="walk", frames=8, fps=10).expect_ok()
    return result


def test_validate_writes_a_conforming_report_that_passes(walk_frames, tmp_path):
    result = cli.validate(walk_frames.frames_dir(), tmp_path).expect_ok()
    report = result.json(cli.KEY_REPORT)
    assert contract.validate_report(report) == []
    failed = [c for c in report["checks"] if not c["pass"]]
    assert report["ok"] is True and not failed, failed


@pytest.mark.parametrize("check_id, tamper", [
    ("palette", lambda frame: frame.__setitem__((slice(0, 3), slice(0, 3)), (1, 2, 3, 255))),
    ("alpha_binary", lambda frame: frame[..., 3].__setitem__(frame[..., 3] == 255, 128)),
    ("orphans", lambda frame: frame.__setitem__((0, 0), frame[frame[..., 3] == 255][0])),
])
def test_validate_catches_a_tampered_frame(check_id, tamper, walk_frames, tmp_path):
    """Corrupt frame 2 on disk; the matching check must fail and point at it."""
    target = walk_frames.frame_paths()[2]
    frame = inv.as_rgba(target).copy()
    tamper(frame)
    Image.fromarray(frame, "RGBA").save(target)
    result = cli.validate(walk_frames.frames_dir(), tmp_path).expect_user_error()
    assert result.payload["error"].startswith("QA failed:")
    report = result.json(cli.KEY_REPORT)
    assert contract.validate_report(report) == []
    assert report["ok"] is False
    failing = [c for c in report["checks"] if c["id"] == check_id and not c["pass"]]
    assert failing, f"check '{check_id}' should fail; report: {report['checks']}"
    assert any(c["frame"] == 2 for c in failing), "the report must name the faulty frame"


def test_validate_catches_a_frame_with_another_canvas_size(walk_frames, tmp_path):
    target = walk_frames.frame_paths()[1]
    frame = inv.as_rgba(target)
    Image.fromarray(np.pad(frame, ((0, 2), (0, 0), (0, 0))), "RGBA").save(target)
    result = cli.validate(walk_frames.frames_dir(), tmp_path).expect_user_error()
    assert result.payload["error"].startswith("QA failed:")
    report = result.json(cli.KEY_REPORT)
    assert report["ok"] is False
    assert any(c["id"] == "canvas_constant" and not c["pass"] for c in report["checks"])


# --------------------------------------------------------------------------- #
# export
# --------------------------------------------------------------------------- #

def test_export_spritesheet_outputs_png_json_and_gif(walk_frames, hero, tmp_path):
    result = cli.export(walk_frames.frames_dir(), tmp_path / "export", tmp_path).expect_ok()
    sheet = result.image(cli.KEY_SHEET)
    layout = cli.parse_sheet_json(result.json(cli.KEY_SHEET_JSON))
    frames = cli.cut_sheet(sheet, layout)
    assert len(frames) == 8
    assert layout.durations_ms == [100] * 8, "8 frames at 10 fps = 100 ms each, written in the JSON"
    manifest = walk_frames.manifest()
    assert layout.frame_size == tuple(manifest["canvas"]) and layout.loop is True
    assert layout.pivots[0] == tuple(manifest["pivot"]), "exported pivot = frames.json pivot"
    inv.assert_no_violations(
        cli.animation_violations(frames, hero.palette, manifest)
        + cli.ground_violations(frames, manifest, "walk")
        + inv.check_pivot_stable(layout.pivots, layout.frame_size), "export walk")
    gif_images, gif_durations = cli.gif_frames(result.path(cli.KEY_GIF))
    assert sum(gif_durations) == 800, "GIF total duration must be the animation duration"
    inv.assert_no_violations(inv.check_palette(gif_images, hero.palette), "export gif")


def test_export_frames_are_the_animated_frames_on_a_constant_canvas(walk_frames, tmp_path):
    """Export may pad, never alter: same content per frame, same offset on all frames."""
    result = cli.export(walk_frames.frames_dir(), tmp_path / "export", tmp_path).expect_ok()
    layout = cli.parse_sheet_json(result.json(cli.KEY_SHEET_JSON))
    exported = cli.cut_sheet(result.image(cli.KEY_SHEET), layout)
    animated = walk_frames.frames()
    assert len(exported) == len(animated)
    offsets = set()
    for index, (out, src) in enumerate(zip(exported, animated)):
        assert np.array_equal(inv.crop_to_content(out), inv.crop_to_content(src)), \
            f"frame {index} content changed during export"
        (ys_o, xs_o), (ys_s, xs_s) = np.nonzero(out[..., 3]), np.nonzero(src[..., 3])
        offsets.add((int(xs_o.min() - xs_s.min()), int(ys_o.min() - ys_s.min())))
    assert len(offsets) == 1, f"frames were re-aligned individually (offsets {sorted(offsets)}): jitter"
