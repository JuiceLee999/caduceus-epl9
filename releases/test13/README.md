# test13: test12e + aspect v6 + Film `*`, bloom colour, mono presets

## Aspect v6 in place (254 edits = the 126 non-aspect edits unchanged + aspect v6, 128)

Camera test 13: Panorama/Wide captured correctly (5184×1920 / 5184×2224) but live view kept the stock 7:6/6:5
pillarbox and looked squished. Cause: the LV output size is not table driven. `CapThr_ThroughImage.cpp` has three
hard-coded switches on the raw setting-270 id (getOutputSize 0x60882bb3, getOutputSizeForFineZoom 0x60882ec4,
getTakeAreaSize 0x608833ae; jump tables 0x60b01e48/74/a0) that return 560×480 / 576×480 for ids 6/7. v5 changed the LV
crop (ratio pair) but not this output box, hence the squish. v6 sends ids 6/7 to new case blocks (640×240 / 640×272)
in the dead EVF gamma table 0x601e143c; the playback `get_aspect_frame` switch (0x60b1f34c) and the rec-view 640
arrays 0x6053e23c/0x6053e24e get the same sizes. docs/ASPECT.md §1e.
- Expect: Panorama/Wide LV full width with top/bottom bars (65:24 / 21:9), not squished; rec view and playback the same shape.
- Emulator: `patches/aspect/build.py --lean` 70/70 (S7–S10 ids 1,2,3,4,9 stock and 6/7 → 640×240/272; rec-view getters).
- Package: decode == stock + edits.json, restore == stock; 129 main bytes differ from the previous test13 package, all in aspect spans.

## Fixed in place after camera test 13b (my 243 edits + the 11 later aspect edits = 254; every aspect edit kept)

Shots PB021368–1373 are COLOR1 (CineStill800, effect 2) and PB021376–1379 are COLOR2 (bloom 5). PB021374–1375 are
MONO1 "Red Contrast". The shots were identified from the makernotes.

1. **CineStill had no red glow: root cause.** Red bloom did run, and its luma glow is visible. Its colour term
   only multiplies the light's own chroma. A white or clipped light has none: on the LED strip the core reads Cr 0 and
   the fringe reads Cr +5, which is the lamp's own cast. A red glow around white lights is not possible in this
   combiner (docs/HALATION_RED.md §8).
   - **Now: bloom colour.** Each slot has a byte for the bloom colour: Neutral, Red, Amber, Warm or Cool.
   - Red spreads the red channel 3.5× as far as the glow and blue only 0.5× (before: 2.5× / 0.625×).
   - The colour shows on warm lights (tungsten, sodium, neon, tail lights). White LEDs stay neutral.
   - CineStill800 in library v2 is now bloom 4 with colour Red. A slot that still has effect 2 (like COLOR1 on your
     card) renders red.
2. **Extras page:** sector 5 shows `5 Bloom Neutral` / `Red` / `Amber` / `Warm` / `Cool`; turn the dial to choose.
   Sector 2 now shows red bloom as `2 Glow N`.
3. **Live view:** a red-bloom slot now gets the LV glow. CineStill lost it in test13, because live view previewed
   effect 1 only.
   - The weaker LV colour you saw is mainly library v2's 3× smaller WB shifts.
   - The new hook and the aspect LV change do not touch LV colour.
4. **Mono presets did apply.** The shots carry red filter strength 2, grain Low, shading −1 and Highlights +1, and the
   wood renders light grey. Two bugs:
   - Shadows and Midtones were swapped. Fixed.
   - The open filter or shading screen did not redraw. Fixed: after the refresh, the preset re-writes the screen's
     own setting, as the colour editor's page step does.
5. **Card format:** slot byte +45 = bloom colour 0..4. The loader allows 0..4 there (it allowed only 0).
   - LOOKS.BIN record +47 carries the colour.
   - Old BUNDLES.BIN and LOOKS.BIN files still load: 0 = neutral.
   - A file that uses a colour is rejected by older firmware.
   - `tools/ep7_bundles_bin.py --check` lists each slot's effect and colour.

Card: BUNDLES.BIN is unchanged. LOOKS.BIN is regenerated: only CineStill800 changed (bloom 4 + Red).

**Camera plan for 13b:**
- E. **Bloom colour:** on COLOR1 (CineStill800 on your card), shoot a tungsten bulb or a warm street light at night.
  The fringe should be red beyond the glow. A white LED will stay neutral: that is expected.
