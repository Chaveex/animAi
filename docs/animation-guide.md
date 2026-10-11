# Guide d'animation animAI (cut-out pixel art)

Propriétaire : expert animation. Complète `docs/schemas.md` (qui reste la source de vérité du format).
Presets décrits ici : `animai/presets/idle.json`, `walk.json`, `attack.json`.

Statut : vague 3. Les presets ont été rendus par le moteur sur quatre sprites riggés à la main (`trials/hero64_x4`, `trials/rogue80_outline`, `trials/knight96`, `trials/mage64x80_bg`) et un rig minimal (`trials/hero_min`). Poses et durées des presets sont figées depuis la vague 2 ; la vague 3 n'a ajouté que `"rest_offsets": true` dans `walk.json`, sans effet sur un rig qui ne définit pas de décalage. Résultats de la grille : chapitre 7.

---

## 1. Conventions

Ces conventions sont maintenant inscrites dans `docs/schemas.md` (« Conventions du moteur ») et appliquées par le moteur. Rappel et intention.

### 1.1 Repère et unités

- Repère écran : origine en haut à gauche, **x vers la droite, y vers le bas**. Unité : pixel du sprite nettoyé (résolution vraie).
- Angles en **degrés**. Décalages `pos` en **pixels entiers**.
- Tous les presets supposent : **vue `side`, personnage tourné vers la droite** (+x = devant lui).
- Côté proche / côté lointain : un personnage qui regarde vers la droite montre son **flanc droit**. Donc `*_r` = membres **proches** (devant le torse), `*_l` = membres **lointains** (derrière le torse).

### 1.2 Sens positif de rotation

**`rot` positif = sens anti-horaire à l'écran** (même sens que `PIL.Image.rotate(angle)` et que Spine).

```
x' =  x·cos(a) + y·sin(a)
y' = -x·sin(a) + y·cos(a)
```

Test de recette : un point situé 10 px **sous** le joint `(0, 10)`, tourné de `+90`, arrive à `(10, 0)`, donc **devant** le personnage.

| Pièce | `rot` positif | `rot` négatif |
|-------|---------------|---------------|
| Pièce qui pend sous son joint (bras, avant-bras, cuisse, tibia) | part **vers l'avant** | part vers l'arrière |
| Pièce qui monte au-dessus de son joint (`spine`, `head`) | bascule **vers l'arrière** | penche vers l'avant |
| Pied (pointe vers l'avant) | pointe **vers le haut** | pointe vers le bas |

Repères pour un bras : `0` = le long du corps, `+90` = horizontal devant, `180` = à la verticale au-dessus de l'épaule, `-90` = horizontal derrière, `-135` = en haut derrière. Un genou se plie avec un `shin` **négatif**, un coude avec un `forearm` **positif**.

### 1.3 Local vs global

- **`rot` est local** : relatif à l'os parent. L'angle monde d'un os = somme de son `rot` et de ceux de tous ses ancêtres. Faire tourner `spine` de 15° emporte la tête et les deux bras.
- Conséquence utile : pour qu'une pièce garde son orientation (et donc ses pixels d'origine), lui donner l'opposé de la somme de ses ancêtres. C'est ce que font les presets pour la tête dans l'attack et pour les pieds posés au sol.
- **`pos` est exprimé dans les axes de l'écran** (non tourné par le parent), s'applique au joint de l'os et **se transmet aux enfants**.
- Arrondi : accumulation en flottant le long de la chaîne, un seul arrondi par pièce.

### 1.4 Qualité de rotation : c'est l'angle monde qui compte

