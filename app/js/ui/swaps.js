// Panneau droit : pièces de remplacement (rig.json « swaps »). Déclarer une image dessinée à la main,
// choisir son os, son ancre, les pièces qu'elle remplace et son z. L'activation par frame reste dans
// la timeline ; le bouton « Dans la frame » d'ici fait la même chose.

import { h, $, mount, icon } from '../dom.js';
import { state, on, backend, frameCount, uploadSwapImage, fetchSwapImage } from '../store.js';
import { hint, addSwap, editSwap, toggleSwapHide, renameSwap, deleteSwap, swapHides, toggleSwap } from '../edits.js';

const VIEW_W = 232, VIEW_H = 168, MAX_ZOOM = 8; // place disponible pour l'image, en pixels d'écran
const opened = new Set();
/** Images par chemin (`spec.image`) : { width, height, data } | { error } | { loading }. */
const images = new Map();

const swaps = () => state.rig.swaps || {};
const swapOn = (name) => frameCount() > 0 && ((state.anim.frames[state.frame] || {}).swap || []).includes(name);

function imageOf(name) {
  const key = swaps()[name].image;
  if (!images.has(key)) {
    // rig.json pas encore écrit : le serveur ne connaît pas ce remplacement, on redemandera une fois enregistré
    if (state.sync.state !== 'saved') return { loading: true };
    images.set(key, { loading: true });
    fetchSwapImage(name, key)
      .then((img) => images.set(key, img), (e) => images.set(key, { error: e.message }))
      .then(render);
  }
  return images.get(key);
}

// --- Ajout et remplacement de l'image -------------------------------------------------
function pickFile(then) {
  const input = h('input', { type: 'file', accept: 'image/png', onchange: () => input.files[0] && then(input.files[0]) });
  input.click();
}

function nameFromFile(file) {
  let base = file.name.replace(/\.[^.]*$/, '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^A-Za-z0-9_-]+/g, '_').replace(/^_+|_+$/g, '');
  if (!/^[A-Za-z]/.test(base)) base = 'swap' + (base ? '_' + base : '');
  base = base.slice(0, 48);
  const taken = Object.keys(swaps());
  if (!taken.includes(base)) return base;
  for (let i = 2; ; i++) if (!taken.includes(`${base}_${i}`)) return `${base}_${i}`;
}

let busy = false;
/** `back` : bouton qui a lancé l'envoi ; inactif pendant l'envoi, il reprend le focus ensuite (ou ce que rend `apply`). */
async function upload(name, file, back, apply) {
  if (busy) return;
  busy = true;
  render();
  let then = back;
  try {
    const r = await uploadSwapImage(name, file);
    images.set(r.image, r.pixels);
    then = apply(r) || back;
  } catch (e) {
    hint(e.message);
    showError(e.message);
  } finally {
    busy = false;
    render();
    if (!document.activeElement || document.activeElement === document.body) focusFid(then);
  }
}

let lastError = null;
function showError(message) {
  lastError = message;
}

function addFromFile(file) {
  lastError = null;
  const name = nameFromFile(file);
  upload(name, file, 'sw-add', (r) => {
    const err = addSwap(name, r.image, r);
    if (err) return showError(err);
    opened.add(name);
    return 'swap-canvas:' + name; // étape suivante : placer l'ancre
  });
}

function replaceImage(name) {
  pickFile((file) => {
    lastError = null;
    upload(name, file, 'sw-image-' + name, (r) => {
      if (r.image === swaps()[name].image) hint('Image identique à celle du remplacement : rien à changer.');
      else editSwap(name, 'image', r.image, 'Image');
    });
  });
}

// --- Image et ancre -------------------------------------------------------------------
function moveAnchor(name, x, y, merge = false) {
  const [ax, ay] = swaps()[name].anchor;
  if (x === ax && y === ay) return;
  editSwap(name, 'anchor', [x, y], 'Ancre', merge);
}

function anchorCanvas(name, img) {
  const spec = swaps()[name];
  const zoom = Math.max(1, Math.min(MAX_ZOOM, Math.floor(VIEW_W / img.width), Math.floor(VIEW_H / img.height)));
  const src = document.createElement('canvas');
  src.width = img.width;
  src.height = img.height;
  src.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(img.data), img.width, img.height), 0, 0);
  const canvas = h('canvas', {
    class: 'swap-canvas', width: img.width * zoom, height: img.height * zoom, tabindex: '0', role: 'application',
    'data-fid': 'swap-canvas:' + name, style: { width: img.width * zoom + 'px', height: img.height * zoom + 'px' },
    'aria-label': `Image du remplacement ${name}, ${img.width} par ${img.height} pixels. Ancre en ${spec.anchor[0]}, ${spec.anchor[1]}. Flèches : déplacer l'ancre d'un pixel, Maj = 5.`,
    title: 'Cliquez le pixel de l\'image qui se pose sur le joint de l\'os (flèches = 1 px)',
  });
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(src, 0, 0, canvas.width, canvas.height);
  // repère de l'ancre : cadre du pixel, noir doublé de blanc pour rester lisible sur toute couleur
  const [ax, ay] = spec.anchor;
  if (ax >= 0 && ay >= 0 && ax < img.width && ay < img.height) {
    ctx.lineWidth = 1;
    ctx.strokeStyle = '#fff';
    ctx.strokeRect(ax * zoom - 0.5, ay * zoom - 0.5, zoom + 1, zoom + 1);
    ctx.strokeStyle = '#000';
    ctx.strokeRect(ax * zoom + 0.5, ay * zoom + 0.5, zoom - 1, zoom - 1);
    ctx.strokeRect(ax * zoom - 1.5, ay * zoom - 1.5, zoom + 3, zoom + 3);
  }
  canvas.addEventListener('click', (e) => {
    const r = canvas.getBoundingClientRect();
    const x = Math.floor(((e.clientX - r.left) / r.width) * img.width), y = Math.floor(((e.clientY - r.top) / r.height) * img.height);
    moveAnchor(name, Math.max(0, Math.min(img.width - 1, x)), Math.max(0, Math.min(img.height - 1, y)));
  });
  canvas.addEventListener('keydown', (e) => {
    const d = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[e.key];
    if (!d || e.ctrlKey || e.metaKey || e.altKey) return;
    e.preventDefault();
    e.stopPropagation(); // sinon les flèches déplaceraient aussi le curseur du viewport
    const k = e.shiftKey ? 5 : 1, [cx, cy] = swaps()[name].anchor;
    moveAnchor(name, cx + d[0] * k, cy + d[1] * k, true);
  });
  return h('div', { class: 'swap-view' }, canvas);
}

