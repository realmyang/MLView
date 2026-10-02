/**
 * The review walk's bar (viewer M3, roadmap step 11): a band at the FOOT OF THE DIAGRAM COLUMN,
 * shown only while the walk runs: directly above the bottom sheet's tabs (with the side panel, at
 * 1260 px and wider, along the bottom of the diagram). It is a flex row of the diagram column, so
 * it never covers a card, and it comes after the canvas in the document, so Tab goes canvas, walk
 * controls, then the claim in the sheet.
 *
 *   Claim 3 of 16 · Not observed   [↑][↓] [Not observed 16] [Findings 4] [All claims 176]   j k step · [ ] quotes · Esc exits   [Exit]
 *   In the editor beside: train.py · lines 12–14, highlighted. Focus stays here.
 *
 * Below 620 px (the measured beside-the-code panel is 541 px) it is one row: "3/16", Previous and
 * Next, the filters and Exit. The key hint and the editor line go; a quote the host did not open
 * puts a warning mark on the position, and the Selection pane says why. The whole sentence ("Claim
 * 3 of 16, Not observed" and the reason) is screen-reader text inside the place, not a name on the
 * paragraph (M3 review, A11Y-M3-6).
 *
 * Previous and Next (M3 review, A11Y-M3-2) step as k and j do, so a pointer can walk too; their
 * names and tooltips give the keys. The controls are ONE `role="toolbar"` tab stop (Previous,
 * Next, the filters and Exit; the arrow keys move between them). The diagram keeps its place within four Tab presses of the top while the walk
 * runs, and Tab is never held here. The bar itself is a labelled region. Everything it says is derived from
 * the authored ids and basis, the host's stale files and the host's answers; nothing is a verdict.
 */

