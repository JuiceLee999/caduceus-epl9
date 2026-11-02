import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, describe, expect, it } from 'vitest';
import { resolveRepoLibrary } from '../scripts/library.mjs';
import {
  checkBundlesBin, checkLooksBin, crc32, decodeLooksBin, encodeBundlesBin, encodeLooksBin, lookRecord, PackError, validatePack,
} from '../src/format';
import {
  ARTS, EFFECTS, GRAINS, TINTS, TONE_KEYS, blankLook, cloneLook, parsePack, toneIsZero, toneLimit, zeroTone,
  type Look, type Pack, type Tone,
} from '../src/pack';
import committed from '../src/data/library.json';

const WEBAPP = join(__dirname, '..');
const ROOT = join(WEBAPP, '..');
const RELEASE_LOOKS = join(ROOT, 'releases/v0.17/card/EP7MOD/LOOKS.BIN');
const TOOLS_COMMIT = 'e477637';      // v0.16-era tools: the LOOKS.BIN format and ranges of the v0.17 card
const hex = (b: Uint8Array) => Buffer.from(b).toString('hex');
const library = () => parsePack(resolveRepoLibrary(ROOT));

// What LOOKS.BIN keeps of a look (no notes, Art Effect or advice).
const cardView = (l: Look) => ({ ...cloneLook(l), notes: '', art_effect: 'off', advice: l.kind === 'mono' ? { mono_filter: { colour: 'none', strength: 1 } } : {} });

describe('built-in library', () => {
  it('v3 LOOKS.BIN is byte-identical to the released v0.17 card file', () => {
    const want = new Uint8Array(readFileSync(RELEASE_LOOKS));
    const got = encodeLooksBin(library(), 3);
    expect(got.length).toBe(want.length);
    expect(hex(got)).toBe(hex(want));
    expect(checkLooksBin(got)).toEqual([]);
  });

  it('v4 LOOKS.BIN = v3 records + tone tail, 64 + 80 n bytes, header version 4 / record length 80', () => {
    const v3 = new Uint8Array(readFileSync(RELEASE_LOOKS));
    const lib = library();
    lib.looks[0].tone = { highlights: -7, shadows: 7, midtones: 3, blacks: -5, whites: 5 };
    const got = encodeLooksBin(lib);
    const n = lib.looks.length, dv = new DataView(got.buffer);
    expect(got.length).toBe(64 + 80 * n);
    expect(checkLooksBin(got)).toEqual([]);
    expect([dv.getUint16(4, true), dv.getUint16(6, true), dv.getUint32(12, true), dv.getUint16(24, true), dv.getUint16(26, true)])
      .toEqual([4, 64, 80 * n, n, 80]);
    expect(hex(got.subarray(20, 24))).toBe(hex(v3.subarray(20, 24)));
    expect(hex(got.subarray(28, 64))).toBe(hex(v3.subarray(28, 64)));
    for (let j = 0; j < n; j++) {
      const r = got.subarray(64 + 80 * j, 64 + 80 * (j + 1));
      expect(hex(r.subarray(0, 64))).toBe(hex(v3.subarray(64 + 64 * j, 128 + 64 * j)));
      expect(r.subarray(69).every((b) => b === 0)).toBe(true);
    }
    expect([...got.subarray(64 + 64, 64 + 69)].map((b) => (b << 24) >> 24)).toEqual([-5, 5, -7, 7, 3]);
  });

  it('imports the released v3 LOOKS.BIN (tone 0) and its own v4 export', () => {
    const lib = library();
    const v3 = decodeLooksBin(new Uint8Array(readFileSync(RELEASE_LOOKS)));
    expect(v3.looks.map((l) => l.tone).every(toneIsZero)).toBe(true);
    expect(v3.looks).toEqual(lib.looks.map((l) => ({ ...cardView(l), tone: zeroTone() })));
    const r = rng(11);
    lib.looks.forEach((l) => (l.tone = randomTone(r)));
    const back = decodeLooksBin(encodeLooksBin(lib));
    expect(back.looks).toEqual(lib.looks.map(cardView));
    expect(hex(encodeLooksBin(back))).toBe(hex(encodeLooksBin(lib)));
  });

  it('src/data/library.json is current (run `npm run gen-library` after changing the library)', () => {
    expect(committed).toEqual(resolveRepoLibrary(ROOT));
  });

  it('starter BUNDLES.BIN from the library slot assignment passes the loader rules', () => {
    const b = encodeBundlesBin(library());
    expect(b.length).toBe(680);
    expect(checkBundlesBin(b)).toEqual([]);
  });

  it('starter BUNDLES.BIN: Blacks/Whites at +47/+48 in COLOR slots only; MONO slots keep 0', () => {
    const c = blankLook('colour', 'C'), m = blankLook('mono', 'M');
    c.tone = { highlights: 7, shadows: -7, midtones: 1, blacks: 3, whites: -4 };
    m.tone = { highlights: 0, shadows: 0, midtones: 0, blacks: -2, whites: 2 };
    const b = encodeBundlesBin(pack([c, m], { COLOR2: 0, MONO1: 0, MONO2: 1 }));
    expect(checkBundlesBin(b)).toEqual([]);
    const slot = (k: number) => b.subarray(32 + 64 * k, 32 + 64 * (k + 1));
    expect([slot(1)[47], slot(1)[48]]).toEqual([3, 0xfc]);
    expect(slot(1).subarray(49).every((x) => x === 0)).toBe(true);
    for (const k of [4, 5]) expect(slot(k).subarray(47).every((x) => x === 0)).toBe(true);
    const bad = b.slice(); bad[32 + 64 + 47] = 6;
    expect(checkBundlesBin(bad).join()).toMatch(/byte 47 = 6 out of range/);
  });
});

