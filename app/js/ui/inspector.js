// Panneau droit (haut) : carte de l'étape en cours + inspecteur de la sélection.

import { h, $, mount } from '../dom.js';
import {
  state, on, exec, setCmd, setStep, setSelection, frameCount, totalDuration, partsOfBone, unassignedCount,
  isAnimStep, applyPreset, backend, exportProject, handRegionParts,
} from '../store.js';
import { moveJoint, boneKey, editBoneKey, editFrameZ, renameBone, deleteBone, reparentBone, boneSubtree, newAnimation, renameAnim, hint } from '../edits.js';
import { labelStyle, swatchCss } from '../label-palette.js';
import { getFrame } from '../preview.js';
import { locateUnassigned } from './qa.js';

const VIEWS = [
  { id: 'side', label: 'De côté' },
  { id: 'front', label: 'De face (v2)', off: true },
  { id: '3/4', label: 'Trois-quarts (v2)', off: true },
  { id: 'top-down', label: 'Vue de dessus (v2)', off: true },
];

// --- Champs --------------------------------------------------------------------------
let scrubbing = false;
let fields = []; // { input, get } : rafraîchis sans reconstruire le panneau (indispensable pendant un scrub)

/** Champ numérique entier : saisie, flèches ↑↓ natives, et scrub en glissant sur le libellé. */
function numField({ fid, label, get, set, min = -9999, max = 9999, step = 1, unit = '', allowEmpty = false, placeholder = '', title = '' }) {
  const clamp = (v) => Math.max(min, Math.min(max, Math.round(v)));
  const input = h('input', {
    type: 'number', class: 'num', id: 'f-' + fid, 'data-fid': fid, min, max, step, placeholder, title,
    onchange: () => {
      if (allowEmpty && input.value === '') return set(null, false);
      const v = parseInt(input.value, 10);
      if (Number.isNaN(v)) return (input.value = show());
      set(clamp(v), false);
      input.value = show();
    },
  });
  const show = () => {
    const v = get();
    return v == null ? '' : String(v);
  };
  input.value = show();
  fields.push({ input, show });
  const lab = h('label', { class: 'scrub', for: 'f-' + fid, title: 'Glisser horizontalement pour faire varier la valeur' }, label);
  lab.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const x0 = e.clientX, v0 = get() ?? 0;
    let last = v0;
    lab.setPointerCapture(e.pointerId);
    scrubbing = true;
    const move = (ev) => {
      const v = clamp(v0 + Math.round((ev.clientX - x0) / 4) * step);
      if (v !== last) set((last = v), true);
    };
    const up = () => {
      scrubbing = false;
      lab.removeEventListener('pointermove', move);
      lab.removeEventListener('pointerup', up);
      lab.removeEventListener('pointercancel', up);
    };
    lab.addEventListener('pointermove', move);
    lab.addEventListener('pointerup', up);
    lab.addEventListener('pointercancel', up);
    e.preventDefault();
  });
  return h('div', { class: 'field' }, lab, h('span', { class: 'field-input' }, input, unit && h('span', { class: 'unit' }, unit)));
}

const info = (label, value) => h('div', { class: 'field' }, h('span', { class: 'field-label' }, label), h('span', { class: 'field-value' }, value));

function refreshValues() {
  for (const f of fields) if (document.activeElement !== f.input) f.input.value = f.show();
}

