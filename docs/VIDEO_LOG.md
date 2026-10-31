# Log video profile on the E-P7 1.1

This is offline research only. Nothing here has run on a camera. No patch sources and no package
were produced, and nothing was committed. Addresses are CPU addresses in main (base `0x60020020`,
decoded SHA-256 `5dd9af16…6190`) unless marked otherwise.

Tools (ours, read-only):
- `tools/ep7_curve_scan.py` finds monotone u16 curve tables in every component.
- `tools/ep7_video_log_probe.py` runs native E-P7 selector code in fishcu's MN103 runner and analyses the curves.
  `--json` writes the full report. All 5 checks pass.

## Verdict

**True log looks feasible, and it appears to be already implemented but hidden. This is unconfirmed
until two things are traced: (X1) which setting feeds the hidden mode byte, and (X2) whether movie
frames actually go through the colour builder that implements it.**

The E-P7 main program contains two hidden picture modes with internal effect ids **2000** and
**2001**. They are selected by a "movie picture mode" byte (value 1 gives 2000, value 2 gives 2001).
Each one has a dedicated **log-shaped RGB gamma table** and a forced-identity luminance curve. They
reset contrast, sharpness, saturation and gradation, and at least six other ISP-configuration stages
special-case them. Id 2001's curve is a genuine log: about **12.4 % of output per stop, within 0.8 %
of a pure log2 line from −1 to −6 EV below clip**, with a linear toe below about −7 EV. It is fed
12-bit linear RGB with the full highlight range still present. This matches how Olympus shipped Flat
and OM-Log400 on other TruePic VIII bodies. Because X1 and X2 are still open, **no patch code was
written**, as the scope required.

## Verified facts (code, data, emulator)

### Two curve banks in main

| Bank | Address | Format | Role (evidence) |
|---|---|---|---|
| A | `0x604edc78`…`0x604f9c78` (+ `0x604f9e82`) | ~97 slots of 512 B, each 256 × u16, output 0…4095 | **RGB gamma**. `0x604edc78` is the identity curve (≈4095·k/255, so 12-bit in, 12-bit out, knot spacing 16 codes). The gamma selector writes one pointer to all three R/G/B slots at colour-output +2596/+2600/+2604 (`0x603ae7d3`). |
| B | `0x604f9e82`…`0x60500fb6` | ≈50 × 256 × u16, output 0…1023 | **Luminance tone** (PEN-F "256-knot tone LUT"). The selector is `0x603b039b`, reached via `0x603b092f`. |

The pointer table at `0x60530b6c` has **25 rows × 32 B**. Each row holds 4 columns × {normal, variant}.
The lookup helper is `0x603ae2fd`. The column comes from request+14: high nibble 0x40 selects +16;
high nibble 0x30 selects +8 or +24; low nibble 2…5 selects +8. The variant comes from flag
`0x603b5606`, which is a bit of request+48 chosen by the request type.

### Picture-mode tone selection (still development path, `0x603b1466` common builder)

- **RGB gamma `0x603ae354`.** Ordinary picture modes (effect id < 2000) all use **row 0**:
  `0x604ede78`, with variant `0x604ee078`. Row 1 is used when request+1879 ≠ 0 and is identity
  `0x604edc78`. Row 2 is used for gradation Auto (request+1797 = 2) and has lifted shadows.
  Art filters (ids `0x01xx00yy`/`0x0200xxxx`) dispatch through a hash switch at `0x60532110` to other
  rows. **Id 2000 gives `0x604f4278` and id 2001 gives `0x604f4478`** (switch keys 1 and 2, handlers
  `0x603ae61e`/`0x603ae627`). Those two tables have no other reference in main.
- Row 0 **is** the camera's base tone curve. With a 1.58× exposure scale it matches
  `sim/base_curve.json` (measured from real JPEGs) to RMS 0.025, against 0.156 for plain sRGB. Its
  input 1/8 of full scale maps to 46 % (8-bit 118), which is standard JPEG mid grey. **So metered
  18 % grey sits at about −3 EV below the gamma's input clip.**
