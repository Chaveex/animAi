"""Integration: hidden zone and fill (docs/schemas.md, "Zone cachee et remplissage").

* rule 3 "same common bone": what is under a front part between two sister limbs belongs to
  the body (their parent), and a limb never gains a trail;
* ``fill: "none"`` lists only what the part encloses alone, without false positive;
* ``fill_color``.
"""
from __future__ import annotations

import numpy as np
import pytest

from tests import cli_adapter as cli, contract, invariants as inv
from tests.conftest import load_case, make_project, write_anim
from tests.test_cli_holes import synthetic_case

pytestmark = pytest.mark.integration

ARM_UP = [{"duration_ms": 100, "bones": {}}, {"duration_ms": 100, "bones": {"arm_r": {"rot": 180}}}]


@pytest.fixture
def knight():
    return load_case("knight96")


def raise_near_arm(tmp_path, case, name, mutate=None):
    project = make_project(tmp_path / name, case, mutate)
    anim = write_anim(project / "anim.json", ARM_UP)
    result = cli.animate(project / "rig.json", project / "frames", tmp_path, keyframes=anim)
    return project, result


def rest_arm_pixels(case, manifest, frame):
    """What the raised-arm frame shows where the near arm (arm, forearm, hand) was at rest:
    list of (x, y, part behind in the row/column sense is unknown, rgba)."""
    raster = inv.rasterize_rig(case.rig, case.native_size)
    chain = [i + 1 for i, name in enumerate(raster.parts) if name in ("arm_r", "forearm_r", "hand_r")]
    ys, xs = np.nonzero(np.isin(raster.labels, chain))
    ox, oy = manifest["origin"]
    return [(int(x), int(y), tuple(int(v) for v in frame[y - oy, x - ox])) for x, y in zip(xs, ys)]


def part_rows(case, part):
    raster = inv.rasterize_rig(case.rig, case.native_size)
    ys, _ = np.nonzero(raster.labels == raster.parts.index(part) + 1)
    return set(ys.tolist())


def part_colours(case, part):
    raster = inv.rasterize_rig(case.rig, case.native_size)
    return {tuple(c) for c in case.sprite_rgba()[raster.labels == raster.parts.index(part) + 1][:, :3].tolist()}


# --------------------------------------------------------------------------- #
# rule 3
# --------------------------------------------------------------------------- #

def test_rule3_sister_limbs_the_parent_body_is_extended_under_the_front_part(tmp_path):
    """far limb = thigh_l, sister of thigh_r, both children of hips: the 72 px under the
    badge are given to the hips part (its colour), not to either thigh."""
    result, manifest, uncovered, colours = synthetic_case(tmp_path, "thigh_l")
    assert (uncovered[..., 3] == 255).all(), "the area under the badge must be filled"
    assert {tuple(c) for c in uncovered[..., :3].reshape(-1, 3).tolist()} == {colours["hips"]}, \
        "filled with the body (hips), never with a limb met on the way"
    cli.validate(result.frames_dir(), tmp_path).expect_ok()


def test_rule3_unrelated_limbs_nothing_is_filled_and_no_limb_gains_a_trail(tmp_path):
    """far limb = arm_l (child of spine) against thigh_r (child of hips): no common bone."""
    result, manifest, uncovered, colours = synthetic_case(tmp_path, "arm_l")
    shown = {tuple(c) for c in uncovered.reshape(-1, 4).tolist()}
    assert (colours["far"] + (255,)) not in shown and (colours["thigh_r"] + (255,)) not in shown, \
        "a limb must not be prolonged under the front part"
    assert (uncovered[..., 3] == 0).all()
    report = cli.rig(result.cwd / "synthetic_arm_l" / "sprite.png", result.cwd / "synthetic_arm_l" / "rig.json",
                     result.cwd / "rig_out", result.cwd).expect_ok().json(cli.KEY_RIG_REPORT)
    assert report["parts"]["far"]["hidden_pixels"] == 0 and report["parts"]["thigh_r"]["hidden_pixels"] == 0


