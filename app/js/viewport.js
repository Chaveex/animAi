// Viewport : rendu canvas net (zoom ENTIER en pixels physiques, lissage désactivé),
// pan / zoom, calques d'affichage et outils d'édition à la souris et au clavier.

import { state, on, emit, exec, paintCmd, setSelection, targetPart, isAnimStep, frameCount, layerActive, toast, undo, beginGesture, endGesture } from './store.js';
import { getFrame, silhouette } from './preview.js';
import { labelStyle, labelPixel } from './label-palette.js';
import { moveJoint, editBoneKey, boneKey, hint } from './edits.js';

export const ZOOMS = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32, 48, 64];
const ONION_PREV = '#0072B2'; // bleu  : frame précédente
const ONION_NEXT = '#E69F00'; // orange : frame suivante

let canvas, ctx;
let zoom = 1; // pixels PHYSIQUES d'écran par pixel du sprite — toujours un entier
let panX = 0, panY = 0; // position physique du pixel (0,0) du sprite dans le canvas
let fitted = false;
let sized = false; // le tampon du canvas a reçu sa vraie taille
let autoFit = true; // tant que l'utilisateur n'a ni zoomé ni déplacé la vue, on recadre pour lui
let lastSceneKey = '';
let raf = 0;
let spriteCanvas = null, restCanvas = null, restLayers = null, bgCanvas = null;
let kbd = null; // curseur pixel clavier
let drag = null;
let spaceHeld = false, spacePanned = false;
let wheelAcc = 0;

export const getZoom = () => zoom;
/** Lecture seule, pour les tests automatisés : zoom et décalage en pixels physiques. */
export const getView = () => ({ zoom, panX, panY });
const unit = () => Math.max(1, Math.round(window.devicePixelRatio || 1));
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function makeCanvas(w, h) {
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  return c;
}

// --- Images dérivées -------------------------------------------------------------

/** Canvas label map + canvas « non assigné » + ancres des badges, depuis une carte de propriétaires. */
function buildLabelLayers(w, h, ownerAt, opaqueAt) {
  const lab = new ImageData(w, h), un = new ImageData(w, h), unList = [];
  const styles = state.partNames.map((_, k) => labelStyle(k));
  const hidden = state.partNames.map((n) => state.hiddenParts.has(n));
  const sum = state.partNames.map(() => [0, 0, 0]);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    if (!opaqueAt(i)) continue;
    const k = ownerAt(i);
    if (k < 0) {
      const v = (x + y) % 2 ? 255 : 0;
      un.data.set([v, v, v, 255], i * 4);
      unList.push(i);
    } else if (!hidden[k] && styles[k]) {
      lab.data.set([...labelPixel(styles[k], x, y), 255], i * 4);
      sum[k][0] += x;
      sum[k][1] += y;
      sum[k][2]++;
    }
  }
  // ancre = pixel de la pièce le plus proche de son barycentre
  const best = sum.map(() => [Infinity, null]);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    if (!opaqueAt(i)) continue;
    const k = ownerAt(i);
    if (k < 0 || hidden[k] || !sum[k] || !sum[k][2]) continue;
    const d = (x - sum[k][0] / sum[k][2]) ** 2 + (y - sum[k][1] / sum[k][2]) ** 2;
    if (d < best[k][0]) best[k] = [d, [x, y]];
  }
  const a = makeCanvas(w, h), b = makeCanvas(w, h);
  a.getContext('2d').putImageData(lab, 0, 0);
  b.getContext('2d').putImageData(un, 0, 0);
  return { label: a, unassigned: b, unList, width: w, anchors: best.map((v) => v[1]) };
}

function rebuildSprite() {
  const s = state.sprite;
  if (!s) return (spriteCanvas = restCanvas = restLayers = null);
  spriteCanvas = makeCanvas(s.width, s.height);
  spriteCanvas.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(s.data), s.width, s.height), 0, 0);
  rebuildLabels();
}

function rebuildLabels() {
  const s = state.sprite;
  if (!s || !state.labels) return;
  restLayers = buildLabelLayers(s.width, s.height, (i) => state.labels[i], (i) => s.data[i * 4 + 3] !== 0);
  // pose de repos : le sprite, moins les pixels des pièces masquées
  if (!state.hiddenParts.size) restCanvas = spriteCanvas;
  else {
    const d = new Uint8ClampedArray(s.data);
    for (let i = 0; i < state.labels.length; i++) {
      const k = state.labels[i];
      if (k >= 0 && state.hiddenParts.has(state.partNames[k])) d[i * 4 + 3] = 0;
    }
    restCanvas = makeCanvas(s.width, s.height);
    restCanvas.getContext('2d').putImageData(new ImageData(d, s.width, s.height), 0, 0);
  }
}

