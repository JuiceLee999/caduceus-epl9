# Code-space allocation map (E-P7 1.1 main)

Single source of truth for which patch owns which bytes. Every new patch must claim a range here first.
Verified loaded FF tails (docs/HSL_PORT.md; section 2 range re-verified via loader 0x60027068/0x60045786).

| Range (end exclusive) | Section | Owner | Status |
|---|---|---|---|
| 0x6055e5c0–0x6055e680 | 2 | HSL hook routine (v0.1, replaced by v0.2) | v0.1 built |
| 0x6055e680–0x6055e6fb | 2 | colour grain modifier (patches/grain) | built + verified |
| 0x6055e700–0x6055e7a6 | 2 | per-profile WB stub (docs/WB_AND_MONO.md) | designed + stub verified |
| (TBD, 512 B) | 3/6/7 | 8-slot bundle table (v0.2) | in progress |

## Hook sites (stock bytes replaced)
| Site | Bytes | Owner |
|---|---|---|
| 0x603b02d9 | 5 | HSL (call builder → jmp) |
| 0x60319157, 0x6031915c | 2+2 | recording limit |
| 0x6035749f | 7 | grain work-list |
| 0x603b5249 | 7 | grain combiner selector |
| 16 getter call sites (docs/WB_AND_MONO.md) | 4 each | per-profile WB |
| 0x603b02c1, 0x603b134e, 0x60353db9 | TBD | MONO-in-colour (design only) |
| 0x603537f0, 0x6035390c, 0x603e669f, 0x603e91e4 | TBD | v0.2 profile transport (in progress) |
