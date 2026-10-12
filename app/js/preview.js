// Cache des frames de l'aperçu d'animation.
// L'UI ne calcule AUCUNE pose : elle affiche les images (et les positions de joints) que la
// couche d'accès aux données lui renvoie. En production ces images sortent du moteur du cœur ;
// en démo elles sortent du rendu simplifié de data/demo-core.js.

import { api } from './data/api.js';
import { state, on, emit, frameCount } from './store.js';

/** @type {Array<null | {canvas, width, height, data, origin, owners, joints, tints: Map}>} */
const cache = [];
let gen = 0;

export const getFrame = (i) => cache[i] || null;

function toEntry(f, index) {
  const canvas = document.createElement('canvas');
  canvas.width = f.width;
  canvas.height = f.height;
  canvas.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(f.data), f.width, f.height), 0, 0);
  // pixels retouchés à la main (indices canvas) : ils n'appartiennent à aucune pièce
  const retouched = new Set();
  const frame = state.anim && state.anim.frames[index];
  for (const [x, y] of (frame && frame.paint) || []) {
    const cx = x + f.origin[0], cy = y + f.origin[1];
    if (cx >= 0 && cy >= 0 && cx < f.width && cy < f.height) retouched.add(cy * f.width + cx);
  }
  return { canvas, width: f.width, height: f.height, data: f.data, origin: f.origin, pivot: f.pivot || null, owners: f.owners || null, joints: f.joints || null, angles: f.angles || null, retouched, tints: new Map() };
}

/**
 * Image de la frame avec des retouches par-dessus (`pixels` : [x, y, '#rrggbb' | null], coordonnées
 * sprite). Sert à montrer un trait tout de suite, avant que le moteur ait re-rendu la frame ; le
 * moteur écrit les retouches en dernier, de la même façon.
 */
export function paintedCanvas(entry, pixels) {
  if (!pixels.length) return entry.canvas;
  const key = JSON.stringify(pixels);
  if (entry.paintKey !== key) {
    const d = new Uint8ClampedArray(entry.data);
    for (const [x, y, c] of pixels) {
      const cx = x + entry.origin[0], cy = y + entry.origin[1];
      if (cx < 0 || cy < 0 || cx >= entry.width || cy >= entry.height) continue;
      const v = c ? parseInt(c.slice(1), 16) : 0;
      d.set(c ? [(v >> 16) & 255, (v >> 8) & 255, v & 255, 255] : [0, 0, 0, 0], (cy * entry.width + cx) * 4);
    }
    const c = document.createElement('canvas');
    c.width = entry.width;
    c.height = entry.height;
    c.getContext('2d').putImageData(new ImageData(d, entry.width, entry.height), 0, 0);
    entry.paintKey = key;
    entry.paintCanvas = c;
  }
  return entry.paintCanvas;
}

/** Silhouette unie de la frame (pour l'onion skin), mise en cache par couleur. */
export function silhouette(entry, color) {
  if (!entry.tints.has(color)) {
    const c = document.createElement('canvas');
    c.width = entry.width;
    c.height = entry.height;
    const ctx = c.getContext('2d');
    ctx.drawImage(entry.canvas, 0, 0);
    ctx.globalCompositeOperation = 'source-in';
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, c.width, c.height);
    entry.tints.set(color, c);
  }
  return entry.tints.get(color);
}

/** Redemande toutes les frames : la frame courante d'abord (retour immédiat), le reste en tâche de fond. */
export async function invalidate() {
  const g = ++gen;
  const n = frameCount();
  cache.length = Math.min(cache.length, n);
  state.render = { done: 0, total: n, error: null };
  emit('preview');
  if (!n || state.status !== 'ready') return;
  const first = Math.min(state.frame, n - 1);
  const order = [first, ...Array.from({ length: n }, (_, i) => i).filter((i) => i !== first)];
  const opts = { hiddenParts: [...state.hiddenParts], rigRev: state.rigRev, animRev: state.animRev };
  for (const i of order) {
    try {
      const f = await api.renderFrame(i, opts);
      if (g !== gen) return;
      cache[i] = toEntry(f, i);
    } catch (e) {
      if (g !== gen) return;
      state.render.error = e.message;
    }
    state.render.done++;
    emit('preview');
  }
}

on('project saved visibility', invalidate);
