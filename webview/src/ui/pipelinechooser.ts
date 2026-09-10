/**
 * MLV-P12 — the chooser a multi-pipeline report opens on.
 *
 * 11.47 F ends with *"No chooser ships here. This section is the analyzer half
 * only… Opening the report on a chooser when a workspace has two or more
 * pipelines is renderer-owned."* This is that half.
 *
 * The problem it solves is measured: a research repo with ten training scripts
 * renders as one 320-node graph at 22 % zoom, and the first thing a reader has
 * to do is a thing the product never offered — say which experiment they came
 * for. So a document that reports two or more pipelines opens on a question
 * instead of on an unreadable picture.
 *
 * FOUR RULES.
 *
 * 1. **It is a question, never a filter.** Every row is a `pipeline:` scope the
 *    breadcrumb can show, copy and clear, and "Show everything" is a first-class
 *    answer sitting beside the pipelines rather than a dismissal hidden in a
 *    corner. Escape and the close button both mean "Show everything".
 * 2. **It is asked once.** The answer persists in `ViewState.pipelineChosen`
 *    (11.9's optional-field rule: absent means "not asked yet", so an older host
 *    round-trips a state it has never seen), and a reader who already restored a
 *    scope is never asked at all — they have already answered.
 * 3. **It states what it cannot tell you.** `sharedCount` is the only signal
 *    that the component detection over-approximated; unreached nodes belong to
 *    no pipeline and are counted but never named; `workspace.entrypoints` is a
 *    ten-entry heuristic. All three are on the panel, not in a tooltip.
 * 4. **It never re-analyses.** Picking a row is `setScope`, which is local
 *    (CONTRACTS 11.8): no `requestRefresh`, no analyzer, no round trip.
 * 5. **It has a floor** (VIEW-R5). `workspace.entrypoints` is a ranked
 *    heuristic, not a list of experiments: on the flagship 5-file demo it names
 *    `train.py`, `config.py` and `data.py`, so the product's own first screen
 *    was a modal offering a one-node constants module as a pipeline. A row is
 *    now OFFERED only if it holds a few nodes of its own or carries a finding,
 *    and the question is only asked when it is worth an interruption: three or
 *    more such rows, or two on a workspace too big to take in whole. Everything
 *    held back is still a `pipeline:` scope, still in the scope picker and still
 *    in `--list-scopes` — the floor decides what INTERRUPTS, never what exists.
 */

