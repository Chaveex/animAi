"""Integration: unknown keys, mandatory `region`, `inspect --segments`, `rig --labels`,
and the `metrics` of report.json (docs/schemas.md, journal points 23, 25, 26, 31)."""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from tests import cli_adapter as cli, invariants as inv
from tests.conftest import load_case, make_project, write_anim

pytestmark = pytest.mark.integration


def unknown(warnings) -> list[str]:
    return sorted(w for w in warnings if w.startswith("unknown key"))


# --------------------------------------------------------------------------- #
# unknown keys
# --------------------------------------------------------------------------- #

def mutate_rig(rig):
    rig["colour"] = "x"
    rig["bones"]["head"]["jiont"] = [1, 2]
    rig["parts"]["head"]["zz"] = 1
    rig["parts"]["head"]["region"]["rect"] = []
    rig["parts"]["head"]["region"]["exclude"] = {"pixel": []}
    rig["ik"]["foot_r"]["bnd"] = 1


EXPECTED_RIG_WARNINGS = sorted([
    "unknown key 'colour' in rig: ignored",
    "unknown key 'jiont' in bone 'head': ignored",
    "unknown key 'zz' in part 'head': ignored",
    "unknown key 'rect' in part 'head'.region: ignored",
    "unknown key 'pixel' in part 'head'.region.exclude: ignored",
    "unknown key 'bnd' in ik 'foot_r': ignored",
])


def test_clean_documents_give_no_unknown_key_warning(case, tmp_path):
    result = cli.rig(case.sprite, case.rig_path, tmp_path / "rig", tmp_path).expect_ok()
    assert unknown(result.warnings) == []
    for preset in cli.MVP_PRESETS:
        animated = cli.animate(case.rig_path, tmp_path / preset, tmp_path, preset=preset).expect_ok()
        assert unknown(animated.warnings) == [], f"preset {preset} uses a key the contract does not define"


def test_unknown_rig_keys_are_reported_one_by_one_with_their_place(hero, tmp_path):
    project = make_project(tmp_path / "project", hero, mutate_rig)
    result = cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "rig", tmp_path).expect_ok()
    assert unknown(result.warnings) == EXPECTED_RIG_WARNINGS
    animated = cli.animate(project / "rig.json", tmp_path / "frames", tmp_path, preset="idle").expect_ok()
    assert unknown(animated.warnings) == EXPECTED_RIG_WARNINGS, "animate reads the same rig"


def test_unknown_rig_keys_are_ignored_not_applied(hero, tmp_path):
    clean = cli.animate(hero.rig_path, tmp_path / "clean", tmp_path, preset="walk").expect_ok()
    project = make_project(tmp_path / "project", hero, mutate_rig)
    noisy = cli.animate(project / "rig.json", tmp_path / "noisy", tmp_path, preset="walk").expect_ok()
    assert [p.read_bytes() for p in clean.frame_paths()] == [p.read_bytes() for p in noisy.frame_paths()]


def test_underscore_keys_are_comments(hero, tmp_path):
    def comment(rig):
        rig["_note"] = "written by Claude"
        rig["bones"]["head"]["_why"] = "neck"
        rig["parts"]["head"]["_todo"] = 1
        rig["parts"]["head"]["region"]["_src"] = "manual"
        rig["ik"]["foot_r"]["_x"] = None
    project = make_project(tmp_path / "project", hero, comment)
    result = cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "rig", tmp_path).expect_ok()
    assert result.warnings == []
    anim = write_anim(tmp_path / "anim.json", [{"duration_ms": 100, "_c": 1, "bones": {"arm_r": {"rot": 15, "_k": 1}}}],
                      _comment="x")
    animated = cli.animate(project / "rig.json", tmp_path / "frames", tmp_path, keyframes=anim).expect_ok()
    assert unknown(animated.warnings) == []


