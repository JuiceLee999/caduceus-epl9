# E-P7 1.1 OSD resources (component kind 0x101)

Offline, read-only analysis of `analysis/ep7_1100/01_0101_421a0020.decoded.bin`
(SHA-256 `8606cb90…2868`) plus palettes in the main program
`00_0100_406a0020.decoded.bin` (`5dd9af16…6190`, CPU base `0x60020020`).
Both tools check these hashes and refuse other inputs.

Three evidence levels are used below:

- **Verified (structural):** every item satisfies strict checks: exact pixel
  count, header dimensions equal to descriptor dimensions, zero padding, and
  bases solved uniquely.
- **Verified (visual):** the decoded pixels show a recognisable icon or glyph.
  I inspected contact sheets of all 5514 bitmaps, all 245 symbols and font
  resources 35 and 36.
- **Inferred / guess:** consistent with the data but not proven, for example
  by a code reference or a hardware test. Don't build a patch on these
  without more work.

Offsets are decoded-file offsets. Container address = offset + `0x421a0020`.

## Layout

| Item | Offset / address | Status |
|---|---|---|
| Directory | `0x0`: 128 × 16-byte records `{u32 ptr, u32 size, 0, 0}`, ptr absolute in `0x421a0020` space; 70 used | verified (same scheme as PEN-F) |
| Resource 0: main bank | off `0x7e0`, size `0x486a00`, **runtime base `0xa3091000`** | base unique by structural search |
| Bank 0 header (runtime ptrs) | +0 symbol table `0xa34f77c4`; +4 `0xa3516e88`; +8 `0xa3516e7c` (font-name list `OlympusLanguage_<lang>tft`); +12 `0xa3516eb0`; +16 bitmap table `0xa34f0164` | +0/+16 verified by use; +4/+12 unknown |
| Bitmap table | 7576 u32 descriptor pointers (extent = up to symbol table, PEN-F rule) | extent inferred; every entry parses |
| Symbol table | 245 entries, `@A000@`–`@A0F4@` | verified |
| Resources 1–34 | language string tables, **shared runtime base `0xa407f540`** (solved separately and identically for all 34); header `{p0 = string ptr table, p1}`; 3645 strings each; English = res 8 | verified; English by content (`Color Profile 1` = string 2749) |
| Resources 35–68 | language font glyph sets; glyph streams start at res-relative `+0x7c` in all 34 | glyphs verified; runtime base `0xa3fb7540` **inferred** (see Fonts) |
| Resource 69: extra bitmap bank | off `0xcfffe0`, size `0x811600`, **runtime base `0xa3611000`** | base unique; 3477 of the decoded bitmaps live here, 2037 in bank 0 |

## Bitmap descriptors

The bitmap table points to descriptors in bank 0 or bank 69. The payload sits
just before its descriptor, with 0–3 bytes of alignment gap.

```
u16 fmt, u16 width, u16 height, u16 field6, u16 0, u16 0,
u32 encoded_size, u32 payload_ptr, [fmt 14 only: u32 extra]
```

| fmt | count | meaning |
|---|---:|---|
| 14 | 5511 | RLE bitmap; `field6` = index bits (8 or 4); 24-byte record |
| 5 | 3 (ids 1, 1707, 1708) | RLE bitmap, 20-byte record (next payload follows at +20). Why it differs from fmt 14 is unknown |
| 1 | 2061 | placeholder: w = h = size = payload = 0, `field6` = 16. These are 20-byte records, so the word at +20 belongs to the next record |
| (null ptr) | 1 | id 0 |

- **Verified (structural):** the record lengths, from where the next payload
  starts.
- **Unknown:** the meaning of `extra`, which takes the values 0, 7, 9, 10, 15
  and 255. I checked whether it is a colour key: it isn't the corner pixel,
  and for 7/255 it's usually not present in the image at all.

### RLE stream (all OSD graphics)

The 4-byte header is:

- `height-1`: byte0, plus bits 0–1 of byte1
- `width-1`: bits 4–7 of byte1, plus bits 0–5 of byte2
- `mode`: byte3

The tokens follow, little-endian, packed into 64-bit groups with
`floor(64/token_bits)` tokens per group. Unused high bits of a group must be
zero. For each token, `run = (token & run_mask) + 1` and `index = token >> run_bits`.

| mode | index bits | run bits | token | where | status |
|---:|---:|---:|---:|---|---|
| 11 | 8 | 4 | 12 (5/group) | 4976 bitmaps (8-bit palette) | verified, structural + visual |
| 10 | 4 | 4 | 8 (byte) | 538 bitmaps (4-bit palette) | verified, structural + visual |
| 1 | 2 | 2 | 4 (nibble) | 245 symbols (2-bit levels) | verified, structural + visual |
| 9 | 2 | 6 | 8 (byte) | font glyphs (2-bit levels) | verified, structural + visual |
| 3 | 8 | 2 | 10 (6/group) | PEN-F format-3 (fishcu) | **not present on E-P7** |

**All 5514 bitmap payloads and all 245 symbols decode with zero failures.**
The tool exits on any failure.

