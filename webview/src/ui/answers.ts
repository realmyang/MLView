/**
 * The Pipeline Answer Card (MLV-P1).
 *
 * The product's headline is answering four questions in 90 seconds; the
 * practitioner walkthrough measured **2 of 4 answered from the first screen,
 * both by the rail rather than the diagram**, with two of them roughly 1600 px
 * below the fold and nothing in any host stating the answers in words.
 *
 * The analyzer composes an `answers` block deterministically from the graph
 * (`emit/answers.py` — no model, so it is identical in all three hosts and stays
 * offline). This renders it as a collapsible card pinned above the canvas, each
 * sentence carrying its `file:line` citations as buttons that post
 * `openLocation` exactly as every other location in the viewer does.
 *
 * Three rules the card must not break:
 *
 *   - **Absent means absent.** No `answers` block, no card — never an empty
 *     card, and never a card that invents a sentence the emitter did not write.
 *     A block that carries only two of the four answers draws two rows.
 *   - **Low confidence is stated, not hidden.** MLV-P1 guards at 0.6: below it
 *     the emitter says "could not determine", and the card marks the row so a
 *     reader can see which answers are load-bearing.
 *   - **It costs no tab stop before the canvas.** VIEW-12 requires the canvas
 *     within four Tab presses of the top of the document, so this card is placed
 *     AFTER the canvas in DOM order and lifted above it visually with
 *     `order: -1` on the flex column in `styles/chrome.css`. Reading order
 *     therefore goes diagram, then answers; tab order goes toolbar, search,
 *     canvas, answers.
 */

import { add, button, clear, el, fileLine, on } from '../dom.js';
import { uiIcon } from '../icons.js';
import { ANSWER_ROWS } from '../types.js';
import type { Answer, AnswerLoc, Answers } from '../types.js';

/** Below this the emitter says "could not determine"; the card says so too. */
export const ANSWER_MIN_CONFIDENCE = 0.6;

export interface AnswersCallbacks {
  onToggle(open: boolean): void;
  onOpen(loc: AnswerLoc): void;
}

let answersSeq = 0;

export class AnswersCard {
  readonly root: HTMLElement;
  private head: HTMLButtonElement;
  private bodyEl: HTMLElement;
  private countEl: HTMLElement;
  private cb: AnswersCallbacks;
  private openState = true;

  constructor(cb: AnswersCallbacks) {
    this.cb = cb;
    const uid = 'mlv-answers' + ++answersSeq;
    this.root = el('section', 'mlv-answers');
    this.root.setAttribute('data-answers', '1');
    this.root.setAttribute('aria-labelledby', uid + '-head');
    this.root.hidden = true;

    this.head = el('button', 'mlv-answers__head') as HTMLButtonElement;
    this.head.type = 'button';
    this.head.id = uid + '-head';
    this.head.setAttribute('aria-expanded', 'true');
    this.head.setAttribute('aria-controls', uid + '-body');
    this.head.appendChild(uiIcon('chevron', 12));
    add(this.head, el('span', 'mlv-answers__title', 'What this pipeline does'));
    this.countEl = add(this.head, el('span', 'mlv-answers__count', ''));
    on(this.head, 'click', () => this.cb.onToggle(!this.openState));
    this.root.appendChild(this.head);

    this.bodyEl = add(this.root, el('div', 'mlv-answers__body'));
    this.bodyEl.id = uid + '-body';
  }

  get open(): boolean {
    return this.openState;
  }

