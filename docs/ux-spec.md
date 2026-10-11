# Spec UX de l'éditeur animAI

Propriétaire : expert UX/UI. Périmètre : `app/` (frontend) et ce document.
Sources qui font foi : `CLAUDE.md` (section « App éditeur ») et `docs/schemas.md`. En cas de contradiction, ces deux fichiers gagnent et ce document est corrigé.

Dans tout le document, la colonne **Coquille** dit ce que fait réellement `app/` aujourd'hui : **oui** (fonctionne, vérifié), **partiel**, **non** (spécifié ici, pas encore construit).

État au terme de la vague 2 : l'éditeur est branché sur le vrai serveur (`animai serve`). Ce qui a été vérifié dans un navigateur contre ce serveur est listé au § 15 ; le mode démo (§ 14.3) reste disponible sans serveur.

---

## 1. Ce qu'est l'éditeur, et ce qu'il n'est pas

L'éditeur sert à **voir** ce que Claude et l'outil ont produit et à **corriger à la main** : pixels mal attribués, joint mal placé, z-order, pose d'une frame, durée. Il travaille sur les mêmes fichiers projet que Claude (`rig.json`, `anim.json`, sprite nettoyé).

Trois règles structurent toute l'interface :

1. **L'UI n'invente aucun pixel.** Toute image affichée (sprite, frame d'animation) est produite par le cœur et affichée telle quelle, à un zoom entier. L'UI ne calcule ni pose, ni rotation, ni rééchantillonnage, ni QA. Elle dessine par-dessus des repères (squelette, label map, grille) clairement distincts de l'image.
2. **Les fichiers projet sont la vérité.** Chaque modification est écrite immédiatement ; il n'y a pas de bouton « Enregistrer ». Une écriture qui écraserait un changement de Claude est refusée et remontée à l'humain.
3. **Tout se défait.** Chaque action qui modifie les données est annulable, y compris ouvrir une autre image et reprendre la version de Claude.

Hors périmètre v1 (rappel de `CLAUDE.md`) : sprites ≤ 32 px, vues autres que « de côté », éléments souples, export Spine.

## 2. Utilisateurs et tâches

| Utilisateur | Contexte | Ce qu'il vient faire |
|---|---|---|
| **Pixel artist / game dev** (principal) | A un sprite, veut une boucle de marche. Connaît Aseprite, pas le rigging. | Déposer l'image, vérifier le découpage proposé, corriger quelques pixels, régler la durée, exporter. |
| **Humain qui supervise Claude** | Claude écrit `rig.json` / `anim.json` en CLI pendant que l'app est ouverte. | Voir les changements arriver, comprendre qui a fait quoi, annuler un lot de Claude, corriger sans se marcher dessus. |
| **Expert animation / testeur** | Valide un preset ou un rendu avant release. | Inspecter frame par frame, lire le rapport QA, localiser un défaut au pixel. |

Tâches classées par fréquence, qui fixent les priorités d'interface :

1. Regarder le sprite et la frame courante à zoom entier, lire un pixel (coordonnées, couleur, pièce).
2. Réassigner des pixels à une pièce (pinceau, gomme).
3. Déplacer un joint d'un ou deux pixels.
4. Lire l'animation, avancer d'une frame, comparer avec la précédente (onion skin).
5. Changer la durée, le fps ou le nombre de frames.
6. Aller au défaut signalé par la QA.
7. Changer un z-index, une rotation ou un décalage d'os dans une frame.
8. Comprendre et arbitrer un changement fait par Claude.
9. Exporter.

## 3. Parcours : Préparer → Rigger → Animer → Exporter

Quatre étapes, toujours visibles dans la barre du haut, numérotées (touches `1` à `4`). **Aucune n'est verrouillée** : on y va dans l'ordre qu'on veut. Chaque étape affiche en haut du panneau droit une **carte d'étape** : une phrase qui dit quoi faire, l'état d'avancement, et un bouton principal « Continuer : étape suivante → ».

À l'ouverture d'un projet, l'app se place sur la première étape incomplète : **Préparer** si aucun pixel n'est assigné, **Rigger** s'il reste des pixels non assignés ou s'il n'y a pas d'animation, **Animer** sinon.

| Étape | Ce que montre le viewport | Carte d'étape | Outils actifs | Coquille |
|---|---|---|---|---|
| **1 Préparer** | Sprite nettoyé seul. Squelette, label map et pivots sont masqués et leurs boutons désactivés ; seule la grille reste. | Taille, nombre de couleurs, palette, alpha binaire, type de vue, avertissements du `prepare` et du rig. | Sélection | oui (nettoyage fait par le cœur : le fichier déposé lui est envoyé tel quel) |
| **2 Rigger** | Pose de repos (le sprite) + squelette, label map, pivots. | Nombre de pixels non assignés avec lien « Les voir ». | Sélection, Pinceau, Gomme, Déplacer | oui |
| **3 Animer** | Frame courante rendue par le cœur, sur le canvas d'export (constant). | Choix du preset (« walk » proposé par défaut) + « Appliquer ». | Sélection, Déplacer (décale l'os dans la frame) ; Pinceau et Gomme désactivés avec explication | oui |
| **4 Exporter** | Comme Animer. | Résumé avant écriture : canvas, frames, durée, fps, boucle, pivot (en pixels du canvas), fichiers, état QA ; bouton « Exporter » ; puis la liste des fichiers écrits (chemins complets), le verdict QA de l'export et les avertissements du moteur. | Sélection | oui (spritesheet PNG + JSON + GIF écrits dans `<projet>/export/`) |

L'export n'est **pas** bloqué par des échecs QA : il les annonce (« QA : 2 échecs ») et laisse décider.

## 4. Structure de l'écran

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ animAI  projet   ①Préparer ②Rigger ③Animer ④Exporter     [synchro] ↶ ↷ ◐ ? │ barre du haut, 40 px
├──────────────────────────────────────────────────────────────────────────────┤
│ (bannière : conflit ou échec d'écriture — seulement quand il y en a)        │
├────┬─────────────┬──────────────────────────────────────────┬───────────────┤
│outils│ Hiérarchie │ calques · opacité · fond · zoom          │ Carte d'étape │
│ 40 │   240 px    ├──────────────────────────────────────────┤ Inspecteur    │
│ px │  os         │                                          │ QA            │
│    │   └ pièces  │              VIEWPORT                    │ Historique    │
│    │             │                                          │    300 px     │
├────┴─────────────┴──────────────────────────────────────────┴───────────────┤
│ ⏮ ▶ ⏭  3 / 6  Boucle  Onion skin  Durée de la frame      Frames  FPS  Durée │ timeline
│ [ 1 ][ 2 ][ 3 ][ 4 ][ 5 ][ 6 ]                                               │
├──────────────────────────────────────────────────────────────────────────────┤
│ x 31  y 12  ■ #E8B088  pièce 3 · head      (message d'aide)     64×64 · ×10 │ barre d'état, 24 px
└──────────────────────────────────────────────────────────────────────────────┘
```

Décisions :

- **Un seul écran, pas d'onglets ni de fenêtres flottantes.** Les quatre étapes changent le contenu du viewport et la carte d'étape, pas la disposition : on ne perd jamais ses repères.
- **Le panneau QA et l'historique sont toujours visibles** (panneau droit, sous l'inspecteur). Un défaut ou un changement de Claude ne doit jamais être caché derrière un onglet.
- **La timeline est toujours visible**, même à l'étape Rigger : appuyer sur lecture y bascule vers Animer.
- En dessous de 1180 px de large les panneaux latéraux rétrécissent ; en dessous de 900 px la hiérarchie disparaît et le panneau droit passe sous le viewport. L'éditeur est un outil de bureau : pas de version mobile.

## 5. Viewport

### 5.1 Netteté (non négociable)

| Règle | Détail | Coquille |
|---|---|---|
| Zoom **entier** uniquement | Niveaux : ×1 2 3 4 5 6 8 10 12 16 20 24 32 48 64. Un pixel du sprite = N×N **pixels physiques** d'écran. | oui |
| Tampon du canvas en pixels physiques | Taille lue par `ResizeObserver` (`device-pixel-content-box`), pas `taille CSS × devicePixelRatio` arrondie : à 125 % ou 150 % de mise à l'échelle Windows, le navigateur ne rééchantillonne rien. | oui, vérifié à 100 %, 125 %, 150 % |
| Lissage désactivé | `imageSmoothingEnabled = false` avant chaque dessin, et `image-rendering: pixelated` sur le canvas en filet de sécurité. | oui |
| Décalage entier | `panX`, `panY` sont des entiers de pixels physiques. | oui |
| Repères jamais mélangés à l'image | Les repères (grille, squelette, numéros) sont dessinés après l'image, en noir et blanc doublés pour rester lisibles sur toute couleur. Tous calques éteints, le viewport ne contient que les couleurs du sprite et celles du fond. | oui, vérifié par lecture des pixels du canvas |

### 5.2 Fond

Le fond de la zone image est **indépendant du thème**, pour juger le sprite sur le même fond en clair et en sombre. Quatre fonds, `Maj+B` pour passer de l'un à l'autre : **damier** gris neutre `#7F7F7F` / `#8F8F8F`, cases de 4 pixels du sprite (défaut) ; **gris 50 %** `#808080` ; **noir** ; **blanc**. Autour de la zone image : gris neutre du thème (`--vp-surround`).

### 5.3 Navigation

| Geste | Effet | Coquille |
|---|---|---|
| Molette | Zoom d'un cran, centré sur le curseur | oui |
| `+` / `−` | Zoom d'un cran, centré sur le viewport | oui |
| `0` ou bouton « Ajuster » | Plus grand zoom entier qui montre toute la zone | oui |
| Clic molette + glisser, ou `Espace` maintenu + glisser | Déplacer la vue | oui |
| `Alt` + flèches | Déplacer la vue de 32 px | oui |

Tant que l'utilisateur n'a ni zoomé ni déplacé la vue, l'app recadre toute seule quand la fenêtre change de taille ou quand la zone affichée change (la pose de repos fait la taille du sprite, la frame fait la taille du canvas d'export). Dès qu'il a touché à la vue, elle ne bouge plus sans lui. Changer d'étape ne décale jamais le sprite à l'écran.

