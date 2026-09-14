/**
 * CFG-ONE, host half — one configuration surface with a STATED precedence.
 *
 * Before this file there were two configuration systems that did not know about each other:
 * `.mlview.toml` was auto-discovered by the analyzer and honoured `[rules].disable` and
 * `[paths].exclude` (`rules/suppress.py:42-46`), while the extension maintained a PARALLEL
 * `mlview.disabledRules` / `mlview.exclude` and never passed `--config` — `grep toml` in
 * `coreClient.ts` and `settings.ts` returned nothing. A team that checked a `.mlview.toml`
 * into the repository got it applied on the CLI and ignored in the editor.
 *
 * The precedence, which the two settings descriptions in package.json state verbatim and
 * `test/config.test.js` asserts:
 *
 *   TOML WINS for `disable` and `exclude`. The `mlview.*` settings are ADDITIVE FILTERS on
 *   top: `mlview.disabledRules` can hide a rule the file leaves on, and `mlview.exclude` can
 *   drop more paths, but neither can re-enable a rule the file disabled or re-include a path
 *   the file excluded.
 *
 * That falls straight out of how the two halves are applied and is not a new mechanism: the
 * analyzer applies the file (it suppresses findings and prunes discovery), and the host then
 * filters what came back. There is deliberately no host-side "override the file" path — a
 * second mechanism that could contradict the checked-in one is exactly what CFG-ONE's risk
 * line warns against.
 *
 * This module is pure except for the two command bodies at the bottom; everything the tests
 * need takes its filesystem through `ConfigProbe`.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import type { CoreClient } from './coreClient';
import type { Logger } from './log';
import type { MlviewSettings } from './settings';

/** The file name the analyzer auto-discovers (`rules/suppress.py:load_config`). */
export const CONFIG_FILE_NAME = '.mlview.toml';
/** The fallback location: a `[tool.mlview]` table inside the project's pyproject. */
export const PYPROJECT_FILE_NAME = 'pyproject.toml';
/** Where `mlview baseline write` puts a baseline when nobody names a path. */
export const DEFAULT_BASELINE_RELATIVE = '.mlview/baseline.json';

