/**
 * The chip row's DATA MODEL: what the row says about a run, before any of it is
 * a DOM node (HOSTS-UX-CHIPWALL).
 *
 * Collecting descriptors rather than appending elements is what lets the row
 * fold identical texts and cap its own length: both are decisions about the
 * WHOLE row, and the code this was lifted out of had made them one chip at a
 * time. Nothing here touches the document — `Chrome.paintChips` does — so the
 * three steps below are testable as what they are: pure functions of the state.
 */

import { COVERAGE_KINDS, SPECIALLY_RENDERED, coverageChipText, notebooksAnalyzedText } from './chromenotes.js';
import { NOTEBOOK_ANALYZED } from '../notebook.js';
import type { ChromeState } from './chrome.js';
import type { MLGraph } from '../types.js';

/**
 * How many chips the diagnostic row draws before the rest fold behind one
 * "N more" chip (HOSTS-UX-CHIPWALL).
 *
 * Eight is what fits two lines of the row at the widths this product is used
 * at, which is the point: the row must never be able to outgrow the picture it
 * annotates. It is a DISCLOSURE and not a deletion — the "N more" chip draws
 * every one of them, each message stays on a `title`, and the status bar keeps
 * counting all of them as "N notes".
 */
export const MAX_CHIPS = 8;

/**
 * One chip, before it is a DOM node.
 *
 * Collecting descriptors rather than appending elements is what lets the row
 * fold identical texts and cap its own length: both are decisions about the
 * WHOLE row, and the old code had made them one chip at a time.
 */
export interface ChipSpec {
  /** The chip's visible text. Identical texts fold into one chip with a count. */
  text: string;
  /** Extra classes after `mlv-chip`. */
  cls: string;
  /** The uppercase heading drawn before the first chip of a run. */
  label: string;
  /** The chip's own `title`, when it has one. */
  title: string;
  attrs: [string, string][];
  /** How many identical entries this chip stands for; 1 draws no count. */
  count: number;
  /** The DISTINCT messages behind a folded chip, for its tooltip. */
  detail: string[];
}

/* ── the chip row's three steps (HOSTS-UX-CHIPWALL) ────────────────────── */

/** One descriptor. `detail` never repeats the text it would sit under. */
function chipSpec(text: string, opts: Partial<ChipSpec> = {}): ChipSpec {
  const title = opts.title || '';
  return {
    text,
    cls: opts.cls || '',
    label: opts.label || '',
    title,
    attrs: opts.attrs || [],
    count: 1,
    detail: title && title !== text ? [title] : [],
  };
}

/**
 * STEP 1 — collect, in the order the row has always drawn them.
 *
 * Every branch is the one that was there before; the only change is that each
 * produces a descriptor instead of appending an element. A diagnostic kind this
 * renderer has never heard of still says what it says (invariant 1.1/6).
 */