// --- Carte d'étape -------------------------------------------------------------------
function download(name, text) {
  const a = h('a', { href: URL.createObjectURL(new Blob([text], { type: 'application/json' })), download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

const next = (step, label) => h('button', { class: 'btn primary', 'data-fid': 'next-step', onclick: () => setStep(step) }, `Continuer : ${label} →`);

/** Prévient AVANT la perte : un trait de pinceau convertit les régions écrites à la main. */
function handNote() {
  const hand = handRegionParts();
  if (!hand.length) return null;
  return h('p', { class: 'note warn', id: 'hand-note' },
    `Ce rig décrit ${hand.length} pièce${hand.length > 1 ? 's' : ''} avec des polygones ou des exclusions écrits à la main (`,
    h('code', {}, hand.slice(0, 6).join(', ') + (hand.length > 6 ? '…' : '')),
    '). Le premier coup de pinceau ou de gomme réécrira toutes les régions en rectangles + pixels : même découpage au pixel près, mais la forme d\'origine quitte rig.json. Annulable (Ctrl+Z rétablit le texte d\'origine). Déplacer un joint ou changer un z-index n\'y touche pas.');
}

function stepCard() {
  const s = state.sprite;
  if (state.step === 'prepare') {
    return h('section', { class: 'card', 'aria-labelledby': 'step-title' },
      h('h2', { id: 'step-title' }, '1 · Préparer'),
      h('p', {}, 'Vérifiez que le sprite nettoyé est correct avant de construire le squelette.'),
      info('Taille', `${s.width}×${s.height} px`),
      info('Palette', `${state.palette.length} couleurs`),
      h('div', { class: 'palette', role: 'img', 'aria-label': `Palette de ${state.palette.length} couleurs` },
        state.palette.slice(0, 64).map((c) => h('span', { class: 'pal', style: { background: c }, title: c.toUpperCase() }))),
      info('Alpha', 'binaire (0 ou 255)'),
      h('div', { class: 'field' }, h('label', { for: 'f-view' }, 'Vue'),
        h('select', { id: 'f-view', 'data-fid': 'view', onchange: (e) => exec(setCmd('rig', ['view'], e.target.value, 'Changer le type de vue')) },
          VIEWS.map((v) => h('option', { value: v.id, selected: state.rig.view === v.id, disabled: v.off }, v.label)))),
      state.prepare.warnings.map((w) => h('p', { class: 'note warn' }, 'Attention : ' + w)),
      next('rig', 'Rigger'));
  }
  if (state.step === 'rig') {
    const un = unassignedCount();
    return h('section', { class: 'card', 'aria-labelledby': 'step-title' },
      h('h2', { id: 'step-title' }, '2 · Rigger'),
      h('p', {}, 'Chaque pixel appartient à une seule pièce rigide. Sélectionnez une pièce, peignez ses pixels (B), placez les pivots (J). « + Pivot » en ajoute un, l\'inspecteur le renomme ou le supprime.'),
      un
        ? h('p', { class: 'note warn' }, `${un} pixel${un > 1 ? 's' : ''} non assigné${un > 1 ? 's' : ''}. `,
          h('button', { class: 'link', 'data-fid': 'see-unassigned', onclick: locateUnassigned }, 'Les voir'))
        : h('p', { class: 'note ok' }, 'Tous les pixels sont assignés.'),
      handNote(),
      next('animate', 'Animer'));
  }
  if (state.step === 'animate') {
    const select = h('select', { id: 'f-preset', 'data-fid': 'preset' }, state.presets.map((p) => h('option', { value: p, selected: state.anim ? state.anim.name === p : p === 'walk' }, p)));
    return h('section', { class: 'card', 'aria-labelledby': 'step-title' },
      h('h2', { id: 'step-title' }, '3 · Animer'),
      h('p', {}, state.anim
        ? 'Outil Déplacer (J) : glissez un pivot pour faire tourner le membre qui le porte, un losange pour le bout d\'un membre (pas de 15° ; Maj = angle libre, Alt = décaler). « Capturer la pose » (K) garde la frame et en ouvre une copie.'
        : 'Aucune animation pour l\'instant : appliquez un preset, ou partez d\'une animation vide et posez-la à la main.'),
      state.anim && h('div', { class: 'field' }, h('label', { for: 'f-anim-name' }, 'Nom'),
        h('span', { class: 'field-input' }, h('input', {
          type: 'text', class: 'txt', id: 'f-anim-name', 'data-fid': 'anim-name', value: state.anim.name || '', spellcheck: 'false', autocomplete: 'off',
          title: 'Nom de l\'animation (écrit dans anim.json et dans l\'export)',
          onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); renameAnim(e.target.value); } }, onchange: (e) => renameAnim(e.target.value),
        }))),
      h('div', { class: 'field' }, h('label', { for: 'f-preset' }, 'Preset'),
        h('span', { class: 'field-input' }, select,
          h('button', { class: 'btn', 'data-fid': 'apply-preset', title: 'Remplace l\'animation courante (annulable)', onclick: () => applyPreset(select.value) }, 'Appliquer'))),
      h('button', { class: 'btn', 'data-fid': 'new-anim', title: 'Une frame au repos, à poser en glissant les pivots. Remplace l\'animation courante (annulable).', onclick: newAnimation }, 'Nouvelle animation vide'),
      backend.isDemo && h('p', { class: 'note' }, 'Démo : presets et aperçu sont des versions simplifiées. Le rendu réel (rotation propre, IK, anti-trous) viendra du cœur.'),
      state.anim && next('export', 'Exporter'));
  }
  // export
  const entry = getFrame(state.frame);
  const fails = state.report ? state.report.checks.filter((c) => c.pass === false).length : 0;
  const n = frameCount(), total = totalDuration();
  const [px, py] = state.rig.pivot || [0.5, 1];
  const pivotText = entry && entry.pivot
    ? `x ${entry.pivot[0]}, y ${entry.pivot[1]} px dans le canvas (rig : ${px} ; ${py} de la bbox au repos)`
    : `${px} ; ${py} de la bbox du sprite au repos`;
  const formats = ['spritesheet', 'gif'];
  const result = h('div', { id: 'export-result', role: 'status' });
  return h('section', { class: 'card', 'aria-labelledby': 'step-title' },
    h('h2', { id: 'step-title' }, '4 · Exporter'),
    n ? [
      info('Canvas', entry ? `${entry.width}×${entry.height} px (constant)` : 'calcul en cours…'),
      info('Frames', `${n} · ${total} ms · ≈ ${Math.round((n * 1000) / total)} fps`),
      info('Boucle', state.anim.loop ? 'oui' : 'non'),
      info('Pivot', pivotText),
      info('Fichiers', 'spritesheet PNG + JSON, GIF, rapport QA'),
      fails
        ? h('p', { class: 'note warn' }, `QA : ${fails} échec${fails > 1 ? 's' : ''}. L'export reste possible, mais corrigez d'abord si vous le pouvez (panneau QA ci-dessous).`)
        : h('p', { class: 'note ok' }, 'QA : aucun échec.'),
      h('button', {
        class: 'btn primary', 'data-fid': 'do-export', disabled: !backend.canExport,
        onclick: async () => {
          result.textContent = 'Export en cours…';
          try {
            const r = await exportProject({ formats });
            const failed = r.qa && r.qa.ok === false ? r.qa.failed || [] : null;
            mount(result,
              h('p', { class: 'note ok' }, 'Export terminé. Fichiers écrits :'),
              h('ul', { class: 'files' }, Object.values(r.outputs || {}).flat().map((f) => h('li', {}, h('code', {}, String(f))))),
              failed && h('p', { class: 'note warn' }, `QA de l'export en échec : ${failed.join(', ')}. Les fichiers sont écrits quand même.`),
              (r.warnings || []).map((w) => h('p', { class: 'note' }, 'Avertissement du moteur : ', h('span', { lang: 'en' }, w))));
          } catch (e) {
            mount(result, h('p', { class: 'note danger' }, 'Export impossible : ' + e.message));
          }
        },
      }, 'Exporter'),
      !backend.canExport && h('p', { class: 'note' }, 'Indisponible en démo : la spritesheet et le GIF sont produits par le cœur, via le serveur. Vous pouvez récupérer les fichiers projet :'),
      result,
    ] : h('p', { class: 'note warn' }, 'Rien à exporter : créez d\'abord une animation à l\'étape Animer.'),
    h('div', { class: 'row' },
      h('button', { class: 'btn', 'data-fid': 'dl-rig', onclick: () => download('rig.json', JSON.stringify(state.rig, null, 2)) }, 'Télécharger rig.json'),
      state.anim && h('button', { class: 'btn', 'data-fid': 'dl-anim', onclick: () => download('anim.json', JSON.stringify(state.anim, null, 2)) }, 'Télécharger anim.json')));
}

