"""Export: spritesheet PNG, Aseprite-compatible JSON (tags/durations), GIF preview."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .errors import AnimaiError
from .sprite import pack_rgb

FORMATS = ("spritesheet", "godot", "phaser", "unity")
IMPLEMENTED_FORMATS = ("spritesheet",)


def build_spritesheet(frames: list[np.ndarray], columns: int | None = None
                      ) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """Pack same-size frames in a grid (row-major, no spacing).

    Returns the RGBA sheet and one ``(x, y, w, h)`` per frame. Default: one row.
    """
    if not frames:
        raise AnimaiError("no frame to export")
    h, w = frames[0].shape[:2]
    if any(f.shape[:2] != (h, w) for f in frames):
        raise AnimaiError("frames have different sizes: cannot build a spritesheet")
    n = len(frames)
    cols = n if columns is None else columns
    if cols < 1:
        raise AnimaiError("--columns must be >= 1")
    cols = min(cols, n)
    rows = -(-n // cols)
    sheet = np.zeros((rows * h, cols * w, 4), dtype=np.uint8)
    rects = []
    for i, f in enumerate(frames):
        x, y = (i % cols) * w, (i // cols) * h
        sheet[y:y + h, x:x + w] = f
        rects.append((x, y, w, h))
    return sheet, rects


def build_sheet_json(manifest: dict, rects: list[tuple[int, int, int, int]], image_name: str,
                     sheet_size: tuple[int, int], version: str = "0.1.0") -> dict:
    """Aseprite-compatible "array" JSON, with animai extras under ``meta.animai``."""
    name = manifest.get("name", "anim")
    meta_frames = manifest["frames"]
    w, h = manifest["canvas"]
    px, py = manifest["pivot"]
    frames = []
    for i, (rect, m) in enumerate(zip(rects, meta_frames)):
        frames.append({
            "filename": f"{name} {i}",
            "frame": {"x": rect[0], "y": rect[1], "w": rect[2], "h": rect[3]},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h},
            "sourceSize": {"w": w, "h": h},
            "duration": int(m["duration_ms"]),
        })
    total = sum(int(m["duration_ms"]) for m in meta_frames)
    return {
        "frames": frames,
        "meta": {
            "app": "animai",
            "version": version,
            "image": image_name,
            "format": "RGBA8888",
            "size": {"w": sheet_size[0], "h": sheet_size[1]},
            "scale": "1",
            "frameTags": [{"name": name, "from": 0, "to": len(frames) - 1, "direction": "forward"}],
            "animai": {
                "name": name,
                "loop": bool(manifest.get("loop", False)),
                "fps": manifest.get("fps"),
                "duration_ms": total,
                "frame_size": {"w": w, "h": h},
                "pivot": {"x": px, "y": py},
                "pivot_normalized": {"x": round(px / w, 6), "y": round(py / h, 6)},
                "mirror": bool(manifest.get("mirror", False)),
            },
        },
    }


def _unused_color(palette: set[int]) -> int:
    for candidate in (0xFF00FF, 0x00FF00, 0x00FFFF):
        if candidate not in palette:
            return candidate
    v = 0
    while v in palette:
        v += 1
    return v


def save_gif(path: str | Path, frames: list[np.ndarray], durations_ms: list[int], *,
             loop: bool = True, scale: int = 4) -> list[str]:
    """Write an animated GIF with exact colours and 1-bit transparency (NN upscale).

    GIF limits: at most 255 colours + transparency (otherwise the preview is
    quantized, with a warning) and durations stored in 1/100 s.
    Returns warnings.
    """
    if scale < 1:
        raise AnimaiError("--gif-scale must be >= 1")
    if len(frames) != len(durations_ms):
        raise AnimaiError("one duration per frame is required")
    warnings: list[str] = []
    colors: set[int] = set()
    for f in frames:
        colors.update(np.unique(pack_rgb(f)[f[..., 3] > 0]).tolist())
    ordered = sorted(colors)

    if len(ordered) <= 255:
        key = _unused_color(colors)
        table = np.array([key] + ordered, dtype=np.uint32)          # index 0 = transparent
        lookup = np.array(ordered, dtype=np.uint32)
        flat = []
        for v in table.tolist():
            flat += [(v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF]
        flat += [0] * (768 - len(flat))
        images = []
        for f in frames:
            idx = (np.searchsorted(lookup, pack_rgb(f)) + 1).astype(np.uint8)
            idx[f[..., 3] == 0] = 0
            if scale > 1:
                idx = np.repeat(np.repeat(idx, scale, axis=0), scale, axis=1)
            im = Image.fromarray(idx, "P")
            im.putpalette(flat)
            images.append(im)
    else:
        warnings.append(f"{len(ordered)} colours: GIF preview quantized to 255 (preview only)")
        images = []
        for f in frames:
            im = Image.fromarray(f, "RGBA")
            if scale > 1:
                im = im.resize((im.width * scale, im.height * scale), Image.Resampling.NEAREST)
            alpha = np.array(im)[..., 3] == 0
            q = im.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT,
                                           dither=Image.Dither.NONE)
            idx = np.array(q, dtype=np.uint8) + 1
            idx[alpha] = 0
            pal = [0, 0, 0] + list(q.getpalette()[:765])
            out = Image.fromarray(idx, "P")
            out.putpalette(pal)
            images.append(out)

    # Round on the cumulative timeline so the total duration does not drift.
    rounded, acc, prev = [], 0, 0
    for d in durations_ms:
        acc += int(d)
        cur = (acc + 5) // 10 * 10
        rounded.append(max(20, cur - prev))
        prev = max(cur, prev + 20)
    if rounded != [int(d) for d in durations_ms]:
        warnings.append(f"GIF durations rounded to 10 ms steps (min 20 ms): {rounded}")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    kwargs = dict(format="GIF", save_all=True, append_images=images[1:], duration=rounded,
                  transparency=0, disposal=2, optimize=False)
    if loop:
        kwargs["loop"] = 0
    images[0].save(p, **kwargs)
    return warnings
