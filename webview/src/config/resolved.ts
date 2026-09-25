/**
 * ANA-10 (Python half) — the viewer's reading of a resolved configuration value.
 *
 * The analyzer resolves module-level dict literals, dataclass field defaults,
 * `argparse add_argument(default=)` and attribute chains rooted at a
 * `CONFIG_NAME_RE` binding, and it resolves `getattr(<module>, <string>)`
 * against that module's exported symbols. Two things then have to appear on
 * screen, and they are what this module composes:
 *
 *   1. **The resolved value, in the card's sublabel.** `batch_size` on a config
 *      card with nothing beside it answers no question at all; `batch_size = 64`
 *      answers *"where does batch_size come from"*, which is what the config lane
 *      exists for.
 *   2. **The one-of-N alternatives node.** A `getattr` registry used to draw two
 *      `unknown` boxes. It is ONE node that resolved to one of N named symbols,
 *      and the card, the Inspector and the screen reader all say so — rather
 *      than pretending to a single answer nobody has.
 *
 * TWO SOURCES, AND THE ORDER MATTERS.
 *
 * **The analyzer's own sublabel** is the source that exists today:
 * `core/config_nodes.py` writes `selects pkg.optims.build_adam` for a resolved
 * selection and `one of 3 in pkg.optims · build_adam, build_rmsprop, build_sgd`
 * for an unresolved one. That wording is SHARED with the CLI and the two other
 * hosts, so when it is the source the card keeps it verbatim and this module
 * only adds the alternatives VISUAL and the Inspector's table around it. A
 * renderer that rewrote the sentence would make the report and `mlview issues`
 * disagree about the same node.
 *
 * **`Node.attrs`** is the forward-compatible source, and takes precedence when
 * it is populated, because a structured value is worth more than a parsed one:
 * `attrs` is `Record<string, string>` and needs no schema change — the same
 * channel the notebook cell map travelled on (11.29 N6). The reader is
 * deliberately tolerant of spelling, because the alternative is a renderer that
 * silently draws nothing when the analyzer picks the other word, and a silently
 * missing value is precisely the failure mode this round exists to end.
 *
 * WHAT IT WILL NOT DO. It never GUESSES a value: a node with none gets the
 * sublabel it always had. It never turns an unresolved value into a resolved one
 * — `unresolved` is drawn as an explicit "not resolved" rather than as absence,
 * because an empty sublabel and "MLView could not read this config" are the two
 * things this product must never confuse. And it de-rates nothing: a
 * config-sourced literal's confidence is the analyzer's to lower, and the card
 * shows the bucket it was given.
 *
 * Pure.
 */

import type { MLNode } from '../types.js';

/** Attribute spellings that carry the resolved value, in precedence order. */
const VALUE_KEYS = ['resolvedValue', 'resolved', 'configValue', 'value'];

/** Attribute spellings that carry where the value was read from. */
const FROM_KEYS = ['resolvedFrom', 'configSource', 'source', 'from'];

/** Attribute spellings that carry the one-of-N candidate list. */
const ALTERNATIVE_KEYS = ['alternatives', 'oneOf', 'candidates'];

/** Attribute spellings that say the analyzer looked and could not resolve it. */
const UNRESOLVED_KEYS = ['unresolved', 'configUnresolved'];

/** How many alternatives a card names before it counts the rest. */
export const MAX_ALTERNATIVES_SHOWN = 3;

/** `one of 3 in pkg.optims · build_adam, build_sgd` — `core/config_nodes.py`. */
const ONE_OF_RE = /^one of (\d+) in (.+?) · (.+)$/;

/** `selects pkg.optims.build_adam` — the resolved half of the same node. */
const SELECTS_RE = /^selects (.+)$/;

export interface ResolvedConfig {
  /** The literal, exactly as the analyzer resolved it. Empty when unresolved. */
  value: string;
  /** Where it came from — `conf.py:12`, `CONFIG["workers"]`, `pkg.optims`. */
  from: string;
  /** The one-of-N candidates, in the analyzer's order. Empty when there is one. */
  alternatives: string[];
  /** The N the analyzer stated, which is `alternatives.length` unless it capped. */
  statedCount: number;
  /** True when the analyzer looked and could not resolve it. Not the same as absent. */
  unresolved: boolean;
  /** Why it could not be resolved, when the analyzer said. */
  reason: string;
  /**
   * True when this was parsed out of the analyzer's OWN sublabel, in which case
   * the card keeps that sublabel verbatim: it is the wording the CLI and the
   * other two hosts print, and one renderer rewriting it would make the same
   * node read two different ways in two places.
   */
  fromSublabel: boolean;
}