function frameLabelLayers(entry) {
  if (!entry.owners) return null;
  if (!entry.labelLayers) {
    entry.labelLayers = buildLabelLayers(entry.width, entry.height, (i) => entry.owners[i], (i) => entry.data[i * 4 + 3] !== 0);
  }
  return entry.labelLayers;
}

function background(w, h) {
  const key = `${w}x${h}:${state.background}`;
  if (bgCanvas && bgCanvas.key === key) return bgCanvas;
  bgCanvas = makeCanvas(w, h);
  bgCanvas.key = key;
  const c = bgCanvas.getContext('2d');
  const flat = { grey: '#808080', black: '#000000', white: '#ffffff' }[state.background];
  if (flat) {
    c.fillStyle = flat;
    c.fillRect(0, 0, w, h);
  } else {
    const a = css('--vp-checker-a') || '#7f7f7f', b = css('--vp-checker-b') || '#8f8f8f';
    for (let y = 0; y < h; y += 4) for (let x = 0; x < w; x += 4) {
      c.fillStyle = ((x + y) / 4) % 2 ? b : a;
      c.fillRect(x, y, 4, 4);
    }
  }
  return bgCanvas;
}

// --- Géométrie -------------------------------------------------------------------

/** Ce qui est affiché : la frame rendue (étapes Animer / Exporter) ou la pose de repos. */
function scene() {
  const s = state.sprite;
  const entry = isAnimStep() && frameCount() ? getFrame(state.frame) : null;
  return entry
    ? { entry, ox: entry.origin[0], oy: entry.origin[1], aw: entry.width, ah: entry.height }
    : { entry: null, ox: 0, oy: 0, aw: s.width, ah: s.height };
}

const sx = (x) => panX + x * zoom;
const sy = (y) => panY + y * zoom;

function eventPos(e) {
  const r = canvas.getBoundingClientRect();
  const px = ((e.clientX - r.left) * canvas.width) / r.width;
  const py = ((e.clientY - r.top) * canvas.height) / r.height;
  return { px, py, x: Math.floor((px - panX) / zoom), y: Math.floor((py - panY) / zoom) };
}

function jointPos(bone) {
  const sc = scene();
  if (sc.entry && sc.entry.joints && sc.entry.joints[bone]) return sc.entry.joints[bone];
  return state.rig.bones[bone].joint;
}

function jointAt(pos) {
  if (!layerActive('skeleton') && !layerActive('pivots') && state.tool !== 'joint') return null;
  let best = null, bestD = (10 * unit()) ** 2;
  for (const b of Object.keys(state.rig.bones)) {
    if (state.hiddenBones.has(b)) continue;
    const [jx, jy] = jointPos(b);
    const d = (sx(jx + 0.5) - pos.px) ** 2 + (sy(jy + 0.5) - pos.py) ** 2;
    if (d <= bestD) {
      bestD = d;
      best = b;
    }
  }
  return best;
}

function pixelInfo(x, y) {
  const s = state.sprite, sc = scene();
  if (sc.entry) {
    const ex = x + sc.ox, ey = y + sc.oy;
    if (ex < 0 || ey < 0 || ex >= sc.aw || ey >= sc.ah) return { x, y, inside: false };
    const i = ey * sc.aw + ex, d = sc.entry.data;
    const k = sc.entry.owners ? sc.entry.owners[i] : -2;
    return { x, y, inside: true, alpha: d[i * 4 + 3], color: [d[i * 4], d[i * 4 + 1], d[i * 4 + 2]], partIndex: k };
  }
  if (x < 0 || y < 0 || x >= s.width || y >= s.height) return { x, y, inside: false };
  const i = y * s.width + x, d = s.data;
  return { x, y, inside: true, alpha: d[i * 4 + 3], color: [d[i * 4], d[i * 4 + 1], d[i * 4 + 2]], partIndex: state.labels[i] };
}

function setHover(x, y) {
  state.hover = x == null ? null : pixelInfo(x, y);
  emit('hover');
}

// --- Zoom / pan --------------------------------------------------------------------

