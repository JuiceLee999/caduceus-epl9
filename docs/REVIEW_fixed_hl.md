# Independent review: E-P7 1.1 "fixed H/L" patch

Reviewer: independent, adversarial, offline only. No camera or device was contacted, no SD-named file was
created, and no repo file was modified except this one. Everything below was re-derived from bytes with
`mn10300-elf-objdump`, our own numpy scanners (all relative branch/call encodings, plus abs32 at every byte
alignment), and an in-memory package build. Nothing was taken from the authors' docs on trust.

Inputs verified by hash:
- Stock container `9d1610…eaeb`.
- Decoded main `5dd9af16…6190`.

Re-running `build.py --recipe classic_neg` into a scratch directory gives a `routine.bin` and edit list
byte-identical to `generated/hsl-fixed-test/`. `tools/ep7_verify_package.py` reproduces PASS for 4/4
saturation sets, with 109 changed bytes, all inside the edit spans.

## Verdict

**Not yet.** I found no defect in the patch code itself. The hook, routine, placement and package
construction all check out, and the routine provably writes only bytes that the stock builder has just
written. The open risks are about the **update and recovery path on the E-P7**, which nobody in this
repo has exercised or traced (H1, H2). They are cheap to close without risk: dry-run the stock restore
package and confirm the installed version. After that, the patch is reasonable to consider, with the
mitigations in M1/M2.

## Findings by severity

### Blocker
None found.

### High

**H1. The E-P7 SD update path has not been demonstrated or traced: entry, main-only and same-version
acceptance, and filename suffix rules.**
- The repo only verified that the `E142????BIN` strings exist.
- The updater lives in section 6:
  - SD client strings at 0x60f2cb24/0x60f2d81c, referenced from 0x602483fc and 0x60f2d84c.
  - `[firmup]` handlers at 0x60c96xxx–0x60c97xxx.
  - `usr_checksum_error` at 0x60c96564.
- The acceptance logic, any component-set requirement, the version/suffix handling, and the physical
  trigger have not been mapped on the E-P7.
- PEN-F evidence (fishcu RECOVERY.md, CONTAINERS.md) shows that main-only same-version packages are
  accepted on PEN-F. It also states that the physical SD entry is "not connected end to end". That is
  a different model with a different updater build.
- Consequence: today nobody knows whether the restore package can actually be installed. That restore
  route is the whole recovery story.
- **Required before flashing the patch:** install `restore-stock.pkg.bin`, renamed by a human, on the
  camera first. It is byte-identical to the installed 1.1 main (see H2). That proves the trigger, the
  acceptance of a main-only same-version package, and the naming, with essentially no risk.
- Caveat: the updater appears to compare each 1 MiB block with the flash contents and skip identical
  blocks. At 0x60c971e5–0x60c97226 it reads flash into 0xaf90e600, calls memcmp 0x60022f89, logs
  `same result of the comparison`, and skips the write at 0x600c4f35. A stock-on-stock dry run
  therefore proves entry and acceptance, but probably not programming.

**H2. A main-only package is only safe if the camera already runs exactly 1.1 / build 1100 on every
other component.**
- The package and the restore both contain only component 0x100. The header carries version 0x1100,
  and the other components carry 0x0100.
- If the camera is on 1.0, or anything other than this build, you would be pairing a 1.1 main with
  non-matching 0x101/0x106/0x10e/0x102 components. The "restore" would not restore that state either.
- Check the camera's menu-reported firmware version is 1.1 before anything else. If it is not, install
  the official full 1.1 update first through the official channel.

### Medium

**M1. Interrupted write risk.**
- An interrupted or failed write to section 2 affects boot, not just COLOR mode.
- Section 2 (0x60280800–0x6055e800) is loaded third at boot (order 1, 7, 2, …). Its 12 initializers
  (list 0x6055e580, byte count 48 at 0x6018e19e) run at boot.
- A partially programmed block containing the hook (decoded offset 0x3902b9) or the routine (0x53e5a0)
  can therefore break startup.
- The SD client is in section 6, which loads later. No pre-main or immutable recovery loader is known
  for the E-P7; RECOVERY.md says the same for PEN-F.
- This is the same exposure as any official update, and smaller if the block-skip in H1 holds (about
  2 blocks rewritten).
- Mitigation: full battery, no card or lens activity, never interrupt.

**M2. When the patched code runs at all is not established.**
- Path: hook → selector 0x603b0252 (only caller 0x603b14f3) → param generator 0x603b1466. That
  generator has two entry wrappers, 0x603b17e6 and 0x603b1819, selected by the request subtype in
  dispatcher 0x603aaced. The dispatcher is called from job runners 0x60339870 and 0x603399d7.
- Which of these are still capture, live view, movie or RAW development is unknown.
- If live view uses this path, a fault in the routine would show up as soon as live view starts in
  COLOR mode. If the profile setting is left on COLOR, that could repeat at every boot.
