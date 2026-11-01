# probe-P2: is the store target the problem?

**What it tests.** The SD loader v2 path is cut down to the hook, the replay of the stock tracker call, the TRIG1-press test and the v2 gates. There is no malloc and no file call. After the gates pass, the probe does exactly one store: halfword `0xFFFF` to **0x622cbcc2**. That address is unused padding (+174) in the HLS event-manager object 0x622cbc14 in .bss. Nothing is written to section RAM. This is the proposed fix location from docs/SD_V2_CRASH.md §3.1.

Base: test 6 (camera-proven), plus 2 edits:
- 0x602c805f: `call 0x602c818c` → `jmp 0x605b7400`
- 146 B probe in the section-3 FF tail at 0x605b7400

Source: `patches/sd_probe/p2.s.in`. Build: `patches/sd_probe/build.py --probe P2`.

**How to test.** Card in, with no `EP7MOD` folder. Boot, then half-press several times. Do this for at least 5 power-cycles, and start one movie.

**What the result means:**
- **Pass (no crash):** the hook, replay, gates and this new state location all work on the camera. Combined with a P1 crash, that confirms cause (a): the write into section-3 RAM is what crashed test 7. 0x622cbcc2 is then camera-proven for the fixed loader.
- **Crash at the first half-press:** the store target is not the culprit. The fault is in the gate, the section-3 tail or the hook. Flash **probe-P2b** next; it is the same as P1 with no store at all.
- Note whether the camera **hangs first** (watchdog after a delay) or **resets instantly**.

Recovery: `restore-stock.pkg.bin`, the proven SD restore.

**Emulator verification** (`tools/ep7_verify_sd_probe.py edits.json`): PASS. Each run starts at the real upstream event (HLS_EVENT → appevent get 0x602c7f5a → real tracker → real get_tid) and is compared against stock:
- **Replay:** all registers, the live stack, the event returned or swallowed, the tracker byte and the leaf calls all equal stock.
- **Store count:** the store runs exactly once per power-on, on the first gated press, at 0x622cbcc2. It does not run during boot windows (sections not copied, HLS_EVENT not created, wrong task, no medium) or on later presses.
- **No other writes:** every other captured region (section-3 tail, event manager, guards, kernel, heap, table, app RAM) is identical to stock, and there are zero service calls.
- **Mutation tests:** 5 of 5 were detected.

**Static checks on 0x622cbcc2** (re-derived in `build.py pad_evidence()`):
- No abs32 word anywhere equals 0x[6a]22cbcc0–7.
- It sits inside the object built by ctor 0x6076fa1f (vtable 0x60a69794; it writes u16 +172 and u32 +176, so +174 is padding).
- Stock writes the same cache line at runtime: the tid via mgr+172 at 0x6076fd95, and 0x622cbcc8–cf at 0x607707b1.
- It is in .bss, which is cleared at boot (0x6002046d), so it is 0 at power-on.
- All 36 class methods, and all 64 getter-call sites, touch +172–175 only as `movhu (172,aN)`.
- Inferred, not proven: no unrelated memcpy or memset touches the padding.

Offline build. No camera was contacted. The package names are deliberately not SD-loadable.
