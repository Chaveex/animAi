// Panneau gauche : arbre des os et de leurs pièces (sélection, visibilité, navigation clavier).

import { h, $, mount, icon } from '../dom.js';
import { state, on, setSelection, partsOfBone } from '../store.js';
import { toggleVisibility, addBone, addPart, deleteBone, hint } from '../edits.js';
import { labelStyle, swatchCss } from '../label-palette.js';

const collapsed = new Set();
let rows = []; // lignes visibles, dans l'ordre d'affichage

function buildRows() {
  rows = [];
  if (!state.rig) return;
  const bones = state.rig.bones;
  const children = (parent) => Object.keys(bones).filter((b) => (bones[b].parent || null) === parent || (parent === null && bones[b].parent && !bones[bones[b].parent]));
  const ikBones = new Set(Object.values(state.rig.ik || {}).flatMap((c) => [...(c.chain || []), c.target_bone]));
  const walk = (bone, level, parentKey) => {
    const kids = children(bone), parts = partsOfBone(bone);
    const key = 'bone:' + bone;
    rows.push({ key, kind: 'bone', id: bone, level, parentKey, expandable: kids.length + parts.length > 0, ik: ikBones.has(bone) });
    if (collapsed.has(key)) return;
    for (const p of parts) rows.push({ key: 'part:' + p, kind: 'part', id: p, level: level + 1, parentKey: key });
    for (const k of kids) walk(k, level + 1, key);
  };
  for (const root of children(null)) walk(root, 1, null);
  // pièces dont l'os n'existe pas (rig incohérent) : visibles plutôt que perdues
  for (const p of state.partNames) {
    if (!bones[state.rig.parts[p].bone]) rows.push({ key: 'part:' + p, kind: 'part', id: p, level: 1, parentKey: null, orphan: true });
  }
}

const isSelected = (r) => state.selection && state.selection.kind === r.kind && state.selection.id === r.id;

function render() {
  const el = $('#tree');
  if (state.status !== 'ready') return el.replaceChildren();
  buildRows();
  const anySelected = rows.some(isSelected);
  $('#tree-count').textContent = `${Object.keys(state.rig.bones).length} os · ${state.partNames.length} pièces`;
  mount($('#tree-actions'),
    h('button', { class: 'btn small', 'data-fid': 'add-bone', title: 'Ajouter un pivot (os), enfant de l\'os sélectionné. Aussi : double-clic dans le viewport avec l\'outil Déplacer.', onclick: () => addBone() }, '+ Pivot'),
    h('button', { class: 'btn small', 'data-fid': 'add-part', title: 'Ajouter une pièce vide sur l\'os sélectionné, à peindre au pinceau', onclick: () => addPart() }, '+ Pièce'));
  mount(el, rows.map((r, i) => {
    const selected = isSelected(r);
    const hidden = (r.kind === 'bone' ? state.hiddenBones : state.hiddenParts).has(r.id);
    const eye = h('button', {
      class: 'eye', tabindex: '-1', 'aria-pressed': String(hidden),
      'aria-label': `${hidden ? 'Afficher' : 'Masquer'} ${r.id}`, title: `${hidden ? 'Afficher' : 'Masquer'} (H)`,
      onclick: (e) => { e.stopPropagation(); toggleVisibility({ kind: r.kind, id: r.id }); },
    }, icon(hidden ? 'eyeOff' : 'eye'));
    let body;
    if (r.kind === 'bone') {
      body = [
        h('span', { class: 'twisty' + (r.expandable ? '' : ' leaf') + (collapsed.has(r.key) ? '' : ' open'), 'aria-hidden': 'true', onclick: (e) => { e.stopPropagation(); toggle(r); } }, r.expandable ? icon('chevron') : null),
        h('span', { class: 'bone-glyph', 'aria-hidden': 'true' }),
        h('span', { class: 'row-name' }, r.id),
        r.ik && h('span', { class: 'tag', title: 'Os piloté par une chaîne IK' }, 'IK'),
      ];
    } else {
      const k = state.partNames.indexOf(r.id), st = labelStyle(k);
      body = [
        h('span', { class: 'twisty leaf', 'aria-hidden': 'true' }),
        h('span', { class: 'swatch', style: { background: swatchCss(st) }, title: `Pièce ${st.number} : ${st.colorName}, motif ${st.patternName}` }, h('span', {}, st.number)),
        h('span', { class: 'row-name' }, r.id),
        r.orphan && h('span', { class: 'tag warn', title: 'L\'os de cette pièce n\'existe pas dans le rig' }, 'os ?'),
        h('span', { class: 'row-meta', title: 'z-index' }, 'z ' + (state.rig.parts[r.id].z || 0)),
      ];
    }
    return h('div', {
      class: 'tree-row' + (selected ? ' selected' : '') + (hidden ? ' is-hidden' : ''),
      role: 'treeitem', 'data-fid': r.key, 'data-index': i,
      'aria-level': r.level, 'aria-selected': String(selected),
      'aria-expanded': r.kind === 'bone' && r.expandable ? String(!collapsed.has(r.key)) : null,
      'aria-label': r.kind === 'bone' ? `Os ${r.id}${hidden ? ', masqué' : ''}` : `Pièce ${state.partNames.indexOf(r.id) + 1}, ${r.id}${hidden ? ', masquée' : ''}`,
      tabindex: selected || (!anySelected && i === 0) ? '0' : '-1',
      style: { paddingLeft: 4 + (r.level - 1) * 12 + 'px' },
      onclick: () => select(r),
      ondblclick: () => r.kind === 'bone' && focusRename(),
    }, body, eye);
  }));
}

