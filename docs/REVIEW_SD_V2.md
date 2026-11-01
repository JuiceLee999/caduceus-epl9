# Independent review: SD look loader v2 (`patches/sd_bundles_v2`)

Reviewer: independent and adversarial, offline only. No device was contacted, no `E142*`-named file was created,
nothing was committed. This file is the only file written in the repo. Scratch rebuild:
`/tmp/claude-1000/-mnt-Storage-Projects---software-Firmware-Olympus-E-P7/ca7a5b2b-a0cb-49f7-8a33-fbf59936fbd5/scratchpad/sdv2`.

Method: the hook, the 659-B routine and every stock function it touches were disassembled from the decoded main
(`tools/dis.sh`, base 0x60020020). Callers were found with `tools/ep7_xref.py` and my own byte scans. The author's
docs (SD_BUNDLES_V2.md) served only as a map. [V] = verified here from bytes. [I] = inference.

## Verdict

**No blocker. OK for a camera test**, under these conditions:
- It goes in as **its own step on the proven test-5 base** (rec_limit + video_log + bundles + grain + bloom). It
  must not ride along with the per-profile WB of test 6.
- The test follows the staged procedure in §Test plan. The first step (card in, **no** BUNDLES.BIN, half-press)
  is the probe for H1.

Any failure appears at the first half-press, not at boot. The loader cannot execute before HLS_EVENT dequeues a
shutter event (§1). The SD updater runs at power-on, before any half-press, so recovery is unaffected.

## Ranked findings

### High

**H1. Runtime stores into loaded section RAM have no stock precedent and no camera proof. The `sd_state` store
happens with or without the file.**
- `sd_go` writes `movbu d0,(0x605b7692)` (section 3, cached alias) **before** `fopen`. It does so on the first
  half-press of every power-on in which a medium reports MOUNT OK [V, listing 0x605b7484]. The table copy then
  writes 512 B to 0x60210900 (section 1, cached alias).
- I scanned for every `mov/movbu/movhu reg,(abs32)` store (fc 80–8f) that targets sections 1, 2, 3, 6 or 7, in both
  the cached and uncached aliases.
  - There are **no stock stores into section 1 or 3** at all. The 6 hits elsewhere are mid-instruction or data
    false positives.
  - Stock keeps its writable data in 0x61f9…/0x6224… RAM, outside the loaded sections. So nothing shows that
    section RAM is writable after load.
  - The absence of a write-protect mechanism (BOOTLOOP_T3) is negative evidence only.
- No camera-proven patch stores into section RAM. Tests 1, 2, 4 and 5 store only into stack or job memory
  [V, grep of the video_log/bundles/grain/bloom/wb sources].
  - The only design that ever did is the aperture ring (0xa0210ffe). It was in the test-3 bootloop. That is
    confounded and does not implicate this loader, but it also proves nothing.
- If section RAM were write-protected, the camera would fault at the first half-press of **every** session with a
  card inserted, whether or not EP7MOD/BUNDLES.BIN exists.
  - That is not a bootloop: the camera boots, then dies on the half-press.
  - Recovery: the SD updater (boot time), or use without a card.
- Not a blocker, because the planned "no file first" step exercises exactly this store in isolation, and recovery
  is proven. Record it as the first thing the test answers.
- If it fails, move `sd_state` and the write path off section RAM.

### Medium

**M1. Blocking is unbounded, and a deadlock path exists but is narrow.** [V]/[I]
- **Unbounded wait [V].** fileif classifies the caller in 0x60643765:
  - (0x8050) ≠ 0 → 2;
  - tid == FILECLBK (0x600408f8) → 0;
  - 0x60618828(tid) ≠ 0 → 0;
  - otherwise → 1, the message path. It waits for FILECLBK's reply with timeout −1 (SD_BUNDLES §1).

  HLS_EVENT therefore sleeps until FILECLBK answers each of its 6 calls.
- **The UI freezes while it waits.** HLS_EVENT is the only consumer of appevent queue id 6 (static id table at
  0x60040ce8). So:
  - while it waits, no key or UI event is dispatched;
  - the half-press that triggered the load is handled only afterwards (AF/AE starts late);
  - other posters block if they use infinite-timeout sends (0x600514b6 with d1 = −1) once the queue fills.
- **Deadlock path [V for the post, I for the trigger].** The FS library stores queue id 6 as a request's notify
  target (0x6061a71e, +28). It posts through 0x6061aace/0x6061aaeb → 0x6061aa93 → **0x600514b6 with d1 = −1**
  (0x6061aac1).
  - If FILECLBK reaches that post while queue 6 is full and HLS_EVENT is inside our call, both sides wait forever.
  - The notifications look media-change related (a 2-entry message table at 0x607084bc/c4) [I].
  - So the realistic trigger is a card event, or a burst of queued events, during the ~6 round trips.
- **Other unknowns.** The queue depth, and whether FILECLBK calls registered app callbacks indirectly (a static
  xref cannot see function-pointer calls), remain unknown.
