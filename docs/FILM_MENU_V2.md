# Film-sims menu v2: pick any library look on the camera (E-P7 1.1)

Design only. Nothing was built, no camera was contacted, no `E142*` file was written, nothing was committed.
Base: v0.6 (test 8: card names on COLOR1–4) plus the look editor line (test 12b camera-proven Movie key; 12c
in progress in `patches/look_editor/*`, which this design does **not** edit). Rule kept: **no runtime store into
0x60020020–0x6191ffe0**.

[V] = read from the decoded main this session (`tools/dis.sh`, `tools/ep7_xref.py`, byte dumps). [I] = inference.
[?] = open; needs the camera or a trace. Confidence: **H** high, **M** medium, **L** low.

## 1. Answer

**Recommended route: a fourth "Film" stop in the Color Profile editor's Movie cycle (option b, refined).**

- Movie already cycles the editor S → L → H (12b). It becomes S → L → H → **F**, but only when a valid
  `EP7MOD/LOOKS.BIN` is loaded.
- On the F stop, the value dial, the arrows and touch-drag (every Up/Down path) step through the library looks
  for **this editor's slot**: COLOR1–4, with wrap-around through "Stock" and the slot's own original look.
- The guide label (12c `ed_guide`) shows `[F] Velvia`. When you leave, the Picture Mode list, LC and SCP show the
  name through the test-8 label hooks, which are camera-proven.
- A pick writes the 64-B slot entry and the 16-B name into the loader's heap block P, then sets 12c's dirty byte.
  12c's save on the next half-press writes them into `BUNDLES.BIN`. **Persistence needs no new file and no new
  write code.** `LOOKS.BIN` is only ever read on the camera.
- Steps reach the camera through a **pure data hook**: the Up/Down words (+12/+16) of the four COLOR editor
  records. 12c does not touch these words. On any guard failure the stock handler runs with all registers intact.

Why not the others, in short:
- **(a) A dedicated list:** every stock list screen lists a *setting's* allowed values and looks up each label
  by value (§3). A 19-entry list therefore needs a host setting with at least 20 values whose storage we own.
  The only such setting is Recording Volume, which the user has rejected. Intercepting its get/set would go
  through the facade words that 12c already hooks. So this is the most expensive option, and it is not
  independent of 12c either.
- **(b) as first designed (Delete/INFO):** Delete never reaches the editor (test 12). INFO toggles ALL, a stock
  function. Movie is the only free key, and 12b already uses it, so the picker has to *share* the Movie cycle.

**No phase was built into `patches/film_menu_v2/`.** Every usable trigger is in a 12c-owned file: the Movie
cycle (`ed_event`), the label feedback (`ed_guide`), the screen refresh (`ed_poke`), and the HLS_EVENT
half-press chain (`ed_trig` at `sd_back` 0x605b7420). A film-only build would therefore be dead code, or it
would collide with 12c on record +52 and the view-part word. The film-owned part, which is the sec-9 core plus
the 8 record words, is specified in §4 so that it can be built as **12d** once 12c passes on the camera (§7).

## 2. New verified facts

