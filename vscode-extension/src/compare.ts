/**
 * VIEW-08 — compare two analyses, host half.
 *
 * The most valuable question a reviewer has is *"my PR added a scaler; did it move to the
 * wrong side of the split?"*. The analyzer answers it (`mlview diff BASE.json HEAD.json`,
 * CONTRACTS §11.38); this module is the three gestures that let an editor ask.
 *
 *   MLView: Save Current Graph As Comparison Base   -> .mlview/comparison-base.json
 *   MLView: Compare With Saved Base                 -> mlview diff base head --json -
 *   MLView: Compare With Clean Sample               -> the same, with a clean twin as base
 *
 * Four rules this module keeps:
 *
 * 1. **The diff is computed by the analyzer, never here.** All three hosts must get one
 *    answer from one implementation; a second comparison in TypeScript is exactly the drift
 *    §11.38 was written to prevent. This file writes two JSON documents and reads one back.
 * 2. **The overlay is a SIBLING of the graph, never merged into it.** `schemaVersion` stays
 *    1.0 and the graph the viewer holds is untouched, which is what keeps a comparison from
 *    changing a single byte of what an unscoped analysis produced.
 * 3. **`notes[]` is never swallowed.** §11.38 C exists because *"−16 nodes"* can mean a
 *    truncation, a projection, a different root or a different analyzer, and a reviewer who
 *    reads it as a deletion has been misled by the tool. Every note goes to the output
 *    channel verbatim, and the toast says how many there are.
 * 4. **A comparison dies with the document it described.** A new graph clears the overlay
 *    (`MlviewPanel.postGraph`), because a stale *"0 new findings"* drawn over a freshly
 *    analyzed diagram is the one failure this product cannot survive.
 *
 * **What this cannot do.** It cannot tell a rename from a delete-plus-add: the §0 stable id
 * embeds the path, so the analyzer reports both, and no rename detection is attempted in the
 * host either. It compares two DOCUMENTS, so a base written before a settings change carries
 * that change into the counts, and the `different-analyzers` note is the only warning
 * available. And "Compare With Clean Sample" is a demo affordance: it finds a twin directory
 * by name, so the pair is siblings rather than two commits of one tree — which is precisely
 * what the `different-roots` note says out loud.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import type { CoreClient } from './coreClient';
import type { MLGraph } from './graph';
import type { Logger } from './log';
import type { DiffOverlay } from './protocol';
import { isInsideWorkspace } from './suppression';
import type { MlviewSettings } from './settings';

export const SAVE_BASE_COMMAND = 'mlview.saveComparisonBase';
export const COMPARE_BASE_COMMAND = 'mlview.compareWithBase';
export const COMPARE_CLEAN_COMMAND = 'mlview.compareWithCleanSample';

/** Beside `.mlview/baseline.json`, in the directory MLView already owns in a workspace. */
export const COMPARISON_BASE_RELATIVE = '.mlview/comparison-base.json';

/** The directory names "Compare With Clean Sample" looks for, in order, under the root. */
export const CLEAN_TWIN_RELATIVE: readonly string[] = [
  'samples/vision_pipeline_clean',
  'vision_pipeline_clean'
];

/** What the three commands need from the controller. */
export interface CompareHost {
  readonly log: Logger;
  readonly core: CoreClient;
  readonly ctx: vscode.ExtensionContext;
  getGraph(): MLGraph | undefined;
  ensureGraph(): Promise<MLGraph | undefined>;
  workspaceRoot(): string | undefined;
  settingsFor(uri: vscode.Uri): MlviewSettings;
  /** The live diagram, or undefined when no panel is open. Never opens one. */
  comparisonPanel(): { postDiffOverlay(overlay: DiffOverlay | null, baseLabel?: string): void } | undefined;
}

/** The absolute path of a workspace-relative name, refused if it escapes the root. */
export function withinRoot(root: string, relative: string): string | undefined {
  const resolved = path.resolve(root, relative);
  return isInsideWorkspace(root, resolved) ? resolved : undefined;
}

/** Where this workspace's comparison base lives. */
export function comparisonBasePath(root: string): string | undefined {
  return withinRoot(root, COMPARISON_BASE_RELATIVE);
}

/**
 * The clean twin, or undefined. Named directories only: guessing at a sibling of the
 * workspace would reach outside the folder the user opened, and this is a demo affordance,
 * not a heuristic worth a filesystem walk.
 */
