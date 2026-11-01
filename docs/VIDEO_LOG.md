# Log video profile on the E-P7 1.1

This is offline research only. Nothing here has run on a camera. Nothing was committed. The
follow-up (2026-11-01) produced `patches/video_log/` (edits spec + emulator verification) but no
SD-named file. Addresses are CPU addresses in main (base `0x60020020`,
decoded SHA-256 `5dd9af16…6190`) unless marked otherwise.

Tools (ours, read-only):
- `tools/ep7_curve_scan.py` finds monotone u16 curve tables in every component.
- `tools/ep7_video_log_probe.py` runs native E-P7 selector code in fishcu's MN103 runner and analyses the curves.
  `--json` writes the full report. All 5 checks pass.

## Verdict

**X1 is resolved (verified): +925 is derived from two hidden properties, `0x4501` (setting 382,
MovPicModeType 0/1) and `0x91b1`[0] (setting 323, MovPicMode 254 = Flat → id 2000, 255 = OM-Log →
id 2001). No E-P7 menu writes either property; no menu table, mask or setter was found.** X2 is
partly verified: the +925 value reaches the effect-id mapper only on the live-view/movie
development path (stills hard-wire b6 = 0), and the ISP job builder that consumes the effect id is
shared with stills; the IPC hop between them is inferred. An option-A patch (5-byte hook + 42-byte
stub) is built and emulator-verified: in movie mode with a chosen picture mode (default Muted),
+925 becomes 2 and the gamma/luma selectors return `0x604f4478` / identity. Not tried on a camera.

Background (first pass): the E-P7 main program contains two hidden picture modes with internal
effect ids **2000** and **2001**, selected by settings byte +925 (1 → 2000, 2 → 2001).
Each one has a dedicated **log-shaped RGB gamma table** and a forced-identity luminance curve. They
reset contrast, sharpness, saturation and gradation, and at least six other ISP-configuration stages
special-case them. Id 2001's curve is a genuine log: about **12.4 % of output per stop, within 0.8 %
of a pure log2 line from −1 to −6 EV below clip**, with a linear toe below about −7 EV. It is fed
12-bit linear RGB with the full highlight range still present. This matches how Olympus shipped Flat
and OM-Log400 on other TruePic VIII bodies.

## Follow-up: X1, X2, option A (2026-11-01)

### X1 — where +925 comes from [verified, static unless noted]

Chain, writer to reader:
1. **Properties.** `0x4501` (setting 382, index 0) = MovPicModeType; `0x91b1` (setting 323, index 0;
   indices 1–6 = settings 670–675) = MovPicMode. `0x6030b3f8` reads both directly:
   `0x4501 == 1 && 0x91b1[0] == 255` is the OM-Log test. `0x6028e27f/0x6028e2ad` test
   `0x4501 == 1 && 0x91b1[1] == 1` (meaning of index 1 unknown; possibly View Assist).
2. **Capture-request builder `0x60407b58`** (R = arg+8): S+81 = R+1 (movie flag), S+82 = R+33 only if
   R+1 == 1, S+83 = R+34. The default builder `0x60407cec` writes S+82 = 0, S+83 = 254.
3. **Message handler `0x6054d116`** (registered at `0x6054cb68`): A+8 = S+69, A+332 = S+81,
   **A+352 = S+82, A+353 = S+83** (else 0/0/0/254 at `0x6054d403`). A = msg+60 is passed to
   `0x60303ef6` → `0x603263c7`.
4. **Validation `0x6030c4c2`**: A+352 ∈ {0,1}, and if 1 then A+353 ∈ {254,255}; otherwise the error
   tags `E_MovPicModeType` / `E_MovPicMode` (strings `0x604e0c65/0x604e0c7a`).
   `0x6030d8e6`: type 1 with 254/255 but A+332 ≠ 1 → `E_MovPicMode_MovieMode`. **So A+332 == 1
   means movie mode.** A+352…+369 is also copied to record +292…+309.
5. **The only writer of +925: `0x6030df3d`** (called once, `0x6032641f`, a1 = rec68+13):
   +13 = 1 if A+352 == 1 && A+353 == 254; = 2 if A+352 == 1 && A+353 == 255 && A+8 == 0; else 0.
6. rec68 (68 B, picture mode at +29 from property `0x9481` via pointer table `0x604e2260`) is
   queued by `0x6030da2f` into an 8-slot ring at `0x62039f4c`, dequeued by `0x6030b1a4`, and
   `memcpy`'d (68 B) to record +912 at `0x6030cc4f`. **rec68+13 = record +925.** The 980-byte
   records live at `0xa2731098 + 980·k` (current index `0xa273104c`). No direct store with
   displacement 925 exists anywhere in main.

