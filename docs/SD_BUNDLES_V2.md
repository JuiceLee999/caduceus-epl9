# SD-card look loader v2 (post-boot trigger: first half-press)

Offline only. Nothing here was run on a camera, no SD-update-named file was created, and nothing was committed.
**Status: built, statically checked and emulator-verified from the upstream event (§7). Replaces v1
(`patches/sd_bundles`, dead hook, REVIEW_v04 H1-new). Not yet reviewed. Not cleared for flashing.**

[V] = read from the decoded main (SHA `5dd9af16…`) or machine-checked by `build.py` / the verifier.
[E] = shown in the emulator. [I] = inference.

## 1. What it does

Stock behaviour without the card file. On the **first shutter half-press after power-on**, if all boot
sections are loaded, the code is running in the HLS_EVENT task and a medium reports MOUNT OK, it makes **one**
attempt to read `C:\EP7MOD\BUNDLES.BIN` (v1 format, 544 B, same CRC/range rules, written by
`tools/ep7_bundles_bin.py`). A valid file replaces the 8×64 bundle table at 0x60210900 in RAM. Missing or invalid
file means no-op. It never tries again until the next power-on.

- Hook: 5 bytes at **0x602c805f**, `call 0x602c818c,[d2,d3,a2,a3],36` → `jmp sd_hook`.
- Code: 659 B at **0x605b7400–0x605b7693**, in the section-3 FF tail (claimed through 0x605b7780).
- Build: `.venv/bin/python -I patches/sd_bundles_v2/build.py --out generated/sd_bundles_v2`
- Verify: `.venv/bin/python -I tools/ep7_verify_sd_bundles_v2.py SPEC.json` (the spec must be merged with a v0.2
  bundles spec; `tools/merge_specs.py` now carries the `sd_bundles_v2` metadata).

## 2. Trigger options evaluated

| Option | Verdict | Why |
|---|---|---|
| Live mount-complete path 0x608658f6 (sec 5) | **Rejected** | It runs **during boot** whenever a card is inserted (the boot mount), which breaks "nothing new may run during boot". It is also a 4-media loop with a logger call before the site (REVIEW_v04 H2-new 3). Its task is unproven. |
| First entry to the profile / picture-mode code | **Rejected** | Coverage: a user who never opens the menu never gets the looks. The menu path also runs in the same UI event machinery as the half-press, so it has no safety advantage. Not traced further. |
| First COLOR builder run (0x603b02d9 area) | **Rejected** | It runs in the image pipeline. BOOTLOOP_T3 §3/§5 notes that the stage list may serve **live view**, so it may run at boot. Blocking it on FILECLBK would stall image processing while REC_FILE is also using FILECLBK. |
| **First shutter half-press** (appevent TRIG1) | **Chosen** | A user action, after boot by construction. It precedes every normal capture. It has a single, statically proven call path in a dedicated event task (§3). Before the gate, the hook replays one stock call and nothing else. |

## 3. Reachability: the real call path [V]

Every step is a direct call, a task-create argument or a loop branch. `check_path()` in the verifier checks each
item against the bytes.

1. **USRSTART2** boot task: `wait(6)` at 0x60191afb (sections 1–6 copied; BOOTLOOP_T3 places these waits in
   USRSTART2), then 0x60191b02 → 0x60767d20 (creates the HIGHLEVEL framework object), then 0x60191b17 →
   **0x60767db2** → 0x607688e3 (HIGHLEVEL run/init).
2. 0x607688ae: mgr = 0x6076fbed() (event-manager singleton 0x622cbc14, "OlyHfwEventManager"). 0x607688b5 stores it
   at (4,obj). 0x60768948/4b: `mov (4,a2),a0; call 0x6076fd56`.
3. **0x6076fd56 creates the task "HLS_EVENT"**: a0 = name 0x60a696f0, a1 = entry **0x6076fdb6**, prio 54, stack
   16360, through 0x60051d66. It stores the returned id at **mgr+172 = 0x622cbcc0** (`movhu d0,(a2)`; a2 = mgr+172).
   It starts the task with 0x6003071f(id). The field is −1 from the constructor (0x6076fa6a) until then, and the
   task is created only while it is < 0.
4. HLS_EVENT entry 0x6076fdb6: mgr = 0x6076fbed(); **0x6076fe04(mgr)**, an endless loop. It calls 0x60770217
   (timeout −1) at 0x6076fe12 and 0x6076feae, dispatches, and jumps back with `jmp 0x6076fe1e` at 0x6076feb7.
