# probe-VA0: View Assist playback-signal probe (on the test7b base)

**What it is.** Test 7b (rec_limit, video log, bundles, grain, bloom, per-profile WB, SD look loader v3) plus the
View Assist reconcile hook with the log test **removed**:
- the LCD gets the View Assist curve whenever the TFT shows the live through image (`0xa272c418` bit 0);
- otherwise the LCD is bypassed (stock).

Its purpose is to prove the playback signal before test10 relies on it (docs/LOG_VIEW_ASSIST.md,
"Trigger measurement").

- Hook: display task reply tail `0x601751f4` (5 B) → `va_hook` (74 B at `0x601e393c`, dead EVF step-0 G table).
- Data: VA LUT 256 B at `0x601e383c` (dead EVF step-0 R table) and TFT step-17 pointers at `0x601e3c40` (12 B).
- No RAM stores. The only writes are the VSC LUT and mode registers, made by the stock programmer `0x60187439`.

38 edits, 2,732 changed bytes. `edits.json` = generated/view_assist/probe_merged.json. Packages are local only.

**Expected on the camera (one flash, flash this BEFORE test10):**
1. Stills or movie live view on the LCD: the image looks **too contrasty / crushed shadows** (the log→display curve
   applied to a normal picture). This is intended for the probe.
2. Press Play: playback images look **normal**. Go back to live view: contrasty again.
3. Menus: either look is acceptable. Note which one you see.
4. HDMI (if available): unchanged.

A pass is 1 + 2. Also note:
- whether the switch is instant or happens one screen redraw later;
- any freeze, hang or crash, and when: at boot, on the first live view, or on Play.

**Recovery:** `restore-stock.pkg.bin` (identical to test 7b's restore), via the proven SD restore. The worst
expected failure is cosmetic (wrong LCD tone).

**Emulator verification:**
- `python3 -I patches/view_assist/build_and_verify.py` covers the S matrix, the P full chain with the stock
  programmer, and M mutations.
- `python3 -I patches/view_assist/build_and_verify.py --package releases/probe-VA0/patched.pkg.bin probe` re-runs
  S and P on the shipped bytes.
- Results: generated/view_assist/probe.verify.json.

Offline build. No camera was contacted. Package names are deliberately not SD-loadable.
