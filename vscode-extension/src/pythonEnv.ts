/**
 * Interpreter resolution — the highest-probability silent failure on Windows.
 *
 * The chain (ARCHITECTURE.md §6.4), in order, each candidate validated as Python >= 3.10 and
 * then handshaken with `-X utf8 -m mlview --version --json`:
 *
 *   1. the `mlview.pythonPath` setting
 *   2. the ms-python.python extension API (getActiveEnvironmentPath -> resolveEnvironment)
 *   3. the `python.defaultInterpreterPath` setting
 *   4. a PATH probe: `python`, `py -3`, `python3`
 *
 * The result is memoized and recomputed when the interpreter or the settings change.
 * `buildCandidates` and `pickInterpreter` are pure so the order is testable with stubbed probes.
 */

import { execFile } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import type { Logger } from './log';
import { readSettings } from './settings';
import { schemaMajor, SCHEMA_VERSION } from './graph';

export type InterpreterSource = 'setting' | 'ms-python' | 'defaultInterpreterPath' | 'path';

export const MIN_PYTHON: readonly [number, number] = [3, 10];

export interface Candidate {
  source: InterpreterSource;
  /** Executable to spawn. Never passed through a shell. */
  command: string;
  /** Leading arguments (e.g. `['-3']` for the `py` launcher). */
  args: string[];
  label: string;
}

export interface CoreHandshake {
  version: string;
  schemaVersion?: string;
}

export type ProbeOutcome =
  | { kind: 'missing'; detail?: string }
  | { kind: 'too-old'; version: [number, number]; executable?: string }
  | { kind: 'ok'; executable: string; version: [number, number]; core?: CoreHandshake };

export interface ResolvedInterpreter {
  /** Absolute path to the interpreter (`sys.executable`), forward slashes preserved as given. */
  executable: string;
  /** Leading args needed to reach that interpreter; empty once resolved to `sys.executable`. */
  args: string[];
  source: InterpreterSource;
  version: [number, number];
  hasCore: boolean;
  core?: CoreHandshake;
}

export interface Attempt {
  candidate: Candidate;
  outcome: ProbeOutcome;
}

export interface PickOutcome {
  interpreter?: ResolvedInterpreter;
  attempts: Attempt[];
}

export interface CandidateInput {
  settingPath?: string;
  msPythonPath?: string;
  defaultInterpreterPath?: string;
}

