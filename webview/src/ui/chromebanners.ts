/**
 * The banner stack: everything the reader has to know about the run BEFORE
 * they trust the picture.
 *
 * Order is the whole design, and it is deliberately not severity order. A run
 * that failed outranks a stale file; "I could not look there" (COVERAGE)
 * outranks "I looked and was unsure" (dynamic scope); and a notebook last run
 * out of order sits above both, because it makes the fit-before-split family
 * unreliable and that has to be read before the findings it de-rates.
 *
 * Every banner is dismissible, and a dismissal is remembered by the App for the
 * life of the document (`ChromeState.dismissed`), never persisted: a new
 * analysis says it again.
 */

import { add, button, clear, el, iconButton, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { COVERAGE_KINDS, coverageHeadline, describe } from './chromenotes.js';
import { outOfOrderDiagnostics, outOfOrderHeadline } from '../notebook.js';
import { rollupCaveats, rollupHeadline, rollupSummary } from '../rollup/rolled.js';
import type { ChromeState } from './chrome.js';

/** The three callbacks a banner can fire. */
export interface BannerActions {
  onAction(id: string): void;
  onRefresh(): void;
  onDismiss(key: string): void;
}

export function renderBanners(host: HTMLElement, s: ChromeState, cb: BannerActions): void {
  clear(host);
  const g = s.graph;
  let any = false;
  const dismissButton = (key: string) => {
    const btn = iconButton('mlv-btn mlv-btn--icon', 'Dismiss');
    btn.appendChild(uiIcon('close'));
    on(btn, 'click', () => cb.onDismiss(key));
    return btn;
  };

  if (s.error) {
    any = true;
    const b = banner('error', 'Analysis failed — ' + s.error.message, s.error.detail);
    const actions = add(b, el('div', 'mlv-banner__actions'));
    for (const a of s.error.actions || []) {
      const btn = button('mlv-btn', a.label);
      on(btn, 'click', () => cb.onAction(a.id));
      actions.appendChild(btn);
    }
    const copy = button('mlv-btn', 'Copy details');
    on(copy, 'click', () => cb.onAction('mlview.copyErrorDetails'));
    actions.appendChild(copy);
    host.appendChild(b);
  }

  if (s.stale.length && !s.dismissed.has('stale')) {
    any = true;
    const names = s.stale.slice(0, 3).join(', ') + (s.stale.length > 3 ? ' and ' + (s.stale.length - 3) + ' more' : '');
    const b = banner('warn', 'Files changed since this analysis: ' + names);
    const actions = add(b, el('div', 'mlv-banner__actions'));
    if (s.capabilities.canReanalyze) {
      const btn = button('mlv-btn mlv-btn--primary', 'Re-analyze');
      on(btn, 'click', () => cb.onRefresh());
      actions.appendChild(btn);
    }
    actions.appendChild(dismissButton('stale'));
    host.appendChild(b);
  }

  if (g) {
    const parseErrors = (g.diagnostics || []).filter((d) => d.kind === 'parse_error');
    if (parseErrors.length && !s.dismissed.has('parse')) {
      any = true;
      const b = banner('warn', parseErrors.length + ' file(s) could not be parsed', describe(parseErrors));
      add(b, el('div', 'mlv-banner__actions')).appendChild(dismissButton('parse'));
      host.appendChild(b);
    }

    // NB. ABOVE the coverage banner: a notebook last run out of order makes
    // the fit-before-split family unreliable, and that has to be read before
    // the findings it de-rates.
    const outOfOrder = outOfOrderDiagnostics(g.diagnostics || []);
    if (outOfOrder.length && !s.dismissed.has('notebook-order')) {
      any = true;
      const b = banner('warn', outOfOrderHeadline(outOfOrder), describe(outOfOrder));
      b.setAttribute('data-notebook-order-banner', String(outOfOrder.length));
      add(b, el('div', 'mlv-banner__actions')).appendChild(dismissButton('notebook-order'));
      host.appendChild(b);
    }
    // COVERAGE. One banner for everything the run could NOT see, above the
    // "partial understanding" note, because "I did not look" outranks "I
    // looked and was unsure".
    const coverage = (g.diagnostics || []).filter((d) => COVERAGE_KINDS.indexOf(d.kind) >= 0);
    if (coverage.length && !s.dismissed.has('coverage')) {
      any = true;
      const b = banner('warn', coverageHeadline(coverage), describe(coverage));
      b.setAttribute('data-coverage-banner', String(coverage.length));
      add(b, el('div', 'mlv-banner__actions')).appendChild(dismissButton('coverage'));
      host.appendChild(b);
    }

    const dynamicDiags = (g.diagnostics || []).filter((d) => d.kind === 'dynamic_scope');
    if ((dynamicDiags.length > 0 || s.dynamicNodes > 0) && !s.dismissed.has('dynamic')) {
      any = true;
      const detail = dynamicDiags.length ? describe(dynamicDiags) : undefined;
      const b = banner(
        'info',
        'Partial understanding: some calls could not be resolved (config-driven or dynamic). ' +
          s.dynamicNodes +
          ' node(s) are shown with reduced confidence.',
        detail,
      );
      add(b, el('div', 'mlv-banner__actions')).appendChild(dismissButton('dynamic'));
      host.appendChild(b);
    }

    // PERF-04. A capped document is now ROLLED UP rather than mutilated, and
    // the banner has to say which of the two it is looking at: a document
    // carrying folded cards or weighted cables gets the rollup wording and
    // its caveats, and one written by an analyzer that still deletes keeps
    // the old sentence, because for that document the old sentence is true.
    const rollup = rollupSummary(g);
    if (rollup && !s.dismissed.has('truncated')) {
      any = true;
      // The analyzer's own sentence is the DETAIL, verbatim: 11.46 D makes it
      // the place the per-phase counts and any lost findings are named, and a
      // paraphrase would be a second set of numbers to keep in step.
      const b = banner('info', rollupHeadline(rollup), rollup.message || undefined);
      b.setAttribute('data-rollup-banner', String(rollup.folded));
      const body = (b.querySelector('.mlv-banner__text') as HTMLElement) || b;
      const notes = add(body, el('ul', 'mlv-banner__notes'));
      notes.setAttribute('data-rollup-notes', String(rollupCaveats(rollup).length));
      for (const text of rollupCaveats(rollup)) add(notes, el('li', '', text));
      add(b, el('div', 'mlv-banner__actions')).appendChild(dismissButton('truncated'));
      host.appendChild(b);
    } else if (g.stats && g.stats.truncated && !s.dismissed.has('truncated')) {
      any = true;
      const b = banner(
        'warn',
        'Graph truncated at ' + g.nodes.length + ' nodes — narrow the scope with --include, or collapse groups.',
      );
      add(b, el('div', 'mlv-banner__actions')).appendChild(dismissButton('truncated'));
      host.appendChild(b);
    }
  }

  host.hidden = !any;
}

function banner(kind: string, text: string, detail?: string): HTMLElement {
  const b = el('div', 'mlv-banner mlv-banner--' + kind);
  b.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  const body = add(b, el('div', 'mlv-banner__text'));
  add(body, el('div', '', text));
  if (detail) add(body, el('pre', 'mlv-banner__detail', detail));
  return b;
}
