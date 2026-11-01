# Film Simulation library (format v2) and on-camera "Film Sim" selector (E-P7 1.1)

Offline design only. No camera was contacted, no SD-update-named file was written, nothing was committed,
and no firmware patch was built. [V] = read from the decoded main (SHA `5dd9af16…`) with `tools/dis.sh` or byte
dumps. [I] = inference. [?] = open.

- Compiler: `tools/ep7_library.py` (desktop). Example input: `bundles/library_example.json`.
- Mock-ups: `sim/screens/film_sim_menu.json`, `sim/screens/film_sim_slot.json` → `generated/mock/`,
  `docs/img/ui_film_sim_menu.jpg`, `docs/img/ui_film_sim_slot.jpg`.

## 1. Summary

- **Labels can be runtime text. No OSD (component 0x101) edit is needed.** An option-list entry is
  `{u32 value, u16 kind, u16 id, u32 text}`. Kind 5 draws the ASCII C string at `text` at draw time
  (§5.1). 3659 stock entries already work this way, for example the EV list "-3.0" … "+3.0".
- **Cheapest credible selector: relabel the eight Colour/Mono Profile entries** in the stock Picture
  Mode lists. Each entry changes from kind 4 (string id) to kind 5, with `text` pointing at a name table
  that the card loader fills.
  - The values (54–59, 64, 65) stay the same, so no setter, validator or consumer changes behaviour.
  - Picking "Classic Neg" in Picture Mode or Live Control simply selects COLOR1. The bundles patch then
    renders COLOR1 with the look assigned to it.
  - This gives 8 simultaneous film sims, with names loaded from the card. The assignment is made on the
    desktop (phase 1).
- Choosing among more than 8 looks on the camera means either repurposing a setting (option a) or adding a
  custom page (option c). Both are phase 3 (§5.3–5.5).

## 2. File format v2: `C:\EP7MOD\LIBRARY.BIN`

Little-endian. The total size is 592 + 96·N + notes, at most 16384 B (the largest fixed-block pool class,
docs/SD_BUNDLES.md §1). Typical sizes: 18 looks = 2.5 KB, 64 looks = 6.7 KB.

| Offset | Size | Field | Rule |
|---|---|---|---|
| 0 | 4 | magic `EP7B` | same family as v1 |
| 4 | 2 | version = **2** | v1 loader requires 1, so it rejects v2 |
| 6 | 2 | header length = 64 | |
| 8 | 4 | firmware build = 1100 | |
| 12 | 4 | payload length = file − 64 | |
| 16 | 4 | CRC-32 (zlib) over bytes 0–15 followed by 20–end | **same rule as v1** |
| 20 | 4 | main SHA-256 prefix `5dd9af16` | same as v1 |
| 24 | 2 | n_looks, 1..64 | |
| 26 | 2 | look record size = 96 | |
| 28 | 2 | slot table offset = 64 | |
| 30 | 2 | resolved table offset = 80 | |
| 32 | 2 | looks offset = 592 | |
| 34 | 2 | notes offset (0 = none) = 592 + 96·N | |
| 36 | 2 | notes length | |
| 38 | 2 | bundle slot size = 64 | ABI check |
| 40 | 4 | `layout_crc`: CRC-32 of canonical `layout.json` (slot size, slot names, field offsets and lengths) | a file built for another ABI is rejected |
| 44 | 20 | zero | reserved |
| **64** | 8 | **slot assignment** `assign[8]`, COLOR1–4 then MONO1–4: look index, or 0xFF = empty (all-zero entry, stock) | |
| 72 | 8 | zero | reserved |
| **80** | 512 | **resolved table**: entry k = P(look assign[k], slot k) (§3), or 64×0 | **byte-identical to the v1 payload** and to `build_table()` |
| **592** | 96·N | **look records** | |
| notes | … | repeated `{u8 look, u8 len, len bytes UTF-8}`, at most 200 B each, at most one per look | not read by the camera; covered by the CRC |

**Look record (96 B):**
- +0: 64-byte canonical bundle in the layout.json ABI.
- +64: name[16]: 1–12 printable ASCII characters (0x20–0x7E except `@`), NUL padded. No leading or
  trailing space.
