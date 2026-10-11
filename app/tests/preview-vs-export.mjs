#!/usr/bin/env node
// =============================================================================
//  Test « l'aperçu est identique à l'export » (checklist UX/UI de CLAUDE.md)
// -----------------------------------------------------------------------------
//  Ce que le test prouve, frame par frame :
//    1. ce que le viewport de l'éditeur AFFICHE (pixels relus dans le canvas,
//       calques éteints) est, pixel pour pixel, la frame rendue par le moteur
//       (`GET /api/render/frames/{i}.png`) ; chaque pixel du sprite est un bloc
//       uni de zoom x zoom pixels physiques (aucun flou, aucun zoom non entier) ;
//    2. avec --export : cette même frame est, pixel pour pixel, la cellule
//       correspondante de la spritesheet écrite par `POST /api/export`.
//  La transparence est vérifiée en relisant le viewport sur fond noir PUIS sur
//  fond blanc : un pixel opaque est identique sur les deux, un pixel transparent
//  prend la couleur du fond.
//
//  Mode d'emploi (Node 22 ou plus, aucune dépendance) :
//    1. lancer le serveur sur un projet qui a une animation :
//         python -m animai.cli.main serve <dossier-projet> --port 8765
//    2. lancer le test :
//         node app/tests/preview-vs-export.mjs --url http://127.0.0.1:8765/
//         node app/tests/preview-vs-export.mjs --url http://127.0.0.1:8765/ --export
//       --export  écrit frames/ et export/ dans le dossier projet (comme le bouton Exporter)
//       --browser chemin de Edge ou Chrome (sinon détecté ; ou variable BROWSER)
//       --scale   densité d'écran à simuler, par exemple 1.25 ou 1.5 (mise à l'échelle Windows)
//  Code de retour : 0 = identique, 1 = différence ou erreur.
//
//  Le test lance son propre navigateur headless sur un profil temporaire et
//  n'arrête que ce processus-là (par son PID), jamais un navigateur déjà ouvert.
// =============================================================================

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { spawn } from 'node:child_process';

const args = process.argv.slice(2);
const opt = (name, def = null) => {
  const i = args.indexOf('--' + name);
  return i < 0 ? def : args[i + 1] && !args[i + 1].startsWith('--') ? args[i + 1] : true;
};
const BASE = String(opt('url', 'http://127.0.0.1:8765/')).replace(/\/?$/, '/');
const API = BASE + 'api';
const WITH_EXPORT = !!opt('export', false);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- PNG -> RGBA (8 bits, non entrelacé : ce que le moteur écrit) -------------------
function decodePng(buf) {
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error('pas un PNG');
  let pos = 8, w = 0, h = 0, depth = 0, type = 0, interlace = 0, palette = null, trns = null;
  const idat = [];
  while (pos < buf.length) {
    const len = buf.readUInt32BE(pos), name = buf.toString('latin1', pos + 4, pos + 8), data = buf.subarray(pos + 8, pos + 8 + len);
    if (name === 'IHDR') { w = data.readUInt32BE(0); h = data.readUInt32BE(4); depth = data[8]; type = data[9]; interlace = data[12]; }
    else if (name === 'PLTE') palette = data;
    else if (name === 'tRNS') trns = data;
    else if (name === 'IDAT') idat.push(data);
    pos += 12 + len;
  }
  const ch = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[type];
  if (depth !== 8 || interlace || !ch) throw new Error(`PNG non géré (profondeur ${depth}, type ${type}, entrelacement ${interlace})`);
  const raw = zlib.inflateSync(Buffer.concat(idat)), stride = w * ch, cur = Buffer.alloc(stride);
  let prev = Buffer.alloc(stride);
  const out = new Uint8Array(w * h * 4);
  for (let y = 0; y < h; y++) {
    const f = raw[y * (stride + 1)], line = raw.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let x = 0; x < stride; x++) {
      const a = x >= ch ? cur[x - ch] : 0, b = prev[x], c = x >= ch ? prev[x - ch] : 0;
      let v = line[x];
      if (f === 1) v += a;
      else if (f === 2) v += b;
      else if (f === 3) v += (a + b) >> 1;
      else if (f === 4) { const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c); v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c; }
      cur[x] = v & 255;
    }
    for (let x = 0; x < w; x++) {
      const o = (y * w + x) * 4, i = x * ch;
      if (type === 6) out.set(cur.subarray(i, i + 4), o);
      else if (type === 2) out.set([cur[i], cur[i + 1], cur[i + 2], 255], o);
      else if (type === 3) out.set([palette[cur[i] * 3], palette[cur[i] * 3 + 1], palette[cur[i] * 3 + 2], trns && cur[i] < trns.length ? trns[cur[i]] : 255], o);
      else if (type === 0) out.set([cur[i], cur[i], cur[i], 255], o);
      else out.set([cur[i], cur[i], cur[i], cur[i + 1]], o);
    }
    prev = Buffer.from(cur);
  }
  return { width: w, height: h, data: out };
}

