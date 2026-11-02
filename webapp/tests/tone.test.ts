import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { zeroTone } from '../src/pack';
import toneData from '../src/data/tone_hsm.json';
import { BASE_LUT, IDENTITY_LUT, hsmLut, lookLut, previewToneLut, remapBW } from '../src/tone';
import { toneModelData } from '../scripts/library.mjs';

const ROOT = join(__dirname, '..', '..');
const TONE_PY = join(ROOT, 'tools/ep7_tone.py');
const python = ['.venv/bin/python', 'python3'].map((p) => (p.startsWith('.') ? join(ROOT, p) : p))
  .find((p) => { try { execFileSync(p, ['-c', '0']); return true; } catch { return false; } });

function rng(seed: number) {
  return () => ((seed = (seed * 1103515245 + 12345) >>> 0) / 2 ** 32);
}
// Test LUTs: identity, a contrast-like S curve, random monotone, random non-monotone, values above 1023 / 16-bit.
function luts(): number[][] {
  const r = rng(5);
  const s = Array.from({ length: 256 }, (_, k) => Math.round(1023 * (0.5 - 0.5 * Math.cos((Math.PI * k) / 255))));
  let acc = 0;
  const mono = Array.from({ length: 256 }, () => (acc = Math.min(1023, acc + Math.floor(r() * 9))));
  const wild = Array.from({ length: 256 }, () => Math.floor(r() * 0x10000));
  const flat = new Array(256).fill(512);
  return [[...IDENTITY_LUT], s, mono, wild, flat];
}

describe('Blacks/Whites remap', () => {
  it('B = W = 0 (and out-of-range values) leave the LUT unchanged', () => {
    for (const l of luts()) for (const [b, w] of [[0, 0], [6, 0], [0, -6], [1.5, 0]]) expect(remapBW(l, b, w)).toEqual(l);
  });

  it('moves the ends as specified and stays monotone', () => {
    for (let B = -5; B <= 5; B++) for (let W = -5; W <= 5; W++) {
      const y = remapBW(IDENTITY_LUT, B, W);
      expect(y[0]).toBe(B > 0 ? 8 * B : 0);
      expect(y[255]).toBe(W < 0 ? 1023 + 10 * W : 1023);
      for (let k = 1; k < 256; k++) expect(y[k]).toBeGreaterThanOrEqual(y[k - 1]);
    }
  });

  it.skipIf(!python || !existsSync(TONE_PY))('bit-exact with tools/ep7_tone.py remap() on every B, W and test LUT', () => {
    const cases: [number[], number, number][] = [];
    for (const l of luts()) for (let B = -6; B <= 6; B++) for (let W = -6; W <= 6; W++) cases.push([l, B, W]);
    const code = 'import importlib.util,json,sys\n' +
      's=importlib.util.spec_from_file_location("t",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n' +
      'print(json.dumps([m.remap(l,b,w) for l,b,w in json.load(sys.stdin)]))';
    const out = JSON.parse(execFileSync(python!, ['-I', '-c', code, TONE_PY], { input: JSON.stringify(cases), maxBuffer: 1 << 26 }).toString());
    cases.forEach(([l, B, W], i) => expect(remapBW(l, B, W), `B=${B} W=${W}`).toEqual(out[i]));
  });
});

const MODEL_PY = join(ROOT, 'tools/ep7_tone_model.py');

describe('Highlights/Shadows/Midtones model (tools/ep7_tone_model.py port)', () => {
  it('src/data/tone_hsm.json is current (npm run gen-library)', () => {
    expect(toneData).toEqual(toneModelData(ROOT));
  });

  it('reproduces the emulator test vectors exactly', () => {
    for (const v of toneData.test_vectors) expect(hsmLut(v.h, v.s, v.m), `H${v.h} S${v.s} M${v.m}`).toEqual(v.lut);
  });

  it.skipIf(!python || !existsSync(MODEL_PY))('bit-exact with tone_lut() on every H/S/M and a B/W sweep, two base LUTs', () => {
    const r = rng(23);
    const cases: number[][] = [];
    for (let h = -7; h <= 7; h++) for (let s = -7; s <= 7; s++) for (let m = -7; m <= 7; m += 2) cases.push([h, s, m, 0, 0]);
    for (let i = 0; i < 300; i++) cases.push([0, 1, 2, 3, 4].map((k) => Math.floor(r() * (k < 3 ? 15 : 11)) - (k < 3 ? 7 : 5)));
    const sCurve = Array.from({ length: 256 }, (_, k) => Math.round(1023 * (0.5 - 0.5 * Math.cos((Math.PI * k) / 255))));
    const code = 'import importlib.util,json,sys\n' +
      's=importlib.util.spec_from_file_location("m",sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n' +
      'd=json.load(sys.stdin);print(json.dumps([[m.tone_lut(*c) for c in d["c"]],[m.tone_lut(*c,base=d["b"]) for c in d["c"][::7]]]))';
    const [out, outS] = JSON.parse(execFileSync(python!, ['-I', '-c', code, MODEL_PY],
      { input: JSON.stringify({ c: cases, b: sCurve }), maxBuffer: 1 << 27 }).toString());
    const tone = (c: number[]) => ({ highlights: c[0], shadows: c[1], midtones: c[2], blacks: c[3], whites: c[4] });
    cases.forEach((c, i) => expect(lookLut(tone(c)), c.join()).toEqual(out[i]));
    cases.filter((_, i) => i % 7 === 0).forEach((c, i) => expect(lookLut(tone(c), sCurve), c.join()).toEqual(outS[i]));
  });
});

describe('preview tone LUT', () => {
  it('zero tone is the identity; the camera keeps the end points; the table is monotone', () => {
    expect(lookLut(zeroTone())).toEqual([...BASE_LUT]);
    const t = previewToneLut(zeroTone());
    for (let i = 0; i <= 1024; i++) expect(t[i]).toBeCloseTo(i / 1024, 5);
    for (const [h, s, m] of [[7, 0, 0], [-7, 0, 0], [0, 7, 0], [0, -7, 0], [0, 0, 7], [0, 0, -7], [7, -7, 7]]) {
      const y = hsmLut(h, s, m);
      expect([y[0], y[255]]).toEqual([0, 1023]);
      for (let k = 1; k < 256; k++) expect(y[k]).toBeGreaterThanOrEqual(y[k - 1]);
      const p = previewToneLut({ ...zeroTone(), highlights: h, shadows: s, midtones: m });
      for (let i = 1; i <= 1024; i++) expect(p[i]).toBeGreaterThanOrEqual(p[i - 1]);
    }
    const lift = previewToneLut({ ...zeroTone(), blacks: 5, whites: -5 });
    expect(lift[0]).toBeCloseTo(40 / 1023, 5);
    expect(lift[1024]).toBeCloseTo(973 / 1023, 5);
    expect(previewToneLut({ ...zeroTone(), shadows: 7 })[128]).toBeGreaterThan(128 / 1024);
  });
});
