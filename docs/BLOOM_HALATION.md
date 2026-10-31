# Bloom and halation on COLOR (Color Profile) stills: E-P7 1.1

Offline research only. Nothing here has run on a camera, and no SD-update-named file was made.
Decoded main image `5dd9af16…6190`, CPU base 0x60020020. Every address was read with `tools/dis.sh` /
`tools/ep7_xref.py`. fishcu's PEN-F CREATIVE_PROCESSING_JOBS.md was used only as a map.

Labels: **[V]** = verified from bytes and/or in the emulator. **[I]** = inference.

## 1. Identifiers [V]

| Thing | Value | Evidence |
|---|---|---|
| Art filter keys (job+11308) | `0x0101_00yy` (Type I), `0x0102_00yy` (II), `0x0103…` (III) | name table `0x604ded4c` (ptr, id): 00_MONO=12, 00_COLOR2=11, 01_POPART=0x64, **02_FANTASIC_FOCUS=0x65**, 03_DAYDREAM=0x66, 04_LIGHT_TONE=0x67, 05_ROUGH_MONOCHROME=0x68, 06_TOY_PHOTO=0x69, 07_DIORAMA=0x6a, 08_CROSS_PROCESS=0x6b, 09_GENTLE_SEPIA=0x6c, 10_DRAMATIC_TONE=0x6d, 11_LIGNE_CLAIR=0x77, 12_WATER_COLOR=0x78, 13_VINTAGE=0x79, 14_PARTCOLOR=0x7a, 15_BLEACH_BYPASS=0x7b, 16_PLACAME=0x7c |
| Soft Focus filter key | **0x01010065** | as above |
| Art Effect ids (capture+24785) | 0 OFF, **1 SOFT_FOCUS**, 2 PIN_HOLE, 3 FRAME, 4 WHITE_EDGE, **5 STAR_LIGHT**, 6/7 DIORAMA_V/H, 8/9 SHADE_V/H | table `0x604dee6c` |

## 2. How effects become passes: job flags [V]

Effects are **not** per-key work lists. They are bits in the job flag word (job+16 = params+12), which the
work-list builder `0x60357415` tests after the per-key handler, for every key (`0x603578bd…`).

| Source | Code | Result |
|---|---|---|
| Art Effect → flag | `0x603eab39` (called from both still converters, `0x603e615c` and `0x603e8abd`), jump table `0x6053dd00` | 1 Soft Focus → **0x80**; 2 Pin Hole → 0x400; 3 Frame → 0x8000; 4 White Edge → 0x2000; **5 Star Light → 0x40**; 6/7 Diorama → 0x100/0x200; 8/9 Shade → 0x800/0x1000 |
| Filter key → flag | constructor hash `0x60521a54` (at `0x603539d7`) | 0x01010065 Soft Focus → **0x80** (also 0x01010071, a hidden id); Pin Hole I/II/III → 0x200000/0x400000/0x600000; Diorama I/II → 0x100/0x200; Vintage I/II → 0x20000/0x40000; Rough Mono I/II and Dramatic Tone II → 0x800000; key 0x01010073 → 0x40 |
| Type strip | `0x60353b15` | if job type `&0xf0 == 0x40` or `&0xf00 == 0x100`, clears 0x40/0x80/0x300/0x4000/0x40000/0x100000 (stock exclusion of effects for some job types; meaning of the types not traced) |
| COLOR shading | `0x60353bcf` | keys 9 and 11 always get 0x80000 (creative shading modifier `0x6035b03a`, effect 0x0c00 → combiner 33) |

So the Soft Focus filter and the Soft Focus Art Effect use **the same bit and the same passes**.

## 3. Soft Focus pipeline (flag 0x80) [V unless marked]

Work list `0x6035797b`:
- **Job class** (job+11341, from `0x603b551d`) 4–8: one entry `0x6035cc1b`/cb `0x6035cd94`, kind-3 effect 0x0403 → **combiner 12**.
- **Classes 0–3:** pass `0x6035c9c1` (pushed with `0x60357363`) + entry `0x6035ca31`/cb `0x6035cbaa` (`0x6035739e`, attach flag 0).

