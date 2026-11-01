# On-camera Film Sim picker (phase 3): design

Design only. No firmware patch was built, no camera was contacted, no `E142*` file was written, nothing was
committed. Base: `releases/test8-filmmenu` (v0.6): loader v3 `--names`, label hooks, accessor, heap block P
published as handle h at 0x622cbcc2. Hard rule kept: **no runtime store into 0x60020020–0x6191ffe0**.
[V] = read from the decoded main (`tools/dis.sh`, byte dumps). [I] = inference. [?] = open; camera or trace needed.

> **2026-11-01: the Recording Volume UI below (§1–§3, §7 3c, §9 steps 0/6) is rejected by the user** because it
> changes the mic level. The loader, LOOKS.BIN, SLOTS.BIN and pk_load/pk_check/pk_apply parts (§4–§5) stay. The
> replacement entry point is **§10 (v2): the Delete key inside the Color Profile editor**.

Mock: `docs/img/ui_look_picker.jpg` (from `sim/screens/look_picker.json` through `sim/ui_mock.py`). The left
panel's "active slot" text is illustration only: stock draws its own item column there.

## 1. Summary

| Question | Answer |
|---|---|
| UI | Use the stock **Recording Volume** item (setting 652) as the picker. It already has a 21-entry list (+10 … −10). With a valid card library, the existing label hooks (extended) draw the item title as "Film Sim" and entry j as library look j (j = 20 = "Stock"). Without a card the menu is stock, byte for byte. No setter, validator, list or OSD edit is needed. |
| Apply | Lazily, in **HLS_EVENT on the next half-press** (the camera-proven loader context): if setting 652 has changed since the last press, look j goes into the **active** COLOR/MONO slot (heap table P+32 and name P+544). |
| Persistence | **(a) `EP7MOD/SLOTS.BIN`** (20 B), written from the same HLS_EVENT hook with the stock fileif fwrite. Recommended. (b) is rejected; (c) RAM-only is the first camera step. |
| Loader | A second card file **`LOOKS.BIN`** (≤ 20 looks, 64 + 64·n ≤ 1344 B) goes into one more class-1 2048-B block L. P+676 (always zeroed by the v3 loader) holds the L pointer. P, the accessor and every reader stay unchanged. |

## 2. Verified facts used

- **Setting 652 = Recording Volume** [V]. Item records at 0x6117b090 (string 1456 "Recording Volume") and
  0x6117b12c (string 1573 "Adjust the microphone level."). Two descriptors `{652, 21, list}` at 0x6117affc
  → list 0x61179dbc and 0x6117afd4 → list 0x6117aa98. Each list is 21 × 12-B entries, values +10 … −10,
  kind 5 (text "+10" …), and "0" is kind 6. Property key/index from the ID table 0x604d6c14[652] =
  `{0xecf9, 0}` [V]. The "+n" strings 0x61179d7c… are shared by other ±7/±10 lists, so the picker keys on the
  **entry address**, not on the text pointer.
- 652 is the only menu setting with ≥ 20 native options and no effect on stills (descriptor scan of sec 6;
  the others are drive, EV, ISO, art/scene and language lists). Its only effect is the movie mic level.
- **Both label builders reach the hook point for every kind** [V] (0x60df255f in A, 0x60df25dc in B). The
  label kind just set is in (a3), and a2 = entry+4 (builder A). So the test-8 hooks can also catch kind-5/6
  entries; today they replay them.
- **fwrite exists** [V]: fileif wrapper **0x60635041** (message 0x10003, implementation 0x60645741). Arguments
  a0 buf, d0 size, d1 count, a1 handle → d0, the same shape as fread. 77 stock call sites, frame
  `[d2,d3,a2,a3],24`. Stock precedent: section-5 app code at 0x60765cc8 does `fopen(path, "w")` (mode string
  0x60a65d37) → sprintf/strlen → `fwrite(buf,1,len,fh)` → `fclose` (an audio-IC register dump to a .txt file).