5. 0x60770217 (the body of the virtual 0x60770212, vtable 0x60a69794 slot 35) → 0x60770224
   `call 0x602c7f5a,[d2,d3,a2,a3],88`. It is the **only caller of 0x602c7f5a**, and 0x60770217 is called only
   from the two loop sites above. Both are xref-checked.
6. **0x602c7f5a, appevent get**: a blocking receive from the appevent queue (0x60040ce8) through 0x602c9b6a /
   0x600513e6 with timeout −1 (0x602c7faf). After its filters, events whose low16 is 0x100 or 0x101 go through
   0x602c805d/5f, `mov (12,sp),a0; call 0x602c818c` (**hook site**). (12,sp) = sp+16 is the event word.
7. 0x602c818c is `api_event_check_release_notice` (its log strings). It tracks the shutter state byte 0x61f9f1c8:
   - 0x02000100 → bit 1, 0x02010100 → clear bit 1;
   - 0x02000101 → bit 2;
   - the source-B codes 0x0204/0x0205xxxx set or clear bits 4/8 and are **rewritten** to 0x0200/0x0201xxxx;
   - an event that does not change the combined TRIG1/TRIG2 state is zeroed (swallowed).

   Low16 0x100 is TRIG1: the 0x601168ed handler logs "APPEVENT_TRIG1 STATUS" for it.

   [I] 0x02000100 is the half-press *press*: it sets the bit, and a release that arrives without a prior press
   is swallowed. Source B is probably the touch shutter or remote. Its press also loads, which is fine.

So the hook is reached at run time exactly when HLS_EVENT dequeues a shutter TRIG event. The emulator runs from
step 6 (§7).

## 4. Sections loaded at that point [V]

- The boot loader copies all sections in **one** function, one after another: 1, 7, 2, 3, 4, 5, 6, 8, 9
  (0x60044f2d…0x600451d0, all calls to 0x600457e7). `build.py` re-checks every call.
  - 0x600457e7 sets bit n−1 of 0xa272e420 only after its copy returns.
  - Section 3 is fully copied before section 5's copy starts.
- The hook site (sec 2) is reachable only from section-5 code (steps 4–5). The HLS_EVENT task is created after
  `wait(6)`. So **sections 1–6 are present whenever the hook can run**. That includes the loader (sec 3), the
  table (sec 1), the tracker (sec 2), fileif (sec 4) and the event loop (sec 5).
- Runtime guard on top of this: the loader does nothing unless `(0xa272e420 & 0x1ff) == 0x1ff`, i.e. all 9
  sections are copied and boot section loading is finished. This guard is code in section 3, and section 3 is
  already proven present.
- Placement [V]: the section-3 FF tail runs from 0x605b7180 to the load end 0x605b7800, and stock data ends at
  0x605b717f. There are no abs32 references (cached, uncached or flash-logical aliases) into
  0x605b73f0–0x605b7800. The two pinned byte-offset hits, 0x601262cb and 0x601273c9, are `divu` instruction bytes.
  Brute-force rel-branch hits into the tail are all in data. Section-3 code is executed by stock: 559 call32 sites
  target it.

## 5. Executing task and deadlock risk

**Task: HLS_EVENT** (created by 0x6076fd56; dynamic id; prio 54; 16 KB stack).
- [V] By path: steps 3–6.
- [V, runtime] Enforced: the loader calls the same get-tid service as fileif's caller classifier, 0x600317ac
  (0x60643765 uses it). It proceeds only if that call returns 0 (a task context, not −25) and the id equals
  the halfword at 0x622cbcc0 (1…0x7fff).
- If the path inference were wrong, the guard fails closed: no file call, and the attempt is not consumed.

**Blocking [V]:** fileif wrappers called from a CPU0 task other than FILECLBK send a message to FILECLBK and wait
forever (SD_BUNDLES §1). HLS_EVENT blocks for 6 round trips plus malloc/free, once per power-on. The emulator
measured 200 B of stack below the caller with stub callees.

**Deadlock analysis.** A cycle needs FILECLBK (or something it waits on) to wait on HLS_EVENT.
- [V] HLS_EVENT is not FILECLBK (16) or FILEFGND (17). The guard demands the dynamic HLS_EVENT id, and the
  emulator shows tid 16 and tid 61 are refused.
- [V] At the hook, HLS_EVENT is between "event dequeued" and "event returned". It holds no lock that is visible
  in 0x602c7f5a.
- [V] The FS library (0x60613000–0x60650000) does not call into sections 5/6 apart from a constant getter
  (SD_BUNDLES §2).
