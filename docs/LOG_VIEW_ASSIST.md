# View Assist for log video (E-P7 1.1): feasibility

This is offline research only. Nothing has run on a camera, no SD-update-named file was created, and
nothing was committed. Addresses are CPU addresses in main (base `0x60020020`, decoded SHA-256
`5dd9af16…6190`). The background is in `docs/VIDEO_LOG.md`, which covers `patches/video_log`, +925 and
the gamma tables.

Labels: **[V]** means read from bytes or disassembly, or run in the emulator on stock code. **[I]** means
inference.

Tool (ours, read-only): `tools/ep7_view_assist_probe.py` runs checks S1–S3, E1, E2 and C1, described
below. They all pass (`python3 -I tools/ep7_view_assist_probe.py [--json r.json] [--lut-out lut.bin]`).

## Verdict

**Feasible, using the display engine and not the ISP. Built and emulator-verified, not yet tried on a
camera:**
- `releases/probe-VA0`: flash this first; it confirms the playback signal;
- `releases/test10-viewassist`: the feature.

Both are on the test7b base, and both use trigger T-D and the through-image signal `0xa272c418` bit 0.
See "Build".

The live-view gamma cannot be split from the recorded gamma inside the ISP. There is one development
per frame and one gamma for it. The display controller ("VSC") has its own hardware LUT, though:
256 entries for each of R, G and B, double-buffered, and applied per output channel. The stock firmware
carries all of the code to load it, plus a 20-slot step table. On the E-P7 this LUT does nothing: every
TFT slot is identity, open/init writes the mode register to bypass, and no stock code sends the command
that loads it.

A log→Rec.709-style curve loaded into that LUT gives a View Assist that:
- touches only the LCD (VSC channel 0);
- leaves the recording and HDMI (channel 1) in log;
- costs no ISP time.

The data side is a 12-byte table edit plus a 256-byte LUT, which can go into the dead EVF tables. The
programmer, register format and mode switch are emulator-verified. What is still open is the code that
switches the LUT on and off in the right task at the right moments. See "Open items".

## Q1: does live view use a separate path from the recorded stream?

**There is one development, and the displayed image is derived from the same developed YCbCr. Display
post-processing is separate.**

Verified:
- The ISP colour-output descriptor has exactly one RGB gamma triple, at +2596/+2600/+2604. Its only
  writer is `0x603ae7d3`; there is no second "sub/display" gamma field anywhere in
  `0x60398000–0x603b6000`. There is also one luma LUT (+2608/+2612 family).
- The movie job's table fetch `0x6039a97b` (← `0x6035169b` ← `0x60351174`, the RECVIEW/movie job path
  in VIDEO_LOG X2) takes one gamma (`0x603ae354`) and one luma LUT (`0x603b092f`).
- The 980-byte "compact ring" `0xa2731098` (HSL_PORT, WB_AND_MONO: the live-view candidate) is **the
  same ring** whose record +925 drives the log mode (VIDEO_LOG X1: records at
  `0xa2731098 + 980·k`). So the live-view settings slot and the movie development request come from
  one record.
- The display controller reads a finished "through image" buffer (`img_hd`, `img_format` in the
  display packets) and does its own output processing:
  - gamma (`attr_gam`, see Q2);
  - LPF (`attr_lpf`) and rotation (`attr_rot`);
  - highlight/shadow warning (`attr_hilight`/`attr_shadow`);
  - edge peaking (`egpk_prm`, display command `SET_EG_PK`);
  - histogram (`r/g/b/y_buff`);
  - OSD mixing.

  Strings at `0x601d7db3…0x601d8727`; command names at `0x601d78e2…0x601d7b0a`.
- This is why peaking and the highlight/shadow display never reach the recording.

Inferred:
- Live view in movie mode shows log because it is the same development (VIDEO_LOG already expects
  this).
