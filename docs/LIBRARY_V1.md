# Look library v1

19 named film looks for the E-P7 bundles/library mods: 16 colour and 3 mono. Every look uses only
controls the camera has or the bundle mods add. These are desktop-sim previews, not camera output. No
camera was connected.

- Recipes: `sim/recipes/library_v1.json` (fuji_like schema, keys `lib_*`). `patches/bundles/build.py`
  loads it through `RECIPE_FILES`.
- Library input: `bundles/library_v1.json` for `tools/ep7_library.py`. It has the names, grain, bloom,
  notes and an example slot assignment. Dry run: 19 looks, 3625 B, passes the loader rules.
- Previews: `sim/library_preview.py` writes contact sheets to `generated/library/`.

## What each control is in camera

| Control | Range used | Where it lives |
|---|---|---|
| hue[12], light[12] | −7..7 | bundle H/L (COLOR slots, or MONO slots with render_colour) |
| sat[12] | −5..5 | **the user's own per-profile saturation setting**. It is advice: the bundle does not set it. Kept within the stock ±5 |
| tone H/S/M, contrast | −4..4, −2..2 | user's stock picture settings (advice) |
| WB shift | −7..7 | bundle WB override. Looks without `wb_shift` keep the user's own fine-tune |
| grain | off/low/medium/high | bundle (v0.4). Colour gains 50/75/100, mono 110/300/600 |
| bloom | strength 1–5 | bundle effect (v0.4 Soft Focus blend, 8–35 % blurred share) |
| mono filter | stock | Monochrome Profile colour filter (user setting) |

None of the looks use halation, clarity or split toning.

## Looks

| Name | Grain / bloom | Description |
|---|---|---|
| Provia | – | Neutral, faithful colour reference: the E-P7 profile at zero. |
| Velvia | – | Saturated landscape slide film: deep skies, dense greens, crushed shadows. Now about 2× stronger than the old `velvia` recipe. |
| Astia | – | Soft slide film: gentle contrast, clean skin, slightly richer skies. |
| Cl. Chrome | – | Documentary look: muted greens and yellows, cyan skies, hard shadows. |
| Classic Neg | low | Superia-style negative: teal-green cast, punchy mids, light skies. The green sunset core of the old recipe is fixed. |
| Nostalgic | low | Amber 1970s print: warm highlights, soft tones, faded blues. |
| Reala Ace | – | Accurate, crisp modern negative: true hues, restrained greens. |
| Eterna | – | Cinema negative: flat, open shadows, quiet teal-leaning colour. |
| Bleach Byp. | low | Silver-retained cinema look: near-monochrome, harsh contrast. |
| Kodachrome64 | low | Rich reds, deep cyan-blue skies, warm and dense. Red sat and magenta are toned down, so skin no longer goes blotchy. |
| Portra 400 | low / bloom 1 | Warm pastel portrait negative: glowing skin, soft contrast. |
| Ektar 100 | – | Ultra-vivid fine-grain negative: saturated reds and blues. |
| Gold 200 | low | Golden consumer negative: sunny yellows, muted cyan skies. |
| Ektachrome | – | Clean, cool slide film: neutral skin, bright saturated blues. |
| CineStill800 | medium / bloom 3 | Tungsten cinema film: strong cool cast (WB B7 M1), lifted shadows, glowing lights. Bloom stands in for halation. |
| Pro 400H | low / bloom 1 | Airy pastel negative: minty greens, light cyan skies. |
| Acros | low (mono) | Fine-grain mono: deep blacks, smooth tones, darker reds (green filter). |
| Tri-X 400 | medium (mono) | Gritty reportage mono: punchy contrast, darker skies (yellow filter 2). |
| HP5 Plus | high (mono) | Soft, grainy mono with wide latitude and open shadows. |

Names are at most 12 characters, because the LIBRARY.BIN name field caps them there
(docs/FILM_LIBRARY.md). That is why some are shortened: "Kodachrome64", "CineStill800", "Bleach Byp.".

## Contact sheets

All looks on each test image. The first tile is the E-P7 neutral sim.

