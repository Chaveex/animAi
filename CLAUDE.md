# animAI

Outil **utilisable par Claude** pour animer des sprites **pixel art 2D** uploadés : l'outil construit un squelette de pièces rigides sur le sprite et l'anime **sans jamais déformer les pixels**. Sortie : spritesheet + JSON + GIF de preview + rapport QA.

## Principes non négociables

1. **Aucune déformation** : pas de smooth skinning, pas de mesh deformation, pas d'étirement. Seulement des pièces rigides déplacées/pivotées.
2. **Pas de sub-pixel** : toute position finale est un entier, tout pixel retombe sur la grille d'origine.
3. **Palette préservée** : jamais de nouvelle couleur (pas d'interpolation, pas d'anti-aliasing). Alpha strictement 0 ou 255.
4. **Claude est le rigger, pas un modèle ML.** L'auto-rigging ML échoue sur le pixel art. Claude voit le sprite et décide des pièces/joints ; l'outil exécute de façon **déterministe**.
5. **Boucle de feedback visuel** : chaque commande produit des images de contrôle que Claude peut regarder pour corriger.

## Interface Claude (CLI / JSON)

Interface primaire pour Claude = **CLI (ou MCP), entrées/sorties JSON**. L'humain dispose d'une **app visuelle** (voir section "App éditeur") qui lit/écrit les **mêmes fichiers projet** : CLI et app partagent un seul cœur, aucune logique dupliquée dans l'UI.

Flux type :

```
1. prepare   sprite.png            -> sprite nettoyé (grille réelle, alpha binaire) + palette.json
2. inspect   sprite.png            -> image NN x8 avec grille + coordonnées (pour que Claude "voie" les pixels)
3. (Claude écrit rig.json : pièces, joints, z-order)
4. rig       sprite.png rig.json   -> overlay squelette + pièces découpées + rapport
5. animate   rig.json --preset walk | --keyframes anim.json [--duration 0.8s | --frames 8 --fps 10] -> frames
6. validate  frames                -> rapport QA JSON (pass/fail)
7. export    frames --format spritesheet|godot|phaser|unity -> PNG + JSON + GIF
```

Chaque étape : sorties reproductibles, codes de retour clairs, erreurs lisibles (JSON).

### Images de contrôle (obligatoires)

- Overlay du squelette (os, joints, pivots) sur le sprite en NN x8.
- Label map colorée des pièces.
- Contact sheet de toutes les frames, zoomée NN.
- GIF/APNG de la boucle.

## Prétraitement d'entrée

- **Détecter l'échelle réelle du pixel** : beaucoup de "pixel art" est upscalé ou généré par IA avec grille non alignée. Retrouver la grille, downscale NN vers la résolution vraie.
  - Gros fichiers (ex. 1254 x 1254) : `prepare` trouve le facteur entier exact, sinon **estime la grille** (pas non entier, décalage, flou, JPEG) et rééchantillonne à la résolution réelle. Contrôle : `grid.png`. Détail : `docs/schemas.md`, section "Grands fichiers et grille non entière".
- **Détourage** : `rembg` ou seuillage couleur si fond uni, puis **binariser l'alpha** (supprimer la semi-transparence).
- Nettoyer artefacts JPEG / quantifier vers une palette propre. Extraire la palette (couleurs uniques).
- **Déclarer le type de vue** en entrée : side, front, 3/4, top-down (squelette et z-order dépendent de la vue).

## Rig (squelette de pièces rigides)

### Segmentation par masque de pixels

- **Label map** : chaque pixel du sprite appartient à une pièce. Pas de bounding boxes (les membres se touchent et se chevauchent).
- Claude fournit les régions (polygones/rectangles/pixels) dans `rig.json`, l'outil produit la label map et signale pixels non assignés.

### Squelette configurable (template JSON)

Humanoïde par défaut, mais template extensible (quadrupède, blob, oiseau...). Os optionnels (pas de cou, pas de bras...).

