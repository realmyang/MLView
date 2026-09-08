/**
 * Inline SVG symbols. One line-art glyph per NodeKind (UX_DESIGN section 4.1),
 * drawn in a 16x16 box, stroked in the stage colour. Unknown kinds fall back to
 * the question-mark glyph — invariant 1.1/6.
 */

import { SVG_NS, svg, setAttrs } from './dom.js';

const KIND_PATHS: Record<string, string> = {
  entrypoint: 'M5 3.2 12.4 8 5 12.8Z',
  config: 'M2.2 4.5h11.6M2.2 8h11.6M2.2 11.5h11.6M5.6 3.1v2.8M10.4 6.6v2.8M7 10.1v2.8',
  dataset:
    'M3 4.3c0-1 2.24-1.8 5-1.8s5 .8 5 1.8-2.24 1.8-5 1.8-5-.8-5-1.8ZM3 4.3v3.4c0 1 2.24 1.8 5 1.8s5-.8 5-1.8V4.3M3 7.7v3.4c0 1 2.24 1.8 5 1.8s5-.8 5-1.8V7.7',
  dataloader: 'M2 4.2h2.6l6.8 7.6H14M2 11.8h2.6l6.8-7.6H14M11.6 2.4 14 4.2l-2.4 1.8M11.6 10 14 11.8l-2.4 1.8',
  split: 'M2 8h3.6l3.4-4.2H14M9 12.2 5.6 8H2M11.8 2 14 3.8l-2.2 1.8M11.8 10.4 14 12.2l-2.2 1.8',
  transform: 'M2.4 13.6 10 6M8.4 4.4l3.2 3.2M12 1.8v2.8M10.6 3.2h2.8M4 2v1.8M3.1 2.9h1.8',
  augment:
    'M5.2 2.2 6.1 5 8.9 5.9 6.1 6.8 5.2 9.6 4.3 6.8 1.5 5.9 4.3 5ZM11.4 8.2l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7Z',
  model: 'M8 2 14 5 8 8 2 5ZM2 8.2 8 11.2 14 8.2M2 11.2 8 14.2 14 11.2',
  layer: 'M2.4 4.6h11.2v2.4H2.4ZM2.4 9h11.2v2.4H2.4Z',
  loss: 'M8 2.2A5.8 5.8 0 1 0 8 13.8 5.8 5.8 0 0 0 8 2.2ZM8 5.4A2.6 2.6 0 1 0 8 10.6 2.6 2.6 0 0 0 8 5.4ZM8 7.4a.6.6 0 1 0 0 1.2.6.6 0 0 0 0-1.2Z',
  optimizer: 'M2.6 12.2a6.4 6.4 0 1 1 10.8 0M8 8.4 11.2 5.2M7.2 12.2h1.6',
  scheduler: 'M2 12.4 5.6 8.6l2.4 2.2L13.4 4.6M9.6 4.6h3.8v3.8',
  scaler: 'M2.4 4h11.2v8H2.4ZM5.4 4v2.4M8 4v3.6M10.6 4v2.4',
  train_loop: 'M13.2 8A5.2 5.2 0 1 1 11.5 4.1M13.6 2.6v3.2h-3.2',
  eval_loop: 'M8 2.2A5.8 5.8 0 1 0 8 13.8 5.8 5.8 0 0 0 8 2.2ZM5.2 8.1 7.2 10.2 11 6',
  metric: 'M3 13V8.4M6.4 13V4.4M9.8 13v-3.4M13.2 13V6.4M2 13.8h12',
  checkpoint: 'M2.6 3h7.6l3.2 3.2v7.4H2.6ZM5.6 3v3.4h4.6V3M5.6 13.6v-3.6h4.6v3.6',
  tracker:
    'M8 6.8A1.2 1.2 0 1 0 8 9.2 1.2 1.2 0 0 0 8 6.8ZM5.2 5.2a4 4 0 0 0 0 5.6M10.8 5.2a4 4 0 0 1 0 5.6M3.1 3.1a7 7 0 0 0 0 9.8M12.9 3.1a7 7 0 0 1 0 9.8',
  predict: 'M9.2 1.6 4 8.6h3.3l-.7 5.8L12 7.2H8.5Z',
  function:
    'M6.6 2.8c-1.7 0-2.1.9-2.1 2.3v1.1c0 1-.5 1.6-1.5 1.6 1 0 1.5.6 1.5 1.6v1.1c0 1.4.4 2.3 2.1 2.3M9.4 2.8c1.7 0 2.1.9 2.1 2.3v1.1c0 1 .5 1.6 1.5 1.6-1 0-1.5.6-1.5 1.6v1.1c0 1.4-.4 2.3-2.1 2.3',
  class: 'M3 2.6h10v10.8H3ZM3 6.2h10M5.4 8.8h5.2M5.4 11h3.2',
  artifact: 'M8 2 14 5v6l-6 3-6-3V5ZM2 5l6 3 6-3M8 8v6',
  external: 'M9 2.8h4.2V7M13.2 2.8 7.4 8.6M11.6 9.4v3.8H2.8V4.4h3.8',
  unknown:
    'M8 2.2A5.8 5.8 0 1 0 8 13.8 5.8 5.8 0 0 0 8 2.2ZM6.2 6.3a1.85 1.85 0 1 1 2.7 1.7c-.6.3-.9.8-.9 1.5M8 11.2v.9',
};