function select(r) {
  setSelection({ kind: r.kind, id: r.id });
  focusRow(r.key);
}

function focusRow(key) {
  const el = $(`#tree [data-fid="${CSS.escape(key)}"]`);
  if (el) el.focus();
}

/** Renommer : le champ « Nom » de l'inspecteur (une seule façon de saisir un nom, annulable). */
function focusRename() {
  const input = $('#f-bone-name');
  if (!input) return;
  input.focus();
  input.select();
}

function toggle(r) {
  if (collapsed.has(r.key)) collapsed.delete(r.key);
  else collapsed.add(r.key);
  render();
}

function onKey(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const cur = e.target.closest('[role="treeitem"]');
  if (!cur) return;
  const i = Number(cur.dataset.index), r = rows[i];
  let to = null;
  switch (e.key) {
    case 'ArrowDown': to = rows[i + 1]; break;
    case 'ArrowUp': to = rows[i - 1]; break;
    case 'Home': to = rows[0]; break;
    case 'End': to = rows[rows.length - 1]; break;
    case 'ArrowRight':
      if (r.kind === 'bone' && r.expandable && collapsed.has(r.key)) toggle(r);
      else if (rows[i + 1] && rows[i + 1].parentKey === r.key) to = rows[i + 1];
      break;
    case 'ArrowLeft':
      if (r.kind === 'bone' && r.expandable && !collapsed.has(r.key)) toggle(r);
      else to = rows.find((x) => x.key === r.parentKey);
      break;
    case 'Enter':
    case ' ':
      to = r;
      break;
    case 'F2':
      if (r.kind !== 'bone') return;
      e.preventDefault();
      select(r);
      return focusRename();
    case 'Delete': {
      if (r.kind !== 'bone') return;
      e.preventDefault();
      const err = deleteBone(r.id);
      if (err) hint(err);
      return;
    }
    default: return;
  }
  e.preventDefault();
  if (to) select(to);
  else focusRow(r.key);
}

export function initHierarchy() {
  $('#tree').addEventListener('keydown', onKey);
  on('status', () => state.status !== 'ready' && $('#tree-actions').replaceChildren());
  on('status project rig selection visibility', render);
  render();
}