// --- navigateur headless piloté par le protocole DevTools --------------------------
function findBrowser() {
  const given = opt('browser') || process.env.BROWSER;
  const candidates = [given,
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
    'C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/microsoft-edge'].filter(Boolean);
  const found = candidates.find((c) => fs.existsSync(c));
  if (!found) throw new Error('Aucun navigateur Chromium trouvé : indiquez --browser <chemin> (Edge ou Chrome).');
  return found;
}

async function launch() {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'animai-test-'));
  const child = spawn(findBrowser(), ['--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--window-size=1440,900',
    '--no-first-run', '--no-default-browser-check', '--disable-gpu', ...(opt('scale') ? [`--force-device-scale-factor=${opt('scale')}`] : []), 'about:blank'], { stdio: 'ignore' });
  const portFile = path.join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 100 && !fs.existsSync(portFile); i++) await sleep(100);
  if (!fs.existsSync(portFile)) { child.kill(); throw new Error('Le navigateur n\'a pas démarré.'); }
  const port = fs.readFileSync(portFile, 'utf8').split('\n')[0].trim();
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map(), errors = [];
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.id) { const p = pending.get(d.id); pending.delete(d.id); d.error ? p.rej(new Error(JSON.stringify(d.error))) : p.res(d.result); }
    else if (d.method === 'Runtime.exceptionThrown') errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
  };
  const send = (method, params = {}) => new Promise((res, rej) => { pending.set(++id, { res, rej }); ws.send(JSON.stringify({ id, method, params })); });
  await send('Runtime.enable'); await send('Page.enable');
  return {
    errors,
    goto: (url) => send('Page.navigate', { url }),
    async eval(expression) {
      const r = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
      if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
      return r.result.value;
    },
    async close() {
      try { ws.close(); } catch { /* déjà fermé */ }
      child.kill(); // uniquement le processus lancé ici
      await sleep(500);
      try { fs.rmSync(profile, { recursive: true, force: true }); } catch { /* profil encore verrouillé : dossier temporaire */ }
    },
  };
}

// --- lecture du viewport, dans la page ------------------------------------------------
const READ_FRAME = `async (index, background) => {
  const store = await import('/js/store.js'), viewport = await import('/js/viewport.js'), preview = await import('/js/preview.js');
  const s = store.state;
  const nextPaint = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  if (s.step !== 'animate') store.setStep('animate');
  if (s.playing) { s.playing = false; }
  for (const l of Object.keys(s.layers)) s.layers[l] = false;      // calques éteints : l'image seule
  s.selection = null; s.qaFocus = null; s.hover = null;
  s.hiddenParts.clear(); s.hiddenBones.clear();
  store.setView({ tool: 'select', background });
  store.setFrame(index, { wrap: false });
  for (let i = 0; i < 100 && !(preview.getFrame(index) && s.render.done >= s.render.total); i++) await new Promise((r) => setTimeout(r, 50));
  const entry = preview.getFrame(index);
  if (!entry) return { error: 'frame ' + index + ' non rendue : ' + (s.render.error || 'délai dépassé') };
  viewport.fit();
  await nextPaint();
  const v = viewport.getView(), canvas = document.getElementById('canvas'), ctx = canvas.getContext('2d');
  const x0 = v.panX - entry.origin[0] * v.zoom, y0 = v.panY - entry.origin[1] * v.zoom, W = entry.width, H = entry.height, z = v.zoom;
  if (!Number.isInteger(z) || !Number.isInteger(x0) || !Number.isInteger(y0)) return { error: 'zoom ou décalage non entier : ' + JSON.stringify(v) };
  if (x0 < 0 || y0 < 0 || x0 + W * z > canvas.width || y0 + H * z > canvas.height) return { error: 'la frame ne tient pas dans le viewport' };
  const img = ctx.getImageData(x0, y0, W * z, H * z).data, out = new Array(W * H * 3);
  let uneven = 0;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const o = ((y * z) * W * z + x * z) * 4, r = img[o], g = img[o + 1], b = img[o + 2];
    for (let dy = 0; dy < z; dy++) for (let dx = 0; dx < z; dx++) {
      const k = ((y * z + dy) * W * z + x * z + dx) * 4;
      if (img[k] !== r || img[k + 1] !== g || img[k + 2] !== b || img[k + 3] !== 255) uneven++;
    }
    out[(y * W + x) * 3] = r; out[(y * W + x) * 3 + 1] = g; out[(y * W + x) * 3 + 2] = b;
  }
  return { width: W, height: H, zoom: z, uneven, rgb: out, dpr: devicePixelRatio, buffer: [canvas.width, canvas.height] };
}`;

