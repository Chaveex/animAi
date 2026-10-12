// ============================================================================
//  SIMULATION DU CŒUR — DÉMO UNIQUEMENT
// ----------------------------------------------------------------------------
//  Tout ce fichier remplace, de façon SIMPLIFIÉE, des fonctions qui
//  appartiennent au cœur Python (animai/core) : codec des régions, rendu des
//  frames, QA, rééchantillonnage, presets, template de squelette.
//
//  Il n'est importé QUE par demo-backend.js. L'UI ne l'importe jamais.
//  En production, ces résultats viennent du serveur (voir docs/ux-spec.md § 13) :
//  l'aperçu est rendu par le moteur du cœur, jamais ré-implémenté côté UI.
//
//  Écarts connus avec le vrai moteur (ne pas s'y fier pour juger un rendu) :
//   - rotation en plus-proche-voisin à angle libre (le cœur : RotSprite) ;
//   - `pos` suit la rotation du parent (dans le cœur il reste en axes écran) ;
//   - pas d'IK, pas de zones de chevauchement, pas de remplissage des pixels cachés ;
//   - QA partielle (plusieurs contrôles renvoient pass = null : « non vérifié »).
// ============================================================================

const clone = (v) => (v === undefined ? undefined : JSON.parse(JSON.stringify(v)));

// --- Codec régions <-> label map --------------------------------------------

/** rig.parts[*].region -> label map (index de pièce par pixel, -1 = non assigné ou transparent). */
export function decodeRegions(rig, sprite) {
  const { width: w, height: h, data } = sprite;
  const parts = Object.keys(rig.parts || {});
  const labels = new Int16Array(w * h).fill(-1);
  let overlaps = 0;
  parts.forEach((name, k) => {
    const reg = rig.parts[name].region || {};
    const put = (x, y) => {
      if (x < 0 || y < 0 || x >= w || y >= h) return;
      const i = y * w + x;
      if (data[i * 4 + 3] === 0) return;
      if (labels[i] !== -1 && labels[i] !== k) overlaps++; // la dernière pièce définie gagne
      labels[i] = k;
    };
    for (const [x, y, rw, rh] of reg.rects || []) {
      for (let yy = y; yy < y + rh; yy++) for (let xx = x; xx < x + rw; xx++) put(xx, yy);
    }
    for (const [x, y] of reg.pixels || []) put(x, y);
  });
  return { parts, labels, overlaps };
}

/** label map -> régions canoniques (partition sans chevauchement : rects fusionnés + pixels isolés). */
export function encodeRegions(labels, parts, w, h) {
  const runs = parts.map(() => []);
  for (let y = 0; y < h; y++) {
    let x = 0;
    while (x < w) {
      const k = labels[y * w + x];
      let x1 = x + 1;
      while (x1 < w && labels[y * w + x1] === k) x1++;
      if (k >= 0 && k < parts.length) runs[k].push([x, y, x1 - x]);
      x = x1;
    }
  }
  const out = {};
  parts.forEach((name, k) => {
    const rects = [];
    const open = new Map();
    for (const [x, y, len] of runs[k]) {
      const key = x + ':' + len;
      const r = open.get(key);
      if (r && r[1] + r[3] === y) r[3]++;
      else {
        const nr = [x, y, len, 1];
        rects.push(nr);
        open.set(key, nr);
      }
    }
    out[name] = {
      rects: rects.filter((r) => r[2] * r[3] > 1),
      pixels: rects.filter((r) => r[2] * r[3] === 1).map((r) => [r[0], r[1]]),
    };
  });
  return out;
}

// --- Préparation (simulée) ---------------------------------------------------

