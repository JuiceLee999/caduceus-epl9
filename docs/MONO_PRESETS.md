# Mono film presets on the stock Mono Profile editors (E-P7 1.1)

Built into test13; camera test 13b found two faults, fixed in place (section "Camera test 13b" below). Replaces the MONO-colour / MONO-wheel plan for this
release: MONO1–4 keep OM's mono rendering and editors, and nothing on the capture path changes.
[V] = read from the decoded main. [I] = inference.

## What it does

In the stock MONO1–4 **colour-filter** editor (keys 0x13b6/0x13b7/0x13b8/0x140d, children filter + strength) and
**shading** editor (keys 0x13b9/0x13ba/0x13bb/0x140e), INFO steps that profile through 6 presets. Each step:
- sets 8 stock settings of that MONO profile through the facade SetValue (vtable +0, the same call a stock edit
  makes): filter, filter strength, toning, grain, shading, highlights, shadows, midtones;
- writes the preset name into the MONO slot name (P+544+16(4+m)), which Picture Mode, LC and SCP show through
  the test-8 name hooks, and sets dirty, so the editor's half-press save writes BUNDLES.BIN;
- refreshes the editor's children and stays open.

The choice persists as the slot name. The heap position (P+1004+m, valid with `EP7M` at P+1008) is rebuilt from
the saved name on first use, so the next INFO after a power cycle goes on from the saved preset. No card table:
stock, INFO closes the editor as before. Stock INFO in these editors is `mov 3,d0; retf` (close; MENU also
closes), so nothing else is lost.

| Preset | filter / strength | toning | grain | shading | HL / SH / MID |
|---|---|---|---|---|---|
| Acros | green 1 | – | low | 0 | −1 / −2 / 0 |
| Tri-X 400 | yellow 2 | – | medium | 0 | −1 / −3 / 0 |
| HP5 Plus | none | – | high | 0 | −2 / +1 / 0 |
| Red Contrast | red 2 | – | low | −1 | +1 / −2 / 0 |
| Sepia Print | none | sepia | low | −2 | −1 / +1 / 0 |
| Cyanotype | yellow 1 | blue | off | 0 | 0 / −1 / 0 |

The first three come from the library v2 mono looks (`bundles/library_v2.json` + `sim/recipes/library_v2.json`).
Contrast and sharpness (the ±2 settings 977/974 …) are left as the user set them.

## Settings map

From the picture-parameter builder 0x602b7b71 MONO branches (public modes 57/58/59/65) and the validator lists:

| Field | MONO1 | MONO2 | MONO3 | MONO4 | List | Meaning |
|---|---|---|---|---|---|---|
| filter | 987 | 988 | 989 | 1680 | 0,1,2,3,6,7,8,4,5 | [V] from the filter matrices 0x60531bc0: 1 Y, 2 O, 3 R, 4 G, 5 YG, 6 Mg, 7 B, 8 Cy |
| strength | 991 | 992 | 993 | 1681 | 0..3 | packer: params = 0x80 \| (s&3)<<4 \| filter; matrices exist for s 1..3 [V]; UI value = s [I] |
| toning | 984 | 985 | 986 | 1679 | 0..4 | N, sepia, blue, purple, green [I] |
| grain | 981 | 982 | 983 | 1678 | 0..3 | off/low/medium/high |
| shading | 995 | 996 | 997 | 1671 | −5..5 | [I] negative = darker corners |
| tone | 998 / 1000 / 999 | 1001 / 1003 / 1002 | 1004 / 1006 / 1005 | 1675 / 1677 / 1676 | −7..7 | highlights / shadows / midtones (MONO1 [V camera 13b], others by analogy) |

`build.py` checks every preset value against each setting's validator list.

## Code and hooks

- `patches/mono_presets/mp.s.in` at 0x601e293c (736 B, dead EVF gamma step-5 tables).
- Hooks: the 8 record +44 words (CODE_SPACE_MAP). The build checks the stock words, the record keys, the editor
  children, and that 0x60e22d8b has no other reference.
- Stores go only to the heap and the stack. No mul/div or setlb.
- Verify: `patches/mono_presets/verify.py --spec <spec>`. Part S covers stock paths on all 8 records (no table,
  other keys, foreign key, child count, gesture, null parent). Part H covers presets on all 8 records: resume,
  wrap, stale position, no names section, SetValue log, name, dirty, EP7E/EP7M, child refresh, registers.

## Unknowns (camera)

- Whether INFO reaches these editors' record +44 (it does in the COLOR editor), and whether the open Mono
  screen is the filter or the shading editor. Both are hooked.
- The [I] meanings above. Check after one INFO: the filter wheel shows the preset's filter, and the
  Highlight & Shadow screen shows the HL/SH values in the right places.
- Whether the screen redraws after the SetValue calls. The child refresh is stock, as in the colour editor's INFO
  page step.

## Camera test 13b

- **Shots:** PB021374–1375 are MONO1, with the slot named "Red Contrast". Makernotes (CameraSettings, parsed without
  exiftool):
  - MonochromeProfileSettings filter = 3 (red), strength 2;
  - grain Low; vignetting −1; toning "normal" (none);
  - ToneLevel Highlights +1, Shadows 0, Midtones −2.
  - The image shows it too: on the red wood the red filter renders light grey.
- **So SetValue worked, and on the right profile.** Filter, strength, toning, grain and shading landed exactly.
- **Fault 1: shadows/midtones swapped.** We wrote shadows −2 to 999, and it came out as Midtones. So 999 = midtones and
  1000 = shadows. Fixed in IDS for all four profiles; MONO2–4 are by analogy.
- **Fault 2: "no visible change".** The open Mono screen did not redraw after the preset.
  - After the SetValue calls, mp refreshed the children but sent no further setting change. The colour editor's
    camera-verified page step does both: refresh, then `ed_poke`.
  - Fix: after the refresh, mp writes the editor's own first child (filter, or shading) once more with its preset
    value (`mp_set`), so the stock listeners rebuild the screen from the refreshed children.
- mp grew to 764 B and now starts at 0x601e283c: the dead EVF step-6 B table, then the step-5 tables. Only refs are the
  step-table words, build-checked.
- **Verified:** `patches/mono_presets/verify.py` S 98, H 48. H now expects 9 SetValue calls: the 8 fields, then field 0
  (filter editors) or field 4 (shading editors).
