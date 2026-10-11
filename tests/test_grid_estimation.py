"""Large inputs whose pixel grid is not an integer upscale (resized or AI-generated "pixel art").

``prepare`` must find the grid, bring the sprite back to its real resolution and
leave native-resolution sprites alone.
"""
from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter

from animai.core.sprite import detect_grid, prepare_sprite

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
NAMES = ["hero64", "knight96", "rogue80_outline"]
BIG = 1254


def _fixture(name: str) -> Image.Image:
    return Image.open(FIXTURES / name / "sprite.png").convert("RGBA")


def _on_white(sprite: Image.Image) -> Image.Image:
    bg = Image.new("RGBA", sprite.size, (255, 255, 255, 255))
    bg.alpha_composite(sprite)
    return bg


def _nearest(sprite: Image.Image) -> np.ndarray:
    """Whole canvas resized to 1254 px, nearest neighbour: sharp, pitch not an integer."""
    return np.asarray(sprite.resize((BIG, BIG), Image.NEAREST))


def _ai_like(sprite: Image.Image) -> np.ndarray:
    """Pitch unrelated to the image size, shifted grid, blur, noise and JPEG artefacts."""
    w, h = sprite.size
    pitch = BIG / (max(w, h) + 7.3)
    big = _on_white(sprite).resize((int(w * pitch), int(h * pitch)), Image.NEAREST).convert("RGB")
    canvas = Image.new("RGB", (BIG, BIG), (255, 255, 255))
    canvas.paste(big, (37, 23))
    arr = np.asarray(canvas.filter(ImageFilter.GaussianBlur(1.0))).astype(np.int16)
    noise = np.random.default_rng(1).integers(-4, 5, arr.shape)
    buf = io.BytesIO()
    Image.fromarray(np.clip(arr + noise, 0, 255).astype(np.uint8)).save(buf, "JPEG", quality=88)
    return np.asarray(Image.open(buf).convert("RGBA"))


def _character(rgba: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(rgba[..., 3])
    return rgba[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


@pytest.mark.parametrize("name", NAMES)
def test_sharp_non_integer_upscale_is_recovered_exactly(name):
    sprite = _fixture(name)
    res = prepare_sprite(_nearest(sprite))
    assert res["grid"] is not None
    assert np.array_equal(res["image"], np.asarray(sprite))
    assert any("pixel grid estimated" in w for w in res["warnings"])


@pytest.mark.parametrize("name", NAMES)
def test_blurry_noisy_grid_gives_back_the_drawing(name):
    sprite = np.asarray(_fixture(name))
    res = prepare_sprite(_ai_like(_fixture(name)), bg_tolerance=24)
    got, want = _character(res["image"]), _character(sprite)
    assert got.shape == want.shape, "same character size as the original, in real pixels"
    assert np.array_equal(got[..., 3], want[..., 3]), "same silhouette"
    gap = np.abs(got[..., :3].astype(int) - want[..., :3].astype(int)).max(axis=2)
    assert int(gap[want[..., 3] > 0].max()) <= 24, "every pixel keeps its colour, up to the source noise"
    assert len(res["palette"]) <= len(np.unique(sprite.reshape(-1, 4), axis=0)) + 2, "noise colours merged"


@pytest.mark.parametrize("name", ["hero64", "hero64_x4", "knight96", "mage64x80_bg", "rogue80_outline"])
def test_native_or_integer_upscaled_sources_have_no_estimated_grid(name):
    source = np.asarray(Image.open(FIXTURES / name / "source.png").convert("RGBA"))
    assert prepare_sprite(source)["grid"] is None


def test_flat_rectangle_is_not_a_grid():
    img = np.zeros((300, 300, 4), dtype=np.uint8)
    img[50:250, 60:240] = (200, 40, 40, 255)
    assert detect_grid(img) is None


def test_estimation_is_deterministic():
    src = _ai_like(_fixture("knight96"))
    a, b = prepare_sprite(src, bg_tolerance=24), prepare_sprite(src, bg_tolerance=24)
    assert a["grid"] == b["grid"] and np.array_equal(a["image"], b["image"])


def test_forced_pitch():
    sprite = _fixture("hero64")
    res = prepare_sprite(_nearest(sprite), scale="19.59375")
    assert np.array_equal(res["image"], np.asarray(sprite))


def _drifting(sprite: Image.Image) -> np.ndarray:
    """Pitch drifting slowly between 9.1 and 10.1 px (as on AI-generated images), blur and noise."""
    rng = np.random.default_rng(7)
    src = np.asarray(_on_white(sprite).convert("RGB"))

    def widths(count: int, phase: float) -> np.ndarray:
        edges = np.rint(np.cumsum(9.6 + 0.5 * np.sin(np.arange(count + 1) / 9.0 + phase)))
        return np.diff(edges).astype(int)

    cols = np.repeat(np.arange(src.shape[1]), widths(src.shape[1], 0.0))
    rows = np.repeat(np.arange(src.shape[0]), widths(src.shape[0], 2.0))
    big = Image.fromarray(src[rows][:, cols]).filter(ImageFilter.GaussianBlur(0.8))
    arr = np.asarray(big).astype(np.int16) + rng.integers(-3, 4, (rows.size, cols.size, 3))
    return np.dstack([np.clip(arr, 0, 255).astype(np.uint8), np.full((rows.size, cols.size), 255, np.uint8)])


def _textured(sprite: Image.Image) -> Image.Image:
    """Shading on every pixel, like a detailed drawing: no long stretch without an edge.

    (On flat areas many cells wide a drifting grid cannot be counted: nothing marks the lines.)
    """
    arr = np.asarray(sprite).copy()
    shade = np.random.default_rng(3).choice([0, 40], arr.shape[:2])
    arr[..., :3] = np.clip(arr[..., :3].astype(int) - shade[..., None], 0, 255)
    arr[arr[..., 3] == 0] = 0
    return Image.fromarray(arr)


@pytest.mark.parametrize("name", NAMES)
def test_irregular_grid_is_tracked(name):
    sprite = _textured(_fixture(name))
    want = _character(np.asarray(sprite))
    res = prepare_sprite(_drifting(sprite), merge_colors=0, bg_tolerance=24)
    assert res["grid"] is not None and res["grid"]["regular"] is False
    got = _character(res["image"])
    assert got.shape == want.shape, "one pixel per cell, whatever its width"
    assert np.array_equal(got[..., 3], want[..., 3]), "same silhouette"
    gap = np.abs(got[..., :3].astype(int) - want[..., :3].astype(int)).max(axis=2)
    assert int(gap[want[..., 3] > 0].max()) <= 16
