"""The ONLY place that knows how the ``animai`` CLI is spelled.

Since wave 2, docs/schemas.md ("Sortie CLI", "Fichiers produits") fixes almost
everything this module needs. What it reads from the contract:

  * stdout = exactly one JSON object {"ok", "outputs", "warnings", "error"};
    return code 0 = ok, 1 = user error (usage errors and a failing QA
    included), 2 = not implemented / internal
  * arguments, options and ``outputs`` keys of each command (table of
    "Sortie CLI"); paths in ``outputs`` are absolute
  * ``validate`` has no ``--out``: it writes ``report.json`` in the frames dir
  * ``frames.json`` (key ``manifest``) and the Aseprite-array export JSON with
    the pivot under ``meta.animai.pivot``
  * ``rig.sprite`` is relative to the rig file; ``rot`` > 0 is anti-clockwise

History of the wave 1 assumptions H1..H11: H2, H3 (now stricter: absolute
only), H4, H5, H6, H8, H9, H10 (sign now fixed: tests no longer accept both)
and H11 became contract and are enforced as such. None contradicts it.

REMAINING ASSUMPTIONS (not written in docs/schemas.md)
  H1  Entry point: ``python -m animai.cli.main`` (same as the ``animai`` script).
  H7  ``prepare`` never crops: the cleaned sprite keeps the full canvas of the
      real pixel grid (the contract only shows ``size`` and ``bbox`` as two
      distinct values in palette.json, which suggests it).
  H12 The frames cut from the exported sheet are the frames of ``frames.json``
      unchanged (same canvas, same order), so the manifest applies to them.
  H13 Ground-line policy per preset (docs/animation-guide.md D5, D7, 5.3), see
      ``ground_tolerances``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from tests import contract, invariants
from tests.invariants import as_rgba

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_COMMAND = [sys.executable, "-m", "animai.cli.main"]          # H1
OUT_FLAG = "--out"
NO_OUT_COMMANDS = ("validate",)
TIMEOUT_S = 180
COMMANDS = ("prepare", "inspect", "rig", "animate", "validate", "export")
MVP_PRESETS = ("idle", "walk", "attack")
LOOPING_PRESETS = ("idle", "walk")
ATTACK_REST_SOURCE_FRAMES = (0, 1, 5, 6)   # guide D7: feet identical to the rest pose

KEY_SPRITE, KEY_PALETTE = "sprite", "palette"
KEY_INSPECT_IMAGE = "inspect"
KEY_OVERLAY, KEY_LABEL_MAP, KEY_RIG_REPORT = "overlay", "labelmap", "report"
KEY_FRAMES, KEY_FRAMES_DIR, KEY_MANIFEST = "frames", "frames_dir", "manifest"
KEY_CONTACT_SHEET = "contact_sheet"
KEY_REPORT = "report"
KEY_SHEET, KEY_SHEET_JSON, KEY_GIF = "spritesheet", "json", "gif"


def ground_tolerances(preset: str, manifest: dict) -> list[int]:
    """Allowed distance (px) between the lowest pixels and the ground line, per frame (H13).

    * idle: 0 (guide D3: pelvis, legs and feet strictly still)
    * walk: 1 (guide D5: same lowest row on all frames, +/- 1 px)
    * attack: 0 on the frames whose pose has the feet at rest (source frames
      0, 1, 5, 6: guide D7), 1 on the lunge frames (same geometry as the walk
      contact, guide 5.3)
    """
    frames = manifest["frames"]
    if preset == "idle":
        return [0] * len(frames)
    if preset == "walk":
        return [1] * len(frames)
    if preset == "attack":
        return [0 if f["source_frame"] in ATTACK_REST_SOURCE_FRAMES else 1 for f in frames]
    raise ValueError(f"no ground-line policy for preset {preset!r}")


def animation_violations(frames, palette, manifest: dict) -> list:
    """Every tester invariant that docs/schemas.md defines, for frames described by ``manifest``:
    canvas, alpha, palette, orphans, holes (by cause), pivot, and loop when the animation loops."""
    return invariants.check_frames(frames, palette, manifest=manifest, loop=manifest["loop"],
                                   source_orphans=manifest["source"]["orphans"])


def ground_violations(frames, manifest: dict, preset: str) -> list:
    """Ground line (pivot y) against the per-preset policy of ``ground_tolerances``."""
    return invariants.check_ground_line(frames, manifest["pivot"][1], ground_tolerances(preset, manifest))


class CliContractError(AssertionError):
    """The CLI answered something the contract does not allow."""


@dataclass
class CliResult:
    args: list[str]
    cwd: Path
    out_dir: Path | None
    returncode: int
    stdout: str
    stderr: str
    payload: dict | None = None
    parse_error: str | None = None

    def describe(self) -> str:
        return (f"$ animai {' '.join(self.args)}\n  return code: {self.returncode}\n"
                f"  stdout: {self.stdout.strip()[:800]!r}\n  stderr: {self.stderr.strip()[-800:]!r}")

    @property
    def command(self) -> str | None:
        return self.args[0] if self.args and self.args[0] in COMMANDS else None

    # -- contract ---------------------------------------------------------- #
    def assert_contract(self) -> "CliResult":
        """stdout is one contract-conforming JSON object, rc consistent with ok."""
        if self.payload is None:
            raise CliContractError(f"stdout is not a single JSON object ({self.parse_error})\n"
                                   + self.describe())
        problems = contract.validate_cli_payload(self.payload)
        if self.returncode not in contract.RETURN_CODES:
            problems.append(f"return code {self.returncode} not in {contract.RETURN_CODES}")
        elif isinstance(self.payload.get("ok"), bool) and self.payload["ok"] != (self.returncode == 0):
            problems.append(f"ok={self.payload['ok']} inconsistent with return code {self.returncode}")
        if problems:
            raise CliContractError("CLI output violates docs/schemas.md: " + "; ".join(problems)
                                   + "\n" + self.describe())
        return self

    def expect_ok(self) -> "CliResult":
        """Success, with every ``outputs`` key the contract lists for the command."""
        if self.returncode != 0:
            raise CliContractError("command failed, expected success\n" + self.describe())
        self.assert_contract()
        if self.command:
            missing = contract.missing_output_keys(self.command, self.payload["outputs"])
            if missing:
                raise CliContractError(f"outputs of '{self.command}' lacks contract key(s) {missing}\n"
                                       + self.describe())
        return self

    def expect_user_error(self) -> "CliResult":
        """Clean failure: rc 1, JSON object, ok false, readable error, no traceback."""
        if self.returncode != 1:
            raise CliContractError(
                f"expected a user error (return code 1), got {self.returncode}\n" + self.describe())
        self.assert_contract()
        if "Traceback (most recent call last)" in self.stderr + self.stdout:
            raise CliContractError("user error leaked a Python traceback\n" + self.describe())
        return self

    # -- outputs ----------------------------------------------------------- #
    @property
    def warnings(self) -> list[str]:
        return list(self.payload["warnings"])

    def resolve(self, value) -> Path:
        path = Path(value)
        if not path.is_absolute():
            raise CliContractError(f"output path {value!r} is not absolute (docs/schemas.md)\n"
                                   + self.describe())
        if not path.exists():
            raise CliContractError(f"output path {value!r} does not exist\n" + self.describe())
        return path

    def output(self, key: str):
        outputs = self.payload["outputs"]
        if key not in outputs:
            raise CliContractError(
                f"outputs has no '{key}' key (have: {sorted(outputs)})\n" + self.describe())
        return outputs[key]

    def path(self, key: str) -> Path:
        value = self.output(key)
        if not isinstance(value, str):
            raise CliContractError(f"outputs['{key}'] should be a path string, got {value!r}")
        path = self.resolve(value)
        if not path.is_file():
            raise CliContractError(f"outputs['{key}'] = {value!r} is not a file")
        return path

    def json(self, key: str):
        path = self.path(key)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise CliContractError(f"outputs['{key}'] ({path}) is not valid JSON: {error}")

    def image(self, key: str) -> np.ndarray:
        return as_rgba(self.path(key))

    # -- animate ----------------------------------------------------------- #
    def frame_paths(self) -> list[Path]:
        value = self.output(KEY_FRAMES)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise CliContractError(f"outputs['{KEY_FRAMES}'] must be the ordered list of frame paths")
        if not value:
            raise CliContractError("animate produced no frame\n" + self.describe())
        return [self.resolve(v) for v in value]

    def frames(self) -> list[np.ndarray]:
        return [as_rgba(p) for p in self.frame_paths()]

    def frames_dir(self) -> Path:
        directory = self.resolve(self.output(KEY_FRAMES_DIR))
        if not directory.is_dir():
            raise CliContractError(f"outputs['{KEY_FRAMES_DIR}'] is not a directory")
        strays = [p for p in self.frame_paths() if p.parent != directory]
        if strays:
            raise CliContractError(f"frames outside outputs['{KEY_FRAMES_DIR}']: {strays}")
        return directory

    def manifest(self) -> dict:
        """``frames.json``, checked against docs/schemas.md."""
        manifest = self.json(KEY_MANIFEST)
        problems = contract.validate_frames_manifest(manifest)
        if not problems:
            listed = [f["file"] for f in manifest["frames"]]
            actual = [p.name for p in self.frame_paths()]
            if listed != actual:
                problems.append(f"frames {listed} differ from outputs['{KEY_FRAMES}'] {actual}")
        if problems:
            raise CliContractError("frames.json violates docs/schemas.md: " + "; ".join(problems[:8]))
        return manifest

    anim = manifest     # timing view: name, loop, fps, frames[].duration_ms


def run(args, cwd: Path, out_dir: Path | None = None) -> CliResult:
    """Run ``animai <args>`` in a subprocess. Never raises on CLI failure."""
    args = [str(a) for a in args]
    if out_dir is not None and args and args[0] not in NO_OUT_COMMANDS:
        args += [OUT_FLAG, str(out_dir)]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO_ROOT)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONHASHSEED", None)
    completed = subprocess.run(
        BASE_COMMAND + args, cwd=str(cwd), env=env, capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
    result = CliResult(args, Path(cwd), Path(out_dir) if out_dir else None,
                       completed.returncode, completed.stdout, completed.stderr)
    try:
        payload = json.loads(completed.stdout)
        if isinstance(payload, dict):
            result.payload = payload
        else:
            result.parse_error = f"top-level JSON is {type(payload).__name__}, not an object"
    except ValueError as error:
        result.parse_error = str(error)
    return result


# --------------------------------------------------------------------------- #
# One function per command
# --------------------------------------------------------------------------- #

def prepare(sprite, out_dir, cwd) -> CliResult:
    return run(["prepare", sprite], cwd, out_dir)


def inspect(sprite, out_dir, cwd, *, segments=False, crop=None) -> CliResult:
    args = ["inspect", sprite]
    if segments:
        args.append("--segments")
    if crop is not None:
        args += ["--crop", ",".join(str(v) for v in crop)]
    return run(args, cwd, out_dir)


def rig(sprite, rig_json, out_dir, cwd, *, labels=None) -> CliResult:
    args = ["rig", sprite, rig_json]
    if labels is not None:
        args += ["--labels", labels]
    return run(args, cwd, out_dir)


def timing_args(duration=None, frames=None, fps=None) -> list[str]:
    args = []
    if duration is not None:
        args += ["--duration", str(duration)]
    if frames is not None:
        args += ["--frames", str(frames)]
    if fps is not None:
        args += ["--fps", str(fps)]
    return args


def animate(rig_json, out_dir, cwd, *, preset=None, keyframes=None,
            duration=None, frames=None, fps=None, mirror=False) -> CliResult:
    args = ["animate", rig_json]
    if preset is not None:
        args += ["--preset", preset]
    if keyframes is not None:
        args += ["--keyframes", keyframes]
    if mirror:
        args.append("--mirror")
    return run(args + timing_args(duration, frames, fps), cwd, out_dir)


def validate(frames_dir, cwd) -> CliResult:
    return run(["validate", frames_dir], cwd)


def export(frames_dir, out_dir, cwd, fmt="spritesheet", *, mirror=False) -> CliResult:
    return run(["export", frames_dir, "--format", fmt] + (["--mirror"] if mirror else []), cwd, out_dir)


def report(validate_result: CliResult) -> dict:
    """report.json of a ``validate`` run, checked against docs/schemas.md (metrics included)."""
    document = validate_result.json(KEY_REPORT)
    problems = contract.validate_report(document, require_metrics=True)
    if problems:
        raise CliContractError("report.json violates docs/schemas.md: " + "; ".join(problems[:8]))
    return document


# --------------------------------------------------------------------------- #
# Export JSON (docs/schemas.md, "Export --format spritesheet")
# --------------------------------------------------------------------------- #

@dataclass
class SheetLayout:
    rects: list[tuple[int, int, int, int]]      # (x, y, w, h) per frame, playback order
    durations_ms: list[float]
    pivots: list[tuple[int, int]]               # the one exported pivot, repeated per frame
    frame_size: tuple[int, int]
    loop: bool
    mirror: bool = False


def parse_sheet_json(document) -> SheetLayout:
    def fail(message):
        raise CliContractError(f"export JSON violates docs/schemas.md: {message}")

    if not isinstance(document, dict) or not isinstance(document.get("frames"), list):
        fail("'frames' must be an array (Aseprite array format)")
    if not document["frames"]:
        fail("no frame listed")
    info = (document.get("meta") or {}).get("animai")
    if not isinstance(info, dict):
        fail("'meta.animai' is missing")
    pivot, size = info.get("pivot"), info.get("frame_size")
    for name, value, keys in (("pivot", pivot, ("x", "y")), ("frame_size", size, ("w", "h"))):
        if not isinstance(value, dict) or not all(
                isinstance(value.get(k), int) and not isinstance(value.get(k), bool) for k in keys):
            fail(f"'meta.animai.{name}' must be {{{', '.join(keys)}}} integers, got {value!r}")
    if not isinstance(info.get("loop"), bool):
        fail("'meta.animai.loop' must be a boolean")
    rects, durations = [], []
    for index, entry in enumerate(document["frames"]):
        try:
            box = entry["frame"]
            rects.append((int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"])))
            durations.append(float(entry["duration"]))
        except (KeyError, TypeError, ValueError) as error:
            fail(f'frame {index} is not {{"frame": {{x,y,w,h}}, "duration": ms}}: {error!r}')
        if rects[-1][2:] != (size["w"], size["h"]):
            fail(f"frame {index} is {rects[-1][2:]}, meta.animai.frame_size says {(size['w'], size['h'])}")
    if not isinstance(info.get("mirror"), bool):
        fail("'meta.animai.mirror' must be a boolean")
    return SheetLayout(rects, durations, [(pivot["x"], pivot["y"])] * len(rects),
                       (size["w"], size["h"]), info["loop"], info["mirror"])


def cut_sheet(sheet: np.ndarray, layout: SheetLayout) -> list[np.ndarray]:
    height, width = sheet.shape[:2]
    frames = []
    for index, (x, y, w, h) in enumerate(layout.rects):
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise CliContractError(f"export JSON frame {index} rect {(x, y, w, h)} "
                                   f"is outside the {width}x{height} sheet")
        frames.append(sheet[y:y + h, x:x + w])
    return frames


def gif_frames(path: Path) -> tuple[list[np.ndarray], list[int]]:
    """Frames (RGBA) and per-frame durations (ms) of a GIF/APNG preview."""
    frames, durations = [], []
    with Image.open(path) as image:
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            frames.append(np.array(image.convert("RGBA"), dtype=np.uint8))
            durations.append(int(image.info.get("duration", 0)))
    return frames, durations


# --------------------------------------------------------------------------- #
# Whole chain
# --------------------------------------------------------------------------- #

@dataclass
class Chain:
    workdir: Path
    project: Path                       # holds sprite.png + rig.json (the "project files")
    steps: dict[str, CliResult] = field(default_factory=dict)

    def __getitem__(self, step: str) -> CliResult:
        return self.steps[step]

    def exported_frames(self) -> tuple[list[np.ndarray], SheetLayout]:
        layout = parse_sheet_json(self["export"].json(KEY_SHEET_JSON))
        return cut_sheet(self["export"].image(KEY_SHEET), layout), layout


def run_chain(source_png: Path, rig_json: Path, workdir: Path, *, preset: str = "walk",
              duration=None, frames=8, fps=10) -> Chain:
    """prepare -> inspect -> rig -> animate -> validate -> export.

    Every step must succeed, except that a red QA verdict from ``validate``
    does not stop the chain: the verdict is asserted by its own test, so that
    export, determinism and golden checks still report independently.
    """
    workdir = Path(workdir)
    project = workdir / "project"
    project.mkdir(parents=True, exist_ok=True)
    chain = Chain(workdir, project)

    chain.steps["prepare"] = prepare(source_png, workdir / "prepare", workdir).expect_ok()
    sprite = project / "sprite.png"
    sprite.write_bytes(chain["prepare"].path(KEY_SPRITE).read_bytes())
    rig_copy = project / "rig.json"
    rig_copy.write_bytes(Path(rig_json).read_bytes())

    chain.steps["inspect"] = inspect(sprite, workdir / "inspect", workdir).expect_ok()
    chain.steps["rig"] = rig(sprite, rig_copy, workdir / "rig", workdir).expect_ok()
    chain.steps["animate"] = animate(
        rig_copy, workdir / "frames", workdir, preset=preset,
        duration=duration, frames=frames, fps=fps).expect_ok()
    frames_dir = chain["animate"].frames_dir()
    chain.steps["validate"] = validate(frames_dir, workdir).assert_contract()
    chain["validate"].path(KEY_REPORT)
    chain.steps["export"] = export(frames_dir, workdir / "export", workdir).expect_ok()
    return chain
