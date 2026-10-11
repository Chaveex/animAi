// Données de démonstration embarquées : un sprite humanoïde 64x64 vu de côté et son rig,
// générés en JS et conformes à docs/schemas.md. Importé uniquement par demo-backend.js.

import { encodeRegions } from './demo-core.js';

const W = 64, H = 64;

const C = {
  outline: [27, 27, 38],
  skin: [232, 176, 136],
  skinS: [196, 133, 95],
  hair: [90, 58, 34],
  shirt: [63, 127, 191],
  shirtL: [95, 155, 215],
  shirtS: [45, 93, 143],
  pants: [74, 74, 92],
  pantsS: [54, 54, 74],
  shoe: [122, 74, 42],
  belt: [217, 179, 74],
};

// Ordre des pièces dans rig.json = numéros affichés dans la label map (1..13).
const PARTS = [
  ['pelvis', 'hips', 0], ['torso', 'spine', 1], ['head', 'head', 2],
  ['arm_r', 'arm_r', 4], ['forearm_r', 'forearm_r', 5], ['hand_r', 'hand_r', 5],
  ['arm_l', 'arm_l', -3],
  ['thigh_r', 'thigh_r', 3], ['shin_r', 'shin_r', 3], ['foot_r', 'foot_r', 3],
  ['thigh_l', 'thigh_l', -2], ['shin_l', 'shin_l', -2], ['foot_l', 'foot_l', -2],
];

// Peinture de l'arrière vers l'avant : [pièce, x, y, w, h, couleur].
const SHAPES = [
  ['arm_l', 36, 22, 3, 12, 'shirtS'], ['arm_l', 36, 34, 3, 3, 'skinS'],
  ['thigh_l', 32, 42, 5, 8, 'pantsS'], ['shin_l', 32, 50, 5, 7, 'pantsS'], ['foot_l', 32, 57, 7, 3, 'shoe'],
  ['pelvis', 27, 37, 10, 5, 'pants'], ['pelvis', 27, 37, 10, 1, 'belt'],
  ['torso', 27, 19, 10, 18, 'shirt'], ['torso', 27, 19, 2, 18, 'shirtS'],
  ['head', 26, 6, 12, 13, 'skin'], ['head', 26, 6, 12, 4, 'hair'], ['head', 26, 6, 3, 9, 'hair'],
  ['head', 34, 12, 1, 2, 'outline'], ['head', 26, 18, 12, 1, 'skinS'],
  ['thigh_r', 27, 42, 5, 8, 'pants'], ['shin_r', 27, 50, 5, 7, 'pants'], ['foot_r', 27, 57, 7, 3, 'shoe'],
  ['arm_r', 30, 21, 4, 9, 'shirtL'], ['forearm_r', 30, 30, 4, 7, 'shirtL'], ['hand_r', 30, 37, 4, 3, 'skin'],
];

const BONES = {
  hips: [null, 32, 39], spine: ['hips', 32, 36], head: ['spine', 32, 19],
  arm_r: ['spine', 32, 22], forearm_r: ['arm_r', 32, 30], hand_r: ['forearm_r', 32, 37],
  arm_l: ['spine', 37, 23],
  thigh_r: ['hips', 29, 42], shin_r: ['thigh_r', 29, 50], foot_r: ['shin_r', 29, 57],
  thigh_l: ['hips', 34, 42], shin_l: ['thigh_l', 34, 50], foot_l: ['shin_l', 34, 57],
};

/** @returns {{sprite: {width, height, data}, rig: object}} */
export function buildDemo() {
  const data = new Uint8ClampedArray(W * H * 4);
  const labels = new Int16Array(W * H).fill(-1);
  const names = PARTS.map((p) => p[0]);

  for (const [part, x, y, w, h, color] of SHAPES) {
    const k = names.indexOf(part);
    for (let yy = y; yy < y + h; yy++) for (let xx = x; xx < x + w; xx++) {
      const i = yy * W + xx;
      data.set([...C[color], 255], i * 4);
      labels[i] = k;
    }
  }

  // Contour 1 px à l'extérieur de la silhouette, rattaché à la pièce voisine.
  const filled = labels.slice();
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = y * W + x;
    if (filled[i] >= 0) continue;
    let owner = -1;
    for (const [dx, dy] of [[0, -1], [1, 0], [0, 1], [-1, 0]]) {
      const nx = x + dx, ny = y + dy;
      if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
      owner = Math.max(owner, filled[ny * W + nx]);
    }
    if (owner >= 0) {
      data.set([...C.outline, 255], i * 4);
      labels[i] = owner;
    }
  }

  // Volontairement : 3 pixels du contour de la tête laissés non assignés, pour que le
  // panneau QA ait un échec localisé à montrer (« 3 pixels non assignés — les voir »).
  for (const x of [30, 31, 32]) labels[5 * W + x] = -1;

  const regions = encodeRegions(labels, names, W, H);
  const bones = {};
  for (const [name, [parent, x, y]] of Object.entries(BONES)) bones[name] = { parent, joint: [x, y] };
  const parts = {};
  for (const [name, bone, z] of PARTS) {
    parts[name] = { bone, z, region: regions[name], overlap: name === 'torso' ? 2 : 1 };
  }

  const rig = {
    version: 1,
    sprite: 'sprite.png',
    view: 'side',
    template: 'humanoid',
    pivot: [0.5, 1.0],
    bones,
    parts,
    ik: {
      foot_r: { chain: ['thigh_r', 'shin_r'], target_bone: 'foot_r' },
      foot_l: { chain: ['thigh_l', 'shin_l'], target_bone: 'foot_l' },
    },
  };
  return { sprite: { width: W, height: H, data }, rig };
}
