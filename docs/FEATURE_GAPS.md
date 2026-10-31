# E-P7 feature opportunities

Evidence levels: **[code]** = string/code found in the E-P7 main program (block 0);
**[menu]** = English UI string in the OSD resource (block 1, possibly shared across models,
so presence ≠ feature); **[spec]** = speculation. Offsets are decoded-file offsets unless
written as CPU addresses (0x60…).

## Ranked

| # | Feature | Evidence | Feasibility | Value |
|---|---|---|---|---|
| 1 | **Per-sector HSL + film-sim recipes** | [code] COLOR builder/table mapped; fixed-H/L patch built + emulator-verified (docs/HSL_PORT.md) | Moderate (in progress) | Very high |
| 2 | **Video recording-length limit** | [code] routine `0x60319139`: modes 3/6/8/9 → `mov 1740,d0` @`0x60319156`, mode 4 → `mov 7200,d0` @`0x6031915b` — same shape as PEN-F `60566309` whose published patch sets 32400 | Easy (4 operand bytes; PEN-F/E-M5 II precedent). Chapter/file/thermal limits may remain | Medium |
| 3 | **Colour film grain** | [code] `COLORTONE_GRAINY_FILM*`, Film Grain Effect (Mono Profile) [menu 2772–2776]; grain HW combiner (fishcu GRAIN.md) | Moderate: enable grain job on COLOR path | High (Fuji users love grain) |
| 4 | **Extra aspect ratios / frame lines (XPan 65:24, 21:9)** | [menu] Image Aspect 4:3/3:2/16:9/1:1/3:4; per-aspect LV grid bitmaps (720×405, 480×480…) | Moderate–hard: aspect table + JPEG crop + overlay; RAW stays full sensor | High |
| 5 | **Flat picture mode** (video/grading base) | [menu] `@A077@Flat` (2886), `@A0C0@Flat` (3258), "Flat & Muted" | Unknown: need to find picture-mode table in main and whether Flat's tone LUT exists | High for video |
| 6 | **Focus bracketing** | [code] `fcs_calc_focus_bracket_info` (0x6f6936); [menu] Focus Bracketing / Focus Stacking (3344/3272) | Unknown–moderate: check whether the bracket engine is gated by model flag or absent | High (macro) |
| 7 | **High Res Shot (pixel shift)** | [code] `HIGH_RES`, `HAND_HIGH_RES` (0x6cd88f/0x6cd8b2), `iseqPixshiftSrCbGetHighResolution*`; [menu] High Res Shot (2438) | Hard/risky: needs sub-pixel IBIS control + compositing; may be library stubs | Very high if real |
| 8 | **Pro Capture** | [code] `[pro_cap] …Plural_Cursor_Move_Set_Mode_Actuator` (0x1163a90); [menu] Pro Capture High/Low (3141/3142) | Hard: pre-buffer memory/throughput | Medium |
| 9 | C4K video | [code] `MOVIE_C4K` (0x1aa2e2); [menu] C4K (3224) | Hard: sensor readout/encoder/thermal | Low–medium |
| 10 | Timecode | [code] 145 timecode strings | Unknown | Low |

**Absent (would need new code — infeasible for now):** Live ND (0 hits), Starry Sky AF (0),
OM-Log (0), zebras (0), false colour/waveform (0), anamorphic desqueeze (0).

**Already present on E-P7:** Live Bulb/Time/Composite, peaking (+colour), HDR BKT,
interval/time-lapse, keystone, fisheye correction, COLOR4/MONO4 profiles.

## Notes
- "High-end lens only" gating: on E-M1-class bodies focus *stacking* had a lens allowlist
  (historical patches removed the branch). On E-P7 the question is whether the bracketing
  engine exists at all; item 6 is the first thing to trace.
- The OSD resource looks multi-model (strings for features the E-P7 never shipped), so
  every [menu]-only item needs a [code] trace before it counts.
- Next steps: (a) port item 2 (tiny, precedent); (b) trace picture-mode table for Flat;
  (c) trace focus-bracket gating; (d) colour grain job on COLOR path.

## Aspect ratios (traced 2026-11-01)
[code] Three parallel tables list **9 still aspects**; the E-P7 menu exposes only 4:3/3:2/16:9/1:1/3:4.
- u32 table `0x60b8cb60`: (id, w, h): 1 4:3 5184×3888 · 2 3:2 5184×3456 · 3 16:9 5184×2920 · 4 1:1 3888×3888 ·
  **5 5:4 4864×3888 · 6 7:6 4544×3888 · 7 6:5 4672×3888 · 8 7:5 5184×3704** · 9 3:4 2912×3888.
- u16 copy `0x60b0a518` (id,0,w,h); u16 table `0x604e92c6` (w,h,code) with ratio codes 0x304, 0x203, 0x910,
  0x606, 0x405, 0x607, 0x506, 0x507, 0x403, plus **0x911 = 17:9 5184×2734**.
- Plan: unhide hidden ids (find menu allowed-value mask), then repurpose two hidden slots to **XPan 65:24
  (5184×1914)** and **21:9 (5184×2222)**. Needs: menu mask, crop/LV overlay, EXIF ratio. Not yet patched.
