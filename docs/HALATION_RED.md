# Red halation per slot ("red bloom", effect_id 2)

Status: **built into test13 (§6); camera test 13b: no red glow (§8); replaced in place by bloom colour (§8).** This design extends the bloom +
clarity routine (docs/BLOOM_HALATION.md, docs/CLARITY.md). Labels: **[V]** read from the decoded main.
**[I]** inference.

## 1. Verdict

- **True red halation is not small.** A red glow around *white* lights needs a chroma term that follows the
  highlight luma. That needs the combiner-156 colour word plus a brightness-key mask pass (FUJI_GAPS §4). It
  is high effort and high risk, and it is not proposed here.
- **A small change can make the existing bloom halo redder than its source.** Spread the blurred image's
  chroma more than its luma, and spread Cr more than Cb. Warm practicals (tungsten, sodium, neon, tail
  lights) then get a red-orange fringe that reaches past the luma glow. White lights still get a neutral glow.
  This is the realistic per-slot "red bloom".

## 2. Facts it relies on [V]

- Combiner 11 handler `0x603a049e`:
  - w comes from getter `0x6039fee8`, which the bloom hook already controls.
  - Per input it writes a config word: A at +88, B at +132, both 0x002A0000.
  - It then writes three gains per input:
    - A: +92 = w | w<<16, and +96 = w.
    - B: +136 = (1024−w) | (1024−w)<<16, and +140 = 1024−w.
  - The tail is `0x603a04e8 mov d1,(136,a3)` / `0x603a04ec mov d3,(140,a3)` / `0x603a04f0 ret [d2,d3,a2,a3],20`.
    At the tail, d2 = w, d3 = 1024−w and a3 = bank.
- Combiner 135 loads **three separate B gains** from request+672/674/676 into the same +136 lo/hi and +140
  fields. So the three gain fields are per channel.
- Defaults `0x6039fdf0` set up signed chroma (offset −128). A gain on a chroma channel therefore scales
  around neutral.
- `effect_id` 2 (halation) already passes the SD loader v3 range (0..3), the LOOKS.BIN check and
  `patches/bundles` (`"type": "halation"`). Today it is stored but not consumed.

## 3. Design

Each chroma channel c gets k_c times the blur share. The weights still sum to 1024 per channel. This is
the same lerp mode that bloom uses on camera, and there are no negative gains:

    B_c = (1024 − w) · k_c        A_c = 1024 − B_c         (luma channel unchanged: A = w, B = 1024 − w)

In flat areas the output equals the input, so there is no global tint or saturation change. Near a light,
chroma bleeds k_c times further than luma. With k_Cr ≈ 2.5 and k_Cb ≈ 0.6, the fringe leans red.

| Piece | Change | Size |
|---|---|---|
| bloom_flag | accept effect_id 2 as well as 1 and 3 (one extra compare) | +4 B |
| bloom_w | effect 2 → halation LUT, 5 weights that no stock or bloom path produces (e.g. 943/883/821/749/667) | +8 B code, 10 B LUT |
| new hook 0x603a04e8 (6 B: `mov d1,(136,a3)` + 2 B → `jmp halo; nop`) | `halo` replays both stores. If d2 is in the halation LUT (5 compares), it computes B_Cr, B_Cb and A_Cr, A_Cb with `mul` + `asr 8` (k in 1/256 units; MDR is not needed because exit is via `ret`, not `retf`). It rewrites the matching halves of +92/+96/+136/+140, then `ret [d2,d3,a2,a3],20` | ~80 B |
| k table | k_Cb, k_Cr per strength 1..5 | 10 B |

- **Total:** about 110 B of new code and data, plus one new 6-B hook. The two existing bloom hooks are unchanged;
  only the routine behind them grows.
- **Space:** it does not fit in the 34 B left in the sec-2 bloom claim (0x6055e6ce–0x6055e6f0). Candidates:
  - the dead EVF step-13 G table after lv_art (0x601e123c…), using the same dead-EVF argument and build check
    as lv_art;
  - the retired sec-1 bloom block 0x60210e10–0x60210e80. The aspect stub starts at 0x60210e90.
