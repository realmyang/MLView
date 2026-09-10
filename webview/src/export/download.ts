/**
 * The standalone report's "save file" (VIEW-07), kept in its own module.
 *
 * It lives here rather than in `bridges.ts` for a reason the gate enforces:
 * `test/bridges.test.mjs` greps `bridges.ts` for `.click()`, `location.href =`
 * and `window.open`, because CONTRACTS 11.17 turns on that file containing no
 * way to move the document at all. A download anchor is NOT such a way — it
 * carries `download`, its href is a `blob:` of bytes this page just made, and a
 * host that refuses it drops the click without touching the frame — but the
 * grep is a blunt instrument on purpose and should stay blunt. So the one
 * anchor click in the viewer sits in a file whose whole job is that click, with
 * the rules it must obey written next to it:
 *
 *   1. It is only ever reached from an explicit export gesture.
 *   2. The href is always an object URL of local bytes; never a scheme, never a
 *      path, never anything a protocol handler could act on.
 *   3. The anchor always carries `download`, and the function refuses to click
 *      one that cannot (an engine without the attribute is a `false`, and the
 *      caller falls back to the clipboard).
 *   4. The anchor is created, clicked and removed inside one call. Nothing
 *      persists that a later gesture could re-trigger.
 */

/** True when the bytes were handed to the browser's download machinery. */
export function downloadBytes(bytes: Uint8Array, name: string, mime: string): boolean {
  const g: any = typeof globalThis === 'undefined' ? {} : globalThis;
  let url = '';
  try {
    if (typeof document === 'undefined' || !document.body) return false;
    if (typeof g.Blob !== 'function' || !g.URL || typeof g.URL.createObjectURL !== 'function') return false;
    const anchor = document.createElement('a');
    // Rule 3: an engine that ignores `download` would NAVIGATE to the blob.
    if (!('download' in anchor)) return false;
    const blob = new g.Blob([bytes], { type: mime });
    url = g.URL.createObjectURL(blob);
    anchor.href = url;
    anchor.download = name;
    anchor.rel = 'noopener';
    anchor.style.position = 'fixed';
    anchor.style.opacity = '0';
    anchor.setAttribute('aria-hidden', 'true');
    anchor.tabIndex = -1;
    document.body.appendChild(anchor);
    anchor.click();
    if (anchor.parentNode) anchor.parentNode.removeChild(anchor);
    // Long enough for the hand-off, short enough that a few exports in a row do
    // not pin their buffers for the session.
    setTimeout(() => revoke(url), 10000);
    return true;
  } catch (_e) {
    revoke(url);
    return false;
  }
}

function revoke(url: string): void {
  const g: any = typeof globalThis === 'undefined' ? {} : globalThis;
  try {
    if (url && g.URL && typeof g.URL.revokeObjectURL === 'function') g.URL.revokeObjectURL(url);
  } catch (_e) {
    /* already revoked, or a host without object URLs */
  }
}
