# Per-profile tone: Blacks / Whites and per-look H/S/M (E-P7 1.1): research and plan

Offline research only. Nothing was built, flashed or committed as firmware. No package, card file or web-app
format changed. [V] = read from the decoded main (`tools/dis.sh`, byte dumps) or run natively in the emulator
this session. [I] = inference.

Asked for: per-slot **Blacks** and **Whites** (−5..+5, moving the two ends of the tone curve, which stock
Highlight/Shadow never moves), per-look **Highlight/Shadow/Midtone offsets** on top of the user's global tone,
edited on the stock tone-control screen as a third INFO page.

**Verdict:** the curve side is feasible, and it is a clean per-job hook (§1–§3). It was **not built in this
pass.** The rest of the scope (UI page, card and LOOKS.BIN format bump, per-look H/S/M at the stock job-setup
stage, web app, library values) needs more mapping and its own emulator verification before it meets the
"high confidence, anti-brick" bar (§5). §6 is the build plan.

## 1. How the stock tone curve is made

The still and live-view development stage list is `0x603b1466` (run by `0x603b17e6`/`0x603b1819` for request
kinds 0/16). Its colour/tone part, in order [V]:

| Call site | Function | Role |
|---|---|---|
| 0x603b14ec | `0x603af7c6` | knee/clip words (output+124), reads the tone block |
| 0x603b14f3 | `0x603b0252` | COLOR selector + builder (the bundles `hl` / `lv` hooks live here) |
| **0x603b14fa** | **`0x603b0a70`** | **luminance tone LUT builder** |
| 0x603b1501 | `0x603b0c66` | next stage (not tone) |

The RGB gamma (bank A, `0x603ae354`, docs/VIDEO_LOG.md) is a ROM pointer per R/G/B and is never generated.

### 1.1 The luminance LUT builder `0x603b0a70` [V]

`a0` = development context `C`; `C+4` = request `R`, `C+12` = colour output `O`.

1. If `R+1524` (art override) is set, `O+2608` = that object's +8 LUT, done.
2. Else if `C+60` has the tone bit, `0x603b092f` → `0x603b039b` picks a ROM LUT from contrast (`R+1796`),
   gradation (`R+1797`) and the effect id (table in VIDEO_LOG §"Picture-mode tone selection"). Some keys
   (0x0101 bloom passes, `R+1838` = 257, format 0xF00D) return **no LUT** (`O+2608` = 0) and the function
   returns early. `0x603b092f` may compose the LUT through a second ROM table into `O+2612`.
3. Art filters (effect ids 0x01010064/65/69, 0x01020069, 0x01030069) bend the LUT with the art strength
   `R+1832` (−5..5) through spline helpers `0x603b098f`…`0x603b0a43` and write it to `O+2612`.
4. **Tone control.** If `0x6034fc27(R+1512)` (any of the 5 tone halfwords non-zero), the LUT is copied into the
   job buffer **`O+2612`** (if it is not there already), `0x6034ff93(O+2612, C+64, R+1802 bit7)` bends it in
   place, and `O+2608` = `O+2612`.

The register writer `0x60346ecb…0x60346fd5` (next to the COLOR writer) reads `O+2608` and expands the 256
halfwords into 32-bit hardware words. `O+2612` is 512 B, ending exactly at `O+3124` (the next field, zeroed by
the output initialiser `0x60343fd5`) [V].

### 1.2 Curve format [V]

- 256 × u16. The input is the knot index (luminance after the RGB gamma, so **display/gamma domain**, 16 codes of
  the 12-bit gamma output per knot). The output is **10-bit, 0…1023**, monotone.
- Contrast 0 LUT `0x604fa082`: k = 0 → 0, 64 → 257, 128 → 514, 255 → 1023. Contrast +2 `0x604fb482`:
  64 → 213, 192 → 817, 240 → 1010. Endpoints stay 0 and 1023 in every stock LUT seen.

### 1.3 Where Highlight/Shadow/Midtone go [V unless marked]

