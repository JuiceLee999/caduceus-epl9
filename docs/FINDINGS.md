# E-P7 1.1 (build 1100) findings

## Container `OLY_E_142_1100_0000_0000.BIN` (111,017,984 bytes)
| # | kind | size | container addr | role |
|---|---|---:|---|---|
| 0 | 0x100 | 26,214,336 | 0x406a0020 | main application (CPU base 0x60020020) |
| 1 | 0x101 | 26,214,336 | 0x421a0020 | TBD |
| 2 | 0x106 | 45,219,776 | 0x43aa0020 | TBD (likely OSD/resources) |
| 3 | 0x10e | 262,080 | 0x00000020 | TBD (small; possibly boot-related) |
| 4 | 0x102 | 13,107,136 | 0x467e0020 | TBD |

## Update paths
- SD: `DCOLYMP/E142????BIN` (body), `S142????BIN` (boot image), `G142…` (TBD).
- USB: OM Workspace PTP-over-SCSI upload (per fishcu PEN-F docs; E-P7 assumed similar, unverified).

## Colour (from fishcu cross-model comparison, to verify ourselves)
COLOR table 0x6051de2c, gains 0x60531810, builder 0x603b0068–0x603b0247,
selector 0x603b0252–0x603b0345, writer 0x6034667e–0x6034677b.
