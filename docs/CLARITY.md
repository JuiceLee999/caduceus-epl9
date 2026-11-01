# Clarity (local contrast) on COLOR stills: E-P7 1.1

Offline work only. No camera was contacted and no SD-update-named file was made. Release candidate:
`releases/test9-clarity/` (test 7b + clarity). **Not cleared for flashing until the user says so.**

Labels: **[V]** read from the decoded main or checked by a build script. **[E]** shown in the emulator.
**[C]** seen on the camera. **[I]** inference (not proven).

## 1. Idea

Bloom already gives COLOR stills the stock Soft Focus passes: reduce to 160×120, upscale, then mix in
combiner 11, out = w·A + (1024−w)·B (docs/BLOOM_HALATION.md). Bloom uses w < 1024, which mixes blur in.
With **w > 1024** the blurred input gets a negative weight: out = A + k·(A − blur(A)), k = (w−1024)/1024.
That is an unsharp mask with a very large radius, which is what "clarity" means (docs/FUJI_GAPS.md §3).

Bundle field: `effect_id` (+28) = **3**, `effect_strength` (+29) = 1..5.
Bundle JSON: `"effect": {"type": "clarity", "strength": 1-5}`.

| Strength | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| w (combiner 11) | 1100 | 1180 | 1260 | 1340 | 1420 |
| k = (w−1024)/1024 | 0.074 | 0.15 | 0.23 | 0.31 | 0.39 |
| B weight 1024−w | −76 | −156 | −236 | −316 | −396 |

Clarity and bloom cannot be used together on one profile. They are one field and share the same passes.

## 2. Verified facts

### 2.1 Combiner programming (CPU side)
- [V][E] Combiner 11 (`0x603a049e`) takes w from the getter `0x6039fee8`, applies `exthu`, and writes
  +92 = w | w<<16, +96 = w, +136 = exthu(1024−w) | (1024−w)<<16, +140 = 1024−w (a 32-bit signed value).
  None of these steps clamps. For w > 1024 the result is a signed halfword pair plus a sign-extended word.
- [E] **Stock combiner 6 (Dramatic Tone) packs its −1024 B gain the same way**: +136 = 0xFC00FC00,
  +140 = 0xFFFFFC00, in mode 0x00100002. The clarity bank matches this packing exactly (verifier part C,
  which runs stock combiner 6 directly). So the B gain uses the same signed format the firmware already
  uses for a negative weight.
- [E] Survey of every stock combiner handler (`generated/clarity/combiner_survey.json`):
  - Combiner 5 writes A = 1066 > 1024 (mode 0x00200000).
  - Combiner 136 writes A = B = 1024 (mode 0x00200001), so the weights do not have to sum to 1024.
  - Combiner 36 loads its +140 B gain with `exth` (a signed halfword) in mode 0x00201021.
  - **No stock combiner writes a negative gain, or a single gain above 1024, in mode 0x00200001.**
    Negative gains appear in stock only in mode 0x00100002.
- [E] The clarity bank changes only the four weight words. The mode word (0x00200001) and every other bank
  byte are byte-identical to stock key 11.

### 2.2 Patch (patches/bloom `--sd-v3 --clarity`)
- [V] It uses the same two hooks as bloom (0x603eabd7 flag converter, 0x6039fee8 weight getter). The bloom
  routine is extended (`bloom_clarity.s.in`) and moved to the section-2 FF tail **0x6055e5c0–0x6055e6ce**
  (claim 0x6055e5c0–0x6055e6f0). The old section-1 block at 0x60210e10 goes back to stock FF.
  docs/CODE_SPACE_MAP.md is updated.
- [V] `bloom_flag`: key 11, mode 11, profile 1..4, slot effect_id **1 or 3**, strength 1..5 → job flag 0x80.
- [V] `bloom_w`, after the unchanged job guard:
  - effect 1 → bloom LUT (unchanged).
  - effect 3 and caller is combiner 11 (MDR = return address 0x603a04ac) → clarity LUT.
  - effect 3 and any other caller (combiner 12, job classes 4–8) → **1024**, i.e. A gain 0 and B gain 1024.
    No negative gain is ever written there.
  - Any failed check → 600 (stock).
- [V] SD loader v3: the per-byte range for effect_id changes from 0..2 to **0..3**
  (`patches/sd_bundles/build.py` RANGES). This is one data byte at 0x605b768c (span 2→3). It has no new
  instructions. `patches/bundles` accepts `"clarity"`.

