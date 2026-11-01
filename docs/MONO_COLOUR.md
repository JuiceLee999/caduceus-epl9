# MONO slots rendering colour (E-P7 1.1)

Offline only. Nothing here has run on a camera. No SD-named file was created and nothing was
committed. "Verified" means executed in the emulator on the exact package bytes. "Static" means
reasoned from the disassembly only.

Goal: MONO1–4 become universal bundle slots, so all 8 profile slots can hold a colour look. A MONO
slot whose bundle says `colour == 1` renders exactly as a COLOR profile with the slot's saturation and
hue/lightness. Every other MONO slot renders as stock mono, including filter and toning.

- Build: `.venv/bin/python -I patches/mono_colour/build.py --out generated/mono_colour`
- Merge: `tools/merge_specs.py out.json releases/v0.3/edits.json generated/mono_colour/edits.json`
  (any spec that contains patches/bundles v0.2; the patch depends on its job extension and table).
- Verify: `.venv/bin/python -I tools/ep7_mono_colour_verify.py out.json [--json r.json]`
- Files: `patches/mono_colour/mono_colour.s.in`, `patches/mono_colour/build.py`,
  `tools/ep7_mono_colour_verify.py`, `bundles/mono_colour_example.json` (demo bundle).

## Bundle fields (patches/bundles/layout.json)

Two fields are added in the slot's reserved bytes (+32..+63 were zero):

| Offset | Field | Meaning |
|---|---|---|
| +32 | `colour` u8 | **Exactly 1** = this MONO slot renders colour. 0, 0xFF (erased) or any other value = stock mono. |
| +33..+44 | `sat[12]` s8 | Per-sector saturation, −5..5 (stock range), in request+1816 order, the same order as a COLOR profile's saturation. Read only when `colour == 1`. |

The slot's existing `hue[12]`/`light[12]` (+0/+12) apply when flags bit1 (H/L) is set. flags bit0
(render colour) stays as a mirror of `colour`; the code reads +32.

In the bundle JSON, a MONO slot with `"render_colour": true` gets `colour = 1`, H/L from its recipe
(flags bit1), and `sat` from the slot's `"sat"` or else the recipe's `sat`. A value outside −5..5 is a
build error (no clamping). `"sat"` without `render_colour` is an error. COLOR slots are unchanged, and
`bundles/example.json` (v0.3) builds a byte-identical table.

## When the colour path runs

All of these must hold, otherwise the stock code runs unchanged:
1. Job marker 0xB2 is present (frame came through the v0.2 converter transport), ext mode == 12,
   ext profile 1..4.
2. `bundle[4 + profile − 1].colour == 1`.
3. All 12 `sat` are in −5..5, and if H/L is enabled all 24 hue/light values are in −7..7.
4. Selector and chroma stage: the request is proven to belong to the job (callback 0x60355fd4, record
   in request+3212, parent == request − 11364), as in v0.2, and the request mode word is 12.
   Packer: job+11308 == 12 (the stock test), and the job pointer comes from the packer itself.

All three hooks use the same predicate, so a slot is either colour everywhere or stock everywhere.

## Sites

| Address | Stock | New | Purpose |
|---|---|---|---|
| 0x603b02bf | `f219 a50b c936` or d2,d1; cmp 11,d1; bne 0x603b02f9 | `dc rel32 cb` jmp sel | Selector 0x603b0252 mode test |
| 0x603b134e | `cdadfee010` call 0x603b11fb,[d2,d3,a2],16 | `dc rel32` jmp chroma | Chroma stage 0x603b132a tone lookup |
| 0x60353db9 | `fa002c2c a00c c92a` mov (11308,a0),d0; cmp 12,d0; bne 0x60353de9 | `dc rel32 cbcbcb` jmp fg | Packer 0x60353d02 mono-filter merge |
| 0x61378c80–0x61378f7c | FF | LUTs + code (764 B) | Section-7 FF tail |

**sel.** It re-executes `or d2,d1` and then:
- mode 11 → jmp 0x603b02c5 (stock COLOR path, which goes on to the v0.2 hook at 0x603b02d9);
- other non-12 modes → jmp 0x603b02f9;
- mode 12, not a colour slot → registers restored, jmp 0x603b02f9 (stock general builder);
- colour slot → the stock COLOR call 0x603b02c5..0x603b02d9 is replayed with `a1 = a3 = slot.sat`
  instead of request+1816: table 0x6051de2c, control word (0x6051e9fc), builder 0x603b0068. Then the
  slot's hue/L are written into the 12 output records exactly as v0.2 `hl` does for COLOR (own copies
  of the v0.2 LUTs and record permutation, taken from patches/bundles/build.py). Then jmp 0x603b02de
  (stock COLOR tail).

