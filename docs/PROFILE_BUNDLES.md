# Profile bundles

Goal: each COLOR profile slot (COLOR1–COLOR4) is a complete look. Turning the profile selector
changes everything at once: HSL, grain, effects and WB shift.

## What already follows the profile (stock)
- 12-sector saturation (−5..+5)
- Shadows / midtones / highlights tone levels
- (Contrast, sharpness and gradation are global picture-mode settings, not per profile.)

## What a bundle adds
| Field | Type | Source feature | Hook (planned) |
|---|---|---|---|
| hue[12] | s8 −7..+7 | HSL | after COLOR builder 0x603b02d9 (v0.1 hook) |
| light[12] | s8 −7..+7 | HSL | same |
| sat_ext | flag | ±7 saturation | extended_range group (HSL_PORT.md) |
| grain | u8 off/low/med/high | colour grain | grain stage (docs/GRAIN_PORT.md, pending) |
| wb_ab, wb_gm | s8 −7..+7 + override flag | per-profile WB fine-tune | WB fine-tune read (pending trace) |
| effect | u8 id + strength | bloom / halation via Soft Focus blend | Art Filter / Art Effect stage (pending) |
| vignette | s8 −5..+5 | shading effect | shading stage (pending) |

## Firmware layout
One table in code space, 4 entries × 64 bytes (room to grow), indexed by the active COLOR profile:

```
+0   hue[12]          s8
+12  light[12]        s8
+24  grain            u8   (0 = off)
+25  wb_flags         u8   bit0 = override WB fine-tune
+26  wb_ab, wb_gm     s8, s8
+28  effect_id        u8   (0 none, 1 bloom, 2 halation)
+29  effect_strength  u8
+30  vignette         s8
+31  reserved (0)    ... to +63
```

Every feature hook does the same thing: get the active profile index, and if it's a COLOR mode (picture
mode 11), read its bundle entry, otherwise do nothing (stock behaviour).

## Phases
1. **Baked bundles (next).** Four recipes are chosen at build time (e.g. COLOR1 Classic Neg, COLOR2
   Kodachrome 64, COLOR3 Classic Chrome, COLOR4 Acros-style colour). No new menus; switch looks with the
   stock profile selector. Your existing saturation and tone settings per profile still apply on top.
2. **Editable bundles.** An in-camera editor (H/S/L tabs, grain, WB, effect) stores values per profile,
   persisted with the camera settings (PEN-F HSL patch precedent: editor_storage + settings_backup groups).

## Blocking unknown
The active COLOR profile index at each hook. The COLOR selector (0x603b0252) only checks picture
mode == 11 and reads the already-selected saturation array at request+1816; the index itself is not in
the request fields used there. Needs a trace of where the capture request is populated from the
settings banks (fishcu PEN-F: settings IDs 919–930 for saturation; E-P7 IDs 927–962 per HSL_PORT.md).

## Build input (planned)
`bundles/<name>.json`:
```json
{"COLOR1": {"recipe": "classic_neg", "wb": {"a_b": 2, "g_m": 1}},
 "COLOR2": {"recipe": "kodachrome_64"},
 "COLOR3": {"recipe": "classic_chrome", "grain": "low"},
 "COLOR4": {"recipe": "nostalgic_neg", "effect": {"type": "halation", "strength": 3}}}
```
The desktop sim renders each slot from the same file so previews and firmware stay in lockstep.