export function findCleanTwin(
  root: string,
  exists: (p: string) => boolean = (p) => fs.existsSync(p)
): string | undefined {
  for (const relative of CLEAN_TWIN_RELATIVE) {
    const candidate = withinRoot(root, relative);
    if (candidate && exists(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

/** `+26 nodes · −16 nodes · 0 new findings · 15 fixed`, or a fallback built from the counts. */
export function overlayHeadline(overlay: DiffOverlay): string {
  const summary = overlay.summary as Record<string, unknown> | undefined;
  const headline = summary?.['headline'];
  if (typeof headline === 'string' && headline.length > 0) {
    return headline;
  }
  return 'comparison complete';
}

/** Every `notes[]` entry as one line. §11.38 C: these are never elided by a renderer. */
export function overlayNoteLines(overlay: DiffOverlay): string[] {
  const notes = Array.isArray(overlay.notes) ? overlay.notes : [];
  return notes.map((raw) => {
    const note = (raw ?? {}) as Record<string, unknown>;
    const kind = typeof note['kind'] === 'string' ? note['kind'] : 'note';
    const message = typeof note['message'] === 'string' ? note['message'] : '';
    const side = typeof note['side'] === 'string' ? ` (${note['side']})` : '';
    return `${kind}${side}: ${message}`;
  });
}

/**
 * Structural guard for what came back on stdout. `kind` is §11.38 B's discriminator and it is
 * checked BEFORE anything else, exactly as the amendment says a consumer must: an older core
 * that does not know `diff` prints a usage error, and a graph is not an overlay.
 */
export function readOverlay(stdout: string): DiffOverlay | undefined {
  let parsed: unknown;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    return undefined;
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    return undefined;
  }
  const doc = parsed as Record<string, unknown>;
  if (doc['kind'] !== 'mlview-diff' || typeof doc['diffVersion'] !== 'string') {
    return undefined;
  }
  return doc as unknown as DiffOverlay;
}

/** Write a graph document where the analyzer can read it back. Throws on an unwritable path. */
function writeDocument(target: string, graph: MLGraph): void {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, `${JSON.stringify(graph, null, 2)}\n`, 'utf8');
}

/** A scratch path inside the extension's own storage — never inside the user's repository. */
function scratchPath(host: CompareHost, name: string): string {
  const dir = host.ctx.globalStorageUri.fsPath;
  fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, name);
}

/**
 * `MLView: Save Current Graph As Comparison Base`.
 *
 * The base is the document the analyzer already produced, written verbatim: re-analysing to
 * capture a base would record a *different* run, and a diff whose two sides were produced by
 * two different invocations is the mistake §11.38 D orders the summary to make visible.
 */
export async function saveComparisonBase(host: CompareHost): Promise<string | undefined> {
  const root = host.workspaceRoot();
  if (!root) {
    void vscode.window.showWarningMessage('MLView: open a folder before saving a comparison base.');
    return undefined;
  }
  const graph = host.getGraph() ?? (await host.ensureGraph());
  if (!graph) {
    void vscode.window.showWarningMessage(
      'MLView: analyze this workspace first — there is no graph to save as a base.'
    );
    return undefined;
  }
  const target = comparisonBasePath(root);
  if (!target) {
    host.log.warn(`refusing to write a comparison base outside ${root}`);
    return undefined;
  }
  const replacing = fs.existsSync(target);
  try {
    writeDocument(target, graph);
  } catch (err) {
    host.log.error(`could not write ${target}`, err);
    void vscode.window.showErrorMessage(`MLView: could not write the comparison base: ${String(err)}`);
    return undefined;
  }
  const relative = path.relative(root, target).replace(/\\/g, '/');
  host.log.info(
    `${replacing ? 'replaced' : 'wrote'} the comparison base at ${target} ` +
      `(${graph.nodes?.length ?? 0} nodes, ${graph.issues?.length ?? 0} findings)`
  );
  void vscode.window.showInformationMessage(
    `MLView: ${replacing ? 'replaced' : 'saved'} the comparison base (${relative}) — ` +
      `${graph.nodes?.length ?? 0} nodes, ${graph.issues?.length ?? 0} findings. ` +
      'Run "MLView: Compare With Saved Base" after your next change.'
  );
  return target;
}

/** Run `mlview diff BASE HEAD --json -` and hand the overlay back, or undefined. */
async function runDiff(
  host: CompareHost,
  root: string,
  basePath: string,
  headPath: string
): Promise<DiffOverlay | undefined> {
  const args = ['-X', 'utf8', '-m', 'mlview', 'diff', basePath, headPath, '--json', '-'];
  let stdout: string;
  try {
    ({ stdout } = await host.core.runCli(args, { cwd: root, key: 'diff' }));
  } catch (err) {
    host.log.error('mlview diff failed', err);
    void vscode.window.showErrorMessage(
      `MLView could not compare the two analyses: ${err instanceof Error ? err.message : String(err)}`
    );
    return undefined;
  }
  const overlay = readOverlay(stdout);
  if (!overlay) {
    host.log.warn('mlview diff produced something that is not an overlay document');
    void vscode.window.showWarningMessage(
      'MLView: the comparison produced no overlay. This core may predate "mlview diff" — run "MLView: Show Output".'
    );
    return undefined;
  }
  return overlay;
}

/** Post the overlay, log every note, and say the headline out loud. */
function publishOverlay(host: CompareHost, overlay: DiffOverlay, baseLabel: string): void {
  const notes = overlayNoteLines(overlay);
  // §11.38 C: notes are NEVER elided. The output channel gets all of them, verbatim.
  for (const line of notes) {
    host.log.info(`diff note — ${line}`);
  }
  const panel = host.comparisonPanel();
  if (panel) {
    panel.postDiffOverlay(overlay, baseLabel);
  }
  const headline = overlayHeadline(overlay);
  host.log.info(`diff vs ${baseLabel}: ${headline}`);
  const caveat = notes.length > 0 ? ` · ${notes.length} caveat(s) — see MLView output` : '';
  const message = `MLView vs ${baseLabel}: ${headline}${caveat}`;
  void vscode.window
    .showInformationMessage(message, ...(notes.length > 0 ? ['Show Output'] : []))
    .then((choice) => {
      if (choice === 'Show Output') {
        host.log.show(false);
      }
    });
  if (!panel) {
    host.log.info('no diagram is open, so the overlay was reported but not drawn');
  }
}

/**
 * `MLView: Compare With Saved Base`.
 *
 * The head is re-analysed first (`ensureGraph`), so the comparison describes what is on disk
 * now rather than whatever the panel happens to be holding.
 */
export async function compareWithSavedBase(host: CompareHost): Promise<DiffOverlay | undefined> {
  const root = host.workspaceRoot();
  if (!root) {
    void vscode.window.showWarningMessage('MLView: open a folder before comparing analyses.');
    return undefined;
  }
  const basePath = comparisonBasePath(root);
  if (!basePath || !fs.existsSync(basePath)) {
    const choice = await vscode.window.showInformationMessage(
      `MLView: no comparison base in this workspace (${COMPARISON_BASE_RELATIVE}). Save one now?`,
      'Save Base',
      'Cancel'
    );
    if (choice === 'Save Base') {
      await saveComparisonBase(host);
    }
    return undefined;
  }
  const graph = host.getGraph() ?? (await host.ensureGraph());
  if (!graph) {
    void vscode.window.showWarningMessage('MLView: there is no current analysis to compare.');
    return undefined;
  }
  const headPath = scratchPath(host, 'comparison-head.json');
  try {
    writeDocument(headPath, graph);
  } catch (err) {
    host.log.error(`could not write ${headPath}`, err);
    return undefined;
  }
  const overlay = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'MLView: comparing analyses…' },
    () => runDiff(host, root, basePath, headPath)
  );
  if (overlay) {
    publishOverlay(host, overlay, path.relative(root, basePath).replace(/\\/g, '/'));
  }
  return overlay;
}