- +80: class: 0 = colour, 1 = mono (the recipe has `mono_filter`).
- +81: slot mask: bit0 = may go in a COLOR slot, bit1 = may go in a MONO slot.
- +82..95: zero.

The canonical bundle depends on the class:
- **Colour look:** the COLOR-slot entry exactly as `slot_entry('COLOR1')` builds it. In addition,
  sat[12] is stored at +33 with the colour byte left at 0. MONO-capable only if sat is within −5..5.
- **Mono look:** the MONO entry exactly as `slot_entry('MONO1')` builds it.

**Why the names are restricted:**
- `@` starts an OSD symbol escape (`@A0xx@`).
- The label widener 0x60df2618 sign-extends each byte (`extb`) [V], so bytes ≥ 0x80 would become garbage
  code points.
- The label buffer is 66 B = 33 UTF-16 code units (§5.1), and the copy is not bounded. A name longer than
  32 characters would overrun the caller's stack. 12 characters + NUL in a 16-byte zero-padded cell is far
  inside that limit.

**Compatibility with v1:**
- Same magic, header words 0–23, CRC rule, per-byte range rules (generated from layout.json by
  `patches/sd_bundles/build.py`), and load-once-at-mount concept.
- The resolved table is a v1 payload. A v2 loader can therefore be the v1 loader with a variable length,
  plus a name copy.
- A v1-only camera ignores LIBRARY.BIN (wrong path, and wrong version and size anyway).
- A v2 loader should try LIBRARY.BIN first, then fall back to BUNDLES.BIN. With BUNDLES.BIN, names stay
  at their defaults.

## 3. Placement rule P(look, slot), i.e. the "slot assignment"

| Slot | Colour look | Mono look |
|---|---|---|
| COLOR1–4 | canonical; +33..+44 := 0; +32 := 0; flags := 2 (H/L) | rejected |
| MONO1–4 | canonical; +32 := 1; flags := 3 (render colour + H/L). Needs mask bit1 | canonical (flags 0) |

`tools/ep7_library.py` asserts **P(record, slot) == `patches/bundles/build.py` `slot_entry()`** for every
look and every slot class it allows. `--check` re-derives every resolved entry from the looks. On the
example, the resolved table equals `build_table()` of the equivalent bundles JSON (checked).

## 4. Loader rules (v2 camera loader and `--check` mirror)

Reject the whole file, leaving table and names untouched, on any of the following:
- size outside 592..16384;
- magic, version, header length, build, payload length, CRC, SHA prefix, the six layout words or
  `layout_crc` wrong;
- reserved bytes not zero;
- n_looks outside 1..64, or a notes block that does not end the file exactly;
- any look byte outside its v1 range;
- a bad name (characters, padding);
- class/mask/reserved bytes wrong, or a mono look with the COLOR bit set;
- an assignment index ≥ N;
- a resolved entry ≠ P(look, slot) (`--check` checks this; a minimal camera loader may range-check the
  table only, as v1 does).

On success:
1. Copy the resolved table to 0x60210900 (as v1).
2. For each slot k, copy the 16-byte name of look assign[k] into name cell k (§5.2). An empty slot keeps
   its default.

`--check` was mutation-tested: CRC flip, hue +8 with a valid CRC, `@` in a name, unterminated padding,
index 99, table ≠ P, mono look in COLOR1, version 1, truncation, layout CRC, reserved header byte and
class 2 are all rejected.

### Compiler

```
.venv/bin/python -I tools/ep7_library.py bundles/library_example.json --out generated/library --list
.venv/bin/python -I tools/ep7_library.py --check generated/library/EP7MOD/LIBRARY.BIN --list
```

Input JSON:
- `include_recipes`: `"all"` or a list. Adds the shipped recipes with default names (≤ 12 characters).
- `looks`: key → `{recipe, name, notes, wb, grain, effect, vignette, sat}`. These keys mean the same as in
  bundles JSON. `render_colour` is derived from the slot.
- `slots`: COLOR1–4/MONO1–4 → look key.

The compiler rejects duplicate names (case-insensitive), unknown keys, recipes or slots, and any value
`build.py` rejects. It never writes into `DCOLYMP/`, never writes `E142*` names, and never writes outside
`--out`. Example output: 18 looks, 2537 B.

