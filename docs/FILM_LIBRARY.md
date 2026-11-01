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
| 1 | **v2 loader**: extend patches/sd_bundles. Read LIBRARY.BIN (≤ 16 KiB; malloc class 3), fall back to BUNDLES.BIN, write table + names. Name table with defaults at 0x61242e00. Emulator verifier extended from `ep7_verify_sd_bundles.py`: valid/reject cases, names NUL-terminated on every path | emulator PASS; no-card = byte-identical stock table |
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