function num(name, key, label, value, { min, max, unit, title, empty = false, onchange }) {
  const id = `sw-${key}-${name}`;
  const input = h('input', {
    type: 'number', class: 'num', id, 'data-fid': id, min, max, step: 1, title, placeholder: empty ? 'auto' : null,
    value: value == null ? '' : String(value),
    onchange: () => {
      if (empty && input.value === '') return onchange(null);
      const v = Math.max(min, Math.min(max, parseInt(input.value, 10)));
      if (Number.isNaN(v)) return render();
      onchange(v);
    },
  });
  return h('div', { class: 'field' }, h('label', { for: id }, label), h('span', { class: 'field-input' }, input, unit && h('span', { class: 'unit' }, unit)));
}

function focusFid(fid) {
  const el = $(`#swaps [data-fid="${CSS.escape(fid)}"]`);
  if (el) el.focus();
  return !!el;
}

/** Supprime, puis donne le focus à la carte voisine (à défaut au bouton d'ajout) : le bouton cliqué n'existe plus. */
function removeSwap(name) {
  const names = Object.keys(swaps()), i = names.indexOf(name);
  const next = names[i + 1] || names[i - 1];
  deleteSwap(name);
  if (!(next && focusFid('sw-sum-' + next))) focusFid('sw-add');
}

