// Regenerate src/data/library.json (and src/data/tone_hsm.json from tools/data/tone_hsm.json) from the repo's look library (bundles/library_v3.json + sim/recipes).
// Run from webapp/: `npm run gen-library`. The output is committed so the Docker build needs only webapp/.
// tests/encoder.test.ts fails if the committed file is stale.
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveRepoLibrary, toneModelData } from './library.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const pack = resolveRepoLibrary(root);
const out = join(here, '..', 'src', 'data', 'library.json');
writeFileSync(out, JSON.stringify(pack, null, 1).replace(/\[\s+([-\d,\s]+?)\s+\]/g, (_m, a) => '[' + a.replace(/\s+/g, '') + ']') + '\n');
console.log(`wrote ${out}: ${pack.looks.length} looks`);

// The preview's tone model data (tools/ep7_tone_model.py): the arrays the TS port needs, plus the test vectors.
const tone = toneModelData(root);
const outTone = join(here, '..', 'src', 'data', 'tone_hsm.json');
writeFileSync(outTone, JSON.stringify(tone) + '\n');
console.log(`wrote ${outTone}`);
