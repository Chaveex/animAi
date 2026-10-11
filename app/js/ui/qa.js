// Panneau droit (bas) : rapport QA cliquable + historique des modifications (vous / Claude).

import { h, $, mount, fmtTime } from '../dom.js';
import { state, on, emit, setStep, setFrame, setLayer, refreshReport, history, travelTo, frameCount, unassignedCount } from '../store.js';
import { getFrame } from '../preview.js';
import { focusOn } from '../viewport.js';

const CHECKS = {
  parts_assigned: 'Pixels assignés à une pièce',
  holes: 'Trous dans la silhouette',
  palette: 'Palette préservée',
  alpha_binary: 'Alpha binaire (0 ou 255)',
  orphans: 'Pixels orphelins',
  pivot_stable: 'Pivot stable',
  canvas_constant: 'Canvas constant',
  loop_closed: 'Boucle fermée',
};

/**
 * Pixels fautifs d'une entrée, en coordonnées SPRITE (le repère du viewport).
 * `pixels` (serveur) est déjà en coordonnées sprite. `pixel` seul (report.json de la CLI) est en
 * coordonnées canvas pour une entrée liée à une frame : on retranche l'origine du canvas.
 */
function pixelsOf(c) {
  if (Array.isArray(c.pixels) && c.pixels.length) return c.pixels;
  if (!c.pixel) return [];
  if (c.frame == null) return [c.pixel];
  const entry = getFrame(c.frame) || getFrame(0);
  return entry ? [[c.pixel[0] - entry.origin[0], c.pixel[1] - entry.origin[1]]] : [c.pixel];
}

/** Saute à la frame et au pixel fautifs, et les surligne dans le viewport. */
export function locate(check) {
  const pixels = pixelsOf(check);
  // Sans animation, le rapport porte sur la pose de repos (« frame 0 ») : on reste sur le sprite.
  const rest = check.frame != null && !frameCount();
  state.qaFocus = { id: check.id, frame: check.frame, pixels, rest };
  if (rest) {
    if (state.step !== 'rig') setStep('rig');
  } else if (check.frame != null) {
    if (state.step !== 'animate') setStep('animate');
    state.playing = false;
    setFrame(check.frame, { wrap: false });
  } else if (check.id === 'parts_assigned') {
    setStep('rig');
    setLayer('labelmap', true);
  }
  focusOn(pixels);
  emit('qa');
  const where = (check.frame != null && !rest ? `frame ${check.frame + 1}, ` : '') + (pixels.length ? `pixel x ${pixels[0][0]}, y ${pixels[0][1]}` : '');
  emit('announce', `${CHECKS[check.id] || check.id} : ${check.detail}. ${where}`);
}

export function locateCheck(id) {
  const c = state.report && state.report.checks.find((k) => k.id === id && k.pass === false);
  if (c) locate(c);
  return !!c;
}

/**
 * Montre les pixels non assignés. Passe par le rapport QA quand il existe ; sinon (rapport
 * indisponible, par exemple tant qu'aucune pièce n'a de pixels) lit la label map déjà affichée.
 */
export function locateUnassigned() {
  if (locateCheck('parts_assigned')) return;
  const w = state.sprite.width, d = state.sprite.data, pixels = [];
  for (let i = 0; i < state.labels.length && pixels.length < 500; i++) {
    if (d[i * 4 + 3] && state.labels[i] < 0) pixels.push([i % w, Math.floor(i / w)]);
  }
  if (pixels.length) locate({ id: 'parts_assigned', pass: false, frame: null, detail: `${pixels.length} pixels non assignés`, pixels });
}

export function clearQaFocus() {
  if (!state.qaFocus) return false;
  state.qaFocus = null;
  emit('qa');
  return true;
}

