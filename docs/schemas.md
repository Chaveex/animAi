# Schémas de données (contrat entre core, CLI, serveur, app)

Source de vérité du format. Tout changement = validé par le lead dev + noté ici.
Coordonnées : pixels entiers, origine en haut à gauche du sprite nettoyé, x vers la droite, y vers le bas. Angles en degrés.

Journal des changements en fin de fichier.

## Conventions du moteur

Elles s'appliquent à `rig.json`, `anim.json` et aux presets. Détail et intention : `docs/animation-guide.md`, chapitre 1.

- **Joint** : `[x, y]` désigne le **centre du pixel** `(x, y)`.
- **Sens de rotation** : `rot` positif = **anti-horaire à l'écran** (comme `PIL.Image.rotate`). Pour un point `(x, y)` relatif au joint : `x' = x·cos a + y·sin a`, `y' = -x·sin a + y·cos a`. Test de recette : `(0, 10)` tourné de `+90` arrive à `(10, 0)`.
- **`rot` est local** (relatif au parent). Angle monde = somme le long de la chaîne.
- **`pos` est en axes écran** (non tourné par le parent), s'applique au joint de l'os et se transmet aux enfants.

```
angle_monde(B) = angle_monde(P) + rot(B)
joint_monde(B) = joint_monde(P) + R(angle_monde(P)) · (jB - jP) + pos(B)
pixels de la pièce = arrondi(joint_monde(B)) + R(angle_monde(B)) · (pixel - jB)
```

- **Arrondi** : les joints sont accumulés en flottant le long de la chaîne ; un seul arrondi par pièce, à la fin (demi vers le haut : `floor(v + 0.5)`). Toute pièce retombe sur la grille.
- **Rotation des pixels** : angle monde multiple de 90 = permutation exacte de pixels. Sinon RotSprite (Scale2x appliqué 3 fois, rotation, un échantillon par pixel de destination), ou plus proche voisin avec `--rotation nearest`. Aucune des deux ne crée de couleur ni d'alpha intermédiaire.
- **Chaque frame est une pose complète** : os absent = `rot 0`, `pos [0, 0]`. Aucune interpolation entre frames.
- **z** : plus grand = devant. À z égal, la pièce définie en dernier dans `parts` est devant.

## rig.json

```json
{
  "version": 1,
  "sprite": "sprite.png",
  "view": "side",
  "template": "humanoid",
  "pivot": [0.5, 1.0],
  "bones": {
    "hips":    {"parent": null,    "joint": [32, 40]},
    "spine":   {"parent": "hips",  "joint": [32, 36]},
    "head":    {"parent": "spine", "joint": [32, 20]},
    "arm_r":   {"parent": "spine", "joint": [38, 24]},
    "thigh_r": {"parent": "hips",  "joint": [35, 42]}
  },
  "parts": {
    "torso": {"bone": "spine", "z": 0, "region": {"rects": [[26, 22, 12, 18]], "pixels": []}, "overlap": 2},
    "arm_r": {"bone": "arm_r", "z": 1, "region": {"rects": [[38, 24, 6, 14]], "pixels": []}, "overlap": 1}
  },
  "ik": {"foot_r": {"chain": ["thigh_r", "shin_r"], "target_bone": "foot_r", "bend": -1}}
}
```

- `sprite` : chemin relatif au dossier de `rig.json` (ou absolu). Le sprite doit être nettoyé (`prepare`) : alpha strictement 0/255, sinon erreur.
- `view` : `side` | `front` | `3/4` | `top-down`. Hors `side` : avertissement (hors périmètre v1).
- `pivot` : `[fx, fy]` dans 0..1, défaut `[0.5, 1.0]`. Voir « Pivot et canvas ».
- `bones.<nom>.parent` : `null` pour une racine. Si le parent nommé est un os canonique absent du rig, l'os est rattaché au premier ancêtre canonique présent (avertissement). Tout autre parent inconnu = erreur. Cycle = erreur.
- `region` : union de `rects` (`[x, y, w, h]`), `polygons` (liste de listes de points `[x, y]`, au moins 3, remplissage Pillow contour inclus) et `pixels` (`[x, y]`), **moins** `exclude` (objet optionnel de même forme : `{"rects": [], "polygons": [], "pixels": []}`). Seuls les pixels opaques comptent. `rects`, `polygons`, `pixels`, `exclude` sont tous optionnels.
- Un pixel appartient à une seule pièce : la dernière définie gagne (avertissement avec le nombre de pixels disputés). Pixel opaque sans pièce = non assigné (avertissement, et échec du check `parts_assigned`).
- `z` (entier, défaut 0), `overlap` (entier >= 0, défaut 0), `fill` (`"own"` par défaut, `"copy"`, `"none"` ; `true` = `"own"`, `false` = `"none"`), `fill_color` (`"#RRGGBB"`, optionnel). Voir « Zone cachée et remplissage ».
- Une pièce sans aucun pixel est ignorée (avertissement).

- `outline` (`"auto"` par défaut, `"none"` ou `false`, ou `"#RRGGBB"`) et `outline_mode` (`"outside"` par défaut, ou `"inside"`) : voir « Passe de contour ».
- `fill_holes` (booléen, défaut `true`) : bouchage automatique des trous au rendu, voir « Bouchage des trous ». Autre valeur qu'un booléen = erreur.
- **`region` est obligatoire** dans chaque pièce et doit être un objet ; `{}` désigne une pièce sans pixel pour l'instant. Une pièce sans `region` est une erreur.
- **Clés inconnues** : toute clé que ce format ne définit pas (dans le rig, un os, une pièce, une région, `exclude`, une entrée `ik`) donne un avertissement `unknown key '<clé>' in <emplacement>: ignored`. Les clés commençant par `_` sont des commentaires, acceptées en silence.

### Zone cachée et remplissage

Chaque pièce est complétée **sous les pièces dessinées devant elle** au repos (z plus grand, ou z égal et définie après). Une pièce ne s'étend jamais sur une pièce située derrière elle ni sur un pixel non assigné : la zone cachée est donc invisible au repos, et **la pose de repos reste identique au sprite pixel pour pixel**.

**Zone cachée d'une pièce P** (calculée par l'outil, rien à dessiner) :

1. *Zone enclavée* : tout pixel appartenant à une pièce de devant et situé **entre deux pixels de P sur sa ligne, ou entre deux pixels de P sur sa colonne**. Exemple : le torse découpé de part et d'autre du bras proche récupère toute la surface du bras située entre ses deux flancs.
2. *Marge d'articulation* : la zone est ensuite dilatée de `overlap` pas 4-connexes, toujours uniquement dans des pixels de pièces de devant. C'est ce qui couvre une articulation en ligne (cuisse sous le tibia, torse sous le cou).

3. *Zone enclavée à plusieurs* : c'est du **corps**, jamais un membre. Un pixel d'une pièce F qu'aucune pièce de derrière ne couvre après les règles 1 et 2 est examiné sur sa ligne, puis sur sa colonne. On marche dans les deux sens (à travers les pixels de F et des pièces de devant, arrêt sur un pixel transparent ou non assigné) jusqu'à un pixel d'une pièce dessinée derrière F dont l'os n'est ni celui de F, ni son parent, ni un de ses enfants. Soient `A` et `B` les os des deux pièces rencontrées.
   - Le pixel n'est rempli que si `A` et `B` **dépendent du même os `P`** : ils sont frères de parent `P`, ou l'un des deux est `P` et l'autre son enfant.
   - Il est donné à **une pièce de l'os `P`** dessinée derrière F (celle qui est le plus devant), jamais à un membre rencontré en chemin. Si `P` n'a pas de telle pièce et que `A` et `B` sont frères, il va à la plus proche des deux pièces rencontrées (égalité : la plus devant).
   - Dans tous les autres cas, rien n'est rempli : aucune pièce n'a à exister là. Exemple : une main lointaine d'un côté et une cuisse de l'autre.
   - Une pièce en `fill: "none"` ne reçoit jamais rien par cette règle.

   Cas visé : la main qui pend devant la hanche, entre les deux cuisses ; les cuisses sont sœurs, filles de `hips`, c'est donc la pièce du bassin qui est prolongée sous la main. La marge `overlap` s'applique ensuite.

**Contenu de la zone cachée**, selon `fill` :