function randomTone(r: () => number): Tone {
  const t = zeroTone();
  if (r() < 0.3) return t;
  for (const k of TONE_KEYS) if (r() < 0.6) t[k] = Math.floor(r() * (2 * toneLimit(k) + 1)) - toneLimit(k);
  return t;
}

// ---- validation rejects
function pack(looks: Look[], slots: Pack['slots'] = {}): Pack {
  return { schema: 'caduceus-pack/1', name: 't', looks, slots };
}
const withLook = (f: (l: Look) => void): Pack => {
  const l = blankLook('colour', 'Test');
  f(l);
  return pack([l]);
};
const rejects = (p: Pack, field: string) => {
  expect(() => encodeLooksBin(p)).toThrow(PackError);
  expect(validatePack(p).some((x) => x.field === field)).toBe(true);
};

describe('validation', () => {
  it('accepts a minimal pack', () => {
    expect(validatePack(pack([blankLook()]))).toEqual([]);
    expect(encodeLooksBin(pack([blankLook()])).length).toBe(144);
  });
  it('rejects an empty pack and more than 32 looks', () => {
    rejects(pack([]), 'looks');
    rejects(pack(Array.from({ length: 33 }, (_, i) => blankLook('colour', `L${i}`))), 'looks');
    expect(encodeLooksBin(pack(Array.from({ length: 32 }, (_, i) => blankLook('colour', `L${i}`)))).length).toBe(64 + 32 * 80);
  });
  it.each([
    ['', 'empty'], ['ThirteenChars', 'too long'], ['A@B', 'at sign'], [' Lead', 'leading space'], ['Trail ', 'trailing space'],
    ['Café', 'non-ASCII'], ['Tab\there', 'control char'],
  ])('rejects name %j (%s)', (name) => rejects(withLook((l) => (l.name = name)), 'name'));
  it('accepts 12-char names and punctuation', () => {
    expect(validatePack(withLook((l) => (l.name = 'Kodachrome25')))).toEqual([]);
    expect(validatePack(withLook((l) => (l.name = 'Cl. Chrome!~')))).toEqual([]);
  });
  it('rejects duplicate names (case-insensitive)', () => rejects(pack([blankLook('colour', 'Velvia'), blankLook('colour', 'VELVIA')]), 'name'));
  it('rejects hue/light beyond the v0.16 firmware ±7 (extended H/L is not released)', () => {
    rejects(withLook((l) => (l.hue[3] = 8)), 'hue');
    rejects(withLook((l) => (l.light[0] = -8)), 'light');
    rejects(withLook((l) => (l.hue[0] = 1.5)), 'hue');
  });
  it('rejects sat beyond ±5, WB beyond ±7, vignette beyond ±5', () => {
    rejects(withLook((l) => (l.sat[5] = 6)), 'sat');
    rejects(withLook((l) => (l.wb = { a_b: 8, g_m: 0 })), 'wb');
    rejects(withLook((l) => (l.vignette = 6)), 'vignette');
  });
  it('tone: H/S/M -7..7, Blacks/Whites -5..5, whole numbers', () => {
    expect(validatePack(withLook((l) => (l.tone = { highlights: -7, shadows: 7, midtones: 7, blacks: -5, whites: 5 })))).toEqual([]);
    for (const [k, v] of [['highlights', 8], ['shadows', -8], ['midtones', 0.5], ['blacks', 6], ['whites', -6], ['blacks', 1.5]] as const)
      rejects(withLook((l) => (l.tone[k] = v)), 'tone');
    expect(() => parsePack({ schema: 'caduceus-pack/1', looks: [{ name: 'x', tone: { blacks: 'a' } }] })).toThrow(/tone blacks/);
    expect(() => parsePack({ schema: 'caduceus-pack/1', looks: [{ name: 'x', tone: { contrast: 1 } }] })).toThrow(/unknown tone/);
    expect(parsePack({ schema: 'caduceus-pack/1', looks: [{ name: 'x', tone: { whites: -2 } }] }).looks[0].tone)
      .toEqual({ highlights: 0, shadows: 0, midtones: 0, blacks: 0, whites: -2 });
    expect(parsePack({ schema: 'caduceus-pack/1', looks: [{ name: 'x' }] }).looks[0].tone).toEqual(zeroTone());
  });
  it('rejects bad effects', () => {
    rejects(withLook((l) => (l.effect = { type: 'bloom', strength: 0 })), 'effect');
    rejects(withLook((l) => (l.effect = { type: 'clarity', strength: 6 })), 'effect');
    rejects(withLook((l) => (l.effect = { type: 'clarity', strength: 2, tint: 'red' })), 'effect');
  });
  it('rejects notes over 200 bytes and Art Effects on mono looks', () => {
    rejects(withLook((l) => (l.notes = 'é'.repeat(101))), 'notes');
    const m = blankLook('mono', 'M');
    m.art_effect = 'pin_hole';
    rejects(pack([m]), 'art_effect');
  });
  it('rejects a mono look in a COLOR slot of BUNDLES.BIN', () => {
    expect(() => encodeBundlesBin(pack([blankLook('mono', 'M')], { COLOR1: 0 }))).toThrow(PackError);
  });
  it('the file checker catches damage', () => {
    const good = encodeLooksBin(pack([blankLook()]));
    const crc = good.slice(); crc[70] ^= 1;
    expect(checkLooksBin(crc)).toContain('crc');
    const hdr = good.slice(); hdr[26] = 64;
    expect(checkLooksBin(hdr)).toContain('header');
    const ver = good.slice(); ver[4] = 5;
    expect(checkLooksBin(ver)).toEqual(['version 5']);
    expect(checkLooksBin(good.slice(0, 100))).toEqual(['size 100']);
    expect(checkLooksBin(good.slice(0, 128))).toEqual(['size 128']);      // a v3-sized file with a v4 header
    const fix = (d: Uint8Array) => { new DataView(d.buffer).setUint32(16, crc32(d.subarray(0, 16), d.subarray(20)), true); return d; };
    const tone = good.slice(); tone[64 + 66] = 8;
    expect(checkLooksBin(fix(tone))).toEqual(['look 0 tone highlights = 8 out of range']);
    const bw = good.slice(); bw[64 + 64] = 0xfa;
    expect(checkLooksBin(fix(bw))).toEqual(['look 0 tone blacks = -6 out of range']);
    const tail = good.slice(); tail[64 + 79] = 1;
    expect(checkLooksBin(fix(tail))).toEqual(['look 0 tone tail']);
    expect(() => decodeLooksBin(fix(tail))).toThrow(/rejected/);
    const b = encodeBundlesBin(pack([blankLook()], { COLOR1: 0 }));
    const nb = b.slice(); nb[600] ^= 1;
    expect(checkBundlesBin(nb)).toContain('name crc');
  });
  it('parsePack rejects malformed files', () => {
    expect(() => parsePack({ schema: 'other' })).toThrow();
    expect(() => parsePack({ schema: 'caduceus-pack/1', looks: [{ name: 'x', hue: [1, 2] }] })).toThrow(/12 integers/);
    expect(() => parsePack({ schema: 'caduceus-pack/1', looks: [{ name: 'x', grain: 'huge' }] })).toThrow(/grain/);
  });
});