- Settings: capture builder `0x602a84e5…` reads properties 0x3719, 0x3739 and 0xEFC9 with the getter
  `0x6005e971` into capture+24781/24782/24783 (signed bytes). Stills converter `0x603eabfb` copies them to the
  job's **tone block** params+5056 (+4, +6, +8 as s16; +122 enable byte; +10.. a 56-halfword table from
  `0x602885f3`). Live view fills the same block from R+1656 (`0x603237bd`, call at 0x603241dd). The packer sets
  `R+1512` = params+5056 when +122 ≠ 0; `0x6034fca0` copies the 5 halfwords to `C+64`.
- **The visible effect is in this LUT [V, emulator].** Context init `0x60344976` (request kinds 0/16 →
  `0x60344a5f`) calls `0x6034fcd2(R+1512, C+64)` at 0x60344a9b/0x60344aae: the raw −7..7 values are scaled by
  4096/7 and mixed through `0x6034f92e` (ROM gains at `0x604eb430`) into 8 spline-knot deltas at C+64, which
  `0x6034ff93` adds to the LUT knots. At ±7 (contrast-0 LUT): Highlights (+4) moves k = 160/192/224 by
  ±60/±117/±95; Shadows (+8) moves k = 16/32/64 by ±65/±109/±96; Midtones (+6) moves the middle by up to ±235.
  `0x603b5769` / params+4466 only carry a Kelvin-like value (block+2), not H/S/M.
