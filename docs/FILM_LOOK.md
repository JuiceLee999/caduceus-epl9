# Film look beyond HSL: halation, bloom, grain, curves and density, and what the E-P7 can do

Status: research notes plus **desktop** implementations (`sim/effects.py`, wired into
`sim/film.py`). Nothing has been tested on a camera. Companion to
[`FILM_SIMS.md`](FILM_SIMS.md), which covers per-sim hue, saturation and tone; this
document doesn't repeat that material.

Evidence labels: **[Fuji]** manufacturer docs · **[manual]** an official manual ·
**[community]** Fuji X Weekly, forums and reviews · **[physics]** textbook/film-datasheet
knowledge (no single URL) · **[ours]** our own estimate or measurement · **[fw]** this repo's
firmware analysis.

---

## 0. Short answer

* **Standard Fuji film sims contain no halation, bloom or diffusion.** No Fuji document
  mentions any for PROVIA … REALA ACE, and you can't turn one on in X/GFX menus [Fuji
  manuals, §1]. The spatial parts of a Fuji JPEG are **Grain Effect** (band-limited noise),
  **Clarity** (mid-frequency local contrast), **Smooth Skin** (skin-area smoothing),
  **Sharpness** and **NR**. Everything else is per-pixel: a 3D LUT and tone curve, plus CCE/FX
  Blue, which is saturation-dependent darkening.
* **Halation appears only on the X-Half (2025)**, as one of three new "film filters"
  (Light Leak, **Halation**, Expired Film). X-Half firmware 2.00 (Sept 2026) added
  **Soft Glow**, a highlight-only diffusion imitation [Fuji, community; §1.3]. No X-series
  or GFX body offers them; the X-E5/X-M5/X100VI menus show only the classic Advanced
  Filters.
* **A GFX image with visible glow or halation was therefore almost certainly made by one of
  the following:**
  1. a **diffusion filter**. Black Pro-Mist and CineBloom are the most common in Fuji
     recipe circles, and FXW stacks 5–20 % CineBloom.
  2. **post-processing**: Dehancer, FilmConvert, Lightroom/Capture One glow, or DaVinci
     halation.
  3. **less likely, the lens**. The GF 80/1.7 is "fairly sharp wide open" in reviews, and
     its residual spherical aberration gives a mild glow, not red halos. Veiling flare from a
     dirty or uncoated filter is another lens-side cause.

  A **red-orange** fringe specifically points to post-processing or halation software,
  because diffusion filters and lenses give a neutral, white glow. A neutral glow that also
  lifts the shadows near lights points to a mist filter. **Negative Clarity also gives a
  mild glow:** FXW likens Clarity −1/−2 to a 1/8 Pro-Mist, and −5 to a 1/2 Pro-Mist
  [community].
* **The E-P7 can plausibly do most of this in camera.** Per-pixel effects (film curve,
  subtractive saturation, CCE-like density, crossover, vignette, mono grain) map onto
  existing ISP units. **Halation and bloom need the Art Filter blur/blend path** (Soft
  Focus / Pale&Light / Diorama), re-parameterised with a highlight key and a tint. That path
  exists in hardware, but we haven't located its parameters in firmware yet. **Grain size,
  Clarity-style local contrast at arbitrary radius, gate weave and per-layer grain are not
  available**; Dramatic Tone is the only local-contrast engine.

---

## 1. Fujifilm in-camera controls by generation

The per-sim colour and tone behaviour, DR, DR-P, H/S tone, Color, Clarity, Grain, CCE, FX
Blue, WB shift and Monochromatic Color are described in `FILM_SIMS.md` §1. This section
adds generation coverage and the spatial/per-pixel classification.

### 1.1 Which body has what

Source for the 2019+ rows: each body's online manual, at
`fujifilm-dsc.com/en/manual/<model>/menu_shooting/image_quality_setting/` [manual].
"—" means not verified.

