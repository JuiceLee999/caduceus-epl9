# Hidden video features and other requests: feasibility (E-P7 1.1)

Research only (2026-11-03). Static reads plus a sibling comparison. Nothing was built, emulated or tried on a camera.
**[V]** means read from the image. **[I]** means inferred. Addresses are E-P7 main CPU addresses (base `0x60020020`).

## Sibling firmware used

These were fetched from OM's catalog with `external/oly_fw_analysis/tools/om_firmware_catalog.py`, stored under
`stock_firmware/<body>/` (gitignored, never committed), and decoded with `oly_container.py` (round trip identical).

| Body | Catalog id | File | SHA-256 |
|---|---|---|---|
| E-M5 III | 1370 | `OLY_E_137_1700_0000_0000.BIN` (1.7) | `939260fc…ded2` |
| E-M10 IV | 1400 | `OLY_E_140_1100_0000_0000.BIN` (1.1) | `73b42ea5…12cd` |
| E-M1 III | 1390 | `OLY_E_139_1600_0000_0000.BIN` (1.6) | `4f9ea315…9aac` |

- **E-M10 IV** has the same code base and layout as the E-P7: the same container addresses and file size, and its
  static validator is at `0x604ceed4` (1214 records). **Every movie and HDMI validator list is identical to the E-P7's.**
  The only differences are the E-P7 colour-profile sids 1645–1707 and the order of 987–989. The E-M10 IV shares the
  E-P7's video limits, so it tells us nothing about video.
- **E-M5 III and E-M1 III** use an older settings layout. The 20-byte validator table is not present in that form, so
  they were compared by tables and strings, not by sid.

## Settings found (E-P7, static validator `0x604cc98c`)

| sid | Meaning (menu string) | Validator list | Notes |
|---|---|---|---|
| 1276 | HDMI Output › Output Mode (3006): 1 Record Mode (3010), 2 Monitor Mode (3008) | `@0x604d2300` [1, 2] | main-menu item `0x6117b04c` (movie section), option list `0x611b9278` |
| 289 | HDMI Output Size: 17 C4K, 18 4K, 16/8 1080p, 6 720p, 3 480/576p | `@0x604cede0` [18, 16, 6, 3] | **C4K (17) excluded**; option list `0x611b7c18` still has it |
| 305 | gate used with 1276 (must be 0) | [0, 1] | [I] HDMI-related flag |
| 1438 | movie type: 1 Standard, 2 4K, 4 High-speed (list `0x6115bd28`) | `@0x604d28c8` [2, 1, 4] | **value 3 skipped**; [I] candidate C4K slot |
| 1439 / 1440 / 1442 / 1441 | movie size / quality / bit rate (3316) / frame rate (3315) | [5,1,2,3] / [1..6] / [2,1,6] / [24,25,30] | gaps (1439 has no 4, 1442 has no 3–5) [I] |
| 6 | ISO: attr 85 (stills, 1/3 steps) and attr 256 (movie, full steps) | both lists start with 0 (Auto) | [I] 0 = Auto |
| 239 / 112 | ISO-Auto enable modes (P/A/S or All) / ISO-Auto Set | [1, 0] / pairs | stills |
| 61 | **Shading Comp.** (string 254), main-menu item `0x6117e294` | [0, 1] | visible stock setting |

## 1. Clean HDMI output: medium, not the "few branch bytes" first estimated

Re-traced 2026-11-05 (static only; nothing built or run). This replaces the first estimate. **[V]** = read from
disassembly or bytes, **[I]** = inference. Verdict: the clean-output mechanism is real and small, but stills also
need a dual-output state that sid 44 is not the only gate on. Worth one 3-byte probe build, not a promise.

### 1.1 What actually removes the overlay

