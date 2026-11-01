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

## Camera test 13c: preset label

- Camera: INFO stepped the presets, but nothing on screen named the preset. The filter jump on INFO is the
  preset's own filter field. INFO is already consumed with a card table: the hook returns 1 and the stock
  `mov 3,d0` never runs. Without a table it is stock.
- [V] The MONO filter and shading editors draw in the Profile view: vtable 0x61189ba8, update 0x60e26ab0,
  GUI data 229, 334-B block at view+4. The view's page byte (+396) selects the page writer:
  - 0 → 0x60e26f80;
  - 1 → 0x60e27162 for MONO (modes 57/58/59/65), 0x60e27289 for COLOR;
  - 2 → 0x60e275a9 (shading, 995..997/1671);
  - 3 → 0x60e27639 (tone).
- [V] Guide slot: view+186 when (404,view) == 1, else view+260. Each slot is a 74-B label {u16 kind, -, u16 id,
  u16 style, text[33]}. The COLOR page writes "All colors[INFO]" there and the tone page writes "Hi. & Sh.[INFO]".
  The MONO pages leave the slot empty.
- **Fix:** the `mov…; call 0x60e26789,[],0` sequences in page 1 (0x60e27209, 8 B) and page 2 (0x60e275c1, 7 B)
  become `call mp_lbl1/2,[],0` (+ nop). mp_lbl writes kind 5 text `Preset: <name>` into the guide slot when:
  - the card table is valid;
  - view+400 is a MONO mode;
  - the slot name P+608+16m equals a preset name.

  It then replays `mov (84,a1),d0` and keeps d1, d2, d3, a2, a3 and sp. mp is 1020 B.
- Checks: L 10/10 (scratch harness, both sites), S 98, H 48.
- [I] Whether the MONO pages actually draw the guide slot, and whether this view is the screen the user sees.
  The colour editor's camera-proven label lives in a different view (0x60dec790).

## v0.15: mono film-sim picker (emulator-verified, not camera-tested)

Modelled on the colour Film page: a **Film page** inside the stock MONO filter and shading editors.

| Key in a MONO1–4 filter / shading editor | Stock | v0.15 (card table loaded) |
|---|---|---|
| INFO (+44) | closes | toggle normal ↔ Film page (INFO is the only extra key proven to reach editors, 12d; MENU/PLAYBACK hooked in the editor never worked on the colour camera test, so +36 stays stock) |
| MENU / PLAYBACK | stock | stock |
| Up / Left (+12 / +20), Down / Right (+16 / +24) | filter: Left/Right = filter, Up/Down = strength (only if setting 130 ≠ 0); shading: Up/Down = shading, Left/Right nothing | **Film page only:** next / previous preset (Up and Left send 0x9004 in stock, so they are "next"). Stock page: unchanged |
| Dials, touch drag | reach +12..+24 through the helpers 0x60e20bd5/bfd/c25/c4d [V] | follow the arrows. The filter rear dial (+28) is gated on setting 130 in stock, so on the Film page `mp_d1_f` jumps to the shading editor's dial routine 0x60e22df0 (same delta, Up/Down helpers, no gate) |
| Init (+4) | build the parent | Film page off, then stock |

[V] The editor router 0x60e20cdc routes only 0x900c / INFO / 0x9015 / 0x9012 to fixed slots; every other event,
including MENU, goes to parent+72 = record +36, where the stock MONO handler checks 0x900e itself. The router and
init are shared with the colour editor, whose +36 / +12 / +16 hooks are camera-proven (12e/13).

**Guide label** (mp_lbl1/2, the camera-proven 13c slot):
- Film page: `Film: Acros`, `Film: Acros*`, or `Film: Custom` (slot name is not a preset).
- Stock page: `Acros[INFO]` / `Acros*[INFO]`, or `Film[INFO]` (no preset), so the key is discoverable.
- At most 17 characters (build check ≤ 20; 13c showed 20).
- `*` = any of the preset's 8 settings now reads differently. The check runs on every view update, through
  facade GetValue (+8) on the MONO ids, compares the low byte only (so sign- and zero-extended values both
  work), and a failed read adds no `*`.
