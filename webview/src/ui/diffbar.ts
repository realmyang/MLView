/**
 * VIEW-08 — the diff banner and its chips.
 *
 *   ⟂  +2 nodes · −2 nodes · 1 new findings · 1 fixed
 *      base vision_pipeline → head vision_pipeline      [changed only]
 *      2 added · 2 removed · 1 changed · 9 unchanged
 *      ▸ both analyses read their whole workspace, so a removed node is a
 *        removed node.
 *
 * Three rules govern every string in this file.
 *
 * **The headline is the analyzer's sentence.** §11.38's `summary.headline` is
 * the wording all three hosts share, so it is drawn verbatim when the overlay's
 * own arrays support it — and recomputed, with a note saying so, when they do
 * not (`DiffIndex` decides; this file only draws the answer).
 *
 * **`notes[]` is never elided.** §11.38 C is explicit: a `removed` status can
 * mean not-analyzed, truncated, projected away, a different root or a different
 * analyzer version, and a reader who saw *"−16 nodes"* and concluded a refactor
 * deleted them would have been misled by the tool. Every note is drawn, in full,
 * and a pair with nothing to declare gets the one line that says so.
 *
 * **The banner states what the VIEWER could not draw**, beside what the analyzer
 * could not see: removed edges are counted and not drawn, a resurrected ghost
 * carries no findings because they live in the base document, and under a scope
 * or a cap some of the diff is simply not in this document. Those are the
 * viewer's blind spots, and this is the only surface that can own them.
 */

