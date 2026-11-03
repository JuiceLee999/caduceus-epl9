// Share codes (format documented in webapp/README.md, "Share codes"; keep that section in step with this file).
//
// Look code v1:  "1" + body + check      (Crockford base32: 0-9 A-Z without I L O U; case-insensitive)
//   body  = one mixed-radix integer (BigInt) holding the look's fields, most significant digit first
//   check = CRC-15/CAN (poly 0x4599) over the 5-bit symbols of "1" + body, as 3 symbols
// Look code v2:  "2" + body + check      the v1 fields with a tone block (H/S/M/B/W) before the name. Only made
//   when the look's tone is not all zero, so a look without tone keeps its v1 code (older apps read it).
// Look code v3 / v4: v1 / v2 with the grain digit in radix 6 (v0.21 apps: grain 0..5). Decoded only; v0.22 apps
//   write grain as the old digit (off 0, fine = old low 1, film = old medium 2), so they always make v1/v2 codes.
// Pack code v1:  "pk1_" + base64url(zlib-deflate(UTF-8 JSON of the pack file, schema caduceus-pack/1))
//   (zlib's Adler-32 catches corruption; base64url is case-sensitive, so pack codes are for links, not typing)
import {
  ARTS, EFFECTS, GRAIN_BYTE, grainFromByte, MONO_FILTERS, TINTS, TONE_KEYS, exportable, parsePack, toneIsZero, toneLimit, zeroTone,
  type Effect, type Look, type Pack, type Tone,
} from './pack';

export const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';
export const LOOK_VERSION = '1';        // codes without tone
export const LOOK_VERSION_TONE = '2';   // codes with a tone block
export const LOOK_VERSION_G6 = '3';     // v1 + grain radix 6
export const LOOK_VERSION_G6_TONE = '4';  // v2 + grain radix 6
export const LOOK_VERSION_G7 = '5';       // v0.22: v1 + grain radix 7 (digit 6 = standard / camera "Off")
export const LOOK_VERSION_G7_TONE = '6';  // v0.22: v2 + grain radix 7
const KNOWN_VERSIONS = [LOOK_VERSION, LOOK_VERSION_TONE, LOOK_VERSION_G6, LOOK_VERSION_G6_TONE, LOOK_VERSION_G7, LOOK_VERSION_G7_TONE];
export const PACK_PREFIX = 'pk1_';
const NAME_CHARS = (() => {
  let s = '';
  for (let c = 0x20; c <= 0x7e; c++) if (c !== 0x40) s += String.fromCharCode(c);
  return s;                                   // 94 printable ASCII characters, no '@'
})();

// ---- CRC-15/CAN (poly 0x4599, init 0, MSB first) over a bit stream; share codes feed 5 bits per symbol
export function crc15Bits(bits: Iterable<number>): number {
  let crc = 0;
  for (const bit of bits) {
    const top = (crc >> 14) & 1;
    crc = (crc << 1) & 0x7fff;
    if (top ^ bit) crc ^= 0x4599;
  }
  return crc;
}
export function crc15(symbols: number[]): number {
  return crc15Bits(symbols.flatMap((s) => [4, 3, 2, 1, 0].map((b) => (s >> b) & 1)));
}

// ---- mixed-radix writer/reader: the first value written is the least significant digit
class Writer {
  digits: [number, number][] = [];
  put(v: number, radix: number) {
    if (!Number.isInteger(v) || v < 0 || v >= radix) throw new Error(`share code: value ${v} outside 0..${radix - 1}`);
    this.digits.push([v, radix]);
  }
  toBigInt(): bigint {
    let n = 0n;
    for (let i = this.digits.length - 1; i >= 0; i--) n = n * BigInt(this.digits[i][1]) + BigInt(this.digits[i][0]);
    return n;
  }
}
class Reader {
  constructor(public n: bigint) {}
  get(radix: number): number {
    const r = BigInt(radix);
    const v = Number(this.n % r);
    this.n /= r;
    return v;
  }
}

