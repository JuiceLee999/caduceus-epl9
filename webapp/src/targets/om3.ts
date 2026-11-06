// OM SYSTEM OM-3 with Caduceus for OM-3 (androidfanman/caduceus-om3): translate a pack to its card files on export.
// The pack stays the one shared format. The OM-3 has 5 looks for each of COLOR 1-4, so the first 20 colour looks fill
// COLOR 1-5, 2-5... in list order; toOm3 limits ranges (docs/OM3_NOTES.md lists what carries over). Hue numbers copy
// across as they are: the direction on each body is an open question there.
import { COLORS, PER, emptyBank, profilesBin, readProfiles, toOm3, type Bank } from '../om3';
import { PACK_SCHEMA, type Look, type Pack } from '../pack';
import type { Target } from './types';

export const OM3_REPO = 'https://github.com/androidfanman/caduceus-om3';
export interface Placed { name: string; k: number; v: number; changed: string[]; dropped: string[] }
export interface Om3Bank { bank: Bank; placed: Placed[]; mono: number; extra: string[]; lens: number }

export function packToBank(p: Pack): Om3Bank {
  const bank = emptyBank(), placed: Placed[] = [];
  const colour = p.looks.filter((l) => l.kind === 'colour');
  colour.slice(0, COLORS * PER).forEach((src, i) => {
    const c = toOm3(src), k = Math.floor(i / PER), v = i % PER;
    bank[k][v] = c.look;
    placed.push({ name: src.name, k, v, changed: c.changed, dropped: c.dropped });
  });
  return {
    bank, placed, mono: p.looks.length - colour.length,
    extra: colour.slice(COLORS * PER).map((l) => l.name),
    lens: colour.slice(0, COLORS * PER).filter((l) => l.lens_correction).length,
  };
}

/** An OM-3 bank as a pack. Empty numbers close up, so re-exporting can move looks. */
export function bankToPack(bank: Bank, name: string): Pack {
  return { schema: PACK_SCHEMA, name, looks: bank.flat().filter((l): l is Look => !!l), slots: {} };
}
export const looksBinToPack = (b: Uint8Array, name: string): Pack => bankToPack(readProfiles(b), name);

// Links from the OM-3 panel: op1_ one look, ob1_ a bank, base64url(deflate(JSON)).
export const isOm3Code = (t: string) => /(^|#)\s*o[pb]1_/.test(t.trim());
export async function decodeOm3Code(t: string): Promise<unknown> {
  const s = t.trim().replace(/^.*#/, '').replace(/\s+/g, '').slice(4);
  try {
    const bytes = Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')), (c) => c.charCodeAt(0));
    const out = new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate')));
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(await out.arrayBuffer()));
  } catch { throw new Error('This link is damaged or incomplete: copy it again.'); }
}

export const om3: Target = {
  id: 'om3-caduceus',
  label: 'OM SYSTEM OM-3 (Caduceus for OM-3)',
  status: 'ready',
  doc: OM3_REPO,
  note: 'LOOKS.BIN and NAMES.BIN for the Film page (Caduceus for OM-3 v0.19 or later).',
  supports: (l) => (l.kind === 'colour' ? true : 'OM-3 looks are colour only.'),
  export: (pack) => [{ name: 'OM3MOD/LOOKS.BIN', data: profilesBin(packToBank(pack).bank) }],
};
