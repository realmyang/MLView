/**
 * Inline SVG symbols. One line-art glyph per NodeKind (UX_DESIGN section 4.1),
 * drawn in a 16x16 box, stroked in the stage colour.
 *
 * The table is keyed to the retired analyzer's kinds. An AUTHORED node's kind
 * is free text, so `nodeGlyphKind` maps the contract's recommended kinds and
 * their common synonyms onto these glyphs and gives everything else a neutral
 * dot (Campaign 3, issue 14): 711 of 817 shakedown nodes, 647 of them
 * `observed`, used to draw the question mark, which read as uncertainty beside
 * an observed basis. Uncertainty is the authored basis's to show (node.css
 * `[data-basis="unresolved"]`). Only a legacy graph's unknown kind still falls
 * back to the question mark.
 */

import { SVG_NS, svg, setAttrs } from './dom.js';
import type { MLNode } from './types.js';

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

/**
 * Glyphs only an authored node draws. Kept out of `KIND_PATHS`, so the legacy
 * `isKnownKind` vocabulary (and the words a screen reader hears) is unchanged.
 */
const AUTHORED_PATHS: Record<string, string> = {
  /** A neutral dot: a step whose kind word this renderer has no picture for. */
  step: 'M8 5.6A2.4 2.4 0 1 0 8 10.4 2.4 2.4 0 0 0 8 5.6Z',
  /** Four tiles: an authored group or phase container. */
  group: 'M2.6 2.6h4.4V7H2.6ZM9 2.6h4.4V7H9ZM2.6 9h4.4v4.4H2.6ZM9 9h4.4v4.4H9Z',
};

/**
 * Authored kind words, normalised (lower case, `-`/`_`/spaces collapsed to one
 * space), to a glyph. The contract's recommended node kinds come first; the
 * rest are synonyms seen in real authored documents. Framework-agnostic on
 * purpose: nothing here names a library.
 */
const AUTHORED_GLYPHS: Record<string, string> = {
  // recommended kinds
  operation: 'function', data: 'dataset', model: 'model', state: 'layer', objective: 'loss',
  optimizer: 'optimizer', evaluation: 'eval_loop', metric: 'metric', output: 'external', config: 'config',
  loop: 'train_loop', branch: 'split', group: 'group', entrypoint: 'entrypoint', artifact: 'artifact',
  // synonyms
  op: 'function', step: 'function', function: 'function', method: 'function', compute: 'function',
  computation: 'function', process: 'function', construction: 'function', initialization: 'function',
  hook: 'function', callback: 'function', forward: 'function', class: 'class', component: 'class',
  dataset: 'dataset', 'data source': 'dataset', datasource: 'dataset', input: 'dataset', inputs: 'dataset',
  batch: 'dataset', dataloader: 'dataloader', 'data loader': 'dataloader', loader: 'dataloader',
  batching: 'dataloader', sampler: 'dataloader', 'data pipeline': 'dataloader', split: 'split',
  'data split': 'split', decision: 'split', conditional: 'split', condition: 'split', selection: 'split',
  control: 'split', 'control flow': 'split', preprocessing: 'transform', preprocess: 'transform',
  postprocessing: 'transform', transform: 'transform', transformation: 'transform', augmentation: 'augment',
  augment: 'augment', network: 'model', module: 'model', architecture: 'model', layer: 'layer',
  'state update': 'layer', update: 'layer', 'state init': 'layer', variable: 'layer', buffer: 'layer',
  parameters: 'layer', weights: 'layer', loss: 'loss', criterion: 'loss', optimiser: 'optimizer',
  optimization: 'optimizer', optimisation: 'optimizer', 'optimizer step': 'optimizer', 'optimization step': 'optimizer',
  scheduler: 'scheduler', schedule: 'scheduler', 'learning rate': 'scheduler', scaler: 'scaler',
  'training loop': 'train_loop', 'train loop': 'train_loop', 'optimization loop': 'train_loop', epoch: 'train_loop',
  'training run': 'train_loop', eval: 'eval_loop', validation: 'eval_loop', test: 'eval_loop',
  'evaluation loop': 'eval_loop', metrics: 'metric', score: 'metric', scoring: 'metric', log: 'tracker',
  logging: 'tracker', logger: 'tracker', tracker: 'tracker', history: 'tracker', checkpoint: 'checkpoint',
  checkpointing: 'checkpoint', persistence: 'checkpoint', save: 'checkpoint', outputs: 'external',
  result: 'external', return: 'external', display: 'external', external: 'external', configuration: 'config',
  settings: 'config', hyperparameters: 'config', arguments: 'config', args: 'config', environment: 'config',
  'entry point': 'entrypoint', entry: 'entrypoint', launcher: 'entrypoint', 'api entry': 'entrypoint',
  main: 'entrypoint', script: 'entrypoint', file: 'artifact', inference: 'predict', predict: 'predict',
  prediction: 'predict', sampling: 'predict', generation: 'predict', phase: 'group', stage: 'group',
};

/** `Data-Source`, `data_source` and `data source` are one kind word. */
export function normalizeKindWord(kind: string): string {
  return String(kind || '').trim().toLowerCase().replace(/[\s_-]+/g, ' ');
}

/**
 * The glyph an authored kind word draws: the whole word, else its last word
 * (`custom metric`, `evaluation data`), else its first (`model loading`), else
 * the neutral dot. Never the question mark.
 */
