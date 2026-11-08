# E-PL9 look hook: design (v1)

Design only (2026-11-07). Nothing is built, packaged or flashed. Addresses are E-PL9 1.101 runtime addresses (main
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

1. **Live view** [?]: whether the LV route resolves Custom through T1/T2 or one of the untraced readers. If not,
   photos get the look but the preview doesn't.
2. **Tone settings for mode 11** [?]: contrast, sharpness and gradation may come from the hidden COLOR-profile
   properties (`0xf6a1`…), not Custom's. Their stock defaults are unknown.
3. **capture+1912** [?]: the E-P7 sets it to 1 for mode 11/12; the E-PL9 doesn't.
4. **EXIF/makernote** [I]: images will record picture mode 11, which E-PL9-aware software may not know.
5. **Packaging** [?]: `tools/build_package.py` writes E-P7 packages; the E-PL9 container format matches (same
   checksum scheme, round-trip verified), but its packager target hasn't been written.

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