/**
 * `MLView: Compare With Clean Sample` — the demo gesture.
 *
 * `samples/vision_pipeline` (54 nodes / 15 findings) against `samples/vision_pipeline_clean`
 * (64 / 0) is the shipped before-and-after pair, and the overlay's own `different-roots` note
 * is the caveat that reading applies: the two are siblings, not two commits of one tree.
 */
export async function compareWithCleanSample(host: CompareHost): Promise<DiffOverlay | undefined> {
  const root = host.workspaceRoot();
  if (!root) {
    void vscode.window.showWarningMessage('MLView: open a folder before comparing analyses.');
    return undefined;
  }
  const twin = findCleanTwin(root);
  if (!twin) {
    void vscode.window.showWarningMessage(
      'MLView: no clean twin found. This command looks for ' +
        CLEAN_TWIN_RELATIVE.map((r) => `"${r}"`).join(' or ') +
        ' under the workspace root; use "MLView: Save Current Graph As Comparison Base" instead.'
    );
    return undefined;
  }
  const graph = host.getGraph() ?? (await host.ensureGraph());
  if (!graph) {
    void vscode.window.showWarningMessage('MLView: there is no current analysis to compare.');
    return undefined;
  }
  const overlay = await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: 'MLView: analysing the clean sample…' },
    async () => {
      let clean: MLGraph;
      try {
        const result = await host.core.analyze({
          scope: 'workspace',
          paths: [twin],
          cwd: twin,
          settings: host.settingsFor(vscode.Uri.file(root))
        });
        clean = result.graph;
      } catch (err) {
        host.log.error('could not analyze the clean sample', err);
        void vscode.window.showErrorMessage(
          `MLView could not analyze ${twin}: ${err instanceof Error ? err.message : String(err)}`
        );
        return undefined;
      }
      const basePath = scratchPath(host, 'clean-sample-base.json');
      const headPath = scratchPath(host, 'comparison-head.json');
      try {
        writeDocument(basePath, clean);
        writeDocument(headPath, graph);
      } catch (err) {
        host.log.error('could not stage the comparison documents', err);
        return undefined;
      }
      return runDiff(host, root, basePath, headPath);
    }
  );
  if (overlay) {
    publishOverlay(host, overlay, path.relative(root, twin).replace(/\\/g, '/') || twin);
  }
  return overlay;
}

/** Register the three comparison commands. Called unconditionally at activation. */
export function registerComparisonCommands(host: CompareHost): vscode.Disposable[] {
  return [
    vscode.commands.registerCommand(SAVE_BASE_COMMAND, () => saveComparisonBase(host)),
    vscode.commands.registerCommand(COMPARE_BASE_COMMAND, () => compareWithSavedBase(host)),
    vscode.commands.registerCommand(COMPARE_CLEAN_COMMAND, () => compareWithCleanSample(host))
  ];
}
