"""Integration: invalid inputs give clean errors.

"Clean" = return code 1, exactly one JSON object on stdout with ok=false and a
readable ``error`` string, no Python traceback (docs/schemas.md, CLAUDE.md).
Needs the lead dev's implementation.
"""
from __future__ import annotations

import json

import pytest

from tests import cli_adapter as cli, contract

pytestmark = pytest.mark.integration


def load_rig(project) -> dict:
    return json.loads((project / "rig.json").read_text(encoding="utf-8"))


def save_rig(project, rig) -> None:
    (project / "rig.json").write_text(json.dumps(rig), encoding="utf-8")


def set_path(document, path, value):
    target = document
    for key in path[:-1]:
        target = target[key]
    if value == "<del>":
        del target[path[-1]]
    else:
        target[path[-1]] = value


# --------------------------------------------------------------------------- #
# missing / unreadable files
# --------------------------------------------------------------------------- #

def test_prepare_missing_sprite(tmp_path):
    result = cli.prepare(tmp_path / "nope.png", tmp_path / "out", tmp_path).expect_user_error()
    assert "nope.png" in result.payload["error"], "the error should name the missing file"


def test_inspect_missing_sprite(tmp_path):
    cli.inspect(tmp_path / "nope.png", tmp_path / "out", tmp_path).expect_user_error()


def test_rig_missing_sprite(project, tmp_path):
    cli.rig(tmp_path / "nope.png", project / "rig.json", tmp_path / "out", tmp_path).expect_user_error()


def test_rig_missing_rig_file(project, tmp_path):
    result = cli.rig(project / "sprite.png", tmp_path / "nope.json", tmp_path / "out", tmp_path)
    result.expect_user_error()
    assert "nope.json" in result.payload["error"]


def test_animate_missing_rig_file(tmp_path):
    cli.animate(tmp_path / "nope.json", tmp_path / "out", tmp_path,
                preset="walk", frames=8, fps=10).expect_user_error()


def test_animate_rig_pointing_to_a_missing_sprite(project, tmp_path):
    (project / "sprite.png").unlink()
    cli.animate(project / "rig.json", tmp_path / "out", tmp_path,
                preset="walk", frames=8, fps=10).expect_user_error()


def test_animate_missing_keyframes_file(project, tmp_path):
    cli.animate(project / "rig.json", tmp_path / "out", tmp_path,
                keyframes=tmp_path / "nope.json").expect_user_error()


def test_validate_missing_frames(tmp_path):
    cli.validate(tmp_path / "no_frames", tmp_path).expect_user_error()


def test_validate_empty_frames_directory(tmp_path):
    (tmp_path / "empty").mkdir()
    cli.validate(tmp_path / "empty", tmp_path).expect_user_error()


def test_export_missing_frames(tmp_path):
    cli.export(tmp_path / "no_frames", tmp_path / "out", tmp_path).expect_user_error()


@pytest.mark.parametrize("command", ["prepare", "inspect"])
def test_sprite_that_is_not_an_image(command, tmp_path):
    fake = tmp_path / "fake.png"
    fake.write_text("this is not a PNG", encoding="utf-8")
    cli.run([command, fake], tmp_path, tmp_path / "out").expect_user_error()


# --------------------------------------------------------------------------- #
# malformed rig.json
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("content", ["", "{", '{"version": 1,}', "[]", "null", '"rig"'],
                         ids=["empty", "truncated", "trailing-comma", "array", "null", "string"])
@pytest.mark.parametrize("command", ["rig", "animate"])
def test_rig_that_is_not_a_json_object(command, content, project, tmp_path):
    (project / "rig.json").write_text(content, encoding="utf-8")
    if command == "rig":
        result = cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "out", tmp_path)
    else:
        result = cli.animate(project / "rig.json", tmp_path / "out", tmp_path,
                             preset="walk", frames=8, fps=10)
    result.expect_user_error()


MALFORMED_RIGS = [
    ("no-bones", ["bones"], "<del>"),
    ("no-parts", ["parts"], "<del>"),
    ("bones-not-object", ["bones"], []),
    ("no-hips", ["bones", "hips"], "<del>"),                  # hips is the only mandatory bone
    ("joint-missing", ["bones", "head", "joint"], "<del>"),
    ("joint-not-a-pair", ["bones", "head", "joint"], [32]),
    ("joint-sub-pixel", ["bones", "head", "joint"], [32.5, 20]),
    ("joint-strings", ["bones", "head", "joint"], ["a", "b"]),
    ("part-without-bone", ["parts", "head", "bone"], "<del>"),
    ("part-without-region", ["parts", "head", "region"], "<del>"),
    ("rect-three-values", ["parts", "head", "region", "rects"], [[1, 2, 3]]),
    ("rect-negative-size", ["parts", "head", "region", "rects"], [[10, 10, -4, 4]]),
    ("rect-sub-pixel", ["parts", "head", "region", "rects"], [[10.5, 10, 4, 4]]),
    ("pixels-not-pairs", ["parts", "head", "region", "pixels"], [[1, 2, 3]]),
    ("z-not-integer", ["parts", "head", "z"], "front"),
    ("pivot-not-a-pair", ["pivot"], [0.5]),
]


