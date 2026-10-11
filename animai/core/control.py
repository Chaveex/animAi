"""Control images Claude looks at: inspect view, skeleton overlay, label map, parts, contact sheet.

All functions return opaque RGB uint8 arrays. Nothing here feeds the pipeline:
these images are for eyes only, the real outputs never go through this module.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from .errors import AnimaiError
from .font import GLYPH_H, draw_text, text_size
from .kinematics import BonePose, round_half_up
from .rig import UNASSIGNED, LabelMap, Part

BG = (40, 40, 44)
CHECK_A, CHECK_B = (176, 176, 176), (152, 152, 152)
TEXT = (235, 235, 235)
# Okabe-Ito colour-blind-safe palette, then extra distinct hues.
PART_COLORS = [
    (230, 159, 0), (86, 180, 233), (0, 158, 115), (240, 228, 66), (0, 114, 178),
    (213, 94, 0), (204, 121, 167), (148, 103, 189), (140, 86, 75), (127, 201, 127),
    (255, 152, 150), (23, 190, 207), (188, 189, 34), (102, 102, 255), (250, 250, 250),
]
UNASSIGNED_COLOR = (255, 0, 255)


def part_color(index: int) -> tuple[int, int, int]:
    base = PART_COLORS[index % len(PART_COLORS)]
    shade = 1.0 - 0.35 * ((index // len(PART_COLORS)) % 3)
    return tuple(int(c * shade) for c in base)


def _checker(x0: int, y0: int, w: int, h: int, cell: int = 4) -> np.ndarray:
    """Checkerboard in sprite coordinates (one value per sprite pixel)."""
    xs = (np.arange(x0, x0 + w) // cell)[None, :]
    ys = (np.arange(y0, y0 + h) // cell)[:, None]
    sel = ((xs + ys) % 2 == 0)[..., None]
    return np.where(sel, np.array(CHECK_A, dtype=np.uint8), np.array(CHECK_B, dtype=np.uint8))


def flatten(rgba: np.ndarray, zoom: int, x0: int = 0, y0: int = 0) -> np.ndarray:
    """RGBA -> RGB on a checkerboard, nearest-neighbour upscaled by ``zoom``."""
    h, w = rgba.shape[:2]
    rgb = _checker(x0, y0, w, h)
    mask = rgba[..., 3] > 0
    rgb[mask] = rgba[mask][:, :3]
    return np.repeat(np.repeat(rgb, zoom, axis=0), zoom, axis=1)


def _blend(img: np.ndarray, sl, color, alpha: float) -> None:
    region = img[sl].astype(np.float32)
    img[sl] = (region * (1 - alpha) + np.array(color, dtype=np.float32) * alpha + 0.5).astype(np.uint8)


def _parse_crop(crop, w: int, h: int) -> tuple[int, int, int, int]:
    if crop is None:
        return 0, 0, w, h
    x, y, cw, ch = (int(v) for v in crop)
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(w, x + cw), min(h, y + ch)
    if x0 >= x1 or y0 >= y1:
        raise AnimaiError(f"crop {list(crop)} is outside the sprite ({w}x{h})")
    return x0, y0, x1 - x0, y1 - y0


class View:
    """Zoomed sprite with coordinate axes. Maps sprite coordinates to image pixels."""

    def __init__(self, rgba: np.ndarray, zoom: int = 8, crop=None, grid: str = "full"):
        if zoom < 1:
            raise AnimaiError("zoom must be >= 1")
        h, w = rgba.shape[:2]
        self.zoom = zoom
        self.cx, self.cy, self.cw, self.ch = _parse_crop(crop, w, h)
        self.scale = 2 if zoom >= 6 else 1
        self.left = text_size("9999", self.scale)[0] + 6
        self.top = GLYPH_H * self.scale + 6
        body = flatten(rgba[self.cy:self.cy + self.ch, self.cx:self.cx + self.cw], zoom, self.cx, self.cy)
        self.img = np.empty((self.top + body.shape[0] + 4, self.left + body.shape[1] + 4, 3), dtype=np.uint8)
        self.img[:] = BG
        self.img[self.top:self.top + body.shape[0], self.left:self.left + body.shape[1]] = body
        self._grid(grid)
        self._axes()

    def sx(self, x: float) -> int:
        """Image x of the left edge of sprite column ``x``."""
        return self.left + int(round((x - self.cx) * self.zoom))

    def sy(self, y: float) -> int:
        return self.top + int(round((y - self.cy) * self.zoom))

    def center(self, x: int, y: int) -> tuple[int, int]:
        """Image position of the centre of sprite pixel ``(x, y)``."""
        return self.sx(x) + self.zoom // 2, self.sy(y) + self.zoom // 2

    def _grid(self, grid: str) -> None:
        if grid == "none":
            return
        z = self.zoom
        bw, bh = self.cw * z, self.ch * z
        levels = []
        if grid == "full" and z >= 4:
            levels.append((1, (128, 128, 128), 0.40))
        if z >= 2:
            levels.append((5, (255, 255, 255), 0.55))
            levels.append((10, (255, 220, 0), 0.90))
        for step, color, alpha in levels:
            for x in range(self.cx, self.cx + self.cw + 1):
                if x % step == 0 and (step != 5 or x % 10) and (step != 1 or x % 5):
                    px = min(self.sx(x), self.left + bw - 1)
                    _blend(self.img, (slice(self.top, self.top + bh), slice(px, px + 1)), color, alpha)
            for y in range(self.cy, self.cy + self.ch + 1):
                if y % step == 0 and (step != 5 or y % 10) and (step != 1 or y % 5):
                    py = min(self.sy(y), self.top + bh - 1)
                    _blend(self.img, (slice(py, py + 1), slice(self.left, self.left + bw)), color, alpha)

    def _axes(self) -> None:
        z, s = self.zoom, self.scale
        need = text_size("999", s)[0] + 4
        step = next((c for c in (5, 10, 20, 50, 100, 200, 500) if c * z >= need), 500)
        for x in range(self.cx, self.cx + self.cw):
            if x % step == 0:
                label = str(x)
                tw = text_size(label, s)[0]
                pos = min(max(self.sx(x) + z // 2 - tw // 2, self.left), self.img.shape[1] - tw - 1)
                draw_text(self.img, pos, 3, label, TEXT, s)
        for y in range(self.cy, self.cy + self.ch):
            if y % step == 0:
                label = str(y)
                tw, th = text_size(label, s)
                pos = min(max(self.sy(y) + z // 2 - th // 2, self.top), self.img.shape[0] - th - 1)
                draw_text(self.img, self.left - tw - 3, pos, label, TEXT, s)


def inspect_view(rgba: np.ndarray, zoom: int = 8, crop=None) -> np.ndarray:
    """Sprite upscaled NN with a pixel grid and coordinates.

    Grid: thin grey line per pixel, white every 5, yellow every 10. A number on
    an axis names the column/row whose cell it is centred on.
    """
    return View(rgba, zoom, crop, "full").img


def grid_overlay(source: np.ndarray, pitch, offset, lines=None) -> np.ndarray:
    """Source image with the estimated pixel grid drawn on it.

    Lines at ``offset + k * pitch``, or at the tracked ``lines`` ([xs, ys]) when given.
    """
    h, w = source.shape[:2]
    img = flatten(source, 1)
    for k, (size, step, start, axis) in enumerate(((w, pitch[0], offset[0], 1), (h, pitch[1], offset[1], 0))):
        first = start - np.floor(start / step) * step
        for line in (np.arange(first, size, step) if lines is None else lines[k]):
            i = int(round_half_up(line))
            if 0 <= i < size:
                _blend(img, (slice(None), slice(i, i + 1)) if axis else (slice(i, i + 1), slice(None)),
                       (255, 0, 255), 0.6)
    return img


def _draw_marker(draw: ImageDraw.ImageDraw, x: int, y: int, r: int, fill) -> None:
    draw.rectangle([x - r - 1, y - r - 1, x + r + 1, y + r + 1], fill=(0, 0, 0))
    draw.rectangle([x - r, y - r, x + r, y + r], fill=fill)


def skeleton_overlay(rgba: np.ndarray, rig: dict, zoom: int = 8,
                     pivot: tuple[int, int] | None = None,
                     pose: dict[str, BonePose] | None = None, labels: str = "names") -> np.ndarray:
    """Bones (parent joint -> joint), joints, bone names and pivot over the zoomed sprite.

    ``pose`` (world pose from ``solve_pose``) draws the skeleton posed instead of at rest.
    ``labels``: ``"names"``, ``"numbers"`` (index of the bone in ``rig["bones"]``, less
    clutter) or ``"none"``.
    """
    if labels not in ("names", "numbers", "none"):
        raise AnimaiError("labels must be names, numbers or none")
    view = View(rgba, zoom, None, "major")
    im = Image.fromarray(view.img, "RGB")
    draw = ImageDraw.Draw(im)
    bones = rig["bones"]

    def joint_xy(name: str) -> tuple[int, int]:
        if pose is not None:
            return round_half_up(pose[name].pos[0]), round_half_up(pose[name].pos[1])
        return tuple(bones[name]["joint"])

    for name, bone in bones.items():
        parent = bone.get("parent")
        if parent is None:
            continue
        a, b = view.center(*joint_xy(parent)), view.center(*joint_xy(name))
        draw.line([a, b], fill=(0, 0, 0), width=5)
        draw.line([a, b], fill=(255, 255, 255), width=1 if zoom < 4 else 2)
    r = max(1, zoom // 3)
    for name, bone in bones.items():
        x, y = view.center(*joint_xy(name))
        _draw_marker(draw, x, y, r + (1 if bone.get("parent") is None else 0),
                     (255, 220, 0) if bone.get("parent") is None else (255, 60, 60))
    if pivot is not None:
        x, y = view.sx(pivot[0]), view.sy(pivot[1])
        arm = max(4, zoom)
        for color, width in (((0, 0, 0), 5), ((0, 230, 255), 2)):
            draw.line([(x - arm, y), (x + arm, y)], fill=color, width=width)
            draw.line([(x, y - arm), (x, y + arm)], fill=color, width=width)
    out = np.array(im, dtype=np.uint8)

    scale = 2 if zoom >= 8 else 1
    used: list[tuple[int, int, int, int]] = []

    def place(text: str, x: int, y: int, color) -> None:
        tw, th = text_size(text, scale)
        x = min(max(x, 1), out.shape[1] - tw - 2)
        y = min(max(y, 1), out.shape[0] - th - 2)
        pad = 3 * scale
        while any(x < u[2] + pad and u[0] < x + tw + pad and y < u[3] + 2 and u[1] < y + th + 2
                  for u in used):
            y += th + 3
        used.append((x, y, x + tw, y + th))
        draw_text(out, x, y, text, color, scale, bg=(0, 0, 0))

    if labels == "none":
        return out
    for number, name in enumerate(bones):
        x, y = view.center(*joint_xy(name))
        place(name if labels == "names" else str(number), x + r + 4, y - GLYPH_H * scale // 2, (255, 255, 255))
    if pivot is not None:
        place("pivot" if labels == "names" else "p", view.sx(pivot[0]) + 6, view.sy(pivot[1]) + 4, (0, 230, 255))
    return out


def labelmap_view(rgba: np.ndarray, labelmap: LabelMap, rig: dict, zoom: int = 8) -> np.ndarray:
    """Every opaque pixel painted with the colour of its part; unassigned pixels hatched magenta.

    A legend on the right lists index, name, z and pixel count of each part.
    """
    colored = np.zeros_like(rgba)
    opaque = rgba[..., 3] > 0
    for index in range(len(labelmap.part_names)):
        mask = labelmap.labels == index
        colored[mask, :3] = part_color(index)
    un = opaque & (labelmap.labels == UNASSIGNED)
    colored[un, :3] = UNASSIGNED_COLOR
    colored[opaque, 3] = 255
    view = View(colored, zoom, None, "full")
    img = view.img
    if un.any() and zoom >= 2:
        big = np.repeat(np.repeat(un, zoom, axis=0), zoom, axis=1)
        yy, xx = np.indices(big.shape)
        hatch = big & ((xx + yy) % max(2, zoom // 2) == 0)
        body = img[view.top:view.top + big.shape[0], view.left:view.left + big.shape[1]]
        body[hatch] = (0, 0, 0)

    scale = 2
    line_h = GLYPH_H * scale + 6
    rows = []
    for index, name in enumerate(labelmap.part_names):
        count = int((labelmap.labels == index).sum())
        rows.append((part_color(index), f"{index} {name} z={rig['parts'][name].get('z', 0)} {count}px"))
    rows.append((UNASSIGNED_COLOR, f"unassigned {len(labelmap.unassigned)}px"))
    legend_w = max(text_size(t, scale)[0] for _, t in rows) + 30
    height = max(img.shape[0], len(rows) * line_h + 12)
    out = np.empty((height, img.shape[1] + legend_w, 3), dtype=np.uint8)
    out[:] = BG
    out[:img.shape[0], :img.shape[1]] = img
    x = img.shape[1] + 6
    for i, (color, text) in enumerate(rows):
        y = 8 + i * line_h
        out[y - 1:y + GLYPH_H * scale + 1, x:x + 12] = color
        draw_text(out, x + 18, y, text, TEXT, scale)
    return out


def _grid_layout(cells: list[np.ndarray], labels: list[str], columns: int, scale: int = 2) -> np.ndarray:
    """Arrange RGB cells in a grid with a caption above each."""
    cap = GLYPH_H * scale + 6
    gap = 8
    cw = max(max(c.shape[1] for c in cells), max(text_size(t, scale)[0] for t in labels))
    ch = max(c.shape[0] for c in cells)
    rows = -(-len(cells) // columns)
    out = np.empty((gap + rows * (ch + cap + gap), gap + columns * (cw + gap), 3), dtype=np.uint8)
    out[:] = BG
    for i, (cell, label) in enumerate(zip(cells, labels)):
        x = gap + (i % columns) * (cw + gap)
        y = gap + (i // columns) * (ch + cap + gap)
        draw_text(out, x, y, label, TEXT, scale)
        out[y + cap:y + cap + cell.shape[0], x:x + cell.shape[1]] = cell
    return out


def parts_sheet(parts: list[Part], rig: dict, zoom: int = 4) -> np.ndarray:
    """Every cut part on a checkerboard, with its joint (red square).

    Pixels of the filled hidden zone (not owned by the part in the label map)
    are framed in magenta at zoom >= 4, dotted in magenta below.
    """
    if not parts:
        raise AnimaiError("no part to show")
    cells, labels = [], []
    for part in parts:
        cell = flatten(part.image, zoom, part.origin[0], part.origin[1])
        ext = (part.image[..., 3] > 0) & ~part.own_mask
        ys, xs = np.nonzero(ext)
        if zoom >= 4:
            for x, y in zip(xs.tolist(), ys.tolist()):
                x0, y0 = x * zoom, y * zoom
                cell[y0, x0:x0 + zoom] = cell[y0 + zoom - 1, x0:x0 + zoom] = (255, 0, 255)
                cell[y0:y0 + zoom, x0] = cell[y0:y0 + zoom, x0 + zoom - 1] = (255, 0, 255)
        elif zoom == 3:
            d = 1
            for x, y in zip(xs.tolist(), ys.tolist()):
                cx, cy = x * zoom + zoom // 2, y * zoom + zoom // 2
                cell[cy - d // 2:cy - d // 2 + d, cx - d // 2:cx - d // 2 + d] = (255, 0, 255)
        jx, jy = rig["bones"][part.bone]["joint"]
        lx, ly = jx - part.origin[0], jy - part.origin[1]
        if 0 <= lx < part.image.shape[1] and 0 <= ly < part.image.shape[0]:
            r = max(1, zoom // 3)
            cx, cy = lx * zoom + zoom // 2, ly * zoom + zoom // 2
            cell[max(0, cy - r - 1):cy + r + 2, max(0, cx - r - 1):cx + r + 2] = (0, 0, 0)
            cell[max(0, cy - r):cy + r + 1, max(0, cx - r):cx + r + 1] = (255, 60, 60)
        cells.append(cell)
        labels.append(f"{part.name} z={part.z}")
    width = sum(c.shape[1] + 8 for c in cells)
    return _grid_layout(cells, labels, min(len(cells), 6 if width / max(1, len(cells)) * 6 <= 2400 else 4))


def contact_sheet(frames: list[np.ndarray], durations_ms: list[int] | None = None,
                  pivot: tuple[int, int] | None = None, zoom: int | None = None,
                  columns: int | None = None) -> np.ndarray:
    """All frames side by side, NN zoomed, captioned with index and duration.

    With ``pivot``, a cyan ground line is drawn at the pivot row and a tick at
    the pivot column, to judge bob and jitter by eye.
    """
    if not frames:
        raise AnimaiError("no frame to show")
    n = len(frames)
    h, w = frames[0].shape[:2]
    if columns is None:
        columns = n if n <= 4 else (4 if n <= 8 else 6)
    columns = max(1, min(columns, n))
    if zoom is None:
        zoom = next((z for z in (8, 6, 4, 3, 2) if columns * (w * z + 8) <= 2000), 1)
    cells, labels = [], []
    for i, f in enumerate(frames):
        cell = flatten(f, zoom)
        if pivot is not None:
            py = min(max(pivot[1] * zoom, 0), cell.shape[0] - 1)
            px = min(max(pivot[0] * zoom, 0), cell.shape[1] - 1)
            _blend(cell, (slice(py, py + 1), slice(None)), (0, 230, 255), 0.6)
            cell[max(0, py - 2 * zoom):py + 1, px:px + 1] = (0, 230, 255)
        cells.append(cell)
        labels.append(f"{i}" if durations_ms is None else f"{i} {int(durations_ms[i])}ms")
    return _grid_layout(cells, labels, columns)
