# v0.1 — fixed H/L (Classic Neg)

Status: **built + verified offline. NOT flashed. Not cleared for flashing** (see docs/REVIEW_fixed_hl.md, docs/SD_UPDATE.md).

- `patched.pkg.bin` — main component (0x100) only; hook 0x603b02d9 + 116-byte routine @0x6055e5c0 (109 bytes changed).
- `restore-stock.pkg.bin` — exact stock main component (bytes 0..26,214,400 of OLY_E_142_1100_0000_0000.BIN).
- `edits.json`, `routine.s`, `routine.lst` — source of the build. `build.json` — hashes.
- Verify: `.venv/bin/python -I tools/ep7_verify_package.py releases/v0.1-fixed-hl-classic_neg/edits.json`

Package files are not SD-named and are gitignored (contain OM firmware). Rebuild with tools/build_package.py.
Requires camera already on firmware 1.1.
