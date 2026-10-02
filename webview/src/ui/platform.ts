/**
 * Viewer M2 live fix: key labels that say what works on the reader's platform.
 *
 * A focused VS Code webview forwards every keydown to the workbench, which runs its own binding
 * for it as well (measured live in VS Code 1.139 on macOS: Cmd+B toggled the side bar as well as
 * the viewer's panel, Cmd+K started a chord, and Ctrl+2 brought the diagram's group to its second
 * tab). So the viewer binds only keys the workbench leaves alone: plain keys on the canvas, and
 * the find key, Cmd+F on macOS and Ctrl+F elsewhere. `Mod+` in a label is that key's modifier.
 */

/** True on macOS (VS Code's webview reports the host platform in its user agent). */
export function isMac(): boolean {
  try {
    if (typeof navigator === 'undefined') return false;
    const nav = navigator as Navigator & { userAgentData?: { platform?: string } };
    const platform = (nav.userAgentData && nav.userAgentData.platform) || nav.platform || nav.userAgent || '';
    return /mac/i.test(platform);
  } catch (_e) {
    return false;
  }
}

/**
 * A key as the shortcut sheet and the menus print it. `Mod+F` is `⌘F` on macOS and `Ctrl+F`
 * elsewhere; on macOS the other modifiers take VS Code's symbols too (`⇧0`, `⌥Enter`).
 */
export function keyLabel(key: string, mac: boolean = isMac()): string {
  if (!mac) return key.replace(/^Mod\+/, 'Ctrl+');
  return key.replace(/^Mod\+/, '⌘').replace(/^Ctrl\+/, '⌃').replace(/^Alt\+/, '⌥').replace(/^Shift\+/, '⇧');
}
