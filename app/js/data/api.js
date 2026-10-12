// ============================================================================
//  COUCHE D'ACCÈS AUX DONNÉES — point d'entrée UNIQUE
// ----------------------------------------------------------------------------
//  Tout le reste de l'app importe `api` d'ici et de nulle part ailleurs.
//  Deux implémentations du même contrat :
//    - demo-backend.js : données embarquées, cœur simulé (défaut) ;
//    - http-backend.js : le vrai serveur FastAPI (docs/ux-spec.md § 13),
//      activé par `?api=/api` dans l'URL ou par `window.ANIMAI_API`.
//
//  Contrat (toutes les méthodes renvoient une Promise) :
//    getProject()                    -> null | { name, sprite, spriteRev, palette, prepare, rig, anim, presets }
//         sprite  = { width, height, data: Uint8ClampedArray RGBA }
//         rig     = { rev, data: <rig.json>, labelmap: { parts: string[], labels: Int16Array }, author, at }
//         anim    = null | { rev, data: <anim.json>, author, at }
//    getRig() / getAnim()            -> même forme que ci-dessus
//    getRevisions()                  -> null | { sprite, rig, anim }   (révisions actuelles du disque)
//    importImage({ name, width, height, data, file }) -> void  (lance `prepare` + template ; `file` = fichier d'origine)
//    putRig(data, baseRev)           -> { rev }                 | ConflictError | ApiError 422
//    putLabelMap({ parts, labels }, baseRev) -> { rev, regions } (le CŒUR ré-encode les régions)
//    putSwapImage(name, file)        -> { image, width, height, pixels: { width, height, data } } | ApiError 422
//         range l'image d'un remplacement dans le projet (jamais d'écrasement) ; `image` = chemin à écrire dans rig.swaps
//    getSwapImage(name, image)       -> { width, height, data }   (image d'un remplacement déclaré dans rig.json)
//    putAnim(data, baseRev)          -> { rev }
//    deleteAnim(baseRev)             -> { rev: null }
//    applyPreset(name, baseRev)      -> { rev, data, warnings }
//    retimeAnim({ frames?, fps?, duration_ms? }, baseRev) -> { rev, data, warnings }   (un, deux ou trois paramètres)
//    renderFrame(i, { hiddenParts, rigRev, animRev })
//                                    -> { width, height, data, origin: [x, y], pivot?: [x, y], joints?, angles?, owners? }
//         origin = position du (0,0) du sprite dans le canvas ; pivot en pixels canvas (coin de grille) ;
//         joints en coordonnées sprite ; owners = index de pièce par pixel du canvas
//    getReport()                     -> <report.json> + `pixels` par entrée, en coordonnées sprite
//    createSnapshot(label)           -> { id, label, at, author }
//    restoreSnapshot(id)             -> void
//    exportProject(options)          -> { outputs, summary, warnings, qa }
//    subscribe(fn)                   -> unsubscribe ; author = 'app' (écrit par l'API) | 'external' ;
//                                       fn({ type: 'rig.changed' | 'anim.changed' |
//                                       'project.changed' | 'connection.lost' | 'connection.open', rev, author, at })
//    capabilities = { export: boolean, swaps: boolean }
//    demo = null | { loadExample(), externalEdit({ silent }) }   (démo uniquement)
// ============================================================================

import { createDemoBackend } from './demo-backend.js';
import { createHttpBackend } from './http-backend.js';

function pickBackend() {
  if (typeof location !== 'undefined') {
    const base = new URLSearchParams(location.search).get('api') || globalThis.ANIMAI_API;
    if (base) return createHttpBackend(base);
  }
  return createDemoBackend();
}

export const api = pickBackend();
export { ApiError, ConflictError } from './errors.js';