- `"own"` (défaut) : les **propres couleurs de P**. Propagation en largeur à l'intérieur de `P ∪ zone cachée`, à partir des pixels de P qui n'ont pas la couleur de contour (de tous ses pixels s'il n'y en a pas d'autre) : chaque pixel caché prend la couleur du pixel source le plus proche (distance 4-connexe mesurée dans la pièce ; à égalité, la couleur vient du voisin du dessus, puis de gauche, de droite, du dessous). Un pixel caché non atteignable prend la couleur source la plus fréquente de P. Si `fill_color` est donné, toute la zone cachée prend cette couleur, qui doit exister dans la palette du sprite (sinon erreur).
- `"copy"` : les pixels du sprite tels quels, donc les couleurs des pièces de devant (comportement de la vague 1).
- `"none"` : aucune donnée. `overlap` est alors sans effet, et les pixels de la zone que la pièce enclave **seule** (règle 1) sont listés comme manquants (voir le check `holes`). La règle 3 n'y ajoute rien.

**Contour.** Le sprite a un contour si une même couleur occupe au moins 60 % de son bord de silhouette (pixels opaques ayant un voisin 4-connexe transparent, le bord de l'image comptant comme transparent). Dans ce cas, en mode `"own"` sans `fill_color` : la couleur de contour ne sert jamais de source, et tout pixel caché situé sur le bord de silhouette du sprite reçoit la couleur de contour (le contour de la pièce de derrière se referme là où le membre de devant formait la silhouette).

Aucune couleur n'est inventée : toutes viennent de la palette du sprite. Limites : le remplissage est un aplat prolongé, pas un dessin (ni ombrage ni motif reconstruits) ; un membre lointain presque entièrement caché n'est reconstruit que là où il dépasse des deux côtés de ce qui le cache ; un membre dessiné à l'intérieur de la silhouette n'a pas de contour propre et n'en gagne pas en sortant du corps.

### Décalage de repos (marche symétrique)

Sur un sprite dessiné jambes côte à côte, la jambe lointaine est décalée de la jambe proche : les deux demi-cycles d'un walk ne partent pas de la même base et la marche est asymétrique. Le décalage de repos ramène un membre sur l'axe voulu **pendant une animation qui le demande**, sans modifier le sprite ni le rig au repos.

- **Valeur, dans le rig.** `bones.<os>.rest_offset: [dx, dy]` (entiers, axes écran). Ou, au niveau du rig, `"rest_offsets": "auto"` (défaut `"none"`) : pour chaque paire `thigh_l` / `thigh_r` et `arm_l` / `arm_r` présente, l'os lointain qui n'a pas de `rest_offset` explicite reçoit `joint(os proche) - joint(os lointain)`, ce qui superpose les deux joints. Un `rest_offset` explicite l'emporte toujours ; `[0, 0]` désactive le calcul pour cet os.
- **Interrupteur, dans l'animation.** `anim.json` : `"rest_offsets": true` (défaut `false`). La CLI peut forcer avec `animate --rest-offsets on|off`. Sans demande, **rien ne change** : le rendu est octet pour octet celui d'un rig sans décalage.
- **Effet.** Quand il s'applique, le décalage est ajouté au `pos` de l'os dans **toutes** les frames de l'animation : il déplace le joint de l'os, sa pièce et tout ce qui en dépend (tibia, pied). C'est une translation rigide, aucun pixel n'est modifié.
- **Pose de repos.** La garantie « frame au repos identique au sprite » vaut pour toute animation qui ne demande pas les décalages (c'est le cas de l'idle). Dans une animation qui les demande, une frame où tous les os sont à zéro diffère du sprite exactement des décalages. Passer d'une animation sans décalage à une animation avec fait donc sauter le membre de la valeur du décalage.
- **Remplissage des pixels cachés.** Calculé une fois sur le sprite au repos, sans tenir compte des décalages : la pièce décalée emporte sa zone cachée, et rien n'est rempli à l'endroit qu'elle quitte (le bassin n'est pas élargi).
- **Contour.** La passe tourne après la composition, comme d'habitude ; la garde de la pose de repos ne protège plus les pixels de la pièce décalée, qui sont bordés comme ceux d'un membre en mouvement.
- **IK.** La cible d'une chaîne est déplacée de la somme des décalages de son os cible et de tous ses ancêtres : la chaîne garde sa forme de repos.
- **Pivot et canvas.** Le pivot reste ancré sur la bbox du sprite au repos ; le canvas est la bbox des frames réellement rendues.
- **Miroir.** `dx` change de signe dans `frames.json`.
- **QA.** `frames.json` porte `rest_offsets: {<os>: [dx, dy]}`, les décalages effectivement appliqués (`{}` sinon). La cause 3 de `holes` (articulation déboîtée) ajoute ce décalage au point d'attache avant de mesurer l'écart : un décalage de repos est un déplacement voulu. Le disque d'articulation (cause 1) est contrôlé autour du joint déplacé : si le membre décalé n'est plus couvert à sa racine, c'est un trou.

Limites : le décalage rétrécit la silhouette à la racine du membre (la cuisse lointaine ne remplit plus le bassin de son côté) ; un bras lointain ramené sur l'axe du bras proche est presque entièrement caché par le torse ; `"auto"` ne connaît que les deux paires canoniques.

### Passe de contour

Sur un sprite à contour, un membre dessiné à l'intérieur du corps n'a pas de trait ; quand il sort de la silhouette, le moteur le borde. La passe s'exécute sur chaque frame, après la composition.

- **Couleur** : une valeur de `outline` qui n'est ni `"auto"`, ni `"none"`, ni `false`, ni `"#RRGGBB"` est une erreur qui nomme la clé (`rig.outline: invalid value 'black' …`). `outline: "auto"` prend la couleur de contour détectée (une même couleur sur au moins 60 % du bord de silhouette du sprite). Si le sprite n'a pas de contour, **rien n'est fait**. `"#RRGGBB"` impose une couleur, qui doit exister dans la palette (sinon erreur). `"none"` ou `false` désactive.
- **Bord de silhouette** d'une frame : pixels opaques ayant un voisin 4-connexe transparent (l'extérieur du canvas compte comme transparent).
- **Règle 1, silhouette.** Pour chaque pixel de bord qui n'a pas la couleur de contour : en mode `"outside"` (défaut), ses voisins 4-connexes transparents deviennent des pixels de contour ; en mode `"inside"`, le pixel lui-même prend la couleur de contour.
- **Règle 2, bord entre deux pièces.** Elle ne s'applique qu'aux pièces dont le bord sur les pièces de derrière est tracé dans le sprite d'origine : au moins 4 pixels propres touchant une pièce de derrière, dont 60 % ou plus ont la couleur de contour (`outline.inner_parts`). Dans une frame, un pixel visible d'une telle pièce qui touche un pixel visible d'une pièce de derrière prend la couleur de contour.
- **Garde de la pose de repos.** Un pixel de frame qui montre la même couleur que le sprite au même endroit n'est jamais modifié s'il était déjà un bord de silhouette du sprite (règle 1) ou s'il appartenait déjà à la même pièce (règle 2). La pose de repos reste donc identique au sprite pixel pour pixel, même si son contour a des lacunes.

Pourquoi `"outside"` par défaut : en `"inside"`, le trait mange un pixel de chaque côté du membre ; un avant-bras de 3 ou 4 px se réduit à un filet et les mains disparaissent. En `"outside"`, le membre garde sa largeur et la silhouette ne grandit que de 1 px, uniquement le long des bords qui n'avaient pas de trait. Il faut un `--padding` d'au moins 1 (défaut 2) pour que ce trait ne soit pas coupé au bord du canvas.

Limites : le trait ajouté est un liseré uniforme de 1 px, sans les nuances d'un contour dessiné ; en `"outside"`, un membre qui sort du corps paraît 1 px plus épais de chaque côté que lorsqu'il était devant le torse ; un interstice de 1 px entre deux membres peut être bouché par le trait.

### Bouchage des trous

Activé par défaut (`"fill_holes": false` dans le rig pour le couper). La passe s'exécute sur chaque frame, après la composition et **avant** la passe de contour. Elle ne fait qu'ajouter des pixels, toujours d'une couleur de la palette, et ne touche jamais à l'espace négatif légitime (vide entre les jambes, entre un bras et le corps).

Deux sortes de trou sont bouchées :

1. **Articulation ouverte** : un pixel transparent dans le disque qui doit rester plein autour d'un joint (rayon `joints.<os>` de `frames.json`, cause 1 du check `holes`).
2. **Fissure** : une zone transparente fermée (4-connexité) d'au plus 4 pixels, bordée par au moins deux pièces différentes. Une zone bordée par une seule pièce est la forme de cette pièce, elle reste vide. Une zone qui est déjà un vide fermé du sprite, au même endroit et entourée de pixels inchangés, reste vide : **la pose de repos n'est jamais modifiée**.

