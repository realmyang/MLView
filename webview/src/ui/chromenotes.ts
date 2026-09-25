/**
 * The chrome's diagnostic vocabulary: the words it uses for a coverage gap, and
 * the one-stat pill the toolbar counts nodes and edges with.
 *
 * Split out of `ui/chrome.ts` when the Sprint 4 viewer drop pushed that file
 * over the size bar. Pure functions over `Diagnostic[]` and strings — no state,
 * no callbacks, nothing that knows the toolbar exists.
 *
 * COVERAGE is why the two `coverage*` functions are worded the way they are:
 * MLView's worst failure mode is that it cannot tell *"I checked and it is
 * fine"* from *"I could not check"*, so every string here has to name what was
 * NOT looked at rather than summarise what was.
 */

import { add, el } from '../dom.js';
import { OUT_OF_ORDER_KINDS } from '../notebook.js';
import type { Diagnostic } from '../types.js';

/**
 * Diagnostic kinds the chrome surfaces somewhere OTHER than the generic note
 * chip: as a banner, as a purpose-built chip, or folded into the status bar.
 * Anything not listed here — including a kind invented by a newer analyzer —
 * falls through to the generic chip, which is what invariant 1.1/6 asks for.
 */
export const SPECIALLY_RENDERED = [
  'parse_error',
  'dynamic_scope',
  'truncated',
  'notebook_skipped',
  'framework_suppressed',
  'config_warning',
  'config_unresolved',
  'untagged_dataflow',
  'single_file_analysis',
  'unresolved_callee',
  'framework_filter',
  'notebook_analyzed',
  // NB. Drawn as a BANNER, not a chip.
].concat(OUT_OF_ORDER_KINDS);

/** The kind ANA-5a and CONTRACTS 11.52 both ship under (11.18's reserved kind). */
export const UNRESOLVED_CALLEE = 'unresolved_callee';

/**
 * The kind CONTRACTS §2.6 C8 ships `--framework <x>`'s cost under.
 *
 * `core.coverage.COVERAGE_KINDS` is `("untagged_dataflow",
 * "single_file_analysis", "framework_filter")` and C9 makes that tuple a SUBSET
 * of every host's own list. The plugin and the extension listed this kind from
 * the day C8 landed; this file did not, and nothing compared it against the
 * core — the gate C9 names exists for the other two hosts only. The measured
 * consequence: a clean workspace analysed with `--framework torch` drew the
 * rail's unqualified *"70 nodes across 7 stages checked — nothing to flag."*
 * with no banner and no chip, while the document's only diagnostic said five
 * rules the detected frameworks would have run did not. That is exactly the
 * clean-bill-of-health sentence the viewer must never draw over a blind spot,
 * reached through a kind the viewer had never heard of. (The tests that held
 * this list to the analyzer's declaration were removed with the analyzer.)
 */
export const FRAMEWORK_FILTER = 'framework_filter';

/**
 * COVERAGE. The product's worst failure mode is that it cannot tell *"I checked
 * and it is fine"* from *"I could not check"*: MLV101 is silent whenever
 * features arrive as a function parameter, and analysing `train.py` alone yields
 * 3 findings where its directory yields 7 — a 57 % loss, with nothing said. Both
 * now arrive as diagnostics, and both get a banner that says what was NOT
 * looked at.
 *
 * TAB2-10. `unresolved_callee` is the third, and it was the one kind the two
 * halves of the product disagreed about: `emit/answers._COVERAGE_KINDS` has
 * counted it as a coverage gap since CONTRACTS 11.52 — it is what makes the
 * verdict say *"so this is not a clean bill of health"* — while the viewer let
 * it fall through to the generic note chip, whose text is the diagnostic's
 * WHOLE message. On `tabular_survival_cox` that drew two chips of 262 and 238
 * characters beside two three-word stage chips, and `.mlv-chiprow .mlv-chip` is
 * `white-space: normal`, so the honest disclosure filled the row's 12vh
 * scroller and the reader had to scroll a chip row to find the short chips.
 * Treating it as what it is gives it the same shape as its two siblings: a
 * short countable chip, the sentence on the chip's `title`, and the sentence
 * again in the coverage banner, which is where a paragraph belongs.
 *
 * REV-02/H2. `framework_filter` is the fourth, and it is not a viewer opinion
 * at all: the core emits it (C8) and §2.6 C9 makes the core's tuple a subset of
 * this list, so its absence here was a contract breach rather than a missing
 * nicety. It takes the same COVERAGE branch as the other three and gains the
 * chip shape, the `title`, the banner and the rail's clean-state caveat in one
 * move — exactly as §10.8 A5 did for `unresolved_callee`.
 */
export const COVERAGE_KINDS = [
  'untagged_dataflow',
  'single_file_analysis',
  UNRESOLVED_CALLEE,
  FRAMEWORK_FILTER,
];

