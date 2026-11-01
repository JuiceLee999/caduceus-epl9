# In-camera extras: clarity slider, grain, WB shift (E-P7 1.1)

Offline work. Nothing here has run on a camera, no `E142*` file was made, nothing was committed.
Built and emulator-verified as a **layer over the look editor** (`patches/look_extras/`). Not cleared for flashing:
it sits on the editor, whose axis key and redraw are still being proven on the camera (12c, 12d).

[V] = read from the decoded main with `tools/dis.sh` / `tools/ep7_xref.py` / byte dumps. [E] = shown in the emulator.
[C] = camera observation. [I] = inference. Rule kept: **no run-time store into 0x60020020–0x6191ffe0**.

## 1. Result

**X axis in the Color Profile wheel editor.** After H, the editor's axis key steps to one more stop, X. On X the
first four wheel sectors are the per-profile extras of the slot being edited:

| Sector (cursor) | Wheel colour [V order, sim/recipes] | Field | Value on the stock −5..+5 list | Slot bytes |
|---|---|---|---|---|
| 1 | yellow | Grain | 0 off, 1 low, 2 medium, 3 high (4, 5 clamp to 3; negative to 0) | +24 |
| 2 | orange | **Glow− / Clarity+** | −5..−1 = bloom 5..1, 0 = none, +1..+5 = clarity 1..5 | +28 id, +29 strength |
| 3 | orange-red | WB A–B | −5..+5 | +26, override bit +25 |
| 4 | red | WB G–M | −5..+5 | +27, override bit +25 |
| 5–12 | others | none | read 0, writes ignored | – |