## 5. Menu design

### 5.1 How option lists, labels and setters work (trace, starting from the aspect work)

- **[V] List entry = `{u32 value, label source}`**, where the label source is
  `{u16 kind, u16 id, u32 text}` (12 B per entry, docs/ASPECT.md §1). The word that ASPECT.md calls "cond"
  is actually a `char*`.
  - Every kind-4 entry points it at an empty string. For example, 0x611799dc holds `""`, and so do
    0x611b6f68 and 0x61163e78.
  - Item records use the same 12-byte label source.
  - The main-menu item records are 36 B: `{key, label src}`, `{list, count, 0}`, `{text?, list2, count2}`.
- **[V] Label builders:**
  - 0x60df250b looks up a value in a list (`a1` list, `d1` count, `d0` value). It has 277 call sites.
  - 0x60df25b5 takes a ready label source (239 call sites).
  - Both fill a label `{u16 kind, u16 bitmap, u16 string, …, +8 UTF-16[33]}`:

  | kind | label | proof |
  |---|---|---|
  | 3 | bitmap id | Picture Mode/drive lists |
  | 4 | string id (OSD string table) | Image Aspect |
  | 1, 2 | string id **and** text, e.g. text "0.3" + string 247 "sec" | self-timer list 0x61179f54 |
  | **5, 6, 12** | **text only**: `strlen(text)` (0x600daed9), then a byte→UTF-16 widen (0x60df2618) into label+8, at draw time | EV list 0x61179b0c ("-3.0"…"+3.0", "0.0" is kind 12), ±10 list 0x61179dbc |
  | 7, 8 | bitmap + text (0x60df250b only) | |

- **[V] Runtime text is already used in the value column.** The item value drawer is 0x60e8af1c, with
  `d0` = item key:
  - Default path: getter vtable, then 0x60df250b on the item's list.
  - Keys 3487 and 3488 (Artist / Copyright Name) build a kind-5 label from the copyright text store
    (0x60e042b6). Names longer than 8 characters are cut to 8 + `...`.
  - Keys 5054–5057 do the same for Lens Info names.
  - So the renderer draws kind-5 labels in menus. The 8-character cut is specific to that code, but it
    hints that the value column is narrow.
- **[V] Setter and validator:** selecting an entry writes its `value` to the item's setting. Allowed values
  are fixed by the static validator 0x604cc98c (docs/BUTTONS.md §2). A relabel changes only kind and text,
  so the setter, validator and every consumer behave as stock. Adding new values (option a) also requires
  validator edits.
- **Answer to "string ids only, or runtime text?":** runtime text works, through kind 5 plus a pointer
  that we control. The text is read at every draw (it is not cached in the list), so a loader that writes
  the names changes the labels with no list relocation. Label buffer limit: 32 characters.

### 5.2 Recommended: relabel the 8 profile entries (phase 1–2)

> **Superseded by §8.** The name table below sits in section 6 and is written by the loader at run time.
> Camera testing (docs/SD_V2_CRASH.md) now rules out runtime writes to 0x60020020–0x6191ffe0. The entry
> inventory is still valid; §8.3 gives the corrected list.

Profile entries found [V] (value, kind 4, string 2749–2751/3626, 2757–2759/3627 or their `@A08x@` variants):
- 12-byte lists:
  - 0x6116874c–0x611687a0 (8, inside the list that also holds Color Creator, value 21);
  - 0x61169340–0x61169364 (COLOR1–4);
  - 0x61169124 / 0x61169928 (COLOR1, MONO1);
  - 0x611895c8–0x6118961c (8, MONO first; list referenced from code 0x60e26f92);
  - 0x611df788…
- 36-byte main-menu items: 0x611bdb18–0x611bdc14 and 0x611cb284–0x611cb380 (two menu trees, each 8).

**Edit per entry:** `kind` 4→5 (u16 at +4) and `text` → name cell k (u32 at +8). That is 6 bytes, in
place: no relocation, no count change, about 40 entries. The string id stays, unused.

