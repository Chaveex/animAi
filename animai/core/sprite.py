"""Sprite loading/cleaning: binary alpha, background removal, real pixel scale, palette."""
from __future__ import annotations

from functools import reduce
from math import gcd

import numpy as np
from PIL import Image

from .errors import AnimaiError
from .imageio import normalize_rgba
from .morph import border_mask, flood


# ---------------------------------------------------------------- colours

def pack_rgb(rgba: np.ndarray) -> np.ndarray:
    """``(H, W)`` uint32 array of ``0xRRGGBB`` (alpha ignored)."""
    a = rgba.astype(np.uint32)
    return (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]


def pack_rgba(rgba: np.ndarray) -> np.ndarray:
    """``(H, W)`` uint32 array; every transparent pixel packs to 0."""
    a = rgba.astype(np.uint32)
    packed = (a[..., 3] << 24) | (a[..., 0] << 16) | (a[..., 1] << 8) | a[..., 2]
    packed[rgba[..., 3] == 0] = 0
    return packed


def unpack_rgba(packed: np.ndarray) -> np.ndarray:
    out = np.empty(packed.shape + (4,), dtype=np.uint8)
    out[..., 0] = (packed >> 16) & 0xFF
    out[..., 1] = (packed >> 8) & 0xFF
    out[..., 2] = packed & 0xFF
    out[..., 3] = (packed >> 24) & 0xFF
    return out


def hex_color(value: int) -> str:
    return f"#{int(value) & 0xFFFFFF:06x}"


