# Hidden video features and other requests: feasibility (E-P7 1.1)

Research only (2026-11-03). Static reads plus a sibling comparison. Nothing was built, emulated or tried on a camera.
**[V]** means read from the image. **[I]** means inferred. Addresses are E-P7 main CPU addresses (base `0x60020020`).

## Sibling firmware used

These were fetched from OM's catalog with `external/oly_fw_analysis/tools/om_firmware_catalog.py`, stored under
`stock_firmware/<body>/` (gitignored, never committed), and decoded with `oly_container.py` (round trip identical).

| Body | Catalog id | File | SHA-256 |
|---|---|---|---|
| E-M5 III | 1370 | `OLY_E_137_1700_0000_0000.BIN` (1.7) | `939260fc…ded2` |
| E-M10 IV | 1400 | `OLY_E_140_1100_0000_0000.BIN` (1.1) | `4f9ea315…9aac` |
| E-M1 III | 1390 | `OLY_E_139_1600_0000_0000.BIN` (1.6) | `73b42ea5…12cd` |

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

## 1. Clean HDMI output: high feasibility, small effort

- **[V] The code is there, not removed.** Record Mode ("video only, no info display") is sid 1276 = 1, and both values
  are in the validator. `CCommon::getHdmiDualContent` at **`0x60d1cb42`** (3 callers) reads sids 305, 44 (movie mode)
  and 1276, and returns content type 2 only when `305 == 0 && 44 == 1 && 1276 ∈ {1, 2} + extra flags`. The same
  305/44/1276 triple is read at `0x60df783c`, `0x60df7a1d`, `0x60e2bfc7` and `0x60d1cc02` (that one also checks
  289 = 17/18, 4K/C4K out). There are also `getPlayRecorderOSDFlag` / `getMenuRecorderOSDFlag` (strings at
  `0x60f9e62a`/`0x60f9e655`) and `CHECK_IS_NOT_HDMI_INFO_OFF`.
- So clean output is **gated to movie mode (sid 44 == 1)**. In stills modes, and for whatever stays drawn in Record Mode
  (battery or warning icons), the info layer goes to HDMI.
- Patch: in `getHdmiDualContent` and the sibling checks, drop the `44 == 1` term, or force the Record branch. That is a
  few branch bytes. To remove an icon that Record Mode still shows, find its draw call under the RecorderOSD flags.
- Risks: low. This is display-only. The LCD may go blank or show a duplicate. **First check on a camera whether stock
  Record Mode already gives a clean feed in movie mode.**
- The E-M5 III and E-M1 III expose the same Monitor/Record Mode in their manuals. Their gating was not compared by
  address because their settings layout differs.

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

## 5. Per-profile "vignette correction off": medium-high, moderate effort

- [V] **The E-P7 has a visible stock "Shading Comp." setting: sid 61**, values [0, 1], main-menu item `0x6117e294`
  (string 254, help 465, list `0x6117c344`). So lens shading correction is a normal global setting, not a hidden one.
- Per profile: read the slot byte (as the Art Effect flag does) and override the value of sid 61 where the still job is
  built. Or patch the reader of sid 61 in the job builder (not traced; start at the shading request in
  docs/HALATION_RED.md: shading modifier `0x6035b0d8`, mask `0x6036b635`; docs/VIGNETTE.md: `params+5552`).
  This is the same pattern as the existing per-slot Extras.
- Risk: low (image only). Note that the stock setting already gives a global off. Rating: **medium-high**, 1–2 sessions.
