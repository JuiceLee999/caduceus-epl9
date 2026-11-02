# Vignette as an Extras sector (8; 6/7 are Blacks/Whites since v0.19): plan (not built)

Status: **not built** in v0.17. It is not a small, clearly safe change: COLOR stills have no shading stage today, and
turning one on means new work-list entries and a stock mask buffer whose key-11 behaviour has not been traced. That
is the same class of change as the White Edge / Frame Art Effects (job flags 0x2000 / 0x8000), which v0.15 had to
turn off after camera use. Offline findings so far are marked [V] (read from the decoded main) or [I] (inference).

## What exists

- **Slot byte already in the ABI.** Bundle `+30 vignette` (s8, −5..5) is in layout.json, the SD loader v3 range
  table, LOOKS.BIN (bytes 0..44) and the tools. It is stored only, with no consumer. So no new card format is needed:
  old files have 0 = off.
- **Shading level in the request** [V]: the packer 0x60354ce4 copies params+5552 → request+1829 (params+5551 →
  +1828 = MONO grain) at 0x60354f3c. Kind-3 (art) requests use request+661 (0x6035b0f0, 0x60370da5, …).
- **Combiner 33** 0x603a06f8 [V]: mode 0x1002 (lerp toward a constant colour). bank+120 = 0x008080FF (white) if the
  level read from request+1829 (kind 0) / +661 (kind 3) is ≥ 0, else 0x00808000 (black). It reads only the **sign**:
  the strength is in the mask and the level gain at request+680 (1024 = neutral, written at 0x603553ea, 0x6035b0f8,
  0x6035c60d, …).
- **Mask** (HALATION_RED §10c) [V]: the cache 0x6036b635 (4 × 100-B objects at 0xa27364e8), generator 0x6036cec0
  (descriptor fmt 0x080C, 128 × 128, stride 128, centre 64/64), memory from the memory manager (message 19), then filled
  on the CPU by 0x603390a4 → 0x60338d49: u16 Q10, 1024 at the centre, a radial table 0x604ebf1c.
- **When the mask is made** [V]: the work-list builder calls the cache at 0x60358312 only when the job's effect-flag
  word has bit **0x2000** (White Edge) or **0x80000**. The result goes to job+14240; if it fails, the build aborts
  (0x60358341).

## Proposed route (smallest)

1. Find who sets job flag 0x80000 and params+5552 for MONO "Shading Effect" (converter, mode-12 gated). Confirm that
   0x80000 is the shading flag and not another effect.
2. COLOR stills: in the existing Art stub path (bloom_flag → `art`, 0x601e1d3c, key 11, profile 1..4), for a slot with
   vignette ≠ 0, set job flag 0x80000 and params+5552 = the stock MONO level that matches the sign.
3. Finer steps (−5..+5): scale the level gain request+680 at the shading request (one store after 0x6035b0f8 /
   0x603553ea, 1024 × k/n). This changes no buffer. Avoid writing our own 128 × 128 mask: buffer size and timing are
   stock-owned.
4. Extras sector 8 `8 Vignette -3` in ex_ui. Live view: later (lv_art can set the same flag).

## Questions to answer before building (offline, emulator)

- Does the key-11 work-list (with 0x80000) add the same entries as MONO's (as for the Art flags in
  `tools/ep7_art_verify.py` L)? Does any stage gate on key 12?
- Mask memory: the message-19 allocation on a COLOR job. Is it the same pool and size as MONO? Is it released by the
  same callback?
- Which request (kind 0 vs 3) carries the shading pass on COLOR? That decides +1829 vs +661.
- Why White Edge / Frame (0x2000 / 0x8000) were dropped in v0.15. If they failed on the camera, the 0x2000 mask route
  is suspect and 0x80000 needs the same check.

Tests, when built: the converter / stub sets the flag and level for each vignette value; 0 == v0.17; no card table
== stock; work-list entries == MONO's; anti-brick.
