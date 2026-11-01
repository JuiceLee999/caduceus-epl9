# test12-editor: in-camera look editor phase 1 + 1s, on test 11

**What it is.** Test 11 (v0.6 + clarity + view assist) plus the look editor from docs/LOOK_EDITOR.md:

1. **Delete cycles the Color Profile wheel axis S → L → H → S** (COLOR1–4), only when a card look table is
   loaded (first half-press after power-on, as in test 8). The dials then edit Lightness or Hue of the
   selected sector, range −5..+5 for now. Values beyond ±5 that came from the card are shown as ±5.
2. **Edits go live straight away**, into the loaded table in RAM (heap). The next picture uses them. Live view does
   **not** show H/L (known limit of the bundles patch); check the saved JPEG.
3. **Save to the card** on the next half-press after an edit: `EP7MOD\BUNDLES.NEW` (read back and checked),
   then the old `BUNDLES.BIN` is copied to `BUNDLES.BAK`, then `BUNDLES.BIN` is written and read back.
   There is one attempt per batch of edits. Nothing is ever written to internal flash or settings.
4. Opening the editor always starts on S. With no card table, everything is stock.

Edits: 96 (test 11's 83, with the loader's last `jmp` retargeted to the save routine, plus 13 new ones).
That is 1,344 bytes changed on top of test 11. `restore-stock.pkg.bin` is identical to test 11's.
The packages and `card/` are local only (gitignored). `card/EP7MOD/BUNDLES.BIN` is test 11's card file.

## Camera test plan (one step at a time; stop at the first surprise; SD restore ready)

1. **Card WITHOUT EP7MOD.** Color Profile editor: press Delete. Nothing new should happen. Edit S as usual,
   power-cycle and check S kept. Hold OK to reset. Shoot COLOR1–4 and record a movie. This should look like test 11.
2. **Card with EP7MOD, half-press once**, then open the COLOR2 editor. Press Delete; if the wheel or numbers do
   not redraw, turn the dial one notch. Note what the screen shows: the numbers should now be Lightness (stock
   card values). Press Delete → Hue, Delete → back to S with the S values unchanged. Report whether the polygon
   follows the axis (not mapped; it may stay on S).
3. Hue axis: set the green sector to +5. Shoot a colour chart in COLOR2 before/after. Greens should shift in the
   JPEG. Also say whether the sector you edited is the colour that changed (checks the sector order).
4. Leave the editor, half-press once (save). On a PC: `BUNDLES.NEW`, `BUNDLES.BAK` and `BUNDLES.BIN` should exist.
   Check them with `tools/ep7_bundles_bin.py --check`. Power-cycle, half-press, reopen: the edit should still be there.
5. Write-protected card or card pulled during the save half-press (spare card): the camera keeps working and the
   edit stays in RAM until power-off.
6. Repeat 2–3 on COLOR4 and with ALL selected (group step stops at ±5).

## Verification (generated/look_editor/verify.json; emulator only)

`tools/ep7_verify_look_editor.py releases/test12-editor/edits.json --base releases/test11/edits.json`.
Every image region is mapped read-only, so any store into 0x60020020–0x6191ffe0 faults.

| Part | Result |
|---|---|
| S: static checks. Guards FF; the only bytes that differ from test 11 are ours; no overlap with test 11, clarity 0x6055e5c0–7f0 or view assist 0x601e383c–3a3c; sd_back → ed_trig | PASS |
| G: GetValue/GetDefault through the real vtable. 17 ids × 11 heap states × 2 slots, plus clamp. Each miss is identical to the stock run | 376/376 PASS |
| W: real setter site. Miss state at 0x60827443 == stock. Hit writes exactly the value, flag and dirty bytes. ±6/7 refused | 1233/1233 PASS |
| E: Delete through the COLOR record words. S→L→H→S on all 4 keys; refresh on children 1..12 in order; 6 guards, 5 heap states and 12 other events behave as stock | 40/40 PASS |
| I: init word. Axis reset; state at stock 0x60e20a54 == stock | 16/16 PASS |
| T: save from sd_back with stub file service. File images pass the loader rules; .NEW/.BAK/.BIN order and read-back; no memory, open fail, short write, corrupt read-back, no/odd old file; non-press, not-dirty and bad-handle cases do nothing; registers at 0x602c8064 == entry | 19/19 PASS |
| M: source mutations | 16/16 detected |
| Package: decoded `patched.pkg.bin` == the emulated image; restore == stock | PASS |

The emulator found three real bugs, now fixed:
- ed_trig: a call return address overwrote a saved register;
- ed_wfile: the .BAK read-back went past the 2 KiB scratch buffer;
- ed_event: a1 was not restored on the guard path.

**Not covered by the emulator** (camera only):
- the stock child refresh 0x60de3670 (stubbed);
- the real fileif and FILECLBK (stubbed);
- whether the editor redraws after Delete;
- the wheel polygon;
- which physical key sends 0x9016;
- the parent's hold-timer flags.

The test-11 loader suite (`ep7_verify_sd_bundles_v3.py`) stops at 0x602c8064 and does not map section 6. Run on
this spec, its runs now continue into ed_trig. That path is covered by part T instead.

Rebuild (each in `systemd-run --user --scope -p MemoryMax=3G -p MemoryHigh=2500M -q`):
```
.venv/bin/python -I patches/look_editor/build.py --base releases/test11/edits.json --out generated/look_editor
.venv/bin/python -I tools/build_package.py generated/look_editor/merged.json --out <new dir>
```
