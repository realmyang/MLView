/**
 * The process seam (CONTRACTS.md §3). This module is the ONLY place in the extension that
 * spawns the analyzer, and the extension contains no analysis of its own.
 *
 *   python -X utf8 -m mlview analyze <paths...> --json - --max-files N --max-nodes N [--exclude G]...
 *
 * Windows/UTF-8 invariant: `-X utf8` in argv, `PYTHONUTF8=1` + `PYTHONIOENCODING=utf-8` in the
 * environment, `shell: false`, and an absolute interpreter path. Without them cp1252 mangles the
 * JSON on the first non-ASCII identifier or path.
 */

import { execFile, type ChildProcess } from 'node:child_process';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { emptyGraph, isSchemaCompatible, looksLikeGraph, type MLGraph } from './graph';
import type { Logger } from './log';
import { ProgressSplitter, type ProgressFrame } from './progress';
import { PythonEnvironment, schemaMismatchMessage } from './pythonEnv';
import { buildAnalyzeArgs, classifyExit, tailLines } from './analyzeArgs';
import { readSettings, type MlviewSettings } from './settings';
import { configLogLine, resolveBaseline, resolveConfig } from './mlviewConfig';
import type { AnalysisScope } from './protocol';
import { isTrusted, MANAGE_TRUST_ACTION, RESTRICTED_DETAIL, RESTRICTED_MESSAGE } from './trust';

export const MAX_BUFFER_BYTES = 32 * 1024 * 1024;
export const SAVE_DEBOUNCE_MS = 400;
const KILL_GRACE_MS = 2000;

export type CoreErrorKind =
  | 'restricted'
  | 'interpreter'
  | 'spawn'
  | 'usage'
  | 'internal'
  | 'parse'
  | 'schema'
  | 'cancelled';

export interface CoreAction {
  id: string;
  label: string;
}

export class CoreError extends Error {
  readonly kind: CoreErrorKind;
  readonly detail: string;
  readonly actions: CoreAction[];

  constructor(kind: CoreErrorKind, message: string, detail = '', actions: CoreAction[] = []) {
    super(message);
    this.name = 'CoreError';
    this.kind = kind;
    this.detail = detail;
    this.actions = actions;
  }
}

export const DEFAULT_ACTIONS: CoreAction[] = [
  { id: 'retry', label: 'Retry' },
  { id: 'selectInterpreter', label: 'Select Interpreter' },
  { id: 'showOutput', label: 'Show Output' }
];

/**
 * The argv, the §3 exit-code table and the stderr tail now live in `src/analyzeArgs.ts`
 * (H10 + CFG-ONE pushed this file past the ~600-line budget). Re-exported here so every
 * existing importer - three test files and `src/testEntry.ts` - is unchanged.
 */
export {
  buildAnalyzeArgs,
  classifyExit,
  tailLines,
  type AnalyzeArgOptions,
  type ExitClass
} from './analyzeArgs';

export interface AnalyzeRequest {
  scope: AnalysisScope;
  /** Absolute paths handed to the analyzer. */
  paths: string[];
  /** Absolute directory the analyzer runs in; also the graph's workspace root. */
  cwd: string;
  token?: vscode.CancellationToken;
  settings?: MlviewSettings;
  /**
   * H10 (11.40): a §11.1 diagram selector, from a language-model tool that asked about one
   * part of the pipeline. It projects the EMITTED DOCUMENT, so a scoped result is a filtered
   * view whose counts describe the scope — which is why the caller must not publish it as the
   * workspace's graph. Absent on every diagram, save and export path.
   */
  scopeSpec?: string;
  /** Boundary hops, 0..2, meaningful only alongside `scopeSpec`. */
  depth?: number;
  /**
   * H3: set by the caller only when a panel is live. Its presence is what adds
   * `--progress-json` to the argv, so nothing about the headless path changes.
   */
  onProgress?: (frame: ProgressFrame) => void;
}

export interface AnalyzeResult {
  graph: MLGraph;
  /** True when the analyzer reported exit code 4 (nothing analyzable). */
  empty: boolean;
  durationMs: number;
}

