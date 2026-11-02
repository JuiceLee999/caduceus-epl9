// Per-look tone for the preview: the camera's luminance tone LUT (256 knots, 10-bit out, display/gamma domain).
//   remapBW      Blacks / Whites curve-end remap, a bit-exact port of tools/ep7_tone.py remap() (the camera routine,
//                patches/tone_ends); tests/tone.test.ts checks it against the Python on a sweep.
//   hsmLut       Highlights / Shadows / Midtones: bit-exact port of tools/ep7_tone_model.py (the stock firmware's
//                knot gains + int32 cubic splines) with its data (src/data/tone_hsm.json, from tools/data/tone_hsm.json).
//   previewToneLut  y (0..1 display luma) -> y' table for the preview: contrast advice, then base LUT -> toned LUT.
import { toneIsZero, type Tone } from './pack';
import toneData from './data/tone_hsm.json';

export const BW_LIMIT = 5;
/** The identity knot LUT (knot k -> its own 10-bit level). */
export const IDENTITY_LUT: readonly number[] = Array.from({ length: 256 }, (_, k) => Math.round((k * 1023) / 255));

/** -> [lo, hi, cB, cW] for slot values B, W (out-of-range values count as 0), as ep7_tone.params. */
export function bwParams(B: number, W: number): [number, number, number, number] {
  B = Number.isInteger(B) && Math.abs(B) <= BW_LIMIT ? B : 0;
  W = Number.isInteger(W) && Math.abs(W) <= BW_LIMIT ? W : 0;
  return [B > 0 ? 8 * B : 0, W < 0 ? 1023 + 10 * W : 1023, B < 0 ? -12 * B : 0, W > 0 ? 12 * W : 0];
}
export const bwActive = (B: number, W: number) => bwParams(B, W).join() !== '0,1023,0,0';

/** 256 LUT values -> Blacks/Whites-remapped copy (unchanged copy when B = W = 0). Integer-exact with ep7_tone.remap. */
export function remapBW(lut: readonly number[], B: number, W: number): number[] {
  if (lut.length !== 256) throw new Error('LUT must have 256 entries');
  if (!bwActive(B, W)) return [...lut];
  const [lo, hi, cB, cW] = bwParams(B, W);
  const K = (hi - lo) * 1025;
  let prev = 0;
  return lut.map((v) => {
    let y = Math.min(v & 0xffff, 1023);
    const t = 1023 - y;
    y -= (cB * ((((t * t) >> 10) * t) >> 10)) >> 10;
    y = Math.max(y, 0);
    y += (cW * ((((y * y) >> 10) * y) >> 10)) >> 10;
    y = Math.min(y, 1023);
    y = lo + Math.floor((y * K + 0xfffff) / 0x100000);     // (y*K + 0xFFFFF) >> 20 without 32-bit overflow
    y = Math.max(y, prev);
    prev = y;
    return y;
  });
}

const clamp = (x: number, lo: number, hi: number) => (x < lo ? lo : x > hi ? hi : x);

// ---- Highlights / Shadows / Midtones: bit-exact port of tools/ep7_tone_model.py (firmware 0x6034fcd2 + 0x6034ff93)
export const HSM_LIMIT = 7;
const TM = toneData as { base_lut: number[]; gains: Record<'highlights' | 'shadows' | 'midtones', number[]>;
  samples_k: number[]; curve_a_x: number[]; curve_b_x: number[]; curve_c_x: number[] };
