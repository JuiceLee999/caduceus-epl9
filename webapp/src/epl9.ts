// Olympus PEN E-PL9 (stock firmware 1.1): translate a look into settings the camera already has, for dialling in by
// hand. No firmware mod is involved, so per-colour hue / saturation / lightness, glow / clarity and the curve ends have
// no equivalent. They are listed as "not on the E-PL9" so the user knows what the RapidRAW preset adds on RAW files.
//
// Camera controls. Checked against the E-PL9 Instruction Manual (ManualsLib #1363421) on 2026-11-07 for which
// controls exist and the menu names. Picture Mode and Highlight & Shadow ranges were then CONFIRMED on the camera
// itself (E-PL9, fw 1.1, P mode) on 2026-11-08 — see each line. WB fine-tune is still corroborated, not yet read
// off the screen (its A/G grid needs the Super Control Panel enabled), so a WB card value could in theory name one
// step past the dial, which simply clamps; the picture-mode and tone values below are the camera's real limits.
//   Picture Mode (manual p.76-77): i-Enhance, Vivid, Natural, Muted, Portrait, Monochrome, Custom, e-Portrait,
//     Color Creator, + Art Filters. i-Enhance has an Effect strength Low/Standard/High (p.92).
//   Contrast / Sharpness / Saturation (p.89-90): ±2. CONFIRMED on camera 2026-11-08 (Vivid, all three ±2).
//   Gradation (p.91): Normal, High Key, Low Key (plus Shadow Adj / Auto).
//   Monochrome (p.92): B&W Filter N, Ye, Or, R, G (no blue filter); Monochrome Color N, S(epia), B(lue), P(urple),
//     G(reen).
//   WB compensation (p.88): A axis (Red-Blue) and G axis (Green-Magenta), ±7 (Olympus WB fine-tune is ±7 A / ±7 G
//     across this generation; corroborated, not yet screen-confirmed on this body).
//   Highlight & Shadow Control (p.94): Shadow, **Midtone** and Highlight, all adjustable; ±7. CONFIRMED on camera
//     2026-11-08 — all three zones (Highlight, Midtone, Shadow) present and each ±7. This IS the E-P7's tone
//     control, which the look format (pack.ts TONE_HSM_MAX) maps to at ±7.
import type { Look, MonoFilter, Tint } from './pack';

export const EPL9 = { pm: 2, wb: 7, hs: 7 } as const;
export const EPL9_ART_FILTERS = ['Pop Art', 'Soft Focus', 'Pale & Light Color', 'Light Tone', 'Grainy Film', 'Pin Hole',
  'Diorama', 'Cross Process', 'Gentle Sepia', 'Dramatic Tone', 'Key Line', 'Watercolor', 'Vintage', 'Partial Color',
  'Bleach Bypass', 'Instant Film'] as const;

export type Epl9Mode = 'Natural' | 'Vivid' | 'Muted' | 'Monotone';
export type Epl9Gradation = 'Normal' | 'High Key' | 'Low Key';
export interface Epl9Recipe {
  mode: Epl9Mode;
  contrast: number; sharpness: number; saturation: number;   // ±2; saturation is colour modes only
  gradation: Epl9Gradation;
  bwFilter?: 'N' | 'Ye' | 'Or' | 'R' | 'G';                  // Monochrome only: B&W filter
  monoColor?: 'N' | 'S' | 'B' | 'P' | 'G';                   // Monochrome only: Monochrome Color (tone)
  wb: { a_b: number; g_m: number };                           // compensation, ±7
  highlights: number; midtones: number; shadows: number;      // Highlight & Shadow Control, ±7
  alternatives: string[];                                     // Art filters / modes that come close to a part of the look
  missing: string[];                                          // parts of the look the stock camera can't do
}

const clamp = (v: number, lim: number) => Math.max(-lim, Math.min(lim, Math.round(v)));
const mean = (a: number[]) => a.reduce((s, x) => s + x, 0) / a.length;
const anyNonZero = (a: number[]) => a.some((x) => x !== 0);
const BW: Record<MonoFilter, Epl9Recipe['bwFilter']> = { none: 'N', yellow: 'Ye', orange: 'Or', red: 'R', green: 'G', blue: 'N' };
// Monochrome Color (tone). A mono look's warmth comes from its glow tint, or from the look name for the classics.
const TONE_TINT: Record<Tint, Epl9Recipe['monoColor']> = { neutral: 'N', red: 'S', amber: 'S', warm: 'S', cool: 'B' };
function monoColour(l: Look): Epl9Recipe['monoColor'] {
  if (/sepia|selenium.*brown|warm\s*tone/i.test(l.name)) return 'S';
  if (/cyanotype|blue\s*tone|cold\s*tone/i.test(l.name)) return 'B';
  if (/split|purple|violet/i.test(l.name)) return 'P';
  if (/green\s*tone/i.test(l.name)) return 'G';
  return l.effect?.tint ? TONE_TINT[l.effect.tint] : 'N';
}