**Name table:** 8 × 16 B in the section-6 FF tail, proposed at **0x61242e00–0x61242e80**. This is inside
the 0x61242d00–0x61242f00 gap that sd_bundles currently leaves as a guard; keep 16 B guards. Section 6 is
also where the lists live, so whenever a list is loaded its pointers are valid.
- The cells must hold **build-time defaults**, NUL-terminated and never FF, because strlen is unbounded:
  "Color Profile 1" … "Color Profile 4", "Mono Profile 1" … "Mono Profile 4" (15/14 characters, string
  2862 precedent).
- Without a card the camera therefore looks stock (in English).

What the user sees: the mock-ups.
- `ui_film_sim_menu.jpg`: Picture Mode list with badges + look names.
- `ui_film_sim_slot.jpg`: Live Control column with the COLOR1 badge; its option label reads "Classic Neg".
- Badges (bitmaps 4344–4355, 7528–7531) and the LV info icon stay stock.

Not covered by the relabel:
- Screens that draw the profile string by id directly, such as the Color Creator/profile edit title and
  the playback info. These keep "Color Profile 1" [I]. The result is inconsistent, not a crash.
- EXIF keeps the stock picture-mode value.

### 5.3 Option (a): repurpose a rarely used setting's list as "Film Sim" (phase 3)

- Candidates with option lists [V]:
  - 433 Wind Noise Reduction (movie audio, 4 values);
  - 695 Recorded Clip Volume (0–5);
  - 843 Recorded Clip Sound (2).
  - Not 1334 Noise Filter: it affects stills.
- Mechanism: relocate the list as the aspect patch did, and use N kind-5 entries pointing at the look
  names.
- Costs:
  1. More than the native value count needs validator edits, plus a guard so the original consumer (audio)
     never sees the new values.
  2. A new hook that copies the chosen look into the active slot (P() on the camera, about 30 instructions)
     when the value changes, or at capture time.
  3. The original function is lost.
- The setting persists for free.
- A dormant multi-model setting ID would avoid costs 1 and 3, but proving that it is dormant is research
  work [?].

### 5.4 Option (b): cycle looks with a button (phase 4, optional)

- [V] No function code maps to a profile switch. The action `LV_CTRL_PROFILE` (76) exists but no
  function-table entry points to it (docs/BUTTONS.md).
- Cycling would need either a new function-table entry and action handler, or a handler that steps
  picture mode 54→55→56→64→57….
- With the relabel in place, the Live Control label shows the name. Without it, the switch is blind.
- The buttons patch was dropped from test 4 (WORKLOG), so this reopens a parked area. Lowest value per risk.

### 5.5 Option (c): a custom page with per-slot look selection (phase 3+)

- A page record such as 0x6117b1b4 (`{u16, u16 nitems, items, ?, ndesc, desc}`) with 8 items and
  per-item kind-5 lists over the N looks.
- Needs 8 persistent settings (storage, defaults, validator entries) or our own persistence, for example
  writing the assignment back to the card (fileif supports writes; untested).
- Most data and the most unknowns. Worth it only after (a) proves the setter/hook path.

## 6. Phased plan

| Phase | Work | Exit check |
|---|---|---|
| 0 (done) | Format v2, `tools/ep7_library.py` (+`--check`), mocks, this trace | compile + mutation checks pass |
| 1 | (*superseded by §8.6*) **v2 loader**: extend patches/sd_bundles. Read LIBRARY.BIN (≤ 16 KiB; malloc class 3), fall back to BUNDLES.BIN, write table + names. Name table with defaults at 0x61242e00. Emulator verifier extended from `ep7_verify_sd_bundles.py`: valid/reject cases, names NUL-terminated on every path | emulator PASS; no-card = byte-identical stock table |
| 2 | **Relabel**: scanner that pins every profile entry (value ∈ {54–59, 64, 65} ∧ profile string id, all lists and both item trees). Edit kind + text. Run 0x60df250b/0x60df25b5 natively on the patched data, checking that the label equals the name and the stack/registers equal stock | emulator PASS; first camera check: menu and LC show names, no card → defaults |
| 3 | In-camera choice among N > 8 looks: option (a) on a proven-safe setting, or (c) | per design review |
| 4 | Optional (b) button cycle | — |

