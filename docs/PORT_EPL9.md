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
