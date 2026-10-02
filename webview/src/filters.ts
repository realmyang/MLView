/**
 * The filter model: which findings are currently in view (the severity toggles and the query).
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
  return { severities: ALL_SEVERITIES.slice(), query: '' };
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
      query: this.current.query,
    };
  }

  /** True when this finding should be counted, listed and marked. */
  keep = (issue: Issue): boolean => this.current.severities.indexOf(normalizeSeverity(issue.severity)) >= 0;

  /**
   * True when the filters exclude this node — dimmed, never removed. Viewer M2 removed the phase
   * chips, the only filter that dimmed cards, so nothing does; the canvas still asks.
   */
  hidesNode(_node: MLNode): boolean {
    return false;
  }

  toggleSeverity(sev: Severity): void {
    const next = this.current.severities.slice();
    const at = next.indexOf(sev);
    if (at >= 0) next.splice(at, 1);
    else next.push(sev);
    this.patch({ severities: next });
  }
}
