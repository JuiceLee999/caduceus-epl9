# Independent review: E-P7 1.1 custom firmware v0.3 (117 edits, main 0x100 only)

Reviewer: independent and adversarial, working offline only. No device was contacted, no `E142*`-named file
was created, and nothing was committed. The only file written in the repo is this one; scratch work is in the
session scratchpad (`rv3/`). Every result below was re-derived from bytes, using:
- `mn10300-elf-objdump -m am33-2` (full-image disassembly);
- a numpy brute-force index of every relative branch/call encoding (c0–ca, cc/cd, dc/dd, f8 e8–eb, fa ff,
  fc ff) at every byte, plus abs32 values at every alignment;
- an independent package parse.

The authors' documents were used only as a map. Where this review rests on their claims, it says so.

Inputs:
- `releases/v0.3/edits.json` sha `18742c96…`. It matches `build.json`.
- Stock container `9d161012…`; decoded main `5dd9af16…`.
- Rebuilding with `tools/build_package.py` gives byte-identical `patched.pkg.bin` (`70fa567a…`) and
  `restore-stock.pkg.bin` (`245b9c8f…`).

Note: during the review, another process changed `tools/merge_specs.py` and `docs/CODE_SPACE_MAP.md`, and added
`patches/wb/`, `docs/WB_PATCH.md` and `tools/ep7_verify_wb.py` (uncommitted). None of this was done by the
reviewer, and none of it touches `releases/v0.3/` (hashes re-checked at the end).

## Verdict

**Not cleared for flashing as a combined build.** I found no defect that breaks instruction boundaries,
stacks, registers or code space in any hook. The package structure is correct, and the restore image is exact
stock. However:
- One patch deviates from stock behaviour in a way the emulator tests cannot catch (H1).
- The COLOR still pipeline now carries a large untested load on every shot (H2).
- The aspect patch is the only feature whose trigger is **persisted in settings and has no physical escape**.
  Its geometry coverage is admittedly incomplete (H3).
- The restore/update path is still undemonstrated, and its torn-write exposure is now about 4× that of v0.1
  (H4).

Test the features individually, in the order given at the end.

## Findings

### Blocker
None in the code. Procedurally, flashing anything before the stock restore dry run (H4) would be a blocker.

### High

**H1. Grain `wl_hook` bypasses the stock job-type gate, so combiner 32 runs on job types that stock never
grains.**
- Stock key-12 (MONO) handler at 0x6035778b:
  - It reads `movhu (16,a2)` (job+20, the job type).
  - It sends a job to the plain default entry 0x603578a9 (no grain modifier) when
    `type&0xf0 ∈ {0x10,0x20,0x40}` or `type&0xf00 == 0x100`.
  - Only then does it test job+11320.
- `wl_hook` (0x6055e680) attaches `grain_mod` to **every** key-11 job, with no such test.
- Where the type comes from: 0x603ea909 produces 0x110/0x120 for capture-request kinds 0x2001/0x2006 (unless
  0x603ed45a returns 1). The constructor itself strips the effect flags 0x40/0x80/0x300/… for type&0xf00 == 0x100
  (0x60353b15). So stock deliberately keeps both grain and effects off these jobs (special multi-frame captures;
  the exact modes were not traced).
- Effect: COLOR captures of those kinds get stage 0x0902 → combiner 32. That ISP path has never run on stock.
- `ep7_grain_verify` T2 compares against stock key **11**, so it cannot detect this.
- Fix (about 20 B): replicate the 0x6035778b gate in `wl_hook` before attaching.
- This adds to the grain doc's own risk 1: combiner 32 runs on full-size class 0–3 stills, where stock MONO uses
  the two-pass mask route.

**H2. Every COLOR still (all four profiles, no off switch) now runs:**
- grain combiner 32 on the development request;
- Soft Focus reduce → full-res upscale → full-res blend. This needs two extra full-size 2 B/px buffers,
  about 80 MB.
- COLOR shading, which loses its attach slot and becomes a separate kind-3 pass.

Consequences:
- That is 3–4 extra full-resolution passes per shot.
- Untested on hardware: sequential/burst, bracketing, in-camera RAW edit, and the buffer-pool failure path
  (0x60350560 ≥ 48 → 0x9ec3/0x9ece; what stock does next is unknown).
- No emulator test covers memory or timing.
- Bloom's input order is still unproven (W = 881 could be 86 % blur). That is a look issue, not a safety issue.

Not a boot risk if the front Profile Control switch really forces picture mode ≠ 11. This is still unverified
(REVIEW_fixed_hl M2).