Couleur d'un pixel bouché : copie d'un voisin 4-connexe opaque. Priorité : une couleur autre que la couleur de contour s'il y a le choix, puis la pièce dessinée le plus derrière dans la frame (le corps continue sous le membre), puis haut, gauche, droite, bas. Le remplissage avance vers l'intérieur un anneau à la fois. Le pixel bouché appartient à la pièce du voisin copié (masquée avec elle dans l'éditeur, comptée dans `owners_runs`).

Un avertissement donne le compte par frame : `holes filled automatically ("fill_holes": false in rig.json to keep them): frame 5: 4 px`.

Limites : c'est un aplat copié, pas un dessin (ni ombrage ni motif) ; un vide fermé de plus de 4 px hors d'un disque d'articulation n'est pas bouché ; un trou sans aucun pixel opaque autour reste vide ; une articulation déboîtée (cause 3 de `holes`) n'est pas corrigée ; les déformations dues à la rotation ne sont pas concernées.

### IK deux os (optionnel)

`ik.<nom>` = `{"chain": [os1, os2], "target_bone": os3, "bend": -1 | 1}` avec la hiérarchie `os1 > os2 > os3` obligatoire.
`bend` (défaut `-1`) = signe du `rot` local de `os2` quand la chaîne se plie : `-1` pour un genou, `+1` pour un coude (personnage tourné vers la droite).
L'IK n'agit que si une frame de `anim.json` contient un bloc `ik` (voir plus bas). Les presets n'en ont pas : le bloc `ik` du rig est ignoré pendant leur lecture.

### Noms d'os canoniques (template `humanoid`)

`hips`, `spine`, `head`, `arm_r`, `forearm_r`, `hand_r`, `arm_l`, `forearm_l`, `hand_l`, `thigh_r`, `shin_r`, `foot_r`, `thigh_l`, `shin_l`, `foot_l`.

Tous optionnels sauf `hips`. Un preset qui référence un os absent du rig l'ignore (un avertissement par os).
Parents canoniques : `spine` > `hips` ; `head`, `arm_*` > `spine` ; `forearm_*` > `arm_*` ; `hand_*` > `forearm_*` ; `thigh_*` > `hips` ; `shin_*` > `thigh_*` ; `foot_*` > `shin_*`.
`*_r` = membres proches (devant le torse), `*_l` = membres lointains, personnage tourné vers la droite.

## anim.json

```json
{
  "version": 1,
  "name": "walk",
  "loop": true,
  "fps": 10,
  "frames": [
    {"duration_ms": 100,
     "bones": {"thigh_r": {"rot": 20, "pos": [0, 0]}, "hips": {"pos": [0, -1]}},
     "z": {"arm_l": -1},
     "ik": {"foot_r": {"pos": [0, 0], "rot": 0}}}
  ]
}
```

- `rot` en degrés autour du `joint` de l'os, `pos` = décalage en px. Absents = 0. **`pos` non entier = erreur.**
- `fps` = cadence de base (défaut 10). `duration_ms` absent = un tick (`1000 / fps`). Un `duration_ms` qui n'est pas un multiple entier du tick donne un avertissement.
- `z` = override de z-index par frame (optionnel). **La clé est un nom d'os** : la valeur remplace, pour cette frame, le `z` de toutes les pièces attachées à cet os (pas à ses enfants). Valeur absolue. Clé qui ne correspond à aucune pièce : ignorée avec avertissement.
- `ik` (optionnel, par frame) : `{"<nom ik du rig>": {"pos": [dx, dy], "rot": deg}}`. La cible est le joint de repos de `target_bone` déplacé de `pos` (entiers, axes écran, **indépendant du bassin** : `[0, 0]` garde le pied planté pendant que `hips` bouge). Les deux os de la chaîne sont tournés pour l'atteindre (degrés entiers), leurs `rot` de la frame sont ignorés. Le joint de `target_bone` est posé sur la cible et son angle **monde** vaut `rot` (défaut 0 = orientation de repos). Cible hors d'atteinte : chaîne tendue au maximum, avertissement.
- `key` (optionnel, par frame) : marque une **pose clé** que le rééchantillonnage doit garder. `true` = priorité 1, un nombre >= 0 = cette priorité (plus grand = gardé en premier), absent ou `false` = 0. `label` (optionnel) : libellé libre (`"contact"`, `"impact"`…), recopié dans `frames.json` et cité dans les avertissements.
- **Clés inconnues** : toute clé non définie ici (dans l'animation, une frame, la pose d'un os, une cible `ik`) donne un avertissement `unknown key '<clé>' in <emplacement>: ignored` ; par exemple `"rotation": 30` à la place de `rot`. Les clés commençant par `_` sont des commentaires.
- `rest_offsets` (booléen, défaut `false`) : demande l'application des décalages de repos du rig pendant cette animation (voir « Décalage de repos »). À mettre dans un walk ou un run, pas dans un idle.
- `name` absent = nom du fichier. `loop` absent = `true`.
- Durée totale = somme des `duration_ms`.

### Rééchantillonnage (`--duration` / `--frames` / `--fps`)

Jamais de pose interpolée : une frame de sortie est toujours la copie d'une frame source.

| Options données | Résultat |
|---|---|
| aucune | animation inchangée |
| `--duration` seule | **toutes** les frames source, dans l'ordre, durées multipliées par le même facteur (somme exacte en ms) ; `fps` multiplié par le facteur inverse |
| `--frames` seule | N frames de même durée sur la durée d'origine |
| `--fps` seule | `N = arrondi(durée × fps)` frames de `1000/fps` ms |
| `--frames` + `--fps` | durée = `N × 1000 / fps` |
| `--duration` + `--frames` | N frames de même durée, `fps = N / durée` |
| `--duration` + `--fps` | `N = durée × fps`, qui doit être entier, sinon **erreur** |
| les trois | doivent vérifier `frames / fps = durée` à 1 ms près, sinon **erreur** |

Quand un nombre de frames N est fixé :

- **N >= nombre de frames source** : chaque frame source garde au moins une frame de sortie ; les frames en plus vont une par une à la frame source dont la durée par frame de sortie est la plus grande ; à égalité, à celle qui est la plus éloignée dans le temps des frames déjà doublées (distance circulaire pour une boucle), puis à la première. Un walk de 8 frames porté à 12 double donc 0, 4, 2 et 6, et non les quatre premières. Une grille de frames égales ne peut pas toujours garder les tenues proportionnelles : si la durée d'une frame source s'écarte de plus de 10 % de sa valeur proportionnelle, un avertissement donne les durées attendues et obtenues (`resampling to N equal frames changes the holds…`). Cet avertissement est émis **même quand la répartition est la meilleure possible** : un walk de 8 frames porté à 12 double 0, 2, 4 et 6, ce qui est la bonne répartition, et avertit quand même que ces quatre frames durent 133 ms contre 67 ms pour les autres, parce que le rythme du cycle n'est plus régulier. C'est le cas de `--fps` seule sur un preset à frames tenues.
- **N < nombre de frames source** : il faut jeter des poses, jamais en inventer.
  1. Les **poses clés** d'abord (`key`) : priorité la plus haute, puis durée la plus longue, puis ordre, tant qu'il reste de la place. Une pose clé qui ne tient pas est citée dans un avertissement (`only N frames: key poses dropped: 2 (strike)`).
  2. Les places restantes vont, une par une, à la frame dont le début est le plus éloigné dans le temps de toutes les frames déjà gardées (distance circulaire pour une boucle ; égalité : la première). Si rien n'est encore gardé, la frame 0 est prise. Sans aucun marqueur, une boucle de 8 frames réduite à 4 garde donc 0, 2, 4, 6, et une animation non bouclée garde sa première et sa dernière frame.
  Les frames source perdues sont listées (`resampling to N frames drops source frames [...]`).

Exemple pour les presets : `{"duration_ms": 50, "key": 2, "label": "strike", "bones": {...}}`. Pour l'attack, marquer anticipation, frappe, impact et repos ; pour le walk, contacts (priorité 2) et passings (priorité 1).

`--duration` accepte `0.8s`, `800ms`, ou un nombre nu compris en secondes. Plus de 8 frames : avertissement.

## Pivot et canvas

- **Pivot ancré sur la pose de repos**, jamais sur la bbox de l'animation : `pivot` de `rig.json` est relatif à la bbox des pixels opaques du **sprite au repos**. `x = bbox.x + arrondi(bbox.w × fx)`, `y = bbox.y + arrondi(bbox.h × fy)`. C'est une coordonnée de **coin de grille** : `[0.5, 1.0]` = milieu du bord inférieur, la ligne de sol entre les pieds. Le personnage occupe donc la même place autour du pivot dans idle, walk et attack.
- **Canvas** = bbox de l'union de toutes les frames (pivot inclus) + `--padding` (défaut 2) de chaque côté. Identique pour toutes les frames d'une animation ; il change d'une animation à l'autre, le pivot exporté permet de les aligner.

## Miroir horizontal

- `animate --mirror` : chaque frame est retournée après le rendu (contour compris). `frames.json` porte `"mirror": true` et **toutes** ses coordonnées sont exprimées dans le sprite retourné : `x → largeur du sprite - 1 - x` pour `rest.bones`, `frames[].bones.joint`, `parts.missing`, `source.unassigned_first` ; `origin.x → largeur du sprite - (origin.x + largeur du canvas)` ; angles de signe opposé ; pivot (coin de grille) `x → largeur du canvas - x`. Le fichier reste donc cohérent pour `validate` et `export`.
- `export --mirror` : retourne les frames au moment de l'export (spritesheet et GIF), sans toucher au dossier de frames ; le pivot du JSON devient `largeur du canvas - x` et `meta.animai.mirror` vaut l'inverse de celui du manifeste.
- Le miroir ne change ni les angles des presets ni le rig : c'est l'image finale qui est retournée.

## Fichiers produits

### palette.json (`prepare`)

```json
{"version": 1, "sprite": "sprite.png", "size": [48, 86], "bbox": [16, 4, 20, 80],
 "scale_detected": 3, "background": "#ffffff", "count": 15,
 "colors": ["#2864c8"], "pixel_counts": [412]}
```

`colors` trié par fréquence décroissante. `bbox` = `[x, y, w, h]` des pixels opaques. `background` = couleur de fond retirée ou `null`.

### rig_report.json (`rig`)

```json
{"version": 1, "sprite_size": [48, 86], "pivot": [26, 84],
 "unassigned_count": 0, "unassigned": [[x, y]], "multi_assigned_count": 0,
 "rest_pose_exact": true,
 "bones": {"hips": {"parent": null, "joint": [24, 49]}},
 "joints": {"spine": 5, "arm_r": 2},
 "parts": {"torso": {"bone": "spine", "z": 20, "pixels": 252, "fill": "own", "hidden_pixels": 96,
                     "missing_pixels": 0, "bbox": [16, 21, 16, 27]}}}
```

`unassigned` est tronqué à 500 pixels. Champs ajoutés : `unmonitored_joints` (articulations de rayon 0), `thin_parts` (`{pièce: plus petit côté}` pour les pièces de moins de 4 px, qui supportent mal une rotation de 15 ou 30°), `outline` (ce que fera la passe de contour, ou `null`). `rest_pose_exact` = la pose de repos recomposée est identique au sprite. `hidden_pixels` = taille de la zone cachée remplie ; `missing_pixels` = pixels de zone enclavée laissés sans donnée (`fill: "none"`). `joints` : voir `frames.json`. `bbox` inclut la zone cachée.

### frames.json (`animate`, lu par `validate` et `export`)

```json
{"version": 1, "name": "walk", "loop": true, "fps": 10.0, "duration_ms": 800,
 "canvas": [48, 86], "origin": [8, 2], "pivot": [25, 82], "padding": 2, "rotation": "rotsprite",
 "source": {"sprite_size": [48, 86], "palette": ["#000000"], "orphans": 0,
            "unassigned": 0, "unassigned_first": null, "multi_assigned": 0},
 "rest": {"bones": {"hips": {"parent": null, "joint": [24, 49]}}},
 "parts": {"torso": {"bone": "spine", "z": 20, "fill": "own", "hidden_pixels": 96, "missing": []}},
 "joints": {"spine": 5, "arm_r": 2},
 "frames": [{"file": "frame_000.png", "duration_ms": 100, "pivot": [25, 82], "source_frame": 0,
             "bones": {"hips": {"angle": 0, "joint": [24, 50]}}, "z": {"arm_l": -1}}]}
```

- `canvas` = `[w, h]` ; `origin` = coordonnées sprite du coin haut gauche du canvas ; `pivot` en coordonnées canvas.
- `frames[].bones` = pose **monde** : `angle` (degrés, anti-horaire, dans `]-180, 180]`) et `joint` arrondi, en coordonnées **sprite** (ajouter `-origin` pour le canvas). `source_frame` = index de la frame source avant rééchantillonnage. `z` présent seulement s'il y a un override.
- `mirror` (booléen) et `outline` (`null`, ou `{color, mode, inner_parts, source_bare, source_border}` : réglage de contour appliqué, et nombre de pixels de bord du sprite sans contour / au total) sont toujours présents. `frames[].label` reprend le libellé de la frame source quand il existe.
- `source` = mesures faites sur le sprite, qui servent de référence à `validate`.
- `rest.bones` = le squelette au repos (après rattachement des parents absents), en coordonnées sprite.
- `parts.<nom>.missing` = pixels `[x, y]` (coordonnées sprite, pose de repos) de la zone enclavée de la pièce restés sans donnée. Vide sauf avec `fill: "none"`.
- `joints.<os>` = rayon entier du disque d'articulation à vérifier autour du joint de cet os (définition dans « report.json », check `holes`). `joints_rest.<os>` = le rayon de repos `r0` dont il est tiré.
- `outline_detected` = `null`, ou `{color, source_bare, source_border}` : le contour que **le sprite possède** (détection automatique), que la passe soit active, désactivée, ou qu'une autre couleur soit imposée par `rig.outline`. Un sprite sans contour donne `null` même si `rig.outline` impose une couleur ; la couleur imposée se lit dans `outline`.
- `rest_offsets` = `{<os>: [dx, dy]}`, décalages de repos appliqués à cette animation (`{}` si aucun).
- Frames : `frame_000.png`, `frame_001.png`... dans le même dossier, avec `contact_sheet.png` et `preview.gif`.

### Export `--format spritesheet`

`<name>.png` (frames en ligne, ou grille avec `--columns`), `<name>.gif`, et `<name>.json` au format tableau d'Aseprite :

```json
{"frames": [{"filename": "walk 0", "frame": {"x": 0, "y": 0, "w": 48, "h": 86}, "rotated": false,
             "trimmed": false, "spriteSourceSize": {"x": 0, "y": 0, "w": 48, "h": 86},
             "sourceSize": {"w": 48, "h": 86}, "duration": 100}],
 "meta": {"app": "animai", "version": "0.1.0", "image": "walk.png", "format": "RGBA8888",
          "size": {"w": 384, "h": 86}, "scale": "1",
          "frameTags": [{"name": "walk", "from": 0, "to": 7, "direction": "forward"}],
          "animai": {"name": "walk", "loop": true, "fps": 10.0, "duration_ms": 800,
                     "frame_size": {"w": 48, "h": 86}, "pivot": {"x": 25, "y": 82},
                     "pivot_normalized": {"x": 0.520833, "y": 0.953488}}}}
```

GIF : couleurs exactes et transparence 1 bit tant qu'il y a au plus 255 couleurs (au-delà : aperçu quantifié, avertissement) ; agrandi en plus proche voisin (`--gif-scale`, défaut 4) ; durées arrondies à 10 ms (minimum 20 ms) sur la ligne de temps cumulée, avec avertissement si elles diffèrent du JSON ; boucle infinie si `loop`, lecture unique sinon.
Formats `godot`, `phaser`, `unity` : non implémentés (code retour 2).

## report.json (QA)

```json
{"ok": true, "checks": [{"id": "palette", "pass": true, "detail": "", "frame": null, "pixel": null}]}
```

Checks : `palette`, `alpha_binary`, `orphans`, `holes`, `pivot_stable`, `canvas_constant`, `loop_closed`, `parts_assigned`.

Les 8 ids sont toujours présents. Un check réussi a une seule entrée. Un check en échec a **une entrée par frame fautive** (au plus 20), avec `frame` et le premier `pixel` fautif en coordonnées canvas. `ok` = toutes les entrées passent.

| Check | Échoue si |
|---|---|
| `palette` | une frame contient une couleur absente de la palette du sprite source |
| `alpha_binary` | un alpha différent de 0 et 255 |
| `orphans` | une frame a plus de pixels opaques sans voisin opaque (8-connexité) que le sprite source |
| `holes` | une frame contient au moins un pixel de trou, selon la définition ci-dessous |
| `pivot_stable` | le pivot n'est pas le même couple d'entiers sur toutes les frames, ou sort du canvas |
| `canvas_constant` | une image de frame n'a pas la taille `canvas`, ou le nombre d'images diffère du manifeste |
| `loop_closed` | animation `loop` dont le pas dernière → première frame est **nul** (dernière frame copie de la première) ou **plus grand que le plus grand pas du cycle majoré de 10 %** (marge contre le bruit de rotation : un walk symétrique dépasse parfois de 1 px). Pas = nombre de pixels qui diffèrent entre deux frames. Toujours réussi si `loop` est faux ou s'il n'y a qu'une frame |
| `parts_assigned` | au moins un pixel opaque du sprite n'appartient à aucune pièce (`pixel` = le premier, en coordonnées sprite). Les pixels disputés entre pièces sont mentionnés dans `detail` sans faire échouer |

### Mesures et avertissements

`report.json` a deux champs de plus, qui ne changent jamais `ok` :

```json
{"ok": true, "checks": [...],
 "metrics": {"unmonitored_joints": ["forearm_l"],
             "outline": {"applied": true, "color": "#140c1c", "source_bare": 0},
             "frames": [{"border": 200, "outline_bare": 0, "ground_offset": 0, "pinholes": []}]},
 "warnings": ["frame 6: pinhole of 1 px at [22, 45] (enclosed negative space, not a hole)"]}
```

| Mesure (par frame) | Sens |
|---|---|
| `border` | nombre de pixels de bord de silhouette |
| `outline_bare` | pixels de bord qui n'ont pas la couleur de contour. Mesuré dès que le sprite a un contour, **même si la passe est désactivée** (`metrics.outline.applied` vaut alors `false`), pour pouvoir comparer ; `null` seulement si le sprite n'a pas de contour (`metrics.outline` est alors `null`) |
| `ground_offset` | rangée opaque la plus basse + 1 - y du pivot : 0 = posé sur la ligne de sol, positif = sous la ligne, négatif = en l'air ; `null` si la frame est vide |
| `pinholes` | pixels `[x, y]` (canvas) des vides fermés de 1 ou 2 px qui ne sont pas des trous : espace négatif légitime, à regarder |

Avertissements émis (repris dans `warnings` de la commande `validate`) : un par frame ayant un trou d'épingle ; `outline: up to N of M border pixels without outline…` quand une frame a plus de bord nu que le sprite ; `ground: frames more than 1 px away from the ground line…` ; `joints placed on the edge of their limb (move them inside): …` pour les articulations dont le rayon de repos `r0` vaut 0 (joint posé sur le bord de la matière). Les articulations de rayon suivi 0, inévitables sur un membre de 3 ou 4 px, ne donnent plus d'avertissement : elles sont listées dans `metrics.unmonitored_joints`, et la cause 3 de `holes` les couvre.

### Définition d'un trou

Un trou est défini par sa **cause**, pas par sa forme. Il y en a trois. Tout le reste est de l'espace négatif légitime : le vide entre les deux jambes ou entre un bras et le corps n'est pas un trou, quelle que soit sa taille et qu'il soit fermé ou non.

**1. Articulation ouverte.** Pour chaque os non racine portant au moins une pièce, la *matière du membre* est l'union des données (pixels propres + zone cachée remplie) des pièces de cet os et de celles de son os parent. Au repos, `r0` est le plus grand entier tel que tous les pixels `(jx + dx, jy + dy)` avec `dx² + dy² <= r0²` appartiennent à cette matière (`j` = joint de l'os). L'os est suivi si le pixel du joint lui-même est de la matière, avec le rayon `r = max(r0 - 1, 0)` : c'est `joints.<os>` dans `frames.json`. Le pixel de marge tolère une encoche de 1 px sur le pourtour de l'articulation.
Dans une frame, avec `J = frames[i].bones.<os>.joint - origin` (coordonnées canvas) : **tout pixel `(Jx + dx, Jy + dy)`, `dx² + dy² <= r²`, transparent ou hors canvas, est un trou.**