/** Binarise l'alpha (seuil 128). Le vrai `prepare` détecte aussi la grille, détoure et quantifie. */
export function prepareImage(img) {
  const data = new Uint8ClampedArray(img.data);
  let nonBinary = 0;
  for (let i = 0; i < data.length; i += 4) {
    const a = data[i + 3];
    if (a !== 0 && a !== 255) nonBinary++;
    if (a >= 128) data[i + 3] = 255;
    else data[i] = data[i + 1] = data[i + 2] = data[i + 3] = 0;
  }
  return { sprite: { width: img.width, height: img.height, data }, nonBinary };
}

export function extractPalette(sprite) {
  const set = new Set();
  const d = sprite.data;
  for (let i = 0; i < d.length; i += 4) {
    if (d[i + 3] === 255) set.add((d[i] << 16) | (d[i + 1] << 8) | d[i + 2]);
  }
  return [...set].map((v) => '#' + v.toString(16).padStart(6, '0'));
}

export function opaqueBBox(sprite) {
  const { width: w, height: h, data } = sprite;
  let x0 = w, y0 = h, x1 = -1, y1 = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (data[(y * w + x) * 4 + 3]) {
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      if (y > y1) y1 = y;
    }
  }
  return x1 < 0 ? { x: 0, y: 0, w, h } : { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
}

// --- Template de squelette (simulé) -------------------------------------------

const HUMANOID = [
  // os, parent, position relative dans la bbox opaque, z de la pièce
  ['hips', null, 0.5, 0.58, 0],
  ['spine', 'hips', 0.5, 0.52, 1],
  ['head', 'spine', 0.5, 0.24, 2],
  ['arm_r', 'spine', 0.48, 0.3, 4],
  ['forearm_r', 'arm_r', 0.48, 0.42, 5],
  ['hand_r', 'forearm_r', 0.48, 0.54, 5],
  ['arm_l', 'spine', 0.6, 0.3, -3],
  ['forearm_l', 'arm_l', 0.6, 0.42, -3],
  ['hand_l', 'forearm_l', 0.6, 0.54, -3],
  ['thigh_r', 'hips', 0.42, 0.62, 3],
  ['shin_r', 'thigh_r', 0.42, 0.78, 3],
  ['foot_r', 'shin_r', 0.42, 0.94, 3],
  ['thigh_l', 'hips', 0.58, 0.62, -2],
  ['shin_l', 'thigh_l', 0.58, 0.78, -2],
  ['foot_l', 'shin_l', 0.58, 0.94, -2],
];

/** Rig humanoïde posé proportionnellement sur la bbox ; aucune pièce n'a encore de pixels. */
export function templateRig(sprite, spriteName = 'sprite.png') {
  const b = opaqueBBox(sprite);
  const bones = {};
  const parts = {};
  for (const [name, parent, rx, ry, z] of HUMANOID) {
    bones[name] = { parent, joint: [Math.round(b.x + rx * (b.w - 1)), Math.round(b.y + ry * (b.h - 1))] };
    const partName = name === 'hips' ? 'pelvis' : name === 'spine' ? 'torso' : name;
    parts[partName] = { bone: name, z, region: { rects: [], pixels: [] }, overlap: 1 };
  }
  return {
    version: 1,
    sprite: spriteName,
    view: 'side',
    template: 'humanoid',
    pivot: [0.5, 1.0],
    bones,
    parts,
    ik: {
      foot_r: { chain: ['thigh_r', 'shin_r'], target_bone: 'foot_r' },
      foot_l: { chain: ['thigh_l', 'shin_l'], target_bone: 'foot_l' },
    },
  };
}

// --- Presets (PLACEHOLDERS de démo ; les vrais vivent dans animai/presets) ----

const mirrorKeys = (bones) => {
  const out = {};
  for (const [k, v] of Object.entries(bones)) {
    const m = k.endsWith('_r') ? k.slice(0, -2) + '_l' : k.endsWith('_l') ? k.slice(0, -2) + '_r' : k;
    out[m] = v;
  }
  return out;
};

