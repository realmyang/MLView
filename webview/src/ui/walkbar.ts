/**
 * The review walk's bar: a band at the FOOT OF THE DIAGRAM COLUMN,
 * shown only while the walk runs: directly above the bottom sheet's tabs (with the side panel,
 * docked while the canvas keeps RAIL_MIN_CANVAS_W, along the bottom of the diagram). It is a flex
 * row of the diagram column, so it never covers a card, and it comes after the canvas in the
 * document, so Tab goes canvas, walk controls, then the claim in the sheet.
 *
 *   Claim 3 of 16 · Not observed   (the far line's place)
 *   [↑][↓] [Not observed 16] [Findings 4] [All claims 176]   j k step · [ ] quotes · Enter opens again · Esc exits   [Exit]
 *   In the editor beside: train.py · lines 12–14, highlighted. Focus stays here.
 *
 * Below 620 px the place is short, "3/16", and the row under it holds Previous and
 * Next, the filters and Exit. The key hint and the editor line go; a quote the host did not open
 * puts a warning mark on the position, and the Selection pane says why. The whole sentence ("Claim
 * 3 of 16, Not observed" and the reason) is screen-reader text inside the place, not a name on the
 * paragraph.
 *
 * Previous and Next step as k and j do, so a pointer can walk too; their names and tooltips give
 * the keys. The controls are ONE `role="toolbar"` tab stop (Previous, Next, the filters and Exit;
 * the arrow keys move between them). The diagram keeps its place within four Tab presses of the
 * top while the walk runs, and Tab is never held here. The bar itself is a labelled region.
 * Everything it says is derived from the authored ids and basis, the host's stale files and the
 * host's answers; nothing is a verdict.
 *
 * The FAR LINE. On a connection whose other end card is out of view the bar
 * names that card, with which way it lies and how far, as one button beside the place:
 *
 *   (...) [↓] Go to  Load training and validation batches            3 steps later · phase 2  [o]
 *   (...) [→] [inferred] Go to  Rebuild a small student for separate…    next step · phase 6  [o]
 *   (...) [↑] Back to  Select distill.json values                  5 steps earlier · phase 1  [o]
 *
 * (...) is the cap the lit line ends in on the canvas (`render/farcap.ts`), in the same colour and
 * with the same dashed or dotted outline for a connection that is not observed, so the line reads
 * as that cap's caption. The line has a place in the bar for as long as the walk runs, and the
 * controls have the row under it at every width, so the bar is the same height on every claim and
 * the canvas never moves between two claims. On a connection with both ends in view that place
 * says so (`farIdleText`); on a step or a finding it is empty. The line is its own Tab
 * stop, the first after the diagram; key o does the same from the diagram and from the bar. What
 * it says is `far.ts`'s.
 *
 * Under 400 px (`WALK_STACKED_W`) the line has the first row to itself, the second is Previous and
 * Next, the place and Exit, and the filters wrap under them. Where the line is short of room its
 * words fold, the least needed first: the verb, the phase, then the distance (workflow.css).
 */

import { add, button, clear, el, on, svg } from '../dom.js';
import { uiIcon } from '../icons.js';
import { RovingGroup } from './roving.js';
import { FILTER_LABEL, filterCountText, WALK_FILTERS, walkEditorText } from '../walk.js';
import type { WalkFilter, WalkOpenStatus } from '../walk.js';
import { farLineDescription, farLineName, farLineText, farLineTitle, isUncertain } from '../far.js';
import type { End, FarLine } from '../far.js';
import { capGlyph, setOrRemove } from '../render/farcap.js';

export interface WalkBarCallbacks {
  onFilter(filter: WalkFilter): void;
  /** Previous (-1) or Next (+1): as k and j. */
  onStep(delta: number): void;
  /** Exit, or Escape inside the bar: the walk ends and the diagram gets the focus back. */
  onExit(): void;
  /**
   * A walk key pressed while the focus is in the bar (j, k, [, ], u, U, n, p, o), or ← or → while
   * it is on the far line. True when the walk used it.
   */
  onKey(ev: KeyboardEvent): boolean;
  /** The far line was pressed: look at that end of the walk's connection. */
  onFar(end: End): void;
  /** The far line has the pointer or the focus (or lost both): the cap on the canvas answers. */
  onFarCue(on: boolean): void;
  /** The far line went while it held the focus: the diagram takes the keyboard back. */
  onFarGone(): void;
}

