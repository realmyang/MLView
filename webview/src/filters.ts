/**
 * The filter model: which findings and which lanes are currently in view.
 *
 * It owns the `Filters` half of the ViewState. Filtering never relayouts — the
 * predicates here only decide which markers are drawn and which cards are dimmed.
 */

import { normalizeSeverity } from './markers.js';
import { sanitizeFilters } from './protocol.js';
import type { Filters, Issue, MLNode, Severity } from './types.js';

export const ALL_SEVERITIES: Severity[] = ['low', 'medium', 'high'];

/** A fresh default Filters — never a shared array, so a merge cannot alias it. */
export function defaultFilters(): Filters {
  return { severities: ALL_SEVERITIES.slice(), stages: [], query: '' };
}

export class FilterModel {
  private current: Filters = defaultFilters();

  get value(): Filters {
    return this.current;
  }

  get query(): string {
    return this.current.query;
  }

  /**
   * Merge a partial update. An explicit `undefined` is IGNORED rather than
   * written through, so a caller that omits a field cannot blank `severities`
   * and make every later predicate throw.
   */
  patch(f: Partial<Filters>): void {
    const next: Filters = this.snapshot();
    if (f.severities !== undefined) next.severities = f.severities.slice();
    if (f.stages !== undefined) next.stages = f.stages.slice();
    if (f.query !== undefined) next.query = String(f.query);
    this.current = next;
  }

  reset(): void {
    this.current = defaultFilters();
  }

  /** Coerce whatever a host handed back into filters we can trust. */
  restore(raw: unknown): void {
    this.current = sanitizeFilters(raw, defaultFilters());
  }

  /** A defensive copy for ViewState. */
  snapshot(): Filters {
    return {
      severities: this.current.severities.slice(),
      stages: this.current.stages.slice(),
      query: this.current.query,
    };
  }

  /** True when this finding should be counted, listed and marked. */
  keep = (issue: Issue): boolean => {
    const f = this.current;
    if (f.severities.indexOf(normalizeSeverity(issue.severity)) < 0) return false;
    // CRIT-3: a workflow-level finding (no nodes, so no stage) belongs to
    // every phase; a phase filter must not hide it.
    if (f.stages.length && issue.stage !== '' && f.stages.indexOf(issue.stage) < 0) return false;
    return true;
  };

  /** True when the stage chips exclude this node — dimmed, never removed. */
  hidesNode(node: MLNode): boolean {
    const f = this.current;
    return f.stages.length > 0 && f.stages.indexOf(node.stage) < 0;
  }

  toggleSeverity(sev: Severity): void {
    const next = this.current.severities.slice();
    const at = next.indexOf(sev);
    if (at >= 0) next.splice(at, 1);
    else next.push(sev);
    this.patch({ severities: next });
  }

  /**
   * `laneIds` is every drawn lane; "everything on" is stored as the empty list.
   *
   * HOSTS-UX-STAGERESET: that encoding has one gesture it cannot express. Turn
   * the last remaining lane OFF and `next` is empty, which means "everything
   * on" — so the chips all flip back. The model keeps that behaviour (an empty
   * selection is the only sane resting state), and the RETURN VALUE is what
   * makes it explicable: true when the reader turned the last lane off and got
   * everything back, so the caller can say so instead of leaving it observed.
   */
  toggleStage(stageId: string, laneIds: string[]): boolean {
    let next = this.current.stages.slice();
    if (next.length === 0) next = laneIds.slice();
    const at = next.indexOf(stageId);
    if (at >= 0) next.splice(at, 1);
    else next.push(stageId);
    // Emptied by a removal, not by a lane list that was empty to begin with.
    const emptied = next.length === 0 && laneIds.length > 0;
    if (next.length === laneIds.length) next = [];
    this.patch({ stages: next });
    return emptied;
  }
}
