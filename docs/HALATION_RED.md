# Red halation per slot ("red bloom", effect_id 2)

Status: **built into test13 (§6), emulator-verified, not camera-tested.** This design extends the bloom +
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