| Angle monde mod 90 | Qualité constatée |
|--------------------|-------------------|
| 0 | parfaite : pixels identiques à la source (vérifié : têtes et pieds d'appui intacts) |
| 45 | bonne, diagonales régulières |
| 15, 30, 60, 75 | correcte sur une pièce d'au moins 5 px de large ; bosses de 1 px sur les bords ; les détails de 1 ou 2 px (un oeil) sont déformés |

Ne jamais tourner une tête qui porte un oeil ou une bouche de 1 à 2 px : dans `trials/custom/hurt.json`, la tête à 30° monde transforme l'oeil de 1 × 2 px en un coude de 3 px.

### 1.5 Frames, durées, fps

- Chaque frame est une **pose complète**. Les presets listent le même jeu d'os dans toutes les frames, avec `rot` et `pos` explicites.
- **Stepped strict** : aucune interpolation.
- `fps` = cadence de base ; chaque `duration_ms` est un multiple entier de `1000 / fps`.
- Boucles : la dernière frame n'est pas une copie de la première.
- **Poses clés.** Chaque frame des presets porte un `label` (nom de la pose) et, pour les poses à garder, un `key` : plus le nombre est grand, plus la pose survit longtemps quand `--frames` ou `--fps` réduit le nombre de frames. Les valeurs sont données au chapitre 5. Dans une animation sur mesure, marquer au moins l'anticipation, l'impact et la dernière frame.
- Rééchantillonnage, vérifié par exécution (chapitre 7) :
  - `--duration` seule : toujours sûr, toutes les poses, proportions exactes. **C'est l'option à préférer pour l'attack**, la seule qui garde une frappe plus courte que les tenues.
  - `--frames N` ou `--fps` avec moins de frames que la source : les poses clés sont gardées par priorité, toutes les frames prennent la même durée. Walk : 2 frames = les contacts, 4 = contacts et passings, 6 = plus les downs (toujours symétrique) ; 3, 5 et 7 sont asymétriques par construction, à éviter. Attack : 4 = anticipation, frappe, impact, repos ; 5 ajoute le rebond ; à 3 la frame de repos saute (avertissement) et l'animation finit sur l'impact.
  - `--frames N` avec plus de frames que la source : les tenues sont dupliquées. Pour une boucle, choisir un multiple du nombre de frames (16 pour le walk) : à 12, le premier demi-cycle dure deux fois plus que le second (avertissement).
  - `--fps` seule sur un preset à tenues (attack à 10 fps, idle à 5 fps) : les tenues sont déformées, un avertissement donne les durées attendues et obtenues.

### 1.6 Z-order

- `z` plus grand = dessiné devant ; à z égal, la pièce définie en dernier est devant.
- Clé de l'override `z` d'une frame = nom d'os, valeur absolue, pas d'héritage. Vérifié dans `trials/custom/hurt.json` (bras lointain passé devant).
- Les presets ne contiennent aucun override `z` : en vue de côté stricte, la bascule serait une erreur.

### 1.7 IK

`anim.json` a un bloc `ik` par frame : `{"<nom ik du rig>": {"pos": [dx, dy], "rot": deg}}`. La cible est le joint de repos de l'os visé, déplacé de `pos`, **indépendamment du bassin** : `[0, 0]` garde le pied planté pendant que `hips` descend. Les deux os de la chaîne sont alors pilotés par le solveur et leurs `rot` de la frame sont ignorés.

- Les **presets** n'ont pas de bloc `ik` : ils sont en cinématique directe pure et ne dépendent pas des noms d'IK du rig.
- Dans une **animation sur mesure**, utiliser l'IK dès que le bassin descend de plus de 1 px. Exemple validé : `trials/custom/crouch_ik.json` (accroupissement de 7 px, pieds plantés au pixel près sur trois sprites). Les angles calculés ne sont pas discrets ; le rendu reste propre sur des membres de 5 px et plus.
- Un nom d'IK absent du rig est ignoré avec un avertissement : la jambe reste alors tendue et le pied suit le bassin sous le sol.

### 1.8 Miroir

Les presets regardent vers la droite. La version gauche s'obtient avec `animate --mirror` (frames retournées, `frames.json` cohérent) ou `export --mirror` (retourne au moment de l'export). Ne jamais changer le signe des angles à la main. Vérifié : les frames miroir sont le retournement exact, pixel pour pixel, des frames normales, le pivot devient `largeur du canvas - x`, et les deux chemins donnent la même spritesheet. Attention : `export --mirror` sur des frames déjà produites avec `animate --mirror` les remet à l'endroit.

---

## 2. Ce que les presets attendent d'un rig

| Preset | Os indispensables | Os qui enrichissent | Os ignorés |
|--------|-------------------|---------------------|------------|
| idle | `spine` | `arm_r`, `arm_l` | tous les autres |
| walk | `thigh_r`, `thigh_l` | `arm_*`, `shin_*`, `foot_*`, `forearm_*` | `spine`, `head`, `hand_*` |
| attack | `arm_r` | `spine`, `head`, `forearm_r`, `arm_l`, `thigh_*`, `foot_*` | `hand_*`, `forearm_l`, `shin_*` |

- **Os de pied fortement conseillés.** Depuis la vague 2, walk et attack contre-tournent `foot_r` et `foot_l` pour que le pied d'appui reste à plat (angle monde 0, pixels d'origine). Sans os de pied (pied fusionné au tibia), le pied tourne avec la jambe : le talon ou la pointe s'enfonce de 1 px sous la ligne de sol sur les frames de contact (mesuré sur `trials/hero_min`).
- Aucun preset ne référence `hand_*`. Une arme est une pièce rigide attachée à `hand_r` (ou à `forearm_r`).
- Un os absent donne un avertissement par os, pas d'erreur.
- Pose de repos attendue : debout, jambes verticales, bras le long du corps, pieds sur la ligne de sol.
- **Jambes dessinées côte à côte : régler un décalage de repos.** Si le sprite montre la jambe lointaine derrière et la jambe proche devant (cas des cinq sprites de référence), les deux demi-cycles du walk ne se ressemblent pas : quand la jambe proche avance le ciseau est large, quand elle recule les jambes se croisent. Le rig corrige cela avec `rest_offset` sur les deux cuisses (3.7). Sans décalage la marche reste lisible mais boite.

---

## 3. Bien rigger un sprite pour le cut-out pixel art

### 3.1 Découpage

- Une pièce = un bloc de pixels qui bouge d'un seul tenant. Pour un personnage de 45 à 60 px de haut : tête, torse, bassin (la ceinture), 2 bras, 2 avant-bras avec main, 2 cuisses, 2 tibias, 2 pieds. Mains séparées à partir de 70 px.
- **Une pièce de moins de 4 px de large ne supporte pas la rotation à 15 ou 30°** : le bras lointain de 3 px de hero devient un escalier irrégulier.
- Couper au milieu d'une zone de couleur unie, jamais sur un détail.
- Faire du **bassin une pièce à part réduite à la ceinture** : c'est elle qui masque les coutures (voir 3.5).

### 3.2 Où placer les joints

Le joint est le point fixe de la rotation : **au centre du cercle que forme le recouvrement entre la pièce et son parent**, jamais sur le bord de la silhouette.

| Joint | Placement |
|-------|-----------|
| `hips` (racine) | centre de la ceinture |
| `spine` | sur la taille, centré en x, dans la ceinture, 1 à 2 px sous son bord supérieur |
| `head` | base du crâne, sur la dernière rangée de la tête, centré sur le cou |
| `arm_*` | centre de la boule d'épaule : une demi-largeur de bras sous le haut du bras, au milieu de sa largeur |
| `forearm_*` | centre du coude |
| `thigh_*` | au milieu de la largeur de la cuisse, sur sa première rangée ou une rangée au-dessus (dans la ceinture) |
| `shin_*` | centre du genou |
| `foot_*` | cheville : première rangée du pied, à l'aplomb du milieu du tibia |

