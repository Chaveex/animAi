// Table UNIQUE des raccourcis : elle alimente à la fois le gestionnaire clavier (main.js)
// et l'aide affichée sur « ? ». Ajouter un raccourci = ajouter une ligne ici + son action.
//
// Les chiffres sont reconnus par touche physique (event.code) : sur un clavier AZERTY ils
// fonctionnent sans Maj. Les lettres et symboles sont reconnus par caractère (event.key).

const mods = (e, { ctrl = false, shift = false, alt = false } = {}) =>
  (e.ctrlKey || e.metaKey) === ctrl && e.shiftKey === shift && e.altKey === alt;
const letter = (ch, m) => (e) => e.key.toLowerCase() === ch && mods(e, m);
const digit = (n) => (e) => (e.code === 'Digit' + n || e.code === 'Numpad' + n) && !e.ctrlKey && !e.metaKey && !e.altKey;
const named = (key, m) => (e) => e.key === key && mods(e, m);
const arrow = (key) => (e) => e.key === key && !e.ctrlKey && !e.metaKey && !e.altKey; // Maj = pas de 5

export const SHORTCUTS = [
  { group: 'Général', keys: '?', label: 'Afficher / masquer cette aide', id: 'help', match: (e) => e.key === '?' },
  { group: 'Général', keys: 'Ctrl+Z', label: 'Annuler', id: 'undo', match: letter('z', { ctrl: true }) },
  { group: 'Général', keys: 'Ctrl+Y ou Ctrl+Maj+Z', label: 'Rétablir', id: 'redo', match: (e) => letter('y', { ctrl: true })(e) || letter('z', { ctrl: true, shift: true })(e) },
  { group: 'Général', keys: 'Échap', label: 'Abandonner le geste en cours, fermer, puis désélectionner', id: 'escape' },
  { group: 'Général', keys: '1 2 3 4', label: 'Étape Préparer / Rigger / Animer / Exporter', id: 'step1', match: digit(1) },
  { id: 'step2', match: digit(2) },
  { id: 'step3', match: digit(3) },
  { id: 'step4', match: digit(4) },
  { group: 'Général', keys: 'F6 / Maj+F6', label: 'Zone suivante / précédente (outils, hiérarchie, viewport, panneau droit, timeline)', id: 'zoneNext', match: named('F6') },
  { id: 'zonePrev', match: named('F6', { shift: true }) },
  { group: 'Général', keys: 'Maj+T', label: 'Thème clair / sombre', id: 'theme', match: letter('t', { shift: true }) },

  { group: 'Outils', keys: 'V', label: 'Sélection (clic = pièce propriétaire du pixel, ou joint)', id: 'toolSelect', match: letter('v') },
  { group: 'Outils', keys: 'B', label: 'Pinceau : assigner des pixels à la pièce sélectionnée', id: 'toolBrush', match: letter('b') },
  { group: 'Outils', keys: 'E', label: 'Gomme : rendre des pixels non assignés', id: 'toolEraser', match: letter('e') },
  { group: 'Outils', keys: 'J', label: 'Déplacer un pivot (Rigger) ou poser le squelette en glissant les pivots (Animer)', id: 'toolJoint', match: letter('j') },
  { group: 'Outils', keys: 'T', label: 'Retouche (Animer) : peindre ou effacer des pixels dans la frame courante, avec les couleurs de la palette', id: 'toolRetouch', match: letter('t') },
  { group: 'Outils', keys: 'Alt+clic', label: 'Retouche : pipette, prendre la couleur sous le curseur' },
  { group: 'Outils', keys: 'Double-clic', label: 'Outil Déplacer, étape Rigger : ajouter un pivot à cet endroit' },
  { group: 'Outils', keys: 'Maj+glisser / Alt+glisser', label: 'Outil Déplacer, étape Animer : angle libre (sinon pas de 15°) / décaler l\'os au lieu de tourner' },
  { group: 'Outils', keys: 'Alt+clic', label: 'Pinceau / gomme : prendre la pièce sous le curseur' },
  { group: 'Outils', keys: 'H', label: 'Afficher / masquer l\'os ou la pièce sélectionnés', id: 'visibility', match: letter('h') },

  { group: 'Viewport', keys: '← ↑ → ↓', label: 'Déplacer le curseur pixel, ou le joint avec l\'outil Déplacer (1 px ; Maj = 5 px)', id: 'left', match: arrow('ArrowLeft') },
  { id: 'right', match: arrow('ArrowRight') },
  { id: 'up', match: arrow('ArrowUp') },
  { id: 'down', match: arrow('ArrowDown') },
  { group: 'Viewport', keys: 'Entrée', label: 'Appliquer l\'outil au curseur pixel', id: 'apply', match: named('Enter') },
  { group: 'Viewport', keys: '+ / −', label: 'Zoom avant / arrière (entiers uniquement)', id: 'zoomIn', match: (e) => (e.key === '+' || e.key === '=') && !e.ctrlKey && !e.metaKey && !e.altKey },
  { id: 'zoomOut', match: (e) => e.key === '-' && !e.ctrlKey && !e.metaKey && !e.altKey },
  { group: 'Viewport', keys: '0', label: 'Ajuster le sprite à la fenêtre', id: 'fit', match: digit(0) },
  { group: 'Viewport', keys: 'Molette', label: 'Zoom centré sur le curseur' },
  { group: 'Viewport', keys: 'Espace+glisser, clic molette', label: 'Déplacer la vue' },
  { group: 'Viewport', keys: 'Alt+flèches', label: 'Déplacer la vue au clavier', id: 'panLeft', match: named('ArrowLeft', { alt: true }) },
  { id: 'panRight', match: named('ArrowRight', { alt: true }) },
  { id: 'panUp', match: named('ArrowUp', { alt: true }) },
  { id: 'panDown', match: named('ArrowDown', { alt: true }) },

  { group: 'Calques', keys: 'S', label: 'Squelette', id: 'layerSkeleton', match: letter('s') },
  { group: 'Calques', keys: 'L', label: 'Label map colorée et numérotée', id: 'layerLabelmap', match: letter('l') },
  { group: 'Calques', keys: 'P', label: 'Pivots (joints et pivot d\'export)', id: 'layerPivots', match: letter('p') },
  { group: 'Calques', keys: 'G', label: 'Grille de pixels (à partir de ×4)', id: 'layerGrid', match: letter('g') },
  { group: 'Calques', keys: 'O', label: 'Onion skin (précédente en bleu, suivante en orange)', id: 'layerOnion', match: letter('o') },
  { group: 'Calques', keys: 'Maj+B', label: 'Fond du viewport : damier, gris, noir, blanc', id: 'background', match: letter('b', { shift: true }) },

  { group: 'Animation', keys: 'Espace', label: 'Lecture / pause', id: 'play' },
  { group: 'Animation', keys: ', ou Page préc.', label: 'Frame précédente', id: 'framePrev', match: (e) => (e.key === ',' || e.key === 'PageUp') && mods(e) },
  { group: 'Animation', keys: '. ou ; ou Page suiv.', label: 'Frame suivante', id: 'frameNext', match: (e) => (e.key === '.' || e.key === ';' || e.key === 'PageDown') && !e.ctrlKey && !e.metaKey && !e.altKey },
  { group: 'Animation', keys: 'Début / Fin', label: 'Première / dernière frame', id: 'frameFirst', match: named('Home') },
  { id: 'frameLast', match: named('End') },
  { group: 'Animation', keys: 'R / Maj+R', label: 'Tourner l\'os sélectionné de +15° / −15° dans la frame courante', id: 'rotPlus', match: letter('r') },
  { id: 'rotMinus', match: letter('r', { shift: true }) },
  { group: 'Animation', keys: 'K', label: 'Capturer la pose : garder la frame et en ouvrir une copie à la suite', id: 'capture', match: letter('k') },

  { group: 'Hiérarchie', keys: '↑ ↓', label: 'Os ou pièce précédent / suivant (la sélection suit)' },
  { group: 'Hiérarchie', keys: '← →', label: 'Replier / déplier, remonter au parent' },
  { group: 'Hiérarchie', keys: 'F2 / Suppr', label: 'Renommer / supprimer le pivot (os) qui a le focus' },
  { group: 'Timeline', keys: '← →', label: 'Frame précédente / suivante quand la bande de frames a le focus' },
  { group: 'Inspecteur', keys: 'Glisser sur un libellé', label: 'Faire varier la valeur ; ↑ ↓ dans le champ = ±1 pas' },
  { group: 'Remplacements', keys: '← ↑ → ↓', label: 'Déplacer l\'ancre quand l\'image du remplacement a le focus (1 px ; Maj = 5 px)' },
];
