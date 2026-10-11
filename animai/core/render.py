"""Frame rendering: rigid parts placed by the kinematics, composed by z-index.

The whole animation shares one canvas (bounding box of every frame + padding)
and one pivot, so nothing is cropped and nothing jumps.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .errors import AnimaiError
from .kinematics import BonePose, normalize_angle, round_half_up, solve_pose
from .morph import dilate4
from .rig import (OUTLINE_MODES, UNASSIGNED, LabelMap, Part, detect_outline_color, outline_setting,
                  silhouette_border)
from .rotate import rotate_part
from .sprite import opaque_bbox, pack_rgb, parse_hex_color


@dataclass
class Layer:
    z: int
    order: int
    image: np.ndarray            # RGBA patch
    pos: tuple[int, int]         # sprite coordinates of the patch's top-left corner
    part: str


@dataclass
class RenderResult:
    frames: list[np.ndarray]                 # RGBA, all of size ``canvas``
    canvas: tuple[int, int]                  # (w, h)
    origin: tuple[int, int]                  # sprite coordinates of the canvas top-left corner
    pivot: tuple[int, int]                   # pivot in canvas coordinates (same for every frame)
    poses: list[dict[str, BonePose]]
    warnings: list[str] = field(default_factory=list)
    layers: list[list[Layer]] = field(default_factory=list)   # per frame, back to front
    outline: "OutlineSpec | None" = None
    sprite: np.ndarray | None = None                          # the source sprite (for the outline pass)


@dataclass
class OutlineSpec:
    color: int                       # packed 0xRRGGBB, a colour of the sprite palette
    mode: str                        # "inside" | "outside"
    inner: list[str]                 # parts whose edge over the parts behind them is drawn in the source
    part_order: dict[str, tuple]     # part name -> (z, index) at rest
    source_gap: int                  # silhouette-border pixels of the sprite that are not outline-coloured
    source_border: int
    labels: np.ndarray | None = None  # rest label map (index in part_order order), for the rest-pose guard


INNER_MIN_PIXELS = 4


def outline_spec(rig: dict, rgba: np.ndarray, labelmap: LabelMap | None = None) -> OutlineSpec | None:
    """Outline settings of a sprite, or None when the pass is off.

    ``rig["outline"]``: ``"auto"`` (default) = the colour found by
    ``detect_outline_color`` (None: the sprite has no outline, nothing is done),
    ``"none"`` / ``false`` = off, ``"#RRGGBB"`` = imposed (must be in the palette).
    A part is listed in ``inner`` when at least 60 % of its own pixels that
    touch (4-neighbours) a pixel of a part drawn behind it are outline-coloured
    (and there are at least 4 such pixels).
    """
    setting = outline_setting(rig)
    if setting is None:
        return None
    opaque = rgba[..., 3] > 0
    rgb = pack_rgb(rgba)
    if setting == "auto":
        color = detect_outline_color(rgba)
        if color is None:
            return None
    else:
        r, g, b = parse_hex_color(setting)
        color = (r << 16) | (g << 8) | b
        if color not in set(np.unique(rgb[opaque]).tolist()):
            raise AnimaiError(f"rig.outline {setting} is not in the sprite palette")
    border = silhouette_border(rgba)
    inner: list[str] = []
    order: dict[str, tuple] = {}
    if labelmap is not None:
        names = labelmap.part_names
        keys = [(int(rig["parts"][n].get("z", 0)), i) for i, n in enumerate(names)]
        order = {n: keys[i] for i, n in enumerate(names)}
        for i, name in enumerate(names):
            behind = np.isin(labelmap.labels, [j for j in range(len(names)) if keys[j] < keys[i]])
            edge = (labelmap.labels == i) & dilate4(behind)
            count = int(edge.sum())
            if count >= INNER_MIN_PIXELS and int((rgb[edge] == color).sum()) * 10 >= count * 6:
                inner.append(name)
    return OutlineSpec(color, rig.get("outline_mode", OUTLINE_MODES[0]), inner, order,
                       int((border & (rgb != color)).sum()), int(border.sum()),
                       None if labelmap is None else labelmap.labels)


def canvas_border(opaque: np.ndarray) -> np.ndarray:
    """Opaque pixels with a transparent 4-neighbour (outside the canvas counts as transparent)."""
    return opaque & dilate4(np.pad(~opaque, 1, constant_values=True))[1:-1, 1:-1]


def outline_gap(frame: np.ndarray, color: int) -> tuple[int, int]:
    """``(bare, border)``: silhouette-border pixels of a frame not outline-coloured, and border size."""
    border = canvas_border(frame[..., 3] > 0)
    return int((border & (pack_rgb(frame) != color)).sum()), int(border.sum())


def apply_outline(frame: np.ndarray, layers: list[Layer], origin: tuple[int, int],
                  sprite: np.ndarray, spec: OutlineSpec) -> np.ndarray:
    """Give a composed frame the outline the source sprite has.

    Rest-pose guard: a frame pixel that shows the same colour as the sprite at
    the same sprite position is left alone when the sprite already had a
    silhouette border there (rule 1) or the same part there (rule 2). The rest
    pose is therefore never modified.

    1. Silhouette: every border pixel (opaque with a transparent 4-neighbour)
       that is not outline-coloured and not guarded is recoloured with the
       outline colour (``mode="inside"``: the silhouette keeps its exact shape),
       or its transparent 4-neighbours become outline pixels (``"outside"``:
       the limb keeps its width, the silhouette grows by 1 px there).
    2. Inner edges, only for the parts of ``spec.inner``: a visible pixel of
       such a part that touches a visible pixel of a part behind it is
       recoloured, unless guarded.
    """
    h, w = frame.shape[:2]
    out = frame.copy()
    opaque = frame[..., 3] > 0
    rgb = pack_rgb(frame)
    # "untouched": same colour as the sprite at the same place
    sh, sw = sprite.shape[:2]
    same = np.zeros((h, w), dtype=bool)
    rest_border = np.zeros((h, w), dtype=bool)
    rest_labels = np.full((h, w), UNASSIGNED, dtype=np.int16)
    x0, y0 = max(0, origin[0]), max(0, origin[1])
    x1, y1 = min(sw, origin[0] + w), min(sh, origin[1] + h)
    if x0 < x1 and y0 < y1:
        src = sprite[y0:y1, x0:x1]
        cut = (slice(y0 - origin[1], y1 - origin[1]), slice(x0 - origin[0], x1 - origin[0]))
        same[cut] = (src[..., 3] > 0) & opaque[cut] & (pack_rgb(src) == rgb[cut])
        rest_border[cut] = silhouette_border(sprite)[y0:y1, x0:x1]
        if spec.labels is not None:
            rest_labels[cut] = spec.labels[y0:y1, x0:x1]
    color = np.array([(spec.color >> 16) & 0xFF, (spec.color >> 8) & 0xFF, spec.color & 0xFF, 255], dtype=np.uint8)

    bare = canvas_border(opaque) & (rgb != spec.color) & ~(same & rest_border)
    if spec.mode == "outside":
        out[dilate4(bare) & ~opaque] = color
    else:
        out[bare] = color

    if spec.inner:
        names = list(spec.part_order)
        owners = compose_owners(layers, origin, (w, h), {n: i for i, n in enumerate(names)})
        for name in spec.inner:
            i = names.index(name)
            behind = np.isin(owners, [j for j, n in enumerate(names) if spec.part_order[n] < spec.part_order[name]])
            edge = (owners == i) & dilate4(behind) & (rgb != spec.color) & ~(same & (rest_labels == i))
            out[edge] = color
    return out


def finish_frame(result: "RenderResult", layers: list[Layer]) -> np.ndarray:
    """Compose a layer stack on the canvas of ``result`` and run the outline pass."""
    frame = compose(layers, result.origin, result.canvas)
    if result.outline is not None and result.sprite is not None:
        frame = apply_outline(frame, layers, result.origin, result.sprite, result.outline)
    return frame


def compute_pivot(rgba: np.ndarray, rig: dict) -> tuple[int, int]:
    """Pivot in sprite coordinates, anchored on the rest pose.

    ``rig["pivot"]`` = ``[fx, fy]`` relative to the bounding box of the opaque
    pixels of the *rest* sprite (never the union box of the animation), so the
    character keeps the same place around the pivot in every animation. The
    result is a grid-corner coordinate: ``[0.5, 1.0]`` is the middle of the
    bottom edge, i.e. the ground line between the feet.
    """
    bbox = opaque_bbox(rgba)
    if bbox is None:
        raise AnimaiError("sprite has no opaque pixel")
    fx, fy = rig.get("pivot", [0.5, 1.0])
    x, y, w, h = bbox
    return x + round_half_up(w * fx), y + round_half_up(h * fy)


def frame_layers(parts: list[Part], rig: dict, pose: dict[str, BonePose],
                 z_override: dict[str, int] | None = None, method: str = "rotsprite",
                 cache: dict | None = None) -> list[Layer]:
    """Rotated and placed parts for one pose, sorted back to front.

    ``z_override`` maps a *bone* name to an absolute z replacing, for this frame,
    the z of every part attached to that bone (children are not affected).
    Larger z = in front; equal z = definition order of the parts.
    """
    z_override = z_override or {}
    cache = cache if cache is not None else {}
    layers: list[Layer] = []
    for part in parts:
        bp = pose[part.bone]
        joint = rig["bones"][part.bone]["joint"]
        key = (part.index, round(bp.angle % 360.0, 6), method)
        if key not in cache:
            cache[key] = rotate_part(part.image, part.origin, joint, bp.angle, method)
        image, (x0, y0) = cache[key]
        # Single rounding per part: the joint lands on an integer pixel.
        dx = round_half_up(bp.pos[0]) - joint[0]
        dy = round_half_up(bp.pos[1]) - joint[1]
        layers.append(Layer(z_override.get(part.bone, part.z), part.index, image,
                            (x0 + dx, y0 + dy), part.name))
    layers.sort(key=lambda l: (l.z, l.order))
    return layers


def layers_bbox(layers: list[Layer]) -> tuple[int, int, int, int] | None:
    """``(x0, y0, x1, y1)`` (exclusive) of the opaque pixels of a layer stack."""
    box = None
    for layer in layers:
        b = opaque_bbox(layer.image)
        if b is None:
            continue
        x0, y0 = layer.pos[0] + b[0], layer.pos[1] + b[1]
        cur = (x0, y0, x0 + b[2], y0 + b[3])
        box = cur if box is None else (min(box[0], cur[0]), min(box[1], cur[1]),
                                       max(box[2], cur[2]), max(box[3], cur[3]))
    return box


def compose(layers: list[Layer], origin: tuple[int, int], size: tuple[int, int]) -> np.ndarray:
    """Paint layers back to front on a transparent canvas. Pixels outside are clipped."""
    w, h = size
    canvas = np.zeros((h, w, 4), dtype=np.uint8)
    for layer in layers:
        ph, pw = layer.image.shape[:2]
        x0, y0 = layer.pos[0] - origin[0], layer.pos[1] - origin[1]
        cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x0 + pw, w), min(y0 + ph, h)
        if cx0 >= cx1 or cy0 >= cy1:
            continue
        patch = layer.image[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0]
        mask = patch[..., 3] > 0
        canvas[cy0:cy1, cx0:cx1][mask] = patch[mask]
    return canvas


def render_rest(rgba: np.ndarray, rig: dict, parts: list[Part]) -> np.ndarray:
    """Rest pose rendered at the sprite's own size (equals the sprite when all pixels are assigned)."""
    pose, _ = solve_pose(rig, {})
    h, w = rgba.shape[:2]
    return compose(frame_layers(parts, rig, pose), (0, 0), (w, h))


