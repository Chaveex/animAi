"""File-level operations shared by the CLI and the server.

Each ``run_*`` function reads project files, calls the pure modules, writes the
outputs and returns a ``Result``. No logic lives in the callers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import control, export, qa, render
from .anim import load_anim, load_preset, retarget
from .errors import AnimaiError, NotImplementedFeature
from .imageio import load_rgba, normalize_rgba, read_json, save_png, write_json
from .rig import build_label_map, cut_parts, load_rig, rest_offsets
from .sprite import extract_palette, is_alpha_binary, opaque_bbox, prepare_sprite, row_segments
from .timing import parse_duration, resample

MANIFEST_NAME = "frames.json"
REPORT_NAME = "report.json"


@dataclass
class Result:
    ok: bool = True
    outputs: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_json(self) -> dict:
        return {"ok": self.ok, "outputs": self.outputs, "warnings": self.warnings, "error": self.error}


def _p(path: Path) -> str:
    return str(Path(path).resolve())


def load_sprite(path: str | Path) -> np.ndarray:
    """Load a *cleaned* sprite; refuses semi-transparent input."""
    rgba = load_rgba(path)
    if not is_alpha_binary(rgba):
        raise AnimaiError(f"{path}: alpha is not strictly 0/255; run 'animai prepare' first")
    return normalize_rgba(rgba)


# ------------------------------------------------------------------ prepare

def palette_document(res: dict) -> dict:
    """Content of palette.json for a ``prepare_sprite`` result."""
    img, palette = res["image"], res["palette"]
    return {
        "version": 1,
        "sprite": "sprite.png",
        "size": [int(img.shape[1]), int(img.shape[0])],
        "bbox": res["bbox"],
        "scale_detected": res["scale"],
        "grid": res.get("grid"),
        "background": res["background"],
        "count": len(palette),
        "colors": [c for c, _ in palette],
        "pixel_counts": [n for _, n in palette],
    }


def run_prepare(input_path: str | Path, out_dir: str | Path | None = None, *, bg: str = "auto",
                bg_mode: str = "flood", bg_tolerance: int = 0, alpha_threshold: int = 128,
                scale: str | int = "auto", max_colors: int | None = None, zoom: int = 8,
                merge_colors: int | None = None) -> Result:
    src = Path(input_path)
    out = Path(out_dir) if out_dir else src.parent / f"{src.stem}.animai"
    source = load_rgba(src)
    res = prepare_sprite(source, bg=bg, bg_mode=bg_mode, bg_tolerance=bg_tolerance,
                         alpha_threshold=alpha_threshold, scale=scale, max_colors=max_colors,
                         merge_colors=merge_colors)
    img = res["image"]
    sprite_path = out / "sprite.png"
    if sprite_path.resolve() == src.resolve():
        raise AnimaiError("output would overwrite the input image; choose another --out directory")
    save_png(sprite_path, img)
    palette = res["palette"]
    write_json(out / "palette.json", palette_document(res))
    save_png(out / "inspect.png", control.inspect_view(img, zoom))
    outputs = {
        "sprite": _p(sprite_path), "palette": _p(out / "palette.json"), "inspect": _p(out / "inspect.png"),
        "size": [int(img.shape[1]), int(img.shape[0])], "bbox": res["bbox"],
        "scale_detected": res["scale"], "background": res["background"],
        "background_pixels_removed": res["removed"], "colors": len(palette),
    }
    grid = res["grid"]
    if grid is not None:      # estimated grid: show it on the source so it can be checked by eye
        save_png(out / "grid.png", control.grid_overlay(source, grid["pitch"], grid["offset"], grid["lines"]))
        outputs["grid"] = {**grid, "image": _p(out / "grid.png")}
    return Result(outputs=outputs, warnings=res["warnings"])


# ------------------------------------------------------------------ inspect

def run_inspect(sprite_path: str | Path, out: str | Path | None = None, *, zoom: int = 8,
                crop: tuple[int, int, int, int] | None = None, segments: bool = False) -> Result:
    src = Path(sprite_path)
    rgba = load_rgba(src)
    warnings = []
    if not is_alpha_binary(rgba):
        warnings.append("alpha is not strictly 0/255: run 'animai prepare' (view shows alpha > 0 as opaque)")
    if out is None:
        target = src.parent / "inspect.png"
    else:
        target = Path(out)
        if target.suffix.lower() != ".png":
            target = target / "inspect.png"
    if target.resolve() == src.resolve():
        raise AnimaiError("output would overwrite the sprite; choose another --out")
    save_png(target, control.inspect_view(rgba, zoom, crop))
    palette = extract_palette(rgba)
    bbox = opaque_bbox(rgba)
    outputs = {
        "inspect": _p(target), "size": [int(rgba.shape[1]), int(rgba.shape[0])],
        "bbox": None if bbox is None else list(bbox), "zoom": zoom, "colors": len(palette),
        "palette": [c for c, _ in palette[:64]],
    }
    if segments:
        outputs["segments"] = row_segments(rgba, crop)
    return Result(outputs=outputs, warnings=warnings)


# ------------------------------------------------------------------ rig

def resolve_sprite_path(rig_path: Path, rig: dict, sprite: str | Path | None) -> Path:
    if sprite:
        return Path(sprite)
    name = rig.get("sprite")
    if not isinstance(name, str) or not name:
        raise AnimaiError("rig.sprite is missing: give --sprite")
    p = Path(name)
    return p if p.is_absolute() else rig_path.parent / p


THIN_PART_PX = 4       # a part narrower than this does not survive a 15 or 30 degree rotation


def rig_diagnostics(rig: dict, rgba: np.ndarray, labelmap, parts: list) -> dict:
    """Facts a rigger wants before animating; none of them is an error.

    ``joints`` (radius followed by the ``holes`` check), ``unmonitored_joints``
    (radius 0: only the joint pixel is checked), ``thin_parts`` (smallest side
    of the part's own pixels under 4 px) and ``outline`` (what the outline pass
    will do, or null).
    """
    radii = qa.joint_radii(rig, parts, rgba.shape[:2])
    thin = {}
    for p in parts:
        ys, xs = np.nonzero(p.own_mask)
        side = int(min(xs.max() - xs.min(), ys.max() - ys.min())) + 1
        if side < THIN_PART_PX:
            thin[p.name] = side
    spec = render.outline_spec(rig, rgba, labelmap)
    return {"joints": radii, "unmonitored_joints": sorted(b for b, r in radii.items() if r == 0),
            "thin_parts": thin,
            "outline": None if spec is None else {"color": f"#{spec.color:06x}", "mode": spec.mode,
                                                  "inner_parts": spec.inner, "source_bare": spec.source_gap,
                                                  "source_border": spec.source_border}}


def rig_report(rig: dict, rgba: np.ndarray, labelmap, parts: list, rest_exact: bool | None = None) -> dict:
    """Content of rig_report.json (also served by the editor server)."""
    if rest_exact is None:
        rest_exact = bool(parts) and bool(np.array_equal(render.render_rest(rgba, rig, parts), rgba))
    return {
        "version": 1,
        "sprite_size": [int(rgba.shape[1]), int(rgba.shape[0])],
        "pivot": list(render.compute_pivot(rgba, rig)),
        "unassigned_count": len(labelmap.unassigned),
        "unassigned": labelmap.unassigned[:500],
        "multi_assigned_count": labelmap.multi_assigned,
        "rest_pose_exact": rest_exact,
        **rig_diagnostics(rig, rgba, labelmap, parts),
        "bones": {n: {"parent": b.get("parent"), "joint": list(b["joint"])} for n, b in rig["bones"].items()},
        "parts": {p.name: {"bone": p.bone, "z": p.z, "pixels": p.own_count,
                           "fill": p.fill, "hidden_pixels": p.extended_count,
                           "missing_pixels": len(p.missing),
                           "bbox": [p.origin[0], p.origin[1], int(p.image.shape[1]), int(p.image.shape[0])]}
                  for p in parts},
    }


def run_rig(sprite_path: str | Path, rig_path: str | Path, out_dir: str | Path | None = None, *,
            zoom: int = 8, labels: str = "names") -> Result:
    rig_file = Path(rig_path)
    rig, warnings = load_rig(rig_file)
    rgba = load_sprite(sprite_path)
    out = Path(out_dir) if out_dir else rig_file.parent / "rig"
    labelmap = build_label_map(rig, rgba)
    warnings += labelmap.warnings
    parts = cut_parts(rig, rgba, labelmap)
    pivot = render.compute_pivot(rgba, rig)

    save_png(out / "rig_overlay.png", control.skeleton_overlay(rgba, rig, zoom, pivot, labels=labels))
    save_png(out / "labelmap.png", control.labelmap_view(rgba, labelmap, rig, zoom))
    outputs = {"overlay": _p(out / "rig_overlay.png"), "labelmap": _p(out / "labelmap.png")}
    parts_dir = out / "parts"
    if parts_dir.is_dir():
        for old in parts_dir.glob("*.png"):
            old.unlink()
    part_files = {}
    for part in parts:
        save_png(parts_dir / f"{part.name}.png", part.image)
        part_files[part.name] = _p(parts_dir / f"{part.name}.png")
    if parts:
        save_png(out / "parts_sheet.png", control.parts_sheet(parts, rig, zoom))
        outputs["parts_sheet"] = _p(out / "parts_sheet.png")
    rest_exact = bool(parts) and bool(np.array_equal(render.render_rest(rgba, rig, parts), rgba))
    if parts and not labelmap.unassigned and not rest_exact:
        warnings.append("rest pose does not reproduce the sprite exactly")

    report = rig_report(rig, rgba, labelmap, parts, rest_exact)
    diagnostics = {k: report[k] for k in ("joints", "unmonitored_joints", "thin_parts", "outline")}
    write_json(out / "rig_report.json", report)
    outputs.update({"report": _p(out / "rig_report.json"), "parts": part_files,
                    "unassigned_count": len(labelmap.unassigned),
                    "multi_assigned_count": labelmap.multi_assigned,
                    "rest_pose_exact": rest_exact, "pivot": list(pivot),
                    "unmonitored_joints": diagnostics["unmonitored_joints"],
                    "thin_parts": diagnostics["thin_parts"], "outline": diagnostics["outline"],
                    "bone_numbers": {n: i for i, n in enumerate(rig["bones"])}})
    return Result(outputs=outputs, warnings=warnings)


# ------------------------------------------------------------------ animate

@dataclass
class Rendered:
    """An animation rendered in memory: what ``animate`` writes, before it is written."""
    result: render.RenderResult
    manifest: dict                 # content of frames.json
    durations: list[int]
    labelmap: object               # rig.LabelMap
    parts: list                    # list[rig.Part]
    warnings: list[str]


def mirror_x(value: int, width: int) -> int:
    return width - 1 - value


def _mirror(result: render.RenderResult, manifest: dict, sprite_width: int) -> None:
    """Flip a rendered animation horizontally, in place, with every coordinate of the manifest.

    Sprite coordinates become those of the mirrored sprite (``x -> width - 1 - x``),
    angles change sign, the pivot (a grid corner) becomes ``canvas width - x``.
    ``result.layers`` keep the unmirrored geometry.
    """
    w = result.canvas[0]
    result.frames = [np.ascontiguousarray(f[:, ::-1]) for f in result.frames]
    result.origin = (sprite_width - (result.origin[0] + w), result.origin[1])
    result.pivot = (w - result.pivot[0], result.pivot[1])
    manifest["origin"] = list(result.origin)
    manifest["pivot"] = list(result.pivot)
    manifest["mirror"] = True
    manifest["rest_offsets"] = {b: [-o[0], o[1]] for b, o in manifest.get("rest_offsets", {}).items()}
    for bone in manifest["rest"]["bones"].values():
        bone["joint"] = [mirror_x(bone["joint"][0], sprite_width), bone["joint"][1]]
    for part in manifest["parts"].values():
        part["missing"] = [[mirror_x(x, sprite_width), y] for x, y in part["missing"]]
    first = manifest["source"].get("unassigned_first")
    if first:
        manifest["source"]["unassigned_first"] = [mirror_x(first[0], sprite_width), first[1]]
    for frame in manifest["frames"]:
        frame["pivot"] = list(result.pivot)
        for pose in frame["bones"].values():
            pose["joint"] = [mirror_x(pose["joint"][0], sprite_width), pose["joint"][1]]
            pose["angle"] = 180 if pose["angle"] in (180, -180) else -pose["angle"]


def render_project(rig: dict, rgba: np.ndarray, anim: dict, source_indices: list[int] | None = None, *,
                   rotation: str = "rotsprite", padding: int = 2, mirror: bool = False,
                   use_rest_offsets: bool | None = None) -> Rendered:
    """Render a (retargeted, resampled) animation and build its ``frames.json`` manifest.

    Single code path for the CLI (``run_animate``) and the server: same frames,
    same manifest. Nothing is read from or written to disk.
    """
    warnings: list[str] = []
    labelmap = build_label_map(rig, rgba)
    warnings += labelmap.warnings
    parts = cut_parts(rig, rgba, labelmap)
    outline = render.outline_spec(rig, rgba, labelmap)
    # Rest offsets: defined in the rig, switched on by the animation (or by the caller).
    if use_rest_offsets is None:
        use_rest_offsets = bool(anim.get("rest_offsets", False))
    offsets = rest_offsets(rig) if use_rest_offsets else {}
    fill_radii = qa.joint_radii(rig, parts, rgba.shape[:2]) if rig.get("fill_holes", True) else None
    result = render.render_animation(rgba, rig, parts, anim, method=rotation, padding=padding, outline=outline,
                                     offsets=offsets, fill_radii=fill_radii)
    warnings += result.warnings
    if source_indices is None:
        source_indices = list(range(len(anim["frames"])))

    name = str(anim.get("name", "anim"))
    durations = [int(f["duration_ms"]) for f in anim["frames"]]
    meta = []
    for i in range(len(result.frames)):
        entry = {"file": f"frame_{i:03d}.png", "duration_ms": durations[i], "pivot": list(result.pivot),
                 "source_frame": source_indices[i], "bones": render.pose_to_json(result.poses[i])}
        if anim["frames"][i].get("z"):
            entry["z"] = anim["frames"][i]["z"]
        if anim["frames"][i].get("label"):
            entry["label"] = anim["frames"][i]["label"]
        meta.append(entry)
    manifest = {
        "version": 1,
        "name": name,
        "loop": bool(anim.get("loop", True)),
        "fps": anim["fps"],
        "duration_ms": sum(durations),
        "canvas": list(result.canvas),
        "origin": list(result.origin),
        "pivot": list(result.pivot),
        "padding": padding,
        "rotation": rotation,
        "mirror": False,
        "outline": None if outline is None else {
            "color": f"#{outline.color:06x}", "mode": outline.mode, "inner_parts": outline.inner,
            "source_bare": outline.source_gap, "source_border": outline.source_border},
        "source": {
            "sprite_size": [int(rgba.shape[1]), int(rgba.shape[0])],
            "palette": sorted(c for c, _ in extract_palette(rgba)),
            **qa.source_stats(rgba),
            "unassigned": len(labelmap.unassigned),
            "unassigned_first": labelmap.unassigned[0] if labelmap.unassigned else None,
            "multi_assigned": labelmap.multi_assigned,
        },
        "rest": {"bones": {n: {"parent": b.get("parent"), "joint": list(b["joint"])}
                           for n, b in rig["bones"].items()}},
        "parts": {p.name: {"bone": p.bone, "z": p.z, "fill": p.fill,
                           "hidden_pixels": p.extended_count, "missing": p.missing} for p in parts},
        "joints": qa.joint_radii(rig, parts, rgba.shape[:2]),
        "joints_rest": qa.joint_rest_radii(rig, parts, rgba.shape[:2]),
        "rest_offsets": offsets,
        "frames": meta,
    }
    detected = render.outline_spec({**rig, "outline": "auto"}, rgba, labelmap)      # what the sprite itself has
    manifest["outline_detected"] = None if detected is None else {
        "color": f"#{detected.color:06x}", "source_bare": detected.source_gap,
        "source_border": detected.source_border}
    if mirror:
        _mirror(result, manifest, int(rgba.shape[1]))
    return Rendered(result, manifest, durations, labelmap, parts, warnings)


def run_animate(rig_path: str | Path, *, preset: str | None = None, keyframes: str | Path | None = None,
                sprite: str | Path | None = None, out_dir: str | Path | None = None,
                duration: str | None = None, frames: int | None = None, fps: float | None = None,
                rotation: str = "rotsprite", padding: int = 2, gif_scale: int = 4,
                mirror: bool = False, use_rest_offsets: bool | None = None) -> Result:
    if (preset is None) == (keyframes is None):
        raise AnimaiError("give exactly one of --preset NAME or --keyframes PATH")
    rig_file = Path(rig_path)
    rig, warnings = load_rig(rig_file)
    rgba = load_sprite(resolve_sprite_path(rig_file, rig, sprite))
    anim, anim_warnings = load_preset(preset) if preset else load_anim(keyframes)
    warnings += anim_warnings
    anim, w = retarget(anim, rig)
    warnings += w
    anim, source_indices, w = resample(
        anim, duration_ms=None if duration is None else parse_duration(duration), frames=frames, fps=fps)
    warnings += w

    rendered = render_project(rig, rgba, anim, source_indices, rotation=rotation, padding=padding,
                              mirror=mirror, use_rest_offsets=use_rest_offsets)
    warnings += rendered.warnings
    result, manifest, durations = rendered.result, rendered.manifest, rendered.durations

    name = manifest["name"]
    out = Path(out_dir) if out_dir else rig_file.parent / "frames" / name
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("frame_*.png"):
        old.unlink()
    stale = out / REPORT_NAME
    if stale.is_file():
        stale.unlink()          # a report describes the frames it was computed on

    files = []
    for i, frame in enumerate(result.frames):
        fname = manifest["frames"][i]["file"]
        save_png(out / fname, frame)
        files.append(_p(out / fname))
    write_json(out / MANIFEST_NAME, manifest)
    save_png(out / "contact_sheet.png", control.contact_sheet(result.frames, durations, result.pivot))
    warnings += export.save_gif(out / "preview.gif", result.frames, durations,
                                loop=manifest["loop"], scale=gif_scale)
    return Result(outputs={
        "frames_dir": _p(out), "manifest": _p(out / MANIFEST_NAME), "frames": files,
        "contact_sheet": _p(out / "contact_sheet.png"), "preview": _p(out / "preview.gif"),
        "name": name, "frame_count": len(files), "duration_ms": sum(durations),
        "durations_ms": durations, "fps": anim["fps"], "loop": manifest["loop"],
        "canvas": list(result.canvas), "pivot": list(result.pivot), "mirror": manifest["mirror"],
        "rest_offsets": manifest["rest_offsets"],
        "outline": manifest["outline"],
    }, warnings=warnings)


# ------------------------------------------------------------------ validate / export

def load_frames(frames_dir: str | Path) -> tuple[dict, list[np.ndarray]]:
    """Read ``frames.json`` and the frame images it lists (no alpha cleaning: QA must see the truth)."""
    d = Path(frames_dir)
    if not d.is_dir():
        raise AnimaiError(f"frames directory not found: {d}")
    manifest = read_json(d / MANIFEST_NAME)
    entries = manifest.get("frames")
    if not isinstance(entries, list) or not entries:
        raise AnimaiError(f"{d / MANIFEST_NAME}: no frames listed")
    return manifest, [load_rgba(d / str(e.get("file"))) for e in entries]


def run_validate(frames_dir: str | Path) -> Result:
    manifest, frames = load_frames(frames_dir)
    report = qa.validate_frames(frames, manifest)
    path = Path(frames_dir) / REPORT_NAME
    write_json(path, report)
    failed = [c["id"] for c in report["checks"] if not c["pass"]]
    failed_ids = [i for i in qa.CHECK_IDS if i in failed]
    warnings = list(report.get("warnings", []))
    if len(frames) > 8:
        warnings.append(f"{len(frames)} frames: more than 8 is hard to read in pixel art")
    return Result(ok=report["ok"], warnings=warnings,
                  outputs={"report": _p(path), "checks": len(report["checks"]), "failed": failed_ids,
                           "metrics": report.get("metrics")},
                  error=None if report["ok"] else "QA failed: " + ", ".join(failed_ids))


def run_export(frames_dir: str | Path, out_dir: str | Path | None = None, *, fmt: str = "spritesheet",
               columns: int | None = None, gif_scale: int = 4, version: str = "0.1.0",
               mirror: bool = False) -> Result:
    if fmt not in export.FORMATS:
        raise AnimaiError(f"unknown format '{fmt}' ({'|'.join(export.FORMATS)})")
    if fmt not in export.IMPLEMENTED_FORMATS:
        raise NotImplementedFeature(f"export format '{fmt}' is not implemented yet (available: spritesheet)")
    d = Path(frames_dir)
    manifest, frames = load_frames(d)
    warnings: list[str] = []
    report_path = d / REPORT_NAME
    if not report_path.is_file():
        warnings.append("frames were not validated: run 'animai validate' before shipping")
    elif not read_json(report_path).get("ok", False):
        warnings.append("QA report is failing: see report.json")
    if any(not is_alpha_binary(f) for f in frames):
        raise AnimaiError("frames contain semi-transparent pixels: refusing to export")

    if mirror:      # flip the frames and the pivot; the frames directory itself is left as it is
        frames = [np.ascontiguousarray(f[:, ::-1]) for f in frames]
        manifest = {**manifest, "pivot": [manifest["canvas"][0] - manifest["pivot"][0], manifest["pivot"][1]],
                    "mirror": not manifest.get("mirror", False)}
    out = Path(out_dir) if out_dir else d / "export"
    name = str(manifest.get("name", "anim"))
    sheet, rects = export.build_spritesheet(frames, columns)
    save_png(out / f"{name}.png", sheet)
    data = export.build_sheet_json(manifest, rects, f"{name}.png",
                                   (int(sheet.shape[1]), int(sheet.shape[0])), version)
    write_json(out / f"{name}.json", data)
    durations = [int(m["duration_ms"]) for m in manifest["frames"]]
    warnings += export.save_gif(out / f"{name}.gif", frames, durations,
                                loop=bool(manifest.get("loop", False)), scale=gif_scale)
    return Result(outputs={
        "spritesheet": _p(out / f"{name}.png"), "json": _p(out / f"{name}.json"),
        "gif": _p(out / f"{name}.gif"), "format": fmt, "frame_count": len(frames),
        "frame_size": list(manifest["canvas"]), "sheet_size": [int(sheet.shape[1]), int(sheet.shape[0])],
        "pivot": list(manifest["pivot"]), "duration_ms": sum(durations),
        "mirror": bool(manifest.get("mirror", False)),
    }, warnings=warnings)
