# Caduceus → E-PL9: feasibility (static, 2026-11-07)

No camera touched. Sources:
- E-PL9 `OLY_E_133_1101_0000_0000.BIN` (OM catalog model 133, SHA-256
  `aefab05396c43ecba0551b94a5d31f7e52350c18d6f4bf1d02d75761108e6028`, 104 552 480 B). It is kept in `stock_firmware/epl9/` and never
  committed. Decoded with `oly_container.py` into `analysis/epl9_1101/` (main = `00_0100_406e0020.decoded.bin`).
- E-P7 `OLY_E_142_1100_0000_0000.BIN` (SHA-256 `9d161012…eaeb`, hash matches upstream).
- Tools: upstream `oly_container.py` and `tools/port_sigmatch.py`.

## Container
- Same format. Checksums valid; repacking gives a byte-identical file.
- Main (0x100): 26 214 336 B, the same size as on the E-P7. Container address `0x406e0020` (E-P7: `0x406a0020`).
- Same CPU: the first bytes of startup code are identical to the E-P7's.
- Components 0x101, 0x106, 0x10e and 0x102 are all present. 0x102 is at `0x468e0020`, the same as on the E-M10 IV.

## Signature match (E-P7 edits found in E-PL9 main)

| Edit list | Edits | Auto (same+shifted) | Absent |
|---|---:|---:|---:|
| v0.20 (the list upstream used for the E-M10 IV) | 294 | **35 %** (E-M10 IV: 48 %) | 60 % |
| v0.29a (current) | 365 | 31 % | 62 % |
| test1 rec limit | 2 | 0 % (E-M10 IV: 100 %) | 100 % |
| test2 log video | 4 | 0 % (E-M10 IV: 100 %) | 100 % |
| test7 SD loader | 33 | 3 % | 97 % |

## Profile system
- `PROFILE` strings: 0 (E-P7: 21).
- `COLORTONE` strings: 61 (E-P7: 213; E-M10 IV: 62).
- **No Color/Mono Profile system.** As with the E-M10 IV, the looks, editor, mono presets and bundles need a new host.

## Reading
The E-PL9 is an older build than the E-M10 IV. Even the small, self-contained patches do not match by surrounding bytes, so
every hook has to be found again by hand: disassembly plus the emulator. This is a fresh port that uses the E-P7 as a
map, not a relocation of the E-P7 patches.

## Colour engine (found 2026-11-07)