import { add, button, clear, el, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import type { DiffIndex } from '../diff/overlay.js';

export interface DiffBarCallbacks {
  /** Toggle the "changed only" projection. */
  onChangedOnly(next: boolean): void;
  /** Drop the overlay entirely and go back to the plain diagram. */
  onDismiss(): void;
}

export interface DiffBarState {
  diff: DiffIndex | null;
  changedOnly: boolean;
  /** How many of the overlay's removed nodes this document actually drew. */
  ghostsDrawn: number;
  /**
   * How many nodes the overlay calls changed or unchanged are actually on
   * screen. A cap, a scope or a filter can absorb the rest, and then the chips
   * count more than the diagram holds (VIEW-R6).
   */
  namedDrawn: number;
  /** Nodes on screen, and in the whole document — stated when they differ. */
  shown: number;
  of: number;
  /** True when "changed only" was asked for and had nothing to project. */
  changedEmpty: boolean;
  /**
   * The HOST's name for what this is compared against — a git ref, a saved run
   * (11.43 D). The overlay knows only the two workspace roots, which are the
   * same string when both sides came from one checkout, so without this the row
   * would read "base X → head X" and name nothing at all.
   */
  baseLabel: string;
}

/** What each §11.38 C note kind means, in the reader's words. */
const NOTE_TITLE: Record<string, string> = {
  'not-analyzed': 'Files were set aside on one side',
  truncated: 'One side was capped',
  projection: 'One side is a scoped view, not a whole analysis',
  'different-roots': 'The two analyses describe different workspace roots',
  'different-analyzers': 'The two documents were written by different analyzer versions',
  'different-schemas': 'The two documents claim different schema versions',
  'counts-disagree': 'The overlay states different totals from the ones it lists',
};

export class DiffBar {
  readonly root: HTMLElement;
  private cb: DiffBarCallbacks;

  constructor(cb: DiffBarCallbacks) {
    this.cb = cb;
    this.root = el('section', 'mlv-diffbar');
    this.root.setAttribute('aria-label', 'Comparison with an earlier analysis');
    this.root.hidden = true;
  }

  update(s: DiffBarState): void {
    clear(this.root);
    const diff = s.diff;
    if (!diff) {
      this.root.hidden = true;
      // The marker goes with the content: a hidden band that still answers
      // `[data-diff-bar]` would tell every consumer a comparison is loaded.
      this.root.removeAttribute('data-diff-bar');
      this.root.removeAttribute('data-diff-changed-only');
      return;
    }
    this.root.hidden = false;
    this.root.setAttribute('data-diff-bar', '1');
    this.root.setAttribute('data-diff-changed-only', s.changedOnly ? '1' : '0');

    const head = add(this.root, el('div', 'mlv-diffbar__head'));
    const icon = uiIcon('diff', 14);
    icon.setAttribute('class', 'mlv-uicon mlv-diffbar__icon');
    head.appendChild(icon);

    // `role="status"`: the headline is the one sentence a reviewer came for, and
    // it has to be announced when an overlay arrives after the graph.
    const line = add(head, el('span', 'mlv-diffbar__headline', diff.headline()));
    line.setAttribute('role', 'status');
    line.setAttribute('data-diff-headline', '1');

    head.appendChild(this.changedChip(s));
    const close = button('mlv-btn mlv-btn--icon mlv-diffbar__close', '', 'Stop comparing — draw this analysis on its own');
    close.appendChild(uiIcon('close', 12));
    on(close, 'click', () => this.cb.onDismiss());
    head.appendChild(close);

    this.root.appendChild(this.sides(diff, s.baseLabel));
    this.root.appendChild(this.counts(diff));
    if (s.changedOnly && !s.changedEmpty) this.root.appendChild(this.shownLine(s));
    if (s.changedEmpty) {
      const warn = add(this.root, el('div', 'mlv-diffbar__empty', 'Nothing that changed is in this document, so the diagram is unchanged.'));
      warn.setAttribute('role', 'status');
      warn.setAttribute('data-diff-empty', '1');
    }
    this.root.appendChild(this.notes(diff, s));
  }

  /** The chip that reuses the scope projection (ROADMAP VIEW-08). */
  private changedChip(s: DiffBarState): HTMLElement {
    const total =
      s.diff!.nodeCounts.added + s.diff!.nodeCounts.removed + s.diff!.nodeCounts.changed;
    const chip = el('button', 'mlv-chip mlv-chip--btn mlv-diffbar__only', 'Changed only') as HTMLButtonElement;
    chip.type = 'button';
    chip.setAttribute('aria-pressed', s.changedOnly ? 'true' : 'false');
    chip.setAttribute('data-changed-only', s.changedOnly ? 'on' : 'off');
    chip.title =
      'Show only the ' + total + ' node(s) this change touched, plus one hop of context. ' +
      'It is a scope, so the rail still says how many findings are outside it.';
    chip.disabled = total === 0;
    on(chip, 'click', () => this.cb.onChangedOnly(!s.changedOnly));
    return chip;
  }

  /** Which two documents these numbers are about — the easiest thing to get wrong. */
  private sides(diff: DiffIndex, baseLabel: string): HTMLElement {
    const box = el('div', 'mlv-diffbar__sides');
    box.setAttribute('data-diff-sides', '1');
    const base = diff.overlay.base;
    const head = diff.overlay.head;
    // The separators carry their own spacing, exactly as the scope breadcrumb's
    // do: a screen reader reads the row as one sentence, not as run-together
    // words ("head vision_pipeline2026-09-06").
    const baseEl = add(box, el('span', 'mlv-diffbar__side', 'base ' + (baseLabel || shortRoot(base.root))));
    baseEl.title = baseLabel ? baseLabel + ' — ' + (base.root || 'unknown') : base.root || 'unknown';
    add(box, el('span', 'mlv-diffbar__arrow', ' → '));
    const headEl = add(box, el('span', 'mlv-diffbar__side', 'head ' + shortRoot(head.root)));
    headEl.title = head.root || 'unknown';
    if (base.generatedAt || head.generatedAt) {
      add(box, el('span', 'mlv-diffbar__arrow', ' · '));
      const when = add(box, el('span', 'mlv-diffbar__when', stamps(base.generatedAt, head.generatedAt)));
      when.title = 'When each analysis was written';
    }
    return box;
  }

  private counts(diff: DiffIndex): HTMLElement {
    const box = el('div', 'mlv-diffbar__counts');
    box.setAttribute('role', 'list');
    const rows: [string, number, string][] = [
      ['added', diff.nodeCounts.added, 'Nodes only the newer analysis has'],
      ['removed', diff.nodeCounts.removed, 'Nodes only the older analysis had — drawn as ghost outlines'],
      ['changed', diff.nodeCounts.changed, 'Nodes both have, whose meaning moved'],
      ['unchanged', diff.nodeCounts.unchanged, 'Nodes both have, identical — a move is not a change'],
      ['new findings', diff.issueCounts.new, 'Findings only the newer analysis reports'],
      ['fixed', diff.issueCounts.fixed, 'Findings the older analysis reported and the newer one does not'],
      ['still present', diff.issueCounts.persisting, 'Findings both analyses report'],
    ];
    for (const [label, count, title] of rows) {
      const chip = add(box, el('span', 'mlv-chip mlv-diffbar__count', count + ' ' + label));
      chip.setAttribute('role', 'listitem');
      chip.setAttribute('data-diff-count', label);
      chip.title = title;
    }
    return box;
  }

  /** "Showing 7 of 14 nodes" while the projection is on. */
  private shownLine(s: DiffBarState): HTMLElement {
    const box = el('div', 'mlv-diffbar__shown');
    box.setAttribute('role', 'status');
    box.setAttribute('data-diff-shown', String(s.shown));
    add(box, el('span', '', 'Showing ' + s.shown + ' of ' + s.of + ' nodes — what changed, plus one hop.'));
    const all = button('mlv-link mlv-link--inline', 'Show all', 'Turn the changed-only view off. Filters and scopes are separate.');
    on(all, 'click', () => this.cb.onChangedOnly(false));
    box.appendChild(all);
    return box;
  }

  /**
   * §11.38 C, drawn in full — plus the viewer's own blind spots, which no
   * analyzer note can carry because they are properties of this renderer.
   */
  private notes(diff: DiffIndex, s: DiffBarState): HTMLElement {
    const box = el('div', 'mlv-diffbar__notes');
    box.setAttribute('data-diff-notes', String(diff.notes.length));
    add(box, el('h3', 'mlv-sr', 'What this comparison cannot tell you'));
    const list = add(box, el('ul', 'mlv-diffbar__notelist'));
    for (const note of diff.notes) {
      const li = add(list, el('li', 'mlv-diffbar__note'));
      li.setAttribute('data-note-kind', note.kind);
      const title = NOTE_TITLE[note.kind] || note.kind;
      add(li, el('span', 'mlv-diffbar__notekind', title + (note.side ? ' (' + note.side + ')' : '')));
      add(li, el('span', 'mlv-diffbar__notetext', ' ' + note.message));
    }
    if (!diff.notes.length) {
      const li = add(list, el('li', 'mlv-diffbar__note mlv-diffbar__note--clean'));
      li.setAttribute('data-note-kind', 'none');
      add(li, el('span', 'mlv-diffbar__notetext', 'Both analyses read their whole workspace, so a removed node is a removed node.'));
    }
    // The viewer's own caveats. They are UNCONDITIONAL because they are true of
    // every overlay this renderer draws, not of some of them.
    for (const text of viewerCaveats(diff, s)) {
      const li = add(list, el('li', 'mlv-diffbar__note mlv-diffbar__note--viewer'));
      li.setAttribute('data-note-kind', 'viewer');
      add(li, el('span', 'mlv-diffbar__notetext', text));
    }
    return box;
  }
}

/** The three things this RENDERER cannot show, whatever the overlay says. */
export function viewerCaveats(diff: DiffIndex, s: DiffBarState): string[] {
  const out: string[] = [];
  const removedEdges = diff.edgeCounts.removed;
  if (removedEdges > 0) {
    out.push(
      removedEdges + ' removed edge(s) are counted here and not drawn: a route needs both of its ' +
        'endpoints in one document, and a removed edge usually lost one.',
    );
  }
  if (s.ghostsDrawn > 0) {
    out.push(
      s.ghostsDrawn + ' removed node(s) are drawn as ghost outlines from the overlay alone, so they ' +
        'carry no findings, no ports and no nesting — those live in the base document, which this page does not have.',
    );
  }
  if (s.ghostsDrawn < diff.nodeCounts.removed) {
    out.push(
      diff.nodeCounts.removed - s.ghostsDrawn + ' removed node(s) are not on screen at all — a scope, a ' +
        'filter or --max-nodes took them out after the diff was computed.',
    );
  }
  // VIEW-R6, symmetrical to the removed-node line above: the chips count the
  // COMPARISON, the diagram draws the document, and a rolled-up card stands for
  // nodes the comparison named individually.
  const named = diff.nodeCounts.changed + diff.nodeCounts.unchanged;
  if (named > s.namedDrawn) {
    out.push(
      named - s.namedDrawn + ' node(s) this comparison names as changed or unchanged are not on screen ' +
        'individually — a rolled-up card, a scope or a filter absorbed them after the diff was computed.',
    );
  }
  out.push('A rename is every node removed plus every node added: the stable id embeds the file path, and no rename detection is attempted.');
  return out;
}

/** `/a/b/vision_pipeline` -> `vision_pipeline`, keeping the full path in the hover. */
function shortRoot(root: string): string {
  if (!root) return 'unknown';
  const parts = root.replace(/[\\/]+$/, '').split(/[\\/]/);
  return parts[parts.length - 1] || root;
}

function stamps(base: string, head: string): string {
  const b = base ? base.slice(0, 10) : '?';
  const h = head ? head.slice(0, 10) : '?';
  return b + ' → ' + h;
}
