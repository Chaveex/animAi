"""Integration: resampling with key-pose markers (docs/schemas.md, "Reechantillonnage").

The presets carry ``key`` / ``label`` per frame. Expected source frames are derived here
from the preset files with an independent implementation of the documented rule, then
compared with ``frames[].source_frame`` of the tool.
"""
from __future__ import annotations

import numpy as np
import pytest

from tests import cli_adapter as cli, invariants as inv
from tests.conftest import preset_document, write_anim

pytestmark = pytest.mark.integration


def priority(frame) -> float:
    key = frame.get("key", False)
    return 1 if key is True else (0 if key is False else key)


def expected_reduction(anim: dict, count: int) -> tuple[list[int], list[int]]:
    """(kept source frames, key poses that did not fit) for N < number of source frames.

    1. key poses first: highest priority, then longest duration, then order;
    2. remaining places, one by one, to the frame whose start is the farthest in time from
       every kept frame (circular distance for a loop; tie: the first; nothing kept: frame 0).
    """
    frames = anim["frames"]
    tick = 1000 / anim.get("fps", 10)
    durations = [f.get("duration_ms", tick) for f in frames]
    starts = [sum(durations[:i]) for i in range(len(frames))]
    total = sum(durations)
    keys = sorted((i for i, f in enumerate(frames) if priority(f) > 0),
                  key=lambda i: (-priority(frames[i]), -durations[i], i))
    kept, dropped = keys[:count], sorted(keys[count:])

    def distance(a, b):
        gap = abs(starts[a] - starts[b])
        return min(gap, total - gap) if anim.get("loop", True) else gap

    while len(kept) < count:
        rest = [i for i in range(len(frames)) if i not in kept]
        if not kept:
            kept.append(0)
            continue
        kept.append(max(rest, key=lambda i: (min(distance(i, k) for k in kept), -i)))
    return sorted(kept), dropped


def animate(project, tmp_path, name, **options):
    return cli.animate(project / "rig.json", tmp_path / name, tmp_path, **options).expect_ok()


def sources(result) -> list[int]:
    return [frame["source_frame"] for frame in result.manifest()["frames"]]


def has(warnings, needle) -> bool:
    return any(needle in warning for warning in warnings)


def test_presets_carry_the_documented_markers():
    walk, attack = preset_document("walk"), preset_document("attack")
    assert [f["label"] for f in walk["frames"]] == [
        "contact_r", "down_r", "passing_r", "up_r", "contact_l", "down_l", "passing_l", "up_l"]
    contacts = [priority(f) for f in walk["frames"] if f["label"].startswith("contact")]
    passings = [priority(f) for f in walk["frames"] if f["label"].startswith("passing")]
    assert min(contacts) > max(passings) > 0, "contacts outrank passings"
    keyed = {f["label"] for f in attack["frames"] if priority(f) > 0}
    assert keyed == {"anticipation", "strike", "impact", "rest"}


@pytest.mark.parametrize("preset, count, kept", [
    ("walk", 4, [0, 2, 4, 6]),             # contacts and passings
    ("walk", 6, [0, 1, 2, 4, 5, 6]),       # + the two downs: every key pose fits
    ("attack", 5, [1, 2, 3, 4, 6]),        # the four key poses + the farthest other frame
    ("attack", 4, [1, 2, 3, 6]),           # exactly the four key poses
    ("attack", 3, [1, 2, 3]),              # 'rest' (lowest priority) does not fit
    ("idle", 2, [0, 2]),
])
def test_fewer_frames_keeps_the_key_poses(preset, count, kept, project, tmp_path):
    document = preset_document(preset)
    expected, dropped_keys = expected_reduction(document, count)
    assert expected == kept, "test premise: the documented rule gives this selection"
    result = animate(project, tmp_path, "out", preset=preset, frames=count)
    assert sources(result) == kept
    manifest = result.manifest()
    assert [f.get("label") for f in manifest["frames"]] == [document["frames"][i]["label"] for i in kept]
    lost = [i for i in range(len(document["frames"])) if i not in kept]
    assert has(result.warnings, f"resampling to {count} frames drops source frames {lost}")
    if dropped_keys:
        names = ", ".join(f"{i} ({document['frames'][i]['label']})" for i in dropped_keys)
        assert has(result.warnings, f"only {count} frames: key poses dropped: {names}"), result.warnings
    else:
        assert not has(result.warnings, "key poses dropped"), result.warnings
    durations = [f["duration_ms"] for f in manifest["frames"]]
    assert max(durations) - min(durations) <= 1 and sum(durations) == manifest["duration_ms"]


def test_strike_frame_of_the_attack_survives_every_reduction(project, tmp_path):
    for count in (6, 5, 4, 3, 2):
        result = animate(project, tmp_path, f"a{count}", preset="attack", frames=count)
        labels = [f.get("label") for f in result.manifest()["frames"]]
        assert "strike" in labels and "anticipation" in labels, f"--frames {count}: {labels}"