### 2.3 Verification on the exact package bytes (`generated/clarity/`)
| Run | Result |
|---|---|
| `tools/ep7_clarity_verify.py releases/test9-clarity/edits.json --card … --expect-sha …` (clarity_release.out) | **all PASS** |
| P: base build == test-7b release sha `d6a85f20…`; test-9 vs base differs only in the 5 changed edits (487 B); old bloom block FF; package sha `5913c948…` | PASS |
| C: converter flag (keys × profiles × modes × art effects, strength 0/6/255, effect 2/4/0x83/0xff, erased); combiner banks for strengths 1..5 on combiners 11 and 12; 14 guard failures → stock w 600; other keys → stock; live caller stack == stock | PASS |
| D: differential vs the camera-proven test-7b image for tables without effect 3 (bloom fixtures, bloom 1..5, halation, all-off, erased, poison, real flashed table): converter and full bank byte-identical; all-off == stock | PASS (bloom unchanged, stock when off) |
| S: store audit of the new routine | PASS: the only stores are `mov d0,(a2)` (job-flag word in the converter's params block, as in bloom) and `mov d1,(sp)`. No absolute stores and none added compared with the test-7b bloom routine |
| No stores into 0x60020020–0x6191ffe0 | Every emulator run maps the image segments read-only, so any such store would fault. All runs passed. The loader change is data only |
| L: real SD loader v3 run (upstream event): clarity file loaded, accessor returns it; **test-7b loader rejects it** (old range); effect 4 rejected; the release card file loads | PASS |
| M: 16 mutations (LUT values, combiner-11 address and branch, effect-id compares in both stubs, strength bound, flag bit, LUT pointers, c12 select, loader range byte) | 16/16 detected |
| Loaded mode (table served from the SD buffer, flashed copy poisoned), C + D (clarity_loaded.out) | PASS (1337/1338 runs relocated; the one left is the table-less combiner-6 run) |
| `ep7_bloom_verify.py` on test 9, flashed / loaded (bloom_*.out) | PASS / PASS |
| `ep7_verify_sd_bundles_v3.py` S,A,R,M + E/F 179 + Q 10 on test 9 (v3_SARM.out, v3_EQ.out) | PASS (10/10 loader mutations). This needs `v3_verifier_clarity.patch` (bloom code range + store-audit baseline), which was applied to a HEAD copy because another agent is editing that verifier |

Builds ran in an isolated copy of HEAD plus these changes, so the concurrent `sd_bundles_v3` work was not
picked up. `patches/bloom` builds without `--clarity` are byte-identical to before [V].

## 3. Inference and risks (not proven offline)

1. **[I] Hardware sign handling in mode 0x00200001 (main risk).** The emulator shows only what the CPU
   writes to the bank. It cannot show what the ISP does with it. Negative gains are proven in stock only
   in mode 0x00100002 (combiner 6). If the blend unit treats the B gain as unsigned in mode 0x00200001,
   then 0xFF9C ≈ +64 × blur, and the image would come out white or saturated. That is a bad picture, not
   a crash [I]. Shoot COLOR3 (strength 2) before COLOR1 (strength 5) and look for that first.
2. **[I] Input order.** Clarity assumes that A (+92) is the sharp image. Test-5/6 bloom "looks good" [C],
   which fits A = sharp, but the order was never isolated. If A were the blurred image, clarity would
   look like strong blur with inverted detail.
3. **[I] Clipping and halos.** Edges overshoot by up to k·(A − blur) and are clamped by the bank's output
   clamps (stock defaults). Expect halos around high-contrast edges at strengths 4–5 (normal for unsharp
   masking). Chroma is sharpened too, because all three channels use the same weights. Luma-only clarity
   would need a handler-tail hook and is not built.
4. **[I] Radius.** It is fixed by the 160×120 reduce: one reduced pixel ≈ 32 px at 5184 wide. The reduce
   may point-sample rather than average. In that case the blur aliases and clarity shows blocky low-frequency
   artefacts.
5. **[I] Job classes 4–8 (combiner 12)** get w = 1024. If combiner 12's B input is the sharp image (inferred
   from Olympus swapping the weights), the result is unchanged except for the time cost. If it is not,
   those jobs show the blur. What these classes are has not been traced.
6. **[I] Cost.** Same as bloom: three full-resolution passes and about 80 MB of buffers per COLOR still
   (test 5: slight write lag).
7. **[V] Coverage.** Stills only, COLOR profiles 1–4, set per slot. Movies and live view do not get it
   (same as bloom).

## 4. Camera test (test 9)

See `releases/test9-clarity/README.md`. Flashed table = test 7b's, so with no card file every profile
behaves exactly like test 7b. The card file adds COLOR1 = clarity 5 and COLOR3 = clarity 2.
