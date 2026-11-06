// The E-P7-convention pack -> OM-3 card files translation (src/targets/om3.ts).
import { describe, expect, it } from 'vitest';
import libraryJson from '../src/data/library.json';
import { COLORS, PER, profilesBin, readProfiles, validateBank } from '../src/om3';
import { blankLook, parsePack, type Pack } from '../src/pack';
import { looksBinToPack, packToBank } from '../src/targets/om3';
import { CAMERAS } from '../src/cameras';
import { encodeLooksBin } from '../src/format';

const LIB = parsePack(libraryJson);
const pack = (looks: Pack['looks']): Pack => ({ ...LIB, looks, slots: {} });

describe('OM-3 export', () => {
  it('the standard library fills 20 valid looks in list order', () => {
    const r = packToBank(LIB), colour = LIB.looks.filter((l) => l.kind === 'colour');
    expect(r.placed).toHaveLength(COLORS * PER);
    expect(validateBank(r.bank)).toEqual([]);
    expect(r.bank[0][0]!.name).toBe(colour[0].name);
    expect(r.bank[1][0]!.name).toBe(colour[5].name);
    expect(r.extra).toEqual(colour.slice(20).map((l) => l.name));
    expect(r.mono).toBe(LIB.looks.length - colour.length);
  });

  it('copies hue as it is, limits ranges and reports what changed', () => {
    const l = blankLook('colour', 'X');
    l.hue[0] = 2; l.hue[3] = 7; l.lens_correction = true; l.art_effect = 'blur';
    const r = packToBank(pack([l, blankLook('mono', 'M')]));
    expect(r.bank[0][0]!.hue[0]).toBe(2);
    expect(r.bank[0][0]!.hue[3]).toBe(5);
    expect(r.bank[0][1]).toBeNull();
    expect(r.placed[0].changed).toContain('Hue/Light');
    expect(r.placed[0].dropped).toEqual(['Blur']);
    expect([r.mono, r.lens]).toEqual([1, 1]);
  });

  it('a card file opens back to the same look values', () => {
    const src = LIB.looks.filter((l) => l.kind === 'colour' && l.hue.every((v) => Math.abs(v) <= 5)).slice(0, 3);
    const back = looksBinToPack(profilesBin(packToBank(pack(src)).bank), 'x');
    expect(back.looks.map((l) => l.hue)).toEqual(src.map((l) => l.hue));
    expect(back.looks.map((l) => l.name)).toEqual(src.map((l) => l.name));
    expect(readProfiles(profilesBin(packToBank(pack(src)).bank))[0][3]).toBeNull();
  });

  it('editor limits match what each camera accepts', () => {
    const l = blankLook('colour', 'X'), c = CAMERAS.om3;
    l.hue[0] = c.hl; l.light[0] = -c.hl; l.sat[0] = c.sat; l.wb = { a_b: c.wb, g_m: -c.wb };
    c.arts.forEach((a) => { l.art_effect = a; expect(validateBank([[l]])).toEqual([]); });
    expect(CAMERAS.ep7.hl).toBe(7);
  });

  it('leaves the E-P7 export alone', () => {
    const before = encodeLooksBin(LIB);
    packToBank(LIB);
    expect(encodeLooksBin(LIB)).toEqual(before);
  });
});
