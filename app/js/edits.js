// Éditions de haut niveau partagées par le viewport, l'inspecteur et les raccourcis.
// Chacune passe par une commande annulable du store.

import { state, exec, setCmd, editCmd, frameCount, setView, setLayer, setStep, isAnimStep, emit, handRegionParts, partsOfBone } from './store.js';

const clone = (v) => JSON.parse(JSON.stringify(v));

export function hint(message) {
  emit('hint', message);
}

/** Déplace le joint d'un os (pose de repos), borné au sprite, au pixel entier. */
export function moveJoint(bone, [x, y], merge = false) {
  const { width, height } = state.sprite;
  const to = [Math.max(0, Math.min(width - 1, Math.round(x))), Math.max(0, Math.min(height - 1, Math.round(y)))];
  exec(setCmd('rig', ['bones', bone, 'joint'], to, `Déplacer le joint « ${bone} »`, merge ? 'joint:' + bone : null));
}

/** Clé de l'os dans la frame courante : { rot, pos } (valeurs par défaut 0). */
export function boneKey(bone, frame = state.frame) {
  const f = state.anim && state.anim.frames[frame];
  const k = (f && f.bones && f.bones[bone]) || {};
  return { rot: k.rot || 0, pos: k.pos ? [...k.pos] : [0, 0] };
}

/** Modifie la clé d'un os dans la frame courante. Les valeurs neutres sont retirées du JSON. */
export function editBoneKey(bone, patch, merge = false) {
  if (!frameCount()) return;
  const frame = state.frame;
  const bones = clone(state.anim.frames[frame].bones || {});
  const k = { ...boneKey(bone), ...patch };
  const out = {};
  if (k.rot) out.rot = Math.round(k.rot);
  if (k.pos[0] || k.pos[1]) out.pos = [Math.round(k.pos[0]), Math.round(k.pos[1])];
  if (Object.keys(out).length) bones[bone] = out;
  else delete bones[bone];
  exec(setCmd('anim', ['frames', frame, 'bones'], bones, `Poser « ${bone} » (frame ${frame + 1})`, merge ? `key:${bone}:${frame}` : null));
  const n = (state.anim.frames[frame].paint || []).length;
  if (n) hint(`Cette frame porte ${n} pixel${n > 1 ? 's' : ''} de retouche : ils restent à leur place quand la pose change. Vérifiez-les, ou effacez-les (outil Retouche).`);
}

// --- Retouche par frame : pixels peints ou effacés à la main, écrits dans anim.json ---------

/**
 * Applique un trait de retouche à la frame courante. `changes` : Map « x,y » (pixels du sprite) ->
 * '#rrggbb' (peindre), null (rendre transparent) ou 'restore' (retirer la retouche de ce pixel).
 */
export function applyRetouch(changes) {
  if (!frameCount() || !changes.size) return;
  const frame = state.frame;
  const map = new Map((state.anim.frames[frame].paint || []).map(([x, y, c]) => [`${x},${y}`, c]));
  for (const [key, value] of changes) {
    if (value === 'restore') map.delete(key);
    else map.set(key, value);
  }
  const list = [...map].map(([key, c]) => [...key.split(',').map(Number), c]);
  const n = changes.size, pl = n > 1 ? 's' : '';
  exec(setCmd('anim', ['frames', frame, 'paint'], list.length ? list : undefined, `Retouche : ${n} pixel${pl} (frame ${frame + 1})`));
}

/** Active ou retire, dans la frame courante, une pièce de remplacement définie dans rig.json (`swaps`). */
export function toggleSwap(name) {
  if (!frameCount()) return;
  const frame = state.frame, cur = state.anim.frames[frame].swap || [];
  const on = cur.includes(name);
  const list = on ? cur.filter((n) => n !== name) : [...cur, name];
  exec(setCmd('anim', ['frames', frame, 'swap'], list.length ? list : undefined, `${on ? 'Retirer' : 'Utiliser'} le remplacement « ${name} » (frame ${frame + 1})`));
  const spec = (state.rig.swaps || {})[name] || {};
  if (!on) hint(`« ${name} » remplace ${(spec.hides || []).join(', ') || 'les pièces de ' + spec.bone} dans cette frame. L'image suit l'os « ${spec.bone} ».`);
}

