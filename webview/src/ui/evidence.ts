/**
 * The trust surface (MLV-P6): the confidence chip, the evidence checklist and
 * the rule card.
 *
 * All 15 sample findings carry 3–5 evidence factors of real substance —
 * MLV301's include *"SmallCNN contains BatchNorm2d, Dropout, which behave
 * differently in train mode"* — and before this `evidence` appeared exactly once
 * in `webview/src`: its own type declaration. Meanwhile the bucket chip was
 * drawn only for `possible` / `speculative`, so `certain` and `likely` looked
 * identical — the distinction a reviewer most needs.
 *
 * Both live behind a `<details>` disclosure. A 111-row rail cannot afford them
 * permanently expanded; a finding you cannot interrogate cannot be trusted.
 */

import { add, el } from '../dom.js';
import { ruleDocFor } from './ruledocs.js';
import type { RuleDoc } from './ruledocs.js';
import type { Evidence, Issue } from '../types.js';

const BUCKETS = ['certain', 'likely', 'possible', 'speculative'];

/** `certain` / `likely` / `possible` / `speculative`, or a passthrough. */
export function normalizeBucket(bucket: string): string {
  return BUCKETS.indexOf(bucket) >= 0 ? bucket : 'unknown';
}

/**
 * The bucket chip, on EVERY row.
 *
 * It used to appear only when the analyzer was unsure, which drained the signal
 * from the two buckets a reviewer acts on: a row with no chip could equally mean
 * "certain" or "the renderer forgot".
 */
export function confidenceChip(issue: Issue): HTMLElement {
  if (issue.basis) {
    const chip = el('span', 'mlv-chip mlv-chip--basis mlv-chip--basis-' + issue.basis, issue.basis);
    chip.setAttribute('data-basis', issue.basis);
    chip.title = 'Basis: ' + issue.basis;
    chip.setAttribute('aria-label', chip.title);
    return chip;
  }
  const bucket = normalizeBucket(issue.confidenceBucket);
  const chip = el('span', 'mlv-chip mlv-chip--conf mlv-chip--conf-' + bucket, issue.confidenceBucket || bucket);
  chip.setAttribute('data-confidence', bucket);
  const pct = typeof issue.confidence === 'number' && isFinite(issue.confidence)
    ? ' (' + Math.round(issue.confidence * 100) + '%)'
    : '';
  chip.title = 'Confidence: ' + (issue.confidenceBucket || bucket) + pct;
  chip.setAttribute('aria-label', chip.title);
  return chip;
}

/** A weight rendered as a number AND a proportional bar — never colour alone. */
function weightCell(weight: number): HTMLElement {
  const value = typeof weight === 'number' && isFinite(weight) ? weight : 0;
  const wrap = el('span', 'mlv-ev__weight');
  wrap.setAttribute('data-weight', value.toFixed(2));
  const bar = add(wrap, el('span', 'mlv-ev__bar'));
  // Clamped to the unit interval: a factor may legitimately exceed 1, and a
  // 300 %-wide bar would blow the row out of the rail.
  bar.style.width = Math.round(Math.max(0, Math.min(1, Math.abs(value))) * 100) + '%';
  add(wrap, el('span', 'mlv-ev__weight-value', value.toFixed(2)));
  return wrap;
}

/** `issue.evidence[]` as a compact list: kind, detail, weight — one per line. */
export function evidenceList(evidence: Evidence[]): HTMLElement {
  const list = el('ul', 'mlv-ev');
  list.setAttribute('data-evidence-count', String(evidence.length));
  for (const factor of evidence) {
    const li = add(list, el('li', 'mlv-ev__item'));
    li.setAttribute('data-evidence-kind', factor.kind || '');
    const head = add(li, el('div', 'mlv-ev__head'));
    add(head, el('span', 'mlv-ev__kind', (factor.kind || 'factor').replace(/_/g, ' ')));
    head.appendChild(weightCell(factor.weight));
    if (factor.detail) add(li, el('div', 'mlv-ev__detail', factor.detail));
  }
  return list;
}