/** A `[tool.mlview]` (or `[tool.mlview.rules]`, ...) table header, at the start of a line. */
const TOOL_TABLE_RE = /^[ \t]*\[[ \t]*tool[ \t]*\.[ \t]*mlview[ \t]*(?:\.[^\]]*)?\][ \t]*(?:#.*)?$/m;

/** The filesystem, injectable so the resolution rules can be tested without one. */
export interface ConfigProbe {
  exists(fsPath: string): boolean;
  readText(fsPath: string): string;
}

export const REAL_PROBE: ConfigProbe = {
  exists: (p) => {
    try {
      return fs.existsSync(p);
    } catch {
      return false;
    }
  },
  readText: (p) => {
    try {
      return fs.readFileSync(p, 'utf8');
    } catch {
      return '';
    }
  }
};

export type ConfigSource = 'setting' | 'toml' | 'pyproject' | 'none';

export interface ResolvedConfig {
  /** Absolute path to hand `--config`, or undefined when there is nothing to hand it. */
  path?: string;
  source: ConfigSource;
  /**
   * Set when `mlview.configPath` names a file that is not there. The caller LOGS this rather
   * than swallowing it: a configPath typo that silently falls back to auto-discovery is the
   * same class of defect CLEANUP 3 fixed for a typo'd rule code.
   */
  missing?: string;
}

/** True when this pyproject.toml actually carries an MLView table. */
export function pyprojectHasMlviewTable(text: string): boolean {
  return TOOL_TABLE_RE.test(text);
}

/** Resolve a possibly-relative user path against the folder root. Empty means "unset". */
export function resolveAgainstRoot(root: string, raw: string | undefined): string | undefined {
  const value = (raw ?? '').trim();
  if (!value) {
    return undefined;
  }
  return path.isAbsolute(value) ? path.normalize(value) : path.resolve(root, value);
}

/**
 * Which file `--config` should name for this folder.
 *
 * 1. `mlview.configPath`, when it is set and the file is there — an explicit answer beats a
 *    discovered one, and it is the only way to point at a config outside the folder.
 * 2. `<root>/.mlview.toml` — the file the analyzer already discovers on its own. Passing it
 *    explicitly changes nothing about the run and everything about `mlview.configPath`
 *    working uniformly.
 * 3. `<root>/pyproject.toml`, **only when it contains a `[tool.mlview]` table.** A pyproject
 *    with no MLView table is not an MLView config, and handing it to `--config` would make a
 *    Python project that has never heard of MLView look configured.
 */
export function resolveConfig(
  root: string,
  settings: Pick<MlviewSettings, 'configPath'>,
  probe: ConfigProbe = REAL_PROBE
): ResolvedConfig {
  const named = resolveAgainstRoot(root, settings.configPath);
  if (named) {
    if (probe.exists(named)) {
      return { path: named, source: 'setting' };
    }
    return { source: 'none', missing: named };
  }
  const toml = path.join(root, CONFIG_FILE_NAME);
  if (probe.exists(toml)) {
    return { path: toml, source: 'toml' };
  }
  const pyproject = path.join(root, PYPROJECT_FILE_NAME);
  if (probe.exists(pyproject) && pyprojectHasMlviewTable(probe.readText(pyproject))) {
    return { path: pyproject, source: 'pyproject' };
  }
  return { source: 'none' };
}

/**
 * Which file `--baseline` should name, or undefined.
 *
 * Only ever the EXPLICIT `mlview.baselinePath`, and only when it exists. A baseline changes
 * which findings are counted and which reach `--fail-on`, so auto-discovering one would let a
 * file dropped into `.mlview/` quietly empty somebody's Problems panel. `MLView: Create
 * Baseline From Current Findings` writes to `DEFAULT_BASELINE_RELATIVE` and then offers to
 * set the setting, which is the moment the user opts in.
 */
export function resolveBaseline(
  root: string,
  settings: Pick<MlviewSettings, 'baselinePath'>,
  probe: ConfigProbe = REAL_PROBE
): { path?: string; missing?: string } {
  const named = resolveAgainstRoot(root, settings.baselinePath);
  if (!named) {
    return {};
  }
  return probe.exists(named) ? { path: named } : { missing: named };
}

/** One human sentence naming what was found, for the output channel. */
export function configLogLine(resolved: ResolvedConfig): string {
  if (resolved.missing) {
    return `mlview.configPath names ${resolved.missing}, which does not exist - no --config was passed`;
  }
  switch (resolved.source) {
    case 'setting':
      return `configuration from mlview.configPath: ${resolved.path}`;
    case 'toml':
      return `configuration discovered: ${resolved.path}`;
    case 'pyproject':
      return `configuration discovered in [tool.mlview]: ${resolved.path}`;
    default:
      return 'no .mlview.toml and no [tool.mlview] table - the mlview.* settings are the only configuration';
  }
}

// ------------------------------------------------------------------ command bodies

/** What the two configuration commands need from the controller. */
export interface ConfigCommandHost {
  readonly log: Logger;
  readonly core: CoreClient;
  /** The active folder's root, or undefined when no folder is open. */
  workspaceRoot(): string | undefined;
  settingsFor(uri: vscode.Uri): MlviewSettings;
  /** The paths the current scope hands the analyzer, for the baseline run. */
  currentPaths(root: string): string[];
}

async function openInEditor(fsPath: string): Promise<void> {
  const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(fsPath));
  await vscode.window.showTextDocument(doc);
}

/**
 * `MLView: Open MLView Configuration`.
 *
 * Opens the file `--config` would name. When there is none, it asks the CORE to write one
 * (`mlview init`, which generates a commented file listing every registered rule from the
 * registry the way `gen_rule_docs.py` does) rather than writing a stub here: a host-authored
 * starter file would be a second, drifting description of the rule catalogue, and CFG-ONE's
 * whole point is that there is one.
 */
