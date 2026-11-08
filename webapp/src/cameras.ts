// What the editor offers on each camera. The pack keeps one format; this only shapes the controls and preview, and
// out-of-range values are kept until the user moves that control. A new camera = one more entry here plus an export target.
import { OM3, OM3_ARTS } from './om3';
import type { Look } from './pack';

export type Cam = 'ep7' | 'om3' | 'epl9';
export interface CameraProfile {
  short: string;
  hl: number; sat: number; wb: number;     // hue and light; saturation; WB shift
  mono: boolean; tints: boolean; lensCorrection: boolean;
  arts: readonly Look['art_effect'][];
  settings: boolean;                       // Contrast, Sharpness and Shading are saved in the look
  lookNr: boolean;                         // NR is saved in the look (OM-3); E-P7 v0.27: Grain and NR belong to each COLOR profile
}
export const CAMERAS: Record<Cam, CameraProfile> = {
  ep7: { short: 'E-P7', hl: 7, sat: 5, wb: 7, mono: true, tints: true, lensCorrection: true, arts: ['off', 'star_light', 'pin_hole'], settings: false, lookNr: false },
  // E-PL9 on stock firmware: the full editor stays (the preview and RapidRAW presets use every value); the export
  // translates each look to the camera's own settings (epl9.ts).
  epl9: { short: 'E-PL9', hl: 7, sat: 5, wb: 7, mono: true, tints: true, lensCorrection: false, arts: ['off', 'pin_hole'], settings: false, lookNr: false },
  om3: { short: 'OM-3', hl: OM3.hl, sat: OM3.sat, wb: OM3.wb, mono: false, tints: false, lensCorrection: false, arts: OM3_ARTS, settings: true, lookNr: true },
};
