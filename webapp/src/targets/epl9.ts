// Olympus PEN E-PL9 on stock firmware: one Markdown card per look with the closest in-camera settings (../epl9.ts).
// A Caduceus firmware port for the E-PL9 is being researched (docs/PORT_EPL9.md); until then this is the card export.
import { epl9Card } from '../epl9';
import type { Target } from './types';

const fileName = (name: string) => (name.replace(/[^\w.-]+/g, '-').replace(/^-+|-+$/g, '') || 'look') + '-EPL9.md';

export const epl9: Target = {
  id: 'epl9-stock',
  label: 'Olympus PEN E-PL9 (stock settings)',
  status: 'ready',
  doc: 'https://github.com/JuiceLee999/caduceus-epl9/blob/main/docs/PORT_EPL9.md',
  note: 'A card per look with the closest Picture Mode, tone and WB settings on a stock E-PL9.',
  supports: () => true,
  export(pack) {
    const used = new Set<string>();
    return pack.looks.map((l) => {
      let n = fileName(l.name);
      for (let k = 2; used.has(n.toLowerCase()); k++) n = fileName(`${l.name}-${k}`);
      used.add(n.toLowerCase());
      return { name: n, data: epl9Card(l), type: 'text/markdown' };
    });
  },
};