- [V] There is **one** coupling. The FS library holds the appevent queue id in one place: 0x6061a71e stores it
  into a request (+28) as a notification target. It also has notify posts with an **infinite** send timeout:
  0x6061aa93 → 0x600514b6 with d1 = −1. The OlyQe queue writer blocks when the queue is full.
- [I] Residual risk: the appevent queue fills while HLS_EVENT is blocked in our ≤6 round trips, **and**
  FILECLBK is posting to it at that moment. Then neither side can proceed.
  - The queue depth is unknown.
  - The window is the time to open and read 544 bytes, once per power-on, right after a half-press.
  - It needs a card and the file. With no file, only the fopen round trip remains.
- Consequence if it ever happened: the UI hangs at the first half-press. A battery pull restores a normally booting
  camera. Removing the file or the card disables the attempt.
- Also [I]: the first half-press's AF/AE response is delayed by the file read, once.

## 6. Guards and load-once semantics [V]/[E]

1. The hook replays the stock call on the same frame. It reads the canonical event from (16,sp) and jumps back
   to 0x602c8064, which reloads d0 from (16,sp).
   - d1/a0/a1 are dead there: they are written before being read on every path. The emulator compares all
     registers at the function's return.
2. It acts only if event == 0x02000100 **and** `sd_state` == 0xFF.
3. `sd_gate` checks, in order: section bits == 0x1ff; get_tid == 0; HLS id in 1…0x7fff; current id == HLS id; one
   of the media status words 0x61fa8fb8/c0/c8/d0 (written by 0x6077d590, [V]) == 0xF000 "MOUNT OK".
   - If any check fails, nothing is touched, there is no file call, and the next half-press tries again.
4. When all pass: `sd_state = 0` (**one attempt per power-on, whatever the outcome**), then sd_load:
   malloc(1024) → fopen("C:\EP7MOD\BUNDLES.BIN","r") → fseek END / ftell == 544 → fseek SET →
   fread(buf,1,544) == 544 → fclose → header + CRC-32 + per-byte ranges → copy 512 B → free.
   - Any failure leaves the table byte-identical.
   - The call frames equal the dominant frame of all stock call sites of each service. For get_tid that is
     `[a2],4`; the replayed tracker call is `[d2,d3,a2,a3],36`.
5. [I] Which media type is the SD slot is not known, hence "any of the four". If a non-SD medium reported 0xF000
   before the card is mounted, the single attempt would be spent on a failing fopen. The result is a no-op until
   the next power-on, not a fault.

## 7. Emulator verification (`tools/ep7_verify_sd_bundles_v2.py`)

Every run starts at the **upstream event**, not at the hook:
1. A synthetic caller executes the exact instruction of 0x60770224, `call 0x602c7f5a,[d2,d3,a2,a3],88`.
2. The real prologue of 0x602c7f5a runs.
3. At 0x602c7f6d, an injector stands in for the blocking receive and pre-filter. It puts one event pair in
   (16,sp)/(20,sp) and continues at 0x602c8045.
4. From there, everything is **real stock code** from the built payload:
   - the 0x100/0x101 gate and the hook site;
   - the real tracker 0x602c818c with its real state byte;
   - key-class handling, 0x602c815c, 0x602c88a6, 0x602c899c;
   - the function's own `ret …,88` back to the caller.

   A swallowed event loops back to 0x602c7f6d. The injector records this and returns with the same `ret`.
5. The loader, and the **real get_tid 0x600317ac** running on fixture kernel memory, run natively.
6. Stubs (ours) at the real entries:
   - the file service, with an in-memory file and hostile clobbering, reused from v1;
   - 0x602fcb69 (key filter), 0x602c96f3 and 0x602e9f1e (logged).
7. Every case also runs on the stock payload as the reference.

Results, for both `bundles-example + v2` and `test4-bundles (rec_limit + video_log + bundles-lachlan) + v2`:
**PASS overall** (`generated/sd_bundles_v2/verify_example.json`, `verify_test4.json`).

- **S static:**
  - the site is `jmp sd_hook`, and its 32 bytes either side are stock;
  - the loader bytes equal the spec, and the region is FF to the section end;
  - all service frames equal stock;
  - the spec contains no v1 edits.
- **P path:** all 14 items in §3, including the single-caller xrefs.
- **E/F, 173 one-press power-ons (12 valid, 161 reject/missing/error):**
  - a valid file replaces the table exactly; nothing else changes;
  - the call sequence and arguments are as specified, fclose runs exactly once, and free runs iff malloc did;
  - the heap outside the buffer is untouched, and the loader region changes only at `sd_state`;
  - against stock: **all registers** (d0–d3, a0–a3, sp, pc, mdr, psw, lir, lar) at return are equal, as are the
    live stack, the tracker byte, the 0xa26999xx and 0x6224xxxx RAM, the swallowed/returned outcome, and the leaf
    calls (argument, sp, return address, caller stack words).
