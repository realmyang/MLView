/**
 * The search box controller: query state, the hit list and its keyboard model.
 *
 * A plain case-insensitive substring match (amendment A6) over node label /
 * qualname / fqn / file / variable and issue title / code / message. The list
 * is a listbox; Up/Down move the cursor and Enter jumps to the hit.
 */

import { renderSearchResults, moveSearchCursor } from './searchbox.js';
import { searchGraphDetailed, SearchHit, SearchResult } from '../search.js';
import type { GraphIndex } from '../layout/model.js';

/** The default budget, and the step "Show more" adds to it (VIEW-09b). */
export const SEARCH_PAGE = 40;

const EMPTY: SearchResult = { hits: [], total: 0, totalNodes: 0, totalIssues: 0, limit: SEARCH_PAGE, truncated: false };

export interface SearchHost {
  /** The graph to search, or null before the first document arrives. */
  index(): GraphIndex | null;
  /** Reveal what the user picked. */
  activate(hit: SearchHit): void;
  /** The query changed — the App mirrors it into the ViewState. */
  onQueryChanged(query: string): void;
  /** Escape in the search box returns focus to the diagram. */
  blurToCanvas(): void;
}

export class SearchController {
  private input: HTMLInputElement;
  private results: HTMLElement;
  private host: SearchHost;
  private result: SearchResult = EMPTY;
  private limit = SEARCH_PAGE;
  private cursor = -1;

  constructor(input: HTMLInputElement, results: HTMLElement, host: SearchHost) {
    this.input = input;
    this.results = results;
    this.host = host;
  }

  /** Run a query typed into the box. A new query resets the budget. */
  run(query: string): void {
    this.limit = SEARCH_PAGE;
    this.execute(query);
    this.host.onQueryChanged(query);
  }

  private execute(query: string): void {
    const index = this.host.index();
    this.result = index ? searchGraphDetailed(index, query, this.limit) : EMPTY;
    this.cursor = this.result.hits.length ? 0 : -1;
    this.render();
  }

  /** "Show more": raise the budget by one page and re-run the same query. */
  showMore(): void {
    this.limit += SEARCH_PAGE;
    this.execute(this.input.value);
  }

  /** What the list is currently showing — the App's read-only view of it. */
  get hits(): SearchHit[] {
    return this.result.hits;
  }

  /** Set the box's text and run it — used by the host's `setFilter` message. */
  setQuery(query: string): void {
    this.input.value = query;
    this.run(query);
  }

  /** Empty the box and the hit list without announcing a query change. */
  clear(): void {
    this.input.value = '';
    this.result = EMPTY;
    this.limit = SEARCH_PAGE;
    this.cursor = -1;
    this.render();
  }

  focus(): void {
    this.input.focus();
    this.input.select();
  }

  hideResults(): void {
    this.results.hidden = true;
  }

  handleKey(ev: KeyboardEvent): void {
    if (ev.key === 'Escape') {
      this.clear();
      this.host.onQueryChanged('');
      this.host.blurToCanvas();
      return;
    }
    const hits = this.result.hits;
    if (!hits.length) return;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      this.cursor = moveSearchCursor(this.cursor, hits.length, ev.key === 'ArrowDown' ? 1 : -1);
      this.render();
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      const hit = hits[Math.max(0, this.cursor)];
      if (hit) {
        this.host.activate(hit);
        this.hideResults();
      }
    }
  }

  private render(): void {
    renderSearchResults(this.results, this.input, {
      query: this.input.value,
      result: this.result,
      cursor: this.cursor,
      onPick: (hit) => {
        this.host.activate(hit);
        this.hideResults();
      },
      onShowMore: () => this.showMore(),
    });
  }
}