**2. Découverte non comblée.** Pour chaque pièce dont `parts.<nom>.missing` n'est pas vide, d'os `B`, de joint de repos `j` (`rest.bones`), de joint monde `J` et d'angle monde `a` dans la frame (`frames[i].bones.<B>`) : un pixel transparent `t` (coordonnées canvas) est ramené dans la pose de repos par

```
(dx, dy) = t + origin - J
x = jx + 0.5 + dx·cos a - dy·sin a
y = jy + 0.5 + dx·sin a + dy·cos a
```

**`t` est un trou si `(floor(x), floor(y))` appartient à `missing`.**

**3. Articulation déboîtée.** Contrôle purement cinématique, qui tient quelle que soit la largeur du membre et qui voit aussi un membre détaché **devant le corps**, là où aucun pixel ne devient transparent. Pour chaque os `B` non racine portant une pièce (un os cité dans `parts.<nom>.bone`), de parent `P` : avec les joints de repos `jB`, `jP` (`rest.bones`), les joints monde `JB`, `JP` et l'angle monde `aP` du parent dans la frame (`frames[i].bones`),

```
(dx, dy) = jB - jP
A   = JP + (dx·cos aP + dy·sin aP, -dx·sin aP + dy·cos aP) + rest_offsets[B]      point où le parent tient l'articulation
gap = max(|JBx - Ax|, |JBy - Ay|)
```