export function collectChips(s: ChromeState): ChipSpec[] {
  const g = s.graph as MLGraph;
  const out: ChipSpec[] = [];
  for (const stage of (g.stages || []).filter((st) => !st.present)) {
    out.push(chipSpec(stage.label || stage.id, { label: 'not detected' }));
  }
  for (const stage of s.outOfScopeStages) {
    out.push(
      chipSpec(stage.label || stage.id, {
        label: 'not in this scope',
        cls: 'mlv-chip--outscope',
        attrs: [['data-out-of-scope', stage.id]],
      }),
    );
  }
  for (const d of g.diagnostics || []) {
    if (d.kind === 'notebook_skipped') {
      out.push(chipSpec((d.count || 0) + ' notebooks not analyzed'));
    } else if (d.kind === NOTEBOOK_ANALYZED) {
      // NB. Without `--include-notebooks` this never appears, because the
      // diagnostic is never emitted.
      //
      // VW-06: ONE diagnostic per notebook, and its `count` is that notebook's
      // code cells — so the chip is one notebook (the hook keeps its name) and
      // the cell count is its own attribute.
      out.push(
        chipSpec(notebooksAnalyzedText(d), {
          title: d.message,
          attrs: [
            ['data-notebooks-analyzed', '1'],
            ['data-notebook-cells', String(d.count || 0)],
          ],
        }),
      );
    } else if (d.kind === 'framework_suppressed') {
      out.push(chipSpec(d.message + (d.codes && d.codes.length ? ' (' + d.codes.join(', ') + ')' : '')));
    } else if (d.kind === 'config_warning' || d.kind === 'config_unresolved') {
      // VW-08. These are SENTENCES, not chips — CI-ADOPT's baseline and
      // --changed-paths warnings carry absolute paths and an instruction, and
      // the `--changed-paths` one measured 1779 px wide at a 1600 px window,
      // running 191 px off the page with no scrollbar and no `title`, so the
      // instruction it exists to give ("Pass the diff itself, or
      // --changed-since <rev>") was the half that was cut. The full text is
      // now on the chip's tooltip, and `.mlv-chiprow .mlv-chip` wraps.
      //
      // HOSTS-UX-CHIPWALL: and because they are sentences, a repository that
      // could not open eight config files drew the SAME sentence eight times.
      out.push(chipSpec(d.message, { title: d.message, attrs: [['data-config-note', d.kind]] }));
    } else if (COVERAGE_KINDS.indexOf(d.kind) >= 0) {
      // COVERAGE: a chip that says the analysis was BLIND here, distinct from
      // the "not detected" row beside it, which says it looked and found none.
      out.push(
        chipSpec(coverageChipText(d), {
          cls: 'mlv-chip--coverage',
          title: d.message,
          attrs: [['data-coverage', d.kind]],
        }),
      );
    } else if (SPECIALLY_RENDERED.indexOf(d.kind) < 0) {
      // A kind this renderer has never heard of still says what it says
      // (invariant 1.1/6) rather than vanishing into the "N notes" count.
      out.push(chipSpec(d.message || d.kind, { attrs: [['data-diagnostic-kind', d.kind]] }));
    }
  }
  if ((g.workspace.filesFailed || 0) > 0) {
    out.push(chipSpec(g.workspace.filesFailed + ' files failed to parse'));
  }
  return foldChips(out);
}

/**
 * STEP 2 — fold identical chips into one that carries its count.
 *
 * Identity is the heading, the variant and the TEXT: two coverage chips that
 * both read `1 value not traced` are one fact repeated, and drawing it 36 times
 * (measured on `analyzer/tests/fixtures`) tells a reader nothing the count does
 * not. The distinct MESSAGES behind the fold are kept for the tooltip, so the
 * per-file detail is one hover away rather than gone.
 */
function foldChips(specs: ChipSpec[]): ChipSpec[] {
  const out: ChipSpec[] = [];
  const seen = new Map<string, ChipSpec>();
  for (const spec of specs) {
    const key = JSON.stringify([spec.label, spec.cls, spec.text]);
    const first = seen.get(key);
    if (!first) {
      seen.set(key, spec);
      out.push(spec);
      continue;
    }
    first.count += 1;
    for (const line of spec.detail) {
      if (first.detail.indexOf(line) < 0) first.detail.push(line);
    }
  }
  return out;
}

/**
 * The tooltip: a folded chip states its count and lists what it folded.
 *
 * TAB2-10: every chip now carries one, falling back to its own text. The
 * stylesheet ellipsises a chip wider than `CHIP_TEXT_CH`, and a reader must
 * always have somewhere to recover the tail from — the generic chip of
 * invariant 1.1/6 had no `title` at all, so a long message from a kind this
 * renderer has never heard of would have been the one that could not be read.
 */
export function chipTitle(spec: ChipSpec): string {
  if (spec.count <= 1) return spec.title || spec.text;
  const head = spec.count + '× ' + spec.text;
  if (!spec.detail.length) return head;
  const lines = spec.detail.slice(0, 6);
  const rest = spec.detail.length - lines.length;
  return head + '\n' + lines.join('\n') + (rest > 0 ? '\n… and ' + rest + ' more' : '');
}