- I rate a fault unlikely (see N3), but the failure would be severe.
- Mitigation:
  - Before flashing, set the camera to a non-COLOR picture mode or profile-switch position. Boot,
    check live view, then enable COLOR deliberately.
  - Confirm on stock firmware first that powering on with the front Profile Control switch in the
    non-COLOR position leaves picture mode ≠ 11. That would be a menu-free escape hatch. This is
    unverified.

**M3. Colour semantics on the E-P7 ISP are unverified.**
- What is verified: the scale (H = −1000·ui, L from fishcu's LUT), the sign, and the sector order
  r ← w = 2(r%6) + r//6 all match fishcu's PEN-F `image_parameters.s` exactly. I checked
  classic_neg rows 0, 1, 2 and 6 by hand.
- The COLOR table is byte-identical to PEN-F, and the stock hue/L fields (table +12/+16) are 0 for all
  12 entries.
- But writer 0x6034667e copies the output words verbatim to hardware descriptors. The ISP is a
  different generation.
- Likely failure: wrong or strong colour shifts in COLOR mode only, not a crash. A hang of the ISP
  pipeline from out-of-range coefficients cannot be excluded statically. The values are within
  PEN-F's physically tested range (±7000 / ±300).

### Low

**L1. Some COLOR images will not get the override. Expect inconsistent colours, not a fault.**
- The selector branches away before the picture-mode test:
  - At 0x603b025e, if request+1524 ≠ 0: it calls the alternate builder 0x603afb94 at 0x603b027c if
    ctx+60 bit 0x10000000 is set, otherwise skips.
  - At 0x603b0299 on the 0xf00d bypass.
- The alternate builder (also called from 0x603b038b) writes the same record layout from another table.
- Also, all 4 COLOR profiles get identical H/L, by design.

**L2. Test coverage gaps (static analysis closes them).**
- `ep7_verify_package.py` checks only callee-saved registers, sp and pc.
- It does not compare d0/d1/a0/a1/MDR/PSW against stock, and it uses a synthetic context and a single
  path.
- Statically, the registers at resume are identical to stock except the PSW flags, which are dead
  (see 1 below).

**L3. Minor `build.py` gaps.**
- `int()` silently truncates fractional recipe values.
- `HUE_OFF`, `RESUME` and `BUILDER` are constants. They are not re-derived from the builder bytes.
  This is acceptable because `build_package.py` pins the stock SHA.
- The FF check covers only the routine length, with no guard bytes.
- None of this affects the reviewed build.

### Notes (checked, no issue)

**1. Hook 0x603b02d9.**
- Encoding:
  - Stock `cd 8f fd f0 60` = `call 0x603b0068,[d2,d3,a2,a3],96`. The instruction boundaries are 0x603b02d3
    (`mov imm32,a0`, 6 B) → 0x603b02d9 (5 B) → 0x603b02de.
  - The new bytes `dc e7 e2 1a 00` = `jmp 0x6055e5c0` (0x603b02d9 + 0x1ae2e7). Exactly 5 bytes, so
    no dangling bytes are left.
- No branch or call of any encoding targets 0x603b02d9–0x603b02dd. I checked br8 c0–cb, f8 e8–eb,
  cc/cd d16, dc/dd d32, calls d16/d32, and abs32 at every alignment. The builder's only caller in the
  whole image is 0x603b02d9. There are no abs32 or function-pointer references to the builder or the
  selector.
- Resume point 0x603b02de: the first instruction is `mov (60,a2),d0`, then `btst 2,d0`. No flags,
  d1, a0 or a1 are read on any path before the selector's `ret [d2,d3,a2,a3],20`
  (0x603b02ed/0x603b0338/0x603b02f0→0x603b0342).

**2. MDR and return address.**
- The builder returns with `ret [d2,d3,a2,a3],96` at 0x603b0244, through the stack return address
  0x6055e5c7, not with `retf`. The `retf` at 0x603b024f belongs to 0x603b0247.
- The call sets MDR, but the builder's own `ext d3`/`div d0,d3` (0x603b013e/0x603b0140) overwrite it
  on every iteration. The routine has no call, mul, div or ext, so MDR at resume is bit-identical to
  stock.
- The source comment "keeps MDR" is harmless but moot. The selector also returns with `ret`, so it
  never reads MDR.
- The re-issued call has the same register mask and frame (`f0 60`) at the same sp. The builder reads
  stack only up to (76,sp), below its saved registers and return address, so the changed return
  address is never read.
- The routine uses no setlb/Lcc, so LIR/LAR are unaffected.

**3. Routine (independent disassembly of `routine.bin` at 0x6055e5c0) matches the listing.**
- Sequence: `call 0x603b0068,[d2,d3,a2,a3],96` (dd a8 1a e5 ff f0 60); `add -16,sp`; save d0/d1/a0/a1;
  `mov (12,a2),a0`; `add 706,a0`; `mov 0x6055e604,a1`; `mov 12,d1`; then a loop of 4× movhu, `add 4,a1`,
  `add 24,a0`, `add -1,d1`, `bne 0x6055e5e1`; restore; `add 16,sp`; `jmp 0x603b02de` (dc e0 1c e5 ff).
- The table is at 0x6055e604, 4-aligned, 0x6055e604–0x6055e634. 116 B in total.
- Stack: the extra 16 B is used after the builder's 96 B frame is released, so peak stack is
  unchanged.
- a2 is preserved by the builder's `ret` mask.
- Alignment and validity: the builder stores 32-bit words at out+688+24r+{0,4,…,20} for r = 0..11
  (two outer × six inner iterations, pointers never reset). Hue is out+706+24r (inside the word at
  +16) and L is out+710+24r (inside the word at +20).
- So **the routine writes a strict subset of the bytes the stock builder has just written through
  d1 = (12,a2)**. The pointer is re-read from the same, unchanged context. The output is necessarily
  4-aligned, or stock would fault.
- It is therefore memory-safe in every context in which the stock call is safe: still, live view,
  RAW development, Art Filter, video. It is reentrant: stack only, plus a read-only table.

**4. Code space.**
- Descriptor table 0x60027068 (9 × 12 B). Section 2 = {0x60280800, src 0x40900800, dst 0x60280800},
  loaded in place.
- End getter 0x60045786: id 2 → stub 0x600457a4 → `mov 0x6055e800,d0`.
- 0x6055e5b0–0x6055e800 is all FF in stock and inside the load. The rest of the tail stays FF in the
  patched payload.
- The only abs32 reference into 0x6055e590–0x6055e800 is the end constant at 0x600457a6. I found none
  in the uncached alias 0xA055e5xx (0x60067102 maps 0x6xxxxxxx → 0xAxxxxxxx) or other aliases. Three
  low-address hits were mid-instruction false positives. No branch targets land in the tail. The four
  br8 hits at 0x6055e59d–a9 are pointer bytes of the initializer list.
- Initializer list 0x6055e580: 48 B (12 entries) at 0x6018e19e. The loop is bounded by byte count,
  with no sentinel scan.
- Section-table users:
  - The loader 0x600457e7 reads `end − start` bytes through 0x6005bc79 → 0x600c4e80. It has no
    checksum; on error it only logs `UserSub_FlashReadErr`.
  - 0x600458d9 and 0x6004595c program region registers at 0x997000xx through 0x60058c66. This is
    region-attribute setup covering 0x600d7800–0x6143a800.
- Data reads from section 2 are normal (the COLOR table 0x6051de2c and the halfword at 0x6051e9fc), so
  the routine's table reads cannot be blocked by that region setup.
- I found **no runtime checksum, CRC or scan over loaded section bytes**. The only integrity checks
  are the container's additive sum, checked by the updater (`usr_checksum_error`), and the updater's
  flash compare. A pre-main boot-ROM check of flash cannot be excluded statically; PEN-F's identical
  method booted.

**5. Package.**
- The patched package is 26,214,400 B, exactly block 0's extent.
- Header (32 B) and trailer[0:28] are identical to stock. Only trailer[28:32] differs: dff1e402 →
  1cd6e0fe, re-validated by an independent parse.
- 113 encoded bytes differ. The 109 in the payload all map back to the two edit spans through the
  inverse scramble.
- The header has no component-count or index field, so a main-only file is structurally just stock
  block 0.
- `restore-stock.pkg.bin` == stock[0:26214400] exactly.
- Patched SHA-256 (classic_neg) `2f61cc49…e050`.

## Failure modes and recovery reachability

| Failure | How it presents | SD `DCOLYMP/E142????BIN` recovery reachable? |
|---|---|---|
| Package rejected (checksum, version, suffix, component set) | Updater error; nothing written | Yes; camera unchanged |
| Power loss or program error mid-write (M1) | Boot failure or loop if a section-2 block is torn | **Probably not.** Section-2 initializers run at boot before the section-6 SD client; no known pre-main loader |
| Routine faults (judged very unlikely, N3) | Crash or freeze only when COLOR-mode processing runs; at every boot if live view uses this path and COLOR is selected | Yes, if the camera can boot in a non-COLOR mode (M2 mitigation); otherwise uncertain |
| Wrong H/L semantics (M3) | Wrong or strong colours in COLOR mode only | Yes |
| Alternate-builder images (L1) | Some COLOR outputs show stock colours | Yes |

## Required before flashing
1. Confirm the camera reports firmware 1.1 (H2).
2. Dry-run the SD path with the exact stock restore package and confirm it is accepted and the camera
   reboots normally (H1).
3. Full battery. Set a non-COLOR picture mode or profile-switch position before installing the patch
   (M1, M2).
4. Keep the restore package on hand and get an explicit go-ahead.
