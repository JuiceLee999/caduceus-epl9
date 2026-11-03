// Pack model (schema "caduceus-pack/1") and its structural parsing. The value vocabulary is the one of the repo's
// library/bundle JSON (bundles/*.json, patches/bundles/build.py) so packs read naturally next to the Python tools.

export const SECTORS = ['Yellow', 'Orange', 'Orange-red', 'Red', 'Magenta', 'Violet', 'Blue', 'Blue-cyan', 'Cyan',
  'Green-cyan', 'Green', 'Yellow-green'] as const;
// v0.22 firmware "natural grain" (camera Noise Filter). JSON name -> slot byte -> camera label:
//   off -> 0 "Global" (Noise Filter untouched), standard -> 6 "Off" (Standard), fine -> 1 "Fine" (Low), film -> 2 "Film" (Off).
// Older bytes 3..5 read as film. Index = share-code digit (v1/v2: off/fine/film = old 0/1/2; standard = digit 6, v5/v6).
export const GRAINS = ['off', 'fine', 'film', 'standard'] as const;
export const GRAIN_BYTE: Record<string, number> = { off: 0, fine: 1, film: 2, standard: 6 };
export const GRAIN_LABEL: Record<string, string> = { off: 'Camera', standard: 'Standard', fine: 'Low', film: 'Off (most texture)' };   // "Noise reduction: …"
// Older names (packs / share codes made before v0.22), by their old byte: low -> fine, medium..extreme -> film.
export const LEGACY_GRAINS = ['off', 'low', 'medium', 'high', 'heavy', 'extreme'] as const;
export const grainFromByte = (b: number): Grain => (b <= 0 ? 'off' : b === 1 ? 'fine' : b === 6 ? 'standard' : b > 6 ? 'off' : 'film');
export const grainFromName = (v: string): Grain | undefined =>
  (GRAINS as readonly string[]).includes(v) ? (v as Grain) : v === 'med' ? 'film'
    : v === 'global' ? 'off'
    : (LEGACY_GRAINS as readonly string[]).includes(v) ? grainFromByte(LEGACY_GRAINS.indexOf(v as never)) : undefined;
export const EFFECTS = ['none', 'bloom', 'halation', 'clarity'] as const;
export const TINTS = ['neutral', 'red', 'amber', 'warm', 'cool'] as const;
// art_effect +46 (patches/bundles ART). 4/5 (white edge, frame) are legacy values the v0.15+ camera treats as Off.
export const ARTS = ['off', 'star_light', 'pin_hole', 'blur', 'white_edge', 'frame'] as const;
export const MONO_FILTERS = ['none', 'yellow', 'orange', 'red', 'green', 'blue'] as const;
export const SLOT_NAMES = ['COLOR1', 'COLOR2', 'COLOR3', 'COLOR4', 'MONO1', 'MONO2', 'MONO3', 'MONO4'] as const;
export const MAX_LOOKS = 32;
export const NAME_MAX = 12;
export const NOTE_MAX = 200;
export const PACK_SCHEMA = 'caduceus-pack/1';

export type Grain = (typeof GRAINS)[number];
export type EffectType = (typeof EFFECTS)[number];
export type Tint = (typeof TINTS)[number];
export type Art = (typeof ARTS)[number];
export type MonoFilter = (typeof MONO_FILTERS)[number];
export type SlotName = (typeof SLOT_NAMES)[number];

export interface Effect { type: Exclude<EffectType, 'none'>; strength: number; tint?: Tint }
export interface Advice {
  tone?: { highlights: number; shadows: number; midtones: number };
  contrast?: number;
  mono_filter?: { colour: MonoFilter; strength: number };
}
/** Per-look tone (LOOKS.BIN v0.19 tone block, colour looks only). H/S/M -7..7: the Film pick writes them to the profile's stock tone settings.
 *  Blacks/Whites -5..5: the two curve ends, placed into COLOR slots of BUNDLES.BIN (+47/+48). 0 = stock. */
