// Habillage : barre du haut (étapes, synchro, annuler/rétablir, thème, aide), rail d'outils,
// barre des calques, barre d'état, bannières, notifications, états vide / chargement / erreur.

import { h, $, mount, icon, fmtTime } from '../dom.js';
import {
  state, on, emit, setStep, setLayer, setView, setUnassignedColor, UNASSIGNED_DEFAULT, undo, redo, canUndo, canRedo, backend, toast,
  resolveConflict, retrySave, simulateClaude, importImage, loadExample, loadProject, isAnimStep, layerAvailable, frameCount, retouchColor,
} from '../store.js';
import { setTool, clearRetouch } from '../edits.js';
import { SHORTCUTS } from '../shortcuts.js';
import * as viewport from '../viewport.js';

export const STEPS = [
  { id: 'prepare', label: 'Préparer' },
  { id: 'rig', label: 'Rigger' },
  { id: 'animate', label: 'Animer' },
  { id: 'export', label: 'Exporter' },
];

const TOOLS = [
  { id: 'select', label: 'Sélection', key: 'V', icon: 'select' },
  { id: 'brush', label: 'Pinceau', key: 'B', icon: 'brush' },
  { id: 'eraser', label: 'Gomme', key: 'E', icon: 'eraser' },
  { id: 'joint', label: 'Déplacer joint / os', key: 'J', icon: 'joint' },
  { id: 'retouch', label: 'Retouche : peindre les pixels de la frame', key: 'T', icon: 'retouch' },
];

const LAYERS = [
  { id: 'skeleton', label: 'Squelette', key: 'S' },
  { id: 'labelmap', label: 'Label map', key: 'L' },
  { id: 'pivots', label: 'Pivots', key: 'P' },
  { id: 'grid', label: 'Grille', key: 'G' },
  { id: 'onion', label: 'Onion skin', key: 'O' },
];

export const BACKGROUNDS = [
  { id: 'checker', label: 'Damier' },
  { id: 'grey', label: 'Gris 50 %' },
  { id: 'black', label: 'Noir' },
  { id: 'white', label: 'Blanc' },
];

/** Palette du cadre des pixels non assignés : couleurs vives, rares dans un sprite. */
const UNASSIGNED_COLORS = [
  { hex: UNASSIGNED_DEFAULT, label: 'Vert (défaut)' },
  { hex: '#FF00FF', label: 'Magenta' },
  { hex: '#00FFFF', label: 'Cyan' },
  { hex: '#FFFF00', label: 'Jaune' },
  { hex: '#FF0000', label: 'Rouge' },
  { hex: '#FF8000', label: 'Orange' },
  { hex: '#0080FF', label: 'Bleu' },
  { hex: '#FFFFFF', label: 'Blanc' },
];

// --- Thème -------------------------------------------------------------------------
export function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem('animai.theme', next);
  } catch { /* stockage indisponible : le choix vaut pour la session */ }
  emit('theme');
}

// --- Barre du haut -----------------------------------------------------------------
function syncLabel() {
  const s = state.sync;
  const who = s.author === 'claude' ? 'Claude' : s.author === 'tab' ? 'autre fenêtre' : 'vous';
  switch (s.state) {
    case 'saving': return { text: 'Enregistrement…', kind: 'busy' };
    case 'conflict': return { text: 'Conflit d\'écriture', kind: 'danger' };
    case 'offline': return { text: 'Serveur injoignable', kind: 'danger' };
    case 'error': return { text: 'Échec d\'enregistrement', kind: 'danger' };
    default: return { text: s.at ? `Enregistré ${fmtTime(s.at)} · ${who}` : 'À jour', kind: 'ok' };
  }
}

let syncOpen = false;
let colorOpen = false;
let retouchOpen = false;

const RETOUCH_MODES = [
  { id: 'paint', label: 'Peindre', title: 'Peindre avec la couleur choisie' },
  { id: 'erase', label: 'Effacer', title: 'Rendre des pixels transparents dans cette frame' },
  { id: 'restore', label: 'Restaurer', title: 'Retirer la retouche : le pixel redevient celui du rendu' },
];

