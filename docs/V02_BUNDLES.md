# v0.2 profile bundles: per-profile H/L (E-P7 1.1)

Offline only. Nothing here has run on a camera. No SD-named file was created and nothing was
committed. "Verified" means executed in the emulator on the exact package bytes, or read directly
from the decoded main. "Static" means reasoned from the disassembly only.

- Build: `.venv/bin/python -I patches/bundles/build.py bundles/example.json --out generated/bundles-example`
- Verify: `.venv/bin/python -I tools/ep7_verify_bundles.py generated/bundles-example/edits.json [--json out.json]`
- Merge with the other patches:
  `tools/merge_specs.py out.json <bundles>/edits.json <grain>/edits.json patches/rec_limit/edits.json`.
  `merge_specs.py` now keeps the bundle and grain verifier metadata, so both verifiers run on the merged spec.
- Files:
  - `patches/bundles/bundles.s.in`: our assembly.
  - `patches/bundles/build.py`
  - `patches/bundles/layout.json`: the fixed table ABI.
  - `tools/ep7_verify_bundles.py`

## What it does

Each COLOR profile (COLOR1–4) gets its own 12-sector hue and lightness, taken from a recipe chosen at
build time. Switching profiles with the stock selector switches the look. Saturation is not part of
the patch: the profile's own stock saturation setting still applies. `build.py` records the recipe's
`sat` as advice in `slots[].advice_sat_ui`.

In a frame without a capture record, the patch leaves the stock output untouched. The same applies
to an unknown profile index, a picture mode other than 11, a disabled slot, or a value out of range.

## Sites and stock bytes

All sites are in main (component 0x100). `build.py` checks every stock byte against the decoded main
(SHA `5dd9af16…6190`). `build_package.py` checks them again against the container.

| Address | Stock | New (example build) | Purpose |
|---|---|---|---|
| 0x603537f0 | `2c803c` mov 15488,d0 | `2c983c` mov 15512,d0 | Job allocation +24 B (extension at job+15488) |
| 0x6035390c | `8510` mov 16,d1 | `8528` mov 40,d1 | Tail memset at job+15472 now covers 15472..15511 |
| 0x603b02d9 | `cd8ffdf060` call 0x603b0068,[d2,d3,a2,a3],96 | `dc c008e6ff` jmp hl | COLOR builder hook (same site as v0.1, which it **replaces**) |
| 0x603e66ab | `f043a00cc926` movbu (a3),d0; cmp 12,d0; bne 0x603e66d5 | `dc 9da4e2ff cb` jmp conv1; nop | Transport, converter 0x603e62d1 |
| 0x603e91f0 | `5c24f040a00c` mov (36,sp),a0; movbu (a0),d0; cmp 12,d0 | `dc 8179e2ff cb` jmp conv2; nop | Transport, converter 0x603e8af1 |
| 0x60210900–0x60210c70 | FF (880 B) | table + LUTs + code | Section-1 FF tail |

- The jmp operands depend on the code length, so `build.py` emits them from the linker labels.
- Changed payload bytes: 868 (example bundle), all inside the edit spans.
- Merged with grain L2 and rec_limit: 11 edits, 1002 bytes, no overlap. That build also respects the
  coordinator reservations: sec-2 0x6055e5c0–7a6, grain hooks 0x6035749f and 0x603b5249, rec-limit
  0x60319157 and 0x6031915c. `build.py` refuses any overlap with them.

**Why the converter sites moved.** The planned 0x603e669f and 0x603e91e4 sit inside the `mode == 11`
block and would only ever see COLOR frames. 0x603e66ab and 0x603e91f0 run for **every** picture mode,
so the transport also carries MONO (mode 12) profile numbers for later use.
- Both new sites are the start of a `cmp 12` test, and both are themselves branch targets.
- No branch, call, Lcc loop start or abs32 reference (0x6… or 0xA… alias) points into the interior
  of any of the three hook spans. This was checked with a brute-force scanner in the verifier, which
  passes a positive control.
- Each stub re-executes the displaced instructions. It leaves d0, a0 and the flags exactly as stock
  would and jumps to the stock successor:
  - conv1 goes to 0x603e66b1 or 0x603e66d5.
  - conv2 goes to the bne at 0x603e91f6.

## Code space