- Coordonnées entières (centre de pixel). Pour un membre de largeur paire, choisir le pixel côté intérieur du corps et faire le même choix pour le membre opposé.
- Les deux cuisses doivent avoir le même `y` de joint, les deux bras aussi.
- Vérifier sur `rig_overlay.png` : le joint doit être à égale distance des deux bords du membre. `rig_report.json` donne `joints.<os>`, le rayon du disque de matière autour du joint : **0 signifie que l'articulation n'est pas surveillée** par le check `holes` (joint posé au bord de la matière). Viser 1 au moins, 3 et plus pour épaule, taille et hanche.

### 3.3 `overlap` et zone cachée

Règle du moteur à avoir en tête : une pièce est complétée **sous les pièces dessinées devant elle**, avec ses propres couleurs. L'`overlap` se règle donc sur la pièce de **derrière**.

- Zone enclavée (automatique) : ce qui est entre deux pixels de la pièce sur une ligne ou une colonne. Le torse découpé de part et d'autre du bras proche récupère tout le dessous du bras. Rien à faire.
- `overlap` (manuel) : marge en plus, pour une articulation en ligne où rien n'est enclavé.

| Pièce de derrière | Sous quelle pièce de devant | `overlap` conseillé |
|-------------------|-----------------------------|---------------------|
| torse | ceinture, tête | 3 |
| cuisses | ceinture, main proche qui pend devant la hanche | 3 |
| cuisse | tibia (genou) | 2 à 3 |
| tibia | pied | 2 |
| bras | avant-bras (coude) | 2 à 3 |
| avant-bras | main | 2 |
| bras lointain | torse | 2 |
| ceinture | rien | 0 |

Piège rencontré (rogue) : donner un `overlap` de 3 à la ceinture placée devant fait déborder sa couleur en croix au-dessus et au-dessous, là où pendait la main. Mettre 0 sur la ceinture et reporter la marge sur les cuisses et le torse.

### 3.4 Éviter les trous de disocclusion

1. **Trou d'articulation** : `overlap` sur la pièce de derrière, joint au centre de la matière.
2. **Trou de découverte** (le membre s'écarte et montre ce qu'il cachait) : le moteur comble seul la zone enclavée par une pièce, et depuis l'étape 4 celle enclavée entre plusieurs pièces (le coin de hanche sous la main proche, entre les deux cuisses). Regarder quand même `rig/parts_sheet.png` : chaque pièce y est dessinée en x8 avec sa zone cachée encadrée. Une zone qui déborde là où elle n'a rien à faire (la main lointaine du knight, chapitre 7.3) se voit sur cette planche avant d'animer.
3. Membres lointains presque entièrement cachés : ils ne sont pas reconstruits. Le bras lointain des sprites de référence est dessiné **devant** le torse, son épaule reste donc accrochée au bord avant du buste : quand il part en arrière on ne voit qu'un moignon triangulaire. Ne pas lancer ce bras en arrière dans une animation sur mesure.

### 3.5 Ordre z en vue de côté (personnage tourné vers la droite)

Ordre retenu après essais, **ceinture devant le torse et devant les cuisses** :

| z | Pièces |
|---|--------|
| -20, -19, -18 | `arm_l`, `forearm_l`, `hand_l` |
| -10, -9, -8 | `thigh_l`, `shin_l`, `foot_l` |
| -5 | torse (`spine`) |
| -4, -3, -2 | `thigh_r`, `shin_r`, `foot_r` |
| 0 | ceinture (`hips`) |
| 30 | tête |
| 40, 41, 42 | `arm_r`, `forearm_r`, `hand_r` |

Pourquoi : la ceinture est la seule pièce du tronc qui ne tourne jamais. Placée devant, elle garde ses pixels d'origine et cache le bas du torse qui bascule et le haut des cuisses qui tournent. Avec le torse devant la ceinture (ordre de la vague 1 et des rigs de `fixtures/`), le bas du torse tourné dessine des créneaux sur la ceinture (attack 1 à 4, knight) et le haut des cuisses l'entaille (walk).

Autres vues (hors MVP) : en vue de face et de 3/4, la bascule `z` par frame devient utile (le bras qui recule passe derrière le torse).

### 3.6 Sprite à contour

Sur un sprite cerné d'un trait de 1 px, les membres dessinés à l'intérieur du corps (bras proche, bord intérieur des jambes, bout des pieds) n'ont pas de trait. Le moteur les borde après composition (`outline` dans `rig.json`, `"auto"` par défaut : rien à écrire, et rien n'est fait sur un sprite sans contour).

- **Garder `outline_mode: "outside"`** (défaut). Le trait est ajouté autour du membre, qui garde sa largeur ; la silhouette grandit de 1 px là où il n'y avait pas de trait. En `"inside"` le trait est pris sur le membre : un avant-bras de 5 px tombe à 3, celui du bras lointain (3 px) devient un filet noir et les mains se réduisent à 2 ou 3 px de couleur. Comparaison : `trials/rogue80_outline/frames/` et `frames_inside/`.
- Ce que la passe ne fait pas : la partie du membre encore devant le corps reste sans trait (comme dans le sprite), seul ce qui dépasse de la silhouette est cerné. C'est cohérent à l'oeil.
- Effets de bord acceptés en `"outside"` : un bras sorti du corps paraît 1 px plus épais de chaque côté ; un interstice de 1 px entre deux membres est bouché par le trait, ce qui crée parfois un trou d'épingle (signalé par la QA).
- La pose de repos reste identique au sprite.
- Garder `--padding` à 1 au moins, sinon le trait ajouté est coupé au bord du canvas.

