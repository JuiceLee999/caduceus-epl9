# Button remapping and arrow-pad customisation (E-P7 1.1)

Offline static analysis plus emulator checks. No camera contact. Nothing committed.
**[V]** = read directly from the decoded main (`tools/dis.sh`, byte dumps) or executed natively in the
emulator. **[I]** = inferred, not executed. **[W]** = from web/manual research.

## 1. How a button press becomes a function

```
key event --0x60cc9790--> key code --table 0x60f389a8--> button sid --getter--> FUNCTION CODE
          --(full buttons only: filter 0x60cc8ad3)--> function table 0x60f38af8 --> ACTION id --> state handlers
```

- **[V] Buttons are settings.** Each assignable button is a settings ID (sid). Its value is a
  *function code*: a number such as 568 Peaking, 3474 Magnify, 3552 ISO/WB or 3200 Off.
- **[V] Key table** `0x60f389a8`: 21 records of 16 bytes, `{u32 keycode, u32 sid, u32 sid_alt, u32 full}`.
  Read by `0x60cc87c8` (key → sid) and `0x60cc8838` (sid → `full`).

  | keycode | sid | full | | keycode | sid | full |
  |---|---|---|---|---|---|---|
  | 15 | 47 | 1 | | 4 | 50 | 0 (arrow) |
  | 16, 18 | 49 | 1 | | 5 | 51 | 0 (arrow) |
  | 11 | 48 | 1 | | 6 | 52 | 0 (arrow) |
  | 19 | 1266 | 1 | | 7 | 53 | 0 (arrow) |
  | 20 / 23 / 24 | 571 / 572 / 573 | 1 | | 49–52 | 1268–1271 | 0 (2nd arrow set) |
  | 21 / 22 | 3560 / 3562 | 0 | | 28–30 | 54 / 55 / 56 | 1 |

  `sid_alt` equals `sid` in every record. The table is shared across bodies, so most rows are buttons
  that the E-P7 does not have.
- **[V] Dispatcher** `0x60cc872f`. First it checks a fixed event map (`0x60cc8878`). Then:
  1. `sid = 0x60cc87c8(event)`.
  2. `value = 0x60cc8979(sid)`. This is the setting value, with mode overrides only for sids 3560, 3562, 48 and 49.
  3. If `full == 1`, `value = 0x60cc8ad3(value)`. This handles AEL and the movie-mode swap.
  4. `action = 0x60cc885c(value)`, looked up in the function table.

  **No step checks which key the function came from.** Arrow-pad sids skip step 3.
- **[V] Function table** `0x60f38af8`: 55 × `{u32 code, u32 action, u32 alt}`. The firmware embeds the
  action names (table `0x60f384f8`, 92 entries, with debug strings). Examples:
  3474→23 `LV_MAGNIFY`, 568→30 `PEAKING`, 3552→43 `SELECT_MODE_ISO_WB`, 3557→31 `FINDER_WATER_LEVEL`,
  437→18 `EVF_FN` (Multi Function), 34→29 `DIGITAL_ZOOM`, 3461→52 `SELECT_MODE_EXPREV`,
  16→53 `SELECT_MODE_STROBE`, 3281→54 `SELECT_MODE_TAKE_DRIVE`, 85→51 `SELECT_MODE_AF_FRAME`,
  6→41 `SELECT_MODE_ISO`, 9→42 `SELECT_MODE_WB`, 3470–3473→`MYSET_1..4`.
  Multi Function sub-functions use table `0x60f38d8c`: 1→48 tone control, 6→49 colour creator, 8/7→43/44,
  2→23, 3→50 aspect, 9→88 S-OVF, 10→30, and also 5→42 WB.
- **[V] No profile function exists.** No function code maps to a Colour/Mono profile switch or slot.
  The action `LV_CTRL_PROFILE` (76) exists, but no function-table entry points to it.

## 2. Where the allowed values come from (the "menu value list")

- **[V] Static validator** `0x604cc98c`: 1333 records of 20 bytes,
  `{u16 sid, u16 attr, u32 list, u32 alt, u16 bytes, u16 elem, u8 sub, u8 type, u16 0}`.
  They are hashed by `sid & 127` into RAM `0x62248528` by `0x602ba4cc`, and found by `0x602ba523`.
  The API is count `0x602b9f70`, value-by-index `0x602b9fdb`, and step `0x602b9cda`/`0x602b9d15` → `0x602ba146`.
  Type 5 = u16 list.
