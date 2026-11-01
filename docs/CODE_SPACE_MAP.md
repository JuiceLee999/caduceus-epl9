# Code-space allocation map (E-P7 1.1 main)

Single source of truth for which patch owns which bytes. Every new patch must claim a range here first.
Verified loaded FF tails (docs/HSL_PORT.md; section 2 range re-verified via loader 0x60027068/0x60045786).

| Range (end exclusive) | Section | Owner | Status |
|---|---|---|---|
| 0x6055e5c0–0x6055e680 | 2 | HSL hook routine v0.1 (v0.2 does NOT use it; free when v0.1 is retired) — **retired by test 9: now inside the bloom + clarity claim below** | v0.1 built (never with test 9) |
| 0x6055e680–0x6055e700 | 2 | colour grain (patches/grain) — v0.3 placement; **v0.4 moved to sec 1; retired by test 9 (bloom + clarity claim below)** | superseded in v0.4 |
| 0x6055e5c0–0x6055e6f0 | 2 | **bloom + clarity** (`patches/bloom --sd-v3 --clarity`, docs/CLARITY.md): bloom_flag, bloom_w, w_lut/c11_lut/c12_lut (270 B used, 0x6055e5c0–0x6055e6ce). Guards 0x6055e5b0–0x6055e5c0 (stock data ends 0x6055e5af) and 0x6055e6f0–0x6055e700 (before WB) stay FF. Replaces the sec-1 bloom block 0x60210e10 in clarity builds (that block is then stock FF) | built + emulator-verified (test 9) |
| 0x6055e700–0x6055e7a6 | 2 | per-profile WB stub `wb_get` (patches/wb; 164 B used, 0x6055e700–0x6055e7a4; 0x6055e7a4–0x6055e7b0 stays FF) | built + emulator-verified (docs/WB_PATCH.md) |
| 0x6055e7b0–0x6055e7f0 | 2 | colour bloom (patches/bloom) — v0.3 placement; **v0.4 moved to sec 1 (row below); range kept reserved for bloom** | superseded in v0.4 |
| 0x60210900–0x60210b00 | 1 | 8-slot bundle table (v0.2), fixed ABI: patches/bundles/layout.json. Read by v0.2 H/L (hue/light) and by patches/wb (wb_flags/wb_ab/wb_gm, all 8 slots) | built + verified |
| 0x60210b00–0x60210c70 | 1 | v0.2 LUTs, converter stubs, H/L routine (docs/V02_BUNDLES.md) | built + verified |
| 0x602108ec–0x60210900, 0x60210c70–0x60210c80 | 1 | guard (keep FF) | – |
| 0x60210c90–0x60210cd0 | 1 | video log vlog_hook (patches/video_log; 42 B, 53 B with Flat; 0x60210c80–0x60210c90 guard) | built + emulator verified |
| 0x60210ce0–0x60210e00 | 1 | v0.4 per-profile colour grain: wl_hook (job-type gate + bundle slot), sel_hook, grain_mod (patches/grain; 0x60210cd0–0x60210ce0 guard) | claimed (v0.4) |
| 0x60210e10–0x60210ef0 | 1 | v0.4 per-profile colour bloom: bloom_flag, bloom_w (+strength LUT) (patches/bloom; 0x60210e00–0x60210e10 and 0x60210ef0–0x60210f00 guards) | claimed (v0.4) |
| 0x60210f00–0x60210f80 | 1 | aspect case blocks S1–S5 (patches/aspect; 110 B used, 0x60210f00–0x60210f6e) | built + emulator-verified |
| 0x61242a00–0x61242d00 | 6 | SD-card bundle loader sd_hook/sd_load/sd_check/sd_crc + path, header, range tables, `sd_state` byte (patches/sd_bundles; 564 B used, 0x61242a00–0x61242c34, sd_state at 0x61242c33 is written at run time). Guards 0x612429b0–0x61242a00 and 0x61242d00–0x61242f00 stay FF; stock data ends 0x612429af | **superseded by v2** (dead hook, REVIEW_v04 H1-new); never combine with v2 |
| 0x605b7400–0x605b7780 | 3 | SD look loader **v2** sd_hook/sd_gate/sd_load/sd_check/sd_crc + path/header/range tables + `sd_state` (0x605b7692, written at run time) (patches/sd_bundles_v2; 659 B used, 0x605b7400–0x605b7693). Guards 0x605b73f0–0x605b7400 and 0x605b7780–0x605b7800 stay FF. 0x605b7190–0x605b73f0 left clear for the provisional ORF/wifi placements (HSL_PORT.md). Stock data ends 0x605b717f; sec 3 load end 0x605b7800 | built + emulator-verified (docs/SD_BUNDLES_V2.md) |
| 0x61242f00–0x61242f60 | 6 | aspect: relocated Image Aspect option list, 8 × 12 B data (patches/aspect) | built + list parse verified |
| 0x61378c80–0x61378f7c | 7 | MONO-colour LUTs + sel/chroma/fg stubs (patches/mono_colour; 764 B). Guards 0x61378c68–0x61378c80 and 0x61378f7c–0x61378f8c stay FF; 0x61378f8c–0x61379000 (116 B) free. Sec-7 end 0x61379000 re-verified via loader 0x60027068 entry 6 + end getter 0x60045786 → 0x600457c4 | built + emulator-verified (docs/MONO_COLOUR.md) |
| 0x60210f80–0x60210ff2 | 1 | aperture ring `.lens` (disp_hook + parse_hook, 114 B; patches/aperture_ring, docs/APERTURE_RING.md). 0x60210ff2–0x60210ffe stays FF | built + emulator-verified |
| 0x60210ffe–0x60211000 | 1 | aperture ring published ring halfword (initial 0x8000, written at run time via 0xa0210ffe) | built + emulator-verified |
| 0x61378f9c–0x61379000 | 7 | aperture ring `.ae` ae_hook (100 B, to section end; 0x61378f8c–0x61378f9c guard) — takes the sec-7 free tail | built + emulator-verified |
| 0x601e383c–0x601e3a3c | 1 | Log View Assist (patches/view_assist): VA LUT 256 B at 0x601e383c (dead EVF step-0 R table) + va_hook (74 B probe / 105 B full) at 0x601e393c (dead EVF step-0 G table; rest of G stays stock). EVF tables are dead on the E-P7 (no EVF; COLORTEMP→EVF only when the current device is EVF, 0x60174d19) [I strong] | built + emulator-verified (docs/LOG_VIEW_ASSIST.md) |

