# Per-profile WB fine-tune patch (E-P7 1.1)

Offline only. Nothing here has run on a camera. No SD-named file was created and nothing was
committed. "Verified" means executed in the emulator on the exact package bytes from
`tools/build_package.build()`, or read directly from the decoded main (SHA `5dd9af16…6190`).
"Static" means reasoned from the disassembly only. Design background: `docs/WB_AND_MONO.md` Part A.

- Build: `.venv/bin/python -I patches/wb/build.py --out generated/wb`
- The table comes from the bundles build (`patches/bundles/build.py`); always merge:
  `tools/merge_specs.py out.json <bundles or releases/v0.3>/edits.json generated/wb/edits.json`
- Verify: `.venv/bin/python -I tools/ep7_verify_wb.py out.json [--json r.json] [--no-mutations]`
- Files: `patches/wb/wb_get.s.in` (our assembly), `patches/wb/build.py`, `tools/ep7_verify_wb.py`.
  `tools/ep7_wb_probe.py` stays as the original design probe (fake getter, synthetic table).

## What it does

Each of the 8 bundle slots (COLOR1–4, MONO1–4) can carry its own WB fine-tune (A–B, G–M, −7..7).
While that profile is active, the image pipeline sees the slot's A/G instead of the stored
per-WB-mode fine-tune. Menus are unchanged and show the stored values; nothing is written back.

Bundle JSON: `"wb": {"a_b": n, "g_m": n}` on a slot sets `wb_flags` bit0 and `wb_ab`/`wb_gm`.
Without `wb` the recipe's `wb_shift` is used (existing behaviour). `"wb": null` disables an inherited
`wb_shift`. The builder rejects non-integers, values outside −7..7, unknown keys in `wb` and
non-object `wb`.

**Behaviour change for v0.3's example bundle.** All four COLOR recipes carry `wb_shift`, so with this
patch merged COLOR1 = +2/+1, COLOR2 = +3/+1, COLOR3 = 0/0 and COLOR4 = +2/0. That applies to every WB mode
except CWB, and it **replaces** the user's own fine-tune. A 0/0 override cancels a stored fine-tune.
MONO1–4 have no override, so they behave as stock.

## Logic of `wb_get` (164 B at 0x6055e700)

The stub is entered through the site's unchanged `call …,[d2,d3],12`, with the getter's contract
(d0 = key, d1 = idx, a0 = 0 → d0). It returns the slot value only when **all** of these hold:

1. The key is 0x84F9 (A–B) or 0x9679 (G–M).
2. The global WB category (key 33057) is not 3 (CWB).
3. The picture mode (key 38017; for mode 6, key 40209 is read, as capture population does) is 11 or 12.
4. The profile is 1..4: for mode 11, key 63153 gives slot p−1; for mode 12, key 63281 gives slot 4+p−1.
5. `bundle[slot].wb_flags & 0x81 == 1`, so bit0 must be set and bit7 clear. An erased 0xFF table
   therefore counts as off.
6. **Both** `wb_ab` and `wb_gm` are in −7..7.

In every other case `wb_pass` tail-jumps into the stock getter with the original d0/d1/a0 on the site's
own frame. The stock path is therefore the stock getter running on an identical frame.

`BUNDLE_TABLE` and the field offsets are read from `patches/bundles/layout.json`; `build.py` hard-codes
neither. `layout.json` now documents "wb_flags bit7 must be 0", and `patches/bundles/build.py` only
writes 0 or 1 there. The profile is read from the global properties (design option A), as the doc
recommends. The job extension (job+15488..15490) is not reachable at the getter sites.

## Sites and stock bytes