def test_hip_under_the_hand_is_filled_with_the_hip(knight, tmp_path):
    """knight96: the near hand hangs in front of the hips and the top of both thighs."""
    _, result = raise_near_arm(tmp_path, knight, "own")
    result.expect_ok()
    manifest = result.manifest()
    frame = result.frames()[1]
    hips_rows, belt = sorted(part_rows(knight, "hips")), part_colours(knight, "hips")
    assert len(belt) == 1
    under = rest_arm_pixels(knight, manifest, frame)
    assert all(rgba[3] == 255 for _, _, rgba in under), "no transparent pixel where the arm was"
    # The torso (in front of the hips) may reach `overlap` rows down under the arm, the thighs
    # `overlap` rows up: between the two margins, only the hips can be there.
    parts = knight.rig["parts"]
    top = hips_rows[0] + parts["torso"]["overlap"]
    bottom = hips_rows[-1] - max(parts["thigh_l"]["overlap"], parts["thigh_r"]["overlap"])
    core = [rgba[:3] for _, y, rgba in under if top <= y <= bottom]
    assert core and set(core) == belt, "the hips rows uncovered by the arm show the hips colour"
    body = belt | part_colours(knight, "torso") | part_colours(knight, "thigh_r") | part_colours(knight, "thigh_l")
    on_hips = {rgba[:3] for _, y, rgba in under if y in hips_rows}
    assert on_hips <= body | part_colours(knight, "arm_r"), f"unexpected colours on the hips rows: {on_hips}"
    inv.assert_no_violations(cli.animation_violations(result.frames(), knight.palette, manifest), "arm up")
    cli.validate(result.frames_dir(), tmp_path).expect_ok()


def test_far_limbs_do_not_show_through_where_the_near_arm_was(knight, tmp_path):
    """No trail: the far arm's own colours never appear in the area the near arm uncovered."""
    _, result = raise_near_arm(tmp_path, knight, "own")
    manifest = result.expect_ok().manifest()
    far_only = (part_colours(knight, "arm_l") | part_colours(knight, "hand_l")) \
        - part_colours(knight, "torso") - part_colours(knight, "hips") - part_colours(knight, "arm_r")
    assert far_only, "test premise: the far arm has colours of its own"
    shown = {rgba[:3] for _, _, rgba in rest_arm_pixels(knight, manifest, result.frames()[1])}
    assert not (shown & far_only), f"far-limb colours {shown & far_only} leaked under the near arm"
    project = tmp_path / "own"
    report = cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "rig", tmp_path) \
        .expect_ok().json(cli.KEY_RIG_REPORT)
    hand = knight.rig["parts"]["hand_l"]
    width = max(r[2] for r in hand["region"]["rects"])
    assert report["parts"]["hand_l"]["hidden_pixels"] <= hand["overlap"] * width, \
        "the far hand only gets its joint margin, not an extension under the thigh"


# --------------------------------------------------------------------------- #
# fill: "none"
# --------------------------------------------------------------------------- #

def test_fill_none_lists_only_what_the_part_encloses_alone(knight, tmp_path):
    project, result = raise_near_arm(tmp_path, knight, "none",
                                     lambda rig: rig["parts"]["hips"].update(fill="none"))
    manifest = result.expect_ok().manifest()
    missing = {tuple(p) for p in manifest["parts"]["hips"]["missing"]}
    assert missing, "the hips enclose the arm on their own rows: those pixels have no data"
    raster = inv.rasterize_rig(knight.rig, knight.native_size)
    hips = raster.labels == raster.parts.index("hips") + 1
    for x, y in missing:
        row, column = np.nonzero(hips[y])[0], np.nonzero(hips[:, x])[0]
        between_row = len(row) and row.min() < x < row.max()
        between_column = len(column) and column.min() < y < column.max()
        assert not hips[y, x] and (between_row or between_column), \
            f"missing pixel {(x, y)} is not enclosed by the hips alone (rule 1)"
    assert all(part["missing"] == [] for name, part in manifest["parts"].items() if name != "hips")
    rig_report = cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "rig", tmp_path) \
        .expect_ok().json(cli.KEY_RIG_REPORT)
    assert rig_report["parts"]["hips"]["missing_pixels"] == len(missing)
    assert rig_report["parts"]["hips"]["hidden_pixels"] == 0, "fill none: no data, overlap has no effect"


