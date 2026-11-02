// Card-file encoders: EP7MOD/LOOKS.BIN (v4 = v3 + 16-byte tone tail per record; v3 still decodes) and EP7MOD/BUNDLES.BIN (v1 + name section).
// Byte-for-byte ports of the v0.16-era desktop tools (commit e477637; the format v0.17 cards use):
//   tools/ep7_looks_bin.py   header / record / make_file / check_file
//   tools/ep7_library.py     look_record (canonical bundle), place (look -> slot entry), name rules
//   patches/bundles/build.py slot_entry (field encoding), patches/sd_bundles/build.py RANGES_LEGACY + header
//   tools/ep7_bundles_bin.py name_section / check_names
// v0.19 tone contract (docs/TONE_ENDS.md §5): LOOKS.BIN v4 header version 4, record length 80 (+26, payload 80 n),
// record = v3 record + tail +64 blacks, +65 whites (s8 -5..5), +66 highlights, +67 shadows, +68 midtones (s8 -7..7),
// +69..79 = 0. BUNDLES.BIN slot +47 blacks, +48 whites (COLOR slots only; MONO slots keep 0).
// tests/encoder.test.ts checks the output against the Python tools and the released card files.
import {
  ARTS, EFFECTS, GRAINS, MAX_LOOKS, NAME_MAX, NOTE_MAX, PACK_SCHEMA, SLOT_NAMES, TINTS, TONE_BW_MAX, TONE_KEYS,
  blankLook, toneLimit, zeroTone, type Look, type Pack,
} from './pack';

