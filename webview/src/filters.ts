/**
 * The filter model: which findings and which lanes are currently in scope.
 *
 * It owns the `Filters` half of the ViewState plus the rule-code restriction a
 * host can push with `setFilter`. Filtering never relayouts — the predicates
 * here only decide which markers are drawn and which cards are dimmed.
 */

import { normalizeSeverity } from './markers.js';
import { sanitizeFilters } from './protocol.js';
import { isSetAside } from './types.js';
import type { Filters, Issue, MLNode, Severity } from './types.js';

export const ALL_SEVERITIES: Severity[] = ['low', 'medium', 'high'];

/** A fresh default Filters — never a shared array, so a merge cannot alias it. */
export function defaultFilters(): Filters {
  return { severities: ALL_SEVERITIES.slice(), stages: [], showSuppressed: false, query: '' };
}

export class FilterModel {
  private current: Filters = defaultFilters();
  private codes: string[] = [];

  get value(): Filters {
    return this.current;
  }

  get query(): string {
    return this.current.query;
  }

  /**
   * Merge a partial update. An explicit `undefined` is IGNORED rather than
   * written through — `setFilter` legitimately omits fields, and a spread would
   * otherwise blank `severities` and make every later predicate throw.
   */
  patch(f: Partial<Filters>): void {
    const next: Filters = this.snapshot();
    if (f.severities !== undefined) next.severities = f.severities.slice();
    if (f.stages !== undefined) next.stages = f.stages.slice();
    if (f.showSuppressed !== undefined) next.showSuppressed = !!f.showSuppressed;
    if (f.query !== undefined) next.query = String(f.query);
    if (f.changedOnly !== undefined) {
      if (f.changedOnly) next.changedOnly = true;
      else delete next.changedOnly;
    }
    this.current = next;
  }

  reset(): void {
    this.current = defaultFilters();
    this.codes = [];
  }

  setCodes(codes: string[]): void {
    this.codes = codes.slice();
  }

  /** Coerce whatever a host handed back into filters we can trust. */
  restore(raw: unknown): void {
    this.current = sanitizeFilters(raw, defaultFilters());
  }

  /** A defensive copy for ViewState. */
  snapshot(): Filters {
    const out: Filters = {
      severities: this.current.severities.slice(),
      stages: this.current.stages.slice(),
      showSuppressed: this.current.showSuppressed,
      query: this.current.query,
    };
    // Absent at its default, like `ViewState.flow` (CI-ADOPT).
    if (this.current.changedOnly) out.changedOnly = true;
    return out;
  }

  /**
   * True when this finding should be counted, listed and marked.
   *
   * A BASELINED finding is set aside exactly as a suppressed one is (CI-ADOPT:
   * "a baselined issue is marked, not deleted, so the existing show-suppressed
   * affordance carries it") — the rail still lists it, in the collapsed
   * "N suppressed" section, with its own chip.
   */
  keep = (issue: Issue): boolean => {
    const f = this.current;
    if (!f.showSuppressed && isSetAside(issue)) return false;
    return this.keepBase(issue);
  };

  /**
   * Everything `keep` tests EXCEPT suppression and baselining.
   *
   * The rail's collapsed suppressed section lists the findings the first rule
   * removed, and it must still honour the severity chips, the stage chips and a
   * host's `setFilter` codes -- otherwise a filtered-away finding reappears in
   * the section that is supposed to be an audit trail of suppressions.
   */
  keepBase = (issue: Issue): boolean => {
    const f = this.current;
    if (f.severities.indexOf(normalizeSeverity(issue.severity)) < 0) return false;
    if (this.codes.length && this.codes.indexOf(issue.code) < 0) return false;
    // CRIT-3: a workflow-level finding (no nodes, so no stage) belongs to
    // every phase; a phase filter must not hide it.
    if (f.stages.length && issue.stage !== '' && f.stages.indexOf(issue.stage) < 0) return false;
    // CI-ADOPT: only an EXPLICIT `existing` is dropped. An unattributed run has
    // no `change` at all and must show everything rather than nothing.
    if (f.changedOnly && issue.change === 'existing') return false;
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
   * on" — so the chips all flip back, 45 dimmed cards undim, and the rail goes
   * from 0 findings back to 15. The model keeps that behaviour (an empty
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