/** Pièces qu'un remplacement cache : sa liste `hides`, sinon toutes les pièces de son os (règle du cœur). */
export function swapHides(name) {
  const spec = (state.rig.swaps || {})[name] || {};
  return spec.hides && spec.hides.length ? [...spec.hides] : partsOfBone(spec.bone);
}

/**
 * Déclare un remplacement dans rig.json. `image` = chemin rendu par le serveur, `size` = { width, height }.
 * Os : celui de la sélection ; pièces remplacées : celles de cet os et de ses descendants (un bras entier).
 * Renvoie un message d'erreur ou null.
 */
export function addSwap(name, image, size) {
  const bones = state.rig.bones;
  const carries = (b) => partsOfBone(b).length > 0;
  let bone = anchorBone();
  if (!carries(bone)) bone = Object.keys(bones).find(carries);
  if (!bone) return 'Aucune pièce à remplacer : créez d\'abord une pièce à l\'étape Rigger.';
  const root = !bones[bone].parent || !bones[bones[bone].parent];
  const hides = (root ? [bone] : boneSubtree(bone)).flatMap(partsOfBone);
  exec(editCmd(`Ajouter le remplacement « ${name} » (os « ${bone} »)`, (d) => {
    d.rig.swaps = { ...(d.rig.swaps || {}), [name]: { image, bone, anchor: [size.width >> 1, size.height >> 1], hides } };
  }));
  hint(`Remplacement « ${name} » ajouté sur « ${bone} ». Cliquez dans l'image le pixel qui se pose sur le joint, puis activez-le dans une frame (étape Animer).`);
  return null;
}

/** Modifie un champ d'un remplacement (`undefined` retire le champ). */
export function editSwap(name, key, value, label, merge = false) {
  exec(setCmd('rig', ['swaps', name, key], value, `${label} du remplacement « ${name} »`, merge ? `swap:${name}:${key}` : null));
}

/** Coche ou décoche une pièce remplacée. Un remplacement remplace toujours au moins une pièce. */
export function toggleSwapHide(name, part) {
  const cur = swapHides(name);
  const list = cur.includes(part) ? cur.filter((p) => p !== part) : state.partNames.filter((p) => p === part || cur.includes(p));
  if (!list.length) return hint('Un remplacement remplace au moins une pièce : cochez-en une autre avant de retirer celle-ci.');
  editSwap(name, 'hides', list, 'Pièces remplacées');
}

/** Renomme un remplacement, dans rig.json et dans les frames qui l'utilisent. Renvoie un message d'erreur ou null. */
export function renameSwap(name, to) {
  to = String(to || '').trim();
  if (to === name) return null;
  const err = nameError(to, Object.keys(state.rig.swaps || {}));
  if (err) return err;
  exec(editCmd(`Renommer le remplacement « ${name} » en « ${to} »`, (d) => {
    d.rig.swaps = renameKey(d.rig.swaps, name, to);
    for (const f of (d.anim && d.anim.frames) || []) if (f.swap) f.swap = f.swap.map((n) => (n === name ? to : n));
  }));
  return null;
}

/**
 * Retire un remplacement de rig.json et de toutes les frames. Le serveur range alors son image hors de
 * `swaps/` (dans `.animai/trash/`) si plus aucun remplacement ne la cite, et la remet en place à l'annulation.
 */
export function deleteSwap(name) {
  if (!(state.rig.swaps || {})[name]) return;
  let used = 0;
  exec(editCmd(`Supprimer le remplacement « ${name} »`, (d) => {
    delete d.rig.swaps[name];
    if (!Object.keys(d.rig.swaps).length) delete d.rig.swaps;
    for (const f of (d.anim && d.anim.frames) || []) {
      if (!f.swap || !f.swap.includes(name)) continue;
      used++;
      f.swap = f.swap.filter((n) => n !== name);
      if (!f.swap.length) delete f.swap;
    }
  }));
  hint(`Remplacement « ${name} » supprimé${used ? ` (retiré de ${used} frame${used > 1 ? 's' : ''})` : ''}. Son image quitte le dossier swaps/. Ctrl+Z pour annuler : elle revient.`);
}

