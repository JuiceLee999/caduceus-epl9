# Still aspect ratios: XPan 65:24 and 21:9 (E-P7 1.1)

Offline static analysis and emulation only. No camera was contacted, no SD-update-named file was
written, nothing was committed. Main = `analysis/ep7_1100/00_0100_406a0020.decoded.bin`, base
`0x60020020`.

Evidence labels:
- **[V]** read directly from the image (byte dump or `tools/dis.sh`), or executed natively in the emulator.
- **[I]** inference: consistent with the data, not proven.
- **[?]** open question.

Patch: `patches/aspect/build.py` writes `patches/aspect/edits.json`. That file holds **145 edits, 2082 bytes (v7: + 17 UI edits, §1f)**; v6 had 128 edits, 1577 bytes (+ 11 LV-switch / rec-view edits, §1e); v5 had 117 edits, 1437 bytes (+ 9 runtime-geometry edits, §1d); v4 had 108 edits, 1209 bytes (+ the 2 validator edits, §1c; v3 had 106 edits, 1192 bytes),
all in component 0x100 (v3, 2026-11-02: the 103 v2 edits unchanged + 3 SCP/Live Control option-strip edits, §1b;
v2 = 101 table/menu/switch edits as in v0.4 + the 2-edit boot clamp, §3(c)).
The script also runs 198 emulator and parse checks (174 as in v2 + 24 SCP-strip checks), and all of them pass,
standalone and with `--base` = test12d minus its aspect edits (= `generated/look_extras_12d/merged.json`, 101 edits;
note `releases/test12d-editor/edits.json` itself already contains aspect v2, so it cannot be the base as-is).
`tools/build_package.py` accepts the spec (it was test-built into the scratchpad only). `patches/aspect/scan_tables.py`
is the table-inventory scanner.

## 1. The setting

| Item | Value | |
|---|---|---|
| Settings ID | **270**, read with `mov 270,d0; call 0x602cbc0a` (getter by ID) | [V] e.g. 0x60a38b92, 0x602e82cb |
| Property key | **0x3081** (property 776, byte, index 0), from the ID→key table 0x604d6c14[270] | [V] |
| Default | 1 (4:3); defaults table record `8130 0100 0100` at 0x60097044 | [V] |
| Still values | 1 4:3, 2 3:2, 3 16:9, 4 1:1, 5 5:4, 6 7:6, 7 6:5, 8 7:5, 9 3:4 | [V] tables |
| Value 10 | 17:9, a **movie** aspect: `0x602e82a8` returns 1/10/3 from the movie resolution when setting 44 == 1, otherwise setting 270 clamped to 1..9 (10 maps to 0) | [V] code; "movie" is [I] |

### What hides 5:4, 7:6, 6:5 and 7:5: a per-setting option **list** (no mask, no switch)

- **[V]** The menu descriptor array at 0x6117af0c holds `{u16 setting, u16 count, u32 list}` records.
  The record at **0x6117af14** is `{270, 6, 0x6117a834}`. It sits in the page record at 0x6117b1b4 (items 0x6117a0cc;
  the item `{cond 0x611799dc, 270, type 4, string 70 "Image Aspect"}` is at 0x6117a0f8).
- **[V]** The list at 0x6117a834 has 12-byte entries `{u32 value, u16 type=4, u16 string, u32 cond=0x611799dc}`:
  `1/"4:3"(292), 3/"16:9"(291), 2/"3:2"(293), 4/"1:1"(1786), 9/"3:4"(295), 10/"17:9"(3261)`.
  Ids 5–8 are simply absent, and every entry uses the same default condition pointer. The next list starts
  right after the last entry, so the list cannot grow in place.
- **[?]** The 6th entry (17:9) does not appear in the still menu (per the manual and the task statement), but I did not
  find the filter. Candidates: the effective-aspect clamp (10 → 0), or a model/mode check in the menu
  framework (0x60e0f8f3..). The relocated list keeps 17:9 **last** and unchanged, so the patch works whether
  the filter tests the value or the last index.

### 1b. Why Panorama/Wide were missing from the SCP (camera test 12d), and every other aspect list (v3)

Camera result on test12d: Panorama/Wide do **not** appear in the Super Control Panel aspect options (the main menu was not reported).
The main-menu descriptor (above) is not used there. Every list in the image that enumerates the aspect values was
found by a stride/width search for the value sequence 1,3,2,4,9 and the string-id sequences 292/291/293/1786/295, plus a scan for
`{u16 270, u16 count, ptr}` records. All hits:

| List | What it is | Enumerates choices? | v3 |
|---|---|---|---|
| 0x6117af14 → 0x6117a834 (6) | main menu Image Aspect | yes | relocated 8-entry list (v0.4) |
| **0x61176fc0** `{270, 5, A 0x61175d78, B 0x61175db4}` | record 14 of the **Lv_Control select array** (header 0x61177140 `{0, 30, 0x61176e70}`, 30 × 24 B, class string `Lv_Control_Mode_Viewer::lv_vertical_select`, user 0x60e0a5fe/0x60e0a92b). Entries `{u32 value, u16 type 3, u16 bitmap, u32 cond 0x611744e4}`; A = white 50×38 icons 477/476/478/2422/479, B = green 64×48 icons 472/471/473/2421/475; values **1,3,2,4,9 only** | **yes**: the SCP/Live Control option strip; also the current-value cell icon (0x60e0aad4 → resolver) | **extended to 7** |
| 0x6123dc94.. `{id, A, B, count}` (ids 0x1ff/0x200, count 5; lists 0x6123dbc4/dbec) and the skin-2 copy 0x6123f17c.. (0x6123ed6c/ed94) | display resources: value → bitmap u32 pairs, chosen by skin 220/221 (0x60ed8885) | no (value → icon lookup, bitmap only, no type field) | unchanged: a 6/7 lookup misses (no icon) [I] |
| 0x611d6754 record `{0, 6, row labels, title 70, (28) 0x611d6228, (32..) pixel-string lists}` | quality / pixel-count screen (RAW/L/M/S/Super-L rows + "Image Aspect"; strings "5184x3888"…) | no: resolves the **current** aspect via 0x60df250b; count 6 is shared by all its lists | unchanged: for 6/7 the aspect label and pixel-size text are blank [I] |
| 0x61162468.. (12 × 6), 0x611d3198.. (8 × 6), 0x61140d98.. (4 × 6), 0x6116daf4 (6 pairs, count at 0x60e00a39), 0x611743e8 → 0x61173d88 (map key 15, 5 entries) | LV display layout/position lookups keyed by the aspect (0x60df78bc.., 0x60e90c22, 0x60e00a1b, 0x60df7e83) | no | unchanged: a miss leaves the stock field as it was [I] |

