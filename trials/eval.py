"""Measured part of the evaluation grid (docs/animation-guide.md, chapter 6).
Usage: python trials/eval.py <sprite dir name> [preset ...]
Trial helper of the animation expert. Reads only files produced by the CLI."""
import json, os, sys
from collections import deque
from PIL import Image

ROOT = os.path.dirname(os.path.abspath(__file__))
s = sys.argv[1]
presets = sys.argv[2:] or ["idle", "walk", "attack"]
D = os.path.join(ROOT, s)
sprite = Image.open(os.path.join(D, "sprite.png")).convert("RGBA")
rig = json.load(open(os.path.join(D, "rig.json")))
SW, SH = sprite.size
spx = sprite.load()


def opaque(im):
    w, h = im.size
    p = im.load()
    return {(x, y) for y in range(h) for x in range(w) if p[x, y][3] > 0}


def part_pixels(name):
    """Own pixels of a part, from the rig regions (rects only, enough for my rigs)."""
    out = set()
    for pn, part in rig["parts"].items():
        px = set()
        for x, y, w, h in part["region"].get("rects", []):
            px |= {(i, j) for i in range(x, x + w) for j in range(y, y + h) if spx[i, j][3] > 0}
        if pn == name:
            out = px
    return out


def outline_color():
    op = opaque(sprite)
    edge = [p for p in op if any((p[0] + dx, p[1] + dy) not in op for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
    cnt = {}
    for p in edge:
        cnt[spx[p][:3]] = cnt.get(spx[p][:3], 0) + 1
    c, n = max(cnt.items(), key=lambda kv: kv[1])
    return (c if n >= 0.6 * len(edge) else None), len(edge)


OUTLINE, _ = outline_color()
src_colors = {spx[p] for p in opaque(sprite)}


def enclosed(im, maxarea=6):
    """Transparent 4-connected components not touching the canvas border, area <= maxarea."""
    w, h = im.size
    op = opaque(im)
    seen = set()
    res = []
    for y in range(h):
        for x in range(w):
            if (x, y) in op or (x, y) in seen:
                continue
            comp, q, border = [], deque([(x, y)]), False
            seen.add((x, y))
            while q:
                cx, cy = q.popleft()
                comp.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if not (0 <= nx < w and 0 <= ny < h):
                        border = True
                        continue
                    if (nx, ny) not in op and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        q.append((nx, ny))
            if not border and len(comp) <= maxarea:
                res.append(comp)
    return res


def slits(im):
    """Transparent pixels with opaque pixels both left and right within 1 px (1 px wide vertical cracks)
    or both above and below (horizontal cracks)."""
    w, h = im.size
    op = opaque(im)
    v = [(x, y) for y in range(h) for x in range(1, w - 1) if (x, y) not in op and (x - 1, y) in op and (x + 1, y) in op]
    hz = [(x, y) for y in range(1, h - 1) for x in range(w) if (x, y) not in op and (x, y - 1) in op and (x, y + 1) in op]
    return v, hz


def orphans(im):
    op = opaque(im)
    return [p for p in op if not any((p[0] + dx, p[1] + dy) in op for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy)]


def run(preset):
    F = os.path.join(D, "frames", preset)
    m = json.load(open(os.path.join(F, "frames.json")))
    ox, oy = m["origin"]
    pvx, pvy = m["pivot"]
    ims = [Image.open(os.path.join(F, f["file"])).convert("RGBA") for f in m["frames"]]
    R = {}
    # A1 / A2
    bad_col = [i for i, im in enumerate(ims) if not {im.load()[p] for p in opaque(im)} <= src_colors]
    R["A1 palette"] = (not bad_col, f"frames with new colours: {bad_col}")
    bad_a = [i for i, im in enumerate(ims) if set(im.getchannel("A").tobytes()) - {0, 255}]
    R["A2 alpha"] = (not bad_a, f"{bad_a}")
    # A3 rest frame identical to sprite
    def same_as_sprite(im):
        w, h = im.size
        p = im.load()
        diff = [(x, y) for y in range(h) for x in range(w)
                if (p[x, y] if p[x, y][3] else (0, 0, 0, 0)) !=
                ((spx[x + ox, y + oy] if spx[x + ox, y + oy][3] else (0, 0, 0, 0))
                 if 0 <= x + ox < SW and 0 <= y + oy < SH else (0, 0, 0, 0))]
        return diff
    if preset == "idle":
        d = same_as_sprite(ims[0])
        R["A3 idle f0 == sprite"] = (not d, f"{len(d)} px differ {d[:3]}")
    # A4 head keeps source pixels (world angle 0), ignoring pixels covered by something else
    head = part_pixels("head")
    if head and "head" in m["frames"][0]["bones"]:
        rj = m["rest"]["bones"]["head"]["joint"]
        worst = []
        for i, (f, im) in enumerate(zip(m["frames"], ims)):
            b = f["bones"]["head"]
            if b["angle"] != 0:
                worst.append((i, "angle %s" % b["angle"]))
                continue
            dx, dy = b["joint"][0] - rj[0] - ox, b["joint"][1] - rj[1] - oy
            p = im.load()
            miss = [(x + dx, y + dy) for (x, y) in head if p[x + dx, y + dy] != spx[x, y]]
            if miss:
                worst.append((i, len(miss), miss[0]))
        R["A4 head pixels intact (uncovered)"] = (not worst, f"(frame, px changed, first canvas px): {worst}")
    # A6 orphans
    so = len(orphans(sprite))
    o = [(i, len(orphans(im)), orphans(im)[0]) for i, im in enumerate(ims) if len(orphans(im)) > so]
    R["A6 orphans"] = (not o, f"{o}")
    # B1 holes (QA) + small enclosed voids + cracks
    rep = json.load(open(os.path.join(F, "report.json")))
    qa = {c["id"]: c["pass"] for c in rep["checks"]}
    R["B1 QA holes"] = (qa.get("holes", False), "report.json")
    enc = [(i, len(c), c[0]) for i, im in enumerate(ims) for c in enclosed(im)]
    R["B1b enclosed voids <=6px (frame, area, canvas px)"] = (not enc, f"{enc}")
    sl = []
    for i, im in enumerate(ims):
        v, hz = slits(im)
        sv, sh = slits(sprite)
        if len(v) > len(sv) or len(hz) > len(sh):
            sl.append((i, len(v) - len(sv), len(hz) - len(sh), (v + hz)[0]))
    R["B4b 1px cracks vs sprite (frame, +vert, +horiz, first)"] = (None, f"{sl}")
    # C1 outline
    if OUTLINE:
        res = []
        for i, im in enumerate(ims):
            op = opaque(im)
            p = im.load()
            edge = [q for q in op if any((q[0] + dx, q[1] + dy) not in op for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))]
            bad = [q for q in edge if p[q][:3] != OUTLINE]
            res.append((i, len(bad), len(edge)))
        R["C1 silhouette px not outline colour (frame, bad, edge)"] = (all(b == 0 for _, b, _ in res), f"{res}")
    # D
    R["D1 canvas constant"] = (len({im.size for im in ims}) == 1 and qa["canvas_constant"], f"{ims[0].size}")
    R["D2 pivot constant"] = (len({tuple(f["pivot"]) for f in m["frames"]}) == 1 and qa["pivot_stable"], f"{m['pivot']}")
    lows = [max(y for _, y in opaque(im)) + 1 - pvy for im in ims]
    R["D5 lowest opaque row vs ground (0 = on the line, + = below)"] = (max(abs(v) for v in lows) <= 1, f"{lows}")
    if preset == "idle":
        waist = m["rest"]["bones"].get("shin_r", m["rest"]["bones"]["hips"])["joint"][1] - oy
        base = ims[0].crop((0, waist, ims[0].width, ims[0].height))
        same = [im.crop((0, waist, im.width, im.height)).tobytes() == base.tobytes() for im in ims]
        R["D3 idle legs still (from knee, canvas row %d)" % waist] = (all(same), f"{same}")
        mv = []
        for i in range(len(ims)):
            a, b = opaque(ims[i]), opaque(ims[(i + 1) % len(ims)])
            mv.append(len(a ^ b))
        R["D4 idle silhouette px changed per step"] = (None, f"{mv}")
    if preset == "walk":
        hj = [f["bones"]["head"]["joint"] for f in m["frames"]] if "head" in m["frames"][0]["bones"] else []
        R["D6 walk head x constant, y range 1"] = (len({j[0] for j in hj}) == 1 and max(j[1] for j in hj) - min(j[1] for j in hj) == 1, f"{hj}")
        w0 = ims[0].getbbox(); w4 = ims[4].getbbox()
        R["E2 bbox width f0 vs f4"] = (abs((w0[2] - w0[0]) - (w4[2] - w4[0])) <= 1, f"{w0[2]-w0[0]} vs {w4[2]-w4[0]}")
        b0 = m["frames"][0]["bones"]; b4 = m["frames"][4]["bones"]
        if "arm_r" in b0 and "thigh_r" in b0:
            e1 = (b0["arm_r"]["angle"] < 0 < b0["thigh_r"]["angle"]) and (b4["arm_r"]["angle"] > 0 > b4["thigh_r"]["angle"])
            R["E1 opposition f0/f4"] = (e1, f"arm_r {b0['arm_r']['angle']}/{b4['arm_r']['angle']} thigh_r {b0['thigh_r']['angle']}/{b4['thigh_r']['angle']}")
        R["E4 a foot on the ground row each frame"] = (all(v >= 0 for v in lows), f"{lows}")
    if preset == "attack":
        d = same_as_sprite(ims[-1])
        R["E10 last frame == rest sprite"] = (not d, f"{len(d)} px differ")
        knee = m["rest"]["bones"].get("shin_r", m["rest"]["bones"]["hips"])["joint"][1] - oy + 3
        base = None
        feet = []
        for i in (0, 1, 5, 6):
            c = ims[i].crop((0, knee, ims[i].width, ims[i].height)).tobytes()
            base = base or c
            feet.append(c == base)
        R["D7 feet identical in f0,1,5,6"] = (all(feet), f"{feet}")
        reach = [im.getbbox()[2] for im in ims]
        R["E9 furthest reach frame"] = (None, f"right edge per frame {reach}, durations {[f['duration_ms'] for f in m['frames']]}")
    R["QA loop_closed/orphans/parts"] = (qa["loop_closed"] and qa["orphans"] and qa["parts_assigned"], f"{qa}")
    ej = os.path.join(F, "export", m["name"] + ".json")
    if os.path.exists(ej):
        e = json.load(open(ej))
        R["F1/F2 export durations"] = ([fr["duration"] for fr in e["frames"]] == [f["duration_ms"] for f in m["frames"]],
                                       f"{[fr['duration'] for fr in e['frames']]} pivot {e['meta']['animai']['pivot']}")
    print(f"== {s} / {preset}  canvas {m['canvas']} origin {m['origin']} pivot {m['pivot']}")
    for k, (ok, det) in R.items():
        print(f"  {'PASS' if ok else ('info' if ok is None else 'FAIL')}  {k}: {det}")


for p in presets:
    run(p)
