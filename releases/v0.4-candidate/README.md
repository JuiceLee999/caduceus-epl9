# v0.4-candidate: v0.3 review fixes H1, H2, M1 (NOT cleared for flashing)

Metadata only: `edits.json` (merged spec). No `.bin` is kept in git; rebuild the packages with
`tools/build_package.py releases/v0.4-candidate/edits.json`. No camera was contacted, and no SD-update-named
file was created.

Merged, in this order (`tools/merge_specs.py`): bundles v0.2 (`bundles/example.json`), grain v0.4, bloom v0.4,
rec_limit, video_log (option A, Muted → log), aspect (M1 heights). That makes 117 edits and 1,969 changed
payload bytes, in the main component only. Not included: per-profile WB, MONO-colour and SD loading (later).

| | sha256 |
|---|---|
| edits.json | d97c9704beaca347031d2bbd27f251e25b3fe195183c53f702de1e7adebc818b |
| patched.pkg (rebuilt in memory) | 15ae718494892f6ff74110b3e1a6d47f099c0b2534e5bf8734518fed7a9c80aa |
| restore-stock.pkg | 245b9c8fcf247a0271121238b09769b5d90f682924e3086aacc4762211b82612 (= v0.3 restore = stock) |

## What changed since v0.3 (docs/REVIEW_v03.md)
- **H1 (grain job-type gate).** The grain work-list hook replicates stock MONO's gate at 0x6035778b: job types
  with `type&0xf0 ∈ {0x10,0x20,0x40}` or `type&0xf00 == 0x100` get no grain. This covers the 0x110/0x120 jobs
  made from capture kinds 0x2001/0x2006. New emulator test T6 compares each kind and type against the full
  stock MONO handler.
- **H2 (load).** Grain and bloom are per profile and **off by default**. They read the active COLOR slot of
  the bundle table (`grain` +24, `effect_id`/`effect_strength` +28/+29). Grain reads the job bytes
  job+15488..15490. The bloom weight getter reads the job through the bundles request guard. The bloom flag
  hook runs before the job exists, so it reads the same capture bytes (+24083/+24053) that the transport
  copies; see docs/BLOOM_HALATION.md §6. With no marker, an invalid index or a disabled slot, behaviour is
  stock.
  - `bundles/example.json` enables grain on **COLOR3 only (low)**. No slot enables bloom: COLOR4 asks for
    halation, which is stored but not consumed. So in this candidate, COLOR1, COLOR2 and COLOR4 shots carry
    no extra passes. To test bloom, add `"effect": {"type": "bloom", "strength": 1}` to one slot.
  - The bundle builder no longer inherits a recipe's grain. Only a slot's own `"grain"` enables it.
- **M1 (aspect).** Every new id-6/7 height is a multiple of 16. L is now 5184×1920 (was 1912) and
  5184×2224. Two exceptions: both thumbnails share 160×64, and see docs/ASPECT.md.
- Code placement. Grain moved to 0x60210ce0–0x60210dde and bloom to 0x60210e10–0x60210eea, both in the
  section-1 FF tail (claimed in docs/CODE_SPACE_MAP.md). The old section-2 ranges stay FF.

## Verification (emulator only; synthetic fixtures; no ISP pixels)
| Verifier | Standalone build (`generated/v04/`) | Merged `edits.json` |
|---|---|---|
| `ep7_verify_bundles.py` | PASS overall (A–D, F + 19 mutations) | PASS overall, 75/75 |
| `ep7_grain_verify.py` (T1–T6, incl. **T6 job-type gate vs stock MONO**) | all PASS | all PASS + T7 real table (COLOR3 low only) |
| `ep7_bloom_verify.py` (T1–T5) | all PASS | all PASS + T7 real table (no bloom slot → stock) |
| `patches/aspect/build.py` | 137/137 PASS (incl. M1 check) | (image-level) |
| `patches/video_log/build_and_verify.py` | PASS | (image-level) |
| `patches/rec_limit/build_and_verify.py` | PASS | (image-level) |

Additional scratch run (not part of the release): bundles with COLOR1 bloom 5, COLOR2 grain medium + bloom 2,
COLOR3 grain high, merged with grain and bloom. Grain and bloom T7 follow the real table: w = 666 / 881, and
levels 2 / 3. Negative controls: the v0.3 grain build fails the new T2/T3/T4/T6, and the v0.3 bloom build
fails the new T1/T4. Invalid bundle input is rejected: strength 6, a missing strength, a numeric grain, an
unknown grain.

## Still open
- H3/H4 and M2–M4 of the v0.3 review are unchanged. Use the review's camera test order: restore dry run first,
  then each feature alone.
- Grain at job classes 0–3 still uses the single-pass combiner 32, where stock MONO uses the two-pass mask
  route (GRAIN_PORT risk 1).
- The bloom input order is unproven, and so is the assumption that the combiner sees the job-embedded request.
  If the guard fails on the camera, a bloom slot renders at the stock weight 600.

## Full merge: `edits_full.json` (v0.4 + WB + MONO-colour + SD loader; NOT cleared for flashing)

`tools/merge_specs.py releases/v0.4-candidate/edits_full.json` with these sources, in order: the six `edits.json`
sources above, then `generated/wb/edits.json`, `generated/mono_colour/edits.json` and `generated/sd_bundles/edits.json`.
That makes 138 edits and 3,504 changed payload bytes, in main only.
- Re-merging the six sources reproduces `edits.json`'s 117 edits exactly.
- The current `patches/wb/build.py` and `patches/mono_colour/build.py` rebuild their specs byte-identically, so
  nothing had to be rebuilt.
- No overlaps (packager checks). Conflicts: none.
- The MONO-colour builder's reservation list still names v0.3, but v0.4 moved grain and bloom into section 1 and
  MONO-colour is in section 7. Its verifier passes on this v0.4-based merge.

| | sha256 |
|---|---|
| edits_full.json | b707fee3e4aa774c245905fb5d65d730a33363aa3bdc9a156f393b172bb3ab38 |
| patched.pkg (rebuilt in memory) | 6517c741fbcb752a4281834d5d402e012f756ee94970e5a9f9180c1a2f7bda48 |
| restore-stock.pkg | 245b9c8fcf247a0271121238b09769b5d90f682924e3086aacc4762211b82612 (= stock) |

Verification of `edits_full.json` (emulator only, run 2026-11-01):
| Verifier | Result |
|---|---|
| `ep7_verify_bundles.py` | PASS overall, 75/75 (A–D, F + 19 mutations) |
| `ep7_grain_verify.py` | T1–T7 all PASS (T7 real table: COLOR3 low only) |
| `ep7_bloom_verify.py` | T1–T5, T7 all PASS (no bloom slot → stock weight 600) |
| `ep7_verify_wb.py` | T, S, U (14 sites), K, W, C, G PASS + 20/20 mutations |
| `ep7_mono_colour_verify.py` | 213/213 tests, 20/20 mutations PASS |
| `ep7_verify_sd_bundles.py` (new) | S, 173 single-mount cases, 7 load-once sequences, 17/17 mutations PASS (docs/SD_BUNDLES.md §6) |
| `patches/aspect/build.py` | 137/137 PASS |
| `patches/video_log/build_and_verify.py` | PASS |
| `patches/rec_limit/build_and_verify.py` | PASS |

The aspect, video_log and rec_limit scripts are image-level standalone checks. They rewrite their own `edits.json`
identically.

Still open for the SD loader: the [I] items in docs/SD_BUNDLES.md. These are the HIGHLEVEL_MAIN context, blocking
fileif at mount, writable section-1 and section-6 copies, and cache coherency. The first camera check is the one
given there.
