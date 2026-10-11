"""Integration: --duration / --frames / --fps on ``animate``.

CLAUDE.md: two of the three are enough, the third is deduced; an inconsistent
triple is a clear error. Needs the lead dev's implementation.
"""
from __future__ import annotations

import numpy as np
import pytest

from tests import cli_adapter as cli, contract, invariants as inv

pytestmark = pytest.mark.integration


def animate(project, tmp_path, out="out", preset="walk", **timing):
    return cli.animate(project / "rig.json", tmp_path / out, tmp_path, preset=preset, **timing)


@pytest.mark.parametrize("timing, frames, total_ms, fps", [
    ({"frames": 8, "fps": 10}, 8, 800, 10),
    ({"duration": "0.8s", "fps": 10}, 8, 800, 10),
    ({"duration": "0.8s", "frames": 8}, 8, 800, 10),
    ({"duration": "800ms", "frames": 8}, 8, 800, 10),
    ({"frames": 4, "fps": 8}, 4, 500, 8),
    ({"duration": "0.5s", "fps": 8}, 4, 500, 8),
    ({"duration": "1s", "frames": 4}, 4, 1000, 4),
    ({"frames": 6, "fps": 12}, 6, 500, 12),
    ({"duration": "0.8s", "frames": 8, "fps": 10}, 8, 800, 10),      # all three, coherent
], ids=lambda value: " ".join(f"{k}={v}" for k, v in value.items()) if isinstance(value, dict) else None)
def test_two_of_three_timing_options_define_the_third(timing, frames, total_ms, fps,
                                                      project, hero, tmp_path):
    result = animate(project, tmp_path, **timing).expect_ok()
    assert len(result.frames()) == frames
    anim = result.anim()
    assert len(anim["frames"]) == frames
    assert contract.total_duration_ms(anim) == pytest.approx(total_ms, abs=1e-6)
    assert anim["fps"] == pytest.approx(fps)
    assert all(f["duration_ms"] > 0 for f in anim["frames"])
    inv.assert_no_violations(cli.animation_violations(result.frames(), hero.palette, anim),
                             f"timing {timing}")


@pytest.mark.parametrize("preset", cli.MVP_PRESETS)
def test_equivalent_timing_spellings_give_identical_frames(preset, project, tmp_path):
    variants = [
        {"frames": 8, "fps": 10},
        {"duration": "0.8s", "fps": 10},
        {"duration": "0.8s", "frames": 8},
        {"duration": "800ms", "fps": 10},
    ]
    outputs = []
    for index, timing in enumerate(variants):
        result = animate(project, tmp_path, out=f"out{index}", preset=preset, **timing).expect_ok()
        outputs.append([inv.canonical(f) for f in result.frames()])
    reference = outputs[0]
    for timing, frames in zip(variants[1:], outputs[1:]):
        assert len(frames) == len(reference), timing
        assert all(np.array_equal(a, b) for a, b in zip(frames, reference)), \
            f"{timing} should be the same animation as {variants[0]}"


@pytest.mark.parametrize("timing", [
    {"duration": "1s", "frames": 8, "fps": 10},        # 8 frames at 10 fps is 0.8 s, not 1 s
    {"duration": "0.8s", "frames": 4, "fps": 10},
    {"duration": "800ms", "frames": 8, "fps": 12},
], ids=lambda t: " ".join(f"{k}={v}" for k, v in t.items()))
def test_inconsistent_duration_frames_fps_is_a_clear_user_error(timing, project, tmp_path):
    result = animate(project, tmp_path, **timing).expect_user_error()
    assert len(result.payload["error"]) >= 10, "the error must explain the inconsistency"
    out = tmp_path / "out"
    assert not (out.exists() and list(out.rglob("*.png"))), "no frame may be written on error"


@pytest.mark.parametrize("timing", [
    {"frames": 0, "fps": 10},
    {"frames": -4, "fps": 10},
    {"frames": "2.5", "fps": 10},
    {"frames": 8, "fps": 0},
    {"frames": 8, "fps": -10},
    {"duration": "0s", "fps": 10},
    {"duration": "-1s", "fps": 10},
    {"duration": "abc", "fps": 10},
    {"duration": "0.8s", "fps": "fast"},
], ids=lambda t: " ".join(f"{k}={v}" for k, v in t.items()))
def test_invalid_timing_values_are_clean_user_errors(timing, project, tmp_path):
    """Still one JSON object on stdout and return code 1 (not argparse's usage/exit 2)."""
    animate(project, tmp_path, **timing).expect_user_error()


@pytest.mark.parametrize("preset", cli.LOOPING_PRESETS)
@pytest.mark.parametrize("frames", [4, 6, 8])
def test_resampled_presets_stay_valid_loops(preset, frames, project, hero, tmp_path):
    """4 to 8 frames is the default readable range: every count must loop cleanly."""
    result = animate(project, tmp_path, preset=preset, frames=frames, fps=10).expect_ok()
    produced = result.frames()
    assert len(produced) == frames
    manifest = result.manifest()
    assert manifest["loop"] is True
    inv.assert_no_violations(
        cli.animation_violations(produced, hero.palette, manifest)
        + cli.ground_violations(produced, manifest, preset),
        f"{preset} resampled to {frames} frames")


def test_more_than_eight_frames_is_allowed(project, hero, tmp_path):
    """CLAUDE.md: 'plus autorise mais signale en QA' -> animate itself must succeed."""
    result = animate(project, tmp_path, frames=16, fps=20).expect_ok()
    assert len(result.frames()) == 16
    assert contract.total_duration_ms(result.anim()) == pytest.approx(800)
    inv.assert_no_violations(
        cli.animation_violations(result.frames(), hero.palette, result.manifest()), "16 frames")
    assert any("16 frames" in w for w in result.warnings), "more than 8 frames = warning (contract)"


def test_timing_reaches_the_export_json_and_the_gif(project, tmp_path):
    result = animate(project, tmp_path, duration="1.2s", frames=6).expect_ok()
    exported = cli.export(result.frames_dir(), tmp_path / "export", tmp_path).expect_ok()
    layout = cli.parse_sheet_json(exported.json(cli.KEY_SHEET_JSON))
    assert layout.durations_ms == [200] * 6
    _, gif_durations = cli.gif_frames(exported.path(cli.KEY_GIF))
    assert sum(gif_durations) == 1200