// ---- cross-check against the Python tools at the v0.16-era commit on random packs
function rng(seed: number) {
  return () => ((seed = (seed * 1103515245 + 12345) >>> 0) / 2 ** 32);
}
function randomLook(r: () => number, i: number): Look {
  const ri = (lo: number, hi: number) => lo + Math.floor(r() * (hi - lo + 1));
  const sparse = (lim: number) => Array.from({ length: 12 }, () => (r() < 0.5 ? 0 : ri(-lim, lim)));
  const mono = r() < 0.25;
  const l = blankLook(mono ? 'mono' : 'colour', `Look ${i}${String.fromCharCode(33 + ri(0, 30))}`.slice(0, 12));
  l.hue = sparse(7); l.light = sparse(7);
  l.sat = mono ? new Array(12).fill(0) : sparse(5);
  l.grain = GRAINS[ri(0, 3)];
  l.wb = r() < 0.5 ? { a_b: ri(-7, 7), g_m: ri(-7, 7) } : null;
  const et = EFFECTS[ri(0, 3)];
  l.effect = et === 'none' ? null : { type: et, strength: ri(1, 5) };
  if (l.effect && et !== 'clarity' && r() < 0.6) l.effect.tint = TINTS[ri(0, 4)];
  l.vignette = ri(-5, 5);
  if (!mono) l.art_effect = ARTS[ri(0, 3)];
  l.notes = r() < 0.3 ? 'note' : '';
  l.tone = randomTone(r);
  return l;
}
function toPython(p: Pack, withTone: boolean) {
  const recipes: Record<string, unknown> = {}, looks: Record<string, unknown> = {}, slots: Record<string, string> = {},
    art: Record<string, number> = {};
  p.looks.forEach((l, i) => {
    const k = `k${i}`;
    recipes[k] = { name: l.name, base: l.kind === 'mono' ? 'Monochrome Profile' : 'Color Profile', hue: l.hue, light: l.light, sat: l.sat };
    const look: Record<string, unknown> = { name: l.name, recipe: k, grain: l.grain };
    if (l.wb) look.wb = l.wb;
    if (l.effect) look.effect = l.effect;
    if (l.vignette) look.vignette = l.vignette;
    if (l.notes) look.notes = l.notes;
    if (withTone && !toneIsZero(l.tone)) look.tone = l.tone;    // missing = 0
    looks[k] = look;
  });
  for (const [s, i] of Object.entries(p.slots)) {
    slots[s] = `k${i}`;
    if (s.startsWith('COLOR')) art[s] = ARTS.indexOf(p.looks[i!].art_effect);
  }
  return { recipes, library: { looks }, slots, art };
}

