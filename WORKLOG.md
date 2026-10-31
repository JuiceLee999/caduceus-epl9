# Work log

Every step, check and decision, newest last. "Verified" = checked by hash or reproducible command.

## 2026-11-01 — Step 1: setup, stock firmware, decode, toolchain

- Supplied archives `reference/om-c-firmware-dbv0.3.0.{zip,tar.gz}` contain only a 15-byte README. Not usable source.
- Basis chosen: fishcu/oly_fw_analysis @ `539fcf1` (submodule `external/`). No licence → referenced, never copied.
- Stock fw: OM catalog (model 1420) offers only v1.1 / build 1100, dated 2022-02-28.
  Downloaded via `tools/fetch_stock.sh`. **Verified** SHA-256 `9d1610…eaeb` = fishcu's reference.
- Project moved from `/mnt/Storage` (NTFS/fuseblk) to `~/projects/ep7-firmware` (btrfs). Toolchains live in `~/ep7fw-toolchains`.
- Decoded with fishcu `oly_container.py` (reviewed first: pure Python, no I/O beyond files).
  **Verified**: exact decode→encode round trip; all 5 component hashes match fishcu's inventory
  (`docs/ep7_1100_components.sha256`). Main CPU base `0x60020020`.
- **Verified** SD updater strings in main: `DCOLYMP/E142????BIN` (body), `S142????BIN` (boot), `G142` (unknown) at decoded `0xf0cb04..`.
- Toolchain: `tools/setup_toolchain.sh` (binutils 2.45 mn10300-elf, GNU sig checked).
- Component roles identified (docs/FINDINGS.md). HSL needs main (0x100) + likely OSD (0x101) for the "Value" graphic, as on PEN-F.
- Toolchain built: binutils 2.45 mn10300-elf in `~/ep7fw-toolchains/mn10300/bin` (GNU signature verified by gpgv).
- **Verified** CPU mapping (base 0x60020020) + fishcu's E-P7 colour addresses: builder 0x603b0068 uses record
  offset 688 and ends `mov d0,(976,a0); retf` at 0x603b024b–0x603b024f, matching their records/control offsets.
- Added `tools/dis.sh` (disassemble by CPU address). **Step 1 complete.**

## 2026-11-01 — Step 2: desktop sims
- Emulator: fishcu MN103 sim built from git commit 87ffb882 (gitiles tarball hash not reproducible; commit + pristine
  file hashes verified; regenerated strict patch byte-identical). fishcu synthetic checks: 50/50 pass.
- `tools/ep7_color_table.py`: E-P7 COLOR table extracted; **verified** SHA `a33d64bd…` = fishcu shared-table hash.
  Records: word0 = sector centre angle, word1 = width, +14 = sat amplitude; per-sector +/- gains.
- `sim/pipeline.py`: ORF→LibRaw linear→tone curve→12-sector engine (firmware angles/gains)→grain→crop.
- `sim/calibrate.py` vs 12 camera JPEGs (testdata, gitignored): colour-only median dE76 ~1–6 (mean 3.1 on CP shots).
- `sim/diff_test.py` Kodachrome(1063) vs warm(1064) same scene: per-hue chroma-ratio error 0.31 without sector
  model → 0.13 with it (corr 0.86). Engine reproduces the camera's Color Profile behaviour approximately.
  Defaults chosen: angle_offset 15°, sat_scale 1.5, base_chroma 1.1 (fitted; not firmware facts).
- `sim/film.py`: recipe renderer limited to camera-feasible controls (stock + planned HSL/grain/vignette).
  Base curve `sim/base_curve.json` = median of 12 fitted camera curves (consistent in shadows/mids).
  Tone-step model cross-checked: 1063 vs 1064 shadow delta ≈ 0.012 luma/step, matches TONE_STEP model.
  Grain scaled for preview size; hue step 5.5°/step is a placeholder pending camera test.
- `tools/build_package.py`: component-selective package + stock restore with stock-byte checks.
  **Verified**: no-op package == restore == exact stock slice; wrong-expect and overlapping edits refused;
  1-byte main+OSD test package re-parses with valid checksums (test output deleted; never SD-named).