export async function openConfiguration(
  host: ConfigCommandHost,
  probe: ConfigProbe = REAL_PROBE
): Promise<void> {
  const root = host.workspaceRoot();
  if (!root) {
    void vscode.window.showWarningMessage('MLView: open a folder before editing its configuration.');
    return;
  }
  const settings = host.settingsFor(vscode.Uri.file(root));
  const resolved = resolveConfig(root, settings, probe);
  host.log.info(configLogLine(resolved));
  if (resolved.path) {
    await openInEditor(resolved.path);
    return;
  }
  const created = path.join(root, CONFIG_FILE_NAME);
  const choice = await vscode.window.showInformationMessage(
    `MLView: no ${CONFIG_FILE_NAME} in ${path.basename(root)}. Create one?`,
    'Create',
    'Cancel'
  );
  if (choice !== 'Create') {
    return;
  }
  try {
    await host.core.runCli(['-X', 'utf8', '-m', 'mlview', 'init'], { cwd: root, key: 'init' });
  } catch (err) {
    host.log.warn(`mlview init failed: ${String(err)}`);
  }
  if (!probe.exists(created)) {
    void vscode.window.showWarningMessage(
      `MLView: this core could not write ${CONFIG_FILE_NAME} (it may predate "mlview init"). ` +
        'Upgrade the MLView core, or create the file by hand - MLView will pick it up on the next run.',
      'Show Output'
    ).then((pick) => {
      if (pick === 'Show Output') {
        host.log.show(false);
      }
    });
    return;
  }
  await openInEditor(created);
}

/**
 * `MLView: Create Baseline From Current Findings` — CI-ADOPT's ratchet, reachable from the
 * editor. Runs `mlview baseline write --out <file>` over exactly the paths the current scope
 * analyses, then offers to point `mlview.baselinePath` at what it wrote, because a baseline
 * nobody is configured to read changes nothing.
 */
export async function createBaseline(
  host: ConfigCommandHost,
  probe: ConfigProbe = REAL_PROBE
): Promise<void> {
  const root = host.workspaceRoot();
  if (!root) {
    void vscode.window.showWarningMessage('MLView: open a folder before recording a baseline.');
    return;
  }
  const settings = host.settingsFor(vscode.Uri.file(root));
  const target =
    resolveAgainstRoot(root, settings.baselinePath) ??
    path.resolve(root, DEFAULT_BASELINE_RELATIVE);
  const args = [
    '-X',
    'utf8',
    '-m',
    'mlview',
    'baseline',
    'write',
    ...host.currentPaths(root),
    '--out',
    target,
    '--max-files',
    String(settings.maxFiles),
    '--max-nodes',
    String(settings.maxNodes)
  ];
  const config = resolveConfig(root, settings, probe);
  if (config.path) {
    args.push('--config', config.path);
  }
  for (const glob of settings.exclude) {
    if (glob.trim().length > 0) {
      args.push('--exclude', glob.trim());
    }
  }
  if (settings.includeNotebooks) {
    args.push('--include-notebooks');
  }
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'MLView: recording a baseline…' },
    async () => {
      try {
        await host.core.runCli(args, { cwd: root, key: 'baseline' });
      } catch (err) {
        host.log.error('mlview baseline write failed', err);
        void vscode.window.showErrorMessage(
          `MLView could not write the baseline: ${err instanceof Error ? err.message : String(err)}`
        );
        return;
      }
      if (!probe.exists(target)) {
        void vscode.window.showWarningMessage(
          `MLView: the baseline run finished but ${target} is not there. Run "MLView: Show Output" for the analyzer's own words.`
        );
        return;
      }
      const relative = path.relative(root, target).replace(/\\/g, '/');
      const already = (settings.baselinePath ?? '').trim().length > 0;
      const choice = await vscode.window.showInformationMessage(
        `MLView baseline written to ${relative}. ` +
          (already
            ? 'mlview.baselinePath already points at it.'
            : 'Point mlview.baselinePath at it so these findings stop counting?'),
        ...(already ? ['Open'] : ['Set mlview.baselinePath', 'Open'])
      );
      if (choice === 'Set mlview.baselinePath') {
        await vscode.workspace
          .getConfiguration('mlview', vscode.Uri.file(root))
          .update('baselinePath', relative, vscode.ConfigurationTarget.WorkspaceFolder);
        host.log.info(`mlview.baselinePath set to ${relative}`);
      } else if (choice === 'Open') {
        await openInEditor(target);
      }
    }
  );
}