interface RunResult {
  code: number | null;
  stdout: string;
  stderr: string;
  cancelled: boolean;
}

/** A trailing-edge debounce, used for the analyze-on-save burst. */
export class Debouncer implements vscode.Disposable {
  private timer: NodeJS.Timeout | undefined;

  constructor(private readonly delayMs: number) {}

  schedule(fn: () => void): void {
    this.cancel();
    this.timer = setTimeout(() => {
      this.timer = undefined;
      fn();
    }, this.delayMs);
  }

  cancel(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
  }

  dispose(): void {
    this.cancel();
  }
}

interface InFlight {
  child: ChildProcess;
  kill: () => void;
}

export class CoreClient implements vscode.Disposable {
  private readonly inFlight = new Map<string, InFlight>();
  private readonly saveDebounce = new Debouncer(SAVE_DEBOUNCE_MS);

  constructor(
    private readonly env: PythonEnvironment,
    private readonly log: Logger,
    /**
     * CACHE (CONTRACTS 11.28). Where the core may keep its per-file fact
     * sidecar. Appended last and optional, so every existing construction -
     * `extension.ts` and three test files - is unchanged.
     *
     * The extension passes its own storage directory rather than letting the
     * default (`<workspace>/.mlview/cache`) apply, because `analyzeOnSave`
     * fires on every Ctrl+S and a tool that writes into the user's repository
     * on every keystroke-plus-save is a tool people turn off. Leave it
     * undefined and the core falls back to the project default; set
     * `MLVIEW_NO_CACHE=1` in the environment and there is no cache at all.
     */
    private readonly cacheDir?: string
  ) {}

  /** Debounced entry point used by the analyze-on-save handler. */
  scheduleAnalyze(fn: () => void): void {
    this.saveDebounce.schedule(fn);
  }

  cancel(scope: AnalysisScope, path?: string): void {
    const key = scopeKey(scope, path);
    const running = this.inFlight.get(key);
    if (running) {
      this.log.info(`cancelling in-flight analysis for ${key}`);
      running.kill();
      this.inFlight.delete(key);
    }
  }

  cancelAll(): void {
    for (const [key, running] of this.inFlight) {
      this.log.debug(`cancelling ${key}`);
      running.kill();
    }
    this.inFlight.clear();
  }

  /**
   * CFG-ONE: what `--config` / `--baseline` should name for this run, logged once so a user
   * can see in the output channel which file the answer they are looking at was produced with.
   */
  private configFlags(request: AnalyzeRequest, settings: MlviewSettings): {
    configPath?: string;
    baselinePath?: string;
  } {
    const config = resolveConfig(request.cwd, settings);
    if (config.missing) {
      this.log.warn(configLogLine(config));
    } else if (config.path) {
      this.log.debug(configLogLine(config));
    }
    const baseline = resolveBaseline(request.cwd, settings);
    if (baseline.missing) {
      this.log.warn(
        `mlview.baselinePath names ${baseline.missing}, which does not exist - no --baseline was passed`
      );
    }
    return {
      ...(config.path ? { configPath: config.path } : {}),
      ...(baseline.path ? { baselinePath: baseline.path } : {})
    };
  }

