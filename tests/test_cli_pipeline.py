"""Integration: the full chain prepare -> inspect -> rig -> animate -> validate
-> export on every reference sprite, plus determinism and golden images.

Needs the lead dev's implementation; fails (not skipped) until then.
"""
from __future__ import annotations

import hashlib
import shutil

import numpy as np
import pytest

from tests import cli_adapter as cli, contract, invariants as inv
from tests.conftest import FIXTURE_NAMES, load_case

pytestmark = pytest.mark.integration

CHAINS = [(name, preset) for name in FIXTURE_NAMES for preset in cli.MVP_PRESETS]
CHAIN_IDS = [f"{name}-{preset}" for name, preset in CHAINS]


@pytest.fixture(params=CHAINS, ids=CHAIN_IDS)
def chain(request, chain_for):
    name, preset = request.param
    return load_case(name), preset, chain_for(name, preset)


def test_chain_runs_and_every_step_honours_the_cli_contract(chain):
    _, _, done = chain
    assert list(done.steps) == ["prepare", "inspect", "rig", "animate", "validate", "export"]
    for step, result in done.steps.items():
        if step != "validate":          # its verdict has its own test below
            result.expect_ok()
        result.assert_contract()


def test_chain_prepared_sprite_is_the_expected_clean_sprite(chain):
    case, _, done = chain
    prepared = inv.canonical(done["prepare"].image(cli.KEY_SPRITE))
    assert np.array_equal(prepared, inv.canonical(case.sprite))


def test_chain_animated_frames_respect_all_invariants(chain):
    case, preset, done = chain
    frames = done["animate"].frames()
    assert len(frames) == 8
    manifest = done["animate"].manifest()
    assert manifest["loop"] is (preset in cli.LOOPING_PRESETS)
    inv.assert_no_violations(cli.animation_violations(frames, case.palette, manifest),
                             f"animate {case.name}/{preset}")


def test_chain_exported_frames_respect_all_invariants(chain):
    """The deliverable itself: palette, alpha, orphans, holes, canvas, pivot, loop."""
    case, preset, done = chain
    frames, layout = done.exported_frames()
    assert len(frames) == 8
    manifest = done["animate"].manifest()
    assert layout.frame_size == tuple(manifest["canvas"])
    assert layout.pivots[0] == tuple(manifest["pivot"]), "exported pivot = frames.json pivot"
    violations = cli.animation_violations(frames, case.palette, manifest)
    violations += inv.check_pivot_stable(layout.pivots, layout.frame_size)
    inv.assert_no_violations(violations, f"export {case.name}/{preset}")
    assert len(inv.palette_of(np.concatenate([f.reshape(-1, 1, 4) for f in frames]))) <= len(case.palette)


def test_chain_ground_line(chain):
    """Feet on the pivot's ground line: strict on idle, +/- 1 px on walk (guide D5), and on
    attack strict on the rest-feet frames (D7), +/- 1 px on the lunge frames."""
    case, preset, done = chain
    manifest = done["animate"].manifest()
    frames, _ = done.exported_frames()
    offsets = inv.ground_offsets(frames, manifest["pivot"][1])
    violations = cli.ground_violations(frames, manifest, preset)
    inv.assert_no_violations(violations, f"ground line {case.name}/{preset}, offsets per frame {offsets} "
                                         f"(source frames {[f['source_frame'] for f in manifest['frames']]})")


def test_chain_pivot_is_anchored_on_the_rest_pose(chain):
    """Same place around the pivot in idle, walk and attack (docs/schemas.md, guide D2)."""
    case, _, done = chain
    manifest = done["animate"].manifest()
    ys, xs = np.nonzero(case.sprite_rgba()[..., 3])
    width = int(xs.max() - xs.min() + 1)
    rest_pivot = [int(xs.min()) + int(np.floor(width * 0.5 + 0.5)), int(ys.max()) + 1]
    in_sprite = [manifest["pivot"][0] + manifest["origin"][0], manifest["pivot"][1] + manifest["origin"][1]]
    assert in_sprite == rest_pivot == done["rig"].payload["outputs"]["pivot"]


