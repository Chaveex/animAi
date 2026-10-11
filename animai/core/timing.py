"""Duration handling: ``--duration`` / ``--frames`` / ``--fps`` and stepped resampling."""
from __future__ import annotations

import copy
import re

from .errors import AnimaiError

DEFAULT_FPS = 10
RECOMMENDED_MAX_FRAMES = 8


def parse_duration(text: str | int | float) -> int:
    """Duration in milliseconds from ``"0.8s"``, ``"800ms"`` or a bare number of seconds."""
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*(ms|s)?\s*", str(text))
    if not m:
        raise AnimaiError(f"invalid duration '{text}' (examples: 0.8s, 800ms)")
    value = float(m.group(1))
    ms = value if m.group(2) == "ms" else value * 1000.0
    ms_int = int(round(ms))
    if ms_int <= 0:
        raise AnimaiError("duration must be > 0")
    return ms_int


def frame_durations(anim: dict) -> list[int]:
    """Per-frame durations in ms (missing ``duration_ms`` = one tick at ``fps``)."""
    fps = float(anim.get("fps", DEFAULT_FPS))
    default = max(1, int(round(1000.0 / fps)))
    return [int(round(f.get("duration_ms", default))) for f in anim["frames"]]


def resolve_timing(n_src: int, total_src_ms: int, *, duration_ms: int | None = None,
                   frames: int | None = None, fps: float | None = None) -> tuple[int | None, int]:
    """Resolve the requested timing.

    Returns ``(frames, duration_ms)``. ``frames`` is None when the source frames
    are kept as they are and only their durations are scaled (``--duration`` alone
    or no option). Any two of the three options determine the third; three
    inconsistent options, or a duration that is not a whole number of frames at
    the given fps, raise AnimaiError.
    """
    if frames is not None and frames < 1:
        raise AnimaiError("--frames must be >= 1")
    if fps is not None and fps <= 0:
        raise AnimaiError("--fps must be > 0")
    if duration_ms is not None and duration_ms <= 0:
        raise AnimaiError("--duration must be > 0")

    if duration_ms is not None and fps is not None:
        exact = duration_ms * fps / 1000.0
        if frames is not None:
            if abs(frames * 1000.0 / fps - duration_ms) > 1.0:
                raise AnimaiError(
                    f"inconsistent timing: {frames} frames at {fps:g} fps last "
                    f"{frames * 1000.0 / fps:g} ms, but --duration is {duration_ms} ms")
            return frames, duration_ms
        n = int(round(exact))
        if n < 1 or abs(exact - n) > 1e-6 * max(1.0, exact) + 1e-3 * fps:
            raise AnimaiError(
                f"inconsistent timing: {duration_ms} ms at {fps:g} fps is {exact:g} frames, "
                "not a whole number; adjust --duration or --fps, or give --frames")
        return n, duration_ms
    if frames is not None and fps is not None:
        return frames, max(1, int(round(frames * 1000.0 / fps)))
    if frames is not None:
        return frames, duration_ms if duration_ms is not None else total_src_ms
    if fps is not None:
        n = max(1, int(round(total_src_ms * fps / 1000.0)))
        return n, max(1, int(round(n * 1000.0 / fps)))
    return None, duration_ms if duration_ms is not None else total_src_ms


def _split(total: int, weights: list[int]) -> list[int]:
    """Split ``total`` proportionally to ``weights``; integers summing exactly to ``total``."""
    wsum = sum(weights)
    out, acc, prev = [], 0, 0
    for w in weights:
        acc += w
        cur = (2 * acc * total + wsum) // (2 * wsum)   # round half up, integer arithmetic
        out.append(cur - prev)
        prev = cur
    return out


def frame_priority(frame: dict) -> float:
    """Key-pose priority of a frame: ``"key": true`` = 1, a number = itself, absent = 0."""
    key = frame.get("key", False)
    if isinstance(key, bool):
        return 1.0 if key else 0.0
    return float(key)


def select_frames(frames: list[dict], durations: list[int], n: int, loop: bool) -> tuple[list[int], list[str]]:
    """Which ``n`` source frames survive when there are more than ``n`` (no pose is ever invented).

    1. Key poses first: frames with priority > 0 (``frame_priority``), highest
       priority first, then longest, then earliest, as long as there is room.
    2. The remaining slots go, one at a time, to the frame that starts farthest
       in time from every frame already kept (circular distance for a loop;
       ties: earliest frame). With nothing kept yet the first frame is taken, so
       an unmarked animation keeps frame 0, and its last frame when it is not a loop.

    Returns the kept indices in playback order, and warnings (key poses dropped).
    """
    count = len(frames)
    total = sum(durations)
    starts, acc = [], 0
    for d in durations:
        starts.append(acc)
        acc += d
    keys = [i for i in range(count) if frame_priority(frames[i]) > 0]
    keys.sort(key=lambda i: (-frame_priority(frames[i]), -durations[i], i))
    kept = keys[:n]
    warnings = []
    if len(keys) > n:
        lost = sorted(keys[n:])
        names = [f"{i} ({frames[i]['label']})" if frames[i].get("label") else str(i) for i in lost]
        warnings.append(f"only {n} frames: key poses dropped: {', '.join(names)}")

    def distance(i: int, j: int) -> int:
        d = abs(starts[i] - starts[j])
        return min(d, total - d) if loop else d

    while len(kept) < n:
        if not kept:
            kept.append(0)
            continue
        best = max((i for i in range(count) if i not in kept),
                   key=lambda i: (min(distance(i, j) for j in kept), -i))
        kept.append(best)
    return sorted(kept), warnings