### 5.4 Lecture d'un pixel

La barre d'état affiche en permanence, pour le pixel survolé (ou sous le curseur clavier) : `x`, `y` (origine en haut à gauche du sprite nettoyé, comme dans `rig.json`), pastille de couleur, code hexadécimal, numéro et nom de la pièce propriétaire, ou « non assigné », « transparent », « hors image ». À l'étape Animer, couleur et pièce sont celles de la frame rendue.

### 5.5 Calques d'affichage

| Calque | Touche | Contenu | Coquille |
|---|---|---|---|
| Squelette | `S` | Liens parent → enfant, trait blanc cerné de noir ; liens de l'os sélectionné en couleur d'accent | oui |
| Label map | `L` | Couleur + motif de chaque pièce par-dessus l'image (opacité réglable de 20 à 100 %, 60 % par défaut) ; numéro de la pièce en badge à partir de ×6 ; pixels non assignés marqués d'un point blanc cerné de noir | oui |
| Pivots | `P` | Joints : rond blanc cerné de noir (carré pour la racine), plus grand et en couleur d'accent pour l'os sélectionné. Pivot d'export : croix, à la position **fournie par le moteur** (champ `pivot` de la frame, en pixels du canvas, coin de grille). Le pivot est ancré sur la bbox du sprite au repos : l'UI ne le recalcule pas, et ne l'affiche pas tant qu'aucune frame n'a été rendue (voir demande D2, § 13.5). | oui |
| Nom de l'os | — | Seul l'os **sélectionné** est nommé. L'étiquette est posée **hors de l'image** (à droite de la zone, sinon à gauche) et reliée au joint par un filet : sur un sprite étroit, une étiquette collée au joint cachait le membre voisin. | oui |
| Grille | `G` | Une ligne par pixel du sprite à partir de ×4, ligne renforcée tous les 8 pixels | oui |
| Onion skin | `O` | Silhouette unie de la frame précédente en **bleu** `#0072B2` et de la suivante en **orange** `#E69F00`, à 40 %, **sous** la frame courante (qui reste intacte). Étapes Animer et Exporter. | oui |
| Zones de chevauchement | — | Extension de chaque pièce sous ses voisines (`overlap`) en hachures | non |
| Trous détectés | — | Surlignage permanent des trous du rapport QA de la frame courante | partiel : visibles un par un en cliquant la ligne QA |
| Sprite original en transparence | — | Sprite source superposé à la frame, pour comparer | non |

