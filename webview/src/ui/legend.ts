/**
 * The legend (VIEW-10).
 *
 * No legend existed anywhere in `webview/src`: a first-time reader got severity
 * glyphs, four edge kinds, ghost cards, back-edge chevrons, collapsed-group
 * count badges and confidence buckets with nothing explaining any of them. The
 * stage chip row is a FILTER, not a key, and the `?` sheet is a shortcut list.
 *
 * Every row here is GENERATED from what actually draws it — `markers.ts` for the
 * severity glyphs, `render/edges.ts`'s `KNOWN_EDGE_KINDS` and `buildDefs()` for
 * the strokes and their arrowheads, the real card classes for the node states —
 * so the key cannot drift from the picture. `legendModel()` is the data behind
 * it, exported so a test can assert the two lists are the same list.
 */

import { add, el, iconButton, on, svg } from '../dom.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, SEVERITY_ORDER, SEVERITY_WORD } from '../markers.js';
import { ARROW_HEADS, edgeKindClass, KNOWN_EDGE_KINDS } from '../render/edges.js';

export interface LegendRow {
  /** `severity` | `edge` | `state` | `confidence`. */
  group: string;
  key: string;
  label: string;
  detail: string;
}

export interface LegendSection {
  id: string;
  title: string;
  rows: LegendRow[];
}

const EDGE_DETAIL: Record<string, string> = {
  data: 'A value produced here is consumed there.',
  call: 'This step calls that definition.',
  control: 'Loop or ordering, not a value.',
  config: 'A setting reaches this step.',
  unknown: 'A connection kind this renderer does not know.',
};

/** The card treatments, named exactly as `render/nodes.ts` stamps them. */
const STATE_ROWS: LegendRow[] = [
  { group: 'state', key: 'is-ghost', label: 'Missing step', detail: 'A stage the pipeline should have and does not.' },
  { group: 'state', key: 'is-collapsed-group', label: 'Collapsed group', detail: 'A unit folded to one card; the badge counts what is inside.' },
  { group: 'state', key: 'is-dynamic', label: 'Dynamic scope', detail: 'A call the analyzer could not resolve statically.' },
  { group: 'state', key: 'is-lowconf', label: 'Low confidence', detail: 'Drawn, but the evidence for it is thin.' },
  { group: 'state', key: 'is-stale', label: 'Stale', detail: 'The file changed since this analysis ran.' },
  { group: 'state', key: 'boundary', label: 'Boundary stub', detail: 'Pulled in by a scope hop; its findings are out of scope, so it carries no badge.' },
];

const CONFIDENCE_ROWS: LegendRow[] = [
  { group: 'confidence', key: 'certain', label: 'certain', detail: 'Every factor the rule wants is present.' },
  { group: 'confidence', key: 'likely', label: 'likely', detail: 'Strong evidence, one factor short.' },
  { group: 'confidence', key: 'possible', label: 'possible', detail: 'Consistent with the defect; check it.' },
  { group: 'confidence', key: 'speculative', label: 'speculative', detail: 'A hint, offered rather than asserted.' },
];

/** The legend's content, derived from the drawing tables. */
export function legendModel(): LegendSection[] {
  return [
    {
      id: 'severity',
      title: 'Severity',
      rows: SEVERITY_ORDER.map((sev) => ({
        group: 'severity',
        key: sev,
        label: SEVERITY_WORD[sev],
        detail:
          sev === 'high'
            ? 'Very likely wrong, and it changes the result.'
            : sev === 'medium'
              ? 'Worth fixing before you trust the numbers.'
              : 'A smell, not a defect.',
      })),
    },
    {
      id: 'edges',
      title: 'Connections',
      rows: KNOWN_EDGE_KINDS.concat(['unknown']).map((kind) => ({
        group: 'edge',
        key: kind,
        label: kind,
        detail: EDGE_DETAIL[kind] || '',
      })).concat([{ group: 'edge', key: 'back', label: 'loop back', detail: 'The return leg of a loop, marked with a chevron.' }]),
    },
    { id: 'states', title: 'Card states', rows: STATE_ROWS },
    { id: 'confidence', title: 'Confidence', rows: CONFIDENCE_ROWS },
  ];
}

/**
 * A short stroke drawn with the REAL edge classes and the REAL arrowhead path.
 *
 * The head is drawn INLINE rather than through `url(#mlv-arrow-…)`: a <marker>
 * id is document-scoped, and a second copy of `buildDefs()` on the page would
 * shadow the scene's own markers.
 */
