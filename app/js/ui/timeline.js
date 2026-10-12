// Bas : timeline (transport, bande de frames, durée / fps / nombre de frames, onion skin).

import { h, $, mount, icon } from '../dom.js';
import { state, on, emit, exec, setCmd, setFrame, setStep, setLayer, frameCount, totalDuration, isAnimStep, retime } from '../store.js';
import { hint, newAnimation, captureFrame, deleteFrame, toggleSwap } from '../edits.js';

let timer = 0;

function schedule() {
  clearTimeout(timer);
  if (!state.playing || !frameCount()) return;
  timer = setTimeout(() => {
    if (!state.playing) return;
    const n = frameCount();
    let next = state.frame + 1;
    if (next >= n) {
      if (!state.anim.loop) return setPlaying(false);
      next = 0;
    }
    setFrame(next);
    schedule();
  }, state.anim.frames[Math.min(state.frame, frameCount() - 1)].duration_ms);
}

function setPlaying(on_) {
  state.playing = on_;
  emit('view');
  schedule();
}

export function togglePlay() {
  if (state.status !== 'ready') return;
  if (!frameCount()) return hint('Aucune animation à lire : appliquez un preset à l\'étape Animer (touche 3).');
  if (!isAnimStep()) setStep('animate');
  if (!state.playing && !state.anim.loop && state.frame === frameCount() - 1) setFrame(0);
  setPlaying(!state.playing);
}

export function stepFrame(delta) {
  if (!frameCount()) return;
  if (state.playing) setPlaying(false);
  if (!isAnimStep()) setStep('animate');
  setFrame(state.frame + delta);
}

export function gotoFrame(i) {
  if (!frameCount()) return;
  if (state.playing) setPlaying(false);
  if (!isAnimStep()) setStep('animate');
  setFrame(i, { wrap: false });
}

const hasKey = (f, bone) => !!(f.bones && f.bones[bone]);
const retouches = (f) => (f.paint ? f.paint.length : 0);
const swapOn = (name) => ((state.anim.frames[state.frame] || {}).swap || []).includes(name);

/** Supprime la frame ; si le bouton se désactive (une seule frame restante), le focus passe à la frame courante. */
function removeFrame() {
  deleteFrame();
  const btn = $('[data-fid="tl-delete"]');
  if (btn && !btn.disabled) return;
  const cell = $(`#tl-strip [data-frame="${state.frame}"]`);
  if (cell) cell.focus();
}

function num(fid, label, value, { min, max, unit, title, onchange }) {
  const input = h('input', {
    type: 'number', class: 'num', id: 't-' + fid, 'data-fid': 't-' + fid, min, max, step: 1, value: String(value), title,
    onchange: () => {
      const v = Math.max(min, Math.min(max, parseInt(input.value, 10)));
      if (Number.isNaN(v)) return render();
      onchange(v);
    },
  });
  return h('span', { class: 'bar-field' }, h('label', { for: 't-' + fid }, label), input, unit && h('span', { class: 'unit' }, unit));
}

