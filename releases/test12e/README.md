# test12e: page key, plain labels, Film page (+ extras, lv_bundles, lv_art, aspect v3)

One combined build, 220 edits, merged in this order: look editor 12e → look_extras → **film_menu_v2** →
lv_bundles → lv_art (hl, bloom) → aspect v3 (XPan/21:9 + SCP list). The base is test 11 (v0.6 + clarity + view
assist). Emulator-verified only; not camera-tested.

## What changed from 12d (card table loaded; without `EP7MOD/BUNDLES.BIN` everything is stock)

**Keys in the Color Profile editor** (revised in place: on the camera MENU/PLAYBACK open their own screens, so
the record +36 hook is gone and those words are stock 0x60e22191 again)
- **INFO steps the page**: **Saturation → Saturation - All → Hue → Light → Film → Extras → Saturation**.
  Saturation → All is the stock toggle; leaving All calls the stock handler (ALL off), then Hue. Film only while
  `EP7MOD/LOOKS.BIN` is loaded (first half-press), Extras via the extras layer. Half-press leaves the editor.
- Key codes for reference (GUI key table 0x6113e938): MENU 0x900e/0x9040/0x900f, PLAYBACK 0x9010/0x9011,
  Movie 0x9012, INFO 0x9014.

**Guide label** (bottom left, at most 16 characters, no probe codes)
- Saturation: `Saturation`, or `Saturation - All` when ALL is on.
- Hue: `Hue`. Light: `Light`.
- Film: `Film: Velvia`. An 11-character name is shown as `Film Classic Neg`. A 12-character name is shown alone,
  e.g. `Kodachrome64`. An empty slot shows `Film: Stock`, and a slot without a name shows `Film: Custom`.
- Extras: the sector number, the field and its current value.

| Sector (cursor) | Wheel colour | Label examples |
|---|---|---|
| 1 | yellow | `1 Grain Off` / `Low` / `Medium` / `High` |
| 2 | orange | `2 Glow 3` (−), `2 Clarity/Glow 0`, `2 Clarity +2` (+) |
| 3 | orange-red | `3 WB Blue 2` (−), `3 WB Amber/Blue`, `3 WB Amber 2` (+) |
| 4 | red | `4 WB Magenta 5` (−), `4 WB Green/Mag.`, `4 WB Green 3` (+) |
| 5–12 | others | `Extras: 1-4 only` |

**Film page** (docs/FILM_MENU_V2.md)
- Loading: on the first half-press, `fm_load` reads `EP7MOD/LOOKS.BIN`. It has 16 colour looks from LIBRARY_V1.
  A missing or invalid file just means there is no Film page.
- Stepping: on Film, the dial, the arrows and touch step this slot through its own look, then the 16 looks, then
  Stock, wrapping around. Each step writes the slot entry and name into the heap and marks the table dirty.
- Saving: the next half-press saves BUNDLES.BIN through the 12d save (.NEW → .BAK → .BIN). Picture Mode, LC and
  SCP then show the name through the test-8 hooks.
- Resume: a slot whose name matches a library look resumes on it. On this card that is COLOR2, Classic Neg.
- The wheel number on Film still shows saturation; it is not edited there.

Code space (docs/CODE_SPACE_MAP.md):
- New: the editor keys at EVF step-3 tables 0x601e2f3c (sec 1). The film UI at EVF step-4 0x601e2c3c (sec 1).
  The film core and LOOKS.BIN rules in the sec-9 claim 0x6143a410.
- No change: lv 0x601e0e3c, lv_art 0x601e113c and the aspect claims.

## Camera plan (one step at a time; stop at the first surprise; SD restore ready)

1. **Card without EP7MOD.** It boots in 4:3. In the Color Profile editor, INFO toggles ALL as stock, and MENU
   closes the editor as stock.
2. **Card = `card/` (BUNDLES.BIN = your current 12d file + LOOKS.BIN).** Half-press once, then open the COLOR2
   editor. Label: `Saturation`. Press INFO: `Saturation - All`. Press INFO again: `Saturation`.
3. **Page key.** Press MENU and note each label: `Hue` → `Light` → `Film Classic Neg` → `1 Grain …` (Extras)
   → `Saturation`. Then try the same with PLAYBACK. If it leaves the editor, use MENU only.
