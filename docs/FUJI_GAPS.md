# Fuji-style gaps, re-examined: E-P7 1.1 image-processor primitives

Offline static analysis only. No device was contacted, no SD-update-named file was created, nothing
was built or committed. Main image `5dd9af16…6190`, CPU base 0x60020020; addresses read with
`tools/dis.sh`, `tools/ep7_xref.py` and small read-only Python dumps of the decoded image.
fishcu's PEN-F docs were used as a map only.

Labels: **[V]** = read from bytes/disassembly in this pass (or in an earlier doc that says [V]).
**[I]** = inference (semantics, ISP behaviour, pixel effect). Nothing here is camera-verified.

## 0. Summary and ranking

| Rank | Gap | Verdict | Why (one line) | Effort | Risk |
|---|---|---|---|---|---|
| 1 | 3. Clarity | **partial → likely feasible** | Soft Focus passes + a combiner weight above 1024 (negative blur weight) is an unsharp mask; signed negative weights already exist in stock (combiner 6, Dramatic Tone) | Low (extends bloom v0.4) | Low–medium |
| 2 | 6. Luminance-dependent colour / split toning | **feasible (crossover/split tone)** | The RGB-gamma setter takes **three independent curve pointers** and stock code passes three different curves on one path | Medium | Low–medium |
| 3 | 5. Live-view preview | **partial** | The live-view/movie job path uses the same job constructor and maps an art-effect bitfield to the same job flags; only the per-profile transport is missing | Medium–high | Medium |
| 4 | 4. Red halation | **partial (new route)** | Stock has a "blend toward an arbitrary constant YCbCr colour through a mask" combiner (Vintage uses a non-neutral colour) plus a brightness-key mask pass; chaining them gives tinted highlight glow | High | Medium–high |
| 5 | 1. 3D LUT / hue×luma transform | **3D LUT infeasible; 2-D partial** | No 3D LUT engine anywhere; but the HSL unit carries 16-knot per-sector curves on a second axis (chroma or luminance, not yet pinned) | Medium (after one A/B test) | Medium |
| 6 | 2. Grain size | **infeasible as a control; crude partial** | Grain combiners have seed + gain only, no scale field, no noise texture; only a reduce→grain→upscale hack. By-product: **colour grain looks cheap** | High (size) / Low (colour) | High (size) |

Value-to-effort order: **Clarity > split tone > live preview > halation > HSL 2-D curves > grain size**.
Colour grain (a by-product of gap 2) would rank between 1 and 2 if counted separately.

---

## 1. Gap 1: true 3D LUT, or a hue-and-luminance-dependent transform

### Verified [V]
- **Every picture mode and art filter uses the same colour-table format.** Picture-mode/art key hash
  `0x60532510` (8-byte {key, handler}), handlers `0x603af8c9…0x603afb1b`, select descriptors
  (52 B: table pointer + 12 sub-pointers, e.g. `0x60530eb8`). All referenced tables are 3028 B in one
  contiguous run `0x605120ec…0x605230f8`, trailer = enable mask (COLOR `0x6051de2c` → 0xfff, Natural-family
  0x3cf, Pop Art 0xf3c, Partial Color / Bleach Bypass / Instant Film 0x41, Cross Process II 0x4, Dramatic
  Tone 0xb8f + 0x7). Map: Pop Art → `0x60515c10`; Cross Process → `0x605173b8`/`0x60518b60`; Dramatic Tone →
  `0x605120ec`+`0x60517f8c`; Water Color → `0x60519734`; Partial Color I/II/III → `0x6051a308`/`aedc`/`bab0`;
  Bleach Bypass → `0x6051c684`/`0x6051d258`; Instant Film → `0x6051d258`; Color Creator (id 10) and
  Vivid/Natural/Muted/Portrait → `0x60512cc0`/`0x60513894`/`0x60514468`/`0x6051503c`; ids 2000/2001 (Flat/Log)
  → `0x605120ec`/`0x60512cc0`.