// --- Inspecteur ------------------------------------------------------------------------
function boneInspector(bone) {
  const b = state.rig.bones[bone];
  const parts = partsOfBone(bone);
  const ik = Object.entries(state.rig.ik || {}).filter(([, c]) => (c.chain || []).includes(bone) || c.target_bone === bone).map(([k]) => k);
  const nameInput = h('input', {
    type: 'text', class: 'txt', id: 'f-bone-name', 'data-fid': 'bone-name', value: bone, spellcheck: 'false', autocomplete: 'off',
    title: 'Renommer ce pivot (F2). Entrée pour valider.',
    // Entrée valide sans quitter le champ : le panneau est reconstruit, le focus y revient
    onkeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); commitName(); } },
    onchange: () => commitName(),
  });
  const commitName = () => {
    const err = renameBone(bone, nameInput.value);
    if (!err) return;
    hint(err);
    nameInput.value = bone;
  };
  const below = boneSubtree(bone);
  const root = !b.parent || !state.rig.bones[b.parent];
  const out = [
    h('h3', {}, 'Pivot (os) · ', h('code', {}, bone)),
    h('div', { class: 'field' }, h('label', { for: 'f-bone-name' }, 'Nom'), h('span', { class: 'field-input' }, nameInput)),
    root
      ? info('Parent', '— (racine)')
      : h('div', { class: 'field' }, h('label', { for: 'f-bone-parent' }, 'Parent'),
        h('select', { id: 'f-bone-parent', 'data-fid': 'bone-parent', title: 'Le pivot suit les mouvements de son parent', onchange: (e) => reparentBone(bone, e.target.value) },
          Object.keys(state.rig.bones).filter((o) => !below.includes(o)).map((o) => h('option', { value: o, selected: b.parent === o }, o)))),
    numField({ fid: 'joint-x', label: 'Joint X', unit: 'px', min: 0, max: state.sprite.width - 1, get: () => state.rig.bones[bone].joint[0], set: (v, m) => moveJoint(bone, [v, state.rig.bones[bone].joint[1]], m) }),
    numField({ fid: 'joint-y', label: 'Joint Y', unit: 'px', min: 0, max: state.sprite.height - 1, get: () => state.rig.bones[bone].joint[1], set: (v, m) => moveJoint(bone, [state.rig.bones[bone].joint[0], v], m) }),
    info('IK', ik.length ? `chaîne ${ik.join(', ')} (lecture seule)` : 'non'),
    info('Poids', '100 % sur cet os'),
    h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Pièces'),
      h('span', { class: 'field-value' }, parts.length
        ? parts.map((p) => h('button', { class: 'link', onclick: () => setSelection({ kind: 'part', id: p }) }, p))
        : 'aucune (rattachez une pièce : champ « Os » de la pièce, ou « + Pièce »)')),
    !root && h('button', {
      class: 'btn', 'data-fid': 'bone-delete', title: 'Ses pièces et ses enfants passent à son parent (Suppr dans la hiérarchie). Annulable.',
      onclick: () => { const err = deleteBone(bone); if (err) hint(err); else if (document.activeElement === document.body && $('#f-bone-name')) $('#f-bone-name').focus(); },
    }, 'Supprimer ce pivot'),
  ];
  if (isAnimStep() && frameCount()) {
    out.push(
      h('h3', { class: 'sub' }, 'Dans la frame ', h('span', { id: 'insp-frame' }, state.frame + 1)),
      numField({ fid: 'key-rot', label: 'Rotation', unit: '°', min: -180, max: 180, step: 15, title: 'Pas de 15° : les angles discrets gardent le pixel art propre', get: () => boneKey(bone).rot, set: (v, m) => editBoneKey(bone, { rot: v }, m) }),
      numField({ fid: 'key-x', label: 'Décalage X', unit: 'px', min: -64, max: 64, get: () => boneKey(bone).pos[0], set: (v, m) => editBoneKey(bone, { pos: [v, boneKey(bone).pos[1]] }, m) }),
      numField({ fid: 'key-y', label: 'Décalage Y', unit: 'px', min: -64, max: 64, get: () => boneKey(bone).pos[1], set: (v, m) => editBoneKey(bone, { pos: [boneKey(bone).pos[0], v] }, m) }),
      h('button', { class: 'btn', 'data-fid': 'key-reset', onclick: () => editBoneKey(bone, { rot: 0, pos: [0, 0] }) }, 'Remettre cet os à zéro dans la frame'));
  }
  return out;
}