/** The closest stock E-PL9 settings for a look. Pure; the same look always gives the same recipe. */
export function toEpl9(l: Look): Epl9Recipe {
  const missing: string[] = [], alternatives: string[] = [];
  const mono = l.kind === 'mono';

  // Tone: the look's own tone block wins; older looks only carry it as advice. The E-PL9's Highlight & Shadow
  // Control has all three of Highlight, Midtone and Shadow (manual p.94), so H/S/M map directly.
  const t = l.tone.highlights || l.tone.shadows || l.tone.midtones ? l.tone : l.advice.tone ?? { highlights: 0, shadows: 0, midtones: 0 };
  const highlights = clamp(t.highlights, EPL9.hs), midtones = clamp(t.midtones, EPL9.hs), shadows = clamp(t.shadows, EPL9.hs);
  if (l.tone.blacks || l.tone.whites) missing.push('Blacks / Whites curve ends');
  // Gradation only for strongly lifted or crushed looks; the curve sliders above do the fine work.
  const gradation: Epl9Gradation = highlights >= 3 && shadows >= 3 ? 'High Key' : highlights <= -3 && shadows <= -3 ? 'Low Key' : 'Normal';

  // Saturation: the mean of the 12 sectors (±5) scaled to ±2. Past that, start from Vivid or Muted.
  let mode: Epl9Mode = mono ? 'Monotone' : 'Natural', saturation = 0;
  if (!mono) {
    const m = mean(l.sat);
    if (m >= 3.5) { mode = 'Vivid'; saturation = clamp((m - 3.5) * 2 / 1.5, EPL9.pm); }
    else if (m <= -3.5) { mode = 'Muted'; saturation = clamp((m + 3.5) * 2 / 1.5, EPL9.pm); }
    else saturation = clamp(m * 2 / 3.5, EPL9.pm);
    const spread = Math.max(...l.sat) - Math.min(...l.sat);
    if (spread >= 2) missing.push('Saturation by colour (only one overall saturation)');
    if (anyNonZero(l.hue)) missing.push('Hue by colour');
    if (anyNonZero(l.light)) missing.push('Lightness by colour');
    // A fairly uniform hue shift across the wheel is the one case the stock Color Creator mode can approximate.
    const hueSpread = Math.max(...l.hue) - Math.min(...l.hue);
    if (anyNonZero(l.hue) && hueSpread <= 3) alternatives.push('Color Creator mode for a single overall hue shift (one colour + saturation, replaces the picture mode settings)');
    // A punchy look (Vivid, or a strong contrast lift) can also be rendered with i-Enhance, which raises local
    // contrast and saturation adaptively. Less predictable than Vivid, so it is a suggestion, not the main mode.
    if (mode === 'Vivid' && (l.advice.contrast ?? 0) >= 1) alternatives.push('i-Enhance mode for a punchier rendering (adaptive contrast + saturation; set Effect to Low/Standard/High)');
  }

  let bwFilter: Epl9Recipe['bwFilter'], monoColor: Epl9Recipe['monoColor'];
  if (mono) {
    const f = l.advice.mono_filter?.colour ?? 'none';
    bwFilter = BW[f];
    if (f === 'blue') missing.push('Blue B&W filter (the E-PL9 has Ye, Or, R, G)');
    monoColor = monoColour(l);
  }

  const wb = { a_b: clamp(l.wb?.a_b ?? 0, EPL9.wb), g_m: clamp(l.wb?.g_m ?? 0, EPL9.wb) };
  if (l.wb && (Math.abs(l.wb.a_b) > EPL9.wb || Math.abs(l.wb.g_m) > EPL9.wb)) missing.push('Part of the WB shift (limited to ±7)');

  if (l.effect) {
    if (l.effect.type === 'clarity') missing.push('Clarity');
    else {
      missing.push(l.effect.type === 'halation' ? 'Halation glow' : 'Bloom glow');
      alternatives.push('Soft Focus art filter for a similar glow (it replaces the picture mode settings)');
    }
  }
  if (l.art_effect === 'pin_hole') alternatives.push('Pin Hole art filter (it replaces the picture mode settings)');
  else if (l.art_effect === 'star_light') missing.push('Star Light effect');
  if (mono && l.effect === null && /grain|tri-?x|hp5|delta|ilford/i.test(l.name)) alternatives.push('Grainy Film art filter for heavy grain');

  return {
    mode, contrast: clamp(l.advice.contrast ?? 0, EPL9.pm), sharpness: clamp(l.advice.sharpness ?? 0, EPL9.pm),
    saturation, gradation, bwFilter, monoColor, wb, highlights, midtones, shadows, alternatives, missing,
  };
}

const sg = (v: number) => (v > 0 ? `+${v}` : v < 0 ? `−${-v}` : '±0');

/** The Markdown card of one look for the E-PL9. */
export function epl9Card(l: Look): string {
  const r = toEpl9(l);
  const out = [`# ${l.name} — Olympus PEN E-PL9`, ''];
  if (l.notes) out.push(l.notes, '');
  out.push('## Picture Mode', '', `- **Mode:** ${r.mode}`, `- **Contrast:** ${sg(r.contrast)}`, `- **Sharpness:** ${sg(r.sharpness)}`);
  if (r.mode !== 'Monotone') out.push(`- **Saturation:** ${sg(r.saturation)}`);
  else out.push(`- **B&W Filter:** ${r.bwFilter}`, `- **Monochrome Color:** ${r.monoColor}`);
  out.push(`- **Gradation:** ${r.gradation}`, '', '## Tone and colour', '',
    `- **Highlight & Shadow Control:** highlights ${sg(r.highlights)}, midtones ${sg(r.midtones)}, shadows ${sg(r.shadows)}`,
    `- **WB compensation:** A ${sg(r.wb.a_b)} (Red–Blue), G ${sg(r.wb.g_m)} (Green–Magenta)`);
  if (r.alternatives.length) out.push('', '## Also try', '', ...r.alternatives.map((a) => `- ${a}`));
  if (r.missing.length) out.push('', '## Not on the stock E-PL9', '',
    'The RapidRAW preset for this look includes these, for RAW files:', '', ...r.missing.map((m) => `- ${m}`));
  out.push('', '_An approximation with stock settings. Made with the Caduceus Control Panel._', '');
  return out.join('\n');
}