- **The "4 u32 + 6 u16 LUTs" are really two groups of five 16-knot curve sets.** The COLOR builder
  `0x603b0068` loops group a0 = 0..1 × sector a1 = 0..5 (12 records, 24 B output stride) and then writes
  ten pointers: group 0 → table+336/+720/+1104/+1296/+1488 to output+3124/3132/3136/3148/3156; group 1 →
  table+1680/+2064/+2448/+2640/+2832 to output+3128/3140/3144/3152/3160 (`0x603b01dc–0x603b0240`).
  Each group = 2 × 384 B + 3 × 192 B. The 384 B slots hold every halfword twice (two identical channels).
- **Entry format:** u16 = `(base << 8) | int8 slope`, base 0..63, slope = delta to the next knot. Each
  96-entry set is **6 sectors × 16 knots**: one piecewise-linear 16-knot curve per sector per slot.
  COLOR examples: slot 0 and slot 4 differ per sector (peaks at knot 11, 5, 11, 4, 11, 9 for records
  0–5); slots 1/2 are one shared curve (0→60 at knot 9, falling to 10); slot 3 is flat 63. Other modes
  use curves that fall to 0 at the top (`63…63,56,48,38,26,15,7,0,0`) or are active only in a band
  (`0,…,0,11,22,33,26,18,10,4,0`).
- The ISP upload (fishcu, PEN-F) copies 128 entries per pointer into a LUT bank; the source has 96.
- **No 3D-LUT evidence:** no strings (3DLUT/CLUT/lattice/tetra/ICC; "cube" hits are the OI.Share
  "cube" feature), and every mode's colour path is matrix + 6-axis + 12-sector unit + RGB gamma +
  luminance LUT + chroma stage. Color Creator is an ordinary table + coefficients, not a LUT.

### Inference [I]
- The 16-knot axis is a **second variable inside each hue sector**, most likely chroma or luminance.
  Knot 0 is 0 in almost every "active" curve (neutral protection fits chroma); per-sector peaks
  (yellow/cyan high, blue/red low) partly fit luminance; neither fits all sectors. fishcu's own label:
  "LUT field semantics … remain unidentified". Five slots per sector suggest {H, S, L} × {chroma, luma}
  weightings, but the slot-to-parameter mapping is not proven.