export const KNOWN_KINDS = Object.keys(KIND_PATHS).sort();

export function kindPath(kind: string): string {
  return KIND_PATHS[kind] || KIND_PATHS.unknown;
}

export function isKnownKind(kind: string): boolean {
  return Object.prototype.hasOwnProperty.call(KIND_PATHS, kind);
}

/** The 26x26 tinted tile with the 16px kind glyph inside it. */
export function kindIcon(kind: string, size = 16): SVGElement {
  const root = svg('svg', {
    class: 'mlv-icon',
    viewBox: '0 0 16 16',
    width: size,
    height: size,
    'aria-hidden': 'true',
    focusable: 'false',
  });
  const p = document.createElementNS(SVG_NS, 'path');
  setAttrs(p, {
    d: kindPath(kind),
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': '1.3',
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
    'vector-effect': 'non-scaling-stroke',
  });
  root.appendChild(p);
  return root;
}

/* Small chrome glyphs, all single-path, 16x16. */
const UI_PATHS: Record<string, string> = {
  search: 'M7.2 2.4a4.8 4.8 0 1 0 0 9.6 4.8 4.8 0 0 0 0-9.6ZM10.8 10.8 14 14',
  refresh: 'M13.2 8A5.2 5.2 0 1 1 11.5 4.1M13.6 2.6v3.2h-3.2',
  export: 'M8 10.6V2.4M5.2 5.2 8 2.4l2.8 2.8M2.8 10.4v2.8h10.4v-2.8',
  close: 'M3.6 3.6 12.4 12.4M12.4 3.6 3.6 12.4',
  chevron: 'M6 3.6 10.4 8 6 12.4',
  plus: 'M8 3.2v9.6M3.2 8h9.6',
  minus: 'M3.2 8h9.6',
  fit: 'M2.6 6V2.6H6M10 2.6h3.4V6M13.4 10v3.4H10M6 13.4H2.6V10',
  rail: 'M2.4 3h11.2v10H2.4ZM9.6 3v10',
  open: 'M9 2.8h4.2V7M13.2 2.8 7.4 8.6M11.6 9.4v3.8H2.8V4.4h3.8',
  filter: 'M2.4 3.4h11.2L9.2 8.4v4.2L6.8 13.6V8.4Z',
  target: 'M8 2.6v2.2M8 11.2v2.2M2.6 8h2.2M11.2 8h2.2M8 5.2A2.8 2.8 0 1 0 8 10.8 2.8 2.8 0 0 0 8 5.2Z',
  check: 'M3 8.4 6.4 11.8 13 5.2',
  scope: 'M2.4 3.2h11.2v9.6H2.4ZM5.6 6.2h4.8v3.6H5.6Z',
  flow: 'M2.4 8h8.4M8.4 5.2 11.6 8l-3.2 2.8M13.2 6.4v3.2',
  /** The legend key (VIEW-10): a list with a swatch beside each row. */
  legend: 'M2.4 3.6h2.4v2.4H2.4ZM2.4 10h2.4v2.4H2.4ZM6.8 4.8h6.8M6.8 11.2h6.8',
};

export function uiIcon(name: string, size = 14): SVGElement {
  const root = svg('svg', {
    class: 'mlv-uicon',
    viewBox: '0 0 16 16',
    width: size,
    height: size,
    'aria-hidden': 'true',
    focusable: 'false',
  });
  const p = document.createElementNS(SVG_NS, 'path');
  setAttrs(p, {
    d: UI_PATHS[name] || UI_PATHS.close,
    fill: 'none',
    stroke: 'currentColor',
    'stroke-width': '1.4',
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
  });
  root.appendChild(p);
  return root;
}