| Layer | Address | Fact | Conf. |
|---|---|---|---|
| OSD flags | `0x61fa90cc` Monitor, `0x61fa90d0` Recorder; setters `0x6079c3cd` / `0x6079c3d6`, getter `0x6079c3df` | Names from the SDK strings `setOsdLayerFlagMonitor` / `setOsdLayerFlagRecorder` (`0x60aa1e44`, `0x60aa1e5f`) | [V] |
| Compositor | Readers `0x6079a8af..0x6079a9bc`, `0x6079b344..0x6079b4a2` (read); `0x6079b8a9..0x6079b9a1` (same flags, not read) | First block: Recorder == 1 zeroes every OSD layer address when the pass is 0, Monitor == 1 when the pass is 1, **and pass 2 is unaffected**. Second block: pass 1 tests Monitor, **any other pass tests Recorder** | [V] |
| Pass to device | `0x6079a6d4..0x6079a72c`, map `0x6079c3e8` | Pass 2 = whole device mask, pass 1 = mask & ~8, pass 0 = bit 8. Map: 16→8, 1→1, 4→16, 8→32, 17→9, 24→40 | [V]; "16 = HDMI" [I strong: `0x607717e4` gives states 8–14 for 16, and `0x60ccc05c..` logs those as HDMI] |
| Decider | `0x60ea3dcb`, only caller `0x60ea1339` (the page setter, right after it stores page `0x61fc4e08`) | HDMI state ≠ 0 or sid 305 ≠ 0: content 0, both flags 0. **sid 44 == 1 and 1276 == 1:** page hash `0x611edf44`, default Recorder 1 / Monitor 0 (`0x60ea3ee2`). Otherwise Monitor 1 / Recorder 0 (`0x60ea3f49`) | [V] |
| Content type | `0x60d1cb42` `getHdmiDualContent`, setter `0x60d1cb36` (this+20), getter `0x60d1cb3c` (26 callers, `0x60d1d763..0x60d1e820`) | Content 2 needs 305 == 0, 44 == 1, 1276 == 1 plus status fields. Those callers draw per display through the `0x607e8de0` object, vtable +12: content 2 draws passes 2 and 1; otherwise pass 2 only | [V]; pass mapping partly [I] |
| Second display | `0x6076b856(which, map)` on mask `0x602cce6a(3)` | Mask with bit 16 plus another bit = dual: which 1 → 16, which 2 → the rest | [V] |

So stock Record Mode means "dual output, Recorder flag set". [I] Removing the sid 44 test from the flag decider alone
may do little in stills if stills still draws pass 2, because the first compositor block ignores the flags on that
pass. The two blocks treat pass 2 differently, so only the camera can settle this.

Other paths to content 2 or a dual state:
- `0x60d1cbdf..0x60d1cbeb`: content 2 with **no sid 44 test** when the `0x607faacb` object's vtable +612 returns 1,
  305 == 0 and 1276 == 1 [V]. That method is untraced.
- `0x60ccdaf4`: returns 1 if the HDMI state is 0, 305 == 0 and (1276 == 1 or 289 ∈ {17, 18}), also with **no sid 44
  test** [V]. Its caller `0x60ccb1f4` logs "4K || C4K" and asks for an output change. So stock stills with Record Mode
  already changes some output state. Check this on the camera first.
- `0x60ccbe07` (target display): HDMI state 0, 305 == 0 and `0x60ccdbea` ≠ 0 → target HDMI (7), else TFT or EVF [V].
  It returns a single target. The code that creates the dual mask was **not found**.

### 1.2 Other sites that gate on sid 44 and 1276

These also test UI state (`this+16`, getter `0x60d1a411`) ∈ {0x8006, 0x8003}, so **sid 44 is not their only gate** [V].
What those two states mean, and which state stills live view uses, is untraced, so what these sites do in stills is
unknown until the probe runs.

| Site | Function |
|---|---|
| `0x60df783c`, `0x60df7a1d`, `0x60e2bfc7`, `0x60dc55a4`, `0x60e9dd21` | Picks `getDisplayDeviceState(1)` (second display) instead of (0) for layout [V, the first three read fully; the last two read as far as the same state test] |
| `0x60d18bb9` (→ `0x60d1cc80`) | Same choice in the output-change handler, 0x8006 only; also needs play/menu flags `0x60d1cd3c` / `0x60d1cd5e` clear [V] |
| `0x60ea2606`, `0x60ea2735`, `0x60ea2ef2`, `0x60ea2fc4` | Page-draw and display-sync paths (vtable +132 with pages 129 / 118) [V] |
| `0x60a36d21` | Plane setup: 1276 == 1, 44 == 1, second display present → display 1 flag 0x200, display 2 flag 0x100 at `(76,sp)` [V]; plane meaning [I] |
| `0x60cea5ae` | 44 ≠ 0 and 1276 == 1: sets `0x60ccdb54(1)`, then clears it unless sid 289 ∈ {18, 17, 16, 8} and the value read through sid 699 is 5 or 6 [V] |
| `0x60d1e01c`, `0x60da5f78`, `0x60dd0821`, `0x60dd0e9a`, `0x60ddcf26`, `0x60de73b6`, `0x60debe95`, `0x60e2c13c`, `0x60e34129`, `0x60e3e4b8`, `0x60ea8dd5` | Read the same settings (with 44, 305 or 289); branch logic not read [V reads only] |

