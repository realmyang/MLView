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
 * STEP 1 — collect: the phases a scope leaves out, then the document's notes.
 *
 * The authored coverage limitations are listed in the header's Details (and
 * counted in each Inspector), so they draw no chip. A scope note
 * (`config_warning`) is a sentence, so its full text is also its tooltip. A
 * note of any other kind still says what it says (invariant 1.1/6).
 */
export function collectChips(s: ChromeState): ChipSpec[] {
  const g = s.graph as MLGraph;
  const out: ChipSpec[] = [];
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
    if (d.kind === 'workflow_limitation') continue;
    if (d.kind === 'config_warning') {
      out.push(chipSpec(d.message, { title: d.message, attrs: [['data-config-note', d.kind]] }));
    } else {
      out.push(chipSpec(d.message || d.kind, { attrs: [['data-diagnostic-kind', d.kind]] }));
    }
  }
  return foldChips(out);
}

/**
 * STEP 2 — fold identical chips into one that carries its count.
 *
 * Identity is the heading, the variant and the TEXT: two chips with one text
 * are one fact repeated, and the count says so. The distinct MESSAGES behind
 * the fold are kept for the tooltip, so the detail is one hover away rather
 * than gone.
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
 * TAB2-10: every chip carries one, falling back to its own text. The
 * stylesheet ellipsises a long chip (`.mlv-chiprow .mlv-chip__text`), and a
 * reader must always have somewhere to recover the tail from.
 */
export function chipTitle(spec: ChipSpec): string {
  if (spec.count <= 1) return spec.title || spec.text;
  const head = spec.count + '× ' + spec.text;
  if (!spec.detail.length) return head;
  const lines = spec.detail.slice(0, 6);
  const rest = spec.detail.length - lines.length;
  return head + '\n' + lines.join('\n') + (rest > 0 ? '\n… and ' + rest + ' more' : '');
}
