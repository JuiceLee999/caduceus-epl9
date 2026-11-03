// Approximate look preview on 8-bit sRGB images (Canvas 2D, CPU). A rough port of the repo's desktop sim
// (sim/pipeline.py ColorEngine + grain, sim/film.py WB / tone levels / mono, sim/library_preview.py bloom), applied to
// already-rendered JPEGs instead of raw files, so it is an approximation of an approximation: good for direction
// and relative strength, not for exact colour. Vignette and Art Effects are not previewed.
// The look's tone (H/S/M/B/W, card data) is a luminance LUT in the display domain after the base curve (src/tone.ts);
// the contrast advice bends the input to it first. The old recipe tone advice (advice.tone) is not previewed: on
// v0.19 the Film pick sets the profile's H/S/M from the look's own tone.
import { GRAINS, toneIsZero, type Look } from './pack';
import { previewToneLut } from './tone';

// Firmware COLOR table (generated/color/ep7_color_table.json, UI order): sector centre / width (0..32767 = 360 deg)
// and the positive/negative saturation gains.
const CENTRE = [12197, 9466, 8192, 6736, 3095, 30401, 28945, 27489, 24212, 20753, 16111, 15019].map((w) => (w / 32768) * 360);
const WIDTH = [3823, 5461, 3959, 2685, 5006, 9057, 6872, 2867, 4642, 6690, 8055, 5643].map((w) => (w / 32768) * 360);
const GAIN_POS = [240, 240, 240, 256, 369, 328, 382, 382, 300, 615, 400, 656];
const GAIN_NEG = [385, 385, 395, 493, 513, 395, 385, 385, 395, 395, 395, 395];
const ANGLE_OFFSET = 15, SAT_SCALE = 1.5, HUE_DEG_PER_STEP = 5.5;
const L_LUT = [-300, -250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250, 300];
const WB_STEP = 0.015, CONTRAST_STEP = 0.035;
const BLOOM_SHARE = [0.08, 0.14, 0.2, 0.27, 0.35];
const COLOUR_GRAIN = [0, 40, 80, 0], MONO_GRAIN = [0, 110, 300, 0];   // v0.22: colour = a hint of sensor-like texture (Noise Filter Low/Off)
const CLARITY = [0.12, 0.22, 0.32, 0.42, 0.52];
const TINT_RGB: Record<string, [number, number, number]> = {
  neutral: [1, 1, 1], red: [1, 0.5, 0.38], amber: [1, 0.75, 0.42], warm: [1, 0.87, 0.72], cool: [0.78, 0.9, 1.1],
};
const MONO_W: Record<string, [number, number, number]> = {
  none: [0.299, 0.587, 0.114], yellow: [0.42, 0.53, 0.05], orange: [0.52, 0.44, 0.04], red: [0.65, 0.32, 0.03],
  green: [0.22, 0.7, 0.08], blue: [0.18, 0.47, 0.35],
};
const FULL_WIDTH = 5184;
const BINS = 720;

const DEC = new Float32Array(256).map((_, i) => {
  const x = i / 255;
  return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
});
const ENC_N = 4096;
const ENC = new Float32Array(ENC_N + 1).map((_, i) => {
  const x = i / ENC_N;
  return x <= 0.0031308 ? 12.92 * x : 1.055 * Math.pow(x, 1 / 2.4) - 0.055;
});
const enc = (x: number) => ENC[Math.max(0, Math.min(ENC_N, (x * ENC_N + 0.5) | 0))];
const clamp01 = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);

/** Per-hue-bin colour-engine response for a look: saturation multiplier, hue shift (deg), lightness (native sum). */
export function sectorLut(hue: number[], light: number[], sat: number[]) {
  const satMul = new Float32Array(BINS), shift = new Float32Array(BINS), lsum = new Float32Array(BINS);
  const sc = sat.map((s, k) => (s * (s >= 0 ? GAIN_POS[k] : GAIN_NEG[k])) / 5 * SAT_SCALE);
  const centre = CENTRE.map((c) => (c + ANGLE_OFFSET) % 360);
  const w = new Float64Array(12);
  for (let b = 0; b < BINS; b++) {
    const h = (b + 0.5) * (360 / BINS);
    let sum = 0;
    for (let k = 0; k < 12; k++) {
      const d = ((h - centre[k] + 540) % 360) - 180;
      const x = Math.max(-1, Math.min(1, d / Math.max(WIDTH[k], 1)));
      w[k] = Math.max(0, Math.cos(x * Math.PI / 2));
      sum += w[k];
    }
    let s = 0, hs = 0, l = 0;
    for (let k = 0; k < 12; k++) {
      const wk = sum > 1e-6 ? w[k] / sum : 1 / 12;
      s += wk * sc[k];
      hs += wk * hue[k] * HUE_DEG_PER_STEP;          // native -1000*u; shift = -native/1000 * deg/step
      l += wk * L_LUT[Math.max(-7, Math.min(7, light[k])) + 7];
    }
    satMul[b] = Math.max(0, Math.min(3, 1 + s / 1000));
    shift[b] = (hs * Math.PI) / 180;
    lsum[b] = l / 4096;
  }
  return { satMul, shift, lsum };
}