- **No loader, ABI, LOOKS.BIN or BUNDLES.BIN format change.** CineStill800 would use
  `"effect": {"type": "halation", "strength": 4}`.
- **Gating:** the halo stub acts only on its own LUT weights. Combiner 11 under the stock Soft Focus filter
  (600..200), bloom (942..666) and clarity (≥1100) is never touched.

## 4. Unknowns and confidence

- **Channel order of the three gains [I].** It is not known which of +92/+136 lo/hi and +96/+140 hold Y, Cb
  and Cr.
  - Plan for the first camera A/B: three build variants that each boost one field. One field's variant
    blurs the luma (that field is Y), one tints the fringe red (Cr), and one tints it blue (Cb).
  - A wrong guess is harmless: the image is softer or tinted, and it does not crash.
- **Look [I].** The fringe colour follows the light's own chroma, so white LEDs stay white. The halo radius
  is fixed by the 160×120 reduce, as for bloom.
- **Side effects:**
  - Extras sector 2 shows effect 2 as neither Glow nor Clarity, and editing it there rewrites it to 1 or 3.
    A label tweak in look_extras would be about 20 B.
  - lv_art previews only effect 1, so a halation slot would have no LV glow.
- **Confidence:**
  - CPU side: **high**. It is the same pattern as clarity: weights in the proven combiner, positive gains
    that sum to 1024, and a store set limited to the bank.
  - Pixel result: **medium–low** until the channel-order A/B test is done.

## 5. Library v2

CineStill800 now uses `"effect": {"type": "halation", "strength": 4}` (bundles/library_v2.json), so a Film pick
of CineStill800 gets red bloom. Its light OR/R +2 and hue OR −1 stay. On firmware older than test13, effect 2 turns
the glow **off**: only use this LOOKS.BIN with test13 or later.

## 6. As built (test13)

- `patches/bloom/build.py --sd-v3 --clarity --halation`:
  - bloom_clarity.s.in (`.if HALO`): bloom_flag also accepts effect_id 2; bloom_w returns `h_lut` =
    943/883/821/749/667 for it (both combiners; no other path returns these). 298 B (was 270) in the same claim.
  - `halo.s.in` at 0x60210e10 (104 B): hook 0x603a04e8 (8 B) `jmp halo; nop×3`. It replays both stores, scans
    the 5 weights, and only on a hit rewrites the gains: Y B = b (stock), Cb B = b/2 + b/8, Cr B = 2b + b/2
    (b = 1024 − w, at most 892), A = 1024 − B. No mul, no clamp needed (build check). It exits with the stock
    `ret [d2,d3,a2,a3],20`, keeping d0/a0 as the stock tail.
- Channel order Y, Cb, Cr (+136 lo, hi, +140) is still [I]. If the camera shows a blurred image instead of a red
  fringe, or a blue fringe, swap the fields in halo.s.in (§4).
- Verified (`tools/ep7_halation_verify.py`): F converter flag for effect 2 / strength / MONO / mode 12; W banks on
  both combiners for strength 1..5 (combiner 11 == the formula; combiner 12 == plain pack; rest of the bank and
  the live stack == stock); D bloom 1..5, clarity 1..5, off, erased, bad effect and stock Soft Focus banks
  byte-identical to the previous test13.
- Known gaps: Extras sector 2 shows effect 2 as `Clarity/Glow 0`, and editing it there rewrites it to bloom or
  clarity. lv_art previews only effect 1, so a red-bloom slot has no LV glow.

## 7. Bloom colour presets (plan, not built)

The tint is the pair (k_Cb, k_Cr) in the halo stub, so presets are cheap in code: neutral (1, 1) = stock bloom,
red (0.625, 2.5), amber (0.4, 2.0), warm/orange (0.8, 1.6), cool (2.0, 0.6). A 5-row k table and one extra index
add about 30 B to the stub.

