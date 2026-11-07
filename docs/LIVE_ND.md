# Live ND on the E-P7

Research only (2026-11-07): static reads of the E-P7 1.1 main, nothing built or run.
**[V]** = read in the image, **[I]** = inference. Addresses are CPU addresses (file offset + 0x60020020).

**Verdict.** The OM-style Live ND module is not in the E-P7. The part that matters is there, though: stock
**Multiple Exposure** already averages Bayer frames. Its combiner loops over N frames, and with Auto Gain on it
gives each frame a gain of 1/N. A useful "Live ND lite" (ND2 to ND4, maybe ND5) needs only menu and validator data,
not new code. Real ND8 to ND32, taken with one press and shown in live view, would be a new module. It is not worth
starting.

This corrects VIDEO_HIDDEN §4 ("none of it") and FEATURE_GAPS ("Live ND (0 hits)"): the name table is present, but
the code is not.

## 1. Live ND remnants

- **[V] Function-name enum only.** The iseq trace-name table at `0x6070567c` has pairs (id, name) and 823 ids. Its
  lookup is at `0x6060b86c`. The table names the whole Digital ND module: `iseq_StartNd`, `iseq_SetNdHandle`,
  `iseq_ExecNdExposure`, `iseq_TermNdLv`, `iseq_ExecNdLv` (ids 3–7), and `iseq_nd_*` / `iseq_ndlv_*` (ids 719–822).
  The latter include `iseq_nd_if_dsp_multi_exp_stl/_lv`, the light and dark frame managers, `ndlv_judge_shake`, and
  `comp_countup/retention`.
- **[V] The code is absent.** The iseq source-file names compiled in (`0x60707094..`, used by asserts at
  `0x6060bc63..0x6060f993`) are only `iseq_mng_cmd.c`, `iseq_sub.c` and `iseq_swpa_*.c`. The local E-M1 III main also
  has `iseq_nd*.c`, `iseq_ndlv*.c` and the `ISEQ_ND_*` dumps; the E-P7 has none of them. Pixel-shift (`iseq_pixshift_sr_*`)
  is enum-only in the same way.
- **[V] Other leftovers:**
  - Sensor-mode flag name `DIGITAL_ND` = bit 0x400 in the flag dump at `0x6060210f`. HAND_HIGH_RES is 0x800 and
    COMPOSITE is 0x4.
  - The AE debug record "THR TAG MOV & DIGITAL_ND" with fields mov/nd_frm_max/tv/rst (`0x613eeda4`, record type 7,
    bytes +81/+76/+78/+80).
  - The help text of the debug command "iseq extif 4 (Digital ND Filter)".
  - The factory `LIFE_TEST_MODE_DURABLE_ND_FILTER`.
- **[V] No UI.** No ND string exists in `generated/osd/strings_en.json`, and no setting id or job type for it was found.
  **[I]** The headers are shared across bodies, so these names prove nothing about the hardware.

## 2. Multi-frame machinery

| Feature | What it does | Use as a base |
|---|---|---|
| **Multiple Exposure** (sid 267 frames, 268 Auto Gain, 269 Overlay) | Bayer combine of N frames, gain 1/N with Auto Gain | **Best** |
| Image Overlay (playback, job 4101) | Same combiner, per-image gain table | Proves arbitrary gains |
| Live Composite / Live Bulb / Live Time | Composite is lighten (max), per VIDEO_HIDDEN, not re-checked | No |
| HDR1/HDR2, HDR BKT | Tone-mapped merge, not linear | No |
| Focus BKT / stacking | Bracketing plus a lens-gated stack | No |
| ISP combiners 11/12/136 (BLOOM_HALATION) | YCbCr two-input blends: 136 = A + B | Fallback only. They are on the developed-image path, not Bayer |

Multiple Exposure in detail:

- **[V] Settings.**
  - Menu `0x611bf200`: sid 267 "Number of Frames", list `0x611bad34` = {0 Off, 2 "2f"}.
  - Sid 268 "Auto Gain", sid 269 "Overlay". A second copy is at `0x611cc96c` (list `0x611c84a0`).
  - Validator record 438 `0x604cebc4` = sid 267, list `0x604cb73c`, 2 bytes, **{0, 2}**.
  - Labels "3f"/"4f"/"5f"… already exist (strings 1430, 1431, 1899…).
- **[V] Capture fields.** `0x602a8372`/`0x602a8385` copy keys 0x1851 (Auto Gain) and 0x1841 (frames) into capture
  +24141 and +24140. `0x602ebd93..ab` also copies them from the getter.
- **[V] Gain.** `0x603ee3d8`:
  - Job type 4101 (Image Overlay) takes the gain from table job+238.
  - Otherwise the gain is 256, or `256 / frames` when Auto Gain is 1, then `<< 3` (Q11, 2048 = 1.0).
  - So gain = 1/N per frame, an average for any N.
- **[V] Combine loop.** `0x603edcca`, reached from the job-type switch `0x603e5fce` (table `0x6053dac0`; types 4098
  and 4101 both go there).
  - It walks job+236 images from job+56.
  - Each pass sends a two-input Bayer request through `0x603523db` (callback `0x603e7b83`). The request carries a
    gain, WB and OB for each input: A gain at sp+310, B gain at sp+398.
  - The running result keeps gain 2048 (1.0) and each new frame gets 1/N, so acc = Σ frame/N.
  - **[I strong]** Type 4098 is the Multiple Exposure combine, since it is the only type that uses the Auto Gain path.