export interface Tone { highlights: number; shadows: number; midtones: number; blacks: number; whites: number }
export const TONE_KEYS = ['highlights', 'shadows', 'midtones', 'blacks', 'whites'] as const;
export const TONE_HSM_MAX = 7, TONE_BW_MAX = 5;
export const toneLimit = (k: keyof Tone) => (k === 'blacks' || k === 'whites' ? TONE_BW_MAX : TONE_HSM_MAX);
export const zeroTone = (): Tone => ({ highlights: 0, shadows: 0, midtones: 0, blacks: 0, whites: 0 });
export const toneIsZero = (t: Tone) => TONE_KEYS.every((k) => t[k] === 0);

export interface Look {
  name: string;
  notes: string;
  kind: 'colour' | 'mono';
  hue: number[];       // 12, UI sector order, -7..7
  light: number[];     // 12, -7..7
  sat: number[];       // 12, -5..5 (advice: the camera's own per-profile saturation; stored for MONO colour slots)
  grain: Grain;
  wb: { a_b: number; g_m: number } | null;
  effect: Effect | null;
  vignette: number;    // -5..5 (stored only)
  art_effect: Art;     // COLOR slots of BUNDLES.BIN only: LOOKS.BIN has no field for it
  tone: Tone;          // LOOKS.BIN tone block when non-zero (H/S/M/B/W); B/W also go into COLOR slots of BUNDLES.BIN
  advice: Advice;      // camera settings the look recommends (preview only; not in any card file)
  origin?: string;     // app-only: the built-in library look this one came from (for Reset look); not exported
  lib?: string;        // app-only: fingerprint of the library values it was copied from (unmodified = still equal)
}
export interface Pack {
  schema: typeof PACK_SCHEMA;
  name: string;
  looks: Look[];
  slots: Partial<Record<SlotName, number>>;   // starter BUNDLES.BIN: slot -> look index
}

export const zeros12 = () => new Array<number>(12).fill(0);

export function blankLook(kind: 'colour' | 'mono' = 'colour', name = kind === 'mono' ? 'New Mono' : 'New Look'): Look {
  return {
    name, notes: '', kind, hue: zeros12(), light: zeros12(), sat: zeros12(), grain: 'off', wb: null, effect: null,
    vignette: 0, art_effect: 'off', tone: zeroTone(), advice: kind === 'mono' ? { mono_filter: { colour: 'none', strength: 1 } } : {},
  };
}

export const cloneLook = (l: Look): Look => JSON.parse(JSON.stringify(l));

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const intArr = (v: unknown, what: string): number[] => {
  if (!Array.isArray(v) || v.length !== 12 || !v.every((x) => Number.isInteger(x)))
    throw new Error(`${what}: need 12 integers`);
  return [...v] as number[];
};
const int = (v: unknown, what: string, dflt = 0): number => {
  if (v === undefined) return dflt;
  if (!Number.isInteger(v)) throw new Error(`${what}: need an integer`);
  return v as number;
};
function oneOf<T extends readonly string[]>(v: unknown, list: T, what: string, dflt: T[number]): T[number] {
  if (v === undefined || v === null) return dflt;
  if (typeof v === 'string' && list === (GRAINS as readonly string[]) && grainFromName(v)) return grainFromName(v) as T[number];
  if (typeof v !== 'string' || !list.includes(v)) throw new Error(`${what}: ${JSON.stringify(v)} (use ${list.join(', ')})`);
  return v as T[number];
}