- If the axis is luminance, a per-sector, per-tone transform (e.g. "darken saturated reds only in
  highlights", REALA-style muting) is possible by editing these curves. If it is chroma, we get
  CCE-like saturation-keyed behaviour per hue. Either is a real 2-D (hue × one variable) transform; a
  full 3D LUT stays impossible.

### Plan / effort / risk
- **Pin the axis first (cheap, decisive):** one camera A/B with a single slot's curves replaced by a
  ramp, shooting a grey-scale + saturation chart. Until then, do not build an editor.
- **Mechanism:** the builder already writes the ten pointers; a 5–10 B hook after `0x603b0240`
  (inside the existing v0.2 H/L routine at `0x603b02d9`) can redirect selected pointers to custom
  curve sets. A full group is 1344 B; code space is nearly exhausted (CODE_SPACE_MAP), so only the
  modified slots/sectors should be stored, or the set must come from the SD bundle loader into RAM
  (no RAM buffer identified yet).
- **Hardware over-read:** the upload reads 128 entries; custom data needs 32 trailing guard entries.
- **Bundle:** new fields at slot +45.. (free 45–63): `curve_set_id` u8 selecting one of a few stored
  curve variants per slot.

## 2. Gap 2: grain size / roughness

### Verified [V]
- Grain combiners 31 `0x603a05b3` and 32 `0x603a065b`: mode words 0x00100002 / 0x00200000, bank+8 = 546,
  seed at bank+172 (31: mask-descriptor halfword; 32: counter `0xa27393f8`), gain from tables
  `0x604ec0ce` (110/300/600) / `0x604ec0d4` (50/75/100) into **bank+136 low half only; bank+136 high half
  and bank+140 = 0**. No other noise parameters are written; no noise-texture table is referenced.
- Combiner 11 (Soft Focus) writes the same layout as three channels: +136 = (1024−w)|(1024−w)<<16,
  +140 = 1024−w.
- Reduce sizes available in stock: Soft Focus `0x604eb450` (160×120, 144×108, 144×80) and Star Light
  helper `0x60348c60` (640×480).

### Inference [I]
- There is **no size/roughness field**: the generator is per-pixel xorshift white noise.
- **Colour grain is a register-level change:** by analogy with combiner 11, +136 high half and +140 are
  the two chroma channels' B gains. Setting them non-zero in the grain_mod/handler path should add
  chroma noise. This is the planned FEATURE_GAPS #3 and looks like ~20 B on top of grain v0.4.
- **Pseudo-size:** select combiner 32 for the kind-3 reduce pass (effect 0x0400) with a large reduce
  size (e.g. 2592×1944), then upscale and lerp. Problems: kind-3 requests are short (624 B on PEN-F), so
  the level byte at +1828 is out of range for kind 3; the reduce table is global; the lerp also softens
  the image. Fidelity low.

### Effort / risk / bundle
- Size: high effort, high risk (new selector rule on kind 3, memory, softening). Not recommended.
- Colour grain: low effort, low–medium risk (ISP chroma behaviour unproven). Bundle: `grain_colour`
  u8 0..3 at a free slot byte.

## 3. Gap 3: Clarity / local contrast at a chosen radius

### Verified [V]
- **Dramatic Tone is not a radius-controlled engine.** Work-list hash `0x6052200c` (key−11)&31: key
  0x0101006d/0x0102006d → handler `0x60357748` (skipped for job types `&0xf00==0x100` or `&0xf0==0x40`).
  Passes: `0x60359e6f` (stage 0x0600 → buffer 0x1040, format 0x0304, 4 B/px, job output size from
  `0x6035636c`) → `0x60359f7f` (0x0601 → 0x1041, 0x0302) → entry `0x6035a086` (0x0602; setup `0x6035a26c`
  copies the 0x1040 descriptor into request+148). Selector hash `0x60532f98`: DT stage 0x0600 → **combiner 5**
  (affine table `0x605244f4` = −10, 1066, −10, 245, 10), 0x0602 → **combiner 6** `0x603a0225`.
- **Combiner 6 subtracts:** mode 0x00100002, A gains +92 = 0x04000400, **B gains +136 = 0xFC00FC00,
  +140 = −1024**. Signed negative B weights are therefore accepted by the bank (at least in mode 0x00100002).
- Combiner 5 writes gain **1066 > 1024** at +92. Combiner 136 has A = B = 1024. So weights are neither
  required to sum to 1024 nor capped at 1024.
- The `dt_param.fC3/fC5/fC7/fD3/fD5/fD7/fM` strings (`0x601a1946…`) printed beside `ca_param` and lens
  focal length are **lens distortion**, not Dramatic Tone ("imgpro_yc_dt" in the swing-panorama module).
- Soft Focus (bloom) path [V, BLOOM_HALATION.md]: reduce to 160×120 → upscale → combiner 11 lerp,
  weight getter `0x6039fee8` already hooked by bloom v0.4.
- Correction to BLOOM_HALATION.md §3: 5184/160 = 32.4, so one reduced pixel spans **1/160 of the width
  (≈32 px)**, not 1/32.

### Inference [I]
- **+Clarity = extrapolated lerp:** out = w·A + (1024−w)·blur(A) with w > 1024, i.e. A + k·(A − blur).
  With w = 1100…1400 that is an unsharp mask with k ≈ 0.07…0.37. The radius from a 160×120 reduce is
  ~32 px (≈0.6 % of width, σ of order 15–25 px if the reduce averages), squarely in Fuji Clarity's range
  (0.5–1 % of width). **−Clarity is the existing bloom.** If the reduce point-samples instead of
  averaging, the result aliases; that is the main pixel risk.
- Combiner 11 runs in mode 0x00200001, not 0x00100002; negative weights are only proven in the latter.
  Safer variant: in a handler-tail hook (`0x603a04e8`, as designed for halation) write combiner-6's mode
  word and set chroma halves to (1024, 0) so only Y gets local contrast.
- Radius choice: per-job size override at the reduce-size getter `0x60348ce2` for key 11 (e.g. 320×240 →
  ~16 px, 640×480 → ~8 px). The table itself is global (stock Soft Focus would change).

### Effort / risk / bundle
- Effort: low. bloom v0.4 already sets job flag 0x80 per profile and returns a per-profile weight; add
  table entries >1024 (≈10–30 B) and optionally the handler-tail mode/chroma write (~40 B).
- Risk: low–medium (weight saturation or wrap in mode 0x00200001; halos are inherent to USM; same
  memory/time cost as bloom: two 40 MB buffers, three full-res passes).
- Bundle: `effect_id` 3 = clarity, `effect_strength` 1..5 → W 1100/1180/1260/1340/1420; optional
  `clarity_radius` u8 at a free byte if the size override is added. Clarity and bloom are mutually
  exclusive (same passes).

## 4. Gap 4: true red halation

### Verified [V]
- **Combiner 33** (`0x603a06f8`, shading): mode 0x1002, bank+120 = constant colour word, **0x008080FF
  (Y 255, Cb/Cr 128 = white) for positive and 0x00808000 (black) for negative**, level from request+1829
  (kind 0) or +661 (kind 3).
- **Combiner 156** (`0x603a0283`, Vintage modifier, stage 0x0900): the same mode 0x1002, but **bank+120 =
  0x001900E1, a non-neutral colour (Y 225, Cb 0x00, Cr 0x19)**, weights +136 = 0x00730073, +140 = 115.
  So the "blend toward a constant colour" unit accepts arbitrary chroma.
- MONO already builds a **brightness-key mask** (stage 0x0900, tone LUT `0x605003aa`: 0 to index 36, 1023
  from 120, chosen by tone selector `0x603b04fa`) and consumes it in a later pass (combiner 31, mask
  descriptor at request+532).
- Star Light: pass `0x6035d0f4` (kind 3, effect 0x0100) reduces to 640×480 (`0x60348c60`); pass
  `0x6035d253` (effect 0x0101) is developed with **no luminance tone LUT** (tone selector `0x603b03b9`
  returns NULL for effect 0x0101); `0x6035d4ae` then allocates buffers 0x1083/0x1084 and calls
  `0x60351786`/`0x603504a0`; entry `0x6035d6ef` adds the star layer with combiner 136 (additive).

### Inference [I]
- Star Light's highlight detection and star drawing are most likely CPU-side, on the small linear
  image. It is not a reusable per-pixel highlight key.
- **New halation route:** (1) a mask pass like MONO's 0x0900 with a highlight-key LUT (0 below ~200/255,
  ramp to ~300/1023), output at reduced size so that resampling on use provides the blur; (2) a late
  kind-3 pass with a combiner-33/156-style config: mode 0x1002, **colour word = orange-red (e.g. Y≈0xD0,
  Cb≈0x60, Cr≈0xC0)**, mask = the key. Result: lerp(image, red-orange, key·s), a highlight-proportional
  red glow. It is a screen-like lerp rather than an additive one, but visually close to halation.