function renderTopbar() {
  const ready = state.status === 'ready';
  const sync = syncLabel();
  const steps = h('ol', { class: 'steps' }, STEPS.map((s, i) =>
    h('li', {}, h('button', {
      class: 'step', 'data-fid': 'step:' + s.id, disabled: !ready,
      'aria-current': ready && state.step === s.id ? 'step' : null,
      title: `${s.label} (${i + 1})`,
      onclick: () => setStep(s.id),
    }, h('span', { class: 'step-num' }, i + 1), s.label))));

  const syncPanel = syncOpen && h('div', { class: 'popover', role: 'group', 'aria-label': 'Synchronisation' },
    h('p', {}, backend.isDemo
      ? 'Mode démo : aucun serveur. Les « fichiers projet » sont en mémoire et disparaissent au rechargement.'
      : 'L\'app et Claude éditent les mêmes fichiers projet. Chaque modification est écrite immédiatement.'),
    h('p', { class: 'muted' }, state.sync.at ? `Dernière écriture : ${fmtTime(state.sync.at)} par ${state.sync.author === 'claude' ? 'Claude (hors app)' : state.sync.author === 'tab' ? 'une autre fenêtre de l\'éditeur' : 'vous'}.` : 'Aucune écriture pour l\'instant.'),
    state.sync.message && h('p', { class: 'danger' }, state.sync.message),
    backend.isDemo && ready && h('div', { class: 'popover-actions' },
      h('button', { class: 'btn', 'data-fid': 'sim-edit', onclick: () => { syncOpen = false; simulateClaude(); renderTopbar(); } }, 'Simuler une modification de Claude'),
      h('button', { class: 'btn', 'data-fid': 'sim-conflict', onclick: () => { syncOpen = false; simulateClaude({ conflict: true }); renderTopbar(); } }, 'Simuler un conflit d\'écriture')));

  mount($('#topbar'),
    h('div', { class: 'brand' }, h('strong', {}, 'animAI'), ready && h('span', { class: 'project-name', title: 'Projet ouvert' }, state.name),
      backend.isDemo && h('span', { class: 'tag', title: 'Données embarquées, cœur simulé : rien n\'est écrit sur le disque.' }, 'Démo')),
    h('nav', { 'aria-label': 'Étapes du parcours' }, steps),
    h('div', { class: 'topbar-actions' },
      h('div', { class: 'sync-wrap' },
        h('button', {
          class: 'sync sync-' + sync.kind, 'data-fid': 'sync', 'aria-expanded': String(syncOpen), 'aria-haspopup': 'true',
          title: 'État de la synchronisation avec les fichiers projet',
          onclick: () => { syncOpen = !syncOpen; renderTopbar(); },
        }, h('span', { class: 'sync-dot', 'aria-hidden': 'true' }), sync.text),
        syncPanel),
      h('button', { class: 'icon-btn', 'data-fid': 'undo', disabled: !canUndo(), 'aria-label': 'Annuler', title: 'Annuler (Ctrl+Z)', onclick: undo }, icon('undo')),
      h('button', { class: 'icon-btn', 'data-fid': 'redo', disabled: !canRedo(), 'aria-label': 'Rétablir', title: 'Rétablir (Ctrl+Y)', onclick: redo }, icon('redo')),
      h('button', { class: 'icon-btn', 'data-fid': 'theme', 'aria-label': 'Basculer le thème clair / sombre', title: 'Thème clair / sombre (Maj+T)', onclick: toggleTheme }, icon('theme')),
      h('button', { class: 'icon-btn', 'data-fid': 'help', 'aria-label': 'Aide et raccourcis clavier', title: 'Raccourcis clavier (?)', onclick: toggleHelp }, icon('help'))));
}

/** Rend le focus au bouton `fid` quand l'élément qui l'avait vient de disparaître. */
function refocus(fid) {
  if (document.activeElement && document.activeElement !== document.body) return;
  const el = $(`[data-fid="${fid}"]`);
  if (el) el.focus();
}

export function closePopovers() {
  if (!syncOpen && !colorOpen && !retouchOpen) return false;
  const opener = syncOpen ? 'sync' : colorOpen ? 'unassigned-color' : 'retouch-color';
  if (syncOpen) {
    syncOpen = false;
    renderTopbar();
  }
  if (colorOpen || retouchOpen) {
    colorOpen = retouchOpen = false;
    renderLayerbar();
  }
  refocus(opener);
  return true;
}