| Generation / body | Sims (newest added) | Grain | CCE / FX Blue | Clarity | Tone | Skin | Other |
|---|---|---|---|---|---|---|---|
| X-Trans I–II (X100, X-Pro1, X-T1, X-E2) | PROVIA…PRO Neg, Classic Chrome (X30/X100T 2014) | – | – | – | H/S ±2 | – | – |
| X-Trans III (X-Pro2, X-T2, X100F) | + ACROS (2016) | Weak/Strong | – | – | H/S −2…+4 | – | Mono WC tint from X-T3 |
| GFX 50S / 50R (2017–18) | + CCE debut (50S) | Weak/Strong | CCE | – | H/S | Smooth Skin later, via X RAW Studio update ([FujiRumors](https://www.fujirumors.com/fujifilm-releases-kaizen-firmware-updates-for-fujifilm-gfx100-gfx50r-and-gfx50s/)) | – |
| X-Trans IV (X-T3 2018; X-Pro3/X100V 2019–20; X-T4, X-S10) | + ETERNA (X-H1), Classic Neg (X-Pro3), Eterna Bleach Bypass (X-T4) | **Roughness × Size** (X-Pro3 on) | CCE (X-T3) / **FX Blue (X-Pro3)** | **Clarity (X-Pro3)** | Tone-curve screen, half steps | **none** on X-T4/X-S10 | Mono WC+MG, DR-P |
| GFX100 (2019) / 100S / 50S II | + Nostalgic Neg (GFX100S, 2021) | R×S | both | 100S yes; GFX100: not listed | H/S | **Smooth Skin debuts on GFX100** ([manual](https://www.fujifilm.com/en/manual/gfx100/menu_shooting/image_quality_setting/index.html#smooth_skin_effect)) | – |
| X-Trans V stacked (X-H2S 2022) | Nostalgic Neg on X | R×S | both | yes | tone curve | **none** | – |
| X-Trans V 40 MP (X-H2, X-T5, X100VI 2024, X-E5 2025) | + **REALA ACE** (GFX100 II 2023 → X 2024) | R×S | both | yes | tone curve | Smooth Skin | X-E5: **FS dial** (FS1–3 + "FS RECIPE"); the X100VI has **no** sim dial |
| X-T50 (2024) | 20 sims | R×S | both | yes | tone curve | Smooth Skin | FS dial: FS1/2/3/ACROS |
| X-M5 (2024) | 20 sims | R×S | both | yes | tone curve | **Portrait Enhancer** (Weak/Med/Strong) | FS dial positions can also hold Advanced Filters |
| GFX100 II (2023), GFX100S II (2024) | REALA ACE | R×S | both | yes | tone curve | Smooth Skin | (manual 404 for GFX100 II; assumed same as GFX100S) |
| GFX100RF (2025) | 20 sims incl. REALA ACE | R×S | both | yes | tone curve | – | aspect dial with 9 ratios incl. 3:4 and 17:6 ([Newsshooter](https://www.newsshooter.com/2025/03/20/fujifilm-gfx100rf/)) |
| GFX ETERNA 55 (Sept 2025, cine) | 20 sims, F-Log2/F-Log2 C | – | – | – | – | – | [whitepaper](https://dl.fujifilm-x.com/support/lut/GFX_ETERNA_WhitePaper_260206_v101.pdf) |
| X-T30 III (Nov 2025) | REALA ACE + 19 others | – | – | – | – | – | sim dial with 3 custom positions ([Engadget](https://www.engadget.com/cameras/fujifilms-x-t30-iii-adds-a-film-simulation-dial-and-6k-video-072148245.html)) |
| **X-Half (X-HF1, May 2025)** | 13 sims (PROVIA, Velvia, ASTIA, Classic Chrome, REALA ACE, Classic Neg, Nostalgic Neg, ETERNA, ACROS ×4, SEPIA) | Grain | not documented | not documented | not documented | – | **26 filters incl. Light Leak, Halation, Expired Film**; Film Camera Mode; 2-in-1 ([Fuji](https://www.fujifilm.com/cy/en/news/Fujifilm_Launches_Compact_Digital_Camera_X-half)) |

No 2026 X or GFX body has been officially announced as of Nov 2026. The X-T6 and a rumoured
new "deep colour" sim are unconfirmed
([FujiRumors](https://www.fujirumors.com/fujifilm-x-t6-everything-we-know-so-far/)). Fuji
did release new F-Log2 / F-Log2 C LUTs in Nov 2025
([PetaPixel](https://petapixel.com/2025/11/18/fujifilms-new-f-log2-and-f-log2c-film-simulation-luts-look-fantastic)).

### 1.2 Each control: what it does, spatial or per-pixel, and reverse engineering

| Control | What it does technically | Spatial? | Best public RE / our model |
|---|---|---|---|
| Film simulation | 3D colour LUT plus tone curve, per sim | per-pixel | Fuji's F-Log2 LUTs (measured in `FILM_SIMS.md` §2) |
| Grain Effect | "Controlled random noise" with Roughness (amplitude, Off/Weak/Strong) and Size (Small/Large) ([Fuji](https://fujifilm-x.com/en-gb/learning-centre/color-chrome-and-film-grain-effects)). Some claim it is tuned per sim, scales with ISO and is applied before sharpening ([Fstoppers summary](https://fstoppers.com/education/fujifilms-grain-effect-more-useful-think-heres-how-actually-use-it-903376)); unverified. ACROS has its own ISO-dependent grain ([Fuji](https://www.fujifilm-x.com/lv-lv/stories/the-newest-film-simulation-acros/)) | **spatial** (Large = low-pass noise) | **No published spectrum analysis exists.** [ours] Small ≈ 1 px correlation and Large ≈ 2–2.5 px at full res; luminance grain with a little chroma. Strong is roughly twice Weak's amplitude, and the grain is weakest in highlights. `effects.FUJI_GRAIN` holds these estimates; measure them from flat-field Fuji JPEGs (§5) |
| Color Chrome Effect | Adds depth to saturated reds, yellows and greens by darkening them, so they keep gradation instead of clipping ([pixls.us analysis](https://discuss.pixls.us/t/what-is-color-chrome-effect-and-how-to-achieve-it/18760)) | per-pixel (saturation-keyed) | **No quantitative measurements are published** (none from Fitzgerald, FXW or DPReview). Our model, `color_chrome()`: up to −30 % linear (≈ −0.5 EV) at Strong on fully saturated, bright colours [ours] |
| Color Chrome FX Blue | Same idea for blues only; works like a polariser ([FXW](https://fujixweekly.com/2020/06/30/fujifilm-x100v-new-feature-color-chrome-effect-blue/)) | per-pixel | same model, with a hue bump at 225° |
| Clarity | Mid-frequency local contrast, −5…+5. A non-zero value causes a "Storing" delay; it is disabled with HEIF and in CL/CH bursts; AUTO sets it itself (X-M5 manual). FXW: negative Clarity looks like a weak Pro-Mist ([FXW 2026](https://fujixweekly.com/2026/04/05/what-does-clarity-actually-do/)) | **spatial**, large radius (it is slow, so it is probably a CPU-side or multi-pass job) | Our model: unsharp mask on luminance, sigma ≈ 0.5–1 % of width, amount ±0.1/step, with a midtone weight |
| DR100/200/400, DR-P | Underexpose 1–2 EV, then lift with a gentler curve | per-pixel, plus exposure | `FILM_SIMS.md` §1.2–1.3 |
| Highlight/Shadow tone | Shoulder and toe of the tone curve | per-pixel | `film_curve()` shoulder/toe |
| Smooth Skin / Portrait Enhancer | Smooths skin; the manual says only "smooth complexions", Weak/Strong. Whether it uses face detection is undocumented | **spatial** (edge-preserving smoothing inside a skin-hue mask) | none public |
| WB + R/B shift | Channel gains | per-pixel | `FILM_SIMS.md` §1.10 |
| Sharpness / NR | Unsharp mask / denoise | spatial | – |
| **X-Half Halation** | Red-orange glow around highlights | **spatial** | Nobody has reverse-engineered it publicly; it looks like a threshold + red blur + add |
| X-Half Light Leak | A random warm overlay that "never repeats" | spatial overlay (no convolution needed: a procedural gradient) | – |
| X-Half Expired Film | Green, Red or Neutral colour casts and fading | per-pixel (probably a LUT) | – |
| X-Half Soft Glow (fw 2.00) | Diffusion imitation, highlights only; can't be combined with sims ([FXW](https://fujixweekly.com/2026/10/02/fujifilm-x-half-firmware-update-adds-new-features/)) | spatial | our `bloom(threshold>0)` |
| Advanced Filters (X/GFX) | Toy Camera, Miniature, Pop Color, High-Key, Low-Key, Dynamic Tone, Soft Focus, Partial Color ([FXW 2026](https://fujixweekly.com/2026/06/03/fujifilms-hidden-feature-advanced-filters-plus-what-fujifilm-should-do-with-it-on-future-cameras/)) | mixed | Same family as Olympus Art Filters. Fuji's Soft Focus is a blurred-copy blend, the only glow on X/GFX |

---

## 2. Physics of film looks, with typical numbers

### 2.1 Halation [physics]
* **Mechanism.** Light passes through the emulsion stack and the base, reflects off the
  back of the base (base/air interface) and returns to re-expose the emulsion around the
  original point. The red-sensitive layer sits at the bottom of a colour tripack, nearest
  the base, so it receives most of the returned light; the green layer gets some and the
  blue layer almost none. That is why the halo is **red to orange**.
* **What normally stops it.** Normal film suppresses halation with an **anti-halation
  layer**: rem-jet (a carbon-black backing) on Kodak motion-picture stocks, and grey/dyed
  base or an AH underlayer on still films. **CineStill 800T/50D are Kodak Vision3 stocks
  with the rem-jet removed**, so their halation is extreme.
* **Halo size.** The halo radius is about 2·t·tan θ, where t is the base thickness
  (triacetate ≈ 0.12–0.14 mm, ESTAR/polyester ≈ 0.1 mm) and θ is the scatter angle. That
  gives a halo **≈ 0.2–0.6 mm** on a 36 mm frame, i.e. **0.5–1.5 % of image width**.
  Medium format gives the same halo in mm, so a smaller percentage. The profile is a ring or
  annulus on top of a long scatter tail, not a pure Gaussian.
* **When you see it.** Halation is proportional to exposure, so you only see it around
  sources several stops over mid-grey (lamps, sun glints, specular water) or along
  bright/dark edges.
* **Implementation.** Add it in **exposure (scene-linear) space before the tone curve**.
  The film's shoulder then compresses the core and leaves the faint skirt visible.

### 2.2 Bloom / diffusion
* **Sources.** (a) **Diffusion filters**: Pro-Mist / Black Pro-Mist, Glimmerglass,
  CineBloom. Particles scatter a fixed fraction of *all* light into a wide PSF. That lifts
  shadows next to bright areas, lowers contrast and gives a neutral glow (Black Pro-Mist
  less so). Strength 1/8 … 2 roughly maps to 2–40 % scattered [ours, by eye]. (b) **Lens**:
  residual spherical aberration wide open gives a soft core glow that disappears when
  stopped down; veiling glare. (c) **Film/print**: emulsion turbidity, and printing-lens
  flare in optical printing.
* **Model.** It conserves energy: `out = (1−s)·img + s·(PSF ⊛ img)` in linear light. The
  PSF has a long tail, which we approximate with a sum of Gaussians at σ, 2σ and 4σ.

### 2.3 Grain
* **Structure.** Silver halide crystals develop into silver grains (B&W) or dye clouds
  (colour). Grain is quantified as RMS granularity σ_D at density 1.0 (Kodak datasheets),
  or by the print-grain index (Portra 400 ≈ 35, Vision3 500T higher).
* **Size.** It rises with speed: about 0.2–2 µm crystals, but dye clouds of 5–15 µm, so
  the *visible* clumps in a 36 mm scan are ~10–30 µm. That is about **1–3 px of a 20 MP
  4/3 or APS-C sensor** (≈ 3.3–3.9 µm pixels). Fuji "Large" ≈ 2 px matches 400–800 ISO
  film.
* **Luminance dependence.** On the negative, granularity peaks at mid densities. After
  printing, grain is **most visible in midtones and light shadows, and suppressed in
  highlights** (a dense negative maps to print highlights compressed by the shoulder) and in
  deep blacks (paper D-max). Model it as a bump peaking at display luma ≈ 0.4–0.5, with
  ~30–40 % of peak amplitude at white.
* **Colour vs mono.** Each dye layer has independent grain, so colour film has
  **chromatic grain**, but the scan or print is dominated by luminance-correlated
  structure. A chroma-noise fraction of ≈ 0.2–0.4 looks right. The blue-sensitive top layer
  in fast films is usually the coarsest (layer size factor ~1.3–1.5).
* **Scale.** Grain is defined in **sensor/film pixels**. A preview must average it (std
  ∝ size × scale factor) rather than draw 1-px noise at preview resolution, which looks 5×
  too coarse. `grain_v2` does this and was checked against a 20 MP render: preview std
  within 10 % of the downsampled full-res result (§3).

### 2.4 Tone curve: toe, shoulder, roll-off
* **Characteristic curve.** Negative film's density/log-exposure curve is long and nearly
  straight (γ ≈ 0.6), with a soft toe. The **print** (γ ≈ 2.5–3) provides the S-shape. The
  combined system gives display γ ≈ 1.5–1.7 at mid-grey, a **toe** that compresses
  shadows, and a very gradual **shoulder** that keeps ~3–5 stops above mid-grey. Highlights
  approach white asymptotically instead of clipping.
* **Per-layer curves.** Each layer has its own curve, so applying the curve per channel
  desaturates highlights toward white and shifts the hue of bright saturated colours
  (orange skies go yellow). That is the "film roll-off" digital clipping lacks.
* **Our function.** `film_curve()` works in log space:
  `d = smax(smin(slope·t, W, shoulder), B, toe)`. W is solved so that sensor clip lands
  exactly on white. The defaults fit the E-P7 base curve to within 0.03 [ours].

### 2.5 Crossover / split toning
* **Crossover.** When the three layers' curves differ in slope or offset, neutrals get
  tinted differently in shadows and highlights. Examples:
  * cross-processing (E-6 in C-41), which is extreme
  * expired film (one layer loses speed)
  * Fuji Classic Neg's green-cyan shadows with warm highlights, and Nostalgic Neg's amber
    highlights (`FILM_SIMS.md` §2.4)
* **Implementation.** Per-channel `black`/`white`/`slope` in `film_curve()`.
  * Typical size: 0.5–2 % (display linear) difference in channel floors, and 1–5 % in
    channel whites.
  * A slope difference of 0.05–0.1 between channels already reads as a cross-process tint.

### 2.6 Colour density / subtractive saturation
* **Why film darkens saturated colours.** Film forms colour *subtractively*: to make a
  saturated red, the print adds cyan dye density (removing green and blue) while red
  transmission stays at most constant. Saturated film colours are therefore *darker* than
  the same hue at low saturation.
* **Why digital gets this wrong.** Digital chroma gain in YCbCr does the opposite: it
  pushes the dominant channel *up* toward clipping. That is why "+saturation" looks
  digital, and why Fuji CCE exists.
* **Model.** Keep the dominant channel and raise the others' density:
  `rgb' = max·(rgb/max)^(1+a)`, with a ≈ 0.1–0.4. Optionally add extra darkening by
  saturation.

### 2.7 Vignetting
* **Causes.** Optical cos⁴ falloff plus mechanical vignetting: about 0.5–1.5 EV in the
  corners for fast lenses wide open, and typically 0.3–0.7 EV in film-look grades.
* **Model.** Multiply in linear light by `1 − k·r^n`, with r the normalised radius, n ≈
  2–4, and k a fraction (0.3 ≈ −0.5 EV at the corner). Doing it in linear (before the curve)
  keeps highlights from going grey.

### 2.8 Gate weave and flicker (video)
* **Gate weave.** Frame-to-frame registration error in camera and projector: low-pass
  random translation of about **0.05–0.2 % of frame width** (a few px at 4K), mostly
  horizontal, correlated over ~0.2–1 s.
* **Flicker.** Exposure and printing-light variation of **±1–3 %** luminance per frame,
  plus occasional density breathing.
* **Implementation.** Per-frame sub-pixel shift (bilinear) plus a global gain. Both are
  temporal, and neither applies to stills.

### 2.9 Chromatic aberration and softness
* **Lateral CA.** Radial scale difference between channels: R scaled about +0.05…0.1 %
  and B about −0.05…0.1 % at the corners. The fringe grows with radius.
* **Softness.** Vintage-lens or film-scan softness: MTF50 around 0.15–0.25 cycles/px, i.e.
  a Gaussian blur σ ≈ 0.5–1 px at 20 MP. Add a slight radial increase if desired.
* **Order.** Apply both in linear light, *before* grain (grain is in the film, after the
  optics).

---

## 3. Algorithms, parameters, and typical values

Common conventions:
* Linear = scene-linear camera RGB (E-P7 mid-grey ≈ 0.07, clip 1.0).
* Radii are a % of image width, so results are resolution-independent.
* Stage order in `film.render()`: WB → bloom → halation → subtractive saturation → CCE →
  film curve → tone levels → HSL → mono → vignette → grain.

### 3.1 Desktop (numpy, 20 MP), as implemented in `sim/effects.py`

| Effect | Algorithm | Parameters (typical) | 20 MP cost |
|---|---|---|---|
| `gaussian_blur` | σ<3: exact separable kernel. Larger σ: BOX-downsample by ⌊σ/3⌋, 3-pass box filter (cumsum), bilinear upsample | – | O(N), independent of σ |
| `halation()` | src = lin · smoothstep(knee→threshold on display luma) · clip-boost(×3 near clip); `glow = PSF ⊛ Y(src)` (Gaussian + 2σ/4σ tail, optional ring); `lin += strength · glow · tint` | threshold 0.75–0.85, radius_pct 0.5–1.5 (35 mm), strength 0.15 subtle / 0.35 visible / 0.9 CineStill, tint [1, 0.25–0.45, 0.05–0.2], tail 0.4, ring 0–0.3 | ~1.4 s |
| `bloom()` | Energy-conserving `lin + s·(PSF⊛src − src)`; threshold 0 = mist (all light), >0 = highlight glow | mist: strength 0.05 (1/8 BPM) / 0.15 (1/2) / 0.3 (1); radius_pct 1.5–3; tail 0.5–0.6 | ~9 s (3 channels, 3 scales) |
| `grain_v2()` | Per channel: unit-variance field (white noise if cell ≤ 1 output px, attenuated by effective cell length; else bicubic-upsampled lattice + blur). Mix mono/independent by `colour`, × luma-bump amplitude, added in sRGB code values | strength 0.2 fine / 0.35 / 0.45 Fuji Strong; size 1 (Small) / 2.2 (Large) / 3 (pushed 1600); colour 0.2–0.4; layer_size [1, 1, 1.4]; highlight 0.35 | ~10 s |
| `film_curve()` | 1-D log-domain LUT (4097 entries) per channel, mixed with a luminance-applied version by `per_channel` | slope 1.6 (E-P7 match) / 1.3 Portra / 1.2 Eterna; shoulder 0.9 (stops); toe 0.3–0.8; black 0.002 / 0.006 matte; per_channel 0.5–0.7; exposure ±EV | ~11 s |
| `subtractive_saturation()` | `max·(rgb/max)^(1+a)`, optional `·(1−d·s^1.5)` | amount 0.1–0.3, density 0–0.2 | <1 s |
| `color_chrome()` | `lin · (1 − max_darken·level·w_sat·w_hue·w_lum)`; Weak 0.5, Strong 1.0 | max_darken 0.30, sat window 0.35–0.85 (HSV in linear) | ~3 s |

Checks done [ours]:
* Bloom conserves energy (an impulse of 30.0 gives 30.02 after blur).
* Blur σ is accurate to within 5–15 % (box-cascade rounding).
* Grain at 900 px matches a 20 MP render downsampled to 900 px: std 0.0069 vs 0.0070
  (size 1), 0.0209 vs 0.0209 (2.2), and 0.0285 vs 0.026 (3.0).
* The existing `fuji_like.json` recipes render **bit-identically** with the new code,
  because every new key is optional.

Not implemented on the desktop (formulas only, see §2): Clarity, vignette v2 (the existing
`vignette` key is used), CA, gate weave and flicker.

### 3.2 Camera ISP (per-pixel LUT, 3×3 matrix, 12-sector HSL, hardware blur/blend, luminance noise combiner)

| Effect | ISP recipe | Fidelity |
|---|---|---|
| Film curve (toe/shoulder) | Luminance tone LUT (`604f7c76`, the Color Profile tone path) and/or the **RGB gamma** unit (`604f6083`) for per-channel curves. Generate the 256/1024-entry LUT from `film_curve()` | High, if the gamma unit accepts arbitrary tables. `CREATIVE_PROCESSING_JOBS.md` only identifies "curve families"; whether custom curves work is unverified [fw] |
| Crossover | Per-channel RGB gamma offsets; or a tone-dependent tint via Mono-style toning (MONO only) | Medium. COLOR-path tint is global |
| Subtractive saturation / CCE / FX Blue | 12-sector **lightness** negative on red/orange/yellow/green (CCE) or blue/blue-cyan (FX Blue), plus a matching small sat boost. The ISP's lightness term is chroma-weighted (`clip(C/0.25)` in our model), which gives the saturation keying for free | Medium–high at mid-tones; it cannot see "bright and saturated" jointly |
| Vignette | Creative shading (combiner 33, radial mask) | High (already used) |
| Mono grain, luma-dependent | Grain combiner: xorshift + 256-entry mask LUT + gain (`GRAIN.md`). Re-shape the mask LUT to a midtone bump (0 → 1023 at index ~110 → ~400 at 255) | High for amplitude and luma shape. **Size: none** (1-px white noise). A pseudo-"Large" could run grain on a reduced-size job and upscale, but no such job is known |
| Colour grain | Planned colour-grain mod (`FEATURE_GAPS.md` #3) | Only luma-correlated (Cb/Cr pass through) |
| Halation | (1) luminance LUT → **highlight key** (0 below threshold, ramp to 1); (2) **3×3 matrix** on the key: R=1·Y, G=0.3·Y, B=0.1·Y; (3) **hardware blur** of the reduced copy (Soft Focus job); (4) **additive or screen blend** back, strength 0.2–0.5 | Plausible but unproven. Needs the Soft Focus job's input to be the keyed/tinted copy and its blend to be additive or screen; a lerp blend darkens the image. Star Light already does highlight detection (see §4) |
| Bloom / mist | Soft Focus job as is: blurred copy blended at 5–30 % (lerp is *exactly* the energy-conserving mist model) | **High.** Soft Focus is literally this |
| Highlight glow (Soft Glow) | Soft Focus with a highlight-keyed input (like halation, matrix = identity) | Plausible |
| Clarity | Dramatic Tone's local-contrast engine at low strength; or unsharp mask = original + k·(original − blur) through the blend unit with negative weight | Medium for +Clarity (DT is a heavier tone-mapper). −Clarity ≈ weak Soft Focus |
| Softness | Soft Focus blend with a small radius | OK |
| CA, gate weave, flicker | – | Not available (no per-channel warp; video Art Filters are frame-rate limited) |

---

## 4. Mapping to the E-P7's Art Filter and Art Effect primitives

### 4.1 What's in the camera

* **Art Filters.** The E-P7 manual lists the filters as Pop Art I/II, Soft Focus,
  Pale&Light Color I/II, Light Tone, Grainy Film I/II, Pin Hole I/II/III, Diorama I/II,
  Cross Process I/II, Gentle Sepia, Dramatic Tone I/II, Key Line I/II, Watercolor I/II,
  Vintage I/II/III, Partial Color I/II/III (18-hue colour ring), Bleach Bypass I/II and
  Instant Film (manual p.72;
  [PDF](https://download.omsystem.com/pages/inst/ep7/manual_ep7_ENU.pdf)).
  * Firmware IDs [fw, `analysis/ep7_1100/strings.jsonl`]: `01_POPART 02_FANTASIC_FOCUS
    03_DAYDREAM 04_LIGHT_TONE 05_ROUGH_MONOCHROME 06_TOY_PHOTO 07_DIORAMA 08_CROSS_PROCESS
    09_GENTLE_SEPIA 10_DRAMATIC_TONE 11_LIGNE_CLAIR 12_WATER_COLOR 13_VINTAGE 14_PARTCOLOR
    15_BLEACH_BYPASS 16_PLACAME`.
  * So: Soft Focus = "Fantasic Focus", Pale&Light = "Daydream", Grainy Film = "Rough
    Monochrome", Pin Hole = "Toy Photo", Key Line = "Ligne Clair", Instant Film = "Placame".
* **Strength slider.** Available on Pop Art, Soft Focus, Pin Hole, Cross Process and
  Instant Film (p.73).
* **Art Effects (p.70).** Soft Focus Effect, Pin-Hole Effect, White Edge, Frame, Star
  Light, Blur Effect (Top&Bottom / Left&Right), Shade Effect, plus Color Filter and
  Monochrome Color.
  * There is no Art Effect called "Film effect". The film-grain control is the
    **Mono-Profile Film Grain Effect** (Off/Low/Med/High, Mono only, "can not be previewed
    in live view", p.107).
  * ExifTool effect codes: Star Light 0x8010, Pin Hole 0x8020, Frame 0x8030, Soft Focus
    0x8040, White Edge 0x8050, B&W 0x8060, Blur T&B 0x8080, Blur L&R 0x8081
    ([ExifTool](https://exiftool.org/TagNames/Olympus.html)).
* **Movie mode.** Supported: Cross Process, Diorama, Dramatic Tone, Gentle Sepia, Grainy
  Film, Key Line, Light Tone, Pale&Light, Pin Hole, Soft Focus, Pop Art and Bleach Bypass,
  but "not 4K / High Speed", and "frame rate may drop"
  ([spec sheet](https://www.fotointern.ch/wp-uploads/2021/06/Specifications_E-P7_EN.pdf)).
  * Live view slows visibly with Diorama and Dramatic Tone
    ([Photography Blog](https://www.photographyblog.com/reviews/olympus_e_p7_review)).
  * The E-P2's Diorama movie ran as a time-lapse.
  * **So the blur and local-tone jobs are the expensive ones, and they run near real time
    only at reduced resolution.** That is consistent with a blur on a downscaled copy.

### 4.2 Which primitive could implement each film-look effect

| Film-look effect | Candidate E-P7 primitive | Why | Confidence |
|---|---|---|---|
| **Bloom / Pro-Mist** | **Soft Focus** filter / **Soft Focus Effect** | It is a blurred-copy blend: the mist model itself | High (visual); the job parameters are not yet located |
| **Highlight glow** | **Pale&Light Color** ("scatters light and slightly overexposes") or Soft Focus + highlight-keyed LUT | Pale&Light already biases glow to bright areas | Medium |
| **Halation** | Soft Focus blur path, fed by a **highlight key + red-tint matrix**; key detection as in **Star Light** | Star Light must find highlights to draw stars on them, so a highlight-key mask exists in some job. Soft Focus provides blur + blend; tint via the colour matrix of the companion pass | Medium–low (needs RE of 0x8010/0x8040 jobs) |
| Lens softness | Soft Focus at low strength; **Diorama**'s graded blur (radial or vertical softness) | Diorama = blur blended through a spatial mask | Medium |
| Clarity +/− | **Dramatic Tone** (local contrast); − via Soft Focus | DT is "partially increasing contrast" | Medium (DT is strong and HDR-like) |
| Film curve, toe/shoulder | Color-Profile tone levels; **Light Tone** (soft shadows and highlights); gradation; RGB gamma | Light Tone is a flattened curve | High (luma), medium (per-channel) |
| Crossover / split toning | **Cross Process** (per-channel curves); **Vintage** ("printed film discoloration and fading", blacks go navy); **Instant Film**; **Bleach Bypass** | These filters must contain per-channel tone LUTs; re-parameterise them | Medium |
| Faded / matte blacks | **Vintage**, Instant Film | lifted, tinted blacks | Medium |
| Subtractive saturation, CCE, FX Blue | 12-sector lightness (HSL mod); **Partial Color**'s hue-selective machinery for single-hue CCE | Partial Color desaturates outside an 18-position hue window, so it is a hue-keyed per-pixel op | Medium |
| Bleach-bypass density | **Bleach Bypass I/II** | direct | High |
| Vignette | **Shade Effect**, **Pin-Hole Effect**, Profile shading ±5 | radial mask (combiner 33) | High |
| Grain (mono, luma-masked) | Mono-Profile grain combiner; **Grainy Film** (grain + high contrast) | see `GRAIN.md` | High for amplitude; no size control |
| Colour grain | planned COLOR-path grain job | – | Medium |
| Expired film | Cross Process / Vintage + WB shift | per-channel LUTs | Medium |
| Light leak | **Frame** / **White Edge** overlay machinery (the edge-mask blend) with a warm colour, or Diorama's mask with tint | White Edge blends a soft edge mask: the same structure as an edge leak | Low–medium (not random) |
| Frame/border | **Frame** | direct | High |

### 4.3 What the E-P7 can't do (no known primitive)

* **Grain size, and per-layer or dye-cloud grain.** The grain combiner adds 1-px noise to Y
  only.
* **A true 3D LUT, or saturation- and lightness-dependent colour** (REALA ACE-style
  muting, "bright AND saturated" CCE). The HSL engine is 1-D in hue.
* **Clarity at a chosen radius and strength.** Only Dramatic Tone's fixed engine exists.
* **Halation that is exactly additive and exposure-proportional with a long tail**, unless
  the Soft Focus blend supports add or screen. Highlight energy above sensor clip is lost
  anyway; the desktop `clip_boost` fakes it.
* **Lateral CA, warps, gate weave and flicker.**
* **Any of the spatial effects in 4K or High-Speed movie, or at full frame rate in
  FHD.**
* **Live-view preview of grain** (manual p.107).
* **Combining Art Filters with Color Profile and HSL.** They are separate picture modes, so
  a "film look" that needs both blur (Art) and the 12-sector HSL (Profile) needs firmware
  work to chain jobs. MONO already chains mask → develop+grain → shading, which proves
  multi-pass scheduling exists (`CREATIVE_PROCESSING_JOBS.md`).

---

## 5. Validation and next steps

1. **Fuji ground truth.** Shoot a flat grey card and a step chart with a Fuji body in all
   six Grain settings and in CCE/FX Blue Off/Weak/Strong, all other things equal. Measure:
   * grain std vs luma
   * the grain spectrum (FFT radial profile → correlation length for Small/Large)
   * ΔL\* of saturated patches vs CCE level

   Then replace the [ours] estimates in `FUJI_GRAIN` and `color_chrome()`.
2. **E-P7 RE.** Locate the Soft Focus (0x8040 / `02_FANTASIC_FOCUS`) and Star Light
   (0x8010) job builders, following the same method as `CREATIVE_PROCESSING_JOBS.md`.
   Answers needed:
   * blur radius and downscale factor
   * blend mode (lerp, add or screen)
   * whether the blur input can be a LUT/matrix-processed copy

   Those answers decide whether in-camera halation is feasible.
3. **Diffusion filter A/B.** A 1/4 Black Pro-Mist on the E-P7 is the zero-firmware
   baseline. Fit `bloom()` strength and radius to it so the recipe values mean something.

## 6. Files

* `sim/effects.py`: `halation`, `bloom`, `grain_v2`, `film_curve`,
  `subtractive_saturation`, `color_chrome`, `gaussian_blur`.
* `sim/film.py`: optional recipe keys `bloom`, `halation`, `subtractive_saturation`,
  `color_chrome`, `film_curve`, `grain_v2`, each a dict of kwargs (`"enabled": false`
  skips one).
* `sim/recipes/film_look.json`: `cinestill_800t`, `portra_400_bloom`,
  `classic_neg_halation`, with per-stage camera-feasibility notes.
* Renders: `generated/film_look/*_contact.jpg`, including
  `synthetic_contact.jpg` (lamps, window, saturated patches) for judging halation and
  bloom.

Example:
```
.venv/bin/python -I sim/film.py --recipes sim/recipes/film_look.json \
    --images testdata/PA221251.ORF testdata/PA211063.ORF --width 900 --out generated/film_look
```