/** Retire toutes les retouches de la frame courante. */
export function clearRetouch() {
  if (!frameCount()) return;
  const frame = state.frame, n = (state.anim.frames[frame].paint || []).length;
  if (!n) return hint('Cette frame n\'a aucune retouche.');
  exec(setCmd('anim', ['frames', frame, 'paint'], undefined, `Effacer les ${n} retouches de la frame ${frame + 1}`));
}

/**
 * Override de z dans la frame courante (null = retirer l'override).
 * La clé de `frames[i].z` est un nom d'OS : la valeur vaut pour toutes les pièces de cet os.
 */
export function editFrameZ(bone, z) {
  if (!frameCount()) return;
  const frame = state.frame;
  const map = clone(state.anim.frames[frame].z || {});
  if (z == null || Number.isNaN(z)) delete map[bone];
  else map[bone] = Math.round(z);
  exec(setCmd('anim', ['frames', frame, 'z'], Object.keys(map).length ? map : undefined, `Z de l'os « ${bone} » (frame ${frame + 1})`));
}

// --- Pivots (os) : ajouter, renommer, supprimer, re-parenter -----------------------------

const NAME_RE = /^[A-Za-z][A-Za-z0-9_-]*$/;

/** Message d'erreur si `name` ne peut pas nommer un nouvel élément parmi `taken`, sinon null. */
export function nameError(name, taken) {
  if (!name) return 'Le nom ne peut pas être vide.';
  if (!NAME_RE.test(name)) return 'Nom invalide : une lettre, puis lettres, chiffres, « _ » ou « - » (pas d\'espace ni d\'accent).';
  if (taken.includes(name)) return `« ${name} » existe déjà.`;
  return null;
}

function freeName(base, taken) {
  for (let i = 1; ; i++) if (!taken.includes(`${base}_${i}`)) return `${base}_${i}`;
}

const isLockedBone = (bone) => bone === 'hips' && (state.rig.template || 'humanoid') === 'humanoid';

/** Os descendants de `bone` (lui compris). */
export function boneSubtree(bone, bones = state.rig.bones) {
  const out = [bone];
  for (let i = 0; i < out.length; i++) for (const b of Object.keys(bones)) if (bones[b].parent === out[i]) out.push(b);
  return out;
}

/** Os visé par une création : l'os sélectionné, celui de la pièce sélectionnée, sinon la racine. */
function anchorBone() {
  const s = state.selection, bones = state.rig.bones;
  if (s && s.kind === 'bone' && bones[s.id]) return s.id;
  if (s && s.kind === 'part' && state.rig.parts[s.id] && bones[state.rig.parts[s.id].bone]) return state.rig.parts[s.id].bone;
  return Object.keys(bones).find((b) => !bones[b].parent) || Object.keys(bones)[0];
}

/** Ajoute un pivot, enfant de l'os visé. `at` = [x, y] en pixels du sprite (défaut : près du parent). */
export function addBone(at = null) {
  if (state.status !== 'ready') return null;
  const { width, height } = state.sprite;
  const parent = anchorBone();
  const [px, py] = state.rig.bones[parent].joint;
  const p = at || [px + 4 > width - 1 ? px - 4 : px + 4, py + 4 > height - 1 ? py - 4 : py + 4];
  const joint = [Math.max(0, Math.min(width - 1, Math.round(p[0]))), Math.max(0, Math.min(height - 1, Math.round(p[1])))];
  const name = freeName('pivot', Object.keys(state.rig.bones));
  exec(editCmd(`Ajouter le pivot « ${name} » (enfant de « ${parent} »)`, (d) => {
    d.rig.bones[name] = { parent, joint };
    d.selection = { kind: 'bone', id: name };
  }));
  if (state.step !== 'rig') setStep('rig');
  setLayer('pivots', true);
  setLayer('skeleton', true);
  hint(`Pivot « ${name} » ajouté sous « ${parent} ». Glissez-le avec l'outil Déplacer (J), renommez-le dans l'inspecteur (F2).`);
  return name;
}

const renameKey = (obj, from, to) => (obj ? Object.fromEntries(Object.entries(obj).map(([k, v]) => [k === from ? to : k, v])) : obj);