**Patch-relevant difference from the PEN-F:** E-P7 8-bit bitmaps use mode 11
(12-bit tokens), not mode 3. fishcu's PEN-F "Value" bitmap
(`value-pixels.txt`) can't be copied in byte for byte. It would have to be
re-encoded as mode 11, and must fit the target asset's allocation.

**PEN-F symbol codes don't carry over.** English string 990 is
`Delete@A032@` on the E-P7, whereas it is `Delete@A047@` on the PEN-F. E-P7
`@A047@` is a `[♥]` symbol.

## Palettes (main program)

There are 58 blocks between `0x61110a74` and `0x6111f03c`, each laid out as
`[u32 0x100][u32 self-0x408][256 × u32 AARRGGBB]`. Unused entries are
`0x01010101`; I read this as an "unpopulated" fill. All blocks are exported to
`palettes.json` and `atlas/palettes.png`. Entry 0 is always `00ffffff`
(transparent).

The blocks come in recurring groups:

- a ~128-entry UI palette (yellow ramp at 1–3, white/grey ramp at 4–6)
- a 160-entry palette (entries 128–159 repeat 0–31 at alpha `fa`/`96`)
- a 16- or 32-entry palette

Variants differ in alpha (`ff` vs `fa`), in the yellow (`e5ff00` vs
`d5ff00`) and in the grey (`fefefe` vs `cbcbcb`).

**Candidate render palettes** (the tool defaults; override with `--palette8` and `--palette4`):

- **8-bit `0x61110e7c`.** The first fully populated, opaque 128-entry block.
  Every index used by any 8-bit bitmap (0–126) is populated in it. Icons
  rendered with it look correct for the Olympus UI: white icons with black
  outline, yellow-green selected states.
- **4-bit `0x6111570c`.** A 16-entry block: transparent, black, white, orange,
  green, blue, translucent black, then repeated. Frame and grid graphics
  render plausibly with it, but **this is a guess.** Rendering the same images
  with the low 16 entries of the 8-bit palette also looks "reasonable".
- **Glyph levels → indices `[0, fg+2, fg+1, fg]`.** This is fishcu's PEN-F
  rule. It matches the E-P7 ramps: fg=4 gives white/`aaaaaa`/`555555`, fg=1
  gives the yellow ramp, fg=13 gives the orange ramp.

**Not verified:** which block the camera loads for which layer or screen. The
strings `OSDControl::setColorPalette` (`0x60a728ac`) and
`OSD3(OSD256_3) [DISP_OSD_LAYER1]` / `OSD1…LAYER2` / `OSD2…LAYER3`
(`0x601db0e4…`) show three 256-colour OSD layers with runtime palette
switching. I traced no code. **The true on-screen colours are therefore not
pinned down.** Mock colours are candidates only.

## Fonts (resources 35–68)

- Glyphs are mode-9 streams packed back to back, starting at res-relative
  `+0x7c`, preceded by 16-byte size records such as `25 00 2a 00 01 00 22 00 08 00`.
  All glyphs are 40–42 px tall cells.
- Glyph counts: res 35 = 188, 36 = 636, 37 = 627, 51 = 551, others 133–207.
- **Res 35** covers ASCII, a Latin-1 subset and Cyrillic, in ascending Unicode
  order. Glyphs 0–94 = U+0020–U+007E (verified visually). This is the only
  code-point mapping the mock uses.
- **Res 36** is Simplified Chinese in ascending Unicode order (`、。一三上下不…`).
- **Not decoded: the code-point map** for glyphs beyond ASCII. The tables the
  header points to, such as res 35 `+0x6ef8` and `+0x76f8`, are all zero in
  flash, so they're probably built at load time. Nor is it known which
  resource the camera pairs with each language.
- **Runtime base `0xa3fb7540` is inferred.** With it, the `p0` header struct
  (e.g. res 35 `{0x87, 0x1e, 0xa3fb758c, 0x93}`) points at the size records in
  every resource. It doesn't resolve uniquely by search, so the tool only
  checks that both header pointers fall inside each resource.

The bank-0 bitmaps also contain complete pre-rendered alphabets: ids
2906–2970 (orange), 4253–4310, 4490–4533, 6970–7029.

## Colour Profile / Color Creator assets

| Asset | IDs | Evidence |
|---|---|---|
| COLOR 1–4 badges (yellow and white variants) | 4344–4346, 4350–4352, 7531, 7530, 4534–4536; symbols `@A082@`–`@A084@`, `@A0A0@` | visual |
| MONO 1–4 badges | 4347–4349, 4353–4355, 7529, 7528, 4537–4538 | visual |
| Profile/mode icons: rainbow (likely Color Profile), black/white (likely Monochrome), orange/blue split, two unknown | 714–718, 1095–1099 | visual; roles guessed |
| "ALL Reset / OK Hold", "Reset", "OK Hold" guides | 7567, 3509, 3510 | visual |
| Pre-rendered labels: Highlight, Shadow, Color, Vivid, Color Filter, Level, Off, All | 4215, 4216, 4221–4226 | visual |
| Colour chips, role unknown | 4227–4233, 7552–7565 | visual |
| Highlight&Shadow tone curves and grid | 4155–4214, 4313–4330, 7574–7575 | visual |
| Strings | 2749–2751 `Color Profile 1–3`, 2755 `All colors@A017@`, 2756 `Single color@A017@`, 1270 `Color Creator`, 628 `Change Color Saturation` | verified (string table) |