**Why the H/L is applied here, not by the v0.2 hook.** The v0.2 `hl` accepts only ext mode 11. Making
it accept mode 12 would change the bundles code, so `releases/v0.3/edits.json` could no longer be
merged unchanged. `sel` therefore calls the builder itself and applies the slot's H/L with the same
rules (flag bit1, validated values, same LUTs). It does not pass through 0x603b02d9.

**chroma.** It re-issues the stock call, then sets MDR back to 0x603b1353, the value the stock call
leaves. For a colour slot it returns a0 = 0. The stock code then calls 0x603b1311 (out+76 = 0), which
is exactly the mode-11 result: no constant {1, Cb, Cr}, so no grey and no toning.

**fg.** For a colour slot it writes params+5528 (mono filter) = 0 and params+5529 (picture tone) = 0.
These are the job's own bytes (job+5564/5565, the address the stock merge itself uses), and it skips
the merge as mode 11 does. request+1802/1803 are filled later from params at request-build time
(0x60355409 → 0x60354f20, called from the pipeline stages), so the 3×3 filter-matrix id
(0x603acfe4 via request+1802) and the curve flag (request+1802 bit7, 0x603b0bfa) are both 0, as for a
COLOR job. Both converters call the packer (0x603e689e, 0x603e92cc) *after* the transport has written
the marker (0x603e66ab / 0x603e91f0). Static.

**Registers and stack.** Each stub saves what it uses in a frame below sp and restores it. Every frame
is released before a stock call, so peak stack depth is unchanged. There is no mul, div, ext or setlb.
Unconditional jmp d32 is used for all exits.

## Code space