def resample(anim: dict, *, duration_ms: int | None = None, frames: int | None = None,
             fps: float | None = None) -> tuple[dict, list[int], list[str]]:
    """Stepped resampling of an animation (no pose interpolation, ever).

    When a frame count N results from the options, the output has N frames of
    equal duration. With N >= source count, every source frame is kept and the
    extra frames go to the longest-held ones; a warning tells when the holds
    could not stay proportional. With N < source count, ``select_frames``
    chooses the survivors (key poses first) and the dropped frames are listed
    in a warning. Otherwise (``--duration`` alone) every source frame is kept,
    in order, with durations scaled proportionally; ``fps`` (the base tick) is
    scaled by the same factor.

    Returns ``(new_anim, source_indices, warnings)``.
    """
    src_durations = frame_durations(anim)
    if any(d <= 0 for d in src_durations):
        raise AnimaiError("duration_ms must be > 0 for every frame")
    total_src = sum(src_durations)
    n_src = len(src_durations)
    n, total = resolve_timing(n_src, total_src, duration_ms=duration_ms, frames=frames, fps=fps)
    warnings: list[str] = []

    if n is None:
        indices = list(range(n_src))
        durations = src_durations if total == total_src else _split(total, src_durations)
    else:
        indices = []
        if n >= n_src:
            # Every source frame keeps at least one output frame; the extra ones go,
            # one at a time, to the frame with the largest duration per output frame.
            # Integer arithmetic only.
            counts = [1] * n_src
            starts, acc = [], 0
            for d in src_durations:
                starts.append(acc)
                acc += d
            loop = bool(anim.get("loop", True))

            def apart(i: int, others: list[int]) -> int:
                gaps = [abs(starts[i] - starts[j]) for j in others]
                return min(min(g, total_src - g) if loop else g for g in gaps) if gaps else 0

            for _ in range(n - n_src):
                best = 0
                for i in range(1, n_src):
                    if src_durations[i] * counts[best] > src_durations[best] * counts[i]:
                        best = i
                # among the frames tied with the best ratio, take the one farthest in time
                # from the frames already repeated, so the additions are spread over the cycle
                tied = [i for i in range(n_src)
                        if src_durations[i] * counts[best] == src_durations[best] * counts[i]]
                given = [j for j in range(n_src) if counts[j] > 1]
                best = max(tied, key=lambda i: (apart(i, given), -i))
                counts[best] += 1
            for i, c in enumerate(counts):
                indices += [i] * c
        else:
            indices, key_warnings = select_frames(anim["frames"], src_durations, n, bool(anim.get("loop", True)))
            warnings += key_warnings
        durations = _split(total, [1] * n)
        dropped = sorted(set(range(n_src)) - set(indices))
        if dropped:
            warnings.append(f"resampling to {n} frames drops source frames {dropped}")
        else:
            # every pose is kept, but a uniform grid cannot always keep the holds proportional
            counts = [indices.count(i) for i in range(n_src)]
            changed = [i for i in range(n_src)
                       if abs(counts[i] * total_src * 10 - src_durations[i] * n * 10) > src_durations[i] * n]
            if changed:
                before = [round(d * total / total_src) for d in src_durations]
                after = [round(c * total / n) for c in counts]
                warnings.append(f"resampling to {n} equal frames changes the holds of source frames {changed}: "
                                f"{before} ms would be proportional, got {after} ms")
    if any(d <= 0 for d in durations):
        raise AnimaiError(f"duration {total} ms is too short for {len(durations)} frames (min 1 ms each)")
    if len(durations) > RECOMMENDED_MAX_FRAMES:
        warnings.append(f"{len(durations)} frames: more than {RECOMMENDED_MAX_FRAMES} "
                        "is hard to read in pixel art")

    out = {k: copy.deepcopy(v) for k, v in anim.items() if k != "frames"}
    out["frames"] = []
    for i, d in zip(indices, durations):
        f = copy.deepcopy(anim["frames"][i])
        f["duration_ms"] = d
        out["frames"].append(f)
    if n is None:
        # frames kept: the base tick scales with the durations
        out["fps"] = round(float(anim.get("fps", DEFAULT_FPS)) * total_src / total, 4)
    else:
        out["fps"] = round(n * 1000.0 / total, 4)
    return out, indices, warnings
