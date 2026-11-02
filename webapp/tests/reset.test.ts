import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { encodeLooksBin } from '../src/format';
import { exportable, parsePack } from '../src/pack';
import { decodeLookCode, encodeLookCode } from '../src/sharecode';
import { fromLibrary, lookFingerprint, migratePack, resetLook, standardPack } from '../src/reset';
import { blankLook, toneIsZero, zeroTone } from '../src/pack';
import libraryJson from '../src/data/library.json';

const LIB = parsePack(libraryJson);
const RELEASE_LOOKS = join(__dirname, '../../releases/v0.19/card/EP7MOD/LOOKS.BIN');
const hex = (b: Uint8Array) => Buffer.from(b).toString('hex');
const names = (p: { looks: { name: string }[] }, skip: number) => p.looks.filter((_, k) => k !== skip).map((l) => l.name);

function mangle(p: ReturnType<typeof standardPack>, i: number) {
  const l = p.looks[i];
  l.hue = l.hue.map((v) => (v + 3) % 7); l.light[0] = -4; l.sat[5] = 2; l.grain = 'high';
  l.wb = { a_b: 3, g_m: -2 }; l.effect = { type: 'clarity', strength: 4 }; l.notes = 'changed';
  l.tone = { highlights: 2, shadows: -3, midtones: 1, blacks: 2, whites: -1 };
}

describe('reset', () => {
  it('standard pack encodes to the shipped LOOKS.BIN', () => {
    expect(hex(encodeLooksBin(standardPack(LIB)))).toBe(hex(new Uint8Array(readFileSync(RELEASE_LOOKS))));
  });

  it('resetting every edited library look gives byte-identical LOOKS.BIN', () => {
    const want = hex(encodeLooksBin(LIB));
    const p = standardPack(LIB);
    p.looks.forEach((_, i) => mangle(p, i));
    p.looks[2].name = 'Renamed';
    expect(hex(encodeLooksBin(p))).not.toBe(want);
    p.looks = p.looks.map((l, i) => resetLook(l, LIB, names(p, i)));
    expect(hex(encodeLooksBin(p))).toBe(want);
    expect(exportable(p).looks).toEqual(LIB.looks);
  });

  it('a renamed library look keeps its name if the shipped one is taken', () => {
    const p = standardPack(LIB);
    p.looks[0].name = 'Mine';
    p.looks[1].name = LIB.looks[0].name;
    const r = resetLook(p.looks[0], LIB, names(p, 0));
    expect(r.name).toBe('Mine');
    expect(r.hue).toEqual(LIB.looks[0].hue);
  });

  it('a non-library look resets to neutral, keeping name, kind and notes', () => {
    const p = standardPack(LIB);
    const imported = decodeLookCode(encodeLookCode(p.looks[0]));  // same values, but no library origin
    imported.notes = 'mine';
    const r = resetLook(imported, LIB);
    expect(r.name).toBe(imported.name);
    expect(r.notes).toBe('mine');
    expect(r.kind).toBe(imported.kind);
    expect([...r.hue, ...r.light, ...r.sat].every((v) => v === 0)).toBe(true);
    expect([r.grain, r.wb, r.effect, r.vignette]).toEqual(['off', null, null, 0]);
    expect(r.tone).toEqual({ highlights: 0, shadows: 0, midtones: 0, blacks: 0, whites: 0 });
  });

  it('origin stays out of exported files and share codes', () => {
    const p = standardPack(LIB);
    expect(p.looks.every((l) => l.origin === l.name)).toBe(true);
    expect(JSON.stringify(exportable(p))).not.toContain('"origin"');
  });
});

describe('library migration (saved pack -> newer built-in library)', () => {
  const card = (p: { looks: Parameters<typeof lookFingerprint>[0][] }) => p.looks.map((l) => lookFingerprint(l));

  it('the current standard pack is already up to date', () => {
    const m = migratePack(standardPack(LIB), LIB, LIB.looks.map((l) => l.name));
    expect([m.updated, m.added]).toEqual([0, 0]);
    expect(card(m.pack)).toEqual(card(LIB));
  });

  it('a pre-tone saved pack (no Look.lib) gets the tone; edited and own looks are kept', () => {
    const old = standardPack(LIB);
    old.looks.forEach((l) => { delete l.lib; l.tone = zeroTone(); });     // saved before the library had tone
    old.looks[2].hue = old.looks[2].hue.map((v) => (v === 7 ? 6 : v + 1));  // the user edited this one
    const edited = JSON.parse(JSON.stringify(old.looks[2]));
    const own = { ...blankLook('colour', 'My Own'), notes: 'mine' };
    old.looks.push(own);
    old.looks.splice(28, 1);                                                // and removed one
    const m = migratePack(old, LIB);
    expect(m.updated).toBe(old.looks.length - 2 - LIB.looks.filter((l) => toneIsZero(l.tone)).length);
    expect(m.added).toBe(0);                                                // has an own look: not the standard pack
    m.pack.looks.forEach((l) => {
      if (l.name === 'My Own') expect(l).toEqual(own);
      else if (l.name === edited.name) expect(l).toEqual(edited);
      else expect(lookFingerprint(l)).toBe(lookFingerprint(LIB.looks.find((o) => o.name === l.origin)!));
    });
    expect(hex(encodeLooksBin(m.pack))).not.toBe(hex(encodeLooksBin(old)));
  });

  it('a standard pack from an older library: unmodified looks updated, edits kept, new library looks added', () => {
    const oldLib = parsePack(libraryJson);
    oldLib.looks[0].hue = oldLib.looks[0].hue.map(() => 0);
    oldLib.looks[0].tone = zeroTone();
    const removedName = oldLib.looks.splice(19, 1)[0].name;                 // a look the new library adds
    const saved = standardPack(oldLib);
    saved.looks[1].light[0] = saved.looks[1].light[0] === 3 ? 2 : 3;          // user edit (fingerprint no longer matches)
    const edited = JSON.parse(JSON.stringify(saved.looks[1]));
    const m = migratePack(saved, LIB, oldLib.looks.map((l) => l.name));
    expect(m.pack.looks[0]).toEqual(fromLibrary(LIB.looks[0]));
    expect(m.pack.looks[1]).toEqual(edited);
    expect(m.added).toBe(1);
    expect(m.pack.looks.at(-1)!.name).toBe(removedName);
    expect(m.updated).toBe(1);
    // the user had removed it themselves (it was in the old library): not re-added
    const m2 = migratePack(saved, LIB, [...oldLib.looks.map((l) => l.name), removedName]);
    expect(m2.added).toBe(0);
  });

  it('origin and lib stay out of exported files', () => {
    expect(JSON.stringify(exportable(standardPack(LIB)))).not.toMatch(/"origin"|"lib"/);
  });
});