- **Luminance tone `0x603b039b`.** The mode is mapped to a contrast family (ids 1→0, 2→1, 3→2,
  4/8→3, 5→4, 10→5, other ids→1), using the per-family offset bytes at `0x60500db0` = `0,0,−1,0,0,0`.
  Request+1796 (contrast) is added to that offset. The result selects one of these:

  | Selection | LUT |
  |---|---|
  | Contrast −3 | `0x604fb082` |
  | Contrast −2 | `0x604fb282` |
  | Contrast −1 | `0x604fa682` |
  | Contrast 0 | `0x604fa082` (≈ identity 4·k) or `0x604fa282` |
  | Contrast +1 | `0x604fa482` |
  | Contrast +2 | `0x604fb482` |
  | Ids 4/8, contrast −2…+2 | `0x604fb682`…`0x604fbe82` |
  | Id 10 | `0x604fae82` |
  | Gradation (request+1797 = 1), High Key by shape | `0x604fc082` |
  | Gradation (request+1797 = −1), Low Key by shape | `0x604fc282` |

  **Ids 2000/2001 always return `0x604fa082` (identity), whatever the contrast value is**
  (emulator check L1).
- Request fields are copied from the processing parameters in packer `0x60354ce4`: params+5522…5537
  go to request+1795…1815. When the effect id is 2000 or 2001, job setup at `0x60353fc7` **clears a
  124-byte block at +5056 and zeroes about 20 picture-parameter bytes in params+5522…5559.** Those
  bytes include the ones that become request+1796 (contrast) and request+1797 (gradation). OM
  manuals describe this same behaviour for Flat and OM-Log400, where sharpness, contrast, saturation
  and gradation are unavailable.
- Other stages that special-case 2000/2001, each with its own constants:
  - `0x603ab17f` (front end): tables `0x6050e410`/`0x6050e45a`
  - `0x603abffa`
  - `0x603ad01b`: `0x6050e4fa`/`0x6050e50c`
  - `0x603af5d9` (saturation offsets): `0x6050e998`/`0x6050e999`
  - `0x603b0e56` (tint/chroma): 2001 only
  - `0x603a32df`…`0x603a3b19`

  This is a complete pipeline personality, not a leftover table.

### Where 2000/2001 come from (emulator check E1)

`0x60349297` maps a settings record {hw picture mode, hw art, b4, b5, **b6**, b7} to the effect id.
**b6 = 1 gives 2000 and b6 = 2 gives 2001**. b5 ≠ 0 gives 2 (Natural). Otherwise the picture mode is
used. There are three callers:
- `0x60324da6` passes b6 through from `0x60316bc7`, which sets **b6 = 1/2 when settings
  byte +925 equals 1/2**. Settings +925 is also read at `0x6030c02f`, `0x60312f72`, `0x60313847`,
  `0x60314db8` and `0x6031691e` (change detection and mode checks).
- `0x603eaa71` hard-wires b6 = 0.
- `0x603ececd` hard-wires b6 = 0.

### Is "Flat" present?

- The OSD has `@A077@Flat` (2886) and `@A0C0@Flat` (3258). There is no "OM-Log", "Log" or
  "View Assist" string.
- Main has the SDK enum strings `COLORTONE_FLAT` (4th, between NATURAL and PORTRAIT) and
  `COLORTONE_SUPERFLAT`. The strings `E_MovPicMode`, `E_MovPicModeType` and `E_MovPicMode_MovieMode`
  are present.
- No ordinary picture-mode id (1…10) has a dedicated flat tone curve. Only 2000/2001 do.

### Curves (from `ep7_video_log_probe.py`)

Output fraction at 0…−8 EV below input clip:

