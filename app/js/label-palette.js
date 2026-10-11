// Palette de la label map (docs/ux-spec.md § 10) : 8 teintes Okabe-Ito, distinguables en
// deutéranopie / protanopie / tritanopie, x 3 motifs. Le NUMÉRO de la pièce reste l'identifiant
// de référence : la couleur seule ne porte jamais l'information.

export const LABEL_COLORS = [
  { hex: '#E69F00', name: 'orange' },
  { hex: '#56B4E9', name: 'bleu ciel' },
  { hex: '#009E73', name: 'vert bleuté' },
  { hex: '#F0E442', name: 'jaune' },
  { hex: '#0072B2', name: 'bleu' },
  { hex: '#D55E00', name: 'vermillon' },
  { hex: '#CC79A7', name: 'rose violacé' },
  { hex: '#4D4D4D', name: 'gris foncé' },
];
export const LABEL_PATTERNS = ['plein', 'damier', 'rayures'];

const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const dark = (c) => c.map((v) => Math.round(v * 0.45));
const toHex = (c) => '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('');

/** Style de la pièce d'index donné (0 = première pièce de rig.json, affichée « 1 »). */
export function labelStyle(index) {
  const base = LABEL_COLORS[index % LABEL_COLORS.length];
  const pattern = Math.floor(index / LABEL_COLORS.length) % LABEL_PATTERNS.length;
  const color = rgb(base.hex);
  return { number: index + 1, hex: base.hex, color, dark: dark(color), pattern, colorName: base.name, patternName: LABEL_PATTERNS[pattern] };
}

/** Couleur du pixel (x, y) pour une pièce : applique le motif à l'échelle du pixel du sprite. */
export function labelPixel(style, x, y) {
  if (style.pattern === 1) return (x + y) % 2 ? style.dark : style.color;
  if (style.pattern === 2) return y % 2 ? style.dark : style.color;
  return style.color;
}

/** Fond CSS d'une pastille reprenant couleur + motif. */
export function swatchCss(style) {
  const d = toHex(style.dark);
  if (style.pattern === 1) return `repeating-conic-gradient(${d} 0 25%, ${style.hex} 0 50%) 0 0 / 6px 6px`;
  if (style.pattern === 2) return `repeating-linear-gradient(0deg, ${style.hex} 0 3px, ${d} 3px 6px)`;
  return style.hex;
}
