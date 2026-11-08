# E-PL9 look hook: design (v1)

**Status (2026-11-07): v1 built and emulator-verified (§5). Not flashed. Not cleared for flashing.** Addresses are E-PL9 1.101 runtime addresses (main
loads at `0x60400020`). [V] = read from the decoded main or checked by a tool. [E] = shown in the emulator. [I] =
inference. [?] = open.

## 1. Goal

Make one stock E-PL9 picture mode render a Caduceus film look: per-hue hue, saturation and lightness through the
camera's own COLOR builder, the way COLOR profiles work on the E-P7. v1 is the smallest thing a camera test can judge:
one look, stills first.

**Decisions (user, 2026-11-07):** the look mode is **Custom**; the v1 look is a **deliberately strong test look**
(obvious shifts such as greens → teal) so the first camera test is easy to judge. A real film look comes after.

## 2. What's established

| Fact | Where | |
|---|---|---|
| Mode 11 is the only mode that reaches the COLOR builder | selector gate, `tools/epl9_color_probe.py` check D | [E] |
| Stock E-PL9 can't select mode 11: setting 111 (`0x9481`) has no 11/12 | validator record `0x608a33f8` | [V] |
| A capture picture-mode byte of 11 reaches the builder through the stock pipeline | `PORT_EPL9.md`, pipeline check | [V] |
| Hook site: `call builder` at `0x6079ec53` (5 bytes), rejoin `0x6079ec58`; after the call a2 = context, context+12 = output | probe check C | [E] |
| Output records: 12 × 24 B at output+688; hue at +18, saturation +20, lightness +22 (s16) | probe A/C | [E] |
| Units: hue = −1000 per UI step (≈11° per 1000), lightness LUT −300…+300 for ±7 (E-P7 `patches/bundles/build.py`) | E-P7 camera tests | [V on E-P7] |
| Free code space with no literal or relative references: sec 1 `0x60600eb0` (336 B), **sec 2 `0x6092c6a8` (344 B)**, sec 6 `0x6162fd8c` (628 B) | `tools/epl9_code_space.py` | [V] |

Where the picture mode is read (setting `0x9481`, 38017) and where Custom (6) is resolved to its base mode
(`0x9d11`, 40209):

| Site | Reads | Role | E-P7 counterpart |
|---|---|---|---|
| `0x60693ce6` / `0x60693d02` | 0x9481, then 0x9d11 if 6 | capture population → capture+22955 | `0x602a856e` (12 votes) |
| `0x606955e4` / `0x6069560c` | 0x9481, then 0x9d11 if 6 | slot 0 of the slot table (capture+23714) | none mapped |
| `0x607cb7cb` | slot byte 6 → slot byte 1 | slot → capture+22955 (per frame / bracketing) | `0x603e2043` |
| `0x60680382`, `0x6069636f`, `0x6070fa37` | 0x9d11 | untraced; one may be the live-view route [?] | |
| `0x606f8f6f…0x606f98a2` (15 reads) | 0x9d11 | Custom settings menu [I] | `0x60303c4a…` cluster |
| `0x605fb010`, `0x6068036c`, `0x60694f14`, `0x60701161`, `0x6070f8d7`, `0x607d4adb`, `0x6080c262` | 0x9481 | untraced | `0x602a9866` → `0x60694f14`, `0x603ecd98` → `0x607d4adb`, `0x60429585` → `0x6080c25b` |

## 3. Design

Two hooks: **T** (trigger) turns the chosen stock mode into 11, and **C** (colour) writes the look into the
builder's output.

### 3.1 Trigger T: Custom (6) becomes mode 11

Recommended: repurpose **Custom**. When the picture mode is Custom, store 11 instead of resolving the Custom base mode.
In place, no code space:

- T1, capture population `0x60693d02`: replace `mov 40209,d0` (6 B) with `mov 11,d0` + `bra 0x60693d12` (the
  `movbu d0,(a2)` that stores the byte). The `cmp 11` at `0x60693d16` then reads profile `0xf6b1` into capture+22985
  as stock does for mode 11.
- T2, slot fill `0x6069560c`: same idea; the slot's mode byte becomes 11, so `0x607cb7cb` and `0x607ca514` copy 11
  unchanged (their `cmp 6` no longer matches).

| Patch | Address | Stock (expect) | New | Instructions |
|---|---|---|---|---|
| T1 | `0x60693d02` | `fc cc 11 9d 00 00` | `80 0b ca 0e cb cb` | `mov 11,d0; bra 0x60693d12; nop; nop` |
| T2 | `0x6069560c` | `fc cc 11 9d 00 00` | `80 0b f0 52 ca 0f` | `mov 11,d0; movbu d0,(a2); bra 0x6069561f` |
| T3 | `0x607210af` | `dd 65 4f ff ff 00 00` | `80 0b cb cb cb cb cb` | `mov 11,d0; nop ×5` (live view, §3.5) |