- **[V]** The count and value wrappers are `0x602af8dc` and `0x602af8a3`. Generic menu option builders
  call them: `0x60886900` (filters each value through `0x602af9d1`) and `0x60bda9b0`.
  `0x602af9d1` → `0x602b2fad` has availability handlers only for sid 1716. The registry objects for
  every button sid (`0x60433408…`) have no dynamic-list hook (+20 = 0). So **the static list is the
  whole story for these sids**: it is what the menu enumerates and what dial stepping walks.
- **[V]** `value(sid, count)` is not rejected (`cmp; ble`): it returns the u16 after the list. Callers
  loop `idx < count`. This is a stock quirk, and the patch keeps it.
- **[V] Labels.** The Button Function screen rows (`0x611d7dc0…`, 28-byte widgets) use the label, icon and help
  tables at `0x611d78cc` / `0x611d7ad0` / `0x611d7b9c`. These tables cover every function code
  (including 6 ISO, 9 WB, Magnify, Peaking, ISO/WB, Level, Multi Function).

### Stock lists (still mode, key 0xECC2 unless noted)

| sid (key idx) | role | list |
|---|---|---|
| 47 (0), 48 (1), 49 (2) | full buttons, 12 codes | AEL/AFL, ◉REC, Preview, one-touch WB, AF area, MF, Exp comp, tele-con, Magnify, Peaking, touch lock, Off |
| 571 (4), 572 (5), 573 (3), 1266 (12), 54/55 (0xECD2 0/1) | full buttons, 28 codes | 12 above + Home, RAW, Test picture, LV-C/SCP, Keystone, HDR, BKT, ISO/WB, WB/ISO, Multi Function, Level, View Selection, S-OVF, AF Limiter, Preset MF, Lens Info, IS mode |
| 56 (0xECE2 0) | lens L-Fn, 29 codes | AF Stop + the 28 |
| **51 (7), 53 (9)** | **arrow right / down**, 8 codes | Exp comp, Flash, Drive, touch lock, e-zoom, LV-C/SCP, MF, Off |
| 50 (6), 52 (8) | arrow up / left | **no validator record**: fixed |
| 1269, 1271 (0xECD2 3/5) | 2nd arrow set, 9 codes | as 51/53 + ISO/WB, WB/ISO, no Off |
| 158, 1253, 1260, 1267 | u8 (0, 2, 1) | arrow-pad mode (Off / Direct Function / …) |
| 437 | Multi Function sub-function | 1, 6, 8, 7, 2, 3, 9, 10 |
| movie 1246–1252, 1258, 1259 (0x55B2…) | 19 codes; 1265 = 20 | movie lists |
| movie 1255, 1257, 1262, 1264 | 6 codes | Exp comp, ISO/WB, WB/ISO, touch lock, e-zoom, MF |

### What is fixed and what is assignable

- **[V]** Up (50) and left (52) have no allowed-value list, so the menu cannot change them. The dispatcher
  would accept any code there, but nothing writes one.
- **[V]** Right (51) and down (53) are assignable, but only to the 8 d-pad codes. **The code accepts
  any of the 55 function codes on them.** Only the list blocks the rest.
- **[I]** Sid ↔ physical-button identity for the E-P7: the arrow sids follow from the d-pad key codes 4–7 and
  the stock functions (up = exp comp, right = flash, down = drive, left = AF point). Two facts point
  to 47/48/49 being the E-P7's ◉ and Fn/AEL buttons: the 12-code list matches the reviewed E-P7 set ("◉ and the AEL/AFL
  button are customisable" [W]), and sid 48 is forced to ◉REC in mode 3 (`0x60cc8a49`).
  The patch widens all three, so the exact mapping does not change the result.

## 3. Built: patches/buttons (data-only, 10 edits / 100 bytes, section 2, in place)

`patches/buttons/build.py` → `patches/buttons/edits.json`; verifier `tools/ep7_buttons_verify.py SPEC`.

- **Full buttons, sids 47/48/49.** One shared 23-code list overwrites the three contiguous 12-code lists at
  `0x604cae3c` (72 B room, 46 B used). It adds AF Home, RAW, Test picture, Keystone, HDR, BKT, ISO/WB, WB/ISO,
  **Multi Function** (H&S / Colour Creator / Magnify / Aspect / Peaking …), Level and IS mode.
  It leaves out EVF-only codes (View Selection, S-OVF), AF Limiter, Preset MF, Lens Info and LV-C/SCP.