Red roof and sky (camera_t5/PB010073):
![roof](img/library/sheet_roof.jpg)

Sunset (PA211064):
![sunset](img/library/sheet_sunset.jpg)

Flower (camera_t5/PB010024):
![flower](img/library/sheet_flower.jpg)

Overview, one row per look: roof, sunset, valley (PA211089), flower:
![overview](img/library/overview.jpg)

## Caveats

- **The scales are uncalibrated.** Hue is 5.5°/step and WB is 1.5 %/step in the sim. On the camera the
  WB shift and hue twists may come out stronger or weaker. CineStill and Velvia are the most sensitive.
- **Colour grain is near-invisible in the sim.** At gains 50/75/100 it barely shows, even in the 50 %
  crop (`generated/library/detail_portrait_50pct.jpg`). GRAIN_PORT.md expects it to be weaker than mono
  grain. Mono grain is clearly visible.
- **Bloom is unverified on pixels.** It is modelled as the intended Soft Focus blend. If the combiner
  input order is reversed (BLOOM_HALATION.md risk 1), it will be much stronger.
- **Stock Olympus mono filters have no blue.** Acros therefore uses green, which only approximates
  ACROS's lighter blues.

## Library v2 (camera-tuned, test 13)

- Files:
  - recipes: `sim/recipes/library_v2.json` (keys `lib2_*`, registered in `patches/bundles/build.py`
    RECIPE_FILES);
  - library: `bundles/library_v2.json`.
- The card file `releases/test13/card/EP7MOD/LOOKS.BIN` holds the 16 colour looks with the same names. The
  slot resume still matches, and `--check` passes.
- Validation: `ep7_looks_bin.py --check` OK; `ep7_library.py --dry-run` OK.

**Camera finding: the WB fine-tune step is about 3× the sim's step.**
- Method: test-13 EXIF `WB_RBLevels` from the same lamp, comparing fine-tune 0/0 against 3/1, 2/2 and −7/1.
- Result: each A–B step moves R and B by about 4.4 % each; the sim assumed 1.5 %.
- So the v1 WB values, which were tuned in the sim, came out about 3× too strong on the camera.
- In v2 the WB values are re-scaled to camera steps. Previews use `WB_STEP` 0.044; `sim/film.py` is unchanged.
- Hue and light are still uncalibrated.

**Saturation is advice only.** The Film page does not set it, so set the profile's own saturation by hand.

