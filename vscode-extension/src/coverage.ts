/**
 * "I could not check" is not "I checked and it is fine" (ROADMAP COVERAGE).
 *
 * The analyzer emits two coverage diagnostics — `single_file_analysis` when the analysed path
 * set is a strict subset of the discoverable Python under the root, and `untagged_dataflow`
 * when a FIT / SPLIT / LOADER / FORWARD call's key argument carried no tag, so the leakage
 * rules could not reason about it. Both mean the run was BLIND somewhere, and a host that shows
 * only the finding count turns that into a clean bill of health.
 *
 * This module is the host's single reader of those diagnostics. It is pure and takes the graph
 * document, so `test/coverage.test.js` asserts every rendering with no `vscode` object; the
 * three consumers are the status-bar tooltip, the diagram panel's description, and the
 * chat / language-model digests (which is what stops Copilot repeating the blind spot as a
 * clean file).
 *
 * Unknown-but-related diagnostic kinds are NOT invented here: the list below is closed, and a
 * kind this host does not know still reaches the viewer untouched inside `graph.diagnostics`.
 */

import type { GraphDiagnostic, MLGraph } from './graph';

/** The `Diagnostic.kind` values this host reads as coverage caveats. */
export const COVERAGE_DIAGNOSTIC_KINDS = ['single_file_analysis', 'untagged_dataflow'] as const;
export type CoverageKind = (typeof COVERAGE_DIAGNOSTIC_KINDS)[number];

/** How many rule codes a single caveat names before the list is elided. */
const MAX_CODES = 6;
/** How long one rendered caveat may get; the tooltip and the 4 KB digests both read these. */
const MAX_LINE = 220;

export interface CoverageNote {
  kind: CoverageKind;
  /** Sites this kind covers: the sum of each diagnostic's `count`, defaulting to one each. */
  count: number;
  /** The analyzer's own message for the first occurrence — the honest wording, kept verbatim. */
  message: string;
  /** Rule codes the analyzer says could not run, when it named any. */
  codes: string[];
}

function isCoverageKind(kind: string): kind is CoverageKind {
  return (COVERAGE_DIAGNOSTIC_KINDS as readonly string[]).includes(kind);
}

function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

function occurrences(d: GraphDiagnostic): number {
  const raw = typeof d.count === 'number' && Number.isFinite(d.count) ? Math.trunc(d.count) : 1;
  return raw > 0 ? raw : 1;
}

/**
 * The coverage caveats in this document, in the order `COVERAGE_DIAGNOSTIC_KINDS` lists them
 * so the tooltip and the digest never reorder between two runs. One note per kind: a workspace
 * with forty untagged fit sites is one caveat with `count: 40`, not forty lines.
 */
export function coverageNotes(graph: MLGraph | undefined): CoverageNote[] {
  const byKind = new Map<CoverageKind, CoverageNote>();
  for (const d of graph?.diagnostics ?? []) {
    const kind = typeof d.kind === 'string' ? d.kind : '';
    if (!isCoverageKind(kind)) {
      continue;
    }
    const existing = byKind.get(kind);
    const codes = Array.isArray(d.codes) ? d.codes.filter((c) => typeof c === 'string') : [];
    if (!existing) {
      byKind.set(kind, {
        kind,
        count: occurrences(d),
        message: typeof d.message === 'string' ? d.message : '',
        codes: codes.slice()
      });
      continue;
    }
    existing.count += occurrences(d);
    for (const code of codes) {
      if (!existing.codes.includes(code)) {
        existing.codes.push(code);
      }
    }
  }
  return COVERAGE_DIAGNOSTIC_KINDS.map((kind) => byKind.get(kind)).filter(
    (note): note is CoverageNote => note !== undefined
  );
}

/** The fallback wording when the analyzer sent the kind with no message of its own. */
function defaultMessage(kind: CoverageKind): string {
  return kind === 'single_file_analysis'
    ? 'Only part of the project was analyzed, so the cross-file rules could not run.'
    : 'A key argument could not be traced, so the leakage rules could not check it.';
}

/** One line per caveat: the analyzer's message, the extra sites, and the rules that stayed silent. */
export function coverageLines(notes: CoverageNote[]): string[] {
  return notes.map((note) => {
    const head = note.message.trim() || defaultMessage(note.kind);
    const more = note.count > 1 ? ` (${note.count} sites)` : '';
    const shown = note.codes.slice(0, MAX_CODES);
    const rest = note.codes.length - shown.length;
    const codes = shown.length
      ? ` — rules that could not run: ${shown.join(', ')}${rest > 0 ? ` +${rest} more` : ''}`
      : '';
    return truncate(`${head}${more}${codes}`, MAX_LINE);
  });
}

/**
 * The short phrase the panel description and the status-bar tooltip head with. Deliberately
 * says "incomplete", never "clean": the whole point is that the count below it is a floor.
 */
export function coverageChip(notes: CoverageNote[]): string | undefined {
  if (notes.length === 0) {
    return undefined;
  }
  const sites = notes.reduce((sum, note) => sum + note.count, 0);
  return `coverage: incomplete (${sites} ${sites === 1 ? 'blind spot' : 'blind spots'})`;
}

/** `coverageLines(coverageNotes(graph))`, the shape every consumer actually wants. */
export function coverageFor(graph: MLGraph | undefined): string[] {
  return coverageLines(coverageNotes(graph));
}
