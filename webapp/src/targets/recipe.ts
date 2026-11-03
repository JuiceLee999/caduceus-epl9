// Recipe card (any camera): one Markdown card per look with every parameter in plain words, to dial in by hand.
import { GRAIN_LABEL, SECTORS, type Look } from '../pack';
import type { Target } from './types';

const sg = (v: number) => (v > 0 ? `+${v}` : v < 0 ? `−${-v}` : '0');
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, ' ');
const ART: Record<string, string> = { off: 'Off', star_light: 'Star Light', pin_hole: 'Pin Hole', blur: 'Blur (Soft Focus)', white_edge: 'White Edge', frame: 'Frame' };

function wbText(wb: Look['wb']): string {
  if (!wb || (!wb.a_b && !wb.g_m)) return 'No shift (keep the camera\'s own white balance fine-tune)';
  const ab = wb.a_b ? `${wb.a_b > 0 ? 'Amber' : 'Blue'} ${Math.abs(wb.a_b)} (A–B ${sg(wb.a_b)})` : 'A–B 0';
  const gm = wb.g_m ? `${wb.g_m > 0 ? 'Green' : 'Magenta'} ${Math.abs(wb.g_m)} (G–M ${sg(wb.g_m)})` : 'G–M 0';
  return `${ab}, ${gm}`;
}

function effectText(e: Look['effect']): string {
  if (!e) return 'Off';
  if (e.type === 'clarity') return `Clarity ${e.strength} of 5 (local contrast)`;
  const tint = e.tint ?? (e.type === 'halation' ? 'red' : 'neutral');
  return `Glow ${e.strength} of 5 (${e.type === 'halation' ? 'halation, ' : ''}${tint} tint)`;
}

/** The Markdown recipe card of one look. */
export function recipeCard(l: Look): string {
  const out: string[] = [`# ${l.name}`, ''];
  if (l.notes) out.push(l.notes, '');
  out.push(`- **Type:** ${l.kind === 'mono' ? 'Monochrome' : 'Colour'}`);
  if (l.kind === 'mono') {
    const mf = l.advice.mono_filter;
    out.push(`- **Colour filter:** ${mf && mf.colour !== 'none' ? `${cap(mf.colour)}, strength ${mf.strength}` : 'None'}`);
  }
  out.push(`- **White balance shift:** ${wbText(l.wb)}`);
  out.push(`- **Noise reduction:** ${GRAIN_LABEL[l.grain] ?? cap(l.grain)}`);
  out.push(`- **Glow / clarity:** ${effectText(l.effect)}`);
  if (l.kind === 'colour') out.push(`- **Art effect:** ${ART[l.art_effect] ?? l.art_effect}`);
  if (l.advice.contrast) out.push(`- **Contrast:** ${sg(l.advice.contrast)}`);
  if (l.kind === 'colour') {
    const t = l.tone;
    out.push('', '## Tone', '',
      `- **Highlights:** ${sg(t.highlights)} (of ±7)`, `- **Midtones:** ${sg(t.midtones)} (of ±7)`, `- **Shadows:** ${sg(t.shadows)} (of ±7)`,
      `- **Blacks:** ${sg(t.blacks)} (of ±5; + lifts to a matte black, − deepens)`,
      `- **Whites:** ${sg(t.whites)} (of ±5; − rolls the white point off, + brightens)`);
    out.push('', '## Colour by hue', '', '| Colour | Hue (±7) | Saturation (±5) | Lightness (±7) |', '|---|---|---|---|');
    SECTORS.forEach((s, k) => out.push(`| ${s} | ${sg(l.hue[k])} | ${sg(l.sat[k])} | ${sg(l.light[k])} |`));
  }
  out.push('', 'Steps are Olympus / OM System steps. On other cameras, scale them to the nearest available setting.', '',
    '_Made with the Caduceus Control Panel._', '');
  return out.join('\n');
}

const fileName = (name: string) => (name.replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'look') + '.md';

export const recipe: Target = {
  id: 'recipe-card',
  label: 'Recipe card (any camera)',
  status: 'ready',
  note: 'A readable card per look with every setting in plain words, for dialling in by hand.',
  supports: () => true,
  export(pack) {
    const used = new Set<string>();
    return pack.looks.map((l) => {
      let n = fileName(l.name);
      for (let k = 2; used.has(n.toLowerCase()); k++) n = fileName(`${l.name}-${k}`);
      used.add(n.toLowerCase());
      return { name: n, data: recipeCard(l), type: 'text/markdown' };
    });
  },
};