The per-hue colour path that Caduceus hooks on the E-P7 (and the PEN-F HSL mod hooks on the PEN-F) **is present in
the E-PL9**: nearly identical code with one constant shift per area. The builder, selector and hook contract now pass
in the emulator (see [Emulator results](#emulator-results-2026-11-07) below).

| Piece | E-P7 1.1 | E-PL9 1.101 | Match |
|---|---|---|---|
| COLOR builder | `0x603b0068–0x603b0247` | `0x603be9e2` (+59 770) | 113 / 116 unique 12-byte windows, all the same shift |
| selector | `0x603b0252–0x603b0345` | `0x603bebcc` (+59 770) | 47 / 57 |
| writer | `0x6034667e–0x6034677b` | `0x60360cf0` (+108 146) | 61 / 60 (all windows) |
| COLOR table | `0x6051de2c` | file `0x6050e360`, **runtime `0x608ee360`** | 4 / 4 64-byte chunks |
| gains | `0x60531810` | file `0x60520230`, **runtime `0x60900230`** | 12 pointers + values identical after relocation (the earlier `0x604f27ec` was a false match on `0x3ff03ff` filler) |
| **color_hook** (`call builder`) | `0x603b02d9` | **`0x603bec53`** | the only caller on both bodies |
| `call selector` | `0x603b14f3` | `0x603bfc15` | the only caller on both |
| `call writer` | `0x60345f8f`, `0x60345fb1` | `0x60360601`, `0x60360623` | the same two callers |

Callers were found by scanning for MN103 `call`/`calls` (d16 and d32) to each entry point.

**What this means:** the hook where looks inject hue, saturation and lightness per sector exists. What's missing is
the E-P7's COLOR *profile* UI and storage around it. Next questions, for the emulator:
1. When does the stock E-PL9 reach `0x603bec53`? Picture modes, Art filters (e.g. Partial Color) or never?
2. Does a non-zero per-hue table there change the output, as on the E-P7 (`tools/ep7_color_probe.py`)?
3. Which existing E-PL9 setting can host a look: a picture mode slot (e.g. Custom) or an Art filter?

## Emulator results (2026-11-07)

`tools/epl9_color_probe.py` (the E-P7 probe, re-mapped) runs the stock E-PL9 code in fishcu's strict MN103 runner.
Synthetic RAM fixtures only; no ISP, pixels or camera behaviour; the test stub lives at a synthetic address and is
never packaged. **All 9 checks pass**, with the same instruction counts as the E-P7 probe.

| Check | Result |
|---|---|
| A builder `0x603be9e2` | Writes 12 output records at +688 and control `0xfff` at +976; table H/L overrides propagate |
| B selector `0x603bebcc`, mode 11 | Reaches the builder, returns cleanly, callee-saved registers intact |
| C hook `0x603bec53` → stub → rejoin `0x603bec58` | Stub's H/L land in all 12 records in wheel order; saturation and context unchanged vs stock |
| C− wrong callback / foreign parent | Output byte-identical to stock |
| C record index 0 / 15 | Same result as index 5 |
| D gate | **Only mode word 11** reaches the builder (tried 0–19 and two high-byte variants); the `0xf00d` bypass skips it |
| E edit the RAM table at `0x608ee360` | Hue (+12) and lightness (+16) reach the output; +14 does not. Output saturation comes from request+1813 × gains |

**E-PL9 layout (found statically, confirmed by C):**

| | E-P7 1.1 | E-PL9 1.101 | Where |
|---|---|---|---|
| Data relocation | none | runtime = file + `0x3e0000` (initialised data copied to RAM) | selector literal, gains pointers |
| Saturation bytes | request+1816 | **request+1813** | selector `0x603bec42` |
| Job size | 15488 | **14552** | constructor `mov 14552,d0` at `0x6036df09` (the only one) |
| Request in job | +11364 | **+10440** | `0x6036f961` |
| Records | job+14576 (request+3212) | **job+13640 (request+3200)**, stride 56 ×16 | 4 / 6 mapped references |
| Job callback | `0x60355fd4` | **`0x603704f6`** | request-header init `0x6036f225` |

**Answers so far:**
2. **Yes.** Per-hue hue/lightness reach the builder's output, either from a hook at `0x603bec53` or from the table
   itself. The table is in RAM on this body, so a runtime write would also work, but it's global (it isn't per look).
1. **Partly answered.** The hook only runs for request mode word 11, which is the COLOR picture mode on the E-P7. The
   E-PL9 has no COLOR profile in its menus, so the open question is whether any stock E-PL9 setting produces mode 11,
   or whether a look host would have to set it. Next step: trace what writes request+8 (header init copies it from
   its source+8) back to the picture-mode / Art-filter value. The E-P7 converter gates (`0x603e66ab`, `0x603eaa04`)
   only map weakly (1–4 votes), so this needs disassembly rather than signature matching.

**Reproducing:** in WSL, build mn10300 binutils (`tools/setup_toolchain.sh`) and the emulator engine
(`external/oly_fw_analysis/tools/build_mn103_emulator.py`; see its `docs/tooling/EMULATOR.md`), then
`python3 tools/epl9_color_probe.py`. The googlesource archive's gzip bytes are regenerated on download, so its
SHA-256 may not match the pinned one. Check the extracted tree against a git checkout of commit `87ffb882` instead.