Encodings come from `mn10300-elf-as` (`mov`, `movbu`) and the stock `bra` at `0x60693d20` (`ca rel8`). In T2, a2 is the
slot pointer (`0x60695604`), so byte 0 (the mode) becomes 11; byte 1 (the Custom base) is left as it was.

Every other mode is byte-identical to stock, because T only fires when the mode is 6. Custom's own base mode
(`0x9d11`) becomes unused, so v2 can use it as the look selector (§3.3).

Alternative: hook the property getter `0x6043e62b` for key 40209. That covers every reader at once, live view and
RAW development included, but the Custom menu cluster reads the same key and would show a wrong base mode. Decide
after the live-view trace.

### 3.2 Colour hook C

`0x6079ec53`: `call builder` → `jmp c_stub` (5 B, `dc rel32`). The stub sits in the sec 2 tail (`0x6092c6a8`):

```
c_stub:  call  builder,[d2,d3,a2,a3],96   ; displaced stock call (PC-relative, resolved by ld)
         save d0,d1,a0,a1,a3,d2
         a3 = (context+12) + 688 + 18      ; record 0 hue
         a1 = look_table                   ; 12 x {hue, sat, light} s16, physical record order
         repeat 12: copy 3 halfwords to (a3), (a3+2), (a3+4); a3 += 24
         restore
         jmp   0x6079ec58
```

- The build script precomputes **native values** per record (hue −1000·ui, the lightness LUT, saturation from the
  look's ±5 value times that record's stock gain). The stub only copies, which keeps it small (≈40 B + 72 B table).
- No job validation is needed in v1: only T produces mode 11, and every mode-11 job should get the look. That includes
  live view and RAW development if they run at mode 11.
- It writes only the builder's output in RAM, as the builder itself does. There are no stores into the loaded image
  `0x60400020–0x617b9000` (the E-P7 hard rule after SD_V2_CRASH).

### 3.3 Choosing a look

- **v1: one look baked into the firmware.** Changing it means a new build. This tests the whole route on the camera.
- **v2 options:** (a) Custom's base-mode setting as a selector (Vivid/Natural/Muted/Portrait → looks 1–4), using
  stock menus with the wrong labels; (b) a look file on the SD card, as on the E-P7 (loader v3 design, more code);
  (c) both.

### 3.4 What v1 leaves open

1. **Live view**: traced, now covered by T3 (§3.5).
2. **Tone settings for mode 11** [?]: contrast, sharpness and gradation may come from the hidden COLOR-profile
   properties (`0xf6a1`…), not Custom's. Their stock defaults are unknown.
3. **capture+1912** [?]: the E-P7 sets it to 1 for mode 11/12; the E-PL9 doesn't.
4. **EXIF/makernote** [I]: images will record picture mode 11, which E-PL9-aware software may not know.
5. **Packaging** [?]: `tools/build_package.py` writes E-P7 packages; the E-PL9 container format matches (same
   checksum scheme, round-trip verified), but its packager target hasn't been written.

### 3.5 Live view (traced 2026-11-07)

Live view doesn't use the stills capture population. As on the E-P7 (`LV_ART_PREVIEW.md`), LV frames are built
from a **record**, and the record's picture mode is resolved separately:

| Step | E-P7 1.1 | E-PL9 1.101 |
|---|---|---|
| Record pointer table, filled from the key list (`{key, 2, ptr}`) | `0x604e2260` → `0xa27354a0…` | `0x608b782c` → `0xa2af4538…` |
| Picture mode `0x9481` slot / Custom base `0x9d11` slot | `0xa27354a0` / `0xa27354a4` | `0xa2af4538` / `0xa2af453c` |
| Record picture mode, then "if 6: replace with the Custom base" | A+354 at `0x6032678d`, getter `0x6031c0b9` | **A+353 at `0x607210a9`, getter `0x60716014` called at `0x607210af`** |
| Custom path also loads Custom's own two fields into A+356/357 | `0x6031c0c4`/`0x6031c0cf` | `0x6071601f`/`0x6071602a` |
| Key mapper: picture mode < 100 and no Flat/scene flag → key = picture mode | `0x60349297` | `0x60743621` (Flat only, no Log) |

T1/T2 don't reach this route, so v1 without T3 would have shown **stock Custom in the preview** and the look only in
the photo. **T3** replaces the 7-byte getter call with `mov 11,d0` and 5 `nop`s, so the following `movbu d0,(a2)`
stores 11. Custom's other record fields keep loading as stock. The mapper then gives key 11, and the selector runs
the builder with the hook, so the preview should show the look.