- **H/S/M are already per Colour Profile** (settings 963/964/965 = COLOR1 HL/MID/SH, 966–968 COLOR2, 969–971
  COLOR3, 1672–1674 COLOR4; 891–893 for ordinary modes; mirrors 384 HL / 694 MID / 383 SH refreshed by
  `0x602b8916` when the profile is active) [V for COLOR1, I for the others' stores]. So per-look H/S/M need no
  firmware curve code: a Film pick can write the profile's own stock settings through the settings manager
  `0x60827440` (the look editor's `ed_set` route), and the stock tone screen already edits them per profile.
- Endpoints never move: k = 0 stays 0, k = 255 stays 1023.

So **stock tone control never moves the black or white point**, and Blacks/Whites are a new control, not a
re-scaled Shadow/Highlight.

## 2. Answers

**(a) A per-job generated curve buffer exists: yes [V].** `O+2612` (256 × u16 in the colour output, part of the
job context, not image RAM) plus its pointer `O+2608`. Stock already does exactly the needed pattern (copy the
ROM LUT in, bend it, point `O+2608` at it). A post-builder hook can do the same. Emulator run this session:
H = 0 gives `O+2608` = `0x604fa082` (ROM); a non-zero tone block gives `O+2608` = `O+2612` with the bent copy.

**(b) Format:** 256 knots, u16, 10-bit out, gamma domain (§1.2).

**(c) Live view uses the same builder [V call graph, I strong for the route].** There is one stage list and one
builder; the COLOR coefficients are already shown to take this same route for LV (docs/LV_BUNDLES.md §2.1),
and the LV request fills the same tone block (`0x603237bd`). A remap on `O+2612` would reach the preview.

**(d) Cost:** one pass over 256 halfwords (copy if needed + remap), about 3–4 k instructions per development:
once per still, and once per LV re-development (setting changes), not per pixel. Negligible.

## 3. Hook design (curve side, ready to build)

- **Site:** `0x603b14ff` `mov d3,a0; call 0x603b0c66,[d2,d3,a2,a3],72` (7 B) → `jmp tone` + 2 × `nop`.
  `tone` re-issues `call 0x603b0c66` with the same mask/frame after its own work and jumps to `0x603b1506`.
  `d3` = context (stage-list callee-saved). The luminance builder has 3 exits, so hooking the stage list after
  it is simpler and safer than its epilogues.
- **Gates (all must hold, else replay only):** `O+2608` ≠ 0 (no LUT → leave alone: bloom/mask passes, art
  override); request key 11 (COLOR); the same job / profile resolution as the bundles readers (stills: the
  `hl` callback/record/parent guard and marker 0xB2 → job+15488 profile; live view: `lv`'s getter
  `0x6005e971(0xF6B1)`); COLOR1–4 slot of the active table with Blacks or Whites ≠ 0 and in range.
- **Remap** (both ends, monotone by construction, 0 = byte-identical):
  `lo = 8·B` for B > 0 (lift, up to 40 codes ≈ 4 % at +5) and `y' = y` with a toe crush for B < 0
  (`y' = max(0, y − c·(1 − y/1023)^3)`, c = 12·|B|); `hi = 1023 − 10·W` for W < 0 (roll-off) and a shoulder push
  for W > 0 (`y' = min(1023, y + c·(y/1023)^3)`). Then `y' = lo + (y − 0)·(hi − lo)/1023` for the end-point
  moves. Integer only, using `y` from the stock LUT (so contrast, gradation, tone control and art bends are
  all kept), and a final running max so the curve stays monotone. Copy ROM → `O+2612` when `O+2608` ≠
  `O+2612`, then `O+2608` = `O+2612`.
- **Code size** about 200–260 B; placement must come from docs/CODE_SPACE_MAP.md (e.g. a further dead EVF
  step table, as `lv`).

## 4. The tone-control screen (UI) [V static, no emulator]

- It is **not** one of the 47 wheel/list editors (descriptor table 0x61186ba4). It is a `Direct_Actuator`
  (creator 0x60df002e, constructor 0x60df008b, vtable 0x61159ea8, shared with a type-3 actuator built by
  0x60def0f4; discriminate on obj+216 in 0x611595a8..0x6115979f).
- Rows: 9 × 56 B at 0x611595a8 (default, COLOR1–4, MONO1–4, picked from setting 111), 2 pages × 7 u32 of setting
  ids (page 0 HL/SH 891/893-style, page 1 MID). obj+220 page count (set to 2 at 0x60df0173), obj+222 page.
- Settings: HL/MID/SH per family (§1.3), all −7..+7; the page lives in **setting 1088** (384/383 = page 0,
  694 = page 1).
- Events: Up/Down 0x60def466/0x60def563, Left/Right 0x60def6bb/0x60def70a, dials 0x9032 → 0x60def75a (Shadows on
  page 0), 0x9031 → 0x60def91e (Highlights); INFO 0x9014 via the hash table 0x61159e28, handler word 0x61159e74
  → 0x60defcd8 (toggles 1088 between 694 and 384).
- The graphic is pre-drawn: a sign code from 384/383/694 picks one of 27 images (table 0x61189734). Page writer
  0x60e27639 (call at 0x60e26bb3); guide strings 2778 `Hi. & Sh.[INFO]`, 2779 `Midtone[INFO]`.
- **Verdict: moderately risky for a third page.** The two-page rule is hard-coded in four places (INFO toggle,
  constructor restore 0x60df01be, touch handler 0x60df0332, page writer test 0x60e276f8); the row tables are
  packed (a third row means moving all nine); our values would need fake ids that the availability check turns
  into "none" (dead dials), so page 3 would need its own input handlers; and the vtable is shared. The curve
  graphic cannot show moved end points (fixed bitmaps). **So v0.19 uses the fallback:** Extras sectors 6
  "Blacks" and 7 "Whites" in the Colour Profile editor. The stock tone screen keeps editing H/S/M, which are
  per profile already, so a look's H/S/M picked from the Film page show there directly.

## 5. Decisions for v0.19

- Blacks/Whites: slot +47/+48 (s8 −5..5, COLOR slots), applied by the post-builder hook (§3).
- H/S/M per look: LOOKS.BIN v4 carries them; a Film pick writes the profile's stock settings (§1.3).
- LOOKS.BIN v4: version 4, record length 80 = v3 record + tail (+64 B, +65 W, +66 H, +67 S, +68 M, rest 0);
  v3 files still load (tone untouched). BUNDLES.BIN: +47/+48 accepted, old files unchanged.
- UI: Extras sectors 6/7 (labels `6 Blacks +2`, `7 Whites -1`); Vignette's planned sector moves to 8.
