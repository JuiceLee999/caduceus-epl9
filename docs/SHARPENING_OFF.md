# Sharpening off per Color Profile (E-P7 1.1)

Research 2026-11-07; **test build t1 (`0.28t1`) since, §4**. Not flashed, not camera-tested, not committed. Main CPU addresses (base `0x60020020`).
[V] = read from code or bytes. [E] = run in the emulator (`tools/ep7_sharp_probe.py`, stock code on a synthetic request).
[I] = inference.

## Verdict

**Feasible, and simple.** The camera's sharpening is one gain byte in one ISP stage, and that byte comes only from
Sharpness. If a COLOR slot reports **Sharpness −5** instead of −2, the gain is exactly 0 [E]. No new ISP code is needed:
one getter redirect like v0.25's `nr_get`. A gain of 0 is also a state the stock firmware already programs, for three
Art Filter keys [V, E].

Sharpness −2 is **not** off. On a COLOR profile it keeps about 40 % of the normal gain (15 of 36 at base ISO) [E].

## 1. Where sharpening happens

Chain [V]: capture getter key `0x8119` at `0x602a7eda` → capture+24010 (u16) → params+5522 (`chSharp`, signed byte;
converters `0x603e6591`, `0x603e3f8a`, `0x603e90da`, `0x6060e265`) → packer `0x60354eeb` → **request+1795**.

The only ISP reader is the gain helper `0x603ab8fe` (loads at `0x603ac008`, `0x603ac01c`) [V]. A byte scan finds no other
load of +1795 in `0x6034..0x603c`. `0x603440c0` only compares it for change detection. `0x603a57ad` copies it into a
local that is never read [V].

- Stage: `0x603ac0c1`, reached from `0x603aaced` → `0x603b17e6` (request kind 0/16, type 1). It writes
  **regs+12 = byte0 | byte1 << 8 | gain << 16** (`0x603ac224..38`) [V]. Words +20..+64 are fixed kernel constants
  (`0x6050ebb4..`, `0x6050e2f4..`) that Sharpness doesn't touch [V].
- Gain: index = base[class] + Sharpness, clamped to 0..10 (`0x603ac022..2d`). Then gain = table[index] × amount / 256,
  capped at 255 [V].
  - Base table `0x6050eb92` = 6, 5, 4, 4, 6, 7. The alternative `0x6050eb98` = 5, 5, 4, 4, 5, 6 is used when the ctx+80 flags are set (likely live view) [I].
  - Gain table `0x6050eb9e` = 0, 16, 64, 112, 184, 256, 256 ... [V].
  - Amount is an ISO-dependent byte, which falls as ISO rises (for example `0x6050eaa2` = 37 → 18). Byte 1 rises with ISO, so it is likely the coring threshold [I].
- Class by job key (hash `0x60531a40`) [V]: 1 (Vivid) → 0; 2 Natural, **11 COLOR, 12 MONO**, unknown ids → 1;
  3 Muted → 2; 4 and 8 → 3; 5 → 4; 10 → 5. The 2000/2001 (Flat/Log) keys use index = Sharpness + 4.

Gain byte by Sharpness, at the emulated ISO [E]:

| Key | −5 | −4 | −3 | **−2** | −1 | 0 | +1 | +2 |
|---|---|---|---|---|---|---|---|---|
| 11 COLOR, 12 MONO, 2 Natural | **0** | 2 | 9 | **15** | 25 | 36 | 36 | 36 |
| 1 Vivid | 2 | 9 | 15 | 25 | 36 | 36 | 36 | 36 |
| 3 Muted, 4 Portrait | 0 | 0 | 2 | 9 | 15 | 25 | 36 | 36 |
| 2001 Log (Sharpness forced 0) | – | – | – | – | – | 25 | – | – |

- At ISO 3200 on COLOR, the gain is 8 at −2 and 20 at 0, and byte 1 rises from 5 to 25 [E].
- Side finding: on COLOR, Sharpness +1 and +2 give the same gain as 0 in this branch, because the table saturates [E]. Other request branches (+1799, +1810/1811) were not emulated.
- Stock zero gain: art keys `0x01010068`, `0x01020068` and `0x01010072` select the all-zero amount table `0x6050eac6`.
  For these keys, gain and byte 1 are 0 at any Sharpness [V, E]. By list order, `0x68` is probably Grainy Film I/II [I].

## 2. True zero, and side effects

- **Use the index, not a new hook in the ISP.** For key 11, Sharpness ≤ −5 puts the index at 0, and table[0] = 0, so the gain is 0 [E].
  −5 also covers the live-view base table (5 for class 1). Other picture modes would need −7 [V]. The value is a byte, sign-extended
  (`extb`) and clamped before use, so it can't overrun the table [V].
