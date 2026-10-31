# Fujifilm film simulations: what they are, and how to approximate them on the E-P7

Status: research notes plus **untested** starting-point recipes. Nothing here has
been checked against a camera. Every recipe needs validating against Fuji JPEGs
and ColorChecker shots before anyone relies on it. The machine-readable copy of
the recipes is [`sim/recipes/fuji_like.json`](../sim/recipes/fuji_like.json); its
values match section 4 exactly.

Evidence labels used throughout:

- **[measured-LUT]**: our own measurement of Fujifilm's official F-Log2 → film
  simulation 3D LUTs (method in §2.1). These are objective numbers, but they
  describe Fuji's *video* LUTs, which are only a proxy for in-camera stills JPEGs.
- **[measured-IR]**: Imaging Resource's Imatest ColorChecker plots of camera JPEGs,
  which they publish as qualitative descriptions of the plots
  ([IR guide](https://old.imaging-resource.com/news/2020/08/18/fujifilm-film-simulations-definitive-guide)).
- **[Fuji]**: Fujifilm's own descriptions of design intent.
- **[community]**: Fuji X Weekly, forum posts and blogs. Subjective.

---

## 1. The Fuji parameter set

Fuji's JPEG engine applies a base **film simulation** (a full tone and colour
transform, effectively a 3D LUT plus tone curve) and then a set of parametric
modifiers. Fuji X Weekly's recipes treat the following list as a complete
JPEG "recipe" (see any recipe, e.g.
[Kodachrome 64 for X-T5](https://fujixweekly.com/2022/11/28/kodachrome-64-fujifilm-x-t5-x-trans-v/)).

### 1.1 Base film simulation
A fixed per-sim transform: a tone curve (toe, mid-tone slope, shoulder) and a
hue/saturation/lightness remap that changes with hue *and* with lightness and
saturation. Fuji publishes some of these as 3D LUTs for video (§2.1), which
shows they are full 3D transforms and not just curves plus a saturation scale.
Approximate dates of introduction:
- PROVIA, Velvia and ASTIA: the original X100 era (2011)
- PRO Neg. Hi/Std: X-T1 / X-E2 era
- CLASSIC CHROME: X30, 2014 ([Fuji Korea story, 2014-10-06](https://www.fujifilm-x.com/ko-kr/stories/film-simulation-classic-chrome/))
- ACROS: X-Pro2, 2016
- ETERNA: X-H1, 2018
- CLASSIC Neg.: X-Pro3, 2019 ([X-Pro3 Stories #2](https://www.fujifilm-x.com/global/stories/x-pro3-stories-2-learning-from-film/))
- ETERNA BLEACH BYPASS: X-T4, 2020
- NOSTALGIC Neg.: GFX100S in 2021, then the X-H2S as the first X-series body
  ([FXW](https://fujixweekly.com/2025/09/11/nostalgic-negative-makes-your-photos-feel-like-memories/))
- REALA ACE: GFX100 II in 2023, then X-series from 2024
  ([FXW](https://fujixweekly.com/2023/09/12/new-reala-ace-film-simulation))

These dates for the older sims come from general knowledge of the camera
line-up, apart from the cited ones.

### 1.2 Dynamic Range: DR100 / DR200 / DR400
This is exposure-based highlight protection. At DR200 the camera meters and
exposes the raw about **1 EV darker**, and at DR400 about **2 EV darker**. The
JPEG tone curve then lifts mid-tones and shadows back up, so the extra stop or
two of highlight headroom ends up in a gentler shoulder. Because the sensor is
underexposed, there are minimum ISOs:
- Older X-Trans III bodies: ISO 400 for DR200 and ISO 800 for DR400
  ([FXW, X100F](https://fujixweekly.com/2017/10/18/fujifilm-x100f-dynamic-range-settings/))
- Later bodies: lower thresholds. Reports put them at 320/640 for the X-T3
  generation and lower again for X-Trans V
  ([jmpeltier](https://www.jmpeltier.com/fujifilm-dynamic-range-settings)).

The cost is shadow noise, the same as pushing an underexposed raw. DR is a
common FXW recipe ingredient: Kodachrome 64 uses DR200 and Portra 400 v2 uses
DR400.

### 1.3 D-Range Priority (DR-P)
DR-P (Weak / Strong / Auto) is an alternative to DR plus the tone controls.
- It combines DR underexposure with a strongly flattened curve. Weak ≈ DR200
  and Strong ≈ DR400.
- It descends from the "Hypertone" correction on Fuji Frontier scanners.
- It disables Highlight/Shadow tone. FXW finds DR400 with H−2/S−2 close to
  DR-P Weak ([FXW, "The curious case of D-Range Priority Auto"](https://fujixweekly.com/tag/d-range-priority-2/)).
- It appeared on X-series bodies around the X-T3 (late 2018).

### 1.4 Highlight Tone / Shadow Tone
These are parametric adjustments to the tone curve's shoulder and toe.
- Range: −2…+4 on X-Trans III/IV/V. Older bodies had −2…+2.
- Half steps arrived on newer bodies, and FXW recipes use values like Shadow
  +0.5 and +1.5
  ([Kodachrome II v2](https://fujixweekly.com/2021/04/05/two-fujifilm-x-trans-iv-film-simulation-recipes-kodachrome-ii/)).
  We did not find a primary source that names the first half-step body.
- From the X-Pro3 on, they are shown on a combined "tone curve" screen
  ([fujilove](https://fujilove.com/?p=24193)).
- Positive values mean harder tone: brighter highlights, darker shadows.

### 1.5 Color
Global saturation, −4…+4 on current bodies (older bodies: −2…+2). It acts as
a chroma multiplier on top of the sim. Its size in chroma terms per step is not
published.

### 1.6 Clarity
Clarity (−5…+5) is mid-frequency local contrast, much like Lightroom's
Clarity. It arrived with the X-Pro3 ([Fuji X-Pro3](https://www.fujifilm-x.com/products/cameras/x-pro3)).
- It adds a noticeable processing delay after each shot.
- FXW notes that it is unavailable when shooting HEIF
  ([FXW](https://fujixweekly.com/2022/11/22/nostalgia-negative-my-first-fujifilm-x-t5-x-trans-v-film-simulation-recipe/)).

### 1.7 Grain Effect
Grain Effect is synthetic film grain.
- Older bodies: Off/Weak/Strong.
- X-Pro3 and later: roughness (Off/Weak/Strong) × size (Small/Large)
  ([Fuji learning centre](https://www.fujifilm-x.com/en-gb/learning-centre/color-chrome-and-film-grain-effects)).
- Large grain uses a lower-frequency noise kernel. Only the size setting changes
  the grain's spatial spectrum.

### 1.8 Color Chrome Effect (CCE)
CCE is Off/Weak/Strong and is described as adding "deeper colours and a wider
tonal range in high-contrast scenes without oversaturating"
([Fuji](https://www.fujifilm-x.com/en-gb/learning-centre/color-chrome-and-film-grain-effects)).
- In practice it **darkens (adds density to) highly saturated colours**, mostly
  reds, then yellows and greens, so they keep their gradation instead of
  clipping. In other words, it compresses lightness that depends on saturation.
- It is derived from FORTIA slide film. The GFX 50S was the first camera with
  it (2017) and the X-T3 the first X-series body (2018)
  ([Imaging Resource GFX 50S review](https://www.imaging-resource.com/cameras/fujifilm-gfx-50s-review/shooting-4)).
- It does not touch raw files.

### 1.9 Color Chrome FX Blue
The same idea as CCE, restricted to blues (Off/Weak/Strong). It works like a
polariser: it lowers the luminance of blue regions such as sky
([jmpeltier](https://www.jmpeltier.com/fujifilm-color-chrome-blue-polarizing-filter-alternative/),
[FXW](https://fujixweekly.com/2020/06/30/fujifilm-x100v-new-feature-color-chrome-effect-blue/)).
It arrived with the X-Pro3 / X100V.

### 1.10 White Balance and WB shift
The WB preset or Kelvin value is followed by a shift on two axes, **R** and
**B**, each −9…+9. The B axis is effectively blue↔yellow and the R axis
red↔cyan. FXW recipes rely on this heavily; for example,
"Daylight, R+2 B−5" is a warm/amber cast.

### 1.11 Sharpness
Sharpness is −4…+4. It is an unsharp-mask-type control, and FXW recipes mostly
use −2…+1.

### 1.12 High ISO NR
High ISO NR is −4…+4 (older bodies −2…+2). FXW recipes almost always set −4,
because noise reduction smears grain and fine texture.

### 1.13 Monochromatic Color (ACROS / MONOCHROME only)
This tints the black-and-white output on two axes.
- **WC** (warm–cool): introduced on the X-T3.
- **MG** (magenta–green): added on the X-Pro3
  ([Fuji X-Pro3](https://www.fujifilm-x.com/products/cameras/x-pro3)).
- Each axis is ±9 on current bodies, although one hands-on report quotes a
  different step count.

---

## 2. What each base simulation does

### 2.1 Method for the [measured-LUT] numbers
In November 2025 Fujifilm released official film simulation 3D LUTs that
convert F-Log2 and F-Log2 C footage to Rec.709. They were packaged with the GFX
ETERNA 55 (archive `gfx-eterna-55-3d-lut-v110.zip`, v1.10, 2026-04-16,
[download page](https://www.fujifilm-x.com/en-gb/support/download/lut/);
coverage: [DIYPhotography](https://www.diyphotography.net/fujifilm-film-simulation-luts-video/),
[PetaPixel](https://petapixel.com/2025/11/18/fujifilms-new-f-log2-and-f-log2c-film-simulation-luts-look-fantastic)).

The pack covers these sims:
- PROVIA, Velvia, ASTIA, CLASSIC CHROME
- REALA ACE, PRO Neg. Std, CLASSIC Neg.
- ETERNA, ETERNA BLEACH BYPASS, ACROS

It also includes two neutral references, `WDR-709` and `FLog2-709`. Its
overview PDF states that each LUT "is designed to create Film Simulation X image".

**Not covered by the LUTs:** NOSTALGIC Neg., PRO Neg. Hi, MONOCHROME and SEPIA.
For those we rely on [measured-IR], [Fuji] and [community] sources.

Procedure (offline, our own script; the LUTs were not modified or
redistributed):
1. Build test colours in sRGB: 12 hues, one per E-P7 sector (HSV hue Ye 60°,
   Or 35°, OR 20°, Re 0°, Mg 320°, Vi 280°, Bl 235°, BC 210°, Cy 185°, GC 160°,
   Gr 125°, YG 85°). Make each at three strengths: *moderate* (S 0.6, V 0.7),
   *saturated* (S 1.0, V 0.85) and *dark-saturated* (S 0.9, V 0.45). Add the 18
   chromatic ColorChecker patches and a grey ramp from −7 to +6 EV around 18 %.
2. Treat each colour as scene-linear reflectance (18 % grey = 0.18).
3. Convert to F-Gamut (BT.2020 primaries) and encode with the published F-Log2
   curve: a=5.555556, b=0.064829, c=0.245281, d=0.384316, e=8.799461,
   f=0.092864, cut=0.000889. 18 % grey encodes to 0.391, which matches Fuji's
   spec, and the `FLog2-709` LUT returns 0.391 for it.
4. Apply the 33³ LUT with trilinear interpolation.
5. Decode the output with gamma 2.4 (BT.1886), convert to CIELAB (D65) and
   compare each sim with **PROVIA** for the same input.
6. Measure hue difference Δh in CIELAB degrees. **Positive = counter-clockwise =
   toward the previous E-P7 sector** (red+ → orange, blue+ → violet), which is
   the same convention as the recipes (§4).
7. For lightness, report "ΔL\* rel": the colour's L\* minus the L\* of a neutral
   grey with the same Rec.709 luminance, as a difference from PROVIA. This
   isolates per-hue lightness from the shared tone curve.

Caveats:
- These are **video** LUTs for one camera model. Fuji's stills engine adds
  DR handling, sharpening and so on, and may differ in detail.
- Saturated patches sit near the Rec.709 gamut edge, so their chroma ratios are
  partly limited by clipping.
- "ΔL\* rel" is partly confounded by chroma: desaturating in display space also
  moves L\*. Neutral WDR-709, which is just a flatter rendering, shows −4…−10
  ΔL\* rel in magentas, violets and blues. For this reason the recipes use only about half
  of the raw lightness deltas for sims that mainly desaturate.
- Comparisons are **relative to PROVIA**, which itself carries roughly 45 % more
  chroma than the neutral WDR-709 rendering (ColorChecker mean chroma ratio of
  WDR/PROVIA = 0.69).

### 2.2 Tone curves [measured-LUT]
Output L\* for a neutral grey at each exposure (EV relative to 18 % grey):

| sim | −4 | −3 | −2 | −1 | 0 | +1 | +2 | +3 | +4 | slope −4…−2 | slope −1…+1 | slope +1…+3 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WDR-709 (neutral) | 0.7 | 3.5 | 12.4 | 25.0 | 40.6 | 56.6 | 69.5 | 79.7 | 87.7 | 5.9 | 15.8 | 11.6 |
| PROVIA | 0.4 | 1.9 | 9.5 | 26.2 | 46.1 | 64.8 | 79.9 | 87.1 | 91.5 | 4.6 | 19.3 | 11.1 |
| Velvia | 0.0 | 0.2 | 4.1 | 24.8 | 46.7 | 63.7 | 78.4 | 87.5 | 93.1 | 2.0 | 19.4 | 11.9 |
| ASTIA | 0.3 | 1.3 | 7.7 | 25.8 | 47.2 | 65.3 | 78.8 | 85.8 | 90.5 | 3.7 | 19.8 | 10.2 |
| CLASSIC CHROME | 0.1 | 0.6 | 5.2 | 23.5 | 46.3 | 66.8 | 81.3 | 87.9 | 92.2 | 2.6 | 21.7 | 10.5 |
| CLASSIC Neg. | 0.3 | 1.7 | 7.3 | 21.9 | 46.5 | 72.2 | 86.5 | 92.4 | 95.4 | 3.5 | 25.2 | 10.1 |
| PRO Neg. Std | 0.6 | 2.5 | 10.7 | 26.9 | 46.4 | 65.0 | 79.8 | 87.0 | 91.5 | 5.0 | 19.0 | 11.0 |
| REALA ACE | 0.3 | 2.6 | 11.3 | 26.0 | 45.4 | 68.4 | 83.8 | 89.6 | 93.8 | 5.5 | 21.2 | 10.6 |
| ETERNA | 1.8 | 5.7 | 14.6 | 27.6 | 46.2 | 64.8 | 78.1 | 85.4 | 90.4 | 6.4 | 18.6 | 10.3 |
| ETERNA BB | 0.7 | 2.2 | 6.8 | 20.2 | 46.0 | 72.5 | 86.8 | 92.1 | 95.1 | 3.1 | 26.1 | 9.8 |
| ACROS | 0.2 | 1.2 | 6.3 | 24.0 | 45.4 | 65.0 | 79.9 | 88.3 | 93.0 | 3.1 | 20.5 | 11.7 |

Slopes are in L\* per EV. All sims put mid-grey at L\* 45–47, so the
differences are in curve *shape*:
- **Velvia, Classic Chrome, ACROS and Bleach Bypass** crush the −2 EV shadows.
- **Eterna** has by far the most open toe.
- **Classic Neg. and Bleach Bypass** have the steepest mid-tones (25–26 vs 19
  L\*/EV) and push +1/+2 EV much brighter.
- **REALA ACE** combines slightly open shadows with bright upper mid-tones,
  matching Fuji's "deep, soft shadows and hard highlights".
- **PRO Neg. Std** is almost the same as PROVIA in the LUT, only a little
  softer in the toe. IR describes it as "very low contrast" in stills, which
  is one place where the stills engine and the LUT may differ.

### 2.3 Per-sector colour behaviour vs PROVIA [measured-LUT]
The table uses *moderate* patches. Each cell is **chroma ratio / Δh° / ΔL\*rel**:

| sim | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Velvia | 1.09/+1/+2 | 1.13/+5/+2 | 1.13/+7/+1 | 1.13/+4/0 | 1.13/−5/0 | 1.20/−2/0 | 1.27/+4/0 | 1.13/+5/−1 | 1.01/+3/0 | 1.08/−2/+1 | 1.12/−1/+3 | 1.10/0/+2 |
| ASTIA | 1.01/−1/+1 | 1.03/+4/0 | 1.00/+3/−2 | 1.02/0/−3 | 1.03/−5/−4 | 1.04/−3/−3 | 1.12/0/0 | 1.09/+3/0 | 0.94/+12/−1 | 0.80/+5/0 | 0.91/−5/+1 | 0.98/−6/+2 |
| CLASSIC CHROME | 0.73/−3/−1 | 0.78/−2/−1 | 0.83/−1/−1 | 0.90/+1/−1 | 0.80/+5/−1 | 0.74/+2/−1 | 0.77/−7/−1 | 0.79/−16/−2 | 0.91/−5/−3 | 0.76/+6/−3 | 0.71/+1/−3 | 0.71/−4/−2 |
| CLASSIC Neg. | 0.72/−3/−5 | 0.89/−7/−5 | 1.01/−1/−3 | 1.07/+9/+1 | 0.85/+27/+3 | 0.65/+20/+6 | 0.69/−5/+7 | 0.83/−4/+4 | 0.88/+17/−2 | 0.70/+29/−4 | 0.63/+17/−7 | 0.65/+6/−6 |
| PRO Neg. Std | 0.87/+1/0 | 0.79/+3/−1 | 0.74/0/−2 | 0.75/−6/−4 | 0.86/−5/−3 | 0.85/−3/−2 | 0.78/−4/−1 | 0.77/−7/−1 | 0.82/−7/−1 | 0.82/−5/0 | 0.82/−3/−1 | 0.85/−2/0 |
| REALA ACE | 1.00/−2/−1 | 0.98/0/−3 | 0.95/0/−3 | 0.96/0/−2 | 0.94/−2/−2 | 0.88/−2/0 | 0.98/0/−7 | 0.95/−1/−5 | 0.85/−2/−4 | 0.78/−2/−1 | 0.79/−4/−1 | 0.92/−4/−1 |
| ETERNA | 0.74/+1/−1 | 0.73/+3/−2 | 0.70/+1/−3 | 0.72/−1/−4 | 0.74/0/−3 | 0.73/−1/−2 | 0.66/−7/−1 | 0.66/−15/−1 | 0.75/−10/−1 | 0.70/−2/−1 | 0.68/−2/−2 | 0.71/−2/−1 |
| ETERNA BB | 0.47/+4/−3 | 0.45/+3/−5 | 0.46/−4/−7 | 0.55/−7/−10 | 0.53/+3/−5 | 0.48/+3/−1 | 0.42/−8/+2 | 0.41/−22/+1 | 0.52/−13/−3 | 0.47/+1/−3 | 0.43/+3/−6 | 0.44/+2/−4 |

**Saturation dependence**, a proxy for Color-Chrome-like and "more saturated =
more muted" behaviour. We divide each chroma ratio on *saturated* patches by
the ratio on *moderate* patches. Values below 1 mean a sim suppresses saturated
colours more than mild ones.
- **REALA ACE** shows it clearly: 0.78–0.87 for magenta through yellow-green.
  This matches Fuji's "the more saturated the subject, the more muted the color"
  ([Fuji](https://www.fujifilm-x.com/en-us/products/film-simulation/reala-ace/)).
- **Velvia** is mildly compressive (0.90–0.97).
- **Classic Chrome, PRO Neg. Std and Eterna** go the other way (1.05–1.20).
  They mute mild colours more than vivid ones.

**ColorChecker summary.** Mean chroma ratio vs PROVIA over the 18 chromatic
patches, and mean |Δh|:

| sim | Velvia | ASTIA | CC | C.Neg | PN Std | REALA | ETERNA | E-BB |
|---|---|---|---|---|---|---|---|---|
| chroma ratio | 1.17 | 1.03 | 0.80 | 0.79 | 0.81 | 0.96 | 0.71 | 0.47 |
| mean \|Δh\|° | 2.6 | 3.6 | 4.1 | 8.7 | 4.0 | 1.6 | 4.4 | 6.1 |

**Neutral casts** [measured-LUT]. All colour sims render greys within ±1 a\*/b\*
of neutral, with one exception: **CLASSIC Neg. split-tones**.
- Shadows go green/cyan: a\* −2.8…−2.9 at −2/−1 EV.
- Highlights go warm red-yellow: a\* +3.4, b\* +2.5 at +1 EV.

### 2.4 Per-simulation notes

**PROVIA / Standard.**
- [Fuji] "Ideal for a wide range of subjects"
  ([Fuji](https://www.fujifilm-x.com/global/products/film-simulation/provia/)).
- [measured-IR] Moderate contrast and near-neutral saturation, with pure reds
  slightly boosted, oranges nudged toward yellow, and light/dark cyans pushed
  toward blue.
- [measured-LUT] Carries about 45 % more chroma than Fuji's neutral WDR
  rendering and a steeper mid-tone (19 vs 16 L\*/EV). It is our baseline.

**Velvia / Vivid.**
- [Fuji] "Vibrant reproduction, ideal for landscape and nature."
- [measured-LUT] +9…+27 % chroma, most in blues and blue-cyan. Blues rotate
  slightly toward violet (+4°) and cyan toward blue. Deep shadows are much
  darker (L\* 4.1 vs 9.5 at −2 EV), with an almost identical mid-tone.
- [measured-IR] Very high saturation in dark greens, dark blues and reds;
  yellow shifted toward orange; "royal blue" skies.

**ASTIA / Soft.**
- [Fuji] "Softer color and contrast."
- [measured-LUT] Near-PROVIA chroma. Cyan rotates hard toward blue (+12…+16°)
  and green-cyan loses 20 % chroma. The highlight shoulder is a little lower
  (L\* 85.8 vs 87.1 at +3 EV) and the −2 EV shadows a little darker. Skin:
  dark-skin patch +16 % chroma, light-skin −8 %.
- [measured-IR] Flatter highlights with steeper shadows; skin less rosy.

**CLASSIC CHROME.**
- [Fuji] "Soft color and enhanced shadow contrast for a calm look." Fuji says
  it was built around tone rather than colour, with saturation lower than any
  other sim at the time, soft highlights and firm shadows. It removes the
  magenta component from skies and retunes red and green
  ([Fuji Korea](https://www.fujifilm-x.com/ko-kr/stories/film-simulation-classic-chrome/)).
- [measured-LUT] Yellows, greens, violets and blues −21…−29 % chroma; reds only
  −10 %. Blue and blue-cyan rotate toward cyan (−7°, −16°) and magenta toward
  red (+5°), which is the "magenta removed from sky" effect in numbers.
  Shadows are much harder (L\* 5.2 vs 9.5 at −2 EV) and upper mid-tones a little
  brighter.
- [measured-IR] agrees: medium/dark blues are desaturated and shifted toward
  cyan.

**CLASSIC Neg.**
- [Fuji] Modelled on SUPERIA. It uses "color-by-color contrast": a different
  brightness-dependent tone response per colour, where some colours are held
  below a threshold to give a "veiled" look. The keys are greens, blues and
  skin. It is designed to be shot slightly overexposed
  ([X-Pro3 Stories #2](https://www.fujifilm-x.com/global/stories/x-pro3-stories-2-learning-from-film/)).
- [measured-LUT] This is the most non-linear sim.
  - Hue twists: magenta → red +27°, violet → magenta +20°, green-cyan → cyan
    +29°, green → cyan +17°, cyan → blue +17°.
  - Per-hue lightness: yellows, greens and yellow-greens 5–7 L\* darker;
    blues and violets 4–7 L\* lighter. This is the "colour-by-colour contrast",
    visible directly.
  - Tone: steepest mid-tones and split-toned greys (green shadows, warm
    highlights).
- [measured-IR] Very high contrast, slightly red overall, reds boosted, and
  bright yellows, greens, purples and blues suppressed.

**NOSTALGIC Neg.** (no LUT available)
- [Fuji] "Amber tinted highlights and rich shadow tone for printed photo look"
  ([Fuji](https://www.fujifilm-x.com/global/products/film-simulation/)). The
  amber is meant to stop shadows sinking into blue or green, and "amber tends
  to become unnatural when adjusted using only white balance"
  ([Fuji](https://www.fujifilm-x.com/en-ph/products/film-simulation/nostalgic-neg/)).
- It was inspired by 1970s American New Color photography (Eggleston, Shore)
  ([Fuji Rumors summary of Fuji X Lab](https://www.fujirumors.com/fujifilm-gfx100s-nostalgic-negative-development-story-recommended-settings-samples-exceeding-full-frame-fujifilm-x-lab/)).
- [community] Softer tone and more saturation than Classic Neg. (Jonas Rask,
  via Fuji Rumors). Warm amber highlights and yellow-shifted greens (Fujifilm
  Focus magazine). FXW describes it as "a blend of Eterna and Classic Chrome",
  flat out of the box
  ([FXW](https://fujixweekly.com/2022/11/22/nostalgia-negative-my-first-fujifilm-x-t5-x-trans-v-film-simulation-recipe/)).
- No quantitative data. A community LUT exists in
  [abpy/FujifilmCameraProfiles](https://github.com/abpy/FujifilmCameraProfiles),
  but it is derived from Adobe's profiles, so we did not treat it as primary.

**REALA ACE.**
- [Fuji] "Faithful color reproduction with hard tonality." Deep, soft shadows
  and hard highlights. Colour is suppressed more on more saturated subjects.
  It is good at purples and yellow-greens
  ([Fuji](https://www.fujifilm-x.com/en-us/products/film-simulation/reala-ace/)).
- [measured-LUT] The most hue-accurate sim relative to PROVIA (mean |Δh| 1.6°).
  Greens and cyans lose 15–25 % chroma, and up to 39 % on saturated patches.
  Blues and cyans are 5–6 L\* darker. Upper mid-tones are brighter
  (+1 EV: L\* 68 vs 65).
- [community] FXW: softer than Classic Neg. but a little more vibrant
  ([FXW](https://fujixweekly.com/2023/09/12/new-reala-ace-film-simulation)).

**ETERNA / Cinema.**
- [Fuji] "Soft color and rich shadow tone suitable for film look movie."
- [measured-LUT] Chroma about 0.71× PROVIA, with blues and blue-cyan cut
  hardest (0.66). Blue-cyan and cyan rotate toward cyan (−10…−20°) and oranges
  toward yellow (+3…+13°). It has the most open toe of all sims
  (L\* 1.8 vs 0.4 at −4 EV) and a slightly lower shoulder.
- [measured-IR] Very flat; greens, magentas and purples desaturated most.

**ETERNA BLEACH BYPASS.**
- [Fuji] "Unique color with low saturation and high contrast"; "an unreal,
  cold feeling"
  ([Fuji](https://www.fujifilm-x.com/en-ph/products/film-simulation/eterna-bleach-bypass/)).
- [measured-LUT] Chroma 0.47× PROVIA, the lowest. Reds 9–16 L\* darker than
  neutral. Blue-cyan rotates toward cyan (−22…−31°). Mid-tone slope 26 L\*/EV,
  with brighter highlights and darker −1 EV. IR suggests underexposing about
  1 EV.

**PRO Neg. Std.**
- [Fuji] "Soft gradations and skin tones."
- [measured-LUT] Chroma about 0.81×, with reds/orange-reds cut most (0.74–0.75)
  and darkened 4–7 L\*. Cyans are slightly less blue than PROVIA's. The tone
  curve is close to PROVIA's with a softer toe.
- [measured-IR] Flat and muted, with skin neutral.

**PRO Neg. Hi.** (no LUT available)
- [Fuji] "Slightly enhanced contrast."
- [measured-IR] Same hues as Std with a steeper curve, and only modestly more
  saturated. On the E-P7, use the PRO Neg. Std data with +1 to +2 contrast.

**ACROS (+Ye / +R / +G).**
- [Fuji] "Rich details with sharpness." The filters slightly darken skies
  (Ye), darken skies considerably (R) and flatter skin (G).
- [measured-LUT] Relative to BT.709 luminance, blues and violets render
  8–9 L\* lighter and reds and oranges 6–8 L\* darker: a mildly blue-leaning
  panchromatic response. The curve is harder from lower mid-tones to
  highlights, with darker −2 EV shadows.
- [measured-IR] ACROS has a structured, ISO-dependent grain-like rendering. It
  is part of the sim, not only the Grain Effect, and it differs from
  MONOCHROME's more random pattern. It is not reproduced by the LUT.

**MONOCHROME / SEPIA.**
- [measured-IR] MONOCHROME is roughly PROVIA with the colour removed and a
  flatter curve than ACROS. SEPIA is MONOCHROME with a warm tone. No numeric
  data.

### 2.5 Community "film" recipes (Fuji X Weekly)

| recipe | sim | grain | CCE / FX Blue | WB + shift | DR | H / S | Color | Sharp / NR / Clarity | EC |
|---|---|---|---|---|---|---|---|---|---|
| [Kodachrome 64 (X-T5)](https://fujixweekly.com/2022/11/28/kodachrome-64-fujifilm-x-t5-x-trans-v/) | Classic Chrome | Weak, Small | Strong / Off | Daylight, R+2 B−5 | DR200 | 0 / +0.5 | +2 | +1 / −4 / +3 | 0…+2/3 |
| [Kodachrome II (X-Trans IV)](https://fujixweekly.com/2021/04/05/two-fujifilm-x-trans-iv-film-simulation-recipes-kodachrome-ii/) | Classic Chrome | Weak, Small | Strong / Weak | Auto, R+3 B−4 | DR200 | +1 / +2 | +1 | +1 / −4 / −2 | +1/3…+2/3 |
| [Kodachrome II v2](https://fujixweekly.com/2021/04/05/two-fujifilm-x-trans-iv-film-simulation-recipes-kodachrome-ii/) | Classic Chrome | Weak, Small | Strong / Weak | Auto White Priority, R+3 B−5 | DR200 | +1 / +1.5 | +1 | +1 / −4 / −2 | +1/3…+2/3 |
| [Kodak Portra 400 v2 (X-T5)](https://fujixweekly.com/2022/12/16/kodak-portra-400-v2-fujifilm-x-t5-x-trans-v-film-simulation-recipe/) | Classic Chrome | Strong, Small | Strong / Off | 5200K, R+1 B−6 | DR400 | 0 / −2 | +2 | −2 / −4 / −2 | +1/3…+1 |
| [Nostalgia Negative (X-T5)](https://fujixweekly.com/2022/11/22/nostalgia-negative-my-first-fujifilm-x-t5-x-trans-v-film-simulation-recipe/) | Nostalgic Neg. | Strong, Small | Strong / Weak | Daylight, R+3 B−3 | DR400 | −1 / +1 | +4 | −1 / −4 / −3 | 0…+2/3 |

The pattern is clear: Kodak-style looks start from Classic Chrome (low chroma,
cyan-shifted blues, hard shadows) and then add warmth through WB (R+, B−),
density through CCE Strong, and a little Color. FXW also has an older
[X-T30 Kodachrome 64](https://fujixweekly.com/2019/08/02/my-fujifilm-x-t30-kodachrome-64-film-simulation-recipe/)
and many Portra variants
([comparison](https://fujixweekly.com/tag/portra-400/)).

### 2.6 Summary table

Contrast and saturation are measured relative to PROVIA [measured-LUT] unless
marked. "Mid" is the L\*/EV slope from −1 to +1 EV; "toe" is L\* at −2 EV.

| sim | mid slope (PROVIA 19.3) | toe L\*@−2EV (PROVIA 9.5) | chroma vs PROVIA | key hue / lightness traits | evidence |
|---|---|---|---|---|---|
| PROVIA | 19.3 | 9.5 | 1.00 | reference; reds slightly boosted (IR) | LUT + IR |
| Velvia | 19.4 | 4.1 (crushed) | 1.17 | blues → violet, cyan → blue; strongest blues/greens | LUT + IR |
| ASTIA | 19.8 | 7.7 | 1.03 | cyan → blue +12°; green-cyan −20 %; softer shoulder | LUT + IR |
| CLASSIC CHROME | 21.7 | 5.2 (hard) | 0.80 | blues → cyan (−7…−16°), magenta out of skies; yellows/greens −27…−29 % | LUT + IR + Fuji |
| CLASSIC Neg. | 25.2 | 7.3 | 0.79 | big twists: Mg → red +27°, greens → cyan +17…+29°; yellows/greens darker, blues lighter; split-toned greys | LUT + IR + Fuji |
| NOSTALGIC Neg. | soft (Fuji) | rich (Fuji) | higher than C.Neg (community) | amber highlights, yellow-shifted greens | Fuji + community only |
| REALA ACE | 21.2 | 11.3 (soft) | 0.96 | most accurate hues; saturated colours suppressed more; darker blues | LUT + Fuji |
| ETERNA | 18.6 | 14.6 (open) | 0.71 | blue-cyan → cyan −15°; orange → yellow | LUT + IR |
| ETERNA BB | 26.1 | 6.8 | 0.47 | reds 9–16 L\* darker; blue-cyan → cyan −22° | LUT + Fuji |
| PRO Neg. Std | 19.0 | 10.7 | 0.81 | reds −25 % and darker; minimal twists | LUT + IR |
| PRO Neg. Hi | steeper than Std (IR) | – | ≈ Std | as Std | IR only |
| ACROS | 20.5 | 6.3 | mono | blues lighter, reds darker; structured grain | LUT + IR |
| MONOCHROME / SEPIA | flatter than ACROS (IR) | – | mono | PROVIA luminance, optional tone | IR only |

---

## 3. Mapping Fuji controls to the E-P7

E-P7 stock capabilities (firmware 1.1), as used in this document:

- **Color Profile** (front-dial COLOR, 4 profiles):
  - 12-sector saturation −5…+5
  - highlight / shadow / midtone tone levels −7…+7
  - creative shading (vignette)
  - Profile 4 is a factory "film-like" preset with saturation
    `-4,0,0,0,-1,-1,-1,0,0,0,0,-4` and shadows/midtones/highlights `-3,0,+3`.
    That is muted yellows and yellow-greens plus a hard S-curve, which is itself
    a Classic-Chrome-ish idea.
- **Monochrome Profile** (front-dial MONO, 4 profiles):
  - colour filters: 8 on PEN-F, adjusted in 3 strength steps
    ([mirrorlessons](https://www.mirrorlessons.com/2016/04/22/olympus-pen-f-monochrome-color-profiles/)).
    The exact E-P7 filter list still needs confirming.
  - tint/toning
  - film grain Off/Low/Medium/High
  - shading and tone levels
- **Picture modes** (Natural, Vivid, Muted, Portrait…) with contrast,
  sharpness and saturation −5…+5, gradation (Auto/Normal/High key/Low key) and
  highlight & shadow control.
- **WB fine-tune** A–B ±7 and G–M ±7.
- **Color Creator**: 30 hues × 8 saturation levels. It is a global tint plus a
  saturation change.

Planned firmware additions, used in the "with mods" column:
- per-sector **Hue** and **Lightness** −7…+7
- saturation extended to ±7
- **colour** (not just mono) grain
- vignette −5…+5 on colour profiles

Internally the native HSL tables already carry hue and lightness coefficients;
stock firmware just doesn't expose them
(`external/oly_fw_analysis/docs/color/MODES.md`).

Unit scales assumed in `sim/pipeline.py` (model, not yet calibrated):
- **Saturation:** one step ≈ gain/5 ‰ of chroma. That is about +4.8 %/step
  for yellow/orange, +7.6 % for blue, +12…+13 % for green-cyan and yellow-green
  on the + side, and −7.7…−10 %/step on the − side.
- **Hue:** one step ≈ 2.75° in the chroma plane.
- **Lightness:** steps 1…7 ≈ 0.6, 1.2, 2.4, 3.7, 4.9, 6.1, 7.3 L\* at full
  chroma, reduced for low-chroma pixels.

The recipe values in §4 were converted from the measured ratios and degrees
with these scales, so they shift if calibration changes them.

| Fuji control | E-P7 stock equivalent | with planned mods | fidelity notes |
|---|---|---|---|
| Base film simulation | Color Profile 12-sector sat + 3 tone levels + picture-mode contrast | + per-sector hue and lightness, sat ±7 | A Fuji sim is a 3D LUT. Twelve sectors × (S, H, L) is a hue-only 1D approximation, and it cannot vary with lightness or saturation within a sector. Classic Neg.'s per-colour tone curves and REALA ACE's saturation-dependent muting can only be averaged. |
| Tone curve shape (toe / shoulder per sim) | highlight / shadow / midtone levels, contrast, gradation | same | Three knobs plus contrast cannot reproduce specific shoulder shapes; e.g. Eterna's open toe *and* lower shoulder are approximated by S+4/H−2. The step size of E-P7 tone levels in L\* is unknown. |
| Dynamic Range DR200/400 | exposure comp −1/−2 EV + shadows/midtones up, highlights down; or gradation Auto | same | Partly replicable. E-P7 tone levels act after capture, so they cannot recover clipped highlights. Real DR400 headroom needs actual underexposure (EC −2) with a lift back, which costs shadow noise just as it does on Fuji. |
| D-Range Priority | gradation Auto / highlight & shadow control | same | Approximate: a flat curve is easy; scene-adaptive DR-P Auto is not. |
| Highlight / Shadow tone | Color Profile highlight / shadow levels (−7…+7) | same | Good analogue. Our assumed mapping is Fuji 1 step ≈ E-P7 1–2 steps, uncalibrated. |
| Color (global sat) | add the same value to all 12 sectors; or picture-mode saturation | sat ±7 per sector | Good. Fuji Color ±4 → about ±1 E-P7 step per Fuji step (assumption). |
| Clarity | none | none | **Not reproducible.** Clarity is local, mid-frequency contrast, and no E-P7 control does that. Global contrast and sharpness are only weak substitutes. |
| Grain Effect | Mono Profile grain only | colour grain Low/Med/High | Strength maps (Weak → Low, Strong → Medium). **Size (Large) is not reproducible**: the E-P7 grain generator is per-pixel noise with a luminance mask (`sim/pipeline.py`) and has no size control. |
| Color Chrome Effect | none (sector sat can only reduce chroma) | negative lightness on red, orange, yellow and green sectors | **Only approximated.** CCE darkens pixels in proportion to their saturation. Sector lightness in our model is scaled by chroma (`clip(chroma/0.25)`), which roughly matches. It cannot reproduce CCE's dependence on highlight tones. |
| Color Chrome FX Blue | none | negative lightness on blue / blue-cyan (−1…−3) | Same caveat. This works reasonably well, because sky is a narrow hue band. |
| White Balance + R/B shift | WB preset + A–B / G–M fine-tune ±7 | same | Different axes. Fuji B− ≈ E-P7 A+ (amber). Fuji R+ ≈ amber plus magenta. Step sizes are not equivalent. |
| Sharpness | picture-mode sharpness −5…+5 | same | Fine. |
| High ISO NR | Noise Filter (Off/Low/Std/High) | same | Coarser control. Use Low/Off to keep grain texture, as FXW's NR −4 does. |
| Monochromatic Color WC / MG | Mono Profile toning; Color Creator tint | same | Approximate. The E-P7 offers preset tint colours rather than a continuous two-axis control. |
| Per-hue luminance (Classic Neg. "colour-by-colour contrast", CCE, REALA's darker blues) | none | per-sector lightness | With mods: reasonable at mid-tones. Not lightness-dependent, so the "below a threshold only" part of Classic Neg. is lost. |
| Split toning (Classic Neg. green shadows / warm highlights; Nostalgic amber highlights) | none (WB is global) | none | **Not reproducible** without a tone-dependent tint stage. Global WB is a compromise, and Fuji itself says amber via WB alone looks unnatural. |
| ACROS grain structure | Mono grain (random) | same | Not reproducible. ACROS's grain is a structured, ISO-dependent pattern. |

**Bottom line.**
- **Reproducible well:** global saturation; most per-hue saturation; WB looks;
  basic contrast and toe/shoulder trends; mono filters and toning; grain amount.
- **With the mods:** hue twists (Classic Chrome blues → cyan, Classic Neg.'s
  big rotations up to the ±19° limit) and per-hue lightness (Classic Neg.,
  REALA ACE's dark blues, CCE / FX Blue density) become feasible to first order.
- **Not reproducible:** Clarity; grain size; split toning; lightness- or
  saturation-dependent colour (true CCE, REALA's "more saturated = more
  muted", Classic Neg.'s threshold curves); DR headroom without real
  underexposure; specific per-sim shoulder shapes.

---

## 4. Recipes in E-P7 terms

Conventions (identical in the JSON):

- **Sector order:** yellow, orange, orange-red, red, magenta, violet, blue,
  blue-cyan, cyan, green-cyan, green, yellow-green. Table headings:
  Ye, Or, OR, Re, Mg, Vi, Bl, BC, Cy, GC, Gr, YG.
- **Hue:** positive = rotate toward the **previous** sector in that order,
  i.e. counter-clockwise in CIELAB a\*b\* and BT.601 CbCr. Examples: red + →
  orange, blue + → violet, green + → green-cyan, cyan + → blue-cyan.
  - We chose this to match `sim/pipeline.py`. It adds the hue slider to
    `atan2(Cr, Cb)`, and the firmware sector centre angles *decrease* with
    `ui_index` (yellow 134° … yellow-green 165° in the ISP plane).
  - About 2.75° per step in the pipeline model.
- **Ranges:** sat, hue, light and tone are −7…+7. Contrast and vignette are
  −5…+5.
- **WB shift:** `a_b` positive = amber, negative = blue. `g_m` positive =
  magenta, negative = green.
- **Vignette:** negative = darker corners (Olympus shading convention; verify).
- **Grain:** off / low / medium / high.
- **Baseline:** every value is relative to an all-zero E-P7 Color Profile,
  which we *assume* is close to PROVIA. Validate that first (§4.11).
- **Stock-compatible** = sat within ±5, hue and light all 0, and no colour
  grain. Otherwise the recipe needs the planned mods. Each recipe also has a
  **stock fallback**: sat clamped to ±5, hue and light zeroed, tone/WB/contrast
  unchanged.

These are **untested starting points**. They come from public LUT
measurements (§2) and descriptions, converted with uncalibrated unit scales.
Expect to iterate them against Fuji JPEGs of the same scene and ColorChecker
shots.

How values were derived (measured sims):
- **sat:** from the chroma ratio vs PROVIA, averaged over the three patch
  strengths and converted with the per-sector gains.
- **hue:** from Δh, about 2.75°/step and clipped at ±7.
- **light:** about half the raw ΔL\*rel for the chroma confound noted in §2.1,
  except where a sign pattern is clearly not a desaturation artefact (Classic
  Neg.'s light blues).
- **tone and contrast:** from the §2.2 tone table.

### 4.1 PROVIA (`provia`)
| | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sat | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| hue | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| light | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

| tone H / S / M | contrast | WB a_b / g_m | grain | vignette | stock-compatible |
|---|---|---|---|---|---|
| 0 / 0 / 0 | 0 | 0 / 0 | off | 0 | yes |

Stock fallback sat (hue and light 0): 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0

The neutral reference. If the E-P7 baseline turns out flatter than PROVIA
(PROVIA itself is about 45 % more chromatic than Fuji's neutral WDR
rendering), add +1…+2 to all sectors here and treat every other recipe as an
offset from this one.

### 4.2 Velvia (`velvia`)
| | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sat | +1 | +2 | +2 | +2 | +1 | +2 | +2 | +3 | 0 | +1 | +1 | +1 |
| hue | 0 | 0 | 0 | 0 | -1 | -1 | +1 | +2 | +2 | -2 | 0 | 0 |
| light | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | +1 | +1 |

| tone H / S / M | contrast | WB a_b / g_m | grain | vignette | stock-compatible |
|---|---|---|---|---|---|
| 0 / -3 / 0 | +1 | 0 / 0 | off | 0 | no |

Stock fallback sat (hue and light 0): +1, +2, +2, +2, +1, +2, +2, +3, 0, +1, +1, +1

- **sat:** measured +9…+27 % chroma vs PROVIA, biggest in blues and blue-cyan.
- **hue:** blues rotate toward violet and cyan toward blue (+1…+5°).
- **tone:** the −2 EV shadow is less than half of PROVIA's L\*, hence shadows
  −3 with contrast +1.
- **light:** greens get +1 because they came out noticeably brighter than the
  chroma confound alone explains.

### 4.3 Classic Chrome (`classic_chrome`)
| | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sat | -2 | -2 | -2 | -1 | -1 | -3 | -3 | -3 | -1 | -3 | -3 | -3 |
| hue | -2 | -1 | 0 | 0 | +3 | +1 | -2 | -4 | -2 | +2 | 0 | -2 |
| light | -1 | -1 | 0 | -1 | -1 | -1 | -1 | -1 | -1 | -1 | -2 | -1 |

| tone H / S / M | contrast | WB a_b / g_m | grain | vignette | stock-compatible |
|---|---|---|---|---|---|
| 0 / -3 / 0 | +1 | 0 / 0 | off | 0 | no |

Stock fallback sat (hue and light 0): -2, -2, -2, -1, -1, -3, -3, -3, -1, -3, -3, -3

- **sat:** measured −21…−29 % chroma on yellows, greens, violets and blues,
  while reds keep most of theirs.
- **hue:** blue −2 and blue-cyan −4 rotate toward cyan, and magenta +3 rotates
  toward red. This is Fuji's "magenta removed from skies".
- **tone:** much harder −2 EV shadows, hence shadows −3 and contrast +1.
- **Stock fallback:** keeps the colour muting but loses the cyan skies.

### 4.4 Classic Neg. (`classic_neg`)
| | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sat | -3 | -2 | -2 | 0 | -1 | -5 | -5 | -3 | -1 | -4 | -4 | -4 |
| hue | 0 | -1 | 0 | 0 | +7 | +6 | -2 | -3 | +6 | +7 | +5 | +2 |
| light | -4 | -4 | -3 | -2 | -1 | +2 | +2 | +3 | -1 | -3 | -5 | -5 |

| tone H / S / M | contrast | WB a_b / g_m | grain | vignette | stock-compatible |
|---|---|---|---|---|---|
| +4 / -2 / +1 | +2 | +1 / 0 | off | 0 | no |

Stock fallback sat (hue and light 0): -3, -2, -2, 0, -1, -5, -5, -3, -1, -4, -4, -4

- **hue:** the sim's hue twists are the largest measured. They exceed the ±7
  step limit (about ±19°) for magenta and green-cyan, so those are clipped.
- **light:** −3…−5 on yellows and greens and +2…+3 on blues and violets
  implement Fuji's "colour-by-colour contrast".
- **tone:** steepest mid-tones and much brighter upper mid-tones, hence
  highlights +4, shadows −2, midtones +1 and contrast +2.
- **Not captured:** the split tone (green shadows, warm highlights). A +1
  amber is only a global average.
- Fuji recommends slight overexposure, so try EC +1/3…+2/3.

### 4.5 Nostalgic Neg. (`nostalgic_neg`)
| | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sat | +1 | +1 | +1 | 0 | -1 | -1 | -1 | -1 | -1 | -1 | 0 | +1 |
| hue | 0 | 0 | 0 | +1 | 0 | 0 | 0 | 0 | 0 | -2 | -3 | -1 |
| light | +1 | +1 | 0 | 0 | 0 | 0 | -1 | 0 | 0 | 0 | 0 | 0 |

| tone H / S / M | contrast | WB a_b / g_m | grain | vignette | stock-compatible |
|---|---|---|---|---|---|
| -1 / 0 / +1 | -1 | +2 / 0 | off | -1 | no |

Stock fallback sat (hue and light 0): +1, +1, +1, 0, -1, -1, -1, -1, -1, -1, 0, +1

**Qualitative only:** there is no Fuji LUT for this sim.
- **WB:** amber +2 stands in for the amber highlights.
- **hue:** greens shift toward yellow (−3 on green, −2 on green-cyan).
- **sat and light:** warm sectors slightly fuller and lighter, with mild
  muting elsewhere.
- **tone:** softer (H −1, contrast −1) with full mid-tones.
- **vignette:** −1 for the "printed photo" feel.
- Expect this to be the weakest match: Fuji says the amber should sit in the
  highlights, and the E-P7 cannot tint highlights alone.

### 4.6 REALA ACE (`reala_ace`)
| | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sat | 0 | 0 | 0 | 0 | -1 | -1 | 0 | -1 | -2 | -3 | -3 | -2 |
| hue | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | -1 | -2 |
| light | 0 | -2 | -2 | -2 | -2 | -1 | -4 | -4 | -4 | -1 | 0 | 0 |

| tone H / S / M | contrast | WB a_b / g_m | grain | vignette | stock-compatible |
|---|---|---|---|---|---|
| +2 / +1 / 0 | +1 | 0 / 0 | off | 0 | no |

Stock fallback sat (hue and light 0): 0, 0, 0, 0, -1, -1, 0, -1, -2, -3, -3, -2

- **hue:** the measured hues are nearly PROVIA's.
- **sat:** greens and cyans lose 15–25 % chroma.
- **light:** −4 on blues and cyans for the measured 5–6 L\* darker blues.
- **tone:** highlights +2 and shadows +1 follow Fuji's "deep, soft shadows and
  hard highlights" and the measured curve.
- **Not captured:** REALA's key trait, "more saturated = more muted", cannot
  be represented by a fixed per-sector table.

### 4.7 Eterna (`eterna`)
| | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sat | -2 | -2 | -3 | -2 | -2 | -3 | -4 | -5 | -2 | -3 | -3 | -3 |
| hue | 0 | +3 | +2 | 0 | 0 | 0 | -2 | -6 | -4 | 0 | -1 | -2 |
| light | -1 | -1 | -2 | -3 | -3 | -2 | -2 | -1 | -1 | -1 | -1 | -1 |

| tone H / S / M | contrast | WB a_b / g_m | grain | vignette | stock-compatible |
|---|---|---|---|---|---|
| -2 / +4 / 0 | -2 | 0 / 0 | off | 0 | no |

Stock fallback sat (hue and light 0): -2, -2, -3, -2, -2, -3, -4, -5, -2, -3, -3, -3

- **sat:** chroma about 0.71× overall, with blues cut most.
- **hue:** blue-cyan and cyan rotate toward cyan (−6/−4) and oranges toward
  yellow (+3).
- **tone:** the most open toe of any sim (shadows +4), a lower shoulder
  (highlights −2) and contrast −2.

### 4.8 Eterna Bleach Bypass (`eterna_bleach_bypass`)
| | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sat | -6 | -7 | -7 | -5 | -4 | -7 | -7 | -7 | -6 | -7 | -7 | -7 |
| hue | 0 | 0 | -2 | -3 | 0 | 0 | -3 | -7 | -5 | 0 | 0 | 0 |
| light | -2 | -3 | -4 | -5 | -4 | -3 | -1 | -1 | -1 | -2 | -3 | -2 |

| tone H / S / M | contrast | WB a_b / g_m | grain | vignette | stock-compatible |
|---|---|---|---|---|---|
| +4 / -3 / 0 | +3 | 0 / 0 | off | 0 | no |

Stock fallback sat (hue and light 0): -5, -5, -5, -5, -4, -5, -5, -5, -5, -5, -5, -5

- **sat:** chroma 0.47× needs the ±7 saturation extension. Stock −5 gets about
  60–75 % of the way, so consider also using picture-mode saturation if the
  mode allows it.
- **light:** reds darken strongly.
- **hue:** blue-cyan/cyan rotate toward cyan, and reds go slightly toward
  magenta for the "cold" feel.
- **tone:** H +4, S −3 and contrast +3 match the steepest measured mid-tones.
- **Exposure:** IR suggests −1 EV.

### 4.9 ACROS (`acros`)
| | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sat | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| hue | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| light | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

| tone H / S / M | contrast | WB a_b / g_m | grain | vignette | stock-compatible |
|---|---|---|---|---|---|
| +1 / -2 / 0 | +1 | 0 / 0 | low | 0 | yes |

Stock fallback sat (hue and light 0): 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0

Base: **Monochrome Profile**, colour filter **blue, strength 1**.
- **Filter:** the LUT shows blues 8–9 L\* lighter and reds and oranges 6–8 L\*
  darker than BT.709 luminance.
- **Variants:** for ACROS+Ye/R/G use the E-P7 yellow, red or green filter
  instead (JSON `mono_filter_variants`).
- **Grain:** Low stands in for ACROS's inherent texture. Its structure is not
  reproducible.
- **Tone:** harder curve, hence H +1, S −2, contrast +1.
- **Caveats:**
  - Sector sat, hue and light are unused (0), because the mono path does not
    use the colour wheel.
  - The relative weighting assumes the E-P7 mono conversion is close to
    BT.709 luminance. That is unverified.
  - Confirm the E-P7 offers a blue filter. If it doesn't, use no filter.

### 4.10 Kodachrome 64, after Fuji X Weekly (`kodachrome_64`)
| | Ye | Or | OR | Re | Mg | Vi | Bl | BC | Cy | GC | Gr | YG |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| sat | 0 | 0 | 0 | +1 | +1 | -1 | -1 | -1 | +1 | -1 | -1 | -1 |
| hue | -2 | -1 | 0 | 0 | +3 | +1 | -2 | -4 | -2 | +2 | 0 | -2 |
| light | -3 | -3 | -2 | -3 | -1 | -1 | -2 | -1 | -1 | -1 | -3 | -2 |

| tone H / S / M | contrast | WB a_b / g_m | grain | vignette | stock-compatible |
|---|---|---|---|---|---|
| -1 / -2 / 0 | +2 | +3 / +1 | low | 0 | no |

Stock fallback sat (hue and light 0): 0, 0, 0, +1, +1, -1, -1, -1, +1, -1, -1, -1

This translates the [FXW X-T5 recipe](https://fujixweekly.com/2022/11/28/kodachrome-64-fujifilm-x-t5-x-trans-v/)
on top of §4.3:

| FXW setting | E-P7 translation |
|---|---|
| Color +2 | sat +2 on every sector |
| Color Chrome Effect Strong | extra −1…−2 lightness on yellow, orange, orange-red, red, green and blue |
| DR200 | highlights −1 (also consider EC −1/3) |
| Shadow +0.5 | shadows −2 instead of −3 |
| Clarity +3 | no equivalent; partly stood in for by contrast +2 |
| WB R+2 B−5 | amber +3, magenta +1 |
| Grain Weak/Small | low (colour grain, needs the mod) |

Kodachrome II and Portra 400 v2 (§2.5) can be built the same way from §4.3.

### 4.11 Validation plan
1. **Check the baseline.** Shoot a ColorChecker under daylight with E-P7
   Natural and the Color Profile at 0. Compare with a Fuji PROVIA JPEG of the
   same chart, or the PROVIA LUT applied to a log/raw rendering. This fixes the
   baseline offset.
2. **Calibrate the units.** Set single sectors to ±5 / ±7 and measure the
   per-step chroma (%), hue (°) and L\* changes. Calibrate `sim/pipeline.py`
   with them (the gains, the 2.75°/step and the lightness table are model
   assumptions).
3. **Tune each recipe in the simulator.** Re-derive each recipe by minimising
   ΔE against the Fuji LUT output on the §2.1 patch set, then confirm on real
   scenes.

---

## 5. Sources

**Fujifilm (primary)**
- Film simulation overview: <https://www.fujifilm-x.com/global/products/film-simulation/>
- PROVIA page: <https://www.fujifilm-x.com/global/products/film-simulation/provia/>
- REALA ACE: <https://www.fujifilm-x.com/en-us/products/film-simulation/reala-ace/>
- NOSTALGIC Neg.: <https://www.fujifilm-x.com/en-ph/products/film-simulation/nostalgic-neg/>
- ETERNA BLEACH BYPASS: <https://www.fujifilm-x.com/en-ph/products/film-simulation/eterna-bleach-bypass/>
- Classic Chrome story (Korean, 2014): <https://www.fujifilm-x.com/ko-kr/stories/film-simulation-classic-chrome/>
- X-Pro3 Stories #2, "Learning from Film" (Classic Neg.): <https://www.fujifilm-x.com/global/stories/x-pro3-stories-2-learning-from-film/>
- Color Chrome and grain effects: <https://www.fujifilm-x.com/en-gb/learning-centre/color-chrome-and-film-grain-effects>
- X-Pro3 product page: <https://www.fujifilm-x.com/products/cameras/x-pro3>
- 3D LUT downloads (source of the measured LUTs): <https://www.fujifilm-x.com/en-gb/support/download/lut/>

**Measurements and analyses**
- Imaging Resource, film simulation guide (Imatest ColorChecker): <https://old.imaging-resource.com/news/2020/08/18/fujifilm-film-simulations-definitive-guide>
- Imaging Resource, GFX 50S review (Color Chrome origin): <https://www.imaging-resource.com/cameras/fujifilm-gfx-50s-review/shooting-4>
- abpy/FujifilmCameraProfiles (community LUTs/DCPs): <https://github.com/abpy/FujifilmCameraProfiles>
- pixls.us, Classic Chrome HaldCLUT from ColorChecker shots: <https://discuss.pixls.us/t/classic-chrome-haldclut-like-the-x-t2-for-rt/1797>
- DIYPhotography, film simulation LUT release: <https://www.diyphotography.net/fujifilm-film-simulation-luts-video/>
- PetaPixel, F-Log2 film simulation LUTs: <https://petapixel.com/2025/11/18/fujifilms-new-f-log2-and-f-log2c-film-simulation-luts-look-fantastic>

**Fuji X Weekly and community**
- Kodachrome 64 (X-T5): <https://fujixweekly.com/2022/11/28/kodachrome-64-fujifilm-x-t5-x-trans-v/>
- Kodachrome 64 (X-T30): <https://fujixweekly.com/2019/08/02/my-fujifilm-x-t30-kodachrome-64-film-simulation-recipe/>
- Kodachrome II (X-Trans IV): <https://fujixweekly.com/2021/04/05/two-fujifilm-x-trans-iv-film-simulation-recipes-kodachrome-ii/>
- Kodak Portra 400 v2 (X-T5): <https://fujixweekly.com/2022/12/16/kodak-portra-400-v2-fujifilm-x-t5-x-trans-v-film-simulation-recipe/>
- Nostalgia Negative (X-T5): <https://fujixweekly.com/2022/11/22/nostalgia-negative-my-first-fujifilm-x-t5-x-trans-v-film-simulation-recipe/>
- Nostalgic Negative essay: <https://fujixweekly.com/2025/09/11/nostalgic-negative-makes-your-photos-feel-like-memories/>
- REALA ACE announcement: <https://fujixweekly.com/2023/09/12/new-reala-ace-film-simulation>
- D-Range Priority: <https://fujixweekly.com/tag/d-range-priority-2/>
- X100F dynamic range settings: <https://fujixweekly.com/2017/10/18/fujifilm-x100f-dynamic-range-settings/>
- Color Chrome Effect Blue: <https://fujixweekly.com/2020/06/30/fujifilm-x100v-new-feature-color-chrome-effect-blue/>
- Understanding CCE and FX Blue: <https://fujixweekly.com/2021/12/19/understanding-color-chrome-effect-color-chrome-fx-blue-videos/>
- jmpeltier, DR settings: <https://www.jmpeltier.com/fujifilm-dynamic-range-settings>
- jmpeltier, CC FX Blue vs polariser: <https://www.jmpeltier.com/fujifilm-color-chrome-blue-polarizing-filter-alternative/>
- Fuji Rumors, Nostalgic Neg. development story: <https://www.fujirumors.com/fujifilm-gfx100s-nostalgic-negative-development-story-recommended-settings-samples-exceeding-full-frame-fujifilm-x-lab/>
- fujilove, X-Pro3 features: <https://fujilove.com/?p=24193>

**Olympus side**
- PEN-F mono/colour profiles (mirrorlessons): <https://www.mirrorlessons.com/2016/04/22/olympus-pen-f-monochrome-color-profiles/>
- Project-internal: `sim/pipeline.py` (sector model, grain model), `generated/color/ep7_color_table.json` (sector geometry and gains)
