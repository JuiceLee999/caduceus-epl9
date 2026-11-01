# probe-P1: does the section-3 RAM store crash the camera?

**What it tests.** The SD loader v2 path is cut down to the hook, the replay of the stock tracker call, the TRIG1-press test and the v2 gates. There is no malloc and no file call. After the gates pass, the probe does exactly one store: v2's own byte store `movbu 0,(0x605b7692)` into section-3 RAM. It sits at the same instruction address, 0x605b7484, and targets the same byte as test 7. Then it returns.

Base: test 6 (camera-proven), plus 2 edits:
- 0x602c805f: `call 0x602c818c` → `jmp 0x605b7400`
- 141 B probe in the section-3 FF tail

0x605b7692 is the stock erased 0xFF byte, so no edit is needed there. Source: `patches/sd_probe/p1.s.in`.

**How to test.** Card in, with no `EP7MOD` folder. Boot, then half-press several times. Do this for at least 5 power-cycles, and start one movie.

**What the result means:**
- **Crash at the first half-press:** the culprit is the store, the gate or the section-3 tail; malloc and fopen are ruled out. Flash **probe-P2** (same code, store moved to 0x622cbcc2):
  - P2 passes: the section-RAM write is confirmed as the cause.
  - P2 crashes: go to **probe-P2b**.
- **Pass, with repeated half-presses fine:** writing to section RAM is ruled out. The crash lies in malloc or fopen from HLS_EVENT (probes P3/P4).
- Note whether the camera **hangs first** or **resets instantly**.

Recovery: `restore-stock.pkg.bin`.

**Emulator verification** (`tools/ep7_verify_sd_probe.py edits.json`): PASS. Each run starts at the real upstream event and is compared against stock:
- **Replay:** registers, live stack, event, tracker byte and leaf calls all equal stock.
- **Store count:** the store runs exactly once per power-on, at 0x605b7692, on the first gated press only. It does not run during boot windows or on later presses.
- **No other writes:** no other change appears in any captured region, and there are zero service calls.
- **Mutation tests:** 5 of 5 were detected.
- **Byte match:** the probe bytes equal test 7's loader up to the store, except the branch offsets.

Offline build. No camera was contacted.