// A 12-value slider vector: mode 0 = all zero, 1 = sparse (12-bit mask + nonzero values), 2 = dense.
function putVec(w: Writer, vals: number[], lim: number) {
  const nz = vals.filter((v) => v !== 0).length;
  const R = 2 * lim + 1;
  if (nz === 0) return w.put(0, 3);
  const sparseBits = 12 + nz * Math.log2(R - 1), denseBits = 12 * Math.log2(R);
  if (sparseBits < denseBits) {
    w.put(1, 3);
    for (const v of vals) w.put(v !== 0 ? 1 : 0, 2);
    for (const v of vals) if (v !== 0) w.put(v < 0 ? v + lim : v + lim - 1, R - 1);   // skip 0
  } else {
    w.put(2, 3);
    for (const v of vals) w.put(v + lim, R);
  }
}
function getVec(r: Reader, lim: number): number[] {
  const R = 2 * lim + 1;
  const mode = r.get(3);
  if (mode === 0) return new Array(12).fill(0);
  if (mode === 1) {
    const mask = Array.from({ length: 12 }, () => r.get(2));
    return mask.map((m) => {
      if (!m) return 0;
      const x = r.get(R - 1) - lim;
      return x < 0 ? x : x + 1;
    });
  }
  if (mode === 2) return Array.from({ length: 12 }, () => r.get(R) - lim);
  throw new Error('share code: damaged (bad vector mode)');
}

const EFFECT_N = 1 + 25 + 25 + 5;   // none | bloom s*tint | halation s*tint | clarity s
function effectIndex(e: Effect | null): number {
  if (!e) return 0;
  const t = e.tint ? TINTS.indexOf(e.tint) : 0;
  if (e.type === 'bloom') return 1 + (e.strength - 1) * 5 + t;
  if (e.type === 'halation') return 26 + (e.strength - 1) * 5 + t;
  return 51 + e.strength - 1;
}
function effectFrom(i: number): Effect | null {
  if (i === 0) return null;
  if (i < 51) {
    const type = i < 26 ? 'bloom' : 'halation';
    const k = i - (i < 26 ? 1 : 26);
    const t = k % 5;
    // tint 0 is stored as "no tint" (byte value 0 either way)
    return { type, strength: Math.floor(k / 5) + 1, ...(t ? { tint: TINTS[t] } : {}) };
  }
  if (i < EFFECT_N) return { type: 'clarity', strength: i - 50 };
  throw new Error('share code: damaged (bad effect)');
}

// Tone block (v2): mask digit (radix 31, = 5-bit mask of the non-zero fields in TONE_KEYS order, minus 1; never 0),
// then each non-zero value in that order, radix 2L (L = 7 for H/S/M, 5 for B/W), coded v+L if v<0 else v+L-1.
function putTone(w: Writer, t: Tone) {
  let mask = 0;
  TONE_KEYS.forEach((k, i) => { if (t[k] !== 0) mask |= 1 << i; });
  w.put(mask - 1, 31);
  for (const k of TONE_KEYS) {
    const v = t[k], L = toneLimit(k);
    if (v !== 0) w.put(v < 0 ? v + L : v + L - 1, 2 * L);
  }
}
function getTone(r: Reader): Tone {
  const mask = r.get(31) + 1, t = zeroTone();
  TONE_KEYS.forEach((k, i) => {
    if (!(mask & (1 << i))) return;
    const L = toneLimit(k), x = r.get(2 * L) - L;
    t[k] = x < 0 ? x : x + 1;
  });
  return t;
}