def test_chain_tool_qa_and_independent_holes_check_agree(chain):
    """Same frames flagged by the tool's `holes` check and by tests/invariants.check_holes."""
    case, preset, done = chain
    manifest = done["animate"].manifest()
    mine = inv.hole_frames(done["animate"].frames(), manifest)
    theirs = contract.failing_frames(done["validate"].json(cli.KEY_REPORT), "holes")
    assert theirs == mine[:contract.MAX_FAILED_ENTRIES], f"{case.name}/{preset}"


def test_chain_no_source_pixel_is_left_unassigned(chain):
    case, _, done = chain
    assert done["rig"].warnings == []
    inv.assert_no_violations(
        inv.check_rig_covers_sprite(done["prepare"].path(cli.KEY_SPRITE), case.rig),
        f"rig {case.name} on the prepared sprite")


def test_chain_qa_report_is_conforming_and_green(chain):
    _, _, done = chain
    report = done["validate"].json(cli.KEY_REPORT)
    assert contract.validate_report(report) == []
    assert report["ok"] is True, [c for c in report["checks"] if not c["pass"]]
    done["validate"].expect_ok()


def test_chain_durations_are_written_in_anim_export_json_and_gif(chain):
    _, _, done = chain
    anim = done["animate"].anim()
    assert [f["duration_ms"] for f in anim["frames"]] == [100] * 8
    _, layout = done.exported_frames()
    assert layout.durations_ms == [100] * 8
    _, gif_durations = cli.gif_frames(done["export"].path(cli.KEY_GIF))
    assert sum(gif_durations) == 800


def test_chain_gif_preview_keeps_the_palette(chain):
    case, _, done = chain
    images, _ = cli.gif_frames(done["export"].path(cli.KEY_GIF))
    inv.assert_no_violations(inv.check_palette(images, case.palette), f"gif {case.name}")


def test_chain_control_images_exist(chain):
    case, _, done = chain
    width, height = case.native_size
    inspected = done["inspect"].image(cli.KEY_INSPECT_IMAGE)
    assert inspected.shape[1] >= 8 * width and inspected.shape[0] >= 8 * height
    for step, key in (("rig", cli.KEY_OVERLAY), ("rig", cli.KEY_LABEL_MAP),
                      ("animate", cli.KEY_CONTACT_SHEET)):
        assert done[step].image(key).size > 0


def test_chain_spritesheet_matches_golden(chain, golden):
    """Pixel-perfect non-regression. Create/refresh with: pytest --update-golden"""
    case, preset, done = chain
    # A golden only ever freezes a GREEN case: tool QA ok and tester invariants ok.
    manifest = done["animate"].manifest()
    frames, _ = done.exported_frames()
    red = [str(v) for v in cli.animation_violations(frames, case.palette, manifest)
           + cli.ground_violations(frames, manifest, preset)]
    if done["validate"].returncode != 0:
        red.append(f"tool QA: {done['validate'].payload['error']}")
    if red:
        pytest.fail(f"{case.name}/{preset} is red, no golden is compared or written for it: "
                    + "; ".join(red[:5]))
    golden(f"{case.name}__{preset}__8f_10fps", done["export"].image(cli.KEY_SHEET))


def test_upscaled_and_plain_hero_give_the_same_animation(chain_for):
    """prepare must fully undo the x4 upscale: downstream output is identical."""
    plain = chain_for("hero64", "walk")["export"].image(cli.KEY_SHEET)
    upscaled = chain_for("hero64_x4", "walk")["export"].image(cli.KEY_SHEET)
    assert np.array_equal(inv.canonical(plain), inv.canonical(upscaled))


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #

def snapshot(directory) -> dict[str, str]:
    return {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.rglob("*")) if path.is_file()}


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_two_runs_give_byte_identical_outputs(name, tmp_path):
    """Same inputs, same working directory, run twice: every file and every
    stdout is identical byte for byte (no timestamp, no random, no dict order)."""
    case = load_case(name)
    workdir = tmp_path / "work"

    def run_once():
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir()
        done = cli.run_chain(case.source, case.rig_path, workdir, preset="walk")
        return snapshot(workdir), {step: result.stdout for step, result in done.steps.items()}

    first_files, first_stdout = run_once()
    second_files, second_stdout = run_once()
    assert sorted(first_files) == sorted(second_files), "the two runs wrote different file sets"
    assert len(first_files) > 2
    changed = [path for path in first_files if first_files[path] != second_files[path]]
    assert not changed, f"files differ between two identical runs: {changed}"
    assert first_stdout == second_stdout, "stdout differs between two identical runs"
