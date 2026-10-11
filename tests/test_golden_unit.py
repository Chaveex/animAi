"""Unit tests of the golden-image mechanism (in a temp dir). Pass today."""
from __future__ import annotations

import numpy as np
import pytest

from tests import golden


def image(colour=(200, 30, 30), size=(6, 4)) -> np.ndarray:
    data = np.zeros((size[1], size[0], 4), np.uint8)
    data[1:3, 1:4] = (*colour, 255)
    return data


def test_missing_golden_fails_and_tells_how_to_create_it(tmp_path):
    with pytest.raises(golden.GoldenMismatch) as error:
        golden.assert_golden("walk", image(), update=False, golden_dir=tmp_path)
    assert "does not exist" in str(error.value) and golden.UPDATE_OPTION in str(error.value)
    assert not list(tmp_path.iterdir()), "a normal run must never create a golden"


def test_update_writes_then_identical_image_passes(tmp_path):
    path = golden.assert_golden("walk", image(), update=True, golden_dir=tmp_path)
    assert path == tmp_path / "walk.png" and path.is_file()
    assert golden.assert_golden("walk", image(), update=False, golden_dir=tmp_path) == path


def test_single_pixel_difference_fails_and_writes_artifacts(tmp_path):
    golden.assert_golden("walk", image(), update=True, golden_dir=tmp_path / "golden")
    changed = image()
    changed[2, 3] = (200, 30, 31, 255)
    with pytest.raises(golden.GoldenMismatch) as error:
        golden.assert_golden("walk", changed, update=False, golden_dir=tmp_path / "golden",
                             artifacts_dir=tmp_path / "out")
    message = str(error.value)
    assert "1 pixel(s) differ" in message and "first at (3, 2)" in message
    assert (tmp_path / "out" / "walk.actual.png").is_file()
    assert (tmp_path / "out" / "walk.diff.png").is_file()


def test_size_difference_fails(tmp_path):
    golden.assert_golden("walk", image(), update=True, golden_dir=tmp_path)
    with pytest.raises(golden.GoldenMismatch, match="size 7x4 != golden 6x4"):
        golden.assert_golden("walk", image(size=(7, 4)), update=False, golden_dir=tmp_path)


def test_alpha_difference_fails(tmp_path):
    golden.assert_golden("walk", image(), update=True, golden_dir=tmp_path)
    changed = image()
    changed[1, 1, 3] = 254
    with pytest.raises(golden.GoldenMismatch):
        golden.assert_golden("walk", changed, update=False, golden_dir=tmp_path)


def test_rgb_of_fully_transparent_pixels_is_ignored(tmp_path):
    golden.assert_golden("walk", image(), update=True, golden_dir=tmp_path)
    changed = image()
    changed[0, 0] = (9, 9, 9, 0)
    golden.assert_golden("walk", changed, update=False, golden_dir=tmp_path)


def test_update_overwrites_an_existing_golden(tmp_path):
    golden.assert_golden("walk", image(), update=True, golden_dir=tmp_path)
    golden.assert_golden("walk", image((1, 2, 3)), update=True, golden_dir=tmp_path)
    golden.assert_golden("walk", image((1, 2, 3)), update=False, golden_dir=tmp_path)
    with pytest.raises(golden.GoldenMismatch):
        golden.assert_golden("walk", image(), update=False, golden_dir=tmp_path)


@pytest.mark.parametrize("name", ["../escape", "a/b", "", ".hidden", "with space"])
def test_golden_names_cannot_leave_the_golden_dir(tmp_path, name):
    with pytest.raises(ValueError):
        golden.golden_path(name, tmp_path)


def test_compare_and_diff_helpers():
    assert golden.compare_images(image(), image()) is None
    changed = image()
    changed[1, 1] = 0
    assert "1 pixel(s) differ" in golden.compare_images(changed, image())
    diff = golden.diff_image(changed, image())
    assert tuple(diff[1, 1]) == (255, 0, 0, 255) and int((diff[..., 0] == 255).sum()) == 1


def test_update_option_is_registered_and_off_by_default(request):
    assert request.config.getoption(golden.UPDATE_OPTION) in (False, True)
    assert golden.GOLDEN_DIR.name == "golden" and golden.GOLDEN_DIR.parent.name == "tests"