const PRESETS = {
  idle: () => {
    const up = { spine: { pos: [0, 0] } };
    const down = { spine: { pos: [0, 1] }, forearm_r: { rot: 15 } };
    return { fps: 5, frames: [up, down, down, up].map((bones) => ({ duration_ms: 200, bones })) };
  },
  walk: () => {
    const contact = {
      thigh_r: { rot: 30 }, shin_r: { rot: -15 },
      thigh_l: { rot: -30 }, shin_l: { rot: -15 },
      arm_r: { rot: -30 }, forearm_r: { rot: 15 }, arm_l: { rot: 30 },
    };
    const down = {
      hips: { pos: [0, 1] },
      thigh_r: { rot: 15 }, shin_r: { rot: -15 },
      thigh_l: { rot: -15 }, shin_l: { rot: -30 },
      arm_r: { rot: -15 }, arm_l: { rot: 15 },
    };
    const pass = { hips: { pos: [0, -1] }, thigh_l: { rot: 15 }, shin_l: { rot: -45 } };
    const half = [contact, down, pass];
    const frames = [...half, ...half.map((f) => ({ ...mirrorKeys(f), ...(f.hips ? { hips: f.hips } : {}) }))];
    return { fps: 10, frames: frames.map((bones) => ({ duration_ms: 100, bones })) };
  },
  attack: () => ({
    fps: 10,
    frames: [
      { duration_ms: 120, bones: { arm_r: { rot: -45 }, forearm_r: { rot: -30 }, spine: { pos: [-1, 0] } } },
      { duration_ms: 80, bones: { arm_r: { rot: 45 }, forearm_r: { rot: 15 } } },
      { duration_ms: 60, bones: { arm_r: { rot: 90 }, forearm_r: { rot: 0 }, spine: { pos: [1, 0] } } },
      { duration_ms: 160, bones: { arm_r: { rot: 90 }, spine: { pos: [1, 0] } } },
      { duration_ms: 120, bones: { arm_r: { rot: 30 } } },
    ],
  }),
};

export const PRESET_NAMES = Object.keys(PRESETS);

/** Preset retargeté : les os absents du rig sont ignorés (avertissement). */
export function buildPreset(name, rig) {
  const make = PRESETS[name];
  if (!make) throw new Error(`Preset inconnu : ${name}`);
  const p = make();
  const warnings = new Set();
  const frames = p.frames.map((f) => {
    const bones = {};
    for (const [b, v] of Object.entries(f.bones)) {
      if (rig.bones[b]) bones[b] = clone(v);
      else warnings.add(`os absent du rig, ignoré : ${b}`);
    }
    return { duration_ms: f.duration_ms, bones };
  });
  return { anim: { version: 1, name, loop: name !== 'attack', fps: p.fps, frames }, warnings: [...warnings] };
}

/**
 * Rééchantillonnage simplifié (timing stepped). Un, deux ou trois paramètres parmi
 * frames / fps / duration_ms, mêmes règles que le cœur (docs/schemas.md « Rééchantillonnage ») :
 * durée seule = toutes les frames, durées à l'échelle ; trois paramètres incohérents = erreur.
 */
