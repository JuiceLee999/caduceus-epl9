// RapidRAW preset export (.rrpreset): the looks as RapidRAW edits, for ORF files or any other camera's raws.
//
// RapidRAW (github.com/CyberTimon/RapidRAW) presets are JSON: { creator, presets: [{ preset: {id, name, adjustments} } |
// { folder: {id, name, children: [preset...]} }] }. Applying one merges its `adjustments` keys over the current edit,
// so every preset here sets every key it uses (a look switch leaves nothing of the previous look behind).
//
// It is an approximation. RapidRAW starts from its own raw rendering, not the camera's JPEG engine, so the looks keep
// their character, not exact colour. The mapping follows the Control Panel preview (src/preview.ts):
//   12-sector Hue / Light / Saturation -> the 8 HSL bands: the preview's colour engine is run on sample colours
//     around the HSV hue circle and the 8 band values are least-squares fitted to RapidRAW's own HSL maths
//     (shader.wgsl apply_hsl_panel: Gaussian bands, hue 0.6 deg per unit, sat and linear luma as 1 + v/100).
//   Tone (H/M/S/Blacks/Whites) + contrast advice -> the luma point curve (the preview's tone LUT, 0..255).
//   WB fine-tune A-B / G-M -> Temperature / Tint (A+ warmer = Temperature+, G+ greener = Tint-).
//   Bloom -> Glow, red-tinted bloom / halation -> Halation, Clarity -> Clarity, vignette -> Vignette.
//   Mono looks -> Monochrome on, with the look's colour filter.
// Not mapped: noise reduction (a camera setting), Art Effects.
import { type Look, type Pack } from './pack';
import { contrastCurve, sectorLut } from './preview';
import { previewToneLut } from './tone';

export const RR_BANDS = ['reds', 'oranges', 'yellows', 'greens', 'aquas', 'blues', 'purples', 'magentas'] as const;
const RR_CENTRE = [358, 25, 60, 115, 180, 225, 280, 330];      // shader.wgsl HSL_RANGES
const RR_WIDTH = [35, 45, 40, 90, 60, 60, 55, 50];
const RR_HUE_DEG = 0.6;                                         // hsl_hue_multiplier 0.3 x 2.0 in the shader
const SAMPLE_S = 0.6, SAMPLE_V = 0.75;                          // fit colours: well inside RapidRAW's saturation mask
const LUM_W = SAMPLE_S * SAMPLE_S * (3 - 2 * SAMPLE_S);         // shader luminance_weight = smoothstep(0, 1, S)

// Effect / WB scales (RapidRAW slider units per camera step). First guesses, to be tuned on ORF + JPEG pairs.
const TEMP_PER_AB = 4, TINT_PER_GM = 4;
const GLOW = [0, 12, 22, 32, 44, 56];                           // bloom strength 1..5 (preview share 8..35 %)
const CLARITY = [0, 10, 18, 26, 34, 42];
const VIGNETTE_PER_STEP = 10;
const MONO_FILTER: Record<string, { hue: number; strength: number }> = {   // RapidRAW's own filter presets
  none: { hue: 0, strength: 0 }, red: { hue: 0, strength: 100 }, orange: { hue: 30, strength: 85 },
  yellow: { hue: 55, strength: 60 }, green: { hue: 120, strength: 70 }, blue: { hue: 225, strength: 80 },
};

const BINS = 720;
const clamp = (x: number, lo: number, hi: number) => (x < lo ? lo : x > hi ? hi : x);
const dec = (x: number) => (x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4));
const luma = (r: number, g: number, b: number) => 0.2126 * dec(r) + 0.7152 * dec(g) + 0.0722 * dec(b);

function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
  const f = (n: number) => { const k = (n + h / 60) % 6; return v - v * s * Math.max(0, Math.min(k, 4 - k, 1)); };
  return [f(5), f(3), f(1)];
}
function rgbToHsv(r: number, g: number, b: number): [number, number, number] {
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d > 1e-9) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, mx > 0 ? d / mx : 0, mx];
}

/** RapidRAW band weights at hue h (normalised, as in the shader). */
function bandWeights(h: number): number[] {
  const w = RR_CENTRE.map((c, i) => {
    const d = Math.min(Math.abs(h - c), 360 - Math.abs(h - c)) / (RR_WIDTH[i] * 0.5);
    return Math.exp(-1.5 * d * d);
  });
  const t = w.reduce((a, b) => a + b, 0);
  return w.map((x) => x / t);
}

/** The preview's colour engine (hue / sat / light only) on one sRGB colour, as in renderLook step 3. */
function engine(rgb: [number, number, number], lut: ReturnType<typeof sectorLut>): [number, number, number] {
  const [r, g, b] = rgb;
  let y = 0.299 * r + 0.587 * g + 0.114 * b;
  let cb = -0.168736 * r - 0.331264 * g + 0.5 * b;
  let cr = 0.5 * r - 0.418688 * g - 0.081312 * b;
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
  return [clamp(y + 1.402 * cr, 0, 1), clamp(y - 0.344136 * cb - 0.714136 * cr, 0, 1), clamp(y + 1.772 * cb, 0, 1)];
}

