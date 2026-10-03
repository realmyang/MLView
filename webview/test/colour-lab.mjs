// Colour arithmetic the token tests share for viewer M4's secondary and muted text: CSS Color 4's
// sRGB <-> CIE Lab (D50), color-mix(in lab, ...), relative colours (`lab(from <colour> L a b)`)
// with the CSS math they use, and tokens.css split at its @supports blocks. A library, not a test
// file: tools/run-tests.mjs runs only *.test.mjs. Written apart from src/export/palette.ts, so the
// export test compares two implementations; capture.mjs's page probe compares Chrome's own values.
import assert from 'node:assert/strict';

const lin = (v) => {
  const s = v / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
};
const gam = (v) => {
  const c = Math.max(0, Math.min(1, v));
  return 255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
};
const mul = (m, v) => m.map((r) => r[0] * v[0] + r[1] * v[1] + r[2] * v[2]);

// CSS Color 4, section 18 (sample code), as rationals.
const RGB_XYZ = [[506752 / 1228815, 87881 / 245763, 12673 / 70218], [87098 / 409605, 175762 / 245763, 12673 / 175545], [7918 / 409605, 87881 / 737289, 1001167 / 1053270]];
const XYZ_RGB = [[12831 / 3959, -329 / 214, -1974 / 3959], [-851781 / 878810, 1648619 / 878810, 36519 / 878810], [705 / 12673, -2585 / 12673, 705 / 667]];
const D65_D50 = [[1.0479297925449969, 0.022946870601609652, -0.05019226628920524], [0.02962780877005599, 0.9904344267538799, -0.017073799063418826], [-0.009243040646204504, 0.015055191490298152, 0.7518742814281371]];
const D50_D65 = [[0.955473421488075, -0.02309845494876471, 0.06325924320057072], [-0.0283697093338637, 1.0099953980813041, 0.021041441191917323], [0.012314014864481998, -0.020507649298898964, 1.330365926242124]];
const D50 = [0.3457 / 0.3585, 1, (1 - 0.3457 - 0.3585) / 0.3585];
const EPS = 216 / 24389;
const KAPPA = 24389 / 27;

/** [r, g, b(, a)] with channels 0..255 as CIE Lab [L, a, b]. */
export function srgbToLab(rgb) {
  const f = mul(D65_D50, mul(RGB_XYZ, rgb.slice(0, 3).map(lin))).map((v, i) => {
    const t = v / D50[i];
    return t > EPS ? Math.cbrt(t) : (KAPPA * t + 16) / 116;
  });
  return [116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])];
}

/** CIE Lab as opaque [r, g, b, 1], clipped to sRGB. */
export function labToSrgb([L, a, b]) {
  const fy = (L + 16) / 116;
  const fx = fy + a / 500;
  const fz = fy - b / 200;
  const xyz = [fx ** 3 > EPS ? fx ** 3 : (116 * fx - 16) / KAPPA, L > KAPPA * EPS ? fy ** 3 : L / KAPPA, fz ** 3 > EPS ? fz ** 3 : (116 * fz - 16) / KAPPA].map((v, i) => v * D50[i]);
  return [...mul(XYZ_RGB, mul(D50_D65, xyz)).map(gam), 1];
}

/** CIE L* of an opaque colour. */
export const lstar = (rgb) => srgbToLab(rgb)[0];

/** color-mix(in lab, a p, b): premultiplied, as CSS Color 5 interpolates colours with alpha. */
export function mixLab(a, b, p) {
  const alpha = a[3] * p + b[3] * (1 - p);
  if (alpha === 0) return [0, 0, 0, 0];
  const [la, lb] = [srgbToLab(a), srgbToLab(b)];
  const lab = [0, 1, 2].map((i) => (la[i] * a[3] * p + lb[i] * b[3] * (1 - p)) / alpha);
  return [...labToSrgb(lab).slice(0, 3), alpha];
}

/* ── CSS math: numbers, the channel keywords, + - * /, calc(), min(), max(), clamp() ─────────── */

