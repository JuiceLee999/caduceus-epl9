# Finer JPEGs ("more super fine"): first look

Status: **corrected 2026-11-05: `Sf` varies per image, so "already at the minimum" was wrong for many files, but the gain left is
very small. Not worth building.** Nothing built or run on a camera.

## Result: measured over all full-size JPEGs in `testdata/`

The first look sampled 12 files and saw only all-1 tables. All 326 readable 5184x3888 files give **[V]**:

| Luma / chroma DQT sum | Fitted `Sf` | Files | Size MB (min / median / max) |
|---|---|---|---|
| 64 / 64 (all 1s) | 0-3 | 187 | 6.0 / 10.0 / 11.6 |
| 86 / 115 | 5 | 121 | 10.7 / 11.9 / 14.8 |
| 96 / 117 | 6 | 7 | 14.8 / 14.8 / 15.1 |
| 116 / 169 | 7 | 9 | 9.4 / 13.5 / 13.9 |
| 150 / 224 | 10 | 1 | 13.9 |
| 160 / 224 | 11 | 1 | 9.3 |

- **[V]** Every table fits `max(1, min(255, (base * Sf + 128) >> 8))` exactly. So a **min-1 clamp exists** somewhere, which the
  "no lower clamp" note below did not see (it may be outside the routine at `0x603b6120`).
- **[I]** All-1s stop at 11.6 MB, and larger files have `Sf` 5+, which suggests a rate control that raises `Sf` for detailed scenes.
  It is not a simple size target: `Sf` 11 occurs at 9.3 MB. The quality setting of each file is unknown (no ImageQuality2 tag
  0x603 found in the maker-note CameraSettings), so some high-`Sf` files may be Fine rather than Super Fine.
- **[V] The gain is tiny.** At `Sf` 5 the largest step is 2; at `Sf` 11 it is 5, and only in the highest frequencies. Forcing `Sf` to 3
  or below would add file size and risk (buffers, burst) for a change that should not be visible.
- Chroma stays 4:2:2 in every file (luma sampling 2x1); 4:4:4 would need the JPEG engine to support it, which is unknown.

The analysis below stays for reference (and for anyone wanting the *lower* qualities, F/N/B, finer or coarser).

Original notes follow. E-P7 1.1 main, addresses are CPU addresses.
Notation: **[V]** read in the disassembly; **[I]** inference.

## What is known

- **[V] The quantisation tables are the standard JPEG Annex K tables at quality 50.** Luma is at `0x60533058` and chroma at
  `0x60533098`, followed by the Huffman tables. A pointer record at `0x60533048` points to both; it is used from `0x603b6186`.
- **[V] A routine around `0x603b6120` scales them at run time.** For each of the 64 entries it computes
  `min(255, (base * Sf + 128) >> 8)` (so `Sf = 256` gives the Q50 tables) and stores the result for the JPEG engine
  (registers at `0x99901xxx`). A smaller `Sf` gives finer quantisation, so a bigger, cleaner JPEG.
  - `Sf` is a halfword read from the job's parameter block. If it is 0 the caller's default is used. The result is cached
    (`0xa27393fc` holds the last `Sf`), so the tables are rebuilt only when `Sf` changes.
  - The debug strings `usJpegSf`, `ucJpegMode`, `ulJpegTargetSize`, `ulJpegCodeSize` name the parameter block fields.
- **[V] There is no lower clamp.** A small `Sf` can produce quantiser steps of 0, which is invalid for the JPEG engine.
  The smallest entry in the base tables is 10, so `Sf` must stay at or above 13 for every step to remain at least 1.

## Not found yet

1. **Where `Sf` is chosen for each quality setting** (SF / F / N / B, and the size classes). It is probably a small table or
   a few constants in the job-setup code; the writer of the parameter block has not been traced.
2. **Whether `ulJpegTargetSize` drives a rate-control loop** that re-encodes at a coarser `Sf` until the file fits a target.
   If so, a finer `Sf` would be undone for large files unless the target is raised too.
3. **Buffer sizes.** A finer JPEG is larger. The code-size buffer, the card-write path and the burst buffer limits need
   checking so a bigger file cannot overrun.

## Dead ends and next step (2026-11-04)

- **[V] Parameter block layout** (from the debug-print code at `0x613e8627..` and `0x613f121b..`): `ulJpegCodeSize` at +0x10,
  `usJpegSf` at +0x14, `usJpegType` at +0x16, `usCtrlThAB` at +0x18.
- A search for code that stores halfwords at +0x10, +0x14 and +0x16 of one block within 60 bytes finds about 100 sites, so
  static tracing from the stores is too slow. The slow-ramp u16 table at `0x60708620` (0..96) is an identity ramp, not an `Sf` table.
- **Do not** blindly halve the output (for example `lsr 9` instead of `lsr 8` at `0x603b619c`): if Super Fine's `Sf` is
  below about 38 the smallest steps become 0.
- **Next step:** run the JPEG setup in the MN103 emulator and read the `Sf` actually passed for each quality setting
  (or log it from a one-off camera probe), then change that value.

## Difficulty (estimate)

Moderate. If `Sf` for Super Fine is a constant or a one-entry table, changing it is a few data bytes. The work is items 1-3 above,
then a test on the E-P7 itself (the maintainer has one): measure file size, decoded quality and burst speed. Risk is medium
(buffers), so try one quality setting first and keep the restore file ready.