- **[V] The sequencer counts to N, not to 2.**
  - `0x60919ec4`: the counter `0x61faccb8` counts up to setting 267 (log "MULTI EXP:get take count over").
  - `0x6091a844`: when count == setting 267 it finishes.
  - `0x6091b064`: each frame handle goes into array `0x61faccac`.
- **[V] Hard limit: 5 frames.** The array is `malloc(20)` at `0x6091b038` (`mov 20,d0`), and the clear loop runs to 5
  at `0x6091b061`. More than 5 frames would overflow it unless both are patched.
- **[I] The other limit is memory.** Every frame is held until the end, at about 40 MB of Bayer each. HDR already holds
  4 full frames on this body, so 4 should fit. 5 is untested.

## 3. Routes

| Route | What | Code space | Feasibility | Brick risk | Garbled-frame / hang risk |
|---|---|---|---|---|---|
| **A. Frames 3f/4f/5f** | Validator list {0,2,3,4,5} plus 5-entry label lists (both menu copies) | ~6 B validator list + 2 × 60 B lists, 6 pointer/count edits. **Data only, no code** | **High** | Low: menu data, same kind as aspect v4, nothing on the boot path | Low–medium: memory at 4–5 frames, or another 2-only assumption in the rec job (untraced) |
| B. Auto-sequence | One press takes all N frames (drive or self-timer driving Multiple Exposure) | 0 B if stock allows it, else a sequencer hook (~50–100 B) | Unknown, so test stock first | Low | Medium |
| C. ND8–ND32 | Change the combine to accumulate as it goes (two buffers, N passes), raise the frame cap, and add N-frame burst sequencing | 1–2 KB new code, new buffer handling | Low | Low–medium | **High**: real-time capture loop, no stock template |
| D. Live-view ND preview | Average live-view frames like `ndlv_*` | Large | Very low | Medium | High |
| Video | Would need 4× sensor rate plus an accumulator in the real-time movie path. MSHDR 120p exists but is not an averager | — | Not feasible | — | — |

- **UI for A.** No new menu. Shooting Menu → Multiple Exposure → Number of Frames: Off / 2f / 3f / 4f (/ 5f), with
  Auto Gain On.
  - ND level = frame count: 2f is ND2 (1 stop), 4f is ND4 (2 stops).
  - The camera meters each frame normally, so the result keeps the brightness of one frame and the motion blur of all
    N frames, plus the gaps between them.
  - A later step could relabel the rows "ND2/ND3/ND4" through the existing strings or the film-menu label hooks.
- **Limit of A.** The gaps between frames show as steps in fast motion. The effect is smooth on water, clouds and
  long-ish exposures, and choppy on short ones. Route B is what closes the gaps.

## 4. Recommendation

Do A, after Probe 0 on stock firmware. It is the stock combiner run at its existing N, on settings data alone. Hold
back on C: OM's 9-bit-headroom accumulate, dark frames and live-view simulation are a different module, and nothing
in the E-P7 runs it.

## 5. First probes

**Probe 0: stock, no build.** It shows that the two-frame average already works.

1. Use a tripod and moving water or clouds. Set Multiple Exposure to 2f, Auto Gain On, Overlay Off. Take two 1 s
   frames.
2. Take a single 2 s frame at one stop less (f-stop +1) for comparison.
3. Expect the same brightness, smoother motion, and no ghost edges on static detail.
4. Also check, for Route B:
   - Does Sequential L, or a custom self-timer set to 2 frames, capture both frames with one press?
   - Is a RAW of the combined result saved?

**Probe 1: one small data patch.** Allow 3f and 4f only. Leave 5f out until 4f has been seen to work.

- Validator record 438 `0x604cebc4`: +4 points to the new list `00 02 03 04`, and +12 changes from 2 to 4. Claim the
  bytes in CODE_SPACE_MAP first.
- Both label lists move to 4-entry copies {0 Off/1454, 2/42, 3/1430, 4/1431}, kind 4, ptr as stock (`0x611b6f68`
  and `0x611c465c`). Then repoint the parent list pointers at `0x611bf20c` and `0x611cc978`, and set the counts at `0x611bf210` and
  `0x611cc97c` from 2 to 4.
- Emulator check, as in ASPECT §1c V1–V6: sid 267 lists 0,2,3,4, and stepping wraps.
- **Camera test** at 4f, Auto Gain On:
  - Four frames are taken and a single file is saved.
  - Brightness equals one frame.
  - Noise is about half of a single frame's in flat areas, since averaging 4 frames gives √4 = 2× lower noise. This is
    the proof that it averages.
  - Watch for "memory full", a hang, or a dark result. A dark result would mean the gain was applied twice.
  - A hang is recoverable by pulling the battery. Never touch the SD card for this.

Not traced yet: whether the rec job builder for type 4098 sizes buffers or the job+56 array for exactly 2. Probe 1
answers this directly.
