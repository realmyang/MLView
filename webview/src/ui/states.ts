/**
 * Designed states: the empty states and the toast stack.
 * Never a blank canvas (R4.5).
 */

import { add, button, clear, el, on } from '../dom.js';
import type { Diagnostic, MLGraph } from '../types.js';

export function buildEmptyState(graph: MLGraph | null): HTMLElement {
  const root = el('div', 'mlv-state mlv-state--empty');
  root.setAttribute('role', 'status');
  const inner = add(root, el('div', 'mlv-state__inner'));
  add(inner, el('h2', 'mlv-state__title', 'No workflow steps'));
  add(
    inner,
    el(
      'p',
      'mlv-state__body',
      'This authored workflow does not contain any steps in the current scope.',
    ),
  );
  const diags: Diagnostic[] = graph ? graph.diagnostics || [] : [];
  if (diags.length) {
    const list = add(inner, el('ul', 'mlv-state__list'));
    for (const d of diags.slice(0, 8)) {
      add(list, el('li', '', d.kind + ' — ' + d.message));
    }
  } else if (graph) {
    add(inner, el('p', 'mlv-state__body', 'The author inspected ' + graph.workspace.filesAnalyzed + ' files.'));
  }
  return root;
}

/**
 * The FOURTH empty state (FEATURES 3.7): the scope resolved to nothing.
 *
 * The filter-empty state would say the wrong thing here — the filters are fine,
 * the selector simply named a part of the pipeline this codebase does not have,
 * which is itself a finding. Two ways out, both one click.
 */
export function buildScopeEmptyState(spec: string, onWiden: () => void, onClear: () => void): HTMLElement {
  const root = el('div', 'mlv-state mlv-state--empty mlv-state--scope');
  root.setAttribute('role', 'status');
  root.setAttribute('data-scope-empty', spec);
  const inner = add(root, el('div', 'mlv-state__inner'));
  add(inner, el('h2', 'mlv-state__title', 'Nothing in this scope'));
  add(inner, el('p', 'mlv-state__body', spec + ' matched no nodes in this analysis.'));
  const actions = add(inner, el('div', 'mlv-state__actions'));
  const widen = button('mlv-btn', 'Widen (+1 hop)');
  on(widen, 'click', onWiden);
  actions.appendChild(widen);
  const clearBtn = button('mlv-btn mlv-btn--primary', 'Clear scope');
  on(clearBtn, 'click', onClear);
  actions.appendChild(clearBtn);
  return root;
}

export function buildFilterEmptyState(onClear: () => void): HTMLElement {
  const root = el('div', 'mlv-state mlv-state--empty');
  root.setAttribute('role', 'status');
  const inner = add(root, el('div', 'mlv-state__inner'));
  add(inner, el('h2', 'mlv-state__title', 'No nodes match your filters'));
  const actions = add(inner, el('div', 'mlv-state__actions'));
  const btn = button('mlv-btn', 'Clear all filters');
  on(btn, 'click', onClear);
  actions.appendChild(btn);
  return root;
}

export class Toasts {
  readonly root: HTMLElement;
  private timers: any[] = [];

  constructor() {
    this.root = el('div', 'mlv-toasts');
    // Several messages exist ONLY as a toast ("Node not found in this graph").
    // An aria-hidden stack made them invisible to
    // assistive tech with no other surface to fall back on (MLV-R2-W10).
    // role="status" IS a polite live region; the explicit aria-live is left off
    // so the app's own announcer stays the only [aria-live] element.
    this.root.setAttribute('role', 'status');
  }

  show(text: string): void {
    const toast = el('div', 'mlv-toast', text);
    this.root.appendChild(toast);
    while (this.root.childElementCount > 3 && this.root.firstElementChild) {
      this.root.removeChild(this.root.firstElementChild);
    }
    const timer = setTimeout(() => {
      if (toast.parentNode === this.root) this.root.removeChild(toast);
    }, 4000);
    this.timers.push(timer);
  }

  destroy(): void {
    for (const t of this.timers) clearTimeout(t);
    this.timers = [];
    clear(this.root);
  }
}
