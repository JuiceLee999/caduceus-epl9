# Still aspect ratios: XPan 65:24 and 21:9 (E-P7 1.1)

Offline static analysis and emulation only. No camera was contacted, no SD-update-named file was
written, nothing was committed. Main = `analysis/ep7_1100/00_0100_406a0020.decoded.bin`, base
`0x60020020`.

Evidence labels:
- **[V]** read directly from the image (byte dump or `tools/dis.sh`), or executed natively in the emulator.
- **[I]** inference: consistent with the data, not proven.
- **[?]** open question.

Patch: `patches/aspect/build.py` writes `patches/aspect/edits.json`. That file holds 101 edits, 950 bytes,
all in component 0x100. The script also runs 136 emulator and parse checks, and all of them pass.
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
| 8 | "Image Aspect" icon (SCP / LV info) | Lists of (value, bitmap) pairs at 0x6123dbc4 (white 477/476/478/479/2422) and 0x6123dbec (green 472/471/473/475/2421), duplicated at 0x6123ed6c/0x6123ed94; descriptors `{id 0x1ff/0x200, listA, listB, count 5}` hold the pointers at 0x6123dd08/0x6123ddb8/0x6123f180/0x6123f43c. **Only ids 1,3,2,9,4** | [V] data |
| 9 | Menu label | String id taken from the option list (sec-6 data) | [V] |
| 10 | Playback edit "Aspect" (string 563) | Separate list at 0x61241ddc (3:2/16:9/1:1/3:4); crops an existing JPEG; not the setting | [V] data; [I] role |
| 11 | LV grid bitmaps 5996–6143 (720×480 / 640×480 / 720×405 / 480×480 / 360×480) | Selection code **not located** | [?] |
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
- Not changed: the icon lists (#8), the playback edit list (#10), the LV grid bitmaps (#11).

### What the user would see [I]
- Menu: "Panorama" and "Wide" after 3:4.
- JPEG: 5184×1920 / 5184×2224 (and the smaller sizes), if no unpatched consumer is left.
- ORF: full sensor data with AspectFrame = the new centred crop. ExifTool would print AspectRatio "7:6"/"6:5" (it decodes
  the id, not the dims). Adobe/other converters that honour the frame crop get the new crop.
- LV and info screen: S1–S6 and the rect tables give the new frame. The aspect icon for ids 6/7 has **no entry**.
  What happens on a miss is unknown (blank is likely).

## 4. Emulator checks (`python3 patches/aspect/build.py`, 137/137 PASS in v0.4)

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
4. **Icon lookup miss** (#8): behaviour is unknown. Mitigation: relocate both icon lists (+2 entries each, reusing e.g. 16:9
   bitmaps) and bump the count to 7.
5. **17:9 filter unknown** (§1): if the filter hides entries by **index**, the new order could expose 17:9 or hide "Wide".
   Check on camera first. A fallback is to put 17:9 back at index 5.
6. **Art filters / bracketing / multi-exposure / digital tele-converter (setting 34)**: not traced. These may carry their
   own per-aspect geometry.
7. **Unverified section residency assumptions**: sec-1 and sec-6 FF tails are inside the loaded ranges
   (`tools/ep7_code_space.py`); the sec-6 tail has a few static false-positive hits (none in 0x61242f00–0x61242f60).
8. The 3968-px (w,h,code) table and the RAM `.data` copies are patched for consistency. Their users on E-P7 are not traced.

Next steps: trace the 17:9 menu filter and the icon-miss path; locate the LV-grid bitmap selector; test once on a
camera with JPEG+ORF in each new aspect (check the JPEG dims, the ORF 0x1113 frame, the LV frame, the playback and the info icon).
