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
  // Tone never existed before v0.19: any colour look still at zero tone whose name matches a library look gets
  // that look's tone (whatever else the user changed).
  for (const l of pack.looks) {
    if (l.kind !== 'colour' || !toneIsZero(l.tone)) continue;
    const src = libraryOrigin(l, library) ?? library.looks.find((o) => o.name.toLowerCase() === l.name.toLowerCase());
    if (src && !toneIsZero(src.tone)) { l.tone = { ...src.tone }; updated++; }
  }
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

/** The library look `l` came from, if any. */
export const libraryOrigin = (l: Look, library: Pack): Look | undefined =>
  l.origin === undefined ? undefined : library.looks.find((o) => o.name === l.origin);

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

