"""Forward kinematics on the bone hierarchy, plus optional two-bone IK.

Conventions (see docs/schemas.md and docs/animation-guide.md, chapter 1)
------------------------------------------------------------------------
* Coordinates are sprite pixels, x right, y down. A joint ``[x, y]`` designates
  the centre of pixel ``(x, y)``.
* Positive ``rot`` turns counter-clockwise on screen (like ``PIL.Image.rotate``):
  ``x' = x cos a + y sin a``, ``y' = -x sin a + y cos a``. The point ``(0, 10)``
  under a joint, rotated by +90, lands on ``(10, 0)``.
* ``rot`` is local; the world angle of a bone is the sum along its chain.
* ``pos`` is a screen-axis offset (not rotated by the parent), applied to the
  bone's joint and inherited by its children::

      angle_world(B) = angle_world(P) + rot(B)
      joint_world(B) = joint_world(P) + R(angle_world(P)) . (jB - jP) + pos(B)

* Joint positions are accumulated in floating point along the chain. Rounding
  to the pixel grid happens once per part, at render time (``round_half_up``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .rig import bone_order


@dataclass(frozen=True)
class BonePose:
    angle: float                     # world rotation in degrees, counter-clockwise on screen
    pos: tuple[float, float]         # world position of the bone's joint (not rounded)


def round_half_up(v: float) -> int:
    return int(math.floor(v + 0.5))


def normalize_angle(deg: float) -> float:
    """Angle in ``(-180, 180]``; integers stay exact."""
    a = math.fmod(deg, 360.0)
    if a > 180.0:
        a -= 360.0
    elif a <= -180.0:
        a += 360.0
    return a + 0.0


def cos_sin(deg: float) -> tuple[float, float]:
    """cos/sin with exact values for multiples of 90 degrees."""
    a = deg % 360.0
    exact = {0.0: (1.0, 0.0), 90.0: (0.0, 1.0), 180.0: (-1.0, 0.0), 270.0: (0.0, -1.0)}
    if a in exact:
        return exact[a]
    r = math.radians(a)
    return math.cos(r), math.sin(r)


def rotate_vec(dx: float, dy: float, deg: float) -> tuple[float, float]:
    """Rotate a vector counter-clockwise on screen (y down)."""
    c, s = cos_sin(deg)
    return dx * c + dy * s, -dx * s + dy * c


def transform_point(pose: BonePose, joint, point) -> tuple[float, float]:
    """World position (float) of a rest-pose ``point`` rigidly attached to a bone."""
    rx, ry = rotate_vec(point[0] - joint[0], point[1] - joint[1], pose.angle)
    return pose.pos[0] + rx, pose.pos[1] + ry


def _solve_two_bone(a, t, len1, len2, rest1, rest2, turn):
    """Analytic two-bone IK in screen space.

    ``a`` = world anchor of the first bone, ``t`` = wanted target, ``rest1`` /
    ``rest2`` = rest directions of both bones (``atan2(dy, dx)``, radians),
    ``turn`` = wanted sign of ``sin(dir2 - dir1)``. Returns the world rotations
    of both bones (integer degrees, counter-clockwise positive), the reachable
    target and whether the target had to be clamped.
    """
    dx, dy = t[0] - a[0], t[1] - a[1]
    dist = math.hypot(dx, dy)
    base = math.atan2(dy, dx) if dist > 1e-9 else rest1
    lo, hi = abs(len1 - len2), len1 + len2
    clamped = dist > hi + 1e-9 or dist < lo - 1e-9
    dist = min(max(dist, lo, 1e-9), hi)
    cos_a = max(-1.0, min(1.0, (len1 * len1 + dist * dist - len2 * len2) / (2 * len1 * dist)))
    inner = math.acos(cos_a)
    tx, ty = a[0] + dist * math.cos(base), a[1] + dist * math.sin(base)
    best = None
    for sign in (1, -1):
        phi1 = base + sign * inner
        bx, by = a[0] + len1 * math.cos(phi1), a[1] + len1 * math.sin(phi1)
        phi2 = math.atan2(ty - by, tx - bx)
        score = math.sin(phi2 - phi1) * turn
        if best is None or score > best[0] + 1e-12:
            best = (score, phi1, phi2)
    _, phi1, phi2 = best
    # atan2 angles grow clockwise on screen; ``rot`` is counter-clockwise positive.
    rot1 = normalize_angle(float(round(-math.degrees(phi1 - rest1))))
    rot2 = normalize_angle(float(round(-math.degrees(phi2 - rest2))))
    return rot1, rot2, (tx, ty), clamped


def solve_pose(rig: dict, frame: dict, offsets: dict | None = None) -> tuple[dict[str, BonePose], list[str]]:
    """World pose of every bone for one animation frame.

    ``offsets`` (``{bone: [dx, dy]}``, from ``rig.rest_offsets``) are added to
    the ``pos`` of those bones, so they move the bone's joint and everything
    below it. An IK target moves by the sum of the offsets of its target bone
    and of all its ancestors, so the chain keeps its rest shape.

    ``frame["bones"][name]`` = ``{"rot": deg, "pos": [dx, dy]}`` (both optional,
    a missing bone is at rest: every frame is a complete pose).

    Optional IK, only when the frame has an ``ik`` object (presets have none, so
    the rig's ``ik`` block is ignored for them): ``frame["ik"][name]`` =
    ``{"pos": [dx, dy], "rot": deg}``. The target is the rest joint of the IK
    target bone moved by ``pos`` on screen; both chain bones are rotated (whole
    degrees) to reach it, the target bone's joint is pinned on the target and
    its world rotation is ``rot`` (default 0 = rest orientation).
    """
    bones = rig["bones"]
    frame_bones = frame.get("bones", {})
    warnings: list[str] = []
    ik_by_start = {}
    for name, target in frame.get("ik", {}).items():
        spec = rig.get("ik", {}).get(name)
        if spec is not None:
            ik_by_start[spec["chain"][0]] = (name, spec, target)

    world: dict[str, BonePose] = {}
    forced_angle: dict[str, float] = {}
    forced_pos: dict[str, tuple[float, float]] = {}
    for name in bone_order(rig):
        bone = bones[name]
        local = frame_bones.get(name, {})
        rot = float(local.get("rot", 0))
        px, py = local.get("pos", [0, 0])
        if offsets and name in offsets:
            px, py = px + offsets[name][0], py + offsets[name][1]
        jx, jy = bone["joint"]
        parent = bone.get("parent")
        if parent is None:
            parent_angle = 0.0
            anchor = (float(jx + px), float(jy + py))
        else:
            pw = world[parent]
            parent_angle = pw.angle
            wx, wy = transform_point(pw, bones[parent]["joint"], (jx, jy))
            anchor = (wx + px, wy + py)

        if name in ik_by_start:
            ik_name, spec, target = ik_by_start[name]
            mid, end = spec["chain"][1], spec["target_bone"]
            jm, je = bones[mid]["joint"], bones[end]["joint"]
            v1 = (jm[0] - jx, jm[1] - jy)
            v2 = (je[0] - jm[0], je[1] - jm[1])
            # ``bend`` = sign of the middle bone's local rot when the chain folds
            # (-1: knee, +1: elbow, character facing right). Internal turn sign is opposite.
            bend = spec.get("bend", -1)
            off = target.get("pos", [0, 0])
            goal = [je[0] + off[0], je[1] + off[1]]
            walker = end
            while offsets and walker is not None:       # offsets inherited along the chain
                if walker in offsets:
                    goal[0] += offsets[walker][0]
                    goal[1] += offsets[walker][1]
                walker = bones[walker].get("parent")
            goal = tuple(goal)
            rot1, rot2, reached, clamped = _solve_two_bone(
                anchor, goal, math.hypot(*v1), math.hypot(*v2),
                math.atan2(v1[1], v1[0]), math.atan2(v2[1], v2[0]), -bend)
            if clamped:
                warnings.append(f"ik '{ik_name}': target {list(goal)} out of reach, clamped to "
                                f"[{round_half_up(reached[0])}, {round_half_up(reached[1])}]")
            forced_angle[name] = rot1
            forced_angle[mid] = rot2
            forced_angle[end] = float(target.get("rot", 0))
            forced_pos[end] = reached

        angle = forced_angle.get(name, parent_angle + rot)
        world[name] = BonePose(normalize_angle(angle), forced_pos.get(name, anchor))
    return world, warnings