The cost is the **per-slot byte**:
- The loader's range table only allows 0 in bytes +45..63.
- +32..44 are the colour byte and sat advice, which the placement rule and the LOOKS.BIN records already use.
- So a tint byte means a BUNDLES.BIN / LOOKS.BIN rule change (loader v3 range table, `fm_check`,
  `ep7_looks_bin`, `ep7_library.place`) plus a sixth Extras field (`5 Bloom Red`, about 60 B in look_extras).

That is well beyond the 110-B red-only design, so test13 ships red only. Suggested route: allow 0..4 in byte +45
(`bloom_tint`) in the next loader revision. The stub never needs the slot: bloom_w can return a distinct weight per
(strength, tint) pair (25 values near the red-bloom ones), and the stub maps the weight back to its k pair.

## 8. Camera test 13b and bloom colour (test13 in place)

### What the camera showed
- Shots: PB021368–1373 are COLOR1 (makernote PictureMode 9; the card's COLOR1 = CineStill800, effect 2 strength 4).
  PB021376–1379 are COLOR2 (mode 10; Pro 400H, plain bloom 5). PB021374–1375 are MONO1 (mode 12).
- PB021373 is a white-warm LED strip. There is a wide luma glow. Across the strip, the fringe chroma is Cb −5 / Cr +4..+7,
  which is the lamp's own warm cast. The clipped core is Cb −1..−2 / Cr 0. There is no red excess anywhere.
- **Root cause (design, not a crash or a wrong hook).** Effect 2 ran as bloom: the luma glow is there. Its chroma term
  only scales the blurred image's *own* chroma (B_Cr = 2.5 b). A clipped or white light has Cr ≈ 0 after
  development, so 2.5 × 0 stays 0. On a warm light, the extra is a few Cr units: too small to see.
  - The field order (§4) cannot be the cause. With Cb and Cr swapped, the fringe would still be only the source chroma.
  - Every combiner-11 bank field is per channel (+80 offsets, +92/+96 and +136/+140 gains, clamps, output offset).
    A constant chroma term would therefore tint the whole frame, and linear compensation cancels it.
  - A red glow around **white** lights still needs the mask route (FUJI_GAPS §4). That was not built.
  - Side finding [V bytes, I meaning]: the input config words (+88/+132) are three 2-bit per-channel source selectors
    (0x2A = image on all channels, 0x15 = the constant / mono term, 0x14 or 0x28 = chroma only). Stock combiners 33, 135
    and 156 use the 0x15 term with a colour word at +120. If that term is "Y of the input × colour word", it would give
    a true luma-keyed red glow in combiner 11. This needs a camera A/B; it is not built.

### What was built (bloom colour)
- **Card format:** slot byte **+45 `bloom_tint`**: 0 neutral, 1 red, 2 amber, 3 warm, 4 cool (layout.json).
  - Loader v3 range: 0..4. Only the span byte at 0x605b774e changes, 0 → 4.
  - LOOKS.BIN record +47 (was "must be 0") carries the tint, and the Film page places it at slot +45.
  - Old files have 0 there, which means neutral, so they still load. `bloom_tint` is kept out of `layout_crc`,
    so old LOOKS.BIN files still pass the header check.
  - Effect 2 with tint 0 renders red (legacy CineStill800 v2 slots).
- **Weights:** `bloom_w` sends effect 1 and 2 to `bw_tint` (sec 1, dead EVF step-6 R table 0x601e263c).
  - It returns w = W[s] + tint (row 0 = the plain bloom table, so tint 0 banks are byte-identical to before).
  - Rows 1..4 are weights no other path returns.
- **Halo stub** (same hook 0x603a04e8, same table): it maps the weight back to (tint, strength).
  - Y spreads as bloom.
  - Cb and Cr: B_c = min(k_c · b / 8, 1024), A_c = 1024 − B_c, so gains stay positive and sum to 1024.
  - k_Cb / k_Cr: red 0.5 / 3.5, amber 2 / 3, warm 1.25 / 2, cool 3 / 0.75.
  - Red spreads Cr further than before (3.5 vs 2.5) and Cb less.
- **Honest limit:** the colour still follows the light's own chroma. Tungsten, sodium and neon get a clearly tinted
  fringe; white LEDs and clipped cores stay neutral.
- **Extras page:** sector 5 shows `5 Bloom Neutral|Red|Amber|Warm|Cool`; the dial steps 0..4.
  - Sector 2 now shows effect 2 as Glow.
  - Editing sector 2 on an effect-2 slot first sets tint red, so the slot stays red when it becomes effect 1.
- **Live view:** lv_art now previews effect 2 as well, as a luma glow. CineStill800 v2 lost its LV glow in test13
  because lv_art previewed effect 1 only.
- **Library v2:** CineStill800 = `{"type": "bloom", "strength": 4, "tint": "red"}`.
- **Verified** (`tools/ep7_halation_verify.py` vs the previous test13): F 24, W 84, D 112.
  - W covers tints 1..4 and effect 2 + tint 0 on both combiners, plus tint 5/255 and strength-6 guards.
  - D: bloom tint 0, clarity, off and erased banks are byte-identical.

## 9. Camera test 13c: bloom colour "still a no go" (analysis; nothing new built)

### Which slots were shot (makernote 0x0520 PictureMode; 9/10/11 = COLOR1–3, 17 = COLOR4 by elimination, 12 = MONO1)
- PB021380–1383: mode 10 = **COLOR2** (bloom 4, tint 4 cool). PB021384–1390: mode 17 = **COLOR4** (bloom 5, tint 1 red).
  - 1384–1388 are XPan desk scenes without a light source. The LED-strip shots are 1381–1383 (cool) and 1390 (red).
- The card's BUNDLES.BIN passes `ep7_bundles_bin.py --check`. Byte +45 is 4 in COLOR2 and 1 in COLOR4, as intended.

### 1. Is the tint applied for effect 1? Yes. Not a bug.
- `bw_tint` takes effect 1 and 2. Effect 1 uses its own +45 tint, and effect 2 with tint 0 becomes red.
- `tools/ep7_halation_verify.py` on releases/test13 gives F 24 / W 84 / D 112, all PASS. W covers effect 1 × tint 1..4 × strength 1/3/5
  on combiner 11 (halo gains) and combiner 12 (plain pack).
- Stills use combiner 11: clarity, which acts only there, was visible on camera in test 11.

### 3. Fringe chroma, measured (1/8-size JPEG decode, rings around the largest Y > 248 region; Cb/Cr offset from 128)

| Shot | slot / tint | core | ≤4 px | ≤12 | ≤30 | ≤60 | ≤120 |
|---|---|---|---|---|---|---|---|
| 1381 | COLOR2 cool | −1.6/+1.0 | −6.4/+4.1 | −9.8/+7.3 | −8.6/+10.0 | −5.0/+9.1 | −2.2/+4.2 |
| 1382 | COLOR2 cool | −1.4/+1.1 | −5.4/+4.6 | −8.9/+8.9 | −9.0/+13.8 | −5.5/+13.7 | −2.4/+7.3 |
| 1383 | COLOR2 cool | −2.7/+0.4 | −5.8/+5.4 | −8.5/+10.2 | −7.9/+13.2 | −4.7/+11.2 | −1.7/+5.3 |
| 1390 | COLOR4 red | −1.2/+2.0 | −5.1/+4.4 | −10.8/+8.8 | −13.5/+14.5 | −9.6/+13.8 | −4.3/+8.1 |
| 13b 1373 | COLOR1 red (eff 2) | −0.9/+0.5 | −3.4/+2.8 | −5.9/+5.4 | −2.5/+5.2 | −0.2/+3.3 | −0.7/+2.0 |

(Cb/Cr pairs; units of 8-bit chroma.)
- "Cool" and "red" give the **same warm fringe** (Cb −9, Cr +10..14). That fringe is the warm-white LED's own chroma, carried by the
  luma glow. The core is neutral (|Cb|, |Cr| ≤ 3) in every shot.
- The model predicts exactly this. The halo stub scales each chroma channel's own blur share, so it can only re-spread chroma the
  light already has. A cool k_Cb = 3 on a source with Cb ≈ −9 makes the fringe *more* yellow, not blue. A clipped white core has
  nothing to spread. A tint you can see needs a term that depends on luma.
- A pixel "after" for the real route cannot be simulated. That route rests on ISP semantics that are not known (below), and there
  is no ISP model to run it on.

### 2. The real tinted-glow route: not built (blockers found this round)
New facts [V bytes]:
- Each combiner-bank input group is 44 B: A = +76..+119, B = +120..+163.
  - +76 / +120 are the group's **constant colour word**: cleared by the config 0x603a013b; set by combiners 33/156/135.
  - +80/+84 and +124/+128 are offsets, +88/+132 config, +92/+96 and +136/+140 gains, +104..+112 and +148..+156 clamps.
  - +164/+168 is the output offset.
- Config word byte 2 = 0x2A selects the image on all three channels, and byte 1 = 0x15 selects the constant (Vintage B =
  0x1500 + colour 0x001900E1, weight 115). Combiner 135 is the same, with colour 0xFFFFFF and per-channel gains from request+672..676.
  No stock config mixes per-channel sources, and none routes Y into a chroma channel.
- Masks: kind-0 requests get the mask descriptor at request+532 (MONO 0x60359e15, shading 0x6035b0ab). **Kind-3 requests get it at
  request+148** (shading modifier 0x6035b0d8, copied from job+14240 → +12, 64 B). The Soft Focus blend setup 0x6035ca31 copies
  buffer 0x1000 → request+20 and 0x1061 → request+84 (job+6592 + 88·idx, idx from 0x60350975). Its +148 is not set.

Why it is not built (each item is [I] and needs a camera probe; a wrong guess means garbage frames or an ISP stall on tinted slots):
1. **Per-channel ops cannot do it.** Every gain, offset and clamp acts on one channel. In flat areas, a constant chroma term on
   B tints the whole frame by β·K. A luma-keyed term needs a mask or a Y→chroma selector, and neither has been exercised.
2. **Mask route inside the blend** (copy 0x1060's descriptor to blend request+148; bank in the combiner-33 style: mode 0x1002,
   B = colour word, +180 = 3):
   - The meaning of mode 0x1002 and of A config 0 in combiner 33 is unknown.
   - The format of a 0x0305 (4 B/px, 160×120) buffer on the mask port is unknown. The shading mask is created by 0x6036b635,
     format not traced.
   - Whether B (+84) is still read in that mode is unknown.
   - Either way, B = the colour word means the luma blur is replaced, not tinted.
3. **Route via the stock late shading pass** (it already runs after every COLOR blend, combiner 33 = lerp(image, colour, mask)):
   - It would need the mask from the blur buffer.
   - 0x1060/0x1061 are released before that pass runs (blend callback), so a lifetime change across two entries is needed.
     That risks a buffer-pool leak (48 slots) or reuse.
   - It also takes over the slot's vignette.
4. The full FUJI_GAPS §4 route (new mask pass) adds a full-size pass, so it is not at stock Soft Focus speed.

Suggested next step (not done; needs the user's go-ahead): a **probe build** that changes only tint 1 (red) to route 2,
with the other tints unchanged, shot on one warm and one white light. If the frame is valid, the mask/colour semantics are
settled and the tints become colour words. If not, revert the tint-1 rows.

## 10. Red-tint mask-route probe (built into test13 in place; not camera-tested)

User go-ahead after §9: route 2, red tint only.
- **probe_set** (hook 0x6035caad in blend setup 0x6035ca31; replays `movhu (12,a3),d1; movhu (14,a3),d2` → 0x6035cab3).
  - Guards: job marker 0xB2, mode 11, profile 1..4. The slot comes via the v3 accessor and must be effect 1 tint 1, or
    effect 2 tint 0/1.
  - It then finds job buffer 0x1060 (job+6592, 48 × 88 B, id at +76; the 160×120 reduce, alive until the blend
    callback) and copies its 64-B descriptor to request+148, the kind-3 third port (the shading mask port; the generic
    programmer 0x60352729 always loads +148).
  - It also sets request+680 = 1024 (the shading modifier's neutral mask gain [I]).
  - Fail safe: any failed check, or no 0x1060, means no store.
- **probe_bank** (halo stub, red row only). If request+148 equals the 0x1060 descriptor word for word, the bank becomes
  combiner 33's (vignette) shape:
  - mode 0x1002, A cfg 0, A gains 1024, B colour word +120 = 0x00C060D0 (Y 0xD0, Cb 0x60, Cr 0xC0), B cfg 0x151500,
    B gains β = 2b (≤ 714, build-checked), +180 = 3.
  - Otherwise it is the §8 chroma-spread bank.
  - Expected look [I]: lerp(image, orange-red, β × blurred-image mask). The colour's Y gives the glow, so this replaces
    the luma blur blend for red slots.
- Space and checks: bw_tint + halo + probe = 510 B in 0x601e263c–0x601e283c (dead EVF step-6 R and G). The only abs32
  refs are the step-table words 0x601e3ce0/e4. `--red-probe` adds the hook edit. Builds without the flag are
  byte-identical to before.
- Unknowns the camera decides:
  - whether mode 0x1002 reads the mask from port +148 at 160×120 / format 0x0305;
  - which byte of the colour word is Cr. A blue halo means swap 0x60/0xC0;
  - the mask scale.
  - A stall is possible on the hardware side only. The CPU side always falls back.
- Verified: `tools/ep7_red_probe_verify.py` S 110 / B 66; halation F/D pass, and W differs only in the (sp) call scratch
  word. Anti-brick: decode == stock + edits, restore == stock.

### 10b. Camera result (PB021392–1394, testdata/camera_v014): garbled frames, probe reverted in releases/v0.14
The red slots came out as a salmon/brown frame with a regular grid of about 65 px tiles (about 80 × 60 across 5184 × 3888).
Each tile is either the flat colour or the image showing through a dark, rounded blob. Mono and plain shots (1391, 1395) were fine.

What this tells us:
- **Proven:**
  - The capture did not stall.
  - Mode 0x1002 does lerp(image, colour word, mask): where the "mask" is low, the image survives, including sharp text.
  - The colour word's byte 2 drives Cr: the hue is red/salmon, not blue.
  - So the bank shape, port +148 and the colour path work.
- **Inferred [I]:**
  - The mask port does not read the 0x0305 (4 B/px, 160 × 120) reduce buffer as one value per pixel. The grid is half of
    160 × 120 per axis. Each tile is interpolated on its own, so blobs are not continuous across tiles.
  - That points to the port expecting the shading mask's own format: probably 1 B/px or a block-grid / tile layout
    with its own stride.
  - It read our YCbCr bytes as that layout. The wrong stride and format give quasi-random, mostly saturated values, so
    most tiles hit full colour.
- **For a retry:**
  - Trace the shading mask's format, size and stride where it is built (0x6036b635 → 0x6036cec0) and copy that descriptor
    shape.
  - Feed the port a buffer in that format, e.g. a reduce pass that writes Y only. Do not feed it the 0x1060 image buffer.
  - A threshold or scale on the mask is still needed: bright flat areas would otherwise tint.

The release is back to the §8 chroma-spread bank for red slots: 273 edits, bloom edits identical to the pre-probe build,
the log probe kept, and the card unchanged (COLOR1 = bloom 4 red). `--red-probe` stays in patches/bloom/build.py for a
future retry, off by default.

### 10c. Retry with the vignette mask's own format: mask side mapped, source side not (nothing built)
**Vignette mask, mapped [V code]:**
- Built by the cache 0x6036b635: 4 objects of 100 B at 0xa27364e8, key 12 B, refcount at +96.
- Generator 0x6036cec0 fills the 64-B descriptor at object+12:
  - +8 format = **0x080C**, +10 stride = 128 px, +12/+14 = 128 × 128, +16/+18 = 128, +20/+22 = 0, +24/+26 = 64/64 (centre);
  - beyond the copied 64 B: +72 = 0x8000, +76 = 0x00011106.
- Memory comes from the memory manager (0x603509e3, message 19). +0 = the address.
- 0x603390a4 → 0x60338d49 then writes the mask **on the CPU**: **u16 per pixel**, row stride 2 × 128 B, a radial profile
  from table 0x604ebf1c (1024 at the centre, falling to 0) plus 7.
  - So the mask is Q10, and 1024 = image unchanged [I strong: the vignette leaves the centre untouched].
  - No cache flush follows the writes, so this memory is coherent for CPU writes [I].
- The shading request copies that descriptor to kind-3 request+148, with +680 = the level gain (1024 neutral).
- This explains 10b: we handed the port a 0x0305 buffer (4 B/px, 160 × 120). Read as a u16 0x080C-style mask, those bytes
  are mostly saturated or out of range, so most tiles go to full colour.

**What a correct mask would need:** a 64 × 64 or 128 × 128 u16 buffer, m = 1024 − k·max(0, Y − T), built on the CPU from
the blurred highlights at blend-setup time. 64 × 64 could be written in place over 0x1060's memory without overwriting
rows not yet read.

**Why it is not built:** the source side is not mapped with reasonable confidence.
1. The component layout of 0x0305 is unknown: which byte or half-word is Y, and whether it is 8 or 16 bit with a pad.
   - Size = stride × h × 4 is confirmed, nothing else.
   - A layout-agnostic proxy (max byte) fails if the pad byte is 0xFF, and is noise if the components are 16-bit.
2. It is not shown that the reduce pass has *finished* when the blend setup 0x6035ca31 runs. Work-list execution order
   is [I].
3. CPU reads of a DMA-written buffer may be cached. A stale mask is harmless, but it makes the probe ambiguous.

**Safe next step (proposed, not built):** a read-only probe. At blend setup, copy 16 bytes from a bright and a dark
pixel of 0x1060, plus its descriptor words, into the log probe's heap record, and show them on the Extras page as the
video-log probe does. One shot of a lamp then maps the 0x0305 layout and timing with no change to the image pipeline.
After that, the mask route above is a small, well-defined build.

### 10d. Read-only blur-buffer probe (v0.14, in place; not camera-tested)
- `patches/bloom/build.py --blur-probe` (with --sd-v3 --clarity --halation). The code is `blurprobe.s.in`, 632 B in the dead
  EVF step-9 R/G/B tables 0x601e1d3c.
- Hooks:
  - **0x6035caad (blend setup) → bp_set.** Red-tint jobs only. It records 0x1060's descriptor words (+0 addr, +8 fmt/stride,
    +12 w/h, +16) and 5 samples × 8 B (2 px), at the quarter points (2,2) (1,1) (3,1) (1,3) (3,3).
  - **0x6035cbaa (blend callback) → bp_cb.** For the same job, it takes the same samples again *after* the blend.
    Equal = the reduce had finished at setup.
- Record **R = L+1920**: +0 'EP7Q', +4 setup n, +5 callback n, +6 LOGDBG pending, +8 job, +12 flags (bit0 0x1060 found),
  +16..31 descriptor words, +32..71 setup samples, +72..111 callback samples.
  - L = the film-page block, P+1016, which needs LOOKS.BIN on the card.
- Output: `vlog_dump` (patches/video_log) now runs when the video-log batch *or* the bloom record is pending, through
  `bq_gate`. It appends 10 lines `Qk: b0 .. b11` (R+0..119) via `bq_dump`. malloc is now 1024.
- Both hooks replay their stock instructions. Only the heap record and the stack are written. The image pipeline and
  the combiner banks are unchanged.
- Checks:
  - `tools/ep7_blur_probe_verify.py`: S 270 / C 5.
  - halation F 24 / W 84 / D 112 against the 04:36 spec.
  - video_log build_probe: all PASS. Q-dump: 4/4.
  - Anti-brick: decode == stock + edits, restore == stock.

### 10e. Blur-buffer probe: camera crash (removed by the log agent)
A COLOR1 Red capture crashed about 1 s after the shot. The only CPU access new in that build was bp_set/bp_cb **reading
the reduce buffer 0x1060 through its descriptor address**. Inference [I]: that address is not CPU-readable (an ISP/DMA
address, or unmapped for the CPU), and the read faulted.

Rules for later:
- Never CPU-read image buffers through a job-buffer descriptor.
- Every route that needs the blur buffer on the CPU is closed until the address space is mapped.

## 11. v0.14: per-channel bloom colour (not possible) and COLOR Art Effect (built)
**Per-channel bloom weights are not possible in this blend.**
- Combiner 11 works on **YCbCr**: signed chroma, offsets of −128 on channels 1 and 2. Its per-channel gains are
  diagonal in Y, Cb and Cr.
- An RGB weight diag(w_R, w_G, w_B) is a full 3 × 3 matrix in YCbCr, so it needs cross-channel terms the combiner
  does not have (§9).
- For a white light the blur difference B − I is pure luma, so any diagonal YCbCr weighting adds luma only.
  This is exactly the existing chroma spread, which the 13c camera shots confirmed.
- Normalising the per-channel gains to sum to 1 cannot change that. The current bloom colour therefore stays as it is.

**Art Effect (slot +46, `art_effect`):**
- Values: 0 off, 1 Star Light, 2 Pin Hole, 3 Blur (Diorama V), 4 White Edge, 5 Frame.
- Loader v3 range 0..5 (span byte 0x605b774f). `bundles` "art_effect": "star_light|pin_hole|blur|white_edge|frame".
- The byte is kept out of layout_crc, so old LOOKS.BIN files load, and old files (0) mean off.
- `patches/bloom --art`: bloom_flag jumps to `art` (76 B, dead EVF step-9 R 0x601e1d3c) right after the slot lookup,
  so only key-11 COLOR stills with profile 1..4 get it. The stub applies the stock converter's own flag update for
  that Art Effect id: 0x40 / 0x400 / (&~0x300) | 0x100 / 0x2000 / 0x8000.
- LV is untouched: the LV route is 0x60312f42 / lv_art, and neither reads +46.
- **Extras:** sector 5 = `5 Art <name>`, sector 6 = `6 Bloom <colour>`, sectors 7–12 = the log probe label / "Extras: 1-6 only"
  (build_probe constants updated).
- Film page: placing a look writes 0 to +46, and fm_mod counts +46, so a slot with an art effect shows `*`.

**Verified** (`tools/ep7_art_verify.py`, native):
- F 768: the converter for art 0..6/255 × effects × profiles × modes × keys × erased table. Flags == the stock
  converter's own result for that id. Everything else == before.
- L 20: the full work-list builder run to its `ret`, for each flag, classes 0/5, with and without bloom. A COLOR job's
  entries == before with the same flags, and the entries each flag adds on key 11 == the entries it adds on the Pop Art
  key in stock (ART mode).
- S 4096: the kind-3 selector gives the same combiner for key 11 and Pop Art for every effect 0x000–0xfff.
- Extras S / G 936 / W 5392 / V 864. Bloom-colour check F/W/D unchanged. build_probe all PASS.
- Anti-brick: decode == stock + edits, restore == stock.

**Not verified:** the effects' own pass setups (buffer allocation, frame and overlay data) do not run in the emulator.
They are the stock ART-mode setups for the same job flags.
