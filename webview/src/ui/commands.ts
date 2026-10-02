/**
 * Binding layer between `keymap.ts` (what the keyboard means) and the app (what
 * it does). Keeping it beside the keymap makes the whole keyboard model two
 * short files that must be read together, rather than a table in one file and
 * fifty lines of closures buried in the application.
 */

import { SEVERITY_ORDER } from '../markers.js';
import type { KeyCommands } from './keymap.js';
import type { Issue, RailTab, Sel, Severity } from '../types.js';

/** The operations the keyboard is allowed to reach. Implemented by App. */
export interface CommandPort {
  focusSearch(): void;
  /** Escape's cascade, innermost first. Returns once something was dismissed; false when nothing was. */
  dismissTopmost(): boolean;
  visibleIssues(): Issue[];
  selectedIssueId(): string | null;
  focusIssue(id: string): void;
  zoom(direction: number): void;
  fit(): void;
  toggleFocusMode(): void;
  zoomToSelection(): void;
  /** Collapse every group and fit (VIEW-10). */
  overview(): void;
  toggleLegend(): void;
  toggleFlow(): void;
  /** Viewer M2: play the settled flow again (Shift+A). */
  replayFlow(): boolean;
  /** Collapse the selected group, or the selected node's parent group. */
  collapseSelection(): boolean;
  /** Open the selection's cited source; `focusEditor` (Alt+Enter) moves focus to the editor. */
  openSelection(focusEditor: boolean): boolean;
  move(key: string): void;
  toggleSeverity(sev: Severity): void;
  toggleRail(): void;
  /** Viewer M2 live fix: `t`, the panel's current tab gets the focus (the panel opens first). */
  focusRailTabs(): void;
  toggleShortcuts(): void;
  cycleConnections(backwards: boolean): boolean;
}

/** Every rail tab, in strip order: About, Findings, Selection, Outline (viewer M2). */
export const RAIL_TABS: readonly RailTab[] = ['about', 'issues', 'inspector', 'outline'];

/**
 * Viewer M2 live fix: a saved selection, or null when it is not a step, connection or finding with
 * a string id (a hand-edited or future state). `setGraph` then drops an id the document lacks.
 */
export function sanitizeSelection(value: unknown): Sel | null {
  if (!value || typeof value !== 'object') return null;
  const { kind, id } = value as { kind?: unknown; id?: unknown };
  if ((kind !== 'node' && kind !== 'edge' && kind !== 'issue') || typeof id !== 'string' || !id) return null;
  return { kind, id };
}

/** A saved or posted tab, or null when it is not one of ours. */
export function sanitizeRailTab(value: unknown): RailTab | null {
  return typeof value === 'string' && (RAIL_TABS as readonly string[]).indexOf(value) >= 0 ? (value as RailTab) : null;
}

export function canvasCommands(port: CommandPort): KeyCommands {
  return {
    focusSearch: () => port.focusSearch(),
    escape: () => port.dismissTopmost(),
    cycleIssue: (backwards) => {
      const issues = port.visibleIssues();
      if (!issues.length) return false;
      const current = port.selectedIssueId();
      const at = current ? issues.findIndex((x) => x.id === current) : -1;
      const next = (at + (backwards ? -1 : 1) + issues.length) % issues.length;
      port.focusIssue(issues[next].id);
      return true;
    },
    zoom: (direction) => port.zoom(direction),
    fit: () => port.fit(),
    toggleFocusMode: () => port.toggleFocusMode(),
    zoomToSelection: () => port.zoomToSelection(),
    overview: () => port.overview(),
    toggleLegend: () => port.toggleLegend(),
    toggleFlow: () => port.toggleFlow(),
    replayFlow: () => port.replayFlow(),
    toggleCollapse: () => port.collapseSelection(),
    openSelection: (focusEditor) => port.openSelection(focusEditor),
    move: (key) => port.move(key),
    toggleSeverity: (i) => {
      const sev = SEVERITY_ORDER[i] as Severity | undefined;
      if (sev) port.toggleSeverity(sev);
    },
    toggleRail: () => port.toggleRail(),
    focusRailTabs: () => port.focusRailTabs(),
    toggleShortcuts: () => port.toggleShortcuts(),
    cycleConnections: (backwards) => port.cycleConnections(backwards),
  };
}