// --- Bannière (conflit, échec d'écriture) : jamais modale ------------------------------
function renderBanner() {
  const el = $('#banner');
  const s = state.sync;
  if (s.state === 'conflict' && s.conflict) {
    const c = s.conflict, file = c.doc + '.json';
    el.hidden = false;
    mount(el,
      h('div', { class: 'banner-text' },
        h('strong', {}, `Conflit sur ${file}. `),
        `Claude a modifié ce fichier${c.at ? ' à ' + fmtTime(c.at) : ''} pendant que vous l'éditiez. Rien n'a été écrasé.`,
        c.changed_paths && c.changed_paths.length ? h('span', { class: 'banner-detail' }, ' Différences : ', h('code', {}, c.changed_paths.join(', ')), '.') : null),
      h('div', { class: 'banner-actions' },
        h('button', { class: 'btn', 'data-fid': 'conflict-mine', title: 'Écrit votre version par-dessus celle de Claude', onclick: () => resolveConflict('mine') }, 'Garder ma version'),
        h('button', { class: 'btn', 'data-fid': 'conflict-theirs', title: 'Remplace votre version ; elle reste récupérable par Annuler', onclick: () => resolveConflict('theirs') }, 'Prendre la version de Claude')));
  } else if (s.state === 'error' || s.state === 'offline') {
    el.hidden = false;
    mount(el,
      h('div', { class: 'banner-text' }, h('strong', {}, s.state === 'offline' ? 'Serveur injoignable. ' : 'Enregistrement impossible. '),
        s.message || 'Vos modifications restent dans l\'app et seront écrites dès que possible.'),
      h('div', { class: 'banner-actions' }, h('button', { class: 'btn', 'data-fid': 'retry', onclick: retrySave }, 'Réessayer')));
  } else {
    el.hidden = true;
    el.replaceChildren();
  }
}

// --- Rail d'outils -----------------------------------------------------------------
function renderTools() {
  const ready = state.status === 'ready';
  mount($('#toolrail'), TOOLS.map((t) => {
    const off = t.id === 'retouch' ? state.step !== 'animate' || !frameCount()
      : t.id !== 'select' && (state.step === 'prepare' || (t.id !== 'joint' && state.step !== 'rig'));
    return h('button', {
      class: 'icon-btn tool', 'data-fid': 'tool:' + t.id, disabled: !ready,
      'aria-pressed': String(state.tool === t.id), 'aria-disabled': off ? 'true' : null,
      'aria-label': t.label, title: `${t.label} (${t.key})${off ? ' — indisponible à cette étape' : ''}`,
      onclick: () => setTool(t.id),
    }, icon(t.icon));
  }));
}

