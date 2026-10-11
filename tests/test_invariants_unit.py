"""Unit tests of the invariant helpers themselves, on hand-built images.

For every invariant: at least one image that must pass and one that must fail.
No dependency on animai.core or the CLI: these pass today.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from tests import invariants as inv

RED, GREEN, BLUE, BLACK = (255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 0, 0)


def blank(width=8, height=8) -> np.ndarray:
    return np.zeros((height, width, 4), dtype=np.uint8)


def put(image, x, y, colour=RED, alpha=255):
    image[y, x] = (*colour, alpha)
    return image


def box(image, x, y, w, h, colour=RED, alpha=255):
    image[y:y + h, x:x + w] = (*colour, alpha)
    return image


def ring(size=8) -> np.ndarray:
    """A 5x5 opaque square outline with a 3x3 transparent inside."""
    image = box(blank(size, size), 1, 1, 5, 5)
    image[2:5, 2:5] = 0
    return image


# --------------------------------------------------------------------------- #
# loading helpers
# --------------------------------------------------------------------------- #

def test_as_rgba_accepts_path_pil_and_array(tmp_path):
    image = box(blank(), 2, 2, 3, 3)
    path = tmp_path / "a.png"
    Image.fromarray(image, "RGBA").save(path)
    for source in (path, str(path), Image.fromarray(image, "RGBA"), image):
        assert np.array_equal(inv.as_rgba(source), image)


def test_as_rgba_converts_rgb_and_palette_files(tmp_path):
    rgb = Image.new("RGB", (4, 4), GREEN)
    rgb.save(tmp_path / "rgb.png")
    loaded = inv.as_rgba(tmp_path / "rgb.png")
    assert loaded.shape == (4, 4, 4) and (loaded[..., 3] == 255).all()
    rgb.convert("P").save(tmp_path / "p.png")
    assert inv.palette_of(tmp_path / "p.png") == {GREEN}


@pytest.mark.parametrize("bad", [np.zeros((4, 4, 3), np.uint8), np.zeros((4, 4, 4), np.float32),
                                 np.zeros((4, 4), np.uint8)])
def test_as_rgba_rejects_wrong_arrays(bad):
    with pytest.raises(ValueError):
        inv.as_rgba(bad)


def test_palette_of_ignores_fully_transparent_pixels():
    image = box(blank(), 0, 0, 2, 2, RED)
    put(image, 5, 5, GREEN, alpha=0)        # invisible colour
    put(image, 6, 6, BLUE, alpha=10)        # visible, even if barely
    assert inv.palette_of(image) == {RED, BLUE}
    assert inv.palette_of(blank()) == frozenset()


def test_canonical_zeroes_invisible_rgb_only():
    image = put(put(blank(), 1, 1, GREEN, alpha=0), 2, 2, RED)
    result = inv.canonical(image)
    assert tuple(result[1, 1]) == (0, 0, 0, 0) and tuple(result[2, 2]) == (*RED, 255)
    assert tuple(image[1, 1]) == (*GREEN, 0), "input must not be modified"


def test_crop_to_content():
    image = box(blank(10, 10), 3, 4, 2, 5)
    assert inv.crop_to_content(image).shape == (5, 2, 4)
    assert inv.crop_to_content(blank()).size == 0


def test_split_grid_row_major_and_rejects_bad_size():
    sheet = blank(8, 4)
    for index, (x, y) in enumerate([(0, 0), (4, 0), (0, 2), (4, 2)]):
        box(sheet, x, y, 4, 2, (index + 1, 0, 0))
    frames = inv.split_grid(sheet, 4, 2)
    assert [int(f[0, 0, 0]) for f in frames] == [1, 2, 3, 4]
    with pytest.raises(ValueError):
        inv.split_grid(sheet, 3, 2)


def test_connected_components_4_vs_8():
    mask = np.zeros((4, 4), bool)
    mask[0, 0] = mask[1, 1] = True          # diagonal neighbours
    assert len(inv.connected_components(mask, 8)) == 1
    assert len(inv.connected_components(mask, 4)) == 2
    with pytest.raises(ValueError):
        inv.connected_components(mask, 6)


# --------------------------------------------------------------------------- #
# palette
# --------------------------------------------------------------------------- #

def test_palette_pass_subset_of_source():
    frames = [box(blank(), 1, 1, 3, 3, RED), box(blank(), 1, 1, 3, 3, GREEN)]
    assert inv.check_palette(frames, [RED, GREEN, BLUE]) == []


def test_palette_fail_new_colour_is_located():
    frame = put(box(blank(), 1, 1, 3, 3, RED), 2, 3, (254, 0, 0))   # off by one = new colour
    violations = inv.check_palette([box(blank(), 1, 1, 3, 3, RED), frame], [RED])
    assert [(v.check, v.frame, v.pixel) for v in violations] == [("palette", 1, (2, 3))]


def test_palette_fail_blended_semi_transparent_colour():
    frame = put(blank(), 4, 4, (128, 128, 0), alpha=128)            # anti-aliased edge
    assert inv.check_palette([frame], [RED, GREEN])


def test_palette_ignores_rgb_under_alpha_zero():
    assert inv.check_palette([put(blank(), 0, 0, BLUE, alpha=0)], [RED]) == []


def test_palette_violations_are_capped_per_frame():
    violations = inv.check_palette([box(blank(), 0, 0, 8, 8, BLUE)], [RED])
    assert len(violations) == inv.MAX_REPORTED + 1 and "more" in violations[-1].detail


def test_palette_rejects_empty_source():
    with pytest.raises(ValueError):
        inv.check_palette([blank()], [])


# --------------------------------------------------------------------------- #
# alpha
# --------------------------------------------------------------------------- #

def test_alpha_binary_pass():
    assert inv.check_alpha_binary([box(blank(), 0, 0, 4, 4), blank()]) == []


@pytest.mark.parametrize("alpha", [1, 127, 128, 254])
def test_alpha_binary_fail(alpha):
    violations = inv.check_alpha_binary([blank(), put(blank(), 6, 2, RED, alpha=alpha)])
    assert [(v.check, v.frame, v.pixel) for v in violations] == [("alpha_binary", 1, (6, 2))]
    assert str(alpha) in violations[0].detail


# --------------------------------------------------------------------------- #
# orphans
# --------------------------------------------------------------------------- #

def test_orphans_pass_solid_shape_and_diagonal_contact():
    frame = box(blank(), 1, 1, 3, 3)
    put(frame, 4, 4)                        # touches the block by a corner: not an orphan
    assert inv.check_orphans([frame]) == []


def test_orphans_fail_isolated_pixel():
    frame = put(box(blank(), 0, 0, 3, 3), 6, 6)
    violations = inv.check_orphans([blank(), frame])
    assert [(v.check, v.frame, v.pixel) for v in violations] == [("orphans", 1, (6, 6))]


def test_orphans_are_compared_to_the_source_sprite_count():
    one = put(box(blank(), 0, 0, 3, 3), 6, 6)
    two = put(one.copy(), 6, 1)
    assert inv.check_orphans([one], allowed=1) == [], "the source already had this speck"
    violations = inv.check_orphans([one, two], allowed=1)
    assert [(v.frame, v.pixel) for v in violations] == [(1, (6, 1))]
    assert "2 isolated pixel(s), source sprite has 1" in violations[0].detail


def test_orphans_two_pixel_speck_is_not_an_orphan():
    frame = box(box(blank(), 0, 0, 3, 3), 6, 6, 2, 1)       # each pixel has an opaque neighbour
    assert inv.check_orphans([frame]) == []


def test_orphans_empty_frame_passes():
    assert inv.check_orphans([blank()]) == []


# --------------------------------------------------------------------------- #
# enclosed regions (tester-side, for source sprites; NOT the contract's holes)
# --------------------------------------------------------------------------- #

def test_enclosed_pass_solid_and_open_notch():
    notch = box(blank(), 1, 1, 5, 5)
    notch[2:6, 3] = 0                       # slit open at the bottom edge of the shape
    assert inv.check_enclosed_regions([box(blank(), 1, 1, 5, 5), notch, blank()]) == []


def test_enclosed_fail_region_reported_once():
    violations = inv.check_enclosed_regions([blank(), ring()])
    assert len(violations) == 1
    assert (violations[0].check, violations[0].frame, violations[0].pixel) == ("enclosed", 1, (2, 2))
    assert "9 pixel" in violations[0].detail


def test_enclosed_fail_single_pixel_crack():
    frame = box(blank(), 1, 1, 5, 5)
    frame[3, 3] = 0
    assert [v.pixel for v in inv.check_enclosed_regions([frame])] == [(3, 3)]


def test_enclosed_diagonal_gap_does_not_open_the_region():
    frame = ring()
    frame[1, 1] = 0                         # the inside only touches the outside diagonally
    assert len(inv.check_enclosed_regions([frame])) == 1


def test_enclosed_shape_touching_canvas_border():
    frame = box(blank(5, 5), 0, 0, 5, 5)
    frame[1:4, 1:4] = 0
    assert len(inv.check_enclosed_regions([frame])) == 1


def test_enclosed_min_area_and_mask():
    frame = box(blank(), 1, 1, 5, 5)
    frame[3, 3] = 0
    assert inv.check_enclosed_regions([frame], min_area=2) == []
    mask = inv.enclosed_mask(ring())
    assert int(mask.sum()) == 9 and mask[2:5, 2:5].all()


# --------------------------------------------------------------------------- #
# holes, by cause (docs/schemas.md), from a hand-written frames.json
# --------------------------------------------------------------------------- #

def manifest(poses, *, canvas=(12, 12), origin=(0, 0), joints=None, parts=None, rest=None,
             pivots=None, parents=None):
    """Minimal frames.json: ``poses`` = one {bone: (angle, (x, y))} per frame, sprite coords."""
    return {
        "canvas": list(canvas), "origin": list(origin), "joints": dict(joints or {}),
        "parts": dict(parts or {}),
        "rest": {"bones": {bone: {"parent": (parents or {}).get(bone), "joint": list(joint)}
                           for bone, joint in (rest or {}).items()}},
        "frames": [{"file": f"frame_{i:03d}.png", "pivot": list((pivots or [(6, 10)] * len(poses))[i]),
                    "bones": {bone: {"angle": angle, "joint": list(joint)}
                              for bone, (angle, joint) in pose.items()}}
                   for i, pose in enumerate(poses)],
    }


def body():
    """12x12 canvas with a solid 8x8 block from (2, 2) to (9, 9)."""
    return box(blank(12, 12), 2, 2, 8, 8)


def test_disk_offsets():
    assert inv.disk_offsets(0) == [(0, 0)]
    assert sorted(inv.disk_offsets(1)) == [(-1, 0), (0, -1), (0, 0), (0, 1), (1, 0)]
    assert len(inv.disk_offsets(2)) == 13 and (2, 2) not in inv.disk_offsets(2)
    assert len(inv.disk_offsets(3)) == 29 and (2, 2) in inv.disk_offsets(3)


# -- cause 1: open joint ---------------------------------------------------- #

def test_holes_open_joint_pass_disk_fully_covered():
    m = manifest([{"shin": (0, (6, 6))}], joints={"shin": 2})
    assert inv.check_holes([body()], m) == []


def test_holes_open_joint_fail_transparent_pixel_in_the_disk():
    frame = body()
    frame[6, 7] = 0                                         # 1 px right of the joint
    frame[4, 6] = 0                                         # 2 px above: on the rim, still inside
    m = manifest([{"shin": (0, (6, 6))}], joints={"shin": 2})
    violations = inv.check_holes([frame], m)
    assert [(v.check, v.frame, v.pixel) for v in violations] == [("holes", 0, (6, 4))]
    assert "open joint 'shin'" in violations[0].detail and "2 pixel(s)" in violations[0].detail
    assert inv.open_joint_pixels(frame, m, 0) == {"shin": [(6, 4), (7, 6)]}
    assert inv.hole_frames([frame], m) == [0]


def test_holes_open_joint_pass_transparent_pixel_just_outside_the_disk():
    frame = body()
    frame[8, 8] = 0                                         # (2, 2) from the joint: 8 > 2^2
    frame[6, 9] = 0                                         # 3 px away
    assert inv.check_holes([frame], manifest([{"shin": (0, (6, 6))}], joints={"shin": 2})) == []


def test_holes_open_joint_radius_zero_checks_the_joint_pixel_only():
    frame = body()
    frame[6, 7] = 0
    m = manifest([{"shin": (0, (6, 6))}], joints={"shin": 0})
    assert inv.check_holes([frame], m) == []
    frame[6, 6] = 0
    assert [v.pixel for v in inv.check_holes([frame], m)] == [(6, 6)]


def test_holes_open_joint_uses_the_frame_pose_and_the_origin():
    # sprite coordinates (26, 36) with origin (20, 30) = canvas (6, 6)
    still = {"shin": (0, (26, 36))}
    moved = {"shin": (-45, (31, 36))}                       # canvas (11, 6): on the edge of the block
    m = manifest([still, moved, still], origin=(20, 30), joints={"shin": 1})
    violations = inv.check_holes([body()] * 3, m)
    assert [(v.frame, v.pixel) for v in violations] == [(1, (11, 5))]
    assert "5 pixel(s)" in violations[0].detail             # the whole radius-1 disk is out of the block


def test_holes_open_joint_fail_disk_leaving_the_canvas():
    frame = box(blank(12, 12), 0, 2, 8, 8)
    m = manifest([{"arm": (0, (1, 6))}], joints={"arm": 2})
    violations = inv.check_holes([frame], m)
    assert len(violations) == 1 and violations[0].pixel == (-1, 6), "off-canvas pixel is reported as is"
    assert "1 pixel(s)" in violations[0].detail


def test_holes_several_bones_and_frames_are_reported_separately():
    frame = body()
    frame[3, 3] = 0
    frame[8, 8] = 0
    pose = {"a": (0, (3, 3)), "b": (0, (8, 8)), "c": (0, (6, 6))}
    m = manifest([pose, pose], joints={"a": 0, "b": 1, "c": 1})
    violations = inv.check_holes([frame, body()], m)
    assert [(v.frame, v.detail.split(":")[0]) for v in violations] == [
        (0, "open joint 'a'"), (0, "open joint 'b'")]


def test_holes_negative_space_between_limbs_is_not_a_hole():
    # A closed empty area, however big, is legitimate when no tracked joint sits there.
    frame = ring(12)
    assert inv.enclosed_mask(frame).sum() == 9
    m = manifest([{"shin": (0, (1, 1))}], joints={"shin": 0})
    assert inv.check_holes([frame], m) == []
    assert inv.check_holes([frame], manifest([{}])) == []


def test_holes_fail_tracked_bone_missing_from_the_pose_or_frame_count_mismatch():
    m = manifest([{}], joints={"shin": 1})
    assert "absent from the frame pose" in inv.check_holes([body()], m)[0].detail
    assert "lists 1 frame(s), got 2" in inv.check_holes([body(), body()], m)[0].detail


# -- cause 2: unfilled disocclusion ----------------------------------------- #

def torso(missing):
    return {"torso": {"bone": "spine", "z": 1, "fill": "none", "missing": [list(p) for p in missing]}}


def test_holes_missing_data_pass_when_still_covered_or_fill_is_own():
    covered = manifest([{"spine": (0, (5, 5))}], parts=torso([(5, 7)]), rest={"spine": (5, 5)})
    assert inv.check_holes([body()], covered) == []         # the arm is still in front of it
    frame = body()
    frame[7, 5] = 0
    filled = manifest([{"spine": (0, (5, 5))}], parts=torso([]), rest={"spine": (5, 5)})
    assert inv.check_holes([frame], filled) == [], "no 'missing' pixel = cause 2 cannot happen"


def test_holes_missing_data_fail_at_rest_position():
    frame = body()
    frame[7, 5] = 0                                         # the missing pixel is uncovered
    frame[7, 4] = 0                                         # its neighbour is not in 'missing'
    m = manifest([{"spine": (0, (5, 5))}], parts=torso([(5, 7)]), rest={"spine": (5, 5)})
    violations = inv.check_holes([frame], m)
    assert [(v.check, v.frame, v.pixel) for v in violations] == [("holes", 0, (5, 7))]
    assert "part 'torso' has no data under its front neighbour: 1 pixel(s)" in violations[0].detail
    assert inv.missing_data_pixels(frame, m, 0) == {"torso": [(5, 7)]}


def test_holes_missing_data_follows_a_translation_and_the_origin():
    frame = body()
    frame[7, 5] = 0
    frame[8, 8] = 0
    # sprite coords = canvas + (20, 30); the torso moved by (+3, +1)
    m = manifest([{"spine": (0, (28, 36))}], origin=(20, 30),
                 parts=torso([(25, 37)]), rest={"spine": (25, 35)})
    assert [v.pixel for v in inv.check_holes([frame], m)] == [(8, 8)], \
        "the uncovered rest position (5, 7) is no longer where the missing pixel is"


@pytest.mark.parametrize("angle, expected", [
    (90, (7, 5)),       # +90 anti-clockwise: 2 px under the joint goes 2 px in front of it
    (-90, (3, 5)),
    (180, (5, 3)),
    (0, (5, 7)),
])
def test_holes_missing_data_follows_a_quarter_turn(angle, expected):
    frame = body()
    for x, y in ((7, 5), (3, 5), (5, 3), (5, 7)):
        frame[y, x] = 0
    m = manifest([{"spine": (angle, (5, 5))}], parts=torso([(5, 7)]), rest={"spine": (5, 5)})
    assert [v.pixel for v in inv.check_holes([frame], m)] == [expected]


def test_holes_missing_data_follows_a_45_degree_turn():
    # rest offset (0, 4) turned by +45 lands at (+2.83, +2.83) -> canvas pixel (8, 8)
    frame = body()
    frame[8, 8] = 0
    frame[9, 5] = 0
    m = manifest([{"spine": (45, (5, 5))}], parts=torso([(5, 9)]), rest={"spine": (5, 5)})
    assert [v.pixel for v in inv.check_holes([frame], m)] == [(8, 8)]


# -- cause 3: dislocated joint (frames.json alone) --------------------------- #

def limb(pose_child, pose_parent=(0, (5, 3)), radius=None, origin=(0, 0)):
    """Parent 'arm' at rest (5, 3), child 'forearm' held 4 px under it at rest (5, 7)."""
    parts = {"arm": {"bone": "arm", "missing": []}, "forearm": {"bone": "forearm", "missing": []}}
    return manifest([{"arm": pose_parent, "forearm": pose_child}], origin=origin, parts=parts,
                    rest={"arm": (5, 3), "forearm": (5, 7)}, parents={"forearm": "arm"},
                    joints={} if radius is None else {"forearm": radius})


def test_holes_dislocation_pass_when_the_child_follows_its_parent():
    assert inv.check_holes([body()], limb((0, (5, 7)))) == []
    # parent turned by +90: 4 px under becomes 4 px in front (anti-clockwise on screen)
    m = limb((90, (9, 3)), pose_parent=(90, (5, 3)))
    assert inv.joint_gaps(m, 0) == {"forearm": 0.0}
    assert inv.check_holes([body()], m) == []


def test_holes_dislocation_fail_and_threshold():
    """gap > joints[B] + 2: an untracked bone tolerates 2 px, not 3."""
    assert inv.check_holes([body()], limb((0, (7, 7)))) == [], "2 px: rounding + a wanted 1 px shift"
    violations = inv.check_holes([body()], limb((0, (8, 7))))
    assert [(v.check, v.frame, v.pixel) for v in violations] == [("holes", 0, (8, 7))]
    assert "dislocated joint 'forearm' (3.00 px" in violations[0].detail
    assert inv.dislocated_joints(limb((0, (5, 4))), 0) == {"forearm": 3.0}, "vertical gap counts too"
    assert inv.dislocated_joints(limb((0, (7, 9))), 0) == {}, "Chebyshev: (2, 2) is a 2 px gap"


def test_holes_dislocation_threshold_grows_with_the_tracked_radius():
    assert inv.dislocated_joints(limb((0, (9, 7)), radius=2), 0) == {}
    assert inv.dislocated_joints(limb((0, (10, 7)), radius=2), 0) == {"forearm": 5.0}


def test_holes_dislocation_uses_the_parent_angle_and_reports_canvas_coordinates():
    # parent at +90 holds the child at (9, 3); the child was left at its rest place (5, 7)
    m = limb((0, (25, 37)), pose_parent=(90, (25, 33)), origin=(20, 30))
    violations = inv.check_holes([body()], m)
    assert [v.pixel for v in violations] == [(5, 7)]
    assert "4.00 px" in violations[0].detail


def test_holes_dislocation_ignores_roots_and_bones_without_part():
    m = limb((0, (11, 7)))
    del m["parts"]["forearm"]
    assert inv.check_holes([body()], m) == [], "a bone that carries no part is not checked"
    lone = manifest([{"hips": (0, (9, 9))}], rest={"hips": (5, 5)},
                    parts={"hips": {"bone": "hips", "missing": []}})
    assert inv.check_holes([body()], lone) == [], "a root has no parent to be held by"


def test_holes_both_causes_in_one_frame():
    frame = body()
    frame[7, 5] = 0
    frame[3, 8] = 0
    m = manifest([{"spine": (0, (5, 5)), "arm": (0, (8, 3))}], joints={"arm": 0},
                 parts=torso([(5, 7)]), rest={"spine": (5, 5)})
    details = [v.detail for v in inv.check_holes([frame], m)]
    assert len(details) == 2
    assert details[0].startswith("open joint 'arm'") and details[1].startswith("part 'torso'")


# --------------------------------------------------------------------------- #
# canvas
# --------------------------------------------------------------------------- #

def test_canvas_constant_pass():
    assert inv.check_canvas_constant([blank(8, 6), blank(8, 6)]) == []
    assert inv.check_canvas_constant([blank(8, 6)], expected_size=(8, 6)) == []


def test_canvas_constant_fail_one_frame_differs():
    violations = inv.check_canvas_constant([blank(8, 6), blank(8, 6), blank(9, 6)])
    assert [(v.check, v.frame) for v in violations] == [("canvas_constant", 2)]


def test_canvas_constant_fail_swapped_dimensions_and_expected_size():
    assert inv.check_canvas_constant([blank(8, 6), blank(6, 8)])
    assert len(inv.check_canvas_constant([blank(8, 6)] * 2, expected_size=(8, 8))) == 2


def test_canvas_constant_fail_without_frames():
    assert inv.check_canvas_constant([])


# --------------------------------------------------------------------------- #
# pivot
# --------------------------------------------------------------------------- #

def test_pivot_stable_pass():
    assert inv.check_pivot_stable([(16, 32)] * 4) == []
    assert inv.check_pivot_stable([(16, 32), [16, 32]], canvas_size=(32, 32)) == [], \
        "grid-corner coordinate: the bottom edge (y = height) is inside"


def test_pivot_stable_fail_jump():
    violations = inv.check_pivot_stable([(16, 32), (16, 32), (17, 32), (16, 31)])
    assert [(v.check, v.frame) for v in violations] == [("pivot_stable", 2), ("pivot_stable", 3)]


@pytest.mark.parametrize("pivot", [(16.0, 32), (16.5, 32), (16,), (True, 3), ("16", "32"), ()])
def test_pivot_stable_fail_not_a_pair_of_integers(pivot):
    violations = inv.check_pivot_stable([pivot, pivot])
    assert len(violations) == 2 and "not a pair of integers" in violations[0].detail


def test_pivot_stable_fail_outside_canvas_or_missing():
    assert inv.check_pivot_stable([(40, 32)] * 2, canvas_size=(32, 32))
    assert inv.check_pivot_stable([(16, -1)], canvas_size=(32, 32))
    assert inv.check_pivot_stable([])


# --------------------------------------------------------------------------- #
# ground line (docs/animation-guide.md D5 / D7)
# --------------------------------------------------------------------------- #

def standing(dy=0):
    """A block whose lowest row is 6 + dy: it stands on the grid line y = 7 + dy."""
    return box(blank(8, 12), 2, 1 + dy, 2, 6)


def test_ground_offsets():
    frames = [standing(), standing(1), standing(-1), standing(2), blank(8, 12)]
    assert inv.ground_offsets(frames, 7) == [0, 1, -1, 2, None]


def test_ground_line_pass_strict_and_with_tolerance():
    assert inv.check_ground_line([standing(), box(blank(8, 12), 4, 3, 3, 4)], 7) == []
    assert inv.check_ground_line([standing(), standing(1), standing(-1)], 7, tolerance=1) == []


def test_ground_line_fail_strict():
    violations = inv.check_ground_line([standing(), standing(1), standing(-1)], 7)
    assert [(v.check, v.frame) for v in violations] == [("ground_line", 1), ("ground_line", 2)]
    assert "1 px below the ground line y=7" in violations[0].detail
    assert "1 px above the ground line y=7" in violations[1].detail


def test_ground_line_fail_beyond_the_tolerance():
    violations = inv.check_ground_line([standing(1), standing(2), standing(-2)], 7, tolerance=1)
    assert [v.frame for v in violations] == [1, 2]
    assert "2 px below" in violations[0].detail and "tolerance 1 px" in violations[0].detail


def test_ground_line_one_tolerance_per_frame():
    frames = [standing(1), standing(1)]
    assert [v.frame for v in inv.check_ground_line(frames, 7, tolerance=[1, 0])] == [1]
    with pytest.raises(ValueError):
        inv.check_ground_line(frames, 7, tolerance=[1])


def test_ground_line_fail_empty_frame():
    assert inv.check_ground_line([standing(), blank(8, 12)], 7, tolerance=1)


# --------------------------------------------------------------------------- #
# loop
# --------------------------------------------------------------------------- #

def _sweep(positions, width=16):
    """A 2x2 block at each x position: a tiny 'animation'."""
    return [box(blank(width, 8), x, 3, 2, 2) for x in positions]


def test_frame_distance():
    a, b = _sweep([2, 3])
    assert inv.frame_distance(a, a) == 0
    assert inv.frame_distance(a, b) == 4            # 2 px vacated + 2 px newly covered
    assert inv.frame_distance(put(blank(), 0, 0, RED, 0), put(blank(), 0, 0, GREEN, 0)) == 0
    with pytest.raises(ValueError):
        inv.frame_distance(blank(8, 8), blank(9, 8))


def test_loop_closed_pass_ping_pong_cycle():
    # 2 -> 3 -> 4 -> 3 -> (2): the wrap is the same 1 px step as the others.
    assert inv.check_loop_closed(_sweep([2, 3, 4, 3])) == []


def test_loop_closed_pass_with_held_frames():
    assert inv.check_loop_closed(_sweep([2, 2, 3, 3, 4, 4, 3, 3])) == []


def test_loop_closed_fail_jump_back_to_start():
    # Moves right 1 px per frame then teleports back 4 px: visible pop.
    violations = inv.check_loop_closed(_sweep([2, 3, 4, 5, 6]))
    assert [(v.check, v.frame) for v in violations] == [("loop_closed", 4)]
    assert "wrap step changes 8 px" in violations[0].detail


def test_loop_closed_fail_last_frame_is_a_copy_of_the_first():
    violations = inv.check_loop_closed(_sweep([2, 3, 4, 3, 2]))
    assert [(v.check, v.frame) for v in violations] == [("loop_closed", 4)]
    assert "copy of the first" in violations[0].detail
    assert inv.check_loop_closed(_sweep([2, 2])), "two identical frames: the wrap step is zero"


def _lit(count):
    """A 16x8 frame with its first ``count`` pixels opaque: distance = difference of counts."""
    frame = blank(16, 8)
    frame.reshape(-1, 4)[:count] = (*RED, 255)
    return frame


def test_loop_closed_ten_percent_margin():
    assert inv.LOOP_TOLERANCE == 1.10
    # in-loop steps: 20 px then 2 px; wrap 22 px = exactly 20 + 10 %
    assert inv.check_loop_closed([_lit(0), _lit(20), _lit(22)]) == []
    violations = inv.check_loop_closed([_lit(0), _lit(20), _lit(23)])
    assert len(violations) == 1 and "23 px" in violations[0].detail
    assert inv.check_loop_closed([_lit(0), _lit(20), _lit(23)], tolerance=1.5) == []
    assert inv.check_loop_closed([_lit(0), _lit(20), _lit(21)], tolerance=1.0)


def test_loop_closed_trivial_and_degenerate_inputs():
    assert inv.check_loop_closed(_sweep([2])) == [], "a single frame always passes"
    assert inv.check_loop_closed(_sweep([2, 9])) == []
    assert inv.check_loop_closed([])
    assert inv.check_loop_closed([blank(8, 8), blank(8, 8), blank(9, 8)])


# --------------------------------------------------------------------------- #
# parts assignment
# --------------------------------------------------------------------------- #

def _rig(parts: dict) -> dict:
    return {"parts": {
        name: {"bone": name, "z": 0, "overlap": 0,
               "region": {"rects": region.get("rects", []), "pixels": region.get("pixels", [])}}
        for name, region in parts.items()}}


def _two_part_sprite():
    sprite = box(blank(), 2, 1, 3, 3, RED)      # "head"
    return box(sprite, 2, 4, 3, 3, GREEN)       # "body"


def test_rasterize_rig_rects_pixels_and_order():
    rig = _rig({"head": {"rects": [[2, 1, 3, 3]]}, "body": {"rects": [[2, 4, 3, 3]], "pixels": [[5, 5]]}})
    raster = inv.rasterize_rig(rig, (8, 8))
    assert raster.parts == ("head", "body")
    assert raster.labels[1, 2] == 1 and raster.labels[4, 2] == 2 and raster.labels[5, 5] == 2
    assert raster.labels[0, 0] == 0
    assert raster.duplicates == () and raster.out_of_bounds == ()


def test_rasterize_rig_last_part_wins_and_duplicates_are_recorded():
    rig = _rig({"head": {"rects": [[2, 1, 3, 4]]}, "body": {"rects": [[2, 4, 3, 3]]}})
    raster = inv.rasterize_rig(rig, (8, 8))
    assert raster.labels[4, 2] == 2
    assert sorted(raster.duplicates) == [(2, 4, "head", "body"), (3, 4, "head", "body"),
                                         (4, 4, "head", "body")]


def test_rasterize_rig_records_out_of_bounds():
    raster = inv.rasterize_rig(_rig({"a": {"rects": [[6, 6, 4, 4]], "pixels": [[9, 0]]}}), (8, 8))
    assert raster.out_of_bounds == (("a", (6, 6, 4, 4)), ("a", (9, 0)))
    assert int((raster.labels == 1).sum()) == 4


def test_all_pixels_assigned_pass():
    sprite = _two_part_sprite()
    rig = _rig({"head": {"rects": [[2, 1, 3, 3]]}, "body": {"rects": [[2, 4, 3, 3]]}})
    assert inv.check_rig_covers_sprite(sprite, rig) == []
    labels = inv.rasterize_rig(rig, (8, 8)).labels
    assert inv.check_all_pixels_assigned(sprite, labels) == []


def test_all_pixels_assigned_pass_region_larger_than_the_opaque_area():
    rig = _rig({"all": {"rects": [[0, 0, 8, 8]]}})
    assert inv.check_rig_covers_sprite(_two_part_sprite(), rig) == []


def test_all_pixels_assigned_fail_lost_pixel():
    rig = _rig({"head": {"rects": [[2, 1, 3, 3]]}, "body": {"rects": [[2, 4, 3, 2]]}})
    violations = inv.check_rig_covers_sprite(_two_part_sprite(), rig)
    assert [v.pixel for v in violations] == [(2, 6), (3, 6), (4, 6)]
    assert {v.check for v in violations} == {"parts_assigned"}


def test_all_pixels_assigned_fail_duplicated_pixel():
    rig = _rig({"head": {"rects": [[2, 1, 3, 4]]}, "body": {"rects": [[2, 4, 3, 3]]}})
    violations = inv.check_rig_covers_sprite(_two_part_sprite(), rig)
    assert len(violations) == 3 and all("claimed by 'head' then 'body'" in v.detail for v in violations)
    assert inv.check_rig_covers_sprite(_two_part_sprite(), rig, allow_duplicates=True) == []


def test_all_pixels_assigned_fail_empty_part_and_off_canvas_region():
    rig = _rig({"all": {"rects": [[0, 0, 8, 8]]}, "ghost": {}, "far": {"rects": [[7, 7, 3, 3]]}})
    details = [v.detail for v in inv.check_rig_covers_sprite(_two_part_sprite(), rig,
                                                             allow_duplicates=True)]
    assert any("'ghost' owns no pixel" in d for d in details)
    assert any("'far'" in d and "leaves the canvas" in d for d in details)


def test_all_pixels_assigned_fail_label_map_size_mismatch():
    assert inv.check_all_pixels_assigned(blank(8, 8), np.zeros((4, 4), int))


# --------------------------------------------------------------------------- #
# aggregate + reporting
# --------------------------------------------------------------------------- #

def test_check_frames_pass_on_clean_loop():
    frames = [box(blank(16, 8), x, 2, 3, 5, RED) for x in (4, 5, 6, 5)]
    assert inv.check_frames(frames, [RED], loop=True) == []
    m = manifest([{"hips": (0, (x + 1, 4))} for x in (4, 5, 6, 5)], canvas=(16, 8),
                 joints={"hips": 1}, pivots=[(8, 7)] * 4)
    assert inv.check_frames(frames, [RED], manifest=m, loop=True) == []


def test_check_frames_collects_every_kind_of_violation():
    good = box(blank(16, 8), 4, 2, 3, 5, RED)
    bad = box(blank(16, 9), 4, 2, 5, 5, RED)        # other canvas
    bad[4, 6] = 0                                   # open joint
    put(bad, 12, 0, GREEN, alpha=200)               # orphan, new colour, soft alpha
    m = manifest([{"hips": (0, (5, 4))}, {"hips": (0, (6, 4))}], canvas=(16, 8),
                 joints={"hips": 0}, pivots=[(8, 7), (9, 7)])
    found = {v.check for v in inv.check_frames([good, bad], [RED], manifest=m)}
    assert found == {"canvas_constant", "alpha_binary", "palette", "orphans", "holes", "pivot_stable"}


def test_check_frames_without_manifest_skips_holes_and_pivot():
    frame = ring(12)
    assert inv.check_frames([frame], [RED]) == []
    m = manifest([{"hips": (0, (3, 3))}], joints={"hips": 0})
    assert {v.check for v in inv.check_frames([frame], [RED], manifest=m)} == {"holes"}


def test_check_frames_canvas_must_be_the_declared_one():
    frames = [blank(16, 8), blank(16, 8)]
    m = manifest([{}, {}], canvas=(16, 9), pivots=[(8, 7)] * 2)
    assert {v.check for v in inv.check_frames(frames, [RED], manifest=m)} == {"canvas_constant"}


def test_check_frames_loop_check_is_opt_in():
    frames = [box(blank(16, 8), x, 2, 2, 2, RED) for x in (2, 3, 4, 5, 6)]
    assert inv.check_frames(frames, [RED]) == []
    assert {v.check for v in inv.check_frames(frames, [RED], loop=True)} == {"loop_closed"}


def test_silhouette_border_and_bare_border_count():
    frame = box(blank(8, 8), 1, 1, 5, 5, BLACK)
    frame[2:5, 2:5, :3] = RED                               # red inside, black rim
    border = inv.silhouette_border(frame)
    assert int(border.sum()) == 16 and not border[3, 3]
    assert inv.bare_border_count(frame, BLACK) == 0
    put(frame, 1, 3, RED)                                   # a gap in the rim
    assert inv.bare_border_count(frame, BLACK) == 1
    edge = box(blank(4, 4), 0, 0, 4, 4, RED)                # glued to the canvas: its edge is border
    assert int(inv.silhouette_border(edge).sum()) == 12
    assert inv.hex_to_rgb("#140c1c") == (20, 12, 28)


def test_assert_no_violations_message():
    inv.assert_no_violations([])
    violation = inv.Violation("holes", "open joint 'shin_r': 1 pixel(s)", 3, (4, 5))
    with pytest.raises(AssertionError) as error:
        inv.assert_no_violations([violation], "walk")
    message = str(error.value)
    assert "1 invariant violation(s) in walk" in message
    assert "[holes]" in message and "frame 3" in message and "pixel (4, 5)" in message


def test_violation_ids_are_report_check_ids():
    assert set(inv.CHECK_IDS) == {"palette", "alpha_binary", "orphans", "holes", "pivot_stable",
                                  "canvas_constant", "loop_closed", "parts_assigned"}