| Step | Setup | Request | Source → destination |
|---|---|---|---|
| Reduce | `0x6035cee6` | kind 3, stage 0xf005, effect 0x0400 | developed image buffer 0x1000 → **0x1060**, format 0x0305, 4 B/px, size from `0x60348ce2`: **160×120** (classes 0–3 default), 144×108 (4/8/9), 144×80 (5/6/7); table `0x604eb450` |
| Upscale | `0x6035cfe9` | kind 3, stage 0xf005, effect 0x0401 | 0x1060 → **0x1061**, full size of 0x1000, format 0x0302 (2 B/px) |
| Blend | `0x6035ca31` | kind 3, stage 0xf005, effect **0x0402** | inputs 0x1000 (request+20) and 0x1061 (request+84) → new 0x1000; then releases 0x1060, 0x1061 and the old 0x1000 |

- **Blur:** there is no convolution kernel. The blur is a downscale to about 160×120 followed by an upscale, which for a 5184×3888 frame is a very wide, smooth glow (roughly 1/32 of the frame width) [V sizes, I visual]. The only size knob is table `0x604eb450`. It is global, so changing it would also change stock Soft Focus.
- **Selector** `0x603b5200`: kind-3 effect 0x0402 → 11 and 0x0403 → 12 on the default effect path (`0x603b539f`, hash `0x60532e98`). This applies to any key without its own rule, **including key 11**.
- **Combiner 11** `0x603a049e` and **12** `0x603a04f3`:
  - Bank (base+7364): mode word +4 = 0x00200001, +8 = 3822, signed-chroma defaults from `0x6039fdf0`.
  - Combiner 11 weights: **+92 = w|w<<16, +96 = w** and **+136 = (1024−w)|…, +140 = 1024−w**. Combiner 12 swaps them. This is a **linear mix (lerp)**.
- **Weight** `0x6039fee8`:
  - key == 0x01010065: level = request+1832 (kind 0) or +708 (kind 3), +5, clamped to 0..10, → table **`0x604ec02e` = 600,653,707,760,680,600,520,440,360,280,200**.
  - Any other key (the Art Effect on another filter): **w = 600**.

[I] **Input order is unproven.** The first group (+88..+96) is assumed to weight request+20 (the sharp image). If that is right, the blur share is 1−w/1024: 41 % at w = 600, and 80 % at stock level +5.

## 4. Star Light (flag 0x40) [V passes, I detection]

- Passes: `0x6035d0f4` (kind 3, effect 0x0100) → `0x6035d253` (kind 3 effect 0x0101; its kind-0 request also gets 0x0101, which the tone selector `0x603b039b` special-cases) → `0x6035d4ae`.
- Entry: `0x6035d6ef` (kind 3, effect **0x0106 → combiner 136**). It combines 0x1000 with a star layer 0x1083.
- Combiner 136 `0x603a0404`: same mode word 0x00200001, but **A gain 1.0 and B gain 1.0** (+92 = 0x04000400, +96 = 1024; +136 = 0x04000400, +140 = 1024). This is a stock **additive** blend [V bytes; I semantics].
- Combiner 135 (kind-3 effect 0x0104, `0x603a03a6`) loads **three per-channel B gains from request+672/674/676** into +136/+140 [V].
- Where the highlights are found is not resolved. It is presumably in or after `0x6035d4ae`, and possibly done by the CPU [I].

## 5. Bloom on COLOR: same mechanism as grain? Slot conflict? Cost?

- **Mechanism [V].** Bloom does not need a modifier. Setting job flag 0x80 on a key-11 job makes the stock work-list code push the Soft Focus pass and entry, and the stock selector maps them to combiner 11/12. Grain had to add a stage, a modifier and a selector rule; bloom needs none of those.
- **No modifier-slot conflict with grain [V emulator T2].**
  - The Soft Focus entries are pushed with `0x60357363`/`0x6035739e`, not attached.
  - With grain merged, the development entry keeps `grain_mod` and the entry sequence is identical to stock.
  - COLOR shading (flag 0x80000) cannot attach to the kind-3 blend entry, so it goes to its own fallback entry `0x6035b517`. This adds one more kind-3 pass after the blend. Grain alone already does this.