### 3.7 Décalage de repos (marche symétrique)

Le walk suppose que les deux cuisses pivotent au même endroit. Sur un sprite aux jambes côte à côte, on ramène les deux joints l'un sur l'autre **pendant le walk seulement**, avec `rest_offset` dans le rig. Le preset `walk` porte `"rest_offsets": true` : il applique les décalages que le rig définit, et ne change rien si le rig n'en définit pas. `idle` et `attack` ne les appliquent pas (l'idle reste identique au sprite).

**Réglage conseillé : jambes seules, moitié de l'écart de chaque côté.** Avec `d = x du joint thigh_r - x du joint thigh_l` :

```json
"thigh_l": {"parent": "hips", "joint": [43, 60], "rest_offset": [4, 0]},
"thigh_r": {"parent": "hips", "joint": [50, 60], "rest_offset": [-3, 0]}
```

soit `thigh_l` de `+arrondi supérieur(d / 2)` et `thigh_r` de `-arrondi inférieur(d / 2)`. Les deux jambes se retrouvent au milieu de la ceinture. Exemples : `trials/<sprite>/rig_ro_center.json`.

Pourquoi pas `"rest_offsets": "auto"` :

- `auto` amène la jambe lointaine sous la jambe proche, donc sur la moitié avant du bassin. Le ciseau est aussi symétrique, mais tout le corps repose sur l'avant : la ceinture déborde de plusieurs pixels dans le dos (la marche à la hanche du knight) et le personnage paraît en déséquilibre sur les passings. Ni `overlap`, ni `fill`, ni l'ordre z ne le corrigent : rien n'est rempli à l'endroit que la cuisse quitte, et un `overlap` gonflé fait déborder la couleur de la ceinture (essai `trials/knight96/rig_ro_legs_overlap.json`). Répartir le décalage sur les deux cuisses supprime le problème.
- `auto` décale aussi le bras lointain. Ramené sur l'épaule proche, il disparaît presque entièrement derrière le torse, 1 à 2 px d'épaule dépassent dans le dos quand il recule, et il saute de 6 à 10 px en passant de l'idle au walk. **Ne pas décaler les bras.** Avec `auto`, écrire `"rest_offset": [0, 0]` sur `arm_l`.

Limites à connaître :

- Sur les passings, les deux jambes ne font plus qu'une colonne de la largeur d'une jambe sous un bassin deux fois plus large. C'est la vue de côté correcte, mais un personnage trapu paraît monté sur un poteau. On peut réduire le décalage (knight à +2 / -2 : colonne de 21 px au lieu de 18, ciseaux 30 / 20 au lieu de 27 / 23) : c'est un compromis entre symétrie et carrure.
- Passage idle vers walk : chaque cuisse saute de la valeur de son décalage (2 à 4 px avec le réglage centré, contre 3 à 7 px sur une seule jambe avec `auto`). Le pied d'une jambe se déplace de 4 à 8 px par frame dans le walk lui-même : le saut est plus petit qu'un pas et ne se remarque pas. Ce qui se voit est le changement de carrure des jambes entre l'idle (deux jambes côte à côte) et le passing (une colonne), comme dans une marche dessinée à la main.
- Une animation sur mesure qui demande les décalages (`"rest_offsets": true` ou `--rest-offsets on`) n'a plus de frame identique au sprite : sa pose « tout à zéro » montre les jambes superposées. Ne les demander que pour les cycles de déplacement (walk, run), pas pour un accroupissement ni une attaque sur place.
- Vérifié : le miroir (`--mirror`) et l'IK fonctionnent avec les décalages. Les frames miroir sont le retournement exact des frames normales ; dans `crouch_ik`, les deux pieds restent plantés sur leur position décalée.

---

## 4. Pièges de rendu et parades

