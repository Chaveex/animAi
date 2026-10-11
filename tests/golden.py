"""Golden images for pixel-perfect non-regression.

Reference PNGs live in ``tests/golden/``. A test calls the ``golden`` fixture
(see conftest.py)::

    golden("hero64__walk", spritesheet_array)

* normal run: the image must match the stored golden exactly (size + every
  pixel; the RGB of fully transparent pixels is ignored). A missing golden is
  a **failure**, never a skip.
* ``pytest --update-golden``: the stored golden is (re)written instead of
  compared. Only do it after looking at the new images; the diff shows up in
  review as changed PNG files.

On mismatch the actual image and a red/grey diff are written next to the
test's tmp dir and their paths are part of the assertion message.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from PIL import Image

from tests.invariants import as_rgba, canonical

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
UPDATE_OPTION = "--update-golden"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")


class GoldenMismatch(AssertionError):
    pass


def golden_path(name: str, golden_dir: Path = GOLDEN_DIR) -> Path:
    if not _SAFE_NAME.match(name):
        raise ValueError(f"invalid golden name {name!r}")
    return Path(golden_dir) / f"{name}.png"


def compare_images(actual, expected) -> str | None:
    """None when identical, else a one-line description of the first difference."""
    a, e = canonical(actual), canonical(expected)
    if a.shape != e.shape:
        return f"size {a.shape[1]}x{a.shape[0]} != golden {e.shape[1]}x{e.shape[0]}"
    different = (a != e).any(axis=2)
    count = int(different.sum())
    if count == 0:
        return None
    ys, xs = np.nonzero(different)
    x, y = int(xs[0]), int(ys[0])
    return (f"{count} pixel(s) differ; first at ({x}, {y}): "
            f"got {tuple(int(v) for v in a[y, x])}, golden {tuple(int(v) for v in e[y, x])}")


def diff_image(actual, expected) -> np.ndarray:
    """Golden in dim grey, differing pixels in opaque red (same size only)."""
    a, e = canonical(actual), canonical(expected)
    out = np.zeros_like(e)
    out[..., :3] = 60
    out[..., 3] = 255
    out[e[..., 3] > 0, :3] = 140
    if a.shape == e.shape:
        out[(a != e).any(axis=2)] = (255, 0, 0, 255)
    return out


def assert_golden(name: str, image, *, update: bool, golden_dir: Path = GOLDEN_DIR,
                  artifacts_dir: Path | None = None) -> Path:
    """Compare ``image`` with the golden ``name`` (or write it when ``update``)."""
    actual = canonical(as_rgba(image))
    path = golden_path(name, golden_dir)
    if update:
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(actual, "RGBA").save(path, format="PNG")
        return path
    if not path.is_file():
        raise GoldenMismatch(
            f"golden image '{name}' does not exist ({path}). Review the output, then "
            f"create it with: pytest {UPDATE_OPTION}")
    problem = compare_images(actual, as_rgba(path))
    if problem is None:
        return path
    message = f"golden '{name}' mismatch: {problem}"
    if artifacts_dir is not None:
        artifacts_dir = Path(artifacts_dir)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        actual_path = artifacts_dir / f"{name}.actual.png"
        diff_path = artifacts_dir / f"{name}.diff.png"
        Image.fromarray(actual, "RGBA").save(actual_path)
        Image.fromarray(diff_image(actual, as_rgba(path)), "RGBA").save(diff_path)
        message += f"\n  actual: {actual_path}\n  diff:   {diff_path}\n  golden: {path}"
    message += f"\n  if the change is intended: pytest {UPDATE_OPTION}"
    raise GoldenMismatch(message)
