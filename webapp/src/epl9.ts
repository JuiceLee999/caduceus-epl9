// Olympus PEN E-PL9 (stock firmware 1.1): translate a look into settings the camera already has, for dialling in by
// hand. No firmware mod is involved, so per-colour hue / saturation / lightness, glow / clarity and the curve ends have
// no equivalent. They are listed as "not on the E-PL9" so the user knows what the RapidRAW preset adds on RAW files.
//
// Camera controls, from the published specs (Imaging Resource spec sheet: art filters, gradation, WB presets) and the
// standard Olympus menus of this generation. Marked UNVERIFIED where the E-PL9 manual hasn't been checked yet:
//   Picture Mode: i-Enhance, Vivid, Natural, Muted, Portrait, Monotone, Custom (+ e-Portrait, Underwater, Art filters)
//   Contrast / Sharpness / Saturation: ±2 (UNVERIFIED range)
//   Gradation: Auto, Normal, High Key, Low Key
//   Monotone: B&W filter N, Ye, Or, R, G (no blue); Pict. Tone N, S, B, P, G (UNVERIFIED)
//   WB compensation: A–B ±7, G–M ±7 (UNVERIFIED range)
//   Highlight & Shadow Control: highlights ±7, shadows ±7, no midtone control (UNVERIFIED)
import type { Look, MonoFilter } from './pack';

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
  bwFilter?: 'N' | 'Ye' | 'Or' | 'R' | 'G';                  // Monotone only
  wb: { a_b: number; g_m: number };                           // compensation, ±7
  highlights: number; shadows: number;                        // Highlight & Shadow Control, ±7
  alternatives: string[];                                     // Art filters that come close to a part of the look
  missing: string[];                                          // parts of the look the stock camera can't do
}

const clamp = (v: number, lim: number) => Math.max(-lim, Math.min(lim, Math.round(v)));
const mean = (a: number[]) => a.reduce((s, x) => s + x, 0) / a.length;
const anyNonZero = (a: number[]) => a.some((x) => x !== 0);
const BW: Record<MonoFilter, Epl9Recipe['bwFilter']> = { none: 'N', yellow: 'Ye', orange: 'Or', red: 'R', green: 'G', blue: 'N' };

/** The closest stock E-PL9 settings for a look. Pure; the same look always gives the same recipe. */
export function toEpl9(l: Look): Epl9Recipe {
  const missing: string[] = [], alternatives: string[] = [];
  const mono = l.kind === 'mono';

  // Tone: the look's own tone block wins; older looks only carry it as advice.
  const t = l.tone.highlights || l.tone.shadows || l.tone.midtones ? l.tone : l.advice.tone ?? { highlights: 0, shadows: 0, midtones: 0 };
  const highlights = clamp(t.highlights, EPL9.hs), shadows = clamp(t.shadows, EPL9.hs);
  if (t.midtones) missing.push(`Midtones ${t.midtones > 0 ? '+' : ''}${t.midtones} (Highlight & Shadow Control has no midtone)`);
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
  }

  let bwFilter: Epl9Recipe['bwFilter'];
  if (mono) {
    const f = l.advice.mono_filter?.colour ?? 'none';
    bwFilter = BW[f];
    if (f === 'blue') missing.push('Blue B&W filter (the E-PL9 has Ye, Or, R, G)');
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
    saturation, gradation, bwFilter, wb, highlights, shadows, alternatives, missing,
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
  else out.push(`- **B&W Filter:** ${r.bwFilter}`, '- **Pict. Tone:** N');
  out.push(`- **Gradation:** ${r.gradation}`, '', '## Tone and colour', '',
    `- **Highlight & Shadow Control:** highlights ${sg(r.highlights)}, shadows ${sg(r.shadows)}`,
    `- **WB compensation:** A–B ${sg(r.wb.a_b)}, G–M ${sg(r.wb.g_m)}`);
  if (r.alternatives.length) out.push('', '## Also try', '', ...r.alternatives.map((a) => `- ${a}`));
  if (r.missing.length) out.push('', '## Not on the stock E-PL9', '',
    'The RapidRAW preset for this look includes these, for RAW files:', '', ...r.missing.map((m) => `- ${m}`));
  out.push('', '_An approximation with stock settings. Made with the Caduceus Control Panel._', '');
  return out.join('\n');
}