/** Pack one look into a mixed-radix integer (v1/v2 field order; never reorder: it is the code format). */
function lookToBigInt(l: Look, withTone: boolean, gr = 4): bigint {
  const w = new Writer();
  w.put(l.kind === 'mono' ? 1 : 0, 2);
  putVec(w, l.hue, 7);
  putVec(w, l.light, 7);
  putVec(w, l.kind === 'mono' ? new Array(12).fill(0) : l.sat, 5);
  w.put(GRAIN_BYTE[l.grain], gr);                      // off/fine/film = old digits 0/1/2; standard = 6 (radix 7)
  w.put(l.wb ? 1 + (l.wb.a_b + 7) * 15 + (l.wb.g_m + 7) : 0, 226);
  w.put(effectIndex(l.effect), EFFECT_N);
  w.put(l.vignette + 5, 11);
  w.put(ARTS.indexOf(l.art_effect), ARTS.length);
  const mf = l.advice.mono_filter;
  w.put(mf ? 1 + MONO_FILTERS.indexOf(mf.colour) * 3 + (Math.min(3, Math.max(1, mf.strength)) - 1) : 0, 19);
  if (withTone) putTone(w, l.tone);
  const name = [...l.name];
  w.put(name.length - 1, 12);
  for (const c of name) w.put(NAME_CHARS.indexOf(c), NAME_CHARS.length);
  return w.toBigInt();
}

function lookFromBigInt(n: bigint, withTone: boolean, gr = 4): Look {
  const r = new Reader(n);
  const kind = r.get(2) ? 'mono' : 'colour';
  const hue = getVec(r, 7), light = getVec(r, 7), sat = getVec(r, 5);
  const grain = grainFromByte(r.get(gr));               // old low -> fine, medium..extreme -> film, 6 standard
  const wbi = r.get(226);
  const wb = wbi ? { a_b: Math.floor((wbi - 1) / 15) - 7, g_m: ((wbi - 1) % 15) - 7 } : null;
  const effect = effectFrom(r.get(EFFECT_N));
  const vignette = r.get(11) - 5;
  const art = r.get(ARTS.length);
  const mfi = r.get(19);
  const tone = withTone ? getTone(r) : zeroTone();
  const len = r.get(12) + 1;
  let name = '';
  for (let i = 0; i < len; i++) name += NAME_CHARS[r.get(NAME_CHARS.length)];
  if (r.n !== 0n) throw new Error('share code: damaged (extra data)');
  return {
    name, notes: '', kind, hue, light, sat, grain, wb, effect, vignette, art_effect: ARTS[art], tone,
    advice: mfi ? { mono_filter: { colour: MONO_FILTERS[Math.floor((mfi - 1) / 3)], strength: ((mfi - 1) % 3) + 1 } } : {},
  };
}

function toSymbols(n: bigint): number[] {
  const out: number[] = [];
  do { out.unshift(Number(n & 31n)); n >>= 5n; } while (n > 0n);
  return out;
}

/** Look -> share code, e.g. "1K7GQ...". group=true inserts a hyphen every 5 characters (ignored on input). */
export function encodeLookCode(l: Look, group = false): string {
  if ([...l.name].some((c) => !NAME_CHARS.includes(c)) || l.name.length < 1 || l.name.length > 12)
    throw new Error('share code: the name must be 1-12 printable ASCII characters without "@"');
  for (const k of TONE_KEYS) {
    const v = l.tone?.[k] ?? 0, L = toneLimit(k);
    if (!Number.isInteger(v) || Math.abs(v) > L) throw new Error(`share code: tone ${k} must be a whole number in -${L}..${L}`);
  }
  const withTone = !!l.tone && !toneIsZero(l.tone);
  const g7 = l.grain === 'standard';                 // only "standard" needs the radix-7 grain digit
  const ver = g7 ? (withTone ? LOOK_VERSION_G7_TONE : LOOK_VERSION_G7) : (withTone ? LOOK_VERSION_TONE : LOOK_VERSION);
  const syms = [ALPHABET.indexOf(ver), ...toSymbols(lookToBigInt(l, withTone, g7 ? 7 : 4))];
  const c = crc15(syms);
  syms.push((c >> 10) & 31, (c >> 5) & 31, c & 31);
  const s = syms.map((v) => ALPHABET[v]).join('');
  return group ? s.match(/.{1,5}/g)!.join('-') : s;
}