export function retime(anim, { frames, fps, duration_ms }) {
  const src = anim.frames;
  const srcTotal = src.reduce((s, f) => s + f.duration_ms, 0);
  const given = [frames, fps, duration_ms].filter((v) => v != null).length;
  if (!given) throw new Error('Donnez au moins un paramètre parmi frames, fps et durée.');
  if (given === 3 && Math.abs((frames * 1000) / fps - duration_ms) > 1) {
    throw new Error(`Incohérence : ${frames} frames à ${fps} fps font ${Math.round((frames * 1000) / fps)} ms, pas ${duration_ms} ms.`);
  }
  const keepAll = given === 1 && duration_ms != null; // durée seule : aucune frame ajoutée ni perdue
  if (duration_ms == null) duration_ms = frames != null && fps != null ? Math.round((frames * 1000) / fps) : srcTotal;
  if (frames == null) frames = keepAll ? src.length : fps != null ? Math.round((duration_ms * fps) / 1000) : src.length;
  if (!(frames >= 1) || !(duration_ms >= frames)) throw new Error('Durée ou nombre de frames invalide.');
  frames = Math.round(frames);

  const out = [];
  if (keepAll) {
    // même découpage : durées mises à l'échelle (held frames proportionnelles)
    let acc = 0, used = 0;
    src.forEach((f, i) => {
      acc += f.duration_ms;
      const end = i === src.length - 1 ? duration_ms : Math.round((acc / srcTotal) * duration_ms);
      out.push({ ...clone(f), duration_ms: Math.max(1, end - used) });
      used = end;
    });
  } else {
    let used = 0;
    for (let k = 0; k < frames; k++) {
      const t = (k / frames) * srcTotal;
      let acc = 0, j = 0;
      while (j < src.length - 1 && acc + src[j].duration_ms <= t) acc += src[j++].duration_ms;
      const end = Math.round(((k + 1) / frames) * duration_ms);
      out.push({ ...clone(src[j]), duration_ms: Math.max(1, end - used) });
      used = end;
    }
  }
  const newFps = keepAll ? ((anim.fps || 10) * srcTotal) / duration_ms : (frames * 1000) / duration_ms;
  return { ...clone(anim), fps: Math.max(1, Math.round(newFps * 100) / 100), frames: out };
}

// --- Rendu de frame (SIMPLIFIÉ) ------------------------------------------------

const I = [1, 0, 0, 1, 0, 0];
const mul = (A, B) => [
  A[0] * B[0] + A[2] * B[1], A[1] * B[0] + A[3] * B[1],
  A[0] * B[2] + A[2] * B[3], A[1] * B[2] + A[3] * B[3],
  A[0] * B[4] + A[2] * B[5] + A[4], A[1] * B[4] + A[3] * B[5] + A[5],
];
const inv = (M) => {
  const det = M[0] * M[3] - M[1] * M[2];
  const a = M[3] / det, b = -M[1] / det, c = -M[2] / det, d = M[0] / det;
  return [a, b, c, d, -(a * M[4] + c * M[5]), -(b * M[4] + d * M[5])];
};
const trig = (deg) => {
  const r = (deg * Math.PI) / 180;
  const snap = (v) => (Math.abs(v - Math.round(v)) < 1e-12 ? Math.round(v) : v);
  return [snap(Math.cos(r)), snap(Math.sin(r))];
};

/** Matrices monde par os pour une frame (cinématique directe ; rot positif = anti-horaire à l'écran, comme le cœur). */
function poseBones(rig, frame) {
  const memo = {};
  const get = (b, depth = 0) => {
    if (memo[b]) return memo[b];
    const bone = rig.bones[b];
    if (!bone || depth > 64) return I;
    const P = bone.parent ? get(bone.parent, depth + 1) : I;
    const k = (frame && frame.bones && frame.bones[b]) || {};
    const [px, py] = k.pos || [0, 0];
    const [cos, sin] = trig(-(k.rot || 0));
    const cx = bone.joint[0] + 0.5, cy = bone.joint[1] + 0.5;
    const L = [cos, sin, -sin, cos, cx - cos * cx + sin * cy + px, cy - sin * cx - cos * cy + py];
    return (memo[b] = mul(P, L));
  };
  for (const b of Object.keys(rig.bones)) get(b);
  return memo;
}

export const RENDER_PAD = 8;

/**
 * Rend la frame i. Retour : { width, height, data, origin, owners, joints }.
 * `origin` = position du (0,0) du sprite dans le canvas (canvas constant, marge fixe).
 */
