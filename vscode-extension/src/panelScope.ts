/**
 * The pure functions behind the panel's scope chrome (CONTRACTS.md §11.7, §11.11).
 *
 * They live outside panel.ts so the panel class stays inside the repo's ~600-line file budget,
 * and so `test/scope.test.js` can assert them with no `vscode` object at all.
 */

import type { ViewState } from './protocol';

/** The panel title while a scope is set. */
export const PANEL_TITLE = 'MLView';

/** The panel chrome a `scopeChanged` message produces (CONTRACTS.md §11.11). */
export interface ScopeChrome {
  title: string;
  description: string;
}

/**
 * `MLView - <label>` while a scope is set, the plain panel title once it is cleared, and the
 * "<drawn> of <analyzed> nodes" description that stops a projection from ever reading as the
 * whole project. Pure, so `test/scope.test.js` can assert it directly.
 */
export function scopeChrome(msg: {
  spec: string | null;
  label: string;
  nodes: number;
  of: number;
}): ScopeChrome {
  const label = msg.label || msg.spec || '';
  return {
    title: msg.spec && label ? `${PANEL_TITLE} — ${label}` : PANEL_TITLE,
    description: `${msg.nodes} of ${msg.of} nodes`
  };
}

/**
 * The selector the viewer says it is drawing, as the export path needs it (§11.6 `--scope`).
 * `depth` is best-effort: `scopeChanged` (§11.7) carries no depth, so it is recovered from the
 * viewer's own saved `ViewState.scope` (§11.9) and only when that state describes the SAME
 * selector; otherwise it is left out and the CLI applies the per-kind default, which is exactly
 * what the viewer applies when no depth was ever chosen.
 */
export interface ActiveScope {
  spec: string;
  depth?: number;
}

/** Pure, so `test/scope.test.js` can assert the recovery rule without a panel. */
export function activeScopeFrom(
  spec: string | null,
  state: ViewState | undefined
): ActiveScope | undefined {
  if (!spec) {
    return undefined;
  }
  const saved = (state as { scope?: { spec?: unknown; depth?: unknown } } | undefined)?.scope;
  const depth = saved && saved.spec === spec ? saved.depth : undefined;
  return typeof depth === 'number' && Number.isInteger(depth) && depth >= 0 && depth <= 2
    ? { spec, depth }
    : { spec };
}