def render_animation(rgba: np.ndarray, rig: dict, parts: list[Part], anim: dict, *,
                     method: str = "rotsprite", padding: int = 2,
                     outline: OutlineSpec | None = None, offsets: dict | None = None) -> RenderResult:
    """Render every frame of ``anim`` on a constant canvas with a stable pivot.

    ``outline`` (from ``outline_spec``) enables the outline pass on every frame.
    ``offsets`` (rest offsets, ``{bone: [dx, dy]}``) are applied to every frame.
    """
    if padding < 0:
        raise AnimaiError("padding must be >= 0")
    if not parts:
        raise AnimaiError("rig has no part with pixels: nothing to render")
    warnings: list[str] = []
    cache: dict = {}
    stacks: list[list[Layer]] = []
    poses: list[dict[str, BonePose]] = []
    px, py = compute_pivot(rgba, rig)
    box = (px, py, px, py)          # the pivot always lies inside the canvas
    for index, frame in enumerate(anim["frames"]):
        pose, pose_warnings = solve_pose(rig, frame, offsets)
        warnings += [f"frame {index}: {w}" for w in pose_warnings]
        layers = frame_layers(parts, rig, pose, frame.get("z"), method, cache)
        b = layers_bbox(layers)
        if b is not None:
            box = (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
        stacks.append(layers)
        poses.append(pose)
    origin = (box[0] - padding, box[1] - padding)
    size = (box[2] - box[0] + 2 * padding, box[3] - box[1] + 2 * padding)
    if size[0] <= 0 or size[1] <= 0:
        raise AnimaiError("animation renders no pixel")
    result = RenderResult([], size, origin, (px - origin[0], py - origin[1]), poses, warnings, stacks,
                          outline, rgba)
    result.frames = [finish_frame(result, layers) for layers in stacks]
    return result


def compose_owners(layers: list[Layer], origin: tuple[int, int], size: tuple[int, int],
                   part_index: dict[str, int]) -> np.ndarray:
    """``(H, W)`` int16 map: index (``part_index[name]``) of the part visible at each pixel, -1 elsewhere."""
    w, h = size
    owners = np.full((h, w), -1, dtype=np.int16)
    for layer in layers:
        ph, pw = layer.image.shape[:2]
        x0, y0 = layer.pos[0] - origin[0], layer.pos[1] - origin[1]
        cx0, cy0, cx1, cy1 = max(x0, 0), max(y0, 0), min(x0 + pw, w), min(y0 + ph, h)
        if cx0 >= cx1 or cy0 >= cy1:
            continue
        mask = layer.image[cy0 - y0:cy1 - y0, cx0 - x0:cx1 - x0, 3] > 0
        owners[cy0:cy1, cx0:cx1][mask] = part_index[layer.part]
    return owners


def pose_to_json(pose: dict[str, BonePose]) -> dict:
    """World pose as plain JSON: ``{bone: {"angle": deg, "joint": [x, y]}}`` (sprite coordinates)."""
    out = {}
    for name, bp in pose.items():
        angle = normalize_angle(bp.angle)
        out[name] = {"angle": int(angle) if float(angle).is_integer() else round(angle, 4),
                     "joint": [round_half_up(bp.pos[0]), round_half_up(bp.pos[1])]}
    return out