/** Build the ordered candidate list. Empty/blank inputs are skipped, duplicates collapse. */
export function buildCandidates(input: CandidateInput): Candidate[] {
  const out: Candidate[] = [];
  const seen = new Set<string>();
  const push = (source: InterpreterSource, command: string, args: string[], label: string): void => {
    const trimmed = command.trim();
    if (trimmed.length === 0) {
      return;
    }
    const key = `${trimmed}\u0000${args.join('\u0000')}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    out.push({ source, command: trimmed, args, label });
  };
  push('setting', input.settingPath ?? '', [], 'mlview.pythonPath');
  push('ms-python', input.msPythonPath ?? '', [], 'ms-python.python active environment');
  push('defaultInterpreterPath', input.defaultInterpreterPath ?? '', [], 'python.defaultInterpreterPath');
  push('path', 'python', [], 'PATH: python');
  push('path', 'py', ['-3'], 'PATH: py -3');
  push('path', 'python3', [], 'PATH: python3');
  return out;
}

/**
 * Walk the candidates in order and return the first usable interpreter.
 *
 * An interpreter that is new enough but has no `mlview` module is remembered as a fallback: it
 * is only returned when nothing better exists, and it drives the "Install MLView core" prompt.
 */
export async function pickInterpreter(
  candidates: Candidate[],
  probe: (candidate: Candidate) => Promise<ProbeOutcome>
): Promise<PickOutcome> {
  const attempts: Attempt[] = [];
  let fallback: ResolvedInterpreter | undefined;
  for (const candidate of candidates) {
    const outcome = await probe(candidate);
    attempts.push({ candidate, outcome });
    if (outcome.kind !== 'ok') {
      continue;
    }
    const resolved: ResolvedInterpreter = {
      executable: outcome.executable,
      args: [],
      source: candidate.source,
      version: outcome.version,
      hasCore: outcome.core !== undefined,
      ...(outcome.core ? { core: outcome.core } : {})
    };
    if (resolved.hasCore) {
      return { interpreter: resolved, attempts };
    }
    fallback = fallback ?? resolved;
  }
  return { ...(fallback ? { interpreter: fallback } : {}), attempts };
}

export function meetsMinimum(version: [number, number]): boolean {
  const [major, minor] = version;
  const [minMajor, minMinor] = MIN_PYTHON;
  return major > minMajor || (major === minMajor && minor >= minMinor);
}

/** Parse the JSON emitted by `python -m mlview --version --json`, defensively. */
export function parseHandshake(stdout: string): CoreHandshake | undefined {
  const text = stdout.trim();
  if (text.length === 0) {
    return undefined;
  }
  try {
    const parsed: unknown = JSON.parse(text);
    if (typeof parsed === 'object' && parsed !== null) {
      const obj = parsed as Record<string, unknown>;
      const version =
        typeof obj['version'] === 'string'
          ? obj['version']
          : typeof obj['mlview'] === 'string'
            ? (obj['mlview'] as string)
            : 'unknown';
      const schema =
        typeof obj['schemaVersion'] === 'string'
          ? (obj['schemaVersion'] as string)
          : typeof obj['schema_version'] === 'string'
            ? (obj['schema_version'] as string)
            : undefined;
      return { version, ...(schema ? { schemaVersion: schema } : {}) };
    }
  } catch {
    /* fall through to the plain-text form */
  }
  const match = /([0-9]+\.[0-9]+\.[0-9]+[^\s]*)/.exec(text);
  return { version: match?.[1] ?? 'unknown' };
}

export function schemaMismatchMessage(coreSchema: string): string {
  return (
    `MLView core speaks graph schema ${coreSchema}, this extension speaks ${SCHEMA_VERSION}. ` +
    `Update whichever is older (major versions must match).`
  );
}

export function isSchemaMismatch(core: CoreHandshake | undefined): boolean {
  return (
    core?.schemaVersion !== undefined &&
    schemaMajor(core.schemaVersion) !== schemaMajor(SCHEMA_VERSION)
  );
}

const VERSION_SNIPPET =
  'import sys,json;print(json.dumps([sys.version_info[0],sys.version_info[1],sys.executable]))';

function run(
  command: string,
  args: string[],
  timeoutMs: number
): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    execFile(
      command,
      args,
      {
        shell: false,
        timeout: timeoutMs,
        windowsHide: true,
        maxBuffer: 4 * 1024 * 1024,
        env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' }
      },
      (err, stdout, stderr) => {
        const code =
          err && typeof (err as NodeJS.ErrnoException & { code?: number }).code === 'number'
            ? ((err as unknown as { code: number }).code ?? 1)
            : err
              ? 1
              : 0;
        resolve({ code, stdout: String(stdout ?? ''), stderr: String(stderr ?? '') });
      }
    );
  });
}

/** The real probe: version check, then the `-m mlview --version --json` handshake. */
export async function probeCandidate(candidate: Candidate, log?: Logger): Promise<ProbeOutcome> {
  const versionArgs = [...candidate.args, '-X', 'utf8', '-c', VERSION_SNIPPET];
  log?.debug(`probing interpreter: ${candidate.command} ${versionArgs.join(' ')}`);
  const probe = await run(candidate.command, versionArgs, 10_000);
  if (probe.code !== 0) {
    return { kind: 'missing', detail: probe.stderr.trim().split('\n').slice(-1)[0] ?? '' };
  }
  let major = 0;
  let minor = 0;
  let executable = candidate.command;
  try {
    const parsed = JSON.parse(probe.stdout.trim()) as [number, number, string];
    major = Number(parsed[0]);
    minor = Number(parsed[1]);
    executable = String(parsed[2] ?? candidate.command);
  } catch {
    return { kind: 'missing', detail: 'unreadable version output' };
  }
  if (!Number.isFinite(major) || !Number.isFinite(minor)) {
    return { kind: 'missing', detail: 'unreadable version output' };
  }
  const version: [number, number] = [major, minor];
  if (!meetsMinimum(version)) {
    return { kind: 'too-old', version, executable };
  }
  const handshake = await run(executable, ['-X', 'utf8', '-m', 'mlview', '--version', '--json'], 20_000);
  if (handshake.code !== 0) {
    log?.debug(`no mlview core in ${executable}: ${handshake.stderr.trim().slice(0, 200)}`);
    return { kind: 'ok', executable, version };
  }
  const core = parseHandshake(handshake.stdout);
  return { kind: 'ok', executable, version, ...(core ? { core } : {}) };
}

interface PythonExtensionApiLike {
  environments?: {
    getActiveEnvironmentPath?: (resource?: vscode.Uri) => { path?: string; id?: string } | undefined;
    resolveEnvironment?: (
      env: unknown
    ) => Thenable<{ executable?: { uri?: vscode.Uri; sysPrefix?: string } } | undefined>;
    onDidChangeActiveEnvironmentPath?: (listener: () => void) => vscode.Disposable;
  };
}

/** Ask ms-python.python for the active interpreter. Never throws; absence is normal. */
export async function queryMsPython(
  log?: Logger
): Promise<{ executable?: string; onChange?: (listener: () => void) => vscode.Disposable }> {
  try {
    const ext = vscode.extensions.getExtension<PythonExtensionApiLike>('ms-python.python');
    if (!ext) {
      return {};
    }
    const api = ext.isActive ? ext.exports : await ext.activate();
    const environments = api?.environments;
    if (!environments?.getActiveEnvironmentPath) {
      return {};
    }
    const active = environments.getActiveEnvironmentPath();
    let executable: string | undefined;
    if (active && environments.resolveEnvironment) {
      // getActiveEnvironmentPath may return a FOLDER, so resolving is required.
      const resolved = await environments.resolveEnvironment(active);
      executable = resolved?.executable?.uri?.fsPath;
    }
    if (!executable && active?.path) {
      executable = active.path;
    }
    const onChange = environments.onDidChangeActiveEnvironmentPath
      ? (listener: () => void): vscode.Disposable =>
          environments.onDidChangeActiveEnvironmentPath!(listener)
      : undefined;
    return { ...(executable ? { executable } : {}), ...(onChange ? { onChange } : {}) };
  } catch (err) {
    log?.warn(`ms-python.python interpreter query failed: ${String(err)}`);
    return {};
  }
}

export interface InterpreterFailure {
  message: string;
  detail: string;
  actions: { id: string; label: string }[];
}

export type InterpreterState =
  | { ok: true; interpreter: ResolvedInterpreter; warning?: InterpreterFailure }
  | { ok: false; failure: InterpreterFailure };

function describeAttempts(attempts: Attempt[]): string {
  return attempts
    .map(({ candidate, outcome }) => {
      const where = `${candidate.label} (${candidate.command}${
        candidate.args.length ? ' ' + candidate.args.join(' ') : ''
      })`;
      switch (outcome.kind) {
        case 'ok':
          return `  OK   ${where} -> ${outcome.executable} (Python ${outcome.version.join('.')}${
            outcome.core ? `, mlview ${outcome.core.version}` : ', mlview NOT installed'
          })`;
        case 'too-old':
          return `  SKIP ${where} -> Python ${outcome.version.join('.')} < ${MIN_PYTHON.join('.')}`;
        default:
          return `  SKIP ${where} -> not found${outcome.detail ? `: ${outcome.detail}` : ''}`;
      }
    })
    .join('\n');
}

/**
 * The stateful, VS Code-facing wrapper: memoizes the chain, watches for interpreter and
 * settings changes, and owns the remediation quick pick.
 */
export class PythonEnvironment implements vscode.Disposable {
  private cached: Promise<InterpreterState> | undefined;
  private readonly disposables: vscode.Disposable[] = [];
  private readonly changeEmitter = new vscode.EventEmitter<void>();

  readonly onDidChange = this.changeEmitter.event;

  constructor(
    private readonly ctx: vscode.ExtensionContext,
    private readonly log: Logger
  ) {
    this.disposables.push(
      vscode.workspace.onDidChangeConfiguration((e) => {
        if (e.affectsConfiguration('mlview.pythonPath') || e.affectsConfiguration('python.defaultInterpreterPath')) {
          this.invalidate();
        }
      })
    );
    void this.subscribeToPythonExtension();
  }

  private async subscribeToPythonExtension(): Promise<void> {
    const { onChange } = await queryMsPython(this.log);
    if (onChange) {
      try {
        this.disposables.push(
          onChange(() => {
            this.log.info('python interpreter changed - re-running the MLView interpreter chain');
            this.invalidate();
          })
        );
      } catch (err) {
        this.log.warn(`could not subscribe to interpreter changes: ${String(err)}`);
      }
    }
  }

  invalidate(): void {
    this.cached = undefined;
    this.changeEmitter.fire();
  }

  resolve(): Promise<InterpreterState> {
    if (!this.cached) {
      this.cached = this.compute();
    }
    return this.cached;
  }

  private async compute(): Promise<InterpreterState> {
    const settings = readSettings();
    const pythonCfg = vscode.workspace.getConfiguration('python');
    const msPython = await queryMsPython(this.log);
    const candidates = buildCandidates({
      settingPath: settings.pythonPath,
      ...(msPython.executable ? { msPythonPath: msPython.executable } : {}),
      defaultInterpreterPath: pythonCfg.get<string>('defaultInterpreterPath') ?? ''
    });
    const { interpreter, attempts } = await pickInterpreter(candidates, (c) =>
      probeCandidate(c, this.log)
    );
    this.log.info(`interpreter chain:\n${describeAttempts(attempts)}`);

    if (!interpreter) {
      return {
        ok: false,
        failure: {
          message: `No Python ${MIN_PYTHON.join('.')}+ interpreter found.`,
          detail: describeAttempts(attempts),
          actions: [
            { id: 'selectInterpreter', label: 'Select Interpreter' },
            { id: 'showOutput', label: 'Show Output' }
          ]
        }
      };
    }
    if (!interpreter.hasCore) {
      return {
        ok: false,
        failure: {
          message: `MLView core is not installed in ${interpreter.executable}.`,
          detail: describeAttempts(attempts),
          actions: [
            { id: 'installCore', label: 'Install MLView core' },
            { id: 'selectInterpreter', label: 'Select Interpreter' },
            { id: 'showOutput', label: 'Show Output' }
          ]
        }
      };
    }
    if (isSchemaMismatch(interpreter.core)) {
      return {
        ok: false,
        failure: {
          message: schemaMismatchMessage(interpreter.core?.schemaVersion ?? 'unknown'),
          detail: describeAttempts(attempts),
          actions: [
            { id: 'installCore', label: 'Install MLView core' },
            { id: 'showOutput', label: 'Show Output' }
          ]
        }
      };
    }
    this.log.info(
      `using ${interpreter.executable} (Python ${interpreter.version.join('.')}, mlview ${
        interpreter.core?.version ?? 'unknown'
      }, via ${interpreter.source})`
    );
    return { ok: true, interpreter };
  }

  /** `<repo>/analyzer` when this extension is running from the MLView repo checkout. */
  analyzerSourceDir(): string | undefined {
    const repoRoot = path.dirname(this.ctx.extensionPath);
    const analyzer = path.join(repoRoot, 'analyzer');
    return fs.existsSync(path.join(analyzer, 'pyproject.toml')) ? analyzer : undefined;
  }

  /** Remediation quick pick, shared by the notification and the webview error banner. */
  async offerRemediation(failure: InterpreterFailure): Promise<void> {
    const picked = await vscode.window.showQuickPick(
      failure.actions.map((a) => ({ label: a.label, id: a.id })),
      { title: 'MLView', placeHolder: failure.message }
    );
    if (picked) {
      await this.runAction(picked.id);
    }
  }

  async runAction(id: string): Promise<void> {
    switch (id) {
      case 'installCore':
        await this.installCore();
        return;
      case 'selectInterpreter':
        await this.selectInterpreter();
        return;
      case 'showOutput':
        this.log.show(false);
        return;
      default:
        this.log.warn(`unknown remediation action: ${id}`);
    }
  }

  async selectInterpreter(): Promise<void> {
    const hasPythonExtension = !!vscode.extensions.getExtension('ms-python.python');
    if (hasPythonExtension) {
      try {
        await vscode.commands.executeCommand('python.setInterpreter');
        this.invalidate();
        return;
      } catch (err) {
        this.log.warn(`python.setInterpreter failed: ${String(err)}`);
      }
    }
    await vscode.commands.executeCommand('workbench.action.openSettings', 'mlview.pythonPath');
  }

  async installCore(): Promise<void> {
    const state = await this.resolve();
    const executable = state.ok ? state.interpreter.executable : 'python';
    const analyzer = this.analyzerSourceDir();
    if (!analyzer) {
      const message =
        'MLView core (the `mlview` Python package) is not installed and the analyzer sources ' +
        'were not found next to this extension. Install it with: pip install -e <mlview-repo>/analyzer';
      this.log.warn(message);
      await vscode.window.showWarningMessage(message, 'Show Output').then((choice) => {
        if (choice) {
          this.log.show(false);
        }
      });
      return;
    }
    const terminal = vscode.window.createTerminal({ name: 'MLView: install core', cwd: analyzer });
    terminal.show(true);
    // `&` is the PowerShell call operator and a syntax error in cmd.exe / bash, so pick the
    // form that matches the user's default shell rather than assuming PowerShell.
    const shell = (vscode.env.shell ?? '').toLowerCase();
    const isPowerShell = shell.includes('powershell') || shell.includes('pwsh');
    const command = `${isPowerShell ? '& ' : ''}"${executable}" -m pip install -e "${analyzer}"`;
    terminal.sendText(command, true);
    this.log.info(`install started in a terminal: ${command}`);
    void vscode.window
      .showInformationMessage(
        'Installing MLView core in a terminal. Run "MLView: Re-analyze" when it finishes.',
        'Re-analyze'
      )
      .then((choice) => {
        if (choice === 'Re-analyze') {
          this.invalidate();
          void vscode.commands.executeCommand('mlview.refresh');
        }
      });
  }

  dispose(): void {
    this.changeEmitter.dispose();
    for (const d of this.disposables) {
      d.dispose();
    }
  }
}
