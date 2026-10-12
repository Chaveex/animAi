// Backend HTTP : client du serveur de l'éditeur (`animai serve`), routes de docs/ux-spec.md § 13
// et précisions de docs/schemas.md « Serveur de l'éditeur ». Vérifié dans un navigateur contre le
// vrai serveur (voir docs/ux-spec.md § 15).

import { ApiError, ConflictError } from './errors.js';

/** PNG -> { width, height, data } sans altération des couleurs (alpha binaire, pas de profil). */
async function decodePng(blob) {
  const bmp = await createImageBitmap(blob, { premultiplyAlpha: 'none', colorSpaceConversion: 'none' });
  const canvas = document.createElement('canvas');
  canvas.width = bmp.width;
  canvas.height = bmp.height;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(bmp, 0, 0);
  const img = ctx.getImageData(0, 0, bmp.width, bmp.height);
  return { width: img.width, height: img.height, data: img.data };
}

async function encodePng({ width, height, data }) {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  canvas.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(data), width, height), 0, 0);
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
}

const runsToLabels = (runs, size) => {
  const labels = new Int16Array(size);
  let i = 0;
  for (const [label, count] of runs) {
    labels.fill(label, i, i + count);
    i += count;
  }
  return labels;
};

const labelsToRuns = (labels) => {
  const runs = [];
  for (let i = 0; i < labels.length; ) {
    let j = i + 1;
    while (j < labels.length && labels[j] === labels[i]) j++;
    runs.push([labels[i], j - i]);
    i = j;
  }
  return runs;
};

export function createHttpBackend(base) {
  base = base.replace(/\/$/, '');

  async function call(method, path, body, raw = false) {
    let res;
    try {
      res = await fetch(base + path, {
        method,
        headers: body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? (body instanceof FormData ? body : JSON.stringify(body)) : undefined,
      });
    } catch {
      throw new ApiError('Serveur injoignable. Vérifiez que « animai serve » tourne toujours.', 0);
    }
    if (res.status === 409) throw new ConflictError(await res.json());
    if (!res.ok) {
      let payload = null;
      try {
        payload = await res.json();
      } catch { /* corps non JSON */ }
      throw new ApiError((payload && payload.error) || `Erreur ${res.status}`, res.status, payload && payload.details);
    }
    return raw ? res : res.json();
  }

  async function getRig() {
    // Deux requêtes : si rig.json change entre les deux, les révisions diffèrent et on recommence.
    for (let attempt = 0; ; attempt++) {
      const [rig, lm] = await Promise.all([call('GET', '/rig'), call('GET', '/labelmap')]);
      if (rig.rev === lm.rev || attempt >= 3) {
        return { ...rig, labelmap: { parts: lm.parts, labels: runsToLabels(lm.runs, lm.width * lm.height) } };
      }
    }
  }

  async function getAnim() {
    try {
      return await call('GET', '/anim');
    } catch (e) {
      if (e.status === 404) return null;
      throw e;
    }
  }

  return {
    kind: 'http',
    capabilities: { export: true, swaps: true },
    demo: null,

    async getProject() {
      let meta;
      try {
        meta = await call('GET', '/project');
      } catch (e) {
        if (e.status === 404) return null;
        throw e;
      }
      const [png, rig, anim] = await Promise.all([call('GET', '/sprite.png?rev=' + encodeURIComponent(meta.sprite.rev), null, true), getRig(), getAnim()]);
      return {
        name: meta.name,
        spriteRev: meta.sprite.rev,
        sprite: await decodePng(await png.blob()),
        palette: meta.palette,
        prepare: meta.prepare || { warnings: [] },
        rig,
        anim,
        presets: meta.presets || [],
      };
    },

    getRig,
    getAnim,

    /** Révisions actuelles du disque, pour reconnaître l'écho d'un import ou d'une restauration. */
    async getRevisions() {
      try {
        const [meta, rig, anim] = await Promise.all([call('GET', '/project'), call('GET', '/rig'), getAnim()]);
        return { sprite: meta.sprite.rev, rig: rig.rev, anim: anim ? anim.rev : null };
      } catch (e) {
        if (e.status === 404) return null;
        throw e;
      }
    },

    async importImage(image) {
      const form = new FormData();
      // Le fichier d'origine part tel quel : c'est le `prepare` du cœur qui détoure et retrouve la grille.
      form.append('file', image.file || (await encodePng(image)), image.name || 'sprite.png');
      form.append('view', 'side');
      await call('POST', '/project/import', form);
    },

    putRig: (data, baseRev) => call('PUT', '/rig', { base_rev: baseRev, data }),

    putLabelMap: ({ parts, labels }, baseRev) => call('PUT', '/labelmap', { base_rev: baseRev, parts, runs: labelsToRuns(labels) }),

    /** Le cœur contrôle l'image (palette du sprite, alpha binaire) et la range dans `swaps/` sans rien écraser. */
    async putSwapImage(name, file) {
      const form = new FormData();
      form.append('file', file, file.name || name + '.png');
      const r = await call('POST', `/swaps/${encodeURIComponent(name)}/image`, form);
      return { ...r, pixels: await decodePng(file) };
    },

    async getSwapImage(name, image = '') {
      const png = await call('GET', `/swaps/${encodeURIComponent(name)}.png?image=${encodeURIComponent(image)}`, null, true);
      return decodePng(await png.blob());
    },

    putAnim: (data, baseRev) => call('PUT', '/anim', { base_rev: baseRev, data }),

    deleteAnim: (baseRev) => call('DELETE', '/anim?base_rev=' + encodeURIComponent(baseRev)),

    applyPreset: (preset, baseRev) => call('POST', '/anim/preset', { base_rev: baseRev, preset }),

    retimeAnim: (params, baseRev) => call('POST', '/anim/retime', { base_rev: baseRev, ...params }),

    async renderFrame(index, { hiddenParts = [], rigRev = '', animRev = '' } = {}) {
      const q = `?rig_rev=${encodeURIComponent(rigRev)}&anim_rev=${encodeURIComponent(animRev)}&hide=${encodeURIComponent(hiddenParts.join(','))}`;
      const [png, meta] = await Promise.all([
        call('GET', `/render/frames/${index}.png${q}`, null, true),
        call('GET', `/render/frames/${index}.json${q}`),
      ]);
      const img = await decodePng(await png.blob());
      return {
        ...img,
        origin: meta.origin,
        pivot: meta.pivot || null,
        joints: meta.joints || null,
        angles: meta.angles || null,
        // `parts` de la frame = même ordre que la label map (ordre de rig.json)
        owners: meta.owners_runs ? runsToLabels(meta.owners_runs, img.width * img.height) : null,
      };
    },

    getReport: () => call('GET', '/report'),

    createSnapshot: (label) => call('POST', '/snapshots', { label }),

    restoreSnapshot: (id) => call('POST', `/snapshots/${encodeURIComponent(id)}/restore`),

    exportProject: (options) => call('POST', '/export', options),

    subscribe(fn) {
      const es = new EventSource(base + '/events');
      const types = ['rig.changed', 'anim.changed', 'project.changed'];
      const handlers = types.map((type) => {
        const h = (e) => fn({ type, ...JSON.parse(e.data || '{}') });
        es.addEventListener(type, h);
        return [type, h];
      });
      es.onerror = () => fn({ type: 'connection.lost' });
      es.onopen = () => fn({ type: 'connection.open' });
      return () => {
        handlers.forEach(([type, h]) => es.removeEventListener(type, h));
        es.close();
      };
    },
  };
}