def test_fill_none_true_positive_when_uncovered_no_false_positive_when_covered(knight, tmp_path):
    project, result = raise_near_arm(tmp_path, knight, "none",
                                     lambda rig: rig["parts"]["hips"].update(fill="none"))
    manifest = result.expect_ok().manifest()
    frames = result.frames()
    assert inv.hole_frames(frames, manifest) == [1], "rest frame: still covered; arm up: uncovered"
    verdict = cli.validate(result.frames_dir(), tmp_path).expect_user_error()
    failing = [c for c in cli.report(verdict)["checks"] if c["id"] == "holes" and not c["pass"]]
    assert [c["frame"] for c in failing] == [1] and "part 'hips' has no data" in failing[0]["detail"]
    # no false positive: the idle never uncovers the hips, the QA must stay green
    idle = cli.animate(project / "rig.json", tmp_path / "idle", tmp_path, preset="idle").expect_ok()
    assert inv.check_holes(idle.frames(), idle.manifest()) == []
    cli.validate(idle.frames_dir(), tmp_path).expect_ok()


def test_fill_none_accepts_false_as_a_synonym(knight, tmp_path):
    _, as_none = raise_near_arm(tmp_path, knight, "none", lambda rig: rig["parts"]["hips"].update(fill="none"))
    _, as_false = raise_near_arm(tmp_path, knight, "false", lambda rig: rig["parts"]["hips"].update(fill=False))
    assert [p.read_bytes() for p in as_none.expect_ok().frame_paths()] == \
           [p.read_bytes() for p in as_false.expect_ok().frame_paths()]


# --------------------------------------------------------------------------- #
# fill_color
# --------------------------------------------------------------------------- #

def test_fill_color_paints_the_whole_hidden_zone(knight, tmp_path):
    colour = "#ac3232"                                         # the belt colour, not a torso colour
    rgb = inv.hex_to_rgb(colour)
    assert rgb in knight.palette and rgb not in part_colours(knight, "torso")
    _, default = raise_near_arm(tmp_path, knight, "own")
    _, painted = raise_near_arm(tmp_path, knight, "color",
                                lambda rig: rig["parts"]["torso"].update(fill_color=colour))
    torso_rows = part_rows(knight, "torso")

    def torso_zone(result):
        manifest = result.expect_ok().manifest()
        return [rgba[:3] for _, y, rgba in rest_arm_pixels(knight, manifest, result.frames()[1])
                if y in torso_rows]

    before, after = torso_zone(default), torso_zone(painted)
    assert rgb not in before, "default fill: the torso's own colours"
    changed = [b for a, b in zip(before, after) if a != b]
    assert changed and set(changed) == {rgb}, "every pixel that changed took fill_color"
    assert after.count(rgb) >= len(after) // 2
    inv.assert_no_violations(inv.check_palette(painted.frames(), knight.palette), "fill_color")


def test_fill_color_outside_the_palette_is_refused(knight, tmp_path):
    project, result = raise_near_arm(tmp_path, knight, "bad",
                                     lambda rig: rig["parts"]["torso"].update(fill_color="#010203"))
    result.expect_user_error()
    assert "#010203" in result.payload["error"] and "torso" in result.payload["error"]
    cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "rig", tmp_path).expect_user_error()
    assert contract.validate_rig(knight.rig) == []
