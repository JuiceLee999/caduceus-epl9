// Resolve a look-library JSON (bundles/library_v3.json, the tools/ep7_looks_bin.py input) plus the recipe files it
// names (sim/recipes/*.json) into the web app's flat pack form. A port of tools/ep7_library.py look_record() and
// patches/bundles/build.py slot_entry() as of the v0.16-era tools (commit e477637): hue/light -7..7, sat -5..5;
// plus the v0.19 per-look "tone" {highlights, shadows, midtones, blacks, whites} (missing = 0).
//
// Used by scripts/gen-library.mjs (writes src/data/library.json at build time) and by the tests.
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

export const RECIPE_FILES = ['sim/recipes/fuji_like.json', 'sim/recipes/film_look.json', 'sim/recipes/library_v1.json',
  'sim/recipes/library_v2.json', 'sim/recipes/library_v3.json'];
export const GRAINS = ['off', 'fine', 'film', 'standard'];   // v0.22: low -> fine, medium/high -> film (Noise Filter Low / Off)
const GRAIN_MAP = { off: 'off', global: 'off', standard: 'standard', low: 'fine', fine: 'fine', med: 'film', medium: 'film', high: 'film', film: 'film', heavy: 'film', extreme: 'film' };
const DEFAULT_NAMES = {
  provia: 'Provia', velvia: 'Velvia', classic_chrome: 'Cl. Chrome', classic_neg: 'Classic Neg',
  nostalgic_neg: 'Nostalgic', reala_ace: 'Reala Ace', eterna: 'Eterna', eterna_bleach_bypass: 'Bleach Byp.',
  acros: 'Acros', kodachrome_64: 'Kodachrome', cinestill_800t: 'CineStill', portra_400_bloom: 'Portra Bloom',
  classic_neg_halation: 'Neg Halation',
};

export function loadRecipes(root) {
  const out = {};
  for (const f of RECIPE_FILES) {
    const j = JSON.parse(readFileSync(join(root, f), 'utf8'));
    for (const [k, v] of Object.entries(j.recipes)) {
      if (k in out) throw new Error(`recipe ${k} defined twice`);
      out[k] = v;
    }
  }
  return out;
}

const isMono = (rc) => Boolean(rc.mono_filter) || String(rc.base ?? '').toLowerCase().startsWith('monochrome');
const zeros = () => new Array(12).fill(0);
const satOk = (s) => Array.isArray(s) && s.length === 12 && s.every((v) => Number.isInteger(v) && v >= -5 && v <= 5);
const titleCase = (s) => s.replace(/_/g, ' ').replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());

/** One library look -> pack look (the same values the Python tools put in its LOOKS.BIN record). */
export function resolveLook(key, look, recipes) {
  const rname = look.recipe ?? key;
  const rc = recipes[rname];
  if (!rc) throw new Error(`look ${key}: unknown recipe ${rname}`);
  const mono = isMono(rc);
  const wb = 'wb' in look ? look.wb : (rc.wb_shift ?? null);
  const eff = look.effect ?? null;
  let sat = zeros();
  if (!mono) {
    const s = look.sat ?? rc.sat ?? zeros();
    if (!satOk(s)) throw new Error(`look ${key}: sat outside -5..5 (the web app always stores sat)`);
    sat = [...s];
  }
  const advice = {};
  const tone = { highlights: 0, shadows: 0, midtones: 0, blacks: 0, whites: 0 };
  // mono looks carry no tone block in LOOKS.BIN (tools/ep7_looks_bin.py compile_looks): keep them at 0
  if (!mono) for (const k of Object.keys(tone)) tone[k] = look.tone?.[k] ?? 0;
  if (rc.tone) advice.tone = { highlights: rc.tone.highlights ?? 0, shadows: rc.tone.shadows ?? 0, midtones: rc.tone.midtones ?? 0 };
  if (rc.contrast) advice.contrast = rc.contrast;
  if (rc.mono_filter) advice.mono_filter = { colour: rc.mono_filter.colour ?? 'none', strength: rc.mono_filter.strength ?? 1 };
  return {
    name: look.name ?? DEFAULT_NAMES[rname] ?? titleCase(rname).slice(0, 12),
    notes: look.notes ?? '',
    kind: mono ? 'mono' : 'colour',
    hue: [...(rc.hue ?? zeros())],
    light: [...(rc.light ?? zeros())],
    sat,
    grain: GRAIN_MAP[look.grain ?? 'off'] ?? look.grain,
    wb: wb ? { a_b: wb.a_b ?? 0, g_m: wb.g_m ?? 0 } : null,
    effect: eff && eff.type !== 'none' ? { type: eff.type, strength: eff.strength, ...(eff.tint ? { tint: eff.tint } : {}) } : null,
    vignette: look.vignette ?? rc.vignette ?? 0,
    art_effect: 'off',
    tone,
    advice,
  };
}

/** Library JSON -> pack file object (schema caduceus-pack/1). */
export function resolveLibrary(lib, recipes, name = 'Caduceus library') {
  const keys = [];
  const looks = [];
  for (const [k, v] of Object.entries(lib.looks ?? {})) {
    keys.push(k);
    looks.push(resolveLook(k, v, recipes));
  }
  let inc = lib.include_recipes ?? [];
  if (inc === 'all') inc = Object.keys(recipes);
  for (const r of inc) {
    if (keys.includes(r)) continue;
    keys.push(r);
    looks.push(resolveLook(r, { recipe: r }, recipes));
  }
  const slots = {};
  for (const [s, k] of Object.entries(lib.slots ?? {})) {
    const i = keys.indexOf(k);
    const l = looks[i];
    // a colour look with a tone is COLOR-only (LOOKS.BIN slot mask 1): it cannot fill a MONO slot
    const toned = l && l.kind === 'colour' && Object.values(l.tone).some((v) => v !== 0);
    if (i >= 0 && !(s.startsWith('MONO') && toned)) slots[s] = i;
  }
  // build stamp: the app updates saved library looks when this changes (src/reset.ts migratePack)
  const version = createHash('sha256').update(JSON.stringify({ looks, slots })).digest('hex').slice(0, 8);
  return { schema: 'caduceus-pack/1', name, version, looks, slots };
}

export function resolveRepoLibrary(root, file = 'bundles/library_v3.json') {
  const lib = JSON.parse(readFileSync(join(root, file), 'utf8'));
  return resolveLibrary(lib, loadRecipes(root));
}

/** tools/data/tone_hsm.json reduced to what src/tone.ts reads (the H/S/M model of tools/ep7_tone_model.py). */
export function toneModelData(root) {
  const d = JSON.parse(readFileSync(join(root, 'tools/data/tone_hsm.json'), 'utf8'));
  const keep = ['base_lut', 'gains', 'samples_k', 'curve_a_x', 'curve_b_x', 'curve_c_x', 'test_vectors'];
  return Object.fromEntries(keep.map((k) => [k, d[k]]));
}