Still untraced, and not on the LV, capture or slot routes: `0x6068036b` (resolves Custom into a structure at +40,
caller frame 368 B) and `0x6070f8d7`/`0x6070fa37` (resolves Custom on its own stack). If something on the camera
still shows stock Custom (e.g. an info screen or a playback function), these are the first suspects.

## 4. Test plan

Emulator (before any build):
- **C:** stock selector + C stub: all 12 records = look table; context, stack and callee-saved registers as stock;
  modes ≠ 11 byte-identical to stock (the builder never runs).
- **T1/T2:** run the patched capture-population and slot-fill fragments with a fake property getter: 6 → 11, and
  1–5, 7–9 and Art modes stay byte-identical to stock.
- **Static:** a store audit of every new instruction; every patched byte range matches the stock bytes the patch
  expects (`expect` hex, as the E-P7 patches do).

Camera (only after you confirm, and with recovery checked first):
1. Custom = look, a deliberately strong look (e.g. a big green shift) so the result is unmistakable. JPEG + RAW.
2. Compare Vivid/Natural against stock: they must be identical.
3. Note live view, RAW development in camera, Custom's menu and EXIF.

## 5. As built (v1, 2026-11-07)

One change from §3.2: at the hook a1 is the builder's saturation pointer (request+1813), so the stub points a1 at
the look's 12 saturation bytes in flash. The stock builder then computes saturation itself (stock gains), and the stub
only writes hue and lightness. There are no saturation tables to get wrong.

```
python3 -I patches/epl9_look/build.py                 # -> generated/epl9_look/edits.json, c_stub.{s,lst,bin}, symbols.json
python3 -I tools/epl9_look_verify.py                  # 8 checks, all must PASS
python3 -I tools/build_package.py generated/epl9_look/edits.json --body epl9 --out generated/epl9_look/pkg
```

| Edit | Address | Bytes |
|---|---|---|
| T1 | `0x60693d02` | `fccc119d0000` → `800bca0ecbcb` |
| T2 | `0x6069560c` | `fccc119d0000` → `800bf052ca0f` |
| T3 | `0x607210af` | `dd654fffff0000` → `800bcbcbcbcbcb` |
| C | `0x6079ec53` | `cd8ffdf060` → `dc5dda1800` (`jmp 0x6092c6b0`) |
| S | `0x6092c6b0–0x6092c738` | 136 B stub + look `test_strong` (hue +6 = −6000 native, sat +3, light 0, all sectors) |

**Code-space claim (E-PL9 main):** `0x6092c6b0–0x6092c800` (section 2 tail) belongs to `patches/epl9_look`. 136 B are
used; `0x6092c6a8–0x6092c6b0` and `0x6092c738–0x6092c800` stay FF as guards and room for v2.

**Verification** (`tools/epl9_look_verify.py`, all PASS):

| Check | Result |
|---|---|
| S1 | Every `expect` matches stock; no overlaps; 157 changed bytes, all inside the edits |
| S2 | Stub inside the FF tail with guards (200 B free after it); hook = `jmp d32` to the stub |
| S3 | The stub's only stores are its 16-B stack frame and the two record-loop stores |
| C1 | Patched selector, mode 11: all 12 records carry the look's hue/light, saturation = the stock builder's result for the look's bytes (independent of the request's own saturation); clean return; context as stock |
| C2 | Modes 0–19 except 11, and the `0xf00d` bypass: memory, registers and instruction count identical to stock |
| T1 | Capture population with a fake getter: modes 1–5, 7–9, 100, 124 identical; Custom with base 1–5 → 11, and the profile number is read into capture+22985 (stock mode-11 path) |
| T2 | Slot fill: the same modes identical; Custom → slot mode byte 11, byte 1 untouched |
| T3 | Live-view record fragment `0x6072109d–0x607210df` with a fake pointer table: the same modes identical; Custom → A+353 = 11, every other record byte (incl. Custom's own fields A+356/357) as stock |

Mutation check: a changed look byte fails C1, T1 left as stock fails T1, a hook jumping 2 bytes late fails S2 and C1, and T3 writing 6 fails T3.

**Package** (`tools/build_package.py --body epl9`, new option; E-P7 stays the default): component 0x100 only,
157 changed payload bytes, container re-parsed with valid checksums. The decoded main equals the verifier's patched
image (SHA-256 `53f03640…9930`). The restore package's main equals stock. The output is deliberately not SD-loadable by
name.

**Before any camera test** (not done):
1. ~~Trace live view~~ done (§3.5).
2. Confirm the E-PL9 update procedure and file name, and that the restore package plus the camera's own updater
   can recover a bad flash. Container validity is not bootability.
3. You decide.
