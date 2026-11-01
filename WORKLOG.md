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
- Colour grain (agent, docs/GRAIN_PORT.md): 3 gates (converter copies grain only for mode 12; work-list gives COLOR
  no grain pass; combiner selector maps 0x0901/0x0902 only for key 12). Approach B built: hooks 0x6035749f,
  0x603b5249 + 123 B @0x6055e680–0x6055e6fa; COLOR gets MONO's single-pass grain (combiner 32, gain 50/75/100).
  **Re-run by me:** tools/ep7_grain_verify.py all PASS; merged v0.1+grain+rec_limit = 7 edits / 243 B, H/L verifier PASS.
  Main unknown: combiner 32 never used on full-size stills in stock (possible size limit) — on-camera test needed.
- **Video log (agent, docs/VIDEO_LOG.md): hidden log modes found.** Movie picture-mode ids 2000/2001 (settings byte
  +925 = 1/2 via 0x60349297) with own gamma tables 0x604f4278 / 0x604f4478, identity luma curve, picture params
  zeroed (same lock-out OM uses for Flat/OM-Log400). id2001 = true log: ~12.4%/stop, within 0.8% of pure log over
  1–6 stops below clip, linear toe. Precedent: E-M1 II (TruePic VIII) got OM-Log400 via fw 3.0.
  **Verified (me):** probe passes; independent read of tables: default 100/88/67/46/27/15/8/4/2 % vs
  id2001 100/88/75/63/50/38/27/18/10 % at 0..8 stops below clip.
  Open: X1 who writes +925 (menu/setting), X2 movie frames use this builder. No patch code yet (per user).
- WB/MONO agent (docs/WB_AND_MONO.md): WB fine-tune = per-WB-mode s8 arrays (keys 0x84F9 A-B, 0x9679 G-M, 20 modes;
  CWB none). Per-profile override = redirect all 16 getter call sites to 166-B stub @0x6055e700. **Re-run (me):**
  wb probe S/W/G PASS; mono probe PASS. LV coverage inferred, not proven. MONO→colour needs 3 hooks
  (selector 0x603b02c1, chroma 0x603b134e, filter guard 0x60353db9); chroma stage 0x603b132a makes grey.