/** Renomme un pivot partout : os, parents, pièces, chaînes IK, clés de l'animation. Renvoie un message d'erreur ou null. */
export function renameBone(bone, name) {
  name = String(name || '').trim();
  if (name === bone) return null;
  if (isLockedBone(bone)) return 'Le template humanoïde exige un os nommé « hips » : il ne peut pas être renommé.';
  const err = nameError(name, Object.keys(state.rig.bones));
  if (err) return err;
  exec(editCmd(`Renommer le pivot « ${bone} » en « ${name} »`, (d) => {
    d.rig.bones = renameKey(d.rig.bones, bone, name);
    for (const b of Object.values(d.rig.bones)) if (b.parent === bone) b.parent = name;
    for (const p of Object.values(d.rig.parts)) if (p.bone === bone) p.bone = name;
    for (const c of Object.values(d.rig.ik || {})) {
      if (Array.isArray(c.chain)) c.chain = c.chain.map((b) => (b === bone ? name : b));
      if (c.target_bone === bone) c.target_bone = name;
    }
    for (const s of Object.values(d.rig.swaps || {})) if (s.bone === bone) s.bone = name;
    for (const f of (d.anim && d.anim.frames) || []) {
      if (f.bones) f.bones = renameKey(f.bones, bone, name);
      if (f.z) f.z = renameKey(f.z, bone, name);
    }
    if (d.selection && d.selection.kind === 'bone' && d.selection.id === bone) d.selection.id = name;
  }));
  if (state.hiddenBones.delete(bone)) emit('visibility');
  return null;
}

/** Supprime un pivot : ses enfants et ses pièces passent à son parent. Renvoie un message d'erreur ou null. */
export function deleteBone(bone) {
  const b = state.rig.bones[bone];
  if (!b) return null;
  if (!b.parent || !state.rig.bones[b.parent]) return 'Le pivot racine ne peut pas être supprimé : tout le squelette en dépend.';
  if (isLockedBone(bone)) return 'Le template humanoïde exige l\'os « hips ».';
  const parent = b.parent;
  const lostIk = Object.entries(state.rig.ik || {}).filter(([, c]) => (c.chain || []).includes(bone) || c.target_bone === bone).map(([k]) => k);
  exec(editCmd(`Supprimer le pivot « ${bone} »`, (d) => {
    delete d.rig.bones[bone];
    for (const o of Object.values(d.rig.bones)) if (o.parent === bone) o.parent = parent;
    for (const p of Object.values(d.rig.parts)) if (p.bone === bone) p.bone = parent;
    for (const s of Object.values(d.rig.swaps || {})) if (s.bone === bone) s.bone = parent;
    for (const k of lostIk) delete d.rig.ik[k];
    for (const f of (d.anim && d.anim.frames) || []) {
      if (f.bones) delete f.bones[bone];
      if (f.z) delete f.z[bone];
      for (const k of lostIk) if (f.ik) delete f.ik[k];
    }
    d.selection = { kind: 'bone', id: parent };
  }));
  state.hiddenBones.delete(bone);
  hint(`Pivot « ${bone} » supprimé : ses pièces et ses enfants sont rattachés à « ${parent} »${lostIk.length ? ` ; chaîne IK retirée : ${lostIk.join(', ')}` : ''}. Ctrl+Z pour annuler.`);
  return null;
}

/** Change le parent d'un pivot (jamais lui-même ni un de ses descendants). */
export function reparentBone(bone, parent) {
  if (!state.rig.bones[parent] || boneSubtree(bone).includes(parent)) return;
  exec(setCmd('rig', ['bones', bone, 'parent'], parent, `Rattacher le pivot « ${bone} » à « ${parent} »`));
}

/** Ajoute une pièce vide sur l'os visé : à peindre ensuite au pinceau. */
export function addPart() {
  if (state.status !== 'ready') return null;
  const bone = anchorBone();
  const name = freeName('piece', Object.keys(state.rig.parts));
  const z = Math.max(0, ...Object.values(state.rig.parts).map((p) => p.z || 0));
  exec(editCmd(`Ajouter la pièce « ${name} » (os « ${bone} »)`, (d) => {
    d.rig.parts[name] = { bone, z, region: {} };
    d.partNames.push(name);
    d.selection = { kind: 'part', id: name };
  }));
  if (state.step !== 'rig') setStep('rig');
  setTool('brush');
  hint(`Pièce « ${name} » ajoutée sur « ${bone} » : peignez ses pixels (les pixels pris à une autre pièce changent de propriétaire).`);
  return name;
}