| Curve | 0 | −1 | −2 | −3 | −4 | −5 | −6 | −7 | −8 | Log fit (−1…−6) |
|---|---|---|---|---|---|---|---|---|---|---|
| Row 0 (stock base) | 1.00 | .883 | .673 | .461 | .274 | .159 | .087 | .045 | .022 | not log: deviates 7 % |
| Id 2000 `0x604f4278` | 1.00 | .876 | .737 | .599 | .461 | .325 | .215 | .135 | .078 | 13.4 %/stop, max dev 1.4 % |
| Id 2001 `0x604f4478` | 1.00 | .888 | .760 | .634 | .510 | .382 | .273 | .184 | .106 | **12.4 %/stop, max dev 0.8 %** |

Id 2001 spends about 31.6 full-range 8-bit codes per stop, flat over 6 stops, then halves per stop
in the toe. Mid grey lands at 8-bit **162 / 130 / 97** if grey sits at −3 / −4 / −5 EV below clip.
Id 2000 is a flatter-gamma variant with a darker toe; by shape it is plausibly "Flat".

## Inferences (not proven)

1. **Ids 2000/2001 are the TruePic VIII "Flat" and "OM-Log400" movie modes**, most likely
   2000 = Flat and 2001 = OM-Log400. The evidence is the two-mode movie byte, the parameter lockout
   and the curve shapes, and the fact that the 2001-only tint stage matches OM-Log400's separate
   colour. The E-P7 UI never sets byte +925.
2. **The gamma input is linear and keeps the full highlight range.** The identity table and the
   default curve's mapping (1/8 of full scale → 46 %) show a linear 12-bit input. The default curve
   only reaches 4095 at input ≈0.94, so nothing upstream clips or knees before it. No earlier
   fixed-knee stage was found, but the 24 {0x800000, 0} pairs at colour-output +128…+316
   (`0x603ae709`) are unidentified.
