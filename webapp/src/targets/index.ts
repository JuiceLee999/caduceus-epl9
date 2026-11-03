// Export target registry. A new camera = a new module implementing Target (./types.ts), listed here.
import { ep7 } from './ep7';
import { recipe } from './recipe';
import type { Target } from './types';

const DOCS = 'https://github.com/cakelesscoder/caduceus-ep7/blob/main/docs/';
const soon = (id: string, label: string, doc: string): Target => ({
  id, label, status: 'soon', doc: DOCS + doc, note: 'Coming soon: see the port plan.',
  supports: () => 'Not available yet',
  export: () => { throw new Error(`${label}: not available yet`); },
});

export const TARGETS: Target[] = [
  ep7,
  recipe,
  soon('em10iv-caduceus', 'Olympus E-M10 IV (Caduceus port)', 'PORT_EM10IV.md'),
  soon('canon-pf2', 'Canon (Picture Style .PF2)', 'PORT_CANON_1100D.md'),
];
export const DEFAULT_TARGET = ep7.id;
export const targetById = (id: string | null | undefined): Target =>
  TARGETS.find((t) => t.id === id && t.status === 'ready') ?? TARGETS.find((t) => t.id === DEFAULT_TARGET)!;
export type { ExportFile, Target } from './types';