  async analyze(request: AnalyzeRequest): Promise<AnalyzeResult> {
    const settings = request.settings ?? readSettings();
    const args = buildAnalyzeArgs({
      paths: request.paths,
      maxFiles: settings.maxFiles,
      maxNodes: settings.maxNodes,
      exclude: settings.exclude,
      includeNotebooks: settings.includeNotebooks,
      ...this.configFlags(request, settings),
      // H10: only ever set by the language-model tools; every other caller omits it.
      ...(request.scopeSpec ? { scopeSpec: request.scopeSpec } : {}),
      ...(typeof request.depth === 'number' ? { depth: request.depth } : {}),
      progress: request.onProgress !== undefined
    });
    const started = Date.now();
    const run = await this.spawn(
      scopeKey(request.scope, request.paths[0], request.scopeSpec),
      args,
      request
    );
    const durationMs = Date.now() - started;
    if (run.cancelled) {
      throw new CoreError('cancelled', 'Analysis cancelled.');
    }
    const outcome = classifyExit(run.code);
    if (outcome === 'nothing-analyzable') {
      this.log.info('analyzer reported nothing analyzable (exit 4)');
      return { graph: emptyGraph(forwardSlashes(request.cwd)), empty: true, durationMs };
    }
    if (outcome === 'usage') {
      throw new CoreError(
        'usage',
        'MLView analyzer reported a usage or I/O error.',
        tailLines(run.stderr) || tailLines(run.stdout),
        DEFAULT_ACTIONS
      );
    }
    if (outcome === 'internal' || outcome === 'unknown') {
      throw new CoreError(
        'internal',
        'MLView analyzer failed internally.',
        tailLines(run.stderr) || tailLines(run.stdout),
        DEFAULT_ACTIONS
      );
    }
    return { graph: this.parseGraph(run), empty: false, durationMs };
  }

  /** `analyze --html <file>`; returns the file that was written. */
  async exportHtml(
    request: AnalyzeRequest & { outFile: string; scopeSpec?: string; depth?: number }
  ): Promise<string> {
    const settings = request.settings ?? readSettings();
    const args = buildAnalyzeArgs({
      paths: request.paths,
      maxFiles: settings.maxFiles,
      maxNodes: settings.maxNodes,
      exclude: settings.exclude,
      includeNotebooks: settings.includeNotebooks,
      ...this.configFlags(request, settings),
      htmlOut: request.outFile,
      // What the panel is drawing, so the exported report opens on the same diagram (§11.8:
      // the file still embeds the WHOLE graph; the scope is one attribute on the root).
      scopeSpec: request.scopeSpec,
      depth: request.depth
    });
    const run = await this.spawn(`export:${request.outFile}`, args, request);
    if (run.cancelled) {
      throw new CoreError('cancelled', 'Export cancelled.');
    }
    const outcome = classifyExit(run.code);
    if (outcome !== 'ok' && outcome !== 'fail-on') {
      throw new CoreError(
        outcome === 'nothing-analyzable' ? 'usage' : 'internal',
        outcome === 'nothing-analyzable'
          ? 'Nothing analyzable was found, so no report was written.'
          : 'MLView could not write the HTML report.',
        tailLines(run.stderr),
        DEFAULT_ACTIONS
      );
    }
    return request.outFile;
  }

  private parseGraph(run: RunResult): MLGraph {
    let parsed: unknown;
    try {
      parsed = JSON.parse(run.stdout);
    } catch (err) {
      throw new CoreError(
        'parse',
        'MLView returned output that is not valid JSON.',
        `${String(err)}\n${tailLines(run.stderr)}`,
        DEFAULT_ACTIONS
      );
    }
    if (!looksLikeGraph(parsed)) {
      throw new CoreError(
        'parse',
        'MLView returned JSON that is not a graph document.',
        tailLines(run.stderr),
        DEFAULT_ACTIONS
      );
    }
    if (!isSchemaCompatible(parsed.schemaVersion)) {
      throw new CoreError('schema', schemaMismatchMessage(parsed.schemaVersion), '', [
        { id: 'installCore', label: 'Install MLView core' },
        { id: 'showOutput', label: 'Show Output' }
      ]);
    }
    return parsed;
  }