/** The value of a CSS math expression, with `env` for the identifiers (a relative colour's channels). */
export function evaluate(expr, env) {
  const tokens = expr.match(/\d*\.\d+|\d+|[a-z-]+\(|[a-z]+|[-+*/(),]/gi);
  assert.equal(tokens.join(''), expr.replace(/\s+/g, ''), 'CSS math the helper can read: ' + expr);
  let i = 0;
  const peek = () => tokens[i];
  const take = (want) => {
    const t = tokens[i++];
    if (want !== undefined) assert.equal(t, want, `${want} in ${expr}`);
    return t;
  };
  function sum() {
    let v = product();
    while (peek() === '+' || peek() === '-') v = take() === '+' ? v + product() : v - product();
    return v;
  }
  function product() {
    let v = unary();
    while (peek() === '*' || peek() === '/') v = take() === '*' ? v * unary() : v / unary();
    return v;
  }
  function unary() {
    if (peek() === '-') { take(); return -unary(); }
    return atom();
  }
  function list() {
    const out = [sum()];
    while (peek() === ',') { take(); out.push(sum()); }
    take(')');
    return out;
  }
  function atom() {
    const t = take();
    if (t === '(' || t === 'calc(') { const v = sum(); take(')'); return v; }
    if (t === 'min(') return Math.min(...list());
    if (t === 'max(') return Math.max(...list());
    if (t === 'clamp(') { const [lo, v, hi] = list(); return Math.max(lo, Math.min(v, hi)); }
    if (/^[\d.]+$/.test(t)) return Number(t);
    assert.ok(Object.prototype.hasOwnProperty.call(env, t), `unknown identifier ${t} in ${expr}`);
    return env[t];
  }
  const v = sum();
  assert.equal(i, tokens.length, 'trailing tokens in ' + expr);
  return v;
}

/** Split `text` at whitespace outside parentheses. */
export function words(text) {
  const out = [];
  let depth = 0;
  let word = '';
  for (const c of text.trim()) {
    if (c === '(') depth++;
    if (c === ')') depth--;
    if (/\s/.test(c) && depth === 0) {
      if (word) out.push(word);
      word = '';
    } else word += c;
  }
  if (word) out.push(word);
  return out;
}

/**
 * `lab(from <origin> <L> <a> <b>)` as [r, g, b, alpha]; `resolve` turns the origin into
 * [r, g, b, alpha]. The alpha is the origin's, as an omitted alpha is in relative colour syntax.
 */
export function relativeLab(text, resolve) {
  assert.ok(text.startsWith('lab(from ') && text.endsWith(')'), text);
  const parts = words(text.slice('lab('.length, -1));
  assert.equal(parts[0], 'from');
  assert.equal(parts.length, 5, 'lab(from <colour> L a b), no alpha: ' + text);
  const origin = resolve(parts[1]);
  const [l, a, b] = srgbToLab(origin);
  const env = { l, a, b };
  const lab = parts.slice(2).map((e) => evaluate(e, env));
  return [...labToSrgb(lab).slice(0, 3), origin[3]];
}

/* ── tokens.css and its @supports blocks ─────────────────────────────────────────────────── */

/** The @supports blocks of a (comment-free) stylesheet, as { condition, body }, and the text without them. */
export function splitSupports(text) {
  const blocks = [];
  let rest = '';
  let at = 0;
  for (;;) {
    const start = text.indexOf('@supports', at);
    if (start < 0) break;
    const open = text.indexOf('{', start);
    let depth = 0;
    let end = open;
    for (; end < text.length; end++) {
      if (text[end] === '{') depth++;
      else if (text[end] === '}' && --depth === 0) break;
    }
    blocks.push({ condition: text.slice(start + '@supports'.length, open).trim(), body: text.slice(open + 1, end) });
    rest += text.slice(at, start);
    at = end + 1;
  }
  return { blocks, rest: rest + text.slice(at) };
}
