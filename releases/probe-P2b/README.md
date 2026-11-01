# probe-P2b: hook, replay and gates only, with no store

**What it tests.** This is P1 minus its one store. It has the same hook, the same replay of the stock tracker call, the TRIG1-press test, a read-only test of the section-3 flag (always 0xFF) and the v2 gates. When the gates pass it returns without writing anything. Because nothing clears the flag, the gates run (all reads) on **every** half-press.

Base: test 6, plus 2 edits:
- 0x602c805f → `jmp 0x605b7400`
- 135 B probe

Source: `patches/sd_probe/p2b.s.in`.

**When to flash.** Only if both P1 and P2 crash.

**How to test.** Card in, with no `EP7MOD` folder. Boot, then half-press several times. Do this for at least 5 power-cycles, and start one movie.

**What the result means:**
- **Crash:** the fault is in the hook, the replay or the section-3 tail itself, or in a gate read (section bits, get_tid, HLS tid, media status). Next, bisect with a replay-only probe.
- **Pass:** the hook, replay and gate reads are all fine. Since P1 and P2 crashed, any store at that point is fatal, which points to something about context or timing.

Recovery: `restore-stock.pkg.bin`.

**Emulator verification** (`tools/ep7_verify_sd_probe.py edits.json`): PASS. Each run starts at the real upstream event and is compared against stock:
- **Replay:** registers, live stack, event, tracker byte and leaf calls all equal stock.
- **No writes:** zero memory writes beyond stock in every captured region, with the section-3 tail and event manager unchanged, and zero service calls.
- **Gate runs:** the gate runs on every gated press and on no other event.
- **Mutation tests:** 4 of 4 were detected.

Offline build. No camera was contacted.