- **Halos:** they come from this gain, so with a gain of 0 there are none [I]. Byte 1 (coring) does nothing when the gain is 0 [I].
- **Noise reduction:** a separate setting (key `0x9719`, `chNf`, its own stage). It doesn't change [V].
- **JPEG:** the encoder is untouched. Files get a little smaller because there is less high-frequency detail [I].
- **Metadata:** capture+24010 also feeds the info copy at `0x603f211f`, so the file will likely say Sharpness −5 [I].
  Check on playback that the INFO screens cope.
- **Other sources of detail, left alone:**
  - Demosaic: built in, can't be separated.
  - Clarity: only when the slot sets it, through the Soft Focus passes (CLARITY.md).
  - NR: smooths and doesn't sharpen.
  - Resizing for smaller JPEG sizes: its filter is not traced.
  - Strings `ucMTFMode` and `LensMtfApertureValue` exist: lens- or aperture-dependent detail compensation is **not ruled out**, and was not traced [open].

## 3. Video

- **Same stage** [V]: live view and movie take `0x603aaced` → `0x603b17e6` (MOVIE_COLOUR §1). The v0.26 Movie slot runs as key 11, so it is the COLOR row above.
- **Route to the movie job** [V chain, I that recordings use it]:
  - Compact block rec+698, byte +3 → message +18 (`0x603158ef`, the builder whose +20 v0.26's `mv_msg` already hooks).
  - Message +16..+19 → record R+2104..2107 (`0x60314d1c..3d`) → job constructor `0x603242d4` → params+5522.
  - This is the same message → record → constructor path that carries the Movie slot's S (R+2119) to the clip.
  - The compact block itself is filled by a table copy from property storage (descriptor `0x604e082c`: key `0x8119` → +73), not through the getter.
  - So the second getter read at `0x6030ec11` (params fill `0x6030e9d1`) is **not** used. It has not been shown to reach recordings.
- **Log/Flat reduce sharpening but don't turn it off.** Job setup zeroes params+5522 for 2000/2001 (`0x60353f79`, `0x60353fe7`),
  and the stage then uses index 4: gain 25, against 36 for COLOR or Vivid at 0 [V, E].

## 4. Built: test t1 (`0.28t1`)

`patches/sharp_off/` (`build.py` `apply(spec)`, `sh.s.in`, `verify.py`), on `releases/v0.27/edits.json`. Output `generated/sharp/t1/` (`edits.json`, `pkg/`).

**Control: Extras sector 10, "Sharp".** Slot byte **+51**: 0 = Camera, 1 = Off. The wheel shows `10 Sharp Camera` / `10 Sharp Off`.
- Turning right gives Off; turning left gives Camera.
- Sectors 11-12 now say `Extras: 1-10 only`.
- +51 was free in v0.27: the flashed table is 0, the SD loader span is 0, and the movie file must be 0 there [V].

**What it changes:**

| Site | Was | Now |
|---|---|---|
| `0x602a7edb` rel32 (capture read of `0x8119`) | getter | `sh_get`: v0.25 `sc_slot` hit (COLOR1-4) and +51 == 1 → −5, else the getter |
| `0x60315900` jmp (message hook) | `mv_msg` | `sh_msg`: rec+176 == 1 (movie), rec+294 == 1 (Vivid), valid table and P2, Movie slot (P2+224) +51 == 1 → message +18 = −5; then `mv_msg` |
| `0x601e1263` / `128b` / `12ea` jmp | `gc_sg9` / `gc_ss9` / `gc_su9` | `sh_sg` / `sh_ss` / `sh_su`: index 9 = +51, others fall through |
| `0x601e3348` jmp (ex_default hit tail) | `gc_def` | `sh_def`: sector 10 answers its current value |
| `0x601e12aa` imm32 | "Extras: 1-9 only" | "Extras: 1-10 only" |
| `0x605b7754` (SD loader v3 span +51) | 0 | 1 |
| `0x601e0d12` / `0x601e0d15` (mv_load zero check) | 867 / 13 | 868 / 12 (+52..63) |

- **Code:** 324 B at `0x601de13c`, the two lowest dead EVF gamma tables (CODE_SPACE_MAP). No word tables (strings after `.balign 4`).
  No absolute stores, mul/div, setlb or fb forms.
- **Owner's rule:** the setting is per profile and only the user changes it. The Film pick, Own and Stock (`u_apply`) copy bytes 0..49 only, and the `*` compare stops at 49 [V, E].
  A reset reads GetDefault, which `sh_def` answers with the current value.
- **mv_load** was changed as a byte edit, the way v0.27 moved its check to +51. Editing `patches/v026_movie/mvl.s.in` would break the v0.27 rebuild, because `build_r1.py` expects 866 from that source.
- **Desktop tools:**
  - `tools/ep7_bundles_bin.py` accepts +51 0..1 (tone rule).
  - `tools/ep7_movie_bin.py` accepts +51 0..1 and needs +52..63 zero.
  - `webapp/` is not updated.
- **Older firmware rejects files with +51 = 1:**
  - **v0.27 and older reject the whole BUNDLES.BIN** (all four COLOR looks fall back to the flashed table).
  - **v0.26 and v0.27 reject MOVIE.BIN** (the Movie slot doesn't load, so movie is stock Vivid).
  - Before going back to v0.27, set Sharp to Camera on every profile and on the Movie slot, then half-press to save.
- **Left out:** live-view preview in stills mode (still sharpened, like NR), MONO, Natural and the other picture modes, and the `0x6030ec11` read.
  Lens detail compensation (`ucMTFMode`, `LensMtf*`): only debug-dump and lens-data strings were found. No consumer was traced, so it isn't touched.

**Emulator checks** (`verify.py`, all pass):

| Check | Result |
|---|---|
| S stills | Real capture site + `sc_slot`: −5 only for COLOR1-4 with +51 == 1; picture modes 11, 6→11, 2, 12, 1; profiles 0..5, 255; stock otherwise and == v0.27 (630) |
| G gain | Stock stage, key 11, Sharpness −5: gain 0 at every ISO field, full-size and resize branch; stock Sharpness == v0.27; stage code and tables unchanged (65) |
| M movie | Real message site → `sh_msg` → `mv_msg` → return: +18 = −5 only on the full gate; all other message bytes and registers == v0.27, including no table, bad magic, state 0 / 0xFFFF, no VM magic (216) |
| E Extras | Sector 10 get / set (−3..5 → 0/1, dirty) / label, other sectors == v0.27, sectors 11-12 label (34) |
| K kept | Film pick (look, own, Stock), `*`, defaults (18) |
| F files | Span table, mv_load, both tools (4) |
| Y alignment | Data labels and every word or halfword access the block made in these runs (98) |
| P anti-brick | Package reparses, restore == stock, decoded == stock + edits, only our sites differ from v0.27 |

## 5. Camera checks for t1

The same tripod scene throughout (fine text, a dark-on-bright edge), ISO 200, the same exposure, and identical looks on COLOR1 and COLOR2.
1. **Boot and menus:** the Firmware screen shows `0.28t1`. Open the Extras wheel on COLOR1: sector 10 reads `10 Sharp Camera`, and sectors 11-12 read `Extras: 1-10 only`. Grain (1) and NR (9) behave as in v0.27.
2. **Stills:** COLOR2 at Sharpness 0, COLOR2 at Sharpness −2, then COLOR1 with Sharp Off. COLOR1 must be softer than −2, with no light or dark rim on the edge. Repeat at ISO 3200.
3. **Stock unchanged:** Natural, and COLOR2 with Sharp Camera, match v0.27 shots.
4. **Keeps:** pick a Film look, Own and Stock on COLOR1, and reset the profile: Sharp stays Off, and the `*` doesn't appear because of it. Power-cycle: Off is still set (BUNDLES.BIN saved).
5. **Playback INFO:** play each shot back and cycle every INFO page. The camera must not hang, and the picture-mode or sharpness text must look sane.
6. **exiftool:** `exiftool -Olympus:Sharpness -Olympus:PictureMode*` on the COLOR1 Off JPEG (and ORF if shot). Expect −5 or an odd value. Stock shots must show their real setting.
7. **Movie:** with the Movie slot set to Sharp Off (Live Control INFO on movie Vivid → Extras sector 10), half-press first, then record 4K and FHD clips against the same scene with Camera. Off must be softer. Also check clip playback and `exiftool` on the clip.
8. **Downgrade warning:** set every Sharp back to Camera before flashing v0.27 again (see above).

**Failure modes:**
- If 2 shows no difference, the capture read isn't the route. The fallback is the packer `0x60354eeb`.
- If 7 shows no difference, recordings take another route; the open lead is `0x6030ec11` / `0x6031be74`.
- A crash on playback INFO would mean a display table is indexed by Sharpness: set Camera, and the fix is to keep the stored value in range.
- A crash at live-view start in movie would point at `sh_msg`. It is emulated on every branch but runs on every settings message.

**Unproven:**
- That −5 reaches the JPEG (the chain is static, the stage emulated).
- That the message route reaches recordings.
- How playback and EXIF show −5.
- Lens detail compensation.
