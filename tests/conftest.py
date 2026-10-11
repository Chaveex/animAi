"""Shared pytest configuration: fixtures on disk, golden option, chain cache."""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fixtures import make_fixtures  # noqa: E402
from tests import cli_adapter, golden as golden_module  # noqa: E402
from tests.invariants import as_rgba, palette_of  # noqa: E402

FIXTURES_DIR = REPO_ROOT / "fixtures"
FIXTURE_NAMES = make_fixtures.FIXTURE_NAMES


def pytest_addoption(parser):
    parser.addoption(
        golden_module.UPDATE_OPTION, action="store_true", default=False,
        help="rewrite tests/golden/*.png from the current output instead of comparing")


def _missing_server_modules() -> list[str]:
    import importlib
    missing = []
    for name in ("fastapi", "python_multipart", "uvicorn", "httpx"):
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    return missing


SERVER_EXTRA_MISSING = _missing_server_modules()
_SERVER_NOTICE = ("SERVER TESTS NOT RUN: tests/test_server.py needs the `server` extra and httpx "
                  "(missing: {}). Install with `pip install -e .[server,dev]`. "
                  "The editor server is NOT covered by this run.")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: runs the real `animai` CLI in a subprocess (needs the lead dev's core)")
    config.addinivalue_line(
        "markers", "server: editor server tests (need the `server` extra and httpx)")


def pytest_report_header(config):
    if SERVER_EXTRA_MISSING:
        return _SERVER_NOTICE.format(", ".join(SERVER_EXTRA_MISSING))
    return "animai server extra: installed, tests/test_server.py will run"


def pytest_terminal_summary(terminalreporter):
    if SERVER_EXTRA_MISSING:
        terminalreporter.section("server tests not run", sep="!", red=True, bold=True)
        terminalreporter.write_line(_SERVER_NOTICE.format(", ".join(SERVER_EXTRA_MISSING)), red=True)


@dataclass(frozen=True)
class FixtureCase:
    name: str
    directory: Path
    source: Path          # raw input for `prepare`
    sprite: Path          # expected cleaned sprite (what rig.json refers to)
    rig_path: Path
    rig: dict
    meta: dict

    @property
    def palette(self) -> frozenset:
        return frozenset(tuple(c) for c in self.meta["palette"])

    @property
    def native_size(self) -> tuple[int, int]:
        return tuple(self.meta["native_size"])

    def sprite_rgba(self):
        return as_rgba(self.sprite)


def load_case(name: str) -> FixtureCase:
    directory = FIXTURES_DIR / name
    case = FixtureCase(
        name=name,
        directory=directory,
        source=directory / "source.png",
        sprite=directory / "sprite.png",
        rig_path=directory / "rig.json",
        rig=json.loads((directory / "rig.json").read_text(encoding="utf-8")),
        meta=json.loads((directory / "meta.json").read_text(encoding="utf-8")),
    )
    assert palette_of(case.sprite) == case.palette, f"{name}: meta.json palette is stale"
    return case


@pytest.fixture(params=FIXTURE_NAMES)
def case(request) -> FixtureCase:
    """Every reference sprite in turn."""
    return load_case(request.param)


@pytest.fixture
def hero() -> FixtureCase:
    """The plain 64x64 sprite, for tests that need just one."""
    return load_case("hero64")


@pytest.fixture
def golden(request, tmp_path):
    """``golden(name, image)``: compare with tests/golden/<name>.png (or update it)."""
    update = request.config.getoption(golden_module.UPDATE_OPTION)

    def check(name: str, image):
        return golden_module.assert_golden(
            name, image, update=update, artifacts_dir=tmp_path / "golden_failures")
    return check


@pytest.fixture(scope="session")
def chain_for(tmp_path_factory):
    """``chain_for(fixture_name, preset)`` -> finished Chain (8 frames @ 10 fps).

    One real run per (fixture, preset) for the whole session. A failing chain
    is re-raised in every test that asks for it: nothing is skipped.
    """
    cache: dict[tuple[str, str], object] = {}

    def get(name: str, preset: str) -> cli_adapter.Chain:
        key = (name, preset)
        if key not in cache:
            fixture_case = load_case(name)
            workdir = tmp_path_factory.mktemp(f"chain_{name}_{preset}")
            try:
                cache[key] = cli_adapter.run_chain(
                    fixture_case.source, fixture_case.rig_path, workdir, preset=preset)
            except Exception as error:  # noqa: BLE001 - cached, re-raised below
                cache[key] = error
        if isinstance(cache[key], Exception):
            raise cache[key]
        return cache[key]
    return get


def make_project(directory: Path, fixture_case: FixtureCase, mutate=None) -> Path:
    """Project dir with the cleaned sprite and (a possibly mutated copy of) the fixture rig."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture_case.sprite, directory / "sprite.png")
    rig = json.loads(json.dumps(fixture_case.rig))
    if mutate is not None:
        mutate(rig)
    (directory / "rig.json").write_text(json.dumps(rig, indent=2), encoding="utf-8")
    return directory


def write_anim(path: Path, frames, *, name="custom", loop=False, fps=10, **extra) -> Path:
    """Write an anim.json (docs/schemas.md) and return its path."""
    document = {"version": 1, "name": name, "loop": loop, "fps": fps, "frames": frames, **extra}
    Path(path).write_text(json.dumps(document), encoding="utf-8")
    return Path(path)


def preset_document(name: str) -> dict:
    return json.loads((REPO_ROOT / "animai" / "presets" / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def project(tmp_path, hero):
    """A scratch project dir (sprite.png + rig.json of hero64) and a cwd for the CLI."""
    directory = tmp_path / "project"
    directory.mkdir()
    shutil.copyfile(hero.sprite, directory / "sprite.png")
    shutil.copyfile(hero.rig_path, directory / "rig.json")
    return directory
