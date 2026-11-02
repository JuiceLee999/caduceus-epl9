import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { encodeLooksBin } from '../src/format';
import { exportable, parsePack } from '../src/pack';
import { decodeLookCode, encodeLookCode } from '../src/sharecode';
import { resetLook, standardPack } from '../src/reset';
import libraryJson from '../src/data/library.json';

const LIB = parsePack(libraryJson);
const RELEASE_LOOKS = join(__dirname, '../../releases/v0.17/card/EP7MOD/LOOKS.BIN');
const hex = (b: Uint8Array) => Buffer.from(b).toString('hex');
const names = (p: { looks: { name: string }[] }, skip: number) => p.looks.filter((_, k) => k !== skip).map((l) => l.name);

function mangle(p: ReturnType<typeof standardPack>, i: number) {
  const l = p.looks[i];
  l.hue = l.hue.map((v) => (v + 3) % 7); l.light[0] = -4; l.sat[5] = 2; l.grain = 'high';
  l.wb = { a_b: 3, g_m: -2 }; l.effect = { type: 'clarity', strength: 4 }; l.notes = 'changed';
}

describe('reset', () => {
  it('standard pack encodes to the shipped LOOKS.BIN', () => {
    expect(hex(encodeLooksBin(standardPack(LIB)))).toBe(hex(new Uint8Array(readFileSync(RELEASE_LOOKS))));
  });

  it('resetting every edited library look gives byte-identical LOOKS.BIN', () => {
    const want = hex(encodeLooksBin(LIB));
    const p = standardPack(LIB);
    p.looks.forEach((_, i) => mangle(p, i));
    p.looks[2].name = 'Renamed';
    expect(hex(encodeLooksBin(p))).not.toBe(want);
    p.looks = p.looks.map((l, i) => resetLook(l, LIB, names(p, i)));
    expect(hex(encodeLooksBin(p))).toBe(want);
    expect(exportable(p).looks).toEqual(LIB.looks);
  });

  it('a renamed library look keeps its name if the shipped one is taken', () => {
    const p = standardPack(LIB);
    p.looks[0].name = 'Mine';
    p.looks[1].name = LIB.looks[0].name;
    const r = resetLook(p.looks[0], LIB, names(p, 0));
    expect(r.name).toBe('Mine');
    expect(r.hue).toEqual(LIB.looks[0].hue);
  });

  it('a non-library look resets to neutral, keeping name, kind and notes', () => {
    const p = standardPack(LIB);
    const imported = decodeLookCode(encodeLookCode(p.looks[0]));  // same values, but no library origin
    imported.notes = 'mine';
    const r = resetLook(imported, LIB);
    expect(r.name).toBe(imported.name);
    expect(r.notes).toBe('mine');
    expect(r.kind).toBe(imported.kind);
    expect([...r.hue, ...r.light, ...r.sat].every((v) => v === 0)).toBe(true);
    expect([r.grain, r.wb, r.effect, r.vignette]).toEqual(['off', null, null, 0]);
  });

  it('origin stays out of exported files and share codes', () => {
    const p = standardPack(LIB);
    expect(p.looks.every((l) => l.origin === l.name)).toBe(true);
    expect(JSON.stringify(exportable(p))).not.toContain('"origin"');
  });
});
