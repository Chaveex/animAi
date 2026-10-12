// Point d'entrée : initialise les zones, branche les raccourcis clavier, charge le projet.

import { $ } from './dom.js';
import { state, on, loadProject, loadExample, setStep, setLayer, setView, setSelection, undo, redo, frameCount, isAnimStep, backend } from './store.js';
import { SHORTCUTS } from './shortcuts.js';
import * as viewport from './viewport.js';
import { moveJoint, editBoneKey, boneKey, setTool, toggleVisibility, hint, captureFrame } from './edits.js';
import { initChrome, toggleTheme, toggleHelp, closePopovers, BACKGROUNDS } from './ui/chrome.js';
import { initHierarchy } from './ui/hierarchy.js';
import { initInspector } from './ui/inspector.js';
import { initSwaps } from './ui/swaps.js';
import { initQa, clearQaFocus } from './ui/qa.js';
import { initTimeline, togglePlay, stepFrame, gotoFrame } from './ui/timeline.js';
import './preview.js';

const selectedBone = () => (state.selection && state.selection.kind === 'bone' ? state.selection.id : null);

/** Flèches : déplacent le joint (outil Déplacer + os sélectionné) ou le curseur pixel. */
function nudge(dx, dy, e) {
  const k = e.shiftKey ? 5 : 1;
  dx *= k;
  dy *= k;
  const bone = selectedBone();
  if (state.status !== 'ready') return;
  if (state.tool === 'joint' && bone) {
    if (isAnimStep()) {
      if (!frameCount()) return;
      const [x, y] = boneKey(bone).pos;
      editBoneKey(bone, { pos: [x + dx, y + dy] }, true);
    } else {
      const [x, y] = state.rig.bones[bone].joint;
      moveJoint(bone, [x + dx, y + dy], true);
    }
  } else if (state.tool === 'joint') hint('Sélectionnez un os (clic sur un joint ou hiérarchie) pour le déplacer aux flèches.');
  else viewport.moveCursor(dx, dy);
}

function rotate(delta) {
  const bone = selectedBone();
  if (!bone) return hint('Sélectionnez un os pour le faire tourner.');
  if (!isAnimStep() || !frameCount()) return hint('La rotation se règle par frame : passez à l\'étape Animer (touche 3).');
  let rot = boneKey(bone).rot + delta;
  if (rot > 180) rot -= 360;
  if (rot < -180) rot += 360;
  editBoneKey(bone, { rot }, true);
}

const ZONES = ['#toolrail', '#tree', '#canvas', '#right', '#timeline'];
function focusZone(dir) {
  const cur = ZONES.findIndex((z) => $(z).contains(document.activeElement));
  for (let k = 1; k <= ZONES.length; k++) {
    const zone = $(ZONES[(cur + dir * k + ZONES.length * 2) % ZONES.length]);
    const target = zone.matches('canvas') ? zone : zone.querySelector('[tabindex="0"], button:not([disabled]), input:not([disabled]), select:not([disabled])');
    if (target) return target.focus();
  }
}

function cycleBackground() {
  const i = BACKGROUNDS.findIndex((b) => b.id === state.background);
  setView({ background: BACKGROUNDS[(i + 1) % BACKGROUNDS.length].id });
}

const step = (id) => () => state.status === 'ready' && setStep(id);
const P = () => 32 * (window.devicePixelRatio || 1);