**`B` est déboîté si `gap > joints[B] + 2`** (`joints[B]` = 0 si l'os n'est pas listé ; `rest_offsets[B]` = `[0, 0]` si l'os n'est pas dans `rest_offsets` de `frames.json`). Les 2 px couvrent l'arrondi des deux joints et un décalage voulu de 1 px (respiration de l'idle). L'entrée du rapport porte la cause `dislocated joint '<os>' (N px from where its parent holds it)` et le pixel `JB` en coordonnées canvas.

`holes` échoue dès qu'une frame a un pixel de trou. `detail` donne le nombre de pixels et les causes (`open joint '<os>'`, `part '<nom>' has no data under its front neighbour`), `pixel` le premier en coordonnées canvas (il peut être hors canvas pour une articulation qui sort du cadre). Tout est recalculable à partir de `frames.json` et des images de frames.

Limites : une encoche située au-delà du rayon `r` n'est pas vue ; un os dont le joint n'est pas posé dans la matière du membre n'est suivi que par la cause 3 ; avec `fill: "own"` ou `"copy"` la cause 2 ne peut pas se produire (la zone enclavée a toujours une donnée) ; la cause 3 ne voit pas un membre déplacé de `joints[B] + 2` px ou moins.

## Sortie CLI

Toute commande imprime **un objet JSON sur stdout** : `{"ok": bool, "outputs": {...}, "warnings": [...], "error": null|str}`. Code retour 0 = ok, 1 = erreur utilisateur, 2 = non implémenté/interne.

- Erreur d'usage (option inconnue, argument manquant) : même objet JSON, code 1.
- `validate` dont la QA échoue : `ok: false`, `error: "QA failed: <ids>"`, code 1, `report.json` écrit quand même et présent dans `outputs`.
- Les chemins de `outputs` sont absolus. Les messages sont en anglais, ASCII.

