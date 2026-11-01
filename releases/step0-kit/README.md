# Step 0 kit — prove the way back BEFORE any modded firmware

Nothing here contains a mod. Files are deliberately NOT SD-named; you rename them when copying.

| File | What | SHA-256 |
|---|---|---|
| `1-trigger-test-CORRUPT.pkg.bin` | stock main with 1 checksum byte flipped → camera rejects before erasing (0x3211, 0 writes — emulator) | d3691507… |
| `2-restore-stock.pkg.bin` | exact stock main (== official 1.1 file bytes 0..26,214,400) | 245b9c8f… |

## A. Check
1. Menu → Settings → Firmware: must read **1.1**. If not, stop and tell Claude.
2. Full battery. Format card in camera. Aspect 4:3, picture mode Natural, mode dial not on movie.

## B. Find the SD update trigger (cannot write anything)
1. On a computer: create folder `DCOLYMP` on the card; copy `1-trigger-test-CORRUPT.pkg.bin` into it renamed `E1429999.BIN`.
2. Camera off. Try one combo per attempt while switching on: **OK + power** (PEN-F lead), then MENU + power,
   INFO + power, Playback + power.
3. Updater ran = LED steady, then **fast blink** (rejected). Switch off. Note which combo.
4. Remove the file; boot normally; confirm firmware still 1.1.
5. If no combo works: stop. Recovery would then go through OM Workspace (USB) instead.

## C. Restore dry run (real full rewrite of stock — same as an official update)
1. Only after B worked. Put `2-restore-stock.pkg.bin` on the card as `DCOLYMP/E1429999.BIN` (only file there).
2. Use the combo from B. LED steady for the whole write (minutes) → **slow blink** = success. Do not touch anything.
3. Switch off, boot, confirm 1.1 and normal operation. Delete the file.

Then report back; the first feature test is the recording-limit patch (smallest, review order step 1).