  /**
   * Draw the block, or hide the card entirely when there is none.
   *
   * `yielded` is HOSTS-UX-R2-06: on a document whose banners and chip row
   * already fill the top of the window this card starts CLOSED, so the reader
   * gets the diagram instead. Nothing is hidden by it — the header still states
   * `1 of 4 answered · 3 not detected`, which is the line a reader scans, and
   * one press opens the rest. The flag only changes the DEFAULT and the
   * sentence the header's tooltip gives for it; a reader who opens the card
   * keeps it open, here and on the next report (`ViewState.answersOpen`).
   */
  update(answers: Answers | undefined, open: boolean, yielded = false): void {
    this.openState = open;
    const rows = readableRows(answers);
    this.root.hidden = rows.length === 0;
    this.root.setAttribute('data-answers-count', String(rows.length));
    if (!rows.length) {
      clear(this.bodyEl);
      return;
    }
    this.head.setAttribute('aria-expanded', open ? 'true' : 'false');
    this.root.setAttribute('data-answers-yielded', yielded ? '1' : '0');
    this.head.title =
      (open ? 'Hide' : 'Show') + ' the four answers this analysis composed' +
      (yielded && !open
        ? ' — it starts closed on this report because the notes above it already fill the top of the window'
        : '');
    if (open) this.root.classList.add('is-open');
    else this.root.classList.remove('is-open');
    // DGRG-12: the counter says what the answers say, never more.
    this.countEl.textContent = answeredLabel(rows);
    this.countEl.title =
      'An answer counts as answered when it names a place in the code. The rest say so in words: ' +
      'the emitter found nothing to point at.';
    this.root.setAttribute('data-answers-answered', String(rows.filter((r) => located(r.answer)).length));
    this.bodyEl.hidden = !open;

    clear(this.bodyEl);
    const list = add(this.bodyEl, el('ol', 'mlv-answers__list'));
    for (const row of rows) {
      const item = add(list, el('li', 'mlv-answers__item'));
      item.setAttribute('data-answer', row.key);
      item.setAttribute('data-answer-located', located(row.answer) ? '1' : '0');
      add(item, el('span', 'mlv-answers__q', row.question));
      const sentence = add(item, el('p', 'mlv-answers__sentence', row.answer.sentence));
      sentence.setAttribute('data-answer-sentence', row.key);
      const confidence = typeof row.answer.confidence === 'number' ? row.answer.confidence : 1;
      if (confidence < ANSWER_MIN_CONFIDENCE) {
        const chip = add(item, el('span', 'mlv-chip mlv-chip--conf mlv-chip--conf-possible', 'low confidence'));
        chip.title = 'The analyzer would not assert this: confidence ' + confidence.toFixed(2) + ' is under ' + ANSWER_MIN_CONFIDENCE + '.';
      }
      const locs = Array.isArray(row.answer.locs) ? row.answer.locs : [];
      if (!locs.length) continue;
      const cites = add(item, el('span', 'mlv-answers__cites'));
      for (const loc of locs) {
        if (!loc || typeof loc.file !== 'string' || typeof loc.line !== 'number') continue;
        const link = button('mlv-link mlv-link--inline', fileLine(loc), 'Open ' + fileLine(loc));
        link.setAttribute('data-answer-loc', fileLine(loc));
        on(link, 'click', (ev: Event) => {
          ev.stopPropagation();
          this.cb.onOpen(loc);
        });
        cites.appendChild(link);
      }
    }
  }
}

/**
 * DGRG-12 — the counter over the four answers says what the answers say.
 *
 * It read `rows.length + ' of 4 answered'`, which counted rows RENDERED rather
 * than questions answered. On the stable-baselines3 report the header said
 * "What this pipeline does · 4 of 4 answered" above three rows that begin "No
 * data entry was detected…", "No loss function was detected…" and "No
 * evaluation stage was detected…". Every sentence under it was honest; the one
 * line a reader scans was not.
 *
 * `emit/answers.py` composes an answer from NODES: an answer that found
 * something carries `locs`/`nodeIds` and a confidence, and one that found
 * nothing carries neither and `confidence: 0.0`. So "did this name a place in
 * the code" is the emitter's own signal, read rather than guessed — and the
 * rows that did not are counted as what they say, not silently as answers.
 */
function answeredLabel(rows: AnswerRow[]): string {
  const answered = rows.filter((r) => located(r.answer)).length;
  const missing = rows.length - answered;
  return (
    answered + ' of ' + ANSWER_ROWS.length + ' answered' +
    (missing > 0 ? ' · ' + missing + ' not detected' : '')
  );
}

/** True when the emitter had somewhere in the code to point at. */
function located(answer: Answer): boolean {
  const locs = Array.isArray(answer.locs) ? answer.locs.length : 0;
  const nodes = Array.isArray(answer.nodeIds) ? answer.nodeIds.length : 0;
  return locs + nodes > 0;
}

interface AnswerRow {
  key: string;
  question: string;
  answer: Answer;
}

/**
 * The four known keys, in the card's fixed order, keeping only the ones that
 * actually carry a sentence. A newer emitter that adds a fifth field is ignored
 * rather than drawn half-understood (invariant 1.1/6).
 */
function readableRows(answers: Answers | undefined): AnswerRow[] {
  if (!answers || typeof answers !== 'object') return [];
  const out: AnswerRow[] = [];
  for (const row of ANSWER_ROWS) {
    const answer = (answers as Record<string, Answer | undefined>)[row.key];
    if (!answer || typeof answer !== 'object') continue;
    if (typeof answer.sentence !== 'string' || !answer.sentence) continue;
    out.push({ key: row.key, question: row.question, answer });
  }
  return out;
}