## 7. Risks

1. **Section-6 DRAM writability and coherency** [I]: the same assumption as the SD loader (docs/SD_BUNDLES.md
   §3). If writes fault, a valid card crashes at mount; remove the card to recover. A stale name on another
   core would only show the old label.
2. **Unbounded strlen into a 66-byte stack buffer** [V]: a name cell without a NUL would overflow the
   caller's stack. Mitigations: defaults in the image, loader writes whole zero-padded 16-byte cells, the
   12-character limit is checked twice (desktop and loader).
3. **Kind-5 support on every screen that uses these lists** [?]: LC, SCP and the menu value column. A
   renderer that special-cases kind 4 would show a blank label. Expected to be blank, not a crash, because
   kind 5 is a stock kind. Emulate each consumer in phase 2, and check on the camera first.
4. **Column width** [?]: the Artist Name path cuts to 8 characters + `...`. A 12-character name may be clipped
   in narrow columns. Mitigation: keep names ≤ 10 characters where possible; the compiler could warn.
5. **Symbol escapes / font** [?]: `@` is forbidden. Whether kind-5 text parses `@A0xx@` is untested (not
   needed). Only ASCII glyphs are verified (font res 35).
6. **Mount timing**: names change when the card mounts. A menu that is already open may show defaults until
   it redraws. Cosmetic.
7. **Mixed labels**: some screens use string ids directly (§5.2). Languages other than English show English
   defaults.
8. **ABI drift**: `layout_crc` ties a file to the layout.json it was built for. Changing layout.json
   invalidates old LIBRARY.BIN files on purpose.
9. **Footprint**: about 40 × 6-byte data edits in section 6, plus 128 B of names and a larger loader. No
   code on the capture path changes beyond what bundles v0.2 and later already do.

## 8. Phase 2 redesign: card-loaded labels with no runtime writes into the image

New constraint (camera tests, docs/SD_V2_CRASH.md): do not store anything at run time into the flash-loaded
range 0x60020020–0x6191ffe0. Writable state lives at ≥0x61b2xxxx: the heap pools, or .bss such as the
2-byte padding at 0x622cbcc2. That rules out §5.2 as written, because its name table at 0x61242e00 is in
section 6. Design only: nothing built, no camera contact, no `E142*` file, no commit.

### 8.1 Verified facts used here [V]

- **Builder A, 0x60df250b** (lookup by value, sets a2 = entry+4):
  - kind-4 path: 0x60df2541 `cmp 4` → 0x60df2559 copies the string id (2,a2) → (4,a3) → **0x60df255f**;
  - then compares for the text kinds, and kind 4 falls through to `ret [d2,d3,a2,a3],24` at **0x60df25b2**;
  - text kinds go to 0x60df2589: clear 66 B at label+8 (call at 0x60df258f), `strlen((4,a2))` (0x600daed9),
    widen 0x60df2618.
- **Builder B, 0x60df25b5** (ready label source, a2 = source): the same shape.
  - Kind-4 id copy at 0x60df25d6 → **0x60df25dc**, then kind 4 falls through to `ret [d2,a2,a3],20` at
    **0x60df2615**.
  - Builder B does not save d3, so a hook must not touch d3.
- In both builders, a2 points at `{u16 kind, u16 id, u32 text}` at the hook point, so **text = (4,a2)**.
- Both hook points have the same 6 stock bytes, `f0 63 a0 01 c8 xx` (`movhu (a3),d0; cmp 1,d0; beq`).
  - The only branches into them land on their first byte: 0x60df2557 → 255f and 0x60df25d4 → 25dc. Nothing
    branches into bytes +1..+5 (ep7_xref).
  - The ret sites are reached only from inside each function (25b2 from 2587 and 25ab; 2615 from 25f0).
- **Widen 0x60df2618** sign-extends bytes and does not write a terminator. Termination comes from the 66-B
  clear (33 UTF-16 units).
- **The text word of kind-4 entries is data only.** Every profile entry points at a per-tree `""`:
  - 0x61163e78 (1977 refs), 0x611b6f68 (2707), 0x611c465c (2729), 0x611895c4 (17), 0x611df608 (71);
  - none of these addresses appears as a literal outside the sec-6 data area (byte search);
  - in stock, many different `""` addresses are interchangeable.