export function authoredGlyphKind(kind: string | undefined): string {
  const key = normalizeKindWord(kind || '');
  if (!key || key === 'unknown') return 'step';
  if (AUTHORED_GLYPHS[key]) return AUTHORED_GLYPHS[key];
  const words = key.split(/[^a-z0-9]+/).filter(Boolean);
  const last = words[words.length - 1];
  if (last && AUTHORED_GLYPHS[last]) return AUTHORED_GLYPHS[last];
  const first = words[0];
  if (first && AUTHORED_GLYPHS[first]) return AUTHORED_GLYPHS[first];
  return 'step';
}

/** The glyph a card or group header draws. A collapsed group is still a group. */
export function nodeGlyphKind(node: Pick<MLNode, 'kind'>, groupLike: boolean): string {
  return groupLike ? 'group' : authoredGlyphKind(node.kind);
}

export function kindPath(kind: string): string {
  return KIND_PATHS[kind] || AUTHORED_PATHS[kind] || KIND_PATHS.unknown;
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

/*
 * Chrome glyphs (viewer M2): drawn for MLView in the codicon style — a 16 px grid, one stroked
 * path, round joins — and inlined, because the webview's CSP (`default-src 'none'`) admits no
 * icon font. They are original drawings, not copies of the codicon set.
 */
const UI_PATHS: Record<string, string> = {
  search: 'M7 2.6a4.4 4.4 0 1 0 0 8.8 4.4 4.4 0 0 0 0-8.8ZM10.2 10.2 13.6 13.6',
  /** The ... menu: three dots (tiny stroked circles read as filled dots). */
  more: 'M3.4 7.4a.6.6 0 1 0 0 1.2.6.6 0 0 0 0-1.2ZM8 7.4a.6.6 0 1 0 0 1.2.6.6 0 0 0 0-1.2ZM12.6 7.4a.6.6 0 1 0 0 1.2.6.6 0 0 0 0-1.2Z',
  close: 'M3.6 3.6 12.4 12.4M12.4 3.6 3.6 12.4',
  chevron: 'M6 3.6 10.4 8 6 12.4',
  plus: 'M8 3.2v9.6M3.2 8h9.6',
  minus: 'M3.2 8h9.6',
  /** Fit the whole diagram: four corners. */
  fit: 'M2.6 6V2.6H6M10 2.6h3.4V6M13.4 10v3.4H10M6 13.4H2.6V10',
  /** The side rail: a window with its right column. */
  rail: 'M2.4 3h11.2v10H2.4ZM9.6 3v10',
  open: 'M9 2.8h4.2V7M13.2 2.8 7.4 8.6M11.6 9.4v3.8H2.8V4.4h3.8',
  /** Zoom to the selection: a crosshair. */
  target: 'M8 2.6v2.2M8 11.2v2.2M2.6 8h2.2M11.2 8h2.2M8 5.2A2.8 2.8 0 1 0 8 10.8 2.8 2.8 0 0 0 8 5.2Z',
  // Viewer M1: a source file no longer matches its published hash (with text beside it, never alone).
  warning: 'M8 2.2 14.4 13.4H1.6ZM8 6.4v3.4M8 11.6v.1',
  /** About this revision (the request and coverage). */
  info: 'M8 2.2a5.8 5.8 0 1 0 0 11.6A5.8 5.8 0 0 0 8 2.2ZM8 7.2v4M8 5v.1',
  /** Viewer M2: "not observed" — a dashed square, the mark an inferred card carries. */
  notobserved: 'M2.6 5V2.6H5M7 2.6h2M11 2.6h2.4V5M13.4 7v2M13.4 11v2.4H11M9 13.4H7M5 13.4H2.6V11M2.6 9V7',
  flow: 'M2.4 8h8.4M8.4 5.2 11.6 8l-3.2 2.8M13.2 6.4v3.2',
  /** The legend key (VIEW-10): a list with a swatch beside each row. */
  legend: 'M2.4 3.6h2.4v2.4H2.4ZM2.4 10h2.4v2.4H2.4ZM6.8 4.8h6.8M6.8 11.2h6.8',
  copy: 'M5.8 5.8h7.6v7.6H5.8ZM2.6 10.2V2.6h7.6v3.2',
  /** The overview minimap: a frame with its viewport. */
  minimap: 'M2.4 3.6h11.2v8.8H2.4ZM8.4 7.4h4.4v4.4H8.4Z',
  /** VIEW-07: a picture in a frame — "export the diagram". */
  image: 'M2.4 3.4h11.2v9.2H2.4ZM2.4 10.6 5.8 7.4l2.4 2.2 2.2-2 3.2 3M10.3 5.3a1.05 1.05 0 1 0 0 2.1 1.05 1.05 0 0 0 0-2.1Z',
  /** Viewer M3: the review walk: a pointer at the first of three rows. */
  review: 'M2.4 3.2 4.8 5.4 2.4 7.6M7.2 5.4h6.4M7.2 9.4h6.4M2.6 13h11',
  /** The shortcut sheet: a keyboard. */
  keyboard: 'M1.8 4.2h12.4v7.6H1.8ZM4.2 6.6h.1M6.7 6.6h.1M9.2 6.6h.1M11.7 6.6h.1M4.8 9.4h6.4',
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