- **Missing card:** the loader is inert. No media word reads 0xF000, so there are zero file calls and the attempt
  is not consumed.
  - The words are written only by 0x6077d590.
  - 0xF000 comes only from the 4-media loop at 0x608658f6.
  - 0x6093a318/68 write only 0 or 0x1001 for types 4 and 8 [V].
- **Slow card or FILECLBK busy** (DCF scan right after boot, or a movie being written): the camera stalls, then
  recovers. There is no hang unless FILECLBK itself stalls.
- **Card pulled mid-read:** the result depends on FILECLBK returning an error, which is [I]. The status word may stay
  0xF000 until the media manager updates it.
- **Consequence of a real hang:** a battery pull. `sd_state` lives in RAM, so the next power-on retries. If the cause
  is deterministic, it repeats at each first half-press until the file or card is removed (needs a PC to delete the
  file).
- Acceptable for a supervised test. Don't half-press during card insertion or removal.

**M2. The doc is wrong: a press that the key filter rejects still loads.**
- `sd_hook` acts right after the tracker and **before** the stock key filter 0x602fcb69 (0x602c8066–0x602c807f) and
  before the remaining class handling [V, 0x602c8064 onward].
- The verifier's own output confirms it: `verify_test4.json` results[4] rows[7], step "press, key filter rejects",
  ends with `sd_state = 0`, i.e. the attempt is consumed.
- SD_BUNDLES_V2 §7 E/Q says "a key-filter reject never load[s]". That is incorrect.
- Effect: the load can fire in UI states where stock ignores the shutter (menus, playback, possibly movie recording
  or USB/remote modes).
- No new safety mechanism is involved; the context is still the HLS_EVENT task. But file I/O can then overlap
  workloads the authors did not consider (see M4/L1).
- Fix the doc. Optionally also gate on the key-filter result: hook after 0x602c807f instead, or call 0x602fcb69
  yourself.

**M3. Concurrent table readers: possible torn update, no cache maintenance.** [V]/[I]
- **The copy [V].** It is a byte loop (`sd_copy`) of 512 B through the cached alias 0x60210900. It takes no lock and
  does no D-cache write-back.
- **Same-core readers [I].** HLS_EVENT (prio 54) can be preempted mid-copy. The readers (v0.2 H/L and converters,
  WB stub, grain, bloom; all CPU code, no DMA found) can then see some old and some new slot bytes.
- **Why it is safe anyway.** Every byte is range-validated before the copy, and each reader range-checks its own
  bytes. The worst case is a valid but mixed parameter set for one frame or shot.
- **Other-core readers.** fileif's (0x8050) classifier shows that code runs on more than one CPU. A reader there
  could keep stale lines, so the flashed look would persist. That is functional, not a safety issue.
- **Cache-line layout [V].** The table (0x60210900–0x60210aff) does not share a cache line with code (0x60210b00 is
  256-aligned). The `sd_state` line 0x605b7680–0x605b769f holds only range-table data: code ends at 0x605b75d9. So
  there is no I/D aliasing.
- Recommended (not required for the test): copy into the table, then clean the D-cache range, or perform the copy
  only on CPU0 readers' terms. Document the coherency [I].

**M4. The SD file can switch on features the flashed table leaves off.**
- The loader accepts any in-range value. For example:
  - `wb_flags = 1` on any of the 8 slots, MONO included;
  - grain 1–3 or bloom strength 1–5 on other slots;
  - `colour = 1`.
- Per-profile WB is **not camera-proven** (test 6 is pending). A v2 test in a WB build would therefore make the SD
  file a second, untested way to enable WB.
- Keep v2 out of the WB build for its first test. The first file should be byte-identical to the flashed table
  except for one visible hue or light change on one COLOR slot that already uses proven features.

### Low

**L1. Remote and tethered shutter can trigger the load.** [V]/[I]
- The source-B codes 0x02040100/0x02040101 are posted from 0x60cbfd57/6c/84 (section 6, next to the PTP/remote
  code), and the tracker canonicalises them.
- So a remote half-press (Wi-Fi app, or USB tethered capture) also performs the load, while FILECLBK may be busy
  with transfers. Delay only [I].

**L2. Movie started with REC before any half-press.** The first half-press during recording runs 6 FS requests in
the middle of the movie stream. This combination has never been run; the worst plausible outcome is a "card too
slow" stop [I]. Avoid it in the test.

**L3. The section-3 tail is executed for the first time on camera.**
- [V] for these: no abs32 references or branches into 0x605b73f0–0x605b7800 (the build re-checks them, and my
  rebuild is byte-identical); FF in flash; the section loads in place to 0x605b7800.
- Not shown: that nothing uses those padding bytes as runtime scratch. Section 1's tail has camera proof; section
  3's does not. If they were overwritten, the fault would show at a half-press, not at boot.

**L4. The vtable slot of 0x60770212** (0x60a69820) permits indirect calls into the appevent getter from other code.
The task-id guard makes any such call fail closed (no file call, attempt not consumed). [V]

## What was verified and holds [V]

