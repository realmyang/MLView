/**
 * Wait for the state a test is actually about, not for a number of milliseconds
 * (HEALTH-03).
 *
 * Five assertions used to sit behind `await new Promise((r) => setTimeout(r, 320))`
 * — one debounce interval plus 20 ms of hope. On a loaded 2-core CI runner that
 * is a coin flip in one direction and 320 ms of dead time in the other, and the
 * failure it produces ("state was saved (debounced) after a change") names the
 * feature rather than the machine.
 *
 * `until()` polls the condition instead, so the test finishes as soon as the
 * viewer has done the thing and only gives up after a timeout long enough that
 * reaching it means something is genuinely broken.
 */

const POLL_MS = 5;
const DEFAULT_TIMEOUT_MS = 5000;

/**
 * Resolve with the first truthy value `probe()` returns.
 *
 * @param {() => any} probe        cheap, side-effect-free, returns falsy until ready
 * @param {string}    what         named in the timeout message
 * @param {{timeout?: number}} [opts]
 */
export async function until(probe, what, opts = {}) {
  const timeout = opts.timeout ?? DEFAULT_TIMEOUT_MS;
  const deadline = Date.now() + timeout;
  for (;;) {
    let value;
    try {
      value = probe();
    } catch (err) {
      // A probe that reads through a half-built object may throw once; only the
      // deadline decides that the wait has failed.
      value = null;
      if (Date.now() > deadline) throw err;
    }
    if (value) return value;
    if (Date.now() > deadline) {
      throw new Error('timed out after ' + timeout + ' ms waiting for ' + what);
    }
    await new Promise((r) => setTimeout(r, POLL_MS));
  }
}

/**
 * Wait for a deferred single-click to land, and answer how many did.
 *
 * `CanvasView` holds a collapsible node's single click back by DOUBLE_CLICK_MS so
 * that a double click cannot also open the file (MLV-R1-010). Proving that a
 * double click posted *nothing* means proving a timer that was never scheduled
 * did not fire — so instead of sleeping past the interval, click the same target
 * once more and wait for THAT deferred `openLocation` to arrive. Timers of equal
 * delay fire in registration order, so once the control click has landed, any
 * stray from the interaction under test would already be in the log.
 *
 * @returns {Promise<number>} the openLocation count once the control click landed
 */
export async function afterDeferredClick(ctx, target) {
  const openLocations = () => ctx.posted.filter((m) => m.type === 'openLocation').length;
  const before = openLocations();
  target.dispatchEvent(new ctx.window.MouseEvent('click', { bubbles: true, cancelable: true, detail: 1 }));
  await until(() => openLocations() > before, 'the control click to post its deferred openLocation');
  return openLocations();
}