- **E/Q, 10 power-on sequences:**
  - The boot windows each give **zero file calls, attempt not consumed, then a later press loads**:
    - sections 8/9 not yet copied (bits 0x07f);
    - HLS_EVENT not created (id −1 / 0, plus −1 with a matching id);
    - wrong task (16, 61);
    - non-task context (get_tid −25);
    - no MOUNT OK.
  - Load once: a second press with another valid file does nothing.
  - A missing file, or a rejected file, consumes the attempt.
  - Release, trig2, repeated press, a non-shutter key (0x02000102), another class (0x01000100) and a key-filter
    reject never load.
  - Source-B press 0x02040100 is canonicalised by the real tracker and loads.
  - A-press while B is held is swallowed and does not load.
- **M, 15/15 mutations detected:**
  - event compare flipped or removed, displaced call removed, jmp-back target +2;
  - section-bit, get_tid status, HLS −1, task compare and mount guards removed;
  - `sd_state` store or test removed;
  - CRC compare flipped, size check removed, range check removed, table address +1.
- **Merge check:** test3-full + v2 (53 edits) packages without overlap.

Not covered by the emulator: the real fileif/FILECLBK path and its timing, the queue receive itself, the real
key filter 0x602fcb69 (stubbed to "accept"), RAM writability of section 3 (`sd_state`) and of section 1 (the
table), and cache coherency of the table for readers on another core (same [I] as v1 §3).

## 8. Boot-safety argument

1. **Changed bytes.** The 5-byte hook and 659 B in a previously unreferenced FF tail [V].
   - Boot code never executes the tail: no references, and the tail is only reached through the hook.
2. **The hook site executes only when HLS_EVENT dequeues a shutter TRIG event** [V: the low16 0x100/0x101 gate at
   0x602c8045–0x602c805b, and the single call path].
   - During boot this happens only if the shutter (or a source-B release) is physically operated [I].
   - Without that, not one new instruction runs.
3. **For every event that does not fire** (wrong kind, swallowed, already attempted, or any guard failing),
   behaviour is equal to stock in registers, live stack and RAM [E, all cases incl. the boot windows].
4. **File I/O needs all of these:** all 9 sections copied, the HLS_EVENT task itself, a medium reporting MOUNT OK,
   a canonical half-press, and `sd_state` unset [V code, E tests].
   - It is therefore never part of power-on. It always follows a user action after section loading finished.
5. **Containment.** Any failure of the loader shows up at a half-press, not at power-on, so the camera always
   boots.
   - Remove the file (1 fopen round trip) or the card (0 file calls) and the loader is inert.
   - The SD-updater recovery used after test 3 (battery out, OK+power) is independent of it: the loader needs a
     half-press to run [I, strong].
6. **No new boot-time reads or writes.** This differs from the test-3 suspects: aperture-ring lens requests, WB
   property reads in live view, per-frame stage hooks.

## 9. Verified vs inferred

**Verified [V]/[E]:**
- the call path §3;
- the section order and the bit semantics;
- the placement is free and unreferenced;
- the HLS_EVENT creation, entry, prio and stack, and the id field at 0x622cbcc0;
- get_tid semantics as used by fileif;
- the tracker logic, emulated as real code;
- the media status addresses;
- the call frames;
- all emulator results in §7.

**Inferred [I]:**
- 0x02000100 = TRIG1 *press*, and source B = touch shutter or remote;
- 0x60051d66 returns the created task id. It is consistent with 0x6003071f(id), and the guard fails closed if
  wrong;
- FILECLBK never waits on HLS_EVENT, except the full-queue notify window (§5);
- the appevent queue depth is unknown;
- which media word is the SD card;
- RAM writability of the section-3 and section-1 copies: BOOTLOOP_T3 found no write protection, but this is not
  camera-proven;
- cache coherency of the table;
- no other task takes TRIG events from the same queue in a way that hides the first press. The second receive
  path 0x602c852d does not call the tracker; at worst the next press loads.

## 10. Before any flash (user decision; never connect without go-ahead)

1. Independent review of this document and of `patches/sd_bundles_v2/`.
2. Suggested first camera check, on top of a proven base (test 4 when it passes):
   - boot and use the camera **without** `EP7MOD/BUNDLES.BIN`; it should be stock;
   - then with a valid file: half-press once, shoot COLOR1, and compare with the flashed look;
   - then a corrupt file, which should give the flashed look.
