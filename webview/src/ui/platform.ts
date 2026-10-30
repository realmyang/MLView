/**
 * Key labels that say what works on the reader's platform.
 *
 * A focused VS Code webview forwards every keydown to the workbench, which runs its own binding
 * for the key as well, even when the viewer has handled it. The workbench binds Escape too, so
 * the panel's bootstrap (`render()` in vscode-extension/src/authoredPanel.ts) stops an Escape
 * the viewer used before it reaches the window. The canvas's key map (handleCanvasKey in
 * ui/keymap.ts) answers keys without Ctrl, Cmd or Alt, Alt+Enter, and F with Ctrl or Cmd (the
 * find key, on every platform); it leaves every other chord to the workbench. `Mod+` in a label
 * is printed ⌘ on macOS and Ctrl+ elsewhere (`keyLabel`).
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
