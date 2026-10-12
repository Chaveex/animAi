"""Replacement images (``rig.swaps`` + ``frames[i].swap``).

A swap draws a hand-made image in place of some parts, in the frames that ask
for it: the image is placed like a rigid part of its bone.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from animai.core import pipeline, qa
from animai.core.anim import load_preset, retarget, validate_anim
from animai.core.errors import AnimaiError
from animai.core.rig import load_rig, validate_rig
from animai.core.sprite import pack_rgb
from animai.core.timing import resample

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
REST = [{"duration_ms": 100, "bones": {}}, {"duration_ms": 100, "bones": {}}]


def _project():
    rig, _ = load_rig(FIXTURES / "hero64" / "rig.json")
    rgba = np.asarray(Image.open(FIXTURES / "hero64" / "sprite.png").convert("RGBA"))
    return rig, rgba


def _block(rgba: np.ndarray, w: int = 6, h: int = 3) -> np.ndarray:
    """A small opaque image in one colour of the sprite, with one transparent corner."""
    colour = rgba[rgba[..., 3] > 0][0]
    image = np.tile(colour, (h, w, 1)).astype(np.uint8)
    image[0, 0] = 0
    return image


def _rig_with(rig: dict, **swap) -> dict:
    spec = {"image": "block.png", "bone": "forearm_r", "anchor": [1, 1], **swap}
    return {**rig, "swaps": {"block": spec}}


def _render(rig, rgba, frames, images, **options):
    anim = {"version": 1, "name": "t", "loop": True, "fps": 10, "frames": frames}
    anim, _ = retarget(anim, rig)
    anim, indices, _ = resample(anim)
    return pipeline.render_project(rig, rgba, anim, indices, swap_images=images, **options)


def _in_frame(out, index: int, x: int, y: int):
    ox, oy = out.result.origin
    return out.result.frames[index][y - oy, x - ox]


def test_swap_replaces_its_parts_only_in_the_frames_that_ask():
    rig, rgba = _project()
    rig = _rig_with(rig)
    block = _block(rgba)
    frames = [REST[0], {**REST[1], "swap": ["block"]}]
    out = _render(rig, rgba, frames, {"block": block})
    plain = _render(rig, rgba, REST, {"block": block})

    assert np.array_equal(out.result.frames[0], plain.result.frames[0]), "frame without swap is untouched"
    jx, jy = rig["bones"]["forearm_r"]["joint"]
    # the anchor pixel [1, 1] of the image sits on the joint
    for dy in range(3):
        for dx in range(6):
            pixel = _in_frame(out, 1, jx - 1 + dx, jy - 1 + dy)
            if (dx, dy) != (0, 0):
                assert tuple(pixel) == tuple(block[dy, dx])
    # the pixels of the replaced part that the image does not cover are gone or show what is behind
    labels = out.labelmap.labels
    index = out.labelmap.part_names.index("forearm_r")
    ys, xs = np.nonzero(labels == index)
    outside = [(x, y) for x, y in zip(xs, ys) if not (jx - 1 <= x < jx + 5 and jy - 1 <= y < jy + 2)]
    changed = [p for p in outside if not np.array_equal(_in_frame(out, 1, *p), _in_frame(plain, 1, *p))]
    assert changed, "the forearm is not drawn in the swapped frame"
    assert out.manifest["frames"][1]["swap"] == ["block"]
    assert out.manifest["frames"][1]["hidden_bones"] == ["forearm_r"]
    assert "swap" not in out.manifest["frames"][0]


def test_swap_follows_its_bone():
    rig, rgba = _project()
    rig = _rig_with(rig)
    block = _block(rgba)
    jx, jy = rig["bones"]["forearm_r"]["joint"]
    moved = _render(rig, rgba, [{"duration_ms": 100, "swap": ["block"], "bones": {"forearm_r": {"pos": [3, -2]}}}],
                    {"block": block})
    assert tuple(_in_frame(moved, 0, jx + 3 + 4, jy - 2 + 1)) == tuple(block[2, 5])
    turned = _render(rig, rgba, [{"duration_ms": 100, "swap": ["block"], "bones": {"forearm_r": {"rot": 90}}}],
                     {"block": block})
    # a quarter turn counter-clockwise: the pixel 4 px right of the anchor ends 4 px above the joint
    assert tuple(_in_frame(turned, 0, jx, jy - 4)) == tuple(block[1, 5])


def test_hides_default_is_the_parts_of_the_bone_and_can_list_more():
    rig, rgba = _project()
    wide = _rig_with(rig, bone="arm_r", hides=["arm_r", "forearm_r"])
    out = _render(wide, rgba, [{**REST[0], "swap": ["block"]}], {"block": _block(rgba)})
    assert out.manifest["frames"][0]["hidden_bones"] == ["arm_r", "forearm_r"]


def test_swap_keeps_palette_and_binary_alpha_in_qa():
    rig, rgba = _project()
    rig = _rig_with(rig)
    out = _render(rig, rgba, [REST[0], {**REST[1], "swap": ["block"]}], {"block": _block(rgba)})
    report = qa.validate_frames(out.result.frames, out.manifest)
    checks = {c["id"]: c["pass"] for c in report["checks"] if c.get("frame") is None}
    assert checks["palette"] is True and checks["alpha_binary"] is True
    assert not [c for c in report["checks"] if c["id"] == "holes" and c["pass"] is False
                and "forearm_r" in c.get("detail", "")], "a replaced articulation is not checked"


def test_image_outside_the_palette_or_with_soft_alpha_is_refused():
    rig, rgba = _project()
    rig = _rig_with(rig)
    palette = set(pack_rgb(rgba)[rgba[..., 3] > 0].tolist())
    alien = next(c for c in (0xFF00FF, 0x00FF00, 0x123456) if c not in palette)
    bad = _block(rgba)
    bad[1, 1] = ((alien >> 16) & 255, (alien >> 8) & 255, alien & 255, 255)
    with pytest.raises(AnimaiError, match="not in the sprite palette"):
        _render(rig, rgba, REST, {"block": bad})
    soft = _block(rgba)
    soft[1, 1, 3] = 128
    with pytest.raises(AnimaiError, match="alpha must be 0 or 255"):
        _render(rig, rgba, REST, {"block": soft})


@pytest.mark.parametrize("swap,match", [
    ({"bone": "nope"}, "unknown bone"),
    ({"anchor": [1.5, 0]}, "anchor"),
    ({"anchor": None}, "anchor"),
    ({"image": ""}, "image"),
    ({"hides": ["nope"]}, "unknown part"),
    ({"hides": "forearm_r"}, "hides"),
    ({"z": "front"}, "z must be"),
    ({"bone": "hips", "hides": []}, None),
])
def test_rig_validation(swap, match):
    rig, _ = _project()
    bad = _rig_with(rig, **swap)
    if match is None:           # hips carries a part: valid
        validate_rig(bad)
        return
    with pytest.raises(AnimaiError, match=match):
        validate_rig(bad)


def test_anim_validation_and_retarget():
    rig, _ = _project()
    anim, _ = load_preset("idle")
    with pytest.raises(AnimaiError, match="swap"):
        validate_anim({**anim, "frames": [{**anim["frames"][0], "swap": "block"}]})
    out, warnings = retarget({**anim, "frames": [{**anim["frames"][0], "swap": ["block"]}]}, rig)
    assert "swap" not in out["frames"][0]
    assert any("swap 'block' is not defined in the rig" in w for w in warnings)


def test_cli_reads_the_image_next_to_the_rig(tmp_path):
    for name in ("sprite.png", "rig.json"):
        shutil.copy(FIXTURES / "hero64" / name, tmp_path / name)
    rig, rgba = _project()
    raw = json.loads((tmp_path / "rig.json").read_text(encoding="utf-8"))
    raw["swaps"] = {"block": {"image": "swaps/block.png", "bone": "forearm_r", "anchor": [1, 1]}}
    (tmp_path / "rig.json").write_text(json.dumps(raw), encoding="utf-8")
    anim = {"version": 1, "name": "t", "fps": 10, "frames": [REST[0], {**REST[1], "swap": ["block"]}]}
    (tmp_path / "anim.json").write_text(json.dumps(anim), encoding="utf-8")

    with pytest.raises(AnimaiError, match="swap 'block'"):
        pipeline.run_animate(tmp_path / "rig.json", keyframes=tmp_path / "anim.json")
    (tmp_path / "swaps").mkdir()
    Image.fromarray(_block(rgba)).save(tmp_path / "swaps" / "block.png")
    result = pipeline.run_animate(tmp_path / "rig.json", keyframes=tmp_path / "anim.json")
    manifest = json.loads(Path(result.outputs["manifest"]).read_text(encoding="utf-8"))
    assert manifest["frames"][1]["swap"] == ["block"]
    a, b = (np.asarray(Image.open(f)) for f in result.outputs["frames"])
    assert not np.array_equal(a, b)
