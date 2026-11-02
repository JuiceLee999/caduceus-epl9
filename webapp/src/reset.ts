// Resetting looks and packs to the built-in library (or to neutral for looks that did not come from it).
import { blankLook, cloneLook, type Look, type Pack } from './pack';

/** A copy of the library pack whose looks remember which library look they are (Look.origin). */
export function standardPack(library: Pack): Pack {
  const p: Pack = JSON.parse(JSON.stringify(library));
  for (const l of p.looks) l.origin = l.name;
  return p;
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
    const r: Look = { ...cloneLook(src), origin: src.name };
    if (otherNames.some((n) => n.toLowerCase() === src.name.toLowerCase())) r.name = l.name;
    return r;
  }
  const r: Look = { ...blankLook(l.kind, l.name), notes: l.notes };
  if (l.origin !== undefined) r.origin = l.origin;
  return r;
}