**Fix (v3):** the 270 record gets 7 entries: `1,3,2,4,9` (stock icons) + `6 = type 4 / string 241 "Panorama"`, `7 = type 4 / string 2661 "Wide"`
in both lists. There is **no Panorama/Wide/65:24/21:9 bitmap** in the OSD resources (all aspect bitmaps were checked visually: 4:3, 16:9, 3:2, 1:1, 3:4, 17:9 only),
so text entries are used. [V] The shared resolver 0x60df250b (also used by the main menu and the quality screen) fills
the bitmap slot for type 3 and the **string slot (out+4) for type 4**, and runs the text path (memset + 0x600daed9 on the
cond word, which is a zero word here exactly as for the main menu's 0x611799dc). Mixed type-3/type-4 lists under one cond are
common in the image (e.g. 182 type-3 entries under the main menu cond). [I] Whether the strip widget draws a type-4 entry as text
in a 50×38 / 64×48 cell, how it clips "Panorama", or whether it shows a blank cell is **not emulated** (renderer not traced). Worst
expected case: a blank or clipped cell that still selects 6/7.
Layout: list A is rewritten **in place** over the stock A+B block 0x61175d78–0x61175df0 (84 of 120 B; only the record points
there [V xref]); list B (84 B) goes to the sec-6 tail **0x61242f60–0x61242fb4** (0x61242fb4–0x61243000 = sec-6 load end stays FF);
the record becomes `{270, 7, 0x61175d78, 0x61242f60}`. 17:9 was never in this list and is still absent.
Interaction [V]: the film-menu patch hooks the same resolver at its kind-4 points (0x60df255f → hookA 0x61242d10, 0x60df25dc → hookB).
The R checks map the whole sec-6 tail, so on the 12d base they execute those hooks: the non-marker cond word falls through and the
result is the stock text-entry result.

### 1c. The real filter: the static setting validator (v4, camera test 12e)

Camera result on test12e (aspect v3): Panorama/Wide appear in **neither** the main menu nor the SCP; only the stock options.
- [V] Both option lists are filtered by the **static setting validator** 0x604cc98c (docs/BUTTONS.md §2): record 442 at
  **0x604cec14** = `{sid 270, attr 0x80, list 0x604cb744, alt 0, bytes 5, elem 1, sub 0, type 1}`, u8 list **1,3,2,4,9**.
  Count 0x602b9f70 / value-by-index 0x602b9fdb sit behind the GUI facade 0x607f9062 (vt+24 0x60826d53 → 0x602af8dc → 0x602b1776;
  vt+28 0x60826d5f → 0x602af8a3) and the generic menu builder 0x60886900; dial stepping is 0x602b9cda. Sid 270 has no
  registry record (0x604317ac, 439 × 60 B), so no dynamic-list hook, and it is not one of the two runtime slots (0x62245800).
- This also explains the hidden **17:9** (§1): 10 is not in the validator list.
- **Fix (v4):** the 7-byte list `01 03 02 04 09 06 07` at **0x60210f70** (sec-1 FF tail inside the aspect claim; sec 1 loads
  first), record +4 → 0x60210f70, +12 bytes 5 → 7 (2 edits, 17 B). The descriptor/SCP lists of v3 stay (they supply labels).
- Checks V1–V6 (emulated native hash init + count/value/step on stock vs patched): 270 enumerates 1,3,2,4,9,6,7 (stock 1,3,2,4,9);
  10 still filtered; step walks the new list with stock wrap; 22 other sids unchanged. 205/205 PASS standalone and on the test12e base.

### 1d. The real capture/LV geometry (v5, camera test 13)

Camera result on test13 (v4): Panorama/Wide selectable, but Panorama saved **4544×3888** and Wide **4672×3888** (stock 7:6/6:5),
embedded previews 896×768 / 912×760, ORF AspectFrame (320,0,4863,3887) / (256,0,4927,3887), and LV pillarboxed in the stock 7:6/6:5 frame.
None of the 44 tables of §3(b) drives capture.
- [V] **Capture size source**: two split u16 tables, **W 0x6053de1c / H 0x6053dfcc**, 9 ids × 24 size classes (48 B per id; class 0 = L,
  2 = 160 thumb, 6 = 1024 preview, …), read through **0x603f0a04 (W) / 0x603f0a18 (H)** (`d0` = id, `d1` = class), ~80 call sites in
  the job builder 0x603e3000–0x603f1200 and RAW develop 0x60c65fb0. Stock rows id 6 = 4544×3888 / 896×768, id 7 = 4672×3888 / 912×760:
  exactly the test-13 files. `scan_tables.py` missed them because w and h sit in separate arrays (a stride search for 4544→4672 finds only this table besides the patched ones).
- [V] **ORF AspectFrame**: 0x603ebe95 (job +5202 id → +5204..5210) dispatches through jump table **0x6053dd28** (index id−1) to a
  width-limited case 0x603ebeac (ids 2,3,8) or a height-limited case 0x603ebed5 (ids 4,5,6,7,9). Emulated stock frames equal the test-13 ORF values.
- [V] **LV/AF ratio**: 0x60552d75 returns a u8 (W,H) pair per id from the RAM `.data` copy 0x61f9eb54 of flash **0x60236e14** (boot copy
  0x600201fe: flash 0x60230800–0x6025eb50 → RAM 0x61f98540, +0x1d67d40). Callers: 0x6029457e/0x60294637 (message +72/+73, sent via 0x605c4023)
  and 0x60552651 (LV/AF struct +84/+85 → globals 0xa276f955/6, read by the AF/LV driver 0x605d–0x605e with special cases for 4:3/16:9/3:2/6:6/3:4/17:9 only).
  A second, unreferenced u16 copy sits at 0x604e06ea. Per-id 320×240 bounds (x0,x1,y0,y1) at 0x604d9cd2 (read at 0x602ef370).
- **Fix (v5, 9 edits)**: W/H rows of ids 6/7 → width = max(4:3, 16:9 width) per class, height to 16 (same rule as §3(b); L 5184×1920 / 5184×2224,
  1024-class 1024×384/432, thumb 160×64; classes that stock leaves 0 stay 0); frame jump entries ids 6/7 → 0x603ebeac; u8 and u16 ratio pairs
  7:6/6:5 → 65:24 / 21:9; 320-grid rows → (0,320,61,179) / (0,320,51,189).
- Checks (`build.py --lean`, 36/36, also on the decoded test13 package): W getters ids 1,2,3,4,6,7,9 × classes 0/2/6 (6/7 new, others stock);
  F native frame builder: id 6 (0,984,5183,2903), id 7 (0,832,5183,3055), ids 1–4/9 identical to stock (= camera ORF values);
  R2 native 0x60552d75: 6 → (65,24), 7 → (21,9), others stock; G grid rows.
- [I] Not emulated: the LV pipeline itself. That LV follows the ratio pair (not a size class) is inferred: the test-13 LV kept the stock frame while every size
  table except W/H was already patched, and the ratio pair is the only per-id input sent to the LV/AF side. If LV is still 7:6-framed on camera, the next
  suspects are the AF/LV driver's per-ratio special cases (0x605de36c, 0x605e6eda), which fall through for 7:6 as well as 65:24.

### 1e. The real LV output size: hard-coded CapThr switches (v6, camera test 13 result)

Camera result on test13 (v5): capture correct (5184×1920 / 5184×2224), but LV still pillarboxed 7:6/6:5 and squished.
- [V] The LV output box is chosen by three hard-coded switches in `CapThr_ThroughImage.cpp` (sec 5) on the raw setting-270 id
  (index id 0..10, from 0x60881f93 / 0x60882015 / 0x60882085 or the getter directly): **getOutputSize** 0x60882bb3 (JT 0x60b01e48,
  W→(44,sp), H→(48,sp)), **getOutputSizeForFineZoom** 0x60882ec4 (JT 0x60b01e74, (40)/(44)), **getTakeAreaSize** 0x608833ae
  (JT 0x60b01ea0, (48)/(52)). Stock: 4:3 640×480, 3:2 624×416, 16:9 640×360, 1:1 480×480, 5:4 640×512, **7:6 560×480, 6:5 576×480**,
  7:5 672×480, 3:4 384×512, 17:9 640×338. v5's ratio pair changed the LV crop but not this box → squish. Found by searching
  code for 7:6/6:5 immediate pairs (560/576 within 0x100 B); S1–S4 are the same pattern elsewhere.
- [V] Same switch in playback `CmpPls_PlaySingleComponent.cpp` get_aspect_frame 0x608daca2 (JT 0x60b1f34c, index id 0..9, a0 = W, d3 = H).
- [V] Rec-view 640-class u16 arrays W 0x6053e23c / H 0x6053e24e (index id−1; getters 0x603f0bff/0x603f0c0f, rec job builder,
  job +283 = id) also held 560/576×480 (split arrays, missed by `scan_tables.py`).
- **Fix (v6, 11 edits, 140 B)**: 8 case blocks (13 B: `mov 640,d0; mov d0,(W,sp); mov H,d0; jmp H-store join`; S10 11 B:
  `mov 640,a0; mov H,d3; jmp 0x608dacf2`), H = 240 / 272 (the 640-class rows), at **0x601e1440–0x601e14a4** in the dead EVF gamma
  table 0x601e143c (only ref: step-table word 0x601e3d40); 8 jump entries; rec-view W/H ids 6/7 → 640×240 / 640×272.
- Checks (`build.py --lean`, 70/70): native S7–S10 dispatch, ids 1,2,3,4,9 identical to stock, 6/7 → 640×240 / 640×272; rec-view getters.
- [I] Not emulated: what the LV pipeline does with the box (expected: full-width frame, top/bottom bars). Remaining 7:6 immediates
  (280/288, 840/864, 1120/1152) were checked and are unrelated (lists / vtable offsets).

### 1f. Pixel-size readout "0x0" and the blank aspect icon (v7, camera test 13 v6 result)

Camera result on test13 (v6): Panorama/Wide preview and capture right, but the size readout shows **"0x0"** and the aspect icon is blank.
- [V] The readout is not the quality-screen string lists of §1b. Three UI callers (0x60dfac83, 0x60dfae48, 0x60ed951f) format UTF-16
  `"%dx%d"` (0x61163d76) from **0x60eac4a9**(d0 = aspect id, d1 = size setting, a0 = &w, a1 = &h). It reads sec-6 table **0x611f09e0**:
  u16 ids[5] = 1,3,2,4,9, then 10 rows × 22 B `{u16 size key, u16 w[5], u16 h[5]}`, keys 0 (L), 13, 11, 8, 7, 6, 5, 3, 20, 21 = the
  0x60b8ce30 recorded-size keys (stock columns equal those lists, build-asserted). d1 == 22 is a shortcut to row 0 / column 0 (5184×3888).
  Ids 6/7 miss → w/h untouched → the callers' zeroed buffers print "0x0".
- [V] The info-display icon: records `{u32 item, listA, listB, u32 count}` 0x6123dd04 / 0x6123ddb4 (skin 1) and 0x6123f17c / 0x6123f438
  (skin 2) in the 11-record tables read by 0x60ed8885 (item id, then list A, list B, count copied out). Lists are value → bitmap u32 pairs, no type
  field, so text is not possible here. The only aspect bitmaps in the 50×38 / 64×48 sizes are 4:3, 16:9, 3:2, 1:1, 3:4 (17:9 exists only as a 44×32 movie icon).
- **Fix (v7, 17 edits, 505 B)**: a 7-column copy of the readout table (ids 1,3,2,4,9,6,7; 30-B rows; ids 6/7 = the patched 0x60b8ce30 rows, i.e. what is recorded:
  L 5184×1920 / 5184×2224, 3200×1184/1376, 2560×944/1104, 1600×592/688, 1280×480/544, 1024×384/432, 640×240/272, 1920×704/816, 8160×3008/3504,
  5760×2128/2464) at **0x601e14b0–0x601e15ea**; 0x60eac4a9's 4 table pointers (5 sites) and 5 immediates (id count 5→7, row stride 22→30 ×2, h offset 12→16 ×2).
  Two 7-entry icon lists at **0x601e15f0 / 0x601e1628** (56 B each; ids 6 and 7 both borrow the **16:9** bitmaps 476 white / 471 green), all four records → new lists, count 5→7.
  Placement: the rest of aspect's dead EVF step-12 tables (claim now 0x601e143c–0x601e173c); a whole-image u32 scan (any alignment, cached + uncached alias) finds only the step-table
  words 0x601e3d40/44/48 (+ 2 dis-checked byte matches inside `call` encodings) in stock, and after the patch only those plus the v6 jump entries and the v7 pointers.
- Checks (`build.py --lean`, 157/157; full suite 362/362): U native 0x60eac4a9 (facade GetValue stubbed) for all 10 size keys × ids 1,2,3,4,9,6,7,5: 1–4/9 identical to stock,
  6/7 stock miss → patched = recorded size, 5 still misses; d1 = 22 shortcut unchanged; I the four icon records (7 entries, stock 5 unchanged); U2 reference scan.
- [I] Not emulated: the "%dx%d" rendering and the icon draw. Panorama and Wide show the **same** 16:9 icon (no better bitmap). The quality/pixel-count screen of §1b
  (type-5 string lists, record 0x611d6754) is a different screen and still shows a blank aspect label / size for 6/7 if it is ever reached.

### 1g. Real XPAN / 21:9 icons and "XPAN WxH" / "UW WxH" size text (v8)

- **Icons [V decoder, I camera]** (`patches/aspect/osd_icons.py`, OSD component 0x101): four new 8-bit mode-11 bitmaps in the stock aspect-icon
  format: white 50x38 (SCP strip list A, info display skin 1/2 list A) and green/selected 64x48 (list B). "21:9" is built from the stock glyph
  pixels ('2' of 3:2, '1' ':' '9' of 16:9, 16:9 spacing) on the stock 16:9 box; "XPAN" is Fira Sans Condensed Bold at the stock digit band,
  quantised to the stock icon's own indices (white 4/5/6/16; green: row background blended to 16 + the stock anti-alias indices).
  The encoder reproduces all 4976 stock mode-11 payloads byte for byte. Placement: payload+descriptor pairs (4.6 KB) appended after resource 69
  (component offset 0x15115e0, zero in stock; runtime 0xa3e22600..0xa3e23788), resource-69 directory size 0x811600 -> 0x812800. The bank loader
  0x6015ad92 copies `size` bytes to 0xa3611000 under the bound 0xf26140 (region 0xa3091000..0xa3fb7140, fonts at 0xa3fb7540) [V code, I region use].
  Bitmap table entries of four stock placeholders (fmt 1, 0x0) -> the new descriptors: **5687 XPAN white, 5685 XPAN green, 4859 21:9 white,
  4431 21:9 green** (no type-3 entry, UI-data u32 or UI-code `mov imm16` of these ids in main; not provably unused [I]).
  SCP entries 6/7 are now type-3 bitmap entries (were type-4 text "Panorama"/"Wide"); the info-display lists point 6/7 at the new ids. The main
  menu stays text ("Panorama"/"Wide"). The package now carries main **and** OSD (restore = stock main + stock OSD).
- **Size text [V emulated]**: the four UTF-16 `"%dx%d"` formatters (readout callers 0x60dfac8a / 0x60dfae4f, info-item kinds 57/58 0x60d91a58,
  0x60d9c401) `mov fmt,d0` -> `jmp stub; nop` (stubs + "XPAN %dx%d" / "UW %dx%d" at 0x601e1660..0x601e16f6). The stub picks the format by the
  size itself: h/w < 0.4 -> XPAN, < 0.5 -> UW, else stock (stock sizes are all >= 0.53; id 6 rows 0.367..0.375, id 7 rows 0.42..0.43), so L/M/S
  print e.g. `XPAN 5184x1920`, `UW 5184x2224`, `XPAN 1280x480`. Sites 3/4 now use 0x61163d76 for the stock case (same "%dx%d" text). Not traced:
  which screen each of sites 3/4 draws (likely LV info / playback info; a playback of an XPAN file would also show the prefix, by design).
- Checks (`build.py`, 377/377 with `--base` = v0.15 minus aspect): LB 4 sites x 78 sizes (ids 1-4/9 + movie/0x0 unchanged, 6/7 prefixed,
  callee-saved regs/sp intact); O0-O4 (patched OSD re-parses with osd_extract, new ids decode with valid fmt-14/mode-11 headers to the new pixels,
  only 4 table words changed, stock aspect icons byte-identical, loader bound); P1/R/I (SCP + info lists: 6/7 -> new ids, 1-4/9 unchanged).

### 1h. Why the v8 icons never showed, and a second attempt (2026-11-06)

[V] read in code/bytes/session logs, [I] inference. **Camera result (v0.25, 2026-11-06): the option strip shows XP and 21:9 correctly, so the in-place bitmaps draw. The current-value cell still shows 4:3 on either, so it does not use row 16 or the patched lists as expected: open.**

**What was on the camera [V].** The session log has the copy: `releases/v0.15/patched.pkg.bin` (52 MB, patched sha `c32c84b6`, the 809744b build.json; OSD edits 6, 0x101 component present) was copied to the card and `cmp`-verified. Main features in that same package were then reported on, and main is flashed after OSD with a failed component aborting the rest (docs/SD_UPDATE.md), so the OSD was written. "The words are okay" = the new `XPAN WxH` / `UW WxH` size text (the camera report's own context), not SCP text entries; there is no contradiction with type-3 SCP entries.
**Correction:** a 0x101 edit **has** reached the display: the 2026-11-01 OSD probe changed Setup `Firmware` to `FIRMWARE` (WORKLOG). That is a string resource; no bitmap edit has been proven.

**The v8 data path is sound in code [V].** Traced for the first time:
- Directory: 0x6015ab7c reads 2048 B from 0x421a0000 to RAM (dir = +32), so the size patched at component offset 0x454 is what the loader sees. Bank loader 0x6015ad92: resource 0 → 0xa3091000, else 0xa3611000; size from the directory, bound 0xf26140 only; 0x6015b7bb copies `size` bytes from flash with no CRC. So the appended bytes do reach RAM at 0xa3e22600. Bank 69 is requested once at boot (0x60044ed8, flag 0xa272c3f9).
- Pool layout from the bounds: bitmaps 0xa3091000 + 0xf26140 + 0x400 = fonts 0xa3fb7540; fonts + 0xc7c00 + 0x400 = strings 0xa407f540; strings + 0x5fc00 + 0x400 = 0xa40df540 (a code immediate). No immediate points into 0xa3e22600..0xa3fb7540. Appended data was inside a free part of the pool [I].
- Getter: 0x60eac846 stores bank-0 header +16 in 0x61fc1734; **0x60d10ba1(id)** returns `&table[id]` (id 0 → NULL). There is no bank-by-id lookup, id bound, hash or per-resource count. Widgets keep `&table[id]` (0x60d48dbf). Draw 0x60d145bf reads fmt/w/h/colour key from `*entry`; 0x60bafbb2 takes the mode from the stream header. So a placeholder id with a repointed table entry is not hidden.

**Cause: a third aspect list was never patched [V for the list, I for it being what was looked at].** §1b's "every list" missed it. The 74-row, 52-B item table 0x6116ae1c has **row 16 at 0x6116b190 `{16, A 0x611670f4, B 0x61167130, count 5}`**: type-3 white/green aspect icons, values 1,3,2,9,4 only, unchanged in every release. `0x60e0a6ff → 0x60e0af25` maps setting **270 → row 16** in `Lv_Control_Mode_Viewer`, stored at self+8528 by 0x60dfc556. Layout table 0x61162d9c has no list function for key 16, so slot 4 stays the default 0x60dfae97 (init image 0x6025ac28) → 0x60dfc1f6, whose loop 0x60dfc27d walks the options and looks each value up in row +8 (selected) or +4 (others), count +12 (0x60dfc367/c3c6/c44c). Values 6/7 miss, and a miss leaves that cell's label empty (0x60df250b falls off the end; the fallback row +20/+24 is null here). So on this layout v8 could not show any icon, whatever the OSD held, and v0.25 still draws nothing there.
Not explained: the report doesn't say which screen, or blank vs 16:9. Record 0x61176fc0 and the info lists did point at the new ids. Either the report was about the row-16 layout, or v8's appended data also failed for a reason not visible in code. The new build removes both.

**Second attempt** (`patches/aspect_icons/build.py`, output `generated/aspect_icons/`, on releases/v0.25/edits.json, read only; 11 edits added, 4 changed):
- Main: row 16 → the 7-entry SCP lists, count 7 (12 B at 0x6116b194; lookups are by value and the resolver ignores the +8 word for type 3 [V], so the different stock order and cond don't matter). SCP lists 6/7 type 4 text → type 3; info lists 6/7 → new ids. The SCP strip loses the words Panorama/Wide; the main menu keeps them.
- OSD, in place, no table/directory/bank change: **3732** white and **3725** green = XP; **5528** white and **5535** green = 21:9. These four are headphone icons; the E-P7 has no headphone jack. Unused on this body is [I]: a reference scan is not proof (some real icons such as LIVE TIME show zero references, so ids can be computed); 5535 is immediate-loaded by touch movie code 0x6086ea8c. Worst case if a stock screen does draw one: it shows the wrong icon.
- Streams 649/692, 1122/1151, 678/692, 1135/1151 B. Descriptor size set exact, colour key 0, remainder zeroed. To fit, the green gradient's dither is flattened on 2 rows (XP) and 4 rows (21:9); glyphs untouched. XP = Fira Sans SemiBold stretched to two half-spans of the 16:9 label; 21:9 = stock glyphs (§1g).
- Checks (12/12, `generated/aspect_icons/checks.json`): package parses; decoded == stock + edits; restore == stock main + stock OSD, sha = v0.25 restore; patched OSD reparses, all 7576 strict; the other 7572 identical; no directory/table edit; new ids decode to the intended pixels; lists and row point at them, stock values unchanged. Not emulated: the draw itself.
- **Bad OSD and boot [V code, I effect]:** the loaders only copy bytes and check size; nothing found decodes bitmaps during boot. A bad stream affects that icon's draw. A bad directory size logs and leaves the bank null, and a bad table pointer would read wild at draw time, so the UI could fault; this build edits neither. The SD updater path is LED-only and draws no OSD (docs/SD_UPDATE.md), and restore has worked from a bootloop.
- **On camera:** with Panorama and Wide, in the SCP cell, the option strip and the info display. No separate diagnostic was built: this build discriminates. If 3:2 etc. still draw but XP/21:9 are blank everywhere, in-place bitmap edits or those ids are at fault; if only one surface is blank, it reads a list still unfound.

## 2. Consumers of the aspect id

| # | Site | What it does | Status |
|---|---|---|---|
| 1 | 0x60a38895 (loop 0x60a38c85–0x60a38ce1) | Recorded size: walks pointer table 0x60b8ce30 `{size-key, list}` → u32 `{id,w,h}` lists (19 size classes). The size key comes from settings 175/176/177/777/1110 (via 234–237/776/1113). It pre-sets 5184×3888, so an unknown id falls back to 4:3 | [V] emulated |
| 2 | 0x6034ee0b | id → `&{w,h,code}` in 0x604e92c0 (ids 1..10; index 0 = null; d1=1/2 select two movie rows); 23 callers in the image pipeline 0x60355..0x603b3c | [V] emulated |
| 3 | 0x6035585e | Crop scale: `w' = w·T[id].w/T[1].w`, `h' = h·T[id].h/T[1].h` (aspect byte at struct+23); skipped for some modes | [V] emulated |
| 4 | 0x602e82a8 | Effective aspect (above); callers 0x602ed48e, 0x602ef358 | [V] |
| 5 | ORF/RAW: makernote tag table 0x604db9d0 | **0x1112 AspectRatio** (BYTE×2 ← job+5202/5203) and **0x1113 AspectFrame** (← +5204..5210). RAW develop 0x60c6362f–0x60c637ac computes the frame as a centred crop from RAM size tables (0x61fafdb0.., `.data` copies of the 0x6024xxxx arrays, offset +0x1d67d40); another writer is at 0x60c61b55 | [V] code; tag names from ExifTool [I] |
| 6 | Display/LV geometry tables | 0x601e5fd0 (720×480 panel boxes), 0x601e6004 (1008×672), 0x601e6038 / 0x605223e8 (1024×768), rects 0x60533880 (640×480, 23 refs at 0x603b78b6..0x603c9a24) and 0x60533930 (320×240) | [V] data; [I] role |
| 7 | Sec-5 UI switches (hard-coded) | **S1** 0x6088b29d, **S2** 0x6088b37f, **S3** 0x60899a34, **S4** 0x6089b7d7: id → 640-class size (immediates equal to table row 0x60b8ced0). **S5** 0x6086275e: id → ratio pair (W→(24,sp), H→(28,sp)). **S6** 0x60879ca9: id → fit group (ids 2,3,10 scale the height; ids 1,4..9 scale the width), plus a 16:9/17:9 special case at 0x60879e9a | [V] emulated |
| 8 | "Image Aspect" icon (display resources) | Lists of (value, bitmap) pairs at 0x6123dbc4 (white 477/476/478/479/2422) and 0x6123dbec (green 472/471/473/475/2421), duplicated at 0x6123ed6c/0x6123ed94; records `{id 0x1ff/0x200, listA, listB, count 5}` at 0x6123dd04/0x6123ddb4/0x6123f17c/0x6123f438 (table 0x6123dc94, user 0x60ed8885). **Only ids 1,3,2,9,4**. The SCP/Live Control strip has its own lists (§1b) | [V] data |
| 9 | Menu label | String id taken from the option list (sec-6 data) | [V] |
| 10 | Playback edit "Aspect" (string 563) | Separate list at 0x61241ddc (3:2/16:9/1:1/3:4); crops an existing JPEG; not the setting | [V] data; [I] role |
| 11 | LV grid bitmaps 5996–6143 (720×480 / 640×480 / 720×405 / 480×480 / 360×480) | Selection code `0x60e32406..0x60e32702`, see §7.3 | [V] |
| 12 | Art Filter / bracketing | **Not traced.** The bracket variant copy (docs/PROFILE_INDEX_WB.md) doesn't list the aspect | [?] |
| 13 | Other key-0x3081 getter sites | 18 `mov 0x3081,d0` candidates: capture 0x602a83ab, 0x60303617, RAW develop 0x60c66f4b/0x60c73029, sec-9 0x613f32ed, … (not each traced) | [V] list, [?] roles |

The table inventory is exhaustive for the layouts that `scan_tables.py` checks: 9 consecutive rows matching the 9 ratios
within 3.5 % in u16 (w,h), u16 rects, u16 (id,0,w,h), u16 (w,h,code) and u32 (id,w,h). It finds
44 tables. One is a second (w,h,code) table for a 3968-px sensor at 0x6052219e (multi-model) [V].
4:3-only rows (stock (0,0) for other ids) are left alone.

## 3. Design

### (a) Unhiding 5:4 / 7:6 / 6:5 / 7:5: not an easy win
- [V] The tables, crop, ORF frame and S1–S6 already handle ids 5–8 natively. Adding list entries
  (relocate the list, count += n) would make them selectable.
- [V] But **no label exists**: there is no "5:4/7:6/6:5/7:5" string in the 3645 strings and no bitmap among the
  aspect labels. The icon lists (#8) have no entry for them either. Unhiding needs OSD string edits
  (component 0x101), or it shows a borrowed or empty label. Not done.

### (b) Repurpose id 6 → XPan 65:24 and id 7 → 21:9 (implemented)
- **Ratio code** [V encoding]: `code = (H<<8) | W` (0x304 = 4:3, 0x910 = 16:9, 0x911 = 17:9, 0x403 = 3:4).
  So **65:24 = 0x1841** (the guess was correct) and **21:9 = 0x0915**.
- **Dimensions**: width = max(width of the table's 4:3 row, width of its 16:9 row), which is the sensor or panel width.
  Height = **nearest multiple of 16** in every table (v0.4, review v0.3 M1; v0.3 used the table's own
  2-power alignment clamped 2..8, which produced heights such as 1280×472 that the shipped firmware never makes).
  16 is the alignment of every UI-reachable stock row in the 1024/1280/1600/2560/320/4032 classes, and it is a
  multiple of every other table's stock alignment (2, 4 or 8), so every new height stays in its table's
  stock size class. `build.py` asserts this per table and re-checks all 88 new heights (check "M1").
  - L: **5184×1920** (1914.1 → 1920) and **5184×2224** (2221.7 → 2224).
  - Other examples: 4032×1488/1728, 3200×1184/1376, 2560×944/1104, 1600×592/688, 1280×480/544, 1024×384/432,
    640×240/272, 320×112/144, 8160×3008/3504, 5760×2128/2464, 160×64/64 (EXIF-thumb class: 60.9 and 68.6 both
    round to 64, so XPan and 21:9 share that tiny thumbnail size).
  - Display: 720×272/304 (panel table), 1008×368/432, 1024×384/432. The 640 rect is (0,120,640,240) /
    (0,104,640,272), plus the clipped second rect, following the stock rule (window origin, band 34..445 / 17..222).
  - 1920×1080 "all ids" list (key 0x1) unchanged; 4:3-only classes unchanged.
- **Menu** [V]: the new 8-entry list goes at **0x61242f00** (sec-6 FF tail, same section as the descriptor):
  `4:3, 16:9, 3:2, 1:1, 3:4, Panorama(6), Wide(7), 17:9`, and the descriptor becomes `{270, 8, 0x61242f00}`.
  - Labels reuse **existing strings** through the existing mechanism: 241 "Panorama" and 2661 "Wide". The user
    sees "Panorama" and "Wide", not "65:24"/"21:9". Real ratio text needs a component-0x101 string edit
    ("17:9", 4 chars, could become "XPan"; but 3261 is shared with movie UI).
- **Code** [V]: S1–S4 and S5 get new case blocks (11 B each) at **0x60210f00–0x60210f6e** (sec-1 tail; sec 1 loads before
  sec 5). Only their jump-table entries change (4 B each). S6 entries for ids 6/7 are redirected to the
  existing width-limited case 0x60879e70 (data only).
- Not changed: the icon lists (#8), the playback edit list (#10), the LV grid bitmaps (#11). The SCP/Live Control strip is extended in v3 (§1b).

### (c) Boot clamp: a saved Panorama/Wide never reaches a boot (review v0.3 H3 / v0.4 M4; v2)
- [V] Boot phase 2 (trace marks "2_l" → "2_o", 0x60190fb9..0x60190fda) calls 0x60192961 once. That function
  loads the settings store (0x602b039a, between the "MCS"/"MCE" trace strings 0x601e708c/0x601e7090), then runs
  the stock per-boot resets: 0x602af9e1 (normal) or 0x602af9f9 (boot reasons 7/9), each gated on byte
  0x62257b04 != 1. Both resets use **0x602b972b(d0 = count, a0 = u16 id list)**: for each id,
  default = 0x602b9bad(id), then 0x602cbc5d / 0x602cc122 / 0x602cc0d0. The 626-entry list (taken when setting 10049 != 0) already
  contains 270, so stock itself resets the aspect with this primitive at this point.
- Hook 0x601929a4 (`mov 0x601e7090,a0`, 6 B, the common tail of both branches) → `jmp clamp; nop`. The clamp
  (0x60210e90, 56 B incl. the list) is: gate byte == 1 → skip; `v = 0x602cbc0a(270)`; if v ∈ {6, 7}:
  `0x602b972b(1, [270])` (so v becomes the stock default 1 = 4:3, record `8130 0100 0100`); then it replays
  the `mov` and jumps to 0x601929aa (`call 0x60023079`, which overwrites d0/d1 first). d2/d3/a2/a3/sp unchanged.
- Effect: Panorama/Wide is a **per-session** choice. Every power-on starts in 4:3, so a fault that is specific to ids 6/7 cannot recur at every boot.
  If XPan crashed live view, a battery pull would bring the camera back to 4:3 on the patched firmware, with no reflash.
  Values 1..5 and 8..10 are never touched (3:2/16:9/1:1/3:4 users keep their choice). A stock restore after a
  patched power-on finds 4:3 (M4 mitigated unless the camera is switched off while still in Panorama/Wide. Stock reads that as its native hidden 7:6/6:5).
- Not covered: whether wake from sleep counts as a boot (if it does, XPan also resets on wake: cosmetic), and the real
  listeners behind 0x602cbc5d at this point (the same calls stock makes here for its 27/6/626-id lists).

### What the user would see [I]
- Menu: "Panorama" and "Wide" after 3:4.
- JPEG: 5184×1920 / 5184×2224 (and the smaller sizes), if no unpatched consumer is left.
- ORF: full sensor data with AspectFrame = the new centred crop. ExifTool would print AspectRatio "7:6"/"6:5" (it decodes
  the id, not the dims). Adobe/other converters that honour the frame crop get the new crop.
- LV and info screen: S1–S6 and the rect tables give the new frame. The aspect icon for ids 6/7 has **no entry**.
  What happens on a miss is unknown (blank is likely).

## 4. Emulator checks (`python3 patches/aspect/build.py [--base SPEC]`, 198/198 PASS in v3; 174/174 in v2; 137/137 in v0.4)

| Check | Stock → patched (id 6 / id 7) |
|---|---|
| T 0x6034ee0b ids 1..10 | (4544,3888,0x607)/(4672,3888,0x506) → (5184,1920,0x1841)/(5184,2224,0x0915); others identical |
| X crop scale 0x6035585e from 5184×3888, ids 1..9 | 4544×3888 / 4672×3888 → **5184×1920 / 5184×2224**; others identical |
| L size loop 0x60a38c85, 19 size keys × ids 1,6,7,9 | new rows have full width, a 16-aligned height within 8 px of the exact ratio; 4:3-only and HDMI rows unchanged |
| M1 | all 88 new id-6/7 heights (every table + the 640-class case blocks) are multiples of 16 |
| S1–S4 (getter stubbed), ids 1,3,5,6,7,8,9 | 560×480 / 576×480 → 640×240 / 640×272; others identical; sp balanced |
| S5 ratio, ids 1,2,3,6,7,8,10 | (7,6)/(6,5) → (65,24)/(21,9) |
| S6 fit group | ids 6/7 now reach the width-limited case 0x60879e70; ids 2/3/10 unchanged |
| M menu | descriptor → 8 entries, as listed above |
| B0 | stock boot tail 0x601929a4 → 0x601929aa: a0 = "MCE" string, no reset |
| B1 | the clamp's id list is the single u16 270 (2-aligned) |
| B2 (33) | boot tail with getter(270) = 0..10 × gate byte 0/1/2 (0x602b972b recorder): reset called **only** for 6/7 with gate != 1, with (d0 = 1, a0 = list); always reaches 0x601929aa with a0 = stock, d2/d3/a2/a3/sp preserved, no fault |
| B3 | native 0x602b972b on [270] (callees stubbed): default lookup for 270, then setter(270, default) |
| B4 | defaults record of key 0x3081 = 1 (4:3) |
| P1 | SCP/Live Control record 0x61176fc0: count 7, A = 1,3,2,4,9 (white icons) + 6/241, 7/2661 (type 4); B the same with green icons |
| P2 | record list B = 0x61242f60; 0x61242fb4–0x61243000 still FF |
| R (22) | native resolver 0x60df250b on the record's list A and B, values 0..10 (memset/strlen stubbed, sec-6 tail mapped): stock 6/7 not found → patched type 4 with string 241/2661; 1,2,3,4,9 identical (type 3, same bitmap); 0,5,8,10 not found in both; regs/sp preserved. On the 12d base this runs through the film-menu resolver hooks |

v3 mutations (scratch): record count left at 5 → R fails for 6/7; list B pointer left at stock → P1/P2 fail (R alone would not: the new list A's tail now sits at the old B address).
Mutations (scratch, not shipped): bhi→bcc, gate beq→bne, add −7, cmp 2, count 2, list+2, call mask → all caught.
v2 also re-ran on the merged image test12c + aspect (generated/aspect_v2/): look editor S/G/W/E/V/I/T PASS, SD v3
E/Q/A/R/N PASS, bloom T1–T5 PASS, clarity C/D/S PASS. Film-menu S and clarity L fail **identically on the 12c spec alone**, which is a pre-existing verifier/spec
mismatch and not caused by aspect. The look-editor M part rebuilds its mutants from the live patches/look_editor sources, which the 12d work is changing. So M is not meaningful against 12c here: 9/41 on the merged spec and 3/41 on 12c alone, run minutes apart while those files changed. Re-run M on the 12d build.
The decoded merged package == the emulated stock+12c+aspect image. It differs from test12c's package only at the 621 aspect bytes.
Restore sha is unchanged (245b9c8f…).

**Not emulated**: the JPEG encoder, thumbnail/EXIF writer, ORF writer, LV pipeline (rect users) and menu rendering.

## 5. Residual risks
1. **JPEG encoder alignment** [I]: since v0.4 every new height is a multiple of 16 (1920, 2224, …), so both 4:2:2
   (16×8) and 4:2:0 (16×16) MCUs tile exactly. Every M/S size now has a height class that stock UI-reachable rows already use.
2. **Thumbnails / preview** [I]: 160-class and the 1024/1280/640 preview arrays are patched. If another, unlisted embedded-preview
   size table exists (a layout the scanner does not cover), it keeps 7:6/6:5 geometry → a wrong-shaped preview.
3. **Playback with unknown dims** [I]: playback reads tag 0x1112 (id 6/7) and probably sizes the display from the patched tables,
   so it is consistent on this camera. Stock-firmware cameras or other bodies that read these files see "7:6/6:5" ids with
   XPan pixels. Most likely a wrong frame or letterbox, not a crash, but this is untested. A hard crash path could
   come from consumers that use the id as an index into fixed-size per-aspect arrays not found here (#11, #12, #13).
4. **Icon lookup miss** (#8, and the quality screen / LV layout lookups in §1b): behaviour is unknown. Mitigation: relocate both icon lists (+2 entries each, reusing e.g. 16:9
   bitmaps) and bump the count to 7.
5. **17:9 filter unknown** (§1): if the filter hides entries by **index**, the new order could expose 17:9 or hide "Wide".
   Check on camera first. A fallback is to put 17:9 back at index 5.
6. **Art filters / bracketing / multi-exposure / digital tele-converter (setting 34)**: not traced. These may carry their
   own per-aspect geometry.
7. **Unverified section residency assumptions**: sec-1 and sec-6 FF tails are inside the loaded ranges
   (`tools/ep7_code_space.py`); the sec-6 tail has a few static false-positive hits (none in 0x61242f00–0x61242f60; v3: no abs32/uncached/rel refs into the list-B range 0x61242f60–0x61242fb4 either).
8. The 3968-px (w,h,code) table and the RAM `.data` copies are patched for consistency. Their users on E-P7 are not traced.

Next steps: trace the 17:9 menu filter and the icon-miss path; locate the LV-grid bitmap selector; test once on a
camera with JPEG+ORF in each new aspect (check the JPEG dims, the ORF 0x1113 frame, the LV frame, the playback and the info icon).
9. **Boot clamp is boot-time code (v2)**: it runs on every power-on. On the common path (setting ≠ 6/7) it only reads the
   gate byte and calls the getter, which stock also does at this point. A fault here would bootloop every boot. The SD updater
   is camera-proven to recover from a bootloop (WORKLOG, test 3). The reset call runs only when the stored aspect is 6/7.
10. **Mixing (H3 proper)** is unchanged *within* a session: untraced consumers (grid selector, art/bracketing/tele-converter,
   18 key-0x3081 sites) can still disagree with the patched tables while Panorama/Wide is selected. The clamp only removes
   the "every boot" part and gives an escape without a reflash (battery pull → 4:3).
11. **SCP strip text entries (v3)** [I]: type-4 text in a cell sized for 50×38 icons may clip ("Panorama") or render blank. The value is still selectable.
   A fallback is to borrow a stock icon (misleading) or add bitmaps through component 0x101.

## 6. Camera plan (folded into the combined 12d build; one session, stop at the first surprise)
0. Before flashing: aspect 4:3 (it is reset at boot anyway). After flashing, power on: the camera boots normally, in 4:3.
1a. **SCP (v3)**: SCP → aspect → the option strip shows 4:3, 16:9, 3:2, 1:1, 3:4, then **Panorama**, **Wide** as text cells
   (or blank/clipped cells: note which). Select each from the SCP and check the cell, then try the front dial on the SCP cell. If the camera has Live Control
   enabled in some mode, check it once too (same list).
1. **Menu**: Shooting menu → Image Aspect lists 4:3, 16:9, 3:2, 1:1, 3:4, **Panorama**, **Wide**, (17:9 hidden as on
   stock?). Note whether 17:9 appears or Wide is missing (risk 5).
2. **LV framing**: choose Panorama. Live view shows a wide letterboxed frame (65:24), and the info-screen aspect icon may be blank (risk 4).
   Try the grid display and the Art filters once and note anything odd. Then choose Wide (21:9).
3. **Shots**: in each of Panorama and Wide, take a JPEG (L-F) + RAW, then JPEG M and S.
   On the PC: L = **5184×1920** (Panorama) / **5184×2224** (Wide). Other sizes are full width with a height that is a multiple of 16 (e.g. 3200×1184/1376,
   1280×480/544). `exiftool -AspectRatio -AspectFrame -ImageSize`: AspectRatio prints "7:6"/"6:5" (id, expected), and
   AspectFrame is the centred crop of those dims.
4. **Playback**: the shots play back with the right shape. Zoom and the info display work. Thumbnails/index are not distorted.
5. **Boot clamp**: with Panorama selected, power off and on. The camera boots in **4:3** (by design).
6. **Back to stock**: select 4:3 and take a shot: 5184×3888, the same as before. Check 3:2 and 16:9 once: 5184×3456 / 5184×2920 (stock sizes).
Escape: if live view or the camera hangs in Panorama/Wide, pull the battery. The next boot is 4:3. If it does not boot,
do the OK+power stock restore.

## 7. Video XPan and 21:9: routes compared (researched 2026-11-05)

Static reads only; nothing built, emulated or run. **[V]** = disassembly or bytes, **[I]** = inference.

**Verdict: land the frame-line overlay tonight (§7.3). A true crop encode is not a one-night job (§7.1).**

| Route | Result in the file | Main edits | Size | Effort | Risk |
|---|---|---|---|---|---|
| (a) True crop encode | Real 1920×816 etc. | Encoder config, frame start offset, about 37 job-layer sites, playback gates | Unknown, several stubs | Several nights plus many test flashes | Hang while recording; ruined clips |
| (b1) Burnt-in bars | 16:9 file with black bars | No stage or hook found | Unknown | Not a night | Dropped frames, cache faults |
| **(b2) Frame lines in live view** | Normal 16:9 file, crop in post | 3 u32 in sec 6, 3 OSD bitmaps | About 12 B main, about 5–15 KB OSD | **About 2 hours** | **Display only** |
| (c) Metadata crop | Full frame coded, players crop | No crop atom exists; SPS writer not found | Unknown | Research first | Clip displayed wrong |

### 7.1 Route (a): what a true crop touches

**The encoder is generic below one hard-coded layer.**

| Layer | Site | Finding | |
|---|---|---|---|
| Config dump | `0x603d3780..` | Names the struct fields. Video block at cfg+96: `ulBitRate` +0, `ulMaxBitrate` +4, `ulHsize` +16, `ulVsize` +20, `ulMaxHsize` +24, `ulMaxVsize` +28, then `eSamplingYcData`, `usSplitSliceNum`, `ulMaxCodeSize` | [V] |
| **Config builder** | **`0x603d1620`** (called from `0x603d13fb`) | One function, not a table. Size enum at arg+22: 5 C4K, 6 4K, 1 1080, 2 720, 3 640×480, 4 640×360. W/H at `0x603d1742..0x603d17b2`; max code size = W×H×3/8 at (56,a2); max W/H at `0x603d17c7` | [V] |
| H.264 plugin | `0x6131ba3e` (progressive, also `0x6131967a`), `0x61317eb7` (interlace) | W and H rounded up to 16 in code, no size list. So a smaller Vsize is accepted at this level | [V] code; result [I] |
| Rate control | `0x6131b563..0x6131b5e5`, `0x6131cff6`, `0x6131ab61` | Tests Vsize == 2160 and Hsize == 1920, with fallthrough cases and no error return | [V] |
| Size check | `0x6133c5a0..0x6133c6e5` | Timescale and size list (1920×1080, 1280×720, 640×480/360, 3840/4096×2160), otherwise 0x80000007. Caller not traced; decoder side likely | [V] code; role [I] |
| Job layer | `0x603210f7` (W, H from A+878), `0x60315f90`, `0x603160a7`, `0x6031ff83`, `0x60320a02`, `0x6032aec9` and others | Hard-coded switches on the size code at A+878 (6, 3, 4, 8, 9, 7), each setting buffer sizes. **44 candidate `878` immediates, about 37 in `0x6030..0x6041`** | [V] sites; count is a byte scan |
| Aspect from size | `0x603088a0` | 4096×2160 → 10, 3840/1920/1280 → 3, others → 1 | [V] |
| Movie size source | `0x602ccf0b` | Sid 699 picks a slot, sids 700–707/852 hold the size code. It is a setting, not derived | [V] |
| MOV header | Atom names at `0x61370d98..0x613715a4` (`moov`, `tkhd`, `stsd`, `avc1`, `avcC`) | No W/H in those tables. Written from the config by the mux [I] | [V] names |
| Playback parser | **`0x603d80a0..0x603d8119`** | Only the 6 stock W×H pairs map to an enum; anything else takes the error at `0x603d8119` | [V] |
| Playback/edit UI | `0x608379f1`, `0x60a00b20` | Only 1280×720, 1920×1080, 3840×2160; otherwise a log path | [V] |

**Not found:** where the encoder's YC frame address comes from. Changing `ulVsize` alone would encode the top of the frame, not the centre [I]. A centre crop also needs Y and C start offsets (pitch × top row). Without that site the route has no working first build.

Heights would be multiples of 16: 1920×704 and 1920×816, 3840×1408 and 3840×1632 (the ASPECT 1920 row).

**What can go wrong, and whether it lasts [I, except where marked]:**
- Nothing here writes flash. The config is RAM, rebuilt for each recording.
- `0x603d4ea7`, the AVM failure helper, only logs and returns [V]. A bad setup is more likely to end in a hung encoder task or a stopped recording than a clean error. A battery pull clears it.
- Clips: an interrupted recording leaves a MOV without `moov`. Stock's own card-full and power-loss cases are the same kind of damage.
- **The one lasting trap is a saved setting.** A new movie size stored through sids 700–707/852 could make live view fault every time the dial is on Movie. That needs a boot clamp like §3(c), and a recovery path through the stock restore.
- With the sensor mode left alone, nothing changes on the sensor side. Heat and card load stay at or below stock.

### 7.2 Routes (b1) and (c)

- **(b1) Burnt-in bars:** no stage that draws into movie YC was found [I]. A CPU fill of 25–35 % of every frame needs a per-frame hook on the encoder input, which is the same missing site as §7.1, plus cache handling at 4K30. Rejected.
- **(c) Metadata:** `clap`, `pasp` and `tapt` occur nowhere in main [V]. New atoms change `moov` layout. Changing `tkhd` W/H alone scales rather than crops [I]. An SPS crop would be a clean file-level answer, but the code that writes the SPS was not found. Changing stored W/H also trips the playback parser above [V]. Worth one research session; not tonight.

### 7.3 Route (b2): frame lines, recommended

**Replaces the §2 #11 open question: the LV grid selector is `0x60e32406..0x60e32702`.** [V]

- Sid 44 == 1 (movie) forces aspect 3 (16:9), or 1 for movie slot 6 (`0x60e32423..0x60e3245d`). Stills read sid 270.
- The grid value comes from sid 155 (LCD) or sid 447 (EVF), key `0x97f1` for sid 155 (`0x60e3258d..0x60e325ab`).
- Grid value 9 is cleared in movie mode (`0x60e325fe`), so **no aspect frame exists in movie today**. The other values continue to the lookup.
- The lookup at `0x60e326c3` finds `{aspect, list, count}` by aspect, then `{value, bitmap}` by grid value, and draws with `0x60df24d7`. No test for "recording" appears in that path. Whether the recording page calls it is not traced [I].

| Row for aspect 3 | List | `{value, bitmap}` |
|---|---|---|
| `0x6118cc18` | `0x6118c868` | 8/5998, 6/6004, 5/6765, 7/6012, 1/6018 (720×405 class) |
| `0x6118cc60` | `0x6118c958` | 8/6084, 6/6090, 5/6096, 7/6102, 1/6108 (720×480 class) |
| `0x6118cca8` | `0x6118ca98` | 8/6028, 6/6034, 5/6040, 7/6046, 1/6052 (640×360 class) |

The table is chosen by display state at `0x60e32673..0x60e326bd`: `0x6118cc48` when (1020,this) == 1, `0x6118cc00` for state 1 or state 5 with (56,..) 1 or 2, otherwise `0x6118cc90` [V]. Which state the LCD is in during movie mode was not traced, so patch all three.

Value 8 is the diagonal grid (checked on a contact sheet), the least useful one to lose [I]. All three list slots are free in `releases/v0.25/edits.json` [V].

**Patch, data only:**
- 3 new bitmaps, same mode-11 format and index 124 as the stock grids: full-width lines at 65:24 and 21:9 in one image, with a small tick to tell them apart. Add through `patches/aspect/osd_icons.py`, which already encodes this format and takes unused placeholder ids. Bank bound per §1g [V].
- 3 u32 edits: the bitmap of value 8 in the three lists.
- Use: Displayed Grid = the diagonal option, in Movie mode. 16:9 stills get the same lines, which is harmless. Stock files; crop in post.
- Lines first. Solid bars depend on how this layer blends, which is unknown.

**Risk:** display only. No encoder, settings or boot-path change. The worst case is a wrong or missing grid, and Grid Off escapes it [I].

**Camera test:** Movie mode, Displayed Grid diagonal. Lines visible on standby? While recording? Check the line positions against a crop of the recorded file. Grid Off: no lines. 16:9 stills: lines shown; 4:3: stock grid.
