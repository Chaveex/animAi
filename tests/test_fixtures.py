"""The reference sprites and rigs are what the rest of the suite assumes.

Pass today: these only look at files under fixtures/.
"""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

from fixtures import make_fixtures
from tests import contract, invariants as inv
from tests.conftest import FIXTURES_DIR, FIXTURE_NAMES, REPO_ROOT, load_case


def test_fixture_set_covers_the_required_variety():
    cases = [load_case(name) for name in FIXTURE_NAMES]
    assert 3 <= len(cases) <= 5
    native = {c.native_size for c in cases}
    assert (64, 64) in native and (96, 96) in native
    assert len(native) >= 3, "sizes must differ"
    assert any(c.meta["outline"] for c in cases), "need a sprite with a 1 px dark outline"
    assert any(c.meta["background"] for c in cases), "need a sprite with a flat background"
    assert any(c.meta["scale"] == 4 for c in cases), "need a x4 upscaled sprite"
    assert all(min(c.native_size) >= 64 for c in cases), "MVP scope is >= 64x64"


def test_files_on_disk_match_the_generator():
    assert make_fixtures.stale_files() == [], "run: python fixtures/make_fixtures.py"


def test_generator_is_deterministic_and_check_mode_works():
    assert make_fixtures.generate() == make_fixtures.generate()
    done = subprocess.run([sys.executable, str(FIXTURES_DIR / "make_fixtures.py"), "--check"],
                          cwd=REPO_ROOT, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr


def test_stale_file_is_detected(tmp_path):
    make_fixtures.write_all(tmp_path)
    assert make_fixtures.stale_files(tmp_path) == []
    (tmp_path / "hero64" / "rig.json").write_text("{}", encoding="utf-8")
    Image.new("RGBA", (64, 64)).save(tmp_path / "hero64" / "sprite.png")
    (tmp_path / "manifest.json").unlink()
    assert sorted(make_fixtures.stale_files(tmp_path)) == [
        "hero64/rig.json", "hero64/sprite.png", "manifest.json"]


def test_manifest_lists_every_fixture():
    manifest = json.loads((FIXTURES_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert [f["name"] for f in manifest["fixtures"]] == list(FIXTURE_NAMES)


# --------------------------------------------------------------------------- #
# sprite.png (the cleaned sprite)
# --------------------------------------------------------------------------- #

def test_sprite_has_native_size_and_rgba_mode(case):
    with Image.open(case.sprite) as image:
        assert image.mode == "RGBA" and image.size == case.native_size


def test_sprite_respects_every_single_frame_invariant(case):
    violations = inv.check_frames([case.sprite], case.palette)
    violations += inv.check_enclosed_regions([case.sprite])
    inv.assert_no_violations(violations, f"fixtures/{case.name}/sprite.png")


def test_sprite_is_one_connected_character_with_few_colours(case):
    sprite = case.sprite_rgba()
    assert len(inv.connected_components(sprite[..., 3] > 0, 8)) == 1
    assert 6 <= len(case.palette) <= 16
    assert case.meta["opaque_pixels"] == int((sprite[..., 3] == 255).sum()) > 300


def test_sprite_stands_on_the_ground_with_margins(case):
    sprite = case.sprite_rgba()
    ys, xs = np.nonzero(sprite[..., 3])
    width, height = case.native_size
    assert xs.min() >= 1 and ys.min() >= 1 and xs.max() <= width - 2 and ys.max() <= height - 2
    assert ys.max() >= height * 0.85, "feet should be near the bottom of the canvas"
    assert (ys.max() - ys.min() + 1) > 2 * (xs.max() - xs.min() + 1), "a standing humanoid is tall"


# --------------------------------------------------------------------------- #
# source.png (raw input of `prepare`)
# --------------------------------------------------------------------------- #

def test_source_size_matches_meta(case):
    with Image.open(case.source) as image:
        assert list(image.size) == case.meta["source_size"]
        assert image.mode == case.meta["source_mode"]
    scale = case.meta["scale"]
    assert case.meta["source_size"] == [case.native_size[0] * scale, case.native_size[1] * scale]


def test_source_reduces_exactly_to_the_clean_sprite(case):
    """source.png -> (drop every scale-th pixel, key the background) == sprite.png."""
    source, scale = inv.as_rgba(case.source), case.meta["scale"]
    blocks = source.reshape(source.shape[0] // scale, scale, source.shape[1] // scale, scale, 4)
    assert (blocks == blocks[:, :1, :, :1]).all(), "source must be an exact NN upscale"
    native = source[::scale, ::scale].copy()
    if case.meta["background"] is not None:
        assert (native[..., 3] == 255).all(), "background fixture must be fully opaque"
        background = (native[..., :3] == case.meta["background"]).all(axis=2)
        assert tuple(case.meta["background"]) not in case.palette
        assert background[0, 0] and background[-1, -1]
        native[background] = 0
    assert np.array_equal(inv.canonical(native), inv.canonical(case.sprite))


def test_outline_fixture_has_a_one_pixel_dark_outline():
    case = load_case("rogue80_outline")
    sprite = case.sprite_rgba()
    opaque = sprite[..., 3] == 255
    padded = np.pad(opaque, 1)
    edge = opaque & ~(padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:])
    outline = (sprite[..., :3] == case.meta["outline_color"]).all(axis=2) & opaque
    assert np.array_equal(outline, edge), "outline = exactly the silhouette's border pixels"
    assert sum(case.meta["outline_color"]) < 3 * 64, "outline must be dark"


def test_upscaled_fixture_is_the_plain_hero():
    plain, upscaled = load_case("hero64"), load_case("hero64_x4")
    assert plain.sprite.read_bytes() == upscaled.sprite.read_bytes()
    assert plain.rig == upscaled.rig
    assert upscaled.meta["source_size"] == [256, 256]


# --------------------------------------------------------------------------- #
# rig.json
# --------------------------------------------------------------------------- #

def test_rig_is_valid_against_the_contract(case):
    assert contract.validate_rig(case.rig) == []
    assert case.rig["sprite"] == case.sprite.name and case.rig["view"] == "side"
    assert case.rig["template"] == "humanoid" and case.rig["pivot"] == [0.5, 1.0]


def test_rig_uses_only_canonical_bones_with_the_documented_hierarchy(case):
    bones = case.rig["bones"]
    assert set(bones) <= set(contract.CANONICAL_BONES)
    required = {"hips", "spine", "head", "arm_r", "forearm_r", "arm_l", "forearm_l",
                "thigh_r", "shin_r", "foot_r", "thigh_l", "shin_l", "foot_l"}
    assert required <= set(bones)
    parents = {name: bone["parent"] for name, bone in bones.items()}
    assert parents["hips"] is None and parents["spine"] == "hips" and parents["head"] == "spine"
    for side in "rl":
        assert parents[f"arm_{side}"] == "spine" and parents[f"forearm_{side}"] == f"arm_{side}"
        assert parents[f"thigh_{side}"] == "hips" and parents[f"shin_{side}"] == f"thigh_{side}"
        assert parents[f"foot_{side}"] == f"shin_{side}"
        if f"hand_{side}" in bones:
            assert parents[f"hand_{side}"] == f"forearm_{side}"


def test_rig_assigns_every_source_pixel_to_exactly_one_part(case):
    inv.assert_no_violations(inv.check_rig_covers_sprite(case.sprite, case.rig),
                             f"fixtures/{case.name}/rig.json")


def test_rig_regions_cover_only_opaque_pixels(case):
    raster = inv.rasterize_rig(case.rig, case.native_size)
    assert np.array_equal(raster.labels > 0, case.sprite_rgba()[..., 3] == 255)


def test_rig_parts_are_real_distinct_limbs(case):
    parts = case.rig["parts"]
    expected = {"head", "torso", "hips", "arm_r", "forearm_r", "arm_l", "forearm_l",
                "thigh_r", "shin_r", "foot_r", "thigh_l", "shin_l", "foot_l"}
    assert expected <= set(parts)
    assert parts["torso"]["bone"] == "spine"
    assert {p["bone"] for p in parts.values()} == set(case.rig["bones"]), "one part per bone"
    raster = inv.rasterize_rig(case.rig, case.native_size)
    for index, name in enumerate(raster.parts, start=1):
        mask = raster.labels == index
        assert mask.sum() >= 6, f"part '{name}' is too small to be a limb"
        # a limb passing in front may cut the visible area of a part in two, not more
        assert len(inv.connected_components(mask, 8)) <= 2, f"part '{name}' is scattered"
    z_values = [p["z"] for p in parts.values()]
    assert len(set(z_values)) == len(z_values), "unique z: draw order must not rely on a tie-break"
    assert parts["arm_l"]["z"] < parts["torso"]["z"] < parts["arm_r"]["z"]
    assert parts["thigh_l"]["z"] < parts["hips"]["z"] < parts["thigh_r"]["z"]


def test_rig_overlaps():
    """Default margins, and the wave 2 fix: 3 px under the knee of the wide knight legs."""
    for name in FIXTURE_NAMES:
        parts = load_case(name).rig["parts"]
        expected = {part: (2 if part in ("hips", "torso") else 1) for part in parts}
        if name == "knight96":
            expected.update(thigh_l=3, thigh_r=3, shin_l=2, shin_r=2)
        assert {part: spec["overlap"] for part, spec in parts.items()} == expected, name


def test_rig_joints_sit_on_the_character(case):
    opaque = case.sprite_rgba()[..., 3] == 255
    width, height = case.native_size
    for name, bone in case.rig["bones"].items():
        x, y = bone["joint"]
        assert 0 <= x < width and 0 <= y < height, f"joint of '{name}' is off canvas"
        assert opaque[max(y - 1, 0):y + 2, max(x - 1, 0):x + 2].any(), f"joint of '{name}' floats"
    joints = {name: bone["joint"] for name, bone in case.rig["bones"].items()}
    for side in "rl":   # y grows downwards: hip above knee above ankle, shoulder above elbow
        assert joints[f"thigh_{side}"][1] < joints[f"shin_{side}"][1] < joints[f"foot_{side}"][1]
        assert joints[f"arm_{side}"][1] < joints[f"forearm_{side}"][1]
    assert joints["head"][1] < joints["spine"][1]


def test_rig_ik_targets_feet(case):
    ik = case.rig["ik"]
    for side in "rl":
        assert ik[f"foot_{side}"] == {"chain": [f"thigh_{side}", f"shin_{side}"],
                                      "target_bone": f"foot_{side}"}


def test_one_fixture_exercises_region_pixels():
    used = [name for name in FIXTURE_NAMES
            if any(p["region"]["pixels"] for p in load_case(name).rig["parts"].values())]
    assert used == ["rogue80_outline"]


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_meta_lists_parts_and_bones(name):
    case = load_case(name)
    assert case.meta["parts"] == list(case.rig["parts"])
    assert case.meta["bones"] == list(case.rig["bones"])
