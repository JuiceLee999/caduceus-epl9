# Lens buttons (L-Fn / AF-stop) on the E-P7: feasibility

Offline static analysis only (E-P7 1.1 main, plus the E-M5 III and E-M10 IV images in `analysis/`). Nothing built,
nothing tested on a camera. **[V]** = read from the decoded image. **[I]** = inferred.

## What the E-P7 firmware already contains

- **[V] Lens key events exist end to end.** Event names `EV_PRESS/RELEASE/LONG_PRESS/REPEAT_LENS_KEY`
  (table `0x60a6f174`), `OLY_*_LENS_KEY` (`0x60f7026c`, `0x60f73060`), `SEND_KEY_LENS_FN2_ON/OFF/LONG_ON`
  (`0x60f77ddc`) and `EVT_KEY_LENS_FN2_*` (`0x611eacb4`). The same code is in the E-M5 III and E-M10 IV, so the
  E-P7 is not stripped of it.
- **[V] The button settings exist.** Key table `0x60f389a8` (see `BUTTONS.md`): keycodes `0x1c/0x1d/0x1e` → sids
  **54 / 55 / 56**, all `full = 1`, so they go through the normal function lookup. Validator records
  `0x604cda94 / 0x604cdaa8 / 0x604cdabc` have 28 / 28 / 29-code lists (sid 56 adds **AF Stop**). The
  E-M10 IV has identical records; the E-M5 III has the same three, with longer lists.
- **[V] The movie-mode key gate knows a lens key.** `checkMovieKeyOnExec` / `isEnableMovieFuncKey`
  (`0x6093009b`, `0x6094b884`) log an `LFn` flag next to Fn1/Fn2/AEL/◉.
- **[V] AF-stop switch handling** (`LENS_AFSTOP_ON`, `get_afstop`, `AFStopSwitch ON!`) is present.

## What is unknown

1. **Is there a menu row?** The Button Function screen is a 20-row table (`0x611d7dc0`, 28-byte rows) that is
   byte-for-byte the same in the E-P7 and E-M10 IV. Row labels are the icon symbols (`@A00C@Function` …); I did
   not identify which symbol is the lens button. If a row exists, its visibility is a runtime condition (lens
   attached / lens reports L-Fn); if none exists, a row would have to be added.
2. **Does the E-P7 deliver lens key events?** The lens-side protocol is shared with E-M-series bodies. Nothing
   found suggests the E-P7 drops it, but only a camera with a Pro lens (12-40, 40-150, 300 …) can confirm.
3. **Do the state handlers act on it?** Stock functions on 54/55/56 are already used by other bodies, so the
   function-to-action step should work (same as the arrow-pad widening in `BUTTONS.md` §3).

## Rough plan and difficulty

| Step | Work | Risk |
|---|---|---|
| A. Probe | Camera-side: with a Pro lens, check whether any L-Fn entry shows in Button Function and whether pressing it does anything (maybe it already works with the stock default, AF Stop / Off). | none |
| B. Menu row | If a row is hidden by a model/lens flag: find the gate and drop it (a one-byte-class patch, like the Record Mode gate). If absent: add a row to the 20-row table (relocation, like the aspect menu list). | low–medium |
| C. Widen the list | Sid 56 already has 29 codes; widen with the `BUTTONS.md` patch method (e.g. add Multi Function, ISO/WB, Level). | low |
| D. Profile switch | Pair with the queued "profile slot direct select" function (`BUTTONS.md` §4.1) so a lens button can cycle Caduceus looks. | medium |

Placement: **Possible / medium**. It becomes "Likely / easy" if step A shows the key already arrives and only the
menu row is hidden. Reference code for implementation: the `patches/buttons` widening and the E-M5 III image
(`analysis/em5iii`), which has the same three sids with a longer list and is the closest model that exposes L-Fn.

## Effort estimate (to pick up next dev push)

- Trace the lens row and its gate: ~1-2 h, no camera.
- Gate found: small patch + emulator test, ~1 h, low risk.
- No row: add and relocate a row (like the aspect menu list), ~half a day, medium risk (Button Function area bootlooped in `BOOTLOOP_T3`).
- Camera test needs an OM Pro lens with an L-Fn button.