function partInspector(part) {
  const k = state.partNames.indexOf(part), st = labelStyle(k);
  const count = () => {
    let n = 0;
    for (let i = 0; i < state.labels.length; i++) if (state.labels[i] === k) n++;
    return n;
  };
  const set = (key, label) => (v, m) => exec(setCmd('rig', ['parts', part, key], v, `${label} de « ${part} »`, m ? `${key}:${part}` : null));
  const out = [
    h('h3', {}, h('span', { class: 'swatch', style: { background: swatchCss(st) } }, h('span', {}, st.number)), ' Pièce · ', h('code', {}, part)),
    info('Repère', `n° ${st.number}, ${st.colorName}, motif ${st.patternName}`),
    h('div', { class: 'field' }, h('label', { for: 'f-part-bone' }, 'Os'),
      h('select', { id: 'f-part-bone', 'data-fid': 'part-bone', onchange: (e) => exec(setCmd('rig', ['parts', part, 'bone'], e.target.value, `Rattacher « ${part} » à « ${e.target.value} »`)) },
        Object.keys(state.rig.bones).map((b) => h('option', { value: b, selected: state.rig.parts[part].bone === b }, b)))),
    numField({ fid: 'part-z', label: 'Z-index', min: -99, max: 99, title: 'Plus grand = devant', get: () => state.rig.parts[part].z || 0, set: set('z', 'Z-index') }),
    numField({ fid: 'part-overlap', label: 'Chevauchement', unit: 'px', min: 0, max: 8, title: 'Extension de la pièce sous ses voisines (anti-trous)', get: () => state.rig.parts[part].overlap || 0, set: set('overlap', 'Chevauchement') }),
    h('div', { class: 'field' }, h('span', { class: 'field-label' }, 'Pixels'), h('span', { class: 'field-value', id: 'insp-pixels' }, count())),
  ];
  if (isAnimStep() && frameCount()) {
    out.push(
      h('h3', { class: 'sub' }, 'Dans la frame ', h('span', { id: 'insp-frame' }, state.frame + 1)),
      numField({
        fid: 'frame-z', label: 'Z forcé (os)', min: -99, max: 99, allowEmpty: true, placeholder: 'hérité',
        title: 'Vaut pour toutes les pièces de l\'os de cette pièce, dans cette frame. Vide = z-index de chaque pièce.',
        get: () => { const z = state.anim.frames[state.frame].z, b = state.rig.parts[part].bone; return z && z[b] != null ? z[b] : null; },
        set: (v) => editFrameZ(state.rig.parts[part].bone, v),
      }));
  }
  fields.push({ input: { set value(v) { const el = $('#insp-pixels'); if (el) el.textContent = v; } }, show: count });
  return out;
}