export function renderFrame(project, i, { hiddenParts = [] } = {}) {
  const { sprite, rig, anim, labels, partNames } = project;
  const { width: w, height: h, data: src } = sprite;
  const pad = RENDER_PAD;
  const W = w + 2 * pad, H = h + 2 * pad;
  const out = new Uint8ClampedArray(W * H * 4);
  const owners = new Int16Array(W * H).fill(-1);
  const frame = anim && anim.frames[i] ? anim.frames[i] : null;
  const mats = poseBones(rig, frame);

  // bbox source de chaque pièce (indice n = pixels non assignés)
  const n = partNames.length;
  const bb = Array.from({ length: n + 1 }, () => [w, h, -1, -1]);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (!src[(y * w + x) * 4 + 3]) continue;
    const k = labels[y * w + x];
    const r = bb[k < 0 ? n : k];
    if (x < r[0]) r[0] = x;
    if (y < r[1]) r[1] = y;
    if (x > r[2]) r[2] = x;
    if (y > r[3]) r[3] = y;
  }

  // override de z par frame : la clé est un nom d'OS, il vaut pour toutes les pièces de cet os
  const zOf = (name) => {
    const bone = rig.parts[name].bone;
    return frame && frame.z && frame.z[bone] != null ? frame.z[bone] : rig.parts[name].z || 0;
  };
  const order = partNames
    .map((name, k) => ({ name, k, z: zOf(name) }))
    .filter((p) => !hiddenParts.includes(p.name))
    .sort((a, b) => a.z - b.z || a.k - b.k);
  // Comme dans le cœur : les pixels non assignés ne sont pas rendus.
  const layers = order.map((p) => ({ k: p.k, M: mats[rig.parts[p.name].bone] || I }));

  for (const { k, M } of layers) {
    const r = bb[k < 0 ? n : k];
    if (r[2] < 0) continue;
    const xs = [], ys = [];
    for (const [x, y] of [[r[0], r[1]], [r[2] + 1, r[1]], [r[0], r[3] + 1], [r[2] + 1, r[3] + 1]]) {
      xs.push(M[0] * x + M[2] * y + M[4]);
      ys.push(M[1] * x + M[3] * y + M[5]);
    }
    const dx0 = Math.max(-pad, Math.floor(Math.min(...xs)) - 1), dx1 = Math.min(w + pad - 1, Math.ceil(Math.max(...xs)) + 1);
    const dy0 = Math.max(-pad, Math.floor(Math.min(...ys)) - 1), dy1 = Math.min(h + pad - 1, Math.ceil(Math.max(...ys)) + 1);
    const N = inv(M);
    for (let dy = dy0; dy <= dy1; dy++) for (let dx = dx0; dx <= dx1; dx++) {
      const sx = Math.floor(N[0] * (dx + 0.5) + N[2] * (dy + 0.5) + N[4]);
      const sy = Math.floor(N[1] * (dx + 0.5) + N[3] * (dy + 0.5) + N[5]);
      if (sx < 0 || sy < 0 || sx >= w || sy >= h) continue;
      const si = sy * w + sx;
      if (labels[si] !== k || !src[si * 4 + 3]) continue;
      const di = (dy + pad) * W + dx + pad;
      out[di * 4] = src[si * 4];
      out[di * 4 + 1] = src[si * 4 + 1];
      out[di * 4 + 2] = src[si * 4 + 2];
      out[di * 4 + 3] = 255;
      owners[di] = k;
    }
  }

  // Retouches de la frame : écrites en dernier, par-dessus tout (comme le moteur).
  for (const [x, y, c] of (frame && frame.paint) || []) {
    if (x < -pad || y < -pad || x >= w + pad || y >= h + pad) continue;
    const di = (y + pad) * W + x + pad, v = c ? parseInt(c.slice(1), 16) : 0;
    out.set(c ? [(v >> 16) & 255, (v >> 8) & 255, v & 255, 255] : [0, 0, 0, 0], di * 4);
  }

  const joints = {};
  for (const [b, bone] of Object.entries(rig.bones)) {
    const M = mats[b] || I;
    const x = bone.joint[0] + 0.5, y = bone.joint[1] + 0.5;
    joints[b] = [Math.floor(M[0] * x + M[2] * y + M[4]), Math.floor(M[1] * x + M[3] * y + M[5])];
  }
  // Pivot : relatif à la bbox opaque du sprite AU REPOS, en coin de grille, exprimé en pixels canvas.
  const box = opaqueBBox(sprite);
  const [fx, fy] = rig.pivot || [0.5, 1];
  const pivot = [box.x + Math.round(box.w * fx) + pad, box.y + Math.round(box.h * fy) + pad];
  return { width: W, height: H, data: out, origin: [pad, pad], pivot, owners, joints };
}

