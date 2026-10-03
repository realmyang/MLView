/**
 * The host's banner once the viewer is mounted (viewer M1): stale files, the workspace-root hint,
 * a refused update, unsaved edits. Before the mount the host bootstrap draws the same text in a
 * `<pre>`; afterwards it is drawn here, under the authored header, with an icon and, for the root
 * hint, its two actions.
 *
 * The text is the host's, set with textContent. Colour marks problems only (a warning or a
 * refused update); every kind also says what it is in words, and problems carry an icon.
 */

import { add, button, clear, el, on } from '../dom.js';
import { uiIcon } from '../icons.js';

/** Codes whose banner reports a refused update or an unreadable artifact. */
const ERROR_CODES = new Set(['invalid', 'parse', 'missing', 'unreadable', 'obsolete', 'same-id-changed']);
/** Codes whose banner reports source files that no longer match, or a wrong workspace root. */
const WARN_CODES = new Set(['stale', 'root-hint']);

export interface HostNoticeCallbacks {
  /** The root hint's actions; the host decides which folder. */
  onWorkspaceHint(action: 'add' | 'open'): void;
  /** Viewer M3: the stale notice's "Review affected claims" starts the walk on Changed files. */
  onReviewAffected(): void;
}

export class HostNotice {
  readonly root: HTMLElement;
  private icon: HTMLElement;
  private text: HTMLElement;
  private actions: HTMLElement;
  private cb: HostNoticeCallbacks;
  /** Viewer M3: "Review affected claims", offered under a stale notice while claims cite those files. */
  private review: HTMLButtonElement;
  private reviewCount = 0;
  private walking = false;
  private message = '';
  private codes: readonly string[] = [];

  constructor(cb: HostNoticeCallbacks) {
    this.cb = cb;
    this.root = el('div', 'mlv-hostnotice');
    this.root.setAttribute('role', 'status');
    this.root.hidden = true;
    this.icon = add(this.root, el('span', 'mlv-hostnotice__icon'));
    this.icon.setAttribute('aria-hidden', 'true');
    this.text = add(this.root, el('p', 'mlv-hostnotice__text'));
    this.actions = add(this.root, el('div', 'mlv-hostnotice__actions'));
    this.review = button('mlv-btn mlv-hostnotice__review', 'Review affected claims');
    this.review.setAttribute('data-notice-action', 'review');
    on(this.review, 'click', () => this.cb.onReviewAffected());
  }

  /**
   * Viewer M3: how many claims cite a changed or missing file (the walk's Changed files count), and
   * whether the walk is running. The action is offered under the host's `stale` notice when that
   * count is above zero and the walk is not already running (it would be a second tab stop before
   * the diagram, and the walk bar has the filter).
   */
  setReview(count: number, walking: boolean): void {
    if (count === this.reviewCount && walking === this.walking) return;
    this.reviewCount = count;
    this.walking = walking;
    this.syncActions();
  }

  /** Show the host's text, or hide the notice when it is empty. */
  update(message: string, codes: readonly string[] | undefined): void {
    const list = codes || [];
    const kind = list.some((code) => ERROR_CODES.has(code)) ? 'error' : list.some((code) => WARN_CODES.has(code)) ? 'warn' : 'info';
    this.root.hidden = !message;
    this.root.className = 'mlv-hostnotice mlv-hostnotice--' + kind;
    this.root.setAttribute('data-codes', list.join(' '));
    this.text.textContent = message;
    clear(this.icon);
    if (kind !== 'info') this.icon.appendChild(uiIcon('warning', 14));
    this.message = message;
    this.codes = list;
    this.syncActions();
  }

  private syncActions(): void {
    const message = this.message;
    const list = this.codes;
    clear(this.actions);
    this.actions.hidden = true;
    if (message && list.indexOf('stale') >= 0 && this.reviewCount > 0 && !this.walking) {
      this.review.title = 'Walk the ' + this.reviewCount + (this.reviewCount === 1 ? ' claim' : ' claims') + ' whose quotes cite a file that changed or went missing; nothing stale is opened';
      this.actions.appendChild(this.review);
      this.actions.hidden = false;
    }
    if (message && list.indexOf('root-hint') >= 0) {
      const addBtn = button('mlv-btn mlv-btn--primary', 'Add folder to workspace');
      addBtn.setAttribute('data-workspace-hint', 'add');
      on(addBtn, 'click', () => this.cb.onWorkspaceHint('add'));
      const openBtn = button('mlv-btn', 'Open folder');
      openBtn.setAttribute('data-workspace-hint', 'open');
      openBtn.title = 'Open the folder the citations resolve against in a new window';
      on(openBtn, 'click', () => this.cb.onWorkspaceHint('open'));
      this.actions.append(addBtn, openBtn);
      this.actions.hidden = false;
    }
  }
}