// --- Barre des calques et du zoom ----------------------------------------------------
function renderLayerbar() {
  const ready = state.status === 'ready';
  const retouching = ready && state.tool === 'retouch';
  const painting = state.tool === 'brush' || state.tool === 'eraser' || retouching;
  const rc = retouching ? retouchColor() : null;
  const z = viewport.getZoom();
  mount($('#layerbar'),
    LAYERS.map((l) => {
      const avail = ready && layerAvailable(l.id);
      return h('button', {
        class: 'chip', 'data-fid': 'layer:' + l.id, disabled: !avail, 'aria-pressed': String(avail && !!state.layers[l.id]),
        title: avail || !ready ? `${l.label} (${l.key})` : `${l.label} : sans objet à cette étape`, onclick: () => setLayer(l.id),
      }, l.label);
    }),
    state.layers.labelmap && layerAvailable('labelmap') && h('label', { class: 'bar-field' }, 'Opacité',
      h('input', {
        type: 'range', min: '20', max: '100', step: '10', value: String(Math.round(state.labelOpacity * 100)), 'data-fid': 'label-opacity',
        'aria-label': 'Opacité de la label map',
        // pas d'emit('view') : reconstruire la barre pendant le glisser casserait le curseur
        oninput: (e) => { state.labelOpacity = e.target.value / 100; viewport.requestDraw(); },
      })),
    ready && layerAvailable('labelmap') && h('div', { class: 'bar-field color-wrap' },
      h('button', {
        class: 'chip', 'data-fid': 'unassigned-color', 'aria-expanded': String(colorOpen), 'aria-haspopup': 'true',
        title: 'Couleur du cadre des pixels non assignés', onclick: () => { colorOpen = !colorOpen; renderLayerbar(); },
      }, h('span', { class: 'px-swatch', style: { background: state.unassignedColor } }), 'Non assignés'),
      colorOpen && h('div', { class: 'popover color-popover', role: 'group', 'aria-label': 'Couleur du cadre des pixels non assignés' },
        h('div', { class: 'swatches' }, UNASSIGNED_COLORS.map((c) => h('button', {
          class: 'color-swatch', 'data-fid': 'unassigned-color:' + c.hex, style: { background: c.hex },
          'aria-pressed': String(state.unassignedColor === c.hex), 'aria-label': `${c.label} ${c.hex}`, title: `${c.label} ${c.hex}`,
          onclick: () => setUnassignedColor(c.hex),
        }))),
        h('label', { class: 'color-custom' }, 'Autre',
          // `change` (et non `input`) : reconstruire la barre pendant le choix fermerait le sélecteur
          h('input', { type: 'color', value: state.unassignedColor.toLowerCase(), 'data-fid': 'unassigned-color-custom', onchange: (e) => setUnassignedColor(e.target.value) }),
          h('code', {}, state.unassignedColor)))),
    retouching && h('div', { class: 'bar-field color-wrap' },
      h('button', {
        class: 'chip', 'data-fid': 'retouch-color', 'aria-expanded': String(retouchOpen), 'aria-haspopup': 'true',
        title: 'Couleur du pinceau de retouche (palette du sprite). Alt+clic dans le viewport : pipette.', onclick: () => { retouchOpen = !retouchOpen; renderLayerbar(); },
      }, h('span', { class: 'px-swatch', style: { background: rc || 'transparent' } }), 'Couleur ', h('code', {}, (rc || '').toUpperCase())),
      retouchOpen && h('div', { class: 'popover color-popover', role: 'group', 'aria-label': 'Couleur du pinceau de retouche' },
        h('div', { class: 'swatches palette-swatches' }, state.palette.map((c) => h('button', {
          class: 'color-swatch', 'data-fid': 'retouch-color:' + c.toLowerCase(), style: { background: c },
          'aria-pressed': String(rc === c.toLowerCase()), 'aria-label': c.toUpperCase(), title: c.toUpperCase(),
          onclick: () => { retouchOpen = false; setView({ retouchColor: c.toLowerCase(), retouchMode: 'paint' }); refocus('retouch-color'); },
        }))),
        h('p', { class: 'muted popover-note' }, 'Seules les couleurs du sprite sont proposées : une retouche n\'ajoute jamais de couleur.'))),
    retouching && RETOUCH_MODES.map((m) => h('button', {
      class: 'chip', 'data-fid': 'retouch-mode:' + m.id, 'aria-pressed': String(state.retouchMode === m.id), title: m.title,
      onclick: () => setView({ retouchMode: m.id }),
    }, m.label)),
    painting && h('label', { class: 'bar-field' }, 'Taille',
      h('input', {
        type: 'number', class: 'num', min: '1', max: '16', step: '1', value: String(state.brushSize), 'data-fid': 'brush-size',
        'aria-label': 'Taille du pinceau en pixels', onchange: (e) => setView({ brushSize: Math.max(1, Math.min(16, parseInt(e.target.value, 10) || 1)) }),
      }), 'px'),
    retouching && h('button', { class: 'btn', 'data-fid': 'retouch-clear', title: 'Retirer toutes les retouches de la frame courante (annulable)', onclick: clearRetouch }, 'Effacer les retouches de la frame'),
    h('span', { class: 'spacer' }),
    h('select', { 'data-fid': 'background', disabled: !ready, 'aria-label': 'Fond du viewport', title: 'Fond du viewport (Maj+B)', onchange: (e) => setView({ background: e.target.value }) },
      BACKGROUNDS.map((b) => h('option', { value: b.id, selected: state.background === b.id }, 'Fond : ' + b.label))),
    h('button', { class: 'icon-btn', 'data-fid': 'zoom-out', disabled: !ready || z === viewport.ZOOMS[0], 'aria-label': 'Zoom arrière', title: 'Zoom arrière (−)', onclick: () => viewport.zoomBy(-1) }, '−'),
    h('output', { class: 'zoom', title: 'Zoom entier : 1 pixel du sprite = N pixels d\'écran', 'aria-label': `Zoom ${z} fois` }, '×' + z),
    h('button', { class: 'icon-btn', 'data-fid': 'zoom-in', disabled: !ready || z === viewport.ZOOMS.at(-1), 'aria-label': 'Zoom avant', title: 'Zoom avant (+)', onclick: () => viewport.zoomBy(1) }, '+'),
    h('button', { class: 'btn', 'data-fid': 'fit', disabled: !ready, title: 'Ajuster à la fenêtre (0)', onclick: viewport.fit }, 'Ajuster'));

  const note = $('#vp-note');
  note.hidden = !(ready && backend.isDemo && isAnimStep());
}

