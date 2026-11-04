// Resetting looks and packs to the built-in library (or to neutral for looks that did not come from it).
import { MAX_LOOKS, blankLook, cloneLook, toneIsZero, type Look, type Pack } from './pack';

/** Fingerprint of what the user can edit in a look (everything but the app-only fields and the advice). */
export function lookFingerprint(l: Look, withTone = true): string {
  const v = [l.name, l.notes, l.kind, l.hue, l.light, l.sat, l.grain, l.wb, l.effect, l.vignette, l.art_effect,
    withTone ? l.tone : null];
  const s = JSON.stringify(v);
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 0x01000193);
  return (h >>> 0).toString(16).padStart(8, '0');
}

/** A pack copy of library look `src` that remembers where it came from (origin) and its values (lib). */
export const fromLibrary = (src: Look): Look => ({ ...cloneLook(src), origin: src.name, lib: lookFingerprint(src) });

/** A copy of the library pack whose looks remember which library look they are (Look.origin, Look.lib). */
export function standardPack(library: Pack): Pack {
  const p: Pack = JSON.parse(JSON.stringify(library));
  p.looks = p.looks.map(fromLibrary);
  return p;
}

/** Did the user leave this library look as it was copied? Looks saved before Look.lib existed count as unmodified
 *  when they equal the current library look, or equal it except for a still-zero tone (pre-v0.19 libraries had none). */
export function unmodified(l: Look, src: Look): boolean {
  if (l.lib !== undefined && lookFingerprint(l) === l.lib) return true;
  // Fingerprints saved by older app versions don't cover tone, so also accept a look that still equals the library
  // look apart from notes and a still-zero (pre-tone) tone.
  const card = (x: Look) => lookFingerprint({ ...x, notes: '' }, false);
  return card(l) === card(src) && (toneIsZero(l.tone) || lookFingerprint(l) === lookFingerprint(src));
}

export interface Migration { pack: Pack; updated: number; added: number }

/**
 * Bring a saved pack up to a newer built-in library: every library look the user did not modify takes the latest
 * values (tone included); edited and user-made looks stay as they are. A pack made only of library looks (the
 * standard library, maybe reordered or trimmed by the user) also gets the looks that are new in this library
 * (`previousNames` = the library names the pack was saved with; unknown = add every missing one).
 */
export function migratePack(saved: Pack, library: Pack, previousNames?: string[]): Migration {
  const pack: Pack = JSON.parse(JSON.stringify(saved));
  let updated = 0, added = 0;
  pack.looks = pack.looks.map((l) => {
    const src = libraryOrigin(l, library);
    if (!src || !unmodified(l, src)) return l;
    const n = fromLibrary(src);
    if (lookFingerprint(n) !== lookFingerprint(l) || JSON.stringify(n.advice) !== JSON.stringify(l.advice)) updated++;
    return n;
  });
  if (pack.looks.length && pack.looks.every((l) => l.origin !== undefined)) {
    const have = new Set(pack.looks.map((l) => l.origin));
    const names = new Set(pack.looks.map((l) => l.name.toLowerCase()));
    for (const src of library.looks) {
      if (pack.looks.length >= MAX_LOOKS) break;
      if (have.has(src.name) || names.has(src.name.toLowerCase())) continue;
      if (previousNames?.includes(src.name)) continue;     // in the old library too: the user removed it
      pack.looks.push(fromLibrary(src));
      added++;
    }
  }
  return { pack, updated, added };
}

/** Library looks that were replaced: a look copied from the old one now belongs to the new one. */
const REPLACED_LOOKS: Record<string, string> = { Nostalgic: 'Provia 400' };

/** Every value set the built-in Nostalgic ever shipped with (tone zero: saved before looks had a tone). */
const isShippedNostalgic = (l: Look): boolean => {
  const eq = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
  const t = l.tone;
  const shippedTone = t.highlights === -2 && t.shadows === 1 && t.midtones === 1 && t.blacks === 1 && t.whites === -1;
  return l.name === 'Nostalgic' && l.kind === 'colour'
    && eq(l.hue, [0, 1, 0, 1, 0, 0, 0, 0, 0, -2, -3, -2]) && eq(l.light, [1, 1, 1, 0, 0, 0, -1, -1, 0, 0, 0, 0])
    && (eq(l.sat, [2, 2, 1, 0, -1, -1, -2, -2, -2, -1, 0, 2]) || l.sat.every((v) => v === 0))   // LOOKS.BIN has no sat
    && eq(l.wb, { a_b: 2, g_m: 0 }) && (shippedTone || toneIsZero(t))
    && l.grain === 'fine' && !l.effect && !l.vignette && l.art_effect === 'off';
};

/**
 * Swap saved copies of a replaced library look for the new one, however old the saved pack is. Recognised by its
 * shipped values, not its fingerprint (older apps wrote different ones), so this runs on every load, not only when
 * the library version changes. A copy with other values is the user's own edit and stays.
 */
export function replaceRetiredLooks(saved: Pack, library: Pack): { pack: Pack; replaced: number } {
  const pack: Pack = JSON.parse(JSON.stringify(saved));
  const src = library.looks.find((o) => o.name === REPLACED_LOOKS.Nostalgic);
  let replaced = 0;
  if (!src) return { pack, replaced };
  for (let i = pack.looks.length - 1; i >= 0; i--) {
    if (!isShippedNostalgic(pack.looks[i])) continue;
    replaced++;
    const have = pack.looks.findIndex((l) => l.name === src.name);
    if (have < 0) {
      pack.looks[i] = fromLibrary(src);
      // a toned look is COLOR-only: it cannot stay in a MONO slot
      for (const [s, v] of Object.entries(pack.slots)) if (v === i && s.startsWith('MONO')) delete pack.slots[s as keyof Pack['slots']];
      continue;
    }
    // already in the pack (added by an earlier library update): drop the old copy, its slots move to the new look
    pack.looks.splice(i, 1);
    const target = have > i ? have - 1 : have;
    for (const [s, v] of Object.entries(pack.slots) as [keyof Pack['slots'], number][]) {
      if (v === i) { if (s.startsWith('MONO')) delete pack.slots[s]; else pack.slots[s] = target; }
      else if (v > i) pack.slots[s] = v - 1;
    }
  }
  return { pack, replaced };
}

/** The library look `l` came from, if any. */
export const libraryOrigin = (l: Look, library: Pack): Look | undefined => {
  if (l.origin === undefined) return undefined;
  const name = REPLACED_LOOKS[l.origin] ?? l.origin;
  return library.looks.find((o) => o.name === name);
};

/**
 * `l` reset: a library look gets its shipped values back (and its shipped name, unless another look in the pack
 * now uses it); any other look becomes neutral, keeping its name, kind and notes.
 */
export function resetLook(l: Look, library: Pack, otherNames: string[] = []): Look {
  const src = libraryOrigin(l, library);
  if (src) {
    const r: Look = fromLibrary(src);
    if (otherNames.some((n) => n.toLowerCase() === src.name.toLowerCase())) r.name = l.name;
    return r;
  }
  const r: Look = { ...blankLook(l.kind, l.name), notes: l.notes };
  if (l.origin !== undefined) r.origin = l.origin;
  return r;
}