## Hook sites (stock bytes replaced)
| Site | Bytes | Owner |
|---|---|---|
| 0x603b02d9 | 5 | HSL (call builder → jmp); v0.1 and v0.2 are mutually exclusive |
| 0x60319157, 0x6031915c | 2+2 | recording limit |
| 0x6030df3d | 5 | video log: `266001f172` (mov 352,a2; add a0,a2) → jmp vlog_hook |
| 0x6035749f | 7 | grain work-list |
| 0x603b5249 | 7 | grain combiner selector |
| 0x603eabd7 | 6 | bloom: art-effect flag converter (key 11 → job flag 0x80); clarity builds: same hook, also effect_id 3 |
| 0x6039fee8 | 6 | bloom: Soft Focus mix-weight getter (key 11 → w); clarity builds: w > 1024 when called from combiner 11 (return address 0x603a04ac) |
| 0x60302c46, 0x60302c60, 0x60302da3, 0x60302db8, 0x60302e35, 0x60302e4b, 0x60302f23, 0x60302f3b, 0x60302f8f, 0x60302fa8, 0x6030bb5b, 0x6030bb6e, 0x6030eb61, 0x6030eb77 (edit at site+1) | 4 each | per-profile WB: rel32 of `call 0x6005e971,[d2,d3],12` → wb_get (docs/WB_PATCH.md) |
| 0x60c68a45, 0x60c68a59 | – | RAW-development WB reads: deliberately left stock (do not claim for WB) |
| 0x603b02bf (6) | 6 | MONO-colour: selector mode test `or d2,d1; cmp 11,d1; bne` → jmp sel |
| 0x603b134e (5) | 5 | MONO-colour: chroma-stage tone lookup call → jmp chroma |
| 0x60353db9 (8) | 8 | MONO-colour: packer mono-filter merge `mov (11308,a0),d0; cmp 12,d0; bne` → jmp fg |
| 0x60210900 table +32 / +33..+44 | data | bundle slot `colour` / `sat[12]` (patches/bundles/layout.json), read by MONO-colour |
| 0x601f9df7 | 5 | aperture ring: dispatcher `bne; jmp null` → jmp disp_hook |
| 0x601f5ed7 | 8 | aperture ring: status parser DIS_FCENC store → call parse_hook,[],0; nop |
| 0x60427ae7 | 5 | aperture ring: AE snapshot `call 0x60429548,[],4` (aperture point 0x80ca) → jmp ae_hook |
| 0x603537f0 (3), 0x6035390c (2) | 5 | v0.2 job size 15488→15512, tail memset 16→40 |
| 0x603e66ab (6), 0x603e91f0 (6) | 12 | v0.2 converter transport (replaces the 0x603e669f/0x603e91e4 candidates) |
| 0x60863e91 | 4 | SD bundle loader v1 (superseded, dead path): rel32 of the mount-OK `call 0x6077d590,[d2],20` at 0x60863e90 → sd_hook (tail-jumps to 0x6077d590) |
| 0x602c805f | 5 | SD look loader v2: appevent TRIG tracker `call 0x602c818c,[d2,d3,a2,a3],36` (in 0x602c7f5a, task HLS_EVENT) → `jmp sd_hook` (replays the call, returns to 0x602c8064) |
| 0x60210900–0x60210b00 | data (run time) | SD bundle loader rewrites the v0.2 bundle table in RAM from a valid C:\EP7MOD\BUNDLES.BIN (no flash edit) |
| 0x6117af14 | 8 | aspect: setting-270 option descriptor (count 6→8, list ptr → 0x61242f00) |
| 0x60b04428/2c, 0x60b04454/58, 0x60b0daf8/fc, 0x60b0e0ec/f0, 0x60af4a18/1c, 0x60b01548/4c | 4 each | aspect: jump-table entries ids 6/7 (S1–S6, sec 5) |
| 0x604cae3c (46 B of 72), 0x604cb00e (32 B) + records 0x604cda08/1c/30, 0x604cdad0/e4 (+4 ptr, +12 bytes) | data (sec 2) | buttons: in-place validator lists for sids 47/48/49 and arrow 51/53 (patches/buttons, docs/BUTTONS.md). Stock lists at 0x604cae54/6c and 0x604cb01e are absorbed; 0x604cae6a–0x604cae84 left stock, unreferenced |
| ~90 table rows for aspect ids 6/7 (patches/aspect/edits.json, `why` = table@addr) | 4–16 each | aspect: size/geometry tables |
| 0x601751f4 | 5 | Log View Assist: display reply tail `movhu (44,sp),d0; clr d2; mov d0,d1` → jmp va_hook |
| 0x601e3c40 | 12 (data) | Log View Assist: TFT gamma step-17 slot R/G/B pointers NULL → 0x601e383c |
