"""Hand retouches of a frame (``frames[i].paint`` in anim.json).

A retouch is written last, over the rendered frame: it paints a pixel with a
palette colour or makes it transparent, in one frame only.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from animai.core import pipeline, qa
from animai.core.anim import load_preset, retarget, validate_anim
from animai.core.errors import AnimaiError
from animai.core.rig import load_rig
from animai.core.sprite import pack_rgb
from animai.core.timing import resample

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _project(name: str = "hero64", preset: str = "walk"):
    rig, _ = load_rig(FIXTURES / name / "rig.json")
    rgba = np.asarray(Image.open(FIXTURES / name / "sprite.png").convert("RGBA"))
    anim, _ = load_preset(preset)
    anim, _ = retarget(anim, rig)
    return rig, rgba, anim


def _render(rig, rgba, anim, **options):
    anim, indices, _ = resample(anim)
    return pipeline.render_project(rig, rgba, anim, indices, **options)


def _hex(pixel) -> str:
    return "#%02x%02x%02x" % tuple(int(v) for v in pixel[:3])


def _with_paint(anim: dict, index: int, paint: list) -> dict:
    frames = [dict(f) for f in anim["frames"]]
    frames[index] = {**frames[index], "paint": paint}
    return {**anim, "frames": frames}


def _opaque_and_empty(out, index: int):
    """Sprite coordinates of one opaque and one transparent pixel of a frame, inside the canvas."""
    frame, (ox, oy) = out.result.frames[index], out.result.origin
    ys, xs = np.nonzero(frame[..., 3] > 0)
    k = len(xs) // 2
    ey, ex = [(y, x) for y, x in zip(*np.nonzero(frame[..., 3] == 0)) if 2 < x < frame.shape[1] - 3 and 2 < y < frame.shape[0] - 3][0]
    return (int(xs[k]) + ox, int(ys[k]) + oy), (int(ex) + ox, int(ey) + oy)


def test_paint_and_erase_change_only_their_pixels_in_their_frame():
    rig, rgba, anim = _project()
    base = _render(rig, rgba, anim)
    (px, py), (ex, ey) = _opaque_and_empty(base, 2)
    colours = sorted(set(pack_rgb(rgba)[rgba[..., 3] > 0].tolist()))
    ox, oy = base.result.origin
    current = pack_rgb(base.result.frames[2])[py - oy, px - ox]
    colour = next(c for c in colours if c != current)
    paint = [[ex, ey, f"#{colour:06x}"], [px, py, None]]
    out = _render(rig, rgba, _with_paint(anim, 2, paint))

    assert out.result.canvas == base.result.canvas and out.result.origin == base.result.origin
    for i, (a, b) in enumerate(zip(base.result.frames, out.result.frames)):
        if i != 2:
            assert np.array_equal(a, b), f"frame {i} must not change"
    changed = (base.result.frames[2] != out.result.frames[2]).any(axis=2)
    assert sorted(zip(*np.nonzero(changed))) == sorted([(ey - oy, ex - ox), (py - oy, px - ox)])
    frame = out.result.frames[2]
    assert _hex(frame[ey - oy, ex - ox]) == f"#{colour:06x}" and frame[ey - oy, ex - ox, 3] == 255
    assert tuple(frame[py - oy, px - ox]) == (0, 0, 0, 0)
    assert out.manifest["frames"][2]["retouched"] == 2
    assert "retouched" not in out.manifest["frames"][0]


def test_last_entry_of_a_pixel_wins_and_hex_case_is_free():
    rig, rgba, anim = _project()
    base = _render(rig, rgba, anim)
    (px, py), _ = _opaque_and_empty(base, 0)
    colour = _hex(rgba[rgba[..., 3] > 0][0])
    out = _render(rig, rgba, _with_paint(anim, 0, [[px, py, None], [px, py, colour.upper()]]))
    ox, oy = out.result.origin
    assert _hex(out.result.frames[0][py - oy, px - ox]) == colour


def test_colour_outside_the_palette_is_refused():
    rig, rgba, anim = _project()
    palette = {_hex(p) for p in rgba[rgba[..., 3] > 0]}
    alien = next(c for c in ("#ff00ff", "#00ff00", "#123456") if c not in palette)
    with pytest.raises(AnimaiError, match="not in the sprite palette"):
        _render(rig, rgba, _with_paint(anim, 1, [[10, 10, alien]]))


@pytest.mark.parametrize("paint", [
    "x", [[1, 2]], [[1.5, 2, None]], [[1, 2, 3]], [[1, 2, "red"]], [{"x": 1, "y": 2}], [[True, 2, None]],
])
def test_malformed_paint_is_an_error(paint):
    _, _, anim = _project()
    with pytest.raises(AnimaiError):
        validate_anim(_with_paint(anim, 0, paint))


def test_paint_is_a_known_frame_key():
    _, _, anim = _project()
    assert not [w for w in validate_anim(_with_paint(anim, 0, [[1, 2, None]])) if "paint" in w]


def test_canvas_grows_to_hold_a_painted_pixel_and_pivot_stays_put():
    rig, rgba, anim = _project()
    base = _render(rig, rgba, anim)
    ox, oy = base.result.origin
    colour = _hex(rgba[rgba[..., 3] > 0][0])
    far = (ox - 5, oy + 3)
    out = _render(rig, rgba, _with_paint(anim, 0, [[far[0], far[1], colour]]))
    nx, ny = out.result.origin
    assert nx == far[0] - out.manifest["padding"]
    assert _hex(out.result.frames[0][far[1] - ny, far[0] - nx]) == colour
    # same pivot in sprite coordinates
    assert (out.result.pivot[0] + nx, out.result.pivot[1] + ny) == (base.result.pivot[0] + ox, base.result.pivot[1] + oy)
    # an erase far away does not grow the canvas
    erased = _render(rig, rgba, _with_paint(anim, 0, [[ox - 50, oy, None]]))
    assert erased.result.canvas == base.result.canvas


def test_retouch_follows_its_frame_through_resampling_and_mirror():
    rig, rgba, anim = _project()
    base = _render(rig, rgba, anim)
    _, (ex, ey) = _opaque_and_empty(base, 1)
    colour = _hex(rgba[rgba[..., 3] > 0][0])
    painted = _with_paint(anim, 1, [[ex, ey, colour]])
    doubled, indices, _ = resample(painted, frames=2 * len(anim["frames"]))
    out = pipeline.render_project(rig, rgba, doubled, indices)
    ox, oy = out.result.origin
    for i, source in enumerate(indices):
        opaque = out.result.frames[i][ey - oy, ex - ox, 3] == 255
        assert ("retouched" in out.manifest["frames"][i]) == (source == 1)
        if source == 1:
            assert opaque and _hex(out.result.frames[i][ey - oy, ex - ox]) == colour
    plain = _render(rig, rgba, painted)
    flipped = _render(rig, rgba, painted, mirror=True)
    assert all(np.array_equal(a[:, ::-1], b) for a, b in zip(plain.result.frames, flipped.result.frames))


def test_qa_still_sees_only_palette_colours_and_binary_alpha():
    rig, rgba, anim = _project()
    base = _render(rig, rgba, anim)
    (px, py), (ex, ey) = _opaque_and_empty(base, 3)
    colour = _hex(rgba[rgba[..., 3] > 0][0])
    out = _render(rig, rgba, _with_paint(anim, 3, [[ex, ey, colour], [px, py, None]]))
    report = qa.validate_frames(out.result.frames, out.manifest)
    checks = {c["id"]: c["pass"] for c in report["checks"] if c.get("frame") in (None, 3)}
    assert checks["palette"] is True and checks["alpha_binary"] is True
