// Regenerate src/data/library.json from the repo's look library (bundles/library_v3.json + sim/recipes).
// Run from webapp/: `npm run gen-library`. The output is committed so the Docker build needs only webapp/.
// tests/encoder.test.ts fails if the committed file is stale.
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolveRepoLibrary } from './library.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..', '..');
const pack = resolveRepoLibrary(root);
const out = join(here, '..', 'src', 'data', 'library.json');
writeFileSync(out, JSON.stringify(pack, null, 1).replace(/\[\s+([-\d,\s]+?)\s+\]/g, (_m, a) => '[' + a.replace(/\s+/g, '') + ']') + '\n');
console.log(`wrote ${out}: ${pack.looks.length} looks`);