import { add, button, clear, el, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { RovingGroup } from './roving.js';
import { FILTER_LABEL, filterCountText, WALK_FILTERS, walkEditorText } from '../walk.js';
import type { WalkFilter, WalkOpenStatus } from '../walk.js';

export interface WalkBarCallbacks {
  onFilter(filter: WalkFilter): void;
  /** Previous (-1) or Next (+1): as k and j. */
  onStep(delta: number): void;
  /** Exit, or Escape inside the bar: the walk ends and the diagram gets the focus back. */
  onExit(): void;
  /**
   * A walk key pressed while the focus is in the bar (j, k, [, ], u, U, n, p). True when the walk
   * used it.
   */
  onKey(ev: KeyboardEvent): boolean;
}

export interface WalkBarState {
  /** 0-based place in the filtered list, and its length. */
  position: number;
  total: number;
  filter: WalkFilter;
  counts: Record<WalkFilter, number>;
  offered: readonly WalkFilter[];
  status: WalkOpenStatus;
  /** Below 620 px: "3/16", the filters and Exit only. */
  narrow: boolean;
}

/** The keys the bar hands to the walk when one of its controls has the focus. */
const WALK_KEYS = new Set(['j', 'J', 'k', 'K', '[', ']', 'u', 'U', 'n', 'N', 'p', 'P']);

export class WalkBar {
  readonly root: HTMLElement;
  private pos: HTMLElement;
  private posText: HTMLElement;
  private posMark: HTMLElement;
  /** The whole place sentence for a screen reader, while the visible place is the short "3/16". */
  private posSpoken: HTMLElement;
  private tools: HTMLElement;
  private filters = new Map<WalkFilter, HTMLButtonElement>();
  private keys: HTMLElement;
  private exit: HTMLButtonElement;
  private editor: HTMLElement;
  private editorText: HTMLElement;
  private editorIcon: HTMLElement;
  private roving: RovingGroup;

  constructor(cb: WalkBarCallbacks) {
    this.root = el('section', 'mlv-walkbar');
    this.root.setAttribute('aria-label', 'Review walk');
    this.root.hidden = true;

    const row = add(this.root, el('div', 'mlv-walkbar__row'));
    this.pos = add(row, el('p', 'mlv-walkbar__pos'));
    this.posMark = add(this.pos, el('span', 'mlv-walkbar__mark'));
    this.posMark.setAttribute('aria-hidden', 'true');
    this.posMark.appendChild(uiIcon('warning', 12));
    this.posMark.hidden = true;
    this.posText = add(this.pos, el('span', 'mlv-walkbar__postext'));
    this.posSpoken = add(this.pos, el('span', 'mlv-sr mlv-walkbar__posspoken'));

    this.tools = add(row, el('div', 'mlv-walkbar__tools'));
    this.tools.setAttribute('role', 'toolbar');
    this.tools.setAttribute('aria-label', 'Review walk controls');
    const steps = add(this.tools, el('div', 'mlv-walkbar__steps'));
    steps.setAttribute('role', 'group');
    steps.setAttribute('aria-label', 'Step through the claims');
    for (const [delta, name, cls] of [[-1, 'Previous claim (k)', 'prev'], [1, 'Next claim (j)', 'next']] as const) {
      const b = button('mlv-btn mlv-btn--icon mlv-walkbar__step mlv-walkbar__step--' + cls, '', name);
      b.setAttribute('data-walk-step', cls);
      b.title = name + (delta < 0 ? ', or ↑' : ', or ↓');
      b.appendChild(uiIcon('chevron', 12));
      on(b, 'click', () => cb.onStep(delta));
      steps.appendChild(b);
    }
    const group = add(this.tools, el('div', 'mlv-walkbar__filters'));
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', 'Which claims to walk');
    for (const filter of WALK_FILTERS) {
      // Not a `.mlv-chip--btn`: an unpressed filter is one of several choices, never struck through.
      const b = button('mlv-walkbar__filter', '');
      b.setAttribute('data-walk-filter', filter);
      b.setAttribute('aria-pressed', 'false');
      add(b, el('span', 'mlv-walkbar__flabel', FILTER_LABEL[filter]));
      add(b, el('span', 'mlv-walkbar__fcount', '0'));
      on(b, 'click', () => cb.onFilter(filter));
      this.filters.set(filter, b);
      group.appendChild(b);
    }
    this.keys = add(this.tools, el('span', 'mlv-walkbar__keys'));
    this.keys.setAttribute('aria-hidden', 'true');
    for (const [k, what] of [['j k', 'step'], ['[ ]', 'quotes'], ['Enter', 'opens again'], ['Esc', 'exits']]) {
      const part = add(this.keys, el('span', 'mlv-walkbar__key'));
      for (const one of k.split(' ')) add(part, el('kbd', 'mlv-kbd', one));
      add(part, el('span', '', ' ' + what));
    }
    this.exit = button('mlv-btn mlv-walkbar__exit', '', 'Exit the review (Escape)');
    this.exit.appendChild(uiIcon('close', 12));
    add(this.exit, el('span', 'mlv-walkbar__exitlabel', 'Exit'));
    this.exit.title = 'Exit the review (Escape). The walk remembers its place for this revision.';
    on(this.exit, 'click', () => cb.onExit());
    this.tools.appendChild(this.exit);

    this.editor = add(this.root, el('p', 'mlv-walkbar__editor'));
    this.editorIcon = add(this.editor, el('span', 'mlv-walkbar__editoricon'));
    this.editorIcon.setAttribute('aria-hidden', 'true');
    this.editorIcon.appendChild(uiIcon('warning', 12));
    this.editorText = add(this.editor, el('span', 'mlv-walkbar__editortext'));

    on(this.root, 'keydown', (ev: KeyboardEvent) => {
      if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      if (ev.key === 'Escape') {
        ev.preventDefault();
        ev.stopPropagation();
        cb.onExit();
        return;
      }
      if (!WALK_KEYS.has(ev.key)) return;
      if (cb.onKey(ev)) ev.preventDefault();
    });
    this.roving = new RovingGroup(this.tools);
  }

  get shown(): boolean {
    return !this.root.hidden;
  }

  /** Show the bar with this state, or hide it (`null`). */
  update(s: WalkBarState | null): void {
    if (!s) {
      this.root.hidden = true;
      return;
    }
    this.root.hidden = false;
    this.root.setAttribute('data-layout', s.narrow ? 'narrow' : 'wide');
    const problem = s.status.state === 'blocked' || s.status.state === 'failed';
    this.root.setAttribute('data-walk-status', s.status.state);
    const label = FILTER_LABEL[s.filter];
    const place = s.total ? 'Claim ' + (s.position + 1) + ' of ' + s.total : 'No claims';
    this.posText.textContent = s.narrow ? (s.total ? s.position + 1 + '/' + s.total : '0/0') : place + ' · ' + label;
    this.posMark.hidden = !(problem && s.narrow);
    const editorLine = walkEditorText(s.status);
    // The narrow form keeps the whole sentence for assistive technology (as text, not a name on
    // the paragraph, which ARIA does not allow) and for the tooltip. Wide, the visible place says it.
    this.pos.title = place + ' · ' + label + (s.narrow ? '. ' + editorLine : '');
    if (s.narrow) this.posText.setAttribute('aria-hidden', 'true');
    else this.posText.removeAttribute('aria-hidden');
    this.posSpoken.textContent = s.narrow ? place + ', ' + label + (problem ? '. ' + editorLine : '') : '';
    this.posSpoken.hidden = !s.narrow;
    for (const [filter, b] of this.filters) {
      const offered = s.offered.indexOf(filter) >= 0;
      b.hidden = !offered;
      b.setAttribute('aria-pressed', filter === s.filter ? 'true' : 'false');
      const count = b.querySelector('.mlv-walkbar__fcount');
      if (count) count.textContent = String(s.counts[filter]);
      const n = s.counts[filter];
      b.setAttribute('aria-label', filterCountText(filter, n));
      b.title = filterTitle(filter, n);
    }
    this.keys.hidden = s.narrow;
    this.editor.hidden = s.narrow;
    this.editor.setAttribute('data-walk-status', s.status.state);
    this.editorIcon.hidden = !problem;
    this.editorText.textContent = editorLine;
    this.roving.sync();
  }

  /** The bar's tab stop (a filter or Exit), for a test or a caller that moves the focus here. */
  focus(): void {
    const stop = Array.from(this.tools.querySelectorAll<HTMLElement>('button')).find((b) => b.tabIndex === 0 && !b.hidden);
    try {
      (stop || this.exit).focus();
    } catch (_e) {
      /* a detached bar cannot take the focus */
    }
  }

  destroy(): void {
    this.roving.destroy();
    clear(this.root);
  }
}

function filterTitle(filter: WalkFilter, n: number): string {
  const count = n + (n === 1 ? ' claim' : ' claims');
  if (filter === 'notObserved') return 'Walk the ' + count + ' the author marked inferred or unresolved (the header\'s "not observed" count)';
  if (filter === 'findings') return 'Walk the ' + count + ' that are findings';
  if (filter === 'changed') return 'Walk the ' + count + ' whose quotes cite a file that changed or went missing since publishing';
  return 'Walk all ' + count + ': every step, connection and finding';
}
