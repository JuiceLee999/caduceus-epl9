# SD-card mod loading (design)

Idea (user, 2026-11-01): keep the flashed changes tiny and put features and data on the SD card.
Precedent: Canon's Magic Lantern and CHDK load from the card.

## Why it's attractive
- **Safety:** if a card-loaded feature misbehaves, power off and remove the card (or delete the file) → stock
  behaviour. Only the small flashed loader + hooks need the full flash-level review.
- **No reflashing to change looks:** bundles (HSL, grain, WB, effects), curves and LUTs edited on a computer
  (desktop sim → `EP7MOD/BUNDLES.BIN`), copied to the card. This also covers much of the editor-UI need.
- **More space:** the flash code-space tails total ~8.8 KB; card data/code is limited only by free RAM.

## What exists in firmware
- The SD updater client (task 88, 0x60c95bab) mounts the card via FILECLBK messages (unmount 18, mount 97),
  walks a directory and reads whole files into a RAM buffer (docs/SD_UPDATE.md). So a file service usable
  from tasks exists.

## Design
1. **Flashed loader** (small): after normal startup has mounted the card, read `/EP7MOD/MOD.BIN` once.
   Validate: magic, format version, target firmware build (1100) + main SHA prefix, length, CRC32.
   Copy into a reserved RAM region. On any failure: leave the pointer null.
2. **Hooks** (flashed) consult the pointer: null → stock behaviour; else read bundle tables / curves from it.
3. Phase 1 = **data only** (bundles, curves). Phase 2 = optional card code via a fixed jump table
   (higher risk; a bad card file could crash the camera, recoverable by removing the card unless it persists settings).
4. Re-read on card insert / power-on; never write to the card from mod code except a log file (optional).

## Unknowns to trace
- A safe, unused RAM region (size, alignment, not used by DMA/ISP, survives sleep).
- The exact file-service API (open/read/close or whole-file read) callable from our hook context, and timing
  relative to boot and card mount (card may mount after the first live-view frame).
- Behaviour with card swap, card absent, slow cards, exFAT vs FAT32.