```text
Root (Bassin/Hips)
 ├── Torse (Spine)
 │    ├── Tête (Head)
 │    ├── Bras Droit (Upper Arm) ── Avant-bras ── Main
 │    └── Bras Gauche (Upper Arm) ── Avant-bras ── Main
 ├── Jambe Droite (Thigh) ── Shin ── Foot
 └── Jambe Gauche (Thigh) ── Shin ── Foot
```

- **Poids 100% sur un seul os** par bloc de pixels.
- **IK** pour pieds et mains (genoux/coudes se plient seuls).
- **Z-index par membre**, modifiable dans le temps (ex. bras gauche derrière le buste, puis devant).
- Props/armes = os attaché rigide.

### Problème des trous (disocclusion) — critique

Quand un membre tourne, la zone derrière est vide et le torse sous le membre n'existe pas dans le sprite.

- **Zones de chevauchement** aux joints : étendre les pièces sous leurs voisines.
- **Fill des pixels cachés** : compléter le torse/bassin sous les membres.
- **Pivot placé dans la zone de recouvrement** pour qu'aucun trou n'apparaisse dans l'amplitude prévue.
- Le rapport QA doit signaler les trous détectés (pixels transparents entourés de pixels opaques à l'intérieur de la silhouette).

## Rendu pixel art

- **Rotation** : préférer **RotSprite** (upscale Scale2x x8 → rotation → downscale) **ou angles discrets** (0, ±15, ±30, ±45, ±90). Jamais NN brut à angle libre (escaliers irréguliers).
- **Translations** arrondies à l'entier.
- **Snap-to-grid / clean-up** après chaque transformation : restituer la palette d'origine.
- **Contours** : l'outline 1 px se casse à la rotation → passe de cleanup d'outline. Limite connue : l'ombrage tourne avec le membre (lumière fixe en théorie). Documenter, ne pas prétendre corriger.
- Upscale temporaire x4/x8 (NN) autorisé pour localiser les joints, puis retour à la taille d'origine.

## Squelette vs frame-by-frame

| Critère | Squelette (rigging) | Frame-by-frame |
|---------|---------------------|----------------|
| Pixel art | Rendu "poupée de chiffon" si sprite < 64x64 | Idéal pour le style, difficile à générer de façon cohérente |
| Poids | Très léger (JSON + 1 image découpée) | Lourd (12 à 24 PNG par action) |

- Sprite **>= 64x64** : rigging par pièces rigides.
- Sprite **<= 32x32** : rigging médiocre → v2 (frame-by-frame / variantes manuelles). Hors scope MVP.

## Animation

- **Pixel art = peu de frames, timing stepped** : 4 à 8 frames par cycle, held frames, pas d'interpolation fluide.
- Principes : bob vertical du bassin, balancier bras/jambes en opposition, anticipation avant attaque, secondary motion minimal.
- **Durée configurable** : l'utilisateur/Claude choisit la durée de l'animation (secondes ou ms) et/ou le nombre de frames + fps. Paramètres : `--duration`, `--frames`, `--fps` (deux des trois suffisent, le troisième est déduit ; incohérence = erreur claire).
  - Le preset est **rééchantillonné** sur la durée demandée (timing stepped conservé, held frames proportionnelles).
  - Durées par frame possibles (ex. frame d'impact tenue plus longtemps) dans `anim.json`.
  - Nombre de frames borné pour rester lisible en pixel art (défaut 4 à 8, plus autorisé mais signalé en QA).
  - La durée finale est écrite dans le JSON d'export (tags/durées par frame) et le GIF.
- **Boucle fermée** : frame N → frame 0 doit enchaîner proprement (vérifié en QA).
- **Presets paramétriques** (JSON, retargetables sur tout squelette) : idle, walk, run, jump, attack, hurt, death.
- **Keyframes custom** : Claude peut écrire `anim.json` (os, rotation/position par frame, durée).
- **Miroir horizontal** gratuit pour gauche/droite ; 4/8 directions en v2.
- **Hors scope v1** : cheveux, cape, éléments souples (éventuellement secondary motion simple par décalage retardé plus tard).

## Export

- **Canvas constant** : bbox max calculée sur toutes les frames, même padding partout (pas de rognage, pas de saut).
- **Pivot identique** sur toutes les frames, entre les pieds au sol (0.5, 1.0 relatif). Pivot qui saute = personnage qui tremble.
- Formats : spritesheet PNG transparente + JSON de tags/durées (Aseprite-compatible, Godot SpriteFrames, atlas Phaser/Unity) + GIF/APNG preview.
- Avancé (v2) : texture découpée + JSON squelette (Spine JSON / DragonBones).

## QA automatique (rapport JSON pass/fail)

- Nombre de couleurs <= palette source, aucune couleur nouvelle.
- Alpha strictement 0/255.
- Pas de pixels orphelins.
- Pas de trous internes à la silhouette.
- Pivot stable, canvas constant.
- Boucle fermée.
- Toutes les pièces assignées (aucun pixel source perdu ou dupliqué par erreur).

## App éditeur (visualiser + bidouiller à la main)

Objectif : voir ce que fait l'outil/Claude, et corriger à la main (pièces, joints, z-order, keyframes) sans passer par le JSON. Conçue et relue avec une **exigence UX/UI d'expert** : checklist de revue en fin de section.

### Principe d'architecture

- **App web locale** : backend Python (FastAPI) exposant le cœur (les mêmes fonctions que la CLI) + frontend canvas. Gradio/Streamlit trop limités pour l'édition pixel par pixel.
- **Source de vérité = fichiers projet** (`rig.json`, `anim.json`, sprite nettoyé). L'app et Claude éditent les mêmes fichiers.
- **Sync live** : file watcher. Quand Claude modifie `rig.json`, l'app se met à jour en direct ; quand l'humain édite, l'app écrit le fichier. Conflit (écriture concurrente) = message clair + choix, jamais d'écrasement silencieux.
- **Undo/redo illimité** par session + historique de versions du projet (snapshots nommés, "avant/après Claude").

### Écrans et zones

- **Viewport central** : sprite en zoom **entier uniquement** (x1, x2, x4, x8...), `image-rendering: pixelated`, jamais de flou. Pan/zoom molette, grille de pixels activable, règles/coordonnées au survol (x,y + couleur du pixel).
- **Gauche — Hiérarchie** : arbre des os/pièces, visibilité (œil), verrouillage, renommage, glisser-déposer pour re-parenter, z-order réordonnable.
- **Droite — Inspecteur** : propriétés de la sélection (pivot, rotation, z-index, IK on/off, poids), valeurs numériques éditables avec scrub.
- **Bas — Timeline** : frames, keyframes par os, durée par frame, play/pause/loop, scrub, **onion skin** (frames précédente/suivante en transparence), contrôles durée/fps/nb de frames.
- **Panneau QA** : liste des problèmes du rapport ; clic = saut à la frame et au pixel fautif, surligné.

### Outils d'édition

- **Sélection** de pièce (clic sur pixel = pièce propriétaire).
- **Pinceau / remplissage / lasso** pour assigner des pixels à une pièce (édition de la label map), gomme = non assigné.
- **Déplacer joint / pivot** (snap entier, flèches clavier = 1 px).
- **Poignées IK** sur pieds/mains.
- **Réglage z-order** par pièce, par frame.
- **Ajout/suppression d'os** et choix du template de squelette.

### Calques d'affichage (toggles)

Squelette · label map colorée · zones de chevauchement · **trous détectés** (alerte) · pivots · grille · onion skin · sprite original en transparence (comparaison).

### Principes UX

- **WYSIWYG strict** : l'aperçu = le rendu exporté, pixel pour pixel (même moteur de rendu que la CLI, pas de ré-implémentation côté UI).
- **Feedback immédiat** : toute modification re-rend la frame courante en < 100 ms ; rendu complet en tâche de fond avec indicateur.
- **Pas de modal bloquante** pour l'édition courante ; erreurs inline et actionnables ("3 pixels non assignés — les voir").
- **Raccourcis clavier** pour tout (outils, play, frame ±1, undo/redo, zoom) + palette de commandes ; cheat-sheet accessible via `?`.
- **Découvrabilité** : état vide avec drag & drop de l'image, étapes guidées (Préparer → Rigger → Animer → Exporter), infobulles courtes.
- **Distinguer humain vs Claude** : les modifications de Claude apparaissent dans l'historique avec leur auteur ; possibilité d'annuler un lot Claude d'un coup.
- **Accessibilité** : couleurs de label map distinguables (palette daltonien-safe + motifs/numéros), contraste suffisant, navigation clavier, thème clair/sombre.
- **Cohérence visuelle** : un seul design system (tokens couleurs/espacements/typo), UI neutre pour ne pas fausser la perception des couleurs du sprite (fond de viewport gris neutre ou damier réglable).
- **Export guidé** : dialogue avec résumé (taille canvas, nb frames, durée, pivot, formats) avant écriture.

### Checklist de revue UX/UI (à passer avant chaque release)

- [ ] Un nouvel utilisateur va de l'upload au GIF exporté sans doc.
- [ ] Aucun flou ni zoom non entier dans le viewport.
- [ ] Toute action est annulable.
- [ ] L'état de sync avec Claude est toujours visible (qui a modifié quoi, quand).
- [ ] Chaque erreur QA est cliquable et localisée.
- [ ] Tout est faisable au clavier.
- [ ] Contraste et daltonisme vérifiés ; thème sombre OK.
- [ ] L'aperçu est identique à l'export (test pixel-perfect automatisé).

## Architecture

- Python ; Pillow + numpy (+ opencv si besoin). `rembg` pour le détourage.
- Structure : `core/` (logique pure, sans I/O UI) · `cli/` · `server/` (FastAPI) · `app/` (frontend). CLI et app n'appellent que `core/`.
- Pipeline modulaire : chaque brique (prepare, segment, rig, animate, render, validate, export) testable séparément.
- Tests : 3 à 5 sprites de référence (tailles/styles différents) en fixtures, tests de non-régression **pixel-perfect**.

## Scope MVP (v1)

- Humanoïde, vue side, sprite **>= 64x64**.
- Rig via `rig.json` écrit par Claude (avec overlays de contrôle).
- 3 presets : idle, walk, attack.
- Export spritesheet + JSON + GIF + rapport QA.
- App éditeur minimale : viewport entier-zoom, hiérarchie, assignation de pixels aux pièces, timeline + onion skin, panneau QA, sync live avec Claude.

**v2** : sprites <= 32x32 (frame-by-frame/warping global), top-down 4/8 dir., Spine JSON, éléments souples, autres morphologies.

## Équipe (agents)

Définitions dans `.claude/agents/`. Contrat de données partagé : `docs/schemas.md`.

| Rôle | Agent | Propriété |
|------|-------|-----------|
| Orchestrateur | session principale | plan, découpage, arbitrages, intégration, `CLAUDE.md` |
| Lead dev | `lead-dev` | `animai/core/`, `animai/cli/`, `animai/server/`, `docs/schemas.md` |
| Dev / testeur | `dev-tester` | `tests/`, `fixtures/` |
| Expert UX/UI | `ux-ui-expert` | `app/`, `docs/ux-spec.md` |
| Expert animation 2D | `animation-expert` | `animai/presets/`, `docs/animation-guide.md`, essais produit |

Règles : chacun n'écrit que dans sa propriété ; un besoin hors périmètre remonte à l'orchestrateur. Le testeur et l'animateur ne corrigent pas le cœur, ils rapportent avec repro. Aucune release sans tests verts, revue UX passée et essai d'animation validé par l'expert animation.

## Conventions

- Langue de communication avec l'utilisateur : français.
- Toute opération sur les pixels préserve la palette d'origine.
