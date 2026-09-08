/**
 * Binding layer between `keymap.ts` (what the keyboard means) and the app (what
 * it does). Keeping it beside the keymap makes the whole keyboard model two
 * short files that must be read together, rather than a table in one file and
 * fifty lines of closures buried in the application.
 */

import { SEVERITY_ORDER } from '../markers.js';
import type { KeyCommands } from './keymap.js';
import type { Issue, RailTab, Severity } from '../types.js';

/** The operations the keyboard is allowed to reach. Implemented by App. */
export interface CommandPort {
  focusSearch(): void;
  /** Escape's cascade, innermost first. Returns once something was dismissed. */
  dismissTopmost(): void;
  visibleIssues(): Issue[];
  selectedIssueId(): string | null;
  focusIssue(id: string): void;
  zoom(direction: number): void;
  fit(): void;
  toggleFocusMode(): void;
  zoomToSelection(): void;
  /** Collapse the selected group, or the selected node's parent group. */
  collapseSelection(): boolean;
  openSelection(): boolean;
  move(key: string): void;
  toggleSeverity(sev: Severity): void;
  toggleRail(): void;
  setRailTab(tab: RailTab): void;
  toggleShortcuts(): void;
  cycleConnections(backwards: boolean): boolean;
  scopeToSelection(): boolean;
  clearScope(): boolean;
  stepDepth(delta: number): boolean;
}

const RAIL_TABS: RailTab[] = ['issues', 'inspector', 'outline'];

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
    toggleCollapse: () => port.collapseSelection(),
    openSelection: () => port.openSelection(),
    move: (key) => port.move(key),
    toggleSeverity: (i) => {
      const sev = SEVERITY_ORDER[i] as Severity | undefined;
      if (sev) port.toggleSeverity(sev);
    },
    toggleRail: () => port.toggleRail(),
    selectRailTab: (i) => {
      if (RAIL_TABS[i]) port.setRailTab(RAIL_TABS[i]);
    },
    toggleShortcuts: () => port.toggleShortcuts(),
    cycleConnections: (backwards) => port.cycleConnections(backwards),
    scopeToSelection: () => port.scopeToSelection(),
    clearScope: () => port.clearScope(),
    stepDepth: (delta) => port.stepDepth(delta),
  };
}