Range: 0/1/2 only. Setting IDs 323 and 382 are absent from the conversion-descriptor table
`0x604cd5f8` (so is picture mode 111; that table is not a menu list). No GUI-section code reads keys
`0x4501`/`0x91b1`; every reader is in sec 1/2 (settings, AE, capture). OSD strings for the menu exist
but are orphaned: 2872 `@A006@Picture Mode` (movie icon + "Picture Mode"), 2880 "Select this
[movie] exclusive mode for shooting video footage to be edited post-shoot.", 2886 `@A077@Flat`,
3258 `@A0C0@Flat`. No "OM-Log" or "View Assist" string. **Conclusion: no hidden menu entry to
unmask; option A needs code.** (A GUI menu-table search by settings ID was not done exhaustively.)

### X2 — movie frames and the builder

Verified (static call graph + emulator):
- +925 → `0x60316bc7` (b6 = 1/2) → `0x60324d6b` → mapper `0x60349297` → id 2000/2001. Run natively
  end to end in `patches/video_log/build_and_verify.py` (check M), then `0x603ae354` →
  `0x604f4478` and `0x603b039b` → `0x604fa082` (identity) for id 2001.
- `0x60316bc7` is reached only from the record path: `0x603114e0` (record → 40-byte development
  request, template `0x604e172c`, callback `0x60306ad5`, sent via `IPCR` `0x60321d3b`) and
  `0x60312f42` (callers `0x60312785`, `0x6031b1a7`, `0x6032ba6d`).
- **Stills cannot get 2000/2001:** the still converter family (`0x603e62d1`, `0x603e8af1`,
  `0x603eacf6`, `0x603f1b23`) calls the mapper through `0x603eaa04`, which passes b6 = 0; RAW
  development uses `0x603ecd3b`, also b6 = 0.
- ISP job path: `0x603323f6` (sequencer, "RECVIEW" tags in `0x6033260c`) → `0x60332d44` →
  `0x6031e502` → `0x603250c4` → `0x60325396` → `0x6031106f` (job at `0xa27326fc`) → `0x60322c28`
  → `0x60350eff` → `0x60351174` → `0x6039a97b` → `0x603ae354`. `0x60350eff` is also called by the
  still jobs (`0x603e8af1`, `0x603eacf6`). A second route `0x603397e0` → `0x603aaced` →
  `0x603b1466` → `0x603ae80d` → `0x603ae354` exists.

Inferred: that the development request built by `0x603114e0` is what fills job+12 (request+8, the
effect id) on the receiving side of the IPC, for both movie-mode live view and recording. The exact
consumer of the IPCR message was not traced.

### Option A design (built, emulator-verified, not camera-tested)

No menu exists, so the smallest change is in the single +925 derivation:

| Site | Stock | New |
|---|---|---|
| `0x6030df3d` (5 B) | `26 60 01 f1 72` (`mov 352,a2; add a0,a2`) | `dc` rel32 → `jmp vlog_hook` |
| `0x60210c90` (42 B, sec-1 FF tail, loads before sec 2) | FF | `vlog_hook` |

`vlog_hook`: if A+352 == 0 (stock type off) **and** A+332 == 1 (movie) **and** picture mode
rec68[29] == `--trig-log` (default 3 = Muted, *inferred id*) → result 2 → `jmp 0x6030df67`
(stock `movbu d0,(a1); retf`). Optional `--trig-flat N` gives result 1 (id 2000; 53 B). Anything else
replays the displaced instructions and rejoins stock at `0x6030df42`. Claimed in
`docs/CODE_SPACE_MAP.md` (sec-2 tail was taken by bloom).

Emulator results (`python3 -I patches/video_log/build_and_verify.py`, writes `edits.json`,
`verify.json`, `routine.lst`; `tools/build_package.py` accepts the spec):
- H, stock vs patched +925: movie + Muted 0 → **2**; stills + Muted 0 → 0; movie + Natural/COLOR/
  MONO/art 0 → 0; A+332 = 2 → 0; stock type 1/254 → 1/1 (stock wins); 1/255 → 2/2; 1/255 with
  A+8 = 1 → 0/0; invalid 1/7 → 0/0. Return, sp and a2 intact.