- **Order [V]:** development (+grain combiner 32) → reduce → upscale → blend → shading.
  - [I] Grain is therefore mixed: the sharp share keeps w/1024 of the grain amplitude, and the blurred share smooths it.
- **Cost [I]:**
  - 3 extra kind-3 passes over the full image: reduce, a full-resolution upscale and a full-resolution blend.
  - Two more full-size 2 B/px buffers, about 40.3 MB each at 5184×3888.
  - This is the same as stock Soft Focus in ART mode.

## 6. Bloom patch (built: `patches/bloom/`)

| Edit | Address | Stock | New |
|---|---|---|---|
| Flag hook | `0x603eabd7` (6 B), inside `0x603eab39` | `fa43f65d a000` (`movbu (24054,a3),d0; cmp 0,d0`) | `jmp bloom_flag; nop` |
| Weight hook | `0x6039fee8` (6 B) | `f82434 2c5802` (`mov (52,a0),a1; mov 600,d0`) | `jmp bloom_w; nop` |
| Code | `0x6055e7b0–0x6055e7e3` (51 B, claimed 0x6055e7b0–0x6055e7f0) | FF | stubs |

- `bloom_flag`:
  - If params key (params+8..11, written by `0x603eaa04` just before) == 11 (halfword +10 = 11, bytes +8/+9 = 0), it ORs **0x80** into the flags.
  - It then replays the two replaced instructions and jumps back to `0x603eabdd`.
- `bloom_w`: ctx key == 11 → `mov W,d0; retf [],0`. Otherwise it runs `mov 600,d0` and jumps to `0x6039feee`.
- **Strength → W** (`--strength`, the bundle `effect_strength`): blur share 8/14/20/27/35 % ⇒ **W = 942/881/819/748/666**. `--weight` overrides it.
- Every other bank byte is stock Soft Focus. Only the four weight words change.

### Verification (`tools/ep7_bloom_verify.py`; emulator, CPU-side only, no pixels)

| Test | Result (S2, W = 881) |
|---|---|
| T1 converter `0x603eab39` over 7 keys × 4 art effects × 2 | PASS: patched = stock \| 0x80 exactly for key 11; other params and capture bytes, stack and regs unchanged |
| T2 work list from `0x6035749f` with the T1 flags | PASS: key 11 class 0 → dev, `0x6035c9c1`, pending `0x6035ca31`/`0x6035cbaa`; class 5 → pending `0x6035cc1b`; shading → fallback `0x6035b517`. Stock image and patched image are identical (merged: plus `grain_mod` on the dev entry) |
| T3 selector, kind-3 0x0400–0x0403 × keys 11/12/0x01010065/0x01010078 | PASS: patched = stock; key 11 → 0/0/11/12 |
| T4 combiner config `0x603a013b` | PASS: key 11 → handler 11/12 with (881, 143) / (143, 881). The rest of the bank is byte-identical to stock key 11 **and** to the stock Soft Focus filter at level 0. Soft Focus levels 0/±5, key 0x01010078, key 12 and key 11 0x0c00/0x0400 are byte-identical to stock |
| T5 | PASS: 61 B in 3 spans |
| Merged (v0.1 + grain L2 + rec_limit + bloom S2) | `generated/bloom-S2-merged/`: 10 edits, 304 B, all in spans. `ep7_verify_package.py` H/L PASS 4/4; `ep7_grain_verify.py` all PASS; `ep7_bloom_verify.py` all PASS |

Not verified: that the stock ISP runs the Soft Focus passes for a key-11 job, the buffers are available, and the pixel result.