function render() {
  const el = $('#timeline');
  if (state.status !== 'ready') return el.replaceChildren();
  const n = frameCount();
  if (!n) {
    return mount(el, h('div', { class: 'tl-empty' },
      h('span', { class: 'muted' }, 'Aucune animation. '),
      h('button', { class: 'link', 'data-fid': 'tl-go', onclick: () => setStep('animate') }, 'Choisir un preset à l\'étape Animer'),
      h('span', { class: 'muted' }, ' ou '),
      h('button', { class: 'link', 'data-fid': 'tl-new', onclick: newAnimation }, 'créer une animation vide à poser à la main')));
  }
  const total = totalDuration();
  const cur = state.anim.frames[state.frame];
  const bone = state.selection && state.selection.kind === 'bone' ? state.selection.id : null;

  const transport = h('div', { class: 'tl-bar', role: 'toolbar', 'aria-label': 'Lecture' },
    h('button', { class: 'icon-btn', 'data-fid': 'tl-prev', 'aria-label': 'Frame précédente', title: 'Frame précédente (,)', onclick: () => stepFrame(-1) }, icon('prev')),
    h('button', { class: 'icon-btn primary', 'data-fid': 'tl-play', 'aria-label': state.playing ? 'Pause' : 'Lecture', title: 'Lecture / pause (Espace)', onclick: togglePlay }, icon(state.playing ? 'pause' : 'play')),
    h('button', { class: 'icon-btn', 'data-fid': 'tl-next', 'aria-label': 'Frame suivante', title: 'Frame suivante (.)', onclick: () => stepFrame(1) }, icon('next')),
    h('output', { class: 'tl-counter', id: 'tl-counter', 'aria-label': 'Frame courante' }, `${state.frame + 1} / ${n}`),
    h('button', {
      class: 'chip', 'data-fid': 'tl-loop', 'aria-pressed': String(!!state.anim.loop), title: 'L\'animation boucle (écrit dans anim.json)',
      onclick: () => exec(setCmd('anim', ['loop'], !state.anim.loop, state.anim.loop ? 'Désactiver la boucle' : 'Activer la boucle')),
    }, icon('loop'), 'Boucle'),
    h('button', { class: 'chip', 'data-fid': 'tl-onion', 'aria-pressed': String(!!state.layers.onion), title: 'Onion skin (O) : précédente en bleu, suivante en orange', onclick: () => setLayer('onion') }, 'Onion skin'),
    num('frame-ms', 'Durée de la frame', cur.duration_ms, {
      min: 1, max: 10000, unit: 'ms', title: 'Tenir cette frame plus ou moins longtemps',
      onchange: (v) => exec(setCmd('anim', ['frames', state.frame, 'duration_ms'], v, `Durée de la frame ${state.frame + 1}`)),
    }),
    h('button', { class: 'btn', 'data-fid': 'tl-capture', title: 'Capturer la pose (K) : garde cette frame et ouvre, juste après, une copie à modifier', onclick: captureFrame }, '+ Capturer la pose'),
    h('button', { class: 'btn', 'data-fid': 'tl-delete', disabled: n < 2, title: 'Supprimer la frame courante (annulable)', onclick: removeFrame }, 'Supprimer la frame'),
    // pièces de remplacement (rig.json « swaps ») : une image dessinée à la place de pièces, pour cette frame
    Object.keys(state.rig.swaps || {}).length > 0 && h('span', { class: 'bar-field tl-swaps', role: 'group', 'aria-label': 'Pièces de remplacement de la frame' }, 'Remplacement',
      Object.keys(state.rig.swaps).map((name) => h('button', {
        class: 'chip', 'data-fid': 'swap:' + name, 'data-swap': name, 'aria-pressed': String(swapOn(name)),
        title: `${name} : dans cette frame, dessiner l'image « ${state.rig.swaps[name].image} » à la place des pièces qu'elle remplace`,
        onclick: () => toggleSwap(name),
      }, h('span', { class: 'chip-text' }, name)))),
    h('span', { class: 'spacer' }),
    h('span', { class: 'tl-render', id: 'tl-render', role: 'status' }),
    num('frames', 'Frames', n, { min: 1, max: 64, title: '4 à 8 recommandé en pixel art. Garde la durée totale ; les frames deviennent de même durée.', onchange: (v) => retime({ frames: v }) }),
    num('fps', 'FPS', Math.round((n * 1000) / total), { min: 1, max: 60, title: 'Cadence moyenne. Garde le nombre de frames ; elles deviennent de même durée (1000 / fps).', onchange: (v) => retime({ frames: n, fps: v }) }),
    num('total', 'Durée', total, { min: n, max: 60000, unit: 'ms', title: 'Garde toutes les frames et leurs proportions (frames tenues comprises)', onchange: (v) => retime({ duration_ms: v }) }));

  const strip = h('div', { class: 'tl-strip', id: 'tl-strip', role: 'group', 'aria-label': `Frames de l'animation ${state.anim.name || ''}` },
    state.anim.frames.map((f, i) => h('button', {
      class: 'tl-frame' + (bone && hasKey(f, bone) ? ' keyed' : '') + (retouches(f) ? ' retouched' : ''), 'data-fid': 'frame:' + i, 'data-frame': i,
      title: retouches(f) ? `${retouches(f)} pixel(s) retouché(s) à la main` : null,
      'aria-current': i === state.frame ? 'true' : null, tabindex: i === state.frame ? '0' : '-1',
      'aria-label': `Frame ${i + 1}, ${f.duration_ms} millisecondes${bone && hasKey(f, bone) ? `, clé sur ${bone}` : ''}${retouches(f) ? `, ${retouches(f)} pixels retouchés` : ''}`,
      style: { flexGrow: String(f.duration_ms) },
      onclick: () => gotoFrame(i),
    }, h('span', { class: 'tl-num' }, i + 1), h('span', { class: 'tl-ms' }, f.duration_ms + ' ms'), h('span', { class: 'tl-key', 'aria-hidden': 'true' }), h('span', { class: 'tl-paint', 'aria-hidden': 'true' }))));
  strip.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const d = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (!d) return;
    e.preventDefault();
    stepFrame(d);
    const b = $(`#tl-strip [data-frame="${state.frame}"]`);
    if (b) b.focus();
  });

  mount(el, transport, strip,
    bone ? h('p', { class: 'tl-legend muted' }, h('span', { class: 'tl-key demo', 'aria-hidden': 'true' }), ` clé sur « ${bone} »`) : h('p', { class: 'tl-legend muted' }, 'Sélectionnez un os pour voir ses clés.'));
  renderProgress();
}

/** Mise à jour légère à chaque changement de frame (pas de reconstruction : la lecture reste fluide). */
function light() {
  if (state.status !== 'ready' || !frameCount()) return;
  const strip = $('#tl-strip');
  if (!strip || strip.children.length !== frameCount()) return render();
  [...strip.children].forEach((b, i) => {
    if (i === state.frame) b.setAttribute('aria-current', 'true');
    else b.removeAttribute('aria-current');
    b.tabIndex = i === state.frame ? 0 : -1;
  });
  $('#tl-counter').textContent = `${state.frame + 1} / ${frameCount()}`;
  document.querySelectorAll('#timeline [data-swap]').forEach((b) => b.setAttribute('aria-pressed', String(swapOn(b.dataset.swap))));
  const ms = $('#t-frame-ms');
  if (ms && document.activeElement !== ms) ms.value = state.anim.frames[state.frame].duration_ms;
}

function renderProgress() {
  const el = $('#tl-render');
  if (!el) return;
  const r = state.render;
  el.textContent = r.error ? 'Rendu impossible : ' + r.error : r.done < r.total ? `Rendu ${r.done} / ${r.total}…` : '';
  el.classList.toggle('danger', !!r.error);
}

export function initTimeline() {
  on('status project anim rig selection', render);
  let key = '';
  on('view', () => {
    const k = `${state.playing}:${state.layers.onion}`;
    if (k !== key) {
      key = k;
      render();
    }
  });
  on('frame', light);
  on('preview', renderProgress);
  on('anim', schedule);
  render();
}