const ACTIONS = {
  help: toggleHelp,
  undo, redo,
  step1: step('prepare'), step2: step('rig'), step3: step('animate'), step4: step('export'),
  zoneNext: () => focusZone(1), zonePrev: () => focusZone(-1),
  theme: toggleTheme,
  toolSelect: () => setTool('select'), toolBrush: () => setTool('brush'), toolEraser: () => setTool('eraser'), toolJoint: () => setTool('joint'), toolRetouch: () => setTool('retouch'),
  visibility: () => (state.selection ? toggleVisibility() : hint('Rien de sélectionné à masquer.')),
  left: (e) => nudge(-1, 0, e), right: (e) => nudge(1, 0, e), up: (e) => nudge(0, -1, e), down: (e) => nudge(0, 1, e),
  apply: () => viewport.applyAtCursor() || hint('Déplacez d\'abord le curseur pixel avec les flèches.'),
  zoomIn: () => viewport.zoomBy(1), zoomOut: () => viewport.zoomBy(-1), fit: viewport.fit,
  panLeft: () => viewport.panBy(P(), 0), panRight: () => viewport.panBy(-P(), 0), panUp: () => viewport.panBy(0, P()), panDown: () => viewport.panBy(0, -P()),
  layerSkeleton: () => setLayer('skeleton'), layerLabelmap: () => setLayer('labelmap'), layerPivots: () => setLayer('pivots'),
  layerGrid: () => setLayer('grid'), layerOnion: () => setLayer('onion'),
  background: cycleBackground,
  framePrev: () => stepFrame(-1), frameNext: () => stepFrame(1), frameFirst: () => gotoFrame(0), frameLast: () => gotoFrame(frameCount() - 1),
  rotPlus: () => rotate(15), rotMinus: () => rotate(-15),
  capture: () => (isAnimStep() ? captureFrame() : hint('La capture de pose se fait à l\'étape Animer (touche 3).')),
};

const TYPING = 'input:not([type="range"]):not([type="checkbox"]), textarea, select, [contenteditable]';
const ACTIVATES = 'button, a, summary, select, input, [role="treeitem"]';
const NEEDS_PROJECT = /^(tool|layer|frame|rot|capture|pan|zoom|fit|left|right|up|down|apply|visibility|background)/;
let spaceDown = false;

function onKeyDown(e) {
  if (e.defaultPrevented) return;
  const t = e.target instanceof Element ? e.target : document.body;
  const help = $('#help');
  if (e.key === 'Escape') {
    if (help.open) return; // le <dialog> se ferme tout seul
    if (viewport.cancelDrag() || closePopovers() || clearQaFocus()) return e.preventDefault();
    if (t.matches(TYPING)) return t.blur();
    viewport.clearCursor();
    if (state.selection) setSelection(null);
    return;
  }
  if (help.open) {
    if (e.key === '?') {
      e.preventDefault();
      help.close();
    }
    return;
  }
  if (t.matches(TYPING)) {
    if (e.key === 'F6') {
      e.preventDefault();
      focusZone(e.shiftKey ? -1 : 1);
    }
    return;
  }
  if (e.code === 'Space' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    if (t.matches(ACTIVATES)) return; // Espace active le contrôle qui a le focus
    e.preventDefault();
    if (!e.repeat) {
      spaceDown = true;
      viewport.setSpace(true);
    }
    return;
  }
  for (const sc of SHORTCUTS) {
    if (!sc.match || !sc.match(e)) continue;
    if (sc.id === 'apply' && t.matches(ACTIVATES)) return;
    if (/^(left|right|up|down)$/.test(sc.id) && t.matches('input')) return; // curseur de plage : flèches natives
    if (state.status !== 'ready' && NEEDS_PROJECT.test(sc.id)) return;
    e.preventDefault();
    ACTIONS[sc.id](e);
    return;
  }
}

function onKeyUp(e) {
  if (e.code !== 'Space' || !spaceDown) return;
  spaceDown = false;
  const panned = viewport.setSpace(false);
  if (!panned) togglePlay();
}

function boot() {
  initChrome();
  initHierarchy();
  initInspector();
  initSwaps();
  initQa();
  initTimeline();
  viewport.initViewport($('#canvas'));
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup', onKeyUp);
  window.addEventListener('blur', () => {
    spaceDown = false;
    viewport.setSpace(false);
  });
  on('status', () => {
    document.title = state.status === 'ready' ? `${state.name} — animAI` : 'animAI — Éditeur';
  });
  window.__animaiBooted = true;

  const params = new URLSearchParams(location.search);
  if (backend.isDemo && params.has('demo')) loadExample().catch(() => loadProject());
  else loadProject();
}

boot();