/** Contrast-0 ROM LUT 0x604fa082. */
export const BASE_LUT: readonly number[] = TM.base_lut;
const i32 = (v: number) => v | 0;                    // exact: every product here stays below 2^53
const s16 = (v: number) => ((v & 0xffff) ^ 0x8000) - 0x8000;
function div(a: number, b: number): number {         // signed, truncating toward zero, integer-exact
  const A = Math.abs(a), B = Math.abs(b), q = (A - (A % B)) / B;
  return (a < 0) === (b < 0) ? q : -q;
}
function solve(xs: readonly number[], ys: number[]): number[] {
  const n = xs.length, M = new Array(n).fill(0), H = new Array(n).fill(0), P = new Array(n + 1).fill(0);
  for (let i = 0; i < n - 1; i++) {
    H[i] = xs[i + 1] - xs[i];
    P[i + 1] = i32(div(i32((ys[i + 1] - ys[i]) * 1024), H[i]));
  }
  M[1] = i32(P[2] - P[1]); P[1] = 2 * (xs[2] - xs[0]);
  for (let i = 1; i < n - 2; i++) {
    const r = div(i32(H[i] * 1024), P[i]);
    M[i + 1] = i32(P[i + 2] - P[i + 1] - (i32(r * M[i]) >> 10));
    P[i + 1] = i32(2 * (xs[i + 2] - xs[i]) - (i32(H[i] * r) >> 10));
  }
  M[n - 2] = i32(M[n - 2] - i32(H[n - 2] * M[n - 1]));
  for (let k = n - 2; k > 0; k--) M[k] = div(i32(i32(M[k] * 1024) - i32(H[k] * M[k + 1])), P[k]);
  return M;
}
function evalSpline(x: number, xs: readonly number[], ys: number[], M: number[]): number {
  let lo = 0, hi = xs.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (xs[mid] < x) lo = mid + 1; else hi = mid; }
  const k = lo > 0 ? lo - 1 : 0;
  const h = xs[k + 1] - xs[k], t = x - xs[k];
  const b = i32(div(i32((ys[k + 1] - ys[k]) * 1048576), h) - i32((2 * M[k] + M[k + 1]) * h));
  const c = div(i32((M[k + 1] - M[k]) * t), h);
  const v = i32(t * i32(i32(t * (3 * M[k] + c)) + b));
  return i32(v + i32(ys[k] * 1048576) + 524288) >> 20;
}
/** 0x6034fcd2: H/S/M (-7..7) -> the 8 knot words. */
export function knots(h: number, s: number, m: number): number[] {
  const q = { highlights: div(h * 4096, 7), midtones: div(m * 4096, 7), shadows: div(s * 4096, 7) };
  return Array.from({ length: 8 }, (_, j) =>
    Math.floor((TM.gains.highlights[j] * q.highlights + TM.gains.midtones[j] * q.midtones + TM.gains.shadows[j] * q.shadows) / 4096));
}
/** 0x6034ff93: bend a 256-entry LUT by the knot words. */
export function bend(lut: readonly number[], w: number[], flag = 0): number[] {
  const S = TM.samples_k, A = TM.curve_a_x;
  const ya = [...A]; ya[1] -= w[2]; ya[3] += w[2];
  const ma = solve(A, ya);
  const smp = S.map((x) => s16(evalSpline(lut[x], A, ya, ma)));
  let xs: number[], ys: number[];
  if (w[5] === 0 && flag !== 1) { xs = TM.curve_b_x; ys = [...xs]; ys[1] += w[3]; ys[6] += w[4]; }
  else { xs = TM.curve_c_x; ys = [...xs]; ys[1] += w[6]; ys[3] += w[7]; ys[2] += w[5]; }
  const mc = solve(xs, ys);
  const out: number[] = [];
  let prev = 0;
  smp.forEach((x, i) => {
    const v = s16(evalSpline(x, xs, ys, mc));
    prev = i === 0 ? (v <= 0 ? 0 : Math.min(v, 1023)) : v <= prev ? prev : Math.min(v, 1023);
    out.push(prev);
  });
  const md = solve(S, out);
  const L = new Array<number>(256).fill(0);
  let d3 = out[0], j = 1;
  L[0] = d3;
  for (let a = 2; a < 255; a += 2) {
    let v: number;
    if (a < S[j]) v = s16(evalSpline(a, S, out, md));
    else { v = out[j]; j++; }
    const d2 = v <= d3 ? d3 : Math.min(v, 1023);
    L[a - 1] = (d3 + d2) >> 1; L[a] = d2; d3 = d2;
  }
  const v = out[26];
  L[255] = v <= d3 ? d3 : Math.min(v, 1023);
  return L;
}
/** Camera LUT for tone H/S/M on `base` (default the contrast-0 ROM LUT); values clamp to -7..7 (ep7_tone_model.hsm_lut). */
export function hsmLut(h: number, s: number, m: number, base: readonly number[] = BASE_LUT): number[] {
  const c = (v: number) => Math.max(-HSM_LIMIT, Math.min(HSM_LIMIT, Math.trunc(v)));
  [h, s, m] = [c(h), c(s), c(m)];
  if (!h && !s && !m) return [...base];
  return bend(base, knots(h, s, m));
}

/** The camera LUT for a look's tone: H/S/M bend, then the Blacks/Whites remap (ep7_tone_model.tone_lut). */
export function lookLut(tone: Tone, base: readonly number[] = BASE_LUT): number[] {
  return remapBW(hsmLut(tone.highlights, tone.shadows, tone.midtones, base), tone.blacks, tone.whites);
}

/** np.interp: piecewise-linear through (xs, ys), clamped to the end values. */
function interp(x: number, xs: readonly number[], ys: readonly number[]): number {
  if (x <= xs[0]) return ys[0];
  const n = xs.length;
  if (x >= xs[n - 1]) return ys[n - 1];
  let lo = 0, hi = n - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (xs[mid] <= x) lo = mid; else hi = mid; }
  const d = xs[hi] - xs[lo];
  return d > 0 ? ys[lo] + ((x - xs[lo]) * (ys[hi] - ys[lo])) / d : ys[hi];
}

/** y -> y' table (n+1 entries over display luma 0..1) for the preview: the image is already past the base curve,
 *  so each display value goes base LUT -> toned LUT (as sim/film.py camera_tone). `pre` (contrast advice) runs
 *  first. Zero tone = identity. */
export function previewToneLut(tone: Tone, n = 1024, pre?: (y: number) => number): Float32Array {
  const xs = BASE_LUT.map((v) => v / 1023), ys = lookLut(tone).map((v) => v / 1023);
  const t = new Float32Array(n + 1);
  for (let i = 0; i <= n; i++) {
    let y = i / n;
    if (pre) y = clamp(pre(y), 0, 1);
    t[i] = toneIsZero(tone) ? y : interp(y, xs, ys);
  }
  return t;
}
