# Per-profile tone: Blacks / Whites and per-look H/S/M (E-P7 1.1): research and plan

Offline research only. Nothing was built, flashed or committed as firmware. No package, card file or web-app
format changed. [V] = read from the decoded main (`tools/dis.sh`, byte dumps) or run natively in the emulator
this session. [I] = inference.

Asked for: per-slot **Blacks** and **Whites** (−5..+5, moving the two ends of the tone curve, which stock
Highlight/Shadow never moves), per-look **Highlight/Shadow/Midtone offsets** on top of the user's global tone,
edited on the stock tone-control screen as a third INFO page.

**Status (v0.19, emulator-verified, camera test pending):** built as `releases/v0.19` (§6, §7): the per-slot
Blacks/Whites curve hook, the SD loader accepting slot +47/+48, and Extras sectors 6 "Blacks" / 7 "Whites" in the
colour editor. **Deferred:** the tone-screen third INFO page (moderately risky, §4), LOOKS.BIN v4 and a Film pick
that applies a look's tone (H/S/M settings + B/W); until then a Film pick zeroes the slot's Blacks/Whites (the
v3 placement writes bytes 32..63 = 0), and the card's BUNDLES.BIN carries the library B/W for its COLOR slots.

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
- H/S/M per look (deferred): LOOKS.BIN v4 carries them; a Film pick writes the profile's stock settings (§1.3).
- LOOKS.BIN v4 (deferred; tools/web app drafts only): version 4, record length 80 = v3 record + tail (+64 B, +65 W,
  +66 H, +67 S, +68 M, rest 0); v3 files still load (tone untouched). BUNDLES.BIN: +47/+48 accepted (v0.19
  loader), old files unchanged; v0.18 firmware rejects a BUNDLES.BIN with non-zero Blacks/Whites.
- UI: Extras sectors 6/7 (labels `6 Blacks +2`, `7 Whites -1`); Vignette's planned sector moves to 8.

## 6. T1 built: curve hook (stage 1 of v0.19)

Status: **built and emulator-verified on the v0.18 base; not released, not camera-tested.** Card files cannot carry
the values yet: the v0.18 SD loader range table requires slot bytes 47..63 = 0, so until T3 the layer is inert
on the camera (the flashed table is all zero there too).

- Build: `.venv/bin/python -I patches/tone_ends/build.py` (default `--base releases/v0.18/edits.json --out
  generated/tone_ends`). Byte-level layer: nothing of the base is rebuilt. The base's bundles reader is checked
  (labels, the job-ABI constants inside its `hl` bytes, the v3 accessor `tbl_idx` = 0x6055e7b0 found from its code).
- Verify: `.venv/bin/python -I tools/ep7_verify_tone_ends.py --jobs 8 --json generated/tone_ends/verify.json`
  (inside `systemd-run --user --scope -p MemoryMax=12G -q`; about 25 s).
- Reference model: `tools/ep7_tone.py` `remap(lut, B, W)` (no dependencies; for sim/ and the web app). The
  verifier checks the camera code against it bit-exactly.

### 6.1 Edits

| Site | Stock | New |
|---|---|---|
| 0x603b14ff (7 B) | `f1ec cd65f7f048` mov d3,a0; call 0x603b0c66,[d2,d3,a2,a3],72 | `dd rel32 f048` call tone,[d2,d3,a2,a3],72 |
| 0x601e103c (212 B) | dead EVF step-14 B gamma LUT | piece A: gate + profile resolution |
| 0x601e133c (235 B) | dead EVF step-13 B gamma LUT | piece B: range rule, copy, remap |

The hook is a d32 call with the stock register list, frame and return address, so `tone` runs inside the frame the
stock call makes, then replays `mov d3,a0` and jumps to 0x603b0c66, which returns to 0x603b1506 itself. The return
word, the saved registers and MDR are what stock leaves (§3 planned a jmp + re-issued call; this variant leaves
the live stack byte-identical). 0x603b1501 is no longer an instruction start: the only brute-force hit is operand
bytes inside the call at 0x603b150f (checked by linear disassembly). The code did not fit one 256-B table, so it
is split over two dead EVF B tables, each referenced only by its step-table word (0x601e3d68, 0x601e3d58).

### 6.2 Semantics

