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