// --- Une ligne par remplacement --------------------------------------------------------
function swapCard(name) {
  const spec = swaps()[name];
  const img = imageOf(name);
  const hides = swapHides(name);
  const anchor = Array.isArray(spec.anchor) ? spec.anchor : [0, 0];
  const outside = img && img.data && (anchor[0] < 0 || anchor[1] < 0 || anchor[0] >= img.width || anchor[1] >= img.height);
  const nameInput = h('input', {
    type: 'text', class: 'txt', id: 'sw-name-' + name, 'data-fid': 'sw-name-' + name, value: name, spellcheck: 'false', autocomplete: 'off',
    title: 'Nom du remplacement, cité par les frames (anim.json). Entrée pour valider.',
    // Entrée valide sans quitter le champ
    onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); commitName(true); } },
    onchange: () => commitName(false),
  });
  const commitName = (keepFocus) => {
    const to = nameInput.value.trim();
    if (to === name) return;
    const err = renameSwap(name, to);
    if (err) {
      hint(err);
      nameInput.value = name;
      return;
    }
    opened.delete(name);
    opened.add(to);
    render();
    if (keepFocus) focusFid('sw-name-' + to);
  };
  const details = h('details', { class: 'swap', open: opened.has(name), 'data-swap-card': name },
    h('summary', { 'data-fid': 'sw-sum-' + name, title: name },
      h('span', { class: 'twisty', 'aria-hidden': 'true' }, icon('chevron')),
      h('span', { class: 'row-name' }, name),
      h('span', { class: 'row-meta' }, spec.bone)),
    h('div', { class: 'swap-body' },
      !img || img.loading ? h('p', { class: 'muted' }, 'Chargement de l\'image…')
        : img.error ? h('p', { class: 'note danger' }, img.error)
          : [anchorCanvas(name, img), h('p', { class: 'muted swap-size' }, `${img.width}×${img.height} px · `, h('code', {}, spec.image))],
      outside && h('p', { class: 'note warn' }, 'L\'ancre est hors de l\'image : cliquez un pixel de l\'image pour la replacer.'),
      h('div', { class: 'field' }, h('label', { for: 'sw-name-' + name }, 'Nom'), h('span', { class: 'field-input' }, nameInput)),
      h('div', { class: 'field' }, h('label', { for: 'sw-bone-' + name }, 'Os'),
        h('select', {
          id: 'sw-bone-' + name, 'data-fid': 'sw-bone-' + name, title: 'L\'image tourne et se déplace avec cet os',
          onchange: (e) => editSwap(name, 'bone', e.target.value, 'Os'),
        }, Object.keys(state.rig.bones).map((b) => h('option', { value: b, selected: spec.bone === b }, b)))),
      num(name, 'ax', 'Ancre X', anchor[0], { min: -512, max: 1024, unit: 'px', title: 'Colonne du pixel de l\'image posé sur le joint de l\'os', onchange: (v) => moveAnchor(name, v, swaps()[name].anchor[1]) }),
      num(name, 'ay', 'Ancre Y', anchor[1], { min: -512, max: 1024, unit: 'px', title: 'Ligne du pixel de l\'image posé sur le joint de l\'os', onchange: (v) => moveAnchor(name, swaps()[name].anchor[0], v) }),
      num(name, 'z', 'Z-index', spec.z, {
        min: -99, max: 99, empty: true, title: 'Plus grand = devant. Vide = z de la première pièce remplacée.',
        onchange: (v) => editSwap(name, 'z', v == null ? undefined : v, 'Z-index'),
      }),
      h('div', { class: 'field swap-hides' }, h('span', { class: 'field-label', id: 'sw-hides-' + name }, 'Remplace'),
        h('span', { class: 'chips', role: 'group', 'aria-labelledby': 'sw-hides-' + name }, state.partNames.map((p) => h('button', {
          class: 'chip', 'data-fid': `sw-hide-${name}:${p}`, 'aria-pressed': String(hides.includes(p)),
          title: `Ne pas dessiner la pièce « ${p} » dans les frames qui utilisent ce remplacement`,
          onclick: () => toggleSwapHide(name, p),
        }, p)))),
      h('div', { class: 'row' },
        frameCount() > 0 && h('button', {
          class: 'chip', 'data-fid': 'sw-use-' + name, 'data-swap-use': name, 'aria-pressed': String(swapOn(name)),
          title: 'Utiliser ce remplacement dans la frame courante (comme la pastille de la timeline)', onclick: () => toggleSwap(name),
        }, 'Dans la frame ', h('span', { class: 'sw-frame' }, state.frame + 1)),
        h('button', { class: 'btn small', 'data-fid': 'sw-image-' + name, disabled: busy, title: 'Choisir un autre PNG. L\'ancienne image quitte swaps/ ; Ctrl+Z la remet.', onclick: () => replaceImage(name) }, 'Changer l\'image…'),
        h('button', { class: 'btn small', 'data-fid': 'sw-delete-' + name, title: 'Retirer ce remplacement du rig et de toutes les frames, et son image du dossier swaps/ (annulable)', onclick: () => removeSwap(name) }, 'Supprimer'))));
  details.addEventListener('toggle', () => (details.open ? opened.add(name) : opened.delete(name)));
  return details;
}

function render() {
  const el = $('#swaps');
  const shown = state.status === 'ready' && (state.step === 'rig' || state.step === 'animate');
  el.hidden = !shown;
  if (!shown) return el.replaceChildren();
  const names = Object.keys(swaps());
  for (const n of [...opened]) if (!names.includes(n)) opened.delete(n);
  mount(el,
    h('div', { class: 'section-head' },
      h('h2', {}, 'Remplacements'),
      h('button', {
        class: 'btn small', 'data-fid': 'sw-add', disabled: !backend.canSwap || busy,
        title: 'Ajouter une image dessinée à la main (PNG aux couleurs du sprite) qui remplace des pièces dans les frames choisies',
        onclick: () => pickFile(addFromFile),
      }, busy ? 'Envoi…' : '+ Image…')),
    !names.length && h('p', { class: 'muted' }, 'Une pose que la rotation ne sait pas faire (bras qui se tend, main qui s\'ouvre) se dessine. Ajoutez un PNG aux couleurs du sprite : il remplace des pièces dans les frames où vous l\'activez.'),
    !backend.canSwap && h('p', { class: 'note' }, 'Indisponible en démo : l\'image est contrôlée et dessinée par le cœur, via le serveur.'),
    lastError && h('p', { class: 'note danger', role: 'alert' }, lastError, ' ',
      h('button', { class: 'link', 'data-fid': 'sw-error-close', onclick: () => { lastError = null; render(); } }, 'Fermer')),
    names.map(swapCard));
}

/** Changement de frame : seul l'état « dans la frame » bouge, pas de reconstruction. */
function light() {
  document.querySelectorAll('#swaps [data-swap-use]').forEach((b) => {
    b.setAttribute('aria-pressed', String(swapOn(b.dataset.swapUse)));
    b.querySelector('.sw-frame').textContent = state.frame + 1;
  });
}

export function initSwaps() {
  on('status project rig labels anim saved', render);
  let step = null;
  on('view', () => {
    if (step !== state.step) {
      step = state.step;
      render();
    }
  });
  on('frame', light);
  render();
}