- The task names `MVR_IMG1/MVR_IMG2/REC_PV1_CPU2` and the RSZ1–35 resizer channels point to the frame
  being resized into a movie copy and a display copy after development. This is not traced.
- If the first on-camera test of `patches/video_log` shows a *normal* live view, this inference is
  wrong, and View Assist is unnecessary.

## Q2: where the display picks its gamma, and remnants

### The VSC display gamma [V]

| Item | Address | Detail |
|---|---|---|
| Display task dispatch | `0x60174667` → jump table `0x601d3a20` | Command 8 = QUALITY → `0x60174bdb`. The names table at `0x601798d1` is 1-based: 1 FASTBOOT, 2 OPEN … 7 BRIGHTNESS, 8 QUALITY … 22 COLORTEMP |
| QUALITY handler | `0x60186432` | Packet {u32 device mask, `attr_gam*`, `attr_lpf*`, `attr_rot*`}. Gamma → `0x60187439` |
| Gamma programmer | `0x60187439` | Device mask 1 (TFT) → index 0; mask 2 (built-in EVF) → index 1; anything else returns. `attr_gam` → u8 step (< 20). **Step 16 = bypass** (all channel modes 0). Otherwise it looks up the step table, writes R/G/B into the inactive bank, then flips the mode |
| Step table | `0x601e3b3c` | 2 devices × 20 slots × 16 B {u8 step, R*, G*, B*}. Slots 0–14 = steps 0–14 (MN7…PL7, matching the debug CSV names `MN7GAMMACSV…PL7GAMMACSV`). **Slots 15–19 = steps 16, 17, 18, 19, 0 with NULL pointers (spare)** (S1) |
| LUT data | `0x601de13c–0x601e3b3c` | 90 × 256 B, 8-bit. **All 45 TFT LUTs are identity** except entry 3 → 2 at step 7 (S1). The EVF LUTs are per-channel scalings (colour temperature) |
| LUT writer | `0x601885f9` | VSC channel c = `0x60043bdd(mask)`: TFT/EVF → 0, HDMI/other → 1. Writes 128 words at `0x9c000000 + c·0x4000 + 4·{2048,2176}` (R bank 1/2), `{2304,2432}` (G), `{2560,2688}` (B). Each word = `(lut[2i+1]<<18 & 0xffff0000) \| (lut[2i]<<2)`, so the output is 10 bits (E1) |
| Mode register | `0x9c000204 + c·0x4000` | `(R<<8)\|(G<<4)\|B`: 0 = bypass, 1 = bank 1, 2 = bank 2. Writer `0x601885a8`, reader `0x60189198` (E2). The programmer ping-pongs: current 0 or 0x222 → load bank 1, set 0x111; current 0x111 → bank 2, set 0x222 |
| Bypass writers | `0x6018819c`, `0x60188307` | Write 0 to the mode register in the TFT open/close init (`0x60184ad6`, `0x60184aa6`). The only other references are the programmer, the reader and a register-dump list (S3) |

**Who loads it in stock.**
- No stock code sends command 8 with a constant id to the display mailbox (`0x60040df4`) (S2).
- The only other caller of the programmer is the EVF colour-temperature path: COLORTEMP → `0x6017773e`,
  mask 2, step = colour temperature.
- TFT brightness and colour temperature go to the panel over SPI instead, using a 15×15×26-byte register
  table at `0x61f9d31e` (`0x60184235` → `0x60184360`).
  Layout (v0.20, `patches/lcd_tint`): .data, init image = address − 0x1d67d40; row = brightness·390 +
  colourtemp·26; words 0–3 → panel cmd 0xd9 [mode 0x80/0x91, R, G, B], words 4–7 → cmd 0x91 (word 7 =
  brightness). G is below R/B at every step (the stock pink). v0.20 rewrites words 0–3 as a green/magenta
  axis: step 7 = 0x91 [0, G·1.08, 0], other steps mode 0x80 with G/RB = (0xe0/0xff)·(1 + (8 + (c−7)·16/7) %).