// ---- CRC-32 (zlib)
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
export function crc32(...parts: Uint8Array[]): number {
  let c = 0xffffffff;
  for (const p of parts) for (let i = 0; i < p.length; i++) c = CRC_TABLE[(c ^ p[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// ---- constants (Python names in comments)
const MAGIC = [0x45, 0x50, 0x37, 0x42];                 // 'EP7B'
const FW_BUILD = 1100;                                  // SB.FW_BUILD
const SHA_PREFIX = [0x5d, 0xd9, 0xaf, 0x16];            // SB.SHA_PREFIX: decoded main SHA-256 5dd9af16...
export const LAYOUT_CRC = 0x68068776;                   // ep7_library.layout_crc() of patches/bundles/layout.json
export const HL_MAX = 7;                                // v0.16 firmware: hue/light -7..7 (RANGES_LEGACY)
export const SAT_MAX = 5, WB_MAX = 7, VIG_MAX = 5, STRENGTH_MAX = 5;
export const LOOKS_VERSION = 4;
const HDR_LEN = 64, REC_V3 = 64, REC_V4 = 80;
const recLen = (version: number) => (version === 3 ? REC_V3 : REC_V4);
// v4 tone tail: record offsets of blacks, whites, highlights, shadows, midtones
const TONE_OFF = { blacks: 64, whites: 65, highlights: 66, shadows: 67, midtones: 68 } as const;
const B_BLACKS = 47, B_WHITES = 48;
const BUNDLE_USED = 45, CLASS_OFF = 45, MASK_OFF = 46, TINT_OFF = 47, NAME_OFF = 48;
const B_TINT = 45, B_ART = 46, B_COLOUR = 32, B_SAT = 33, B_FLAGS = 31;
const FLAG_RENDER_COLOUR = 1, FLAG_HL = 2;
const BUNDLES_VERSION = 1, B_HDR_LEN = 32, B_PAYLOAD = 512, B_FILE = 544, B_FILE_N = 680;
const NMAGIC = [0x45, 0x50, 0x37, 0x4e];                // 'EP7N'
export const SLOT_NAME_MAX = 15;

// Per-byte loader ranges of the 64-byte bundle ABI (sd_bundles RANGES_LEGACY over layout.json fields).
const FIELDS: [number, number, number, number][] = [   // off, len, lo, hi
  [0, 12, -HL_MAX, HL_MAX], [12, 12, -HL_MAX, HL_MAX], [24, 1, 0, 3], [25, 1, 0, 1], [26, 1, -WB_MAX, WB_MAX],
  [27, 1, -WB_MAX, WB_MAX], [28, 1, 0, 3], [29, 1, 0, 5], [30, 1, -VIG_MAX, VIG_MAX], [31, 1, 0, 3], [32, 1, 0, 1],
  [33, 12, -SAT_MAX, SAT_MAX], [45, 1, 0, 4], [46, 1, 0, 5],
  [B_BLACKS, 1, -TONE_BW_MAX, TONE_BW_MAX], [B_WHITES, 1, -TONE_BW_MAX, TONE_BW_MAX]];
export const RANGE_LO = new Int8Array(64), RANGE_HI = new Int8Array(64);   // unclaimed bytes: 0..0
for (const [off, n, lo, hi] of FIELDS) for (let k = off; k < off + n; k++) { RANGE_LO[k] = lo; RANGE_HI[k] = hi; }
const s8 = (b: number) => (b >= 128 ? b - 256 : b);
const u8 = (v: number) => v & 0xff;

// ---- validation (same rules and limits as the tools; messages are for people)
export interface Problem { look?: number; field: string; message: string }

const NAME_RE = /^[\x20-\x3f\x41-\x7e]{1,12}$/;          // printable ASCII except '@' (OSD symbol escape)
export function nameProblem(name: string): string | null {
  if (name.length === 0) return 'Name is empty.';
  if (name !== name.trim()) return 'No spaces at the start or end of the name.';
  if (name.length > NAME_MAX) return `At most ${NAME_MAX} characters (${name.length}).`;
  if (name.includes('@')) return '"@" is not allowed (the camera uses it for symbols).';
  if (!NAME_RE.test(name)) return 'Plain ASCII letters, digits, spaces and punctuation only.';
  return null;
}

const intIn = (v: unknown, lo: number, hi: number) => Number.isInteger(v) && (v as number) >= lo && (v as number) <= hi;

export function validateLook(l: Look, i?: number): Problem[] {
  const p: Problem[] = [];
  const add = (field: string, message: string) => p.push({ look: i, field, message });
  const np = nameProblem(l.name);
  if (np) add('name', np);
  if (new TextEncoder().encode(l.notes).length > NOTE_MAX) add('notes', `Notes: at most ${NOTE_MAX} bytes.`);
  if (l.kind !== 'colour' && l.kind !== 'mono') add('kind', 'Kind must be colour or mono.');
  for (const [k, lim] of [['hue', HL_MAX], ['light', HL_MAX], ['sat', SAT_MAX]] as const) {
    const a = l[k];
    if (!Array.isArray(a) || a.length !== 12 || !a.every((v) => intIn(v, -lim, lim)))
      add(k, `${k}: 12 whole numbers in -${lim}..${lim} (v0.16/v0.17 firmware).`);
  }
  if (!GRAINS.includes(l.grain)) add('grain', 'Grain: off, low, medium or high.');
  if (l.wb && !(intIn(l.wb.a_b, -WB_MAX, WB_MAX) && intIn(l.wb.g_m, -WB_MAX, WB_MAX)))
    add('wb', `WB shift: A-B and G-M in -${WB_MAX}..${WB_MAX}.`);
  if (l.effect) {
    const e = l.effect;
    if (!EFFECTS.includes(e.type) || e.type === ('none' as string)) add('effect', 'Effect: bloom, halation or clarity.');
    else if (!intIn(e.strength, 1, STRENGTH_MAX)) add('effect', `Effect strength: 1..${STRENGTH_MAX}.`);
    if (e.tint !== undefined && (!TINTS.includes(e.tint) || (e.type !== 'bloom' && e.type !== 'halation')))
      add('effect', 'Glow colour only goes with bloom or halation.');
  }
  if (!intIn(l.vignette, -VIG_MAX, VIG_MAX)) add('vignette', `Vignette: -${VIG_MAX}..${VIG_MAX}.`);
  if (!l.tone || typeof l.tone !== 'object') add('tone', 'Tone: missing.');
  else for (const k of TONE_KEYS) {
    const lim = toneLimit(k);
    if (!intIn(l.tone[k], -lim, lim)) add('tone', `Tone ${k}: a whole number in -${lim}..${lim}.`);
  }
  if (!ARTS.includes(l.art_effect)) add('art_effect', 'Unknown Art Effect.');
  else if (l.art_effect !== 'off' && l.kind === 'mono') add('art_effect', 'Art Effects are for colour looks (COLOR slots).');
  return p;
}

export function validatePack(pack: Pack): Problem[] {
  const p: Problem[] = [];
  const n = pack.looks.length;
  if (n < 1) p.push({ field: 'looks', message: 'A pack needs at least one look.' });
  if (n > MAX_LOOKS) p.push({ field: 'looks', message: `At most ${MAX_LOOKS} looks (the camera's limit); this pack has ${n}.` });
  pack.looks.forEach((l, i) => p.push(...validateLook(l, i)));
  const seen = new Map<string, number>();
  pack.looks.forEach((l, i) => {
    const k = l.name.toLowerCase();
    if (seen.has(k)) p.push({ look: i, field: 'name', message: `Same name as look ${seen.get(k)! + 1} ("${l.name}").` });
    else seen.set(k, i);
  });
  for (const [s, i] of Object.entries(pack.slots)) {
    if (i === undefined) continue;
    const l = pack.looks[i];
    if (!l) p.push({ field: 'slots', message: `${s}: no look ${i + 1}.` });
    else if (s.startsWith('COLOR') && l.kind === 'mono') p.push({ field: 'slots', message: `${s}: a mono look can only go in a MONO slot.` });
  }
  return p;
}

// ---- LOOKS.BIN
/** The look's LOOKS.BIN record: v3 64 bytes (bundle bytes 0..44, class, slot mask, bloom tint, name[16]);
 *  v4 (default) adds the 16-byte tone tail. */
export function lookRecord(l: Look, version = LOOKS_VERSION): Uint8Array {
  const r = new Uint8Array(recLen(version));
  for (let k = 0; k < 12; k++) { r[k] = u8(l.hue[k]); r[12 + k] = u8(l.light[k]); }
  r[24] = GRAINS.indexOf(l.grain);
  if (l.wb) { r[25] = 1; r[26] = u8(l.wb.a_b); r[27] = u8(l.wb.g_m); }
  if (l.effect) {
    r[28] = EFFECTS.indexOf(l.effect.type);
    r[29] = l.effect.strength;
    if (l.effect.tint) r[TINT_OFF] = TINTS.indexOf(l.effect.tint);
  }
  r[30] = u8(l.vignette);
  const mono = l.kind === 'mono';
  r[B_FLAGS] = mono ? 0 : FLAG_HL;
  if (!mono) for (let k = 0; k < 12; k++) r[B_SAT + k] = u8(l.sat[k]);
  r[CLASS_OFF] = mono ? 1 : 0;
  r[MASK_OFF] = mono ? 2 : 3;          // colour looks always carry sat (-5..5), so they may also go in MONO slots
  const nm = new TextEncoder().encode(l.name);
  r.set(nm.subarray(0, 15), NAME_OFF);
  if (version !== 3) for (const k of TONE_KEYS) r[TONE_OFF[k]] = u8(l.tone[k]);
  return r;
}

function looksHeader(n: number, crc: number, version: number): Uint8Array {
  const h = new Uint8Array(HDR_LEN);
  const v = new DataView(h.buffer);
  const rl = recLen(version);
  h.set(MAGIC, 0);
  v.setUint16(4, version, true); v.setUint16(6, HDR_LEN, true);
  v.setUint32(8, FW_BUILD, true); v.setUint32(12, rl * n, true); v.setUint32(16, crc, true);
  h.set(SHA_PREFIX, 20);
  v.setUint16(24, n, true); v.setUint16(26, rl, true); v.setUint32(28, LAYOUT_CRC, true);
  return h;
}

export class PackError extends Error {
  constructor(public problems: Problem[]) { super(problems.map((p) => (p.look !== undefined ? `look ${p.look + 1}: ` : '') + p.message).join('\n')); }
}

/** Validated LOOKS.BIN bytes for the pack (throws PackError). The app always exports v4; `version` 3 exists for
 *  the tests (byte identity with the v3-era tools and release files; the tone is dropped). */
export function encodeLooksBin(pack: Pack, version = LOOKS_VERSION): Uint8Array {
  const probs = validatePack({ ...pack, slots: {} });
  if (probs.length) throw new PackError(probs);
  const n = pack.looks.length, rl = recLen(version);
  const out = new Uint8Array(HDR_LEN + rl * n);
  pack.looks.forEach((l, j) => out.set(lookRecord(l, version), HDR_LEN + rl * j));
  out.set(looksHeader(n, 0, version), 0);
  const crc = crc32(out.subarray(0, 16), out.subarray(20));
  new DataView(out.buffer).setUint32(16, crc, true);
  const chk = checkLooksBin(out);
  if (chk.length) throw new PackError(chk.map((m) => ({ field: 'file', message: m })));
  return out;
}

function nameOk(nm: Uint8Array): boolean {     // camera rule (_name_ok): 1..15 printable non-'@' then NUL to byte 15
  if (nm.length !== 16 || nm[0] === 0 || nm[15] !== 0) return false;
  let seen = false;
  for (const c of nm) {
    if (c === 0) seen = true;
    else if (seen || c === 0x40 || c < 0x20 || c > 0x7e) return false;
  }
  return true;
}

/** The version field of a LOOKS.BIN (3 or 4 are known), or 0 when it is too short to tell. */
export const looksBinVersion = (d: Uint8Array) => (d.length >= 6 ? d[4] | (d[5] << 8) : 0);

/** Mirror of the camera's pk_check (tools/ep7_looks_bin.py check_file, legacy ranges) for v3 and v4: [] = accepted. */
export function checkLooksBin(d: Uint8Array): string[] {
  const p: string[] = [];
  const size = d.length;
  const version = looksBinVersion(d);
  if (version !== 3 && version !== 4) return size < 6 ? [`size ${size}`] : [`version ${version}`];
  const rl = recLen(version);
  if (size < HDR_LEN + rl || size > HDR_LEN + rl * MAX_LOOKS || (size - HDR_LEN) % rl) return [`size ${size}`];
  const n = (size - HDR_LEN) / rl;
  const want = looksHeader(n, 0, version);
  for (let i = 0; i < HDR_LEN; i++) if ((i < 16 || i >= 20) && d[i] !== want[i]) { p.push('header'); break; }
  const crc = new DataView(d.buffer, d.byteOffset, d.byteLength).getUint32(16, true);
  if (crc32(d.subarray(0, 16), d.subarray(20)) !== crc) p.push('crc');
  for (let j = 0; j < n; j++) {
    const r = d.subarray(HDR_LEN + rl * j, HDR_LEN + rl * (j + 1));
    for (let k = 0; k < BUNDLE_USED; k++) {
      const v = s8(r[k]);
      if (v < RANGE_LO[k] || v > RANGE_HI[k]) { p.push(`look ${j} byte ${k} = ${v} out of range`); break; }
    }
    const cls = r[CLASS_OFF], mask = r[MASK_OFF];
    if (!((cls === 0 && (mask === 1 || mask === 3)) || (cls === 1 && mask === 2)) || r[TINT_OFF] > 4)
      p.push(`look ${j} class/mask/tint ${cls}/${mask}/${r[TINT_OFF]}`);
    if (!nameOk(r.subarray(NAME_OFF, NAME_OFF + 16))) p.push(`look ${j} name`);
    if (version === 4) {
      const bad = TONE_KEYS.find((k) => Math.abs(s8(r[TONE_OFF[k]])) > toneLimit(k));
      if (bad) p.push(`look ${j} tone ${bad} = ${s8(r[TONE_OFF[bad]])} out of range`);
      else if (r.subarray(69, REC_V4).some((b) => b !== 0)) p.push(`look ${j} tone tail`);
    }
  }
  return p;
}

/** LOOKS.BIN (v3 or v4, checked like the camera) -> pack. v3 looks get tone 0. LOOKS.BIN has no notes, Art Effect
 *  or advice; mono looks get the "no filter" advice. Throws with a readable message. */
export function decodeLooksBin(d: Uint8Array, name = 'Imported LOOKS.BIN'): Pack {
  const probs = checkLooksBin(d);
  if (probs.length) throw new Error(`LOOKS.BIN rejected (${probs.slice(0, 3).join('; ')})`);
  const version = looksBinVersion(d), rl = recLen(version), n = (d.length - HDR_LEN) / rl;
  const looks: Look[] = [];
  for (let j = 0; j < n; j++) {
    const r = d.subarray(HDR_LEN + rl * j, HDR_LEN + rl * (j + 1));
    const mono = r[CLASS_OFF] === 1;
    const nm = r.subarray(NAME_OFF, NAME_OFF + 16);
    const l = blankLook(mono ? 'mono' : 'colour', String.fromCharCode(...nm.subarray(0, nm.indexOf(0))));
    for (let k = 0; k < 12; k++) { l.hue[k] = s8(r[k]); l.light[k] = s8(r[12 + k]); if (!mono) l.sat[k] = s8(r[B_SAT + k]); }
    l.grain = GRAINS[r[24]];
    if (r[25]) l.wb = { a_b: s8(r[26]), g_m: s8(r[27]) };
    if (r[28]) {
      l.effect = { type: EFFECTS[r[28]] as Exclude<(typeof EFFECTS)[number], 'none'>, strength: r[29] };
      if (r[TINT_OFF]) l.effect.tint = TINTS[r[TINT_OFF]];
    }
    l.vignette = s8(r[30]);
    l.tone = zeroTone();
    if (version === 4) for (const k of TONE_KEYS) l.tone[k] = s8(r[TONE_OFF[k]]);
    looks.push(l);
  }
  return { schema: PACK_SCHEMA, name, looks, slots: {} };
}

// ---- BUNDLES.BIN (starter slot file)
/** P(look, slot): the 64-byte table entry a slot gets (tools/ep7_library.place) + the COLOR-slot Art Effect and
 *  Blacks/Whites (+47/+48; MONO slots keep 0). */
export function placeLook(l: Look, slot: string): Uint8Array {
  const rec = lookRecord(l);
  const b = new Uint8Array(64);
  b.set(rec.subarray(0, BUNDLE_USED));
  b[B_TINT] = rec[TINT_OFF];
  if (slot.startsWith('COLOR')) {
    if (l.kind === 'mono') throw new Error(`${slot}: a mono look cannot go in a COLOR slot`);
    b.fill(0, B_SAT, B_SAT + 12);
    b[B_COLOUR] = 0;
    b[B_FLAGS] = FLAG_HL;
    b[B_ART] = ARTS.indexOf(l.art_effect);
    b[B_BLACKS] = u8(l.tone.blacks);
    b[B_WHITES] = u8(l.tone.whites);
  } else if (l.kind === 'colour') {
    b[B_COLOUR] = 1;
    b[B_FLAGS] = FLAG_HL | FLAG_RENDER_COLOUR;
  } else {
    b[B_FLAGS] = 0;
  }
  return b;
}

/** BUNDLES.BIN for the pack's slot assignment (680 B with the look names as slot names; empty slot = stock). */
export function encodeBundlesBin(pack: Pack, withNames = true): Uint8Array {
  const probs = validatePack(pack).filter((p) => p.field === 'slots' || (p.look !== undefined && Object.values(pack.slots).includes(p.look)));
  if (probs.length) throw new PackError(probs);
  const out = new Uint8Array(withNames ? B_FILE_N : B_FILE);
  const dv = new DataView(out.buffer);
  out.set(MAGIC, 0);
  dv.setUint16(4, BUNDLES_VERSION, true); dv.setUint16(6, B_HDR_LEN, true);
  dv.setUint32(8, FW_BUILD, true); dv.setUint32(12, B_PAYLOAD, true);
  out.set(SHA_PREFIX, 20);
  SLOT_NAMES.forEach((s, k) => {
    const i = pack.slots[s];
    if (i !== undefined) out.set(placeLook(pack.looks[i], s), B_HDR_LEN + 64 * k);
  });
  dv.setUint32(16, crc32(out.subarray(0, 16), out.subarray(20, B_FILE)), true);
  if (withNames) {
    SLOT_NAMES.forEach((s, k) => {
      const i = pack.slots[s];
      if (i !== undefined) out.set(new TextEncoder().encode(pack.looks[i].name).subarray(0, SLOT_NAME_MAX), B_FILE + 16 * k);
    });
    out.set(NMAGIC, B_FILE + 128);
    dv.setUint32(B_FILE + 132, crc32(out.subarray(B_FILE, B_FILE + 132)), true);
  }
  const chk = checkBundlesBin(out);
  if (chk.length) throw new PackError(chk.map((m) => ({ field: 'file', message: m })));
  return out;
}

/** Mirror of tools/ep7_bundles_bin.py check_file (+ check_names for a 680-byte file): [] = accepted. */
export function checkBundlesBin(d: Uint8Array): string[] {
  if (d.length !== B_FILE && d.length !== B_FILE_N) return [`size ${d.length}`];
  const p: string[] = [];
  const dv = new DataView(d.buffer, d.byteOffset, d.byteLength);
  const want = new Uint8Array(B_HDR_LEN);
  want.set(MAGIC, 0);
  new DataView(want.buffer).setUint16(4, BUNDLES_VERSION, true);
  new DataView(want.buffer).setUint16(6, B_HDR_LEN, true);
  new DataView(want.buffer).setUint32(8, FW_BUILD, true);
  new DataView(want.buffer).setUint32(12, B_PAYLOAD, true);
  want.set(SHA_PREFIX, 20);
  for (let i = 0; i < B_HDR_LEN; i++) if ((i < 16 || i >= 20) && d[i] !== want[i]) { p.push(`header byte ${i}`); break; }
  if (crc32(d.subarray(0, 16), d.subarray(20, B_FILE)) !== dv.getUint32(16, true)) p.push('crc32');
  for (let k = 0; k < B_PAYLOAD; k++) {
    const v = s8(d[B_HDR_LEN + k]);
    if (v < RANGE_LO[k % 64] || v > RANGE_HI[k % 64]) { p.push(`slot ${k >> 6} byte ${k % 64} = ${v} out of range`); break; }
  }
  if (d.length === B_FILE_N) {
    if (!NMAGIC.every((c, i) => d[B_FILE + 128 + i] === c)) p.push('name marker');
    else if (crc32(d.subarray(B_FILE, B_FILE + 132)) !== dv.getUint32(B_FILE + 132, true)) p.push('name crc');
    else for (let k = 0; k < 8; k++) {
      let nul = false;
      for (let i = 0; i < 16; i++) {
        const c = d[B_FILE + 16 * k + i];
        if (c === 0) nul = true;
        else if (nul || i === 15 || c === 0x40 || c < 0x20 || c > 0x7e) { p.push(`slot ${k} name`); break; }
      }
    }
  }
  return p;
}
