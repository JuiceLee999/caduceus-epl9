# test8-filmmenu: film names on the Picture Mode profiles (phase 2a), on the test-7b base

**What it is.** Test 7b (camera-proven: rec_limit, video log, bundles lachlan_v3, grain, bloom, per-profile WB,
SD look loader v3) plus two things. Design and results: docs/FILM_LIBRARY.md §8.7.

1. **Loader v3 + names.** `EP7MOD/BUNDLES.BIN` may now be 680 bytes: the old 544-byte file unchanged, then 8 slot
   names (≤ 15 characters), `EP7N` and a CRC. A 544-byte file loads exactly as in 7b. Bad names are dropped,
   but the looks still load. Names are written into the heap block in this order: names, then `EP7N`, then the
   handle at 0x622cbcc2. Nothing is ever written into image RAM.
2. **Label hook.** The two option-label builders (0x60df255f / 0x60df25dc) jump to a 159-B hook in the
   section-6 tail. 40 COLOR/MONO profile entries (Picture Mode lists, Live Control/SCP lists, both menu item
   trees) have their unused text pointer moved to 8 flashed empty strings at 0x61242e00. The name is shown
   only when the entry is marked, the handle is valid, the block holds `EP7B` and `EP7N`, and that slot's name
   is not empty. In every other case the 6 stock instructions are replayed, so the label is stock.

79 edits, 3,016 changed bytes. `edits.json` = generated/film_menu/t8.json. All 34 of test 7b's edits are
byte-identical except the loader (0x605b7400): names code, plus one range-table byte, because effect_id is now
0..3 (clarity's change, kept so that clarity can merge later). Clarity itself is **not** included.
`restore-stock.pkg.bin` is identical to the 6/7b restore. The packages and `card/` are local only (*.bin/*.BIN are
gitignored).

**Card file.** `card/EP7MOD/BUNDLES.BIN` (680 B, sha256 `59439e6f…`) is built from `bundles/lachlan_v3_names.json`.

| Slot | Look | Name |
|---|---|---|
| COLOR1 | none (your own profile) | Kodachrome |
| COLOR2 | Classic Neg, grain low | Classic Neg |
| COLOR3 | none (your own profile) | Warm |
| COLOR4 | Portra 400 + bloom 2, WB A+2 | Portra |

Its look table is byte-identical to the flashed one, so **pictures look the same with or without the card**.
Only the labels change. MONO1–4 keep their stock labels.

## Camera test plan (one step at a time; stop at the first surprise)

Keep the proven SD restore (`restore-stock.pkg.bin`) ready.

1. **Flash `patched.pkg.bin`, card WITHOUT the EP7MOD folder.** Expect stock labels everywhere. Check:
   - Picture Mode menu: scroll the whole list. Color Profile 1–4 and Monochrome Profile 1–4 should show stock
     names and badges.
   - Live Control and the Super Control Panel picture-mode list.
   - Both shooting menus where the picture mode appears, and the Color Creator / profile sub-screens.
   - Scroll a few unrelated lists too (EV, aspect, WB, ISO). Every list goes through the hooked builders.
   - 5 power cycles, half-press several times, shoot COLOR2 and COLOR4 (should look like 7b), record one movie.

   A crash or garbage here means a hook replay bug. Reflash the 7b package or restore.
2. **Copy `card/EP7MOD` to the card root.** Power on.
   - Before any half-press, open Picture Mode: labels should still be stock (names load on the first half-press).
   - Half-press once, then reopen Picture Mode. Expect **Kodachrome, Classic Neg, Warm, Portra** on Color Profile
     1–4. MONO1–4 stay stock.
   - Check Live Control, SCP and the menu value column too. Note any clipped, blank or garbled label, and say on
     which screen, and whether a `@` badge disappeared.
   - Shoot COLOR2 and COLOR4: unchanged from step 1.
3. **Remove the card folder (or the card) and power cycle.** Stock labels again, with no reflash needed.
4. Optional: put back the 7b test file (544 B, no names). Expect stock labels, and COLOR1 greens teal (the 7b
   check). This proves that old files still load.

Every failure in steps 2–4 depends on the card, so taking the card out brings the stock labels back.

## Emulator verification (generated/film_menu/*.out, *.json)

- `tools/ep7_verify_film_menu.py`:
  - **S** static: edits, markers, guards, sites. The only section-6 diffs are ours, and exactly 40 words point
    at the markers.
  - **L** the real builders A and B run over all 44,703 label sources in section 6 (plus 18 boundary entries).
    11 handle/heap states, 22 runs, all PASS. Every no-name state is byte-identical to stock: labels, d0/d1/a0/a1,
    sp, d2, final registers and stack. With names, the marked entries are byte-identical to stock's kind-5
    label of the name, with ≤ 15 characters and a terminator. Corrupt heap names give 15 characters at most,
    sign-extended like stock. Section 6, the heap block and the state are mapped read-only, so any store into
    them would fault.
  - **X** the real loader reads this card file, and the hook shows the 4 names. A 544-B file gives stock.
  - **M** 14/14 hook mutations detected.
- `tools/ep7_verify_sd_bundles_v3.py`: S, E/F (179 cases), Q (10), A (64), R, and N (29 name cases: valid,
  CRC, marker, `@`, 16 characters, 0x7f/0x1f/0x80/0xff, text after NUL, sizes, short read) all PASS.
  M: 20/20 mutations detected.
- Reader verifiers on t8, flashed and loaded: bundles 56/56 and grain 7/7, both PASS in both modes. Bloom has
  6/6 checks; its flashed and loaded runs both exit 0. WB: 26 PASS in each mode, plus the same single
  config-dependent mutation miss as tests 6/7b.

Rebuild (main tree, each command in `systemd-run --user --scope -p MemoryMax=3G -p MemoryHigh=2500M -q`):
```
G=generated/film_menu
.venv/bin/python -I patches/sd_bundles_v3/build.py --names --out $G/sdv3
.venv/bin/python -I patches/film_menu/build.py --out $G/menu
.venv/bin/python -I patches/bundles/build.py bundles/lachlan_v3.json --out $G/bundles --sd-v3
.venv/bin/python -I patches/grain/build.py --out $G/grain --sd-v3
.venv/bin/python -I patches/bloom/build.py --out $G/bloom --sd-v3
.venv/bin/python -I patches/wb/build.py --out $G/wb --sd-v3
.venv/bin/python -I tools/merge_specs.py $G/t8.json patches/rec_limit/edits.json patches/video_log/edits.json \
    $G/bundles/edits.json $G/grain/edits.json $G/bloom/edits.json $G/wb/edits.json $G/sdv3/edits.json $G/menu/edits.json
.venv/bin/python -I tools/build_package.py $G/t8.json --out releases/test8-filmmenu
.venv/bin/python -I tools/ep7_bundles_bin.py bundles/lachlan_v3_names.json --out releases/test8-filmmenu/card
```

Offline build. No camera was contacted. The package names are deliberately not SD-loadable. Not yet
independently reviewed.
