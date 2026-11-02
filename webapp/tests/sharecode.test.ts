import { describe, expect, it } from 'vitest';
import { lookRecord } from '../src/format';
import { blankLook, parsePack, type Look } from '../src/pack';
import {
  ALPHABET, crc15, crc15Bits, decodeLookCode, decodePackCode, encodeLookCode, encodePackCode, isPackCode, normaliseLookCode,
} from '../src/sharecode';
import library from '../src/data/library.json';

const pack = parsePack(library);
const hex = (b: Uint8Array) => Buffer.from(b).toString('hex');
// What a look code carries: the card bytes (incl. name), the Art Effect and the mono-filter advice.
const essence = (l: Look) => [hex(lookRecord(l)), l.art_effect, JSON.stringify(l.advice.mono_filter ?? null)];

describe('look codes', () => {
  it('round-trip every library look', () => {
    const lens: number[] = [];
    for (const l of pack.looks) {
      const code = encodeLookCode(l);
      lens.push(code.length);
      expect(code).toMatch(/^1[0-9A-HJKMNP-TV-Z]+$/);
      expect(essence(decodeLookCode(code))).toEqual(essence(l));
    }
    const avg = lens.reduce((a, b) => a + b, 0) / lens.length;
    console.log(`look code length: min ${Math.min(...lens)}, avg ${avg.toFixed(1)}, max ${Math.max(...lens)}`);
    expect(Math.max(...lens)).toBeLessThan(70);
  });

  it('round-trips extremes (all fields at their limits, mono, effects, art)', () => {
    const l = blankLook('colour', '~ !"#$%&\'()*');
    l.hue = l.hue.map((_, i) => (i % 2 ? 7 : -7)); l.light = l.light.map(() => -7); l.sat = l.sat.map(() => 5);
    l.wb = { a_b: -7, g_m: 7 }; l.effect = { type: 'halation', strength: 5, tint: 'cool' }; l.vignette = -5;
    l.grain = 'high'; l.art_effect = 'frame';
    expect(essence(decodeLookCode(encodeLookCode(l)))).toEqual(essence(l));
    const m = blankLook('mono', 'B&W');
    m.advice = { mono_filter: { colour: 'red', strength: 3 } };
    m.effect = { type: 'clarity', strength: 1 };
    expect(essence(decodeLookCode(encodeLookCode(m)))).toEqual(essence(m));
    const z = blankLook('colour', 'Z');
    expect(encodeLookCode(z).length).toBeLessThan(16);
    expect(essence(decodeLookCode(encodeLookCode(z)))).toEqual(essence(z));
  });

  it('is forgiving: case, spaces, dashes, URL prefix, Crockford O/I/L', () => {
    const l = pack.looks[0];
    const code = encodeLookCode(l);
    const grouped = encodeLookCode(l, true);
    expect(grouped.replace(/-/g, '')).toBe(code);
    for (const v of [code.toLowerCase(), ` ${grouped} `, `https://example.com/caduceus/#${code}`, code.replace(/(.{4})/g, '$1 ')])
      expect(essence(decodeLookCode(v))).toEqual(essence(l));
    expect(normaliseLookCode('1o-il')).toBe('1011');
  });

  it('catches every single-character typo and adjacent swap', () => {
    for (const l of pack.looks.slice(0, 8)) {
      const code = encodeLookCode(l);
      for (let i = 1; i < code.length; i++) {
        for (const ch of ALPHABET) {
          if (ch === code[i]) continue;
          const bad = code.slice(0, i) + ch + code.slice(i + 1);
          expect(() => decodeLookCode(bad), bad).toThrow();
        }
        if (i + 1 < code.length && code[i] !== code[i + 1]) {
          const sw = code.slice(0, i) + code[i + 1] + code[i] + code.slice(i + 2);
          expect(() => decodeLookCode(sw)).toThrow();
        }
      }
      expect(() => decodeLookCode(code.slice(0, -1))).toThrow();
    }
  });

  it('version prefix: v1 decodes, newer versions say so, junk is refused', () => {
    const code = encodeLookCode(pack.looks[1]);
    expect(code[0]).toBe('1');
    const v2 = '2' + code.slice(1);
    expect(() => decodeLookCode(v2)).toThrow(/newer/);
    expect(() => decodeLookCode('X' + code.slice(1))).toThrow(/not a Caduceus/);
    expect(() => decodeLookCode('1U23456')).toThrow(/not a code character/);
    expect(() => decodeLookCode('12')).toThrow(/too short/);
  });

  it('CRC-15/CAN check value', () => {
    // catalogue check value: CRC-15/CAN("123456789") = 0x059E
    const bits = [...'123456789'].flatMap((c) => [7, 6, 5, 4, 3, 2, 1, 0].map((b) => (c.charCodeAt(0) >> b) & 1));
    expect(crc15Bits(bits)).toBe(0x059e);
    expect(crc15([])).toBe(0);
  });
});

describe('pack codes', () => {
  it('round-trip the whole library (with notes and slots)', async () => {
    const code = await encodePackCode(pack);
    expect(code.startsWith('pk1_')).toBe(true);
    expect(isPackCode(code)).toBe(true);
    expect(isPackCode(`https://x/caduceus/#${code}`)).toBe(true);
    expect(isPackCode(encodeLookCode(pack.looks[0]))).toBe(false);
    const back = await decodePackCode(`https://lfolabs.com/caduceus#${code}`);
    expect(back).toEqual(pack);
    console.log(`pack code for the ${pack.looks.length}-look library: ${code.length} chars`);
  });

  it('rejects damage and unknown versions', async () => {
    const code = await encodePackCode(pack);
    const mid = Math.floor(code.length / 2);
    const bad = code.slice(0, mid) + (code[mid] === 'A' ? 'B' : 'A') + code.slice(mid + 1);
    await expect(decodePackCode(bad)).rejects.toThrow();
    await expect(decodePackCode(code.slice(0, -10))).rejects.toThrow();
    await expect(decodePackCode('pk2_abc')).rejects.toThrow(/newer/);
    await expect(decodePackCode('hello')).rejects.toThrow(/not a Caduceus/);
  });
});
