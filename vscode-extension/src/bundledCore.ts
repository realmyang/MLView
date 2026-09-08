/**
 * PACKAGING — the analyzer that ships INSIDE the VSIX, and the rule that decides
 * whether it or an installed `mlview` runs (docs/contracts/11.25-packaging.md).
 *
 * Two audits wanted opposite things: "bundle the analyzer so no pip is needed"
 * and "pip install from PyPI". Shipping both as first-class produces two support
 * stories, so this is a precedence chain instead of a choice:
 *
 *   1. an INSTALLED core wins when it is present, its schema major matches this
 *      extension's, and its version is >= the bundled one;
 *   2. otherwise the BUNDLED core at `<extension>/core`, run by putting that
 *      directory on `PYTHONPATH` — exactly how `.mcp.json` runs the plugin's
 *      `vendor/` copy;
 *   3. and only when there is neither does the "Install MLView core" prompt appear.
 *
 * Every function here is pure and filesystem-injectable, so `test/packaging.test.js`
 * decides the chain without an extension host, a Python or a marketplace.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { schemaMajor, SCHEMA_VERSION } from './graph';
import type { CoreHandshake } from './pythonEnv';

/** The core `tools/sync-core.py` copied into `vscode-extension/core`. */
export interface BundledCore {
  /**
   * The directory that goes on `PYTHONPATH` — `<extension>/core`, the PARENT of the
   * `mlview` package, because that is what `import mlview` needs to see.
   */
  pythonPath: string;
  version: string;
  schemaVersion: string;
}

export interface BundledCoreIo {
  exists?: (p: string) => boolean;
  read?: (p: string) => string;
}

const VERSION_RE = /^__version__\s*=\s*['"]([^'"]+)['"]/m;
const SCHEMA_RE = /^SCHEMA_VERSION\s*=\s*['"]([^'"]+)['"]/m;

/**
 * Read `<extension>/core/mlview/version.py` — 30 bytes of regex rather than a
 * Python spawn, because this runs on the interpreter-resolution path and a
 * bundled core that cannot be read must degrade to "absent", never to a stall.
 */
export function readBundledCore(extensionPath: string, io: BundledCoreIo = {}): BundledCore | undefined {
  const exists = io.exists ?? fs.existsSync;
  const read = io.read ?? ((p: string): string => fs.readFileSync(p, 'utf8'));
  const pythonPath = path.join(extensionPath, 'core');
  const versionFile = path.join(pythonPath, 'mlview', 'version.py');
  try {
    if (!exists(versionFile)) {
      return undefined;
    }
    const text = read(versionFile);
    const version = VERSION_RE.exec(text)?.[1];
    const schema = SCHEMA_RE.exec(text)?.[1];
    if (!version || !schema) {
      return undefined;
    }
    return { pythonPath, version, schemaVersion: schema };
  } catch {
    return undefined;
  }
}

/**
 * Compare two dotted version strings numerically: -1, 0 or 1.
 *
 * `0.10.0` is newer than `0.9.0` (a string compare says the opposite), a missing
 * component counts as 0, and any trailing pre-release marker (`0.2.0rc1`) sorts
 * BELOW the same release, which is what keeps a release candidate installed for
 * testing from silently outranking the bundled stable core.
 */
export function compareVersions(a: string, b: string): number {
  const parts = (v: string): { nums: number[]; pre: boolean } => {
    const trimmed = String(v ?? '').trim();
    const match = /^v?(\d+(?:\.\d+)*)(.*)$/.exec(trimmed);
    if (!match) {
      return { nums: [-1], pre: false };
    }
    return {
      nums: match[1]!.split('.').map((n) => Number(n)),
      pre: match[2]!.trim().length > 0
    };
  };
  const left = parts(a);
  const right = parts(b);
  const width = Math.max(left.nums.length, right.nums.length);
  for (let i = 0; i < width; i += 1) {
    const l = left.nums[i] ?? 0;
    const r = right.nums[i] ?? 0;
    if (l !== r) {
      return l < r ? -1 : 1;
    }
  }
  if (left.pre === right.pre) {
    return 0;
  }
  return left.pre ? -1 : 1;
}

export type CoreSource = 'installed' | 'bundled';

export type CoreChoice =
  | {
      kind: 'installed';
      source: 'installed';
      core: CoreHandshake;
      /** Why the bundled copy lost, when there was one. */
      reason: 'no-bundled-core' | 'installed-is-current';
    }
  | {
      kind: 'bundled';
      source: 'bundled';
      bundled: BundledCore;
      reason: 'no-installed-core' | 'installed-schema-mismatch' | 'installed-is-older';
      /** The installed core that lost, so the log and the tooltip can name it. */
      installed?: CoreHandshake;
    }
  | { kind: 'none' };

/**
 * The precedence chain, as one pure decision.
 *
 * `extensionSchema` defaults to this extension's `SCHEMA_VERSION`: a core whose
 * schema MAJOR differs speaks a document this build cannot read, and the existing
 * handshake (`isSchemaMismatch`) already treats that as fatal. With a bundled core
 * present it stops being fatal — we simply use the copy we shipped, and say so.
 */
export function chooseCore(
  installed: CoreHandshake | undefined,
  bundled: BundledCore | undefined,
  extensionSchema: string = SCHEMA_VERSION
): CoreChoice {
  if (!installed && !bundled) {
    return { kind: 'none' };
  }
  if (!bundled) {
    return { kind: 'installed', source: 'installed', core: installed!, reason: 'no-bundled-core' };
  }
  if (!installed) {
    return { kind: 'bundled', source: 'bundled', bundled, reason: 'no-installed-core' };
  }
  const installedSchema = installed.schemaVersion;
  if (installedSchema !== undefined && schemaMajor(installedSchema) !== schemaMajor(extensionSchema)) {
    return {
      kind: 'bundled',
      source: 'bundled',
      bundled,
      reason: 'installed-schema-mismatch',
      installed
    };
  }
  if (compareVersions(installed.version, bundled.version) < 0) {
    return { kind: 'bundled', source: 'bundled', bundled, reason: 'installed-is-older', installed };
  }
  return { kind: 'installed', source: 'installed', core: installed, reason: 'installed-is-current' };
}

/**
 * One line for the status-bar tooltip and the output channel. The whole point of
 * a precedence chain is that the user can find out which end of it they are on
 * without reading the source (PACKAGING acceptance).
 */
export function coreLabel(choice: CoreChoice, executable?: string): string {
  const where = executable ? ` · ${executable}` : '';
  switch (choice.kind) {
    case 'installed':
      return `core: mlview ${choice.core.version} installed in the interpreter${where}`;
    case 'bundled': {
      const because =
        choice.reason === 'no-installed-core'
          ? 'no mlview installed in the interpreter'
          : choice.reason === 'installed-is-older'
            ? `the installed mlview ${choice.installed?.version ?? '?'} is older`
            : `the installed mlview speaks graph schema ${
                choice.installed?.schemaVersion ?? '?'
              }, this extension speaks ${SCHEMA_VERSION}`;
      return `core: mlview ${choice.bundled.version} bundled with the extension (${because})${where}`;
    }
    default:
      return 'core: not found';
  }
}