- **Profile label sources in sec 6** (scanner: kind 4, profile string id, text → NUL). Addresses are of the
  label source; the text word is at +4.

  | List | Entries | Slot order |
  |---|---|---|
  | 0x61168750 +12k | 8 | C1 C2 C3 C4 M1 M2 M3 M4 |
  | 0x61169128, 0x61169134 | 2 | C1, M1 |
  | 0x61169344 +12k (`@A08x@` ids) | 4 | C1–C4 |
  | 0x6116992c, 0x61169938 | 2 | C1, M1 |
  | 0x611895cc +12k | 8 | M1–M4, C1–C4 |
  | 0x611bdb1c +36k (item tree 1, `@` ids) | 8 | C1–C4, M1–M4 |
  | 0x611cb288 +36k (item tree 2, `@` ids) | 8 | C1–C4, M1–M4 |
  | 0x611c1b44 +8k, 0x611cf2b0 +8k (bare 8-B sources, consumer unknown) | 8+8 | C1–C4, M1–M4 |
  | 0x611df788 +12k (mixed list: values 58/59 str 1163, then 54–56, then 2049…) | 3 | C1–C3 |

  The values are 54/55/56/64 = COLOR1–4 and 57/58/59/65 = MONO1–4. Note that value 59 is MONO3 and 64 is
  COLOR4, so the values are not in slot order.
- **Section 6 tail** 0x61242d00–0x61242f00 is all FF in stock. The one static "reference" into it
  (0x607a21ea → 0x61242e8a) is the middle of a `call` instruction at 0x607a21e7, so it is a false positive.
  The builders, the lists and this tail are all in section 6 (load 0x60ba7000–0x61243000).

### 8.2 Options evaluated

| # | Idea | Verdict |
|---|---|---|
| 1 | Kind-5 entries whose text points at fixed .bss cells that the loader fills | **Rejected.** (a) No unused 128-B .bss block can be proven: SD_V2_CRASH §3.1 found only 2 B of provably unused padding, and every other gap sits inside a struct or array. (b) If stock code does use the cells, the label is whatever bytes are there, and strlen is unbounded into a 66-B **stack** buffer, so a missing NUL overflows the stack (§7 risk 2). (c) With no card, before the first half-press, or with a bad file, the cell is empty and the label is **blank**, not stock. Showing defaults would need a loader write on every boot, and the defaults would be English only. |
| 1b | Kind 1/2 (string id + text) pointing at a .bss cell | Rejected. It has the same fixed-address problem. How the renderer joins id and text ("0.3" + "sec") is unknown, so a loaded name would probably show as "Classic NegColor Profile 1". |
| 2 | Hook in builders A and B: when a marked entry is drawn and names are loaded, emit a kind-5 label from the heap block | **Chosen** (§8.3). The flash edits are build-time only. The runtime reads only heap and .bss. With no card, the camera runs the stock kind-4 path byte for byte. |
| 2b | Same hook, keyed on the profile string ids (24 ids, including `@` and short variants) instead of markers | Fallback. It needs no data edits, but it also renames every builder-drawn screen that uses those ids (titles, playback), and the slot comes from an id table. Use it only if the marker edits turn out to matter somewhere. |
| 3 | Repoint the OSD runtime string pointer table (base 0xa407f540, string 2749…) at heap names | Rejected. That table is a runtime write into a loaded resource region, the same class of risk as the image, and its writability is unproven. It is also per-language, and it affects every use of the string. |
| 4 | The value-column special case, as used for Artist/Lens Info (0x60e8af1c) | Rejected. It covers only the menu value column, not the Picture Mode list, LC or SCP, and it is not a list path. |

### 8.3 Chosen design: marker entries + label-builder hook

**Build-time flash edits (none written at run time):**
1. **Marker cells**: 8 bytes of 0x00 at **0x61242e00–0x61242e07**, one per slot: k = 0..3 COLOR1–4, 4..7
   MONO1–4. Each cell is a valid `""` string, so a marked entry is equivalent to stock for any reader that
   treats the text as a string.