So the clarity slider is sector 2: right = clearer, left = softer glow. One field, because bloom and clarity share
the same passes (CLARITY.md §1). The guide label (bottom left, 12c's hook) reads `[X] Grain 0-3`,
`[X] Glow-  Clarity+`, `[X] WB A-B`, `[X] WB G-M`, `[X] colours 1-4 only`, or `[X] off in All colors`.

WB rule: setting A–B or G–M to non-zero turns the slot's override on (bundle `wb_flags` bit 0). Setting both to 0
turns it off, so the camera's own fine-tune applies again. If the override was off, the first edit starts both axes
from 0.

Mock-up: not drawn. The stock wheel stays on screen; the numeric value and the guide label change.

## 2. Options compared

| Option | What it needs | Verdict |
|---|---|---|
| **(a) X stop on the wheel editor** | The editor's own facade/setter hooks (already built and emulator-verified), one more stop on its axis key, the 12c guide hook. No new hook *sites*: the layer takes over 8 words the editor already owns and falls through to it | **Chosen, built.** Cheapest: ≈1.1 KB of code, no stock function lost, no settings storage, saved by the editor's card save |
| (b) Repurpose a stock list/slider | A per-profile item that is visible in COLOR mode and rarely used. Survey of the 47 editor descriptors (0x61186ba4) and the validator lists (0x604cc98c) [V]: 987–989/1680 (key 0xf791, 9 values 0,1,2,3,6,7,8,4,5) is the **Mono** filter, shown only for MONO; 981–983 (0xf779, 0..3) is Mono grain, MONO only; 91–96/144/212/… (0x84f9, −7..7) are the WB A–B fine-tune **per WB mode** (G–M is 0x9679); 652 Recording Volume was already rejected (LOOK_PICKER §10) | Rejected. Every candidate either is hidden in COLOR mode, or loses a stock function and changes what its stock consumer sees. Relabelling also needs list/validator edits. (b′) WB fine-tune screen edits the slot WB while a profile is active: it changes the meaning of a stock screen, and WB fine-tune is per WB mode, not per profile |
| (c) Own page / new setting | Settings storage, validator, defaults, a menu page | Rejected (most unknowns, REVIEW_v03 H3 class: values persisted in internal settings) |
| (c′) Polygon-free wheel axis | = (a) | (a) does not need the polygon: the numeric value comes from the facade (`0x60decabd`) |

## 3. How the layer works

### 3.1 Chaining (no edits to `patches/look_editor`)

`patches/look_extras/build.py --editor <editor merged.json>` reads the editor's spec and symbols, checks that each
word below holds the editor's routine, re-points it to ours, and adds our code. On a miss every entry jumps on to
the routine that word held, with d0/d1/a0/a1, the stack and MDR as at entry. So the editor and stock run unchanged
whenever the axis is not X.

| # | Site (owner before) | Now | Falls through to | Conf. |
|---|---|---|---|---|
| X1 | 0x60acb0e4 facade vtable +8 GetValue (editor `ed_get`) | `ex_get` | `ed_get` (→ stock 0x607f9549) | high [V][E] |
| X2 | 0x60acb174 facade vtable +152 GetDefault (`ed_default`) | `ex_default` (X: 0) | `ed_default` | high [V][E] |
| X3 | 0x607fa355 `call …,[d2,d3,a2],16` in the GUI setter (`call ed_set`) | `call ex_set` | `ed_set` (→ 0x60827440) | high [V][E] |
| X4 | 0x6025aa98 .data init word of view part 3 (`ed_guide`; stock 0x60decbfc) | `ex_guide` | runs `ed_guide` first, then relabels on X only | high [V][E]; [C] the 12c guide hook runs on the camera (it shows `[S]`) |
| X5 | COLOR1–4 record word of the **axis key** (build parameter `--key-word`) | `ex_event` | whatever the word held (editor handler or stock) | site high [V][E]; **key delivery: see §5** |

X5 values: Movie `+52` (0x61185c10/c48/c80/cb8, events 0x9012/0x9016, the 12b/12c route; verified build) or INFO
`+44` (0x61185c08/c40/c78/cb0, stock 0x60e22579, event 0x9014; builds, see §5). Router 0x60e20cdc sends 0x9014 to
parent+80 (record +44), 0x9015 to +84 (+48), 0x9012 to +88 (+52), everything else to +72 (+36) [V, LOOK_PICKER §10.1].

### 3.2 Entries

- **ex_find** (shared): id ∈ 927..962 / 1655..1666 (u16, as stock `exthu`), handle and `EP7B` valid, `EP7E` set,
  axis byte P+684 == X → slot, sector. Anything else = miss.
- **ex_get / ex_default**: hit → `*a1` = value / 0, d0 = 0, `rets` (the editor's own hit convention). Reads are
  range-checked exactly like the readers: grain > 3, effect id ∉ {1, 3} or strength ∉ 1..5, WB without the override
  bit (or bit 7 set) all read 0; WB is clamped to ±5 for the stock list.
- **ex_set**: hit → if ALL (`(0x61fc3800) | (0x61fc3804)`, [V] Up handler 0x60e20edb) or sector ≥ 4: no write.
  Otherwise clamp, write in a race-safe order (effect: id 0, strength, new id; WB: value, then the override byte),
  dirty = 1, then enter the stock manager 0x60827440 with the id's **unchanged S value** (stock getter 0x602af887),
  exactly as the editor's 12c H/L path does, so the listeners redraw. Saturation never changes.
- **ex_event**: axis key with axis == `x_prev` and the editor's own guards (key, 13 children, no held gesture,
  children ids) → axis = X, stock child refresh 0x60de3670 on children 1..12, then the editor's `ed_poke`
  (cursor re-write → screen rebuild), return 1. Any other state → the previous handler. The next key press on X
  goes to the editor, whose cycle wraps any axis ≥ its last stop to S [V 12c source: `inc; cmp 3; bcs → 0`].
- **ex_guide**: after `ed_guide`, on X only and only for the kind-4 label 2755/2756: GetValue(111) → picture mode
  54/55/56/64 → cursor setting 1091/1096/1097/1686 → sector (cursor 1..12 [V Up handler: child[cursor]]) → text.

### 3.3 Code space

Section 1, **dead EVF gamma tables, steps 2 and 1** (R/G/B × 256 B): **0x601e323c–0x601e383c**, 1112 of 1536 B used
(ex_core 496 B at 0x601e323c, ex_ui 616 B at 0x601e342c). The only references into the range are the six step-table
words 0x601e3c90–98 and 0x601e3ca0–a8 (EVF device, slots 1 and 2) [V build-checked abs32 scan]. The EVF programmer runs only for
the EVF device (COLORTEMP, `0x60174d19`); the E-P7 has no EVF [I strong, same basis as View Assist, which uses step 0
at 0x601e383c and ran on the camera in test 11 [C]]. Section 1 loads first, so every hook word can see the code.
Not used, on request: 0x6143a400–0x6143a800 and 0x60b9de80–0x60b9e000 (film-menu F stop).

## 4. Live apply and live view

| Field | Next still | Live view | Persist |
|---|---|---|---|
| Grain | yes: grain readers read the heap table via `tbl_idx` at capture [V SD_BUNDLES_V3 §4] | no (stills pipeline only, GRAIN_PORT) | editor card save on the next half-press (`ed_trig`, dirty) |
| Glow / clarity | yes (bloom_flag / bloom_w via `tbl_idx`) | no (stills only, CLARITY §3.7) | same |
| WB A–B / G–M | yes: all 10 capture reads + params builder go through `wb_get` (`tbl_off`) [V WB_PATCH] | **untraced**: the compact ring slot is redirected, but when it refreshes is unknown (WB_PATCH coverage). Expect no change until LV restarts, if then | same |

The screen redraw on X uses the same two calls as 12c (manager listeners after a write, `ed_poke` after the key).
If those do not redraw on the camera, X redraws exactly as badly as H/L. A capture racing an edit can see one old
and one new byte; every combination is a valid, range-checked look.

## 5. Coordination (shared hook points)

| Point | Owner | Interaction |
|---|---|---|
| Facade +8/+152, setter 0x607fa355, guide word 0x6025aa98 | look editor (12c+) | X1–X4 re-point the editor's words. The build refuses an editor spec where these do not hold `ed_get`/`ed_default`/`ed_set`/`ed_guide`, and needs `ed_poke`, `ed_event` |
| Axis key record word | look editor | **Movie never reaches the editor on the camera [C 12c]**, so the verified `--key-word 52` build is not the camera route. **12d moves the cycle to INFO** (S·Single → S·All → L → H). Use `--key-word 44 --events 0x9014` on the 12d spec. Requirements on 12d: (1) on H the INFO word may be handled by `ex_event` first; (2) INFO on an axis ≥ its last stop goes to S·Single; (3) ALL is off on L and H (else X opens in ALL and writes nothing). If 12d instead keeps the INFO logic inside `ed_event` (+36), use `--key-word 36` |
| Axis byte values | editor (S 0, L 1, H 2), film menu F | `--x-prev/--x-axis`: 2/3 without F; **3/4 after F** (S → L → H → F → X). F hooks the Up/Down record words +12/+16 (FILM_MENU_V2.md); X never touches them, and F's Up/Down replay on non-F axes, so both coexist. The X label is written after `ed_guide`, so F's label changes in `ed_guide` do not clash |
| Heap block P+680..686 | editor | X uses the axis and dirty bytes only |
| Card save | editor `ed_save` | saves the whole table (grain/effect/WB included); loader ranges already allow effect 3 (build checks the base loader's span table) |

## 6. Verification (emulator; `generated/look_extras/`)

```
.venv/bin/python -I patches/look_extras/build.py --editor generated/look_editor_12c/merged.json --out generated/look_extras
.venv/bin/python -I patches/look_extras/verify.py --editor generated/look_editor_12c/merged.json \
    --layered generated/look_extras/merged.json --jobs 18 --json generated/look_extras/verify.json
```

Differential against the editor build it sits on, every run entering through the real edited word/site, image
regions read-only:

| Part | Result |
|---|---|
| S: layered image differs from the editor image only in the region + the 8 words; region was the stock EVF tables; no abs32 into the region; no absolute stores | PASS |
| G: GetValue/GetDefault, 15 heap states × 58 ids (all 48 sector ids, misses incl. 0x103a3), two field fixtures covering every read branch: not X → == editor run (stop, registers incl. MDR, live stack, *out); X → model | 744/744 |
| W: setter, 16 values (−2³¹..2³¹−1) × 21 ids × states + ALL cases: not X → == editor; X → heap == model, and the state entering 0x60827443 == the editor's S edit of that id to its S value | 4048/4048 |
| E: axis key via the record word, 4 keys × 5 events × states + 6 guard failures: transition only on H + key + guards (axis, 12 refreshes, facade get/set of the cursor, d0 1); else == editor | 246/246 |
| V: guide, 6 labels × 9 mode/cursor pairs × states: not X → == editor; X → exact kind-5 text | 648/648 |
| M: 16 source mutations (axis compares, grain bounds, bloom sign/id, WB mask and 0/0 rule, ALL check, dirty byte, sector bound, MDR restore, transition from/to, child guard, guide axis/bound) | 16/16 detected |
| Package: `tools/build_package.py` accepts it; decoded patched payload == emulated image, restore == stock | PASS (not a release; local only) |

Not covered: the real Up/Down/dial handlers driving the children (the editor verifier does not run them either),
key delivery on the camera, redraw, the wheel polygon, and ISP output of clarity (CLARITY §3).

## 7. Risks

1. **Key route [C].** Movie does not reach the editor; the INFO route is the editor's 12d work. X is only as
   reachable as the editor's cycle. Medium until 12d passes on the camera.
2. **Wheel shape.** The polygon producer is unmapped (LOOK_EDITOR §1.5); on X the wheel keeps its drawing. Only the
   number and the label are right. UX, not safety.
3. **Axis outlives the editor [I].** Like H/L, the axis byte stays X after the editor closes until the next editor
   open (`ed_init` resets it). A different GUI that reads or writes sector ids 927–962/1655–1666 through the facade
   in that window would see/set extras. Same class as the editor's H/L risk; card-gated (no table → stock).
4. **ALL mode.** Writes are refused; the stock ALL step may move the children's indices before the refresh
   re-reads them (brief wrong numbers) [I].
5. **Clarity on hardware [I].** Negative blend weight in mode 0x00200001 is unproven (CLARITY §3.1). Test 11 had
   COLOR2 clarity 3 on the card; image quality was not recorded in WORKLOG.
6. **EVF region [I strong].** If any code ever programmed the EVF gamma with steps 1/2, it would load our code bytes
   as a LUT into a display that does not exist. No crash path.
7. **WB live view** may lag the capture (§4).

Worst case of every runtime risk: wrong numbers on screen or an unexpected look on the next shot; removing
`EP7MOD/BUNDLES.BIN` returns the editor to stock S (no table → every entry misses).

## 8. Camera test (after the editor's 12d axis key passes; one flash on that base)

1. No EP7MOD: editor stock; INFO toggles ALL as stock.
2. With BUNDLES.BIN, half-press, open COLOR2: cycle to H, press the key once more → label `[X] …`. Dial to sector 1
   (yellow): label `[X] Grain 0-3`, set 2. Sector 2: set +3 (clarity 3). Sector 3: A–B +2.
3. Key once more → `[S]`; S values unchanged.
4. Shoot COLOR2: grain visible, clarity look, warmer WB. EXIF WB fine-tune A+2.
5. Half-press after closing the editor: `tools/ep7_bundles_bin.py` on the PC shows COLOR2 grain 2, effect (3, 3),
   wb (1, 2, 0). Power-cycle, half-press, values back.
6. Set sector 2 to −2 → bloom 2; set A–B and G–M to 0 → override off (EXIF shows the camera's own fine-tune).

## 9. test12e

- Built with `--key-word 0` (new default): the layer hooks no key word. The editor's page key (ed_page) steps to
  X itself, using the editor byte `ed_cfg_x`, which this build sets to `--x-axis` 4 (page order S → H → L → F → X).
- The label is now plain text with the value (read through ex_get, so it matches the wheel number):
  `1 Grain Off|Low|Medium|High`, `2 Glow N` / `2 Clarity/Glow 0` / `2 Clarity +N`,
  `3 WB Blue N` / `3 WB Amber/Blue` / `3 WB Amber N`, `4 WB Magenta N` / `4 WB Green/Mag.` / `4 WB Green N`,
  `Extras: 1-4 only`, `Extras: no All`. A+ = amber and G+ = green (sim/film.py convention).
- Verified: S, G 744, W 4048, V 648 on the 12e editor.