1. **Hook site.**
   - 0x602c805f: `cd 2d 01 f0 24` = `call 0x602c818c,[d2,d3,a2,a3],36`. It is replaced by the 5-byte `dc` jmp32 to
     0x605b7400.
   - 0x602c805d (`mov (12,sp),a0`) is untouched, so the tracker still gets a0 = sp+16.
   - It is reachable only behind the low16 0x100/0x101 tests at 0x602c8045–0x602c805b.
   - It is inside 0x602c7f5a, whose only caller is 0x60770224 (xref). That caller is reached from the HLS_EVENT loop
     0x6076fe12/0x6076feae. HLS_EVENT is created at 0x6076fd8e (entry 0x6076fdb6, prio 54, stack 16360, tid stored
     at mgr+172).
   - There is a second event source into the same gate: the pending-event peek at 0x602c7f77 → 0x602c803f. It runs
     in the same task, so this is fine.
   - So the hook runs only when this task handles a shutter TRIG event, not on every event and not by itself at
     boot. Before the gate it adds one compare and one byte load per shutter event, and after the attempt one
     compare.
2. **Frame and return path.**
   - `sd_hook` replays the call on the same frame and does not move sp. It then jumps to 0x602c8064, which reloads
     d0 from (16,sp).
   - d2/d3/a2/a3 are preserved by every callee. d1/a0/a1 at 0x602c8064 are already arbitrary in stock (they depend
     on the path and are clobbered by the tracker).
   - (12,sp) (the sp+16 pointer, reused on the swallow loop) is never written by our code.
   - The return-address slot (0,sp) is not read by 0x602c7f5a.
   - The function returns with `ret`, not `retf`, so the changed MDR does not matter.
3. **Call encodings.** Every service call matches the **unanimous** encoding of all its stock call sites:

   | Service | Encoding | Stock call sites |
   |---|---|---|
   | malloc | `[],4` | 744 |
   | free | `[],4` | 764 |
   | fopen | `[],4` | 76 |
   | fclose | `[d2,a2,a3],16` | 145 |
   | fseek | `[d2,d3,a2,a3],20` | 37 |
   | ftell | `[d2,a2,a3],16` | 10 |
   | fread | `[d2,d3,a2,a3],24` | 49 |
   | get_tid | `[a2],4` | 73 |
   | replayed tracker call | `[d2,d3,a2,a3],36` | 1 |

   get_tid ends in `retf [a2],4`, and `call` sets MDR, so that is correct.
4. **Gating.**
   - The section bits are read through the uncached alias 0xa272e420, and the code requires `& 0x1ff == 0x1ff`.
   - get_tid 0x600317ac returns −25 in non-task contexts, otherwise 0 and the per-CPU tid.
   - The HLS tid halfword is checked against 0 and the sign bit, then compared.
   - One of the 4 media words must equal 0xF000.
   - Load-once works: `sd_state` is 0xFF from the flash image on every power-on, is set to 0 only after all guards
     pass, and is tested before the gate.
5. **Parsing.**
   - malloc(1024) is checked for 0.
   - fopen is checked.
   - fseek(END), ftell == 544 **exactly**, fseek(SET).
   - fread(buf,1,544) is compared with 544. The 544 B fit the 1024-B buffer.
   - fclose runs exactly once on every path after a successful fopen. free runs iff malloc succeeded.
   - The header bytes 0–15 and 20–31 must equal the template, including the 4-byte SHA prefix of the stock main.
   - The CRC is reflected CRC-32 (0xEDB88320, init −1, final NOT) over bytes 0–15 and 20–543, equal to
     `zlib.crc32`. The stored CRC is compared byte by byte.
   - The range check is signed `v − lo` against an unsigned span over all 512 bytes using slot offset & 63, so values
     below lo wrap high and are rejected. The ranges match `layout.json` (all 12 fields; unclaimed bytes must be 0).
   - No string from the file is ever parsed, so NUL handling does not arise. The path is a fixed `.asciz`.
   - Stack use is small against HLS_EVENT's 16 KB.
6. **Reproducibility.** A rebuild from source gives a byte-identical `routine.bin` and `edits.json`. The loader is
   not in any `releases/*/edits.json` yet.

## Test plan (when the user gives the go-ahead)

Base: the proven test-5 package + v2 only. Before each step: full battery, card formatted in camera, no movie
recording, no USB or Wi-Fi.

1. **Card in, no EP7MOD folder.** Boot, wait for the card to be ready, half-press, shoot.
   - This exercises the `sd_state` section-RAM store and one `fopen` (H1, M1).
   - Expect stock behaviour.
2. **Valid file** (= flashed table + one visible hue/light change on one COLOR slot). Power-cycle, wait about 5 s,
   half-press once, then shoot that COLOR slot.
   - Expect the new look, and a brief first-press lag at most.
3. **Corrupt file** (bad CRC). Expect the flashed look.
4. **Recovery if anything hangs or faults:** a battery pull. Then delete the file on a PC, or use the SD updater
   (boot time, independent of the loader).
