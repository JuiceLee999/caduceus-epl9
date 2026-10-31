# Code-space allocation map (E-P7 1.1 main)

Single source of truth for which patch owns which bytes. Every new patch must claim a range here first.
Verified loaded FF tails (docs/HSL_PORT.md; section 2 range re-verified via loader 0x60027068/0x60045786).

| Range (end exclusive) | Section | Owner | Status |
|---|---|---|---|
| 0x6055e5c0–0x6055e680 | 2 | HSL hook routine v0.1 (v0.2 does NOT use it; free when v0.1 is retired) | v0.1 built |
| 0x6055e680–0x6055e6fb | 2 | colour grain modifier (patches/grain) | built + verified |
| 0x6055e700–0x6055e7a6 | 2 | per-profile WB stub (docs/WB_AND_MONO.md) | designed + stub verified |
| 0x6055e7b0–0x6055e7f0 | 2 | colour bloom stubs (patches/bloom; 51 B used, 0x6055e7b0–0x6055e7e3) | built + emulator-verified |
| 0x60210900–0x60210b00 | 1 | 8-slot bundle table (v0.2), fixed ABI: patches/bundles/layout.json | built + verified |
| 0x60210b00–0x60210c70 | 1 | v0.2 LUTs, converter stubs, H/L routine (docs/V02_BUNDLES.md) | built + verified |
| 0x602108ec–0x60210900, 0x60210c70–0x60210c80 | 1 | guard (keep FF) | – |
| 0x60210c90–0x60210cd0 | 1 | video log vlog_hook (patches/video_log; 42 B, 53 B with Flat; 0x60210c80–0x60210c90 guard) | built + emulator verified |

## Hook sites (stock bytes replaced)
| Site | Bytes | Owner |
|---|---|---|
| 0x603b02d9 | 5 | HSL (call builder → jmp); v0.1 and v0.2 are mutually exclusive |
| 0x60319157, 0x6031915c | 2+2 | recording limit |
| 0x6030df3d | 5 | video log: `266001f172` (mov 352,a2; add a0,a2) → jmp vlog_hook |
| 0x6035749f | 7 | grain work-list |
| 0x603b5249 | 7 | grain combiner selector |
| 0x603eabd7 | 6 | bloom: art-effect flag converter (key 11 → job flag 0x80) |
| 0x6039fee8 | 6 | bloom: Soft Focus mix-weight getter (key 11 → w) |
| 16 getter call sites (docs/WB_AND_MONO.md) | 4 each | per-profile WB |
| 0x603b02c1, 0x603b134e, 0x60353db9 | TBD | MONO-in-colour (design only) |
| 0x603537f0 (3), 0x6035390c (2) | 5 | v0.2 job size 15488→15512, tail memset 16→40 |
| 0x603e66ab (6), 0x603e91f0 (6) | 12 | v0.2 converter transport (replaces the 0x603e669f/0x603e91e4 candidates) |