/** Least squares with a small ridge: rows A (m x 8), targets t -> x (8). */
function fit(A: number[][], t: number[], ridge = 1e-4): number[] {
  const n = 8, M = Array.from({ length: n }, () => new Array<number>(n + 1).fill(0));
  A.forEach((row, k) => {
    for (let i = 0; i < n; i++) {
      for (let j = 0; j < n; j++) M[i][j] += row[i] * row[j];
      M[i][n] += row[i] * t[k];
    }
  });
  for (let i = 0; i < n; i++) M[i][i] += ridge * A.length;
  for (let c = 0; c < n; c++) {                                  // Gauss-Jordan, partial pivot
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = 0; r < n; r++) {
      if (r === c) continue;
      const f = M[r][c] / M[c][c];
      for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k];
    }
  }
  return M.map((row, i) => row[n] / row[i]);
}

export type Hsl = Record<(typeof RR_BANDS)[number], { hue: number; saturation: number; luminance: number }>;

/** The 8 RapidRAW HSL bands that best reproduce the look's 12-sector Hue / Light / Saturation. */
export function hslFor(look: Look, withSat = true): Hsl {
  const lut = sectorLut(look.hue, look.light, withSat ? look.sat : new Array(12).fill(0));
  const A: number[][] = [], th: number[] = [], ts: number[] = [], tl: number[] = [];
  for (let h = 0; h < 360; h += 2) {
    const src = hsvToRgb(h, SAMPLE_S, SAMPLE_V), out = engine(src, lut);
    const [ho, so] = rgbToHsv(...out);
    A.push(bandWeights(h));
    th.push((((ho - h + 540) % 360) - 180) / RR_HUE_DEG);
    ts.push((so / SAMPLE_S - 1) * 100);
    tl.push((luma(...out) / luma(...src) - 1) * 100 / LUM_W);
  }
  const [vh, vs, vl] = [th, ts, tl].map((t) => fit(A, t).map((v) => Math.round(clamp(v, -100, 100))));
  return Object.fromEntries(RR_BANDS.map((b, i) => [b, { hue: vh[i] + 0, saturation: vs[i] + 0, luminance: vl[i] + 0 }])) as Hsl;
}

const CURVE_X = [0, 32, 64, 96, 128, 160, 192, 224, 255];
const identity = () => [{ x: 0, y: 0 }, { x: 255, y: 255 }];

/** Luma point curve from the look's tone and contrast advice (identity when both are zero). */
export function lumaCurve(look: Look): { x: number; y: number }[] {
  const con = look.advice.contrast ?? 0;
  const t = look.tone;
  if (!con && !t.highlights && !t.shadows && !t.midtones && !t.blacks && !t.whites) return identity();
  const lut = previewToneLut(t, 255, con ? contrastCurve(con) : undefined);
  return CURVE_X.map((x) => ({ x, y: Math.round(clamp(lut[x] * 255, 0, 255)) }));
}

/** RapidRAW adjustments for one look. */
export function rrAdjustments(look: Look): Record<string, unknown> {
  const mono = look.kind === 'mono';
  const e = look.effect, st = e ? clamp(e.strength, 0, 5) : 0;
  const halation = !!e && (e.type === 'halation' || (e.type === 'bloom' && e.tint === 'red'));
  const glowy = !!e && (e.type === 'bloom' || e.type === 'halation');
  const mf = MONO_FILTER[look.advice.mono_filter?.colour ?? 'none'] ?? MONO_FILTER.none;
  const mfk = clamp(look.advice.mono_filter?.strength ?? 0, 0, 3) / 3;
  const zeroHsl = Object.fromEntries(RR_BANDS.map((b) => [b, { hue: 0, saturation: 0, luminance: 0 }]));
  return {
    hsl: mono ? zeroHsl : hslFor(look),
    curves: { luma: lumaCurve(look), red: identity(), green: identity(), blue: identity() },
    curveMode: 'point',
    temperature: (look.wb?.a_b ?? 0) * TEMP_PER_AB,
    tint: -(look.wb?.g_m ?? 0) * TINT_PER_GM + 0,
    glowAmount: glowy ? (halation ? Math.round(GLOW[st] * 0.4) : GLOW[st]) : 0,
    halationAmount: halation ? GLOW[st] : 0,
    clarity: e?.type === 'clarity' ? CLARITY[st] : 0,
    vignetteAmount: (look.vignette ?? 0) * VIGNETTE_PER_STEP,
    monochromeEnabled: mono,
    monochromeFilterHue: mono ? mf.hue : 0,
    monochromeFilterStrength: mono ? Math.round(mf.strength * mfk) : 0,
  };
}

const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'look';
const rrPreset = (look: Look, i: number) => ({
  id: `caduceus-${i + 1}-${slug(look.name)}`, name: look.name, adjustments: rrAdjustments(look),
  includeMasks: false, includeCropTransform: false, presetType: 'style',
});

/** .rrpreset text: one look, or the whole pack in a folder named after the pack. */
export function rrpreset(pack: Pack, only?: number): string {
  const presets = only !== undefined
    ? [{ preset: rrPreset(pack.looks[only], only) }]
    : [{ folder: { id: `caduceus-${slug(pack.name || 'caduceus')}`, name: pack.name || 'Caduceus', children: pack.looks.map(rrPreset) } }];
  return JSON.stringify({ creator: 'Caduceus Control Panel', presets }, null, 1) + '\n';
}