| Range | Content |
|---|---|
| 0x60210900–0x60210b00 | **Bundle table, 8 × 64 B. Fixed address `BUNDLE_TABLE = 0x60210900`.** Exported in `patches/bundles/layout.json` for the per-profile WB stub. `build.py` cross-checks that file. |
| 0x60210b00–0x60210b48 | Hue LUT (15 hw, −1000·ui), L LUT (15 hw, fishcu's), physical-record permutation (12 B) |
| 0x60210b48 / b71 / b99 | conv1 / conv2 / hl |
| 0x60210c70 | End. A 16-byte FF guard is kept on each side (0x602108ec… start of FF is checked) |

Why section 1 and not the section-2 tail:
- The section-2 tail is now fully reserved (HSL, grain, WB).
- Section 1 (0x600d7800–0x60211000) **loads first** (boot order 1, 7, 2, …). Its code and data are
  therefore present before any section-2 hook can run.
- `build.py` re-verifies the following from the image:
  - descriptor 0x60027068 entry 0 = {0x600d7800, src 0x40757800, dst 0x600d7800}, so it loads in place;
  - end getter jump-table entry 0x60046780 → 0x6004579c `mov 0x60211000,d0`;
  - the placement plus its guards is all FF.
- The only abs32 hit in 0x602108ec–0x60211000 is 0x602108f0 at 0x6086f774. It is mid-instruction
  (`mov (792,a0),a0; mov sp,a1; mov (a0),a2`), so a false positive.
- The first abs32 references above the tail are ≥0x60211000, beyond the load end. So the tail does not
  look like the start of BSS. This is static only.

v0.2 does **not** use 0x6055e5c0–0x6055e67f. A v0.2 package must not also contain v0.1: both claim
0x603b02d9, and `build_package.py` rejects the overlap.

## Bundle table (per slot, 64 B)

`+0 hue[12] s8`, `+12 light[12] s8` (UI −7..7, UI sector order), `+24 grain`, `+25 wb_flags (bit0)`,
`+26 wb_ab`, `+27 wb_gm`, `+28 effect_id`, `+29 effect_strength`, `+30 vignette`, `+31 flags`,
`+32..63 = 0`.

**flags:** bit1 = H/L enabled (set for every COLOR slot present in the JSON), bit0 = MONO render
colour (stored only).

Slots: COLOR1–4 = 0–3, MONO1–4 = 4–7. A slot missing from the JSON is all zero, so it is disabled
and gives stock output.

How the fields are filled:
- WB is the slot's `wb`, otherwise the recipe's `wb_shift`.
- Grain comes from the slot only (`"grain": "low|medium|high"`); since v0.4 a recipe's grain is **not**
  inherited (it is reported as `advice_grain`), so grain stays off unless the bundle asks for it.
- The effect comes from the slot only: `"effect": {"type": "bloom|halation", "strength": 1-5}`
  (strength is required and range-checked since v0.4; `"none"` takes no strength).
- Vignette is the slot's value, otherwise the recipe's.

**Consumers (v0.4):** COLOR hue/light (this patch), WB fields (patches/wb), `grain` of COLOR1–4
(patches/grain v0.4) and `effect_id`/`effect_strength` bloom of COLOR1–4 (patches/bloom v0.4). Vignette and
halation are stored only.

`build.py` rejects:
- unknown slot names or keys, and unknown recipes;
- non-integer values (no silent truncation, fixing review L3);
- values out of range;
- `render_colour` on a COLOR slot.

## Transport (task 1)

- **Job extension:** job+15488 = profile byte (capture+24083), +15489 = picture mode
  (capture+24053), +15490 = marker 0xB2, +15491..15511 = 0.
- **Size change, verified everywhere it is used:**
  - Allocation: verified by native run. 0x60022700 picks a fixed-block class by size: ≤128, ≤2048,
    ≤16384 (`cmp 16384` at 0x60022713). 15512 stays in class 2, the same as 15488. Static.
  - Zeroing: verified by native run. The constructor clears 36..11294 and 14308..15472 in pieces,
    then 15472+len. Only the last piece changes.
  - Copies: none. The decimal value 15488 appears only at 0x603537f0. In sec 5, d1=15488 at
    0x609393fb goes into an allocator wrapper whose class is chosen by d0=4, so it is unrelated.
    No 32-bit literal 15488 or 15472 exists anywhere.
  - Offsets: the only explicit job offsets ≥15472 in the whole image are 15472–15478 (the stock
    16-byte tail). The packer copies 8 halfwords from job+15472. Freeing goes through 0x60022732,
    which is size-agnostic.
- **Which jobs get the bytes:**
  - All 5 converter calls (0x603e6d50, 0x603ebcbe, 0x603f0e72, 0x603f2850 → 0x603e62d1;
    0x603f2bc9 → 0x603e8af1) run directly after the job constructor 0x603537eb on the job it just
    returned. In the CPU2 builder, a3 = sp+24, so (36,a3) = (60,sp). Static.
  - Jobs from the other constructor callers (0x60321ea8, 0x603e39c7, 0x6060dbe3) never pass a
    converter. Their extension stays 0, so no marker, so stock output.
- **Fallback choice: stock, not the global getter.**
  - Calling 0x6005e971(63153,0,0) from the builder hook depends on the per-core address translation
    (CPU id at 0x8050) and on runtime registry RAM. Neither can be exercised in the emulator, and it
    is unknown which core runs the builder.
  - A wrong guess there could fault inside image processing. The stock fallback cannot.
  - **Trade-off:** any COLOR rendering that does not come from a capture record keeps stock H/L. If
    live view uses such a path, the preview will not show the bundle's H/L, but the recorded image
    will. Whether live view uses this builder at all is still untraced.
- **Also on the stock fallback:** jobs built by 0x6060dbe3, which writes params+5538 itself
  (0x6060e2e5).
- **Picture-mode bracketing:** stays per frame because 0x603e2084 restores capture+24083 before
  conversion. Static, from PROFILE_INDEX_WB.md.

## Routine (task 2)

The routine at `hl`:
1. Re-issues the builder call, then saves d0–d3, a0, a1 and a3 in an inline 28-byte frame, with no
   second CALL. a2 (the context) is only read.
2. Guard:
   - request = (4,a2) has callback 0x60355fd4;
   - request+4 equals one of the 16 records at request+3212, stride 56. This is an arithmetic
     compare, done before any dereference;
   - record+0 == request−11364.
3. Marker == 0xB2, mode == 11, profile−1 < 4 (unsigned, so 0 and 5..255 are rejected).
4. Slot entry = table + 64·slot, and the flags bit1 is set.
5. All 24 values are validated as −7..7 **before** anything is written.
6. For each r = 0..11, writes w = perm[r] = 2(r%6)+r/6, then hue = HUE_LUT[h_w+7] → out+706+24r and
   L = L_LUT[l_w+7] → out+710+24r.
7. Restores the registers and `jmp 0x603b02de`.

No mul, div or ext is used, so MDR is untouched, and neither is setlb, so LIR/LAR are untouched.
Peak stack is unchanged: the 28 B frame is used after the builder's 96 B frame has been released.

## Verification (task 4)

The verifier builds the package with `build_package.build()` and decodes the patched and restore
payloads. Every run uses code from those payloads, with stock and patched on the same fixture. The
expected H/L values come from re-running `build_table` on the bundle JSON, so they are independent
of the image.

| # | Test | Result |
|---|---|---|
| A | Selector → hook → v0.2. COLOR1–4 × 4 saturation sets. H/L == slot table rows. Saturation, control word and all other output bytes == stock. Context and job == stock. **All registers** (d0–d3, a0–a3, sp, pc, mdr, psw, lir, lar) at return == stock. | 16/16 PASS |
| B | Profile 0/5/255, marker absent (no capture record), wrong marker, ext mode 12/0, wrong callback, foreign parent: output **byte-identical** to stock. Run on a *hostile* table with all 8 slots enabled and non-zero. Records 0/15 accepted. Slot disabled and values +8, −8, −128 in the table: stock. | 15/15 PASS |
| C | Converter code natively, from the patched payload: 0x603e6681→0x603e66d5 and 0x603e91c3→0x603e921c. Modes 11/12/5/6, profiles 1–4/0/255, stale extension 0x55. Extension == (capture+24083, capture+24053, 0xB2). Every other job, capture and stack byte, and all registers at the stop PC, == stock. | 20/20 PASS |
| D | Constructor 0x603537eb natively up to 0x60353915, with a stub allocator and a self-tested stub memset. Size requested 15512 (stock 15488). job+15472..15511 zero. Nothing ≥15512 written. Bytes <15488 == stock. Static: alloc imm, memset base+len = size, class-2 bound, extension inside the job, no references into hook interiors. | PASS |
| F | Table in the package == table rebuilt from JSON. Changed bytes all inside the edit spans. | PASS |
| E | Mutations (see below) | 19/19 detected |
| Merged | v0.2 + grain L2 + rec_limit through `merge_specs.py`: bundle verifier (A–D, F) all PASS; `ep7_grain_verify.py` T1–T5 all PASS; rec_limit's bytes are inside the merged spans. Its own verifier runs on the image, not the spec, and PASSes standalone. | PASS |
| Partial | Bundle with only COLOR1 (`cinestill_800t`) and MONO2 set: COLOR2–4 output == stock; 56/56 PASS | PASS |

| Mutation (applied to the patched payload) | Detected by |
|---|---|
| hue offset 706->708 | yes: 16 test(s), e.g. A COLOR1 sat=[0, 0, 0].. |
| record loop 12->11 | yes: 16 test(s), e.g. A COLOR1 sat=[0, 0, 0].. |
| frame -28 -> -24 (stack) | yes: 31 test(s), e.g. A COLOR1 sat=[0, 0, 0].. |
| a0 not restored | yes: 29 test(s), e.g. A COLOR1 sat=[0, 0, 0].. |
| profile bound 4 -> 5 | yes: 1 test(s), e.g. B profile 5 -> stock |
| no -1 on profile | yes: 20 test(s), e.g. A COLOR1 sat=[0, 0, 0].. |
| marker check removed | yes: 2 test(s), e.g. B marker absent (no capture record) -> stock |
| mode check 11 -> 12 | yes: 19 test(s), e.g. A COLOR1 sat=[0, 0, 0].. |
| value check 15 -> 16 | yes: 1 test(s), e.g. B COLOR3 hue[5]=+8 -> stock |
| enable flag check skipped | yes: 18 test(s), e.g. A COLOR1 sat=[0, 0, 0].. |
| callback check off-by-one | yes: 19 test(s), e.g. A COLOR1 sat=[0, 0, 0].. |
| perm swap r0/r1 | yes: 16 test(s), e.g. A COLOR1 sat=[0, 0, 0].. |
| light LUT[+1] corrupted | yes: 4 test(s), e.g. A COLOR4 sat=[0, 0, 0].. |
| conv1 profile -> job+15487 | yes: 9 test(s), e.g. C conv1 mode=11 profile=1 stale=0x0 |
| conv1 skips mono branch | yes: 10 test(s), e.g. C conv1 mode=11 profile=1 stale=0x0 |
| conv2 mode from capture+24054 | yes: 10 test(s), e.g. C conv2 mode=11 profile=1 stale=0x0 |
| conv2 wrong compare 12->11 | yes: 8 test(s), e.g. C conv2 mode=11 profile=1 stale=0x0 |
| memset 40 -> 39 | yes: 2 test(s), e.g. D constructor (native, stub alloc/memset) |
| alloc back to 15488 | yes: 2 test(s), e.g. D constructor (native, stub alloc/memset) |

A single test catches 'profile bound 4→5', 'value check 15→16' and 'marker removed'. Those checks are defence in depth: the hostile-table B cases are the only tests that can reach them.

## Verified only statically (not executed)

- That the converters reach 0x603e66ab / 0x603e91f0 on every conversion, with a3/d3 and
  (20/24/36,sp) as fixtured. Stock code relies on the same registers and slots at those PCs, and none
  of them is written between their set-up and the site. The emulator starts mid-function from these
  register values.
- The heap class bound, and that no other code depends on the job size (searched for decimal
  immediates/displacements and 32-bit literals; dynamic sizes cannot be excluded).
- Which real pipelines use which builder: still image, RAW development, live view, movie, Art
  Filter. Also the alternate builder 0x603afb94, which bypasses the hook (review L1).
- Code-space residency: no BSS or heap over the section-1 tail, no reload, no runtime checksum.
  This is the same argument as v0.1.
- The memory allocator and memset in test D are stubs. Only the constructor's own code is native.

## Residual risks

1. **Profile value encoding.** The routine assumes capture+24083 = 1..4 for COLOR1..4, as given and
   as in PROFILE_INDEX_WB.md, where COLOR4's value is inferred. If it is 0-based on the camera,
   COLOR1 would render stock and COLOR2–4 would show the looks of COLOR1–3. That is wrong colours,
   not a crash.
   - First camera check: COLOR1 must not look stock.
   - If the encoding is 0-based, the fix is a one-byte change: drop the `add -1`.
2. **Live view and other non-capture paths keep stock H/L** because of the chosen fallback.
3. **ISP semantics of H/L.** The scale and sign are unverified on the E-P7 (review M3), as for v0.1.
4. **Larger footprint than v0.1:** 6 sites, 2 of them in the job constructor and 2 in converters that
   every capture uses. A fault in conv1 or conv2 would affect every shot in every picture mode, not
   only COLOR.
   - The stubs are 41 and 40 bytes of straight-line loads and stores into the job just allocated
     with the new size.
   - Emulator results: registers identical to stock.
5. **Boot exposure:** section 1 now holds the code. A torn write to section 1 or section 2 affects
   boot, the same exposure class as review M1.
6. The H1/H2 prerequisites from REVIEW_fixed_hl.md still apply: restore dry run, camera already on 1.1.

## Design only (not implemented)

- MONO slots (mode 12 → slots 4–7): the transport already records mode and MONO profile. The
  selector redirect at 0x603b02c1 is in WB_AND_MONO.md.
- Grain, WB, effect and vignette consumers of the table. The WB stub must read `BUNDLE_TABLE`
  0x60210900 from `layout.json`.
- Editable bundles, in-camera editing and persistence.