Non-setting uses of the same immediate, ignore them: `0x60315f84..0x60316169` (buffer offset), `0x6097c379`,
`0x6097c393`, `0x609c98a2`, `0x609cfe76` (source line number). Sid 1276 reads with no sid 44 test, output sizing only:
`0x6088202b`, `0x6088204e`, `0x60882d4a`, `0x608989c2`, `0x60898a2a`.

**Sid 44 cannot be faked at its getter.** It also drives the aspect code (`0x602e82a8`), capture sequencing
(`0x60932c9c`) and more.

### 1.3 Menu row

- Row: Video tab (page `0x6117b1ec`, tab 2), item 7 of 13: `{1276, string 3004 "HDMI Output"}` at `0x6117b048` [V].
- No availability gate: the facade's handler `0x602b2fad` only handles sid 1716 (docs/BUTTONS.md) [V]. The two
  sid 44 reads in the menu code (`0x60e0a9a9`, `0x60e1105f`) are not row filters for it [V].
- Item visibility is still unmapped (LOOK_MENUS §2 #9), so "the Video tab opens with the dial on stills" is [I].
- It does not matter much: 1276 is one global setting (one validator record), so it can be set with the dial on
  movie and stays set in stills [I].

### 1.4 Minimal edit list (probe build)

| # | Site | Stock → new | Effect |
|---|---|---|---|
| E1 | `0x60ea3e5e` | `c8 05` → `ca 05` (1 byte) | Flag decider skips the sid 44 test |
| E2 | `0x60d1cb92` | `c9 20` → `cb cb` (2 bytes) | `getHdmiDualContent` skips the sid 44 test |

Neither overlaps `releases/v0.24/edits.json` [V]. Expected follow-up if the probe shows a dual state with a wrong
layout: the state tests in §1.2 (`0x60df7875` / `0x60df7a3e` / `0x60e2bffd` blocks, about 10–30 bytes). If the
probe changes nothing, the dual-mask creator has to be traced, and this becomes a hard item.

### 1.5 Failure modes

Display only, with no flash or settings writes. Worst expected outcomes [I]:
- HDMI still shows the overlay.
- LCD blank or wrong layout, because the LCD gets Monitor 0 / Recorder 1 while it may be the only output.
- `cw_updateDualDisplay` logs "Unsupported Pass" (`0x6079adba`, `0x6079ae02`) and carries on [V].
- A hang in a display path. That is cleared by a battery pull and, while HDMI is unplugged, the decider takes the stock
  "both flags 0" exit if the HDMI state is non-zero then [V path, I meaning].

The patch adds no boot-path code. Brick risk is the normal package risk only, and the restore file still applies.

### 1.6 Camera test

Gear: micro-HDMI (type D) to HDMI cable and a monitor, or a cheap USB capture dongle so a PC can record the feed.

1. **Stock firmware, no build:** Output Mode = Record, Size 1080p. Dial on movie: is HDMI clean, is the LCD on? Dial on
   P: what do HDMI and the LCD show? Stock-only probe, and it may already settle how much is left to do.
2. Probe build (E1 + E2), P mode: HDMI clean? LCD still live and with info? Half-press, shoot, playback, menu.
3. Monitor Mode and HDMI unplugged must behave as stock.

## 2. ISO Auto in movie M: medium feasibility, effort unknown

- [V] The movie ISO list (sid 6, attr 256) already contains value 0, which is Auto [I]. So the validator does not hide
  it. The restriction in movie M is dynamic: in the AE or exposure-mode code, or in a mode-dependent availability
  check. No GUI availability handler exists for sid 6 (`0x602b2fad` only handles 1716, docs/BUTTONS.md).
- Not located within the time box. Next step: trace the movie-M ISO clamp in the AE mode code (`0x6015e…`/`0x6016e…`
  area, docs/VIDEO_LOG.md) and the SCP's ISO option filtering in movie mode.
- The E-M5 III and E-M1 III allow Auto ISO in movie M, so the AE engine supports it. A patch is probably a single
  branch once the gate is found. Risk: low (exposure only). Rating: **medium**, 1–3 sessions.

## 3. Hidden video modes: C4K is low–medium, FHD 120p is low

- **[V] C4K is hidden, not removed.** E-P7 and E-M5 III both contain the sensor drive-mode list (`MOVIE_4K`,
  **`MOVIE_C4K`**, `MOVIE_HS`, …; debug print at file offset `0x1aa2ea`). The 4096×2160 u16 geometry pairs are as
  common in the E-P7 (26) as in the E-M5 III (25), and HDMI C4K output (`HDMI_C4K_24HZ`, sid 289 = 17) exists. The UI
  strings "C4K" (3224) and "(C4K)" are present. The movie-type validator skips value 3 [I: the C4K slot].
- What blocks it: the menu or validator (easy), then **whether the E-P7's sensor and encoder setup has a populated C4K
  register set and a 237 Mbps (IPB) rate entry.** No literal 237M or 102M bit-rate constant was found in any of the
  four bodies, so the rates are coded some other way. Not traced.
- **FHD 120p:** the E-P7 HS mode is 1280×720 120fps (string 3410), and no FHD-120 string is in its OSD.
  The E-M5 III has FHD 120p; it shares the `MOVIE_HS` drive mode but would need a different readout window and encoder
  level. **Low.**
- Risks:
  - Heat: the small PEN body has no 4K-length thermal margin.
  - Encoder level: 4096 wide at 237 Mbps is beyond the E-P7's 102 Mbps 4K.
  - Card speed: needs a U3/V30 card.
  - Sensor readout: C4K uses a wider window than UHD, so the rolling shutter and the line-time setup differ.
  - Buffer sizes: the movie buffers are sized for 3840 [I].
  - A wrong sensor or encoder setting can hang the camera, which is recoverable with the restore file.
- Rating: **C4K low–medium** (validator and menu: easy; making it record: weeks plus camera tests).
  **FHD 120p: low.**

## 4. Live ND: low, needs new code

- [V] The E-M1 III main has the Live ND pipeline (`IMGBUFF_ALOC_DIGITAL_ND_9BIT_BAYER*`, `ISEQ_ND_BAYERINFO`,
  `ISEQ_ND_COMPINFO`, …). **The E-P7 and E-M5 III have none of it.** Only a factory life-test name
  (`LIFE_TEST_MODE_DURABLE_ND_FILTER`) appears there.
- The E-P7 does have Live Composite, Live Time and Live Bulb (strings 1549/1551/2585 and their code). Live Composite is a
  lighten-max combiner, not an average. An N-frame average would need a new accumulate mode in the composite job,
  9-bit headroom buffers and the exposure split. That is new ISP sequencing with no stock template. **Low**: a research
  project, months.

## 5. Per-profile "vignette correction off": easy, if the camera test confirms the override

Re-traced 2026-11-05 (static only; nothing built or run). **[V]** = disassembly or bytes, **[I]** = inference.
Verdict: a read-site override is small and safe. What is not known is which of the readers changes the image.

### 5.1 Who reads sid 61

- [V] The UI is a normal setting: main-menu item `0x6117e294`, string 254, help 465, list `0x6117c344`, validator record
  301 at `0x604ce110`, values [0, 1], **property key `0x8c21`** (ID table `0x604d6c14`[61]).
- [V] Whole-image scan: **exactly four reads of key `0x8c21`**, each `call 0x6005e971,[d2,d3],12` (7 bytes, `dd`). No
  non-GUI read by sid through `0x602cbc0a` was found.

| # | Key load | Call (edit rel32 at call+1) | Function | Role |
|---|---|---|---|---|
| R1 | `0x6030308b` | `0x60303093` | Capture parameter setup, same function family as the WB reads | Stores cap+3060. **No reader of cap+3060 found** across the image (direct or base+offset) [V] |
| R2 | `0x602ab47f` | `0x602ab488` | `0x602ab42d`, callers `0x60297fbe`, `0x6029f37a`, `0x602a21c9`, `0x602a5534` | If the record's +4 has bit 8 and key == 1, sets bit 0x2000 in the request flags. Beside the lens still commands [I] |
| R3 | `0x60299b6c` | `0x60299b75` | Key == 1 → `0x602a79ef`, then `0x6029a2b7` | Runs a lens-side data step [I] |
| R4 | `0x6029fe5c` | `0x6029fe64` | Key == 1 → `0x602a79ef`, then `0x6029c1da(…, 2, 0)` | Same [I] |

Related, not sid 61 readers [V]:
- Debug print `0x6055c282`, "STILL_EXEC_SHADING_POST", 16 u16 from `0x601f2838`.
- `0x600f1295` copies those 16 u16 to cap+4268 (no other reader found; debug print at `0x600f1fd3`).
- RAP stage names "RAP_SHADING_SETTING" at `0x601cab46`.

[I] So correction seems to depend on lens-side data, and R2–R4 are the likely gates. **Where the correction is applied
to pixels was not found.** The earlier note that it can be overridden "where the still job is built" has no site behind
it. This is not the stock MONO "Shading Effect" stage in docs/VIGNETTE.md either: that one darkens or lightens corners
through job flags and is a separate feature.

### 5.2 Patch

Redirect all four `call` rel32s to one stub, the same technique as `wb_get` (14 sites, docs/WB_PATCH.md):

- Stub: resolve the COLOR slot as `wb_get` does. If the slot byte says "off", return 0. Otherwise tail-jump to
  `0x6005e971` with the frame untouched. Key test not needed, since only these four sites enter it.
- Return value 0 is the stock global Off, so every reader sees a value it already handles [V]. No new state and no
  settings write; the user's menu value stays.
- **Avoids the NR limitation.** NR writes a global on look pick or sector edit, so it lags a profile switch. A read-site
  override reads the current slot each time, so a profile switch applies at once. R1 runs per capture [V]; R2–R4 run on
  lens-side paths [I]. A settings-manager write on profile select would have the NR problem and also change the user's
  saved setting: rejected.
- One small gap: if the profile changes between a lens-side read and the capture, one shot may mix the two [I]. Image
  only.

**Storage:** slot byte **+49**. Bytes 49..63 are unused and must be 0 today (`patches/bundles/layout.json`) [V]. 0 = follow
the camera, 1 = off.
- SD loader v3: range table +49 → 0..1. Data only, same as the v0.19 swap for +47/+48.
- A Film pick zeroes bytes 45..63 (FILM_MENU_V2 §4) [V], so a pick resets this to "follow camera", unless the pick path
  is changed to preserve it.
- It is per profile slot, not per look: LOOKS.BIN records carry bytes 0..44 [V]. Adding it to looks would change the
  record format.
- Do not reuse +30: it is the vignette strength (looks already fill it) and stays for docs/VIGNETTE.md.

**UI:** Extras sectors 8–12 are free (they show "Extras: 1-7 only") [V]. Sector 8 is pencilled for vignette strength, which
is not built and needs the riskier job-flag work. Options: take sector 9 and leave 8 reserved, or take 8 and move
strength to 9. Taking 8 reads better on the wheel; it changes the roadmap line in the README at the next README update.

**Code space:** free in `releases/v0.24/edits.json`: `0x601e38fb–0x601e3c3c`, dead EVF step-0 tables. `0x601e393c` is
step-0 G (only ref `0x601e3c84`) [V]. Claim it in docs/CODE_SPACE_MAP.md when built.

**Size:** 4 × 4 B rel32, stub about 50–70 B, Extras get/set/label about 60–100 B, 1–2 data bytes in the loader's range
table. Tools and the web app also need the new byte; add it under `color_fields` in layout.json so the LOOKS.BIN
`layout_crc` stays the same, as +47/+48 did.

### 5.3 Camera test

Same lens, wide open, evenly lit wall (a wall or grey card shows corners best), COLOR1 = off, COLOR2 = camera:
1. Baseline on stock: Shading Comp. On, then Off. **Do the corners change?** If not with this lens, use another.
2. Build, menu Shading Comp. On: COLOR1 corners must match the stock Off shot; COLOR2 must match the stock On shot.
3. Switch COLOR1 ↔ COLOR2 without touching Extras: the next shot follows the profile.
4. If step 2 shows no change, the image path uses another read. Then trace it from cap+3060's bulk copy.

Risk: low, image only, and every reader gets a stock-legal value.