function edgeSwatch(kind: string): SVGElement {
  const known = edgeKindClass(kind === 'back' ? 'control' : kind);
  const root = svg('svg', { class: 'mlv-legend__swatch', viewBox: '0 0 44 14', width: 44, height: 14, 'aria-hidden': 'true' });
  const g = svg('g', { class: 'mlv-edge mlv-edge--' + known + (kind === 'back' ? ' mlv-edge--back' : '') });
  // `mlv-legend__edge`, never `mlv-edge__path`: edge.css lists both on every
  // kind rule, so the swatch shows the real stroke without becoming a decoy for
  // the queries that walk the scene's cables.
  const path = svg('path', { class: 'mlv-legend__edge', d: 'M2 7 H 33' });
  g.appendChild(path);
  const head = ARROW_HEADS[known] || ARROW_HEADS.unknown;
  const arrow = svg('path', { class: 'mlv-arrow mlv-arrow--' + known, d: head.d, transform: 'translate(31,2)' });
  if (!head.filled) arrow.setAttribute('fill', 'none');
  g.appendChild(arrow);
  if (kind === 'back') {
    g.appendChild(
      svg('path', {
        class: 'mlv-edge__loopmark',
        d: 'M22 3 L18 7 L22 11',
        fill: 'none',
        stroke: 'var(--mlv-edge)',
        'stroke-width': 1.3,
        'stroke-linecap': 'round',
      }),
    );
  }
  root.appendChild(g);
  return root;
}

/** A miniature card carrying the same class the scene stamps on a real one. */
function stateSwatch(key: string): HTMLElement {
  const card = el('div', 'mlv-legend__card mlv-node');
  // `data-legend-role`, never `data-view-role`: that attribute is projection
  // data, and scope.css lists both selectors so the swatch still shows the real
  // dashed, faded treatment (see the note beside that rule).
  if (key === 'boundary') card.setAttribute('data-legend-role', 'boundary');
  else card.classList.add(key);
  if (key === 'is-collapsed-group') add(card, el('span', 'mlv-badge__count', '6'));
  return card;
}

function confidenceSwatch(bucket: string): HTMLElement {
  const chip = el('span', 'mlv-chip mlv-chip--conf mlv-chip--conf-' + bucket, bucket);
  chip.setAttribute('data-confidence', bucket);
  return chip;
}

function swatchFor(row: LegendRow): Node {
  if (row.group === 'severity') return severityGlyph(row.key, 14, '');
  if (row.group === 'edge') return edgeSwatch(row.key);
  if (row.group === 'state') return stateSwatch(row.key);
  return confidenceSwatch(row.key);
}

/**
 * The panel itself: anchored to the minimap corner of the canvas, collapsible,
 * and remembered per viewer through `ViewState.legendOpen`.
 */
export class Legend {
  readonly root: HTMLElement;
  private body: HTMLElement;
  private toggleBtn: HTMLButtonElement;
  private openState = false;

  constructor(onToggle: (open: boolean) => void) {
    this.root = el('aside', 'mlv-legend');
    this.root.setAttribute('data-legend', '1');
    this.root.setAttribute('aria-label', 'Diagram legend');

    const head = add(this.root, el('div', 'mlv-legend__head'));
    add(head, el('h2', 'mlv-legend__title', 'Legend'));
    this.toggleBtn = iconButton('mlv-btn mlv-btn--icon mlv-legend__close', 'Close legend');
    this.toggleBtn.appendChild(uiIcon('close', 12));
    on(this.toggleBtn, 'click', () => {
      this.setOpen(false);
      onToggle(false);
    });
    head.appendChild(this.toggleBtn);

    this.body = add(this.root, el('div', 'mlv-legend__body'));
    for (const section of legendModel()) {
      const block = add(this.body, el('section', 'mlv-legend__section'));
      block.setAttribute('data-legend-section', section.id);
      add(block, el('h3', 'mlv-legend__heading', section.title));
      const list = add(block, el('dl', 'mlv-legend__list'));
      for (const row of section.rows) {
        const term = add(list, el('dt', 'mlv-legend__term'));
        term.setAttribute('data-legend-row', row.group + ':' + row.key);
        const swatch = swatchFor(row);
        term.appendChild(swatch);
        // A swatch that already SPELLS the row's name is the label. The
        // confidence chip is a word-shaped pill, so adding the name beside it
        // made every Confidence row read "certain / certain / Every factor the
        // rule wants is present." — the only self-repeating row in the legend,
        // in the section a first-time reader is most likely to be reading.
        if ((swatch.textContent || '').trim() !== row.label) {
          add(term, el('span', 'mlv-legend__label', row.label));
        }
        add(list, el('dd', 'mlv-legend__desc', row.detail));
      }
    }
    this.setOpen(false);
  }

  get open(): boolean {
    return this.openState;
  }

  setOpen(next: boolean): void {
    this.openState = next;
    this.root.hidden = !next;
  }

  toggle(): boolean {
    this.setOpen(!this.openState);
    return this.openState;
  }
}