def parse_hex_color(text: str) -> tuple[int, int, int]:
    t = text.strip().lstrip("#")
    if len(t) != 6 or any(c not in "0123456789abcdefABCDEF" for c in t):
        raise AnimaiError(f"invalid colour '{text}', expected #RRGGBB")
    v = int(t, 16)
    return (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF


SMALL_SPRITE_MAX = 32      # largest side of the character (opaque bbox), CLAUDE.md "<= 32x32"


# ---------------------------------------------------------------- queries

def row_segments(rgba: np.ndarray, crop: tuple[int, int, int, int] | None = None) -> dict[str, list]:
    """The opaque pixels as horizontal runs of one colour: ``{"y": [[x0, x1, "#rrggbb"], ...]}``.

    ``x1`` is inclusive. Rows without opaque pixel are omitted. Meant to read a
    boundary to the pixel without looking at an image.
    """
    h, w = rgba.shape[:2]
    x0, y0, x1, y1 = 0, 0, w, h
    if crop is not None:
        x0, y0 = max(0, int(crop[0])), max(0, int(crop[1]))
        x1, y1 = min(w, int(crop[0]) + int(crop[2])), min(h, int(crop[1]) + int(crop[3]))
    packed = pack_rgba(rgba)
    out: dict[str, list] = {}
    for y in range(y0, y1):
        row = packed[y, x0:x1]
        if not row.any():
            continue
        edges = np.flatnonzero(np.diff(row)) + 1
        starts = np.concatenate(([0], edges))
        ends = np.concatenate((edges, [row.size]))
        runs = [[int(x0 + s), int(x0 + e - 1), hex_color(int(row[s]))] for s, e in zip(starts, ends) if row[s]]
        out[str(y)] = runs
    return out

def is_alpha_binary(rgba: np.ndarray) -> bool:
    a = rgba[..., 3]
    return bool(np.all((a == 0) | (a == 255)))


def opaque_bbox(rgba: np.ndarray) -> tuple[int, int, int, int] | None:
    """``(x, y, w, h)`` of the opaque pixels, or None if the image is empty."""
    ys, xs = np.nonzero(rgba[..., 3] > 0)
    if xs.size == 0:
        return None
    x0, y0 = int(xs.min()), int(ys.min())
    return x0, y0, int(xs.max()) - x0 + 1, int(ys.max()) - y0 + 1


def extract_palette(rgba: np.ndarray) -> list[tuple[str, int]]:
    """Unique colours of the opaque pixels as ``(hex, count)``, most frequent first."""
    opaque = rgba[..., 3] > 0
    values, counts = np.unique(pack_rgb(rgba)[opaque], return_counts=True)
    pairs = sorted(zip(values.tolist(), counts.tolist()), key=lambda vc: (-vc[1], vc[0]))
    return [(hex_color(v), int(c)) for v, c in pairs]


# ---------------------------------------------------------------- cleaning

def binarize_alpha(rgba: np.ndarray, threshold: int = 128) -> np.ndarray:
    """Alpha becomes 0 or 255 (``alpha >= threshold`` is opaque)."""
    out = rgba.copy()
    out[..., 3] = np.where(rgba[..., 3] >= threshold, 255, 0).astype(np.uint8)
    return normalize_rgba(out)


def detect_background(rgba: np.ndarray, tolerance: int = 0) -> tuple[int, int, int] | None:
    """Colour of a uniform background, guessed from the four corners.

    Returns None when the image already has transparency or the corners differ.
    """
    if np.any(rgba[..., 3] == 0):
        return None
    corners = [rgba[0, 0], rgba[0, -1], rgba[-1, 0], rgba[-1, -1]]
    ref = corners[0][:3].astype(np.int16)
    for c in corners[1:]:
        if int(np.abs(c[:3].astype(np.int16) - ref).max()) > tolerance:
            return None
    return int(ref[0]), int(ref[1]), int(ref[2])


def remove_background(rgba: np.ndarray, color: tuple[int, int, int], tolerance: int = 0,
                      mode: str = "flood") -> tuple[np.ndarray, int, int]:
    """Make the background colour transparent.

    ``mode="flood"`` only removes background-coloured pixels connected to the
    image border (safe for interior pixels of the same colour);
    ``mode="key"`` removes every pixel of that colour.

    Returns ``(image, removed_count, remaining_count)`` where ``remaining_count``
    is the number of opaque pixels still matching the background colour.
    """
    if mode not in ("flood", "key"):
        raise AnimaiError(f"unknown background mode '{mode}' (flood|key)")
    diff = np.abs(rgba[..., :3].astype(np.int16) - np.array(color, dtype=np.int16)).max(axis=2)
    match = (diff <= tolerance) & (rgba[..., 3] > 0)
    kill = match if mode == "key" else flood(border_mask(match.shape), match)
    out = rgba.copy()
    out[kill] = 0
    return out, int(kill.sum()), int((match & ~kill).sum())


def remove_background_rembg(rgba: np.ndarray) -> np.ndarray:
    """Background removal with the optional ``rembg`` package (not a core dependency)."""
    try:
        from rembg import remove  # type: ignore
    except ImportError as exc:
        raise AnimaiError("rembg is not installed; run: pip install animai[rembg]") from exc
    result = remove(Image.fromarray(rgba, "RGBA"))
    return np.array(result.convert("RGBA"), dtype=np.uint8)


def detect_pixel_scale(rgba: np.ndarray) -> int:
    """Integer upscale factor of the image (1 if it is not an exact NN upscale).

    Exact detection: the factor is the gcd of the image size and of every
    column/row index where the image content changes. Misaligned or blurry
    grids (AI-generated "pixel art", JPEG) are not handled and yield 1.
    """
    packed = pack_rgba(rgba)
    h, w = packed.shape
    col_changes = np.nonzero(np.any(packed[:, 1:] != packed[:, :-1], axis=0))[0] + 1
    row_changes = np.nonzero(np.any(packed[1:, :] != packed[:-1, :], axis=1))[0] + 1
    if col_changes.size == 0 and row_changes.size == 0:
        return 1  # uniform image: nothing to infer
    kx = reduce(gcd, col_changes.tolist(), w)
    ky = reduce(gcd, row_changes.tolist(), h)
    return max(1, gcd(kx, ky))


def downscale(rgba: np.ndarray, factor: int) -> np.ndarray:
    """Nearest-neighbour downscale by an integer factor (samples block centres)."""
    if factor < 1:
        raise AnimaiError("scale factor must be >= 1")
    if factor == 1:
        return rgba.copy()
    h, w = rgba.shape[:2]
    if w % factor or h % factor:
        raise AnimaiError(f"image size {w}x{h} is not a multiple of scale {factor}")
    off = factor // 2
    return np.ascontiguousarray(rgba[off::factor, off::factor])


# ------------------------------------------------- non-integer / blurry grid

GRID_MIN_PITCH = 6.0          # below this an estimated grid cannot be told from native pixels
GRID_WINDOW = 4.0             # width in source pixels of the band around a line where its edge may fall
GRID_MIN_CELLS = 8            # the image must hold at least this many cells per axis
GRID_MIN_LINES = 5            # at least this many grid lines must carry an edge, per axis
GRID_MIN_EXCESS = 0.5         # share of the edge energy on the lines, beyond what chance gives
GRID_COARSE_EXCESS = 0.3      # blurry image: enough to get a first pitch, the lines are then tracked
GRID_DRIFT = 0.2              # how far a tracked gap may be from the mean pitch
GRID_LOCAL = 12               # cells on each side used to measure the local pitch of a tracked grid
GRID_PRIOR = 6                # weight of the global pitch in that measure, in number of gaps
GRID_SQUARE_CRISP = 0.02      # allowed gap between the pitch of the two axes, sharp image
GRID_SQUARE_TRACKED = 0.1     # ... and tracked grid (the pitch drifts)
GRID_CRISP_COLORS = 256       # an image with at most this many colours is sharp (no blur, no JPEG)
GRID_CRISP_EXCESS = 0.95      # ... and must then have nearly all its edges on the grid
GRID_MERGE_COLORS = 16        # default --merge-colors when the grid had to be estimated
GRID_NOISE = 48               # colour steps under this (sum of channels) are noise, not edges


def _edge_profile(rgba: np.ndarray, axis: int) -> np.ndarray:
    """Edge energy between neighbouring columns (axis=1) or rows (axis=0); index i = edge before i.

    Differences are taken two pixels apart so that a blurred edge still counts, and small
    steps (noise, JPEG ringing) are ignored.
    """
    v = rgba.astype(np.int32)
    v[v[..., 3] == 0] = 0
    diff = np.abs(v[:, 2:] - v[:, :-2] if axis == 1 else v[2:] - v[:-2]).sum(axis=2)
    diff[diff < GRID_NOISE] = 0
    profile = diff.sum(axis=0 if axis == 1 else 1).astype(np.float64)
    return np.concatenate([[0.0], profile, [0.0]])


def _fold(profile: np.ndarray, pitch: float) -> float:
    """Excess capture of the best line window (``GRID_WINDOW`` px wide) for this pitch.

    1 when all the edge energy sits on the lines, 0 when the lines catch no more than
    their share of the image. Phases are binned by half pixels so that the rounding of
    a non-integer pitch does not push an edge out of the window.
    """
    x = np.arange(profile.size, dtype=np.float64)
    nb = int(np.ceil(pitch * 2))
    bins = np.bincount(np.floor((x % pitch) * 2).astype(np.int64), weights=profile, minlength=nb)[:nb]
    window = sum(np.roll(bins, k) for k in range(int(GRID_WINDOW * 2)))
    cover = GRID_WINDOW / pitch
    return (float(window.max() / profile.sum()) - cover) / (1.0 - cover)


def _line_offset(profile: np.ndarray, pitch: float) -> float:
    """Offset of the grid lines of a known pitch (phase of the Fourier term at 1/pitch)."""
    x = np.arange(profile.size, dtype=np.float64)
    phase = np.angle((profile * np.exp(-2j * np.pi * x / pitch)).sum())
    return float((-phase / (2 * np.pi) * pitch + 0.5) % pitch)   # +0.5: see _estimate_axis


def _estimate_axis(profile: np.ndarray, min_excess: float = GRID_MIN_EXCESS) -> dict | None:
    """Pitch and offset of the grid lines along one axis, or None when no grid stands out."""
    n = profile.size
    if profile.sum() <= 0 or n < GRID_MIN_PITCH * GRID_MIN_CELLS:
        return None
    pitches = np.arange(GRID_MIN_PITCH, n / GRID_MIN_CELLS + 1e-9, 0.02)
    excess = np.array([_fold(profile, float(p)) for p in pitches])
    top = float(excess.max())
    if top < min_excess:
        return None
    # Divisors of the real pitch score as well as the pitch itself: keep the largest.
    coarse = float(pitches[np.nonzero(excess >= 0.9 * top)[0][-1]])
    # Refinement: the Fourier magnitude at 1/pitch is sharp enough to keep the drift under
    # half a source pixel over the whole image; its phase gives the offset of the lines.
    x = np.arange(n, dtype=np.float64)
    span = max(0.03, 1.5 * coarse * coarse / n)
    cands = np.linspace(coarse - span, coarse + span, 801)
    mags = np.abs((profile[None, :] * np.exp(-2j * np.pi * x[None, :] / cands[:, None])).sum(axis=1))
    pitch = float(cands[int(np.argmax(mags))])
    phase = np.angle((profile * np.exp(-2j * np.pi * x / pitch)).sum())
    offset = float(-phase / (2 * np.pi) * pitch)
    # Two lone edges (a flat rectangle) fit any pitch and must not be taken for a grid.
    lines = np.rint(np.arange(offset % pitch, n - 1, pitch)).astype(np.int64)
    padded = np.pad(profile, 1)
    energy = padded[lines] + padded[lines + 1] + padded[lines + 2]
    hit = np.nonzero(energy > 0.02 * energy.max())[0]
    if hit.size < GRID_MIN_LINES:
        return None
    # The profile is centred half a pixel before the boundary it measures.
    return {"pitch": pitch, "offset": float((offset + 0.5) % pitch), "span": int(hit[-1] - hit[0]),
            "profile": profile, "capture": float(_fold(profile, pitch))}


def _track_lines(profile: np.ndarray, pitch: float) -> tuple[np.ndarray, float]:
    """Grid lines followed one by one when the pitch drifts inside the image (AI-generated art).

    Dynamic programming: a chain of lines from one border to the other, each
    ``pitch`` away from the previous one within ``GRID_DRIFT``, that collects the most
    edge energy; where there is no edge the lines stay ``pitch`` apart. Returns the
    boundary positions (source pixels) and the excess capture of the chain.
    """
    n = profile.size
    smooth = np.convolve(profile, [1.0, 2.0, 1.0], "same")
    gain = np.minimum(smooth / float(np.median(smooth[smooth > 0])), 3.0)   # one strong edge must not rule
    gaps = np.arange(int(np.floor(pitch * (1 - GRID_DRIFT))), int(np.ceil(pitch * (1 + GRID_DRIFT))) + 1)

    def best_chain() -> np.ndarray:
        score = gain.copy()
        back = np.full(n, -1, dtype=np.int64)
        cost = 0.05 * ((gaps - pitch) / pitch) ** 2 + 1e-6 * np.abs(gaps - np.rint(pitch))
        for i in range(int(gaps[0]), n):
            prev = i - gaps
            cand = np.where(prev >= 0, score[np.maximum(prev, 0)] - cost, -np.inf)
            k = int(np.argmax(cand))
            if i >= gaps[-1] or cand[k] > 0:        # past the first gap every line has a predecessor
                score[i] = gain[i] + cand[k]
                back[i] = prev[k]
        i = n - int(gaps[-1]) + int(np.argmax(score[n - int(gaps[-1]):]))
        chain = []
        while i >= 0:
            chain.append(i)
            i = int(back[i])
        return np.array(chain[::-1], dtype=np.int64)

    chain = best_chain()
    # Sub-pixel position: centroid of the edge around the line (+0.5, see _estimate_axis).
    padded = np.pad(profile, 2)
    near = np.zeros(n + 4, dtype=bool)
    found = []
    for c in chain[gain[chain] >= 0.5]:        # lines that sit on an edge
        local = padded[c:c + 5]
        found.append(c + 0.5 + float((local * np.arange(-2, 3)).sum() / local.sum()))
        near[c:c + 5] = True
    found = np.array(found)
    if found.size < 2:
        return found, 0.0
    # Where no edge exists the chain only moves by whole pixels and loses count of the
    # cells: lay those lines out evenly instead, with the pitch measured nearby (gaps
    # between two neighbouring lines that both sit on an edge).
    gaps_f = np.diff(found)
    single = np.nonzero(np.abs(gaps_f - pitch) <= GRID_DRIFT * pitch)[0]
    widths = gaps_f[single]
    centres = (found[single] + found[single + 1]) / 2.0

    def local_pitch(x: float) -> float:
        # Mean of the gaps measured within GRID_LOCAL cells, pulled towards the pitch of
        # the whole image when there are few of them (each one is only known to +-1 px).
        close = np.abs(centres - x) <= GRID_LOCAL * pitch
        return float((widths[close].sum() + GRID_PRIOR * pitch) / (int(close.sum()) + GRID_PRIOR))

    lines = []
    step = local_pitch(found[0])
    lines.extend((found[0] - step * np.arange(int(found[0] // step), 0, -1)).tolist())
    for left, right in zip(found[:-1], found[1:]):
        count = max(1, int(round((right - left) / local_pitch((left + right) / 2.0))))
        lines.extend(np.linspace(left, right, count, endpoint=False).tolist())
    step = local_pitch(found[-1])
    lines.extend((found[-1] + step * np.arange(0, int((n - found[-1]) // step) + 1)).tolist())
    lines = np.array(lines)
    mean_gap = float(np.diff(lines).mean())
    cover = min(0.9, (GRID_WINDOW + 1) / mean_gap)
    capture = (float(padded[near].sum() / profile.sum()) - cover) / (1.0 - cover)
    return lines, capture


def detect_grid(rgba: np.ndarray) -> dict | None:
    """Estimate a non-integer or blurry pixel grid (AI-generated "pixel art", resized exports).

    Returns ``{"pitch": [px, py], "offset": [ox, oy], "confidence": float, "lines": None | [xs, ys]}``
    in source pixels, or None when no grid stands out (native-resolution sprite, smooth
    art, pitch under 6 px). Sharp images get a regular grid, a line at ``offset + k * pitch``.
    Blurry or noisy ones get tracked ``lines`` (cell boundaries, the pitch may drift);
    ``pitch`` is then their mean spacing and ``offset`` the first line.
    """
    px, py = _edge_profile(rgba, 1), _edge_profile(rgba, 0)
    crisp = len(np.unique(pack_rgba(rgba))) <= GRID_CRISP_COLORS
    ax = _estimate_axis(px, GRID_MIN_EXCESS if crisp else GRID_COARSE_EXCESS)
    ay = _estimate_axis(py, GRID_MIN_EXCESS if crisp else GRID_COARSE_EXCESS)
    if ax is None or ay is None:
        return None
    # Pixels are square: two axes that disagree mean the "grid" is only the layout of a
    # native-resolution drawing made of flat blocks.
    tolerance = GRID_SQUARE_CRISP if crisp else GRID_SQUARE_TRACKED
    if abs(ax["pitch"] - ay["pitch"]) > tolerance * max(ax["pitch"], ay["pitch"]):
        return None
    if crisp:
        confidence = min(ax["capture"], ay["capture"])
        if confidence < GRID_CRISP_EXCESS:
            return None      # sharp image: a real grid explains every edge, not most of them
        # The axis whose edges span more lines gives the more precise pitch.
        ref, other = (ax, ay) if ax["span"] >= ay["span"] else (ay, ax)
        other["offset"] = _line_offset(other["profile"], ref["pitch"])
        other["pitch"] = ref["pitch"]
        return {"pitch": [ax["pitch"], ay["pitch"]], "offset": [ax["offset"], ay["offset"]],
                "confidence": round(confidence, 3), "lines": None}
    xs, cx = _track_lines(px, ax["pitch"])
    ys, cy = _track_lines(py, ay["pitch"])
    if min(cx, cy) < GRID_MIN_EXCESS or min(xs.size, ys.size) < GRID_MIN_CELLS:
        return None
    return {"pitch": [float(np.diff(xs).mean()), float(np.diff(ys).mean())],
            "offset": [float(xs[0]), float(ys[0])], "confidence": round(min(cx, cy), 3), "lines": [xs, ys]}


def _edges_from_lines(size: int, lines: np.ndarray) -> np.ndarray:
    """Tracked lines plus the image borders; border cells under half a cell are dropped."""
    half = float(np.diff(lines).mean()) / 2
    edges = lines[(lines > 0) & (lines < size)]
    if edges[0] >= half:
        edges = np.concatenate([[0.0], edges])
    if size - edges[-1] >= half:
        edges = np.concatenate([edges, [float(size)]])
    return edges


def _cell_edges(size: int, pitch: float, offset: float) -> np.ndarray:
    """Cell boundaries covering the image; border cells narrower than half a pitch are dropped."""
    first = offset - np.floor(offset / pitch) * pitch
    lines = np.arange(first - pitch, size + pitch, pitch)
    lines = lines[(lines > -pitch / 2) & (lines < size + pitch / 2)]
    return np.clip(lines, 0, size)


def resample_grid(rgba: np.ndarray, pitch: tuple[float, float], offset: tuple[float, float],
                  lines=None) -> np.ndarray:
    """One output pixel per grid cell, read in the central half of the cell (blurred borders ignored).

    A cell of a single colour is copied as is; otherwise (noise, JPEG) the pixel is the
    per-channel median of the majority side, opaque or transparent.
    """
    h, w = rgba.shape[:2]
    if lines is not None:     # tracked grid: explicit boundaries, ``pitch`` and ``offset`` unused
        xs, ys = _edges_from_lines(w, np.asarray(lines[0])), _edges_from_lines(h, np.asarray(lines[1]))
    else:
        xs, ys = _cell_edges(w, pitch[0], offset[0]), _cell_edges(h, pitch[1], offset[1])
    if xs.size < 2 or ys.size < 2:
        raise AnimaiError("grid pitch is larger than the image")
    out = np.zeros((ys.size - 1, xs.size - 1, 4), dtype=np.uint8)

    def core(a: float, b: float, limit: int) -> tuple[int, int]:
        lo = int(np.floor(a + (b - a) * 0.25))
        hi = int(np.ceil(b - (b - a) * 0.25))
        lo = min(max(lo, 0), limit - 1)
        return lo, max(hi, lo + 1)

    for j in range(ys.size - 1):
        y0, y1 = core(ys[j], ys[j + 1], h)
        for i in range(xs.size - 1):
            x0, x1 = core(xs[i], xs[i + 1], w)
            cell = rgba[y0:y1, x0:x1].reshape(-1, 4)
            opaque = cell[cell[:, 3] > 0]
            if opaque.shape[0] * 2 > cell.shape[0]:
                out[j, i, :3] = np.median(opaque[:, :3], axis=0).astype(np.uint8)
                out[j, i, 3] = 255
    return out


def merge_near_colors(rgba: np.ndarray, tolerance: int) -> tuple[np.ndarray, int]:
    """Merge colours closer than ``tolerance`` (largest channel gap) into the most used one.

    Greedy, most frequent colour first, so the result is deterministic and only keeps
    colours already present. Returns the image and the number of colours removed.
    """
    opaque = rgba[..., 3] > 0
    values, inverse, counts = np.unique(rgba[opaque][:, :3], axis=0, return_inverse=True, return_counts=True)
    if tolerance <= 0 or len(values) < 2:
        return rgba.copy(), 0
    order = sorted(range(len(values)), key=lambda k: (-int(counts[k]), tuple(int(c) for c in values[k])))
    kept: list[int] = []
    target = np.zeros(len(values), dtype=np.int64)
    for k in order:
        if kept:
            gap = np.abs(values[kept].astype(np.int32) - values[k].astype(np.int32)).max(axis=1)
            near = int(np.argmin(gap))
            if gap[near] <= tolerance:
                target[k] = kept[near]
                continue
        kept.append(k)
        target[k] = k
    out = rgba.copy()
    out[opaque, :3] = values[target[inverse.reshape(-1)]]
    return out, len(values) - len(kept)


def quantize_colors(rgba: np.ndarray, max_colors: int) -> np.ndarray:
    """Reduce the opaque pixels to at most ``max_colors`` colours (median cut, no dither)."""
    if not 1 <= max_colors <= 256:
        raise AnimaiError("--max-colors must be between 1 and 256")
    opaque = rgba[..., 3] > 0
    n = int(opaque.sum())
    if n == 0 or len(np.unique(pack_rgb(rgba)[opaque])) <= max_colors:
        return rgba.copy()
    strip = Image.fromarray(rgba[opaque][:, :3].reshape(1, n, 3), "RGB")
    quant = strip.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT,
                           dither=Image.Dither.NONE).convert("RGB")
    out = rgba.copy()
    out[opaque, :3] = np.array(quant, dtype=np.uint8).reshape(n, 3)
    return out


def prepare_sprite(rgba: np.ndarray, *, bg: str = "auto", bg_mode: str = "flood",
                   bg_tolerance: int = 0, alpha_threshold: int = 128,
                   scale: str | int = "auto", max_colors: int | None = None,
                   merge_colors: int | None = None) -> dict:
    """Full cleaning pipeline.

    Order: binarize alpha -> detect/apply real pixel scale (exact integer factor, else
    estimated grid) -> background removal -> merge of near colours -> optional
    quantization -> palette.

    ``bg``: ``"auto"`` | ``"none"`` | ``"rembg"`` | ``"#RRGGBB"``.

    Returns a dict with keys ``image`` (RGBA array), ``palette`` (list of
    ``(hex, count)``), ``scale`` (int), ``background`` (hex or None),
    ``removed`` (int), ``bbox`` (``[x, y, w, h]`` or None), ``warnings``.
    """
    warnings: list[str] = []
    if not 1 <= alpha_threshold <= 255:
        raise AnimaiError("--alpha-threshold must be between 1 and 255")
    if bg_tolerance < 0:
        raise AnimaiError("--bg-tolerance must be >= 0")

    if bg == "rembg":
        rgba = remove_background_rembg(rgba)
    semi = int(((rgba[..., 3] > 0) & (rgba[..., 3] < 255)).sum())
    if semi:
        warnings.append(f"{semi} semi-transparent pixels binarized (threshold {alpha_threshold})")
    img = binarize_alpha(rgba, alpha_threshold)

    grid = None
    if scale == "auto":
        factor = detect_pixel_scale(img)
        if factor == 1:
            grid = detect_grid(img)
    else:
        try:
            factor = int(scale)
        except (TypeError, ValueError):
            try:
                pitch = float(scale)
            except (TypeError, ValueError):
                raise AnimaiError(f"invalid --scale '{scale}' (auto, integer, or pixel pitch like 19.6)") from None
            if not pitch >= 1.0:
                raise AnimaiError("--scale must be >= 1")
            factor, found = 1, detect_grid(img)
            offset = [0.0, 0.0]
            regular = found is not None and found["lines"] is None
            if regular and all(abs(p - pitch) < 0.02 * pitch for p in found["pitch"]):
                offset = found["offset"]
            else:
                warnings.append(f"no grid of pitch {pitch} found in the image: lines assumed to start at 0,0")
            grid = {"pitch": [pitch, pitch], "offset": offset, "lines": None,
                    "confidence": None if found is None else found["confidence"]}
    if grid is not None:
        source_size = [int(img.shape[1]), int(img.shape[0])]
        lines = grid["lines"]
        img = resample_grid(img, tuple(grid["pitch"]), tuple(grid["offset"]), lines)
        grid = {"pitch": [round(p, 3) for p in grid["pitch"]], "offset": [round(o, 2) for o in grid["offset"]],
                "confidence": grid["confidence"], "source_size": source_size, "regular": lines is None,
                "lines": None if lines is None else [[round(float(v), 1) for v in axis] for axis in lines]}
        about, tracked = ("", "") if lines is None else ("about ", " (irregular, lines tracked)")
        warnings.append(f"pixel grid estimated: {about}{grid['pitch'][0]} x {grid['pitch'][1]} px per pixel"
                        f"{tracked}, sprite resampled from {source_size[0]}x{source_size[1]} to "
                        f"{img.shape[1]}x{img.shape[0]}; check grid.png")
        # An estimated grid means a noisy source: clean it by default, before the background
        # is looked for (a noisy flat background is then one colour).
        early = GRID_MERGE_COLORS if merge_colors is None else merge_colors
        if early < 0:
            raise AnimaiError("--merge-colors must be >= 0")
        img, merged = merge_near_colors(img, early)
        if merged:
            warnings.append(f"{merged} near-duplicate colours merged (tolerance {early}; "
                            "--merge-colors 0 to keep them)")
        merge_colors = 0
    else:
        img = downscale(img, factor)

    background = None
    removed = 0
    if bg == "auto":
        background = detect_background(img, bg_tolerance)
        if background is None and not np.any(img[..., 3] == 0):
            warnings.append("no transparency and no uniform background detected: "
                            "sprite kept fully opaque (use --bg #RRGGBB or --bg rembg)")
    elif bg not in ("none", "rembg"):
        background = parse_hex_color(bg)
    if background is not None:
        img, removed, remaining = remove_background(img, background, bg_tolerance, bg_mode)
        if removed == 0:
            warnings.append("background colour not found on the image border: nothing removed")
        if remaining:
            warnings.append(f"{remaining} pixels of the background colour remain inside the sprite "
                            "(use --bg-mode key if they are background)")

    if merge_colors is None:
        merge_colors = 0
    if merge_colors < 0:
        raise AnimaiError("--merge-colors must be >= 0")
    img, merged = merge_near_colors(img, merge_colors)
    if merged:
        warnings.append(f"{merged} near-duplicate colours merged (tolerance {merge_colors}; "
                        "--merge-colors 0 to keep them)")
    if max_colors is not None:
        img = quantize_colors(img, max_colors)
    img = normalize_rgba(img)

    bbox = opaque_bbox(img)
    if bbox is None:
        raise AnimaiError("sprite is empty after cleaning (no opaque pixel)")
    if max(bbox[2], bbox[3]) <= SMALL_SPRITE_MAX:
        warnings.append(f"the character is {bbox[2]}x{bbox[3]} px: rigid parts give poor results at "
                        f"{SMALL_SPRITE_MAX} px and under (limbs too thin to rotate)")
    return {
        "image": img,
        "palette": extract_palette(img),
        "scale": factor if grid is None else round(float(np.mean(grid["pitch"])), 2),
        "grid": grid,
        "background": None if background is None else hex_color(
            (background[0] << 16) | (background[1] << 8) | background[2]),
        "removed": removed,
        "bbox": list(bbox),
        "warnings": warnings,
    }
