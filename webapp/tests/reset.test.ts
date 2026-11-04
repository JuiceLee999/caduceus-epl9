import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { encodeLooksBin } from '../src/format';
import { exportable, parsePack } from '../src/pack';
import { decodeLookCode, encodeLookCode } from '../src/sharecode';
import { fromLibrary, lookFingerprint, migratePack, replaceRetiredLooks, resetLook, standardPack } from '../src/reset';
import { blankLook, toneIsZero, zeroTone } from '../src/pack';
import libraryJson from '../src/data/library.json';

const LIB = parsePack(libraryJson);
const RELEASE_LOOKS = join(__dirname, '../../releases/v0.24/card/EP7MOD/LOOKS.BIN');
const hex = (b: Uint8Array) => Buffer.from(b).toString('hex');
const names = (p: { looks: { name: string }[] }, skip: number) => p.looks.filter((_, k) => k !== skip).map((l) => l.name);

function mangle(p: ReturnType<typeof standardPack>, i: number) {
  const l = p.looks[i];
  l.hue = l.hue.map((v) => (v + 3) % 7); l.light[0] = -4; l.sat[5] = 2; l.grain = 'film';
  l.wb = { a_b: 3, g_m: -2 }; l.effect = { type: 'clarity', strength: 4 }; l.notes = 'changed';
  l.tone = { highlights: 2, shadows: -3, midtones: 1, blacks: 2, whites: -1 };
}

describe('reset', () => {
  describe('replaceRetiredLooks: saved Nostalgic of any age', () => {
    const NOST = { name: 'Nostalgic', hue: [0, 1, 0, 1, 0, 0, 0, 0, 0, -2, -3, -2], light: [1, 1, 1, 0, 0, 0, -1, -1, 0, 0, 0, 0],
      sat: [2, 2, 1, 0, -1, -1, -2, -2, -2, -1, 0, 2], grain: 'fine', wb: { a_b: 2, g_m: 0 }, effect: null, vignette: 0,
      tone: { highlights: -2, shadows: 1, midtones: 1, blacks: 1, whites: -1 } };
    const zero = { highlights: 0, shadows: 0, midtones: 0, blacks: 0, whites: 0 };
    const make = (extra: Record<string, unknown>, drop: string[] = []) => {
      const p = standardPack(LIB) as any;
      const i = p.looks.findIndex((l: any) => l.name === 'Provia 400');
      p.looks[i] = { ...p.looks[i], ...NOST, ...extra };
      for (const k of drop) delete p.looks[i][k];
      return { p, i };
    };
    const cases: [string, Record<string, unknown>, string[]][] = [
      ['an old fingerprint', { origin: 'Nostalgic', lib: 'deadbeef' }, []],
      ['origin but no fingerprint', { origin: 'Nostalgic' }, ['lib']],
      ['no origin (imported)', {}, ['origin', 'lib']],
      ['no tone (pre-v0.19)', { origin: 'Nostalgic', lib: 'deadbeef', tone: zero }, []],
      ['no sat (from a LOOKS.BIN)', { sat: new Array(12).fill(0) }, ['origin', 'lib']],
    ];
    it.each(cases)('%s becomes Provia 400 in place', (_n, extra, drop) => {
      const { p, i } = make(extra, drop);
      const r = replaceRetiredLooks(p, LIB);
      expect(r.replaced).toBe(1);
      expect(r.pack.looks.length).toBe(LIB.looks.length);
      expect(r.pack.looks[i]).toEqual(fromLibrary(LIB.looks[i]));
      expect(replaceRetiredLooks(r.pack, LIB).replaced).toBe(0);
    });
    it('keeps a copy the user edited', () => {
      const { p } = make({ origin: 'Nostalgic', lib: 'deadbeef', vignette: 2 });
      const r = replaceRetiredLooks(p, LIB);
      expect(r.replaced).toBe(0);
      expect(r.pack.looks.some((l: any) => l.name === 'Nostalgic')).toBe(true);
    });
    it('a pack already holding Provia 400 loses the old copy; slots follow', () => {
      const p = standardPack(LIB) as any;
      p.looks.length = 6;
      const prov = p.looks.findIndex((l: any) => l.name === 'Provia 400');
      p.looks.splice(1, 0, { ...p.looks[0], ...NOST, origin: 'Nostalgic', lib: 'deadbeef', art_effect: 'off' });
      const after = p.looks[prov + 2].name;
      p.slots = { COLOR1: 1, COLOR2: prov + 2, MONO1: 1 };
      const r = replaceRetiredLooks(p, LIB);
      expect(r.pack.looks.filter((l: any) => l.name === 'Nostalgic')).toEqual([]);
      expect(r.pack.looks[r.pack.slots.COLOR1!].name).toBe('Provia 400');
      expect(r.pack.looks[r.pack.slots.COLOR2!].name).toBe(after);
      expect(r.pack.slots.MONO1).toBeUndefined();
    });
  });

  describe('replaced library look (Nostalgic -> Provia 400)', () => {
    const oldPack = (edit = false) => {
      const p = standardPack(LIB);
      const i = p.looks.findIndex((l) => l.name === 'Provia 400');
      const old = { ...p.looks[i], name: 'Nostalgic', origin: 'Nostalgic', wb: { a_b: 2, g_m: 0 } };
      p.looks[i] = { ...old, lib: lookFingerprint(old) };
      if (edit) p.looks[i].sat = p.looks[i].sat.map(() => 3);
      return { p, i };
    };
    const prev = LIB.looks.map((l) => (l.name === 'Provia 400' ? 'Nostalgic' : l.name));
    it('an unedited saved copy becomes the new look in place, in a full pack', () => {
      const { p, i } = oldPack();
      const m = migratePack(p, LIB, prev);
      expect(m.pack.looks.length).toBe(LIB.looks.length);
      expect(m.pack.looks[i].name).toBe('Provia 400');
      expect(m.pack.looks[i].wb).toEqual(LIB.looks[i].wb);
      expect(m.pack.looks.filter((l) => l.name === 'Nostalgic')).toEqual([]);
      expect(m.updated).toBe(1);
    });
    it('an edited saved copy is kept', () => {
      const { p, i } = oldPack(true);
      const m = migratePack(p, LIB, prev);
      expect(m.pack.looks[i].name).toBe('Nostalgic');
      expect(m.pack.looks[i].sat[0]).toBe(3);
    });
  });

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

describe('migration of packs saved before tone', () => {
  it('a library look with a stale (pre-tone) fingerprint and zero tone takes the library tone', () => {
    const old = standardPack(LIB);
    for (const l of old.looks) { l.tone = zeroTone(); l.lib = 'deadbeef'; }   // fingerprint from an older app version
    const m = migratePack(old, LIB);
    const portra = m.pack.looks.find((l) => l.origin === 'Portra 400')!;
    expect(toneIsZero(portra.tone)).toBe(false);
    expect(m.pack.looks.every((l, i) => JSON.stringify(l.tone) === JSON.stringify(LIB.looks[i].tone))).toBe(true);
  });
  it('a look the user edited (hue changed) keeps its values', () => {
    const old = standardPack(LIB);
    old.looks[0].hue[0] += 1; old.looks[0].tone = zeroTone(); old.looks[0].lib = 'deadbeef';
    const m = migratePack(old, LIB);
    expect(m.pack.looks[0].hue[0]).toBe(LIB.looks[0].hue[0] + 1);
  });
});