- **So on the E-P7 the TFT runs with the VSC gamma bypassed, and the LUT hardware and its loader are
  dormant [V static, I that no computed-id sender exists].**
- HDMI is VSC channel 1. The programmer never addresses it, so HDMI output has no display gamma [V].

### Can the ISP live-view gamma be forced to default while recording stays log?

**No**, as far as can be seen. There is a single development and a single gamma (Q1). Forcing
`0x603ae354` back to `0x604ede78` in movie mode would also un-log the recording. The only kind-specific
gamma behaviour is request kind 4 (`0x603b18cd`): its `0x603ae7ee` sets output+4 bit 0x1000 and so
*skips* the gamma update. It does not select a different gamma, and nothing shows it is a display-only
pass [V code, I meaning].

### Remnants of an "assist" or a display-only gamma

- The **VSC gamma path itself** is a complete display-only gamma: loader, double buffering, a bypass
  step (16) and three reserved step ids (17–19) with empty slots. Whether OM bodies use those slots for
  View Assist is unknown [I].
- A debug **gamma CSV loader** has orphaned strings (`gamma_ctrl`, `[display]gamma cvs file read`,
  `@R/@G/@B`, `CDIFKNEECSV` colour-difference knee, `CHROMAPRCSV`, `MN7_CTMPCSV…`) but no code
  references. The debug `lut` command (`0x601789f7`) is a bare `retf` [V].
- Setting 670 (`0x91b1` index 1) is tested by `0x6028e27f`/`0x6028e2ad`, only together with
  MovPicModeType (`0x4501`) == 1. These tests send events 4/6 through `0x6028e6eb` and call the hook at
  `0x6223ed50`. The position next to MovPicMode fits a View Assist flag, but the consumers are not traced
  [V tests, I meaning].
- There is no "View Assist", "OM-Log" or "Log" string in main or the other components [V].

## Q3: minimal patch design (built, see "Build")

Condition: **VSC TFT gamma = VA LUT exactly while record +925 == 2 (log active), otherwise bypass.**
Keying on +925 covers both `patches/video_log` and the stock MovPicMode = 255 route.

### Data (12 + 256 bytes, no new code space)

| Edit | Site | Stock | New |
|---|---|---|---|
| VA LUT, 256 B | `0x601e383c` (EVF slot 0, R) | EVF LUT | `row0 ∘ inverse(id-2001)` (C1) |
| Step-17 slot pointers | `0x601e3c40` (12 B; step byte 17 at `0x601e3c3c` is already present) | 3 × NULL | 3 × `0x601e383c` |

The E-P7 has no EVF or accessory port, so the device-index-1 tables are dead data (that is a product
fact, not proven from code [I]). If a non-EVF location is preferred, the LUT needs a 256-byte claim in
`docs/CODE_SPACE_MAP.md`.

The VA LUT is derived from the firmware's own tables (C1):

| Log 8-bit in | 0 | 32 | 64 | 97 | 130 | 162 | 192 | 224 | 255 |
|---|---|---|---|---|---|---|---|---|---|
| Display out | 0 | 7 | 19 | 40 | 70 | **118** | 168 | 222 | 255 |

Log 162 is the 2001 code for grey at −3 EV below clip, and it maps to 118, the stock JPEG mid grey. The
LUT is applied per R/G/B channel after the VSC's YCbCr→RGB conversion. That this domain is RGB follows
from the per-channel EVF colour-temperature tables [I strong].

### Trigger (code, about 60–90 B; this is the open part)

The programmer must run inside the display task, because it toggles the through-image flag
(`0x60175cdf`/`0x60175c01`, see "Trigger measurement") and the registers are owned by that task. Two candidates:

- **T-A (preferred): a reconcile hook in the display task.** Add a stub on a display-task command path
  that runs whenever live view (re)starts, such as the UPD_IMG handler `0x60174a92` or the end of the
  OPEN handler. The stub:
  1. computes `want = (record[(0xa273104c)].+925 == 2)`;
  2. reads `cur = 0x60189198(1) != 0`;
  3. if they differ, calls `0x60187439(d0 = 1, a0 = &step17)` or `(…, &step16)`.

  This needs no RAM state, because the hardware mode register is the state. Bypass is the stock value,
  so any non-zero mode on the TFT is ours. It also survives the bypass reset at display reopen.
- **T-B: edge-triggered QUALITY send.** From the +925 derivation (`vlog_hook`, `0x60210c90`), send
  command 8 {mask 1, `&step17`/`&step16`} via `0x602c9cf1(d0 = (0x60040df4), d1 = 8, a0 = packet,
  a1 = name)` when the result changes. This catches picture-mode changes inside movie mode, which T-A
  may miss if UPD_IMG doesn't fire then. It does not survive a display reopen on its own.

T-A + T-B together is the robust form. Before building, it needs:
1. how often UPD_IMG and OPEN fire (when live view starts, a mode change, a picture-mode change);
2. whether `0x602c9cf1`/`0x60054b33` block (sync reply) when called from the settings context;
3. a playback rule (below).

Verification would then cover:
- the stub natively;
- 0x60187439 natively with stubs for the lock and memcpy helpers at `0x47001xxx`;
- E1/E2 as now.

### Stretch: user-selectable preview look

Step ids 17, 18 and 19 have three spare slots per device (`0x601e3c3c`, `0x601e3c4c`, `0x601e3c5c`), and
the dead EVF tables hold 45 × 256 B. So up to three looks need only data. Each look can be any
per-channel 1D curve:
- Natural (above);
- a contrastier "Vivid" tone;
- a warm or cool tint, using a different curve per channel;
- a film-style tone from a bundle recipe.

The selector could be a byte in the bundle table (`patches/bundles/layout.json` has no free field
defined; offset ≥ 45 of a slot is unused) or the active COLOR/MONO profile. The stub then picks step
17 + n.

**Not possible here:** monochrome, hue shifts or saturation changes. Those need channel mixing, which
the LUT cannot do. A chroma stage exists only as orphaned CSV strings (`CHROMAPRCSV`, `CDIFKNEECSV`)
with no traced registers.

## Q4: limitations

- **HDMI:** stays log (VSC channel 1 is never programmed) [V static]. That is good for an external
  recorder or monitor LUT. There is no VA on HDMI unless channel 1 is programmed too, and the stock
  programmer rejects that mask.
- **Playback:** the LUT stays on the TFT channel until it is reset. If playback reuses the open panel
  without the init bypass, stills and menus in playback get the VA curve. The rule should be to switch
  off on NOTIFY_PLY (command 41) / playback state, or to key on "movie live view active" as well as
  +925. Whether a display reopen happens when switching to playback is unknown.
- **OSD and overlays:** it is unknown whether the gamma sits before or after OSD mixing. If after,
  menus, icons, peaking colours and highlight/shadow colours are also re-toned. Black and white stay
  fixed, but mid-tones shift. Histogram buffers may be computed before or after the LUT [I].
- **Performance:** no ISP cost. One toggle is 3 × 128 register writes plus a mode write in the display
  task. Double-buffered banks mean no visible tearing [I].
- **Image quality of the preview:** 8-bit input. The log toe is expanded (codes 0–32 → 0–7), so the
  display shows shadow posterisation; the recording is unaffected. The 2001-only tint/chroma stage
  (`0x603b0e56`) is not undone, so colours sit near Natural but not exactly. Per-channel contrast
  restores most of the saturation [I].
- **LCD brightness and colour-temperature menus:** unaffected. They act on the panel over SPI, not on the
  VSC LUT [V].