/** Forgiving clean-up: drop a URL up to '#', spaces and dashes; upper-case; Crockford O->0, I/L->1. */
export function normaliseLookCode(s: string): string {
  const h = s.lastIndexOf('#');
  if (h >= 0) s = s.slice(h + 1);
  return s.replace(/[\s\-_.]/g, '').toUpperCase().replace(/O/g, '0').replace(/[IL]/g, '1');
}

export function decodeLookCode(input: string): Look {
  const s = normaliseLookCode(input);
  if (s.length < 6) throw new Error('That code is too short.');
  const syms = [...s].map((ch) => ALPHABET.indexOf(ch));
  const bad = syms.indexOf(-1);
  if (bad >= 0) throw new Error(`"${s[bad]}" is not a code character.`);
  if (!KNOWN_VERSIONS.includes(s[0])) {
    if (/[7-9]/.test(s[0])) throw new Error(`This is a version-${s[0]} code from a newer Caduceus app. Update the app (or ask for a pack link).`);
    throw new Error('This is not a Caduceus look code.');
  }
  const body = syms.slice(0, -3), chk = syms.slice(-3);
  const c = crc15(body);
  if (chk[0] !== ((c >> 10) & 31) || chk[1] !== ((c >> 5) & 31) || chk[2] !== (c & 31))
    throw new Error('Check failed: the code has a typo (or is incomplete).');
  let n = 0n;
  for (const v of body.slice(1)) n = (n << 5n) | BigInt(v);
  const gr = s[0] === LOOK_VERSION_G7 || s[0] === LOOK_VERSION_G7_TONE ? 7 : s[0] === LOOK_VERSION_G6 || s[0] === LOOK_VERSION_G6_TONE ? 6 : 4;
  return lookFromBigInt(n, [LOOK_VERSION_TONE, LOOK_VERSION_G6_TONE, LOOK_VERSION_G7_TONE].includes(s[0]), gr);
}

// ---- pack codes
function b64url(b: Uint8Array): string {
  let s = '';
  for (let i = 0; i < b.length; i += 0x8000) s += String.fromCharCode(...b.subarray(i, i + 0x8000));
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
function unb64url(s: string): Uint8Array {
  const t = s.replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(t + '='.repeat((4 - (t.length % 4)) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}
async function pipe(data: Uint8Array, stream: CompressionStream | DecompressionStream): Promise<Uint8Array> {
  const out = new Response(new Blob([data as BlobPart]).stream().pipeThrough(stream));
  return new Uint8Array(await out.arrayBuffer());
}

export async function encodePackCode(pack: Pack): Promise<string> {
  const json = JSON.stringify({ schema: pack.schema, name: pack.name, looks: exportable(pack).looks, slots: pack.slots });
  return PACK_PREFIX + b64url(await pipe(new TextEncoder().encode(json), new CompressionStream('deflate')));
}

export async function decodePackCode(input: string): Promise<Pack> {
  let s = input.trim();
  const h = s.lastIndexOf('#');
  if (h >= 0) s = s.slice(h + 1);
  s = s.replace(/\s/g, '');
  if (!s.startsWith(PACK_PREFIX)) {
    if (/^pk\d+_/.test(s)) throw new Error('This pack link comes from a newer Caduceus app.');
    throw new Error('This is not a Caduceus pack link.');
  }
  let json: string;
  try {
    json = new TextDecoder('utf-8', { fatal: true }).decode(await pipe(unb64url(s.slice(PACK_PREFIX.length)), new DecompressionStream('deflate')));
  } catch {
    throw new Error('The pack link is damaged or incomplete.');
  }
  return parsePack(JSON.parse(json));
}

export const isPackCode = (s: string) => /(^|#)\s*pk\d+_/.test(s.trim());

// Re-exported so the tests can check the effect table stays complete.
export const _internals = { effectIndex, effectFrom, EFFECT_N, EFFECTS };
