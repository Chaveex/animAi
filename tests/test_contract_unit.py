"""Unit tests of the schema validators and of the CLI adapter's pure helpers.

Pass today: nothing here needs the real CLI.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest
from PIL import Image

from tests import cli_adapter, contract

SCHEMA_RIG = {  # the example of docs/schemas.md, completed so that ik bones exist
    "version": 1, "sprite": "sprite.png", "view": "side", "template": "humanoid",
    "pivot": [0.5, 1.0],
    "bones": {
        "hips": {"parent": None, "joint": [32, 40]},
        "spine": {"parent": "hips", "joint": [32, 36]},
        "head": {"parent": "spine", "joint": [32, 20]},
        "arm_r": {"parent": "spine", "joint": [38, 24]},
        "thigh_r": {"parent": "hips", "joint": [35, 42]},
        "shin_r": {"parent": "thigh_r", "joint": [35, 50]},
        "foot_r": {"parent": "shin_r", "joint": [35, 58]},
    },
    "parts": {
        "torso": {"bone": "spine", "z": 0,
                  "region": {"rects": [[26, 22, 12, 18]], "pixels": []}, "overlap": 2},
        "arm_r": {"bone": "arm_r", "z": 1,
                  "region": {"rects": [[38, 24, 6, 14]], "pixels": []}, "overlap": 1},
    },
    "ik": {"foot_r": {"chain": ["thigh_r", "shin_r"], "target_bone": "foot_r"}},
}
SCHEMA_ANIM = {
    "version": 1, "name": "walk", "loop": True, "fps": 10,
    "frames": [{"duration_ms": 100,
                "bones": {"thigh_r": {"rot": 20, "pos": [0, 0]}, "hips": {"pos": [0, -1]}},
                "z": {"arm_l": -1}}],
}
SCHEMA_REPORT = {"ok": True, "checks": [
    {"id": cid, "pass": True, "detail": "", "frame": None, "pixel": None}
    for cid in contract.CHECK_IDS]}


def mutated(document, path, value):
    """Deep copy with document[path[0]][path[1]]... = value ('<del>' removes the key)."""
    result = copy.deepcopy(document)
    target = result
    for key in path[:-1]:
        target = target[key]
    if value == "<del>":
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return result


# --------------------------------------------------------------------------- #
# CLI payload
# --------------------------------------------------------------------------- #

def test_cli_payload_valid_success_and_failure():
    assert contract.validate_cli_payload(
        {"ok": True, "outputs": {"sprite": "a.png"}, "warnings": ["w"], "error": None}) == []
    assert contract.validate_cli_payload(
        {"ok": False, "outputs": {}, "warnings": [], "error": "file not found: x.png"}) == []


@pytest.mark.parametrize("payload", [
    [], "ok", None,
    {"ok": False, "error": "'prepare' not implemented"},                      # today's stub
    {"ok": "true", "outputs": {}, "warnings": [], "error": None},
    {"ok": True, "outputs": [], "warnings": [], "error": None},
    {"ok": True, "outputs": {}, "warnings": "none", "error": None},
    {"ok": True, "outputs": {}, "warnings": [1], "error": None},
    {"ok": True, "outputs": {}, "warnings": [], "error": 3},
    {"ok": True, "outputs": {}, "warnings": [], "error": "but it says ok"},
    {"ok": False, "outputs": {}, "warnings": [], "error": None},
    {"ok": False, "outputs": {}, "warnings": [], "error": ""},
])
def test_cli_payload_invalid(payload):
    assert contract.validate_cli_payload(payload)


# --------------------------------------------------------------------------- #
# rig.json
# --------------------------------------------------------------------------- #

def test_rig_schema_example_is_valid():
    assert contract.validate_rig(SCHEMA_RIG) == []


def test_rig_ik_is_optional():
    assert contract.validate_rig(mutated(SCHEMA_RIG, ["ik"], "<del>")) == []


def test_rig_optional_fields_of_wave_2_are_accepted():
    rig = mutated(SCHEMA_RIG, ["parts", "torso"], {
        "bone": "spine", "fill": "none", "fill_color": "#2864c8",
        "region": {"polygons": [[[26, 22], [38, 22], [32, 40]]],
                   "exclude": {"rects": [[30, 30, 2, 2]], "pixels": [[27, 23]]}}})
    rig["ik"]["foot_r"]["bend"] = 1
    rig["pivot"] = [0.5, 1.0]
    assert contract.validate_rig(rig) == []
    for fill in ("own", "copy", True, False):
        assert contract.validate_rig(mutated(SCHEMA_RIG, ["parts", "torso", "fill"], fill)) == []
    assert contract.validate_rig(mutated(SCHEMA_RIG, ["pivot"], "<del>")) == []
    for outline in ("auto", "none", False, "#140c1c"):
        assert contract.validate_rig(mutated(SCHEMA_RIG, ["outline"], outline)) == []
    assert contract.validate_rig(mutated(SCHEMA_RIG, ["outline_mode"], "inside")) == []


def test_rig_canonical_parent_absent_from_the_rig_is_not_an_error():
    # no forearm_r in the rig: hand_r is re-attached to arm_r by the tool (warning)
    rig = mutated(SCHEMA_RIG, ["bones", "hand_r"], {"parent": "forearm_r", "joint": [40, 38]})
    assert contract.validate_rig(rig) == []


@pytest.mark.parametrize("path, value, expected", [
    (["version"], 2, "version"),
    (["version"], "<del>", "version"),
    (["sprite"], "", "sprite"),
    (["view"], None, "view"),
    (["view"], "isometric", "view"),
    (["parts", "torso", "fill"], "blur", "fill"),
    (["parts", "torso", "fill_color"], "blue", "fill_color"),
    (["parts", "torso", "region", "polygons"], [[[1, 2], [3, 4]]], "polygons"),
    (["parts", "torso", "region", "exclude"], {"rects": [[1, 2, 3]]}, "exclude.rects"),
    (["ik", "foot_r", "bend"], 0, "bend"),
    (["outline"], "black", "outline"),
    (["outline"], True, "outline"),
    (["outline_mode"], "middle", "outline_mode"),
    (["ik", "foot_r", "chain"], ["shin_r", "thigh_r"], "hierarchy"),
    (["ik", "foot_r", "chain"], ["thigh_r"], "chain"),
    (["pivot"], [0.5], "pivot"),
    (["pivot"], [0.5, 1.5], "pivot"),
    (["bones"], {}, "bones"),
    (["bones", "hips"], "<del>", "hips"),
    (["bones", "hips", "parent"], "spine", "root"),
    (["bones", "head", "parent"], "neck", "unknown parent 'neck'"),
    (["bones", "head", "parent"], "<del>", "unknown parent"),
    (["bones", "head", "joint"], [32.5, 20], "joint"),
    (["bones", "head", "joint"], [32], "joint"),
    (["bones", "head", "joint"], [True, 20], "joint"),
    (["parts"], {}, "parts"),
    (["parts", "torso", "bone"], "tail", "unknown bone 'tail'"),
    (["parts", "torso", "z"], 0.5, "'z'"),
    (["parts", "torso", "overlap"], -1, "overlap"),
    (["parts", "torso", "region"], "<del>", "region"),
    (["parts", "torso", "region", "rects"], [[26, 22, 12]], "rects"),
    (["parts", "torso", "region", "rects"], [[26, 22, 0, 18]], "non positive"),
    (["parts", "torso", "region", "pixels"], [[1, 2, 3]], "pixels"),
    (["ik", "foot_r", "chain"], ["thigh_r", "knee_r"], "chain"),
    (["ik", "foot_r", "target_bone"], "toe_r", "target_bone"),
])
def test_rig_invalid(path, value, expected):
    problems = contract.validate_rig(mutated(SCHEMA_RIG, path, value))
    assert problems and any(expected in p for p in problems), problems


def test_rig_parent_cycle_is_detected():
    rig = mutated(SCHEMA_RIG, ["bones", "spine", "parent"], "head")     # spine <-> head
    assert any("cycle" in p for p in contract.validate_rig(rig))


def test_rig_not_an_object():
    assert contract.validate_rig([]) and contract.validate_rig(None)


# --------------------------------------------------------------------------- #
# anim.json
# --------------------------------------------------------------------------- #

def test_anim_schema_example_is_valid():
    assert contract.validate_anim(SCHEMA_ANIM) == []
    assert contract.total_duration_ms(SCHEMA_ANIM) == 100


def test_anim_bones_and_z_are_optional_per_frame():
    assert contract.validate_anim(mutated(SCHEMA_ANIM, ["frames"], [{"duration_ms": 80}])) == []


def test_anim_key_label_and_unknown_keys_are_valid():
    """Unknown keys are warnings of the tool, not schema errors; ``_x`` keys are comments."""
    anim = mutated(SCHEMA_ANIM, ["frames", 0, "key"], 2)
    anim["frames"][0].update(label="contact", _note="c", hold=3)
    anim["frames"][0]["bones"]["thigh_r"]["rotation"] = 30
    assert contract.validate_anim(anim) == []
    assert contract.validate_anim(mutated(SCHEMA_ANIM, ["frames", 0, "key"], True)) == []


def test_anim_defaults_and_ik_block():
    # name = file name, loop = true, fps = 10, duration_ms = one tick when absent
    assert contract.validate_anim({"version": 1, "frames": [{}]}) == []
    with_ik = mutated(SCHEMA_ANIM, ["frames", 0, "ik"], {"foot_r": {"pos": [0, 0], "rot": 0}})
    assert contract.validate_anim(with_ik) == []


@pytest.mark.parametrize("path, value, expected", [
    (["version"], 3, "version"),
    (["name"], "", "name"),
    (["loop"], 1, "loop"),
    (["fps"], 0, "fps"),
    (["frames"], [], "frames"),
    (["frames", 0, "duration_ms"], 0, "duration_ms"),
    (["frames", 0, "duration_ms"], "100", "duration_ms"),
    (["frames", 0, "ik"], {"foot_r": {"pos": [0.5, 0]}}, "ik 'foot_r': 'pos'"),
    (["frames", 0, "bones", "thigh_r", "rot"], "20", "rot"),
    (["frames", 0, "bones", "thigh_r", "pos"], [0.5, 0], "pos"),
    (["frames", 0, "key"], -1, "'key'"),
    (["frames", 0, "key"], "yes", "'key'"),
    (["frames", 0, "label"], 3, "'label'"),
    (["frames", 0, "z"], {"arm_l": 0.5}, "'z'"),
])
def test_anim_invalid(path, value, expected):
    problems = contract.validate_anim(mutated(SCHEMA_ANIM, path, value))
    assert problems and any(expected in p for p in problems), problems


# --------------------------------------------------------------------------- #
# report.json
# --------------------------------------------------------------------------- #

def test_report_valid_pass_and_fail():
    assert contract.validate_report(SCHEMA_REPORT) == []
    failing = mutated(mutated(SCHEMA_REPORT, ["ok"], False), ["checks", 3], {
        "id": "holes", "pass": False, "detail": "2 px hole", "frame": 4, "pixel": [12, 30]})
    assert contract.validate_report(failing) == []


def test_report_schema_one_line_example_is_valid_when_not_requiring_all_checks():
    example = {"ok": True, "checks": [
        {"id": "palette", "pass": True, "detail": "", "frame": None, "pixel": None}]}
    assert contract.validate_report(example, require_all_checks=False) == []
    assert any("missing" in p for p in contract.validate_report(example))


def test_report_one_entry_when_passing_one_per_faulty_frame_when_failing():
    def entry(frame, passed=False):
        return {"id": "holes", "pass": passed, "detail": "open joint 'shin_r'", "frame": frame,
                "pixel": [3, 4]}

    others = [c for c in SCHEMA_REPORT["checks"] if c["id"] != "holes"]
    failing = {"ok": False, "checks": others + [entry(2), entry(5)]}
    assert contract.validate_report(failing) == []
    assert contract.failing_frames(failing, "holes") == [2, 5]
    assert contract.failing_frames(failing, "palette") == []
    doubled = {"ok": True, "checks": SCHEMA_REPORT["checks"] + [SCHEMA_REPORT["checks"][0]]}
    assert any("passes but has 2 entries" in p for p in contract.validate_report(doubled))
    mixed = {"ok": False, "checks": others + [entry(2), entry(None, passed=True)]}
    assert any("mixes passing and failing" in p for p in contract.validate_report(mixed))
    flood = {"ok": False, "checks": others + [entry(i) for i in range(21)]}
    assert any("more than 20" in p for p in contract.validate_report(flood))


@pytest.mark.parametrize("path, value, expected", [
    (["ok"], "yes", "'ok'"),
    (["checks"], {}, "checks"),
    (["checks", 0, "id"], "colors", "unknown id"),
    (["checks", 0, "pass"], None, "'pass'"),
    (["checks", 0, "detail"], None, "'detail'"),
    (["checks", 0, "detail"], "<del>", "missing key 'detail'"),
    (["checks", 0, "frame"], -1, "'frame'"),
    (["checks", 0, "pixel"], [1.5, 2], "'pixel'"),
    (["checks", 0, "pass"], False, "exactly when every check passes"),   # ok true, one fails
    (["ok"], False, "exactly when every check passes"),                  # ok false, all pass
])
def test_report_invalid(path, value, expected):
    problems = contract.validate_report(mutated(SCHEMA_REPORT, path, value))
    assert problems and any(expected in p for p in problems), problems


def _metrics(outline=None, **frame):
    base = {"border": 200, "outline_bare": None if outline is None else 0, "ground_offset": 0,
            "pinholes": []}
    base.update(frame)
    return dict(SCHEMA_REPORT, warnings=[], metrics={
        "unmonitored_joints": ["forearm_l"], "outline": outline, "frames": [base]})


OUTLINE_METRIC = {"applied": True, "color": "#140c1c", "source_bare": 0}


def test_report_metrics_valid():
    assert contract.validate_report(_metrics(), require_metrics=True) == []
    assert contract.validate_report(_metrics(OUTLINE_METRIC, pinholes=[[22, 45]], ground_offset=None),
                                    require_metrics=True) == []
    assert contract.validate_report(SCHEMA_REPORT) == [], "metrics are only checked on demand"


@pytest.mark.parametrize("report, expected", [
    (SCHEMA_REPORT, "'metrics' must be an object"),
    (dict(_metrics(), warnings=None), "'warnings'"),
    (_metrics(border=-1), "'border'"),
    (_metrics(outline_bare=3), "must be null when the sprite has no outline"),
    (_metrics(OUTLINE_METRIC, outline_bare=None), "must be an integer when the sprite has an outline"),
    (_metrics({"color": "#140c1c"}), "metrics.outline"),
    (_metrics(ground_offset=0.5), "'ground_offset'"),
    (_metrics(pinholes=[[1]]), "'pinholes'"),
])
def test_report_metrics_invalid(report, expected):
    problems = contract.validate_report(report, require_metrics=True)
    assert problems and any(expected in p for p in problems), problems


# --------------------------------------------------------------------------- #
# frames.json
# --------------------------------------------------------------------------- #

SCHEMA_MANIFEST = {
    "version": 1, "name": "walk", "loop": True, "fps": 10.0, "duration_ms": 200,
    "canvas": [48, 86], "origin": [8, 2], "pivot": [25, 82], "padding": 2, "rotation": "rotsprite",
    "source": {"sprite_size": [48, 86], "palette": ["#000000"], "orphans": 0,
               "unassigned": 0, "unassigned_first": None, "multi_assigned": 0},
    "rest": {"bones": {"hips": {"parent": None, "joint": [24, 49]},
                       "spine": {"parent": "hips", "joint": [24, 45]}}},
    "parts": {"torso": {"bone": "spine", "z": 20, "fill": "own", "hidden_pixels": 96, "missing": []}},
    "joints": {"spine": 5}, "joints_rest": {"spine": 6},
    "mirror": False, "outline": None, "outline_detected": None,
    "frames": [
        {"file": f"frame_{i:03d}.png", "duration_ms": 100, "pivot": [25, 82], "source_frame": i,
         "bones": {"hips": {"angle": 0, "joint": [24, 50]}, "spine": {"angle": 180, "joint": [24, 46]}}}
        for i in range(2)],
}


def test_manifest_schema_example_is_valid():
    assert contract.validate_frames_manifest(SCHEMA_MANIFEST) == []
    with_z = mutated(SCHEMA_MANIFEST, ["frames", 0, "z"], {"arm_l": -1})
    assert contract.validate_frames_manifest(with_z) == []
    outlined = mutated(SCHEMA_MANIFEST, ["outline"], {
        "color": "#140c1c", "mode": "outside", "inner_parts": [], "source_bare": 0, "source_border": 147})
    outlined["outline_detected"] = {"color": "#140c1c", "source_bare": 0, "source_border": 147}
    assert contract.validate_frames_manifest(outlined) == []


@pytest.mark.parametrize("path, value, expected", [
    (["name"], "", "name"),
    (["loop"], None, "loop"),
    (["fps"], 0, "fps"),
    (["canvas"], [48.0, 86], "canvas"),
    (["origin"], "<del>", "origin"),
    (["pivot"], [25.5, 82], "pivot"),
    (["source", "palette"], ["black"], "source.palette"),
    (["source", "orphans"], "<del>", "source.orphans"),
    (["rest"], "<del>", "rest.bones"),
    (["rest", "bones", "spine", "joint"], [24.5, 45], "rest bone 'spine'"),
    (["parts", "torso", "bone"], "chest", "part 'torso'"),
    (["parts", "torso", "missing"], "<del>", "missing"),
    (["parts", "torso", "missing"], [[1, 2, 3]], "missing"),
    (["joints"], "<del>", "joints"),
    (["joints", "spine"], -1, "joints 'spine'"),
    (["joints", "spine"], 2.5, "joints 'spine'"),
    (["joints", "tail"], 2, "joints 'tail'"),
    (["joints_rest"], "<del>", "joints_rest"),
    (["joints_rest", "spine"], 9, "max(joints_rest - 1, 0)"),
    (["mirror"], "<del>", "mirror"),
    (["outline"], "<del>", "'outline'"),
    (["outline"], {"color": "#140c1c"}, "'outline'"),
    (["outline_detected"], "<del>", "outline_detected"),
    (["frames"], [], "frames"),
    (["frames", 1, "pivot"], [25.0, 82], "frame 1: 'pivot'"),
    (["frames", 1, "duration_ms"], 0, "frame 1: 'duration_ms'"),
    (["frames", 1, "source_frame"], "<del>", "source_frame"),
    (["frames", 1, "bones", "spine"], "<del>", "frame 1: bone 'spine'"),
    (["frames", 1, "bones", "spine", "joint"], [24.4, 46], "frame 1: bone 'spine'"),
    (["frames", 1, "bones", "spine", "angle"], -180, "not in ]-180, 180]"),
    (["duration_ms"], 300, "sum of the frame durations"),
])
def test_manifest_invalid(path, value, expected):
    problems = contract.validate_frames_manifest(mutated(SCHEMA_MANIFEST, path, value))
    assert problems and any(expected in p for p in problems), problems


# --------------------------------------------------------------------------- #
# CLI adapter, pure parts
# --------------------------------------------------------------------------- #

def _result(tmp_path, payload, returncode=0, stdout=None, stderr="", args=("x",)):
    return cli_adapter.CliResult(
        list(args), tmp_path, tmp_path / "out", returncode,
        json.dumps(payload) if stdout is None else stdout, stderr,
        payload if isinstance(payload, dict) else None,
        None if isinstance(payload, dict) else "not an object")


OK = {"ok": True, "outputs": {}, "warnings": [], "error": None}
KO = {"ok": False, "outputs": {}, "warnings": [], "error": "rig.json: unknown bone 'tail'"}


def test_adapter_accepts_conforming_results(tmp_path):
    _result(tmp_path, OK, 0).expect_ok()
    _result(tmp_path, KO, 1).expect_user_error()
    _result(tmp_path, dict(KO, error="'rig' not implemented"), 2).assert_contract()


@pytest.mark.parametrize("payload, returncode", [
    (OK, 1), (KO, 0),                    # ok flag and return code disagree
    (OK, 3),                             # unknown return code
    ({"ok": True}, 0),                   # keys missing
    (None, 0),                           # stdout is not an object
    (dict(OK, warnings=["caf\u00e9"]), 0),   # messages are ASCII
])
def test_adapter_rejects_contract_violations(tmp_path, payload, returncode):
    with pytest.raises(cli_adapter.CliContractError):
        _result(tmp_path, payload, returncode).assert_contract()


def test_adapter_expect_ok_and_user_error_check_the_return_code(tmp_path):
    with pytest.raises(cli_adapter.CliContractError):
        _result(tmp_path, KO, 1).expect_ok()
    with pytest.raises(cli_adapter.CliContractError):
        _result(tmp_path, dict(KO, error="not implemented"), 2).expect_user_error()
    with pytest.raises(cli_adapter.CliContractError):
        _result(tmp_path, KO, 1, stderr="Traceback (most recent call last):\n ...").expect_user_error()


def test_adapter_expect_ok_requires_the_contract_output_keys_of_the_command(tmp_path):
    complete = dict(OK, outputs={"report": "r", "checks": 8, "failed": [], "metrics": {}})
    _result(tmp_path, complete, args=("validate", "frames")).expect_ok()
    with pytest.raises(cli_adapter.CliContractError, match="lacks contract key"):
        _result(tmp_path, dict(OK, outputs={"report": "r"}), args=("validate", "frames")).expect_ok()
    assert contract.missing_output_keys("export", {"spritesheet": "", "json": "", "gif": ""}) == [
        "format", "frame_count", "frame_size", "sheet_size", "pivot", "duration_ms", "mirror"]
    assert set(contract.CLI_OUTPUT_KEYS) == set(cli_adapter.COMMANDS)


def test_adapter_rejects_the_wave_0_stub(tmp_path):
    stub = {"ok": False, "error": "'prepare' not implemented"}
    with pytest.raises(cli_adapter.CliContractError):
        _result(tmp_path, stub, 2).expect_ok()
    with pytest.raises(cli_adapter.CliContractError):
        _result(tmp_path, stub, 2).assert_contract()


def test_adapter_output_paths_must_be_absolute_and_exist(tmp_path):
    frames_dir = tmp_path / "out" / "frames"
    frames_dir.mkdir(parents=True)
    for index in (1, 0, 2):
        Image.new("RGBA", (4, 4), (index, 0, 0, 255)).save(frames_dir / f"frame_{index:03d}.png")
    listed = [str(frames_dir / f"frame_{i:03d}.png") for i in (2, 0)]
    result = _result(tmp_path, dict(OK, outputs={"frames": listed, "frames_dir": str(frames_dir)}))
    assert [int(f[0, 0, 0]) for f in result.frames()] == [2, 0], "the listed order is the playback order"
    assert result.frames_dir() == frames_dir
    for bad in (["frame_000.png"],                                   # relative
                [str(frames_dir / "frame_009.png")],                 # missing
                [], str(frames_dir)):                                # empty / not a list
        with pytest.raises(cli_adapter.CliContractError):
            _result(tmp_path, dict(OK, outputs={"frames": bad})).frame_paths()
    with pytest.raises(cli_adapter.CliContractError):
        _result(tmp_path, OK).output("frames")
    elsewhere = dict(OK, outputs={"frames": listed, "frames_dir": str(tmp_path)})
    with pytest.raises(cli_adapter.CliContractError):
        _result(tmp_path, elsewhere).frames_dir()


def _sheet_json(count=2, pivot=None, size=None):
    return {"frames": [{"filename": f"walk {i}", "frame": {"x": 4 * i, "y": 0, "w": 4, "h": 4},
                        "duration": 100} for i in range(count)],
            "meta": {"size": {"w": 4 * count, "h": 4},
                     "animai": {"name": "walk", "loop": True, "mirror": False, "fps": 10.0,
                                "duration_ms": 100 * count,
                                "frame_size": size or {"w": 4, "h": 4},
                                "pivot": pivot or {"x": 2, "y": 4}}}}


def test_adapter_parse_sheet_json():
    layout = cli_adapter.parse_sheet_json(_sheet_json())
    assert layout.rects == [(0, 0, 4, 4), (4, 0, 4, 4)]
    assert layout.durations_ms == [100, 100] and layout.pivots == [(2, 4), (2, 4)]
    assert layout.frame_size == (4, 4) and layout.loop is True and layout.mirror is False
    no_mirror = _sheet_json()
    del no_mirror["meta"]["animai"]["mirror"]
    with pytest.raises(cli_adapter.CliContractError):
        cli_adapter.parse_sheet_json(no_mirror)
    object_form = _sheet_json()
    object_form["frames"] = {e["filename"]: e for e in object_form["frames"]}
    no_meta = _sheet_json()
    del no_meta["meta"]["animai"]
    broken_frame = _sheet_json()
    del broken_frame["frames"][1]["duration"]
    for broken in ({}, {"frames": []}, object_form, no_meta, broken_frame,
                   _sheet_json(pivot={"x": 2.5, "y": 4}), _sheet_json(pivot=[2, 4]),
                   _sheet_json(size={"w": 5, "h": 4})):
        with pytest.raises(cli_adapter.CliContractError):
            cli_adapter.parse_sheet_json(broken)


def test_adapter_cut_sheet():
    sheet = np.zeros((4, 8, 4), np.uint8)
    sheet[:, 4:] = 255
    layout = cli_adapter.parse_sheet_json(_sheet_json())
    first, second = cli_adapter.cut_sheet(sheet, layout)
    assert not first.any() and second.all()
    with pytest.raises(cli_adapter.CliContractError):
        cli_adapter.cut_sheet(sheet, cli_adapter.parse_sheet_json(_sheet_json(3)))


def test_adapter_timing_args():
    assert cli_adapter.timing_args() == []
    assert cli_adapter.timing_args("0.8s", 8, 10) == ["--duration", "0.8s", "--frames", "8", "--fps", "10"]


def test_adapter_ground_tolerances():
    frames = [{"source_frame": i} for i in (0, 1, 1, 2, 3, 4, 5, 6)]
    assert cli_adapter.ground_tolerances("idle", {"frames": frames}) == [0] * 8
    assert cli_adapter.ground_tolerances("walk", {"frames": frames}) == [1] * 8
    assert cli_adapter.ground_tolerances("attack", {"frames": frames}) == [0, 0, 0, 1, 1, 1, 0, 0]
    with pytest.raises(ValueError):
        cli_adapter.ground_tolerances("jump", {"frames": frames})