def test_unknown_anim_keys_are_reported_and_a_misspelt_rot_does_nothing(project, hero, tmp_path):
    """`"rotation": 30` instead of `rot`: warning, and the pose stays at rest."""
    anim = write_anim(tmp_path / "anim.json", [
        {"duration_ms": 100, "hold": 2, "bones": {"arm_r": {"rotation": 90}},
         "ik": {"foot_r": {"pos": [0, 0], "target": [1, 1]}}}], nam="typo")
    result = cli.animate(project / "rig.json", tmp_path / "frames", tmp_path, keyframes=anim).expect_ok()
    assert unknown(result.warnings) == sorted([
        "unknown key 'nam' in anim: ignored",
        "unknown key 'hold' in frame 0: ignored",
        "unknown key 'rotation' in frame 0, bone 'arm_r': ignored",
        "unknown key 'target' in frame 0, ik 'foot_r': ignored",
    ])
    assert np.array_equal(inv.crop_to_content(result.frames()[0]), inv.crop_to_content(hero.sprite))


# --------------------------------------------------------------------------- #
# region is mandatory
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("region", ["<del>", None, [], "all"])
def test_part_without_region_object_is_an_error(region, hero, tmp_path):
    def mutate(rig):
        if region == "<del>":
            del rig["parts"]["head"]["region"]
        else:
            rig["parts"]["head"]["region"] = region
    project = make_project(tmp_path / "project", hero, mutate)
    for result in (cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "rig", tmp_path),
                   cli.animate(project / "rig.json", tmp_path / "frames", tmp_path, preset="idle")):
        result.expect_user_error()
        assert "head" in result.payload["error"] and "region" in result.payload["error"]


def test_empty_region_object_is_a_part_without_pixel_yet(hero, tmp_path):
    project = make_project(tmp_path / "project", hero, lambda rig: rig["parts"]["head"].update(region={}))
    result = cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "rig", tmp_path).expect_ok()
    assert any("'head'" in w for w in result.warnings), "a part without pixel is ignored with a warning"
    assert result.payload["outputs"]["unassigned_count"] > 0
    assert "head" not in result.payload["outputs"]["parts"]


# --------------------------------------------------------------------------- #
# inspect --segments
# --------------------------------------------------------------------------- #

def rebuild(segments: dict, size) -> np.ndarray:
    image = np.zeros((size[1], size[0], 4), np.uint8)
    for y, runs in segments.items():
        for x0, x1, colour in runs:
            assert x0 <= x1, "x1 is included"
            assert not image[int(y), x0:x1 + 1, 3].any(), "segments of a row must not overlap"
            image[int(y), x0:x1 + 1] = (*inv.hex_to_rgb(colour), 255)
    return image


def test_segments_describe_the_sprite_exactly(case, tmp_path):
    result = cli.inspect(case.sprite, tmp_path / "out", tmp_path, segments=True).expect_ok()
    segments = result.payload["outputs"]["segments"]
    assert np.array_equal(rebuild(segments, case.native_size), inv.canonical(case.sprite))
    sprite = case.sprite_rgba()
    assert sorted(int(y) for y in segments) == np.nonzero((sprite[..., 3] > 0).any(axis=1))[0].tolist(), \
        "empty rows are omitted, every other row is present"
    for runs in segments.values():                     # maximal runs: neighbours differ in colour or are apart
        for (a0, a1, colour_a), (b0, b1, colour_b) in zip(runs, runs[1:]):
            assert b0 > a1 and (b0 > a1 + 1 or colour_a != colour_b)


def test_segments_are_limited_to_the_crop(hero, tmp_path):
    x, y, w, h = 24, 13, 14, 6
    result = cli.inspect(hero.sprite, tmp_path / "out", tmp_path, segments=True, crop=(x, y, w, h)).expect_ok()
    expected = np.zeros_like(inv.canonical(hero.sprite))
    expected[y:y + h, x:x + w] = inv.canonical(hero.sprite)[y:y + h, x:x + w]
    assert np.array_equal(rebuild(result.payload["outputs"]["segments"], hero.native_size), expected)