function pick(attrs: Record<string, string>, keys: string[]): string {
  for (const key of keys) {
    const value = attrs[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

/**
 * Split a candidate list. The analyzer writes one string; both a comma and a
 * pipe are accepted as the separator, because a resolved symbol name never
 * contains either and guessing wrong would show one long candidate.
 */
function splitAlternatives(raw: string): string[] {
  const parts = raw.split(raw.indexOf('|') >= 0 ? '|' : ',');
  const out: string[] = [];
  for (const part of parts) {
    const text = part.trim();
    if (text) out.push(text);
  }
  return out;
}

/** The forward-compatible source: structured fields on `Node.attrs`. */
function fromAttrs(node: MLNode): ResolvedConfig | null {
  const attrs = node.attrs || {};
  const value = pick(attrs, VALUE_KEYS);
  const alternativesRaw = pick(attrs, ALTERNATIVE_KEYS);
  const unresolvedRaw = pick(attrs, UNRESOLVED_KEYS);
  const alternatives = alternativesRaw ? splitAlternatives(alternativesRaw) : [];
  const unresolved = unresolvedRaw === 'true' || unresolvedRaw === '1' || (!!unresolvedRaw && !value);
  if (!value && !alternatives.length && !unresolved) return null;
  return {
    value,
    from: pick(attrs, FROM_KEYS),
    alternatives,
    statedCount: alternatives.length,
    unresolved,
    reason: unresolvedRaw && unresolvedRaw !== 'true' && unresolvedRaw !== '1' ? unresolvedRaw : '',
    fromSublabel: false,
  };
}

/** The source that exists today: the sentence `core/config_nodes.py` writes. */
function fromSublabel(node: MLNode): ResolvedConfig | null {
  const sub = (node.sublabel || '').trim();
  if (!sub) return null;
  const many = ONE_OF_RE.exec(sub);
  if (many) {
    const names = splitAlternatives(many[3]);
    return {
      value: '',
      from: many[2],
      alternatives: names,
      // The analyzer's own N, kept even if it ever names fewer than it counts:
      // "one of 8" over three rows is a true statement; "one of 3" would not be.
      statedCount: Number(many[1]) || names.length,
      unresolved: false,
      reason: '',
      fromSublabel: true,
    };
  }
  const one = SELECTS_RE.exec(sub);
  if (one) {
    return {
      value: node.fqn || one[1],
      from: '',
      alternatives: [],
      statedCount: 0,
      unresolved: false,
      reason: '',
      fromSublabel: true,
    };
  }
  return null;
}

/**
 * What this node says about a resolved configuration value, or `null` when it
 * says nothing at all — which is every node in a document written by an analyzer
 * that predates ANA-10.
 */
export function resolvedConfig(node: MLNode): ResolvedConfig | null {
  // RENDER-6: an authored node's label and detail are prose written by the
  // model. The renderer never reads a resolved value out of them.
  if (node.authored) return null;
  return fromAttrs(node) || fromSublabel(node);
}

/** True when this node resolved to one of several named symbols (ANA-10). */
export function isAlternatives(info: ResolvedConfig | null): boolean {
  return !!info && info.alternatives.length > 1;
}

/** The N to print: what the analyzer said, falling back to what it listed. */
export function alternativeCount(info: ResolvedConfig): number {
  return info.statedCount || info.alternatives.length;
}

/**
 * The card's sublabel, or `null` to leave whatever the document wrote.
 *
 * `name = 64` for a resolved literal, `one of 3: build_a, build_b, build_c` for
 * an alternatives node, and `not resolved` — never an empty string — when the
 * analyzer looked and could not. Always `null` when the information came out of
 * the analyzer's own sublabel: that sentence is already the answer, and it is
 * the one the CLI prints.
 */
export function configSublabel(node: MLNode): string | null {
  const info = resolvedConfig(node);
  if (!info || info.fromSublabel) return null;
  if (isAlternatives(info)) {
    const shown = info.alternatives.slice(0, MAX_ALTERNATIVES_SHOWN);
    const rest = alternativeCount(info) - shown.length;
    return 'one of ' + alternativeCount(info) + ': ' + shown.join(', ') + (rest > 0 ? ', +' + rest : '');
  }
  if (info.unresolved) return info.reason ? 'not resolved — ' + info.reason : 'not resolved';
  const name = node.var || node.label || '';
  // `batch_size = 64`, unless the label already IS the assignment, in which case
  // repeating the name would be the same redundancy the chip budget removes.
  if (!name || name === info.value || node.label.indexOf('=') >= 0) return info.value;
  return name + ' = ' + info.value;
}

/**
 * The spoken form, for the card's `aria-label`. Screen-reader users get the
 * provenance the sighted hover gets, rather than a bare number — and they get it
 * whichever source it came from, including the sublabel the card kept verbatim.
 */
export function configSpoken(node: MLNode): string | null {
  const info = resolvedConfig(node);
  if (!info) return null;
  if (isAlternatives(info)) {
    return (
      'resolves to one of ' + alternativeCount(info) + ': ' + info.alternatives.join(', ') +
      (info.from ? ', defined in ' + info.from : '')
    );
  }
  if (info.unresolved) return 'value not resolved' + (info.reason ? ', ' + info.reason : '');
  if (!info.value) return null;
  return 'resolved value ' + info.value + (info.from ? ', from ' + info.from : '');
}