// --- Barre d'état --------------------------------------------------------------------
const hex = (c) => '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('').toUpperCase();
let hintTimer = 0;

function renderHover() {
  const el = $('#status-hover');
  const hv = state.hover;
  if (!hv || state.status !== 'ready') return el.replaceChildren(h('span', { class: 'muted' }, 'Survolez le sprite pour lire un pixel'));
  const cells = [h('span', { class: 'coord' }, `x ${hv.x}`), h('span', { class: 'coord' }, `y ${hv.y}`)];
  if (!hv.inside) cells.push(h('span', { class: 'muted' }, 'hors image'));
  else if (!hv.alpha) cells.push(h('span', { class: 'muted' }, 'transparent'));
  else {
    cells.push(h('span', { class: 'px-swatch', style: { background: hex(hv.color) } }), h('span', {}, hex(hv.color)));
    if (hv.partIndex >= 0) cells.push(h('span', {}, `pièce ${hv.partIndex + 1} · ${state.partNames[hv.partIndex]}`));
    else if (hv.partIndex === -1) cells.push(h('span', { class: 'warn' }, 'non assigné'));
  }
  el.replaceChildren(...cells);
}

function renderStatusRight() {
  const s = state.sprite;
  $('#status-right').textContent = state.status === 'ready' ? `${s.width}×${s.height} px · ${state.palette.length} couleurs · zoom ×${viewport.getZoom()}` : '';
}

// --- Notifications -------------------------------------------------------------------
function showToast({ message, action, kind = 'info', engine = false }) {
  const box = $('#toasts');
  const close = () => el.remove();
  // Les avertissements du moteur sont en anglais : on les cite tels quels, annoncés comme tels,
  // plutôt que de les traduire à la volée (une traduction approximative d'un message technique induit en erreur).
  const el = h('div', { class: 'toast toast-' + kind },
    engine
      ? h('span', { class: 'toast-msg' }, 'Avertissement du moteur : ', h('span', { lang: 'en', class: 'engine-msg' }, message))
      : h('span', { class: 'toast-msg' }, (kind === 'error' ? 'Erreur : ' : kind === 'warn' ? 'Attention : ' : '') + message),
    action && h('button', { class: 'btn', onclick: () => { close(); action.run(); } }, action.label),
    h('button', { class: 'icon-btn', 'aria-label': 'Fermer la notification', onclick: close }, '×'));
  box.append(el);
  while (box.children.length > 4) box.firstChild.remove();
  if (kind !== 'error') {
    let t = setTimeout(close, action ? 12000 : 7000);
    el.addEventListener('pointerenter', () => clearTimeout(t));
    el.addEventListener('focusin', () => clearTimeout(t));
    el.addEventListener('pointerleave', () => (t = setTimeout(close, 4000)));
  }
}

// --- Aide ------------------------------------------------------------------------------
export function toggleHelp() {
  const dlg = $('#help');
  if (dlg.open) return dlg.close();
  if (!dlg.firstChild) {
    const groups = [];
    for (const s of SHORTCUTS) {
      if (!s.label) continue;
      let g = groups.find((x) => x.name === s.group);
      if (!g) groups.push((g = { name: s.group, rows: [] }));
      g.rows.push(s);
    }
    dlg.append(
      h('div', { class: 'help-head' }, h('h2', { id: 'help-title' }, 'Raccourcis clavier'),
        h('button', { class: 'btn', onclick: () => dlg.close() }, 'Fermer (Échap)')),
      h('div', { class: 'help-body' }, groups.map((g) => h('section', {}, h('h3', {}, g.name),
        h('table', {}, h('tbody', {}, g.rows.map((r) => h('tr', {}, h('th', { scope: 'row' }, h('kbd', {}, r.keys)), h('td', {}, r.label)))))))),
      h('p', { class: 'muted help-foot' }, 'Parcours : 1 Préparer → 2 Rigger → 3 Animer → 4 Exporter. Chaque modification est annulable (Ctrl+Z) et écrite dans les fichiers projet partagés avec Claude.'));
  }
  dlg.showModal();
}

// --- États : vide, chargement, erreur ---------------------------------------------------
let emptyError = '';