| Range | Content |
|---|---|
| 0x61378c68–0x61378c80 | guard (FF) |
| 0x61378c80–0x61378cc8 | hue LUT, L LUT, permutation (copies of v0.2's) |
| 0x61378cc8 / 0x61378e1b / 0x61378ee9 | sel / chroma / fg |
| 0x61378f7c–0x61378f8c | guard (FF); 0x61378f8c–0x61379000 (116 B) free |

`build.py` re-verifies the following from the image:
- descriptor 0x60027068 entry 6 = {0x612c7000, src 0x41947000, dst 0x612c7000}, so it loads in place;
- end getter 0x60045786 indexes 0x60046780; entry 7 → 0x600457c4 `mov 0x61379000,d0`;
- the whole tail 0x61378c68–0x61379000 is FF;
- there is no abs32 reference (0x6… or 0xA… alias) into the tail. The last referenced address below it
  is 0x61378c54, the initializer list that ends at 0x61378c68;
- no overlap with any v0.3 edit or with the per-profile WB patch.

Section 7 loads second (boot order 1, 7, 2, …), so the code is present before any section-2 hook
runs. Section 7 holds code (0x612c7000 is a function). The same residency argument as section 1
applies (no BSS over the tail). Static.

## Verification (`tools/ep7_mono_colour_verify.py`, emulator, exact package bytes)

Images: **patched** = package payload; **base** = same spec without the mono_colour edits (= v0.3);
**stock** = restore payload. Test tables are written into emulator RAM only.

| # | Test | v0.3 + mono_colour |
|---|---|---|
| S1 | Selector 0x603b0252, whole function. Colour slot MONO1–4 × 4 sat sets (MONO4 without H/L), request+1816 filled with junk. Output (5212 B), context, job and **all registers** (d0–d3, a0–a3, sp, pc, mdr, psw, lir, lar) == a mode-11 run whose COLOR slot has the same H/L and whose request sat == the slot's sat. H/L == rows derived from the slot values. Output ≠ stock mono. | 16/16 PASS |
| S2 | Not a colour slot, on a hostile table (all MONO slots colour): profile 0/5/255, marker absent/wrong, ext mode 11/0 with request mode 12, wrong callback, foreign parent, colour 0/2/0xFF, sat +6/−6/−128, hue +8 / light −8 with H/L, toned + filtered with colour 0, alternate default table. Output, context, job, live stack and all registers **byte-identical to stock**. | 19/19 PASS |
| S3 | Mode 11 COLOR1–4 (real and hostile table) == base (v0.3), registers included. Modes 1 and 5 == stock. | 18/18 PASS |
| C | Chroma stage 0x603b132a. Colour slot × tones 0–4 × request+1800 0/1: out+76 = 0 == mode-11 run (stock mono gives 0x00808001 / sepia 0x008d7501 / …). Output, context, job and live stack == mode-11 run; registers == mode-11 run except a1/LIR/LAR (see below). Non-colour cases × tones: == stock incl. all registers (MDR too). Mode 11/5 == stock. | 101/101 PASS |
| P | Packer segment 0x60353db7→0x60353de9. Colour slot: params+5528/5529 → 0, nothing else in the job written, merge skipped, registers == stock mode-11 run except d0 (12 vs 11) and psw. Non-colour: == stock incl. registers (filter bits 0x80\|x<<4 as stock). Modes 11/5/0 == stock. | 51/51 PASS |
| R | Package's own table: each MONO slot with colour 1 == mode-11 reference, otherwise == stock mono. | v0.3: 4/4 stock |
| X | No branch, call, loop or abs32 reference into the interior of the 3 hook spans (brute-force scanner from ep7_verify_bundles). Changed bytes all inside spans. Spec contains the bundles edits. | PASS |
| E | 20 mutations (colour test, ext mode, profile −1, sat bound, sat pointer, H/L frame/skip/offset, request parent check, sel_mono frame, chroma a0 = 0 / MDR fix / mode word / callback / parent / ch_keep restore, fg tone and filter offsets, fg colour check, fg_mono restore) | 20/20 detected |

Total 213/213 tests and 20/20 mutations PASS on `releases/v0.3/edits.json` + mono_colour
(121 edits, 2,438 payload bytes). On the same merged spec `ep7_verify_bundles.py`,
`ep7_grain_verify.py` and `ep7_bloom_verify.py` PASS. The grain and bloom verifiers used are the
committed (v0.3-era, HEAD b77a86d) versions: the working-tree copies were being rewritten for v0.4 by
another agent during this work and no longer accept a v0.3 spec (bloom needs `strength_w`, grain T2
expects per-profile grain), independent of this patch.

**Real-table demo.** `bundles/mono_colour_example.json` = example.json + MONO1 colour
(classic_chrome), MONO2 colour (cinestill_800t H/L, own sat), MONO3 plain mono. It is built into
`generated/bundles-mono-colour` and merged with the other five v0.3 sources and mono_colour. On that
spec all 213 tests pass, and R gives MONO1/MONO2 colour == mode-11 reference and MONO3/MONO4 stock
(note: that demo uses the working-tree `patches/aspect/edits.json`).

**Chroma a1/LIR/LAR.** These are left by the re-issued stock tone lookup 0x603b11fb. Its hash search
(setlb loop) runs for key 12 but not for key 11. The caller never reads them: a1 is reloaded at
0x603b1363 or dead at return, and LIR/LAR are only used by an Lcc right after a setlb. Against stock
mono, the non-colour runs are register-identical.

**Dead stack.** Stub frames leave data below sp. That memory is dead, so only the live stack (≥ sp) is
compared.

## Not covered / risks

- **ISP output and the camera are untested.** Selector, chroma and packer outputs are CPU-side
  parameters; the colour image itself is inferred from "mode-11 parameters ⇒ COLOR rendering".
- **Not hooked:**
  - MONO grain/shading (request+1828/1829) and the mode-12 grain work-list still run. The slot gets
    the user's MONO grain/shading setting: set it to Off for clean colour.
  - The key-12 skip at 0x60367ee3 (extra 0xff11 pass, meaning unknown) still applies, so a colour
    MONO slot may lack one pass a COLOR job gets.
  - Converter gates for mode 12 (filter/grain/shading copy) are untouched. Their filter/tone output is
    neutralised by `fg`.
  - EXIF/makernote still says Monotone (cosmetic).
  - The Art path's separate calls to 0x603b11fb (0x603b13e4/0x603b1416) are not hooked, which matters
    only for Art requests, not mode 12.
- **Live view / EVF:** frames without a capture record (marker absent) stay stock mono. The preview
  may show grey while the recorded image is colour. Not traced.
- **Profile encoding:** same assumption as v0.2 (capture+24083 = 1..4 for MONO1..4).
- 0x603acfe4 with request+1802 = 0 is assumed to equal the mode-11 matrix path (mode 12 has no special
  case there; static, not executed).
- Depends on v0.2 bundles (job extension, transport, table at 0x60210900). Without them the marker
  read would be outside a stock-size job; the verifier refuses a spec without the bundles edits.
