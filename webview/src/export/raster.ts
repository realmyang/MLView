/**
 * SVG → PNG, at 2× (VIEW-07).
 *
 * The PNG is drawn FROM the exported SVG, never from a second traversal of the
 * scene: whatever the SVG says, the raster says, at twice the resolution. That
 * is why the no-external-reference rule in `export/svg.ts` is load-bearing here
 * too — an `<img>` carrying an SVG that fetches anything taints the canvas, and
 * `toDataURL` then throws a SecurityError instead of returning bytes.
 *
 * The source is a `data:` URI rather than a `blob:` one on purpose: a VS Code
 * webview's CSP is written per scheme, `img-src blob:` is not something this
 * renderer may assume, and a data URI needs no revocation and no object-URL
 * lifetime to get wrong.
 *
 * Everything degrades to `null`: jsdom has no canvas, an unsupported host has
 * no `toDataURL`, and a caller that gets `null` says so rather than claiming a
 * file it never produced.
 */

const SVG_MIME = 'image/svg+xml';
const PNG_MIME = 'image/png';

export interface RasterResult {
  /** Raw base64, with no `data:` prefix — the shape `exportFile` carries. */
  base64: string;
  width: number;
  height: number;
  scale: number;
}

/** The SVG as an inline image source. Contains no reference to anything. */
export function svgDataUri(svg: string): string {
  return 'data:' + SVG_MIME + ';charset=utf-8,' + encodeURIComponent(svg);
}

/**
 * Rasterise. Rejected promises are turned into `null` by the caller's `catch`;
 * this function itself rejects only through the image's own error event, which
 * is what a malformed SVG produces.
 */
export function rasterize(svg: string, width: number, height: number, scale = 2): Promise<RasterResult | null> {
  return new Promise((resolve) => {
    if (typeof document === 'undefined' || typeof Image === 'undefined') {
      resolve(null);
      return;
    }
    let canvas: HTMLCanvasElement;
    let ctx: CanvasRenderingContext2D | null;
    try {
      canvas = document.createElement('canvas');
      canvas.width = Math.max(1, Math.round(width * scale));
      canvas.height = Math.max(1, Math.round(height * scale));
      ctx = typeof canvas.getContext === 'function' ? canvas.getContext('2d') : null;
    } catch (_e) {
      resolve(null);
      return;
    }
    if (!ctx || typeof canvas.toDataURL !== 'function') {
      resolve(null);
      return;
    }
    const image = new Image();
    let settled = false;
    const done = (value: RasterResult | null) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };
    image.onload = () => {
      try {
        ctx!.setTransform(scale, 0, 0, scale, 0, 0);
        ctx!.drawImage(image, 0, 0, width, height);
        const url = canvas.toDataURL(PNG_MIME);
        const comma = url.indexOf(',');
        done(comma < 0 ? null : { base64: url.slice(comma + 1), width: canvas.width, height: canvas.height, scale });
      } catch (_e) {
        // A tainted canvas throws here. It should be unreachable — the SVG
        // carries no external reference — so the honest answer is "no PNG".
        done(null);
      }
    };
    image.onerror = () => done(null);
    try {
      image.src = svgDataUri(svg);
    } catch (_e) {
      done(null);
    }
  });
}

/*
 * Base64 and UTF-8, written out rather than borrowed.
 *
 * `TextEncoder` / `TextDecoder` are absent from more hosts than one would
 * expect — jsdom 26 has neither on its window, which is where the gates run —
 * and a viewer that silently produces an empty file on such a host is worse
 * than one that never offered the button. `btoa` / `atob` are used when the
 * host has them because they are faster on a megabyte of markup, and the
 * hand-written path below is the answer when it does not.
 */

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

