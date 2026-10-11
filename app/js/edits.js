// Éditions de haut niveau partagées par le viewport, l'inspecteur et les raccourcis.
// Chacune passe par une commande annulable du store.

import { state, exec, setCmd, editCmd, frameCount, setView, setLayer, setStep, isAnimStep, emit, handRegionParts } from './store.js';

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
  setView({ tool });
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
