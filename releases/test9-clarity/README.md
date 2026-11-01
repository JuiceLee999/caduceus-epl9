# test9-clarity: COLOR clarity (local contrast) on the test-7b base

**What it is.** Test 7b (camera-proven: rec_limit, video log, bundles lachlan_v3, grain, bloom, per-profile WB,
SD look loader v3) plus **clarity**: bundle `effect_id` 3, strength 1–5. It runs on the same stock Soft Focus passes
as bloom, but with a mix weight above 1024, which makes an unsharp mask with a ~32 px radius
(w = 1100/1180/1260/1340/1420). Design, evidence and risks: docs/CLARITY.md.

Changes vs test 7b (5 of 34 edits, 487 bytes):
- The bloom stubs are rebuilt with clarity and moved to the section-2 tail 0x6055e5c0. The old section-1 block
  0x60210e10 is back to stock FF. The two hooks (0x603eabd7, 0x6039fee8) now jump to the new address.
- SD loader v3: effect_id range 0..2 → 0..3 (one data byte). Without that change, a card file with clarity would be rejected.
- The flashed bundle table is identical to test 7b's. **No profile uses clarity unless the card file asks for it.**

`edits.json` = generated/clarity/t9.json. `patched.pkg.bin`, `restore-stock.pkg.bin` and `card/` stay local
(not committed).

**Test file.** `card/EP7MOD/BUNDLES.BIN` (544 B) = the flashed table plus **COLOR1 = clarity 5** and
**COLOR3 = clarity 2**. Both slots are stock in the flashed table, and every other profile is unchanged.
Rebuild it with `python3 -I generated/clarity/make_card.py releases/test9-clarity/edits.json <dir>`.

**How to test (one step at a time):**
1. Flash `patched.pkg.bin`. Use a card with **no EP7MOD folder**. Boot, half-press, then shoot COLOR2 and COLOR4
   (COLOR4 = bloom 2). Both should look exactly like test 7b. Start one movie. Do 5 power cycles.
2. Copy `EP7MOD` to the card root, power on and half-press once. Shoot a scene with soft edges and mid-tones in
   **COLOR3 (clarity 2) first**, then COLOR1 (clarity 5), then the same scene in COLOR2 or with the card folder
   removed. Expected: more local contrast and edge "pop", with halos at strong edges in COLOR1.
   Main risk: if the hardware treats the negative weight as unsigned, the frame comes out white or garbage.
   That is a bad image, not expected to crash. Note which happened.
3. Bloom check: COLOR4 should still glow as in test 7b.
4. For any crash, note when it happened (boot / first half-press / shot) and whether it reset or hung.

Recovery: `restore-stock.pkg.bin` (identical to test 6/7b's) via the proven SD restore. Removing EP7MOD from the
card turns clarity off without reflashing.

**Emulator verification** (generated/clarity/): clarity verifier P/C/D/S/L/M all PASS, including 16/16 mutations
and the release card file through the real loader. The bloom verifier passes with the table flashed and
SD-loaded. SD loader v3 S/A/R/M (10/10 mutations) + E/F 179 + Q 10 all PASS. The new code adds no store into
image RAM.

Offline build. No camera was contacted. Package names are deliberately not SD-loadable.