**H3. Aspect: the persisted id 6/7 drives a partially re-geometried pipeline at every boot (live view), with no
physical escape.**
- Stock already handles ids 6/7 as 7:6/6:5 in every table. The risk is therefore **mixing**: a buffer sized
  from a patched table (e.g. 640×240) combined with an unpatched consumer that computes 7:6 geometry (560×480)
  overruns by about 2× in height.
- Consumers the authors list as untraced:
  - the live-view grid selector;
  - Art Filter / bracketing / tele-converter geometry;
  - 18 key-0x3081 getter sites;
  - layouts the scanner does not cover;
  - users of the ratio codes 0x1841/0x0915.
- The `.data` tables (0x60230800–0x6025eb50) are copied at reset (0x600201f9) to RAM at 0x61f98540, so they are
  writable at runtime. Runtime rewrites were not excluded.
- Once Panorama/Wide is selected, live view runs this at power-on.
- The SD-update trigger is unknown (SD_UPDATE §1), so a fault that recurs every boot may not be recoverable.

Verified OK:
- S1–S5 case blocks: the registers are correct for each join (d2/d3, d3/d2, d1/d0, d0/d1, (24,sp)/(28,sp)).
- The jump-table entries index the right slots, and the S6 data entries are correct.
- The 2×16-B rect rows follow the stock rule.
- The menu descriptor count 8 is fine: other lists have up to 62 entries.
- The list lies inside sec 6 (the load ends 0x61243000). Stock data ends 0x612429af, and there are no
  references into the tail.

### Medium

**M1. Aspect heights break the alignment invariant of the reachable rows.**
- `build.py` clamps alignment at 8. In 13 tables (the 1024/1280/2560/320 classes), every UI-reachable stock row
  is 16-aligned. The only 8-aligned rows there are the hidden 6:5 rows (e.g. 912×760).
- New rows such as 1280×472/552, 1024×376/440, 2560×1096 and 320×120/136 are heights the shipped firmware never
  produced. The JPEG M/S sizes with Panorama/Wide hit them.
- L (1912/2224) is in the same 8-aligned class as stock 2920/3704, so L is fine.
- Recommendation: round to 16 in those tables, or test every M/S size on the camera.

**M2. A stored aspect 6/7 survives the stock restore.**
- Stock still handles the geometry (7:6/6:5).
- The generic lookups are bounded and write only on a hit:
  - icon 0x60df24d7: loop ≤ count, store only on match;
  - option list 0x60df250b: stride 12, ≤ count.
- So a miss most likely gives a blank or stale label/icon, not an out-of-bounds read. Caller defaults were not
  traced.
- Patched-aspect JPEG/ORF files played back on stock are untested.
- Mitigation: set 4:3 before any restore or re-flash (and in any saved/custom set). Don't play back
  Panorama/Wide files on stock until this is checked.

**M3. Video log (verified hook; behaviour inferred).**
- Verified:
  - The 5-B hook at a `call`-entered function entry is correct.
  - The stub reads the same fields stock reads (A+332 is read as a u32, as at 0x6030d902).
  - It returns through stock `retf [a2],4`; a2 is restored by the retf mask, and MDR is untouched.
- Stills cannot get 2000/2001: both still mapper callers pass b6 = 0. Checked at 0x603eaa2d (`(18,sp) = 0`) and
  0x603ecec0 (`(46,sp) = 0`).
- Inferred or untested:
  - id 3 = Muted;
  - effect id 2001 in 4K/FHD60. Because the properties are untouched, any stock log/mode restrictions and the
    log AE do not engage.
- It runs on every settings update, including at boot. Escape: the mode dial away from movie (A+332 ≠ 1).
- Nothing persists: +925 lives in a RAM record.

**M4. Undemonstrated stock assumptions carried from v0.1/v0.2.**
- Whether live view uses the COLOR builder or work-list paths (M2 of the prior review).
- Profile encoding 1..4.
- The H/L ISP semantics.

### Low

**L1. Recording limit.**
- `mov imm16` 1740/7200 → 32400. It is positive, and the routine stores a u32.
- The routine is reached indirectly (its only reference is 0x60319174).
- Thermal and file-size limits are unchanged.

**L2. Job size 15488 → 15512.**
- The allocator 0x60022700 is fixed-block, with classes ≤128/≤2048/≤16384. Pool 2 has 64 blocks per core
  (0x600228b6). The class and capacity are unchanged.
