/**
 * DOM helpers. The renderer builds every element with document.createElement /
 * createElementNS / textContent — never a markup-string assignment (CONTRACTS
 * section 8, "non-negotiable build rules"). The SVG namespace is assembled at
 * runtime from parts so the bundle contains no scheme-and-slashes literal.
 * `test/bundle.test.mjs` checks the built bundle for both rules.
 */

import { authoredCell, cellRef, locLabel, locParts, locTitle } from './notebook.js';
import type { LocLike } from './notebook.js';

export const SVG_NS = ['http', '//www.w3.org/2000/svg'].join(':');
/**
 * SMIL's `<mpath>` reference is `href` in SVG 2 and `xlink:href` in SVG 1.1;
 * both are written, and the legacy one has to land in the XLink NAMESPACE (a
 * plain `setAttribute('xlink:href')` lands in no namespace and is ignored by
 * every renderer that only implements SVG 1.1). Assembled from parts for the
 * same reason as SVG_NS (`test/bundle.test.mjs`).
 */
export const XLINK_NS = ['http', '//www.w3.org/1999/xlink'].join(':');

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  cls?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function svg(tag: string, attrs?: Record<string, string | number>): SVGElement {
  const node = document.createElementNS(SVG_NS, tag) as SVGElement;
  if (attrs) setAttrs(node, attrs);
  return node;
}

export function setAttrs(node: Element, attrs: Record<string, string | number>): void {
  for (const key of Object.keys(attrs)) node.setAttribute(key, String(attrs[key]));
}

export function clear(node: Element): void {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function add<T extends Node>(parent: Node, child: T): T {
  parent.appendChild(child);
  return child;
}

/** A button with a text label and an accessible name. */
export function button(cls: string, label: string, title?: string): HTMLButtonElement {
  const b = el('button', cls, label);
  b.type = 'button';
  b.setAttribute('aria-label', title || label);
  if (title) b.title = title;
  return b;
}

/** Icon-only button whose visible content is supplied by the caller. */
export function iconButton(cls: string, title: string): HTMLButtonElement {
  const b = el('button', cls);
  b.type = 'button';
  b.title = title;
  b.setAttribute('aria-label', title);
  return b;
}

export function on<K extends keyof HTMLElementEventMap>(
  target: HTMLElement | Document | Window,
  type: K | string,
  handler: (ev: any) => void,
  opts?: AddEventListenerOptions | boolean,
): () => void {
  target.addEventListener(type as string, handler as EventListener, opts as any);
  return () => target.removeEventListener(type as string, handler as EventListener, opts as any);
}

/** Middle-truncate long qualified names so both ends stay readable. */
export function middleTruncate(text: string, max: number): string {
  if (text.length <= max) return text;
  const keep = max - 1;
  const head = Math.ceil(keep * 0.6);
  const tail = keep - head;
  return text.slice(0, head) + '…' + text.slice(text.length - tail);
}

export function debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T & { cancel(): void } {
  let handle: any = null;
  const wrapped = ((...args: any[]) => {
    if (handle !== null) clearTimeout(handle);
    handle = setTimeout(() => {
      handle = null;
      fn(...args);
    }, ms);
  }) as T & { cancel(): void };
  wrapped.cancel = () => {
    if (handle !== null) clearTimeout(handle);
    handle = null;
  };
  return wrapped;
}

/**
 * Where something is, in one string, for every surface that shows a location.
 *
 * `train.py:27` as it always was — and `notebooks/leak.ipynb > cell 3 : 4` when
 * the location carries a cell mapping (NB). The translation itself lives in
 * `notebook.ts`; this stays the name the twelve call sites already import.
 */
export function fileLine(loc: LocLike): string {
  return locLabel(loc);
}

/**
 * A `<span>` carrying that label, plus the two things a test and a hover need:
 * `data-cell` when the location is inside a notebook cell, and a `title` naming
 * the flat line the label was translated from. For a `.py` location this is
 * exactly `el('span', cls, file + ':' + line)` and nothing more.
 */
export function locSpan(cls: string, loc: LocLike, tag: 'span' | 'div' = 'span'): HTMLElement {
  const span = el(tag, cls + (cls ? ' ' : '') + 'mlv-loc');
  const parts = locParts(loc);
  // Two children, not one string: `.mlv-loc__file` is the shrinkable half and
  // `.mlv-loc__at` is not, so a card too narrow for the whole label loses the
  // directory rather than the cell number (or, on a `.py` path, the line). The
  // element's textContent is still exactly `locLabel(loc)`.
  add(span, el('span', 'mlv-loc__file', parts.head));
  add(span, el('span', 'mlv-loc__at', parts.tail));
  const ref = cellRef(loc);
  const authored = ref ? null : authoredCell(loc);
  if (ref) {
    span.setAttribute('data-cell', String(ref.cell));
    span.setAttribute('data-cell-line', String(ref.line));
    span.title = locTitle(loc);
  } else if (authored) {
    // VIEWUI-8: the zero-based index the contract carries.
    span.setAttribute('data-cell', String(authored.cell));
    span.title = locTitle(loc);
  }
  return span;
}
