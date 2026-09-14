/**
 * The scope picker: the one place that answers "which part of this codebase?".
 *
 * It lists, in this order: Everything · the four Concerns with LIVE counts · the
 * stages the document declares · every scopable unit, searchable and labelled
 * `baseline() · sklearn_baseline.py:18 · 13 nodes`. A concern that matches
 * nothing renders disabled as "not detected in this project" — itself a finding,
 * exactly as an absent stage already is elsewhere in the product.
 *
 * Depth lives here too (0 / 1 / 2), because "how much of the neighbourhood" is
 * part of choosing a scope rather than a separate idea.
 */

import { add, button, clear, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { concernRows, pipelineRows, scopeCatalog, stageRows } from '../scope/catalog.js';
import type { ScopeGroup, ScopeUnit } from '../scope/catalog.js';
import { drawnCount, rowSeverity } from '../scope/pipelines.js';
import type { PipelineRow } from '../scope/pipelines.js';
import type { MLGraph } from '../types.js';

export interface ScopePickerCallbacks {
  /** `spec: null` means Everything. `depth` undefined keeps the kind's default. */
  onPick(spec: string | null, depth?: number): void;
  onClose(): void;
}

export interface ScopePickerState {
  graph: MLGraph | null;
  spec: string | null;
  depth: number;
}

let pickerSeq = 0;

export class ScopePicker {
  readonly root: HTMLElement;
  private cb: ScopePickerCallbacks;
  private body: HTMLElement;
  private searchInput: HTMLInputElement;
  private state: ScopePickerState = { graph: null, spec: null, depth: 0 };
  private query = '';
  private openFlag = false;

  constructor(cb: ScopePickerCallbacks) {
    this.cb = cb;
    const uid = 'mlv-scope' + ++pickerSeq;
    this.root = el('div', 'mlv-scopepicker');
    this.root.hidden = true;
    this.root.setAttribute('role', 'dialog');
    this.root.setAttribute('aria-modal', 'false');
    this.root.setAttribute('aria-label', 'Scope the diagram');

    const head = add(this.root, el('div', 'mlv-scopepicker__head'));
    add(head, el('h2', 'mlv-scopepicker__title', 'Scope diagram to a part of this codebase'));
    const close = iconButton('mlv-btn mlv-btn--icon', 'Close the scope picker');
    close.appendChild(uiIcon('close', 12));
    on(close, 'click', () => this.cb.onClose());
    head.appendChild(close);

    const search = add(this.root, el('div', 'mlv-scopepicker__search'));
    const label = add(search, el('label', 'mlv-sr', 'Search units'));
    label.htmlFor = uid + '-q';
    this.searchInput = add(search, el('input', 'mlv-input')) as HTMLInputElement;
    this.searchInput.id = uid + '-q';
    this.searchInput.type = 'search';
    this.searchInput.placeholder = 'Search classes, functions, files…';
    this.searchInput.autocomplete = 'off';
    on(this.searchInput, 'input', () => {
      this.query = this.searchInput.value;
      this.render();
    });

    this.body = add(this.root, el('div', 'mlv-scopepicker__body'));

    on(this.root, 'keydown', (ev: KeyboardEvent) => {
      if (ev.key !== 'Escape') return;
      ev.preventDefault();
      ev.stopPropagation();
      this.cb.onClose();
    });
  }

  get open(): boolean {
    return this.openFlag;
  }

  show(state: ScopePickerState): void {
    this.state = state;
    this.openFlag = true;
    this.root.hidden = false;
    this.render();
    try {
      this.searchInput.focus();
    } catch (_e) {
      /* a host may not have attached the panel yet */
    }
  }

  hide(): void {
    this.openFlag = false;
    this.root.hidden = true;
  }

  update(state: ScopePickerState): void {
    this.state = state;
    if (this.openFlag) this.render();
  }

  private render(): void {
    clear(this.body);
    const graph = this.state.graph;
    if (!graph) {
      add(this.body, el('div', 'mlv-empty-note', 'No analysis loaded yet.'));
      return;
    }

    const everything = this.row('Everything', graph.nodes.length + ' nodes', null, this.state.spec === null);
    this.body.appendChild(everything);

    // MLV-P12. Pipelines come FIRST, above the concerns: on a repo with ten
    // training scripts "which experiment?" is the question you have before
    // "which concern?", and the chooser that opens on such a report offers
    // exactly these rows — one list, in one order, in both places.
    const pipelines = pipelineRows(graph);
    if (pipelines.length) {
      this.body.appendChild(this.heading('Pipelines'));
      for (const row of pipelines) this.body.appendChild(this.pipelineRow(row));
    }

    this.body.appendChild(this.heading('Concerns'));
    for (const row of concernRows(graph)) this.body.appendChild(this.groupRow(row));

    this.body.appendChild(this.heading('Depth'));
    const depths = add(this.body, el('div', 'mlv-scopepicker__depths'));
    depths.setAttribute('role', 'group');
    depths.setAttribute('aria-label', 'Boundary hops');
    for (const depth of [0, 1, 2]) {
      const b = el('button', 'mlv-chip mlv-chip--btn') as HTMLButtonElement;
      b.type = 'button';
      b.textContent = depth === 0 ? 'exact' : depth + (depth === 1 ? ' hop' : ' hops');
      b.setAttribute('aria-pressed', this.state.depth === depth ? 'true' : 'false');
      b.title = depth === 0 ? 'Only the scope itself' : 'Include nodes ' + depth + ' connection(s) away';
      // Depth alone is meaningless without a scope: keep the current one.
      on(b, 'click', () => this.cb.onPick(this.state.spec, depth));
      b.disabled = this.state.spec === null;
      depths.appendChild(b);
    }

    const stages = stageRows(graph).filter((s) => s.present);
    if (stages.length) {
      this.body.appendChild(this.heading('Stages'));
      for (const row of stages) this.body.appendChild(this.groupRow(row));
    }

    const units = this.filtered(scopeCatalog(graph, 200));
    this.body.appendChild(this.heading('Units'));
    if (!units.length) {
      add(this.body, el('div', 'mlv-empty-note', 'No unit matches “' + this.query + '”.'));
      return;
    }
    let currentFile = '';
    for (const unit of units) {
      if (unit.file !== currentFile) {
        currentFile = unit.file;
        add(this.body, el('div', 'mlv-scopepicker__file', currentFile));
      }
      this.body.appendChild(this.unitRow(unit));
    }
  }

  private filtered(units: ScopeUnit[]): ScopeUnit[] {
    const q = this.query.trim().toLowerCase();
    if (!q) return units;
    return units.filter(
      (u) =>
        u.label.toLowerCase().indexOf(q) >= 0 ||
        u.qualname.toLowerCase().indexOf(q) >= 0 ||
        u.file.toLowerCase().indexOf(q) >= 0,
    );
  }

  private heading(text: string): HTMLElement {
    const h = el('h3', 'mlv-scopepicker__heading');
    h.textContent = text;
    return h;
  }

  private groupRow(row: ScopeGroup): HTMLElement {
    const detail = row.present ? row.nodes + (row.nodes === 1 ? ' node' : ' nodes') : 'not detected in this project';
    const el_ = this.row(row.label, detail, row.spec, this.state.spec === row.spec);
    if (!row.present) {
      el_.setAttribute('aria-disabled', 'true');
      (el_ as HTMLButtonElement).disabled = true;
    }
    return el_;
  }

  /**
   * MLV-P12. `train.py · 34 nodes · 6 shared` — the shared count is on the row
   * because it is the ONE number that says the component detection
   * over-approximated (11.47 F), and a menu that hid it would let a reader take
   * "the exp03 pipeline" as a partition when it is not one.
   */
  private pipelineRow(row: PipelineRow): HTMLElement {
    const spec = 'pipeline:' + row.entrypoint;
    const shared = row.sharedCount ? ' · ' + row.sharedCount + ' shared' : '';
    // HOSTS-UX-PIPELINECOUNT: the number the CLICK delivers, not the relation's.
    const drawn = drawnCount(row);
    const detail = drawn + (drawn === 1 ? ' node' : ' nodes') + shared;
    const el_ = this.row(pipelineName(row.entrypoint), detail, spec, this.state.spec === spec);
    el_.setAttribute('data-pipeline', row.entrypoint);
    el_.setAttribute('data-pipeline-nodes', String(drawn));
    const sev = rowSeverity(row);
    if (sev) el_.setAttribute('data-sev', sev);
    // The projection keeps a `context` ancestor so `parent` still forms a
    // forest (11.3), and that ancestor need not be inside the reach — so the
    // row's number can exceed the relation's, and the tooltip says which is
    // which rather than leaving a reader with an unexplained extra card.
    const kept = drawn - row.nodeCount;
    el_.title =
      row.entrypoint + ' — ' + detail +
      (row.sharedCount
        ? '. The shared nodes are reachable from another entrypoint too, so they are drawn as context rather than claimed by this pipeline.'
        : '. Nothing here is shared with another entrypoint.') +
      (kept > 0
        ? ' ' + kept + ' of them is an enclosing scope kept so the containment tree stays whole; this pipeline reaches ' +
          row.nodeCount + '.'
        : '');
    return el_;
  }

  private unitRow(unit: ScopeUnit): HTMLElement {
    const detail = unit.file + ':' + unit.line + ' · ' + unit.nodeCount + (unit.nodeCount === 1 ? ' node' : ' nodes');
    const row = this.row(unit.label, detail, unit.spec, this.state.spec === unit.spec);
    if (unit.maxSeverity) row.setAttribute('data-sev', unit.maxSeverity);
    return row;
  }

  private row(label: string, detail: string, spec: string | null, active: boolean): HTMLElement {
    const b = button('mlv-scopepicker__row', label, label + ' — ' + detail) as HTMLButtonElement;
    clear(b);
    add(b, el('span', 'mlv-scopepicker__rowlabel', label));
    add(b, el('span', 'mlv-scopepicker__rowdetail', detail));
    b.setAttribute('aria-pressed', active ? 'true' : 'false');
    if (spec) b.setAttribute('data-scope-spec', spec);
    else b.setAttribute('data-scope-spec', 'all');
    on(b, 'click', () => this.cb.onPick(spec));
    return b;
  }
}

/**
 * `experiments/exp03/train.py` -> `exp03/train.py`.
 *
 * A row is ~360 px wide and ten sibling experiments differ in the LAST two
 * segments, so a head-truncated path is the one that still distinguishes them.
 * The full path stays in the row's `title` and in `data-pipeline`.
 */
export function pipelineName(entrypoint: string): string {
  const parts = entrypoint.split('/');
  if (parts.length <= 2) return entrypoint;
  return '…/' + parts.slice(-2).join('/');
}