Un calque sans objet à l'étape courante est désactivé avec une infobulle qui le dit. Activer le pinceau ou la gomme allume la label map ; activer l'outil Déplacer allume les pivots (on ne déplace pas ce qu'on ne voit pas).

## 6. Outils

Quatre outils dans le rail de gauche, un seul actif à la fois. Chacun a une lettre.

### Sélection (`V`) — coquille : oui

- Clic sur un joint (à moins de 10 px d'écran, si squelette ou pivots sont visibles) : sélectionne l'**os**.
- Sinon, clic sur un pixel : sélectionne la **pièce propriétaire** du pixel. À l'étape Animer, le propriétaire vient de la carte des propriétaires renvoyée avec la frame.
- Clic sur un pixel transparent, non assigné, ou hors image : désélectionne.
- Clavier : flèches pour déplacer le curseur pixel, `Entrée` pour sélectionner.

### Pinceau (`B`) — coquille : oui

- Assigne les pixels **opaques** sous le pinceau à la pièce cible. Les pixels transparents ne sont jamais assignables.
- Pièce cible = la pièce sélectionnée, ou l'unique pièce de l'os sélectionné. Sans cible, rien n'est peint et la barre d'état explique quoi faire.
- `Alt`+clic : prend pour cible la pièce sous le curseur.
- Pinceau carré, taille 1 à 16 px (champ « Taille » dans la barre des calques), contour affiché au survol. Le tracé entre deux positions de souris est continu (pas de trous quand on va vite).
- **Un trait = une entrée d'historique = une écriture** dans `rig.json`, au relâchement. Pendant le trait, la label map se met à jour en direct. `Échap` pendant le trait l'abandonne.
- Étape Rigger uniquement. Ailleurs le bouton est grisé et un clic explique pourquoi.

### Gomme (`E`) — coquille : oui

Comme le pinceau, mais rend les pixels **non assignés**. Pas besoin de pièce cible.

### Déplacer (`J`) — coquille : oui

- **Étape Rigger** : glisser un joint le déplace dans la pose de repos, aimanté au pixel entier, borné au sprite. Seul ce joint bouge (ses enfants gardent leur position). Écrit `bones.<os>.joint`.
- **Étapes Animer / Exporter** : glisser un joint décale l'os **dans la frame courante** (`frames[i].bones.<os>.pos`). Un rond fantôme montre la destination ; la frame est re-rendue au relâchement.
- Flèches : 1 px sur l'os sélectionné ; `Maj`+flèche : 5 px. Une rafale de flèches (moins de 0,8 s entre deux appuis) forme une seule entrée d'historique.
- `R` / `Maj+R` : rotation de l'os sélectionné de +15° / −15° dans la frame courante. Le pas de 15° est voulu (angles discrets de `CLAUDE.md`) ; le champ de l'inspecteur accepte tout entier.
- `Échap` pendant un glisser : abandonne.

### Outils spécifiés, pas encore construits

| Outil | Comportement décidé |
|---|---|
| **Remplissage** (`F`) | Clic : assigne à la pièce cible tous les pixels opaques contigus (4-connexité) qui ont le même propriétaire que le pixel cliqué. |
| **Lasso** (`Q`) | Tracé à main levée fermé au relâchement ; assigne les pixels opaques dont le centre est dedans. `Alt` = désassigner. |
| **Poignées IK** | À l'étape Animer, un losange sur chaque `target_bone` d'une chaîne IK ; le glisser déplace la cible, le cœur résout la chaîne et renvoie les rotations. |
| **Ajout / suppression d'os et de pièces, renommage, re-parentage** | Dans la hiérarchie : menu contextuel et glisser-déposer. Supprimer un os rattache ses pièces et ses enfants à son parent ; supprimer une pièce rend ses pixels non assignés. |
| **Choix du template** | À l'étape Préparer, liste des templates ; en changer repose les os proportionnellement et demande confirmation en ligne si des joints ont déjà été déplacés. |
| **Verrouillage** | Cadenas par ligne de la hiérarchie : une pièce verrouillée ne peut être ni peinte ni gommée, un os verrouillé ne peut pas être déplacé. |
| **Palette de commandes** (`Ctrl+K`) | Liste filtrable de toutes les actions de la table des raccourcis. |

## 7. Panneaux

### 7.1 Hiérarchie (gauche) — coquille : sélection, visibilité, pliage, clavier

- Arbre des **os** ; sous chaque os, ses **pièces**. Un os a un rond creux, une pièce a une **pastille couleur + motif + numéro** identique à la label map.
- À droite de chaque ligne : le z-index de la pièce, la mention **IK** pour un os pris dans une chaîne, et un **œil**.
- Œil d'une pièce : masque ses pixels dans le viewport (pose de repos et frame rendue). Œil d'un os : le retire du squelette. La visibilité est un réglage d'affichage : elle n'est ni écrite dans les fichiers ni dans l'historique.
- Clic ou flèches ↑ ↓ : la sélection suit le focus. ← → : replier, déplier, remonter au parent. `H` : basculer l'œil.
- Une pièce dont l'os n'existe pas reste affichée en bas, marquée « os ? », plutôt que de disparaître.
- Pas encore construits : verrouillage, renommage, re-parentage par glisser-déposer, réordonnancement du z par glisser-déposer (le z s'édite dans l'inspecteur).

### 7.2 Inspecteur (droite) — coquille : oui

Champs numériques : entiers uniquement, saisie directe, ↑ ↓ pour ±1 pas, et **scrub** en glissant sur le libellé (4 px de souris = 1 pas ; un scrub = une entrée d'historique).

| Sélection | Champs | Écrit dans |
|---|---|---|
| **Os** | Parent (lecture) · Joint X, Joint Y · IK (lecture : chaînes concernées) · Poids (toujours 100 % sur cet os, lecture) · Pièces (liens) | `rig.json` `bones.<os>.joint` |
| **Os**, étapes Animer / Exporter | Rotation (pas de 15°, −180 à 180) · Décalage X, Y · « Remettre cet os à zéro dans la frame » | `anim.json` `frames[i].bones.<os>` (les valeurs nulles sont retirées du JSON) |
| **Pièce** | Repère (numéro, couleur, motif) · Os (liste) · Z-index · Chevauchement (0 à 8 px) · Pixels (lecture) | `rig.json` `parts.<pièce>.bone`, `.z`, `.overlap` |
| **Pièce**, étapes Animer / Exporter | Z forcé (os) dans la frame (vide = hérité). La clé est un **nom d'os** : la valeur vaut pour toutes les pièces de l'os de la pièce sélectionnée, ce que dit l'infobulle. | `anim.json` `frames[i].z.<os>` |
| **Rien** | Projet, template, vue | — |

### 7.3 Timeline (bas) — coquille : oui

- **Transport** : frame précédente, lecture / pause, frame suivante, compteur « 3 / 6 ».
- **Bande de frames** : un bouton par frame, **largeur proportionnelle à sa durée**, numéro et durée affichés. Frame courante encadrée. Un losange marque les frames où l'os sélectionné a une clé.
- **Boucle** : bascule `anim.loop` (c'est une donnée, donc annulable). La lecture respecte `loop` : sans boucle elle s'arrête sur la dernière frame.
- **Onion skin** : même bascule que le calque.
- **Durée de la frame** : `duration_ms` de la frame courante (frame d'impact tenue plus longtemps).
- **Frames / FPS / Durée** : trois champs liés. Le cœur accepte un, deux ou trois paramètres (`docs/schemas.md`, « Rééchantillonnage ») ; l'app envoie le plus petit jeu qui dit ce que l'utilisateur veut :

  | Champ modifié | Envoyé au cœur | Effet (règles du cœur) |
  |---|---|---|
  | Frames | `frames` | N frames de même durée, sur la durée totale actuelle. En réduire le nombre peut supprimer des poses : le cœur le dit dans un avertissement, affiché tel quel. |
  | FPS | `frames` actuel, `fps` | Même nombre de frames, chacune de `1000 / fps` ms. La durée totale change. |
  | Durée | `duration_ms` | **Toutes** les frames gardées, durées multipliées par le même facteur : les frames tenues restent tenues. C'est le réglage à utiliser pour ralentir ou accélérer. |

  Le champ FPS affiche la cadence moyenne (`frames × 1000 / durée`). Le rééchantillonnage est fait **par le cœur** ; l'UI n'en fait aucun. Une incohérence renvoyée par le cœur s'affiche en notification, et les champs reprennent leurs valeurs.
- La lecture utilise la durée de chaque frame. Changer de frame à la main met en pause.
- Pas encore construit : une ligne de clés par os (dope sheet), copier / coller une pose, insertion et suppression d'une frame.

### 7.4 Panneau QA (droite) — coquille : oui

- Une ligne par contrôle de `report.json`, échecs en premier. Chaque ligne porte un **signe** (✕, ✓, ?), le **mot** (Échec, OK, Non vérifié) et le détail : jamais la couleur seule.
- En-tête : « 2 échecs · 5 OK · 1 non vérifié » et bouton « Relancer ». Le rapport se rafraîchit seul après chaque écriture.
- **Chaque échec localisé est un bouton.** Clic : passe à l'étape et à la frame concernées, centre le viewport sur le pixel (zoom porté à ×8 au moins), entoure les pixels fautifs (cadre noir et blanc par pixel + cercle autour du groupe). `Échap` retire le surlignage. Le surlignage suit les corrections : il se met à jour à chaque nouveau rapport et disparaît quand le contrôle passe.
- **Repères.** L'app surligne les pixels du champ `pixels` (coordonnées sprite, fourni par `GET /api/report`). Devant un `report.json` de la CLI, qui n'a que `pixel` en coordonnées canvas, elle retranche l'origine du canvas de la frame. Sans animation, le rapport porte sur la pose de repos : la ligne dit « pose de repos » et le clic reste sur l'étape Rigger.
- **Rapport indisponible.** Tant qu'aucune pièce n'a de pixels (juste après un import), le serveur ne peut rien rendre : le panneau l'explique (« Le rapport QA sera disponible dès qu'une pièce aura des pixels ») au lieu d'afficher l'erreur, et « Les voir » surligne quand même les pixels non assignés, lus dans la label map déjà affichée.
- Le texte `detail` de chaque ligne est le message du moteur, en anglais, cité tel quel (voir § 8.2).
- Libellés : `parts_assigned` « Pixels assignés à une pièce » · `holes` « Trous dans la silhouette » · `palette` « Palette préservée » · `alpha_binary` « Alpha binaire (0 ou 255) » · `orphans` « Pixels orphelins » · `pivot_stable` « Pivot stable » · `canvas_constant` « Canvas constant » · `loop_closed` « Boucle fermée ».

### 7.5 Historique (droite) — coquille : oui pour la session, non pour les versions nommées

- Liste des actions de la session, la plus récente en haut, avec **auteur** (pastille « Vous » pleine, « Claude » en tirets, « Autre » en pointillés pour une autre fenêtre de l'éditeur), libellé et heure.
- Cliquer une entrée ramène l'état juste après elle (annulations ou rétablissements en chaîne). « État initial » annule tout.
- Un changement de Claude est **une** entrée : l'annuler défait tout le lot d'un coup.
- Annuler / rétablir : illimité sur la session. L'historique est linéaire : annuler puis modifier efface la branche rétablissable.
- Ouvrir une autre image s'appuie sur les versions du serveur (`/api/snapshots`) : une version est prise avant et après, `Ctrl+Z` restaure la première. Depuis l'état vide il n'y a rien à mettre de côté : cette première ouverture n'est pas annulable.
- Pas encore construit : la liste des versions nommées (« avant / après Claude »), persistantes entre sessions. Les routes existent.

## 8. États

| État | Ce que voit l'utilisateur | Coquille |
|---|---|---|
| **Vide** (aucun projet) | Zone de dépôt plein écran : « Déposez un sprite pixel art ici », bouton « Choisir une image… », les quatre étapes résumées. En démo : bouton « Charger l'exemple ». | oui |
| **Dépôt en cours** | Voile sur toute la fenêtre : « Déposez l'image pour ouvrir ce sprite — remplace le projet courant, annulable avec Ctrl+Z ». | oui |
| **Chargement** | Indicateur + « Chargement du projet… ». | oui |
| **Erreur de chargement** | Message du serveur + « Réessayer ». | oui |
| **Fichier refusé** | Message précis dans la zone de dépôt, ou en notification si un projet est ouvert : pas une image, image illisible, image > 512 px après nettoyage, image vide. | oui |
| **Enregistrement** | Pastille de synchro « Enregistrement… ». | oui |
| **À jour** | Pastille « Enregistré 11:18:27 · vous » (ou « · Claude », « · autre fenêtre »). Toujours visible dans la barre du haut. | oui |
| **Changement de Claude** | Appliqué en direct, sans rien demander, si l'humain n'a rien en attente. Notification « Claude a modifié rig.json » avec le bouton **Annuler ce lot**. Entrée « Claude » dans l'historique. | oui |
| **Changement venu d'une autre fenêtre de l'éditeur** | Même traitement, mais dit comme tel : « rig.json a été modifié dans une autre fenêtre de l'éditeur », entrée « Autre ». | oui |
| **Sa propre écriture** | Rien. Le serveur renvoie un événement pour chaque écriture de l'app ; il est consommé en silence (voir 8.3). | oui |
| **Fichier invalide écrit sur le disque** | L'app ne bouge pas (le serveur n'émet rien) ; la raison apparaît dans les avertissements de l'étape Préparer au prochain chargement. | oui |
| **Conflit** | Voir 8.1. | oui |
| **Écriture impossible / serveur injoignable** | Bannière non modale + « Réessayer ». Les modifications restent dans l'app et repartent à la reconnexion. | partiel : codé, non vérifié (serveur jamais coupé pendant l'essai) |
| **Rendu en cours** | La frame précédente reste affichée jusqu'à l'arrivée de la nouvelle (pas de clignotement) ; « Rendu 3 / 6… » dans la timeline. La frame courante est toujours demandée en premier. | oui |
| **Aucune animation** | Timeline : « Aucune animation. Choisir un preset à l'étape Animer ». | oui |

### 8.1 Conflit de synchronisation

Un conflit arrive quand l'app veut écrire un fichier que Claude a modifié depuis la dernière version qu'elle connaît. Le serveur refuse l'écriture (HTTP 409) : **rien n'est écrasé, d'un côté comme de l'autre.**

Cas typique : Claude écrit `rig.json` **pendant un geste** (un trait de pinceau, un joint en cours de déplacement). Tant que le geste dure, l'app n'applique pas le changement du disque : remplacer le rig sous le curseur fausserait le geste. Au relâchement, soit le geste écrit quelque chose et le serveur répond 409, soit il n'écrit rien et le changement de Claude est appliqué normalement.

L'app affiche une **bannière non modale** sous la barre du haut ; on peut continuer à regarder et à éditer, mais plus rien n'est écrit tant que le conflit n'est pas tranché :

> **Conflit sur rig.json.** Claude a modifié ce fichier à 11:18:27 pendant que vous l'éditiez. Rien n'a été écrasé. Différences : `bones.head.joint`.
> [ Garder ma version ] [ Prendre la version de Claude ]

- **Garder ma version** : l'app réécrit le fichier entier avec sa version. Celle de Claude est perdue sur le disque (il la verra changer).
- **Prendre la version de Claude** : l'app charge la version du disque. La version de l'humain devient une entrée d'historique : `Ctrl+Z` la rétablit, et la notification propose « Revenir à ma version ».
- Pas de fusion automatique champ par champ en v1 : la liste `changed_paths` suffit pour décider, et une fusion fausse serait pire qu'un choix clair.

### 8.2 Messages du moteur (en anglais)

Le cœur écrit ses messages en anglais (`docs/schemas.md`, « Sortie CLI »). L'interface est en français. Décision :

- **Erreurs** : le serveur compose une phrase française suivie du message du cœur (« Durée incohérente : frames / fps … »). L'app affiche cette phrase **telle quelle**. La partie française dit ce qui a échoué, la citation dit pourquoi.
- **Avertissements** (preset, rééchantillonnage, export) et **détail des lignes QA** : cités tels quels, annoncés comme venant du moteur (« Avertissement du moteur : … »), en police à chasse fixe, balisés `lang="en"` pour les lecteurs d'écran.
- **L'app ne traduit rien à la volée.** Une table de traduction côté interface casserait à chaque reformulation du cœur, et une traduction approximative d'un message technique induit en erreur. Si l'on veut tout en français, c'est au cœur de porter des identifiants de message (demande D6, § 13.5).

### 8.3 Reconnaître ses propres écritures

Le serveur diffuse un événement pour chaque écriture, y compris celles de l'app (c'est ce qui synchronise deux fenêtres). L'app ne doit jamais présenter son propre écho comme « Claude a modifié ». Règles côté client, indépendantes du délai de 0,15 s que le serveur ajoute :

1. Tant qu'une écriture de l'app est en vol (requête partie, réponse pas encore reçue), les événements reçus sont **mis en attente** : on ne peut pas encore savoir s'ils sont son écho.
2. À chaque réponse d'écriture, l'app note la révision obtenue comme **écho attendu**. L'événement qui porte cette révision est consommé en silence, même si l'app a déjà écrit autre chose depuis. Un écho attendu ne sert qu'une fois et expire au bout de 10 s.
3. Un événement dont la révision est celle que l'app a déjà en mémoire est ignoré.
4. Tout autre événement est un vrai changement : `author: "external"` est présenté comme Claude, `author: "app"` comme une autre fenêtre de l'éditeur.
5. `project.changed` (import, restauration) : l'app compare les révisions du disque (sprite, rig, animation) aux siennes et ne recharge que si elles diffèrent.

Pourquoi pas un simple ensemble de « révisions déjà vues » : une révision est un hash du contenu. Si Claude remet un fichier dans un état antérieur, la révision est connue et le changement serait ignoré à tort (défaut rencontré pendant l'essai à deux fenêtres).

### 8.4 Régions écrites à la main et label map

`PUT /api/labelmap` ré-encode les régions de **toutes** les pièces en `rects` + `pixels`. Un rig écrit par Claude avec des `polygons` ou des `exclude` perd donc cette écriture au premier trait de pinceau ou de gomme, même si le trait ne touche qu'un pixel d'une autre pièce. Le découpage reste identique au pixel près ; ce qui disparaît, c'est la forme lisible que Claude avait écrite et qu'il comptait peut-être retoucher.

Ce que fait l'éditeur :

- **Avant.** Tant que le rig contient au moins un polygone ou une exclusion, la carte de l'étape Rigger affiche un avertissement permanent qui nomme les pièces concernées et dit ce qui va se passer. Choisir le pinceau ou la gomme le rappelle dans la barre d'état. Rien n'est bloqué, aucune confirmation n'est demandée.
- **Pendant.** Le trait s'applique normalement.
- **Après.** Une notification dit que les régions viennent d'être converties et propose **Annuler**.
- **Annulation.** L'app a gardé le texte d'origine de toutes les régions : `Ctrl+Z` les réécrit telles quelles par `PUT /api/rig`, polygones compris, au lieu de repasser par la label map. Vérifié contre le serveur : le polygone d'origine revient à l'identique dans `rig.json`.
- Déplacer un joint, changer un z-index ou un chevauchement passe par `PUT /api/rig`, qui écrit le rig tel que reçu : aucune perte.

Ce qui supprimerait le problème côté serveur : demande D1, § 13.5.

## 9. Raccourcis clavier

Source unique : `app/js/shortcuts.js` alimente à la fois le gestionnaire clavier et l'aide (`?`). Les chiffres sont reconnus par **touche physique** : sur un clavier AZERTY ils fonctionnent sans `Maj`. Les raccourcis à une lettre sont inactifs pendant la saisie dans un champ.

| Groupe | Touches | Action |
|---|---|---|
| Général | `?` | Afficher / masquer l'aide |
| | `Ctrl+Z` | Annuler |
| | `Ctrl+Y` ou `Ctrl+Maj+Z` | Rétablir |
| | `Échap` | Dans l'ordre : abandonner le geste en cours, fermer le panneau ouvert, retirer le surlignage QA, quitter le champ, désélectionner |
| | `1` `2` `3` `4` | Étape Préparer / Rigger / Animer / Exporter |
| | `F6` / `Maj+F6` | Zone suivante / précédente : outils, hiérarchie, viewport, panneau droit, timeline |
| | `Maj+T` | Thème clair / sombre |
| Outils | `V` | Sélection |
| | `B` | Pinceau |
| | `E` | Gomme |
| | `J` | Déplacer un joint (Rigger) ou décaler un os dans la frame (Animer) |
| | `Alt`+clic | Pinceau / gomme : prendre la pièce sous le curseur |
| | `H` | Afficher / masquer l'os ou la pièce sélectionnés |
| Viewport | `←` `↑` `→` `↓` | Curseur pixel, ou joint avec l'outil Déplacer : 1 px ; avec `Maj` : 5 px |
| | `Entrée` | Appliquer l'outil au curseur pixel |
| | `+` / `−` | Zoom avant / arrière |
| | `0` | Ajuster à la fenêtre |
| | Molette | Zoom centré sur le curseur |
| | `Espace`+glisser, clic molette | Déplacer la vue |
| | `Alt`+flèches | Déplacer la vue au clavier |
| Calques | `S` `L` `P` `G` `O` | Squelette, label map, pivots, grille, onion skin |
| | `Maj+B` | Fond : damier, gris, noir, blanc |
| Animation | `Espace` | Lecture / pause |
| | `,` ou `Page préc.` | Frame précédente |
| | `.` ou `;` ou `Page suiv.` | Frame suivante (`;` est la touche voisine de `,` en AZERTY) |
| | `Début` / `Fin` | Première / dernière frame |
| | `R` / `Maj+R` | Rotation de l'os sélectionné de +15° / −15° dans la frame |
| Hiérarchie | `↑` `↓` | Ligne précédente / suivante (la sélection suit) |
| | `←` `→` | Replier / déplier, remonter au parent |
| Timeline | `←` `→` | Frame précédente / suivante quand la bande de frames a le focus |
| Inspecteur | Glisser sur un libellé | Faire varier la valeur |

`Espace` : un appui bref lance ou arrête la lecture ; maintenu avec un glisser, il déplace la vue sans toucher à la lecture. Sur un bouton qui a le focus, `Espace` et `Entrée` activent ce bouton, comme partout.

Réservés pour les outils à venir : `F` remplissage, `Q` lasso, `Ctrl+K` palette de commandes.

## 10. Design tokens

Fichier : `app/css/tokens.css`. Aucune couleur ni dimension en dur ailleurs dans le CSS.

### 10.1 Couleurs

L'interface est en **gris strictement neutres** (R = G = B) : un gris teinté déplacerait la perception des couleurs du sprite. Une seule couleur d'accent (bleu), réservée au focus, à la sélection et à l'action principale ; elle n'apparaît dans le viewport que sur l'os sélectionné.

| Token | Sombre | Clair | Usage |
|---|---|---|---|
| `--bg-app` | `#1C1C1C` | `#ECECEC` | Fond général, états vide / chargement |
| `--bg-panel` | `#252525` | `#F7F7F7` | Panneaux, barres |
| `--bg-raised` | `#2F2F2F` | `#FFFFFF` | Boutons, cartes, notifications |
| `--bg-input` | `#181818` | `#FFFFFF` | Champs |
| `--bg-hover` | `#383838` | `#E2E2E2` | Survol |
| `--bg-selected` | `#1F3A66` | `#D3E2FB` | Ligne ou bouton sélectionné |
| `--border` | `#3D3D3D` | `#CFCFCF` | Séparateurs |
| `--border-strong` | `#757575` | `#858585` | Contour des champs (≥ 3:1) |
| `--text` | `#E8E8E8` | `#1A1A1A` | Texte |
| `--text-muted` | `#A8A8A8` | `#595959` | Texte secondaire |
| `--accent` | `#78AAFF` | `#1A56C4` | Focus, sélection, action principale, liens |
| `--on-accent` | `#0A0A0A` | `#FFFFFF` | Texte sur accent |
| `--danger` | `#FF8A80` | `#B3261E` | Échec, conflit |
| `--warn` | `#E6B84D` | `#7A5200` | Avertissement |
| `--ok` | `#6FD08C` | `#17692F` | Succès |
| `--vp-surround` | `#2B2B2B` | `#C4C4C4` | Autour de la zone image |
| `--vp-checker-a` / `-b` | `#7F7F7F` / `#8F8F8F` | idem | Damier du viewport (indépendant du thème) |

Contrastes calculés (WCAG 2.x) sur les valeurs ci-dessus :

| Paire | Sombre | Clair | Seuil |
|---|---|---|---|
| `--text` sur `--bg-panel` | 12,5 | 16,3 | 4,5 |
| `--text` sur `--bg-selected` | 9,2 | 13,3 | 4,5 |
| `--text-muted` sur `--bg-panel` | 6,5 | 6,5 | 4,5 |
| `--text-muted` sur `--bg-selected` (pire cas) | 4,8 | 5,4 | 4,5 |
| `--accent` sur `--bg-panel` | 6,6 | 6,2 | 4,5 |
| `--on-accent` sur `--accent` | 8,5 | 6,6 | 4,5 |
| `--danger` sur `--bg-panel` | 6,7 | 6,1 | 4,5 |
| `--warn` sur `--bg-panel` | 8,3 | 6,5 | 4,5 |
| `--ok` sur `--bg-panel` | 8,1 | 6,3 | 4,5 |
| `--border-strong` sur `--bg-panel` | 3,3 | 3,4 | 3 |

### 10.2 Espacements, tailles, typographie

| Token | Valeur | Usage |
|---|---|---|
| `--sp-1` … `--sp-6` | 4, 8, 12, 16, 24 px | Base 4 px |
| `--ctl-h` | 28 px | Hauteur de tout contrôle = cible de clic minimale (WCAG 2.2 : 24 px) |
| `--topbar-h` / `--statusbar-h` | 40 / 24 px | |
| `--rail-w` / `--left-w` / `--right-w` | 40 / 240 / 300 px | |
| `--radius` | 4 px | |
| `--font-ui` | pile système (`system-ui`, Segoe UI, Roboto…) | Interface. Aucune police téléchargée. |
| `--font-mono` | `ui-monospace`, Cascadia Mono, Consolas… | Toute valeur : coordonnées, couleurs, durées, noms d'os et de pièces. Chiffres tabulaires. |
| `--fs-xs` / `-sm` / `-md` / `-lg` | 11 / 12 / 13 / 16 px | Corps à 13 px, interligne 1,4 |

### 10.3 Thèmes

Deux thèmes, sombre et clair, portés par `data-theme` sur `<html>`. Premier lancement : préférence du système ; ensuite le choix est mémorisé (`localStorage`, clé `animai.theme`). Bascule : bouton de la barre du haut ou `Maj+T`. Le fond du viewport ne change pas avec le thème.

## 11. Palette de la label map

Objectif : distinguer les pièces **sans dépendre de la couleur**. Trois signaux redondants :

1. **Numéro** — l'identifiant de référence. Numéro = rang de la pièce dans `rig.json` `parts` (la première est « 1 »). Il figure sur la pastille de la hiérarchie, dans l'inspecteur, dans la barre d'état au survol, et en badge sur le sprite à partir de ×6 (fond noir, chiffre blanc, liseré de la couleur de la pièce).
2. **Couleur** — 8 teintes, reprises de la palette Okabe-Ito (le noir, qui se confondrait avec les contours des sprites, est remplacé par un gris foncé).
3. **Motif** — à partir de la 9ᵉ pièce les couleurs reviennent, avec un motif à l'échelle du pixel du sprite.

| N° | Couleur | Hex | N° 1 à 8 | N° 9 à 16 | N° 17 à 24 |
|---|---|---|---|---|---|
| 1, 9, 17 | orange | `#E69F00` | plein | damier | rayures |
| 2, 10, 18 | bleu ciel | `#56B4E9` | plein | damier | rayures |
| 3, 11, 19 | vert bleuté | `#009E73` | plein | damier | rayures |
| 4, 12, 20 | jaune | `#F0E442` | plein | damier | rayures |
| 5, 13, 21 | bleu | `#0072B2` | plein | damier | rayures |
| 6, 14, 22 | vermillon | `#D55E00` | plein | damier | rayures |
| 7, 15, 23 | rose violacé | `#CC79A7` | plein | damier | rayures |
| 8, 16, 24 | gris foncé | `#4D4D4D` | plein | damier | rayures |

- **Damier** : un pixel sur deux (ceux où x + y est impair) prend la couleur assombrie à 45 %. **Rayures** : une ligne sur deux (y impair). Au-delà de 24 pièces le cycle recommence ; le numéro reste unique.
- **Non assigné** : point blanc cerné de noir au centre de chaque pixel (damier noir et blanc à 50 % en dessous de ×5). Lisible sur toute couleur, et le sprite reste visible même quand rien n'est encore assigné.
- La label map se dessine à 60 % d'opacité par-dessus le sprite (réglable jusqu'à 100 % pour juger les couleurs pures).

Vérification faite : simulation des trois dichromaties (matrices de Machado et al., sévérité maximale) sur les 8 teintes à 100 % d'opacité, plus petite distance ΔE (CIE76) entre deux teintes : vision normale 26, protanopie 21, deutéranopie 17, tritanopie 16. Avec le gris moyen `#999999` d'abord envisagé, le rose et le gris tombaient à 7 en deutéranopie : d'où le gris foncé. Non vérifié : test avec des personnes daltoniennes, et lisibilité à 60 % d'opacité sur des sprites très colorés (le numéro et le motif sont là pour ça).

## 12. Accessibilité

| Règle | Mise en œuvre | Coquille |
|---|---|---|
| Tout au clavier | Tab parcourt tous les contrôles ; `F6` saute de zone en zone ; le viewport est focalisable, avec un curseur pixel (flèches, `Entrée`) ; l'arbre et la bande de frames suivent les conventions ARIA (un seul arrêt de tabulation, flèches à l'intérieur). | oui pour ce qui est construit |
| Focus toujours visible | Contour de 2 px en couleur d'accent sur tout élément focalisé au clavier, y compris le canvas. | oui |
| Jamais la couleur seule | État enfoncé = fond + bordure + coche ; outil actif = barre latérale ; statut QA = signe + mot ; auteur = pastille pleine ou pointillée + nom ; pièces = numéro + motif ; onion skin = bleu / orange (distinguables en daltonisme) + position temporelle dite dans l'infobulle. | oui |
| Contraste | Texte ≥ 4,5:1, contours de champs et repères ≥ 3:1, dans les deux thèmes (table 10.1). Repères du viewport en noir et blanc doublés. | oui |
| Noms accessibles | Chaque bouton à icône a un `aria-label` et une infobulle avec son raccourci. Étapes : `aria-current="step"`. Bascules : `aria-pressed`. Arbre : `role="tree"`, `aria-level`, `aria-selected`, `aria-expanded`. | oui (aucun contrôle sans nom, vérifié par script) |
| Annonces | Zone `aria-live` : position, couleur et pièce du curseur pixel ; résultat d'un clic QA. Barre d'état en `role="status"` pour les messages d'aide. Bannière de conflit en `role="alert"`. Messages du moteur balisés `lang="en"`. | oui, non testé avec un lecteur d'écran |
| Pas de modale pour l'édition | Erreurs et conflits en ligne ou en bannière. La seule fenêtre modale est l'aide (`?`), qui n'interrompt aucune édition. | oui |
| Mouvement | Aucune animation d'interface hormis l'indicateur de chargement, coupé si `prefers-reduced-motion`. La lecture de l'animation est toujours déclenchée par l'utilisateur. | oui |
| Contraste forcé (Windows) | Les états sélectionnés reçoivent un contour système. | codé, non vérifié |
| Cibles de clic | 28 × 28 px au minimum ; œil de la hiérarchie 24 × 24 px. | oui |
| Notifications | Disparaissent après 7 s (12 s s'il y a une action), jamais pendant le survol ou le focus ; les erreurs restent jusqu'à fermeture. | oui |

Limite assumée : peindre une label map reste une tâche visuelle. Le clavier permet de la faire pixel par pixel, pas de la faire sans voir.

## 13. Ce que l'app attend du serveur

État : **les 21 routes ci-dessous sont implémentées** (`animai/server/`, précisions dans `docs/schemas.md`, « Serveur de l'éditeur »). Le client est `app/js/data/http-backend.js` ; le contrat côté app est résumé en tête de `app/js/data/api.js`. Les demandes nouvelles de la vague 2 sont au § 13.5, les défauts constatés au § 15.3.

### 13.1 Conventions

- Lancement : `python -m animai.cli.main serve <dossier-projet> [--port 8765]`. Le serveur sert `app/` en statique à la racine et l'API sous `/api`. Il redirige `/` vers `/index.html?api=/api` : c'est ce paramètre qui fait quitter le mode démo.
- JSON en UTF-8. Succès : la ressource, HTTP 200. Échec : `{"error": "message lisible par un humain, en français", "details": …}` avec le bon code HTTP. Le message est affiché tel quel.
- **Révisions** : chaque fichier projet a un `rev` opaque (hash du contenu ou compteur). Toute écriture envoie le `base_rev` qu'elle connaît ; si le fichier a changé depuis, le serveur répond **409** sans rien écrire.
- **Auteur** : `"app"` pour une écriture faite par cette API, `"external"` pour tout changement détecté sur le disque (Claude via la CLI ou en écrivant le fichier). L'UI affiche `external` comme « Claude ».
- **PNG** : RGBA 8 bits, alpha 0 ou 255, **sans profil colorimétrique ni chunk gamma** (`iCCP`, `gAMA`, `sRGB`) : sinon le navigateur corrige les couleurs à l'affichage et la palette est faussée.
- Délai visé : une frame en moins de 100 ms pour un sprite de 64 à 128 px (principe « retour immédiat » de `CLAUDE.md`).

### 13.2 Routes

| # | Route | Entrée | Sortie 200 | Erreurs |
|---|---|---|---|---|
| 1 | `GET /api/project` | — | `{name, sprite: {width, height, rev}, palette: ["#rrggbb"…], prepare: {warnings: [str]}, presets: ["idle","walk","attack"]}` | 404 si aucun projet (l'app affiche l'état vide) |
| 2 | `POST /api/project/import` | multipart : `file` (image), `view` (`side`) | comme 1. Lance `prepare`, crée le rig depuis le template, **pas** d'`anim.json`. | 422 (pas une image, trop grande, vide) |
| 3 | `GET /api/sprite.png` | `?rev=` (cache) | PNG du sprite nettoyé | 404 |
| 4 | `GET /api/rig` | — | `{rev, author, at, data: <rig.json>}` (`at` en ms epoch) | 404 |
| 5 | `PUT /api/rig` | `{base_rev, data: <rig.json>}` | `{rev}` | **409** `{error, doc: "rig", rev, author, at, changed_paths: ["bones.head.joint"…]}` · 422 si invalide |
| 6 | `GET /api/labelmap` | — | `{rev, width, height, parts: [noms dans l'ordre de rig.json], runs: [[label, longueur]…]}` — RLE ligne par ligne ; `label` = index dans `parts`, `-1` = non assigné ou transparent ; même `rev` que le rig | 404 |
| 7 | `PUT /api/labelmap` | `{base_rev, parts, runs}` | `{rev, regions: {<pièce>: {rects, pixels}}}` — le **cœur** ré-encode les régions de toutes les pièces et écrit `rig.json` | 409 (comme 5) · 422 |
| 8 | `GET /api/anim` | — | `{rev, author, at, data: <anim.json>}` | 404 si pas d'animation |
| 9 | `PUT /api/anim` | `{base_rev, data}` (`base_rev: null` pour créer) | `{rev}` | 409 avec `doc: "anim"` · 422 |
| 10 | `DELETE /api/anim` | `?base_rev=` | `{rev: null}` | 409 |
| 11 | `POST /api/anim/preset` | `{base_rev, preset, frames?, fps?, duration_ms?}` | `{rev, data, warnings}` — écrit `anim.json` | 409 · 422 |
| 12 | `POST /api/anim/retime` | `{base_rev, frames?, fps?, duration_ms?}` : un, deux ou trois paramètres | `{rev, data, warnings}` (avertissement au-delà de 8 frames ou si des poses sont perdues) | 409 · 422 si incohérent, avec la phrase qui explique |
| 13 | `GET /api/render/frames/{i}.png` | `?rig_rev=&anim_rev=&hide=pièce1,pièce2` | PNG de la frame `i`, sur le canvas constant, **octet pour octet identique à la frame exportée** quand `hide` est vide. Rend toujours l'état courant du disque ; `rig_rev` et `anim_rev` ne servent que de clés de cache. | 404 |
| 14 | `GET /api/render/frames/{i}.json` | idem | `{width, height, origin: [x, y], pivot: [x, y], joints: {<os>: [x, y]}, angles, duration_ms, parts, owners_runs}` — `origin` = position du (0,0) du sprite dans le canvas ; `pivot` = pivot d'export en pixels du **canvas** (coin de grille) ; `joints` = joints posés, en coordonnées du sprite ; `owners_runs` = propriétaire de chaque pixel du canvas, index dans `parts` (pour cliquer une pièce dans une frame) | idem |
| 15 | `GET /api/report` | — | `<report.json>` pour l'état courant du disque, **pose de repos s'il n'y a pas d'animation**. Chaque entrée porte en plus `pixels` : tous les pixels fautifs en coordonnées **sprite** (`pixel` reste en coordonnées canvas pour une entrée liée à une frame). | 422 si rien n'est rendable |
| 16 | `GET /api/snapshots` | — | `[{id, label, author, at}]` | |
| 17 | `POST /api/snapshots` | `{label}` | `{id, label, author, at}` | |
| 18 | `POST /api/snapshots/{id}/restore` | — | comme 1 | 404 |
| 19 | `GET /api/export/summary` | — | `{canvas: {width, height}, frames, duration_ms, fps, loop, pivot: [x, y], formats: […]}` | 404 |
| 20 | `POST /api/export` | `{formats: ["spritesheet","gif",…]}` | `{outputs: {<format>: [chemins]}, summary, warnings, qa: {ok, failed, report}}` — l'export a lieu même si la QA échoue | 422 |
| 21 | `GET /api/events` | — | flux SSE, voir 13.3 | |

Priorités : **P0** (l'app tourne) 1, 3, 4, 5, 6, 7, 8, 9, 13, 14, 15, 21 · **P1** (parcours complet) 2, 11, 12, 20 · **P2** 10, 16 à 19, et `owners_runs` dans 14.

Pourquoi les routes 6 et 7 : l'app édite une label map (un propriétaire par pixel), `rig.json` stocke des régions (rectangles + pixels). La conversion dans les deux sens est une règle du cœur (« la dernière pièce définie gagne », intersection avec les pixels opaques) ; la dupliquer en JavaScript ferait deux implémentations à garder d'accord. L'app n'envoie donc que la label map.

### 13.3 Événements de synchronisation live (`GET /api/events`, Server-Sent Events)

SSE plutôt que WebSocket : le flux est à sens unique, la reconnexion est automatique, et c'est trois lignes dans FastAPI.

| Événement | `data` | Quand | Réaction de l'app |
|---|---|---|---|
| `rig.changed` | `{rev, author, at}` | `rig.json` a changé sur le disque, quelle qu'en soit l'origine | Si `rev` est déjà le sien : ignoré (écho). Sinon, si rien n'est en attente d'écriture : `GET /api/rig` + `GET /api/labelmap`, appliqué comme un lot « Claude » annulable. S'il y a une écriture en attente : rien, le 409 de cette écriture ouvrira le conflit. |
| `anim.changed` | `{rev, author, at}` (`rev: null` si supprimé) | idem pour `anim.json` | idem avec `GET /api/anim` |
| `project.changed` | `{}` | Le sprite nettoyé a changé (nouveau `prepare`) ou un snapshot a été restauré | Rechargement complet, en gardant l'étape |
| (commentaire `: ping`) | — | Toutes les 15 s | Maintient la connexion |

Le serveur doit émettre l'événement **aussi** pour les écritures venues de l'app (deux onglets ouverts se synchronisent ainsi). Le file watcher doit attendre la fin de l'écriture (fichier complet et JSON valide) avant d'émettre ; un `rig.json` invalide écrit par Claude ne casse pas l'app : le serveur n'émet rien et renvoie l'erreur de validation dans `GET /api/project` (`prepare.warnings`).

Perte de connexion : l'app passe en « Serveur injoignable », garde les modifications, et recharge le projet à la reconnexion.

### 13.4 Points du contrat tranchés (vague 2)

Les huit questions posées en vague 1 ont reçu une décision dans `docs/schemas.md`. Ce que l'app en a fait :

| # | Décision du lead dev | Dans l'app |
|---|---|---|
| 1 | Plusieurs entrées de même `id` ; `pixels` (coordonnées sprite) dans `GET /api/report` | Surlignage d'après `pixels` ; repli sur `pixel` − origine du canvas (§ 7.4) |
| 2 | Pas de contrôle « non exécuté » | L'état « Non vérifié » ne sert plus qu'en démo |
| 3 | `rot` positif = anti-horaire à l'écran | Données de démo alignées (presets et rendu simplifié) |
| 4 | `region.pixels` ajoute, `exclude` retire | Voir § 8.4 |
| 5 | Pixels non assignés : pas rendus | La démo fait de même |
| 6 | `rig.pivot` relatif à la bbox du sprite au repos ; pivot canvas dans les routes 14 et 19 | Croix dessinée d'après la route 14 (§ 5.5) |
| 7 | Une animation par projet | Inchangé |
| 8 | Auteurs `app` / `external` | `external` = « Claude », `app` venu d'ailleurs = « autre fenêtre » (§ 8.3) |

### 13.5 Demandes au lead dev (vague 2)

Par ordre d'utilité pour l'utilisateur.

| # | Demande | Pourquoi | En attendant |
|---|---|---|---|
| **D1** | `PUT /api/labelmap` ne réécrit que les pièces dont l'ensemble de pixels a **changé**, et sous forme de **delta** : région d'origine conservée, pixels gagnés ajoutés à `pixels`, pixels perdus ajoutés à `exclude.pixels`. Les autres pièces ne sont pas touchées. | Un trait d'un pixel ne doit pas effacer les polygones que Claude a écrits pour dix autres pièces (§ 8.4). | Avertissement avant, notification après, annulation qui restaure le texte d'origine. |
| **D2** | `GET /api/rig/report` : le contenu de `rig_report.json` pour l'état du disque (`pivot` en coordonnées sprite, `joints` = rayons surveillés par la QA, et par pièce `hidden_pixels`, `missing_pixels`, `fill`, `bbox`). Même `rev` que le rig. | Trois besoins d'un coup : la croix du pivot sans animation ; signaler les articulations non surveillées (§ 16.3) ; chiffrer la zone cachée (§ 16.1). | Pivot affiché seulement quand une frame existe ; rien sur la surveillance. |
| **D3** | `GET /api/rig/parts/{pièce}.png` : la pièce **complète** telle que le moteur la déplace (pixels propres + zone cachée remplie), sur un canvas de la taille du sprite, et `…/{pièce}.json` avec `hidden_runs` (masque de la zone cachée) et `missing`. | Vue de la zone remplie sous chaque pièce (§ 16.1). L'UI ne doit pas recalculer le remplissage. | Non construit. |
| **D4** | `GET /api/report` répond aussi quand aucune pièce n'a de pixels (au lieu de 422 « nothing to render ») : `parts_assigned` en échec avec ses `pixels`, les contrôles de rendu réussis ou marqués sans objet. | Juste après un import, le panneau QA est le meilleur guide (« N pixels non assignés — les voir »). | Message explicatif + « Les voir » calculé sur la label map affichée. |
| **D5** | `GET /api/project` donne les révisions : `rig: {rev}`, `anim: {rev} \| null`. | Évite un `GET /api/anim` qui répond 404 (ligne d'erreur dans la console du navigateur à chaque chargement d'un projet sans animation) et réduit de trois à une les requêtes de détection d'écho de `project.changed`. | 404 traité comme « pas d'animation ». |
| **D6** | Erreurs et avertissements du cœur avec un identifiant stable et des paramètres (`{code: "resample_drops_frames", params: {…}, message: "…"}`), et le message du cœur séparé de la phrase française dans les erreurs (`details.core_message`). | Seule façon propre d'avoir une interface entièrement en français (§ 8.2). | Messages cités tels quels, annoncés comme venant du moteur. |
| **D7** | `POST /api/snapshots` accepte un dossier sans projet (version « vide »). | Rendre annulable la toute première ouverture d'image. | Non annulable, et dit comme tel. |

## 14. La coquille `app/`

### 14.1 Lancer

**Avec le serveur (usage normal).** Dépendances : `pip install -e ".[server]"`.

```
python -m animai.cli.main serve <dossier-projet> --port 8765
```

puis ouvrir `http://127.0.0.1:8765/`. Le dossier peut être vide : l'éditeur affiche alors la zone de dépôt.

**Sans serveur (mode démo).** Les modules JavaScript natifs ne se chargent pas depuis `file://` : il faut servir le dossier.

```
python -m http.server 8765 --directory app
```

puis ouvrir `http://localhost:8765/` (état vide) ou `http://localhost:8765/?demo` (exemple chargé d'office). Ouvert en `file://`, `index.html` affiche un message qui donne cette commande.

### 14.2 Organisation

| Fichier | Rôle |
|---|---|
| `index.html`, `css/tokens.css`, `css/app.css` | Structure, tokens, styles |
| `js/main.js` | Démarrage, gestionnaire clavier |
| `js/store.js` | État, commandes annulables, historique, file d'écriture, conflits, événements |
| `js/edits.js` | Éditions de haut niveau (joint, clé d'os, z de frame, outil, visibilité) |
| `js/viewport.js` | Canvas : rendu net, zoom, pan, calques, outils |
| `js/preview.js` | Cache des frames demandées à la couche de données |
| `js/shortcuts.js` | Table unique des raccourcis |
| `js/label-palette.js` | Couleurs, motifs, numéros de la label map |
| `js/ui/*.js` | Barre du haut, hiérarchie, inspecteur, QA, historique, timeline |
| **`js/data/api.js`** | **Couche d'accès aux données, point d'entrée unique.** Choisit le backend. |
| `js/data/http-backend.js` | Client du vrai serveur (section 13). Vérifié contre lui (§ 15). |
| `tests/preview-vs-export.mjs` | Test automatisé « l'aperçu est identique à l'export » (§ 14.5) |
| `js/data/demo-backend.js` | Faux serveur en mémoire, même contrat |
| `js/data/demo-core.js`, `js/data/demo-sprite.js` | **Simulation du cœur** et données d'exemple. Importés uniquement par `demo-backend.js`. |

Seuls `store.js` et `preview.js` importent `api.js`. Aucun fichier d'interface n'importe `demo-*.js`.

### 14.3 Ce qui est simulé en démo

Tout ce qui suit vit dans `js/data/demo-core.js`, est marqué comme tel en tête de fichier, et **ne sert qu'en mode démo** (sans `?api=`). Contre le serveur, rien de tout cela n'est exécuté et le bandeau « Aperçu simplifié » n'apparaît pas.

| Simulé | Écart avec le vrai cœur |
|---|---|
| **Aperçu d'animation** | Cinématique directe + rotation au plus proche voisin à angle libre. Même sens de rotation que le cœur (positif = anti-horaire), mais pas de RotSprite, pas d'IK, pas de remplissage des pixels cachés, et `pos` suit la rotation du parent. **Ce n'est pas le rendu d'export.** Le viewport l'affiche en toutes lettres (« Aperçu simplifié (démo) — pas le rendu d'export ») aux étapes Animer et Exporter. |
| Presets `idle`, `walk`, `attack` | Poses écrites à la main pour la démo ; les vrais presets appartiennent à l'expert animation. |
| Rééchantillonnage | Un, deux ou trois paramètres comme le cœur, mais échantillonnage naïf. |
| `prepare` | Binarisation de l'alpha au seuil 50 %, palette = couleurs uniques. Pas de détection de grille, pas de détourage, pas de quantification. |
| Template | 15 os posés proportionnellement à la boîte englobante, pièces vides. |
| QA | `parts_assigned`, `holes`, `palette`, `alpha_binary` calculés sur le rendu simplifié ; `canvas_constant` et `pivot_stable` vrais par construction ; `orphans` et `loop_closed` renvoyés « non vérifiés ». |
| Codec régions ↔ label map | Version JavaScript de la règle du cœur. |
| Fichiers projet, révisions, conflits, versions | En mémoire, perdus au rechargement. |
| Claude | Deux boutons dans le panneau de synchro : « Simuler une modification de Claude », « Simuler un conflit d'écriture ». |
| Export | Indisponible ; téléchargement de `rig.json` et `anim.json` à la place. |

Le sprite d'exemple (humanoïde 64×64, 11 couleurs, 13 os, 13 pièces) laisse volontairement 3 pixels non assignés sur le contour de la tête, pour que la QA ait un échec localisé à montrer.

### 14.4 Ce qui reste à construire

1. Outils remplissage et lasso (sans eux, rigger à la main un sprite importé reste long), poignées IK, édition de la structure du squelette, verrouillage.
2. Vue de la zone cachée par pièce et signalement des articulations non surveillées, dès que les routes D2 et D3 existent (§ 16).
3. Calques chevauchement, trous permanents, sprite original.
4. Liste des versions nommées, palette de commandes, dope sheet.
5. Essai avec un lecteur d'écran et avec des utilisateurs daltoniens.

### 14.5 Test « l'aperçu est identique à l'export »

Fichier : `app/tests/preview-vs-export.mjs`. Node 22 ou plus, aucune dépendance. Mode d'emploi complet en tête du fichier.

```
python -m animai.cli.main serve <dossier-projet> --port 8765
node app/tests/preview-vs-export.mjs --url http://127.0.0.1:8765/ --export
```

Le projet servi doit avoir une animation. Le test lance son propre navigateur headless (Edge ou Chrome, profil temporaire, arrêté par son PID) et vérifie, pour chaque frame :

1. **Viewport = moteur.** Calques éteints, les pixels du canvas de l'éditeur sont relus sur fond noir puis sur fond blanc et comparés à `GET /api/render/frames/{i}.png` décodé indépendamment par Node : un pixel opaque doit avoir la couleur du moteur sur les deux fonds, un pixel transparent la couleur du fond. Chaque pixel du sprite doit être un bloc uni de zoom × zoom pixels physiques.
2. **Moteur = export** (`--export`). `POST /api/export` écrit la spritesheet ; chaque cellule est comparée, composante par composante, à la frame de l'étape 1.

`--scale 1.25` simule une mise à l'échelle de l'écran. Code de retour 0 si tout est identique, 1 sinon. `--export` écrit `frames/` et `export/` dans le dossier projet, comme le bouton Exporter.

Résultats au § 15.2.

## 15. Vérification contre le vrai serveur (vague 2)

Projet d'essai : copie de `fixtures/hero64` (`sprite.png`, `rig.json`) dans un dossier temporaire, servi par `python -m animai.cli.main serve`. Navigateur : Edge 154 headless piloté par le protocole DevTools (vraies frappes, vrais clics et glisser), profil temporaire. Chaque point ci-dessous a été constaté **dans l'app et sur le disque** (relecture de `rig.json` / `anim.json` après l'action).

### 15.1 Ce qui a été vérifié

| Cas | Constat |
|---|---|
| Chargement | Redirection vers `?api=/api`, sprite et label map décodés, aucune mention « démo », aucune erreur JavaScript. |
| Joint | Glisser et flèches écrivent `bones.head.joint` ; deux `Ctrl+Z` réécrivent la valeur d'origine. |
| Z-index | Écrit puis annulé sur le disque. |
| Label map | Gomme : `parts_assigned` passe en échec côté serveur et dans le panneau ; clic sur la ligne : pixels fautifs exacts ; pinceau : le contrôle repasse, le surlignage disparaît ; régions réécrites par le cœur. |
| Preset | `walk` écrit `anim.json` ; les 8 frames du moteur arrivent avec pivot, joints et propriétaires ; pas de bandeau « aperçu simplifié ». |
| Durée / fps / frames | Frames = 4, durée doublée (mêmes frames), fps = 10, durée d'une frame : tout écrit, tout annulé. |
| Défaut QA dans une frame | Tête décalée de 9 px en frame 2 : le serveur signale une articulation ouverte ; clic : étape Animer, frame 2, pixel centré ; les pixels surlignés sont bien transparents dans la frame du moteur. Repli sur `pixel` (coordonnées canvas) vérifié. |
| Pivot | La croix utilise le `pivot` de la route 14 (égalité vérifiée avec la réponse du serveur). |
| Modification externe | `rig.json` réécrit par un autre processus : appliqué en moins d'une seconde, notification « Claude a modifié rig.json », entrée « Claude », pastille « · Claude » ; « Annuler ce lot » réécrit la version précédente. Un JSON tronqué sur le disque laisse l'app intacte. |
| Conflit | `rig.json` modifié sur le disque pendant un glisser de joint : le changement attend la fin du geste, bannière au relâchement avec les chemins qui diffèrent, rien d'écrasé ; « Prendre la version de Claude » puis `Ctrl+Z` (ma version réécrite) ; second conflit résolu par « Garder ma version ». |
| Polygone écrit à la main | Avertissement dans la carte Rigger avant ; conversion et notification après un trait ; « Annuler » remet le polygone d'origine dans `rig.json`. |
| Deux fenêtres | A modifie : B se met à jour et annonce « modifié dans une autre fenêtre », A n'affiche rien ; puis l'inverse. |
| Écho | Aucun « Claude a modifié » après ses propres écritures, sur l'ensemble du parcours (contrôlé après chaque groupe d'actions). |
| Export | Résumé, bouton actif, trois fichiers listés et présents sur le disque (`walk.png`, `walk.json`, `walk.gif`). |
| Import par dépôt | `fixtures/mage64x80_bg/source.png` (fond magenta) : projet remplacé, fond retiré par le `prepare` du cœur, étape Préparer, pas de rechargement en boucle ; `Ctrl+Z` restaure sprite, rig et animation précédents. |
| Parcours complet | Image déposée → « Les voir » → deux pièces peintes au pinceau → preset → Exporter → GIF présent sur le disque, sans quitter l'interface. |

69 assertions sur le parcours détaillé, 7 sur le parcours complet, toutes vraies. Le mode démo a été rejoué après les changements (81 assertions).

Non vérifié : coupure du serveur en cours d'édition (bannière « Serveur injoignable ») ; navigateurs autres qu'Edge ; lecteur d'écran ; sprites de plus de 96 px ; un vrai nouvel utilisateur.

### 15.2 Aperçu identique à l'export

`node app/tests/preview-vs-export.mjs --url … --export`, sur le projet d'essai :

| Animation | Densité d'écran | Zoom | Viewport = moteur | Moteur = spritesheet |
|---|---|---|---|---|
| walk, 8 frames | 1 | ×10 | identique (26 928 pixels comparés) | identique |
| attack, 7 frames | 1,25 | ×12 | identique (22 848 pixels) | identique |
| attack, 7 frames | 1,5 | ×16 | identique (22 848 pixels) | identique |

Contrôle négatif : le même test avec le calque squelette allumé échoue, comme attendu. Le lead dev travaillait sur la passe de contour pendant l'essai : le test compare deux sorties du même moteur au même instant, il reste valable quel que soit l'aspect des frames.

### 15.3 Défauts et limites constatés côté serveur

| # | Constat | Reproduction | Attendu | Obtenu |
|---|---|---|---|---|
| S1 | L'auteur d'un changement externe est faux quand son contenu a déjà été écrit par l'API pendant la vie du serveur. | 1. `PUT /api/rig` avec un contenu A. 2. Écrire un contenu B dans `rig.json` depuis un autre processus. 3. Y réécrire exactement A (mêmes octets que le serveur : indentation 2, LF). Reproduit sur une copie de `fixtures/hero64`, A = le rig d'origine avec `bones.spine.joint[0]` augmenté de 5 : après l'étape 3, `GET /api/rig` répond `author: "app"`. | Événement `rig.changed` avec `author: "external"`, et `GET /api/rig` idem. | `author: "app"` : l'éditeur annonce « une autre fenêtre » au lieu de Claude. Cause : `_authors` est indexé par hash de contenu et n'est jamais purgé. Piste : un changement vu par `poll_changes` est externe par définition. |
| S2 | `GET /api/report` et les routes de rendu répondent 422 juste après un import. | `POST /api/project/import` (n'importe quelle image), puis `GET /api/report`. | Un rapport avec `parts_assigned` en échec. | `{"error": "Rendu impossible : rig has no part with pixels: nothing to render"}`. Voir demande D4. |
| S3 | Une articulation fine n'est pas surveillée par `holes`, et rien ne le dit. | Projet `hero64`, preset `walk`, `frames[1].bones.forearm_r = {"pos": [9, 0]}` (l'avant-bras est détaché du bras de 9 px). `GET /api/report`. | `holes` en échec (« open joint 'forearm_r' »). | `holes` réussi, « 12 articulations checked ». Le bras fait 4 px de large : `r0 = 1`, donc rayon surveillé `r = 0`, soit le seul pixel du joint, qui appartient toujours au membre. Conforme à la définition, mais c'est un angle mort : voir § 16.3. |
| S4 | `GET /api/anim` répond 404 sans animation. | Charger un projet sans `anim.json`. | Pas d'erreur réseau pour un état normal. | Ligne d'erreur dans la console du navigateur à chaque chargement. Voir demande D5. |

## 16. Retours de l'expert animation : ce que l'éditeur en fait

### 16.1 Voir la zone remplie sous chaque pièce

Besoin : en riggant, juger ce que le moteur a reconstruit sous une pièce (la zone cachée), puisque c'est ce qui apparaîtra quand le membre de devant bougera.

Décision : un calque **« Zone cachée »** à l'étape Rigger, actif quand une pièce est sélectionnée. Le viewport montre alors cette pièce **seule et complète** (ses pixels + la zone cachée remplie), image fournie par le moteur ; la zone cachée est cernée d'un trait noir et blanc, les pixels restés sans donnée (`fill: "none"`) sont marqués comme les pixels non assignés. Le zoom et le pan restent ceux du viewport : pas de fenêtre annexe. L'inspecteur de la pièce gagne trois lignes : mode de remplissage (`fill` : propre / copie / aucun, écrit dans `rig.json`), nombre de pixels cachés, nombre de pixels sans donnée.

Ce que l'UI ne fera pas : recalculer la zone enclavée ou le remplissage. Il faut les routes D3 (image et masque de la pièce) et D2 (compteurs). Non construit en attendant.

### 16.2 Étiquettes d'os qui recouvrent un sprite étroit

Dans l'éditeur : **fait.** Seul l'os sélectionné est nommé, et son étiquette est posée hors de l'image, reliée au joint par un filet (§ 5.5). Tous les autres noms se lisent dans la hiérarchie.

Pour les images de contrôle de la CLI (overlay du squelette), qui appartiennent au lead dev, même principe recommandé : étiquettes dans la marge, à gauche pour les os lointains et à droite pour les proches, reliées par un filet, jamais sur la silhouette ; à défaut, un numéro par joint et une légende sous l'image.

### 16.3 Articulations non surveillées par la QA

Besoin : la QA ne suit une articulation que si son joint est posé dans la matière commune de l'os et de son parent, et sur un rayon `r = max(r0 − 1, 0)`. Avec `r = 0`, seul le pixel du joint est contrôlé : un membre peut se détacher sans échec (constat S3). Aujourd'hui rien ne le signale.

Décision :

- **Hiérarchie** : une mention **« QA ✕ »** sur tout os dont l'articulation n'est pas suivie ou l'est avec un rayon 0, avec l'infobulle « Articulation non surveillée par la QA : un trou ici ne sera pas détecté ».
- **Inspecteur de l'os** : une ligne « Surveillance QA » : « rayon 3 px », « rayon 0 : seul le pixel du joint est contrôlé », ou « non surveillée : le joint n'est pas dans la matière commune avec *parent* ». Dans les deux derniers cas, le conseil : « déplacez le joint au milieu de la zone où les deux pièces se recouvrent ».
- **Viewport**, calque Pivots : le disque surveillé de l'os sélectionné, en trait noir et blanc ; un joint non surveillé est dessiné en losange creux au lieu d'un rond plein (forme différente, pas seulement couleur).
- **Panneau QA** : la ligne `holes` réussie dit combien d'articulations sont suivies sur combien (« 9 sur 12 ») et devient cliquable pour sélectionner la première non suivie.

Ce qu'il faut du serveur : les rayons (`joints` de `rig_report.json`), par la route D2. Non construit en attendant. Indépendamment de l'éditeur, la question de fond est pour le lead dev et l'expert animation : faut-il un contrôle qui tienne aussi pour les membres de 3 ou 4 px de large (par exemple : le pixel du joint et son voisin côté parent doivent rester opaques) ?
