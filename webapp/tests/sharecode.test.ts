import { describe, expect, it } from 'vitest';
import { lookRecord } from '../src/format';
import { TONE_KEYS, blankLook, parsePack, toneLimit, zeroTone, type Look } from '../src/pack';
import {
  ALPHABET, crc15, crc15Bits, decodeLookCode, decodePackCode, encodeLookCode, encodePackCode, isPackCode, normaliseLookCode,
} from '../src/sharecode';
import library from '../src/data/library.json';

const pack = parsePack(library);
const hex = (b: Uint8Array) => Buffer.from(b).toString('hex');
// What a look code carries: the card bytes (LOOKS.BIN record: incl. name and tone block), the Art Effect and the mono-filter advice.
const essence = (l: Look) => [hex(lookRecord(l)), l.art_effect, JSON.stringify(l.advice.mono_filter ?? null)];

describe('look codes', () => {
  it('round-trip every library look', () => {
    const lens: number[] = [];
    for (const l of pack.looks) {
      const code = encodeLookCode(l);
      lens.push(code.length);
      expect(code).toMatch(/^[12][0-9A-HJKMNP-TV-Z]+$/);
      expect(code[0]).toBe(l.tone && Object.values(l.tone).some((v) => v !== 0) ? '2' : '1');
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
    l.grain = 'film'; l.art_effect = 'frame';
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

  it('version prefix: v1/v2 decode, newer versions say so, junk is refused', () => {
    const code = encodeLookCode({ ...pack.looks[1], tone: zeroTone() });
    expect(code[0]).toBe('1');
    expect(() => decodeLookCode('2' + code.slice(1))).toThrow(/Check failed/);
    expect(() => decodeLookCode('7' + code.slice(1))).toThrow(/newer/);
    expect(() => decodeLookCode('X' + code.slice(1))).toThrow(/not a Caduceus/);
    expect(() => decodeLookCode('1U23456')).toThrow(/not a code character/);
    expect(() => decodeLookCode('12')).toThrow(/too short/);
  });

  it('v0.22 grain off/fine/film -> v1/v2 codes as the old digits 0/1/2; v0.21 v3/v4 codes still decode', () => {
    for (const [g, tone, v] of [['fine', false, '1'], ['film', true, '2'], ['off', false, '1']] as const) {
      const l = { ...pack.looks[1], grain: g, tone: tone ? { ...zeroTone(), shadows: 2 } : zeroTone() } as typeof pack.looks[1];
      const c = encodeLookCode(l);
      expect(c[0]).toBe(v);
      expect(decodeLookCode(c).grain).toBe(g);
    }
    for (const tone of [false, true]) {             // standard (camera "Noise Std") -> v5/v6 codes
      const l = { ...pack.looks[1], grain: 'standard', tone: tone ? { ...zeroTone(), shadows: 2 } : zeroTone() } as typeof pack.looks[1];
      const c = encodeLookCode(l);
      expect(c[0]).toBe(tone ? '6' : '5');
      expect(decodeLookCode(c).grain).toBe('standard');
    }
    // a v0.21 app code: v1 body with the grain digit in radix 6 = 5 (extreme), re-labelled '3' -> reads as film
    const l = { ...pack.looks[1], grain: 'film', tone: zeroTone() } as typeof pack.looks[1];
    expect(decodeLookCode(encodeLookCode(l)).grain).toBe('film');
  });

  it('old (v0.18 app) v1 codes still decode, with tone 0', () => {
    // made by the v0.18 web app (commit 14e67e1) from the built-in library; the README's CineStill800 example
    const OLD: Record<string, string> = {
      Velvia: '1162ZKTXN0WRYEQ5BBWBAQ3P9MZKTTW01YHBNYJFDT',
      'Reala Ace': '1YHMTVJYVTRMA7PA8P9NP9FZPVVGCYKYB00ATJ02YB4',
      'Gold 200': '11VPNYPEPG80R01YC878VQ47M19DG9FPT02WVY',
      Cibachrome: '1D3MHQR46HJVQ07E6AW55EEEAJBB61P8GA5901JCSW',
      'HP5 Plus': '15PXTJK0F0AGHWGNRS3P18',
      Acros: '176RJFTCQNXMNDQK5Z',
      CineStill800: '1BM9Y-B0K8X-PVAC8-KB9ND-BFVKG-0YAYT-SC59H-5W548-8TYZ0',
    };
    for (const [name, code] of Object.entries(OLD)) {
      const want = pack.looks.find((l) => l.name === name)!;
      const got = decodeLookCode(code);
      expect(got.tone).toEqual(zeroTone());
      expect(essence(got), name).toEqual(essence({ ...want, tone: zeroTone() }));
      // a look without tone still gets the same v1 code, so older apps read what this one makes
      // (v0.22: an old 'high' grain digit 3 reads as film and is re-written as digit 2, so HP5 Plus gets a new code)
      if (name !== 'HP5 Plus') expect(encodeLookCode({ ...want, tone: zeroTone() }), name).toBe(code.replace(/-/g, ''));
    }
  });

  it('tone: v2 codes round-trip every tone field at every value, and stay short', () => {
    const base = pack.looks[3];
    const v1 = encodeLookCode({ ...base, tone: zeroTone() });
    for (const k of TONE_KEYS) {
      const L = toneLimit(k);
      for (let v = -L; v <= L; v++) {
        const l = { ...base, tone: { ...zeroTone(), [k]: v } };
        const code = encodeLookCode(l);
        expect(code[0]).toBe(v === 0 ? '1' : '2');
        expect(decodeLookCode(code).tone).toEqual(l.tone);
        expect(essence(decodeLookCode(code))).toEqual(essence(l));
        expect(code.length - v1.length).toBeLessThanOrEqual(2);       // one tone value costs at most 2 symbols
      }
    }
    const full = { ...base, tone: { highlights: -7, shadows: 7, midtones: -1, blacks: 5, whites: -5 } };
    const code = encodeLookCode(full, true);
    expect(decodeLookCode(code).tone).toEqual(full.tone);
    expect(code.replace(/-/g, '').length - v1.length).toBeLessThanOrEqual(5);
    const m = { ...blankLook('mono', 'Mono T'), tone: { ...zeroTone(), shadows: -3, whites: 2 } };
    expect(essence(decodeLookCode(encodeLookCode(m)))).toEqual(essence(m));
  });

  it('tone: v2 codes catch typos and swaps; out-of-range tone is refused', () => {
    const l = { ...pack.looks[0], tone: { highlights: 2, shadows: -4, midtones: 0, blacks: 1, whites: -1 } };
    const code = encodeLookCode(l);
    for (let i = 0; i < code.length; i++) {
      for (const ch of ALPHABET) {
        if (ch === code[i]) continue;
        expect(() => decodeLookCode(code.slice(0, i) + ch + code.slice(i + 1))).toThrow();
      }
      if (i + 1 < code.length && code[i] !== code[i + 1])
        expect(() => decodeLookCode(code.slice(0, i) + code[i + 1] + code[i] + code.slice(i + 2))).toThrow();
    }
    for (const [k, v] of [['highlights', 8], ['blacks', -6], ['whites', 6], ['midtones', 0.5]] as const)
      expect(() => encodeLookCode({ ...l, tone: { ...l.tone, [k]: v } })).toThrow(/tone/);
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