2. **Entry edits**: change the text word (label source +4) of each selected entry from its tree's `""` to
   `0x61242e00 + k`. The kind and string id stay 4/stock.
   - Phase 2a covers the 40 selection entries: lists 0x61168750, 0x61169128/34, 0x61169344, 0x6116992c/38,
     0x611895cc and both item trees. The edits are 4 B each, 160 B in total.
   - The 16 bare sources (0x611c1b44, 0x611cf2b0) and the 0x611df788 list wait until their consumers are
     identified.
3. **Hook sites**: 0x60df255f and 0x60df25dc, 6 B each → `dc <rel32>` (jmp hookA or hookB) + `cb` (nop).
4. **Hook code** at **0x61242e10–0x61242ef0**. This is two copies of the body below, about 85 B each.
   AM33 has no stack-free bsr, and the scratch registers differ between the two builders.
   - Guards: 0x61242d00–0x61242e00 and 0x61242ef0–0x61242f00 stay FF.
   - The aspect list at 0x61242f00 is unchanged.
   - Claim the range in CODE_SPACE_MAP.md when this is built. It takes the old guard range of the dead v1
     loader, so the v1 loader must stay retired.

**Body** (uses only d0, d1, a0, a1; no stack; no `setlb` loops, so LIR/LAR are untouched):
```
hookX:  movhu (a3),d0 ; cmp 4,d0 ; bne replay        ; label kind just set by stock
        mov (4,a2),d0 ; add -0x61242e00,d0 ; cmp 8,d0 ; bcc replay   ; k = text - MARK, unsigned < 8
        movhu (0x622cbcc2),d1 ; cmp 0,d1 ; beq replay ; cmp 0xad40,d1 ; bhi replay   ; same decode as tbl_base
        mov d1,a0 ; add 0xa1f8d7ff,a0                 ; a0 = persistent block P (uncached class-1 pool)
        mov (672,a0),d1 ; cmp 'EP7N',d1 ; bne replay  ; names present
        asl 4 on d0 ; add d0,a0 ; add 544,a0          ; a0 = P+544+16k
        movbu (a0),d1 ; cmp 0,d1 ; beq replay         ; empty slot -> stock label
        mov 5,d0 ; movhu d0,(a3)                      ; label kind 5 (string id at +4 left as is)
        clear 33 halfwords at a3+8 (unrolled/counted, no setlb)
        copy at most 15 bytes from a0 as u16 to a3+8.., stop at NUL ; terminator guaranteed by the clear
        jmp RET_X                                      ; A: 0x60df25b2, B: 0x60df2615
replay: movhu (a3),d0 ; cmp 1,d0 ; bne +5 ; jmp T1_X ; jmp NEXT_X
        ; A: T1 0x60df2589, NEXT 0x60df2565 ; B: T1 0x60df25f2, NEXT 0x60df25e2
```
- **Returned d0 [I].** Stock returns the kind (4) on the kind-4 path and widen's d0 on the text path, so
  callers cannot depend on it. The hook returns 5.
- **Copy limits.** The copy is capped at 15 units and the clear is done first. Even a corrupt heap block can
  therefore produce at most 15 characters plus NUL in the 33-unit buffer, with no strlen on heap data.

**How names reach the heap (v3 loader; SD_V2_CRASH §3.2 already keeps a class-1 block and publishes
handle h at 0x622cbcc2):**
1. Parse LIBRARY.BIN under the §4 rules, into a temporary buffer (≤16 KiB, class 3).
2. Persistent block P = the class-1 1024-B block:
   - +0..31 header;
   - +32 resolved table (512 B, as v1);
   - +544 names[8][16], each zero-padded, 1–12 printable ASCII characters, no `@`; an unassigned slot is all
     zero;
   - +672 u32 `EP7N`.

   Write `EP7N` last, after the names. For BUNDLES.BIN (v1), zero +544..+676, so the names stay stock.
3. Check that P is 4-aligned and inside the pool, then store h with a single `movhu`, as the very last step.
   P is never freed, so readers never see a partly written or freed block.
4. Free the temporary buffer.

**Behaviour:**
- **No card, no file, bad file, BUNDLES.BIN only, or before the first half-press** (the loader trigger):
  h = 0 / 0xFFFF, or `EP7N` is absent. The hook replays stock, so the labels are the stock localized strings,
  `@A08x@` badges included.
