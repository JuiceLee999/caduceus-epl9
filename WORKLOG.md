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