- **Active slot** [V]: property getter 0x6005e971 (`d0` key, `d1` 0, `a0` 0, frame `[d2,d3],12`, lock-free,
  docs/PROFILE_INDEX_WB.md). Mode = key 38017 (6 → re-read 40209). 11 → COLOR profile via key 63153,
  12 → MONO via key 63281, profile 1..4 (patches/bundles). Slot = 0/4 + profile − 1.
- **Class-1 malloc blocks are ≥ 2048 B** [V/I]: malloc sends every request of 129..2048 B to class 1. Pool
  [0xa1f8d800, 0xa1f98540) = 44352 B = 21 × 2112, which fits 21 blocks of 2048 B plus a 64-B header each [I].
  The v3 loader's malloc(1024) therefore already holds a 2048-B block. The picker takes one more (2 of 21).
- **P+676..679 is zero after every successful v3 load** [V, loader source]. The loader zeroes +544..+679, and the
  names path writes only +544..+675.
- Free FF tails with no real references (HSL_PORT.md section table): **sec 5 0x60b9dd00–0x60b9e000** (768 B)
  and **sec 9 0x6143a350–0x6143a800** (1200 B; a `cmp 0x6143a350,a0` bound points at the start of the sec-9
  tail). Both are entered in CODE_SPACE_MAP.md as **proposed, not built**.

## 3. UI (question 1)

Cheapest credible: **relabel Recording Volume when a library is loaded**. It is reached through Menu → Video
(movie) tab, Recording Volume [?: confirm on stock firmware that it can be edited in stills mode].

- Title: a kind-4 label with string id 1456 → "Film Sim" (flashed constant), only when the library is valid.
- Value list: the entry at list+12·j (either list) → name of look j (j = 10 − value). The hook checks that
  a2 == list + 4 + 12·j for the j it computed. j < n → look name; j = 20 (−10) → "Stock"; n ≤ j < 20 → "--".