// --- QA (PARTIELLE, simulée) ---------------------------------------------------

/** Rapport au format report.json. pass = null signifie « non vérifié en démo ». */
export function validate(project) {
  const { sprite, anim, labels } = project;
  const { width: w, height: h, data } = sprite;
  const checks = [];
  const add = (id, pass, detail = '', frame = null, pixels = null) =>
    checks.push({ id, pass, detail, frame, pixel: pixels && pixels.length ? pixels[0] : null, ...(pixels ? { pixels } : {}) });

  const unassigned = [];
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (data[(y * w + x) * 4 + 3] && labels[y * w + x] < 0) unassigned.push([x, y]);
  }
  add('parts_assigned', unassigned.length === 0,
    unassigned.length ? `${unassigned.length} pixel${unassigned.length > 1 ? 's' : ''} non assigné${unassigned.length > 1 ? 's' : ''}` : '',
    null, unassigned.length ? unassigned.slice(0, 2000) : null);

  const palette = new Set();
  for (let i = 0; i < data.length; i += 4) if (data[i + 3]) palette.add((data[i] << 16) | (data[i + 1] << 8) | data[i + 2]);

  const n = anim ? anim.frames.length : 0;
  let paletteOk = true, alphaOk = true, holeFrames = 0;
  for (let f = 0; f < n; f++) {
    const fr = renderFrame(project, f);
    const { width: W, height: H, data: d, origin } = fr;
    const holes = [];
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      const i = (y * W + x) * 4;
      const a = d[i + 3];
      if (a !== 0 && a !== 255) alphaOk = false;
      if (a) {
        if (!palette.has((d[i] << 16) | (d[i + 1] << 8) | d[i + 2])) paletteOk = false;
      } else if (x > 0 && y > 0 && x < W - 1 && y < H - 1 &&
        d[i - 4 + 3] && d[i + 4 + 3] && d[i - W * 4 + 3] && d[i + W * 4 + 3]) {
        holes.push([x - origin[0], y - origin[1]]);
      }
    }
    if (holes.length) {
      holeFrames++;
      add('holes', false, `${holes.length} pixel${holes.length > 1 ? 's' : ''} vide${holes.length > 1 ? 's' : ''} enfermé${holes.length > 1 ? 's' : ''}`, f, holes);
    }
  }
  if (!holeFrames) add('holes', n ? true : null, n ? '' : 'aucune animation');
  add('palette', n ? paletteOk : null, n ? '' : 'aucune animation');
  add('alpha_binary', n ? alphaOk : null, n ? '' : 'aucune animation');
  add('canvas_constant', n ? true : null, n ? '' : 'aucune animation');
  add('pivot_stable', n ? true : null, n ? '' : 'aucune animation');
  add('orphans', null, 'non vérifié en démo');
  add('loop_closed', null, 'non vérifié en démo');
  return { ok: checks.every((c) => c.pass !== false), checks };
}

/** Chemins modifiés entre deux documents JSON (pour le résumé d'un conflit). */
export function diffPaths(a, b, prefix = '', depth = 0, out = []) {
  if (JSON.stringify(a) === JSON.stringify(b)) return out;
  const isObj = (v) => v && typeof v === 'object' && !Array.isArray(v);
  if (depth < 3 && isObj(a) && isObj(b)) {
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
      diffPaths(a[k], b[k], prefix ? prefix + '.' + k : k, depth + 1, out);
    }
  } else out.push(prefix);
  return out;
}