| Look | v2 change (H/L in sector order Y,O,OR,R,M,V,B,BC,C,GC,G,YG) |
|---|---|
| CineStill800 | Halation stand-in: bloom 3→4; light OR/R +2; hue OR −1 (towards red); blue light −1. WB B7 G1 → **B3 G0**, so warm practicals stay warm and glow red-orange while daylight is still clearly cool. Sat advice OR +2, R +3; tone advice HL −1, SH +2. True red halation: docs/HALATION_RED.md |
| Kodachrome64 | No longer a copy of Cl. Chrome's hue. Hue: M +1, B −1, BC −2, C −1, GC +1, G/YG −1 (olive greens). Light: dense, −1..−2 everywhere. Sat advice: reds/OR +2. WB A3 → A1 |
| Velvia | Red hue −1 (towards magenta); light G/YG −1 (denser foliage) |
| Nostalgic | WB A3 → A2; orange hue +1 (amber) |
| Gold 200 | WB A4 M1 → A2 |
| Portra 400 | WB A3 G1 → A1 |
| Ektachrome | WB B2 → B1 |
| Pro 400H | WB B2 M1 → B1 |
| Classic Neg, Ektar 100 | WB +1 removed (no override, so the user's own fine-tune is kept) |
| Provia, Astia, Cl. Chrome, Reala Ace, Eterna, Bleach Byp. | unchanged |

Slots already saved with a v1 look keep the v1 values. To get v2, step the slot off the look and back on in
the Film page.

## Library v3 (12 more classic colour looks)

- Files: recipes `sim/recipes/library_v3.json` (keys `lib3_*`, each with a `source` field, registered in
  `patches/bundles/build.py` RECIPE_FILES); libraries `bundles/library_v3.json` (32 looks: v2's 17 colour, the 12
  new, then the 3 mono) and `bundles/library_v3_20.json` (≤20 fallback: best 20 colour looks, best first, no mono —
  mono uses its own presets).
- `releases/v0.15/card/EP7MOD/LOOKS.BIN` holds the **20-look** fallback until the 32-look loader is confirmed on the
  camera; then build `bundles/library_v3.json` with `tools/ep7_looks_bin.py` (2112 B, `--check` OK at MAX_LOOKS 32).
- Converting OM recipes: OM Color Profile 12-sector saturation = our sat advice, value for value (same order
  Y,O,OR,R,M,V,B,BC,C,GC,G,YG); contrast and highlight/mid/shadow are kept as advice; WB A/G fine-tune = our
  `wb_shift` a_b/g_m in camera steps. OM recipes have no per-sector hue/lightness, so small H/L moves are added here
  so the bundle itself carries part of the look (sat is advice only).

| Look | Grain / bloom | Intent | Source |
|---|---|---|---|
| Kodachrome25 | – | Dense slide: rich reds, muted cyan/green, deep shadows | GarethB, mu-43.com thread 92950 (2017) "My Kodachrome / Classic Chrome Pen-F settings". Sat verbatim; advice contrast +2, H−2 M+3 S−5. Source WB A−2 G+2 rendered too cold, bundle uses A0 G+1 |
| Portra 160 | – | Fine-grain portrait neg: natural skin, quiet greens | Isaac Mitropoulos, om-recipes.com/recipes/isaac-mitropoulos_portra-160 (5300K, A0 G0) |
| Fujicolor200 | low | Fuji C200: warm yellows, fresh greens | James Bloomer, om-recipes.com "OM-3 Fujicolor 200" (A2 G1) |
| Superia 400 | medium | Green-leaning consumer neg, cyan skies | James Bloomer, om-recipes.com "Fujicolor Superia Premium 400" (A3 G1) |
| Cibachrome | – | Glossy print: magenta-reds, deep blues | Jay, om-recipes.com "Cibachrome Print" (A1 G−1) |
| UltraMax 400 | medium | Warm punchy Kodak consumer neg | own design |
| Agfa Vista | low | Vivid magenta-leaning reds, cool punch | own design |
| CineStill50D | low / bloom 2 red | Clean daylight cinema, rich blues, faint glow | own design |
| Vision3 250D | low | Flat cinema neg, gentle teal/orange | own design |
| Vision3 500T | medium / bloom 1 red | Tungsten neg in daylight: cool teal, warm lights | own design |
| Polaroid | low / bloom 2 | Faded instant film, warm highs, cyan shadows | own design |
| Cross Proc. | medium | E-6 in C-41: hard, yellow-green highs, cyan skies | own design |

Credits: om-recipes.com is Ian Will's (mu-43 `ian_co`) collection of OM System Color Profile recipes (84 at the time,
launched Feb 2026); no AI/Claude authorship could be confirmed. Bloomer's recipes originate on
studioarchitecturecom.wordpress.com. Other Kodachrome 25 variants found but not used: Siegfried "VideoPic"
(myolympusomd.blogspot.com, PEN-F colour profiles page), BushmanOrig (same mu-43 thread, p.6). No Olympus recipes with
numbers were found for CineStill, Vision3, Agfa, Polaroid, Ektar or cross-processing, hence the own designs.

Fallback order (≤20): Classic Neg, Kodachrome25, Portra 400, Kodachrome64, Gold 200, Portra 160, Ektar 100, Velvia,
Cl. Chrome, Superia 400, UltraMax 400, CineStill800, Ektachrome, Pro 400H, Vision3 500T, Fujicolor200, Nostalgic,
Eterna, Polaroid, Cross Proc. Dropped from it: Provia (= stock), Astia, Reala Ace, Bleach Byp., Aerochrome, Cibachrome,
Agfa Vista, CineStill50D, Vision3 250D, the mono looks.