async function openFile(file) {
  emptyError = '';
  try {
    if (!file || !/^image\//.test(file.type)) throw new Error(`« ${file ? file.name : 'ce fichier'} » n'est pas une image. Déposez un PNG (ou GIF, WebP, JPEG).`);
    const bmp = await createImageBitmap(file, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' }).catch(() => {
      throw new Error(`Impossible de lire « ${file.name} » : fichier image corrompu ou format non pris en charge.`);
    });
    const c = document.createElement('canvas');
    c.width = bmp.width;
    c.height = bmp.height;
    const cx = c.getContext('2d', { willReadFrequently: true });
    cx.imageSmoothingEnabled = false;
    cx.drawImage(bmp, 0, 0);
    const img = cx.getImageData(0, 0, c.width, c.height);
    await importImage({ name: file.name, width: img.width, height: img.height, data: img.data, file });
  } catch (e) {
    if (state.status === 'ready') toast(e.message, { kind: 'error' });
    else {
      emptyError = e.message;
      renderOverlay();
    }
  }
}

function pickFile() {
  const input = h('input', { type: 'file', accept: 'image/*' });
  input.addEventListener('change', () => input.files[0] && openFile(input.files[0]));
  input.click();
}

function renderOverlay() {
  const el = $('#overlay');
  document.getElementById('app').dataset.status = state.status;
  if (state.status === 'ready') {
    el.hidden = true;
    return el.replaceChildren();
  }
  el.hidden = false;
  if (state.status === 'loading') {
    mount(el, h('div', { class: 'state-card', role: 'status' }, h('div', { class: 'spinner', 'aria-hidden': 'true' }), h('p', {}, 'Chargement du projet…')));
  } else if (state.status === 'error') {
    mount(el, h('div', { class: 'state-card', role: 'alert' },
      h('h2', {}, 'Le projet n\'a pas pu être chargé'),
      h('p', {}, state.error || 'Erreur inconnue.'),
      h('button', { class: 'btn primary', 'data-fid': 'reload', onclick: () => loadProject() }, 'Réessayer')));
  } else {
    mount(el, h('div', { class: 'state-card dropzone', id: 'dropzone' },
      h('h2', {}, 'Déposez un sprite pixel art ici'),
      h('p', {}, 'PNG de préférence, à sa résolution réelle (64×64 px ou plus), personnage vu de côté.'),
      h('div', { class: 'state-actions' },
        h('button', { class: 'btn primary', 'data-fid': 'pick', onclick: pickFile }, 'Choisir une image…'),
        backend.isDemo && h('button', { class: 'btn', 'data-fid': 'example', onclick: () => loadExample().catch((e) => { emptyError = e.message; renderOverlay(); }) }, 'Charger l\'exemple')),
      emptyError && h('p', { class: 'danger', role: 'alert' }, emptyError),
      h('ol', { class: 'state-steps' },
        h('li', {}, h('strong', {}, 'Préparer'), ' — vérifier le sprite nettoyé et sa palette'),
        h('li', {}, h('strong', {}, 'Rigger'), ' — assigner les pixels aux pièces, placer les joints'),
        h('li', {}, h('strong', {}, 'Animer'), ' — choisir un preset, régler frames et durée'),
        h('li', {}, h('strong', {}, 'Exporter'), ' — spritesheet, JSON et GIF'))));
  }
}

function initDrop() {
  let depth = 0;
  const veil = $('#dropveil');
  const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes('Files');
  window.addEventListener('dragenter', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth++;
    veil.hidden = false;
  });
  window.addEventListener('dragover', (e) => hasFiles(e) && e.preventDefault());
  window.addEventListener('dragleave', (e) => {
    if (!hasFiles(e)) return;
    if (--depth <= 0) {
      depth = 0;
      veil.hidden = true;
    }
  });
  window.addEventListener('drop', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    veil.hidden = true;
    openFile(e.dataTransfer.files[0]);
  });
}

export function initChrome() {
  on('status project view sync history', renderTopbar);
  on('sync', renderBanner);
  on('status view', renderTools);
  on('status view zoom', renderLayerbar);
  on('hover status', renderHover);
  on('status project zoom', renderStatusRight);
  on('status', renderOverlay);
  on('toast', showToast);
  on('hint', (message) => {
    const el = $('#status-hint');
    el.textContent = message;
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => (el.textContent = ''), 6000);
  });
  on('announce', (text) => ($('#live').textContent = text));
  document.addEventListener('pointerdown', (e) => {
    if ((syncOpen && !e.target.closest('.sync-wrap')) || ((colorOpen || retouchOpen) && !e.target.closest('.color-wrap'))) closePopovers();
  });
  initDrop();
  renderTopbar();
  renderBanner();
  renderTools();
  renderLayerbar();
  renderHover();
  renderOverlay();
}