- **Exposure:** VA makes the preview look correctly exposed when log is exposed with grey at about
  −3 EV below clip, which is the stock AE target. With the −2 EV compensation VIDEO_LOG recommends,
  the preview looks about 2 EV dark. A second look tuned for EC −2 (grey at about −5 EV) is a good use
  of slot 18.

## Trigger measurement (2026-11-01, offline, static)

Display command ids are the 1-based name index (`0x601d78e2` + 12·k); the dispatcher indexes jump table
`0x601d3a20` with id − 2. Senders were found by scanning every reference to the display mailbox id
`0x60040df4` and every call to `0x602c9cf1` [V].

| Candidate | How often it fires | Verdict |
|---|---|---|
| T-A UPD_IMG (id 18, handler `0x60174a92` → `0x60185062` per device) | Rare. It is an image-adjust command (halfwords +16/+18 centred on 128, LPF/attr pointers), not a frame update. Senders: display-internal `0x60186bd5` (from `0x60175eca`/`0x60175edf`, the device-routing path), `0x60c7d8b4`, and app function `0x603207e0`, which has no caller (its only references are its own error-log arguments) [V] | **Rejected.** Does not fire on picture-mode, movie/stills or playback changes |
| T-A OPEN (id 2, `0x60174686`) | Once per display open; the open path writes bypass (`0x6018819c`) | **Rejected** as sole trigger. Useful only as a reset |
| T-B send from `vlog_hook` | Once per capture request (message handler `0x6054d116` → `0x60303ef6` → `0x603263c7` → `0x6030df3d`) | **Rejected (unsafe).** `0x602c9cf1` → `0x60054b33` is a synchronous RPC: reply queue, post, then `0x600513e6` with d1 = −1 (no timeout) [V]. The capture-control task would block until the display task has drained its queue. No evidence was found that this task sends display commands in stock (not exhaustively checked), so a deadlock cannot be ruled out (same failure class as SD_V2_CRASH cause (b)). It also needs RAM state for edge detection and never runs on entry to playback |
| **T-D (chosen): reconcile at the display task's common reply tail `0x601751f4`** | After **every** display command. 37 handler branches converge on `0x601750ef`, which falls through to `0x601751f4` [V] | **Safe by construction**: runs in the task that owns the VSC and the locks (same context as QUALITY), never blocks, no stores outside the stack, the hardware mode register `0x9c000204` is the only state, so the LUT loads once and survives reopen. Hook = 5 bytes at an instruction boundary: `f8 bc 2c 08 81` (`movhu (44,sp),d0; clr d2; mov d0,d1`) → `jmp stub`; the stub replays them and returns to `0x601751f9` |

T-D stub (built, see "Build"):
1. Skip unless TFT is running: `(0xa272c40c) & 1` (the same running-device mask the UPD_IMG/UPD_SCRN
   handlers test before touching a device). This keeps register reads and writes away from a closed VSC.
2. `want = record[(0xa273104c)].+925 == 2` **and not playback**.
3. `cur = (0x9c000204) != 0`. If they differ, call `0x60187439(d0 = 1, a0 = &step17 or &step16)`.
   Save and restore d1/a0/a1 around the call.

**Playback signal (traced 2026-11-01, follow-up): use the display's "through image" mask `0xa272c418`,
bit 0 = TFT.**

What the code shows [V]:
- `0x60175cdf(mask)` returns `(0xa272c418 & mask) != 0`. `0x60175c01(mask, flag 0/1)` sets or clears the
  bits. Both run under semaphore `0x10190010`. These are the through-image flag getter and setter. Earlier
  versions of this doc called them display "locks"; that was wrong.
- The display debug dump labels the getter's value "last through flg" (`0x6017920a` → string
  `0x601d74a3`). The packet field that feeds the setter is `through_permit`: UPD_IMG packet +22
  (`0x601850b3`) and UPD_SCRN/layer packet +34 (`0x60184bbb`, `0x601856b1`).
