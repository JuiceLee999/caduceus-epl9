# Code-space allocation map (E-P7 1.1 main)

Single source of truth for which patch owns which bytes. Every new patch must claim a range here first.
Verified loaded FF tails (docs/HSL_PORT.md; section 2 range re-verified via loader 0x60027068/0x60045786).

| Range (end exclusive) | Section | Owner | Status |
|---|---|---|---|
| 0x6055e5c0–0x6055e680 | 2 | HSL hook routine v0.1 (v0.2 does NOT use it; free when v0.1 is retired) | v0.1 built |
| 0x6055e680–0x6055e700 | 2 | colour grain (patches/grain) — v0.3 placement; **v0.4 moved to sec 1 (row below); range kept reserved for grain** | superseded in v0.4 |
| 0x6055e700–0x6055e7a6 | 2 | per-profile WB stub `wb_get` (patches/wb; 164 B used, 0x6055e700–0x6055e7a4; 0x6055e7a4–0x6055e7b0 stays FF) | built + emulator-verified (docs/WB_PATCH.md) |
| 0x6055e7b0–0x6055e7f0 | 2 | colour bloom (patches/bloom) — v0.3 placement; **v0.4 moved to sec 1 (row below); range kept reserved for bloom** | superseded in v0.4 |
| 0x60210900–0x60210b00 | 1 | 8-slot bundle table (v0.2), fixed ABI: patches/bundles/layout.json. Read by v0.2 H/L (hue/light) and by patches/wb (wb_flags/wb_ab/wb_gm, all 8 slots) | built + verified |
| 0x60210b00–0x60210c70 | 1 | v0.2 LUTs, converter stubs, H/L routine (docs/V02_BUNDLES.md) | built + verified |
| 0x602108ec–0x60210900, 0x60210c70–0x60210c80 | 1 | guard (keep FF) | – |
| 0x60210c90–0x60210cd0 | 1 | video log vlog_hook (patches/video_log; 42 B, 53 B with Flat; 0x60210c80–0x60210c90 guard) | built + emulator verified |
| 0x60210ce0–0x60210e00 | 1 | v0.4 per-profile colour grain: wl_hook (job-type gate + bundle slot), sel_hook, grain_mod (patches/grain; 0x60210cd0–0x60210ce0 guard) | claimed (v0.4) |
| 0x60210e10–0x60210ef0 | 1 | v0.4 per-profile colour bloom: bloom_flag, bloom_w (+strength LUT) (patches/bloom; 0x60210e00–0x60210e10 and 0x60210ef0–0x60210f00 guards) | claimed (v0.4) |
| 0x60210f00–0x60210f80 | 1 | aspect case blocks S1–S5 (patches/aspect; 110 B used, 0x60210f00–0x60210f6e) | built + emulator-verified |
| 0x61242f00–0x61242f60 | 6 | aspect: relocated Image Aspect option list, 8 × 12 B data (patches/aspect) | built + list parse verified |

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
| 0x60302c46, 0x60302c60, 0x60302da3, 0x60302db8, 0x60302e35, 0x60302e4b, 0x60302f23, 0x60302f3b, 0x60302f8f, 0x60302fa8, 0x6030bb5b, 0x6030bb6e, 0x6030eb61, 0x6030eb77 (edit at site+1) | 4 each | per-profile WB: rel32 of `call 0x6005e971,[d2,d3],12` → wb_get (docs/WB_PATCH.md) |
| 0x60c68a45, 0x60c68a59 | – | RAW-development WB reads: deliberately left stock (do not claim for WB) |
| 0x603b02c1, 0x603b134e, 0x60353db9 | TBD | MONO-in-colour (design only) |
| 0x603537f0 (3), 0x6035390c (2) | 5 | v0.2 job size 15488→15512, tail memset 16→40 |
| 0x603e66ab (6), 0x603e91f0 (6) | 12 | v0.2 converter transport (replaces the 0x603e669f/0x603e91e4 candidates) |
| 0x6117af14 | 8 | aspect: setting-270 option descriptor (count 6→8, list ptr → 0x61242f00) |
| 0x60b04428/2c, 0x60b04454/58, 0x60b0daf8/fc, 0x60b0e0ec/f0, 0x60af4a18/1c, 0x60b01548/4c | 4 each | aspect: jump-table entries ids 6/7 (S1–S6, sec 5) |
| ~90 table rows for aspect ids 6/7 (patches/aspect/edits.json, `why` = table@addr) | 4–16 each | aspect: size/geometry tables |
