"""Integration: the outline pass (docs/schemas.md, "Passe de contour").

rogue80_outline has a 1 px dark outline on its whole silhouette; hero64 has none.
Every property is recomputed here from the frame images.
"""
from __future__ import annotations

import numpy as np
import pytest

from tests import cli_adapter as cli, invariants as inv
from tests.conftest import load_case, make_project, write_anim

pytestmark = pytest.mark.integration

LIMB_POSE = {"arm_r": {"rot": 90}, "thigh_l": {"rot": -30}, "forearm_l": {"rot": 45}}


@pytest.fixture
def rogue():
    return load_case("rogue80_outline")


def render(tmp_path, case, name, mutate=None, *, preset=None, frames=None):
    """Animate a (mutated) copy of the fixture rig; returns the animate result."""
    project = make_project(tmp_path / name, case, mutate)
    if preset is not None:
        return cli.animate(project / "rig.json", project / "frames", tmp_path, preset=preset)
    anim = write_anim(project / "anim.json", frames or [{"duration_ms": 100, "bones": LIMB_POSE}])
    return cli.animate(project / "rig.json", project / "frames", tmp_path, keyframes=anim)


def in_sprite_space(result, size):
    """Frame 0 pasted at its place in sprite coordinates, on a canvas big enough to compare
    renders whose canvases differ (the outside outline grows the bounding box by 1 px)."""
    manifest, frame = result.manifest(), result.frames()[0]
    margin = 24
    canvas = np.zeros((size[1] + 2 * margin, size[0] + 2 * margin, 4), np.uint8)
    x, y = manifest["origin"][0] + margin, manifest["origin"][1] + margin
    canvas[y:y + frame.shape[0], x:x + frame.shape[1]] = frame
    return inv.canonical(canvas)


@pytest.mark.parametrize("preset", cli.MVP_PRESETS)
def test_outlined_sprite_has_no_bare_border_on_any_frame(preset, rogue, tmp_path):
    result = render(tmp_path, rogue, "auto", preset=preset).expect_ok()
    manifest = result.manifest()
    colour = tuple(rogue.meta["outline_color"])
    assert manifest["outline"]["color"] == "#%02x%02x%02x" % colour
    assert manifest["outline"]["mode"] == "outside"
    assert manifest["outline_detected"]["source_bare"] == inv.bare_border_count(rogue.sprite, colour) == 0
    assert manifest["outline_detected"]["source_border"] == int(inv.silhouette_border(rogue.sprite).sum())
    bare = [inv.bare_border_count(frame, colour) for frame in result.frames()]
    assert bare == [0] * len(bare), f"bare silhouette border pixels per frame: {bare}"
    inv.assert_no_violations(cli.animation_violations(result.frames(), rogue.palette, manifest), preset)


@pytest.mark.parametrize("off", ["none", False])
def test_outline_disabled_leaves_bare_borders_and_the_qa_measures_them(off, rogue, tmp_path):
    """The failing counterpart: without the pass the limbs leave the body without a line."""
    result = render(tmp_path, rogue, "off", lambda rig: rig.update(outline=off), preset="walk").expect_ok()
    manifest = result.manifest()
    assert manifest["outline"] is None and result.payload["outputs"]["outline"] is None
    assert manifest["outline_detected"]["color"] == "#%02x%02x%02x" % tuple(rogue.meta["outline_color"])
    colour = tuple(rogue.meta["outline_color"])
    bare = [inv.bare_border_count(frame, colour) for frame in result.frames()]
    assert max(bare) > 0, "a moving limb drawn inside the body has no line of its own"
    verdict = cli.validate(result.frames_dir(), tmp_path).expect_ok()      # metrics never change ok
    report = cli.report(verdict)
    assert report["metrics"]["outline"] == {"applied": False, "color": manifest["outline_detected"]["color"],
                                           "source_bare": 0}
    assert [f["outline_bare"] for f in report["metrics"]["frames"]] == bare
    assert any(w.startswith(f"outline: up to {max(bare)} of ") for w in report["warnings"]), report["warnings"]
    assert verdict.warnings == report["warnings"]


def test_sprite_without_outline_is_left_untouched(hero, tmp_path):
    auto = render(tmp_path, hero, "auto", preset="walk").expect_ok()
    off = render(tmp_path, hero, "off", lambda rig: rig.update(outline="none"), preset="walk").expect_ok()
    manifest = auto.manifest()
    assert manifest["outline"] is None and manifest["outline_detected"] is None
    assert [p.read_bytes() for p in auto.frame_paths()] == [p.read_bytes() for p in off.frame_paths()]
    report = cli.report(cli.validate(auto.frames_dir(), tmp_path).expect_ok())
    assert report["metrics"]["outline"] is None
    assert all(f["outline_bare"] is None for f in report["metrics"]["frames"])


