/**
 * The motion preference, read once and then watched: the OS media query AND, since viewer M2,
 * VS Code's own `vscode-reduce-motion` body class, which the editor sets on a webview when its
 * Reduce Motion setting is on. Either one means `reduced`. A user who turned Reduce Motion on in
 * VS Code but not in the OS used to get the full animation.
 *
 * The hover-intent timers deliberately do NOT read it (RENDER-19): they are
 * intent delays, not animation, and dropping them under `reduce` made every
 * card a pointer sweep crossed toggle the whole-canvas dim. What does need it:
 *
 *  - the flow layer must NEVER BUILD `.mlv-edge__flow` under `reduce`
 *    (CONTRACTS 11.13 rule 3). The blanket clamp in `styles/base.css` freezes an
 *    animation instead of removing it, which would park a 12 px charge stub at
 *    the outlet of every lit edge — a bug that reads as a rendering fault rather
 *    than as a respected preference. The stylesheet ALSO carries an explicit
 *    `display: none !important` for the element, so a stale node from a
 *    mid-session preference change cannot appear either.
 *
 * Viewer M2: VS Code's screen-reader class (`vscode-using-screen-reader`) counts as `reduced` too:
 * a reader listening to the diagram gains nothing from moving charges.
 *
 * Every access is wrapped: `window.matchMedia` is absent in jsdom by default and
 * a host may hand back a partial stub (no `addEventListener`).
 *
 * The stylesheet honours both signals too (base.css, flow.css), so the CSS transitions and the
 * blanket animation clamp follow the body class even where this module is not consulted.
 */

export type MotionMode = 'full' | 'reduced';

export const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

/** The class VS Code puts on a webview's <body> when its Reduce Motion setting applies. */
export const REDUCE_MOTION_CLASS = 'vscode-reduce-motion';

/**
 * Viewer M2: the class VS Code puts on a webview's <body> while its screen-reader optimisation is
 * on (`editor.accessibilitySupport`). The viewer then skips motion, as under Reduce Motion, and
 * announces a selection by its claim (app.ts).
 */
export const SCREEN_READER_CLASS = 'vscode-using-screen-reader';

/** The current preference. `full` whenever it cannot be determined. */
export function motionMode(): MotionMode {
  return matches(REDUCED_MOTION_QUERY) || bodyAsksStillness() ? 'reduced' : 'full';
}

/** True while VS Code says a screen reader is in use (the body class above). */
export function screenReaderActive(): boolean {
  return bodyHas(SCREEN_READER_CLASS);
}

function bodyAsksStillness(): boolean {
  return bodyHas(REDUCE_MOTION_CLASS) || bodyHas(SCREEN_READER_CLASS);
}

function bodyHas(name: string): boolean {
  try {
    const body = typeof document !== 'undefined' ? document.body : null;
    return !!body && body.classList.contains(name);
  } catch (_e) {
    return false;
  }
}

function matches(query: string): boolean {
  try {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    const list = window.matchMedia(query);
    return !!(list && list.matches);
  } catch (_e) {
    return false;
  }
}

/**
 * Watch the preference. `onChange` fires only when the mode actually flips, so a
 * host that re-emits the media query never causes a re-render.
 */
export class MotionWatcher {
  private current: MotionMode;
  private stop: (() => void) | null = null;

  constructor(onChange: (mode: MotionMode) => void) {
    this.current = motionMode();
    const handler = () => {
      const next = motionMode();
      if (next === this.current) return;
      this.current = next;
      onChange(next);
    };
    const stops: (() => void)[] = [];
    try {
      const list = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(REDUCED_MOTION_QUERY) : null;
      if (list && typeof list.addEventListener === 'function') {
        list.addEventListener('change', handler);
        stops.push(() => list.removeEventListener('change', handler));
      }
    } catch (_e) {
      /* a host without matchMedia keeps the mode it was born with */
    }
    // VS Code rewrites the body classes when the setting (or the theme) changes.
    try {
      const body = typeof document !== 'undefined' ? document.body : null;
      if (body && typeof MutationObserver === 'function') {
        const observer = new MutationObserver(handler);
        observer.observe(body, { attributes: true, attributeFilter: ['class'] });
        stops.push(() => observer.disconnect());
      }
    } catch (_e) {
      /* no observer: the class is still read at mount and on every media-query change */
    }
    if (stops.length) {
      this.stop = () => {
        for (const stop of stops) {
          try {
            stop();
          } catch (_e) {
            /* a host may already have torn the query down */
          }
        }
      };
    }
  }

  get mode(): MotionMode {
    return this.current;
  }

  destroy(): void {
    if (this.stop) this.stop();
    this.stop = null;
  }
}
