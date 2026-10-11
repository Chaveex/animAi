"""Small binary-mask helpers (numpy only): dilation, flood fill, components."""
from __future__ import annotations

import numpy as np


def dilate4(mask: np.ndarray) -> np.ndarray:
    """One step of 4-connected dilation."""
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def neighbor_count8(mask: np.ndarray) -> np.ndarray:
    """Number of set 8-neighbours for every cell."""
    p = np.pad(mask.astype(np.int16), 1)
    h, w = mask.shape
    total = np.zeros((h, w), dtype=np.int16)
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            if dy == 1 and dx == 1:
                continue
            total += p[dy:dy + h, dx:dx + w]
    return total


def flood(seed: np.ndarray, passable: np.ndarray) -> np.ndarray:
    """4-connected flood fill of ``passable`` starting from ``seed``."""
    reach = seed & passable
    count = int(reach.sum())
    while True:
        reach = dilate4(reach) & passable
        new_count = int(reach.sum())
        if new_count == count:
            return reach
        count = new_count


def border_mask(shape: tuple[int, int]) -> np.ndarray:
    m = np.zeros(shape, dtype=bool)
    m[0, :] = m[-1, :] = True
    m[:, 0] = m[:, -1] = True
    return m


def enclosed_transparent(opaque: np.ndarray) -> np.ndarray:
    """Transparent cells that cannot reach the outside of the image (4-connected).

    The image is treated as surrounded by transparent space, so a transparent
    cell on the image border is never enclosed.
    """
    passable = np.pad(~opaque, 1, constant_values=True)
    reach = flood(border_mask(passable.shape), passable)
    return (passable & ~reach)[1:-1, 1:-1]


def components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    """4-connected components as lists of ``(x, y)``, in raster order.

    Pure-Python BFS: meant for small masks (holes, leftovers), not full images.
    """
    ys, xs = np.nonzero(mask)
    todo = {(int(x), int(y)) for x, y in zip(xs, ys)}
    out: list[list[tuple[int, int]]] = []
    for y, x in zip(ys.tolist(), xs.tolist()):
        if (x, y) not in todo:
            continue
        todo.discard((x, y))
        comp = [(x, y)]
        i = 0
        while i < len(comp):
            cx, cy = comp[i]
            i += 1
            for n in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                if n in todo:
                    todo.discard(n)
                    comp.append(n)
        comp.sort(key=lambda p: (p[1], p[0]))
        out.append(comp)
    return out
