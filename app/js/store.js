// État de l'app, historique annuler/rétablir, et synchronisation avec les fichiers projet.
// Seul module (avec preview.js) qui parle à la couche d'accès aux données.

import { api, ConflictError } from './data/api.js';

const clone = (v) => (v == null ? v : JSON.parse(JSON.stringify(v)));

/** Couleur du cadre des pixels non assignés. Choix de l'utilisateur, gardé d'une session à l'autre. */
export const UNASSIGNED_DEFAULT = '#00FF00';
const UNASSIGNED_KEY = 'animai.unassignedColor';
function storedUnassignedColor() {
  try {
    const v = localStorage.getItem(UNASSIGNED_KEY);
    if (/^#[0-9a-f]{6}$/i.test(v || '')) return v.toUpperCase();
  } catch { /* stockage indisponible */ }
  return UNASSIGNED_DEFAULT;
}

// --- Bus d'événements ---------------------------------------------------------
// Sujets : status project rig labels anim selection view frame hover sync report
//          history preview saved visibility toast qa
const subs = new Map();
export function on(topics, fn) {
  for (const t of topics.split(' ')) {
    if (!subs.has(t)) subs.set(t, new Set());
    subs.get(t).add(fn);
  }
}
export function emit(topic, payload) {
  const set = subs.get(topic);
  if (set) for (const fn of [...set]) fn(payload);
}

// --- État ---------------------------------------------------------------------
export const state = {
  status: 'loading', // loading | empty | ready | error
  error: null,
  name: '',
  sprite: null,
  palette: [],
  prepare: { warnings: [] },
  presets: [],
  rig: null,
  rigRev: null,
  anim: null,
  animRev: null,
  partNames: [],
  labels: null, // Int16Array : index de pièce par pixel, -1 = non assigné
  report: null,
  reportError: null,

  step: 'rig', // prepare | rig | animate | export
  tool: 'select', // select | brush | eraser | joint | retouch
  brushSize: 1,
  selection: null, // { kind: 'bone' | 'part', id }
  layers: { skeleton: true, labelmap: false, pivots: true, grid: false, onion: false },
  labelOpacity: 0.6,
  unassignedColor: storedUnassignedColor(), // cadre des pixels non assignés, #RRGGBB
  retouchColor: null, // couleur du pinceau de retouche : toujours une couleur de la palette
  retouchMode: 'paint', // paint | erase (rendre transparent) | restore (retirer la retouche)
  background: 'checker', // checker | grey | black | white
  hiddenParts: new Set(),
  hiddenBones: new Set(),
  frame: 0,
  playing: false,
  hover: null, // { x, y, inside, color, alpha, part }
  qaFocus: null, // { id, frame, pixels }
  sync: { state: 'saved', author: null, at: null, message: '', conflict: null },
  render: { done: 0, total: 0, error: null },
};

export const frameCount = () => (state.anim ? state.anim.frames.length : 0);
export const totalDuration = () => (state.anim ? state.anim.frames.reduce((s, f) => s + f.duration_ms, 0) : 0);
export const partsOfBone = (bone) => state.partNames.filter((p) => state.rig.parts[p] && state.rig.parts[p].bone === bone);
export const isAnimStep = () => state.step === 'animate' || state.step === 'export';

/** Pièce ciblée par le pinceau : la pièce sélectionnée, ou l'unique pièce de l'os sélectionné. */
export function targetPart() {
  const s = state.selection;
  if (!s || !state.rig) return null;
  if (s.kind === 'part') return s.id;
  const parts = partsOfBone(s.id);
  return parts.length === 1 ? parts[0] : null;
}

/** Couleur du pinceau de retouche : le choix de l'utilisateur s'il est dans la palette, sinon la première couleur. */
export function retouchColor() {
  const c = (state.retouchColor || '').toLowerCase();
  const pal = state.palette.map((p) => p.toLowerCase());
  return pal.includes(c) ? c : pal[0] || null;
}

export function unassignedCount() {
  if (!state.sprite || !state.labels) return 0;
  const d = state.sprite.data;
  let n = 0;
  for (let i = 0; i < state.labels.length; i++) if (d[i * 4 + 3] && state.labels[i] < 0) n++;
  return n;
}

export function setView(patch) {
  Object.assign(state, patch);
  emit('view');
}
export function setUnassignedColor(color) {
  if (!/^#[0-9a-f]{6}$/i.test(color || '')) return;
  state.unassignedColor = color.toUpperCase();
  try {
    localStorage.setItem(UNASSIGNED_KEY, state.unassignedColor);
  } catch { /* stockage indisponible : le choix vaut pour la session */ }
  emit('view');
}
export function setLayer(name, value) {
  state.layers[name] = value ?? !state.layers[name];
  emit('view');
}
/** Un calque n'est dessiné que s'il a un sens à l'étape courante (Préparer montre le sprite nu). */
export function layerActive(name) {
  if (state.step === 'prepare') return name === 'grid' && state.layers.grid;
  if (name === 'onion') return isAnimStep() && state.layers.onion;
  return !!state.layers[name];
}
export function layerAvailable(name) {
  if (state.step === 'prepare') return name === 'grid';
  return name !== 'onion' || isAnimStep();
}
export function setSelection(sel) {
  state.selection = sel;
  emit('selection');
}
export function setFrame(i, { wrap = true } = {}) {
  const n = frameCount();
  if (!n) return;
  state.frame = wrap ? ((i % n) + n) % n : Math.max(0, Math.min(n - 1, i));
  emit('frame');
}
export function setStep(step) {
  if (state.step === step) return;
  state.step = step;
  if (!isAnimStep() && state.playing) state.playing = false;
  if (step === 'prepare' || (step !== 'rig' && (state.tool === 'brush' || state.tool === 'eraser'))) state.tool = 'select';
  if (step !== 'animate' && state.tool === 'retouch') state.tool = 'select';
  emit('view');
}

// --- Passerelles vers le backend (le reste de l'UI n'importe jamais api.js) -------
export const backend = { kind: api.kind, isDemo: !!api.demo, canExport: !!api.capabilities.export, canSwap: !!api.capabilities.swaps };
export const uploadSwapImage = (name, file) => api.putSwapImage(name, file);
export const fetchSwapImage = (name, image) => api.getSwapImage(name, image);
export const importImage = (img) => openProject(`Ouvrir « ${img.name} »`, () => api.importImage(img));
export const loadExample = () => openProject('Charger l\'exemple', () => api.demo.loadExample());
export const exportProject = (options) => api.exportProject(options);
/** DÉMO : fait jouer à Claude une modification de rig.json. `conflict` = à l'insu de l'app, puis écriture. */
export function simulateClaude({ conflict = false } = {}) {
  api.demo.externalEdit({ silent: conflict });
  if (conflict) scheduleSave(['rig']);
}
export function toast(message, opts = {}) {
  emit('toast', { message, ...opts });
}

// --- Chargement ---------------------------------------------------------------
export async function loadProject({ keepView = false } = {}) {
  if (!keepView) {
    state.status = 'loading';
    emit('status');
  }
  try {
    const p = await api.getProject();
    if (!p) {
      Object.assign(state, { status: 'empty', sprite: null, rig: null, anim: null, labels: null, partNames: [], report: null, selection: null, qaFocus: null, name: '' });
    } else {
      Object.assign(state, {
        status: 'ready', error: null, name: p.name, sprite: p.sprite, spriteRev: p.spriteRev, palette: p.palette, prepare: p.prepare, presets: p.presets,
        rig: p.rig.data, rigRev: p.rig.rev, partNames: p.rig.labelmap.parts, labels: p.rig.labelmap.labels,
        anim: p.anim ? p.anim.data : null, animRev: p.anim ? p.anim.rev : null,
        selection: null, qaFocus: null, playing: false, frame: 0, report: null,
      });
      state.hiddenParts.clear();
      state.hiddenBones.clear();
      if (!keepView) {
        const total = state.labels.reduce((n, v, i) => n + (state.sprite.data[i * 4 + 3] ? 1 : 0), 0);
        const un = unassignedCount();
        state.step = un === total ? 'prepare' : un > 0 || !state.anim ? 'rig' : 'animate';
        state.tool = 'select';
      }
      state.sync = { state: 'saved', author: p.rig.author === 'external' ? 'claude' : 'human', at: p.rig.at, message: '', conflict: null };
    }
  } catch (e) {
    state.status = 'error';
    state.error = e.message;
  }
  emit('status');
  emit('project');
  emit('sync');
  if (state.status === 'ready') refreshReport();
}

// --- QA -----------------------------------------------------------------------
let reportGen = 0;
export async function refreshReport() {
  const g = ++reportGen;
  try {
    const r = await api.getReport();
    if (g !== reportGen) return;
    state.report = r;
    state.reportError = null;
    if (state.qaFocus) {
      const c = r.checks.find((k) => k.id === state.qaFocus.id && k.frame === state.qaFocus.frame && k.pass === false);
      state.qaFocus = c && c.pixels && c.pixels.length ? { ...state.qaFocus, pixels: c.pixels } : c ? state.qaFocus : null;
      emit('qa');
    }
  } catch (e) {
    if (g !== reportGen) return;
    state.reportError = e.message;
  }
  emit('report');
}

// --- Commandes (toutes annulables) ----------------------------------------------
const getPath = (root, path) => path.reduce((o, k) => (o == null ? undefined : o[k]), root);
function setPath(root, path, value) {
  let o = root;
  for (let i = 0; i < path.length - 1; i++) {
    if (o[path[i]] == null) o[path[i]] = {};
    o = o[path[i]];
  }
  const last = path[path.length - 1];
  if (value === undefined) delete o[last];
  else o[last] = clone(value);
}

/** Affecte une valeur à un chemin de rig.json ou anim.json. `mergeKey` fusionne les coups rapprochés. */
export function setCmd(doc, path, value, label, mergeKey = null) {
  const before = clone(getPath(state[doc], path));
  const cmd = {
    label, mergeKey, saves: [doc], emits: [doc],
    after: clone(value),
    redo() { setPath(state[doc], path, cmd.after); },
    undo() { setPath(state[doc], path, before); },
    absorb(next) { cmd.after = next.after; },
    isNoop: () => JSON.stringify(before) === JSON.stringify(cmd.after),
  };
  return cmd;
}

/** Trait de pinceau / gomme : diff compact de la label map. */
export function paintCmd(indices, before, after, label) {
  const apply = (values) => {
    for (let k = 0; k < indices.length; k++) state.labels[indices[k]] = values[k];
  };
  // Écrire la label map fait ré-encoder TOUTES les régions en rects + pixels par le cœur.
  // Si le rig contient des régions écrites à la main (polygones, exclusions), on garde leur
  // texte d'origine : annuler ce trait les réécrit telles quelles au lieu de repasser par la label map.
  const hand = handRegionParts();
  const original = hand.length ? Object.fromEntries(state.partNames.map((n) => [n, clone(state.rig.parts[n].region)])) : null;
  const cmd = {
    label, saves: ['labels'], emits: ['labels'], convertsRegions: hand,
    redo() {
      apply(after);
      cmd.saves = ['labels'];
    },
    undo() {
      apply(before);
      if (!original) return;
      for (const [n, region] of Object.entries(original)) if (state.rig.parts[n]) state.rig.parts[n].region = clone(region);
      cmd.saves = ['rig'];
      cmd.emits = ['labels', 'rig'];
    },
  };
  return cmd;
}

const filled = (r) => !!r && ['rects', 'polygons', 'pixels'].some((k) => Array.isArray(r[k]) && r[k].length);
/** Pièces dont la région contient ce que la label map ne sait pas réécrire : polygones ou exclusions. */
export function handRegionParts() {
  if (!state.rig) return [];
  return Object.keys(state.rig.parts).filter((n) => {
    const r = state.rig.parts[n].region || {};
    return (Array.isArray(r.polygons) && r.polygons.length > 0) || filled(r.exclude);
  });
}

/**
 * Édition structurelle de rig.json et / ou anim.json en un seul pas d'historique : ajouter,
 * renommer ou supprimer un pivot (os), ajouter une pièce, ajouter ou retirer une frame.
 * `mutate` reçoit un brouillon { rig, anim, partNames, selection, frame } et le modifie.
 */
export function editCmd(label, mutate) {
  const snap = () => ({ rig: clone(state.rig), anim: clone(state.anim), partNames: [...state.partNames], selection: clone(state.selection), frame: state.frame });
  const before = snap(), after = snap();
  mutate(after);
  const rigChanged = JSON.stringify(before.rig) !== JSON.stringify(after.rig);
  const animChanged = JSON.stringify(before.anim) !== JSON.stringify(after.anim);
  const partsChanged = before.partNames.join('\n') !== after.partNames.join('\n');
  const apply = (s) => {
    if (rigChanged) state.rig = clone(s.rig);
    if (partsChanged) state.partNames = [...s.partNames];
    if (animChanged) state.anim = clone(s.anim);
    state.selection = clone(s.selection);
    state.frame = Math.max(0, Math.min(s.frame, frameCount() - 1));
  };
  return {
    label,
    saves: [rigChanged && 'rig', animChanged && 'anim'].filter(Boolean),
    emits: [rigChanged && 'rig', partsChanged && 'labels', animChanged && 'anim', 'selection', 'frame'].filter(Boolean),
    redo: () => apply(after),
    undo: () => apply(before),
    isNoop: () => !rigChanged && !animChanged,
  };
}

export const rigSnap = () => ({ rig: clone(state.rig), partNames: [...state.partNames], labels: state.labels.slice() });
export const animSnap = () => ({ anim: clone(state.anim) });

/** Remplace un document entier (lot Claude, preset, rééchantillonnage, résolution de conflit). */
export function replaceCmd(doc, before, after, label, author = 'human') {
  const apply = (s) => {
    if (doc === 'rig') {
      state.rig = clone(s.rig);
      state.partNames = [...s.partNames];
      state.labels = s.labels.slice();
      const sel = state.selection;
      if (sel && !(sel.kind === 'bone' ? state.rig.bones[sel.id] : state.rig.parts[sel.id])) state.selection = null;
    } else {
      state.anim = clone(s.anim);
      state.frame = Math.max(0, Math.min(state.frame, frameCount() - 1));
    }
  };
  return {
    label, author,
    saves: doc === 'rig' ? ['rig', 'labels'] : ['anim'],
    emits: doc === 'rig' ? ['rig', 'labels', 'selection'] : ['anim', 'frame'],
    redo: () => apply(after),
    undo: () => apply(before),
  };
}

// --- Historique -----------------------------------------------------------------
const undoStack = [];
const redoStack = [];
let chain = Promise.resolve();

function settle(cmd, save) {
  for (const t of cmd.emits || []) emit(t);
  emit('history');
  if (save && cmd.saves && cmd.saves.length) scheduleSave(cmd.saves);
}

/** Exécute une commande et l'empile. `save: false` quand le serveur a déjà la nouvelle version. */
export function exec(cmd, { save = true } = {}) {
  if (cmd.isNoop && cmd.isNoop()) return;
  cmd.at = Date.now();
  cmd.author = cmd.author || 'human';
  const last = undoStack[undoStack.length - 1];
  cmd.redo();
  if (last && cmd.mergeKey && last.mergeKey === cmd.mergeKey && cmd.at - last.at < 800 && !redoStack.length) {
    last.absorb(cmd);
    last.at = cmd.at;
  } else undoStack.push(cmd);
  redoStack.length = 0;
  settle(cmd, save);
}

/** Empile une commande déjà appliquée (ex. import d'image, fait côté serveur). */
export function pushApplied(cmd) {
  cmd.at = Date.now();
  cmd.author = cmd.author || 'human';
  undoStack.push(cmd);
  redoStack.length = 0;
  emit('history');
}

function step(from, to, method) {
  chain = chain.then(async () => {
    const cmd = from.pop();
    if (!cmd) return;
    try {
      await cmd[method]();
      to.push(cmd);
      settle(cmd, true);
    } catch (e) {
      from.push(cmd);
      toast(`Impossible d'${method === 'undo' ? 'annuler' : 'appliquer'} « ${cmd.label} » : ${e.message}`, { kind: 'error' });
    }
  });
  return chain;
}
export const undo = () => step(undoStack, redoStack, 'undo');
export const redo = () => step(redoStack, undoStack, 'redo');
export const canUndo = () => undoStack.length > 0;
export const canRedo = () => redoStack.length > 0;
/** Entrées de l'historique, de la plus ancienne à la plus récente ; `done` = encore appliquée. */
export const history = () => [
  ...undoStack.map((c) => ({ label: c.label, author: c.author, at: c.at, done: true })),
  ...[...redoStack].reverse().map((c) => ({ label: c.label, author: c.author, at: c.at, done: false })),
];
/** Revient à l'état qui suit l'entrée n° index (-1 = tout annuler). Sert à « annuler un lot Claude ». */
export async function travelTo(index) {
  while (undoStack.length - 1 > index) await undo();
  while (undoStack.length - 1 < index && redoStack.length) await redo();
}

// --- Synchronisation avec les fichiers projet -------------------------------------
const dirty = new Set();
let pumping = null;

// Échos attendus : le serveur renvoie un événement pour chaque écriture de l'app. On note la
// révision de chacune de nos écritures ; l'événement qui la porte est consommé en silence,
// jamais présenté comme « Claude a modifié ». Une révision est un hash du CONTENU : on ne peut
// donc pas se contenter d'un ensemble « déjà vu » (Claude peut légitimement remettre un fichier
// dans un état antérieur) ; chaque écho attendu ne sert qu'une fois et expire au bout de 10 s.
// `busy` = écritures en vol ; les événements reçus pendant ce temps attendent la réponse HTTP.
const expectedEchoes = [];
function remember(...revs) {
  const until = Date.now() + 10000;
  revs.forEach((r) => r != null && expectedEchoes.push({ rev: r, until }));
}
function consumeEcho(rev) {
  const now = Date.now();
  for (let i = expectedEchoes.length - 1; i >= 0; i--) if (expectedEchoes[i].until < now) expectedEchoes.splice(i, 1);
  const i = expectedEchoes.findIndex((e) => e.rev === rev);
  if (i < 0) return false;
  expectedEchoes.splice(i, 1);
  return true;
}
let busy = 0;
let gestures = 0;
const deferred = [];
/**
 * Un geste d'édition est en cours dans le viewport (trait, glisser d'un joint). Les changements
 * venus du disque attendent sa fin : s'il écrit, le serveur répondra 409 et la bannière de
 * conflit s'ouvrira ; s'il n'écrit rien, le changement est appliqué juste après.
 */
export function beginGesture() {
  gestures++;
}
export function endGesture() {
  gestures = Math.max(0, gestures - 1);
  if (!gestures && !busy) deferred.splice(0).forEach(onServerEvent);
}
async function tracked(fn) {
  busy++;
  try {
    return await fn();
  } finally {
    busy--;
    if (!busy && !gestures) deferred.splice(0).forEach(onServerEvent);
  }
}

function setSync(patch) {
  state.sync = { ...state.sync, ...patch };
  emit('sync');
}

export function scheduleSave(kinds) {
  kinds.forEach((k) => dirty.add(k));
  return pump();
}

function pump() {
  if (pumping) return pumping;
  if (state.sync.state === 'conflict' || !dirty.size) return Promise.resolve();
  pumping = (async () => {
    setSync({ state: 'saving', message: '' });
    let kind = null;
    try {
      while (dirty.size) {
        // rig avant labels : une pièce tout juste ajoutée doit exister dans rig.json quand la label map la cite
        kind = ['rig', 'labels', 'anim'].find((k) => dirty.has(k));
        dirty.delete(kind);
        if (kind === 'labels') {
          const r = await tracked(() => api.putLabelMap({ parts: [...state.partNames], labels: state.labels.slice() }, state.rigRev));
          state.rigRev = r.rev;
          remember(r.rev);
          for (const [name, region] of Object.entries(r.regions)) if (state.rig.parts[name]) state.rig.parts[name].region = region;
        } else if (kind === 'rig') {
          state.rigRev = (await tracked(() => api.putRig(state.rig, state.rigRev))).rev;
          remember(state.rigRev);
        } else if (state.anim) {
          state.animRev = (await tracked(() => api.putAnim(state.anim, state.animRev))).rev;
          remember(state.animRev);
        } else if (state.animRev != null) {
          await tracked(() => api.deleteAnim(state.animRev));
          state.animRev = null;
        }
      }
      setSync({ state: 'saved', author: 'human', at: Date.now(), conflict: null });
      emit('saved');
      refreshReport();
    } catch (e) {
      dirty.add(kind);
      if (e instanceof ConflictError) setSync({ state: 'conflict', conflict: e.info });
      else setSync({ state: 'error', message: e.message });
    } finally {
      pumping = null;
    }
  })();
  return pumping;
}

export const retrySave = () => {
  setSync({ state: 'saving' });
  return pump();
};

/** Version du disque reprise dans l'app, comme un lot annulable attribué à Claude. */
async function adoptRemote(doc, label, author = 'claude') {
  if (doc === 'rig') {
    const fresh = await api.getRig();
    const before = rigSnap();
    state.rigRev = fresh.rev;
    exec(replaceCmd('rig', before, { rig: fresh.data, partNames: fresh.labelmap.parts, labels: fresh.labelmap.labels }, label, author), { save: false });
    return fresh;
  }
  const fresh = await api.getAnim();
  const before = animSnap();
  state.animRev = fresh ? fresh.rev : null;
  exec(replaceCmd('anim', before, { anim: fresh ? fresh.data : null }, label, author), { save: false });
  return fresh;
}

/** Résout un conflit d'écriture. choice = 'mine' (ma version écrase) | 'theirs' (je reprends celle du disque). */
export async function resolveConflict(choice) {
  const c = state.sync.conflict;
  if (!c) return;
  const file = c.doc + '.json';
  if (choice === 'mine') {
    state[c.doc + 'Rev'] = c.rev;
    if (c.doc === 'rig') dirty.add('rig').add('labels');
    else dirty.add('anim');
    setSync({ state: 'saving', conflict: null });
    await pump();
  } else {
    (c.doc === 'rig' ? ['rig', 'labels'] : ['anim']).forEach((k) => dirty.delete(k));
    try {
      const fresh = await adoptRemote(c.doc, `Version de Claude reprise (${file})`);
      setSync({ state: 'saved', author: 'claude', at: (fresh && fresh.at) || Date.now(), conflict: null });
      emit('saved');
      refreshReport();
      toast(`Version de Claude reprise pour ${file}. Votre version reste dans l'historique.`, { action: { label: 'Revenir à ma version', run: undo } });
      pump();
    } catch (e) {
      setSync({ state: 'error', message: e.message });
    }
  }
}

let eventChain = Promise.resolve();
function onServerEvent(ev) {
  eventChain = eventChain.then(() => handleServerEvent(ev)).catch((e) => setSync({ state: 'error', message: e.message }));
}

async function handleServerEvent(ev) {
  if (ev.type === 'connection.lost') return setSync({ state: 'offline' });
  if (ev.type === 'connection.open') return state.sync.state === 'offline' && loadProject({ keepView: true });
  // Une écriture de l'app est en vol : on ne sait pas encore si cet événement est son écho.
  if (busy || gestures) return deferred.push(ev);
  if (ev.type === 'project.changed') {
    // Écho d'un import ou d'une restauration faits ici ? On compare avec ce que le serveur a maintenant.
    const revs = await api.getRevisions();
    if (!revs) return state.status === 'empty' ? null : loadProject();
    if (state.status === 'ready' && revs.sprite === state.spriteRev && revs.rig === state.rigRev && (revs.anim ?? null) === (state.animRev ?? null)) return null;
    return loadProject({ keepView: state.status === 'ready' });
  }
  const doc = ev.type === 'rig.changed' ? 'rig' : ev.type === 'anim.changed' ? 'anim' : null;
  if (!doc || state.status !== 'ready') return null;
  const echo = ev.rev != null && consumeEcho(ev.rev); // écho d'une de nos écritures, même déjà dépassée
  if (echo || (ev.rev ?? null) === (state[doc + 'Rev'] ?? null)) return null; // rien de neuf pour cette fenêtre
  if (pumping || dirty.size || state.sync.state === 'conflict') return null; // l'écriture en attente remontera le conflit (409)
  // `app` + révision inconnue = une autre fenêtre de l'éditeur ; `external` = Claude, la CLI, un éditeur de texte.
  const other = ev.author === 'app';
  const who = other ? 'tab' : 'claude';
  await adoptRemote(doc, other ? `Modification de ${doc}.json dans une autre fenêtre` : `Modification de ${doc}.json`, who);
  setSync({ state: 'saved', author: who, at: ev.at || Date.now(), conflict: null });
  emit('saved');
  refreshReport();
  toast(other ? `${doc}.json a été modifié dans une autre fenêtre de l'éditeur.` : `Claude a modifié ${doc}.json.`, { action: { label: 'Annuler ce lot', run: undo } });
  return null;
}

api.subscribe(onServerEvent);

// --- Opérations exécutées par le cœur -----------------------------------------------
async function serverAnimOp(label, call) {
  await pump();
  if (state.sync.state === 'conflict') return;
  const before = animSnap();
  try {
    const r = await tracked(() => call(state.animRev));
    state.animRev = r.rev;
    remember(r.rev);
    exec(replaceCmd('anim', before, { anim: r.data }, label), { save: false });
    setSync({ state: 'saved', author: 'human', at: Date.now() });
    emit('saved');
    refreshReport();
    (r.warnings || []).forEach((w) => toast(w, { kind: 'warn', engine: true }));
  } catch (e) {
    if (e instanceof ConflictError) setSync({ state: 'conflict', conflict: e.info });
    else toast(e.message, { kind: 'error' });
    emit('anim'); // rétablit les champs saisis
  }
}
export const applyPreset = (name) => serverAnimOp(`Preset « ${name} »`, (rev) => api.applyPreset(name, rev));
export const retime = (params) => serverAnimOp('Changer la durée / le nombre de frames', (rev) => api.retimeAnim(params, rev));

/** Ouvre une image (ou l'exemple) : remplace le projet, de façon annulable via les versions. */
export async function openProject(label, action) {
  await pump();
  const hadProject = state.status === 'ready';
  state.status = 'loading';
  emit('status');
  try {
    await tracked(async () => {
      // Sans projet ouvert il n'y a rien à mettre de côté : l'ouverture n'est alors pas annulable.
      const before = hadProject ? await api.createSnapshot('Avant : ' + label) : null;
      await action();
      const after = await api.createSnapshot(label);
      const restore = (id) => () => tracked(async () => {
        await api.restoreSnapshot(id);
        await loadProject();
      });
      if (before) pushApplied({ label, undo: restore(before.id), redo: restore(after.id) });
      await loadProject();
    });
    return true;
  } catch (e) {
    await loadProject();
    throw e;
  }
}
