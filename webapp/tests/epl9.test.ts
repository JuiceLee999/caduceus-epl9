import { describe, expect, it } from 'vitest';
import { EPL9, epl9Card, toEpl9 } from '../src/epl9';
import { blankLook, parsePack } from '../src/pack';
import { targetById } from '../src/targets';
import libraryJson from '../src/data/library.json';

const LIB = parsePack(libraryJson);

describe('E-PL9 stock settings', () => {
  it('a blank look is Natural with everything at zero and nothing missing', () => {
    const r = toEpl9(blankLook());
    expect(r).toMatchObject({ mode: 'Natural', contrast: 0, sharpness: 0, saturation: 0, gradation: 'Normal', highlights: 0, shadows: 0, wb: { a_b: 0, g_m: 0 } });
    expect(r.missing).toEqual([]);
  });

  it('every library look stays inside the camera ranges', () => {
    for (const l of LIB.looks) {
      const r = toEpl9(l);
      for (const v of [r.contrast, r.sharpness, r.saturation]) expect(Math.abs(v)).toBeLessThanOrEqual(EPL9.pm);
      for (const v of [r.highlights, r.shadows]) expect(Math.abs(v)).toBeLessThanOrEqual(EPL9.hs);
      for (const v of [r.wb.a_b, r.wb.g_m]) expect(Math.abs(v)).toBeLessThanOrEqual(EPL9.wb);
      expect(r.mode === 'Monotone').toBe(l.kind === 'mono');
      expect(Number.isInteger(r.saturation) && Number.isInteger(r.contrast)).toBe(true);
    }
  });

  it('strong saturation starts from Vivid or Muted', () => {
    const hot = blankLook(); hot.sat.fill(5);
    const flat = blankLook(); flat.sat.fill(-5);
    expect(toEpl9(hot)).toMatchObject({ mode: 'Vivid', saturation: 2 });
    expect(toEpl9(flat)).toMatchObject({ mode: 'Muted', saturation: -2 });
    const mild = blankLook(); mild.sat.fill(2);
    expect(toEpl9(mild)).toMatchObject({ mode: 'Natural', saturation: 1 });
  });

  it('clamps WB and tone to ±7 and reports what does not carry over', () => {
    const l = blankLook();
    l.wb = { a_b: 9, g_m: -3 };
    l.tone = { highlights: 9, shadows: -2, midtones: 1, blacks: 2, whites: 0 };
    l.hue[0] = 3;
    l.effect = { type: 'bloom', strength: 2 };
    const r = toEpl9(l);
    expect(r.wb).toEqual({ a_b: 7, g_m: -3 });
    expect(r.highlights).toBe(7);
    expect(r.shadows).toBe(-2);
    expect(r.missing.join('|')).toMatch(/Midtones.*\|Blacks \/ Whites.*\|Hue by colour\|.*WB shift.*\|Bloom glow/);
    expect(r.alternatives[0]).toMatch(/Soft Focus/);
  });

  it('mono looks map the B&W filter, and blue falls back to N', () => {
    const l = blankLook('mono');
    l.advice.mono_filter = { colour: 'orange', strength: 1 };
    expect(toEpl9(l).bwFilter).toBe('Or');
    l.advice.mono_filter = { colour: 'blue', strength: 1 };
    const r = toEpl9(l);
    expect(r.bwFilter).toBe('N');
    expect(r.missing.some((m) => /Blue/.test(m))).toBe(true);
  });

  it('uses the look tone, or the advice tone for older looks', () => {
    const l = blankLook();
    l.advice.tone = { highlights: 2, shadows: -3, midtones: 0 };
    expect(toEpl9(l)).toMatchObject({ highlights: 2, shadows: -3 });
    l.tone.highlights = -1;
    expect(toEpl9(l)).toMatchObject({ highlights: -1, shadows: 0 });
  });

  it('the card and the export target', () => {
    const card = epl9Card(LIB.looks[0]);
    expect(card).toMatch(/^# .+ — Olympus PEN E-PL9/);
    expect(card).toMatch(/Highlight & Shadow Control/);
    const files = targetById('epl9-stock').export(LIB);
    expect(files).toHaveLength(LIB.looks.length);
    expect(new Set(files.map((f) => f.name.toLowerCase())).size).toBe(files.length);
    expect(files.every((f) => f.name.endsWith('-EPL9.md'))).toBe(true);
  });
});