export interface WalkBarState {
  /** 0-based place in the filtered list, and its length. */
  position: number;
  total: number;
  filter: WalkFilter;
  counts: Record<WalkFilter, number>;
  offered: readonly WalkFilter[];
  status: WalkOpenStatus;
  /** Below 620 px: the short place ("3/16"), and no key hint and no editor line. */
  narrow: boolean;
  /** Below WALK_STACKED_W: the far line has a row to itself and the filters the rows under the controls. */
  stacked: boolean;
}

/**
 * The panel width (CSS px) under which the bar stacks its rows. From 400 px Previous, Next, the
 * three filters a document usually offers and Exit fit one row under the row the place and the
 * far line share. Narrower, the controls need a second line whatever shares the place's row, so
 * the far line takes the first row to itself: it has the panel's width there and loses none of
 * it when the place grows by "· far end".
 */
export const WALK_STACKED_W = 400;

/** Bars made so far: each far line's description needs an id of its own in the document. */
let walkBarSeq = 0;

/** The keys the bar hands to the walk when one of its controls has the focus. */
const WALK_KEYS = new Set(['j', 'J', 'k', 'K', '[', ']', 'u', 'U', 'n', 'N', 'p', 'P', 'o', 'O']);

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
  private cb: WalkBarCallbacks;
  /** What `update` last showed, for the place (`renderPlace`). */
  private last: WalkBarState | null = null;
  /** The far line, its parts, and what its place says when there is no line. */
  private far: HTMLButtonElement;
  private farIdle: HTMLElement;
  private farGlyph: HTMLElement;
  private farArrow: SVGElement;
  private farTag: HTMLElement;
  private farBody: HTMLElement;
  private farVerb: HTMLElement;
  private farTitle: HTMLElement;
  private farDistance: HTMLElement;
  private farMore: HTMLElement;
  private farDot: HTMLElement;
  private farPhase: HTMLElement;
  /**
   * The far line's description for assistive technology (`farLineDescription`). Without it the
   * tooltip would be the description, and it repeats the title and the phase the name has said.
   */
  private farNote: HTMLElement;
  /** The end the far line goes to, and whether the view is at the far end now. */
  private farEnd: End = 'target';
  private atFar = false;

  constructor(cb: WalkBarCallbacks) {
    this.cb = cb;
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

    // The far line, between the place and the controls in the document (its own Tab stop, the
    // first after the diagram). Its slot keeps its 22 px whether or not there is a line.
    const slot = add(row, el('div', 'mlv-walkbar__farslot'));
    this.farIdle = add(slot, el('span', 'mlv-walkbar__faridle'));
    this.farIdle.hidden = true;
    this.far = add(slot, el('button', 'mlv-walkbar__far'));
    this.far.type = 'button';
    this.far.hidden = true;
    this.far.setAttribute('aria-keyshortcuts', 'o');
    this.farGlyph = add(this.far, capGlyph('mlv-walkbar__farglyph mlv-farglyph'));
    // The way comes first, in a box, so it is read before the title.
    const way = add(this.far, el('span', 'mlv-walkbar__farway'));
    this.farArrow = svg('svg', { class: 'mlv-walkbar__fararrow', viewBox: '0 0 12 12', width: 12, height: 12, 'aria-hidden': 'true', focusable: 'false' });
    this.farArrow.appendChild(svg('path', { d: 'M1.8 6h8M6.6 2.8 9.8 6 6.6 9.2', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
    way.appendChild(this.farArrow);
    // The basis tag is in the document only on a connection that is not observed (`setFar`): a
    // document with nothing uncertain carries no basis tag anywhere (calm-canvas.test.mjs).
    this.farTag = el('span', 'mlv-basis-tag mlv-walkbar__fartag');
    // Three boxes, each one line high, fold the words to the room the line has (workflow.css): the
    // verb goes first, then the phase, then the distance.
    this.farBody = add(this.far, el('span', 'mlv-walkbar__farbody'));
    const lead = add(this.farBody, el('span', 'mlv-walkbar__farlead'));
    const words = add(lead, el('span', 'mlv-walkbar__farwords'));
    this.farVerb = add(words, el('span', 'mlv-walkbar__farverb'));
    this.farTitle = add(words, el('span', 'mlv-walkbar__fartitle'));
    this.farDistance = add(lead, el('span', 'mlv-walkbar__farmeta mlv-walkbar__fardistance'));
    this.farMore = add(this.farBody, el('span', 'mlv-walkbar__farmeta mlv-walkbar__farmore'));
    this.farDot = add(this.farMore, el('span', 'mlv-walkbar__fardot', '·'));
    this.farPhase = add(this.farMore, el('span', 'mlv-walkbar__farphase'));
    add(this.far, el('kbd', 'mlv-kbd mlv-walkbar__farkey', 'o'));
    on(this.far, 'click', () => cb.onFar(this.farEnd));
    on(this.far, 'pointerenter', () => cb.onFarCue(true));
    on(this.far, 'pointerleave', () => cb.onFarCue(this.far.ownerDocument.activeElement === this.far));
    on(this.far, 'focus', () => cb.onFarCue(true));
    on(this.far, 'blur', () => cb.onFarCue(false));

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
    this.farNote = add(this.root, el('span', 'mlv-walkbar__farnote'));
    this.farNote.hidden = true;
    this.farNote.id = 'mlv-walkbar-far' + ++walkBarSeq;
    this.far.setAttribute('aria-describedby', this.farNote.id);

    on(this.root, 'keydown', (ev: KeyboardEvent) => {
      if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      if (ev.key === 'Escape') {
        ev.preventDefault();
        ev.stopPropagation();
        cb.onExit();
        return;
      }
      // On the far line ← and → are the diagram's: the end that lies that way. A click on the line
      // leaves the focus on it, and the line itself prints an arrow.
      const arrow = ev.target === this.far && (ev.key === 'ArrowLeft' || ev.key === 'ArrowRight');
      if (!arrow && !WALK_KEYS.has(ev.key)) return;
      if (cb.onKey(ev)) ev.preventDefault();
    });
    this.roving = new RovingGroup(this.tools);
  }

  get shown(): boolean {
    return !this.root.hidden;
  }

  /** The bar was last drawn with its rows stacked (`WalkBarState.stacked`). */
  get stacked(): boolean {
    return this.root.getAttribute('data-rows') === 'stacked';
  }

  /** Show the bar with this state, or hide it (`null`). */
  update(s: WalkBarState | null): void {
    if (!s) {
      this.root.hidden = true;
      return;
    }
    this.root.hidden = false;
    this.root.setAttribute('data-layout', s.narrow ? 'narrow' : 'wide');
    setOrRemove(this.root, 'data-rows', s.stacked ? 'stacked' : null);
    const problem = s.status.state === 'blocked' || s.status.state === 'failed';
    this.root.setAttribute('data-walk-status', s.status.state);
    this.last = s;
    this.renderPlace();
    const editorLine = walkEditorText(s.status);
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

  /**
   * The walk's place: "7/176" narrow, "Claim 7 of 176 · All claims" wide. While the view is at
   * the far end of the walk's connection the place says so ("7/176 · far end"), because the claim
   * has not changed and the picture has.
   */
  private renderPlace(): void {
    const s = this.last;
    if (!s) return;
    const problem = s.status.state === 'blocked' || s.status.state === 'failed';
    const label = FILTER_LABEL[s.filter];
    const far = this.atFar && s.total > 0;
    const place = (s.total ? 'Claim ' + (s.position + 1) + ' of ' + s.total : 'No claims') + (far ? ', far end' : '');
    const short = (s.total ? s.position + 1 + '/' + s.total : '0/0') + (far ? ' · far end' : '');
    this.posText.textContent = s.narrow ? short : place + ' · ' + label;
    this.posMark.hidden = !(problem && s.narrow);
    const editorLine = walkEditorText(s.status);
    // The narrow form keeps the whole sentence for assistive technology (as text, not a name on
    // the paragraph, which ARIA does not allow) and for the tooltip. Wide, the visible place says it.
    this.pos.title = place + ' · ' + label + (s.narrow ? '. ' + editorLine : '');
    if (s.narrow) this.posText.setAttribute('aria-hidden', 'true');
    else this.posText.removeAttribute('aria-hidden');
    this.posSpoken.textContent = s.narrow ? place + ', ' + label + (problem ? '. ' + editorLine : '') : '';
    this.posSpoken.hidden = !s.narrow;
  }

  /**
   * Show the far line with this content, or hide it (`null`). The line's slot keeps its
   * height either way. A line that goes while it holds the focus hands the keyboard back.
   */
  setFar(line: FarLine | null): void {
    if (!line) {
      if (this.far.hidden) return;
      const doc = this.far.ownerDocument;
      const focused = !!doc && doc.activeElement === this.far;
      this.far.hidden = true;
      this.farIdle.hidden = !this.farIdle.textContent;
      if (this.farTag.parentNode) this.farTag.parentNode.removeChild(this.farTag);
      this.setAtFar(false);
      if (focused) this.cb.onFarGone();
      return;
    }
    this.farEnd = line.end;
    const uncertain = isUncertain(line.basis);
    const text = farLineText(line);
    const write = (node: Element, value: string) => {
      if (node.textContent !== value) node.textContent = value;
    };
    this.far.setAttribute('data-far-end', line.end);
    setOrRemove(this.far, 'data-basis', uncertain ? line.basis : null);
    // The copy of the cap is drawn as the cap is: with the outline of the line it sits on.
    setOrRemove(this.farGlyph, 'data-basis', line.drawnBasis);
    for (const mark of [this.farGlyph, this.far]) {
      setOrRemove(mark, 'data-phase-tone', line.tone);
      setOrRemove(mark, 'data-sev', line.severity);
    }
    this.farGlyph.classList.toggle('is-lit', !!line.lit);
    // The words a card's tag prints (`basisTagText`), and the same dashed or dotted outline.
    if (uncertain) {
      write(this.farTag, text.tag);
      setOrRemove(this.farTag, 'data-basis', line.basis);
      if (this.farTag.parentNode !== this.far) this.far.insertBefore(this.farTag, this.farBody);
    } else if (this.farTag.parentNode) this.farTag.parentNode.removeChild(this.farTag);
    write(this.farVerb, text.verb);
    write(this.farTitle, text.title);
    this.farArrow.style.transform = 'rotate(' + line.compass * 45 + 'deg)';
    // The distance printed is the one in reading order ("12 steps later"), which does not change
    // as the reader pans; the screens are in the tooltip.
    write(this.farDistance, text.distance);
    this.farMore.hidden = !text.phase;
    this.farDot.hidden = !text.phase;
    this.farPhase.hidden = !text.phase;
    write(this.farPhase, text.phase);
    setOrRemove(this.far, 'aria-label', farLineName(line));
    const title = farLineTitle(line);
    if (this.far.title !== title) this.far.title = title;
    write(this.farNote, farLineDescription(line));
    this.far.hidden = false;
    this.farIdle.hidden = true;
    this.setAtFar(line.atFar);
  }

  /**
   * What the far line's slot says when there is no far line: on a connection whose two ends are
   * in view, that they are (`farIdleText`); nothing on a step or a finding.
   */
  setFarIdle(text: string): void {
    if (this.farIdle.textContent !== text) this.farIdle.textContent = text;
    this.farIdle.hidden = !text || !this.far.hidden;
  }

  /**
   * The far line's own copy of the cap is the cap's twin: shown while a cap is on the canvas, and
   * not when the line of a far connection is in sight all the way to a card that is only partly
   * in view (no cap is drawn then, and a copy here would send the reader looking for one).
   */
  markFar(capped: boolean): void {
    if (this.farGlyph.hidden === capped) this.farGlyph.hidden = !capped;
  }

  /** The cap on the canvas has the pointer: the far line answers. */
  cueFar(on: boolean): void {
    this.far.classList.toggle('is-cued', on);
  }

  private setAtFar(atFar: boolean): void {
    if (this.atFar === atFar) return;
    this.atFar = atFar;
    this.renderPlace();
  }

  /** Focus the bar's tab stop among its controls (or Exit), for a test or a caller that moves the focus here. */
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
  if (filter === 'revision') return 'Walk the ' + count + ' added or changed since the revision this panel showed before (About lists them)';
  if (filter === 'changed') return 'Walk the ' + count + ' whose quotes cite a file that changed or went missing since publishing';
  return 'Walk all ' + count + ': every step, connection and finding';
}
