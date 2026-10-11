"""Integration: horizontal mirror (docs/schemas.md, "Miroir horizontal")."""
from __future__ import annotations

import numpy as np
import pytest

from tests import cli_adapter as cli, invariants as inv
from tests.conftest import load_case, make_project

pytestmark = pytest.mark.integration

CASES = ["hero64", "rogue80_outline", "knight96"]


@pytest.fixture(params=CASES)
def pair(request, tmp_path):
    """(case, plain animate, mirrored animate) of the walk, same rig."""
    case = load_case(request.param)
    project = make_project(tmp_path / "project", case)
    plain = cli.animate(project / "rig.json", tmp_path / "plain", tmp_path, preset="walk").expect_ok()
    mirrored = cli.animate(project / "rig.json", tmp_path / "mirrored", tmp_path,
                           preset="walk", mirror=True).expect_ok()
    return case, plain, mirrored


def test_mirrored_frames_are_the_exact_flip_of_the_plain_ones(pair):
    _, plain, mirrored = pair
    a, b = plain.frames(), mirrored.frames()
    assert len(a) == len(b)
    for index, (left, right) in enumerate(zip(a, b)):
        assert np.array_equal(inv.canonical(left)[:, ::-1], inv.canonical(right)), f"frame {index}"
    assert not np.array_equal(inv.canonical(a[0]), inv.canonical(b[0])), "the character is not symmetric"
    assert plain.payload["outputs"]["mirror"] is False and mirrored.payload["outputs"]["mirror"] is True


def test_mirrored_manifest_is_expressed_in_the_flipped_sprite(pair):
    case, plain, mirrored = pair
    a, b = plain.manifest(), mirrored.manifest()
    sprite_w, canvas_w = case.native_size[0], a["canvas"][0]
    assert a["mirror"] is False and b["mirror"] is True
    assert b["canvas"] == a["canvas"]
    assert b["pivot"] == [canvas_w - a["pivot"][0], a["pivot"][1]], "pivot is a grid corner: x -> w - x"
    assert b["origin"] == [sprite_w - (a["origin"][0] + canvas_w), a["origin"][1]]
    for bone, rest in a["rest"]["bones"].items():
        assert b["rest"]["bones"][bone]["joint"] == [sprite_w - 1 - rest["joint"][0], rest["joint"][1]]
    for fa, fb in zip(a["frames"], b["frames"]):
        assert fb["pivot"] == b["pivot"] and fb["duration_ms"] == fa["duration_ms"]
        for bone, pose in fa["bones"].items():
            flipped = fb["bones"][bone]
            assert flipped["joint"] == [sprite_w - 1 - pose["joint"][0], pose["joint"][1]], bone
            assert flipped["angle"] == (180 if pose["angle"] == 180 else -pose["angle"]), bone
    assert b["joints"] == a["joints"] and b["source"]["palette"] == a["source"]["palette"]


def test_mirrored_frames_pass_the_tool_qa_and_the_independent_invariants(pair, tmp_path):
    """The flipped manifest must stay coherent: holes (3 causes), pivot, ground line."""
    case, _, mirrored = pair
    manifest = mirrored.manifest()
    inv.assert_no_violations(
        cli.animation_violations(mirrored.frames(), case.palette, manifest)
        + cli.ground_violations(mirrored.frames(), manifest, "walk"), f"mirrored {case.name}")
    cli.validate(mirrored.frames_dir(), tmp_path).expect_ok()


def test_a_manifest_that_is_not_flipped_would_be_caught(pair):
    """Failing counterpart: mirrored images described by the plain manifest do not hold."""
    case, plain, mirrored = pair
    wrong = dict(plain.manifest())
    violations = inv.check_holes(mirrored.frames(), wrong)
    assert violations, "the independent check must notice joints that are no longer under the limbs"


def test_export_mirror_equals_animate_mirror(pair, tmp_path):
    _, plain, mirrored = pair
    late = cli.export(plain.frames_dir(), tmp_path / "late", tmp_path, mirror=True).expect_ok()
    early = cli.export(mirrored.frames_dir(), tmp_path / "early", tmp_path).expect_ok()
    assert np.array_equal(inv.canonical(late.image(cli.KEY_SHEET)), inv.canonical(early.image(cli.KEY_SHEET)))
    a, b = cli.parse_sheet_json(late.json(cli.KEY_SHEET_JSON)), cli.parse_sheet_json(early.json(cli.KEY_SHEET_JSON))
    assert a.pivots == b.pivots and a.rects == b.rects and a.durations_ms == b.durations_ms
    assert a.mirror is True and b.mirror is True
    assert late.payload["outputs"]["mirror"] is True and early.payload["outputs"]["mirror"] is True
    canvas_w = plain.manifest()["canvas"][0]
    assert a.pivots[0] == (canvas_w - plain.manifest()["pivot"][0], plain.manifest()["pivot"][1])
    gif_late, _ = cli.gif_frames(late.path(cli.KEY_GIF))
    gif_early, _ = cli.gif_frames(early.path(cli.KEY_GIF))
    assert all(np.array_equal(x, y) for x, y in zip(gif_late, gif_early))


def test_export_mirror_does_not_touch_the_frames_directory(pair, tmp_path):
    _, plain, _ = pair
    before = {p.name: p.read_bytes() for p in plain.frames_dir().iterdir() if p.is_file()}
    cli.export(plain.frames_dir(), tmp_path / "late", tmp_path, mirror=True).expect_ok()
    after = {p.name: p.read_bytes() for p in plain.frames_dir().iterdir() if p.is_file()}
    assert after == before


def test_mirroring_twice_gives_back_the_plain_export(pair, tmp_path):
    _, plain, mirrored = pair
    straight = cli.export(plain.frames_dir(), tmp_path / "straight", tmp_path).expect_ok()
    twice = cli.export(mirrored.frames_dir(), tmp_path / "twice", tmp_path, mirror=True).expect_ok()
    assert np.array_equal(inv.canonical(straight.image(cli.KEY_SHEET)), inv.canonical(twice.image(cli.KEY_SHEET)))
    layout = cli.parse_sheet_json(twice.json(cli.KEY_SHEET_JSON))
    assert layout.mirror is False, "meta.animai.mirror = the opposite of the manifest's"
    assert layout.pivots == cli.parse_sheet_json(straight.json(cli.KEY_SHEET_JSON)).pivots


def test_mirror_is_deterministic(tmp_path):
    case = load_case("hero64")
    project = make_project(tmp_path / "project", case)
    runs = [cli.animate(project / "rig.json", tmp_path / f"run{i}", tmp_path, preset="attack",
                        mirror=True).expect_ok() for i in range(2)]
    assert [p.read_bytes() for p in runs[0].frame_paths()] == [p.read_bytes() for p in runs[1].frame_paths()]
