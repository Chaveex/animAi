// Petits utilitaires DOM (aucune dépendance).

export const $ = (sel, root = document) => root.querySelector(sel);

/** h('button', { class: 'btn', onclick: fn, 'aria-label': '…' }, 'texte', autreNoeud) */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'value') el.value = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** Remplace le contenu d'un conteneur en conservant le focus (repéré par data-fid). */
export function mount(container, ...nodes) {
  const active = document.activeElement;
  const fid = active && container.contains(active) ? active.dataset.fid : null;
  container.replaceChildren(...nodes.flat(Infinity).filter(Boolean));
  if (fid) {
    const again = container.querySelector(`[data-fid="${CSS.escape(fid)}"]`);
    if (again) again.focus({ preventScroll: true });
  }
}

const ICONS = {
  select: '<path d="M3 2l9 5-4 1.2L6.8 12z"/>',
  brush: '<path d="M10.5 2.5l3 3-6 6-3-3zM3.5 9.5l3 3c-1 1.5-3 1.5-4.5 1 1-.8 1-2.5 1.5-4z"/>',
  eraser: '<path d="M9 2.5l4.5 4.5-6 6H4L2 11zM2.5 14h11v1h-11z" fill-rule="evenodd"/>',
  joint: '<path d="M8 1l2.5 3H9v3h3V5.5L15 8l-3 2.5V9H9v3h1.5L8 15l-2.5-3H7V9H4v1.5L1 8l3-2.5V7h3V4H5.5z"/>',
  eye: '<path d="M8 3.5C4.5 3.5 2 6.5 1 8c1 1.5 3.5 4.5 7 4.5s6-3 7-4.5c-1-1.5-3.500-4.500-7-4.500zm0 7a2.500 2.500 0 110-5 2.500 2.500 0 010 5z"/>',
  eyeOff: '<path d="M2 2.700l11.300 11.300.900-.900L2.900 1.800zM8 12.500c-3.500 0-6-3-7-4.500.500-.800 1.400-1.900 2.600-2.800l1.900 1.900a2.500 2.500 0 003.400 3.400l1.400 1.400c-.700.400-1.500.600-2.300.600zm7-4.500c-.400.600-1 1.400-1.800 2.200L6.900 3.600c.400-.100.700-.100 1.100-.100 3.500 0 6 3 7 4.500z"/>',
  play: '<path d="M4 2.500v11l9-5.500z"/>',
  pause: '<path d="M4 2.500h3v11H4zM9 2.500h3v11H9z"/>',
  prev: '<path d="M3 3h2v10H3zM13 3v10L6 8z"/>',
  next: '<path d="M11 3h2v10h-2zM3 3v10l7-5z"/>',
  loop: '<path d="M4 4h7V2l3 3-3 3V6H5v2H3V5a1 1 0 011-1zM12 12H5v2l-3-3 3-3v2h6V8h2v3a1 1 0 01-1 1z"/>',
  undo: '<path d="M6 3L2 7l4 4V8.500h3.500a2.500 2.500 0 010 5H6V15h3.500a4 4 0 000-8H6z"/>',
  redo: '<path d="M10 3l4 4-4 4V8.500H6.500a2.500 2.500 0 000 5H10V15H6.500a4 4 0 010-8H10z"/>',
  theme: '<path d="M8 1a7 7 0 100 14A7 7 0 008 1zm0 1.500v11a5.500 5.500 0 010-11z"/>',
  help: '<path d="M8 1a7 7 0 100 14A7 7 0 008 1zm-.800 9.200h1.600v1.600H7.200zM8 4c1.600 0 2.700 1 2.700 2.300 0 1-.600 1.600-1.300 2-.500.300-.700.600-.700 1.100H7.200c0-1 .500-1.600 1.200-2 .500-.300.800-.600.800-1 0-.500-.500-.900-1.200-.900-.700 0-1.200.400-1.300 1.100H5.200C5.300 5 6.400 4 8 4z"/>',
  chevron: '<path d="M5 3l5 5-5 5z"/>',
};

export function icon(name) {
  return h('span', { class: 'icon', 'aria-hidden': 'true', html: `<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor">${ICONS[name] || ''}</svg>` });
}

export const fmtTime = (ms) => new Date(ms).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
