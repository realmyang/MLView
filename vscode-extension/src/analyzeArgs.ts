/**
 * The analyzer command line, as data.
 *
 * Split out of `coreClient.ts` when H10 and CFG-ONE pushed that file past the repo's ~600-line
 * budget (`test/hygiene.test.js`). Nothing here touches a process, a setting or `vscode`: it is
 * the argv, the §3 exit-code table and the stderr tail, so `test/coreClient.test.js` can assert
 * the exact command that would be run without running anything.
 *
 *   python -X utf8 -m mlview analyze <paths...> --json - --max-files N --max-nodes N
 *          [--exclude G]... [--config F] [--baseline F] [--include-notebooks]
 *          [--scope SPEC [--depth N]] [--progress-json]
 */

export interface AnalyzeArgOptions {
  paths: string[];
  maxFiles: number;
  maxNodes: number;
  exclude: string[];
  /**
   * NB: read `.ipynb` files instead of counting them as skipped. Omitted (the default) the
   * argv is byte-identical to the one this builder produced before notebooks existed, which
   * is what makes `mlview.includeNotebooks: false` a true no-op rather than a fast path.
   */
  includeNotebooks?: boolean;
  /** When set, the graph is written to this file as a self-contained HTML report instead. */
  htmlOut?: string;
  /**
   * A CONTRACTS.md §11.1 diagram selector (`unit:train.validate`, `concern:evaluation`, ...).
   * Named `scopeSpec`, not `scope`, because `AnalyzeRequest.scope` is already the
   * `'workspace' | 'file'` ANALYSIS scope - the same collision §11.7 avoided by naming the
   * message field `spec`.
   */
  scopeSpec?: string;
  /** Boundary hops, 0..2 (§11.5). Omitted means the per-kind default. */
  depth?: number;
  /**
   * CFG-ONE: the `.mlview.toml` (or the `pyproject.toml` carrying `[tool.mlview]`) this
   * folder is configured by, resolved by `mlviewConfig.resolveConfig`. Omitted when there is
   * no such file, which is what makes an unconfigured project's argv byte-identical to the
   * argv this builder produced before configuration existed.
   */
  configPath?: string;
  /**
   * CI-ADOPT: `mlview.baselinePath`, and ONLY when the user set it and the file is there.
   * A baseline decides which findings are counted, so it is never auto-discovered.
   */
  baselinePath?: string;
  /**
   * H3: ask the analyzer for `{"t":"progress",...}` frames on **stderr**. Passed only
   * when a panel is live, so the headless and export paths emit the bytes they emit
   * today — the flag is the difference between a 5.64 s indeterminate spinner and a
   * bar that names the file being parsed.
   */
  progress?: boolean;
}

/**
 * Pure argv builder. Order is frozen: `analyze`, the paths, `--json -`, the caps, the excludes,
 * the configuration, then the optional projection flags. `-X utf8` is prepended by the caller
 * so it is impossible to forget. An unscoped, unconfigured call produces exactly the argv it
 * produced before scopes and configuration existed.
 */
export function buildAnalyzeArgs(opts: AnalyzeArgOptions): string[] {
  const args = ['-X', 'utf8', '-m', 'mlview', 'analyze', ...opts.paths];
  if (opts.htmlOut) {
    args.push('--html', opts.htmlOut, '--format', 'summary');
  } else {
    args.push('--json', '-');
  }
  args.push('--max-files', String(opts.maxFiles), '--max-nodes', String(opts.maxNodes));
  for (const glob of opts.exclude) {
    if (glob.trim().length > 0) {
      args.push('--exclude', glob.trim());
    }
  }
  // CFG-ONE: a discovery/suppression flag, so it sits with the excludes it can extend and
  // ahead of every projection flag. Absent when no configuration file was found.
  if (opts.configPath) {
    args.push('--config', opts.configPath);
  }
  if (opts.baselinePath) {
    args.push('--baseline', opts.baselinePath);
  }
  // NB: an INGEST flag, so it sits with the excludes and ahead of the projection flags.
  if (opts.includeNotebooks) {
    args.push('--include-notebooks');
  }
  if (opts.scopeSpec && opts.scopeSpec.trim().length > 0) {
    args.push('--scope', opts.scopeSpec.trim());
    if (typeof opts.depth === 'number' && Number.isInteger(opts.depth)) {
      args.push('--depth', String(opts.depth));
    }
  }
  if (opts.progress) {
    args.push('--progress-json');
  }
  return args;
}

export type ExitClass = 'ok' | 'nothing-analyzable' | 'usage' | 'internal' | 'fail-on' | 'unknown';

/** CONTRACTS.md §3 exit codes. `2` is never produced here because `--fail-on` is never passed. */
export function classifyExit(code: number | null): ExitClass {
  switch (code) {
    case 0:
      return 'ok';
    case 1:
      return 'usage';
    case 2:
      return 'fail-on';
    case 3:
      return 'internal';
    case 4:
      return 'nothing-analyzable';
    default:
      return 'unknown';
  }
}

export function tailLines(text: string, count = 8): string {
  return text
    .replace(/\r\n/g, '\n')
    .split('\n')
    .filter((line) => line.trim().length > 0)
    .slice(-count)
    .join('\n');
}