/**
 * HOSTS-UX-CLEANSTATE. The three kinds above are what the coverage BANNER is
 * about; blindness is wider than that. A file that failed to parse and a
 * notebook that was never opened are strictly LARGER gaps than an unresolved
 * call — CONTRACTS 11.60 A2 settles that for `emit/answers`, and the rail's
 * clean state answers the same question on the same document, so it reads the
 * same set.
 *
 * `truncated` is here CONDITIONALLY, and `scope` (11.59 A1) is what decides it:
 * `files`, `rounds` and `dataflow` mean something was not READ, while `nodes`
 * means the graph was rolled up for display — the reader can see that in the
 * diagram and it is not a gap in the analysis. Before `scope` existed this
 * distinction could not be drawn at all, which is why the clean state could not
 * have been fixed honestly in round 1.
 */
export const UNREAD_KINDS = ['parse_error', 'notebook_skipped'];

export function blindSpots(diags: Diagnostic[]): Diagnostic[] {
  return (diags || []).filter(
    (d) =>
      COVERAGE_KINDS.indexOf(d.kind) >= 0 ||
      UNREAD_KINDS.indexOf(d.kind) >= 0 ||
      (d.kind === 'truncated' && (d.scope || '') !== 'nodes'),
  );
}

/**
 * TAB2-10 — how wide a chip's text may be drawn before it is ellipsised.
 *
 * A chip is a label. Three diagnostic kinds carry a SENTENCE instead — the two
 * config kinds since VW-08, and `unresolved_callee` — and one of them ran to
 * 262 characters, which `.mlv-chiprow .mlv-chip { white-space: normal }` then
 * wrapped into a paragraph filling the row's whole 12vh scroller.
 *
 * The bound is drawn in CSS, on a `.mlv-chip__text` wrapper, and it is a CLIP
 * rather than a cut: the element still holds every character, so the exported
 * HTML, `textContent` and every screen reader get the whole sentence, the
 * browser paints an ellipsis where it stops, and the chip's `title` carries it
 * for a hover. `ui/chrome.ts` guarantees the `title` — that is the half a
 * renderer has to do, and the half VW-08's defect was missing.
 *
 * The number is `48ch` ≈ 290 px at this row's 11 px type, so four chips take a
 * 1240 px line and nine of them (MAX_CHIPS plus the opener) take three.
 */
export const CHIP_TEXT_CH = 48;


/** One `12 nodes` pill for the toolbar's stat row. */
export function stat(value: string, label: string): HTMLElement {
  const wrap = el('span', 'mlv-stat');
  add(wrap, el('span', 'mlv-stat__value', value));
  add(wrap, el('span', '', label));
  return wrap;
}

/**
 * NB. The chip for `notebook_analyzed` — the counterpart of the
 * `notebook_skipped` chip the chrome has always drawn. Its opposite sat in the
 * "specially rendered" list with nothing rendering it, so a run that DID read
 * the notebooks said so nowhere outside the "N notes" count.
 *
 * VW-06. `core/pipeline.py` emits ONE of these PER NOTEBOOK and its `count` is
 * that notebook's CODE CELLS — the diagnostic's own message says so verbatim
 * ("leak.ipynb: 4 of 4 cell(s) are code and were analyzed as ..."). Printing it
 * as "4 notebooks analyzed" told a reader of a two-notebook workspace that
 * there were eight, twice; the number was only ever right for a one-cell
 * notebook. The chip now says what the diagnostic says: the notebook's name and
 * its cell count.
 */
export function notebooksAnalyzedText(d: Diagnostic): string {
  const n = d.count || 0;
  const cells = n + (n === 1 ? ' cell' : ' cells');
  const name = basename(d.file || '');
  return name ? name + ' — ' + cells + ' analyzed' : cells + ' analyzed';
}

/** The last path segment, for a chip that has room for a name and not a path. */
function basename(file: string): string {
  const at = Math.max(file.lastIndexOf('/'), file.lastIndexOf('\\'));
  return at >= 0 ? file.slice(at + 1) : file;
}

/** The chip text for one coverage diagnostic — short, countable, honest. */
export function coverageChipText(d: Diagnostic): string {
  if (d.kind === 'single_file_analysis') {
    const codes = d.codes && d.codes.length ? ' — ' + d.codes.join(', ') + ' need more files' : '';
    return 'single-file analysis' + codes;
  }
  if (d.kind === UNRESOLVED_CALLEE) return unreadCallsChipText(d);
  if (d.kind === FRAMEWORK_FILTER) return frameworkFilterChipText(d);
  const n = d.count || 0;
  return n > 0 ? n + (n === 1 ? ' value not traced' : ' values not traced') : 'dataflow not traced';
}