export function fit() {
  if (!state.sprite || !sized) return; // pas encore mesuré : le premier redimensionnement ajustera
  const sc = scene();
  const m = 24 * unit();
  let z = 1;
  for (const v of ZOOMS) if (sc.aw * v <= canvas.width - m && sc.ah * v <= canvas.height - m) z = v;
  zoom = z;
  panX = Math.round((canvas.width - sc.aw * z) / 2) + sc.ox * z;
  panY = Math.round((canvas.height - sc.ah * z) / 2) + sc.oy * z;
  fitted = true;
  autoFit = true;
  lastSceneKey = `${sc.aw}x${sc.ah}`;
  emit('zoom');
  requestDraw();
}

/** La zone affichée a changé de taille (pose de repos <-> canvas d'export) : recadrer si la vue est intacte. */
function refitIfSceneChanged() {
  if (state.status !== 'ready' || !sized || !state.sprite) return;
  const sc = scene(), key = `${sc.aw}x${sc.ah}`;
  if (key === lastSceneKey) return;
  lastSceneKey = key;
  if (autoFit) fit();
}

export function setZoom(z, cx = canvas.width / 2, cy = canvas.height / 2) {
  if (!ZOOMS.includes(z) || z === zoom) return;
  panX = Math.round(cx - ((cx - panX) / zoom) * z);
  panY = Math.round(cy - ((cy - panY) / zoom) * z);
  zoom = z;
  autoFit = false;
  emit('zoom');
  requestDraw();
}

export function zoomBy(dir, cx, cy) {
  const i = ZOOMS.indexOf(zoom) + dir;
  if (i >= 0 && i < ZOOMS.length) setZoom(ZOOMS[i], cx, cy);
}

export function panBy(dx, dy) {
  autoFit = false;
  panX += Math.round(dx);
  panY += Math.round(dy);
  requestDraw();
}

/** Centre le viewport sur un groupe de pixels (QA) en garantissant un zoom lisible. */
export function focusOn(pixels) {
  if (!pixels || !pixels.length) return;
  const xs = pixels.map((p) => p[0]), ys = pixels.map((p) => p[1]);
  const cx = (Math.min(...xs) + Math.max(...xs) + 1) / 2, cy = (Math.min(...ys) + Math.max(...ys) + 1) / 2;
  if (zoom < 8) zoom = 8;
  autoFit = false;
  panX = Math.round(canvas.width / 2 - cx * zoom);
  panY = Math.round(canvas.height / 2 - cy * zoom);
  emit('zoom');
  requestDraw();
}

function ensureVisible(x, y) {
  const m = 16 * unit();
  if (sx(x) < m) panX += m - sx(x);
  if (sx(x + 1) > canvas.width - m) panX -= sx(x + 1) - (canvas.width - m);
  if (sy(y) < m) panY += m - sy(y);
  if (sy(y + 1) > canvas.height - m) panY -= sy(y + 1) - (canvas.height - m);
}

// --- Clavier -----------------------------------------------------------------------

export function moveCursor(dx, dy) {
  if (state.status !== 'ready') return;
  const s = state.sprite;
  if (!kbd) kbd = state.hover && state.hover.inside ? { x: state.hover.x, y: state.hover.y } : { x: s.width >> 1, y: s.height >> 1 };
  else kbd = { x: Math.max(0, Math.min(s.width - 1, kbd.x + dx)), y: Math.max(0, Math.min(s.height - 1, kbd.y + dy)) };
  ensureVisible(kbd.x, kbd.y);
  setHover(kbd.x, kbd.y);
  const hv = state.hover;
  const part = hv.partIndex >= 0 ? `pièce ${hv.partIndex + 1} ${state.partNames[hv.partIndex]}` : hv.alpha ? 'non assigné' : 'transparent';
  emit('announce', `x ${kbd.x}, y ${kbd.y}, ${part}`);
  requestDraw();
}

/** Applique l'outil courant au curseur clavier (touche Entrée). */
export function applyAtCursor() {
  if (!kbd || state.status !== 'ready') return false;
  const pos = { x: kbd.x, y: kbd.y, px: sx(kbd.x + 0.5), py: sy(kbd.y + 0.5) };
  if (state.tool === 'brush' || state.tool === 'eraser') {
    if (!beginStroke(pos)) return true;
    endStroke();
  } else pick(pos);
  return true;
}

export function clearCursor() {
  kbd = null;
  requestDraw();
}

export function setSpace(down) {
  if (down) {
    if (!spaceHeld) spacePanned = false;
    spaceHeld = true;
  } else spaceHeld = false;
  updateCursorStyle();
  return spacePanned;
}

// --- Outils ------------------------------------------------------------------------