let shownStep = null;

function render() {
  const el = $('#inspector');
  shownStep = state.step;
  if (state.status !== 'ready') {
    fields = [];
    $('#stepcard').replaceChildren();
    return el.replaceChildren();
  }
  fields = [];
  mount($('#stepcard'), stepCard());
  let sel = state.selection;
  if (sel && !(sel.kind === 'bone' ? state.rig.bones[sel.id] : state.rig.parts[sel.id])) sel = null; // os ou pièce disparu entre-temps
  mount(el,
    h('h2', {}, 'Inspecteur'),
    !sel
      ? [h('p', { class: 'muted' }, 'Rien de sélectionné. Cliquez un pixel du sprite ou une ligne de la hiérarchie.'),
        info('Projet', state.name), info('Template', state.rig.template || '—'), info('Vue', (VIEWS.find((v) => v.id === state.rig.view) || {}).label || state.rig.view)]
      : sel.kind === 'bone' ? boneInspector(sel.id) : partInspector(sel.id));
}

function refresh() {
  refreshValues();
  const f = $('#insp-frame');
  if (f) f.textContent = state.frame + 1;
}

export function initInspector() {
  on('status project selection', render);
  on('view', () => {
    if (shownStep !== state.step) render();
  });
  // Pendant un scrub, reconstruire le panneau détruirait le libellé en cours de glisser.
  on('rig anim', () => (scrubbing ? refresh() : render()));
  on('frame', refresh);
  on('labels report preview', () => {
    if (state.status !== 'ready') return;
    if (state.step === 'rig' || state.step === 'export') mount($('#stepcard'), stepCard());
    refreshValues();
  });
  render();
}
