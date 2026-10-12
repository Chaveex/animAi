// Infobulles : une seule bulle pour toute l'app, à la place des infobulles natives (lentes, jamais
// affichées au clavier, sans les raccourcis). Elle montre ce que fait le contrôle et, s'il en a un,
// le raccourci qui fait la même chose (table unique de shortcuts.js).
//
// Aucun contrôle n'a à s'y brancher : le texte est celui de son attribut `title`, repris au survol ou
// au focus ; le raccourci est retrouvé par son `data-fid`.

import { h } from './dom.js';
import { tipKeys } from './shortcuts.js';

const DELAY = 450; // survol avant affichage, en ms ; nul quand une bulle est déjà affichée
const GAP = 6;
const SKIP = 'canvas, #help, #help *';
const ON_FOCUS = 'button, summary, a, [role="treeitem"], [role="button"]'; // pas les champs : la bulle gênerait la saisie

let bubble = null;
let anchor = null;
let timer = 0;
let watch = 0;

/** Reprend le `title` natif du contrôle : il devient le texte de la bulle, et reste lisible par un lecteur d'écran. */
function adopt(el) {
  if (!el.hasAttribute('title')) return;
  const text = el.getAttribute('title');
  el.removeAttribute('title');
  if (!text) return;
  el.dataset.tip = text;
  const named = el.getAttribute('aria-label') || el.textContent.trim() || (el.labels && el.labels.length);
  if (!named) el.setAttribute('aria-label', text);
  else if (!el.hasAttribute('aria-description')) el.setAttribute('aria-description', text);
}

/** Contrôle le plus proche qui a quelque chose à dire, avec son contenu : { el, text, keys }. */
function tipOf(target) {
  for (let el = target instanceof Element ? target.closest('[title], [data-tip], [data-fid]') : null; el; el = el.parentElement && el.parentElement.closest('[title], [data-tip], [data-fid]')) {
    if (el.matches(SKIP) || el.disabled) return null;
    adopt(el);
    const keys = el.dataset.fid ? tipKeys(el.dataset.fid) : null;
    // le raccourci a sa pastille : on le retire de la phrase si elle le citait entre parenthèses
    const text = (el.dataset.tip || '').replace(keys ? ` (${keys})` : '\u0000', '').trim();
    if (text || keys) return { el, text: text || el.getAttribute('aria-label') || el.textContent.trim(), keys };
  }
  return null;
}

function place(el) {
  bubble.style.left = bubble.style.top = '0px'; // mesurée à l'origine : près du bord droit elle serait comprimée
  const a = el.getBoundingClientRect(), b = bubble.getBoundingClientRect();
  const vw = document.documentElement.clientWidth, vh = document.documentElement.clientHeight;
  let x, y;
  if (el.closest('#toolrail')) { // rail vertical : à droite de l'outil
    x = a.right + GAP;
    y = a.top + (a.height - b.height) / 2;
  } else {
    x = a.left + (a.width - b.width) / 2;
    y = a.bottom + GAP;
    if (y + b.height > vh - 4) y = a.top - GAP - b.height;
  }
  bubble.style.left = Math.round(Math.max(4, Math.min(vw - b.width - 4, x))) + 'px';
  bubble.style.top = Math.round(Math.max(4, Math.min(vh - b.height - 4, y))) + 'px';
}

function show(tip) {
  clearTimeout(timer);
  if (!tip.el.isConnected) return hide();
  anchor = tip.el;
  bubble.replaceChildren(h('span', {}, tip.text), tip.keys && h('kbd', {}, tip.keys) || '');
  bubble.hidden = false;
  place(tip.el);
  clearInterval(watch);
  watch = setInterval(() => anchor && !anchor.isConnected && hide(), 250); // contrôle reconstruit sous la bulle
}

function hide() {
  clearTimeout(timer);
  clearInterval(watch);
  anchor = null;
  if (bubble) bubble.hidden = true;
}

function onOver(e) {
  if (e.pointerType !== 'mouse') return;
  const tip = tipOf(e.target);
  if (!tip) return hide();
  if (tip.el === anchor) return;
  const warm = !bubble.hidden;
  clearTimeout(timer);
  if (warm) return show(tip);
  anchor = tip.el; // en attente : un second survol du même contrôle ne relance pas le délai
  timer = setTimeout(() => show(tip), DELAY);
}

function onFocus(e) {
  const el = e.target;
  if (!(el instanceof Element) || !el.matches(ON_FOCUS) || !el.matches(':focus-visible')) return;
  const tip = tipOf(el);
  if (tip && tip.el === el) show(tip);
}

export function initTooltips() {
  bubble = h('div', { class: 'tip', id: 'tip', role: 'tooltip', hidden: true });
  document.body.append(bubble);
  document.addEventListener('pointerover', onOver);
  document.addEventListener('pointerleave', hide);
  document.addEventListener('focusin', onFocus);
  document.addEventListener('focusout', hide);
  // tout geste ferme la bulle : elle ne doit jamais recouvrir ce qu'on est en train de faire
  for (const type of ['pointerdown', 'keydown', 'wheel']) document.addEventListener(type, hide, { capture: true, passive: true });
  document.addEventListener('scroll', hide, { capture: true, passive: true });
  window.addEventListener('blur', hide);
}
