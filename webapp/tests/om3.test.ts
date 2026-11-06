// From androidfanman/caduceus-om3 @ daa453b (Apache-2.0, see NOTICE), unchanged.
// OM-3 mode (Caduceus for OM-3): the profile bank and PROFILES.BIN.
// The byte check against card/mkprofiles.py runs when the caduceus-om3 repo is the parent folder (skipped otherwise).
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import libraryJson from '../src/data/library.json';
import { blankLook, parsePack, type Look } from '../src/pack';
import { fromLibrary } from '../src/reset';
import { COLORS, PER, defaultBank, emptyBank, parseBank, profilesBin, readProfiles, toOm3, validateBank, type Bank } from '../src/om3';
import { parseLook } from '../src/pack';

const LIB = parsePack(libraryJson);
const MK = join(__dirname, '../../card/mkprofiles.py');
const hex = (b: Uint8Array) => Buffer.from(b).toString('hex');

/** The bank in mkprofiles.py's input format. */
const pyJson = (bank: Bank) => ({
  sel: [0, 0, 0, 0],
  prof: bank.map((row) => row.map((l) => l && {
    name: l.name, hue: l.hue, light: l.light, sat: l.sat, wb: !!(l.wb && (l.wb.a_b || l.wb.g_m)), ab: l.wb?.a_b ?? 0, gm: l.wb?.g_m ?? 0,
    blacks: l.tone.blacks, whites: l.tone.whites, contrast: l.advice.contrast ?? 0, sharp: l.advice.sharpness ?? 0, shading: l.vignette,
    sh: l.tone.shadows, mid: l.tone.midtones, hi: l.tone.highlights,
    fx: !l.effect ? 0 : l.effect.type === 'clarity' ? l.effect.strength : -l.effect.strength,
    art: ['off', 'star_light', 'pin_hole', 'blur', 'white_edge', 'frame'].indexOf(l.art_effect), nr: ['off', 'standard', 'fine', 'film'].indexOf(l.grain),
  })),
});
function rnd(seed: number) { let s = seed; return (n: number) => { s = (s * 1103515245 + 12345) & 0x7fffffff; return (s % (2 * n + 1)) - n; }; }
function randomBank(seed: number): Bank {
  const r = rnd(seed), b = emptyBank();
  for (let k = 0; k < COLORS; k++) for (let v = 0; v < PER; v++) {
    if (r(1) === 0) continue;
    const l = blankLook('colour', `P${k}${v} ${seed}`.slice(0, 12));
    l.hue = l.hue.map(() => r(5)); l.light = l.light.map(() => r(5)); l.sat = l.sat.map(() => r(5));
    l.wb = r(1) ? { a_b: r(5), g_m: r(5) } : null;
    l.tone = { highlights: r(7), shadows: r(7), midtones: r(7), blacks: r(5), whites: r(5) };
    l.advice = { contrast: r(2), sharpness: r(2) }; l.vignette = r(5);
    const fx = r(5); l.effect = fx < 0 ? { type: 'bloom', strength: -fx } : fx > 0 ? { type: 'clarity', strength: fx } : null;
    l.art_effect = (['off', 'star_light', 'pin_hole', 'white_edge', 'frame'] as const)[Math.abs(r(4))];
    l.grain = (['off', 'standard', 'fine', 'film'] as const)[Math.abs(r(3))];
    b[k][v] = l;
  }
  return b;
}

describe('OM-3 profile bank', () => {
  it('first visit: 20 colour library looks, all valid for the camera', () => {
    const b = defaultBank(LIB, fromLibrary);
    expect(b.flat().filter(Boolean)).toHaveLength(20);
    expect(validateBank(b)).toEqual([]);
    expect(b[0][0]!.name).toBe('Velvia');
  });

  it('toOm3: mono refused, ranges limited, v0.20 Extras kept (glow without colour, no Blur)', () => {
    expect(toOm3(blankLook('mono')).look).toBeNull();
    const l = blankLook('colour', 'X');
    l.hue[0] = 7; l.light[3] = -6; l.wb = { a_b: 7, g_m: -1 }; l.grain = 'film'; l.effect = { type: 'halation', strength: 2, tint: 'red' }; l.art_effect = 'pin_hole';
    const c = toOm3(l);
    expect(c.look!.hue[0]).toBe(5); expect(c.look!.light[3]).toBe(-5); expect(c.look!.wb).toEqual({ a_b: 5, g_m: -1 });
    expect(c.look!.grain).toBe('film'); expect(c.look!.effect).toEqual({ type: 'bloom', strength: 2 }); expect(c.look!.art_effect).toBe('pin_hole');
    expect(c.changed).toEqual(['Hue/Light', 'WB', 'halation as glow']);
    expect(c.dropped).toEqual([]);
    const b = blankLook('colour', 'Y'); b.art_effect = 'blur'; b.effect = { type: 'clarity', strength: 3 };
    const d = toOm3(b);
    expect(d.look!.art_effect).toBe('off'); expect(d.dropped).toEqual(['Blur']); expect(d.look!.effect).toEqual({ type: 'clarity', strength: 3 });
    expect(validateBank([[c.look, d.look]])).toEqual([]);
  });

  it('PROFILES.BIN round-trips', () => {
    for (const seed of [1, 2, 3]) {
      const b = randomBank(seed), back = readProfiles(profilesBin(b));
      for (let k = 0; k < COLORS; k++) for (let v = 0; v < PER; v++) {
        const a = b[k][v], z = back[k][v];
        if (!a) { expect(z).toBeNull(); continue; }
        expect(z!.name).toBe(a.name);
        for (const f of ['hue', 'light', 'sat', 'tone', 'vignette', 'effect', 'art_effect', 'grain'] as const) expect(z![f]).toEqual(a[f]);
        expect(z!.advice).toEqual(a.advice);
        expect(z!.wb && (z!.wb.a_b || z!.wb.g_m) ? z!.wb : null).toEqual(a.wb && (a.wb.a_b || a.wb.g_m) ? a.wb : null);
      }
    }
  });

  it('bank files parse back', () => {
    const b = defaultBank(LIB, fromLibrary);
    const f = parseBank(JSON.parse(JSON.stringify({ schema: 'caduceus-om3-bank/1', name: 'x', bank: b })), parseLook);
    expect(hex(profilesBin(f.bank))).toBe(hex(profilesBin(b)));
  });

  it.skipIf(!existsSync(MK))('PROFILES.BIN is byte-identical to card/mkprofiles.py', () => {
    const dir = mkdtempSync(join(tmpdir(), 'om3-'));
    for (const [i, b] of [defaultBank(LIB, fromLibrary), randomBank(7), randomBank(8), emptyBank()].entries()) {
      writeFileSync(join(dir, `in${i}.json`), JSON.stringify(pyJson(b)));
      execFileSync('python3', ['-I', MK, join(dir, `in${i}.json`), join(dir, `out${i}.bin`)]);
      expect(hex(profilesBin(b))).toBe(hex(new Uint8Array(readFileSync(join(dir, `out${i}.bin`)))));
    }
  });
});

export type { Look };