| Commande | Arguments et options | `outputs` |
|---|---|---|
| `prepare INPUT` | `--out DIR` (défaut `<stem>.animai/` à côté de l'entrée), `--bg auto\|none\|rembg\|#RRGGBB`, `--bg-mode flood\|key`, `--bg-tolerance N`, `--alpha-threshold N` (128), `--scale auto\|N\|PAS` (PAS = pas de grille non entier, ex. `19.6`), `--merge-colors N`, `--max-colors N`, `--zoom N` (8) | `sprite`, `palette`, `inspect`, `size`, `bbox`, `scale_detected`, `background`, `background_pixels_removed`, `colors`, et `grid` si la grille a été estimée |
| `inspect SPRITE` | `--out FICHIER.png\|DIR` (défaut `inspect.png` à côté du sprite), `--zoom N` (8), `--crop X,Y,W,H`, `--segments` | `inspect`, `size`, `bbox`, `zoom`, `colors`, `palette` (64 premières), et avec `--segments` : `segments` = `{"y": [[x0, x1, "#rrggbb"]…]}`, segments horizontaux d'une même couleur, `x1` inclus, lignes vides omises, limité à `--crop` |
| `rig SPRITE RIG` | `--out DIR` (défaut `rig/` à côté de `rig.json`), `--zoom N` (8), `--labels names\|numbers\|none` (étiquettes de l'overlay) | `overlay`, `labelmap`, `parts_sheet`, `report`, `parts` (nom → PNG), `unassigned_count`, `multi_assigned_count`, `rest_pose_exact`, `pivot`, `unmonitored_joints`, `thin_parts`, `outline`, `bone_numbers` (os → numéro affiché avec `--labels numbers`) |
| `animate RIG` | `--preset NOM` ou `--keyframes CHEMIN` (un des deux), `--sprite CHEMIN`, `--duration D`, `--frames N`, `--fps F`, `--out DIR` (défaut `frames/<name>/` à côté de `rig.json`), `--rotation rotsprite\|nearest`, `--padding N` (2), `--gif-scale N` (4), `--mirror`, `--rest-offsets on\|off` | `frames_dir`, `manifest`, `frames` (liste ordonnée), `contact_sheet`, `preview`, `name`, `frame_count`, `duration_ms`, `durations_ms`, `fps`, `loop`, `canvas`, `pivot`, `mirror`, `outline`, `rest_offsets` |
| `validate FRAMES_DIR` | aucune (écrit `report.json` dans le dossier) | `report`, `checks`, `failed`, `metrics` |
| `export FRAMES_DIR` | `--format spritesheet\|godot\|phaser\|unity`, `--out DIR` (défaut `export/` dans le dossier), `--columns N`, `--gif-scale N` (4), `--mirror` | `spritesheet`, `json`, `gif`, `format`, `frame_count`, `frame_size`, `sheet_size`, `pivot`, `duration_ms`, `mirror` |

`prepare` : alpha binarisé, puis détection de l'échelle (upscale entier exact uniquement), puis détourage, puis quantification éventuelle. `--bg auto` ne détoure que si l'image n'a aucune transparence et que ses quatre coins ont la même couleur. `flood` ne retire que le fond relié au bord ; `key` retire toute la couleur.
`prepare` avertit quand le plus grand côté du personnage (bbox des pixels opaques, pas la taille de l'image) est de 32 px ou moins. La planche `parts_sheet.png` de `rig` est au zoom `--zoom` ; les pixels de zone cachée y sont encadrés de magenta.
`animate` supprime les `frame_*.png` et le `report.json` déjà présents dans son dossier de sortie.
`export` n'exécute pas la QA : il avertit si `report.json` est absent ou en échec.

## Serveur de l'éditeur (`animai serve`)

`animai serve <dossier-projet> [--port 8765] [--app-dir DIR] [--open]` : imprime l'objet JSON habituel (`outputs.url`, `api`, `host`, `port`, `project_dir`, `app_dir`) puis sert jusqu'à l'arrêt du processus. Écoute **uniquement sur `127.0.0.1`** et refuse tout en-tête `Host` autre que `127.0.0.1` / `localhost`. Nécessite l'extra `server` (`pip install animai[server]`). `/` redirige vers `/index.html?api=/api` ; `app/` est servi en statique à la racine, l'API sous `/api`. `--open` ouvre le navigateur par défaut.

Le serveur est une couche fine sur `animai/core/project.py` ; le rendu, la QA et l'export passent par les mêmes fonctions que la CLI.

### Dossier projet

Source de vérité unique, partagée avec la CLI et les éditions à la main :

```
<projet>/sprite.png      sprite nettoyé (prepare ou import)
<projet>/palette.json
<projet>/rig.json
<projet>/anim.json       l'animation éditée dans l'app (optionnelle)
<projet>/frames/<name>/  et  <projet>/export/     écrits par un export
<projet>/.animai/snapshots/<id>/                  versions nommées
```

`GET /api/project` répond 404 tant que `sprite.png` ou `rig.json` manque. `rig.sprite` doit valoir `sprite.png`.

### Révisions, auteurs, conflits

- `rev` = 16 premiers chiffres hexadécimaux du SHA-1 du contenu du fichier. Opaque pour le client. Le `rev` de la label map est celui de `rig.json`.
- `at` = date de modification du fichier, en millisecondes epoch.
- `author` = `"app"` seulement si le fichier sur le disque est **l'état même** que l'API a écrit en dernier (même contenu et même date de modification) ; `"external"` sinon (CLI, éditeur de texte, Claude). Les mêmes octets réécrits plus tard par un autre processus sont donc `external`. Au démarrage tout est `external`.
- Toute écriture envoie `base_rev` (`null` pour créer `anim.json`). Si `base_rev` diffère du `rev` du disque : **409, rien n'est écrit**, corps `{error, doc: "rig"|"anim", rev, author, at, changed_paths}`. `changed_paths` = chemins pointés des feuilles qui diffèrent entre le fichier du disque et ce que la requête allait écrire (50 au plus).
- Erreurs : `{"error": "<phrase en français>", "details": ...}`. Quand la cause vient du cœur, `details` est un objet avec `code` (identifiant stable : `rig_invalid`, `anim_invalid`, `json_invalid`, `timing_inconsistent`, `preset_refused`, `image_refused`, `sprite_unreadable`, `render_failed`, `export_failed`, `labelmap_invalid`, `part_unknown`, `core_error`) et `core_message` (le message du cœur seul, en anglais). La phrase d'en-tête est en français ; quand la cause vient du cœur, son message (en anglais) est cité à la suite. 404 = ressource absente, 422 = contenu refusé, 500 = erreur interne.
- Les fichiers JSON écrits par le serveur ont le format de la CLI (indentation 2, fins de ligne LF).

### Routes

Numéros de `docs/ux-spec.md` § 13.2. Toutes sont implémentées.

| # | Route | Précisions par rapport à la spec |
|---|---|---|
| 1 | `GET /api/project` | `prepare.warnings` contient aussi les avertissements du rig et la raison d'un `rig.json` / `anim.json` invalide sur le disque. Les avertissements de `prepare` ne sont connus que pour un import fait pendant la vie du serveur. |
| 2 | `POST /api/project/import` | multipart `file`, `view`. `prepare` avec les options par défaut, puis `sprite.png`, `palette.json`, `rig.json` (template : 15 os canoniques placés d'après la bbox, une pièce vide par os), suppression d'`anim.json`. 422 : pas une image, vide, plus de 512 px après nettoyage. Remplace le projet sans `base_rev`. |
| 3 | `GET /api/sprite.png` | ré-encodé par l'encodeur du moteur (chunks `IHDR`, `IDAT`, `IEND` uniquement). 422 si l'alpha n'est pas binaire. |
| 4, 5 | `GET` / `PUT /api/rig` | le rig est validé par le cœur avant écriture (422) ; il est écrit tel que reçu. |
| 6 | `GET /api/labelmap` | `runs` coupés à chaque fin de ligne. `-1` = non assigné ou transparent. |
| 7 | `PUT /api/labelmap` | `runs` peuvent enjamber les lignes. `parts` doit ne citer que des pièces du rig. Les régions de **toutes** les pièces sont ré-encodées en `rects` + `pixels` (fusion verticale des segments de même étendue) : `polygons` et `exclude` disparaissent. Les labels posés sur des pixels transparents sont ignorés. |
| 8, 9, 10 | `GET` / `PUT` / `DELETE /api/anim` | validation par le cœur (422). |
| 11 | `POST /api/anim/preset` | le preset est écrit entier ; les os absents du rig donnent des `warnings`, pas une erreur. `frames`, `fps`, `duration_ms` optionnels. |
| 12 | `POST /api/anim/retime` | un, deux ou trois paramètres, règles du tableau « Rééchantillonnage ». 422 avec la phrase d'explication si incohérent. |
| 13 | `GET /api/render/frames/{i}.png` | identique octet pour octet à `frame_00i.png` de `animai animate <rig> --keyframes anim.json` quand `hide` est vide. `hide` retire des pièces sans changer le canvas. 404 sans animation ou hors bornes. |
| 14 | `GET /api/render/frames/{i}.json` | `{width, height, origin, joints, angles, pivot, duration_ms, parts, owners_runs}`. `origin` = position du (0,0) du sprite dans le canvas (l'opposé de `origin` de `frames.json`). `joints` = joints posés en coordonnées sprite ; `angles` = angles monde ; `pivot` = pivot en pixels **canvas** ; `owners_runs` = pièce visible par pixel du canvas, index dans `parts`, `-1` = vide. |
| 15 | `GET /api/report` | mêmes contrôles que `animai validate` sur l'état du disque. Sans `anim.json` : rapport de la pose de repos (une frame) au lieu d'un 404. Champ `pixels` en plus, voir ci-dessous. |
| 16, 17, 18 | `/api/snapshots` | copie de `sprite.png`, `palette.json`, `rig.json`, `anim.json`. `id` = horodatage. La restauration émet `project.changed`. |
| 19 | `GET /api/export/summary` | `{canvas: {width, height}, frames, duration_ms, fps, loop, pivot, name, formats: ["spritesheet", "gif"]}`, `pivot` en pixels canvas. |
| 20 | `POST /api/export` | exécute `animate` → `validate` → `export` de la CLI dans le dossier projet. `{outputs: {spritesheet: [png, json], gif: [gif]}, summary, warnings, qa: {ok, failed, report}}`, chemins absolus. Format inconnu ou non implémenté : 422. L'export a lieu même si la QA échoue ; `qa.ok` le dit. |
| 21 | `GET /api/events` | SSE : `rig.changed` / `anim.changed` `{rev, author, at}` (`rev: null` si supprimé), `project.changed` `{}`, commentaire `: ping` toutes les 15 s. |

Routes ajoutées à l'étape 3 (lecture seule) :

| Route | Sortie |
|---|---|
| `GET /api/sprite/segments?crop=x,y,w,h` | `{rev, width, height, segments}`, même contenu que `inspect --segments` |
| `GET /api/rig/diagnostics` | `{rev, joints, unmonitored_joints, thin_parts, outline, parts: {<pièce>: {bone, z, pixels, fill, hidden_pixels, missing_pixels}}}` |

`GET /api/report` porte aussi `metrics` et `warnings` (voir « Mesures et avertissements » ; `pinholes` y reste en coordonnées canvas). Les frames servies passent par la passe de contour, y compris avec `hide`.

Ajouts de l'étape 5 (aucune réponse existante ne perd de champ) :

| Route | Comportement |
|---|---|
| `GET /api/project` | champs ajoutés : `rig: {rev}`, `anim: {rev}` ou `null`, `prepare.warnings_coded`. |
| `PUT /api/labelmap` | **delta** : seules les pièces dont l'ensemble de pixels change sont réécrites. Pixel gagné : ajouté à `region.pixels` (et retiré de `exclude.pixels`). Pixel perdu : retiré de `region.pixels`, et ajouté à `region.exclude.pixels` si un `rect` ou un `polygon` le couvre encore. `rects`, `polygons` et les formes de `exclude` écrits à la main sont conservés. Comme la dernière pièce définie gagne, le résultat est recalculé et corrigé jusqu'à égalité ; s'il ne peut pas l'être (pixel voulu par une pièce mais exclu par un de ses propres `exclude.rects` / `polygons`), toutes les régions sont ré-encodées comme avant. Réponse : `{rev, regions, changed: [pièces modifiées], full_reencode: bool}`, `regions` donnant la région de chaque pièce telle qu'écrite. Label map identique à celle du disque : rien n'est écrit, même `rev`, pas d'événement. |
| `GET /api/report` | répond aussi quand aucune pièce n'a de pixel (juste après un import) : `ok: false`, `parts_assigned` en échec avec ses `pixels`, les sept autres contrôles réussis avec le détail `not applicable: no part has pixels yet`. Champ ajouté : `warnings_coded`. |
| `GET /api/rig/report` | `{rev, …}` + le contenu de `rig_report.json` pour l'état du disque (`pivot` en coordonnées sprite, `joints`, `unmonitored_joints`, `thin_parts`, `outline`, `bones`, et par pièce `pixels`, `fill`, `hidden_pixels`, `missing_pixels`, `bbox`). |
| `GET /api/rig/parts/{pièce}.png` | la pièce complète telle que le moteur la déplace (pixels propres + zone cachée remplie), sur un canvas de la taille du sprite. 404 si la pièce n'existe pas ; image vide si elle n'a aucun pixel. |
| `GET /api/rig/parts/{pièce}.json` | `{rev, name, bone, z, width, height, fill, bbox, pixels, hidden_pixels, missing, own_runs, hidden_runs}` : `own_runs` et `hidden_runs` sont des masques RLE ligne par ligne (`[valeur, longueur]`, 1 = dans le masque) des pixels propres et de la zone cachée remplie ; `missing` = pixels sans donnée (`fill: "none"`). |
| `POST /api/anim/preset`, `/api/anim/retime`, `/api/export` | champ ajouté : `warnings_coded`. |
| `POST /api/snapshots` | accepté dans un dossier sans projet ; la version porte `empty: true`. La restaurer supprime `sprite.png`, `palette.json`, `rig.json`, `anim.json` et répond `{"empty": true}` ; `GET /api/project` répond ensuite 404. Une restauration supprime désormais tout fichier projet absent de la version. |

`warnings_coded` = la liste `warnings` où chaque phrase devient `{code, params, message}`. `code` est stable, `params` contient les valeurs extraites (chaînes), `message` est la phrase d'origine. Codes : `unknown_key`, `bone_not_in_rig`, `z_override_unknown`, `ik_not_in_rig`, `ik_out_of_reach`, `bone_reparented`, `joint_outside_sprite`, `part_empty`, `part_overridden`, `pixels_multi_assigned`, `pixels_unassigned`, `view_out_of_scope`, `duration_off_grid`, `resample_key_poses_dropped`, `resample_drops_frames`, `resample_changes_holds`, `too_many_frames`, `gif_durations_rounded`, `gif_quantized`, `pinhole`, `outline_bare`, `ground_offset`, `joints_on_edge`, `not_validated`, `qa_failing`, `rest_pose_differs`, `semi_transparent_binarized`, `no_background_detected`, `background_not_found`, `background_remains`, `sprite_small`, `rig_invalid_on_disk`, `doc_invalid_on_disk`, et `other` pour une phrase non reconnue. La table est dans `animai/core/messages.py` ; les phrases sont reconnues par motif, pas produites avec leur code à la source.

`GET /api/anim` sans animation répond toujours 404 (inchangé pour ne pas casser le client). Recommandation : lire `anim` dans `GET /api/project` et n'appeler `GET /api/anim` que s'il n'est pas `null`.

**Événements.** Le disque est relu toutes les 0,3 s. Un changement externe n'est annoncé que si le fichier est un JSON complet **et** valide pour le cœur ; sinon rien n'est émis et la raison apparaît dans `GET /api/project`. Une écriture faite par l'API émet le même événement avec `author: "app"`, 0,15 s après la réponse HTTP pour que l'auteur de l'écriture connaisse sa nouvelle révision avant de recevoir l'écho.

### Décisions sur les huit points de `docs/ux-spec.md` § 13.4

1. **Plusieurs défauts par contrôle.** Plusieurs entrées de même `id` (une par frame fautive), déjà en place. Le champ `pixels: [[x, y]…]` est ajouté **dans la réponse de `GET /api/report` uniquement** : tous les pixels fautifs de l'entrée (500 au plus), liste vide pour une entrée réussie. Il est exprimé en **coordonnées sprite** (le repère dans lequel l'éditeur dessine), alors que `pixel` garde son sens actuel (coordonnées canvas pour une entrée liée à une frame). `report.json` écrit par la CLI n'a pas ce champ pour l'instant.
2. **Contrôle non exécuté.** N'existe pas : les 8 contrôles sont toujours exécutés, `pass` est toujours un booléen.
3. **Sens de `rot`.** Anti-horaire à l'écran (voir « Conventions du moteur »).
4. **`region.pixels`.** Ajoute seulement ; le retrait passe par `region.exclude`.
5. **Pixels non assignés.** Ils ne sont pas rendus (absents de toutes les frames) et font échouer `parts_assigned`.
6. **`pivot`.** `rig.pivot` est relatif à la bbox des pixels opaques du **sprite au repos**, pas au canvas. Le pivot en pixels du canvas est fourni par les routes 14 et 19.
7. **Animations par projet.** Une seule dans l'éditeur : `anim.json`. La CLI peut toujours rendre n'importe quel preset ou fichier de keyframes.
8. **Auteur.** `app` / `external` seulement : la CLI ne signe pas ses écritures.

## Journal des changements

Vague 1 (lead dev). Ajouts et précisions, aucun champ existant retiré.

1. Conventions du moteur écrites (sens de rotation anti-horaire, `rot` local, `pos` en axes écran, arrondi unique par pièce, joint = centre de pixel, pose complète par frame, sens du z). Fixées par l'expert animation, reprises telles quelles.
2. `region` : ajout de `polygons` et de `exclude` ; « pixels ajoutés/retirés » devient `pixels` (ajout) et `exclude` (retrait).
3. `overlap` : sémantique précisée (extension uniquement sous les pièces dessinées devant). Redéfini en vague 2, point 13.
4. `bones.parent` : rattachement automatique au premier ancêtre canonique présent.
5. `ik` : ajout de `bend` dans le rig et du bloc `ik` par frame dans `anim.json`.
6. `anim.json` : clé de `z` = nom d'os ; `pos` non entier = erreur ; défauts de `name`, `loop`, `fps`, `duration_ms`.
7. Rééchantillonnage : tableau des combinaisons d'options.
8. Pivot (ancré sur la bbox du sprite au repos, coin de grille) et canvas.
9. Nouveaux fichiers documentés : `palette.json`, `rig_report.json`, `frames.json`, JSON d'export.
10. `report.json` : plusieurs entrées possibles pour un même id en échec ; définition de chaque check.
11. Sortie CLI : options et clés de `outputs` par commande ; `validate` en échec QA = code 1 ; erreur d'usage = code 1.

Vague 2, étape 1 (lead dev) : remplissage des pixels cachés et définition d'un trou.

12. `parts.<nom>.fill` (`"own"` par défaut, `"copy"`, `"none"`) et `parts.<nom>.fill_color` ajoutés. Les rigs existants profitent du remplissage sans modification.
13. `overlap` **gardé et redéfini** : c'est la marge d'articulation ajoutée à la zone enclavée, elle-même calculée automatiquement. Son contenu suit `fill` : couleurs propres de la pièce par défaut, et non plus couleurs de la voisine de devant (l'ancien comportement reste disponible avec `fill: "copy"`).
14. Check `holes` : nouvelle définition par la cause (articulation ouverte, découverte non comblée). L'ancienne (vide fermé de 16 px ou moins, comparé au sprite) est supprimée.
15. `frames.json` : ajout de `rest`, `parts`, `joints` ; retrait de `source.hole_pixels` et `source.hole_max_area`.
16. `rig_report.json` : `parts.<nom>.overlap_pixels` remplacé par `fill`, `hidden_pixels`, `missing_pixels` ; ajout de `joints`.

Vague 2, étape 2 (lead dev) : serveur de l'éditeur. Aucun fichier écrit par la CLI ne change.

17. Section « Serveur de l'éditeur » : commande `animai serve`, dossier projet, révisions, routes, événements, décisions sur les huit points de la spec UX.
18. `pixels` (coordonnées sprite) ajouté aux entrées du rapport servi par `GET /api/report`, pas à `report.json`.
19. Extra `server` de `pyproject.toml` : `python-multipart` ajouté (import d'image), `watchfiles` retiré (surveillance par relecture périodique).

Vague 2, étape 3 (lead dev) : contour, trou de hanche, poses clés, clés inconnues, miroir, outils de rig.

20. `rig.outline` et `rig.outline_mode` ; section « Passe de contour ». Le rendu des sprites à contour change.
21. Zone cachée : règle 3, « zone enclavée à plusieurs » (ferme le trou sous la main entre les deux cuisses).
22. `anim.json` : `key` et `label` par frame ; rééchantillonnage vers moins de frames refondu (poses clés, puis frames les plus éloignées dans le temps) ; avertissement quand une grille égale déforme les tenues.
23. Clés inconnues signalées par un avertissement dans `rig.json` et `anim.json` ; clés `_…` = commentaires. `region` confirmé obligatoire (`{}` autorisé).
24. Miroir : `animate --mirror`, `export --mirror`, `mirror` dans `frames.json` et dans `meta.animai`.
25. `frames.json` : `mirror`, `outline`, `frames[].label`. `report.json` : `metrics` et `warnings` (ajouts ; `ok` et `checks` inchangés).
26. `rig` : `--labels`, `unmonitored_joints`, `thin_parts`, `outline`, `bone_numbers` ; `inspect --segments` ; planche des pièces au zoom demandé.
27. `prepare` : alerte de petite taille fondée sur la bbox du personnage (32 px ou moins) et non plus sur 64 px.
28. Serveur : routes `GET /api/sprite/segments` et `GET /api/rig/diagnostics` ; `metrics` et `warnings` dans le rapport.

Vague 2, étape 5 (lead dev) : régression du remplissage, QA cinématique, demandes de l'éditeur.

29. Zone cachée, règle 3 réécrite : le pixel va à une pièce de l'os dont dépendent les deux pièces rencontrées, et seulement si elles dépendent du même os. Corrige la main lointaine prolongée sous la cuisse (régression de l'étape 3). `fill: "none"` : `missing` ne contient plus que la zone enclavée par la pièce seule.
30. Check `holes` : troisième cause, « articulation déboîtée » (cinématique).
31. `frames.json` : `joints_rest`, `outline_detected`. `report.json` : `metrics.unmonitored_joints`, `metrics.outline.applied` ; `outline_bare` mesuré même contour désactivé ; l'avertissement de rayon 0 devient `joints placed on the edge…` (rayon de repos 0 seulement).
32. Rééchantillonnage vers plus de frames : les frames ajoutées sont réparties sur le cycle.
33. Serveur : auteur lié à l'état exact du fichier ; `PUT /api/labelmap` en delta ; rapport sans pièce ; routes `GET /api/rig/report`, `GET /api/rig/parts/{pièce}.png|.json` ; `rig` et `anim` dans `GET /api/project` ; `warnings_coded`, `details.code`, `details.core_message` ; snapshot d'un dossier vide.

Vague 3 (lead dev) : écarts avec le contrat, décalage de repos.

34. `outline_detected` décrit toujours le contour que le sprite possède ; `null` sur un sprite sans contour, même avec une couleur imposée.
35. `GET /api/report` juste après un import porte `warnings_coded`.
36. Erreur de `rig.outline` invalide : le message nomme la clé. Contrat précisé : l'avertissement « changes the holds » est émis aussi sur la meilleure répartition possible (walk de 8 à 12 frames) ; le comportement ne change pas.
37. Décalage de repos : `bones.<os>.rest_offset`, `rig.rest_offsets: "auto"`, `anim.rest_offsets`, `animate --rest-offsets on|off`, `rest_offsets` dans `frames.json` et dans la formule de la cause 3 de `holes`. Désactivé par défaut : aucun rendu existant ne change.

## Grands fichiers et grille non entière (`prepare`)

Un fichier de 1254 x 1254 px est presque toujours un petit sprite agrandi : chaque pixel du dessin
occupe un bloc de plusieurs pixels du fichier. `prepare` ramène le sprite à sa résolution réelle ;
tout le reste de la chaîne travaille à cette résolution.

`--scale auto` (défaut) essaie dans l'ordre :

1. **Facteur entier exact** (`scale_detected` entier, comme avant) : image nette, blocs alignés sur 0,0.
2. **Grille estimée** : blocs de taille non entière, décalés, flous ou bruités (image générée par IA,
   export redimensionné, JPEG). Le pas et le décalage des lignes sont estimés sur les bords de
   couleur, puis chaque bloc donne un pixel (médiane du centre du bloc, bords flous ignorés).
3. Sinon l'image est gardée telle quelle (`scale_detected: 1`).

Quand la grille est estimée :

- `outputs.grid` = `{"pitch": [px, py], "offset": [ox, oy], "confidence": 0..1, "source_size": [w, h], "regular": bool, "lines": null | [xs, ys], "image": ".../grid.png"}`.
  Une ligne de grille passe en `offset + k * pitch` (pixels du fichier source).
- `scale_detected` = pas moyen (nombre à virgule). `palette.json` reprend `grid`.
- `grid.png` : image de contrôle, la source avec la grille tracée dessus. **À regarder** : les lignes
  doivent tomber sur les bords des blocs.
- Un avertissement `pixel grid estimated: ...` est toujours émis.
- Les couleurs proches sont fusionnées (`--merge-colors`, défaut 16 dans ce cas, 0 sinon ; écart
  maximal par canal). `--merge-colors 0` les garde toutes.

Limites de l'estimation :

- Pas minimal 6 px source par pixel du dessin, au moins 8 blocs par axe, au moins 5 lignes de grille
  portant un bord sur chaque axe.
- Pixels carrés seulement : si les deux axes donnent des pas différents (plus de 2 %), pas de grille.
- Image nette (256 couleurs au plus) : 95 % des bords doivent tomber sur la grille. Image floue : 50 %.
- La fusion des couleurs proches se fait avant la recherche du fond : un fond uni mais bruité est
  alors reconnu et retiré.
- Grille irrégulière (pas qui varie dans l'image, fréquent sur les images IA) : gérée sur les images
  floues ou bruitées. Les lignes sont suivies une à une (écart au pas moyen : 20 % au plus) ;
  `grid.regular` vaut `false` et `grid.lines` = `[xs, ys]` donne chaque ligne. Les deux axes peuvent
  alors différer de 10 %. Sur une image nette, seule une grille régulière est cherchée.
- Grille irrégulière + grande zone sans aucun bord (aplat de plus de 10 pixels du dessin de large,
  sur toute la hauteur ou la largeur de l'image) : rien ne marque les lignes, leur nombre peut être
  faux d'une unité dans cette zone. Un dessin détaillé n'a pas ce cas.
- `--scale 19.6` force le pas ; le décalage est repris de l'estimation si elle concorde, sinon 0,0.

Un sprite réellement dessiné en haute résolution (pas de blocs) n'a pas de grille : il est traité à
sa taille. Ordre de grandeur mesuré pour un personnage de 270 x 950 px sur un canvas de 1254 px,
15 pièces : `rig` 5 s, `animate` 8 frames 7 s. Les décalages en pixels des presets (`pos`) ne sont
pas mis à l'échelle : un rebond de 1 px ne se voit pas à cette taille.