import { add, button, clear, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { severityGlyph } from '../markers.js';
import { pipelineName } from './scopepicker.js';
import { pipelineIndexOf } from '../scope/catalog.js';
import { pipelineDrift, rowSeverity } from '../scope/pipelines.js';
import type { PipelineRow } from '../scope/pipelines.js';
import type { MLGraph } from '../types.js';

/**
 * VIEW-R5 — how many nodes of its own a row must hold to be offered at all.
 *
 * Below this, and with no finding to its name, an "entrypoint" is a module the
 * ranking happened to reach: the demo's `config.py` is one node and no findings.
 */
export const CHOOSER_MIN_EXCLUSIVE = 3;

/**
 * VIEW-R5 — the workspace size at which TWO choices are worth a modal.
 *
 * Three or more pipelines is a menu nobody can hold in their head from the
 * picture, so it always asks. Two is a choice a reader can make from the diagram
 * itself — unless the diagram is one they cannot take in, which is the premise
 * MLV-P12 was written for ("a research repo with ten training scripts renders as
 * one 320-node graph at 22 % zoom"). 120 is a little over twice the flagship
 * demo, which VIEW-01 tunes the first paint to and which must never open
 * occluded.
 */
export const CHOOSER_MIN_NODES = 120;

/** The rows worth offering, in the analyzer's ranked order (VIEW-R5). */
export function chooserRows(rows: PipelineRow[]): PipelineRow[] {
  return rows.filter(
    (row) =>
      row.exclusiveCount >= CHOOSER_MIN_EXCLUSIVE ||
      row.issueCounts.high + row.issueCounts.medium + row.issueCounts.low > 0,
  );
}

/**
 * Is this workspace worth interrupting for? (VIEW-R5)
 *
 * Pure, so a host and a gate can both ask without a DOM.
 */
export function shouldAskPipeline(graph: MLGraph, rows: PipelineRow[]): boolean {
  const offered = chooserRows(rows);
  if (offered.length < 2) return false;
  if (offered.length >= 3) return true;
  return (graph.nodes || []).length >= CHOOSER_MIN_NODES;
}

export interface PipelineChooserCallbacks {
  /** `spec: null` means "Show everything". Both answers close the chooser. */
  onPick(spec: string | null): void;
}

let chooserSeq = 0;

export class PipelineChooser {
  readonly root: HTMLElement;
  private cb: PipelineChooserCallbacks;
  private panel: HTMLElement;
  private openFlag = false;
  private uid: string;

  constructor(cb: PipelineChooserCallbacks) {
    this.cb = cb;
    this.uid = 'mlv-pipes' + ++chooserSeq;
    this.root = el('div', 'mlv-pipechooser');
    this.root.hidden = true;
    this.panel = add(this.root, el('div', 'mlv-pipechooser__panel'));
    this.panel.setAttribute('role', 'dialog');
    this.panel.setAttribute('aria-modal', 'true');
    this.panel.setAttribute('aria-labelledby', this.uid + '-title');
    on(this.root, 'keydown', (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') {
        ev.preventDefault();
        ev.stopPropagation();
        // Escape is an ANSWER, not an abandonment: it means "show me
        // everything", and it is recorded so the question is not asked again.
        this.cb.onPick(null);
        return;
      }
      // `aria-modal="true"` is a PROMISE to a screen reader that nothing behind
      // this panel is reachable, and the diagram behind it is full of tab stops.
      // Tab therefore cycles inside the panel while it is open — without this,
      // the attribute would be a lie and a keyboard reader would tab into a
      // diagram they cannot see.
      if (ev.key === 'Tab') this.trapTab(ev);
    });
  }

  /** Wrap Tab and Shift+Tab around the panel's own focusable elements. */
  private trapTab(ev: KeyboardEvent): void {
    const stops = Array.from(
      this.panel.querySelectorAll('button:not([disabled]), [href], input, [tabindex]:not([tabindex="-1"])'),
    ) as HTMLElement[];
    if (!stops.length) return;
    const first = stops[0];
    const last = stops[stops.length - 1];
    const active = this.root.ownerDocument ? this.root.ownerDocument.activeElement : null;
    // Focus outside the panel at all (a host moved it, or nothing is focused)
    // lands on an end of the ring rather than escaping into the diagram.
    const inside = stops.indexOf(active as HTMLElement) >= 0;
    if (!inside) {
      ev.preventDefault();
      (ev.shiftKey ? last : first).focus();
      return;
    }
    if (ev.shiftKey && active === first) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && active === last) {
      ev.preventDefault();
      first.focus();
    }
  }

  get open(): boolean {
    return this.openFlag;
  }

  hide(): void {
    this.openFlag = false;
    this.root.hidden = true;
  }

  /** Draw and show. `rows` is the computed relation, never the emitted block. */
  show(graph: MLGraph, rows: PipelineRow[]): void {
    this.render(graph, rows);
    this.openFlag = true;
    this.root.hidden = false;
    try {
      const first = this.panel.querySelector('[data-pipeline]') as HTMLElement | null;
      if (first) first.focus();
    } catch (_e) {
      /* a host may not have attached the panel yet */
    }
  }

  private render(graph: MLGraph, found: PipelineRow[]): void {
    // The floor decides what is OFFERED; `found` is what the relation computed,
    // and the difference is stated in the notes rather than silently dropped.
    const rows = chooserRows(found);
    const heldBack = found.length - rows.length;
    clear(this.panel);
    const head = add(this.panel, el('div', 'mlv-pipechooser__head'));
    const title = add(head, el('h2', 'mlv-pipechooser__title', 'This workspace has ' + rows.length + ' pipelines'));
    title.id = this.uid + '-title';
    const close = iconButton('mlv-btn mlv-btn--icon', 'Close and show everything');
    close.appendChild(uiIcon('close', 12));
    on(close, 'click', () => this.cb.onPick(null));
    head.appendChild(close);

    add(
      this.panel,
      el(
        'p',
        'mlv-pipechooser__lede',
        // VIEW-R5: `workspace.entrypoints` is a ranked heuristic and promises no
        // such thing — two of the demo's three rows are not training scripts.
        'Each one is an entrypoint and everything its data and call edges reach. Pick the one you ' +
          'came for, or show the whole workspace — you can change this at any time from the scope picker.',
      ),
    );

    const list = add(this.panel, el('div', 'mlv-pipechooser__rows'));
    list.setAttribute('role', 'list');
    for (const row of rows) {
      // VIEW-R4. `role` on a <button> REPLACES the implicit button role, so the
      // rows used to reach a screen reader as inert list items — the modal's
      // only real actions, absent from the button rotor. The list semantics now
      // live on a wrapper and the button stays a button.
      const item = add(list, el('div', 'mlv-pipechooser__item'));
      item.setAttribute('role', 'listitem');
      item.appendChild(this.pipelineButton(row));
    }

    const all = button(
      'mlv-btn mlv-pipechooser__all',
      'Show everything (' + (graph.nodes || []).length + ' nodes)',
      'Draw the whole workspace, every pipeline at once',
    );
    on(all, 'click', () => this.cb.onPick(null));
    this.panel.appendChild(all);

    this.panel.appendChild(this.notes(graph, rows, heldBack));
  }

  private pipelineButton(row: PipelineRow): HTMLElement {
    const b = button('mlv-pipechooser__row', '', '') as HTMLButtonElement;
    clear(b);
    b.setAttribute('data-pipeline', row.entrypoint);
    const sev = rowSeverity(row);
    if (sev) b.setAttribute('data-sev', sev);
    add(b, el('span', 'mlv-pipechooser__name', pipelineName(row.entrypoint)));
    const meta = add(b, el('span', 'mlv-pipechooser__meta'));
    add(meta, el('span', 'mlv-pipechooser__count', row.nodeCount + (row.nodeCount === 1 ? ' node' : ' nodes')));
    if (row.sharedCount) {
      const shared = add(meta, el('span', 'mlv-pipechooser__shared', row.sharedCount + ' shared'));
      shared.title =
        row.sharedCount + ' of these nodes are reachable from another entrypoint too, so this view draws ' +
        'them as context rather than claiming them.';
    }
    const total = row.issueCounts.high + row.issueCounts.medium + row.issueCounts.low;
    if (total > 0 && sev) {
      const findings = add(meta, el('span', 'mlv-pipechooser__findings'));
      findings.appendChild(severityGlyph(sev, 12, sev + ' severity'));
      add(findings, el('span', '', total + (total === 1 ? ' finding' : ' findings')));
    }
    // VIEW-R4: the label is the row, read out — same words, same omissions. It
    // used to announce "1 nodes, 0 shared with another pipeline, 0 findings"
    // over a row that correctly showed "1 node" and no chips at all.
    b.setAttribute('aria-label', rowLabel(row));
    b.title = row.entrypoint;
    on(b, 'click', () => this.cb.onPick('pipeline:' + row.entrypoint));
    return b;
  }

  /** 11.47 F, on the panel rather than in a tooltip. */
  private notes(graph: MLGraph, rows: PipelineRow[], heldBack: number): HTMLElement {
    const box = el('div', 'mlv-pipechooser__notes');
    add(box, el('h3', 'mlv-sr', 'What this list cannot tell you'));
    const list = add(box, el('ul', 'mlv-pipechooser__notelist'));
    const caveats = chooserCaveats(graph, rows, heldBack);
    for (const text of caveats) add(list, el('li', '', text));
    box.setAttribute('data-pipechooser-notes', String(caveats.length));
    return box;
  }
}

