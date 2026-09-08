/**
 * The search results list. A plain listbox over the substring matches from
 * search.ts (amendment A6 trims the fuzzy palette to exactly this).
 */

import { add, button, clear, el, on } from '../dom.js';
import { severityGlyph } from '../markers.js';
import type { SearchHit, SearchResult } from '../search.js';

/** The id of the nth option — the combobox's `aria-activedescendant` target. */
export function optionId(list: HTMLElement, index: number): string {
  return (list.id || 'mlv-search-results') + '-opt-' + index;
}

export interface SearchListView {
  query: string;
  result: SearchResult;
  cursor: number;
  onPick(hit: SearchHit): void;
  /** Raise the budget and re-run — the "show more" affordance (VIEW-09b). */
  onShowMore(): void;
}

export function renderSearchResults(list: HTMLElement, input: HTMLInputElement, view: SearchListView): void {
  const { query, result, cursor, onPick } = view;
  const hits = result.hits;
  clear(list);
  if (!query) {
    list.hidden = true;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    return;
  }
  list.hidden = false;
  input.setAttribute('aria-expanded', 'true');
  if (!hits.length) {
    add(list, el('li', 'mlv-result__empty', 'No matches'));
    input.removeAttribute('aria-activedescendant');
    return;
  }
  hits.forEach((hit, i) => {
    const li = add(list, el('li'));
    li.setAttribute('role', 'presentation');
    const row = el('button', 'mlv-result') as HTMLButtonElement;
    row.type = 'button';
    row.id = optionId(list, i);
    row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', i === cursor ? 'true' : 'false');
    if (hit.severity) row.appendChild(severityGlyph(hit.severity, 12, ''));
    add(row, el('span', 'mlv-result__label', hit.label));
    add(row, el('span', 'mlv-result__meta', hit.meta));
    // VIEW-09a: the pinned `path:line` hit says WHY it is first, and whether the
    // line is inside that node or merely the nearest one in the file.
    if (hit.location) {
      const where = hit.location.line === null ? 'first in file' : 'line ' + hit.location.line;
      const chip = add(row, el('span', 'mlv-result__jump', hit.location.exact ? 'jump to ' + where : 'nearest to ' + where));
      chip.setAttribute('data-search-jump', hit.location.exact ? 'exact' : 'nearest');
      li.setAttribute('data-search-pinned', '1');
    }
    on(row, 'click', () => onPick(hit));
    li.appendChild(row);
  });

  // VIEW-09b. `pipeline_5` and `loss` each returned exactly 40 rows with nothing
  // saying the list had been cut — a correctness bug in a search box.
  if (result.truncated) {
    const foot = add(list, el('li', 'mlv-result__foot'));
    foot.setAttribute('role', 'presentation');
    foot.setAttribute('data-search-truncated', String(result.total));
    add(foot, el('span', '', 'showing ' + hits.length + ' of ' + result.total));
    const more = button('mlv-link mlv-link--inline', 'Show more', 'Show more search results');
    more.setAttribute('data-search-more', '1');
    on(more, 'click', (ev: Event) => {
      ev.preventDefault();
      view.onShowMore();
    });
    foot.appendChild(more);
  }
  // The outer half of the ARIA 1.2 combobox pattern is useless without the inner
  // half: focus stays in the text field, so the only way an assistive technology
  // can follow the cursor is aria-activedescendant (MLV-R2-W07).
  if (cursor >= 0 && cursor < hits.length) input.setAttribute('aria-activedescendant', optionId(list, cursor));
  else input.removeAttribute('aria-activedescendant');
}

/** Arrow / Enter handling for the results list; returns the new cursor index. */
export function moveSearchCursor(cursor: number, total: number, delta: number): number {
  if (total <= 0) return -1;
  return (cursor + delta + total) % total;
}
