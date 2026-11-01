# test7b-sdloader-v3: SD look loader v3 on the test-6 base

**What it is.** Test 6 (camera-proven: rec_limit, video log, bundles lachlan_v3, grain, bloom, per-profile WB) with
the SD look loader rebuilt so that nothing is ever stored into flash-loaded image RAM (the test-7a crash suspect,
docs/SD_V2_CRASH.md). Design and results: docs/SD_BUNDLES_V3.md.

- Same hook as v2 / probe P2 (0x602c805f → 0x605b7400); same gates. State lives at **0x622cbcc2** (P2 proved it
  writable on the camera).
- A valid `EP7MOD/BUNDLES.BIN` is read into a heap buffer that is kept; a 16-bit handle at 0x622cbcc2 points to it.
  Nothing is copied over the flashed table.
- bundles H/L, grain, bloom (×2) and WB now fetch the table through a 60-B accessor at 0x6055e7b0: the loaded copy
  if a valid handle is stored, else the flashed table (exactly test 6's behaviour).

34 edits, 2,393 changed bytes. `edits.json` = generated/sd_bundles_v3/t7b.json. Packages are local only.

**Test file.** `card/EP7MOD/BUNDLES.BIN` (544 B; local only; rebuild with
`patches/sd_bundles_v3/make_test_file.py --out releases/test7b-sdloader-v3/card`) = the flashed table plus one
obvious change: **COLOR1 greens shifted hard toward teal/cyan** (COLOR1 is stock in the flashed table). All other
profiles are identical with or without the file.

**How to test (one step at a time):**
1. Flash `patched.pkg.bin` (the usual SD update path). Card in, **no EP7MOD folder**. Boot, half-press several
   times, shoot COLOR2/COLOR4 (should look exactly like test 6), start one movie. 5 power cycles.
   This is the first time the fopen call runs on the camera (missing file).
2. Copy the `EP7MOD` folder to the card root. Power on, half-press once (the file is read then), then shoot a green
   scene in COLOR1: greens should be teal. Shoot COLOR2/COLOR4: unchanged. Power-cycle without the card folder:
   COLOR1 back to stock.
3. Note for any crash: on boot / first half-press / later; instant reset or hang first.

Recovery: `restore-stock.pkg.bin` (identical to test 6's restore), via the proven SD restore.

**Emulator verification** (generated/sd_bundles_v3/*.out, *.json): see docs/SD_BUNDLES_V3.md §7.

Offline build. No camera was contacted. Package names are deliberately not SD-loadable.
