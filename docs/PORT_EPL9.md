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

**Addresses.** The E-PL9 main image loads at **`0x60400020`** (the E-P7's at `0x60020020`), so for E-PL9 main,
file offset = address − `0x60400020`. Every absolute pointer agrees: job callback, key-hash handlers, COLOR table,
gains, the picture-mode lists. All E-PL9 addresses below are runtime addresses. Earlier drafts used the E-P7 base
and listed E-PL9 code `0x3e0000` lower (e.g. builder `0x603be9e2`), and misread the difference as a data relocation.

The per-hue colour path that Caduceus hooks on the E-P7 (and the PEN-F HSL mod hooks on the PEN-F) **is present in
the E-PL9**: nearly identical code with one constant shift per area. The builder, selector and hook contract pass
in the emulator (see [Emulator results](#emulator-results-2026-11-07)).

| Piece | E-P7 1.1 | E-PL9 1.101 | Match |
|---|---|---|---|
| COLOR builder | `0x603b0068–0x603b0247` | `0x6079e9e2` | 113 / 116 unique 12-byte windows, all the same shift |
| selector | `0x603b0252–0x603b0345` | `0x6079ebcc–0x6079ecbf` | 47 / 57 |
| writer | `0x6034667e–0x6034677b` | `0x60740cf0` | 61 / 60 (all windows) |
| COLOR table | `0x6051de2c` | `0x608ee360` | 4 / 4 64-byte chunks |
| gains | `0x60531810` | `0x60900230` | 12 pointers + values identical (an earlier `0x604f27ec` was a false match on `0x3ff03ff` filler) |
| **color_hook** (`call builder`) | `0x603b02d9` | **`0x6079ec53`** | the only caller on both bodies |
| `call selector` | `0x603b14f3` | `0x6079fc15` | the only caller on both |
| `call writer` | `0x60345f8f`, `0x60345fb1` | `0x60740601`, `0x60740623` | the same two callers |

Callers were found by scanning for MN103 `call`/`calls` (d16 and d32) to each entry point.

## Emulator results (2026-11-07)

`tools/epl9_color_probe.py` (the E-P7 probe, re-mapped) runs the stock E-PL9 code in fishcu's strict MN103 runner.
Synthetic RAM fixtures only; no ISP, pixels or camera behaviour; the test stub lives at a synthetic address and is
never packaged. **All 9 checks pass** at the runtime addresses, with the same instruction counts as the E-P7 probe.

| Check | Result |
|---|---|
| A builder `0x6079e9e2` | Writes 12 output records at +688 and control `0xfff` at +976; table H/L overrides propagate |
| B selector `0x6079ebcc`, mode 11 | Reaches the builder, returns cleanly, callee-saved registers intact |
| C hook `0x6079ec53` → stub → rejoin `0x6079ec58` | Stub's H/L land in all 12 records in wheel order; saturation and context unchanged vs stock |
| C− wrong callback / foreign parent | Output byte-identical to stock |
| C record index 0 / 15 | Same result as index 5 |
| D gate | **Only mode word 11** reaches the builder (tried 0–19 and two high-byte variants); the `0xf00d` bypass skips it |
| E edit the table at `0x608ee360` | Hue (+12) and lightness (+16) reach the output; +14 does not. Output saturation comes from request+1813 × gains |

**E-PL9 layout (found statically, confirmed by C):**

| | E-P7 1.1 | E-PL9 1.101 | Where |
|---|---|---|---|
| Saturation bytes | request+1816 | **request+1813** | selector `0x6079ec42` |
| Job size | 15488 | **14552** | constructor `mov 14552,d0` at `0x6074df09` (the only one) |
| Request in job | +11364 | **+10440** | `0x6074f961` |
| Records | job+14576 (request+3212) | **job+13640 (request+3200)**, stride 56 ×16 | 4 / 6 mapped references |
| Job callback | `0x60355fd4` | **`0x607504f6`** | request-header init `0x6074f225` |

So per-hue hue and lightness reach the builder's output on this body, from a hook at `0x6079ec53` or from the table.

## Mode 11 trace (2026-11-07): the stock E-PL9 never reaches the hook

**Result: the COLOR-profile pipeline is in the E-PL9 firmware but switched off. The picture-mode setting can't
hold 11, so stock stills never reach `0x6079ec53`.** All [V], static.

How the mode reaches the selector (same chain as the E-P7, one constant shift per body):

| Step | E-P7 1.1 | E-PL9 1.101 |
|---|---|---|
| Slot 0 filled from picture-mode property `0x9481` (38017); mode 6 Custom → base mode from `0x9d11` (40209) | `0x602a857e` | `0x606955ec` |
| Slot table (record stride / slots) | capture+24810 (46 / 48) | capture+23714 (44 / 40) |
| Slot byte → capture picture-mode byte | `0x603e204a` → capture+24053 | `0x607cb7d2` → capture+22955 |
| Converter checks of that byte for **11** (and 14) | `0x603ea9a9`, `0x603ea9e9` | `0x607d2646`, `0x607d2685` |
| Key written for the request | `0x603eaa04` | `0x607d26a0` |
| Picture-mode key hash (no 11 or 12 on either body; 11 goes straight to the selector) | `0x60532510` | `0x60900db0` |

What the picture-mode setting allows (static validator, 20-byte records, type 6 = 64-byte value records):

| Setting | E-P7 1.1 | E-PL9 1.101 |
|---|---|---|
| **111 = `0x9481`, the effective picture mode** | 7, 1–6, 8, 9, **12 ×4, 11 ×4**, Art 100–109, 119–124 (`0x604ba8fc`) | 7, 1–6, 8, 9, Art 100–109, 119–124 (`0x608a33f8` → list). **No 11 or 12** |
| 1645 / 1646 (normal / Profile list, Profile Control lever) | present | **absent** |
| COLOR-profile record `0xf6a1` (E-P7 905–907, 972 / E-PL9 902–906, 971) | present | **present**; E-PL9 906 = `0xf6a1`[5] uses the 27-entry list with 11 and 12 (`0x60899e88`) |
| Effective COLOR profile number `0xf6b1` | sid 908 | **sid 907** |
| MONO profile number `0xf731` | sid 973 | sid 972 |

The backend survives: the COLOR-profile properties, the mode-11 checks in capture population (`0x607ca51f`) and the
converter, the selector gate, the builder and its table. Only the user-facing route to mode 11 is gone.

**Host options this leaves** (none tried yet):
1. **Data patch:** point setting 111's validator at a list that includes 11 (the stock 27-entry list at
   `0x60899e88` already has 11 and 12). Smallest change, but the picture-mode UI has no COLOR label or icon, the
   profile number/saturation settings (`0xf6b1`, `0xf6ea`?) have no menus, and Live Control may show garbage. Needs
   a UI check.
2. **Code hook:** keep the stock menus and turn a chosen stock mode (e.g. Custom, 6) into 11 at the capture
   picture-mode byte (`0x607cb7d2`) or the request key (`0x607d26a0`), and feed the look's HSL from our own data
   at `0x6079ec53`. Looks change no setting values, and the stock Custom behaviour is lost while a look is active.
3. Use an Art filter slot instead: it has its own colour tables (Partial Color etc.), but it would mean a separate
   colour path, not the COLOR builder.

## Pipeline check for mode 11 (2026-11-07)

**Result: if the capture picture-mode byte is 11, the stock E-PL9 carries it all the way to the colour builder.
The only things it drops are E-P7 extras our looks don't need.** Static [V], stage by stage against the E-P7:

| Stage | E-P7 1.1 | E-PL9 1.101 | Same? |
|---|---|---|---|
| Capture population: mode 11 → profile number `0xf6b1` → capture byte; 12 × saturation `0xf6ea` → capture | `0x602a859e` (+24083, +24058) | `0x60693d16` (+22985, +22960) | **yes**, instruction for instruction |
| Converter: mode 11 copies the 12 saturation bytes into params | `0x603e6683` → params+5538, plus shading +24086 → params+5552 | `0x607cea1e` → params+4764; **no shading byte** | yes, minus shading |
| Packer: params saturation → request | `0x60354faa` → request+1816 | `0x6074f500` → **request+1813** (what the selector reads) | **yes** |
| Request key = picture mode | `0x603eaa04` | `0x607d26a0` | yes |
| Work list: key at job+11308 / +10384; only key 12 and Art `0x01010068`/`0x01020068` are special; key 11 takes the default list like Vivid/Natural | `0x60357415` | `0x607519cf` | **yes** |
| Picture-mode key hashes: no table has an entry for 11 on either body (12 tables E-P7, 9 E-PL9), so 11 always takes the default handler | | | **yes** |
| Selector call: skipped only for request+12 = `0xa200`/`0xa600`, not by key or job flags | `0x603aade3` → `0x603b14f3` | `0x60799fac` → `0x6079fc15` | **yes** |
| Selector gate mode 11 → builder | emulator check D | emulator check D | **yes** |

Direct `cmp 11` checks in the pipeline code (`0x6034…0x603f…` vs `0x6072…0x607e…`): 137 of the E-P7's 191 have an
E-PL9 counterpart. Of the rest, most are loop counters, the capture+24776 byte (also compared with 14; not the picture
mode) or matches just outside the search window. Two real differences:

- **Job flag `0x80000` (COLOR shading).** The E-P7 job constructor sets it for keys 9, 11 and 12 (`0x60353baa`); the E-PL9
  constructor doesn't have that code, even for Underwater (9). With the flag, the E-P7 dispatcher builds the effect work
  list (`0x60356297`, shading modifier `0x6035b03a`); without it the job takes the plain development path. The
  E-PL9 converter doesn't copy the shading byte either. So an E-PL9 mode-11 job gets **no shading (vignette) pass**,
  which we don't need.
- **capture+1912 = 1 for modes 11/12** (E-P7 `0x603e23ee`). The E-PL9 sets it only on its mode-9 path. Meaning untraced [I]:
  watch for it if a mode-11 image comes out wrong.

**What this means for the host choice:** setting the capture picture-mode byte (capture+22955, written at
`0x607cb7d2`; the request key follows from it at `0x607d26a0`) to 11 is enough to reach the builder. Saturation
comes along from setting `0xf6ea` by the stock route, and hue/lightness come from the hook at `0x6079ec53`.
Option 2 (a code hook turning a chosen stock mode into 11 there) needs no menu or validator changes.

Not covered: live view. On the E-P7, LV runs key 11 through the same stages (`LV_ART_PREVIEW.md`), and the E-PL9
selector is shared code, but the E-PL9 LV capture path hasn't been traced. Also untested: the result on real pixels.
That needs a camera test.

**Reproducing:** in WSL, build mn10300 binutils (`tools/setup_toolchain.sh`) and the emulator engine
(`external/oly_fw_analysis/tools/build_mn103_emulator.py`; see its `docs/tooling/EMULATOR.md`), then
`python3 tools/epl9_color_probe.py`. The googlesource archive's gzip bytes are regenerated on download, so its
SHA-256 may not match the pinned one. Check the extracted tree against a git checkout of commit `87ffb882` instead.