/**
 * TAB2-10 — `unresolved_callee` as a chip rather than as a paragraph.
 *
 * Both emitters of this kind carry the same two structured fields, so the chip
 * is built from them and never from the prose:
 *
 *   `core/unknown_framework.py`  scope = the top-level package (`lifelines`),
 *                                count = call sites into it (11.52 A2)
 *   `core/unresolved.py`         scope = the enclosing scope's qualname,
 *                                count = call sites in it (11.18 C1)
 *
 * The two say different things — *"I read these calls and have no table for
 * this library"* versus *"I could not read these callees"* — and the kind does
 * not distinguish them (11.52 B1/B2 ship both under it deliberately). So the
 * chip states only what is true of BOTH, "N calls not understood", and names
 * the scope they are in. The distinction stays in the message, which is on the
 * chip's `title` and in the coverage banner, word for word.
 */
export function unreadCallsChipText(d: Diagnostic): string {
  const n = d.count || 0;
  const calls = n > 0 ? n + (n === 1 ? ' call' : ' calls') + ' not understood' : 'calls not understood';
  const scope = (d.scope || '').trim();
  return scope ? scope + ' — ' + calls : calls;
}

/**
 * REV-02 — `framework_filter` as a chip rather than as a 287-character wall.
 *
 * `count` on this kind is SUPPRESSED RULE CODES and not blind sites (§2.6 C9
 * says so in as many words), so the chip counts rules and the headline gives it
 * a clause of its own; nothing here adds that number to a blind-spot total.
 *
 * The framework's NAME is read off the front of the message, which is the one
 * place it exists: `core.coverage.framework_filter_diagnostic` builds the row
 * with `codes` and `count` and no `scope`, and the message it fixes by contract
 * opens `--framework <name> narrowed the rule set: …`. Reading a leading flag
 * token is not the guess §10.8 A3 forbids — that clause is about inferring
 * which of two FLAVOURS a row is, and this kind has one. When the token is not
 * there the chip simply drops the name and still states the cost, so a reworded
 * message degrades to a shorter chip rather than to a wrong one.
 */
export function frameworkFilterChipText(d: Diagnostic): string {
  const n = d.count || (d.codes || []).length;
  const rules = n > 0 ? n + (n === 1 ? ' rule' : ' rules') + ' not run' : 'rules not run';
  const name = frameworkFilterName(d);
  return name ? '--framework ' + name + ' — ' + rules : rules;
}

/** `torch` out of ``--framework torch narrowed …``, or '' when it is not there. */
function frameworkFilterName(d: Diagnostic): string {
  const match = /^--framework[ \t]+([A-Za-z0-9_.+-]+)\b/.exec(d.message || '');
  return match ? match[1] : '';
}

/** The banner headline: what was not checked, in the reader's words. */
export function coverageHeadline(diags: Diagnostic[]): string {
  const single = diags.some((d) => d.kind === 'single_file_analysis');
  const untagged = diags.filter((d) => d.kind === 'untagged_dataflow');
  const unread = diags.filter((d) => d.kind === UNRESOLVED_CALLEE);
  const parts: string[] = [];
  if (single) parts.push('only part of this project was analyzed, so cross-file rules could not run');
  // REV-02. Beside `single_file_analysis`, because the two say the same kind of
  // thing — rules that would have judged this workspace did not run — and a
  // reader who sees both should read them together. The number is RULES, never
  // added to a count of blind sites (§2.6 C9).
  const filtered = diags.filter((d) => d.kind === FRAMEWORK_FILTER);
  if (filtered.length) {
    const n = filtered.reduce((sum, d) => sum + (d.count || (d.codes || []).length || 1), 0);
    const names = frameworkNames(filtered);
    parts.push(
      n +
        (n === 1 ? ' rule the detected frameworks would have run was' : ' rules the detected frameworks would have run were') +
        ' not run' +
        (names ? ' under --framework ' + names : ' because of --framework'),
    );
  }
  if (untagged.length) {
    const n = untagged.reduce((sum, d) => sum + (d.count || 1), 0);
    parts.push(n + (n === 1 ? ' value' : ' values') + ' reaching a fit or split could not be traced');
  }
  if (unread.length) {
    const n = unread.reduce((sum, d) => sum + (d.count || 1), 0);
    parts.push(n + (n === 1 ? ' call was' : ' calls were') + ' not understood' + scopeList(unread));
  }
  // HOSTS-UX-CLEANSTATE: the banner never hands these two in — it passes
  // COVERAGE_KINDS — but the rail's clean state hands in `blindSpots()`, and a
  // sentence that silently dropped the largest gap of the three would be the
  // defect it is there to fix.
  const skipped = diags.filter((d) => d.kind === 'notebook_skipped');
  if (skipped.length) {
    const n = skipped.reduce((sum, d) => sum + (d.count || 1), 0);
    parts.push(n + (n === 1 ? ' notebook was' : ' notebooks were') + ' not analyzed');
  }
  const unparsed = diags.filter((d) => d.kind === 'parse_error');
  if (unparsed.length) {
    const n = unparsed.reduce((sum, d) => sum + (d.count || 1), 0);
    parts.push(n + (n === 1 ? ' file' : ' files') + ' could not be parsed');
  }
  const stopped = diags.filter((d) => d.kind === 'truncated' && (d.scope || '') !== 'nodes');
  if (stopped.length) {
    parts.push(stopped.length === 1 ? 'one analysis cap was hit' : stopped.length + ' analysis caps were hit');
  }
  // A kind added to COVERAGE_KINDS by a later round still gets a headline that
  // reads as a sentence rather than "Coverage: . A clean result…".
  if (!parts.length) {
    parts.push(diags.length + (diags.length === 1 ? ' coverage gap was' : ' coverage gaps were') + ' reported');
  }
  return 'Coverage: ' + parts.join('; ') + '. A clean result here is not a clean bill of health.';
}