export const contrastCurve = (contrast: number) => (y: number) => clamp01(y + 0.5 * CONTRAST_STEP * contrast * Math.sin(2 * Math.PI * (y - 0.5)));

/** Box-downsample to ~sw px wide, blur, and bilinear-upsample back: the Soft Focus "blurred copy". */
function blurredCopy(src: Float32Array, w: number, h: number, sw: number, sigma: number): Float32Array {
  const f = Math.max(1, Math.round(w / sw));
  const W = Math.max(4, Math.ceil(w / f)), H = Math.max(3, Math.ceil(h / f));
  let small = new Float32Array(W * H * 3);
  const cnt = new Float32Array(W * H);
  for (let y = 0; y < h; y++) {
    const Y = Math.min(H - 1, (y / f) | 0);
    for (let x = 0; x < w; x++) {
      const X = Math.min(W - 1, (x / f) | 0), o = (Y * W + X), i = (y * w + x) * 3;
      small[o * 3] += src[i]; small[o * 3 + 1] += src[i + 1]; small[o * 3 + 2] += src[i + 2]; cnt[o]++;
    }
  }
  for (let o = 0; o < W * H; o++) { const c = cnt[o] || 1; small[o * 3] /= c; small[o * 3 + 1] /= c; small[o * 3 + 2] /= c; }
  // separable gaussian
  const r = Math.ceil(sigma * 3), ker = new Float32Array(2 * r + 1);
  let ks = 0;
  for (let i = -r; i <= r; i++) ks += ker[i + r] = Math.exp(-(i * i) / (2 * sigma * sigma));
  ker.forEach((v, i) => (ker[i] = v / ks));
  for (const horiz of [true, false]) {
    const out = new Float32Array(small.length);
    for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
      let a = 0, b = 0, c = 0;
      for (let k = -r; k <= r; k++) {
        const xx = horiz ? Math.min(W - 1, Math.max(0, x + k)) : x, yy = horiz ? y : Math.min(H - 1, Math.max(0, y + k));
        const j = (yy * W + xx) * 3, kv = ker[k + r];
        a += small[j] * kv; b += small[j + 1] * kv; c += small[j + 2] * kv;
      }
      const o = (y * W + x) * 3;
      out[o] = a; out[o + 1] = b; out[o + 2] = c;
    }
    small = out;
  }
  const big = new Float32Array(w * h * 3);
  for (let y = 0; y < h; y++) {
    const fy = Math.min(H - 1, Math.max(0, (y + 0.5) / f - 0.5)), y0 = fy | 0, y1 = Math.min(H - 1, y0 + 1), ty = fy - y0;
    for (let x = 0; x < w; x++) {
      const fx = Math.min(W - 1, Math.max(0, (x + 0.5) / f - 0.5)), x0 = fx | 0, x1 = Math.min(W - 1, x0 + 1), tx = fx - x0;
      const o = (y * w + x) * 3;
      for (let c = 0; c < 3; c++) {
        const a = small[(y0 * W + x0) * 3 + c] * (1 - tx) + small[(y0 * W + x1) * 3 + c] * tx;
        const b = small[(y1 * W + x0) * 3 + c] * (1 - tx) + small[(y1 * W + x1) * 3 + c] * tx;
        big[o + c] = a * (1 - ty) + b * ty;
      }
    }
  }
  return big;
}

export interface PreviewOptions { advice: boolean }

