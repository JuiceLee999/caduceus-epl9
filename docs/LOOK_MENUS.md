# Real list / slider menus for looks and extras (E-P7 1.1): feasibility

Research only. Nothing built, no camera, no `E142*`, no commit; `patches/` and `releases/` untouched.
[V] = read this session with `tools/dis.sh`, `tools/ep7_xref.py` or byte dumps. [C] = earlier camera result.
[I] = inference. [?] = open. Confidence: H / M / L.

Question: can the looks (16–64 card names) and Clarity/Grain/WB-shift get a real vertical list or a slider
instead of the pages in the Color Profile wheel editor (LOOK_EDITOR §6, LOOK_EXTRAS, FILM_MENU_V2 §8)?

## 1. Verdict

**Technically yes, but every working route needs a host menu item, and every host costs something the user
has already said no to. Not worth building now. Keep the editor pages (F / X stops).**

- **Mechanism works [V/M]: "virtual list on a host setting".** List screens get their entries from count and
  value-by-index, and their labels from a value→label list, all through the settings facade (§2). If we answer
  get / set / count / value-by-index / available for one host id from the heap, and relocate that id's label
  list to N marker entries, the list shows N runtime names. Internal storage is never written: the set is
  caught at 0x607fa355, and the host's consumer keeps reading its frozen stored value through 0x602afa81 /
  0x602af887, which bypass the facade.
- **The blocker is the host, not the code.** Every reachable list belongs to a visible item with a stock job
  (§3). 652 Recording Volume was rejected. The other hosts are weaker, or need a visibility filter that has not
  been mapped.
- **If the user accepts giving up one item's UI** (the stock value stays frozen while a card is in), the build
  is route V1 (§4): about 0.6–0.8 KB of code plus about 0.8 KB of data, confidence M.
- **The Picture Mode list (§5), a new menu item (§6) and sliders (§7)** each cost more and are riskier. Not
  recommended.

## 2. How list screens get count, values and labels

| # | Fact | Evidence |
|---|---|---|
| 1 | The facade (`OlyApiSettingControllerController`, singleton getter 0x607f9062, vtable 0x60acb0dc) delegates per method: +0 SetValue 0x607fa129 (the GUI set call at **0x607fa355** sits inside it); +8 GetValue → 0x60826c82; **+20 / +36 available(id,value)** 0x607f9a06 / 0x607f90f9 → 0x60826dde → 0x602af9d1; **+24 count** 0x607f95dc → 0x60826d53 → **0x602af8dc** → 0x602b1776; **+28 value-by-index** 0x607f9912 → 0x60826d5f → **0x602af8a3** (index map) + **0x602af8c1** (value); +152 GetDefault | dis [V] |
| 2 | The stock thunks 0x602af8dc / 0x602af8a3 / 0x602af8c1 have only 3 / 4 / 4 callers: the facade, **0x60886900** (OI.Share remote property list; entry 0x608868e5 ← 0x6097c7d4, Wi-Fi remote module) and **0x60bda9b6..d3** [?, role unknown]. So hooking the 3 thunks for one id would cover every enumerator; hooking the facade words +24/+28 covers the GUI only | xref [V] |
| 3 | **Generic GUI list = `Cursor_Move_Set_Mode_Actuator`.** Initialize 0x60de3540: it looks up the modeId in the per-mode init table 0x61151474 (314 × 8 B `{u16 mode, fn}`). With no per-mode entry it runs the default 0x60de3670: **facade +24** → obj+88 (count), +8 GetValue (current), **+28** per index (0x60de3886, 0x60de3920). The count is forced to 13 for 1091/1096/1097/1686 | dis [V] |
| 4 | Other actuators use the same pattern. Example: `AF_Target_Actuator` 0x60dd5dfe (vtable 0x61140490 slot): +24 → obj+56, malloc(count·4), +28 fills the array, +8 locates the cursor. About 40 facade +24 sites and 50 +28 sites in 0x60dd–0x60ee | dis + byte scan [V] |
| 5 | **Main menu = root 0x6117b410** (read by 0x60e0fa45): 7 tabs, page array 0x6117b1b4, 28-B page records `{u16 tab, u16 n, items, helps, ndesc, desc[], n2, x}`. An item is 12 B, `{u32 setting id, label src}`. A desc is 8 B, `{u16 id, u16 count, list}`. Example: Video page 0x6117b1ec, 13 items, desc 652 → list 0x6117aa98 (21) | dump + strings [V] |
| 6 | **Static descriptor counts do not decide the menu entries; count/value-by-index do.** Aspect v3 raised the 270 desc count 6→8 and showed nothing new in the menu or the SCP. Only the validator list edit (v4) changed what was enumerated | ASPECT.md §1c [C][V] |
| 7 | Labels: the value is looked up in the desc list by builder A 0x60df250b (menu 0x60e0aad4 / 0x60e0ab24; value column 0x60e8af1c). **A value with no entry leaves the label untouched** (loop at 0x60df2515 falls off the end). Virtual values therefore need list entries, and those entries can be marker entries that the camera-proven test-8 hookA/hookB (0x60df255f / 0x60df25dc) turn into heap names | dis [V]; FILM_LIBRARY §8 |
| 8 | The value column 0x60e8af1c already has runtime-text cases keyed on the item id (3487/3488 Artist/Copyright, 5054–5057 Lens Info: kind 5, 8 characters + `...`) | dis [V] |
| 9 | **Item visibility is filtered at run time**: root 0x6117b410 is multi-model (Accessory Port page, "H./I. EVF", High Res Shot 775; ids 685/1038 sit on two pages). No `{id, fn}` table for 775/3495/3333/5076 was found. The iteration 0x60e1011e / 0x60e10bef calls a 0x607af9ce-object vtable (+20, +48) [?] | scan [V], filter [?] |
| 10 | Colour-wheel polygon producer = vtable+4972 method **0x60932fa6** (case 1). Cursor id from setting **1648**, ID table 0x60b40c4c, values via **0x602afa81** (bypasses the facade). So the wheel graphic always shows stock sector values; any virtual-value editor page (F / X) changes only the numeric value and the label, never the polygon | spot-check [V] (1648 at 0x609330bc, 0x602afa81 ×3) |