/** `torch` / `torch, sklearn` — the filters a run of these rows names, bounded. */
function frameworkNames(diags: Diagnostic[]): string {
  const names: string[] = [];
  for (const d of diags) {
    const name = frameworkFilterName(d);
    if (name && names.indexOf(name) < 0) names.push(name);
  }
  const rest = names.length - 3;
  return names.slice(0, 3).join(', ') + (rest > 0 ? ' and ' + rest + ' more' : '');
}

/** `(lifelines, sksurv)` — the scopes a run of diagnostics names, bounded. */
function scopeList(diags: Diagnostic[]): string {
  const names: string[] = [];
  for (const d of diags) {
    const scope = (d.scope || '').trim();
    if (scope && names.indexOf(scope) < 0) names.push(scope);
  }
  if (!names.length) return '';
  const rest = names.length - 3;
  return ' (' + names.slice(0, 3).join(', ') + (rest > 0 ? ' and ' + rest + ' more' : '') + ')';
}

/** The `<pre>` body under a banner: up to eight diagnostics, file and line first. */
export function describe(diags: Diagnostic[]): string {
  return diags
    .slice(0, 8)
    .map((d) => (d.file ? d.file + (d.line ? ':' + d.line : '') + ' — ' : '') + d.message)
    .join('\n');
}

/* ── HOSTS-UX-R2-06: one budget over the bands above the canvas ─────────── */

/**
 * What one banner row costs. MEASURED in Chromium at 1280x800 on the pinned
 * public corpus: yolov5's three banners were 160 px together.
 */
export const BANNER_PX = 53;
/** The chip row's own padding and border, without any chips in it. */
export const CHIPROW_PAD_PX = 17;
/** One wrapped line of chips inside it. */
export const CHIP_LINE_PX = 30;
/**
 * How many chips fit one line. A chip is now at most `CHIP_TEXT_MAX`
 * characters, which is about a third of a 1280 px row.
 */
export const CHIPS_PER_LINE = 3;
/**
 * Above this much chrome ABOVE it, the Pipeline Answer Card starts collapsed.
 *
 * MEASURED at first paint across the public corpus (HOSTS-UX-R2-06): at
 * 1280x800 the canvas was 247 px — 31 % of the window — on 24 of 45 large
 * workspaces, behind 160 px of banners, 105 px of chips and a 165 px answer
 * card. Round 1 bounded each band separately (11.55 B1); nothing bounded their
 * SUM, and the card is the only one of the three whose content the reader can
 * ask for later without losing anything, because its header keeps stating
 * `1 of 4 answered · 3 not detected` either way. 200 px is the line: it is
 * reached by three banners and a chip row, and not by anything the 92-program
 * labelled corpus draws.
 */
export const CHROME_CROWDED_PX = 200;

/**
 * What the two bands above the canvas will take, in CSS pixels at 1280x800.
 *
 * An ESTIMATE, deliberately: the decision it feeds is a default, it is taken
 * before first paint (jsdom has no layout, and a host that measured would be
 * reading a box that has not been laid out yet), and being 20 px out changes
 * nothing. It reproduces the two numbers it was built from — three banners is
 * 159 px against 160 measured, and a full chip row of nine chips is 107 px
 * against 105 measured.
 */
export function chromeBandHeight(banners: number, chips: number): number {
  const rows = Math.max(0, Math.ceil(Math.max(0, chips) / CHIPS_PER_LINE));
  const chipRow = rows > 0 ? CHIPROW_PAD_PX + CHIP_LINE_PX * rows : 0;
  return Math.max(0, banners) * BANNER_PX + chipRow;
}
