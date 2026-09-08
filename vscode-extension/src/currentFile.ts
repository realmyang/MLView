/**
 * What `MLView: Visualize (Current File)` actually analyzes (ROADMAP COVERAGE, host half).
 *
 * The measured defect: `mlview issues <dir>/train.py` reports 3 findings where
 * `mlview issues <dir> --scope file:train.py` reports 7 — a 57% loss, and until the analyzer
 * started emitting `single_file_analysis` it was completely silent. MLV301 / MLV302 / MLV401 /
 * MLV501 all need a sibling module, so a single-file run cannot fire them at all.
 *
 * The fix is not to analyze less honestly but to analyze more: `mlview.currentFileAnalysisScope`
 * defaults to `package`, so the command analyzes the directory the file's package lives in and
 * then narrows the DIAGRAM to the file through the existing §11.7 `setScope` path. The user sees
 * the same one-file picture and gets the cross-file findings.
 *
 * Everything here is pure — the filesystem arrives as an `exists` predicate — so
 * `test/currentFile.test.js` can assert the whole resolution table with no `vscode` and no disk.
 */

import { toWorkspaceRelative } from './location';

/** The values of `mlview.currentFileAnalysisScope`. */
export const CURRENT_FILE_SCOPES = ['file', 'package', 'workspace'] as const;
export type CurrentFileAnalysisScope = (typeof CURRENT_FILE_SCOPES)[number];

/** The `file:` selector kind of the §11.1 grammar, as the current-file command produces it. */
export const SCOPE_KIND_FILE = 'file';

export interface CurrentFileTarget {
  /** The ANALYSIS scope (§4 `analysisStarted`), not the §11.1 diagram selector. */
  scope: 'workspace' | 'file';
  /** Absolute path handed to the analyzer. Undefined for a workspace run. */
  path?: string;
  /**
   * The file the DIAGRAM is scoped to once the graph arrives, when that is not simply the
   * whole analyzed target. Undefined when the analyzed path IS the file, because narrowing a
   * one-file graph to that same file would post a scope that changes nothing.
   */
  focusFile?: string;
}

function normalize(p: string): string {
  return p.replace(/\\/g, '/').replace(/\/+$/, '');
}

function dirname(p: string): string {
  const norm = normalize(p);
  const cut = norm.lastIndexOf('/');
  return cut <= 0 ? norm.slice(0, cut + 1) || norm : norm.slice(0, cut);
}

/** True when `child` is `parent` or sits underneath it. Comparison is case-sensitive. */
function within(parent: string, child: string): boolean {
  const p = normalize(parent);
  const c = normalize(child);
  return c === p || c.startsWith(p + '/');
}

/**
 * The directory to analyze for `filePath` under `package` scope.
 *
 * A directory is a package when it holds an `__init__.py`. Starting at the file's own directory
 * the walk climbs while EVERY step is a package, so `src/data/loader.py` in a package chain
 * resolves to `src/` — the unit the cross-file rules actually reason over — and stops at the
 * first non-package. A file that is in no package at all resolves to its own directory, which is
 * the `samples/vision_pipeline/train.py` case in the COVERAGE acceptance criterion.
 *
 * The walk never leaves `workspaceRoot`: a `__init__.py` at the root of a repo must not turn a
 * current-file command into a whole-workspace analysis by accident.
 */
export function packageRootFor(
  filePath: string,
  workspaceRoot: string,
  exists: (path: string) => boolean
): string {
  const start = dirname(filePath);
  if (!within(workspaceRoot, start)) {
    return start;
  }
  let current = start;
  while (exists(current + '/__init__.py')) {
    const parent = dirname(current);
    // Stopping BELOW the root is the point: a repo whose own root carries an `__init__.py`
    // must not turn a current-file command into a whole-workspace analysis by accident.
    if (parent === current || parent === normalize(workspaceRoot) || !within(workspaceRoot, parent)) {
      break;
    }
    if (!exists(parent + '/__init__.py')) {
      break;
    }
    current = parent;
  }
  return current;
}

/**
 * Resolve the current-file command to "what to analyze" plus "what to scope the diagram to".
 *
 * `file` keeps the historical behaviour (and is now reported as incomplete by the analyzer's
 * `single_file_analysis` diagnostic); `package` analyzes `packageRootFor(...)`; `workspace`
 * analyzes the whole folder. The last two both carry `focusFile`.
 */
export function resolveCurrentFileTarget(
  filePath: string,
  workspaceRoot: string,
  mode: CurrentFileAnalysisScope,
  exists: (path: string) => boolean
): CurrentFileTarget {
  if (mode === 'workspace') {
    return { scope: 'workspace', focusFile: filePath };
  }
  if (mode === 'file') {
    return { scope: 'file', path: filePath };
  }
  const root = packageRootFor(filePath, workspaceRoot, exists);
  // The package resolved to nothing wider than the file's own directory holding just this file
  // is still a directory run, so the cross-file rules see whatever siblings are there.
  return { scope: 'file', path: root, focusFile: filePath };
}

/**
 * The §11.1 selector that narrows the diagram to one file. `relativePath` is already
 * workspace-relative and forward-slashed (`location.toWorkspaceRelative`).
 */
export function fileScopeSpec(relativePath: string): string {
  return `${SCOPE_KIND_FILE}:${relativePath}`;
}

/**
 * The §11.1 selector for the focused file, or null when it is not inside the analyzed root.
 *
 * The refusal is the interesting half: `toWorkspaceRelative` answers with a `..` path for a
 * file outside the graph's root, and posting `file:../thing.py` would leave the viewer showing
 * an empty projection of a document that never contained the file. Leaving the scope alone and
 * saying so in the log is the honest failure.
 */
export function focusScopeSpec(graphRoot: string, focusFile: string): string | null {
  const relative = toWorkspaceRelative(graphRoot, focusFile);
  return relative.startsWith('..') ? null : fileScopeSpec(relative);
}
