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

**Camera results (user / coordinator):**
1. With bloom/clarity looks the review starts dark.
2. The +2 s Rec View build (8ded8fd) showed **a short unprocessed review image, then a long black screen**.
   The extra time only lengthened the black, so 8ded8fd is **reverted** (v0.21 is byte-identical to 06805e4 again).

**How Rec View gets its image and timer [V code]:** the Rec View state machine lives in the record task.
- Handler table `0x604e4bc0` (state x event: {action, entry}), transitions `0x604e4c20`, dispatcher `0x60332607`.
- Event 0 in state 0 goes to state 1 and runs `0x6033277f`:
  - it allocates the yc buffer (`0x6031c483`: memory-manager request `0x6031f7ff` / `0x6031f9f2`, area 0x3c00,
    double-buffer table `0x6266a31c`, index `0x6266a319`);
  - it develops a **separate small review image** from the capture (set_imgprm_recview `0x6031ce13` / `0x6031cd12`,
    "exe image proc" `0x6031cfb3`: request 10, waited for by `0x60311a5b`). The review image is not the finished
    JPEG or thumbnail.
- Then `0x603328bd` posts the buffer to the display (`0x6031c614` -> `0x60320610`). Right after, it starts the
  timer at `0x60332905` (`0x6031c7be`, d0 = time in 0.1 s; callback `0x6031d247` posts the end event), and
  sets state 2.
- In state 2:
  - event 0 runs `0x6033277f` / `0x603328bd` **again**: it stops the timer, re-develops into the other buffer,
    re-displays and restarts the timer. This is a stock "redo the review" path.
  - event 1 runs `0x6033293e` (stop and clear);
  - event 2 runs `0x60332972` (stop, clear, free the yc buffer: the end);
  - event 3 runs `0x60332a27`.

**What blanks it (not settled) [I]:** the review image is up, and then it goes black while the still job runs
our bloom/clarity passes. The passes need two job buffers:
- 0x1060, the 160x120 reduce;
- **0x1061, a full-size 2 B/px upscale** (about 40 MB at 5184x3888; BLOOM_HALATION table). It is described to the
  job pool (`0x60350578`: 48 x 88-B descriptors at job+6592), with its address supplied by the pass setup
  `0x6035cfe9`.

COLOR stills never need 0x1061 in stock, but ART-mode Soft Focus does. So the most likely cause is that the
address the pass setup chooses lies in image memory that the review yc buffer or the display plane also uses in
COLOR mode. The other candidate is that display output is held while the ISP is busy. Neither the memory map nor
the display plane's source is traced, and neither can be emulated meaningfully.

**Why no fix ships yet:**
1. A different scratch buffer for 0x1061 needs the image-memory map (unknown), so it risks corrupting the
   capture.
2. Re-showing the review needs event 0 posted to the Rec View machine (state 2 -> redo) from the still job's
   completion. That runs on another task and its poster is untraced. If the yc buffer was overwritten, a redo
   re-develops it, which is fine; a bare re-post of the old buffer would show garbage.

Neither is clearly safe from static analysis alone.

**Camera results 2 (coordinator):**
- Rec View Off: a short unprocessed frame, then no black.
- COLOR bloom with Rec View 2 s: the unprocessed preview, then 2 s of black.
- **Stock ART Soft Focus with Rec View 2 s:** the colour-corrected picture, then the same picture updated with the
  bloom once processing finishes. So stock already shows and then updates, but only for art filters.

**Where ART mode differs [V code, I meaning]:** the converters split a capture into sub-developments by capture kind
(+194: 0x2001 / 0x2006 / 0x100a) and pass number (+206 = 1 / 2; copied by the record task at `0x603148c1` from
+264 of its source).
- Key mapper `0x603eaa78`: when picture mode (cap+24053) is >= 100, kind is 0x2001/0x2006 and +206 == 2, the key bytes
  are cleared and the result is 2. So pass 2 of an art capture gets a plain (non-art) key, which is [I] the
  colour-corrected first review.
- Params builder `0x603e3fd8`: the same gate (mode >= 100, kind 0x2001/0x2006, +206 == 2) sets params+5528 = 0.
- In COLOR mode (11) both gates fail. Our bloom/clarity therefore runs on every sub-development, including the
  review one, and the review cannot update.
- [I] The ART flow needs more than those two gates: the capture sequencer must also issue the extra development and
  post the Rec View machine's state-2 event 0 (redo, above) when the art pass finishes. Where it decides that for
  picture mode >= 100 is not yet traced. Candidates are the `cmp 100` sites in the record task: `0x60313013`,
  `0x60314d4b`, `0x60316c2b`, `0x60318d2e`, `0x60318f6b`, `0x6031999c`, `0x6031aadc`, `0x60320314/1d`,
  `0x603209ab/b4`, `0x603311b9`.

**Status:** no fix shipped. Extending only the two converter gates to COLOR + effect would strip our effect from
pass 2 without the sequencer's update step, which risks a review that never updates or a missing pass. Next step:
trace the >= 100 sites above to the one that schedules the second development and the review refresh, then extend
that one gate (with the converter gates) to COLOR slots with an effect.

**Trace of the record-task `cmp 100` sites (stopped):** none of them is a single "schedule the art follow-up" gate.
- `0x60314d4b`: record +294 >= 100 forces param +2108 = 0, next to the +206 pass copy at `0x603148c1`.
- `0x6031aadc`: picture mode >= 100 -> `0x60307c8c` table lookup (output codes); below 100, a 1..12 jump table.
- `0x60316c2b`: the LV art-level byte.
- `0x60318d2e` / `0x60318f6b` / `0x6031999c`: a mode value == 100 in request records.
- `0x603311b9`: record art -> `0x60312123`.
- `0x60313013`: the LV Art Effect switch.

The ART two-pass review is spread over the capture sequencer, the record parameters and the converters. ART mode
probably also reserves image memory for its full-size buffers. Changing several of these gates with semantics that
are unproven and cannot be emulated risks lost or corrupted captures. **Judged not safe to build statically.**
Workaround: Auto ▶ or ▶ after the shot.

**Camera probes that would settle it** (cheap; no capture-path change):
- (a) The stock Soft Focus **art filter** with Rec View 2 s. Does it also go black? If yes, this is stock ISP
  contention, not our layout.
- (b) A COLOR look with clarity but bloom 0, and one with grain only. Does the black need the 0x1061 passes?
- (c) Raise the image size from S to L. Does the black scale with the full-size buffer?

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

**Rec View / Auto Review:** thanks for testing. With glow (bloom) or clarity looks, the review image appears
briefly and then goes black while the camera runs the extra glow/clarity processing. The photo itself is fine (check
it in playback). Making the review longer only made the black part longer, so I've taken that change out, and I'm
still tracking down what blanks the screen. Until then:
1. Use **Auto ▶** (Menu → Setup (wrench) → Rec View), which opens playback after the shot. Playback shows the
   finished photo.
2. Or press ▶ after the shot.
3. For fast checks, use a profile whose look has glow/clarity at 0. Those reviews behave as stock.

It would really help if you could tell me:
- Does the stock **Soft Focus** art filter also go black after a shot (Rec View 2 s)?
- Does the black part get longer at image size L than at S?

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