def test_segments_are_absent_without_the_option_and_detect_a_changed_pixel(hero, tmp_path):
    plain = cli.inspect(hero.sprite, tmp_path / "plain", tmp_path).expect_ok()
    assert "segments" not in plain.payload["outputs"]
    changed = hero.sprite_rgba().copy()
    changed[20, 30, :3] = changed[57, 30, :3]                    # one pixel takes another colour
    Image.fromarray(changed, "RGBA").save(tmp_path / "changed.png")
    result = cli.inspect(tmp_path / "changed.png", tmp_path / "out", tmp_path, segments=True).expect_ok()
    rebuilt = rebuild(result.payload["outputs"]["segments"], hero.native_size)
    assert np.array_equal(rebuilt, inv.canonical(changed))
    assert not np.array_equal(rebuilt, inv.canonical(hero.sprite))


# --------------------------------------------------------------------------- #
# rig --labels and the rig diagnostics
# --------------------------------------------------------------------------- #

def test_rig_labels_modes_change_the_overlay_only(hero, tmp_path):
    results = {mode: cli.rig(hero.sprite, hero.rig_path, tmp_path / mode, tmp_path, labels=mode).expect_ok()
               for mode in ("names", "numbers", "none")}
    overlays = {mode: r.image(cli.KEY_OVERLAY) for mode, r in results.items()}
    assert not np.array_equal(overlays["names"], overlays["none"])
    assert not np.array_equal(overlays["numbers"], overlays["none"])
    assert not np.array_equal(overlays["names"], overlays["numbers"])
    default = cli.rig(hero.sprite, hero.rig_path, tmp_path / "default", tmp_path).expect_ok()
    assert any(np.array_equal(default.image(cli.KEY_OVERLAY), o) for o in overlays.values())
    reports = [json.dumps(r.json(cli.KEY_RIG_REPORT), sort_keys=True) for r in results.values()]
    assert len(set(reports)) == 1, "--labels must not change rig_report.json"
    numbers = results["numbers"].payload["outputs"]["bone_numbers"]
    assert set(numbers) == set(hero.rig["bones"])
    assert sorted(numbers.values()) == list(range(len(numbers))), "one distinct number per bone"


def test_rig_labels_invalid_value_is_a_user_error(hero, tmp_path):
    cli.rig(hero.sprite, hero.rig_path, tmp_path / "out", tmp_path, labels="emoji").expect_user_error()


def test_rig_diagnostics_unmonitored_joints_and_thin_parts(case, tmp_path):
    result = cli.rig(case.sprite, case.rig_path, tmp_path / "rig", tmp_path).expect_ok()
    outputs, report = result.payload["outputs"], result.json(cli.KEY_RIG_REPORT)
    zero = sorted(bone for bone, radius in report["joints"].items() if radius == 0)
    assert sorted(outputs["unmonitored_joints"]) == zero == sorted(report["unmonitored_joints"])
    raster = inv.rasterize_rig(case.rig, case.native_size)
    thin = {}
    for index, name in enumerate(raster.parts, start=1):
        ys, xs = np.nonzero(raster.labels == index)
        side = int(min(xs.max() - xs.min() + 1, ys.max() - ys.min() + 1))
        if side < 4:
            thin[name] = side
    assert outputs["thin_parts"] == thin == report["thin_parts"], "parts under 4 px: {part: smallest side}"
    if case.meta["outline"]:
        assert outputs["outline"]["color"] == "#%02x%02x%02x" % tuple(case.meta["outline_color"])
    else:
        assert outputs["outline"] is None and report["outline"] is None


# --------------------------------------------------------------------------- #
# report.json metrics
# --------------------------------------------------------------------------- #

@pytest.fixture(params=["hero64", "rogue80_outline"])
def walked(request, tmp_path):
    case = load_case(request.param)
    result = cli.animate(case.rig_path, tmp_path / "frames", tmp_path, preset="walk").expect_ok()
    return case, result


