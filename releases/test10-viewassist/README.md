# test10-viewassist: Log View Assist on the test7b base

**What it is.** Test 7b plus Log View Assist: while recording or previewing log, the LCD shows a normal-looking
image. The recording and HDMI stay log.

The LUT goes on when all three hold:
- the TFT is running;
- the TFT shows the live through image (`0xa272c418` bit 0);
- the current settings record has +925 == 2 (log). With `patches/video_log` that means movie mode with picture
  mode Muted.

Otherwise the LCD is bypassed (stock). Design and evidence: docs/LOG_VIEW_ASSIST.md.

- Same hook, LUT and pointers as probe-VA0. `va_hook` is 105 B at `0x601e393c`.
- No RAM stores. Loads once: the VSC mode register is the only state, and it is reconciled after every display
  command.

38 edits, 2,763 changed bytes. `edits.json` = generated/view_assist/full_merged.json. Packages are local only.

**Flash only after probe-VA0 passes.** Expected:
1. Movie mode, picture mode Muted (log): the LCD looks roughly like Natural. Recorded clips are flat log, as in
   test 6/7b.
2. Movie mode with another picture mode, or stills mode: the LCD is stock. Recordings are as before.
3. After a log session, press Play: playback looks normal. Return to movie + Muted: the assist comes back.
4. HDMI: log (no assist).

The preview shows shadow posterisation, and the colours are near Natural but not exact. With −2 EV compensation
the preview looks about 2 EV dark. See LOG_VIEW_ASSIST Q4.

**Recovery:** `restore-stock.pkg.bin` (identical to test 7b's restore).

**Emulator verification:** as for probe-VA0, with variant `full`:
`--package releases/test10-viewassist/patched.pkg.bin full`. Results: generated/view_assist/full.verify.json.

Offline build. No camera was contacted. Package names are deliberately not SD-loadable.
