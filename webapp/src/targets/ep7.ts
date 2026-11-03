// Olympus E-P7 with Caduceus: the card's EP7MOD/LOOKS.BIN (the export the app always had).
import { encodeLooksBin, validateLook } from '../format';
import type { Target } from './types';

export const ep7: Target = {
  id: 'ep7-caduceus',
  label: 'Olympus E-P7 (Caduceus)',
  status: 'ready',
  note: 'LOOKS.BIN for the Film page (Caduceus v0.19; older firmware ignores the tone).',
  supports(look) {
    const p = validateLook(look);
    return p.length ? p[0].message : true;
  },
  export: (pack) => [{ name: 'EP7MOD/LOOKS.BIN', data: encodeLooksBin(pack) }],
};