// --- Animation à la main : nouvelle animation, capture de poses ---------------------------

/** Animation vide d'une frame au repos, à poser en glissant les pivots. Remplace l'animation courante (annulable). */
export function newAnimation() {
  if (state.status !== 'ready') return;
  exec(editCmd('Nouvelle animation vide', (d) => {
    d.anim = { version: 1, name: 'custom', loop: true, fps: 10, frames: [{ duration_ms: 100, bones: {} }] };
    d.frame = 0;
  }));
  if (state.playing) state.playing = false;
  if (state.step !== 'animate') setStep('animate');
  setTool('joint');
  hint('Glissez un pivot pour faire tourner le membre qui le porte (pas de 15°, Maj = angle libre), puis « Capturer la pose » (K) pour passer à la frame suivante.');
}

/** Garde la pose de la frame courante et ouvre, juste après, une copie à modifier. */
export function captureFrame() {
  if (!frameCount()) return newAnimation();
  const i = state.frame;
  exec(editCmd(`Capturer la pose (frame ${i + 1}) et ouvrir la frame ${i + 2}`, (d) => {
    const copy = clone(d.anim.frames[i]);
    delete copy.key;
    delete copy.label;
    delete copy.paint; // les retouches valent pour la pose d'origine, pas pour celle qu'on va poser
    d.anim.frames.splice(i + 1, 0, copy);
    d.frame = i + 1;
  }));
  if (state.playing) state.playing = false;
  const n = frameCount();
  hint(`Frame ${i + 2} / ${n} : copie de la pose précédente, modifiez-la.${n > 8 ? ' Plus de 8 frames : au-delà, le pixel art perd en lisibilité.' : ''}`);
}

export function deleteFrame() {
  const n = frameCount(), i = state.frame;
  if (n < 2) return hint('Une animation garde au moins une frame.');
  exec(editCmd(`Supprimer la frame ${i + 1}`, (d) => {
    d.anim.frames.splice(i, 1);
    d.frame = Math.min(i, n - 2);
  }));
}

export function renameAnim(name) {
  name = String(name || '').trim();
  if (!state.anim || !name) return;
  exec(setCmd('anim', ['name'], name, `Renommer l'animation en « ${name} »`));
}

export function setTool(tool) {
  if (tool !== 'select' && state.step === 'prepare') {
    hint('L\'étape Préparer sert à vérifier le sprite : passez à l\'étape Rigger (touche 2) pour éditer.');
    return;
  }
  if ((tool === 'brush' || tool === 'eraser') && state.step !== 'rig') {
    hint('Le pinceau et la gomme modifient la label map : passez à l\'étape Rigger (touche 2).');
    return;
  }
  if (tool === 'retouch') {
    if (state.step !== 'animate') return hint('La retouche corrige les pixels d\'une frame : passez à l\'étape Animer (touche 3).');
    if (!frameCount()) return hint('Aucune animation à retoucher : appliquez un preset ou créez une animation vide.');
  }
  setView({ tool });
  if (tool === 'retouch') hint('Retouche : peignez les pixels de CETTE frame avec une couleur de la palette. Alt+clic prend la couleur sous le curseur.');
  if ((tool === 'brush' || tool === 'eraser') && handRegionParts().length) {
    hint('Ce rig contient des polygones ou des exclusions écrits à la main : le premier trait les convertira en rectangles + pixels (annulable).');
  }
  if (tool === 'brush' || tool === 'eraser') setLayer('labelmap', true);
  if (tool === 'joint') setLayer('pivots', true);
}

export function toggleVisibility(sel = state.selection) {
  if (!sel) return;
  const set = sel.kind === 'bone' ? state.hiddenBones : state.hiddenParts;
  if (set.has(sel.id)) set.delete(sel.id);
  else set.add(sel.id);
  emit('visibility');
}

export { isAnimStep };