Bundles (later):
- `bloom_flag` runs with `a3` = capture, and capture+24083 is the active profile byte (docs/PROFILE_INDEX_WB.md), so it could read `effect_id` directly.
- The strength needs to be transported to the combiner, which sees only ctx and request. One route is to have the flag stub write params+5560 (art-filter level, packed to request+1832) and have `bloom_w` read it as stock does for 0x01010065. This needs a trace of how kind-3 request+708 is filled [I].

## 7. Halation: designed, not built

What the primitives give [V bytes, I semantics]:
- **Additive with independent gains**: combiner 136 (A = B = 1.0) proves the weights need not sum to 1024.
- **Per-channel gains**: combiner 135 takes three halfwords from the request.
- **Per-input affine and clamp**: combiner 5 (Water Color I, `0x6039fe58`) loads table `0x605244f4` = (−10, 1066, −10, 245, 10) into +80 (input offset), +92 (gain), +104/+108 (clamps) and +164 (output offset). Water Color II is the identity (0, 1024, 0, 255, 0). Defaults: `0x6039fdf0` (signed chroma: offsets −128, clamps [0,255]/[−128,127], output +128) and `0x6039fdb5` (unsigned).

Design (combiner 11 for key 11 only; hook the handler tail `0x603a04e8–0x603a04f2`, stock `fa178800 fa1f8c00 dff014`):
- A (sharp): gains 1024 (unity).
- B (blurred): Y input offset (low half of +124) = −T, Y lower clamp 0, Y gain = g. This gives B′ = max(0, B_Y − T)·g, a **threshold applied after the blur**. Chroma gains on B are 0..1.5.
- Mode: additive (as combiner 136).
- Strength → g, e.g. 1..5 → 0.10..0.40 × 1024, with T ≈ 200/255.

Limits:
- **No true red halation [I].** Every unit seen is per channel, with no cross-channel term. A red tint *proportional to the highlight key* cannot be made. A constant chroma offset on B tints the whole frame. The best available result is a **thresholded highlight glow** in its native colour, with B chroma gain > 1 to warm already-warm lights.
- The threshold acts on the 160×120 blurred copy, not on the sharp highlights. This matches the physics poorly, but the look is similar.
- The kind-3 route has no tone LUT (PEN-F: neutral tone and tint on the image route). The threshold therefore has to come from the combiner offset/clamp fields, whose layout is inferred from the three handlers above.

## 8. Risks (highest first)

1. **[I] Input order of combiner 11.** If +88 weights the blurred image, W = 881 gives 86 % blur. On a first camera test use `--strength 1`. If the result is mush, rebuild with `--weight 1024−W`.
2. **[I] Memory and time.** The patch adds two full-size buffers (about 80 MB) and three full-resolution passes to every COLOR still, the same as stock Soft Focus in ART mode. Risks are buffer-pool failures (`0x60350560` returning ≥48 → error 0x9ec3/0x9ece) in bursts, buffer depth and shot-to-shot time. Sequential/burst modes with COLOR are untested.
3. **[I] Coverage.**
   - Movie: not touched. Movie Art filters are excluded from 4K/High-Speed in stock, and movie frames do not use these converters.
   - Live view: the compact path has no capture params, so there is probably no preview.
   - Job classes 4–8 use combiner 12 with the same W.
   - In-camera RAW edit of a COLOR image shares key 11 and would get bloom if it goes through these converters.
   - Job types stripped at `0x60353b15` get no bloom (stock behaviour).
4. **[I] Look.**
   - Lerp is the Pro-Mist energy model: it lowers highlights and lifts shadows.
   - The glow radius is fixed by 160×120.
   - Grain is softened by the blur share.
5. **[V] Fixed strength.** Strength is fixed at build time. There is no menu, and it applies to all COLOR profiles until the bundle transport exists.
6. Inherited from v0.1 and grain: the update/restore path is untested on a camera, and a valid container does not prove the package boots.

Files:
- `patches/bloom/build.py`, `patches/bloom/bloom.s.in`, `tools/ep7_bloom_verify.py`.
- `tools/merge_specs.py` now keeps the `bloom` metadata.
- `generated/bloom-S2{,-merged}/` (edits.json, verify JSON).