3. **Precision is adequate.** The knot spacing is linear (16 of 4096), so knot 1 sits at −8 EV below
   clip and anything below it is a straight line from 0. That is a linear toe starting about 5 EV
   under grey (S-Log3's toe starts about 4 EV under grey). The hardware interpolation mode is assumed
   linear, as fishcu found for the luminance LUT. A 12-bit linear input carries about 12 stops, which
   is the sensor's raw depth. In the 8-bit H.264 output id 2001 gives about 31 codes per stop, the
   same class as the 8-bit OM-Log400 that the E-M1 II recorded.
4. **Movie frames use this builder.** This is likely but untraced. The mapper and the builder handle
   movie-only ids, art filters and picture modes, and these apply in E-P7 movie mode. The movie ISP
   job setup was not located.

## Precedent (web)

- **E-M1 Mark II (TruePic VIII) gained OM-Log400 through firmware 3.0 (19 June 2019)**, with 8-bit
  H.264 and no hardware change (Olympus release; CineD; Photoreview). The E-M1X had it from launch in
  January 2019.
- **The E-M5 Mark III (TruePic VIII, the E-P7's generation) shipped with Flat but no log profile.**
  Nothing was found showing log was added to it later.
- The OM-5 has OM-Log400 and uses TruePic IX.
- Conclusion: the ISP generation demonstrably supports 8-bit log through a firmware-defined gamma.
  Leaving it off the E-M5 III, E-M10 IV and E-P7 looks like product segmentation. The E-P7 code base
  still carries the implementation.

## Options

**A. Unhide 2000/2001 (preferred).** The aim is to make settings byte +925 reach 1 or 2 in movie
mode. That is either a menu or availability-mask change, or a tiny forcing patch in `0x60316bc7`.
Prerequisite X1 is to find the property and menu item behind +925 (its writer was not found; the
field is probably bulk-copied), plus any model mask. The patch could be data-only if a menu table
merely hides the value. Id 2001 has no UI label, so the "Flat" string (2886/3258) or a reused label
would be needed.

**B. Retune the dedicated table (only if A works or a hook exists).** `0x604f4478` (512 B) is
referenced only by `0x603ae629`, so a data patch to it changes **only** id 2001 and has no effect on
stock stills or video. Patching row 0 instead would change every ordinary picture mode, still and
movie, plus the other row-0 consumers at `0x603b16ed` and `0x603b1b6a`. Do not patch row 0.

Here is a curve for B, if a different grey placement is wanted. x is linear input (1 = clip) and
x_g = grey input. Then:

- y = 0.40 + s·log2(x/x_g) for x ≥ x_t
- y = y_t·x/x_t (linear toe, matched in value) for x < x_t

Set s = 0.60/h, where h is the stops over grey that should reach y = 1. Put the toe at
x_t = x_g·2⁻⁵ and clamp the result monotone. Encode as knot k = round(4095·y(16k/4095)).

With stock AE (x_g = 1/8, h = 3), s = 0.20 and the curve is very steep. Reaching +6 EV over grey needs
EC ≈ −3 (x_g = 1/64, s = 0.10), which leaves about 6 stops under grey before noise. Id 2001 as
shipped already corresponds to grey at about −5 EV (y ≈ 0.38) with EC ≈ −2.

## Risks

- 8-bit 4:2:0 H.264: about 31 codes per stop means banding in skies and walls when graded hard.
  OM-Log400 has the same limitation.
- The Y range (full 0–255 or limited 16–235) was not traced.
- Sharpening and NR strength under 2000/2001 come from their own tables and are not evaluated.
- AE is unchanged. Without about −2 EV of exposure compensation, the log maps grey to 8-bit ~160.
  It is unknown whether the code applies an OM-Log400-style ISO 400 floor or exposure offset for
  2001.
- The live-view preview is log too (flat image), and there is no View Assist.
- If byte +925 persists in settings and a later firmware or menu doesn't expect it, the camera could
  be left in an odd state. Forcing it in stills could also leak 2000/2001 into JPEGs, although the
  pipeline does handle them.
- The movie path is unconfirmed (X2). The ids might be honoured in stills but not in the movie
  pipeline, or the reverse.
- Any change goes through the SD updater. Its risks are covered in `docs/SD_UPDATE.md`.

## Next steps

1. **X1.** Find the property and menu that write settings +925. Trace the snapshot builder that feeds
   `0x60311641`/`0x60312fbd`, and the menu items showing OSD 2886/3258.
2. **X2.** Locate the movie ISP job setup and confirm it reaches `0x603ae354` and `0x603b039b`
   (callers `0x603ae82b`, `0x6039a98a`) with the movie effect id.
3. Only after X1 and X2: write `patches/video_log/` (Option A first) and verify with
   `ep7_video_log_probe.py`-style emulator runs, patched against stock.

Sources: [Olympus press release, firmware 3.0](https://www.olympusamerica.com/press-release/2019-06-19/olympus-announces-firmware-upgrades-enhancing-autofocus-performance-and),
[CineD on E-M1 II fw 3.0](https://www.cined.com/es/olympus-om-d-e-m1-mark-ii-firmware-update-3-0-brings-flat-picture-profile-and-more/),
[Photoreview fw 3.0](https://www.photoreview.com.au/news/firmware-updates/firmware-updates-for-olympus-om-d-e-m1-mk-ii-and-om-d-e-m1x/),
[Newsshooter E-M5 III launch (Flat, no log)](https://newsshooter.com/2019/10/17/olympus-releases-om-d-e-m5-mark-iii),
[OM manual: Flat/OM-Log400 lock out sharpness/contrast/saturation/gradation](https://learning.omsystem.com/OM-5MarkII/zz_html_manual/en/movie_picture_mode_view_assist_137.html),
[OM-5 spec sheet](https://magazine.e-group.uk.net/pages/wp-content/uploads/2022/10/Specifications_OM-5_EN.pdf).
