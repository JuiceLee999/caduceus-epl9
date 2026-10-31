# ep7-firmware

Custom firmware research for the Olympus PEN E-P7 (firmware 1.1, build 1100).

Goals: HSL colour control, colour film grain, extra still aspect ratios
(XPan 65:24, 21:9), video framing guides, film-simulation recipes.

**Status: offline research only. Nothing in this repo has been flashed to a camera.**

## Layout
- `stock_firmware/` – local only; `SHA256SUMS` records the expected stock image.
- `external/oly_fw_analysis` – fishcu's research repo (submodule, pinned). Unlicensed: referenced, not copied.
- `tools/` – our scripts. `docs/` – our findings.
- `WORKLOG.md` – chronological log of every step, decision and check.

## Setup
```bash
git clone --recurse-submodules <this repo>
# Obtain OLY_E_142_1100_0000_0000.BIN via OM's catalog (tools/fetch_stock.sh), then:
(cd stock_firmware && sha256sum -c SHA256SUMS)
tools/setup_toolchain.sh   # builds mn10300-elf binutils into ~/ep7fw-toolchains
```

## Safety rules
1. Never connect to or flash the camera without an explicit, per-step go-ahead.
2. Every flashable output must have a matching, verified stock-restore image.
3. Checksums passing is not proof of safety; changed bytes are diffed and reviewed.
