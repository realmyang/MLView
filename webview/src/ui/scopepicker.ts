/**
 * The scope picker: the one place that answers "which part of this codebase?".
 *
 * It lists, in this order: Everything · the phases that have steps · every
 * scopable unit, searchable and labelled `Train the model · train.py:18 · 13 nodes`.
 *
 * Depth lives here too (0 / 1 / 2), because "how much of the neighbourhood" is
 * part of choosing a scope rather than a separate idea.
 */

import { add, button, clear, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { scopeCatalog, stageRows, viewCountOf } from '../scope/catalog.js';
import type { ScopeGroup, ScopeUnit } from '../scope/catalog.js';
import { locLabel, locTitle } from '../notebook.js';
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
    const label = add(search, el('label', 'mlv-sr', 'Search steps, phases, files'));
    label.htmlFor = uid + '-q';
    this.searchInput = add(search, el('input', 'mlv-input')) as HTMLInputElement;
    this.searchInput.id = uid + '-q';
    this.searchInput.type = 'search';
    this.searchInput.placeholder = 'Search steps, phases, files…';
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
      add(this.body, el('div', 'mlv-empty-note', 'No workflow loaded yet.'));
      return;
    }

    const everything = this.row('Everything', graph.nodes.length + ' nodes', null, this.state.spec === null);
    this.body.appendChild(everything);

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

    // The search box offers steps, phases and files, so it filters the stage
    // rows too (by label or id), and units also match by node id (VIEWUI-6).
    const stages = this.filteredStages(stageRows(graph).filter((s) => s.present));
    if (stages.length) {
      this.body.appendChild(this.heading('Stages'));
      for (const row of stages) this.body.appendChild(this.groupRow(row));
    }

    const units = this.filtered(scopeCatalog(graph, 200));
    if (!units.length && stages.length && this.query.trim()) return;
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
        u.nodeId.toLowerCase().indexOf(q) >= 0 ||
        u.file.toLowerCase().indexOf(q) >= 0,
    );
  }

  private filteredStages(stages: ScopeGroup[]): ScopeGroup[] {
    const q = this.query.trim().toLowerCase();
    if (!q) return stages;
    return stages.filter((s) => s.label.toLowerCase().indexOf(q) >= 0 || s.spec.replace(/^stage:/, '').toLowerCase().indexOf(q) >= 0);
  }

  private heading(text: string): HTMLElement {
    const h = el('h3', 'mlv-scopepicker__heading');
    h.textContent = text;
    return h;
  }

  /**
   * HOSTS-UX-ROWCOUNT: the number the CLICK delivers, not the relation's.
   *
   * A unit row's match set under-counts by the kind's default depth, and a
   * stage row's by the `context` ancestors the projection keeps, so each row
   * asks the projection itself.
   */
  private drawn(spec: string, relation: number): number {
    const graph = this.state.graph;
    if (!graph) return relation;
    const count = viewCountOf(graph, spec);
    return count === null ? relation : count;
  }

  /** A phase row. Only phases with steps are listed (`render`). */
  private groupRow(row: ScopeGroup): HTMLElement {
    const drawn = this.drawn(row.spec, row.nodes);
    return this.row(row.label, drawn + (drawn === 1 ? ' node' : ' nodes'), row.spec, this.state.spec === row.spec);
  }

  private unitRow(unit: ScopeUnit): HTMLElement {
    const drawn = this.drawn(unit.spec, unit.nodeCount);
    // A step with no evidence has no location; never print a fake `:1`. The
    // shared label names an authored notebook cell, like the card (VIEWUI-8).
    const where = unit.file ? locLabel(unit.loc) + ' · ' : '';
    const detail = where + drawn + (drawn === 1 ? ' node' : ' nodes');
    const row = this.row(unit.label, detail, unit.spec, this.state.spec === unit.spec);
    const title = unit.file ? locTitle(unit.loc) : '';
    if (title) row.title = unit.label + ' — ' + detail + ' (' + title + ')';
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