- Decimal 15488 occurs only at 0x603537f0 (0x609393fb is an unrelated wrapper with d0 = 4). There is no other
  displacement ≥ 15479.
- Memset 15472+40 = 15512 exactly.
- All 5 converter calls follow the constructor directly on its returned job. Constructor: `ret` d0 = a3 = job.
  Converter: d3 = (job slot)+36 via 0x60353cfb, so `(15452,d3)` = job+15488. Status (12,sp) ≠ 0 skips the
  converter on allocation failure.
- `hl` dereferences job+15490 only after the arithmetic record match. The stack-built requests (0x60368b30)
  cannot match.

**L3. Interior branch scan.** No branch of any encoding, no abs32, and no 0xA… alias targets the interior of any
code hook. The table-row hits are data false positives.

### Notes (checked, no issue)

**Hooks.** All 12 code hooks:
- start on instruction boundaries and replace whole instructions;
- leave the nop padding unreachable;
- give a resume point whose flags are either recomputed or replayed: conv2 and `bloom_flag` replay the
  `cmp`, and every other resume recomputes flags first;
- contain no `setlb` in any stub and sit inside no Lcc loop;
- clobber no MDR. This matters for the `retf` functions 0x6030df3d, 0x6039fee8 and `grain_mod`.

Call masks and frames match the callees:

| Call | Callee returns with |
|---|---|
| `call 0x6035739e,[d2,d3,a2,a3],16` | `retf …,16` |
| `call 0x603573d3,[a2,a3],8` | `retf …,8` |
| builder `call …,96` | same as stock |

`grain_mod` is entered with `calls` and returns with `retf [],0`, the same as stock 0x60359e5e. `hl` saves and
restores d0–d3, a0, a1, a3 in a 28-B frame below the released builder frame.

**Code space** (loader 0x60027068 plus the end getter's jump table at 0x60046780). The loader is called only from
boot, 9 times in order 1,7,2,3,4,5,6,8,9. Nothing is reloaded or loaded late.

| Section | Loaded range | Stock data ends | Placements |
|---|---|---|---|
| sec1 | 0x600d7800–0x60211000 | 0x602108eb | 0x60210900–c70, c90–cba, f00–f6e |
| sec2 | 0x60280800–0x6055e800 | 0x6055e5af | 0x6055e680–6fb, 7b0–7e2 |
| sec6 | 0x60ba7000–0x61243000 | 0x612429af | 0x61242f00–f60 |

- Every gap is ≥ 20 B of FF, and nothing overlaps.
- The only abs32 references into the tails are section-end constants. The other hits were checked as
  mid-instruction or pointer-table false positives (0x6086f774, 0x6020ec90, 0x607a21ea).
- No code sits before its section is loaded: sec2/sec5 hooks jump into sec1, which loads first.

**Package.**
- Header and trailer[0:28] are identical to stock; the checksum validates.
- Exactly 1,674 payload bytes differ, all inside the 117 edit spans, and payload == stock + edits.
- The restore equals stock[0:26214400].
- Changed 1-MiB flash blocks: 8, versus 2 for v0.1. They include 0x40800000, which holds the end of sec 1 and
  the reset-copied `.data`.

**H4 (carried from REVIEW_fixed_hl H1/H2/M1).**
- The SD trigger, main-only acceptance and the restore are undemonstrated.
- The camera must report 1.1.
- A torn write in any of the 8 blocks kills boot before the updater (the block-0x40800000 data is used at
  reset).

## Recommended camera test order (each as its own package, stock restore in between)
0. Confirm the camera reports firmware 1.1. Dry-run the restore (stock-on-stock). On stock, confirm the Profile
   switch escape. Set aspect 4:3, a non-COLOR picture mode, and the mode dial off movie. Full battery and a
   formatted card.
1. **rec_limit** (4 B, movie only). This proves the patched-install path at the lowest risk.
2. **video_log**. It runs at boot, but it is tiny and verified. Test stills in Muted first, then movie (4K and
   FHD); escape with the mode dial.
3. **bundles v0.2**. The converters run on every shot in every mode, so shoot P/Natural first, then COLOR1–4
   single frames.
4. **grain**, only after the H1 fix. COLOR single frames, then special capture modes.
5. **bloom**. COLOR single frames at strength 1, then sequential/burst stress.
6. **grain + bloom** burst stress.
7. **aspect**, last and alone (after M1 rounding if adopted). Check every size and JPEG/ORF, the live view and
   info screens, and playback. Return to 4:3 before any further flash.
8. The combined build only after 1–7 pass and the restore has been re-proven.