/** Structural parse of one look (types and shapes; value ranges are checked by format.validateLook). */
export function parseLook(v: unknown, what = 'look'): Look {
  if (!isObj(v)) throw new Error(`${what}: must be an object`);
  const kind = v.kind === 'mono' ? 'mono' : v.kind === undefined || v.kind === 'colour' ? 'colour' : null;
  if (!kind) throw new Error(`${what}: kind must be "colour" or "mono"`);
  if (typeof v.name !== 'string') throw new Error(`${what}: name must be a string`);
  let wb: Look['wb'] = null;
  if (v.wb !== undefined && v.wb !== null) {
    if (!isObj(v.wb)) throw new Error(`${what}: wb must be {"a_b": n, "g_m": n} or null`);
    wb = { a_b: int(v.wb.a_b, `${what} wb a_b`), g_m: int(v.wb.g_m, `${what} wb g_m`) };
  }
  let effect: Effect | null = null;
  if (v.effect !== undefined && v.effect !== null) {
    if (!isObj(v.effect)) throw new Error(`${what}: effect must be an object or null`);
    const type = oneOf(v.effect.type, EFFECTS, `${what} effect type`, 'none');
    if (type !== 'none') {
      effect = { type, strength: int(v.effect.strength, `${what} effect strength`, -1) };
      if (v.effect.tint !== undefined) effect.tint = oneOf(v.effect.tint, TINTS, `${what} effect tint`, 'neutral');
    }
  }
  const tone = zeroTone();
  if (v.tone !== undefined && v.tone !== null) {
    if (!isObj(v.tone)) throw new Error(`${what}: tone must be {"highlights", "shadows", "midtones", "blacks", "whites"}`);
    for (const k of Object.keys(v.tone)) if (!(TONE_KEYS as readonly string[]).includes(k)) throw new Error(`${what}: unknown tone field ${k}`);
    for (const k of TONE_KEYS) tone[k] = int(v.tone[k], `${what} tone ${k}`);
  }
  const adv: Advice = {};
  if (isObj(v.advice)) {
    const a = v.advice;
    if (isObj(a.tone)) adv.tone = { highlights: int(a.tone.highlights, 'tone'), shadows: int(a.tone.shadows, 'tone'), midtones: int(a.tone.midtones, 'tone') };
    if (a.contrast !== undefined) adv.contrast = int(a.contrast, 'contrast');
    if (isObj(a.mono_filter)) adv.mono_filter = { colour: oneOf(a.mono_filter.colour, MONO_FILTERS, 'mono filter', 'none'), strength: int(a.mono_filter.strength, 'mono filter strength', 1) };
  }
  return {
    name: v.name,
    notes: typeof v.notes === 'string' ? v.notes : '',
    kind,
    hue: intArr(v.hue ?? zeros12(), `${what} hue`),
    light: intArr(v.light ?? zeros12(), `${what} light`),
    sat: intArr(v.sat ?? zeros12(), `${what} sat`),
    grain: oneOf(v.grain, GRAINS, `${what} grain`, 'off'),
    wb,
    effect,
    vignette: int(v.vignette, `${what} vignette`),
    art_effect: oneOf(v.art_effect, ARTS, `${what} art_effect`, 'off'),
    tone,
    advice: adv,
    ...(typeof v.origin === 'string' ? { origin: v.origin } : {}),
    ...(typeof v.lib === 'string' ? { lib: v.lib } : {}),
  };
}

/** The pack without app-only bookkeeping (Look.origin / Look.lib), for files and share links. */
export const exportable = (p: Pack): Pack => ({ ...p, looks: p.looks.map(({ origin: _o, lib: _l, ...l }) => l) });

/** Structural parse of a pack file (JSON object). Throws with a readable message. */
export function parsePack(v: unknown): Pack {
  if (!isObj(v)) throw new Error('pack: not a JSON object');
  if (v.schema !== PACK_SCHEMA) throw new Error(`pack: schema ${JSON.stringify(v.schema)} (this app reads ${PACK_SCHEMA})`);
  if (!Array.isArray(v.looks)) throw new Error('pack: "looks" must be a list');
  const looks = v.looks.map((l, i) => parseLook(l, `look ${i + 1}`));
  const slots: Pack['slots'] = {};
  if (isObj(v.slots)) {
    for (const [k, i] of Object.entries(v.slots)) {
      if (!(SLOT_NAMES as readonly string[]).includes(k)) throw new Error(`pack: unknown slot ${k}`);
      if (i === null || i === undefined) continue;
      if (!Number.isInteger(i) || (i as number) < 0 || (i as number) >= looks.length) throw new Error(`pack: slot ${k} -> bad look index`);
      slots[k as SlotName] = i as number;
    }
  }
  return { schema: PACK_SCHEMA, name: typeof v.name === 'string' ? v.name : 'My pack', looks, slots };
}