/** Render `look` from `src` (8-bit sRGB RGBA) into `dst` (same size). */
export function renderLook(src: ImageData, dst: ImageData, look: Look, opt: PreviewOptions) {
  const { width: w, height: h } = src;
  const s = src.data, d = dst.data, n = w * h;
  const img = new Float32Array(n * 3);
  const mono = look.kind === 'mono';
  // 1. WB fine-tune (linear light)
  const ab = look.wb?.a_b ?? 0, gm = look.wb?.g_m ?? 0;
  const gr = 1 + WB_STEP * ab, gg = 1 + WB_STEP * gm, gb = 1 - WB_STEP * ab;
  for (let i = 0; i < n; i++) {
    const p = i * 4, q = i * 3;
    if (ab || gm) {
      img[q] = enc(DEC[s[p]] * gr); img[q + 1] = enc(DEC[s[p + 1]] * gg); img[q + 2] = enc(DEC[s[p + 2]] * gb);
    } else {
      img[q] = s[p] / 255; img[q + 1] = s[p + 1] / 255; img[q + 2] = s[p + 2] / 255;
    }
  }
  // 2. contrast advice + the look's tone (luminance), 3. 12-sector colour engine, 4. mono
  const con = opt.advice ? look.advice.contrast ?? 0 : 0;
  const tl = !toneIsZero(look.tone) || con ? previewToneLut(look.tone, 1024, con ? contrastCurve(con) : undefined) : null;
  const lut = sectorLut(look.hue, look.light, opt.advice && !mono ? look.sat : new Array(12).fill(0));
  const mf = look.advice.mono_filter;
  let mw: [number, number, number] = MONO_W.none;
  if (mono && mf) {
    const f = MONO_W[mf.colour] ?? MONO_W.none, k = Math.min(3, Math.max(0, mf.strength)) / 3;
    mw = [0, 1, 2].map((c) => MONO_W.none[c] + (f[c] - MONO_W.none[c]) * k) as [number, number, number];
    const t = mw[0] + mw[1] + mw[2];
    mw = [mw[0] / t, mw[1] / t, mw[2] / t];
  }
  for (let i = 0; i < n; i++) {
    const q = i * 3;
    const r = img[q], g = img[q + 1], b = img[q + 2];
    let y = 0.299 * r + 0.587 * g + 0.114 * b;
    let cb = -0.168736 * r - 0.331264 * g + 0.5 * b;
    let cr = 0.5 * r - 0.418688 * g - 0.081312 * b;
    if (tl) y = tl[Math.max(0, Math.min(1024, (y * 1024 + 0.5) | 0))];   // luminance only: Cb/Cr untouched
    const chroma = Math.hypot(cb, cr);
    if (chroma > 1e-5) {
      let hd = (Math.atan2(cr, cb) * 180) / Math.PI;
      if (hd < 0) hd += 360;
      const bin = Math.min(BINS - 1, (hd * (BINS / 360)) | 0);
      const ang = (hd * Math.PI) / 180 + lut.shift[bin];
      const ch = chroma * lut.satMul[bin];
      y += lut.lsum[bin] * Math.min(1, chroma / 0.25);
      cb = ch * Math.cos(ang); cr = ch * Math.sin(ang);
    }
    let R = y + 1.402 * cr, G = y - 0.344136 * cb - 0.714136 * cr, B = y + 1.772 * cb;
    R = clamp01(R); G = clamp01(G); B = clamp01(B);
    if (mono) R = G = B = mw[0] * R + mw[1] * G + mw[2] * B;
    img[q] = R; img[q + 1] = G; img[q + 2] = B;
  }
  // 5. bloom / halation (Soft Focus blend of a 160-px-wide blurred copy) or clarity (large-radius local contrast)
  const e = look.effect;
  if (e && e.strength >= 1) {
    const st = Math.min(5, e.strength) - 1;
    if (e.type === 'clarity') {
      const bl = blurredCopy(img, w, h, 96, 1.5), k = CLARITY[st];
      for (let i = 0; i < n * 3; i += 3) {
        const yo = 0.299 * img[i] + 0.587 * img[i + 1] + 0.114 * img[i + 2];
        const yb = 0.299 * bl[i] + 0.587 * bl[i + 1] + 0.114 * bl[i + 2];
        const dy = k * (yo - yb) * (1 - Math.abs(2 * yo - 1) * 0.5);
        img[i] = clamp01(img[i] + dy); img[i + 1] = clamp01(img[i + 1] + dy); img[i + 2] = clamp01(img[i + 2] + dy);
      }
    } else {
      const tint = TINT_RGB[e.tint ?? (e.type === 'halation' ? 'red' : 'neutral')] ?? TINT_RGB.neutral;
      const bl = blurredCopy(img, w, h, 160, 1.2), sh = BLOOM_SHARE[st];
      for (let i = 0; i < n * 3; i += 3) {
        for (let c = 0; c < 3; c++) img[i + c] = clamp01((1 - sh) * img[i + c] + sh * Math.min(1, bl[i + c] * tint[c] * 1.08));
      }
    }
  }
  // 6. grain (Olympus xorshift32 luma grain with brightness mask; v0.4 colour gains / stock mono gains)
  const gi = GRAINS.indexOf(look.grain);
  const gain = gi > 0 ? (mono ? MONO_GRAIN : COLOUR_GRAIN)[gi] : 0;
  const scale = Math.min(1, w / FULL_WIDTH) * 2.2;   // a little stronger than full-res-viewed-small, so it stays visible
  for (let i = 0; i < n; i++) {
    const q = i * 3, p = i * 4;
    let r = img[q], g = img[q + 1], b = img[q + 2];
    if (gain) {
      let st = (Math.imul(i, 2654435761) + 10) >>> 0;
      for (let k = 0; k < 3; k++) { st ^= st << 13; st >>>= 0; st ^= st >>> 17; st ^= st << 5; st >>>= 0; }
      const rnd = (st & 0xffff) - 32768;
      const y = 0.299 * r + 0.587 * g + 0.114 * b;
      const m = clamp01(((y * 255) - 36) / (120 - 36)) * 1023;
      const noise = Math.max(-6682, ((gain * m) / 1024) * rnd / 1024) * scale / 65535;
      r += noise; g += noise; b += noise;
    }
    d[p] = clamp01(r) * 255 + 0.5; d[p + 1] = clamp01(g) * 255 + 0.5; d[p + 2] = clamp01(b) * 255 + 0.5; d[p + 3] = 255;
  }
}