- The menu value column (item value drawer → builder A on the item's list) then shows the current pick.
- Picture Mode, LC and SCP already show slot names from P+544 (test 8). They update when a pick is applied.

**Flow:** set Picture Mode to the slot (e.g. COLOR2) → Menu → Film Sim → pick "Velvia" → exit → half-press.
COLOR2 renders Velvia and is labelled "Velvia", and SLOTS.BIN is written.

**Limits (accepted for phase 3):**
1. The pick lands on whichever slot is active **at the half-press**.
2. A change is detected only as "652 differs from the value seen at the last press". Choosing the *same* look
   for a second slot needs another pick in between.
3. A mono look picked for a COLOR slot (or a colour look without the MONO bit for a MONO slot) is refused
   silently. The slot's label keeps the old name, which is the only feedback.
4. **The movie mic level becomes the look index** (value = 10 − j). This is the main cost for a video user.
   Fix in phase 3c: trace the audio consumer of 652 (22 `mov 652,d0` sites, none traced) and pin it to a
   baked level. Or move to an intercepted host (§8, option H2).

Rejected UIs: button cycle (no function code or action handler exists, and it is blind without LC); a new
page or settings (validator, storage and defaults, the most unknowns); virtual Picture Mode entries (the setter
sees only the value, so duplicate values cannot be told apart).

## 4. Persistence (question 2)

| Option | Verdict |
|---|---|
| **(a) SLOTS.BIN via fwrite** | **Recommended.** fwrite is available [V]. Writes happen **from HLS_EVENT**, not the UI task: the fileif RPC from HLS_EVENT is camera-proven by tests 7b/8 (reads). From the UI task (HIGHLEVEL_MAIN) it is unproven (the v1 path was dead). 3 round trips (fopen "w", fwrite 20 B, fclose), only on a press right after a change. |
| (b) Repurpose a persistent setting | **Rejected.** It needs 8 bytes of dormant persistent settings, validator edits and a proof of dormancy. It is the REVIEW_v03 H3 risk class: a persisted value with no physical escape that survives card removal and restore. The map is also meaningless without the card's library. |
| (c1) RAM only | First camera step (no writes at all). The picks are lost at power-off, and the defaults come from SLOTS.BIN or BUNDLES.BIN. |
| (c2) Rewrite LIBRARY/LOOKS in place | Rejected: any failure corrupts the library. |

**Risks of (a), mitigated:**
- A power cut mid-write gives a short or empty file → CRC or size check fails → ignored at the next boot
  (BUNDLES.BIN slots). A tiny FAT risk, the same class as any image write.
- A locked or full card → fopen or fwrite fails → the pick still holds in RAM until power-off. **One attempt
  per change**: no retry on every press.
- Half-press latency: one write after a change. If FILECLBK is busy flushing a burst, HLS_EVENT blocks until
  it is served [I]. That is a delay, not a deadlock, by the same reasoning as SD_BUNDLES_V2 §5. The appevent
  queue coupling risk is unchanged in kind.
- A card swap: SLOTS.BIN carries the LOOKS.BIN CRC, so a map written for another library is ignored.
- Fixed path `C:\EP7MOD\SLOTS.BIN` in flash. The code can never write any other name (never DCOLYMP/ or E142*).
- Buffer: the 20-B image lives in the uncached heap block L, not on the cached stack (in case the FS DMAs
  from the caller's buffer [?]).

## 5. Loader change (question 3)

Keep loader v3 `--names`, the accessor and all readers as they are (camera-proven). Add:

1. **sd_hook** (sec 3, about +17 B; 865 → about 882 of 896 B): `bne sd_back` → `bne sd_pk`. After the gate:
   `if 1 ≤ h ≤ lim: call pk_press` (sec 9). The call runs only with a valid handle, and a valid handle means the
   9-section gate has already passed, so section 9 is loaded. A default build stays byte-identical (empty slot).
2. **pk_press** (sec 9, about 700 B):
   - decode P as tbl_idx does, plus a check for `EP7B`;
   - w = (P+676): 0 → pk_load (once per power-on; writes 1 first); 1 → done; otherwise validate L (inside the
     pool for 2048 B, 4-aligned, `EP7L` at L+1408);
   - v = property(0xecf9) low byte (sign-extended). If v ≠ baseline: baseline = v, j = 10 − v ∈ 0..20,
     k = active slot. Apply (j < n and mask allows, or j = 20 → stock), then pk_save.
3. **pk_load:** malloc(2048) → L (inside the pool, aligned, else free) → fopen LOOKS.BIN → fseek END/ftell:
   size = 64 + 64n, 1 ≤ n ≤ 20 → fseek SET → fread → fclose → **pk_check**:
   - header: magic, version 3, 64, 1100, payload, SHA prefix, n, 64, layout_crc, zero bytes;
   - CRC with the v1 rule, reusing `sd_crc`;
   - per record: bytes 0..44 against `sd_lo`/`sd_span` (the loader's own range tables), class/mask/reserved,
     and the name rule (as `sd_names`, non-empty).

   Then state: baseline = property(0xecf9), assign[8] = 0xFE (untouched). Then SLOTS.BIN: fopen → fread 20 →
   fclose. If its magic, LOOKS CRC binding and CRC are good, apply each valid assign. Write `EP7L` last, then
   P+676 = L.
4. **pk_apply(k, j)** = P(look, slot) exactly as `tools/ep7_library.place()`:
   - copy bytes 0..44 and zero 45..63;
   - COLOR: +33..44 = 0, +32 = 0, +31 = 2;
   - MONO with a colour look: +32 = 1, +31 = 3; MONO with a mono look: +31 = 0;
   - copy the name to P+544+16k, then `EP7N` at P+672;
   - j = stock: zero the entry and the name.

   Stores go only into P and L (heap).
5. **Label hooks v2:** the test-8 body plus the 652-list route and the 1456-title route (above). The P/L checks
   are duplicated per route (still no stack, no calls) and land in two copies of about 300 B. They move from
   0x61242d10/0x61242e10 to the **sec-5 tail** (proposed 0x60b9dd10–0x60b9dff0); the sec-6 markers at
   0x61242e00 and the 40 entry edits stay.

**Heap layout of L (2048 B):** +0 LOOKS.BIN (≤ 1344 B), +1408 `EP7L`, +1412 n, +1414 baseline,
+1416 assign[8], +1424 LOOKS CRC, +1440 SLOTS image (20 B).

**Card files** (desktop: `tools/ep7_looks_bin.py`, written during this session, offline only):
- `LOOKS.BIN` v3: 64-B header (v1-family CRC rule) + 64-B records (bundle 0..44, class, mask, 0, name[16]).
- `SLOTS.BIN`: `EP7S`, LOOKS CRC, assign[8] (look / 0xFF stock / 0xFE untouched), CRC-32.

`library_v1.json` → 1280 B, 19 looks. `--check` mirrors the camera rules. BUNDLES.BIN (544 or 680 B) is still
required: it creates P.

## 6. Sites and code space (proposed; none built)

| What | Where | Size |
|---|---|---|
| sd_hook branch + pk call | 0x605b7400 loader (sec 3) | +≈17 B (fits 896) |
| pk_press/load/check/apply/save + paths "LOOKS.BIN", "SLOTS.BIN", "w" | sec 9 0x6143a410–0x6143a7f0 | ≈700 B |
| label hooks v2 + "Film Sim", "Stock", "--" | sec 5 0x60b9dd10–0x60b9dff0 (sites 0x60df255f/25dc retargeted) | ≈2×300 B |
| services used | malloc 0x60022782, free 0x600227b4, fopen 0x60634fbc, fclose 0x60634fc5, fread 0x6063514b, **fwrite 0x60635041**, ftell 0x606351d9, fseek 0x60635243, property 0x6005e971 | — |
| runtime stores | P (table, names, `EP7N`, +676), L, 0x622cbcc2 (unchanged) | heap/.bss only |

Before claiming for real: re-run `tools/ep7_code_space.py` on both tails and check them against the look-editor
agent's claims.

## 7. Phases and emulator gate

| Phase | Content | Emulator exit check |
|---|---|---|
| 3a | Loader branch + pk_load/apply (LOOKS + SLOTS read) + label hooks v2; **no fwrite** (picks are RAM only) | v3 suite unchanged on the new loader (pk stubbed); pk: every LOOKS/SLOTS reject case; P() == `place()` for every look × slot; stores only into P/L; film-menu L over all 44,703 sources with picker states (only 42 list sources + id-1456 titles change) |
| 3b | + pk_save (fwrite) | the call sequence fopen("w") → fwrite(L+1440,1,20) → fclose exactly once per change, never on an unchanged press; the image == `make_slots()` |
| 3c | Decouple the mic level (trace the 652 audio consumer) or the H2 host | — |

## 8. Alternatives kept

- **H2 intercepted host:** hook the get/set of one setting so that its stock storage never changes and the
  picker state lives only in the heap. That keeps the mic level, but needs a trace of the menu commit path
  (the per-sid registry objects at 0x60433408…: +24 is an on-change callback, e.g. 0x602b536b for sid 47 [V])
  and validator list relocation.
- **Class-2 block for > 20 looks:** pool [0xa1dd8d40, 0xa1e85800); one 16-KiB leak; headroom unknown.

## 9. Camera test plan (each a separate flash, restore package ready)

| Step | Build / card | Expect | Fail action |
|---|---|---|---|
| 0 | **Stock or v0.6 firmware**, no flash | Recording Volume can be edited in stills mode (Menu → Video tab); note its default | if hidden in stills mode, redesign the host |
| 1 | 3a build, card without EP7MOD | Every menu stock (incl. Recording Volume +10..−10), 5 power cycles, shoot, one movie | crash → reflash v0.6 |
| 2 | + BUNDLES.BIN (test 8 card) only | as test 8 (names after half-press); Recording Volume stock | — |
| 3 | + LOOKS.BIN | after the 1st half-press: "Film Sim" + 19 names + "Stock"; pick Velvia on COLOR2, half-press → COLOR2 label "Velvia", the picture looks like Velvia; power-cycle → back to BUNDLES look (RAM only) | remove LOOKS.BIN → stock picker |
| 4 | 3b build | as 3; after the pick+half-press, SLOTS.BIN (20 B) on the card; power-cycle → COLOR2 still Velvia; `ep7_looks_bin.py --check --slots-file` OK | delete SLOTS.BIN |
| 5 | Card locked; corrupt SLOTS.BIN; another card's SLOTS.BIN | the pick still works in RAM; file ignored; ignored | — |
| 6 | Movie test | the mic level follows the pick (known limit); note how the audio sounds | phase 3c |

Every failure after step 1 is card-gated: removing LOOKS.BIN/SLOTS.BIN restores the v0.6 behaviour.

## 10. v2 entry point (replaces the Recording Volume UI)

Design only, same rules as above: nothing built, no camera, no `E142*`, no commit, no runtime store into
0x60020020–0x6191ffe0. Requirement: **no other camera function changes behaviour**, with or without a card.

Mock: `docs/img/ui_look_picker_v2.jpg` (`sim/screens/look_picker_v2.json`). The title name is the only part v2a
draws; the counter and look strip are an optional later overlay.

![look picker v2 mock](img/ui_look_picker_v2.jpg)

### 10.1 New verified facts (this session)

- **Editor controller records** [V]: table 0x6118474c, 167 × 56 B, scanned by init 0x60e206a0/0x60e207f7. The record
  starts at its key (LOOK_EDITOR §1.1 quotes the addresses 12 B late). Layout: `+0 key, +4 init, +8 child_get,
  +12..+52 = 11 handler words`. Init copies each **non-zero** word into editor object +48..+88. Zero words keep
  the defaults copied first from .data 0x61fc3810 (init image 0x6025bad0).
  COLOR records: 0x13b3 @ **0x61185bdc**, 0x13b4 @ **0x61185c14**, 0x13b5 @ **0x61185c4c**, 0x140c @ **0x61185c84**;
  in all four, +36 = 0x60e22191 and +48 = +52 = 0.
- **Event → slot routing** [V], editor vtable 0x61187540, slot 0x60e20cdc: `0x900c` → obj+76 (record +40, OK),
  `0x9014` → obj+80 (record +44), `0x9015` → obj+84 (record +48), `0x9012` → obj+88 (record +52), **every other
  event** → obj+72 (record +36 = 0x60e22191).
- **0x9014 = INFO press** [V]: its handler 0x60e22579 logs `"INFO pUcColorInfo.cc2SetType=%d"` and toggles ALL
  (settings 1098/1099…, bound checks 0x60e230e0/0x60e231e0). The key table 0x6113e938 (`{index, event}`) has
  press/long/release triples; INFO is the pair 0x25 → 0x9014 / 0x26 → 0x9015 (no long press). **0x9015 is the INFO
  release** [I strong]. Its default handler 0x60e228e9 and the 0x9012 default 0x60e228fb are `clr d0; retf`.
- **Delete (0x9016) does nothing in the stock COLOR editor** [V for this chain]. Delete is triple 0x27/0x28/0x29 =
  0x9016 / 0x9042 (long) / 0x9017. 0x60e22191 tests only 0x900d, 0x903e, 0x900e, 0x972b and 0xf855, then hands
  every other event to the generic 0x60e21fa6. That handler tests 0x971d, 0x9749, 0xf805, 0x972b, 0x900e, 0x9305,
  0x9a51 and 0x9ac6, and **never 0x9016**. [?] Whether the outer screen FSM delivers 0x9016 to the editor at all
  (the key-repeat translator 0x60d1a6a0 does map logical key 10 → 0x9016).
- On-screen guide symbols [V, OSD sheet]: @A015@ MENU, @A016@ OK, @A017@ INFO.

### 10.2 Options

| # | Entry point | Sites / evidence | What the user sees | Effort | Risk / other functions changed |
|---|---|---|---|---|---|
| **a** | **Color Profile editor: Delete = next look for this slot** | 4 data words (record +36 at 0x61185c00/…c38/…c70/…ca8) → `pk_evt`. pk_evt: `d0 == 0x9016` ∧ L valid → step; else `jmp 0x60e22191` (exact replay: same a0/d0/d1, no stack) | COLOR1–4 editor opens as stock. Delete steps through the LOOKS.BIN looks, wrapping through "Stock". The slot name updates in Picture Mode, LC and SCP (test-8 hooks); in the editor title only if its label source is marked [?] | Low: data hook, no FSM globals; ~120 B plus the existing §5 core; label hooks stay as built | **None in stock** (Delete is a no-op there [V chain]); no card → pure replay. Open: Delete delivery [?], in-editor redraw [?]. Clashes with LOOK_EDITOR's planned Delete = S/L/H (see 10.4) |
| a′ | Same editor, **INFO release (0x9015)** or **0x9012** via the empty record slots +48/+52 | Pure data: fill +48 or +52 (no replay needed; stock is `return 0`) | An INFO *release* would fire after every INFO press, so ALL toggles **and** the look steps. 0x9012's physical key is unknown | Lowest | 0x9015 couples to the stock INFO/ALL behaviour, so it fails the requirement. 0x9012 is a fallback, only once its key is identified (and it must not be MENU/PLAY/movie) |
| a″ | Same editor, a dial | Dial handlers 0x60e21cae/0x60e21efb are used (sector/value, setting 170) | — | — | Changes stock dial behaviour. Rejected |
| b | Picture Mode list / LC: INFO or long-press on a COLOR/MONO entry | INFO has **no long-press event** [V key table]. INFO/→ on a profile entry already opens the profile editor (stock function). OK-long (0x903e) in the list is unmapped. The list FSM is not mapped | A sub-list of looks over the Picture Mode list | High: list FSM, new popup | Overloads a stock key (INFO) or relies on unmapped long-press handling. Rejected for now |
| c | A truly dead menu item | The 652 scan (§2) found no other ≥ 20-option list without a stills effect. A dead item would need (1) to be **visible** on the E-P7 (model-irrelevant items are hidden by condition records), (2) every getter traced: by ID 0x602cbc0a, by key 0x6005e971 (Image Aspect alone has 18 key sites), facade, bank save/restore, OI.Share property dump | A relabelled item, like v1 | High (tracing), and proof by absence | Fails safe only if the proof is complete. Unhiding a hidden item edits condition data. Not pursued |
| d | New option list / menu page from the stock machinery | Needs a setting ID with storage, validator, default and setter, or the §8 H2 intercepted host (registry +24 callback, list relocation) | A real "Film Sim" menu item | Highest | The most unknowns; persists in internal settings (REVIEW_v03 H3 class). Later, if ever |

**Recommendation: (a).** It is the only option whose hooked key is unused in stock *and* whose hook is pure data. The
slot is the editor's own profile: object +100 key 0x13b3/0x13b4/0x13b5/0x140c → slot 0/1/2/3. That fixes v1 limits
1–2 (no "active slot at half-press", and the same look can go to any slot) and removes limit 4 (mic level).

### 10.3 v2 design

- **Data hook (build time, sec 6):** record +36 of the four COLOR records: `0x60e22191 → pk_evt`. Other records
  (Color Creator 0x13a9, the rest of the 167) stay stock.
- **pk_evt** (sec 9 with the §5 core, about 120 B, frame like 0x60e22191: entered by `calls (a1)` from
  0x60e20d1b with a0 = editor, d0 = event, d1 = arg):
  1. `d0 ≠ 0x9016` → `jmp 0x60e22191` (first instruction, no register touched).
  2. Decode h/P as `tbl_idx` plus `EP7B`; read L from P+676 and check `EP7L` (§5 step 2). Any failure → replay.
  3. k = slot from `movhu (100,a0)`. Any other key → replay.
  4. j = next index after assign[k] that is allowed for a COLOR slot (mask), wrapping through n = "Stock".
     Then `pk_apply(k, j)` (§5 step 4: P table + name + `EP7N`), assign[k] = j, dirty = 1. Return d0 = 1 (handled).
     Stores go only to P and L (heap).
  5. **Persistence:** unchanged §4(a). The next half-press runs the HLS_EVENT hook, which sees dirty and writes
     SLOTS.BIN (fwrite). Phase v2a stays RAM-only, as 3a.
- **Loader:** §5 items 1–4 as designed, minus everything about 652 (no baseline, no property 0xecf9). pk_load still
  runs on the first half-press, so Delete does nothing until then. That is the same timing as the names.
- **Labels:** the test-8 hookA/hookB stay at 0x61242d10/0x61242e10 unchanged. The §5 item 5 "v2 hooks" (652 list
  + id-1456 title routes) and the sec-5 relocation are **dropped**, so the sec-5 claim 0x60b9dd00–0x60b9e000 can be
  released.
  - **In-editor feedback** [?]: the editor's "Color Profile n" title is drawn from a label source not yet identified.
    Candidates are the deferred lists 0x611df788 and the bare sources 0x611c1b44/0x611cf2b0 (FILM_LIBRARY §8.7).
    If it goes through builder A/B, marking it (one data word per slot) shows the name with no new code. It
    refreshes only when the screen redraws; the viewer redraw call is unmapped (LOOK_EDITOR §1.5).
  - Fallback feedback: exit with OK, and the Picture Mode list, LC and SCP show the new name (proven path).
- **No card / no LOOKS.BIN / before the first half-press:** pk_evt replays, so the editor is byte-for-byte stock.
- **MONO slots:** not covered. The Color Profile editor is COLOR-only. MONO needs the Monochrome Profile screen's own
  record (unmapped) or stays on BUNDLES.BIN.

### 10.4 Interaction with the look editor (LOOK_EDITOR.md)

LOOK_EDITOR H4 plans Delete = S → L → H at the FSM dispatcher 0x60d1145e, and that hook needs unmapped globals.
Both can't own Delete. Proposal: **one record-level handler** (`pk_evt` grows into `ed_evt`) owns Delete for both,
using the same data hook and a0 = parent (which also solves LOOK_EDITOR §1.5 "current-editor holder").
- Without the editor build: Delete = next look.
- With it: the axis tab gets one extra position, Delete cycles **Look → S → L → H**, and in the Look tab the dials
  step the look instead of a sector [design decision for later].

Delete-long (0x9042) is an alternative axis key once its delivery is checked.

### 10.5 Gates

| Gate | Check |
|---|---|
| Emulator E1 | Run 0x60e20cdc with every event in 0x9000–0x9fff and 0xf800–0xf8ff on a real editor object (init 0x60e20a54 path), on stock and patched images, in each state (h = 0, no `EP7L`, valid L). Registers, object and memory must be identical except for 0x9016 with a valid L |
| Emulator E2 | 0x9016 with a valid L: P/L stores only, P() == `ep7_library.place()` for every look × COLOR slot, the wrap and mask order, the dirty flag |
| Emulator E3 | Trace the outer screen FSM from the key translator to see whether 0x9016 reaches 0x60e20cdc while a COLOR editor is open (removes the main [?]) |
| Camera C0 | **Stock/v0.6 firmware, no flash:** open COLOR1, press Delete, INFO, OK-hold and the dials; note that Delete does nothing visible |
| Camera C1 | v2a build, no card: the editor and every other screen are stock; Delete is still a no-op |
| Camera C2 | + BUNDLES.BIN + LOOKS.BIN, half-press, open COLOR2, Delete ×3, OK → the Picture Mode list shows the third look's name, and the JPEG looks like it; power-cycle → back (RAM only) |

Every failure after C1 is card-gated: remove LOOKS.BIN to get v0.6 behaviour back.