function pick(pos) {
  const b = jointAt(pos);
  if (b) return setSelection({ kind: 'bone', id: b });
  const info = pixelInfo(pos.x, pos.y);
  if (info.inside && info.partIndex >= 0) setSelection({ kind: 'part', id: state.partNames[info.partIndex] });
  else setSelection(null);
}

function dab(x, y) {
  const s = state.sprite, n = state.brushSize, off = Math.floor((n - 1) / 2);
  for (let yy = y - off; yy < y - off + n; yy++) for (let xx = x - off; xx < x - off + n; xx++) {
    if (xx < 0 || yy < 0 || xx >= s.width || yy >= s.height) continue;
    const i = yy * s.width + xx;
    if (!s.data[i * 4 + 3] || state.labels[i] === drag.value) continue;
    if (!drag.changed.has(i)) drag.changed.set(i, state.labels[i]);
    state.labels[i] = drag.value;
  }
}

function strokeTo(x, y) {
  let { x: x0, y: y0 } = drag.last;
  const dx = Math.abs(x - x0), dy = -Math.abs(y - y0), stepX = x0 < x ? 1 : -1, stepY = y0 < y ? 1 : -1;
  let err = dx + dy;
  for (;;) {
    dab(x0, y0);
    if (x0 === x && y0 === y) break;
    const e2 = 2 * err;
    if (e2 >= dy) { err += dy; x0 += stepX; }
    if (e2 <= dx) { err += dx; y0 += stepY; }
  }
  drag.last = { x, y };
  rebuildLabels();
  requestDraw();
}

function beginStroke(pos) {
  if (state.step !== 'rig') {
    hint('Le pinceau et la gomme s\'utilisent à l\'étape Rigger (touche 2).');
    return false;
  }
  let value = -1;
  if (state.tool === 'brush') {
    const part = targetPart();
    if (!part) {
      hint('Choisissez d\'abord la pièce à peindre : dans la hiérarchie, ou Alt+clic sur un pixel déjà assigné.');
      return false;
    }
    value = state.partNames.indexOf(part);
  }
  drag = { type: 'paint', value, changed: new Map(), last: { x: pos.x, y: pos.y } };
  strokeTo(pos.x, pos.y);
  return true;
}

function endStroke() {
  const d = drag;
  drag = null;
  if (!d || !d.changed.size) return;
  const idx = Int32Array.from(d.changed.keys());
  const before = Int16Array.from(d.changed.values());
  const after = new Int16Array(idx.length).fill(d.value);
  const n = idx.length, pl = n > 1 ? 's' : '';
  const label = d.value < 0 ? `Gomme : ${n} pixel${pl} désassigné${pl}` : `Pinceau : ${n} pixel${pl} → « ${state.partNames[d.value]} »`;
  const cmd = paintCmd(idx, before, after, label);
  exec(cmd);
  if (cmd.convertsRegions.length) {
    const n = cmd.convertsRegions.length;
    toast(`Les régions écrites à la main (polygones, exclusions) de ${n} pièce${n > 1 ? 's' : ''} viennent d'être converties en rectangles + pixels. Le découpage est identique au pixel près ; Annuler rétablit le texte d'origine de rig.json.`,
      { kind: 'warn', action: { label: 'Annuler', run: undo } });
  }
}

/**
 * Pivot d'export en coordonnées sprite (coin de grille), ou null s'il n'est pas connu.
 * Il vient du moteur (champ `pivot` de la frame, en pixels canvas) : il est ancré sur la bbox du
 * sprite au repos, donc identique pour toutes les frames. L'UI ne le recalcule pas.
 */
function exportPivot(sc) {
  let e = sc.entry;
  for (let i = 0; !e && i < frameCount(); i++) e = getFrame(i);
  return e && e.pivot ? [e.pivot[0] - e.origin[0], e.pivot[1] - e.origin[1]] : null;
}

function onDown(e) {
  canvas.focus({ preventScroll: true });
  if (e.button === 1 || (e.button === 0 && spaceHeld)) {
    drag = { type: 'pan', cx: e.clientX, cy: e.clientY, panX, panY };
    canvas.setPointerCapture(e.pointerId);
    e.preventDefault();
    return;
  }
  if (e.button !== 0 || state.status !== 'ready') return;
  kbd = null;
  const pos = eventPos(e);
  const tool = state.tool;
  if (tool === 'select') pick(pos);
  else if (tool === 'joint') {
    const b = jointAt(pos);
    if (!b) return hint('Cliquez sur un joint (rond) pour le saisir, ou utilisez les flèches sur l\'os sélectionné.');
    setSelection({ kind: 'bone', id: b });
    if (isAnimStep()) {
      if (!frameCount()) return;
      drag = { type: 'key', bone: b, from: pos, cur: pos, base: boneKey(b).pos };
    } else drag = { type: 'joint', bone: b, start: [...state.rig.bones[b].joint], cur: [...state.rig.bones[b].joint] };
    beginGesture();
    canvas.setPointerCapture(e.pointerId);
  } else {
    if (e.altKey) {
      const info = pixelInfo(pos.x, pos.y);
      if (info.inside && info.partIndex >= 0) setSelection({ kind: 'part', id: state.partNames[info.partIndex] });
      return;
    }
    if (beginStroke(pos)) {
      beginGesture();
      canvas.setPointerCapture(e.pointerId);
    }
  }
}