- Unknowns: whether the mask port takes a reduced mask (the shading mask is 128×128 and resampled, which
  suggests yes); whether a key-11 job can carry the extra mask pass (MONO's needs ~20 MB for a full-size
  mask); and which combiner ID to use for the late pass (33 is taken by COLOR shading).

### Effort / risk / bundle
- Effort: high (new work-list wiring like MONO's mask → … → late pass, a tone-selector rule, a combiner
  config, buffers). Risk: medium–high (buffer pool, format traps: PEN-F's mask wrapper forces a mono
  word).
- Bundle: `effect_id` 2 (already reserved), `effect_strength` → key amplitude; optional `halation_hue`
  u8 at a free byte → colour word.

## 5. Gap 5: live-view preview of the effects

### Verified [V]
- The job constructor `0x603537eb` has eight callers, among them **`0x60321ea8`** inside the IPCR
  development-request handler `0x60321d36` (the live-view/movie path, VIDEO_LOG X2).
- That handler builds the job flag word itself from a bitfield at request+20: bit 0 → 0x40 (Star Light),
  **bit 1 → 0x80 (Soft Focus)**, bits 2–3 → 0x300 (Diorama), bit 4 → 0x400, bits 5–6 → 0x1800, bit 7 →
  0x2000, bit 8 → 0x4000, bit 9 → 0x8000, bit 10 → 0x10000, bit 11 → 0x800000 (`0x60321d97–0x60321e50`).
  These are the same flags the still converters produce.
- Soft Focus for job classes 4–8 is a single entry `0x6035cc1b`, effect 0x0403 → combiner 12; MONO grain
  for classes 4–9 is the single-pass 0x0902 (combiner 32).

### Inference [I]
- Live-view jobs are small-output classes. Bloom/Clarity (combiner 12, single pass) and grain (0x0902)
  are therefore the cheap variants and should run at preview rate, as stock Soft Focus does.
