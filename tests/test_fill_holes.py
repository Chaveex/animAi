"""Automatic hole filling (``rig.fill_holes``, on by default).

The pass only adds pixels where a pose opened a hole, with colours of the
palette, and never touches the rest pose.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from animai.core import pipeline, qa
from animai.core.anim import load_preset, retarget
from animai.core.errors import AnimaiError
from animai.core.rig import load_rig, validate_rig
from animai.core.sprite import pack_rgb
from animai.core.timing import resample

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CASES = [("hero64", "walk"), ("hero64", "attack"), ("knight96", "walk"), ("knight96", "attack"),
         ("rogue80_outline", "attack"), ("mage64x80_bg", "attack")]


def _render(name: str, preset: str, fill: bool, frames=None):
    rig, _ = load_rig(FIXTURES / name / "rig.json")
    rgba = np.asarray(Image.open(FIXTURES / name / "sprite.png").convert("RGBA"))
    anim, _ = load_preset(preset)
    anim, _ = retarget(anim, rig)
    if frames is not None:
        anim = {**anim, "frames": frames}
    anim, indices, _ = resample(anim)
    return rgba, pipeline.render_project({**rig, "fill_holes": fill}, rgba, anim, indices)


@pytest.mark.parametrize("name,preset", CASES)
def test_filling_only_adds_palette_pixels_in_holes(name, preset):
    rgba, off = _render(name, preset, False)
    _, on = _render(name, preset, True)
    palette = set(np.unique(pack_rgb(rgba)[rgba[..., 3] > 0]).tolist())
    assert on.result.canvas == off.result.canvas and on.result.origin == off.result.origin
    filled = 0
    for a, b in zip(off.result.frames, on.result.frames):
        changed = (a != b).any(axis=2)
        filled += int(changed.sum())
        assert (b[changed][:, 3] == 255).all(), "a changed pixel is an opaque pixel"
        assert set(pack_rgb(b)[changed].tolist()) <= palette, "no colour outside the palette"
        assert ((a[..., 3] > 0) <= (b[..., 3] > 0)).all(), "nothing is removed"
    assert filled > 0, "these animations open at least one hole"
    assert any("holes filled automatically" in w for w in on.warnings)
    assert not any("holes filled automatically" in w for w in off.warnings)


@pytest.mark.parametrize("name,preset", CASES)
def test_no_open_joint_left(name, preset):
    _, on = _render(name, preset, True)
    for i, frame in enumerate(on.result.frames):
        causes = [h[2] for h in qa.find_holes(frame, on.manifest, i)]
        assert not [c for c in causes if c.startswith("open joint")], f"frame {i}"


@pytest.mark.parametrize("name", ["hero64", "knight96", "rogue80_outline", "mage64x80_bg"])
def test_rest_pose_is_untouched(name):
    rest = [{"duration_ms": 100, "bones": {}}]
    _, on = _render(name, "idle", True, frames=rest)
    _, off = _render(name, "idle", False, frames=rest)
    assert np.array_equal(on.result.frames[0], off.result.frames[0])
    assert not any("holes filled automatically" in w for w in on.warnings)


def test_fill_holes_must_be_a_boolean():
    rig, _ = load_rig(FIXTURES / "hero64" / "rig.json")
    with pytest.raises(AnimaiError, match="fill_holes"):
        validate_rig({**rig, "fill_holes": "yes"})