def small_enclosed(frame) -> set:
    return {pixel for component in inv.connected_components(inv.enclosed_mask(frame), 4)
            if len(component) <= 2 for pixel in component}


def test_metrics_are_what_the_images_say(walked, tmp_path):
    case, result = walked
    manifest, frames = result.manifest(), result.frames()
    verdict = cli.validate(result.frames_dir(), tmp_path).expect_ok()
    report = cli.report(verdict)
    metrics = report["metrics"]
    assert verdict.payload["outputs"]["metrics"] == metrics
    assert len(metrics["frames"]) == len(frames)
    assert [f["ground_offset"] for f in metrics["frames"]] == inv.ground_offsets(frames, manifest["pivot"][1])
    assert [f["border"] for f in metrics["frames"]] == [int(inv.silhouette_border(f).sum()) for f in frames]
    assert sorted(metrics["unmonitored_joints"]) == sorted(b for b, r in manifest["joints"].items() if r == 0)
    if case.meta["outline"]:
        colour = tuple(case.meta["outline_color"])
        assert metrics["outline"]["applied"] is True
        assert [f["outline_bare"] for f in metrics["frames"]] == [inv.bare_border_count(f, colour) for f in frames]
    else:
        assert metrics["outline"] is None
    for index, frame in enumerate(frames):
        listed = {tuple(p) for p in metrics["frames"][index]["pinholes"]}
        assert listed == small_enclosed(frame), f"frame {index}: pinholes = closed voids of 1 or 2 px"
        if listed:
            assert any(w.startswith(f"frame {index}: pinhole") for w in report["warnings"])
    assert verdict.warnings == report["warnings"]


def test_metrics_follow_a_tampered_frame_without_deciding_the_verdict_alone(walked, tmp_path):
    """Frame 2 pushed 2 px down (as far as the default padding allows without clipping) and
    one pixel pierced: ground_offset and pinholes must say so."""
    case, result = walked
    manifest = result.manifest()
    target = result.frame_paths()[2]
    frame = inv.as_rgba(target).copy()
    frame[2:] = frame[:-2].copy()
    frame[:2] = 0
    ys, xs = np.nonzero(frame[..., 3])
    inner = [(x, y) for x, y in zip(xs.tolist(), ys.tolist())
             if frame[y - 1:y + 2, x - 1:x + 2, 3].all()]
    px, py = inner[len(inner) // 2]
    frame[py, px] = 0
    Image.fromarray(frame, "RGBA").save(target)
    verdict = cli.validate(result.frames_dir(), tmp_path)
    verdict.assert_contract()
    report = cli.report(verdict)
    measured = report["metrics"]["frames"][2]
    assert measured["ground_offset"] == inv.ground_offsets([frame], manifest["pivot"][1])[0] == 2
    assert [px, py] in measured["pinholes"] or any(
        c["id"] == "holes" and c["frame"] == 2 for c in report["checks"]), \
        "the pierced pixel is either a pinhole (metric) or a hole (check)"
    assert any(w.startswith("ground: frames more than 1 px away") for w in report["warnings"]), report["warnings"]
    others = [f["ground_offset"] for i, f in enumerate(report["metrics"]["frames"]) if i != 2]
    assert others == [0] * len(others)


def test_metrics_ground_offset_is_null_on_an_empty_frame(project, tmp_path):
    result = cli.animate(project / "rig.json", tmp_path / "frames", tmp_path, preset="idle").expect_ok()
    target = result.frame_paths()[1]
    empty = np.zeros_like(inv.as_rgba(target))
    Image.fromarray(empty, "RGBA").save(target)
    verdict = cli.validate(result.frames_dir(), tmp_path)
    verdict.assert_contract()
    measured = cli.report(verdict)["metrics"]["frames"][1]
    assert measured["ground_offset"] is None and measured["border"] == 0 and measured["pinholes"] == []