// --- test -------------------------------------------------------------------------------
async function main() {
  const getJson = async (url, init) => {
    const r = await fetch(url, init);
    const body = await r.json().catch(() => null);
    if (!r.ok) throw new Error(`${url} -> ${r.status} ${body && body.error ? body.error : ''}`);
    return body;
  };
  const anim = await getJson(API + '/anim').catch((e) => { throw new Error('Le projet servi n\'a pas d\'animation (appliquez un preset) : ' + e.message); });
  const n = anim.data.frames.length;
  console.log(`Projet ${BASE} · animation « ${anim.data.name} » · ${n} frames`);

  const engine = [];
  for (let i = 0; i < n; i++) engine.push(decodePng(Buffer.from(await (await fetch(`${API}/render/frames/${i}.png`)).arrayBuffer())));
  for (const f of engine) for (let k = 3; k < f.data.length; k += 4) if (f.data[k] !== 0 && f.data[k] !== 255) throw new Error('la frame du moteur a un alpha non binaire');

  let failures = 0;
  const browser = await launch();
  try {
    await browser.goto(BASE);
    for (let i = 0; i < 100; i++) { await sleep(100); if (await browser.eval(`document.getElementById('app')?.dataset.status === 'ready' && !!window.__animaiBooted`).catch(() => false)) break; }
    const kind = await browser.eval(`(async()=>(await import('/js/store.js')).backend.kind)()`);
    if (kind !== 'http') throw new Error('l\'app n\'est pas branchée sur le serveur (mode démo) : ouvrez la racine du serveur, qui redirige vers ?api=/api');
    let checked = 0, zoom = 0, dpr = 0;
    for (let i = 0; i < n; i++) {
      const ref = engine[i];
      for (const [bgName, bg] of [['black', 0], ['white', 255]]) {
        const got = await browser.eval(`(${READ_FRAME})(${i}, '${bgName}')`);
        if (got.error) throw new Error(got.error);
        zoom = got.zoom; dpr = got.dpr;
        if (got.width !== ref.width || got.height !== ref.height) { failures++; console.log(`ÉCHEC frame ${i} : taille ${got.width}x${got.height} affichée, ${ref.width}x${ref.height} rendue`); continue; }
        if (got.uneven) { failures++; console.log(`ÉCHEC frame ${i} (fond ${bgName}) : ${got.uneven} pixels physiques hors de leur bloc uni (flou ou zoom non entier)`); }
        let bad = 0, first = null;
        for (let p = 0; p < ref.width * ref.height; p++) {
          const a = ref.data[p * 4 + 3];
          const exp = a ? [ref.data[p * 4], ref.data[p * 4 + 1], ref.data[p * 4 + 2]] : [bg, bg, bg];
          if (got.rgb[p * 3] !== exp[0] || got.rgb[p * 3 + 1] !== exp[1] || got.rgb[p * 3 + 2] !== exp[2]) {
            bad++;
            first ??= `(${p % ref.width}, ${Math.floor(p / ref.width)}) affiché ${got.rgb.slice(p * 3, p * 3 + 3)} attendu ${exp}`;
          }
        }
        checked += ref.width * ref.height;
        if (bad) { failures++; console.log(`ÉCHEC frame ${i} (fond ${bgName}) : ${bad} pixels diffèrent, premier ${first}`); }
      }
    }
    console.log(`Viewport = moteur : ${n} frames x 2 fonds, ${checked} pixels comparés, zoom x${zoom}, densité d'écran ${dpr} -> ${failures ? 'DIFFÉRENCES' : 'identique'}`);
    if (browser.errors.length) { failures++; console.log('Erreurs JavaScript dans la page :', browser.errors); }
  } finally {
    await browser.close();
  }

  if (WITH_EXPORT) {
    const exp = await getJson(API + '/export', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ formats: ['spritesheet'] }) });
    const [pngPath, jsonPath] = exp.outputs.spritesheet;
    const sheet = decodePng(fs.readFileSync(pngPath)), meta = JSON.parse(fs.readFileSync(jsonPath, 'utf8'));
    const cells = Array.isArray(meta.frames) ? meta.frames : Object.values(meta.frames);
    let bad = 0;
    if (cells.length !== n) { bad++; console.log(`ÉCHEC export : ${cells.length} cellules pour ${n} frames`); }
    cells.forEach((cell, i) => {
      const { x, y, w, h } = cell.frame, ref = engine[i];
      if (!ref || w !== ref.width || h !== ref.height) { bad++; return console.log(`ÉCHEC export frame ${i} : cellule ${w}x${h}`); }
      let diff = 0;
      for (let yy = 0; yy < h; yy++) for (let xx = 0; xx < w; xx++) for (let c = 0; c < 4; c++) {
        if (sheet.data[((y + yy) * sheet.width + x + xx) * 4 + c] !== ref.data[(yy * w + xx) * 4 + c]) diff++;
      }
      if (diff) { bad++; console.log(`ÉCHEC export frame ${i} : ${diff} composantes diffèrent de la frame affichée`); }
    });
    console.log(`Moteur = spritesheet exportée (${path.basename(pngPath)}, ${cells.length} cellules) -> ${bad ? 'DIFFÉRENCES' : 'identique'}`);
    failures += bad;
  }

  console.log(failures ? `ÉCHEC (${failures})` : 'OK : l\'aperçu est identique à l\'export.');
  process.exit(failures ? 1 : 0);
}

main().catch((e) => { console.error('ERREUR : ' + e.message); process.exit(1); });
