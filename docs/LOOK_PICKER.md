# On-camera Film Sim picker (phase 3): design

Design only. No firmware patch was built, no camera was contacted, no `E142*` file was written, nothing was
committed. Base: `releases/test8-filmmenu` (v0.6): loader v3 `--names`, label hooks, accessor, heap block P
published as handle h at 0x622cbcc2. Hard rule kept: **no runtime store into 0x60020020–0x6191ffe0**.
[V] = read from the decoded main (`tools/dis.sh`, byte dumps). [I] = inference. [?] = open; camera or trace needed.

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
