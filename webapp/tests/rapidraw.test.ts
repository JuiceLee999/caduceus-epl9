import { describe, expect, it } from 'vitest';
import lib from '../src/data/library.json';
import { type Look, type Pack } from '../src/pack';
import { RR_BANDS, hslFor, lumaCurve, rrAdjustments, rrpreset } from '../src/rapidraw';

const pack = lib as unknown as Pack;
const look = (n: string) => pack.looks.find((l) => l.name === n) as Look;
const flat = (): Look => ({ ...look('Velvia'), hue: Array(12).fill(0), light: Array(12).fill(0), sat: Array(12).fill(0),
  wb: null, effect: null, vignette: 0, tone: { highlights: 0, shadows: 0, midtones: 0, blacks: 0, whites: 0 }, advice: {} });

describe('rapidraw export', () => {
  it('a neutral look is a no-op preset', () => {
    const a = rrAdjustments(flat());
    for (const b of RR_BANDS) expect((a.hsl as any)[b]).toEqual({ hue: 0, saturation: 0, luminance: 0 });
    expect((a.curves as any).luma).toEqual([{ x: 0, y: 0 }, { x: 255, y: 255 }]);
    expect([a.temperature, a.tint, a.glowAmount, a.halationAmount, a.clarity, a.monochromeEnabled]).toEqual([0, 0, 0, 0, 0, false]);
  });

  it('follows the look direction', () => {
    const v = hslFor(look('Velvia'));
    expect(v.greens.saturation).toBeGreaterThan(20);           // Velvia: denser, more saturated colour
    expect(v.blues.saturation).toBeGreaterThan(10);
    const c = rrAdjustments(look('CineStill800'));
    expect(c.halationAmount).toBeGreaterThan(0);
    expect(c.temperature).toBeLessThan(0);                       // tungsten-balanced: cool
    const k = lumaCurve(look('Velvia'));
    expect(k.find((p) => p.x === 64)!.y).toBeLessThan(64);       // crushed shadows
    const a = rrAdjustments(look('Acros'));
    expect(a.monochromeEnabled).toBe(true);
    expect(a.monochromeFilterHue).toBe(120);
  });

  it('writes a RapidRAW preset file (folder + single)', () => {
    const all = JSON.parse(rrpreset(pack));
    expect(all.presets).toHaveLength(1);
    expect(all.presets[0].folder.children).toHaveLength(pack.looks.length);
    const c0 = all.presets[0].folder.children[0];
    expect(Object.keys(c0)).toEqual(['id', 'name', 'adjustments', 'includeMasks', 'includeCropTransform', 'presetType']);
    const one = JSON.parse(rrpreset(pack, 3));
    expect(one.presets[0].preset.name).toBe(pack.looks[3].name);
    for (const ch of all.presets[0].folder.children) {
      for (const b of RR_BANDS) for (const v of Object.values(ch.adjustments.hsl[b]) as number[]) expect(Math.abs(v)).toBeLessThanOrEqual(100);
    }
  });
});
