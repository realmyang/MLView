/**
 * The OS motion preference, read once and then watched.
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
 * Every access is wrapped: `window.matchMedia` is absent in jsdom by default and
 * a host may hand back a partial stub (no `addEventListener`).
 */

export type MotionMode = 'full' | 'reduced';

export const REDUCED_MOTION_QUERY = '(prefers-reduced-motion: reduce)';

/** The current OS preference. `full` whenever it cannot be determined. */
export function motionMode(): MotionMode {
  return matches(REDUCED_MOTION_QUERY) ? 'reduced' : 'full';
}

export function prefersReducedMotion(): boolean {
  return motionMode() === 'reduced';
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
    try {
      if (typeof window === 'undefined' || !window.matchMedia) return;
      const list = window.matchMedia(REDUCED_MOTION_QUERY);
      if (!list || typeof list.addEventListener !== 'function') return;
      const handler = () => {
        const next = motionMode();
        if (next === this.current) return;
        this.current = next;
        onChange(next);
      };
      list.addEventListener('change', handler);
      this.stop = () => {
        try {
          list.removeEventListener('change', handler);
        } catch (_e) {
          /* a host may already have torn the query down */
        }
      };
    } catch (_e) {
      /* a host without matchMedia keeps the mode it was born with */
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