/**
 * The four things this list is not — 11.47 F, worded for a reader.
 *
 * Each is conditional on the fact that makes it true, because a caveat that does
 * not apply teaches a reader to skip the block. The last one is unconditional: a
 * ten-entry heuristic is a ten-entry heuristic on every workspace.
 */
export function chooserCaveats(graph: MLGraph, rows: PipelineRow[], heldBack = 0): string[] {
  const out: string[] = [];
  if (heldBack > 0) {
    out.push(
      heldBack + ' more entrypoint(s) are not offered here: each reaches fewer than ' + CHOOSER_MIN_EXCLUSIVE +
        ' nodes of its own and carries no finding, which reads as a module rather than a pipeline. Every one ' +
        'of them is still in the scope picker and still resolves as `pipeline:<file>`.',
    );
  }
  if (indistinguishable(graph, rows)) {
    out.push(
      'Every row below shows the SAME counts: the cap summarised this workspace into shared cards, so the ' +
        'file name is the only thing that tells these pipelines apart here.',
    );
  }
  const shared = rows.filter((r) => r.sharedCount > 0).length;
  if (shared) {
    out.push(
      'These are not a partition: ' + shared + ' of them share nodes with another pipeline, and a shared ' +
        'node is drawn as context in both rather than claimed by either. A finding anchored only on a ' +
        'shared node is outside every pipeline view, and the rail says so.',
    );
  }
  const unreached = pipelineIndexOf(graph).unreached.length;
  if (unreached > 0) {
    out.push(
      unreached + ' node(s) belong to no pipeline at all — nothing counts them into a row here, and there ' +
        'is no selector for them. Only "Show everything" draws them.',
    );
  }
  out.push(
    'Only data and call edges join a pipeline. A script that depends on a shared config module is not ' +
      'shown as owning it — the view is about data and calls.',
  );
  out.push(
    'The entrypoint list is a ranked heuristic capped at ten, so a repo with fifteen training scripts ' +
      'gets ten pipelines and no statement that five are missing.',
  );
  if (graph.stats && graph.stats.truncated) {
    out.push(
      'This document was capped, so these counts describe the summarised graph: a rolled-up card counts ' +
        'once however many nodes it stands for.',
    );
  }
  const drift = pipelineDrift(graph, rows);
  if (drift) out.push(drift);
  return out;
}