- Gates, in order: O+2608 ≠ 0; request in a job (callback / record / parent guard, as `hl`/`lv`); request key
  word R+8 == 0x000b0000 (key 11, COLOR; same value as the selector's composed key); capture job (marker 0xB2):
  job+15489 == 11 and profile = job+15488 (as `hl`); otherwise (live view): some COLOR slot has byte 47 or 48
  ≠ 0, then profile = getter 0x6005e971(0xF6B1, 0, 0) (as `lv`; never called while every COLOR slot is 0);
  profile 1..4 → COLOR slot 0..3 via tbl_idx (SD-loaded or flashed table).
- Slot bytes: **+47 Blacks, +48 Whites, s8 −5..5**. A value outside −5..5 counts as 0 for that field (the other
  field still applies). B = W = 0 → no copy and no store. Bytes +49..+63 are ignored (stock H/S/M are already
  per-COLOR-profile settings, so the hook carries no H/S/M). No flags bit is needed: the bytes alone switch it on.
- Remap (on the active LUT, so contrast, gradation, tone control and art LUTs are kept): toe crush
  `y −= 12|B|·cube(1023−y)` for B < 0, shoulder push `y += 12W·cube(y)` for W > 0 (cube(t) = ((t²>>10)·t>>10)>>10,
  clamped 0..1023), then `y = lo + ((y·(hi−lo)·1025 + 0xFFFFF) >> 20)` with lo = 8B (B > 0), hi = 1023 − 10|W|
  (W < 0), then a running max. So y[0] = 8B for B > 0 (up to 40 codes) and y[255] = 1023 − 10|W| for W < 0 (down
  to 973); B < 0 / W > 0 keep the end points 0 / 1023 and bend the toe / shoulder (about 12 codes per step at the
  ends, a few codes at mid-grey).
- **Idempotent (v0.19 fix after the camera test: LV compounded).** The builder leaves O+2608 alone when it does
  not rebuild (C+60 & 0x8268063e = 0 and no art override R+1524), so in live view O+2612 can still hold the last
  pass's remapped LUT. The hook remaps when O+2608 ≠ O+2612 (a pristine ROM/art LUT) or when the builder rebuilt
  this pass; otherwise it leaves the LUT as it is. Limit: B/W edited with no rebuild show at the next rebuild
  (when O+2612 holds stock tone control's own bend). Verify part R: repeated passes == one pass.
- Like the stock tone-control step: copy the LUT to O+2612 if O+2608 points elsewhere, remap in place,
  O+2608 = O+2612, clear O+4 bit 8.
- Registers all restored, MDR restored. Stores: own stack frame (48 B below the callee frame), O+2612..O+3123,
  O+2608, O+4 only. No store into 0x60020020–0x6191ffe0 (static audit; image regions read-only in the emulator).

### 6.3 Verification (generated/tone_ends/verify.json): 284/284 PASS

Real stage-list span 0x603b14f8 → 0x603b1506 natively (builder 0x603b0a70 with its real LUT selection and
tone-control bender, the hook, tone, real 0x603b0c66), real getter on a fixture registry, real tbl_idx.

| Part | What | Result |
|---|---|---|
| P | merged spec builds a package; base part == releases/v0.18 edits and reproduces its patched.pkg.bin; restore main == stock hash | PASS |
| S | hook bytes; stock bytes; no branch into the hook interior; only the step-table words reference the placements; store audit; changed bytes only in the 3 tone edits vs v0.18 | PASS |
| N | == v0.18 (output, job, context, live stack, all registers): B=W=0 stills/LV (registry unmapped: no getter call), only MONO slots set, out-of-range values, O+2608 = 0, keys 12 / 0x0100000b / 0x000b0000, MONO profiles 5/6/8, profile 0/255 (stills and LV), capture mode 12, wrong callback, foreign parent; SD-loaded subset | 27/27 |
| A | all 120 non-zero B×W at contrast 0; 48 at contrast −2 and +2; 9 with a non-zero tone block; 9 with an art override LUT: LUT == remap() bit-exact, monotone, y[0]/y[255] as specified, O+2608 = O+2612, O+4 bit 8 cleared, every other byte/register == v0.18; SD-loaded subset | 238/238 |
| L | live view (getter) == stills (marker) LUT, output, context and registers: COLOR1–4 × contrast −2/0/+2 and tone block, CPU id 1 | 17/17 |

Not covered: camera behaviour; whether the register writer needs anything beyond O+2608 and O+4 bit 8 (stock's
own tone step does exactly these); the ISP look of the remap.

## 7. v0.19 release spec (patches/v019/build.py)

`releases/v0.19/edits.json` = v0.18 + tone_ends (§6) + loader ranges + tone_x + fw label 0.19. Edits that differ
from v0.18: 0x601e103c / 0x601e133c (tone pieces A/B), 0x603b14ff (hook), 0x605b7400 (loader: 4 data bytes,
sd_lo/sd_span[47..48] at 0x605b7710/11 and 0x605b7750/51 → −5..5), 0x601e323c (look extras: four same-size
redirects + "Extras: 1-7 only"), 0x601e123c (tone_x, 255 B, dead EVF step-13 G table, only ref 0x601e3d54),
0x601e1c40 (label 0.19). Component 0x101 is byte-identical to v0.18.

Extras (tone_x): sector 6 = slot +47 Blacks, 7 = +48 Whites, −5..+5 (out-of-range bytes read 0), ALL mode writes
nothing, writes set the editor's dirty byte so the card is saved as for the other extras; labels `6 Blacks -3`,
`6 Blacks 0`, `7 Whites +2`; sectors 8–12 `Extras: 1-7 only`. A stock-blanked guide (id 0, when the page's
values touch both −5 and +5) is labelled like id 2755 on the Extras page (the v0.17 lesson).

| Check | Tool | Result |
|---|---|---|
| Curve hook on the final spec | `tools/ep7_verify_tone_ends.py releases/v0.19/edits.json --jobs 16` | N 27/27, A 238/238, L 17/17, S pass (P's "base == v0.18" is false by design: the base now carries the loader/extras/label edits) |
| Loader | `tools/ep7_verify_v019_loader.py releases/v0.19/edits.json --part E,A,R` | E 179/179 (incl. +47/+48 = −6/−5/5/6, +49..63 = 1), A, R pass; the same driver on v0.18 rejects the tone boundary tables |
| Extras | `tools/ep7_verify_v019_extras.py --editor releases/v0.18/edits.json --layered releases/v0.19/edits.json --part G,W,V --jobs 16` | G 936/936, V 1296/1296 (labels, blank restore), W 6064/6160: every sector-5/6 write passes; the 96 misses are the art sector (4) only, whose v0.14 ex_art path (0x601e1b3c) the old harness does not map (that path is unchanged: tone_x passes sector 4 straight back) |
| Package | build_package + decode | patched main == stock + edits, restore == stock, 13036 changed bytes all inside edit spans, `caduceus.py build --release v0.19` reproduces SHA256SUMS |

Card: BUNDLES.BIN = v0.18's with the library Blacks/Whites in its COLOR slots (CineStill800 0/−1 ×2, Cuban Neg
0/−2, Cl. Chrome −1/0); LOOKS.BIN unchanged (v3).

## 8. Tone-screen third page: mapping notes (not built; v0.19 ships Extras 6/7)

Mapped statically for a later build [V]:
- Event dispatcher `0x60defafe` (frame 232 + 16; (16,sp) = object, a2 = the profile's reset table, a3 = result,
  exit `0x60defe91`). Hash table 0x61159e28 (16 × {event, handler}); INFO's case `0x60defcd8` is entered by
  `jmp (a0)` inside that frame, so a data redirect of word 0x61159e74 gives a case-level hook.
- **Screen identity:** obj+236 (first constructor halfword) is 383 or 893 on the tone screen; the INFO case already
  tests it, and the other `Direct_Actuator` takes the generic N-page loop at 0x60defd82 (obj+220 count, availability
  via 0x607b3c32 on row+28·page+20/+24).
- Dials: 0x60def75a (0x9032) steps obj+208 (Shadows id), 0x60def91e (0x9031) steps obj+212 (Highlights id), both
  via facade SetValue(id, 1/2 = step, 0). 0x60defe96 fills obj+208/212/160/164/168 from row+28·obj+222, so obj+222 = 2
  would read the next profile's row: a B/W page must keep obj+222 ≤ 1 and hold its own page flag (heap P).
- View page writer 0x60e27639: page from setting 1088 (384/383 → page 0, else Midtone); guide label at view+186 or
  +260 (by view+404) as {kind 4, id 2778/2779, 2}. A kind-5 text label there is the cheapest B/W readout.
Remaining for a build: dial/arrow case hooks, a redraw poke (re-write 1088), the label hook, and an emulator harness
for this object (none exists yet).