All sites are in main section 2. Each edit is 4 bytes at site+1 (the call's rel32). Opcode and
`c0 0c` stay. `build.py` checks the 7 stock bytes, that the call targets 0x6005e971, and that every
site is preceded by `mov 0,a0` with no a0 write in between.

| Site | Stock | New rel32 | Key / idx | Role |
|---|---|---|---|---|
| 0x60302c46 | `dd2bbdd5ffc00c` | `baba2500` | A / 0 | capture: preset, cat 1 |
| 0x60302c60 | `dd11bdd5ffc00c` | `a0ba2500` | G / 0 | capture: preset, cat 1 |
| 0x60302da3 | `ddcebbd5ffc00c` | `5db92500` | A / 15 | capture: Flash |
| 0x60302db8 | `ddb9bbd5ffc00c` | `48b92500` | G / 15 | capture: Flash |
| 0x60302e35 | `dd3cbbd5ffc00c` | `cbb82500` | A / 0 | capture: one-touch |
| 0x60302e4b | `dd26bbd5ffc00c` | `b5b82500` | G / 0 | capture: one-touch |
| 0x60302f23 | `dd4ebad5ffc00c` | `ddb72500` | A / 0 | capture: cat 4 |
| 0x60302f3b | `dd36bad5ffc00c` | `c5b72500` | G / 0 | capture: cat 4 |
| 0x60302f8f | `dde2b9d5ffc00c` | `71b72500` | A / 1 | capture: Auto |
| 0x60302fa8 | `ddc9b9d5ffc00c` | `58b72500` | G / 1 | capture: Auto |
| 0x6030bb5b | `dd162ed5ffc00c` | `a52b2500` | A / 0 | compact ring slot (live-view candidate) |
| 0x6030bb6e | `dd032ed5ffc00c` | `922b2500` | G / 0 | compact ring slot (live-view candidate) |
| 0x6030eb61 | `dd10fed4ffc00c` | `9ffb2400` | A / 0 | params builder 0x6030e9d1 → params+5520 |
| 0x6030eb77 | `ddfafdd4ffc00c` | `89fb2400` | G / 0 | params builder 0x6030e9d1 → params+5521 |
| 0x60c68a45 / 0x60c68a59 | `dd2c5f3fffc00c` / `dd185f3fffc00c` | **unchanged** | A, G / per mode | RAW development (left stock on purpose) |
| 0x6055e700..0x6055e7a4 | FF | stub (164 B) | | 0x6055e7a4..0x6055e7b0 stays FF before bloom |

Standalone WB: 15 edits. Merged with v0.3: 132 edits, 1890 changed payload bytes. No overlap; the
packager and both builders check the reservations against each other.

## Register, stack and MDR contract (verified)

- **Pass path:** all registers d0–d3, a0–a3, sp, pc, mdr, psw, lir and lar at the return point equal
  stock.
- **Override path:** everything equals stock except d0 (the value), a0 and psw.
  - The stub sets d1 = idx, which is what the getter leaves.
  - a1 and MDR come out equal because the stub's last action is a real getter call, which ends in
    `calls`/`retf` inside 0x6005c8cf.
  - a0 (bundle pointer instead of property-data pointer) and the flags are caller-saved scratch.
    Every site's continuation rewrites a0 before reading it. The native runs W and C execute past
    each site to that point.
- **Stack:** the site's frame and everything above it are byte-identical. The callee's scratch word
  at (0,sp) holds a different call return address, which is dead.
- **Peak depth:** 44 B against 28 B stock, so **+16 B** (the 12 B stub frame plus the 4 B `wb_prop`
  frame).
- No mul, div or setlb is used, so LIR/LAR are untouched.

## Verification (`tools/ep7_verify_wb.py`)

The **real** getter runs natively from the payload: 0x6005e971, registry lookup 0x6005d924, typed read
0x6005efbd, and CPU-0 translation 0x6005c8cf → `retf`. It reads a synthetic registry
(0xa26ffa88 + 8·(key>>4), overlay flag 0, CPU id 0). An unknown key faults.

Expected values are rebuilt from the bundle JSON, independently of the image, and the table in the
package must match them.

| # | Test | v0.3 + WB merged |
|---|---|---|
| T | Package table == table rebuilt from `bundles/example.json` | PASS |
| S | 14 rel32s → stub; RAW sites byte-identical to stock; stub inside its reservation, gap to bloom FF; 1890 changed bytes all inside the 132 edit spans | PASS |
| U | 14 sites × 26 states, plus 17 hostile-table cases per site (602 runs per image). States: 8 slots, CWB, Auto/one-touch/cat 4, mode 6 → 11/12/5/6, profile 0/5/255 (COLOR) and 0/5 (MONO), modes 0/5/10/13/104. Hostile cases: +8/−8/−128/127 values, flags 0xFF/0x02/0x81/0x03, COLOR or MONO profile 5 with all slots valid, MONO1/MONO4 valid. Override → d0 = slot value, otherwise stock-identical | PASS |
| K | A non-WB key sent through the stub == the stock getter (all registers) | PASS |
| W | Native capture WB segment 0x60302c0f→0x60302fc9, 7 categories × 11 states, whole 25 000 B capture block diffed. Only +24098/+24100 (A/G) and the stock-derived +1874 (preset code) / +1916 (fine-tune flag) change, and only when active. CWB, and "global CWB with capture forced to cat 1", are stock | PASS (77 rows) |
| C | Native compact-slot sequence 0x6030bb52→0x6030bb7d and params-builder sequence 0x6030eb58→0x6030eb84: bytes written == slot A/G when active, otherwise stock | PASS (24 rows) |
| G | Native gain calculator 0x603b5769 (bytes unchanged): for every A/G pair from W plus the ±7 corners, patched output == stock output, and every non-zero pair moves the output | PASS |
| M | 20 mutations of the patched payload (CWB check, mode 11/12, profile bound/offset, MONO +4, flags mask/compare, both range checks, A/G selector, field offset, slot stride, mode-6 key, G-key compare, pass-path idx, d1 restore, ret frame, two sites left un-redirected) | 20/20 detected |

**Same run on the example-only merge** (bundles + WB): all PASS, 20/20 mutations.

**Partial bundle** (COLOR1 `"wb": null`, COLOR2 −7/+7, MONO2 +4/−3): all PASS, 20/20. COLOR1/3/4 and
MONO1/3/4 are stock. MONO2 yields +4/−3 in the capture segment, the compact slot and the params
builder.

**Other verifiers on the merged v0.3 + WB spec:**
- `ep7_grain_verify.py`: T1–T5 PASS.
- `ep7_bloom_verify.py`: T1–T5 PASS.
- `ep7_verify_bundles.py`: PASS, 19/19 mutations (run note below).
- `ep7_verify_bundles.py` on the regenerated `generated/bundles-example`: PASS, 19/19 mutations. Its
  edits are byte-identical to the previous build; only the metadata gained `wb_source`.

## Coverage, stated honestly

- **Still captures: covered** (capture WB resolution; whether RAW metadata records the overridden A/G is not traced). All 10 capture-segment
  reads are redirected and verified natively, as is the second params builder (0x6030e9d1 ← 0x60329080).
  WB bracketing still applies its steps afterwards (static: they are added after the read, at
  0x603e1a40).
- **Live view / EVF: NOT shown.** The compact ring slot (0x6030bb5b/6e) is redirected and verified up to
  the bytes it writes (+75/+77 of its buffer). But the consumer of that slot, and whether the EVF takes
  its WB from it, is **untraced** (see WB_AND_MONO.md A2). When the compact slot refreshes after a
  profile change is also unknown. The preview may show the stock fine-tune, or update only on the next
  refresh.
- **In-camera RAW development: stock by design.** It reads the global profile, which need not be the one
  the RAW was shot with. A RAW developed in camera therefore uses the stored per-mode fine-tune, not the
  bundle's.
- **Movie, Art Filter and other picture modes:** no override unless the picture mode is 11 or 12 (or 6
  resolving to 11/12).
- **Not proven anywhere:** ISP pixel output and on-camera behaviour.

## Risks

1. **Global profile race (design option A).** The profile and mode are read at getter time, not taken
   from the frame. A profile change between capture setup and these reads could apply the wrong slot.
   The capture-segment reads happen during capture setup, the same phase that fills capture+24083,
   which is static. Burst or buffered behaviour is not checked.
2. **Getter on other cores/contexts.** The stub calls 0x6005e971 four or five more times per read,
   from the same context the site already calls it from. Only the CPU-0 translation was emulated. The
   getter takes no locks and only reads (static).
3. **Category source.** CWB is judged from the global key 33057. Capture can force a category itself
   (0x602a94bf..: one-touch/auto under some conditions); when the global value is CWB, the stub then
   stays stock. That is conservative and verified (W "global CWB, capture forced cat 1").
4. **Override replaces the user's fine-tune** for every non-CWB mode, including a recipe `wb_shift` of
   0/0. Leaving the slot's `wb` out or setting it to `null` restores stock behaviour.
5. **Profile encoding** is assumed to be 1..4, as in v0.2 (V02_BUNDLES risk 1). If it is 0-based,
   COLOR1 gets no override and COLOR2–4 get the A/G of COLOR1–3.
6. **Stack +16 B** on these call paths. Stock call depth headroom is unmeasured (static).
7. **Boot exposure:** the stub is in the section-2 tail, the same class as grain and bloom.
8. **Live view may disagree with the capture**, as described under coverage.

## Run note: bundles verifier on the merged spec

`ep7_verify_bundles.py` on the merged v0.3 + WB spec (132 edits, 1890 bytes): PASS overall, 75 PASS lines
including 19/19 mutations (about 8 minutes).