const python = ['.venv/bin/python', 'python3'].map((p) => (p.startsWith('.') ? join(ROOT, p) : p))
  .find((p) => { try { execFileSync(p, ['-c', '0']); return true; } catch { return false; } });
let ref: string | undefined;
try {
  if (python && existsSync(join(ROOT, '.git'))) {
    ref = mkdtempSync(join(tmpdir(), 'caduceus-ref-'));
    execFileSync('sh', ['-c', `git -C "${ROOT}" archive ${TOOLS_COMMIT} tools patches/bundles patches/sd_bundles patches/wb | tar -x -C "${ref}"`]);
  }
} catch { ref = undefined; }
afterAll(() => { if (ref) rmSync(ref, { recursive: true, force: true }); });

function randomPacks(seed: number, count: number): Pack[] {
  const r = rng(seed);
  const packs: Pack[] = [];
  for (let t = 0; t < count; t++) {
    const n = 1 + Math.floor(r() * 32);
    const looks = Array.from({ length: n }, (_, i) => randomLook(r, i));
    const slots: Pack['slots'] = {};
    const colour = looks.map((l, i) => (l.kind === 'colour' ? i : -1)).filter((i) => i >= 0);
    ['COLOR1', 'COLOR2', 'COLOR3', 'COLOR4'].forEach((s) => { if (colour.length && r() < 0.7) slots[s as 'COLOR1'] = colour[Math.floor(r() * colour.length)]; });
    ['MONO1', 'MONO2', 'MONO3', 'MONO4'].forEach((s) => { if (r() < 0.7) slots[s as 'MONO1'] = Math.floor(r() * n); });
    packs.push(pack(looks, slots));
  }
  return packs;
}
const runPy = (root: string, cases: unknown[]) => JSON.parse(execFileSync(python!, ['-I', join(WEBAPP, 'tests/py_reference.py'), root],
  { input: JSON.stringify(cases), maxBuffer: 1 << 26 }).toString());