def test_walk_12_frames_spreads_the_doubled_frames_over_the_cycle(project, tmp_path):
    result = animate(project, tmp_path, "w12", preset="walk", frames=12)
    assert sources(result) == [0, 0, 1, 2, 2, 3, 4, 4, 5, 6, 6, 7], "doubles 0, 4, 2 and 6, not the first four"
    assert has(result.warnings, "resampling to 12 equal frames changes the holds")
    assert has(result.warnings, "12 frames: more than 8")
    assert not has(result.warnings, "drops source frames")


def test_output_frames_are_copies_of_source_frames_never_new_poses(project, tmp_path):
    full = animate(project, tmp_path, "full", preset="walk")
    reference = [inv.crop_to_content(f) for f in full.frames()]
    for count in (4, 6, 12):
        result = animate(project, tmp_path, f"n{count}", preset="walk", frames=count)
        for frame, source in zip(result.frames(), sources(result)):
            assert np.array_equal(inv.crop_to_content(frame), reference[source]), \
                f"--frames {count}: a frame is not the copy of source frame {source}"


def test_identity_resampling_warns_about_nothing(project, tmp_path):
    result = animate(project, tmp_path, "same", preset="walk", frames=8)
    assert sources(result) == list(range(8))
    assert not has(result.warnings, "resampling"), result.warnings
    assert not has(result.warnings, "key poses"), result.warnings


def test_flattened_holds_are_reported(project, tmp_path):
    """idle is 600/100/600/100 ms: an equal grid cannot keep those proportions."""
    eight = animate(project, tmp_path, "i8", preset="idle", frames=8)
    assert sources(eight) == [0, 0, 0, 1, 2, 2, 2, 3]
    assert has(eight.warnings, "resampling to 8 equal frames changes the holds of source frames [0, 1, 2, 3]")
    assert has(eight.warnings, "[600, 100, 600, 100] ms would be proportional")
    by_fps = animate(project, tmp_path, "fps", preset="idle", fps=5)        # --fps alone
    assert has(by_fps.warnings, "equal frames changes the holds")
    fourteen = animate(project, tmp_path, "i14", preset="idle", frames=14)  # 6+1+6+1: exact
    assert sources(fourteen) == [0] * 6 + [1] + [2] * 6 + [3]
    assert not has(fourteen.warnings, "changes the holds"), fourteen.warnings


def poses(count):
    """`count` distinguishable poses without any marker."""
    return [{"duration_ms": 100, "bones": {"arm_r": {"rot": 15 * i}}} for i in range(count)]


def test_animation_without_marker_loop_keeps_evenly_spread_frames(project, tmp_path):
    anim = write_anim(tmp_path / "loop.json", poses(8), loop=True)
    result = animate(project, tmp_path, "loop", keyframes=anim, frames=4)
    assert sources(result) == [0, 2, 4, 6] == expected_reduction({"frames": poses(8), "loop": True}, 4)[0]
    assert not has(result.warnings, "key poses dropped")
    assert has(result.warnings, "drops source frames [1, 3, 5, 7]")


def test_animation_without_marker_non_loop_keeps_first_and_last(project, tmp_path):
    anim = write_anim(tmp_path / "once.json", poses(8), loop=False)
    for count in (2, 3, 4):
        result = animate(project, tmp_path, f"once{count}", keyframes=anim, frames=count)
        kept = sources(result)
        assert kept[0] == 0 and kept[-1] == 7, f"--frames {count}: kept {kept}"
        assert kept == expected_reduction({"frames": poses(8), "loop": False}, count)[0]


def test_custom_markers_priorities_and_booleans(project, tmp_path):
    frames = poses(6)
    frames[1].update(key=True, label="a")          # priority 1
    frames[4].update(key=5, label="b")
    frames[5].update(key=False, label="c")         # not a key pose
    anim = write_anim(tmp_path / "keys.json", frames, loop=False)
    one = animate(project, tmp_path, "one", keyframes=anim, frames=1)
    assert sources(one) == [4]
    assert has(one.warnings, "only 1 frames: key poses dropped: 1 (a)")
    two = animate(project, tmp_path, "two", keyframes=anim, frames=2)
    assert sources(two) == [1, 4] and not has(two.warnings, "key poses dropped")
    assert [f.get("label") for f in two.manifest()["frames"]] == ["a", "b"]


@pytest.mark.parametrize("key", [-1, "yes", [1]])
def test_invalid_key_marker_is_a_user_error(key, project, tmp_path):
    frames = poses(3)
    frames[1]["key"] = key
    anim = write_anim(tmp_path / "bad.json", frames)
    cli.animate(project / "rig.json", tmp_path / "out", tmp_path, keyframes=anim).expect_user_error()