- Research agent: `docs/FILM_SIMS.md` (Fuji sim anatomy, 75 sources) + `sim/recipes/fuji_like.json` (10 recipes,
  derived from Fuji's published F-Log2 LUTs relative to Provia). Untested starting points.
- film.py: Monochrome Profile filter mixing (Acros). Contact sheets in generated/film/.

## 2026-11-01 — Step 2: OSD resources (component 0x101), offline

- Added `tools/osd_extract.py`, `sim/ui_mock.py` (+ `sim/screens/*.json`), `docs/OSD.md`. Read-only; hash-checked inputs.
- **Verified**: bank 0 base `0xa3091000`, bank 69 base `0xa3611000`, string base `0xa407f540` (all unique by structural search).
  All 5514 bitmaps (modes 11/10), 245 symbols (mode 1) and 34 font resources (mode 9) decode strictly; visually checked.
- E-P7 8-bit bitmaps are mode 11 (12-bit tokens), not PEN-F mode 3 — PEN-F bitmap patches need re-encoding.
- Palettes: 58 ARGB blocks in main `0x61110a74..0x6111f03c`; render candidate `0x61110e7c`/`0x6111570c` — runtime selection unverified.
- Colour wheel not a bitmap; C3D-drawn (strings `BackGroundCtrl::drawC3dAsync`). Mock wheel is procedural.

## 2026-11-01 — Step 2: PEN-F HSL → E-P7 port mapping (offline)

- Mapped all 153 PEN-F `main_ranges` to E-P7 candidates: `patches/hsl/ep7/port_map.json` (stock bytes read by
  `tools/ep7_port_map.py`; `--check` passes). Write-up: `docs/HSL_PORT.md`.
- **Verified (emulator, `tools/ep7_color_probe.py`)**: builder 0x603b0068 record layout; selector 0x603b0252 runs natively;
  5-byte jmp at 0x603b02d9 → stub → rejoin 0x603b02de works with E-P7 job offsets (request job+11364, records +14576 ×56,
  callback 0x60355fd4, trailer job+15488). Stub exists only in emulator RAM.
- Code-space audit `tools/ep7_code_space.py`: descriptor table 0x60027068, loader 0x600457e7; 8 FF suffixes inside loads.
- No firmware image built, nothing flashed, nothing committed.
- **Independent check of HSL-port agent (me):** hook 0x603b02d9 = `cd8ffdf060` call 0x603b0068 (COLOR builder),
  preceded by `mov 0x6051de2c,a0` (COLOR table). Section table 0x60027068 + end getter 0x60045786 decoded:
  section 2 = 0x60280800..0x6055e800 (contains builder); tail 0x6055e5b0..0x6055e800 all FF, no abs32 refs. Agrees.
- UI agent: `tools/osd_extract.py` (5514/5514 bitmaps, 245 symbols, fonts), `sim/ui_mock.py` + screens, docs/OSD.md.
  E-P7 uses RLE modes 9/10/11 (no PEN-F format 3) → "Value" graphic must be re-encoded. Colour wheel is runtime-drawn.

## 2026-11-01 — Step 3: minimal fixed-H/L patch (offline)
- **Verified (me)** section loader: table 0x60027068 + end getter 0x60045786 → section 2 = 0x60280800..0x6055e800.
- `patches/hsl/ep7-fixed/`: recipe → 5-byte hook (0x603b02d9 `cd8ffdf060` → `jmp 0x6055e5c0`) + 116-byte routine
  (re-issues builder call, inline 16-byte frame, writes hue/L of 12 output records from a constant table, jmp 0x603b02de).
  Native values: H = -1000*slider, L = fishcu LUT; physical record order r ↔ UI 2*(r%6)+r//6.
- `tools/ep7_verify_package.py`: builds the package in memory and runs the native selector from the PATCHED payload
  vs STOCK in the emulator. classic_neg: **PASS** at 4 saturation sets (H/L exact, sat + all other output bytes ==
  stock, ctx == stock, stack/callee-saved OK); 109 changed bytes all inside edit spans.
  Mutation tests (offset 706→708, loop 12→11, stack 16→12): all detected (FAIL).
- Scope limits: emulator covers CPU code only, not the ISP's pixel response, live-view path, or the alternate
  builder 0x603afb94. On-camera H/L direction/scale unverified.
- docs/FEATURE_GAPS.md (me): string + code survey. Key find: recording-duration routine 0x60319139 identical in shape
  to PEN-F 60566309 (1740 s @0x60319156, 7200 s @0x6031915b) → 4-byte port candidate with precedent.
  Code strings for HIGH_RES/pixshift, pro_cap, focus_bracket, C4K exist in main; menu has Flat picture mode.
- ui_mock: image background (live-view stand-in from film renders); screens xpan_live, hsl_live. Aspect crop previews in generated/aspect.
- Independent review (agent, docs/REVIEW_fixed_hl.md): **no blockers, no code defects**. Verdict "not yet":
  H1 E-P7 SD update trigger/acceptance untraced (updater in section 6 ~0x60c96xxx; skips 1 MiB blocks equal to
  flash) → recovery path unproven. H2 main-only packages require camera already on 1.1.
  Medium: power loss mid-write in section 2 (runs at boot before updater); ISP H/L interpretation unverified.
  Confirmed: hook boundaries/liveness, routine bytes, code-space load + no integrity scan, package == stock metadata.
- Next: trace E-P7 SD updater entry + acceptance rules; then a restore-only dry run on camera (user go-ahead needed).
- SD updater trace (agent, docs/SD_UPDATE.md; probe 19/19 PASS): client task 88 FIRMUP_CLI 0x60c95bab → server
  task 18 FIRMUP_SRV 0x60c96030. Accepts model 0x1420 + valid checksums; version NOT checked (same-version /
  main-only OK); all components validated before any erase. Main = full erase+program (corrects review: 0x100000
  is a BOOT type flag — spot-checked by me: `cmp 1048576,d0` on stack arg at 0x60c971ea). LED-only feedback.
  Trigger (button combo) NOT found in main — likely pre-main/sub-CPU. FIRMUP_SRV started only in normal startup
  after section 2 init → a boot-breaking section-2 fault likely makes SD recovery unreachable.
  Safe trigger test: checksum-corrupted restore copy (rejected before erase).

## 2026-11-01 — Step 4: unlock push
- Saved `releases/v0.1-fixed-hl-classic_neg/` (sources + hashes committed; .pkg.bin local only).
- `patches/rec_limit/`: recording-duration routine 0x60319139 (entered via `calls`, ret [d2],28) — operands
  @0x60319157 (1740) and @0x6031915c (7200) → 32400 s. Emulator: native routine patched vs stock, modes
  3/6/8/9/4 all return 32400 s with ret 0, stack/regs intact. **PASS.** Chapter/file/thermal limits untouched.
- `tools/merge_specs.py`; v0.1 + rec_limit combined: fixed-H/L verifier still PASS, 113 bytes changed, all in spans.
- Agents running: film-look research (bloom/halation), colour-grain RE, video-log research (verdict before code).
- Aspect tables found: 9 still aspects in code (5:4, 7:6, 6:5, 7:5 hidden) + 17:9 entry; XPan/21:9 via repurposed hidden slots (FEATURE_GAPS.md).
- Aspect menu mask: simple value-list search (ids 1,2,3,4,9 / codes) found nothing specific → needs schema/menu trace (queued).
- Profile bundles design (docs/PROFILE_BUNDLES.md, bundles/example.json): per-COLOR-slot HSL/grain/WB/effect table; blocker = active profile index at hooks.
- Issues #11 rename profiles (OSD strings + badges), #12 more slots (hard; alternatives listed).
- Decisions: no build-time rename (#11); MONO1–4 become universal bundle slots → 8 slots (#12).
- Film-look agent: docs/FILM_LOOK.md, sim/effects.py (halation, bloom, grain_v2, film_curve, subtractive_saturation,
  color_chrome), sim/recipes/film_look.json (cinestill_800t, portra_400_bloom, classic_neg_halation).
  Findings: no Fuji film sim has halation/bloom (only X-Half film filters); GFX glow ≈ diffusion filter or post.
  E-P7: bloom ↔ Soft Focus (FANTASIC_FOCUS) blend; halation plausible (highlight mask + tint + blur) but unproven.
  **Verified (me):** all 10 fuji_like recipes render byte-identical vs pre-agent film.py; synthetic halation/bloom look correct.
- Profile-index agent (docs/PROFILE_INDEX_WB.md): settings 908 = active COLOR profile (key 63153), 973 = active
  MONO profile (key 63281), getter 0x6005e971(key,idx,a0=0). Capture population stores profile byte at
  capture+24083 (mode 11→COLOR idx, 12→MONO idx). **Verified (me)** at 0x602a859c–0x602a85c0.
  Not transported into job/request → hook can't see it yet. Design: job +1 byte (constructor edits 0x603537f0/
  0x6035390c) + converter hooks 0x603e669f/0x603e91e4; getter fallback for live view. MONO splits at 0x603b02c1.
  WB fine-tune: candidates settings 324/325, 329/330 — unresolved.