| # | Fact | Evidence |
|---|---|---|
| 1 | COLOR editor records (56 B, start at key): 0x61185bdc (0x13b3), 0x61185c14 (0x13b4), 0x61185c4c (0x13b5), 0x61185c84 (0x140c). Word +12 = Up 0x60e20e0a, +16 = Down 0x60e2107a, identical in all four | byte dump [V] |
| 2 | Init copies record +12..+52 to parent +48..+88, so Up goes to parent+48 and Down to parent+52 | router 0x60e20cdc uses +72..+88 for record +36..+52 [V]; offsets are consistent with LOOK_PICKER §10.1 |
| 3 | **Every value step goes through parent+48/+52.** Helper 0x60e20bd5 does `mov (48,a2),a1; calls (a1)` with event 0x9004, and 0x60e20bfd does `(52,a2)` with 0x9006. Each helper has 17 call16 sites: the dial handler 0x60e21cae (once per dial notch, delta from 0x60ea3b35), the touch handler 0x60e22e18…e85, and others. After a return of 1, the helper restarts the parent refresh timer (+108, 500 ms) | dis [V], xref [V] |
| 4 | 0x60e20e0a and 0x60e2107a are referenced **only as data** (the 5 records at 0x61185bb0…c90, plus 0x61186400/0x61186438 = two other editors that stay stock). Nothing calls them directly | xref [V] |
| 5 | Up re-reads picture mode (setting 111 via facade +8) and acts only for 54/55/56/64 | dis 0x60e20e21 [V] |
| 6 | The Picture Mode label list is a **value→label table**, not a screen list: 0x611686d4, 72 × 12 B (values 7, 0, 1, 2, 5, 3, 6, 20, 28, 21, 54…). It is referenced only from a 52-B descriptor table (0x6116b3f0 / 0x6116b424, with 0x611682a8 = 74 icon entries and 0x61168638 = 13 entries (values 6913…)). No code references it by address | rng scan + dump [V] |
| 7 | Free space: sec 9 0x6143a350–0x6143a800 is all FF (proposed picker-v1 claim 0x6143a400–a800, **unbuilt**); sec 5 0x60b9de80–0x60b9e000 is all FF (left over after 12c's ed_view claim) | dump [V] |
| 8 | Loader v3 `--names` helpers: `sd_crc` 0x605b7615 (CRC-32 reflected, d0 running, a0 data, d1 len), `sd_lo` 0x605b76e1 / `sd_span` 0x605b7721 (64-B per-byte range tables). These addresses are internal to that build, so the film core keeps **its own copies** | generated/film_menu/sdv3/symbols.json [V] |
| 9 | 12c save (`ed_save`) copies P[0..679] and writes 680 B (with names) when P+672 = `EP7N`, else 544 B. Order: .NEW (read back) → .BAK → .BIN (read back) | patches/look_editor/ed_ui.s.in (read only) [V] |
| 10 | 12c `ed_guide` leaves the stock label for axis byte ≥ 3, and `ed_get`/`ed_set` act only for axis 1/2. **Axis 3 is therefore already inert in 12c**: S values on the wheel, S edits, stock label | 12c sources (read only) [V] |

## 3. Options (with addresses)

| Option | What it needs | Cost / risk | Verdict |
|---|---|---|---|
| **a1** Dedicated list from a stock list screen | A host setting with ≥ 20 validator values (validator 0x604cc98c), a visible menu item, the facade get/set intercepted for that id (0x60acb0e4 / 0x607fa355, **12c-owned**) and the list labels relabelled through builders A/B | Only setting 652 (Recording Volume) qualifies (LOOK_PICKER §2), and the user rejected it. Intercepting it keeps the mic level but hides the item while a card is in. It shares 12c hook sites. **M** effort, **L** acceptance | Rejected |
| a2 | A new menu page/item (page record e.g. 0x6117b1b4) with its own setting id | New id storage, defaults, validator entries, persistence in internal settings (REVIEW_v03 H3 class) | Rejected (highest unknowns) |
| a3 | Extra Picture Mode entries (duplicate value 54 ×19) | The list is a value→label table (fact 6), and the screen enumerates values, so duplicate values cannot be told apart | Infeasible |
| **b1** **F stop in the editor's Movie cycle; Up/Down step looks** | 8 record words (fact 1) + sec-9 core + 4 small 12c changes (§4.3) | Data hook, exact replay, stores to the heap only, persistence via 12c's save. Depends on 12c's camera result (redraw) | **Chosen** |
| b2 | Movie toggles a separate film mode (no editor axis) | Same as b1, but needs record +52 and the view-part word, which collide with 12c | Only if the look editor is dropped |
| c1 | Movie in the Picture Mode list steps the highlighted COLOR row's look | List-screen FSM, event routing and the highlighted entry are all unmapped | Later research (§7 F4) |
| c2 | LOOKS.BIN appended to BUNDLES.BIN | Loader v3 accepts only 544/680 B, so a longer file loads nothing. 12c's save would also truncate it | Rejected |

## 4. Design b1

### 4.1 Hooks (flash data, build time)

| # | Site (word) | Stock | New | Conf. |
|---|---|---|---|---|
| F1–F4 | COLOR1–4 record +12: **0x61185be8, 0x61185c20, 0x61185c58, 0x61185c90** | 0x60e20e0a | `fm_up` | H (facts 1–4) |
| F5–F8 | COLOR1–4 record +16: **0x61185bec, 0x61185c24, 0x61185c5c, 0x61185c94** | 0x60e2107a | `fm_down` | H |
| — | Records 0x61185bb0 (Color Creator), 0x61186400, 0x61186438 | stock | untouched | — |

`fm_up` / `fm_down` (CALLS entry, as the stock handlers: a0 = parent, d0 = 0x9004 / 0x9006, d1 = 0):
1. Guard, using no register before it is saved:
   - P valid (same decode as `tbl_idx`: h at 0x622cbcc2, 1 ≤ h ≤ 0xa941, (h−1) % 4 == 0, `EP7B`);
   - P+680 = `EP7E` and axis P+684 == 3;
   - film handle valid (§4.2);
   - parent key u16 (100,a0) ∈ {0x13b3, 0x13b4, 0x13b5, 0x140c}, giving k = 0..3.
   - On any failure, restore everything and `jmp 0x60e20e0a` / `0x60e2107a`.
2. Step: `cur[k] = next/prev(cur[k])` over the order [own, look 0..n−1 with mask bit0, Stock]. Mono looks are
   skipped, because COLOR slots cannot render mono.
3. Apply to the slot (heap only):
   - clear flags P+32+64k+31 first (the slot renders stock while it is half-written);
   - write bytes 0..30 and 32..63 = P(look, COLOR) (`ep7_looks_bin.place()`: bytes 0..44, +32 = 0,
     +33..44 = 0, 45..63 = 0);
   - write the flags byte (2) last;
   - write the name to P+544+16k;
   - if P+672 ≠ `EP7N`, first zero P+544..671 (already zero after a 544-B load), then write the name, then
     `EP7N`;
   - "Stock" = a zero entry and an empty name; "own" = the snapshot taken at the first step for this slot.
4. Set dirty P+685 = 1 (12c's byte; its save runs on the next half-press).
5. Refresh: re-write the cursor setting (1091/1096/1097/1686) with its own value through the facade, as 12c's
   `ed_poke` does, so that the view rebuilds and `ed_guide` redraws. Return d0 = 1, so the helper restarts the
   refresh timer as stock does.

Stores: P, L and the stack only. No mul/div, no setlb.

### 4.2 Library load and state (HLS_EVENT, first half-press)

`fm_load` is called from 12c's `ed_trig` (change E3) after P is valid. It runs once per power-on and uses the
camera-proven fopen context (test 7b/8):
- Mark the attempt first: P+1020 = `EP7X`.
- `malloc(2048)` → L (inside the class-1 pool 0xa1f8d800..0xa1f98540, 4-aligned, else free).
- fopen `C:\EP7MOD\LOOKS.BIN` "r" → fseek END / ftell: size = 64 + 64n with 1 ≤ n ≤ 20 → fseek SET → fread →
  fclose.
- Services [V, LOOK_PICKER §6]: malloc 0x60022782, free 0x600227b4, fopen 0x60634fbc, fclose 0x60634fc5,
  fread 0x6063514b, ftell 0x606351d9, fseek 0x60635243.
- `fm_check` mirrors `tools/ep7_looks_bin.py --check`:
  - header: `EP7B`, version 3, 64, 1100, payload, SHA prefix, n, 64, layout_crc, zero bytes;
  - CRC with the v1 rule (own CRC copy);
  - per record: bytes 0..44 against own copies of `sd_lo`/`sd_span`; class/mask/reserved; name 1..15 bytes
    of 0x20..0x7e, no `@`, NUL-padded.
- Initial cur[k]: the look whose name equals P+544+16k (16-B compare), else "own". So after a saved pick, the
  next power-on resumes on the same look.
- Publish: L+1408 `EP7L`, L+1412 = P (back-pointer); then P+1016 = L; then P+1020 = `EP7F` (last). On any
  failure: free L, and P+1020 stays `EP7X`.
- Handle check (in every reader): P+1020 == `EP7F` ∧ L inside the pool and aligned ∧ L+1408 == `EP7L` ∧
  L+1412 == P. P+1016..1023 lie past everything the loader and 12c use (loader: ≤ +815 including the name
  staging; 12c: +680..686), so stale heap bytes are caught by the triple check.

L layout: +0 LOOKS.BIN (≤ 1344 B), +1408 `EP7L`, +1412 P, +1416 n, +1417 cur[4], +1421 snap flags[4],
+1428 snapshots 4 × 80 B (entry + name), which ends at 1748 < 2048.

### 4.3 Changes to 12c files (owner: the look-editor agent; listed, not made)

| # | File / routine | Change | Size |
|---|---|---|---|
| E1 | `ed_ui.s.in` `ed_event` | Axis cycle S → L → H → F → S when `fm_valid` (else unchanged S → L → H → S). On reaching F, call `fm_enter(k)` (snapshot/index) | ~20 B |
| E2 | `ed_view.s.in` `ed_guide` | Axis 3: kind-5 text `[F] ` + the slot name (P+544+16k), or "Stock" / "Own", ≤ 19 characters (33-unit buffer). Today axis ≥ 3 → stock label, so without E2, F works blind | ~40 B |
| E3 | `ed_core.s.in` `ed_trig` | `call fm_load` when P is valid and P+1020 ∉ {`EP7F`, `EP7X`}, before the save branch | ~15 B |
| E4 | (none) | `ed_get`/`ed_set` need no change: axis 3 is S for them (fact 10) | 0 |

### 4.4 Code space (claim when built; not entered in CODE_SPACE_MAP.md, which another agent is editing)

| What | Where | Size |
|---|---|---|
| fm_up, fm_down, fm_step, fm_apply, fm_enter, fm_valid, fm_name, poke | sec 9 **0x6143a410–0x6143a7f0** (FF [V]; the picker-v1 proposed claim, reused). Guards 0x6143a400–a410 and a7f0–a800. 0x6143a350–a400 stays free (`cmp 0x6143a350,a0` bound at 0x613feff6) | ≈ 600 B |
| fm_load, fm_check, own crc + range tables + path | same range, or sec 5 0x60b9de80–0x60b9e000 (FF [V]) if it overflows | ≈ 400 B |

Sec 9 is reached only after P is valid, which implies that the loader's 9-section gate has passed, so the
section is loaded (LOOK_PICKER §5 reasoning).

## 5. Behaviour

| Situation | Result |
|---|---|
| No card / no EP7MOD / before the first half-press | No P: `fm_up`/`fm_down` replay; the editor is exactly 12c (stock without P) |
| BUNDLES.BIN only, or a bad LOOKS.BIN | No `EP7F`: Movie cycles S → L → H as 12c; Up/Down replay |
| Valid LOOKS.BIN | 4th Movie stop. Dial steps through the 16 colour looks + Stock + Own; names in the guide label; the JPEG uses the look on the next shot |
| Half-press after a pick | 12c save writes BUNDLES.BIN (680 B, with the new entry + name) via .NEW/.BAK. Power cycle → same look and name; F resumes on it (name match) |
| LOOKS.BIN removed later | The saved pick stays (it lives in BUNDLES.BIN); the F stop disappears |
| Card removed after load | The heap copy works until power-off; the save fails (12c status byte); nothing persists |
| Write-protected card | As 12c: RAM pick, one save attempt per change |
| MONO1–4 | Not covered (the Color Profile editor is COLOR-only). Mono looks are skipped |

**LV refresh.** Bundle hue/light do not show in live view on any build (LOOK_EDITOR §4 item 3; v0.2 residual
risk). They show in the JPEG. Grain, bloom and clarity are capture-only. A WB-shift override is read at LV
start (WB_PATCH: 4 LV-start sites), so a picked look's WB appears after the LV restarts (leaving the menu)
[I]. The cursor-setting re-write also runs the stock picture-mode refresh 0x602ccfcb/0x602cd045 through the
settings manager [V, LOOK_EDITOR §1.3], which may restart it sooner [?].

**Saturation, tone and contrast** in LIBRARY_V1 are advice (the user's stock settings), and P() drops sat.
Optional F2 below writes the look's sat[12] to the stock sector settings through the facade.

## 6. Risks

1. [?] **Redraw after a step** relies on the same cursor re-write as 12c's `ed_poke`, which is not yet proven
   on the camera. If the screen does not redraw, the pick still applies and Picture Mode shows it; only the
   in-editor feedback lags. This is why F is gated on 12c's camera result.
2. [V/I] **Card writes.** No new write code, but every pick leads to a BUNDLES.BIN rewrite, so the test-11 FAT
   corruption question applies to 12c and therefore here. Keep a spare card. `.BAK` keeps the previous file.
3. [I] **Heap.** One more persistent 2048-B class-1 block (P, L: 2 of about 21) plus 12c's temporary save
   block. Pool headroom is unknown, but malloc failure is handled (no F stop).
4. [I] **Second fopen on the first half-press** (LOOKS.BIN after BUNDLES.BIN) adds one short read to that
   press. This is the same class as test 7b/8.
5. [I] **Torn slot during a capture:** flags are cleared first and set last, so a racing capture renders stock
   or the complete look. The readers range-check every byte anyway.
6. [?] **Touch / OK-hold in the F stop.** Touch-drag goes through Up/Down (fact 3), so it steps looks.
   OK-hold reset (0x903e, routed to 12c's +36) still resets *saturation*. Document this, or have 12c ignore
   0x903e on axis 3.
7. [?] **Label width:** `[F] CineStill800` is 16 characters. The bottom-left guide area's visible width is
   unmeasured; names are ≤ 12 characters.
8. **Mono looks** can't be picked (no MONO editor mapped). **Names collide** if two library looks share a
   name (`ep7_looks_bin` already rejects duplicates).

## 7. Phased plan

| Phase | Content | Exit gate |
|---|---|---|
| F0 | Wait for 12c camera result (Movie cycle redraw, `ed_poke`, save on half-press, card health) | 12c PASS on the camera |
| F1 (= 12d) | `patches/film_menu_v2/`: fm core (§4.1–4.2) + F1–F8 record words; look-editor agent adds E1–E3. Card: BUNDLES.BIN (test 8) + LOOKS.BIN (`tools/ep7_looks_bin.py bundles/library_v1.json`) | Emulator: **G1** each record, 0x9004/0x9006 via the helpers 0x60e20bd5/0x60e20bfd on a real parent built by init, states {no P, no `EP7E`, axis 0/1/2, no `EP7F`, stale `EP7F` with a bad L, valid}: all non-valid states byte-identical to stock (registers, parent, memory); **G2** a full wrap in both directions on 4 slots: slot entry == `place()` for all 16 colour looks, mono skipped, stores only to P/L/stack with the image mapped read-only; **G3** fm_load: every `--check` reject case (CRC, sizes 0/63/65/1408, n 0/21, name rules, ranges, layout_crc) → no `EP7F`, L freed; **G4** pick → 12c ed_save → the file passes `ep7_bundles_bin.py --check` and reloads through the real loader with the same entry + name, and F resumes on it; **G5** guide text for axis 3; mutation set |
| F1 camera | C1 no card: editor = 12c. C2 BUNDLES only: 3 stops. C3 + LOOKS.BIN, half-press: 4th stop `[F] …`, dial cycles, OK → Picture Mode name, shot shows the look. C4 half-press → BUNDLES.NEW/.BAK/.BIN on the PC; power cycle → kept. C5 corrupt LOOKS.BIN → 3 stops. C6 remove LOOKS.BIN → the saved look stays | Each failure after C1 is card-gated (remove LOOKS.BIN) |
| F2 (optional) | On a pick, also write the look's sat[12] (L record +33..44) to the stock sector settings through facade SetValue, as an S edit. User choice: it overwrites their own saturation | G: 12 SetValue calls, ids per slot, values −5..5 |
| F3 | MONO slots: map the Monochrome Profile screen's controller record | trace |
| F4 | Research: Movie in the Picture Mode list (c1), so a pick is possible without opening the editor | list-FSM trace |

## 8. As built (test12e, emulator-verified, not camera-tested)

`patches/film_menu_v2/` (build.py, fm_ui.s.in, fm_core.s.in, verify.py), a layer over the 12e editor + extras.
- The F stop is page 3 in the editor's MENU/PLAYBACK page cycle (12e `ed_page`, not Movie): S → H → L → F → X.
  E1/E3 are the editor's layer words `ed_cfg_fv` (→ fm_valid, asked on L → next) and `ed_cfg_fl` (→ fm_load,
  called by ed_trig on every half-press with a valid P); E2 is in 12e `ed_guide` ("Film: <name>", ≤16 chars).
- fm_up/fm_down on the record +12/+16 words as §4.1; positions [own, looks, Stock], mono skipped, entry =
  record bytes 0..31 + 32 zero bytes (== `ep7_looks_bin.place()`, checked per look in the verifier), name, EP7N,
  dirty, then the editor's ed_poke. L layout as §4.2 plus staging at L+1752.
- Code: fm_core 845 B in the sec-9 claim 0x6143a410; fm_ui 660 B in the dead EVF step-4 tables 0x601e2c3c
  (1505 B did not fit sec 9 alone).
- Card: `--card` writes LOOKS.BIN with the 16 colour looks of bundles/library_v1.json (1088 B).
- Verified: V 10, U 62, P 11, L 50, H 1, T 4 (patches/film_menu_v2/verify.py). No mutation run (user request).


**test13:** `fm_mod` (in fm_core, 971 B now) answers the editor's `ed_cfg_fm`. It returns 1 when slot k sits on a
library look (pos 1..n) and its entry differs from that look's `place()`: record bytes 0..31, then zeros. Own,
Stock and no LOOKS.BIN give 0. This drives the `*` in the Film label. Verified: part M 50/50 (+ label runs through
ed_guide). LOOKS.BIN is regenerated from library v2 (CineStill800 = red bloom, docs/HALATION_RED.md).