## 3. Q1: virtualise an existing setting that already has a list

| Host | Where | Native list | Lost while a card is in | Verdict |
|---|---|---|---|---|
| 652 Recording Volume | Video page, desc 0x6117afd4 → 0x6117aa98 (21, kind 5/6) | ±10 | mic-level UI (level frozen) | **Rejected by the user** (LOOK_PICKER §10) |
| 650 / 651 Elec. Zoom Speed (stills / movie) | Shooting 2 desc 0x6117b174 → 0x61179a1c (3); Video desc 0x6117afcc → 0x6117aa74 (3) | 3 | power-zoom speed UI (EZ lenses only) | Best remaining candidate, **but probably greyed without an EZ lens [?]**. That would mean virtualising +20/+36 as well |
| 1038 AF Illuminator, 685 Keystone, 180 RC Mode, 267 Multi-Exposure, 472 HDR, 605 Bracketing | Shooting 1/2 descs | 2–8 | a stock shooting function | Rejected: real functions; 685/1038 appear twice (hidden copy per model, §2 #9) |
| 433 / 695 / 843 (audio, FILM_LIBRARY §5.3) | sub-pages | 2–6 | audio UI | Weak: same class as 652 |
| A hidden item (EVF items 3333/5076, Accessory 3493–3495, High Res 775) | root pages | — | nothing visible | **Visibility filter unmapped [?]** (§2 #9). Most of these open special screens, not desc lists. L |

The list itself does **not** need the host's native count or validator: count, value-by-index and set are ours,
and the 0x604cc98c validator sits behind 0x60827440, which the 0x607fa355 hook never reaches for the host id.

## 4. Route V1 (only if the user accepts one host): host item → list of looks

| # | Site | Change | Size | Conf. |
|---|---|---|---|---|
| V1 | 0x60acb0f4 (+24), 0x60acb0f8 (+28) | data words → `vl_cnt` / `vl_val`: host id ∧ L valid → N+1 / k (k = 0 means "Own"); else jmp stock | 2 × 4 B, ~60 B code | H [V #1, #3] |
| V2 | 0x60acb0f0 (+20), 0x60acb100 (+36) | available(host, v) → 1 for v ≤ N; needed if the host is greyed | 2 × 4 B, ~40 B | M |
| V3 | existing chain 0x60acb0e4 / 0x60acb174 / 0x607fa355 (ed_get → ex_get, ed_default, ed_set → ex_set) | one more id case: get → current pick, set → `fm_apply(slot, k)` (FILM_MENU_V2 §4.1 step 3) and return; never call 0x60827440 for the host | ~150 B | H (same pattern as ed/ex, emulator-proven) |
| V4 | host desc list pointer + count (e.g. 0x6117afd8/0x6117afd6 for 652) | → new list of 65 × 12 B `{k, kind 4, stock string, marker+k}` | 780 B data + 65 NUL marker bytes | H (aspect precedent) |
| V5 | hookA / hookB (`patches/film_menu`) | second marker range → name `L+16k`; "Own" → slot name | ~60 B per copy | H |
| V6 | slot choice | the look goes to the **active** COLOR slot (property 0x6005e971 key 38017/63153, LOOK_PICKER §2), or to COLOR1 only | ~40 B | M |
| — | persistence | the heap + 12c save (BUNDLES.BIN), as F | 0 | H |

Totals: about 0.6–0.8 KB of code (sec 9 / dead EVF space; CODE_SPACE_MAP would need a new claim), plus about
0.85 KB of data. **Risk to internal settings: low.** Stock storage for the host is never written, because the
set is intercepted. What remains: [?] whether another setter path (SCP/LC dial step 0x602b9cda, custom-mode
recall, Reset) writes host values; those would write stock values only. **Open [?]:** whether the main-menu
popup enumerates through the facade or through the stock thunks (if the latter, hook the 3 thunks of §2 #2
instead of V1, 3 × 6-B sites); and the label width (8-character value column, §2 #8).
**Confidence M.** Gate: emulator run of 0x60de3670 and the main-menu list path on the host, plus a camera
check that the popup scrolls 65 rows.

**Clarity / Grain / WB as lists:** the same mechanism, with 4 hosts (one per field) or 1 host with 4 × 11
combined entries. Each needs its own visible host, so it is worse than V1. Not proposed.

## 5. Q2: the Picture Mode list (test-8 names)

- [V] `Cursor_Move_Set_Mode_Actuator::Initialize_picture_mode` (string ref 0x60de47c0) builds its rows from
  static 20-B tables chosen by condition: 0x61152c80 (MONO rows 57/58/59/65 with sub-screen ids
  1047/1048/1049/1685), 0x61152184, 0x61151f90. It also uses facade +8 / +28 on setting 111.
- **Adding look rows** means virtual values on **setting 111**, the most-read setting there is (LC, SCP,
  capture). One missed setter path stores a bogus picture mode. **High risk. Rejected.**
- **Movie/INFO → sub-list:** INFO/→ already opens the profile editor (stock). The list FSM key routing and a
  popup screen are unmapped (FILM_MENU_V2 c1, LOOK_PICKER §10.2 b). A new popup screen is the most expensive
  item here. **L, not worth it.**

## 6. Q3: a new item on a shooting-menu page

- [V] Binding is by id: page record items[] `{id, label}`, helps[] and desc[] `{id, count, list}` (§2 #5).
  A new item means relocating items[] and helps[] (+1 entry each), adding a desc, and editing page n
  (Shooting 1 0x6117b1b4 has 10 items and 6 descs; Shooting 2 0x6117b1d0 has 14 and 11).
- A new id has **no** ID-table entry or storage, so **every** facade method and every direct reader the menu
  uses for an item (value column 0x60e8af1c getter vtable, availability, lock/grey, help, the open-dispatch to
  an actuator, Reset 10003, custom-mode save) must be intercepted. A non-intercepted path would hand an
  unknown id to 0x602af887 / 0x602afa81 [?].
- The page row limit and the visibility filter are unmapped (§2 #9). Est. 1.2–1.6 KB plus a large trace.
  **Risk M–H (an unknown id reaching stock getters), confidence L.** Not recommended.

## 7. Q4: sliders

| Screen | Why not |
|---|---|
| Color Creator 2-value editor (record 0x13a9 at 0x61185bb0, settings 617/618) | It is reachable only with Picture Mode = Color Creator, which changes the render. Virtualising 617/618 makes the CC screen lie |
| EV-style rulers (setting 17 list 0x61179b0c, 19 kind-5/12 entries), Highlight & Shadow | Bound to exposure settings: the same host problem as §3, with a real function lost |
| `Progress_Bar_Actuator` | Display only, no input [I] |

The X stop already gives Clarity/Grain/WB a −5..+5 value on the wheel. A slider adds nothing that a host-free
route can provide. **Not worth it.**

## 8. Summary table

| Route | Stock path | Hooks | Est. bytes | Internal-settings risk | Conf. | Verdict |
|---|---|---|---|---|---|---|
| Editor F / X stops (built, test12e) | record +12/+16, facade +8/+152, 0x607fa355 | existing | built | none | H (emulator) | **Keep** |
| V1 virtual host list | facade +24/+28 (+20/+36), desc list, builder A/B | §4 V1–V6 | ~0.7 KB code + 0.85 KB data | low | M | Only if the user accepts losing one host UI (650/651 or 652) |
| Picture Mode extra rows | 0x60de47c0 static tables + setting 111 | 111 count/value + tables | ~1 KB | **high** | L | Rejected |
| Picture Mode sub-list | unmapped list FSM | new screen | >2 KB | M | L | Rejected |
| New menu item | page 0x6117b1b4.. + all facade methods | many | 1.2–1.6 KB + trace | M–H | L | Rejected |
| Sliders (CC / EV ruler) | 0x61185bb0 / setting 17 | host | — | M | L | Rejected |