- M/G/L (stock and patched images): +925 0/1/2 → ids 2/2000/2001 → gamma `0x604ede78` /
  `0x604f4278` / **`0x604f4478`**; luma for 2000/2001 = **`0x604fa082`** (identity) at contrast +2.

Picture-mode ids [inferred]: 1 Vivid, 2 Natural, 3 Muted, 4 Portrait, 5 i-Enhance, 6 Custom
(re-resolved through `0x9d11` at `0x60326793`), 8 e-Portrait, 10 Color Creator, 11 COLOR,
12 MONO. Basis: contrast families, Natural as the stock default (A+354 = 2), and the Custom
re-resolve. Confirm on camera before relying on "Muted".

### Side effects

Verified:
- **Stills:** cannot use 2000/2001 (b6 = 0 in all still/RAW mapper callers). The hook also needs
  A+332 == 1.
- **Settings backup:** the patch writes no property. +925 is recomputed from the message on every
  settings update; nothing persists. Properties `0x4501`/`0x91b1` stay stock.
- **AE/ISO:** the firmware's log-specific exposure logic keys on the *properties*, not +925:
  `0x6030b3f8` (keys `0x4501`/`0x91b1` directly) and AE struct +41/+42 (`0x6016e771`, from the AE
  property table, entries 28/22). At `0x6015f9fd`, OM-Log skips the AE offsets −76 (when +17 ≠ 0)
  and ±128 (when +11 = ±1); `0x6015ebe8` has a mode-3 + log branch that compares against 2048
  (ISO/limit, meaning not confirmed). **With the patch none of this engages: AE, ISO floor and
  metering are those of the trigger picture mode. Use about −2 EV compensation manually.**
- Other +925 readers behave as in stock log: `0x60312f72` clears a flag when +925 ≠ 0;
  `0x60308601` exports +925 when record +807 == 1 (consumer at `0x6032d469`, purpose unknown;
  possibly movie metadata); `0x6031d452` copies rec68+13 onward.

Inferred / unknown:
- EXIF/makernote: JPEGs are unaffected (still path). The movie file's picture-mode tag will
  most likely say Muted; whether `0x60308601`'s export ends up in movie metadata is unknown.
- The stock log path also forces an internal picture-mode copy to 2 (`0x6030d90a`); the patch
  does not, but job setup zeroes the picture parameters for 2000/2001 anyway (`0x60353fc7`).
- A+8 (S+69), which gates 255 in stock, is not identified; the patch ignores it.
- Movie-mode live view should also show log (same record path); there is no View Assist.

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
4. **Movie frames use this builder.** Now partly verified (see X2 above); the IPC hop is still inferred. Original note: likely but untraced. The mapper and the builder handle
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

**A. Unhide 2000/2001 (preferred; now built, see "Option A design").** The aim is to make settings
byte +925 reach 1 or 2 in movie mode. Original plan: That is either a menu or availability-mask change, or a tiny forcing patch in `0x60316bc7`.
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

1. On-camera test of `patches/video_log` (human-approved; SD_UPDATE.md risks apply): movie mode +
   Muted should give a flat/log image; stills in Muted unchanged; picture-mode ids confirmed.
2. Optional: trace the IPCR consumer of `0x603114e0`'s request to close X2 statically.
3. Optional: a real menu (Off/Flat/OM-Log) writing `0x4501`/`0x91b1`, which would also engage the
   firmware's own log AE logic. Needs the settings setter path and a GUI menu table: large.
4. Option B (retune `0x604f4478`) remains independent and data-only.

Sources: [Olympus press release, firmware 3.0](https://www.olympusamerica.com/press-release/2019-06-19/olympus-announces-firmware-upgrades-enhancing-autofocus-performance-and),
[CineD on E-M1 II fw 3.0](https://www.cined.com/es/olympus-om-d-e-m1-mark-ii-firmware-update-3-0-brings-flat-picture-profile-and-more/),
[Photoreview fw 3.0](https://www.photoreview.com.au/news/firmware-updates/firmware-updates-for-olympus-om-d-e-m1-mk-ii-and-om-d-e-m1x/),
[Newsshooter E-M5 III launch (Flat, no log)](https://newsshooter.com/2019/10/17/olympus-releases-om-d-e-m5-mark-iii),
[OM manual: Flat/OM-Log400 lock out sharpness/contrast/saturation/gradation](https://learning.omsystem.com/OM-5MarkII/zz_html_manual/en/movie_picture_mode_view_assist_137.html),
[OM-5 spec sheet](https://magazine.e-group.uk.net/pages/wp-content/uploads/2022/10/Specifications_OM-5_EN.pdf).