  /**
   * CFG-ONE: run one non-analyze CLI verb (`mlview init`, `mlview baseline write`) through
   * the SAME seam every analysis goes through — the trust gate, the interpreter chain, the
   * bundled-core PYTHONPATH and the UTF-8 environment are all in `spawn`, and a second
   * `execFile` anywhere in this extension would be a second place for `untrustedWorkspaces:
   * "limited"` to be forgotten. Throws a `CoreError` on a non-zero exit.
   */
  async runCli(
    args: string[],
    request: { cwd: string; key: string; token?: vscode.CancellationToken }
  ): Promise<{ stdout: string; stderr: string }> {
    const run = await this.spawn(`cli:${request.key}`, args, request);
    if (run.cancelled) {
      throw new CoreError('cancelled', 'Cancelled.');
    }
    const outcome = classifyExit(run.code);
    if (outcome !== 'ok' && outcome !== 'fail-on') {
      throw new CoreError(
        outcome === 'usage' ? 'usage' : 'internal',
        `MLView could not run "${args.filter((a) => !a.startsWith('-X')).slice(1).join(' ')}".`,
        tailLines(run.stderr) || tailLines(run.stdout),
        DEFAULT_ACTIONS
      );
    }
    return { stdout: run.stdout, stderr: run.stderr };
  }