/** A `<details>` block with a summary line. Collapsed until the user asks. */
function disclosure(summaryText: string, cls: string): HTMLDetailsElement {
  const box = el('details', cls) as HTMLDetailsElement;
  const summary = document.createElement('summary');
  summary.className = 'mlv-disclosure__summary';
  summary.textContent = summaryText;
  box.appendChild(summary);
  return box;
}

/**
 * "Why this confidence" — the evidence checklist, as progressive disclosure.
 * Returns null when the finding carries no factors, so a rule that ships none
 * does not grow an empty twisty.
 */
export function evidenceDisclosure(issue: Issue): HTMLElement | null {
  const evidence = issue.evidence || [];
  if (!evidence.length) return null;
  const box = disclosure(
    'Why this confidence · ' + evidence.length + (evidence.length === 1 ? ' factor' : ' factors'),
    'mlv-disclosure mlv-disclosure--evidence',
  );
  box.setAttribute('data-evidence-for', issue.id);
  box.appendChild(evidenceList(evidence));
  return box;
}

/**
 * The rows of the rule card, MINUS anything the surface above already printed.
 *
 * Both callers — the expanded rail row and the Inspector — render `message`,
 * `why` and `fixHint` immediately above this card. While no rule-doc sidecar
 * exists (see `ruledocs.ts`), `ruleDocFor` composes those same three strings, so
 * the disclosure re-printed the three paragraphs of the row it sat under: a
 * click that bought the reader nothing (TB-01). A row survives only when the
 * sidecar actually said something different — and `falsePositives`, the one
 * section that has no composed fallback at all, always survives.
 */
export function ruleDocRows(issue: Issue, doc: RuleDoc): { label: string; text: string }[] {
  const rows: { label: string; text: string }[] = [];
  const add_ = (label: string, text: string | undefined, shown: string | undefined) => {
    if (text && text !== shown) rows.push({ label, text });
  };
  add_('Why it matters', doc.why, issue.why);
  add_('How it is detected', doc.detection, issue.message);
  add_('How to fix it', doc.fix, issue.fixHint);
  add_('False positives it avoids', doc.falsePositives, undefined);
  return rows;
}

/**
 * "About MLV301" — the rule card: what the rule knows that this row does not.
 *
 * Self-contained and offline: every string comes from the document. Null when
 * there is nothing to add — no sidecar text beyond the finding's own and no
 * document to cite — so a report never ships an empty or duplicating twisty.
 */
export function ruleDocDisclosure(issue: Issue): HTMLElement | null {
  const doc = ruleDocFor(issue);
  const rows = ruleDocRows(issue, doc);
  if (!rows.length && !doc.docs) return null;

  const box = disclosure('About ' + doc.code, 'mlv-disclosure mlv-disclosure--rule');
  box.setAttribute('data-rule-doc', doc.code);
  const body = add(box, el('div', 'mlv-ruledoc'));
  for (const row of rows) {
    const section = add(body, el('div', 'mlv-ruledoc__row'));
    section.setAttribute('data-ruledoc-section', row.label);
    add(section, el('div', 'mlv-ruledoc__label', row.label));
    add(section, el('p', 'mlv-ruledoc__text', row.text));
  }
  if (doc.docs) {
    const cite = add(body, el('div', 'mlv-ruledoc__source', doc.docs));
    cite.setAttribute('data-ruledoc-source', doc.docs);
  }
  return box;
}

/** Both disclosures, in the order the rail and the Inspector both use them. */
export function appendTrustSections(parent: HTMLElement, issue: Issue): void {
  const evidence = evidenceDisclosure(issue);
  if (evidence) parent.appendChild(evidence);
  const rule = ruleDocDisclosure(issue);
  if (rule) parent.appendChild(rule);
}