| Défaut | Comment il se manifeste | Parade côté rig / animation | Parade côté moteur |
|--------|-------------------------|-----------------------------|--------------------|
| **Membre sans contour** | sur un sprite à contour, un membre dessiné à l'intérieur de la silhouette perd son trait en sortant du corps | laisser `outline` à `auto` et `outline_mode` à `outside` (3.6) | passe de contour (en place) ; mesure `outline_bare` par frame dans le rapport |
| **Ceinture crénelée** | le bas du torse tourné mord la ceinture | ceinture devant (3.5) | aucune nécessaire |
| **Escaliers** | bosses de 1 px sur les bords des membres à 15 et 30° | pièces d'au moins 5 px de large ; préférer 45 et 90° quand la pose le permet | rotation exacte aux multiples de 90 (en place) |
| **Pied qui s'enfonce** | pointe ou talon sous la ligne de sol | os de pied + contre-rotation (en place dans les presets) ; IK si le bassin descend | aucune |
| **Coin qui dépasse** | 1 px de tibia derrière le talon d'un pied à plat, 1 à 3 px de cuisse lointaine derrière la ceinture | arrondir le bas du tibia dans la région (`exclude` des coins) | aucune |
| **Trou d'épingle** | 1 ou 2 px transparents enfermés entre deux jambes qui se croisent, ou entre un bras cerné et le corps | aucune (espace négatif réel) | signalé par frame (`pinholes`, avertissement) sans faire échouer la QA |
| **Poupée de chiffon** | tout tourne en même temps, pas de poids | peu d'os animés par frame, frames tenues, tête et pieds d'appui à angle monde 0 | aucune interpolation (en place) |
| **Ombrage qui tourne** | la lumière du bras levé vient d'en bas | limite connue | aucune |
| **Main invisible** | une main couleur peau passe devant un visage couleur peau | garder le bras frappeur hors de la tête sur les frames tenues (en place dans l'attack) | aucune |

---

## 5. Les presets, pose par pose

Notation : angles locaux en degrés, `pos` en px. Ce qui n'est pas cité vaut 0.

### 5.1 idle (`idle.json`) : 4 frames, 1400 ms, 10 fps, boucle

Inchangé depuis la vague 1. Aucune rotation : toutes les pièces gardent leurs pixels d'origine. Le torse **descend** de 1 px à l'expiration et s'enfonce dans la ceinture ; les bras suivent avec une frame de retard.

| # | Durée | Pose | `spine.pos` | `arm_r.pos`, `arm_l.pos` | Intention |
|---|-------|------|-------------|--------------------------|-----------|
| 0 | 600 ms | inspiration, tenue | [0, 0] | [0, 0] | pose de repos exacte du sprite |
| 1 | 100 ms | début d'expiration | [0, 1] | [0, -1] | torse et tête descendent de 1 px ; les bras restent en place |
| 2 | 600 ms | expiration, tenue | [0, 1] | [0, 0] | les bras rejoignent le torse |
| 3 | 100 ms | début d'inspiration | [0, 0] | [0, 1] | torse et tête remontent ; les bras restent en bas une frame |

Marqueurs : `inhale` (key 2), `exhale_start`, `exhale` (key 1), `inhale_start`.

Constaté : frame 0 identique au sprite, bassin et jambes strictement immobiles, aucun trou. Seul écart : sur le sprite à contour, frame 3, 1 px de torse apparaît sans contour au-dessus de l'épaule lointaine pendant 100 ms.

### 5.2 walk (`walk.json`) : 8 frames, 800 ms, 10 fps, boucle

Marche tranquille. Demi-cycles strictement symétriques (frame `i + 4` = frame `i`, droite et gauche échangées). Torse et tête ne tournent pas.

| # | Pose | `hips.pos` | `thigh_r` / `shin_r` / `foot_r` | `thigh_l` / `shin_l` / `foot_l` | `arm_r` / `forearm_r` | `arm_l` / `forearm_l` |
|---|------|-----------|----------------------------------|----------------------------------|-----------------------|-----------------------|
| 0 | contact (jambe droite devant) | [0, 1] | +15 / 0 / -15 | -15 / 0 / +15 | -30 / 0 | +30 / +30 |
| 1 | down | [0, 1] | +15 / 0 / -15 | -15 / -45 / +30 | -15 / 0 | +15 / +15 |
| 2 | passing | [0, 0] | 0 / 0 / 0 | +15 / -45 / +30 | 0 / +15 | 0 / +15 |
| 3 | up | [0, 0] | 0 / -15 / +15 | +30 / -15 / 0 | +15 / +15 | -15 / 0 |
| 4 | contact (jambe gauche devant) | [0, 1] | -15 / 0 / +15 | +15 / 0 / -15 | +30 / +30 | -30 / 0 |
| 5 | down | [0, 1] | -15 / -45 / +30 | +15 / 0 / -15 | +15 / +15 | -15 / 0 |
| 6 | passing | [0, 0] | +15 / -45 / +30 | 0 / 0 / 0 | 0 / +15 | 0 / +15 |
| 7 | up | [0, 0] | +30 / -15 / 0 | 0 / -15 / +15 | -15 / 0 | +15 / +15 |

Toutes les frames durent 100 ms.

Marqueurs : `contact_r` et `contact_l` (key 3), `passing_r` et `passing_l` (key 2), `down_r` et `down_l` (key 1), `up_r` et `up_l` (pas de key). Les downs ont une priorité pour que `--frames 6` reste symétrique.

- **Contact** : ciseau, deux jambes tendues, deux pieds à plat au sol. Bras à l'extrême opposé des jambes.
- **Down** : la jambe avant reste tendue et plantée, la jambe arrière décolle, talon vers l'arrière. Bassin bas.
- **Passing** : jambe d'appui verticale, bassin haut. La jambe libre passe sous le corps, genou devant, pied à plat en l'air.
- **Up** : la jambe d'appui plie légèrement (talon qui se soulève, pied gardé à plat), la jambe libre s'allonge devant, pointe relevée, plus loin qu'au contact, puis revient se poser.

Règles de construction, toutes issues de l'essai :

1. **Appui à ±15° et bob de 1 px vers le bas.** Une jambe tendue de longueur `L` tournée de 15° remonte de `L·(1 - cos 15°)`, soit 0,7 à 1,4 px pour une jambe de 20 à 42 px : le bob compense. Seules les jambes en l'air montent à 30 et 45°.
2. **Jambe d'appui tendue au down.** En vague 1 elle pliait (tibia à -15) : la jambe pliée est plus longue de 0,3 à 0,7 px que ce que le bob absorbe, et le pied passait entièrement 1 px sous la ligne de sol sur les trois sprites.
3. **Pied d'appui à angle monde 0.** `foot` = opposé de `thigh + shin` sur les frames d'appui : le pied garde ses pixels d'origine et ne plante ni talon ni pointe. En vague 1 la pointe descendait de 1 à 2 px sous le sol à l'up et au contact arrière.
4. **Pied libre relevé** (+30 aux frames où le tibia est à -45) : sans cela la pointe d'une botte longue traverse le sol au passing (knight).

Résultat mesuré : rangée la plus basse identique sur les 8 frames pour les trois sprites à os de pied ; +1 px sur les frames de contact et de down sans os de pied.

Vitesse au sol : le pied d'appui recule en moyenne de `0,13 × L` px par frame, soit **`1,3 × L` px par seconde à 10 fps** (`L` = hanche à semelle). Le recul n'est pas régulier (0, puis 0,26 L, puis 0,13 L deux fois) : c'est le prix de la jambe tendue au down.

Rig réduit : sans `shin_*`, cuisses seules +15, +15, 0, 0, -15, -15, +15, +30. Sans `forearm_*`, balancier entier.

### 5.3 attack (`attack.json`) : 7 frames, 700 ms, 20 fps, non bouclé

Coup du bras proche, armé derrière la tête puis porté droit devant et rabattu. Fente, jambe proche devant.

| # | Durée | Pose | `hips.pos` | `spine` | `head` | `arm_r` / `forearm_r` | `arm_l` | `thigh_r` / `foot_r` | `thigh_l` / `foot_l` |
|---|-------|------|-----------|---------|--------|-----------------------|---------|----------------------|----------------------|
| 0 | 100 ms | élan | [0, 0] | 0 | 0 | -45 / 0 | 0 | 0 / 0 | 0 / 0 |
| 1 | 150 ms | armé, tenu (anticipation) | [0, 0] | +15 | -15 | -150 / +30 | +15 | 0 / 0 | 0 / 0 |
| 2 | 50 ms | frappe | [0, 1] | -15 | +15 | +105 / 0 | +15 | +15 / -15 | -15 / +15 |
| 3 | 150 ms | impact, tenu | [0, 1] | -15 | +15 | +60 / 0 | +15 | +15 / -15 | -15 / +15 |
| 4 | 100 ms | rebond | [0, 1] | -15 | +15 | +75 / +15 | +15 | +15 / -15 | -15 / +15 |
| 5 | 100 ms | récupération | [0, 0] | 0 | 0 | +30 / +15 | 0 | 0 / 0 | 0 / 0 |
| 6 | 50 ms | repos | [0, 0] | 0 | 0 | 0 / 0 | 0 | 0 / 0 | 0 / 0 |

Angles monde du bras frappeur : -45, -135 (avant-bras -105), +90, +45, +60, +30, 0.

Marqueurs : `windup`, `anticipation` (key 4), `strike` (key 3), `impact` (key 2), `rebound`, `recover`, `rest` (key 1).

- **0, élan** : le bras part en arrière et sort de la silhouette dans le dos. Corps droit.
- **1, armé tenu** : le torse bascule de 15° en arrière, le bras monte derrière la tête à 45°, avant-bras presque horizontal vers l'arrière. La tête contre-tourne (angle monde 0). 150 ms : c'est la frame que le joueur lit.
- **2, frappe** : 50 ms. Le torse passe de +15 à -15, le bras est tendu à l'horizontale devant (angle monde 90 : pixels exacts, portée maximale), le corps tombe en fente.
- **3, impact tenu** : le bras s'abat à 45° vers le bas. 150 ms. Frame à synchroniser avec la hitbox et le son.
- **4, rebond** : le bras remonte de 15°, le coude se relâche.
- **5, récupération** : le corps se redresse, les jambes se rassemblent.
- **6, repos** : identique au sprite au repos (vérifié pixel pour pixel), pour enchaîner sur idle ou walk.

Règles de construction issues de l'essai :

1. **Le bras frappeur ne passe pas devant la tête sur une frame tenue.** En vague 1 le bras montait par l'avant (+135 puis +180 local) : sur les trois sprites la main couleur peau se confondait avec le visage et le bras sans contour était illisible. L'armé se fait maintenant par l'arrière.
2. **Jambe proche devant dans la fente.** En vague 1 la jambe lointaine avançait : sur des sprites aux jambes côte à côte les jambes se croisaient et la fente rétrécissait la silhouette au lieu de l'élargir.
3. **Pieds à plat, jambes tendues** : même géométrie que le contact du walk. En vague 1 le tibia arrière plié à -15 plantait la pointe 2 à 3 px sous le sol.
4. **Le bras lointain reste à l'aplomb** (angle monde 0 pendant la fente). En vague 1 il partait en arrière et ne laissait voir qu'un moignon triangulaire devant le buste.

`hips.pos` n'est jamais animé en x. Les deux pieds s'écartent d'un coup à la frame 2 et se rassemblent à la frame 5.

Rig réduit : sans `forearm_r` l'arc reste complet. Sans `spine`, `head` tournerait seule de ±15° : rig déconseillé pour ce preset.

---

## 6. Grille d'évaluation du rendu

Protocole : pour chaque sprite et chaque preset, `animate`, `validate`, `export`, puis contact sheet, zooms et overlay. Un critère est **pass** ou **fail** ; tout fail est rapporté avec frame, pièce, pixel. **B** = bloquant. Les critères mesurables sont calculés par `trials/eval.py`.

### A. Intégrité des pixels

| Id | Critère observable | Pass si | |
|----|--------------------|---------|---|
| A1 | Couleurs de chaque frame | incluses dans la palette source | B |
| A2 | Alpha | uniquement 0 ou 255 | B |
| A3 | Idle frame 0 comparée au sprite nettoyé | identique pixel pour pixel | B |
| A4 | Pièces à angle monde 0 (tête, pieds d'appui) | pixels identiques à la source, hors pixels recouverts par une pièce de devant | B |
| A6 | Pixels orphelins | pas plus que dans le sprite | |

### B. Trous et coutures

| Id | Critère observable | Pass si | |
|----|--------------------|---------|---|
| B1 | Check `holes` du rapport QA, selon la définition du contrat : articulation ouverte (pixel transparent dans le disque de matière d'un joint) ou découverte non comblée. Le vide entre deux jambes ou entre un bras et le corps n'est pas un trou | réussi | B |
| B1b | Trous d'épingle : `metrics.frames[].pinholes` du rapport (vides fermés de 1 ou 2 px, espace négatif légitime) | au plus un par animation | |
| B2 | Taille (idle 1 à 3, attack 1 à 4) | aucune ligne transparente ni dent de plus de 1 px à la jonction torse / ceinture | B |
| B3 | Épaule proche (attack 0 à 4, idle 3) | aucun pixel transparent entre bras et torse ; flanc découvert rempli | B |
| B4 | Genoux, coudes, chevilles | pas d'encoche ni de coin qui dépasse de plus de 1 px | |
| B5 | Membres lointains | visibles et entiers quand ils sortent de derrière le corps | |

### C. Contours et escaliers

| Id | Critère observable | Pass si | |
|----|--------------------|---------|---|
| C1 | Sprites à contour : `metrics.frames[].outline_bare` du rapport (pixels de bord sans la couleur de contour) | 0 sur toutes les frames | |
| C1b | Sprites sans contour : la passe de contour ne fait rien | `outline` vaut `null` dans le rapport de rig | B |
| C1c | Sprites à contour : pose de repos | idle frame 0 et dernière frame de l'attack identiques au sprite | B |
| C2 | Outline interne parasite | aucun segment de contour de plus de 2 px au milieu d'une zone de couleur unie | |
| C4 | Bords des membres à 15 et 30° | pas de bosse de plus de 1 px | |
| C5 | Largeur d'un membre tourné | égale à la source à ±1 px | |

### D. Stabilité

| Id | Critère observable | Pass si | |
|----|--------------------|---------|---|
| D1 | Taille de canvas | identique sur toutes les frames | B |
| D2 | Pivot d'export | identique sur toutes les frames, et à la même place par rapport aux pieds au repos dans les trois presets | B |
| D3 | Idle : jambes | strictement immobiles sous le genou | B |
| D5 | `metrics.frames[].ground_offset` du rapport | 0 sur toutes les frames avec os de pied ; entre -1 et +1 sans | |
| D6 | Walk : tête | x constant, y varie de 1 px exactement | |
| D7 | Attack : pieds en frames 0, 1, 5, 6 | identiques à la pose de repos | |
| D8 | Deux exécutions de la même commande | sorties identiques octet pour octet | B |

### E. Lecture du mouvement (jugement d'animateur)

| Id | Critère observable | Pass si | |
|----|--------------------|---------|---|
| E1 | Walk : opposition | frames 0 et 4, bras proche du côté opposé à la jambe proche | B |
| E2 | Walk : symétrie des ciseaux. Largeur de la zone des jambes (rangées sous le joint des cuisses + 2) sur la frame 0 et sur la frame 4 | écart de 4 px au plus | |
| E3 | Walk et idle : boucle | le pas dernière vers première frame n'est pas plus grand que les autres (check `loop_closed` + lecture de la contact sheet) | B |
| E4 | Walk : appui | sur chaque frame un pied touche la ligne de sol | |
| E5 | Walk : z-order | membres lointains derrière le corps, proches devant, sur les 8 frames | B |
| E7 | Idle : vie | au plus 1 px de déplacement par pixel entre deux frames | |
| E8 | Attack : anticipation | sur la frame 1 seule, le bras armé dépasse de la silhouette et ne se confond pas avec la tête | |
| E9 | Attack : impact | les frames 1 et 3 sont les plus longues ; la frame 2 est celle où le bras va le plus loin en x | |
| E10 | Attack : retour | dernière frame identique au sprite au repos | B |
| E11 | Attack : tête | angle monde 0 sur toutes les frames | |
| E12 | Poupée de chiffon | aucune pièce détachée de son parent | |

### F. Timing et format

| Id | Critère observable | Pass si | |
|----|--------------------|---------|---|
| F1 | Durées exportées (JSON) | égales aux `duration_ms` du preset | B |
| F2 | Nombre de frames sans rééchantillonnage | idle 4, walk 8, attack 7 | B |
| F3 | Rééchantillonnage | `--duration` : mêmes poses, proportions exactes ; walk `--frames 4` = contacts et passings, `--frames 6` symétrique ; attack `--frames 4` = anticipation, frappe, impact, repos | |
| F4 | Os absent du rig | un avertissement par os, pas d'erreur | B |
| F5 | Miroir (`--mirror`) | frames = retournement exact des frames normales ; pivot = largeur du canvas - x ; `animate --mirror` et `export --mirror` donnent la même spritesheet | |
| F6 | Rapport QA | les 8 checks présents ; tout trou vu à l'oeil y figure | |

Verdict par sprite et par preset : **validé** si aucun fail bloquant et au plus 2 fails non bloquants ; **à corriger** sinon.

---

## 7. Résultats de la vague 2 (état final, étape 4)

Rigs écrits à la main dans `trials/<sprite>/rig.json`, ordre z du 3.5, presets finaux, passe de contour en `outside`. Les mesures viennent de `report.json` (`metrics`) ; A4, E2 et D8 viennent de `trials/eval.py`.

### 7.1 Grille par sprite

| Critère | hero64_x4 | rogue80_outline (contour) | knight96 (mains séparées) | mage64x80_bg (membres de 4 px) |
|---------|-----------|---------------------------|---------------------------|--------------------------------|
| A1 à A6 | pass | pass | pass | pass |
| B1, B2, B3 | pass | pass | pass | pass |
| B1b trous d'épingle | pass : walk f5, 1 px | **fail** : walk f0 et f7, 1 px chacun ; attack f1, 1 px | pass : walk f5, 2 px | pass : walk f6 et attack f1, 1 px chacun |
| B4 coins | pass | pass | **fail** : main lointaine prolongée par 6 à 11 px parasites (walk f0, f1, f2, f6, f7 ; attack f1 à f4) | pass |
| C1 bord sans contour | sans objet | pass : 0 px sur toutes les frames (22 à 78 avant la passe) | sans objet | sans objet |
| C1b passe inactive sans contour | pass, frames identiques à l'étape 2 | sans objet | pass (`outline: null`) | pass |
| C1c repos identique au sprite | pass | pass | pass | pass |
| C4, C5 | pass | pass | pass | pass |
| D1 à D8 (`ground_offset` 0 partout) | pass | pass | pass | pass |
| E1, E3, E5, E10 | pass | pass | pass | pass |
| E2 symétrie du walk, zone des jambes f0 / f4, sans décalage | fail : 21 / 10 | fail : 27 / 15 | fail : 34 / 17 | fail : 23 / 13 |
| E2 avec décalage centré (`rig_ro_center.json`) | pass : 16 / 14 | pass : 23 / 20 | pass : 27 / 23 | pass : 20 / 16 |
| E8, E9, E11, E12 | pass | pass | pass | pass |
| F1, F2, F4 | pass | pass | pass | pass |
| F3 rééchantillonnage | pass (7.2) | | | |
| F5 miroir | | pass | pass | |
| F6 rapport QA | pass : la repro de l'étape 2 (`rig_repro_hole.json`) n'a plus de trou | | | |

Verdicts : idle, walk et attack **validés** sur les quatre sprites (aucun fail bloquant, au plus 2 fails non bloquants par animation). L'asymétrie du walk disparaît avec le décalage de repos centré sur les deux cuisses (3.7) ; le rig minimal `hero_min` passe de 22 / 11 à 17 / 16. L'écart qui reste (2 à 4 px) vient du pied proche, dessiné plus long que le pied lointain. Avec le décalage : QA verte, `ground_offset` 0, aucun trou sur les quatre sprites.

### 7.2 Rééchantillonnage avec les marqueurs (`trials/knight96/resample2/`)

| Commande | Frames source gardées | Jugement |
|----------|-----------------------|----------|
| `walk --frames 4` | 0, 2, 4, 6 (contacts, passings) | bon |
| `walk --frames 6` | 0, 1, 2, 4, 5, 6 | bon, symétrique |
| `walk --frames 2` | 0, 4 | bon |
| `walk --frames 3`, `5`, `7` | 0, 2, 4 ; 0, 1, 2, 4, 6 ; 0 à 6 | asymétrique par construction, à éviter |
| `walk --frames 12` | tenues 133 ms sur le premier demi-cycle, 67 ms sur le second | boiteux, avertissement émis ; prendre 16 |
| `walk --fps 5` | 0, 2, 4, 6 | bon |
| `walk --duration 0.4s` | les 8, 50 ms chacune | bon |
| `attack --frames 5` | 1, 2, 3, 4, 6 (anticipation, frappe, impact, rebond, repos) | bon |
| `attack --frames 4` | 1, 2, 3, 6 | bon |
| `attack --frames 3` | 1, 2, 3 ; repos perdu, avertissement | conforme à la priorité demandée ; finit sur l'impact |
| `attack --frames 6` | 0, 1, 2, 3, 4, 6 | bon |
| `attack --fps 10` | les 7, 100 ms chacune ; avertissement sur les tenues | timing aplati, à éviter |
| `attack --fps 20` | 14 frames, tenues proportionnelles | bon |
| `attack --duration 0.35s` et `1.4s` | les 7, proportions exactes | bon |
| `idle --frames 2` | 0, 2 | bon |
| `idle --fps 5` | 7 frames, tenues 600 / 200 / 400 / 200 ; avertissement | acceptable |
| `idle --duration 2s` | les 4, 857 / 143 / 857 / 143 | bon |

Avec `--frames`, toutes les frames ont la même durée : la frappe de l'attack dure autant que l'anticipation. Seule `--duration` garde le rythme.

### 7.3 Défauts du moteur encore ouverts

1. **Main lointaine prolongée (knight).** `python -m animai.cli.main animate trials/knight96/rig.json --preset walk` : `frame_000.png` a 11 pixels de la couleur du gant (#8f563b) en (48 à 51, 40 à 44), accrochés sous la main lointaine ; ils étaient transparents à l'étape 2 (`trials/_prev/knight96/walk/frame_000.png`). Cause visible sur `rig/parts_sheet.png` : la zone cachée de `hand_l` s'étend de 5 px vers la gauche, sous le haut de la cuisse proche. Contournement `fill: "none"` sur `hand_l` (`trials/knight96/rig_fill_none_false_hole.json`) : le rendu redevient propre mais le check `holes` échoue à tort sur walk et attack.
2. Décalage de repos : livré en vague 3 et validé (3.7). Reste que `"rest_offsets": "auto"` décale aussi le bras lointain et met toute la correction sur la jambe lointaine ; le réglage qui donne le meilleur rendu (jambes seules, réparti sur les deux cuisses) doit être écrit à la main.
3. `walk --frames 12` : les frames en plus vont toutes au premier demi-cycle.
4. `outline: "none"` sur un sprite à contour : `outline_bare` vaut `null`, on perd la mesure au moment où elle servirait à comparer.
5. Limite, pas défaut : sur des membres de 4 px le rayon de surveillance des articulations est 0, l'avertissement correspondant revient à chaque `validate`.