  private async spawn(
    key: string,
    args: string[],
    request: {
      cwd: string;
      token?: vscode.CancellationToken;
      onProgress?: (frame: ProgressFrame) => void;
    }
  ): Promise<RunResult> {
    // THE trust gate. This is the only place in the extension that starts a child process, so
    // checking here is what actually keeps the `untrustedWorkspaces: "limited"` promise: no
    // interpreter probe, no `--version` handshake, no analyzer (CONTRACTS.md §6).
    if (!isTrusted()) {
      throw new CoreError('restricted', RESTRICTED_MESSAGE, RESTRICTED_DETAIL, [
        MANAGE_TRUST_ACTION,
        { id: 'showOutput', label: 'Show Output' }
      ]);
    }
    const state = await this.env.resolve();
    if (!state.ok) {
      throw new CoreError(
        'interpreter',
        state.failure.message,
        state.failure.detail,
        state.failure.actions
      );
    }
    const executable = state.interpreter.executable;
    // PACKAGING: when the precedence chain chose the BUNDLED core, the only thing that
    // makes `-m mlview` resolve is `<extension>/core` on PYTHONPATH — prepended, never
    // replacing, so a user's own PYTHONPATH still works for everything else.
    const bundledPath = state.interpreter.corePythonPath;

    // Single-flight per scope: a newer request for the same scope supersedes the running one.
    const previous = this.inFlight.get(key);
    if (previous) {
      this.log.debug(`superseding in-flight analysis for ${key}`);
      previous.kill();
      this.inFlight.delete(key);
    }

    this.log.info(`> "${executable}" ${args.map(quoteForLog).join(' ')}`);
    this.log.debug(`cwd: ${request.cwd}`);

    return await new Promise<RunResult>((resolve, reject) => {
      let cancelled = false;
      let settled = false;
      let stderrBuffer = '';
      let tokenSub: vscode.Disposable | undefined;
      // Supersede is synchronous but this child's terminal handler is not: by the time it runs,
      // the map entry for `key` may already belong to the run that REPLACED us. Only ever
      // unregister our own record, or `cancelAll()`, `cancel()` and single-flight all start
      // operating on a map that no longer knows about the process that is actually running.
      let entry: InFlight | undefined;
      const release = (): void => {
        if (entry && this.inFlight.get(key) === entry) {
          this.inFlight.delete(key);
        }
      };

      const child = execFile(
        executable,
        args,
        {
          cwd: request.cwd,
          shell: false,
          windowsHide: true,
          maxBuffer: MAX_BUFFER_BYTES,
          env: {
            ...process.env,
            PYTHONUTF8: '1',
            PYTHONIOENCODING: 'utf-8',
            // CACHE: only when the host named a directory. An unset variable
            // is not the same as an empty one - the core treats "" as absent,
            // but sending it at all would override a user's own setting.
            ...(this.cacheDir ? { MLVIEW_CACHE_DIR: this.cacheDir } : {}),
            ...(bundledPath
              ? {
                  PYTHONPATH: process.env['PYTHONPATH']
                    ? `${bundledPath}${path.delimiter}${process.env['PYTHONPATH']}`
                    : bundledPath,
                  // The bundled core is read-only in a real install and must never leave
                  // __pycache__ inside the VSIX's own directory.
                  PYTHONDONTWRITEBYTECODE: '1'
                }
              : {})
          }
        },
        (err, stdout, stderr) => {
          if (settled) {
            return;
          }
          settled = true;
          release();
          tokenSub?.dispose();
          const code = extractExitCode(err);
          // With a splitter running, `stderrBuffer` is the stderr MINUS the progress
          // frames, and it is the one an error tail should quote: a failure banner
          // reading `{"t":"progress","done":3,...}` names nothing a user can act on.
          const text = splitter ? stderrBuffer : String(stderr ?? '') || stderrBuffer;
          if (err && code === null && !cancelled) {
            const overflow =
              (err as { code?: unknown }).code === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER';
            reject(
              new CoreError(
                overflow ? 'internal' : 'spawn',
                overflow
                  ? `The graph exceeded the ${Math.round(
                      MAX_BUFFER_BYTES / (1024 * 1024)
                    )} MB transfer limit. Lower mlview.maxNodes or narrow the scope with mlview.exclude.`
                  : `Could not run the MLView analyzer with ${executable}.`,
                `${String(err)}\n${tailLines(text)}`,
                DEFAULT_ACTIONS
              )
            );
            return;
          }
          resolve({ code, stdout: String(stdout ?? ''), stderr: text, cancelled });
        }
      );

      const kill = (): void => {
        cancelled = true;
        if (child.exitCode === null && !child.killed) {
          child.kill('SIGTERM');
          const hard = setTimeout(() => {
            if (child.exitCode === null) {
              child.kill('SIGKILL');
            }
          }, KILL_GRACE_MS);
          hard.unref?.();
        }
      };

      // H3. Without `onProgress` this is byte-for-byte the old behaviour: every chunk
      // goes to the log and to the error tail. With it, the `{"t":"progress"` frames
      // are peeled off and everything else still does.
      const splitter = request.onProgress
        ? new ProgressSplitter(
            (frame) => {
              try {
                request.onProgress?.(frame);
              } catch (err) {
                this.log.warn(`progress listener threw: ${String(err)}`);
              }
            },
            (text) => {
              stderrBuffer += text;
              this.log.raw(text);
            }
          )
        : undefined;
      child.stderr?.setEncoding('utf8');
      child.stderr?.on('data', (chunk: string) => {
        if (splitter) {
          splitter.push(chunk);
          return;
        }
        stderrBuffer += chunk;
        this.log.raw(chunk);
      });
      child.stderr?.on('end', () => splitter?.flush());
      child.on('error', (err) => {
        if (settled) {
          return;
        }
        settled = true;
        release();
        tokenSub?.dispose();
        reject(
          new CoreError(
            'spawn',
            `Could not run the MLView analyzer with ${executable}.`,
            String(err),
            DEFAULT_ACTIONS
          )
        );
      });

      tokenSub = request.token?.onCancellationRequested(() => kill());
      entry = { child, kill };
      this.inFlight.set(key, entry);
    });
  }

  dispose(): void {
    this.saveDebounce.dispose();
    this.cancelAll();
  }
}

function extractExitCode(err: unknown): number | null {
  if (!err) {
    return 0;
  }
  const code = (err as { code?: unknown }).code;
  if (typeof code === 'number') {
    return code;
  }
  return null;
}

function quoteForLog(arg: string): string {
  return /\s/.test(arg) ? `"${arg}"` : arg;
}

/**
 * The single-flight key. `spec` is appended only when a caller asked for a §11.1 projection
 * (H10's language-model tools), so every existing key is byte-identical: without it a scoped
 * tool call and the diagram's unscoped run would supersede each other and the diagram would
 * silently lose its analysis to a question asked in chat.
 */
export function scopeKey(scope: AnalysisScope, path?: string, spec?: string): string {
  const base = scope === 'workspace' ? 'workspace' : `file:${path ?? ''}`;
  const trimmed = (spec ?? '').trim();
  return trimmed ? `${base}#${trimmed}` : base;
}

export function forwardSlashes(p: string): string {
  return p.replace(/\\/g, '/');
}