- ed_get / ex_get on the same facade word only take COLOR sector ids (927–962, 1655–1666), so MONO ids read
  stock storage [V]. A hand edit to filter, strength, toning, grain, shading or Hi/Sh shows the `*` on the next
  redraw. Contrast and sharpness are not compared.

**Redraw:** after a step or a page toggle, every child is refreshed, then the editor's own first setting
(filter / shading) is re-written with its current value (GetValue → SetValue). This is the colour editor's
ed_poke, which is camera-proven for its page step. For the toggle it is the only trigger: [I] strong.

**Persistence and resume:** the slot name is written into P+608+16m (`EP7N`) with dirty set, and the editor's
half-press save writes BUNDLES.BIN (camera-proven). After a power cycle, the first take-over rebuilds the
positions from the names (`mp_resume`), and the label matches by name directly. The page byte P+1012 is trusted
only with `EP7M` at P+1008, and it is cleared by `mp_resume` and by every editor init.

**Presets (10, slowest film first):**

| Preset | filter / strength | toning | grain | shading | HL / SH / MID |
|---|---|---|---|---|---|
| Pan F 50 | yellow 1 | – | off | 0 | +1 / −3 / +1 |
| Acros | green 1 | – | low | 0 | −1 / −2 / 0 |
| T-Max 100 | none | – | off | 0 | −1 / 0 / +1 |
| SFX 200 | red 3 | – | medium | −1 | +2 / −2 / 0 |
| Tri-X 400 | yellow 2 | – | medium | 0 | −1 / −3 / 0 |
| HP5 Plus | none | – | high | 0 | −2 / +1 / 0 |
| Delta 3200 | none | – | high | −2 | −2 / +2 / +1 |
| Sepia Print | none | sepia | low | −2 | −1 / +1 / 0 |
| Selenium | none | purple [I] | low | −1 | 0 / −2 / 0 |
| Cyanotype | yellow 1 | blue | off | 0 | 0 / −1 / 0 |

"Red Contrast" was replaced by SFX 200. A slot saved as "Red Contrast" shows `Film: Custom` until the next pick.

**Code:**
- Part A, 932 B at 0x601e283c: entries, step, page, init and rear dial; 10 stock fallbacks through 8-byte
  trampolines, which the build checks.
- Part B, 800 B at 0x601e173c: the label, keys, ids and presets. It sits in the dead EVF step-11 R/G/B and
  step-10 R tables. Their only references are the step-table words 0x601e3d30/34/38 and 0x601e3d20, which the
  build checks.
- 56 record words (8 records × +4/+12/+16/+20/+24/+44, + 4 filter +28) and 2 label sites.
- Heap: P+1004..1007 pos, P+1008 `EP7M`, P+1012 page. This is below film +1016 and above the editor's 680..703.

**Verified** (`patches/mono_presets/verify.py`):
- S 530: stock paths on every hooked word, +36 stays stock;
- I 24: init;
- H 192: steps both ways, wraps, stale position, resume, no names section;
- K 48: INFO page toggle;
- L 408: label texts, `*` per field, byte vs s32 values, getter failure, no `EP7M`, non-MONO mode;
- D 28: rear dial, with an end-to-end run through the real 0x60e22df0 and helpers.
- No mutations (user request).

**Routes and limits:**
- Only the filter and shading screens are wheel editors. The editor descriptor table has no record for
  toning, grain or Hi/Sh, so the picker lives in these two screens. Whichever route opens them (Picture Mode
  → MONO → INFO / →, or SCP), it is the same record.
- Picture-mode slot m comes from the editor key. The label uses the view's picture mode (view+400).
- With MONO slots used as colour bundle slots (8-slot work), a preset still writes only the stock mono
  settings and the slot name. It overwrites a bundle name on that slot.

**Colour Film page as host?** No. The Color Profile editor opens only in COLOR modes (Up re-reads setting 111
∈ {54, 55, 56, 64}), and its children are the COLOR saturation ids, so a MONO slot cannot reach it. The mono
picker therefore stays in the MONO editors. Note for the 8-slot agent: this needs no change in film_menu_v2.