function renderQa() {
  const el = $('#qa');
  if (state.status !== 'ready') return el.replaceChildren();
  const head = (summary) => h('div', { class: 'panel-head' }, h('h2', {}, 'QA'), h('span', { class: 'muted' }, summary),
    h('button', { class: 'btn small', 'data-fid': 'qa-refresh', title: 'Relancer la validation', onclick: refreshReport }, 'Relancer'));
  if (state.reportError) {
    const nothing = unassignedCount() > 0 && !state.labels.some((v) => v >= 0);
    return mount(el, head(''),
      nothing
        ? h('p', { class: 'note warn' }, 'Le rapport QA sera disponible dès qu\'une pièce aura des pixels. Commencez par assigner des pixels à l\'étape Rigger.')
        : h('p', { class: 'note danger' }, 'Validation impossible. ', h('span', { lang: 'en' }, state.reportError)));
  }
  if (!state.report) return mount(el, head(''), h('p', { class: 'muted' }, 'Validation en cours…'));

  const rank = (c) => (c.pass === false ? 0 : c.pass == null ? 1 : 2);
  const checks = [...state.report.checks].sort((a, b) => rank(a) - rank(b));
  const fails = checks.filter((c) => c.pass === false).length;
  const unknown = checks.filter((c) => c.pass == null).length;
  const summary = `${fails} échec${fails > 1 ? 's' : ''} · ${checks.length - fails - unknown} OK${unknown ? ` · ${unknown} non vérifié${unknown > 1 ? 's' : ''}` : ''}`;

  mount(el, head(summary), h('ul', { class: 'qa-list' }, checks.map((c, i) => {
    const status = c.pass === false ? ['fail', '✕', 'Échec'] : c.pass == null ? ['unknown', '?', 'Non vérifié'] : ['pass', '✓', 'OK'];
    const px = pixelsOf(c);
    const focused = state.qaFocus && state.qaFocus.id === c.id && state.qaFocus.frame === c.frame;
    const meta = [c.frame != null ? (frameCount() ? `frame ${c.frame + 1}` : 'pose de repos') : null, c.detail || null, px.length ? `x ${px[0][0]}, y ${px[0][1]}` : null].filter(Boolean);
    const content = [
      h('span', { class: 'qa-status qa-' + status[0], 'aria-hidden': 'true' }, status[1]),
      h('span', { class: 'qa-body' },
        h('span', { class: 'qa-label' }, CHECKS[c.id] || c.id),
        // `detail` est le message du moteur, cité tel quel (en anglais)
        h('span', { class: 'qa-detail', lang: c.detail ? 'en' : null }, h('span', { class: 'qa-word qa-' + status[0], lang: 'fr' }, status[2]), meta.length ? ' · ' + meta.join(' · ') : '')),
      c.pass === false && px.length ? h('span', { class: 'qa-go' }, 'Voir →') : null,
    ];
    return h('li', {}, c.pass === false && px.length
      ? h('button', { class: 'qa-row' + (focused ? ' focused' : ''), 'data-fid': `qa:${c.id}:${c.frame}:${i}`, 'aria-pressed': String(!!focused), onclick: () => locate(c) }, content)
      : h('div', { class: 'qa-row' }, content));
  })));
}

function renderHistory() {
  const el = $('#history');
  if (state.status === 'loading') return;
  const all = history();
  const items = all.map((e, i) => ({ ...e, index: i })).slice(-40).reverse();
  mount(el,
    h('div', { class: 'panel-head' }, h('h2', {}, 'Historique'), h('span', { class: 'muted' }, `${all.filter((e) => e.done).length} action${all.length > 1 ? 's' : ''}`)),
    items.length
      ? h('ul', { class: 'history-list' }, items.map((e) => h('li', {},
        h('button', {
          class: 'history-row' + (e.done ? '' : ' undone'), 'data-fid': 'hist:' + e.index,
          title: e.done ? 'Revenir juste après cette action' : 'Rétablir jusqu\'à cette action',
          onclick: () => travelTo(e.index),
        },
        h('span', { class: 'author author-' + e.author, title: e.author === 'tab' ? 'Autre fenêtre de l\'éditeur' : null }, e.author === 'claude' ? 'Claude' : e.author === 'tab' ? 'Autre' : 'Vous'),
        h('span', { class: 'history-label' }, e.label, e.done ? '' : ' (annulé)'),
        h('time', { class: 'muted' }, fmtTime(e.at))))),
      h('li', {}, h('button', { class: 'history-row', 'data-fid': 'hist:-1', onclick: () => travelTo(-1) }, h('span', { class: 'history-label' }, 'État initial'))))
      : h('p', { class: 'muted' }, 'Aucune modification pour l\'instant. Les vôtres et celles de Claude apparaîtront ici.'));
}

export function initQa() {
  on('status report qa', renderQa);
  on('status history', renderHistory);
  renderQa();
  renderHistory();
}