@pytest.mark.parametrize("mode", ["outside", "inside"])
def test_rest_pose_stays_identical_to_the_sprite(mode, rogue, tmp_path):
    result = render(tmp_path, rogue, mode, lambda rig: rig.update(outline_mode=mode),
                    frames=[{"duration_ms": 100, "bones": {}}]).expect_ok()
    assert result.manifest()["outline"]["mode"] == mode
    assert np.array_equal(inv.crop_to_content(result.frames()[0]), inv.crop_to_content(rogue.sprite))


def test_outside_mode_only_adds_outline_pixels_around_the_silhouette(rogue, tmp_path):
    plain = render(tmp_path, rogue, "off", lambda rig: rig.update(outline="none")).expect_ok()
    lined = render(tmp_path, rogue, "outside").expect_ok()
    assert lined.manifest()["outline"]["inner_parts"] == [], "test premise: no part-to-part line here"
    before, after = in_sprite_space(plain, rogue.native_size), in_sprite_space(lined, rogue.native_size)
    was, now = before[..., 3] > 0, after[..., 3] > 0
    assert not (was & ~now).any(), "outside mode never removes a pixel"
    assert np.array_equal(after[was], before[was]), "outside mode never repaints an existing pixel"
    added = now & ~was
    assert added.any(), "the limbs that left the body must gain a line"
    assert {tuple(c) for c in after[added][:, :3].tolist()} == {tuple(rogue.meta["outline_color"])}
    bare = inv.silhouette_border(before) & ~(before[..., :3] == rogue.meta["outline_color"]).all(axis=2)
    grown = np.zeros_like(bare)
    grown[1:, :] |= bare[:-1, :]
    grown[:-1, :] |= bare[1:, :]
    grown[:, 1:] |= bare[:, :-1]
    grown[:, :-1] |= bare[:, 1:]
    assert np.array_equal(added, grown & ~was), "added = transparent 4-neighbours of bare border pixels"
    assert inv.bare_border_count(after, rogue.meta["outline_color"]) == 0


def test_inside_mode_repaints_border_pixels_without_growing_the_silhouette(rogue, tmp_path):
    plain = render(tmp_path, rogue, "off", lambda rig: rig.update(outline="none")).expect_ok()
    lined = render(tmp_path, rogue, "inside", lambda rig: rig.update(outline_mode="inside")).expect_ok()
    before, after = in_sprite_space(plain, rogue.native_size), in_sprite_space(lined, rogue.native_size)
    assert np.array_equal(before[..., 3], after[..., 3]), "inside mode keeps the silhouette as it is"
    changed = (before != after).any(axis=2)
    assert changed.any()
    assert {tuple(c) for c in after[changed][:, :3].tolist()} == {tuple(rogue.meta["outline_color"])}
    bare = inv.silhouette_border(before) & ~(before[..., :3] == rogue.meta["outline_color"]).all(axis=2)
    assert np.array_equal(changed, bare), "repainted = exactly the bare border pixels"
    assert inv.bare_border_count(after, rogue.meta["outline_color"]) == 0


def test_imposed_colour_from_the_palette_is_applied_even_without_detected_outline(hero, tmp_path):
    colour = "#222034"                                           # the eye colour of hero64
    assert inv.hex_to_rgb(colour) in hero.palette
    plain = render(tmp_path, hero, "auto").expect_ok()
    lined = render(tmp_path, hero, "hex", lambda rig: rig.update(outline=colour)).expect_ok()
    manifest = lined.manifest()
    assert manifest["outline"]["color"] == colour
    before, after = in_sprite_space(plain, hero.native_size), in_sprite_space(lined, hero.native_size)
    added = (after[..., 3] > 0) & ~(before[..., 3] > 0)
    assert added.any() and {tuple(c) for c in after[added][:, :3].tolist()} == {inv.hex_to_rgb(colour)}
    inv.assert_no_violations(inv.check_palette(lined.frames(), hero.palette), "imposed outline")


def test_outline_detected_stays_null_on_a_sprite_without_outline_when_a_colour_is_imposed(hero, tmp_path):
    """docs/schemas.md: outline_detected = 'le contour que le sprite possede, que la passe soit
    active ou non'. hero64 has none, whatever colour the rig imposes."""
    lined = render(tmp_path, hero, "hex", lambda rig: rig.update(outline="#222034")).expect_ok()
    assert lined.manifest()["outline_detected"] is None


@pytest.mark.parametrize("mutation, needle", [
    ({"outline": "#123456"}, "#123456"),             # not a colour of the sprite
    ({"outline_mode": "middle"}, "outline_mode"),
    ({"outline": "black"}, "black"),
])
def test_invalid_outline_settings_are_refused(mutation, needle, rogue, tmp_path):
    project = make_project(tmp_path / "bad", rogue, lambda rig: rig.update(mutation))
    for result in (cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "rig", tmp_path),
                   cli.animate(project / "rig.json", tmp_path / "frames", tmp_path, preset="idle")):
        result.expect_user_error()
        assert needle in result.payload["error"]
    assert not list(tmp_path.rglob("frame_*.png")), "no frame may be written with a refused setting"