4. **Film.** On the Film page, turn the dial. The label steps `Film: Nostalgic`, `Film: Reala Ace`, … through
   `Film: Stock` and back to your own look. Pick Velvia and leave. Picture Mode should show Velvia for COLOR2.
   Shoot a frame. Half-press, then check on the PC that BUNDLES.NEW/.BAK/.BIN were written. Run
   `tools/ep7_bundles_bin.py --check`, which shows COLOR2='Velvia'.
5. **Extras.** On Extras, move the cursor over sectors 1–4 and check that the label names the field and value.
   Set grain 2 and clarity +2, then shoot to compare.
6. **Persistence.** Power-cycle, half-press, then open COLOR2 and go to Film. The label shows `Film: Velvia`.
7. **Live view** (lv_bundles / lv_art, docs/LV_BUNDLES.md, docs/LV_ART_PREVIEW.md): COLOR slot H/L and bloom now
   show in LV.
8. **Aspect:** Panorama and Wide sizes, and the SCP list (docs/ASPECT.md).

Recovery: removing LOOKS.BIN removes the Film page, and picks already saved stay. Removing BUNDLES.BIN gives
stock. `restore-stock.pkg.bin` restores stock firmware; it is identical to the 12d restore.

## Verification (emulator)

| Check | Result |
|---|---|
| Editor (`tools/ep7_verify_look_editor.py generated/look_editor_12e/merged.json --part S,E,V,T`) | S; **E 269** (INFO page cycle with/without F and X on 4 COLOR keys, page × ALL flags, stock decline, guards, no table == stock, other events, router: +36 stock again); **V 230** (labels incl. Film names); T 19 PASS |
| Extras (`patches/look_extras/verify.py … --part S,G,W,V`) | S, G 744, W 4048, **V 648** (new labels with values) PASS |
| Film (`patches/film_menu_v2/verify.py`) | V 10 (fm_valid handle checks), **U 62** (no LOOKS.BIN / bad handle / other page == 12e without film, at the stock Up/Down), **P 11** (full wraps Up/Down on 4 keys, entry == `place()`, own restored, mono skipped, no names section), **L 50** (load OK incl. 1/16/19/20 looks; 41 reject cases: sizes, header, CRC, ranges, class/mask, name rules, no file, malloc/fseek/short read → EP7X, L freed; already loaded → no call), H 1 (half-press loads once), **T 4** (pick → half-press save: .NEW/.BIN == heap image, camera rules, name) PASS |
| lv_bundles (`tools/ep7_verify_lv_bundles.py --no-mutations`) | 91/91 PASS (sd_v3=True) |
| lv_art (`patches/lv_art/verify.py --no-mutations`) | 8/8 PASS |
| lv_art × lv | an LV job with lv_art's transport (0xB2 + profile p, registry says another profile): 12e == the same build without lv; H/L applied once, from slot p (3 cases) PASS |
| Aspect v3 (`patches/aspect/build.py --base` the pre-aspect spec) | 198/198 PASS; generated spec == patches/aspect/edits.json |
| Package | `patched.pkg.bin` payload == emulated image of edits.json; `restore-stock.pkg.bin` == stock (byte-identical to 12d's) |

Per the user's request no mutation runs were made this round. **Not covered by the emulator** (camera only):
- the real redraw after a Film step;
- label clipping;
- clarity/grain image effect;
- the LV pixel result.

Rebuild:
```
python patches/look_editor/build.py --base releases/test11/edits.json --out generated/look_editor_12e
python patches/look_extras/build.py --editor generated/look_editor_12e/merged.json --out generated/look_extras_12e
python patches/film_menu_v2/build.py --base generated/look_extras_12e/merged.json --out generated/film_menu_v2_12e --card generated/film_menu_v2_12e/card
python patches/lv_bundles/build.py --base generated/film_menu_v2_12e/merged.json --out generated/lv_bundles/t12e
python patches/lv_art/build.py --base generated/lv_bundles/t12e/merged.json --out generated/lv_art/t12e
python tools/merge_specs.py generated/test12e/merged.json generated/lv_art/t12e/merged.json patches/aspect/edits.json
python tools/build_package.py generated/test12e/merged.json --out releases/test12e
```
The 12d sources are kept in generated/look_editor_12d/src_12d and generated/look_extras_12d/src_12d.