- **Arrow right/down, sids 51/53.** One shared 16-code list overwrites the two contiguous 8-code lists at
  `0x604cb00e`. It keeps all 8 stock codes and adds **ISO/WB, WB/ISO, Peaking, Magnify, Level, Digital
  tele-converter, Multi Function and RAW**.
- **Records.** Each of the 5 records gets ptr = shared list and bytes = 2·n. No other record and no
  code references the rewritten bytes (abs32 scan, all 1333 records). Each added code meets three checks:
  it is in the function table, it is in the Button Function label table, and it is allowed on some stock
  E-P7 button sid.

**[V] Emulator results** (`tools/ep7_buttons_verify.py`, payloads decoded from the in-memory package):
- **S.** Changes in the validator region are confined to the patch.
- **V.** Native hash init, count and value for the 5 sids give exactly the new lists. 24 other sids match stock.
- **N.** Native stepping walks each new list like stock, with the same wrap at the ends.
- **A.** Native function → action matches stock for every listed code, and none is 0. Sid kinds: 47/48/49 = 1, 50–53 = 0.
- **M.** 3 mutations are caught.

The same suite runs again on the v0.4 merge (`releases/v0.5-candidate/edits.json`); results are in WORKLOG.

**Risks / not proven [I]:**
- Each state handler (55 callers of `0x60cc872f`) decides whether an action applies in that state. Every
  added action is already delivered from stock buttons, so the handlers know it. Delivery from an arrow is
  untested on hardware.
- **Magnify on an arrow.** In the magnify-frame state the arrows move the frame, so pressing the same arrow
  again probably moves the frame instead of zooming. You can still zoom/exit with OK or a half-press. This is
  UX friction, not a hang. The same applies to Multi Function's hold-and-dial.
- **Restoring stock.** A saved value that is not in the stock list (e.g. right = Peaking) stays stored. The
  stock dispatcher still executes it (it does not validate), and the menu shows the nearest stock entry.
  This is benign, but reset Button Function before restoring.

## 4. Queued (designs, not built)

1. **D-pad → profile slot direct select (pairs with profile bundles).** No function code exists. Option A:
   repurpose a function-table entry that the E-P7 never uses, e.g. 3470–3473 `MYSET_1..4`, 665 ×3 or 530/532.
   Point its action to 76 `LV_CTRL_PROFILE`, add the code to the 51/53 list and give it a label. This is data-only,
   but what action 76 does when fired from a key is unknown, so trace its state handler first. Option B: a new action
   that sets setting 908 (COLOR profile) / 973 (MONO) to N directly. This needs a hook in the action executor (not located yet)
   and code space in sec 6. Medium confidence, not started.
2. **ISO-only / WB-only on an arrow** (codes 6 / 9 → actions 41 / 42). These are in the function and label tables,
   but no stock E-P7 list uses them, and action 42 is reachable only through an unlisted Multi Function value. Add
   them after confirming the action-41/42 handlers exist.
3. **Up / left arrows (sids 50/52).** They need a validator record. The table is a fixed 1333-record array, so one
   cannot be added in place. Option: repoint an E-P7-unused record's sid (needs a model-usage audit) plus a
   Button Function menu row. Low priority.
4. **Movie-mode arrow lists** (sids 1255/1257/1262/1264, 6 codes). Same method as section 3, 12 B room each.
5. **Myset recall on a button** (3470–3473). Needs Myset slots, which the E-P7 lacks [I].

## 5. Other bodies and community work

- **[W]** Web search did not return the E-P7 manual's Button Function table. One review says only the ◉ and
  AEL/AFL buttons plus the arrows are customisable. Other bodies in this family carry the 28/29-code lists on several
  buttons and four-way Direct Function arrows: the PEN-F (Fn1/Fn2/◉/arrows/L-Fn) and the E-M5 III / E-M10 IV / OM-5 (Fn/◉/arrows).
  The firmware's shared tables reflect that superset. The E-P7 is the restricted variant.
- **[V]** fishcu/oly_fw_analysis: `docs/boot/pen-f/INPUTS.md` covers only raw input events (OK level,
  controller IRQ → UI_IN task). There are no button-remapping docs, issues or PRs (issues #1/#3/#5/#6, PRs #2/#4 checked).
  No public firmware mod remaps buttons on Olympus/OM bodies, as far as was found.
