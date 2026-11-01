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

Portrait (testdata/camera_t5/PB010074):
![portrait](img/library/sheet_portrait.jpg)

Red roof and sky (camera_t5/PB010073):
![roof](img/library/sheet_roof.jpg)

Sunset (PA211064):
![sunset](img/library/sheet_sunset.jpg)

Flower (camera_t5/PB010024):
![flower](img/library/sheet_flower.jpg)

Overview, one row per look: portrait, roof, sunset, valley (PA211089), flower:
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
