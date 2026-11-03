import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { encodeLooksBin } from '../src/format';
import { SECTORS, blankLook, parsePack } from '../src/pack';
import { DEFAULT_TARGET, TARGETS, targetById } from '../src/targets';
import { recipeCard } from '../src/targets/recipe';
import libraryJson from '../src/data/library.json';

const LIB = parsePack(libraryJson);
const hex = (b: Uint8Array | string) => Buffer.from(b as Uint8Array).toString('hex');

describe('export target registry', () => {
  it('has unique ids, the E-P7 default, the recipe card and disabled placeholders with port docs', () => {
    expect(new Set(TARGETS.map((t) => t.id)).size).toBe(TARGETS.length);
    expect(DEFAULT_TARGET).toBe('ep7-caduceus');
    expect(TARGETS.filter((t) => t.status === 'ready').map((t) => t.id)).toEqual(['ep7-caduceus', 'recipe-card']);
    const soon = TARGETS.filter((t) => t.status === 'soon');
    expect(soon.map((t) => t.doc!.split('/').pop())).toEqual(['PORT_EM10IV.md', 'PORT_CANON_1100D.md']);
    for (const t of soon) {
      expect(t.supports(LIB.looks[0])).not.toBe(true);
      expect(() => t.export(LIB)).toThrow(/not available/);
    }
    for (const doc of soon.map((t) => t.doc!.split('/').pop()!)) expect(readFileSync(join(__dirname, '../../docs', doc), 'utf8').length).toBeGreaterThan(0);
  });

  it('falls back to the default for unknown, missing or not-ready ids', () => {
    for (const id of [null, undefined, 'nope', 'canon-pf2']) expect(targetById(id).id).toBe('ep7-caduceus');
    expect(targetById('recipe-card').id).toBe('recipe-card');
  });

  it('E-P7 target = the LOOKS.BIN export, unchanged', () => {
    const [f, ...rest] = targetById('ep7-caduceus').export(LIB);
    expect(rest).toEqual([]);
    expect(f.name).toBe('EP7MOD/LOOKS.BIN');
    expect(hex(f.data)).toBe(hex(encodeLooksBin(LIB)));
    const bad = blankLook('colour', 'Bad'); bad.hue[0] = 9;
    expect(targetById('ep7-caduceus').supports(bad)).toMatch(/hue/);
    expect(targetById('ep7-caduceus').supports(LIB.looks[0])).toBe(true);
  });
});

describe('recipe cards', () => {
  it('one Markdown file per look, unique names', () => {
    const files = targetById('recipe-card').export(LIB);
    expect(files.length).toBe(LIB.looks.length);
    expect(new Set(files.map((f) => f.name.toLowerCase())).size).toBe(files.length);
    expect(files.every((f) => f.name.endsWith('.md'))).toBe(true);
    const dup = targetById('recipe-card').export({ ...LIB, looks: [blankLook('colour', 'A/B'), blankLook('colour', 'A B')] });
    expect(dup.map((f) => f.name)).toEqual(['A-B.md', 'A-B-2.md']);
  });

  it('lists every parameter in plain words', () => {
    const l = blankLook('colour', 'Test Look');
    l.notes = 'Some notes.';
    l.hue[3] = 2; l.sat[6] = -4; l.light[10] = 1;
    l.tone = { highlights: -2, midtones: 1, shadows: 3, blacks: 2, whites: -1 };
    l.wb = { a_b: 3, g_m: -2 };
    l.grain = 'film';
    l.effect = { type: 'bloom', strength: 2, tint: 'amber' };
    l.art_effect = 'pin_hole';
    const c = recipeCard(l);
    for (const s of ['# Test Look', 'Some notes.', '**Type:** Colour', 'Amber 3 (A–B +3)', 'Magenta 2 (G–M −2)', '**Noise reduction:** Off (most texture)',
      'Glow 2 of 5 (amber tint)', '**Art effect:** Pin Hole', '**Highlights:** −2', '**Midtones:** +1', '**Shadows:** +3',
      '**Blacks:** +2', '**Whites:** −1', '| Red | +2 | 0 | 0 |', '| Blue | 0 | −4 | 0 |', '| Green | 0 | 0 | +1 |'])
      expect(c, s).toContain(s);
    for (const s of SECTORS) expect(c).toContain(`| ${s} |`);
    l.effect = { type: 'clarity', strength: 4 }; l.wb = null;
    expect(recipeCard(l)).toContain('Clarity 4 of 5');
    expect(recipeCard(l)).toContain('No shift');
  });

  it('mono cards give the filter and leave out the colour table and tone', () => {
    const acros = LIB.looks.find((l) => l.kind === 'mono')!;
    const c = recipeCard(acros);
    expect(c).toContain('**Type:** Monochrome');
    expect(c).toMatch(/\*\*Colour filter:\*\* (None|\w+, strength \d)/);
    expect(c).not.toContain('## Colour by hue');
    expect(c).not.toContain('## Tone');
  });

  it('every library look makes a card with its own name and tone', () => {
    for (const l of LIB.looks.filter((x) => x.kind === 'colour')) {
      const c = recipeCard(l);
      expect(c.startsWith(`# ${l.name}\n`)).toBe(true);
      expect(c).toContain(`**Blacks:** ${l.tone.blacks > 0 ? '+' : l.tone.blacks < 0 ? '−' : ''}${Math.abs(l.tone.blacks)}`);
    }
  });
});
