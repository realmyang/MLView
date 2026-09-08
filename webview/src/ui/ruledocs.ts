/**
 * The rule-doc sidecar (MLV-P6).
 *
 * `docs/rules/MLV201.md` holds the one paragraph that answers *"why should I
 * believe this"* — how the rule detects the defect, and the false positives it
 * deliberately avoids (gradient accumulation, LBFGS, factory-built optimizers).
 * The standalone report could reach none of it: `grep -c "How it is detected"
 * .mlview/report.html` is 0 and the report contains zero anchor elements.
 *
 * THE HOOK. The analyzer will expose a compact per-rule JSON sidecar
 * (`gen_rule_docs.py`, ~1–2 KB per rule) and `emit/html_out.py` will inline the
 * entries for the rules that actually fired. This module is the single place
 * that reads it, under two clearly named, entirely optional sources:
 *
 *   1. `<script type="application/json" id="mlview-rule-docs">{ "MLV201": … }`
 *      — the element the emitter will write, beside `#mlview-graph`.
 *   2. `window.MLViewRuleDocs` — the same map assigned by a host that builds
 *      the page some other way (the VS Code webview, `dev/*.html`).
 *
 * Until that lands, `ruleDocFor` composes the same three sections out of the
 * finding itself, so the disclosure is useful today and gets richer for free the
 * day the sidecar appears. Nothing here throws: a missing, malformed or
 * partially-typed sidecar degrades to the composed form (invariant 1.1/6).
 */

import type { Issue } from '../types.js';

/** The id of the `<script type="application/json">` the emitter will write. */
export const RULE_DOCS_ELEMENT_ID = 'mlview-rule-docs';
/** The global a host may assign instead of embedding the element. */
export const RULE_DOCS_GLOBAL = 'MLViewRuleDocs';

/** One rule's compact documentation. Every field is optional. */
export interface RuleDoc {
  code: string;
  title?: string;
  /** Why the defect matters. */
  why?: string;
  /** How the rule decides — "How it is detected" in the Markdown. */
  detection?: string;
  /** What to do about it. */
  fix?: string;
  /** "False positives it avoids" — the skepticism-killer. */
  falsePositives?: string;
  /** The repo-relative path of the full document, for hosts that can open it. */
  docs?: string;
}

export type RuleDocMap = Record<string, RuleDoc>;

let overrideMap: RuleDocMap | null = null;
let cached: RuleDocMap | null = null;

/**
 * Install a sidecar directly. Used by hosts that already hold the JSON, and by
 * tests; passing `null` restores the document-scanning behaviour.
 */
export function setRuleDocs(map: RuleDocMap | null): void {
  overrideMap = map ? sanitize(map) : null;
  cached = null;
}

/** The sidecar for this document, read once and remembered. */
export function ruleDocs(): RuleDocMap {
  if (overrideMap) return overrideMap;
  if (cached) return cached;
  cached = readFromDocument();
  return cached;
}

function readFromDocument(): RuleDocMap {
  const out: RuleDocMap = {};
  try {
    const g = typeof window !== 'undefined' ? (window as unknown as Record<string, unknown>) : null;
    if (g && g[RULE_DOCS_GLOBAL]) Object.assign(out, sanitize(g[RULE_DOCS_GLOBAL] as RuleDocMap));
  } catch (_e) {
    /* a host may seal its global object */
  }
  try {
    const node = typeof document !== 'undefined' ? document.getElementById(RULE_DOCS_ELEMENT_ID) : null;
    const text = node ? node.textContent || '' : '';
    if (text.trim()) Object.assign(out, sanitize(JSON.parse(text) as RuleDocMap));
  } catch (_e) {
    /* a malformed sidecar must never take the report down */
  }
  return out;
}

/** Keep string fields, drop everything else. A sidecar is data, not markup. */
function sanitize(raw: RuleDocMap): RuleDocMap {
  const out: RuleDocMap = {};
  if (!raw || typeof raw !== 'object') return out;
  for (const code of Object.keys(raw)) {
    const entry = raw[code] as unknown;
    if (!entry || typeof entry !== 'object') continue;
    const src = entry as Record<string, unknown>;
    const doc: RuleDoc = { code };
    for (const key of ['title', 'why', 'detection', 'fix', 'falsePositives', 'docs'] as const) {
      const value = src[key];
      if (typeof value === 'string' && value.trim()) doc[key] = value;
    }
    out[code] = doc;
  }
  return out;
}

/**
 * The rule card for one finding: the sidecar entry when there is one, filled in
 * from the finding itself where it is silent.
 *
 * `message` is the composed fallback for `detection` on purpose — it is the
 * sentence naming what was actually seen at this site, which is the honest
 * stand-in for "how it is detected" until the sidecar arrives.
 */
export function ruleDocFor(issue: Issue, map: RuleDocMap = ruleDocs()): RuleDoc {
  const sidecar = (map && map[issue.code]) || null;
  return {
    code: issue.code,
    title: (sidecar && sidecar.title) || issue.title,
    why: (sidecar && sidecar.why) || issue.why || undefined,
    detection: (sidecar && sidecar.detection) || issue.message || undefined,
    fix: (sidecar && sidecar.fix) || issue.fixHint || undefined,
    falsePositives: sidecar ? sidecar.falsePositives : undefined,
    docs: (sidecar && sidecar.docs) || issue.docs || undefined,
  };
}

/** True when the sidecar — not the composed fallback — supplied this entry. */
export function hasSidecar(code: string, map: RuleDocMap = ruleDocs()): boolean {
  return !!(map && map[code]);
}