- F. **Extras:** step to Extras, go to sector 5 and turn the dial: Neutral → Red → Amber → Warm → Cool. Save, then
  shoot the same light with Amber and with Cool.
- G. **Mono:** in MONO1's filter screen, press INFO. The filter shown should change at once. Then check Highlight &
  Shadow for Red Contrast: Highlights +1, Shadows −2, Midtones 0.
- H. **LV:** COLOR1 should show a glow in live view.

Emulator (no mutations):
- halation F 24, W 84, D 112 (tints × combiners 11/12, guards; tint-0 bloom / clarity / off / erased banks
  byte-identical to the previous test13);
- mono S 98, H 48;
- extras S, G 120, W 224, V 72 (quick);
- film L 50, P 5, M 50 (quick);
- lv_art 8/8;
- loader v3 E 179 and N 29 (on the base spec: tint 4 loads, 5 rejects);
- package: decode == emulated image, restore == stock (byte-identical). 3160 bytes differ from the previous test13,
  all inside edit spans.

Rebuild (generated/test13t): as below, with `--out generated/test13t/...`. The base is generated/test13r/base_t11h.json
with the loader v3 edit rebuilt from the new layout (one byte, 0x605b774e 0→4) and the bloom edits replaced. The
release edits = test13t/mp + the aspect edits taken from the release's edits.json.

---

## Added in place (243 edits; aspect v5 kept unchanged)

1. **Film label `*`.** When the slot's entry differs from its picked library look, the Film page shows
   `Film: Velvia*`. The name is cut so the label stays at 16 characters. The film layer's `fm_mod` is reached through
   the new editor layer word `ed_cfg_fm`.
2. **Red bloom (effect_id 2)**, docs/HALATION_RED.md §6. Same luma glow as bloom, but the blurred share spreads Cr
   2.5× and Cb 0.625× (hook 0x603a04e8 → halo stub 0x60210e10, plus bloom_w/bloom_flag accepting 2). CineStill800 in
   library v2 and `card/EP7MOD/LOOKS.BIN` now uses it at strength 4. Bloom colour presets are only a plan (§7): they
   need a card-format change, so this release has red only.
3. **Mono presets**, docs/MONO_PRESETS.md (replaces the mono-colour plan; MONO rendering stays stock). In the stock
   MONO1–4 colour-filter or shading editor, **INFO** steps Acros → Tri-X 400 → HP5 Plus → Red Contrast → Sepia Print
   → Cyanotype. Each step sets the profile's stock filter, strength, toning, grain, shading and highlight / shadow /
   midtone through the stock SetValue, and names the MONO slot. The half-press save keeps the name, and INFO resumes
   from it. Without a card table, INFO closes the editor as stock.

Card: BUNDLES.BIN is unchanged. LOOKS.BIN is regenerated (16 colour looks of library v2; only CineStill800's effect
changed).

**Camera plan for these three** (after steps 1–8 below):
- A. **Mono, no card:** in a MONO profile's filter screen, INFO closes the editor as before.
- B. **Mono, card loaded** (half-press once):
  - In MONO1's filter screen, press INFO. The filter should change; note what it shows.
  - Press INFO again a few times and check filter, grain, toning and Highlight & Shadow against the table in
    docs/MONO_PRESETS.md. Note any field that differs: the toning order and the HL/SH/MID order are guesses.
  - Leave the editor. Picture Mode shows the preset name for MONO1.
  - Half-press, power-cycle, then check that the name stays.
- C. **Film `*`:** pick Velvia on COLOR2 Film, step to Hue, change one sector, then step back to Film. The label
  should read `Film: Velvia*`.
- D. **Red bloom:** pick CineStill800 and shoot a tungsten or neon light at night. Expect a red-orange fringe beyond
  the luma glow. Compare with a bloom slot. If the result is blurred or blue instead, report it: the channel order
  is a guess (HALATION_RED §4).

