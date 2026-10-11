// Backend de DÉMONSTRATION : un « serveur » en mémoire qui implémente le même contrat que
// http-backend.js (voir api.js et docs/ux-spec.md § 13). Il joue le rôle des fichiers projet
// (sprite nettoyé, rig.json, anim.json) et simule le cœur via demo-core.js.
// Rien ici n'est persistant : recharger la page repart de zéro.

import { ApiError, ConflictError } from './errors.js';
import { buildDemo } from './demo-sprite.js';
import * as core from './demo-core.js';

const clone = (v) => (v == null ? v : JSON.parse(JSON.stringify(v)));
const cloneSprite = (s) => ({ width: s.width, height: s.height, data: new Uint8ClampedArray(s.data) });

export function createDemoBackend() {
  /** @type {null | {name, sprite, nonBinary, rig, rigRev, rigAuthor, rigAt, labels, partNames, anim, animRev, animAuthor, animAt}} */
  let project = null;
  let revCounter = 0;
  let spriteCounter = 0;
  let snapCounter = 0;
  const snapshots = new Map();
  const listeners = new Set();

  const nextRev = () => 'r' + ++revCounter;
  const emit = (ev) => queueMicrotask(() => listeners.forEach((fn) => fn(ev)));
  const need = () => {
    if (!project) throw new ApiError('Aucun projet ouvert.', 404);
    return project;
  };

  function setRig(p, rig, author) {
    p.rig = clone(rig);
    const dec = core.decodeRegions(p.rig, p.sprite);
    p.labels = dec.labels;
    p.partNames = dec.parts;
    p.rigRev = nextRev();
    p.rigAuthor = author;
    p.rigAt = Date.now();
  }

  function setAnim(p, anim, author) {
    p.anim = clone(anim);
    p.animRev = anim ? nextRev() : null;
    p.animAuthor = author;
    p.animAt = Date.now();
  }

  function makeProject(name, sprite, nonBinary, rig, anim) {
    const p = { name, sprite, nonBinary, spriteRev: 'sp' + ++spriteCounter };
    setRig(p, rig, 'app');
    setAnim(p, anim, 'app');
    return p;
  }

  function checkRig(rig) {
    if (!rig || !rig.bones || !rig.parts) throw new ApiError('rig.json invalide : « bones » et « parts » sont requis.', 422);
    for (const [name, b] of Object.entries(rig.bones)) {
      if (!Array.isArray(b.joint) || !b.joint.every(Number.isInteger)) {
        throw new ApiError(`rig.json invalide : le joint de « ${name} » doit être un couple d'entiers.`, 422);
      }
      if (b.parent != null && !rig.bones[b.parent]) throw new ApiError(`rig.json invalide : parent inconnu pour « ${name} ».`, 422);
    }
    for (const [name, part] of Object.entries(rig.parts)) {
      if (!rig.bones[part.bone]) throw new ApiError(`rig.json invalide : la pièce « ${name} » référence un os inconnu.`, 422);
    }
  }

  function checkAnim(anim) {
    if (!anim || !Array.isArray(anim.frames) || !anim.frames.length) throw new ApiError('anim.json invalide : au moins une frame est requise.', 422);
    for (const f of anim.frames) {
      if (!(f.duration_ms >= 1)) throw new ApiError('anim.json invalide : duration_ms doit être ≥ 1.', 422);
    }
  }

  const conflict = (p, doc, mine) =>
    new ConflictError({
      doc,
      rev: p[doc + 'Rev'],
      author: p[doc + 'Author'],
      at: p[doc + 'At'],
      changed_paths: core.diffPaths(mine, p[doc]).slice(0, 12),
    });

  const rigPayload = (p) => ({
    rev: p.rigRev,
    data: clone(p.rig),
    labelmap: { parts: [...p.partNames], labels: p.labels.slice() },
    author: p.rigAuthor,
    at: p.rigAt,
  });
  const animPayload = (p) => (p.anim ? { rev: p.animRev, data: clone(p.anim), author: p.animAuthor, at: p.animAt } : null);

  return {
    kind: 'demo',
    capabilities: { export: false },

    async getProject() {
      if (!project) return null;
      const p = project;
      const warnings = [];
      if (p.nonBinary) warnings.push(`${p.nonBinary} pixel(s) semi-transparent(s) binarisé(s) (seuil 50 %).`);
      if (Math.min(p.sprite.width, p.sprite.height) < 64) warnings.push('Sprite de moins de 64 px : le rig par pièces rigides donne un rendu médiocre (prévu en v2).');
      return {
        name: p.name,
        spriteRev: p.spriteRev,
        sprite: cloneSprite(p.sprite),
        palette: core.extractPalette(p.sprite),
        prepare: { warnings },
        rig: rigPayload(p),
        anim: animPayload(p),
        presets: core.PRESET_NAMES,
      };
    },

    async getRig() {
      return rigPayload(need());
    },

    async getAnim() {
      return animPayload(need());
    },

    async getRevisions() {
      return project ? { sprite: project.spriteRev, rig: project.rigRev, anim: project.animRev } : null;
    },

    async importImage({ name, width, height, data }) {
      if (!width || !height) throw new ApiError('Image vide ou illisible.', 422);
      if (width > 512 || height > 512) {
        throw new ApiError(`Image de ${width}×${height} px : trop grande pour un sprite (maximum 512×512). Si elle est agrandie, réduisez-la à sa résolution réelle.`, 422);
      }
      const { sprite, nonBinary } = core.prepareImage({ width, height, data });
      if (!core.extractPalette(sprite).length) throw new ApiError('L\'image est entièrement transparente.', 422);
      project = makeProject(name || 'sprite.png', sprite, nonBinary, core.templateRig(sprite, name || 'sprite.png'), null);
    },

    async putRig(data, baseRev) {
      const p = need();
      if (baseRev !== p.rigRev) throw conflict(p, 'rig', data);
      checkRig(data);
      setRig(p, data, 'app');
      return { rev: p.rigRev };
    },

    async putLabelMap({ parts, labels }, baseRev) {
      const p = need();
      if (baseRev !== p.rigRev) throw conflict(p, 'rig', p.rig);
      const { width: w, height: h } = p.sprite;
      if (labels.length !== w * h) throw new ApiError('Label map de taille incorrecte.', 422);
      const regions = core.encodeRegions(labels, parts, w, h);
      const rig = clone(p.rig);
      for (const name of parts) if (rig.parts[name]) rig.parts[name].region = regions[name];
      setRig(p, rig, 'app');
      return { rev: p.rigRev, regions: clone(regions) };
    },

    async putAnim(data, baseRev) {
      const p = need();
      if (baseRev !== p.animRev) throw conflict(p, 'anim', data);
      checkAnim(data);
      setAnim(p, data, 'app');
      return { rev: p.animRev };
    },

    async deleteAnim(baseRev) {
      const p = need();
      if (baseRev !== p.animRev) throw conflict(p, 'anim', null);
      setAnim(p, null, 'app');
      return { rev: null };
    },

    async applyPreset(name, baseRev) {
      const p = need();
      if (baseRev !== p.animRev) throw conflict(p, 'anim', p.anim);
      const { anim, warnings } = core.buildPreset(name, p.rig);
      setAnim(p, anim, 'app');
      return { rev: p.animRev, data: clone(p.anim), warnings };
    },

    async retimeAnim(params, baseRev) {
      const p = need();
      if (!p.anim) throw new ApiError('Aucune animation à rééchantillonner.', 404);
      if (baseRev !== p.animRev) throw conflict(p, 'anim', p.anim);
      let anim;
      try {
        anim = core.retime(p.anim, params);
      } catch (e) {
        throw new ApiError(e.message, 422);
      }
      setAnim(p, anim, 'app');
      return { rev: p.animRev, data: clone(p.anim), warnings: anim.frames.length > 8 ? ['Plus de 8 frames : peu lisible en pixel art.'] : [] };
    },

    /** DÉMO : rendu simplifié (demo-core.js). En production : PNG rendu par le moteur du cœur. */
    async renderFrame(index, opts = {}) {
      const p = need();
      return core.renderFrame(p, index, opts);
    },

    async getReport() {
      return core.validate(need());
    },

    async createSnapshot(label) {
      const id = 's' + ++snapCounter;
      const p = project;
      snapshots.set(id, p ? { ...p, sprite: cloneSprite(p.sprite), rig: clone(p.rig), anim: clone(p.anim) } : null);
      return { id, label, at: Date.now(), author: 'app' };
    },

    async restoreSnapshot(id) {
      if (!snapshots.has(id)) throw new ApiError('Version introuvable.', 404);
      const s = snapshots.get(id);
      project = s ? makeProject(s.name, cloneSprite(s.sprite), s.nonBinary, s.rig, s.anim) : null;
    },

    async exportProject() {
      throw new ApiError('Export indisponible en mode démo : il est produit par le cœur, via le serveur.', 501);
    },

    subscribe(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },

    // --- Uniquement en démo : simuler Claude qui modifie les fichiers projet ---
    demo: {
      async loadExample() {
        const { sprite, rig } = buildDemo();
        project = makeProject('exemple-humanoide', sprite, 0, rig, core.buildPreset('walk', rig).anim);
      },
      /** Claude déplace le joint de la tête. `silent` = sans événement, pour provoquer un conflit à la prochaine écriture. */
      externalEdit({ silent = false } = {}) {
        const p = need();
        const rig = clone(p.rig);
        const bone = rig.bones.head ? 'head' : Object.keys(rig.bones)[0];
        const [x, y] = rig.bones[bone].joint;
        rig.bones[bone].joint = [Math.min(p.sprite.width - 1, x + 1), Math.max(0, y - 1)];
        setRig(p, rig, 'external');
        if (!silent) emit({ type: 'rig.changed', rev: p.rigRev, author: 'external', at: p.rigAt });
      },
    },
  };
}