describe.skipIf(!ref)(`cross-check with the Python tools at ${TOOLS_COMMIT} (v3, no tone)`, () => {
  it('random packs: v3 LOOKS.BIN and BUNDLES.BIN are byte-identical', () => {
    const packs = randomPacks(7, 40);
    // the v3-era tools know no tone: H/S/M do not reach v3 files, Blacks/Whites would reach BUNDLES.BIN
    packs.push(library());
    for (const p of packs) for (const l of p.looks) { l.tone.blacks = 0; l.tone.whites = 0; }
    const out = runPy(ref!, packs.map((p) => toPython(p, false)));
    packs.forEach((p, i) => {
      expect(out[i].error).toBeUndefined();
      expect(out[i].looks_check).toEqual([]);
      expect(out[i].bundles_check).toEqual([]);
      expect(hex(encodeLooksBin(p, 3))).toBe(out[i].looks);
      expect(hex(encodeBundlesBin(p))).toBe(out[i].bundles);
    });
  });

  it('the Python tools reject what the app rejects (hue 8 on v0.16 firmware)', () => {
    const l = blankLook('colour', 'Hot');
    l.hue[0] = 8;
    const out = runPy(ref!, [toPython(pack([l]), false)]);
    expect(out[0].error).toMatch(/hue/);
    expect(() => encodeLooksBin(pack([l]))).toThrow(PackError);
  });

  it('record bytes do not depend on notes or advice', () => {
    const l = randomLook(rng(3), 1);
    const m = cloneLook(l);
    m.notes = 'different';
    m.advice = { contrast: 3 };
    expect(hex(lookRecord(l))).toBe(hex(lookRecord(m)));
  });
});

// The current tools (working tree): LOOKS.BIN v4 + Blacks/Whites in BUNDLES.BIN. Skipped (with a note) until the
// repo's tools/ep7_looks_bin.py writes version 4.
let pyLooksVersion = 0;
try { if (python) pyLooksVersion = JSON.parse(execFileSync(python, ['-I', join(WEBAPP, 'tests/py_reference.py'), ROOT, '--info']).toString()).looks_version; }
catch { pyLooksVersion = 0; }
if (python && pyLooksVersion !== 4) console.warn(`v4 cross-check skipped: the repo's tools/ep7_looks_bin.py writes version ${pyLooksVersion}`);

describe.skipIf(pyLooksVersion !== 4)('cross-check with the current Python tools (v4, tone)', () => {
  it('random packs with tone: v4 LOOKS.BIN and BUNDLES.BIN are byte-identical', () => {
    const packs = randomPacks(19, 40);
    packs.push(library());
    const out = runPy(ROOT, packs.map((p) => toPython(p, true)));
    packs.forEach((p, i) => {
      expect(out[i].error).toBeUndefined();
      expect(out[i].looks_check).toEqual([]);
      expect(out[i].bundles_check).toEqual([]);
      expect(hex(encodeLooksBin(p))).toBe(out[i].looks);
      expect(hex(encodeBundlesBin(p))).toBe(out[i].bundles);
    });
  });

  it('the Python tools reject out-of-range tone like the app', () => {
    for (const t of [{ highlights: 8 }, { blacks: -6 }, { whites: 6 }, { midtones: -8 }]) {
      const l = blankLook('colour', 'T');
      Object.assign(l.tone, t);
      const out = runPy(ROOT, [toPython(pack([l]), true)]);
      expect(out[0].error, JSON.stringify(t)).toBeDefined();
      expect(() => encodeLooksBin(pack([l]))).toThrow(PackError);
    }
  });
});

describe('card zip', () => {
  it('is a valid zip with the EP7MOD folder (checked with Python zipfile)', async () => {
    const { makeZip } = await import('../src/zip');
    const lb = encodeLooksBin(library()), bb = encodeBundlesBin(library());
    const z = makeZip([{ name: 'EP7MOD/LOOKS.BIN', data: lb }, { name: 'EP7MOD/BUNDLES.BIN', data: bb }]);
    const py = python ?? 'python3';
    const out = execFileSync(py, ['-I', '-c',
      'import sys,zipfile,io,hashlib;z=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read()));assert z.testzip() is None;' +
      'print(";".join(f"{i.filename}:{hashlib.sha256(z.read(i)).hexdigest()}" for i in z.infolist()))'], { input: Buffer.from(z) }).toString().trim();
    const sha = (b: Uint8Array) => createHash('sha256').update(b).digest('hex');
    expect(out).toBe(`EP7MOD/LOOKS.BIN:${sha(lb)};EP7MOD/BUNDLES.BIN:${sha(bb)}`);
  });
});
