# GitHub issues #19 and #20 (v0.20): findings and fixes

Offline static analysis plus emulator runs. Nothing here has run on a camera. Labels: **[V]** read from bytes or
disassembly, or run in the emulator. **[I]** inference.

## #20: colour profile + Blur restarts the camera without saving

**Cause (most likely) [I]:** our COLOR Art Effect injection skips stock preconditions that ART mode always has.
- Stock honours an Art Effect only with an art filter selected (record path `0x60312f42`, picture mode >= 100) [V].
- For art keys, the constructor's strip `0x60353b15` clears the Blur bits 0x300 on job types `&0xf0 == 0x40` or
  `&0xf00 == 0x100` [V]. Examples are the special capture jobs 0x110 / 0x120 from capture kinds 0x2001 / 0x2006
  (GRAIN_PORT H1). That strip never runs for key 11 [V]. So a COLOR Blur flag (0x100, set by the Art stub
  `0x601e1d3c` in converter `0x603eab39`) reaches job types where stock never runs the Diorama passes.
- The combination bloom 0x80 + Blur 0x100 also never occurs in stock: Soft Focus and Blur are one Art Effect id.
  Most library looks and the starter slots have bloom.
- The Blur passes' own setup (buffer allocation, band position) does not run in the emulator, so the F/L/S checks
  of tools/ep7_art_verify.py could not catch this (HALATION_RED section 11, "Not verified").

**Fix (v0.21): Blur is mapped to Off everywhere.** It cannot be made provably safe without a camera. These are
byte-level edits on the v0.21 spec (`patches/v021/build.py`, inside existing edit spans):

| Where | Edit |
|---|---|
| Art stub (stills) `0x601e1d42` | bound `cmp 3` -> `cmp 2`: art 3 adds nothing; dead table entry `0x601e1d70` -> AND ~0 / OR 0 |
| lv_art (LV) `0x601e11c3` | bound `cmp 2` -> `cmp 1`: Pin Hole only; dead entry `0x601e1214` -> 0 |
| look extras ex_get `0x601e331c` | art byte 3 reads Off |
| look extras ex_set `0x601e33a0..b6` | pre-clamp -3..5, wrap modulo 3: Extras sector 5 cycles Off / Star Light / Pin Hole |

A Blur byte already saved on a card stays in BUNDLES.BIN but does nothing, and it shows as Off. Web app: Blur is
offered only as a legacy value.

**Verified** (`patches/v021/verify.py`, v0.20 as the control):
- B1 converter, 864 runs: art 3 == art 0; everything else == v0.20. Control: v0.20 adds 0x100.
- B2 lv_art, 192 runs: the same; Pin Hole 0x400 is kept.
- B3 ex_get and B4 ex_set: as above.
- R / G / S / L (grain) and P anti-brick: PASS.
- With the old v0.21 spec, B1-B4 FAIL, so the checks are sensitive.
- `caduceus.py build --release v0.21` reproduces the package.

**Same risk class, not reported:** Star Light (0x40) is also in the stock 0x1xx strip list. Watch for reports.
Pin Hole (0x400) is not stripped for 0x1xx in stock.

## #19 (a): Rec View / Auto Review does not show, and the setting has no effect

**No Caduceus edit touches the Rec View path [V]:**
- The setting is **sid 19** (validator record 282 at `0x604ce0b4`, u8 list `0x604cb258` = 255 Auto ▶, 0 Off,
  3/5 = 0.3/0.5 s, 10..200 = 1..20 s), property key **0x81e1** (ID table `0x604d6c14`[19]).
- Its reader `0x602a2140` (getter `0x6005e971` -> RAM byte `0x6223e5ec`) is stock.
- The validator table has exactly one edit in every release from v0.14 to v0.21: record 442 (aspect sid 270),
  list pointer -> `0x60210f70`, count 5 -> 7. Record 282 and its list are untouched, and nothing shifted.
- The aspect v6 rec-view size edits `0x6053e246` / `0x6053e258` change only ids 6/7 (index id-1 in the 9-entry
  W/H arrays `0x6053e23c` / `0x6053e24e`). 4:3 / 3:2 / 16:9 / 1:1 / 3:4 rec view is stock.
- The rec-view code is stock: `set_imgprm_recview` `0x6031339b` (its request goes to `0x603220ea`, not through
  the lv_art gate `0x60321eaf`) and the post-capture recview / "E_skip recview" function `0x6031d184`.
- lv_art only acts on the IPCR constructor call. lv_art_refresh calls the settings manager only when a slot's
  art byte changes. The tone / lv_bundles hooks only change LUT contents. ed_get / ex_get / ed_set / ex_set
  intercept only COLOR saturation-sector ids 927..962 / 1655..1666, so sid 19 passes through.