- docs/CODE_SPACE_MAP.md: allocation registry for all patches.
- SD mod loading design (docs/SD_MODS.md, user idea): data-from-card first; remove card = stock.
- v0.2 bundles (agent, docs/V02_BUNDLES.md): job +24 B, converter stubs copy profile/mode/marker, 8×64 table @0x60210900
  (section-1 tail). **Re-run (me):** tools/ep7_verify_bundles.py overall PASS (A/B/C/D + 19 mutations). Risk: profile
  stored as 1–4 assumed (check COLOR1 isn't stock on camera); live view shows stock H/L.
- Bloom (agent, docs/BLOOM_HALATION.md): Soft Focus = job flag 0x80 (shrink 160×120 → upscale → combiner 11 linear mix).
  Patch: 2 hooks + 51 B @0x6055e7b0. **Re-run (me):** ep7_bloom_verify T1–T5 PASS on merged build (10 edits/304 B).
  Halation: design only (per-channel controls; true red tint not possible). Risk: blend input order → test strength 1.
- Aspect (docs/ASPECT.md, patches/aspect): setting 270 ↔ key 0x3081; menu = option list {270,6,0x6117a834} (4:3,16:9,3:2,1:1,3:4,17:9);
  ratio code (H<<8)|W. Repurposed id6 → XPan 5184×1912 (0x1841), id7 → 21:9 5184×2224 (0x0915) across 44 tables + 6 sec-5 switches;
  list relocated to 0x61242f00 ("Panorama"/"Wide" labels), case blocks 0x60210f00. build.py: 136 checks PASS, 101 edits/950 B.
  Open: 17:9 menu filter, icon-miss path (ids 6/7 have no icon), LV grid selector, art/bracket paths.
- Log video (agent): no hidden menu; option A code patch: hook 0x6030df3d → 42-B stub @0x60210c90; movie + Muted →
  +925=2 (log id 2001). Emulator PASS (stills unaffected). Muted = picture-mode id 3 inferred.
- Aspect (agent, docs/ASPECT.md): setting 270, menu list 0x6117a834 → new 8-entry list; id 6→XPan 5184×1912,
  id 7→21:9 5184×2224 (labels reuse "Panorama"/"Wide"). 101 edits; 136/136 checks PASS. Risks: icon miss, 17:9 filter.
- merge_specs: namespaced per-patch metadata. **v0.3 candidate (me):** all 6 merged = 117 edits / 1,674 B;
  bundles 75/75, grain 5/5, bloom 5/5, video_log, aspect PASS. Saved releases/v0.3-candidate (pkgs local only).
- Saved v0.3 (releases/v0.3, git tags v0.1/v0.3). Status page v2 published. Agents: v0.3 review, WB patch build, MONO-colour build. SD-loader agent stopped (brief truncated); SD loading paused.
- MONO-colour agent (interrupted before implementing): mono filter = 3×3 matrix id via guard 0x60353db9 → request+1802
  (selector 0x603acfe4); toning in chroma stage 0x603b134e; selector redirect needs 6 bytes at 0x603b02bf → 0x603b02d9;
  H/L hook must accept mode 12; candidate code space section 7 tail 0x61378c68–0x61379000; MONO grain/shading still run.
- **v0.3 review (agent, docs/REVIEW_v03.md):** no structural defects; not cleared as combined build. H1 grain hook skips stock job-type check (0x6035778b) → fix. H2 grain+bloom on every COLOR shot, no off switch. H3 aspect persists at boot. H4 restore unproven. M1 aspect heights → round to 16. Test order: rec_limit → log → bundles → grain → bloom → aspect → combined.
- Step-0 camera kit (releases/step0-kit): corrupt trigger-test + exact stock restore; corrupt copy fails additive checksum; native validator rejects bad checksum with 0x3211 / 0 writes (USB + SD modes).
- Per-profile WB (agent, docs/WB_PATCH.md): 164-B stub @0x6055e700 + 14 getter redirects (RAW-dev sites stock). Merged v0.3+WB 132 edits/1890 B: bundles, grain, bloom, WB (20/20 mutations) PASS. LV unproven. Example recipes carry wb_shift → applied when override set.
- **Camera step 0 (user, 2026-11-01):** fw 1.1 confirmed. OK+power starts SD updater. Corrupt file: ~15 s solid → fast blink (rejected, as predicted). Stock main-only restore: identical ~15 s solid → fast blink = REJECTED, nothing written; camera boots fine on 1.1. Battery ~50%. Emulator modelled only the validator → real path has an extra check. Agent tracing (docs/SD_REJECT.md).
- SD looks loader (agent, docs/SD_BUNDLES.md): fopen/fread API found (FILECLBK task 16); hook at media 'MOUNT OK' 0x60863e90; 564-B loader @0x61242a00 reads C:\EP7MOD\BUNDLES.BIN (CRC/range-validated) into table 0x60210900. **Built, NOT emulator-verified yet** (WIP). Desktop writer tools/ep7_bundles_bin.py.
- SD reject trace (agent, partial): validator ACCEPTS exact stock main-only on real bytes (mode 0 → 1 write 0x806a0000 size 0x1900000, chained emulation); server E-path has no date/version/size checks. Rejection likely pre-erase guard in flash writer (battery?) — tracing. Same 15 s solid for both files ≈ file read time → nothing erased.
- SD reject (agent, docs/SD_REJECT.md): no visible check rejects stock main-only; no battery check on E path. Hypotheses: OK+power isn't task 88; file read truncated; misread blink. Zero-write tests: T1 no E-file, T2 tiny corrupt E-file (timing), T3 full battery.
- MONO-colour (agent, docs/MONO_COLOUR.md, patches/mono_colour): bundle slot +32 `colour` (==1) / +33 `sat[12]` (−5..5);
  hooks 0x603b02bf (selector → COLOR builder with slot sat + slot H/L, own copy of v0.2 hl logic so v0.3 merges unchanged),
  0x603b134e (chroma a0=0, MDR restored), 0x60353db9 (params+5528/5529 = 0, merge skipped); 764 B @0x61378c80 (sec-7 tail).
  tools/ep7_mono_colour_verify.py on v0.3+mono_colour (121 edits/2438 B): 213/213 + 20/20 mutations PASS; demo bundle
  bundles/mono_colour_example.json R test PASS. ep7_verify_bundles now maps the sec-7 tail. Grain/bloom/bundles verifiers
  PASS at HEAD versions; working-tree versions are mid-v0.4 rewrite (not v0.3-compatible). Open: MONO grain/shading,
  0x60367ee3 skipped pass, LV stays mono, EXIF Monotone.
- Review fixes (agent): H1 grain job-type check (T6 77 rows), H2 grain/bloom per-slot & off by default (bloom_flag uses capture bytes), M1 heights ×16. v0.4-candidate merged 117 edits/1,969 B, all verifiers PASS.
- MONO→colour (agent, docs/MONO_COLOUR.md): 3 hooks (0x603b02bf, 0x603b134e, 0x60353db9) + 764 B @0x61378c80 (sec 7). Slot +32 colour, +33 sat[12]. 213/213 tests, 20/20 mutations on v0.3+mono. Needs re-verify on v0.4 merge.
- Full merge (agent): v0.4 + WB + MONO-colour + SD loader = releases/v0.4-candidate/edits_full.json, 138 edits / 3,504 B. All 9 verifiers PASS (SD: 173 cases + 7 sequences + 17/17 mutations). Open: section-6/1 RAM writability for loader state + table.
- **REVIEW_v04:** no code defects; B1 blocker = no proven install/recovery path. H1-new SD loader hook dead (confirmed by me at 0x60863e4f/0x60863e62) → excluded. Saved releases/v0.4 (no SD loader), tag v0.4.
- **Buttons (agent, docs/BUTTONS.md, patches/buttons):** buttons = settings whose value is a function code; menu/stepping read the
  static validator lists (0x604cc98c, no availability filter for button sids); dispatcher 0x60cc872f maps key->sid->code->action
  (55-entry table 0x60f38af8) with no per-key check. Arrow right/down = sids 51/53 (8 codes), up/left 50/52 fixed (no list).
  **Built** data-only, 10 edits/100 B in place (sec 2): sids 47/48/49 -> 23 codes (+Multi Function, ISO/WB, HDR, BKT, Level, ...),
  arrows 51/53 -> 16 codes (+ISO/WB, WB/ISO, Peaking, Magnify, Level, tele-con, Multi Function, RAW). tools/ep7_buttons_verify.py
  S/V/N/A/M PASS. Merge releases/v0.5-candidate/edits.json (v0.4 + buttons, 146 edits/3,005 B): bundles, grain, bloom, WB,
  MONO-colour, buttons verifiers all PASS. Queued: profile-slot select (no function code exists), ISO/WB-only, up/left, movie arrows.
- Aperture ring (agent, docs/APERTURE_RING.md): port of fishcu PR #4 with E-P7 fix (81 E3 kind 4/5 → parse rule (kind&2)==0). 6 edits/223 B; dispatcher 1921/1921, parser 600/600, AE 298/298, 8/8 mutations. Merges with v0.4 (142 edits), other verifiers pass. Risks: section-1 RAM write, Panasonic ring word from PEN-F reports only.
- Camera: official full 1.1 file w/ FULL battery → same solid (1–2 min) then ~2 Hz blink. fishcu PEN-F INSTALLATION.md: 'blinks rapidly on completion' = SUCCESS → our fast=fail inference likely wrong; updates may have succeeded (invisible: same firmware). Probe: OSD-only package (7 bytes, Setup 'Firmware'→'FIRMWARE'); emulator: OSD-only accepted, writes only OSD region. build_package now allows OSD-only.
- **CAMERA PROOF (user):** OSD probe flashed via SD (OK+power) → Setup shows 'FIRMWARE'. ⇒ SD updater writes; ~2 Hz blink after solid = SUCCESS (code-derived fast=fail was wrong). Earlier stock main-only restore + official full reinstall therefore also succeeded (camera fine on 1.1). REVIEW_v04 B1 resolved: install + recovery path proven.
- v0.5 = v0.4 + buttons + aperture ring: 152 edits / 3,233 B; all 7 verifiers PASS (background run).
- **TEST 1 PASSED (camera):** rec_limit flashed via SD; movie remaining time now ~1 h (card-limited) vs stock 29-min cap; stock OSD restored.
- **TEST 2 PASSED (camera):** movie + Muted records log-looking footage.
- Test 3 verify (releases/test3-full/VERIFY.log): all functional checks PASS (buttons, aperture, grain, bloom, WB 25, MONO 234, bundles 73). Undetected mutations (WB 3, bundles 1) are config-dependent: they need WB override / COLOR3 enabled, which the personal bundle leaves off; same code catches them on the example bundle. Cleared to flash.
- **TEST 3 FAILED (camera): BOOTLOOP** with releases/test3-full (bundles-lachlan, wb, grain, bloom, mono_colour, rec_limit, video_log, buttons, aperture_ring). **Recovered**: battery out → OK+power with stock main restore → success, camera back to stock. ⇒ SD updater reachable even from a bootloop. Next: bisect one feature per flash; test4 = rec_limit + video_log + buttons.
- Buttons dropped (user). Test 4 = rec_limit + video_log + bundles-lachlan.
- Aperture ring parked (user) — excluded from builds; kept in repo for community later.
- Agents: SD loader v2 (boot-safe, post-boot trigger), film-sim library + menu design, log view-assist feasibility.
- Bootloop analysis (agent, docs/BOOTLOOP_T3.md): #1 aperture ring (runs at power-on every lens request; bit 0x80 unproven; parser consumes 2 bytes unconditionally), #2 WB (4 LV-start sites), #3 MONO chroma; bundles low risk at boot. Test 4 (rec+log+bundles) cleared.
- **TEST 4 PASSED (camera):** rec_limit + log + bundles booted fine; COLOR2/COLOR4 colours visibly changed.
- Fuji gaps (agent, docs/FUJI_GAPS.md): Clarity likely feasible (Soft Focus + weight>1024 unsharp, effect_id 3); split toning feasible via per-channel RGB gamma setter 0x603ae7d3; LV preview partial; red halation partial (combiner 156 colour word + mask); 3D LUT infeasible; grain size infeasible; colour grain chroma gains possible.
- Film library (agent, docs/FILM_LIBRARY.md): menu labels CAN come from runtime text (kind 5/6/12 entries draw a C string pointer). Cheapest Film Sim menu: switch ~40 COLOR/MONO option entries to kind 5 pointing at 8 name cells loaded from card. Library v2 format + tools/ep7_library.py (18-look example, 12 corruption tests rejected). Mocks docs/img/ui_film_sim_*.jpg.
- Log View Assist (agent, docs/LOG_VIEW_ASSIST.md): feasible via dormant display-controller RGB LUT (loader 0x60187439, regs 0x9c002000/0x9c000204, steps 17–19 empty); LUT = default∘inverse(log). Trigger site undecided (needs frequency/blocking trace). HDMI stays log. Not built.
- Test 5 verified (grain 7/7, bloom 6/6, bundles 73 functional; config-dependent mutation miss only). Loaded on card. Test-4 camera shots copied to testdata/camera_t4 (36 JPG/ORF, 4 MOV).
- SD loader v2 (agent, docs/SD_BUNDLES_V2.md): trigger = first shutter half-press (hook 0x602c805f in HLS_EVENT task), 659 B in section-3 tail; nothing at boot. Verifier from upstream event: 173 runs + 10 sequences + 15/15 mutations PASS. Risk: possible event-queue deadlock at that press (UI hang; battery pull recovers). Needs independent review before camera.