@pytest.mark.parametrize("path, value", [(p, v) for _, p, v in MALFORMED_RIGS],
                         ids=[i for i, _, _ in MALFORMED_RIGS])
def test_malformed_rig_is_rejected_by_rig_command(path, value, project, tmp_path):
    rig = load_rig(project)
    set_path(rig, path, value)
    assert contract.validate_rig(rig), "test bug: this rig is supposed to be invalid"
    save_rig(project, rig)
    result = cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "out", tmp_path)
    result.expect_user_error()
    assert len(result.payload["error"]) >= 10, "the error must say what is wrong"


@pytest.mark.parametrize("path, value", [(p, v) for _, p, v in MALFORMED_RIGS[:6]],
                         ids=[i for i, _, _ in MALFORMED_RIGS[:6]])
def test_malformed_rig_is_rejected_by_animate_too(path, value, project, tmp_path):
    rig = load_rig(project)
    set_path(rig, path, value)
    save_rig(project, rig)
    cli.animate(project / "rig.json", tmp_path / "out", tmp_path,
                preset="walk", frames=8, fps=10).expect_user_error()


# --------------------------------------------------------------------------- #
# unknown bones
# --------------------------------------------------------------------------- #

UNKNOWN_BONE_RIGS = [
    ("part-on-unknown-bone", ["parts", "head", "bone"], "skull"),
    ("unknown-parent", ["bones", "head", "parent"], "neck"),
    ("ik-chain-unknown-bone", ["ik", "foot_r", "chain"], ["thigh_r", "knee_r"]),
    ("ik-unknown-target", ["ik", "foot_r", "target_bone"], "toe_r"),
]


@pytest.mark.parametrize("path, value", [(p, v) for _, p, v in UNKNOWN_BONE_RIGS],
                         ids=[i for i, _, _ in UNKNOWN_BONE_RIGS])
@pytest.mark.parametrize("command", ["rig", "animate"])
def test_rig_referencing_an_unknown_bone(command, path, value, project, tmp_path):
    rig = load_rig(project)
    set_path(rig, path, value)
    save_rig(project, rig)
    if command == "rig":
        result = cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "out", tmp_path)
    else:
        result = cli.animate(project / "rig.json", tmp_path / "out", tmp_path,
                             preset="walk", frames=8, fps=10)
    result.expect_user_error()
    unknown = value if isinstance(value, str) else value[-1]
    assert unknown in result.payload["error"], f"the error should name the unknown bone '{unknown}'"


def test_rig_with_a_parent_cycle(project, tmp_path):
    rig = load_rig(project)
    rig["bones"]["spine"]["parent"] = "head"           # spine -> head -> spine
    save_rig(project, rig)
    cli.rig(project / "sprite.png", project / "rig.json", tmp_path / "out", tmp_path).expect_user_error()


# --------------------------------------------------------------------------- #
# animate arguments
# --------------------------------------------------------------------------- #

def test_animate_unknown_preset(project, tmp_path):
    result = cli.animate(project / "rig.json", tmp_path / "out", tmp_path,
                         preset="moonwalk", frames=8, fps=10).expect_user_error()
    assert "moonwalk" in result.payload["error"]


def test_animate_without_preset_nor_keyframes(project, tmp_path):
    cli.animate(project / "rig.json", tmp_path / "out", tmp_path, frames=8, fps=10).expect_user_error()


@pytest.mark.parametrize("content", ["{", "[]", '{"version": 1, "name": "x", "loop": false, "fps": 10}',
                                     '{"version": 1, "name": "x", "loop": false, "fps": 10, "frames": []}',
                                     '{"version": 1, "name": "x", "loop": false, "fps": 10, '
                                     '"frames": [{"duration_ms": 0}]}',
                                     '{"version": 1, "name": "x", "loop": false, "fps": 10, '
                                     '"frames": [{"duration_ms": 100, "bones": {"hips": {"pos": [0.5, 0]}}}]}'],
                         ids=["truncated", "array", "no-frames-key", "zero-frames", "zero-duration",
                              "sub-pixel-pos"])
def test_animate_malformed_keyframes(content, project, tmp_path):
    anim = tmp_path / "anim.json"
    anim.write_text(content, encoding="utf-8")
    cli.animate(project / "rig.json", tmp_path / "out", tmp_path, keyframes=anim).expect_user_error()


# --------------------------------------------------------------------------- #
# export / unknown command
# --------------------------------------------------------------------------- #

def test_export_unknown_format(project, tmp_path):
    frames = cli.animate(project / "rig.json", tmp_path / "frames", tmp_path,
                         preset="walk", frames=8, fps=10).expect_ok()
    result = cli.export(frames.frames_dir(), tmp_path / "export", tmp_path, fmt="betamax")
    result.expect_user_error()
    assert "betamax" in result.payload["error"]


def test_unknown_command_is_a_clean_user_error(tmp_path):
    cli.run(["teleport"], tmp_path).expect_user_error()


def test_missing_positional_argument_is_a_clean_user_error(tmp_path):
    cli.run(["prepare"], tmp_path).expect_user_error()