- **Valid LIBRARY.BIN:** after the first half-press, the next redraw shows the look names on the marked
  entries. Empty slots keep their stock labels. Values, setters, validator and capture are unchanged.

### 8.4 Risks

1. **[V] The kind-4 path is hooked for every list** (277 + 239 call sites). A non-marked entry fails at the
   `text − MARK < 8` test and replays the stock 6 bytes exactly. The emulator must check this over **every**
   list entry in sec 6.
2. **[?] `@`-variant entries lose their badge** (lists 0x61169344 and both item trees) when a name is shown.
   Whether kind-5 text parses `@A08x@` is untested.
   - Optional 2b: have the hook prefix the 6-character escape for those string ids.
   - Test first with a debug name, using an internal test hook, not the user format, which forbids `@`.
3. **[?] Kind-5 support on each screen** (LC, SCP, menu value column, as in §7 risk 3). The new point is that
   this is **gated by the card**: removing LIBRARY.BIN restores stock without reflashing.
4. **[?] Other label paths.** Widen has 17 more callers (0x60df6753, 0x60df9bc6, 0x60e0e6b3, …). They build
   from getters, not from kind-4 entries, so screens drawn through them keep stock labels. That is
   inconsistent, but not a crash.
5. **[I] Heap block lifetime.** The block depends on SD_V2_CRASH §3.2 (one leaked class-1 block, pool
   headroom unknown). The hook reads it uncached from the UI task: a halfword h plus bytes, with no lock.
   Publication order is stores to uncached memory in program order on the loading core.
6. **[?] Text field consumers.** If some code outside the two builders did compare the `""` pointer of a
   kind-4 entry, a marked entry would differ. The byte search found no such literal; the 2b fallback avoids
   the question entirely.
7. **Width** (§7 risk 4) and **mount timing** (names appear only after the first half-press) are unchanged.

### 8.5 Emulator gate (before any camera build)

Run 0x60df250b and 0x60df25b5 natively on stock and patched images:
- (a) h = 0;
- (b) h = 0xFFFF;
- (c) a valid block with names;
- (d) a valid h without `EP7N`;
- (e) a 16-byte name with no NUL;
- (f) an empty slot;
- (g) every list entry in sec 6 with h valid.

Expected results:
- (a), (b), (d), (f), (g) for unmarked entries: the label (8 + 66 B), d2/d3/a2/a3, sp and the stack are
  identical to stock.
- (c): the label is identical to stock's output for a kind-5 entry whose text is the name.
- (e): exactly 15 characters, then NUL.

Also check that no store is made outside the label and that d3 is preserved in builder B.

### 8.6 Camera test plan (each a separate flash on the last camera-proven base, with the SD restore ready)

| Step | Build / card | Expect | Fail action |
|---|---|---|---|
| 0 | Prerequisite: v3 loader (SD_V2_CRASH P3–P5) passes with BUNDLES.BIN | — | do not start |
| 1 | + markers, entry edits, hooks; card **without** EP7MOD | Every Picture Mode list, LC, SCP, both menu trees and Color Creator show the **stock** labels and badges; scroll every list; 5 power cycles; shoot COLOR1 | crash → hook replay bug: reflash the base |
| 2 | Same build; LIBRARY.BIN with COLOR1 = "Classic Neg", MONO2 = "WWWWWWWWWWWW" (12-character width test), others empty | Before the first half-press: stock. After it: the names on those two entries, the rest stock; LC and SCP too; note any clipping or blank labels and badge loss; shooting unchanged | blank or garbled → remove the card (stock again), report the screen |
| 3 | Corrupt LIBRARY.BIN (CRC flip) | Stock labels; the flashed table is used | — |
| 4 | Remove the card, power cycle | Stock labels | — |
| 5 | Switch the language to non-English with a valid card | The names stay; other entries are localized | — |
| 6 | Open the Picture Mode menu before the first half-press, then half-press and reopen it | Defaults, then names (cosmetic) | — |

Only step 1 can need a reflash. Every later failure mode depends on the card and is recovered by removing the
card.