**Not settled:** a behavioural cause cannot be ruled out without a camera, for example review-image development
failing on a looks job. Needed from the user: whether it also happens on `restore-stock`, the Rec View value,
the aspect (Panorama/Wide?), the picture mode, and drive mode (sequential, anti-shock or silent).

## #19 (b): the camera gets hot

What runs per live-view frame [V code, I rate]:
- **lv_art** (constructor hook) runs when the LV job is built: after a capture or a real colour change, not per
  frame (lv_art_refresh analysis). The work list it builds does run on every frame.
  - A **bloom slot without grain** gets the stock Soft Focus LV passes: a 144×108 reduce and one combiner-12 blend
    per frame, the same work as the stock Soft Focus art filter in LV.
  - A **Pin Hole** slot adds the stock Pin Hole LV stage.
  - A **grain slot** gets no LV preview at all (the GRAIN_OFF build).
  - In the starter BUNDLES.BIN only COLOR4 (Cl. Chrome, bloom 5, no grain) runs the LV Soft Focus pass.
- **lv_bundles H/L** and **tone remap** change table contents only. The remap is about 3-4 k instructions per job
  build (TONE_ENDS (d)), and there is no extra pixel pass.
- Nothing else (WB getters, LCD tint, SD loader) adds per-frame work.

Conclusion [I]: the mods add at most one stock-sized IPU pass per LV frame, and only on bloom or Pin Hole slots.
That is unlikely to explain a large difference, and the E-P7 runs warm in LV in stock too.

Mitigations, if a restore-stock comparison shows a real difference:
- a build without the LV bloom preview (`patches/lv_art --features hl,art`);
- a class-8-only gate (stills LV only; keeps movies clean);
- later, a user toggle "Preview effects in live view" (default off).

## #19 (c): "only the 800T preset was imported"

[I] Almost certainly a usage question. The installer copies the starter BUNDLES.BIN only if none exists. Its
COLOR1/COLOR2 slots are CineStill 800T, so the profile showed 800T. The other 28 colour looks in LOOKS.BIN are not
slots. They are a library on each profile's **Film page**, to be picked one per COLOR slot. A slot the user has not
picked keeps its BUNDLES.BIN contents or the user's own colour-wheel settings.

## Suggested replies

### #19

Thanks for the detailed report, and no need to apologise for the translation, it's very clear.

**Rec View / Auto Review:** I went through everything the mod changes. Nothing touches the Rec View setting, its
allowed values or the review-image code, except two size entries for the Panorama/Wide aspects. I can't reproduce
it from the code alone, so could you help me narrow it down?
1. Which Rec View value is set (Menu → Setup (wrench) → Rec View), and which aspect, picture mode and drive mode
   (single, sequential, anti-shock or silent) do you use?
2. Set Rec View to 2 sec, switch the camera off and on, and take one shot in P mode with the Natural picture mode.
   Does the review show?
3. If you can, flash `restore/E1429999.BIN` (stock 1.1) and try the same shot. Does stock show the review on your
   camera? Then reflash Caduceus.

**Heat:** the mod adds at most one small live-view pass (the same as the stock Soft Focus art filter), and only on
profiles whose look has glow (bloom) or Pin Hole. Colour, tone and the other settings cost nothing per frame. The
E-P7 also gets warm in live view on stock firmware. If you can compare with the stock firmware (step 3) and it's
clearly cooler, please tell me: I can make the live-view glow preview optional.

**LUTs / looks:** I think everything was imported. The looks just live somewhere else than you expected.
`BUNDLES.BIN` holds your four colour-profile slots (the starter file puts CineStill 800T in the first ones, which is
the one you saw). `LOOKS.BIN` adds the other looks to the **Film page**, a library you pick from. To use them
without losing your own colour-wheel settings:
1. Keep your `EP7MOD/BUNDLES.BIN` (don't overwrite it).
2. Copy `LOOKS.BIN` into `EP7MOD/` on the card.
3. Put the card in, switch on, and half-press the shutter once (that loads the files).
4. Choose a Colour Profile slot you don't mind changing (for example Color 4), open its colour wheel, and press
   **INFO** until the page shows a look name (the Film page).
5. Turn the dial to pick a look and confirm. Only that slot changes, and your other profiles keep their own
   settings.

### #20

Thanks for reporting this, and sorry about the lost shot. You're right: on a colour profile, Blur can restart
the camera. It turns on a camera effect outside the mode it was designed for, and I can't make that safe
without more testing. So **v0.21 removes Blur**: the Art Effect now cycles Off / Star Light / Pin Hole, and a profile
that already has Blur saved behaves as Off.

Until v0.21 is out: open that profile's colour wheel, press **INFO** to the Extras page, and set **5 Art** to Off
(or Star Light / Pin Hole). Half-press once to save it.
