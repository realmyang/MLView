/**
 * The legend (VIEW-10, rewritten in viewer M2).
 *
 * Every row here is GENERATED from what actually draws it — `markers.ts` for the
 * severity glyphs, `render/edges.ts`'s arrowhead and edge.css's basis dashes for
 * the strokes, `render/nodes.ts`'s basis tags and the phase tones for the cards —
 * so the key cannot drift from the picture. `legendModel()` is the data behind
 * it, exported so a test can assert the two lists are the same list.
 *
 * Viewer M2: line style now encodes the claim's basis, not the connection kind,
 * so the eight-kind key is gone; the kinds the diagram uses are listed in words.
 */

import { add, el, iconButton, on, svg } from '../dom.js';
import { uiIcon } from '../icons.js';
import { severityGlyph, SEVERITY_ORDER, SEVERITY_WORD } from '../markers.js';
import { ARROW_HEAD } from '../render/edges.js';
import { basisTagText } from '../render/nodes.js';
import { PHASE_TONES } from '../layout/model.js';

export interface LegendRow {
  /** `basis` | `severity` | `edge` | `phase` | `freshness`. */
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

/**
 * WorkflowDocument 1.0's three authored evidence bases. Viewer M2: only the exceptions are
 * marked, by line style and a word, never by colour alone.
 */
const BASIS_ROWS: LegendRow[] = [
  { group: 'basis', key: 'observed', label: 'Observed', detail: 'Directly supported by cited workspace source. Most claims are observed, so they carry no mark.' },
  { group: 'basis', key: 'inferred', label: 'Inferred', detail: 'Reasoned from cited source and stated assumptions; the quotes do not show all of it. Dashed border or line, and an "inferred" tag.' },
  { group: 'basis', key: 'unresolved', label: 'Unresolved', detail: 'The available evidence does not settle this claim. It does not mean the step is absent. Dotted border or line, faint hatching, and a "? unresolved" tag.' },
];

const EDGE_ROWS: LegendRow[] = [
  { group: 'edge', key: 'arrow', label: 'connection', detail: 'Points from the step that produces something to the step that uses it. The line style shows the basis above, not the kind.' },
  { group: 'edge', key: 'back', label: 'loop back', detail: 'The return leg of a loop, marked with a chevron.' },
  { group: 'edge', key: 'kinds', label: 'kind', detail: 'What a connection carries (data, call, state…) is written in its hover card and the Selection tab.' },
];

const PHASE_ROWS: LegendRow[] = [
  { group: 'phase', key: 'order', label: 'phase colour', detail: 'Each phase gets a colour by its place in the document, shown on the lane\'s left rule and the card\'s left edge. It means nothing else. Problems are the only other colour on the diagram.' },
];

const FRESHNESS_ROWS: LegendRow[] = [
  // Viewer M2: the status bar says it in muted words; there is no mark for it, and no green.
  { group: 'freshness', key: 'verified', label: 'Unchanged', detail: 'The status bar counts the cited files that still match the hashes published with this revision. Unchanged means the quoted lines still exist; it does not prove the interpretation.' },
  { group: 'freshness', key: 'draft', label: 'Not checked', detail: 'This revision has no published source hashes, so the status bar says freshness is not checked.' },
  // Viewer M1: the only freshness mark on the diagram. Unchanged files get none.
  { group: 'freshness', key: 'stale', label: 'Changed or missing', detail: 'A cited file no longer matches the published revision. Cards, connections, findings and quotes that cite it carry this mark and a border in the warning colour, and their jumps are blocked. It does not say whether the claim is still right. When the notice above says the workspace root is the wrong folder, the mark means the file is unchanged in another folder.' },
];

/** The legend's content, derived from the drawing tables. */
export function legendModel(): LegendSection[] {
  return [
    { id: 'basis', title: 'Claim basis', rows: BASIS_ROWS },
    {
      id: 'severity',
      title: 'Findings',
      rows: SEVERITY_ORDER.map((sev): LegendRow => ({
        group: 'severity',
        key: sev,
        label: SEVERITY_WORD[sev],
        detail:
          sev === 'high'
            ? 'High potential impact if the finding is correct.'
            : sev === 'medium'
              ? 'Medium potential impact if the finding is correct.'
              : 'Low potential impact if the finding is correct. Severity does not express certainty.',
      })).concat([
        { group: 'severity', key: 'short', label: 'numbers', detail: 'Findings numbered in document order. A new revision can renumber them; the hover card, the Selection tab and Refine prompts use the real id.' },
      ]),
    },
    { id: 'edges', title: 'Connections', rows: EDGE_ROWS },
    { id: 'phases', title: 'Phases', rows: PHASE_ROWS },
    { id: 'freshness', title: 'Source freshness', rows: FRESHNESS_ROWS },
  ];
}

/**
 * A short stroke drawn with the REAL edge classes and the REAL arrowhead path: `basis` picks the
 * dash (edge.css keys it on `data-basis`, as on the canvas).
 *
 * The head is drawn INLINE rather than through `url(#mlv-arrow)`: a <marker> id is
 * document-scoped, and a second copy of `buildDefs()` on the page would shadow the scene's own.
 */
function edgeSwatch(basis: string, back = false): SVGElement {
  const root = svg('svg', { class: 'mlv-legend__swatch', viewBox: '0 0 44 14', width: 44, height: 14, 'aria-hidden': 'true' });
  const g = svg('g', { class: 'mlv-edge mlv-edge--data' + (back ? ' mlv-edge--back' : '') });
  g.setAttribute('data-basis', basis);
  // `mlv-legend__edge`, never `mlv-edge__path`: edge.css lists both on every stroke rule, so the
  // swatch shows the real stroke without becoming a decoy for the queries that walk the cables.
  g.appendChild(svg('path', { class: 'mlv-legend__edge', d: 'M2 7 H 33' }));
  g.appendChild(svg('path', { class: 'mlv-arrow', d: ARROW_HEAD.d, transform: 'translate(31,2)' }));
  if (back) {
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

/** A miniature card carrying the basis the scene stamps on a real one, and its line. */
function basisSwatch(basis: string): HTMLElement {
  const wrap = el('span', 'mlv-legend__basis');
  const card = add(wrap, el('span', 'mlv-legend__card'));
  card.setAttribute('data-basis', basis);
  const tag = basisTagText(basis);
  if (tag) {
    const chip = add(card, el('span', 'mlv-legend__tag', tag));
    chip.setAttribute('data-basis', basis);
  }
  wrap.appendChild(edgeSwatch(basis));
  return wrap;
}

/** The phase tones, one bar each, in order. */
function phaseSwatch(): HTMLElement {
  const wrap = el('span', 'mlv-legend__phases');
  wrap.setAttribute('aria-hidden', 'true');
  for (let i = 0; i < PHASE_TONES; i++) {
    const bar = add(wrap, el('span', 'mlv-legend__phase'));
    bar.setAttribute('data-phase-tone', String(i));
  }
  return wrap;
}

function swatchFor(row: LegendRow): Node {
  if (row.group === 'severity') {
    if (row.key === 'short') return el('span', 'mlv-legend__short', 'F1');
    return severityGlyph(row.key, 14, '');
  }
  if (row.group === 'basis') return basisSwatch(row.key);
  if (row.group === 'edge') {
    if (row.key === 'kinds') return el('span', 'mlv-chip', 'data');
    return edgeSwatch('observed', row.key === 'back');
  }
  if (row.group === 'phase') return phaseSwatch();
  if (row.key === 'stale') {
    const chip = el('span', 'mlv-chip mlv-chip--stale');
    chip.appendChild(uiIcon('warning', 11));
    add(chip, el('span', '', 'changed'));
    return chip;
  }
  return el('span', 'mlv-chip', row.key === 'verified' ? 'hashes' : 'no hashes');
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
        // Viewer M2: a basis swatch is a miniature card above a line, too wide to share the term
        // column with its name, so the name opens the description instead.
        const nameInDetail = row.group === 'basis';
        // A swatch that already SPELLS the row's name is the label. The
        // confidence chip is a word-shaped pill, so adding the name beside it
        // made every Confidence row read "certain / certain / Every factor the
        // rule wants is present." — the only self-repeating row in the legend,
        // in the section a first-time reader is most likely to be reading.
        if (!nameInDetail && (swatch.textContent || '').trim() !== row.label) {
          add(term, el('span', 'mlv-legend__label', row.label));
        }
        const desc = add(list, el('dd', 'mlv-legend__desc'));
        if (nameInDetail) add(desc, el('strong', 'mlv-legend__label', row.label + '. '));
        desc.appendChild(desc.ownerDocument.createTextNode(row.detail));
      }
    }
    this.setOpen(false);
  }

  get open(): boolean {
    return this.openState;
  }

  /**
   * Viewer M2: name the connection kinds this diagram uses, with how many of each, since the line
   * no longer shows the kind. `unspecified` counts the connections that carry no kind at all.
   */
  setKinds(kinds: { kind: string; count: number }[], unspecified: number): void {
    const desc = this.root.querySelector('[data-legend-row="edge:kinds"]');
    const dd = desc && desc.nextElementSibling;
    if (!dd) return;
    const prior = dd.querySelector('.mlv-legend__authored');
    if (prior) prior.remove();
    const parts: string[] = [];
    if (kinds.length) {
      // Every count names its unit: "Connections in this diagram, by kind: data 12, call 3."
      const shown = kinds.slice(0, 8).map((k) => k.kind + ' ' + k.count).join(', ');
      parts.push('Connections in this diagram, by kind: ' + shown + (kinds.length > 8 ? ', and ' + (kinds.length - 8) + ' more kinds' : '') + '.');
    }
    if (unspecified > 0) parts.push(unspecified + (unspecified === 1 ? ' connection has' : ' connections have') + ' no kind.');
    if (!parts.length) return;
    add(dd, el('span', 'mlv-legend__authored', ' ' + parts.join(' ')));
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