/** UTF-8 encode without TextEncoder. Lone surrogates become U+FFFD. */
export function utf8Bytes(text: string): Uint8Array {
  const out: number[] = [];
  for (let i = 0; i < text.length; i++) {
    let code = text.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = i + 1 < text.length ? text.charCodeAt(i + 1) : 0;
      if (next >= 0xdc00 && next <= 0xdfff) {
        code = 0x10000 + ((code - 0xd800) << 10) + (next - 0xdc00);
        i++;
      } else {
        code = 0xfffd;
      }
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      code = 0xfffd;
    }
    if (code < 0x80) out.push(code);
    else if (code < 0x800) out.push(0xc0 | (code >> 6), 0x80 | (code & 63));
    else if (code < 0x10000) out.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 63), 0x80 | (code & 63));
    else out.push(0xf0 | (code >> 18), 0x80 | ((code >> 12) & 63), 0x80 | ((code >> 6) & 63), 0x80 | (code & 63));
  }
  return new Uint8Array(out);
}

/** UTF-8 decode without TextDecoder. Malformed sequences become U+FFFD. */
export function utf8Text(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length; ) {
    const b = bytes[i];
    let code: number;
    let size: number;
    if (b < 0x80) {
      code = b;
      size = 1;
    } else if ((b & 0xe0) === 0xc0) {
      code = b & 0x1f;
      size = 2;
    } else if ((b & 0xf0) === 0xe0) {
      code = b & 0x0f;
      size = 3;
    } else if ((b & 0xf8) === 0xf0) {
      code = b & 0x07;
      size = 4;
    } else {
      out += '�';
      i++;
      continue;
    }
    if (i + size > bytes.length) {
      out += '�';
      break;
    }
    for (let k = 1; k < size; k++) code = (code << 6) | (bytes[i + k] & 63);
    i += size;
    if (code > 0xffff) {
      code -= 0x10000;
      out += String.fromCharCode(0xd800 + (code >> 10), 0xdc00 + (code & 1023));
    } else {
      out += String.fromCharCode(code);
    }
  }
  return out;
}

export function bytesToBase64(bytes: Uint8Array): string {
  const g: any = typeof globalThis === 'undefined' ? {} : globalThis;
  if (typeof g.btoa === 'function') {
    let binary = '';
    // Chunked: `apply` on a megabyte-long argument list overflows the stack.
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode.apply(null, Array.prototype.slice.call(bytes.subarray(i, i + 0x8000)));
    }
    return g.btoa(binary);
  }
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i];
    const b = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const c = i + 2 < bytes.length ? bytes[i + 2] : 0;
    out += B64.charAt(a >> 2) + B64.charAt(((a & 3) << 4) | (b >> 4));
    out += i + 1 < bytes.length ? B64.charAt(((b & 15) << 2) | (c >> 6)) : '=';
    out += i + 2 < bytes.length ? B64.charAt(c & 63) : '=';
  }
  return out;
}

/** UTF-8 text → base64, for the SVG arm of `exportFile`. */
export function utf8ToBase64(text: string): string {
  return bytesToBase64(utf8Bytes(text));
}

/** base64 → bytes, for the download anchor and the clipboard image item. */
export function base64ToBytes(base64: string): Uint8Array {
  const g: any = typeof globalThis === 'undefined' ? {} : globalThis;
  if (typeof g.atob === 'function') {
    const binary = g.atob(base64);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i) & 0xff;
    return out;
  }
  const clean = String(base64).replace(/[^A-Za-z0-9+/]/g, '');
  const size = Math.floor((clean.length * 3) / 4);
  const out = new Uint8Array(size);
  let at = 0;
  for (let i = 0; i < clean.length; i += 4) {
    const n =
      (B64.indexOf(clean.charAt(i)) << 18) |
      (B64.indexOf(clean.charAt(i + 1)) << 12) |
      (Math.max(0, B64.indexOf(clean.charAt(i + 2))) << 6) |
      Math.max(0, B64.indexOf(clean.charAt(i + 3)));
    if (at < size) out[at++] = (n >> 16) & 0xff;
    if (at < size) out[at++] = (n >> 8) & 0xff;
    if (at < size) out[at++] = n & 0xff;
  }
  return out;
}

/** base64 of UTF-8 text → the text again, for the standalone copy fallback. */
export function base64ToUtf8(base64: string): string {
  return utf8Text(base64ToBytes(base64));
}

export const MIME = { svg: SVG_MIME, png: PNG_MIME };