**The 12-sector colour wheel, slider marks and sector labels were not found
as bitmaps.** The evidence that the wheel is drawn at runtime:

- No bitmap has more than 13 distinct indices. A hue ring needs more.
- Scans of main found no 12-hue ARGB or packed-RGB table.
- Main contains `BackGroundCtrl::drawC3dAsync` (`0x60a70fa2`),
  `BackGroundCtrl::setColorCreatorScpEvent` (`0x60a71019`) and
  `fwOpe::drawC3dAsync` (`0x60a92807`).
- fishcu found the PEN-F wheel polygon/dots drawn through `Draw_C3d_Async`.

So the wheel is almost certainly drawn by the C3D engine onto a background
layer. Its geometry and colours are unknown, and the mock draws a
**procedural approximation**.

Component 0x102 (picture resources) holds 221 JPEGs: 640/720×480 dark
gradient backgrounds, scene-guide photos and dialog art. It doesn't hold the
wheel either.

## Aspect-ratio and menu-frame graphics

- **Aspect labels:** 16–18, 471–473, 475–479, 2421–2423, 2630, 989, 1584,
  4988 (3:2), 4989 (17:9), 5866–5871.
- **Per-aspect live-view grid overlays:** ids ~5996–6143 come as one design
  in several sizes:
  - 720×480 = 3:2
  - 640×480 = 4:3
  - 720×405 = 16:9
  - 480×480 = 1:1
  - 360×480 = 3:4
  - variants at 628/708/468/348×474

  This is evidence (visual and dimensional) that the firmware uses
  **aspect-sized overlay assets**. A new aspect would need new or reused
  sized overlays, or code-drawn lines. At full width, 65:24 = 720×266 and
  21:9 = 720×309.
- **Menu graphics:**
  - selected-item cells (blue fill, yellow/orange border): 4656, 4800,
    5149–5156, 6309, 6313, 6389, 6557, 5574
  - menu tab icons: 4706–4745
  - page labels A1…J2: 4773–4793
  - OK/MENU/INFO guides: 1387–1389, 1185–1186, 5543–5545
  - scroll arrows: 4794–4798
- **Canvas:** 720×480. Many full-screen 720×480 bitmaps and JPEGs exist, with
  640×480 for 4:3 content. A few 814×558 assets (879, 1872) may be for
  another output; unknown.

These identifications are listed in the tool's `IDENTIFIED` table and in
`catalog.json → identified`.

## Tools

```bash
.venv/bin/python -I tools/osd_extract.py            # ~15 s, writes generated/osd/
.venv/bin/python -I sim/ui_mock.py sim/screens/color_profile.json \
    sim/screens/hsl_mock.json sim/screens/xpan_mock.json   # writes generated/mock/
```

`generated/osd/` contains:

- `catalog.json`: structure, bases, palettes summary, every bitmap (index,
  descriptor/payload address and component offset, encoded size, fmt, mode,
  dimensions, `extra`, indices used, payload SHA-256, status), symbols, fonts,
  identifications and failures
- `bitmaps/bNNNN.png`: **P-mode PNGs whose pixel values are the raw firmware
  indices**. The candidate palette is attached for viewing only.
  `Image.open(...).getdata()` gives the exact indices back; checked by
  round trip.
- `symbols/A0xx.png`
- `fonts/font_rNN.png` (per-resource sheets) and `fonts/r35/gNNN.png`
- `strings_en.json`
- `palettes.json`
- `atlas/`: `bitmaps_00..19.png`, `symbols.png`, `font_r35.png`,
  `palettes.png` and `identified.png`

`sim/ui_mock.py` renders a screen from a JSON element list (`bitmap`, `symbol`,
`text` with firmware glyphs and `@A0xx@` tokens or `string_id`, `rect`,
`color_wheel`, `aspect_frame`, `watermark`). Notes are printed in a strip
*below* the 720×480 canvas. To add a screen, add a JSON file to
`sim/screens/`.

Caveats for the mocks:

- Layout positions are guesses. No firmware layout tables have been decoded.
- Text scaling is host-side resampling. The camera draws native-size glyphs.

## Open questions

1. Which palette block does each layer or screen use? Trace the
   `setColorPalette` callers.
2. What do descriptor `extra` and fmt 5 vs 14 mean, and what are bank-0
   header words +4 and +12?
3. What is the font code-point map, and which font goes with which language?
   Verify the font runtime base.
4. How does C3D draw the wheel (geometry, colours, sector order)? Needed
   before mocking the wheel faithfully or patching it.
5. Bitmap-table extent: 7576 entries assumed, ending where the symbol table
   starts. Not confirmed from code.
