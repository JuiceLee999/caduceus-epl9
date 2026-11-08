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
the E-PL9**: nearly identical code with one constant shift per area. Static evidence only; nothing has run in the emulator yet.

| Piece | E-P7 1.1 | E-PL9 1.101 | Match |
|---|---|---|---|
| COLOR builder | `0x603b0068–0x603b0247` | `0x603be9e2` (+59 770) | 113 / 116 unique 12-byte windows, all the same shift |
| selector | `0x603b0252–0x603b0345` | `0x603bebcc` (+59 770) | 47 / 57 |
| writer | `0x6034667e–0x6034677b` | `0x60360cf0` (+108 146) | 61 / 60 (all windows) |
| COLOR table | `0x6051de2c` | `0x6050e360` | 4 / 4 64-byte chunks |
| gains | `0x60531810` | `0x604f27ec` | 3 / 4 64-byte chunks |
| **color_hook** (`call builder`) | `0x603b02d9` | **`0x603bec53`** | the only caller on both bodies |
| `call selector` | `0x603b14f3` | `0x603bfc15` | the only caller on both |
| `call writer` | `0x60345f8f`, `0x60345fb1` | `0x60360601`, `0x60360623` | the same two callers |

Callers were found by scanning for MN103 `call`/`calls` (d16 and d32) to each entry point.

**What this means:** the hook where looks inject hue, saturation and lightness per sector exists. What's missing is
the E-P7's COLOR *profile* UI and storage around it. Next questions, for the emulator:
1. When does the stock E-PL9 reach `0x603bec53`? Picture modes, Art filters (e.g. Partial Color) or never?
2. Does a non-zero per-hue table there change the output, as on the E-P7 (`tools/ep7_color_probe.py`)?
3. Which existing E-PL9 setting can host a look: a picture mode slot (e.g. Custom) or an Art filter?
