// Éditions de haut niveau partagées par le viewport, l'inspecteur et les raccourcis.
// Chacune passe par une commande annulable du store.

import { state, exec, setCmd, frameCount, setView, setLayer, isAnimStep, emit, handRegionParts } from './store.js';

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