- Other setters call it directly from app tasks, not through the display mailbox:
  - the through/live-view display module `0x602ac141…0x602ad64c` (1 at `0x602ac3c2`, `0x602acc4d`,
    `0x602acff0`; 0 at `0x602ad34a`, `0x602ad64c`; device mask from `0x602acf12`, which reads
    output-device setting `0x6223e7d6`);
  - `0x6054c34e` (called from `0x6028df95` with 0 and from `0x6028e035` with 1).
- The mask is cleared at display init (`0x60041834`), per device on close (`0x601761fa`), and bit 0
  is cleared on a TFT→EVF switch (`0x601757f8`).
- The programmer `0x60187439` saves the TFT bit, clears it while it loads the banks, and sets it again
  afterwards (`0x601874d7`/`0x601874e6` … `0x60187612`). So a VA load leaves the flag as it found it.
- None of the CBC/CBS/EV play-key name tables (`0x60a6af10`, `0x60a6cd2c`, `0x60a6ef30`) has a code
  reader. They are debug name lists and lead to no state variable.

Inference [I]: playback shows a decoded still, not the through image, so bit 0 is clear in playback.
It is set while movie live view or recording is on screen. It may also clear in full-screen menus;
that is harmless, because the LUT then goes to bypass.

**T-D condition, final:** `(0xa272c40c & 1) && (0xa272c418 & 1) && record[(0xa273104c)].+925 == 2`
→ step 17; otherwise step 16 (only when the mode register is non-zero).

Caveat: the app-side setters change the flag without sending a display command, so T-D reacts at the
next display command. Entering playback redraws the screen and OSD (display commands), so the expected
lag is one command. That is [I].

**Camera confirmation (built as `releases/probe-VA0`).** P-VA0 is the T-D stub with the +925 test removed:
`want = (0xa272c40c & 1) && (0xa272c418 & 1)`.
- It writes no RAM, only the VSC LUT and mode registers through the stock programmer.
- Expected result: the LCD looks contrasty or "graded" in every live view (stills and movie). Playback,
  and the menus if they drop through, look stock. HDMI is unaffected.
- A pass confirms the signal and the reaction lag in one flash. The full build (+925 added) then needs no
  separate probe.
- Recovery: the stock restore package. The worst case is cosmetic (wrong tone on the LCD).

## Build (2026-11-01, offline)

`patches/view_assist/` holds `view_assist.s.in` and `build_and_verify.py`. They write
`generated/view_assist/{probe,full}.json`, `.lst` and `.verify.json`.

| Edit | Site | Bytes |
|---|---|---|
| Hook | `0x601751f4` `f8bc2c0881` → `dc 48 e7 06 00` (jmp `0x601e393c`) | 5 |
| VA LUT | `0x601e383c` (dead EVF step-0 R) | 256 |
| `va_hook` | `0x601e393c` (dead EVF step-0 G): 74 B probe / 105 B full | ≤ 256 |
| Step-17 pointers | `0x601e3c40` → 3 × `0x601e383c` | 12 |

The hook and the code are in section 1, the same section as the display task. The step ids passed to the
programmer are the stock step bytes in the table:
- step 17 at `0x601e3c3c`;
- step 16 (bypass) at `0x601e3c2c`.

The ring index is bounded to < 5: the next static after the ring is at `0xa27323bc` = `0xa2731098 + 5·980`.

Notes on the MN103 `call` convention [V], as the emulator shows:
- A call stores its return address at the caller's `(0,sp)`. That slot is never read by the dispatcher
  (`0x601744f0–0x601752c6`).
- Callee-saved d2/d3/a2/a3 are preserved by the call masks.
- a0/a1 are dead at `0x601751f9`.
- Stack depth is shallower than in the stock QUALITY path, which reaches the programmer through
  `0x60186432`.

