/**
 * The search box controller: query state, the hit list and its keyboard model.
 *
 * A plain case-insensitive substring match (amendment A6) over node label /
 * qualname / fqn / file / variable and issue title / code / message. The list
 * is a listbox; Up/Down move the cursor and Enter jumps to the hit.
 */

import { renderSearchResults, moveSearchCursor } from './searchbox.js';
import { searchGraph, SearchHit } from '../search.js';
import type { GraphIndex } from '../layout/model.js';

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
  private hits: SearchHit[] = [];
  private cursor = -1;

  constructor(input: HTMLInputElement, results: HTMLElement, host: SearchHost) {
    this.input = input;
    this.results = results;
    this.host = host;
  }

  /** Run a query typed into the box. */
  run(query: string): void {
    const index = this.host.index();
    this.hits = index ? searchGraph(index, query) : [];
    this.cursor = this.hits.length ? 0 : -1;
    this.render();
    this.host.onQueryChanged(query);
  }

  /** Set the box's text and run it — used by the host's `setFilter` message. */
  setQuery(query: string): void {
    this.input.value = query;
    this.run(query);
  }

  /** Empty the box and the hit list without announcing a query change. */
  clear(): void {
    this.input.value = '';
    this.hits = [];
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
    if (!this.hits.length) return;
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault();
      this.cursor = moveSearchCursor(this.cursor, this.hits.length, ev.key === 'ArrowDown' ? 1 : -1);
      this.render();
    } else if (ev.key === 'Enter') {
      ev.preventDefault();
      const hit = this.hits[Math.max(0, this.cursor)];
      if (hit) {
        this.host.activate(hit);
        this.hideResults();
      }
    }
  }

  private render(): void {
    renderSearchResults(this.results, this.input, this.input.value, this.hits, this.cursor, (hit) => {
      this.host.activate(hit);
      this.hideResults();
    });
  }
}