Emulator for this round (no mutation runs):
- editor E 269, V 230, T 19 (S: only the known 0x609330fa site);
- extras S, V 648;
- film **M 50** (fm_mod + label), V 10, U 62, P 11, L 50, H 1, T 4;
- verify_poly 595/595;
- lv_bundles 91/91, lv_art 8/8;
- **halation** F 70, W 46, D 284 (`tools/ep7_halation_verify.py` vs the previous test13);
- **mono presets** S 98, H 48 (`patches/mono_presets/verify.py`);
- aspect lean checks on the pre-aspect spec;
- package: decode == emulated image, restore == stock (byte-identical). 1909 bytes differ from the previous test13,
  all inside edit spans. Nothing new runs at boot: the new code is reached only through editor keys, the art /
  bloom combiner, and the label.


**Aspect v5 (in place, 232 edits):** camera test 13 saved Panorama/Wide at the stock 7:6/6:5 sizes. The capture size comes from the split
W/H tables 0x6053de1c/0x6053dfcc (getters 0x603f0a04/18), LV/AF from the ratio pair table 0x60236e14 (.data). v5 patches those + the ORF frame
fit entries (docs/ASPECT.md §1d). Expected: Panorama 5184×1920, Wide 5184×2224, LV letterboxed top/bottom. Other edits unchanged.

## Wheel polygon follows the page (added to test13, 223 edits)

On **Hue**, **Light** and **Extras**, the coloured polygon on the wheel now draws the values that page shows,
not saturation. On **Film** it is a neutral circle, and on **Saturation** it stays stock. The producer was mapped
as view vtable +4972 = 0x60932fa6, case 1. It reads its 12 sector values through the stock getter 0x602afa81,
which is why H/L never showed. Hook: 0x609330f9 → `ed_poly` (ed_keys, sec 1, docs/LOOK_EDITOR.md §6 test13).
Without a card table the behaviour is stock. Known limit: after you leave the editor on Hue, Light or Extras, any
other screen that draws the COLOR wheel keeps that page's shape until the editor is opened again. The numbers
already behave this way.

Camera check: open COLOR2 and press INFO to step to Hue. The polygon should change to the hue values; a sector at
0 sits on the neutral ring. Edit a hue sector: the polygon follows. Then check Light, Film (circle) and Extras
(bumps on sectors 1–4).

Emulator (lean): `patches/look_editor/verify_poly.py` 595/595 on each of editor, +extras, +film and the final
spec (real site, image read-only). The stock path matches stock in registers and stack; H/L equal the table;
Extras equals ex_get; Film is 0. Relocation spot checks: editor E 269 and T 19, film H 1 and T 4 PASS. The editor
static check S lists 0x609330fa as an unknown diff; that is the new site, not yet in its allowlist. Package:
decode == emulated image; restore == stock (byte-identical to 12e).

List-style menus: feasibility in docs/LOOK_MENUS.md. Nothing was built, because every list route needs a host
menu item whose control we would give up.


**test13 = test12e with the aspect edits swapped for aspect v4 (108 edits, 222 total).** Camera test 12e showed Panorama/Wide in neither the menu nor the SCP: the static setting validator 0x604cc98c (sid 270 record 0x604cec14, u8 list 1,3,2,4,9) filters every option list. v4 relocates that list to 0x60210f70 = 1,3,2,4,9,6,7 (count 5→7). docs/ASPECT.md §1c. Everything below is as test12e.

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

Rebuild (current, generated/test13r):
```
python patches/bloom/build.py --sd-v3 --clarity --halation --out generated/test13r/bloom
  (base_t11h.json = releases/test11/edits.json with its 3 bloom edits replaced by those 5)
python patches/look_editor/build.py --base generated/test13r/base_t11h.json --out generated/test13r/le
python patches/look_extras/build.py --editor generated/test13r/le/merged.json --out generated/test13r/lx
python patches/film_menu_v2/build.py --base generated/test13r/lx/merged.json --out generated/test13r/fm
python patches/lv_bundles/build.py --base generated/test13r/fm/merged.json --out generated/test13r/lv
python patches/lv_art/build.py --base generated/test13r/lv/merged.json --out generated/test13r/la
python patches/mono_presets/build.py --base generated/test13r/la/merged.json --out generated/test13r/mp
python tools/merge_specs.py generated/test13r/merged.json generated/test13r/mp/merged.json patches/aspect/edits.json
python tools/build_package.py generated/test13r/merged.json --out generated/test13r/pkg  (then copied into releases/test13)
LOOKS.BIN = ep7_looks_bin.compile_looks(film_menu_v2 colour_library(bundles/library_v2.json))
```
The 12d sources are kept in generated/look_editor_12d/src_12d and generated/look_extras_12d/src_12d.