Emulator results (all PASS, for both variants):
- **S**: 58-case matrix through the patched hook, with a spy at the programmer:
  - run × through × (+925, index including out-of-ring values) × mode (0 / 0x111 / 0x222);
  - every image region and all state inputs are read-only, and the IO window is unmapped while the TFT is
    not running;
  - checks: call/no-call and step id; replayed d0/d1/d2; d3/a2/a3/sp preserved; dispatcher frame
    untouched.
- **P**: the real stock programmer, mode writer and LUT writer, run in sequence. Log on writes VSC TFT
  bank 1 (`0x9c002000/2400/2800`) with exactly the VA LUT words and sets mode 0x111. Then:
  - a repeat changes nothing (loads once);
  - playback (through flag off) gives mode 0;
  - back in live view the LUT reloads;
  - log off gives mode 0 (full) or no change (probe);
  - TFT not running changes nothing.
- **M**: every mutant fails S or P (10 mutants for the probe, 15 for full), covering the gates, bits, step
  swap, device mask, replay, ring bound, stride, +925 offset and value, and load-every-time.
- **K**: S and P re-run on the main payload decoded from each built `patched.pkg.bin`. The four spans
  are byte-identical to the verified image.

Releases (local only, names not SD-loadable; restore identical to test 7b's):

| Release | Edits | Changed bytes |
|---|---|---|
| `releases/probe-VA0` | 38 | 2,732 |
| `releases/test10-viewassist` | 38 | 2,763 |

Residual risks:
- The playback meaning of the through flag is [I]; probe-VA0 confirms it.
- The reaction can lag by one display command, because app-side setters change the flag directly.
- Whether OSD is re-toned (gamma before or after mixing) is unknown; it shows on the camera.
- The EVF step-0 R/G tables now hold the LUT and the code. They would only be read by COLORTEMP for the
  EVF, which runs only when the current device is the EVF (`0x60174d19`); the E-P7 has no EVF.

## Open items before building

1. Done: see "Trigger measurement". T-D chosen; the send (T-B) is synchronous with no timeout.
   Playback signal: `0xa272c418` bit 0 (traced; playback meaning [I], confirm with P-VA0).
   Built: probe-VA0 and test10 (see "Build").
2. Whether the VSC gamma applies before or after OSD mixing. On the camera this shows directly.
3. The first camera test of `patches/video_log` must confirm that live view is in fact log (Q1
   inference).
4. Any camera test needs the usual go-ahead and the SD_UPDATE.md risk notes.

## Issue #17 re-check: was the LUT really baked into recordings?

**Verdict: the VSC LUT is still the display-only path. The "baked in" finding is unproven [I].** There is no better path to look for.

- [V] This doc, Q1: the recording comes from the developed image; the VSC reads a finished buffer and applies its LUT on output, as
  with peaking. That VSC output is never written back to memory is [I]: no write-back path was searched for.
- [V] WORKLOG line 288 and commit `4e4b7f3` ("suspected log override"): the same v0.14 build **also** fixed the log trigger (stills
  picture mode vs movie picture mode, broken since 12e). The p1 1 → p1 13 result therefore has two changes behind it. No clip was
  compared with only the LUT changed.
- [V] CODE_SPACE_MAP: `0x601e383c–0x601e3a3c` (old LUT and hook) now holds v0.15 mc data, v0.21 labels and v0.22 code. The step-17
  pointer `0x601e3c40` and hook `0x601751f4` are stock again. A return needs a new 256 B LUT + about 105 B code home, and the T-D
  test must use the v0.14 movie-picture-mode decision, not +925 alone [I].

**Decide with one A/B, before any port:** on the current build, flash a test with the LUT forced on while recording log, and compare
the clip's p1/p50 with the same scene on the plain build. If they match, restore it with a user toggle. If not, the VSC output does
reach the encoder on this body, and no display-only path exists. WORKLOG says it must not come back "in that form", so this is the
user's call. Effort: small (data 12 B + 256 B, hook 5 B, stub about 105 B). Risk: cosmetic on the LCD; a recording shows the result.