function onMove(e) {
  const pos = eventPos(e);
  if (drag && drag.type === 'pan') {
    const r = canvas.getBoundingClientRect(), k = canvas.width / r.width;
    panX = drag.panX + Math.round((e.clientX - drag.cx) * k);
    panY = drag.panY + Math.round((e.clientY - drag.cy) * k);
    if (spaceHeld) spacePanned = true;
    autoFit = false;
    return requestDraw();
  }
  if (state.status !== 'ready') return;
  if (kbd) kbd = null;
  setHover(pos.x, pos.y);
  if (drag && drag.type === 'paint') strokeTo(pos.x, pos.y);
  else if (drag && drag.type === 'joint') {
    const s = state.sprite;
    const to = [Math.max(0, Math.min(s.width - 1, pos.x)), Math.max(0, Math.min(s.height - 1, pos.y))];
    if (to[0] !== drag.cur[0] || to[1] !== drag.cur[1]) {
      drag.cur = to;
      state.rig.bones[drag.bone].joint = to; // aperçu en direct ; validé (et annulable) au relâchement
      emit('rig');
    }
  } else if (drag && drag.type === 'key') drag.cur = pos;
  requestDraw();
}

function onUp(e) {
  const d = drag;
  if (!d) return;
  if (canvas.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
  if (d.type === 'paint') {
    endStroke();
    return endGesture();
  }
  drag = null;
  if (d.type === 'pan') {
    updateCursorStyle();
    return requestDraw();
  }
  if (d.type === 'joint') {
    state.rig.bones[d.bone].joint = d.start;
    if (e.type === 'pointercancel') emit('rig');
    else moveJoint(d.bone, d.cur);
  } else if (d.type === 'key' && e.type !== 'pointercancel') {
    const dx = d.cur.x - d.from.x, dy = d.cur.y - d.from.y;
    if (dx || dy) editBoneKey(d.bone, { pos: [d.base[0] + dx, d.base[1] + dy] });
  }
  endGesture();
  updateCursorStyle();
  requestDraw();
}

/** Échap pendant un glisser : abandonne sans rien modifier. Renvoie true si quelque chose a été annulé. */
export function cancelDrag() {
  if (!drag) return false;
  const d = drag;
  drag = null;
  if (d.type === 'paint') {
    for (const [i, v] of d.changed) state.labels[i] = v;
    rebuildLabels();
  } else if (d.type === 'joint') {
    state.rig.bones[d.bone].joint = d.start;
    emit('rig');
  }
  if (d.type !== 'pan') endGesture();
  requestDraw();
  return true;
}

function onWheel(e) {
  e.preventDefault();
  wheelAcc += e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
  if (Math.abs(wheelAcc) < 50) return;
  const pos = eventPos(e);
  zoomBy(wheelAcc < 0 ? 1 : -1, pos.px, pos.py);
  wheelAcc = 0;
}

function updateCursorStyle() {
  if (!canvas) return;
  canvas.style.cursor = spaceHeld ? (drag && drag.type === 'pan' ? 'grabbing' : 'grab')
    : { select: 'default', brush: 'crosshair', eraser: 'crosshair', joint: 'move' }[state.tool];
}

// --- Dessin ------------------------------------------------------------------------

export function requestDraw() {
  if (!raf) raf = requestAnimationFrame(draw);
}

function line(x0, y0, x1, y1, color, width) {
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.stroke();
}

function pixelBox(x, y, w, h, u) {
  ctx.lineWidth = u;
  ctx.strokeStyle = '#000';
  ctx.strokeRect(sx(x) - u * 1.5, sy(y) - u * 1.5, w * zoom + 3 * u, h * zoom + 3 * u);
  ctx.strokeStyle = '#fff';
  ctx.strokeRect(sx(x) - u * 0.5, sy(y) - u * 0.5, w * zoom + u, h * zoom + u);
}

function draw() {
  raf = 0;
  if (!ctx) return;
  const cw = canvas.width, ch = canvas.height, u = unit();
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.imageSmoothingEnabled = false; // jamais de lissage : chaque pixel du sprite = un carré net
  ctx.globalAlpha = 1;
  ctx.fillStyle = css('--vp-surround') || '#2b2b2b';
  ctx.fillRect(0, 0, cw, ch);
  if (state.status !== 'ready' || !state.sprite || !spriteCanvas) return;

  const s = state.sprite, sc = scene();
  const L = { skeleton: layerActive('skeleton'), labelmap: layerActive('labelmap'), pivots: layerActive('pivots'), grid: layerActive('grid'), onion: layerActive('onion') };
  const ax = sx(-sc.ox), ay = sy(-sc.oy), aw = sc.aw * zoom, ah = sc.ah * zoom;
  ctx.drawImage(background(sc.aw, sc.ah), ax, ay, aw, ah);

  // 1. image : frame rendue par le moteur, ou pose de repos
  let layers = null;
  if (sc.entry) {
    if (L.onion && frameCount() > 1) {
      const n = frameCount();
      const prev = getFrame((state.frame - 1 + n) % n), next = getFrame((state.frame + 1) % n);
      ctx.globalAlpha = 0.4;
      if (prev) ctx.drawImage(silhouette(prev, ONION_PREV), ax, ay, aw, ah);
      if (next) ctx.drawImage(silhouette(next, ONION_NEXT), ax, ay, aw, ah);
      ctx.globalAlpha = 1;
    }
    ctx.drawImage(sc.entry.canvas, ax, ay, aw, ah);
    layers = frameLabelLayers(sc.entry);
  } else {
    ctx.drawImage(restCanvas, panX, panY, s.width * zoom, s.height * zoom);
    layers = restLayers;
  }

  // 2. label map (couleur + motif), pixels non assignés en damier noir/blanc
  if (L.labelmap && layers) {
    ctx.globalAlpha = state.labelOpacity;
    ctx.drawImage(layers.label, ax, ay, aw, ah);
    ctx.globalAlpha = 1;
    // Non assigné : un point blanc cerné de noir au centre du pixel. Visible sur toute couleur,
    // sans masquer le sprite (indispensable quand rien n'est encore assigné).
    if (zoom < 5) {
      ctx.globalAlpha = 0.5;
      ctx.drawImage(layers.unassigned, ax, ay, aw, ah);
      ctx.globalAlpha = 1;
    } else {
      const d = Math.max(2 * u, Math.round(zoom / 4)), o = Math.floor((zoom - d) / 2);
      for (const i of layers.unList) {
        const x = ax + (i % layers.width) * zoom + o, y = ay + Math.floor(i / layers.width) * zoom + o;
        if (x < -zoom || y < -zoom || x > cw || y > ch) continue;
        ctx.fillStyle = '#000';
        ctx.fillRect(x - u, y - u, d + 2 * u, d + 2 * u);
        ctx.fillStyle = '#fff';
        ctx.fillRect(x, y, d, d);
      }
    }
  }

  // 3. grille de pixels
  if (L.grid && zoom >= 4) {
    const x0 = Math.max(0, Math.ceil(-ax / zoom)), x1 = Math.min(sc.aw, Math.floor((cw - ax) / zoom));
    const y0 = Math.max(0, Math.ceil(-ay / zoom)), y1 = Math.min(sc.ah, Math.floor((ch - ay) / zoom));
    const top = Math.max(0, ay), bottom = Math.min(ch, ay + ah), left = Math.max(0, ax), right = Math.min(cw, ax + aw);
    for (let x = x0; x <= x1; x++) {
      const major = (x - sc.ox) % 8 === 0;
      ctx.fillStyle = major ? 'rgba(0,0,0,0.6)' : 'rgba(0,0,0,0.3)';
      ctx.fillRect(ax + x * zoom, top, 1, bottom - top);
      if (zoom >= 8) {
        ctx.fillStyle = major ? 'rgba(255,255,255,0.4)' : 'rgba(255,255,255,0.16)';
        ctx.fillRect(ax + x * zoom + 1, top, 1, bottom - top);
      }
    }
    for (let y = y0; y <= y1; y++) {
      const major = (y - sc.oy) % 8 === 0;
      ctx.fillStyle = major ? 'rgba(0,0,0,0.6)' : 'rgba(0,0,0,0.3)';
      ctx.fillRect(left, ay + y * zoom, right - left, 1);
      if (zoom >= 8) {
        ctx.fillStyle = major ? 'rgba(255,255,255,0.4)' : 'rgba(255,255,255,0.16)';
        ctx.fillRect(left, ay + y * zoom + 1, right - left, 1);
      }
    }
  }

  // 4. squelette (liens parent -> enfant)
  const accent = css('--accent') || '#78aaff';
  const sel = state.selection && state.selection.kind === 'bone' ? state.selection.id : null;
  const bones = Object.keys(state.rig.bones).filter((b) => !state.hiddenBones.has(b));
  ctx.lineCap = 'round';
  if (L.skeleton) {
    for (const b of bones) {
      const parent = state.rig.bones[b].parent;
      if (!parent || !state.rig.bones[parent] || state.hiddenBones.has(parent)) continue;
      const [x0, y0] = jointPos(parent), [x1, y1] = jointPos(b);
      const p = [sx(x0 + 0.5), sy(y0 + 0.5), sx(x1 + 0.5), sy(y1 + 0.5)];
      line(...p, '#000', 4 * u);
      line(...p, b === sel || parent === sel ? accent : '#fff', 2 * u);
    }
  }

  // 5. pivots : joints (rond ; carré pour la racine) et pivot d'export (croix)
  if (L.pivots || (state.tool === 'joint' && state.step !== 'prepare')) {
    for (const b of bones) {
      const [jx, jy] = jointPos(b);
      const x = sx(jx + 0.5), y = sy(jy + 0.5), r = (b === sel ? 6 : 4) * u;
      ctx.fillStyle = b === sel ? accent : '#fff';
      ctx.strokeStyle = '#000';
      ctx.lineWidth = 2 * u;
      ctx.beginPath();
      if (state.rig.bones[b].parent) ctx.arc(x, y, r, 0, Math.PI * 2);
      else ctx.rect(x - r, y - r, 2 * r, 2 * r);
      ctx.fill();
      ctx.stroke();
    }
    const pv = exportPivot(sc);
    if (pv) {
      const px = sx(pv[0]), py = sy(pv[1]), k = 7 * u;
      line(px - k, py, px + k, py, '#000', 4 * u);
      line(px, py - k, px, py + k, '#000', 4 * u);
      line(px - k, py, px + k, py, '#fff', 2 * u);
      line(px, py - k, px, py + k, '#fff', 2 * u);
    }
  }

  // 6. numéros des pièces (lisibles sans la couleur)
  ctx.font = `bold ${11 * u}px ${css('--font-mono') || 'monospace'}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  if (L.labelmap && layers && zoom >= 6) {
    layers.anchors.forEach((a, k) => {
      if (!a) return;
      const st = labelStyle(k), text = String(st.number);
      const w = ctx.measureText(text).width + 6 * u, hh = 14 * u;
      const x = Math.round(ax + (a[0] + 0.5) * zoom - w / 2), y = Math.round(ay + (a[1] + 0.5) * zoom - hh / 2);
      ctx.fillStyle = st.hex;
      ctx.fillRect(x - u, y - u, w + 2 * u, hh + 2 * u);
      ctx.fillStyle = '#000';
      ctx.fillRect(x, y, w, hh);
      ctx.fillStyle = '#fff';
      ctx.fillText(text, x + w / 2, y + hh / 2 + u * 0.5);
    });
  }

  // 7. nom de l'os sélectionné
  if (sel && state.rig.bones[sel] && (L.pivots || L.skeleton || state.tool === 'joint')) {
    // Étiquette HORS de l'image (à droite de la zone, sinon à gauche), reliée au joint par un
    // filet : sur un sprite étroit, une étiquette posée à côté du joint cachait le membre voisin.
    const [jx, jy] = jointPos(sel);
    const text = sel, w = ctx.measureText(text).width + 8 * u;
    const jsx = sx(jx + 0.5), jsy = sy(jy + 0.5);
    let x = Math.round(ax + aw + 8 * u);
    if (x + w > cw - 4 * u) x = Math.round(ax - 8 * u - w);
    if (x < 4 * u) x = Math.round(cw - w - 4 * u); // image plus large que la fenêtre : bord droit
    const y = Math.round(Math.max(4 * u, Math.min(ch - 20 * u, jsy - 8 * u)));
    const lx = x > jsx ? x : x + w;
    line(jsx, jsy, lx, y + 8 * u, '#000', 3 * u);
    line(jsx, jsy, lx, y + 8 * u, '#fff', u);
    ctx.fillStyle = '#000';
    ctx.fillRect(x, y, w, 16 * u);
    ctx.fillStyle = '#fff';
    ctx.fillText(text, x + w / 2, y + 8 * u + u * 0.5);
  }

  // 8. problème QA localisé
  const q = state.qaFocus;
  if (q && q.pixels.length && (q.frame == null || (q.rest ? !sc.entry : sc.entry && q.frame === state.frame))) {
    const px = q.pixels.slice(0, 400);
    for (const [x, y] of px) pixelBox(x, y, 1, 1, u);
    const xs = px.map((p) => p[0]), ys = px.map((p) => p[1]);
    const cx = sx((Math.min(...xs) + Math.max(...xs) + 1) / 2), cy = sy((Math.min(...ys) + Math.max(...ys) + 1) / 2);
    const r = Math.hypot(Math.max(...xs) - Math.min(...xs) + 1, Math.max(...ys) - Math.min(...ys) + 1) * zoom / 2 + 12 * u;
    for (const [color, width] of [['#000', 5 * u], ['#fff', 2 * u]]) {
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.stroke();
    }
  }

  // 9. curseurs : pinceau au survol, curseur pixel clavier, fantôme de déplacement
  const hv = state.hover;
  if (kbd) pixelBox(kbd.x, kbd.y, 1, 1, u);
  else if (hv && hv.inside && (state.tool === 'brush' || state.tool === 'eraser') && state.step === 'rig') {
    const n = state.brushSize, off = Math.floor((n - 1) / 2);
    pixelBox(hv.x - off, hv.y - off, n, n, u);
  }
  if (drag && drag.type === 'key') {
    const [jx, jy] = jointPos(drag.bone);
    const x = sx(jx + 0.5 + drag.cur.x - drag.from.x), y = sy(jy + 0.5 + drag.cur.y - drag.from.y);
    ctx.strokeStyle = '#000';
    ctx.lineWidth = 4 * u;
    ctx.beginPath();
    ctx.arc(x, y, 6 * u, 0, Math.PI * 2);
    ctx.stroke();
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2 * u;
    ctx.stroke();
  }
}

// --- Initialisation ----------------------------------------------------------------

export function initViewport(el) {
  canvas = el;
  ctx = canvas.getContext('2d');

  const resize = (w, h) => {
    w = Math.max(1, Math.round(w));
    h = Math.max(1, Math.round(h));
    if (canvas.width === w && canvas.height === h) return;
    const dx = (w - canvas.width) / 2, dy = (h - canvas.height) / 2;
    canvas.width = w; // taille du tampon = pixels PHYSIQUES : aucun rééchantillonnage par le navigateur
    canvas.height = h;
    sized = true;
    if ((!fitted || autoFit) && state.status === 'ready') fit();
    else {
      panX += Math.round(dx); // garde le sprite centré au même endroit
      panY += Math.round(dy);
    }
    if (raf) cancelAnimationFrame(raf);
    draw();
  };
  const ro = new ResizeObserver((entries) => {
    const e = entries[0];
    if (e.devicePixelContentBoxSize) resize(e.devicePixelContentBoxSize[0].inlineSize, e.devicePixelContentBoxSize[0].blockSize);
    else resize(e.contentRect.width * devicePixelRatio, e.contentRect.height * devicePixelRatio);
  });
  try {
    ro.observe(canvas, { box: 'device-pixel-content-box' });
  } catch {
    ro.observe(canvas);
  }

  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerup', onUp);
  canvas.addEventListener('pointercancel', onUp);
  canvas.addEventListener('pointerleave', () => {
    if (!kbd) setHover(null);
    requestDraw();
  });
  canvas.addEventListener('wheel', onWheel, { passive: false });
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('auxclick', (e) => e.preventDefault());

  on('project', () => {
    kbd = null;
    if (drag && drag.type !== 'pan') endGesture();
    drag = null;
    rebuildSprite();
    fitted = false;
    if (state.status === 'ready') fit();
    requestDraw();
  });
  on('labels visibility', () => {
    rebuildLabels();
    requestDraw();
  });
  // panX / panY sont exprimés par rapport au (0,0) du sprite : passer de la pose de repos au
  // canvas d'export (plus grand) ne décale pas le sprite. On ne recadre que si l'utilisateur
  // n'a pas touché à la vue (autoFit).
  on('view', () => {
    refitIfSceneChanged();
    updateCursorStyle();
    requestDraw();
  });
  on('frame preview', refitIfSceneChanged);
  on('rig anim selection frame preview qa theme', requestDraw);
}