- Missing piece: per-profile data. Live-view jobs never pass through conv1/conv2, so the job extension
  (+15488..15490) is zero, and bloom_w / grain / H/L guards fall back to stock. A hook in `0x60321d36`
  (before `0x60321ea8`) would need to set flag 0x80 and write the transport for key 11. The profile
  byte is not proven to be present in the 980-byte compact record (HSL_PORT: compact hooks "low").
- WB shift already reaches the compact-slot reader (WB_PATCH sites `0x6030bb5b/6e`).

### Effort / risk / bundle
- Effort: medium–high (trace the compact record for profile/picture mode, one hook, reuse the existing
  stubs). Risk: medium (preview-rate and buffer limits; it touches every live frame). No new bundle
  fields; a global `preview_effects` flag is optional.

## 6. Gap 6: luminance-dependent colour (split toning, crossover)

### Verified [V]
- **RGB gamma setter `0x603ae7d3` takes three pointers** (a1 → colour-output +2596, d0 → +2600,
  d1 → +2604). It has two callers: the main development path `0x603ae995` (pointers from the stack
  locals, after `0x603ae354`/`0x603b5e8c`) and `0x603af2db`, which for Ligne Clair kind-3 effects
  0x0b00–0x0b05 passes **three different tables** (`0x604f9878`, `0x604f9a78`, `0x604f9c78`, and others
  in that branch).
- The curves are bank A (`0x604edc78…`, 256 × u16, 12-bit in/out); row 0 `0x604ede78` is the E-P7 base
  curve (VIDEO_LOG).
- The chroma/toning stage `0x603b132a` (hook site `0x603b134e`) writes a single constant {1, Cb, Cr}
  to output+76, so mono toning is global [V WB_AND_MONO]. No tone-range-dependent matrix was found:
  the matrix is one 3×3.

### Inference [I]
- Different R/G/B curves on white-balanced linear RGB are film per-layer curves: neutrals get
  different tints in shadows and highlights (Classic Neg's green-cyan shadows with warm highlights,
  Nostalgic Neg's amber highlights, cross-processing), with the shoulder compressing per channel.
  That is a true luminance-dependent colour shift, including on greys. Whether the matrix runs before
  or after gamma changes the exact tint but not the feasibility.
- The 16-knot per-sector curves (gap 1), if luminance-indexed, add hue-selective tone dependence.

### Effort / risk / bundle
- Mechanism: hook the `0x603ae995` call (5 B): for key 11 + valid transport + slot `rgb_curve_id ≠ 0`,
  load three pointers from a per-look table; else stock. ~40–60 B code.
- Data: 3 × 512 B per look. Options: (a) zero-cost reuse of existing bank-A curves (~97 slots; limited
  palette); (b) one or two custom looks in the free sec-3 tail `0x605b7180–0x605b7800` (1664 B; needs a
  CODE_SPACE_MAP claim, and the hook must not run before section 3 loads); (c) compact parametric
  deltas, which still need a RAM destination (none identified).
- Risk: low–medium. Pointer-only change, stock hardware path, but the slots' R/G/B identity and the
  12-bit range must be confirmed on camera.
- Bundle: `rgb_curve_id` u8 (0 = stock) at a free byte; the desktop sim's `film_curve()` per-channel
  `black/white/slope` generate the tables.

## 7. Side findings
- **Lens distortion and lateral-CA correction** coefficients exist (`dt_param fC3/fC5/fC7`, `ca_param
  fC1r/fC3r/fC5r/fC1b…`, imgpro "yc_dt" in the panorama module). FILM_LOOK's "no per-channel warp" may
  be wrong; vintage-lens CA might be emulated. Not investigated.
- Art-filter colour tables share the HSL format, so Partial Color, Bleach Bypass and Instant Film
  colour behaviour is just a different table + enable mask (useful as donor curves).

## 8. What would change these verdicts
1. A/B test of one HSL curve slot → fixes gap 1's axis (chroma vs luminance).
2. Camera test of the bloom path with W > 1024 → confirms Clarity (and the reduce's averaging).
3. Camera test of three distinct bank-A pointers on a grey ramp → confirms split toning.
4. A trace of the compact record (profile byte) → decides live preview effort.