/**
 * The row, read out: the same numbers the row shows, with the same omissions.
 *
 * VIEW-R4. `1 node` is not `1 nodes`, and a row that draws no shared chip and no
 * finding chip must not announce two zeroes.
 */
export function rowLabel(row: PipelineRow): string {
  const total = row.issueCounts.high + row.issueCounts.medium + row.issueCounts.low;
  let out = row.entrypoint + ', ' + row.nodeCount + (row.nodeCount === 1 ? ' node' : ' nodes');
  if (row.sharedCount) out += ', ' + row.sharedCount + ' shared with another pipeline';
  if (total) out += ', ' + total + (total === 1 ? ' finding' : ' findings');
  return out + '.';
}

/**
 * A capped document can summarise every pipeline into the same shared cards, and
 * then the counts stop distinguishing the rows (VIEW-R5). Only worth saying when
 * the document really was truncated: identical counts on a whole document are a
 * fact about the workspace, not about the cap.
 */
function indistinguishable(graph: MLGraph, rows: PipelineRow[]): boolean {
  if (rows.length < 2) return false;
  if (!(graph.stats && graph.stats.truncated)) return false;
  const key = (row: PipelineRow): string =>
    row.nodeCount + '/' + row.sharedCount + '/' + row.issueCounts.high + '/' + row.issueCounts.medium + '/' +
    row.issueCounts.low;
  const first = key(rows[0]);
  return rows.every((row) => key(row) === first);
}
