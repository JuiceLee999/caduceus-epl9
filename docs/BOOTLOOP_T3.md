# Test 3 bootloop: root-cause analysis (offline)

Status: **static analysis only.** No camera contact, no SD-named files, nothing committed.
Input: `releases/test3-full/edits.json` (51 edits). Tests 1 and 2 (rec_limit, video_log) are proven good on the camera.
Tags: **[V]** = read from the decoded main (`tools/dis.sh`, byte scans); **[I]** = inference.

## Bottom line

No patch has a crash path that can be proven from the bytes alone. Every hook's register, stack and MDR contract has
already been emulator-verified. The ranking below therefore rests on four questions: what runs **before the first
shot**, what depends on hardware or peripheral behaviour the emulator cannot model, what is new relative to tests 1
and 2, and which hypotheses the evidence rules out.

| Rank | Suspect | Runs at boot? | Risk |
|---|---|---|---|
| 1 | **Aperture ring** (disp 0x601f9df7, parse 0x601f5ed7, AE 0x60427ae7, RAM write 0xa0210ffe) | **Yes, certainly**: every lens request from power-on, plus every AE frame of live view | **High** |
| 2 | **WB stub** (14 redirects → 0x6055e700) | **Probably**: 0x6030bb5b/6e (compact ring slot) and 0x6030eb61/77 (params builder) look like live-view and parameter paths | Medium-low |
| 3 | **MONO-colour** (0x603b02bf, 0x603b134e, 0x60353db9; code in sec 7) | Possibly: the chroma hook sits in the per-frame image-parameter stage list, but it is read-only until gated | Low-medium |
| 4 | Grain, bloom | No: they hook capture/job paths only | Low |
| 5 | Bundles v0.2 (job size, converters, H/L 0x603b02d9, table) | H/L possibly (read-only gate); the rest are capture-only | Low |
| 6 | Buttons (validator data) | Yes: the hash init reads the records | Low |

## Boot facts established [V]

- **Section loading.** The loader task is a static task entry (0x6003c4b8 → 0x60044f11). It copies sections in place
  (dst = src + 0x1F980000; size = end − start, using the full range).
  - Order: 1 (0x60044f2d), then 7 (0x60044f66), then 2–6, 8, 9, one after another in a single task.
  - Section 7 is therefore fully copied, and its constructors have run, before section 2 is copied. Section-7 code
    reached from section 2 can never be unloaded.
- **Section 7 constructors.** Right after section 7 is copied, 0x600457e7 calls 0x6018e1f2. That function runs the
  5-entry init_array at 0x61378c54–0x61378c68. Patched bytes start at 0x61378c80, so there is no overlap.
- **Boot task waits.** Waits in USRSTART2: wait(2) at 0x60190e18, wait(3)/(4) at 0x60191347/5d, wait(5) at 0x60191aab,
  wait(6) at 0x60191afb, then wait(7)/(8)/(9) at 0x60191ba2/b8/ce. wait(1) is at 0x600452a7.
- **What the 0x99700000 "region guard" is.** It is a bus-access monitor.
  - Initial setup 0x6004595c (from 0x60044b30, early init) arms channel 8 over [start(sec1), end(sec9)]. Each new
    wait(n) (0x600458af) narrows it to [start(sec n+1), end(sec9)]. wait(9) disables it (0x6005915f).
  - A hit is an NMI. All three vectors (0x60055250/c0/330) clear 0x99700000 and call 0x60059a9d. That handler prints
    `[SYS WANA] NMI_INT Hassei!` and then **spins forever** (`bra .` at 0x60059cec). A trip would therefore hang, and a
    watchdog would reset the camera: a bootloop.
  - **But stock code accesses guarded addresses all the time.** Resident section-0 code calls section 7 directly:
    0x60051299…0x600512f3 → 0x613698d0…, 0x60059d52 → 0x6136a0c4, and about 17 call32 sites in total. The section-7
    constructors also execute while section 7 is still inside the armed range.
  - So the monitor does not trap ordinary CPU accesses to section 7. **The guard is ruled out as the cause [I, strong].**
    The rule "keep hooks in sections ≤ the highest section waited for" is still good hygiene.
- **No write protection was found.** Only the boot and section code and the debug console program 0x99700000. Every
  other abs32 hit (0x6042c66e, 0x604499fe, 0x6075ee7b, 0x6103bf3e) is data. Section 1 is never inside the guard after
  wait(1), so the runtime ring write to 0xa0210ffe (section 1) is not guarded either.
- **Tails are intact at run time.**
  - Section 1: test 2's vlog hook at 0x60210c90 executed on the camera.
  - Sections 2 and 7: each loaded range ends exactly at a page boundary (0x6055e800, 0x61379000). Stock data ends at
    0x6055e5af and 0x61378c67, and each section's init_array ends before its tail.
  - Neither of those two tails has camera proof yet.
- **No interior branch targets.** A brute-force short/long branch scan into every ≤8-byte hook span of test 3 finds 3
  hits. All are mid-instruction false positives: 0x60302ff7, 0x601f9e39 and 0x601f9e68 (the latter two are inside
  `cmp imm16`).

## Per-suspect analysis

### 1. Aperture ring: High

**When it runs.**
- `disp_hook` runs for **every** lens request through the shared dispatcher 0x601f9df3, from the first lens
  handshake at power-on.
- `parse_hook` runs on every C1 80 / 81 E3 status response.
- `ae_hook` runs on every AE snapshot, i.e. every live-view frame.
- It is the only test-3 feature that is guaranteed to execute before the first shot, and the only one that changes
  what the camera **sends to an external device**.

**Failure modes.**
1. **The capability bit has unknown meaning on the E-P7 [V].** The gate is `device+0x440 & 0x80`. Stock E-P7 code
   tests 0x4, 0x20, 0x40, 0x10000, 0x20000, 0x200000, 0x400000, 0x2000000, 0x8000000 and 0x20000000 at +0x440 (30 sites
   in section 1), but **never 0x80**. Its meaning comes from the PEN-F (+0x23c) by analogy. If the bit is set for an
   Olympus/OM lens, or is not yet initialised during the first handshake, the body asks a ring-less lens for an
   option it does not implement.
2. **Parse length depends on what we requested, not on what the lens replied.** `parse_hook` consumes 2 bytes
   whenever req+21 bit 0 was set and the kind has bit 1 clear. A lens that ignores the option shifts every later
   field (APACT, DIS lists, LAF values).
   - The LAF loop counts come from the caller's stack ((27,sp)), not from the response [V, 0x601f5f3e]. So this is
     not a buffer overrun.
   - It does feed garbage zoom, focus and aperture state into lens control every poll. A lens NAK or timeout on an
     unknown option is equally plausible.
   - Either can stall the lens or AE task during startup and trigger a watchdog reset. [I]
3. **Runtime store into the loaded code image.** The store goes to 0xa0210ffe, the uncached alias of section 1. No
   protection was found and the PEN-F does the same [R].
   - The AE hook reads through the same alias, so the stale-D-cache problem does not arise.
   - Remaining risk: low, but not zero (alias assumed, not proven).
4. **`ae_hook` runs every frame, from section 7.** Its contract is verified, and the guard is ruled out. Low on its
   own.

**Discriminator (for a later on-camera test only).** The ring code engages only with a lens attached and connected,
and only when the capability bit is set. A ring-patched build that boots with the lens removed but loops with the
lens attached would confirm modes 1 and 2.

The user has already parked this feature. That is consistent with it ranking first.

### 2. WB stub: Medium-low

**When it runs.**
- Ten sites sit in the capture WB segment 0x60302c0f…0x60302fc9.
- Four sites probably run at live-view start:
  - 0x6030bb5b/6e, in 0x6030bb2d ← 0x6030ba62, which fills the "compact ring slot" (+75/+77);
  - 0x6030eb61/77, in the params builder 0x6030e9d1 ← 0x60329080.
- None has a proven boot path, but the WB of live view has to come from somewhere [I].

**Failure modes.**
- **Getter recursion: none [V].** `wb_prop` and `wb_pass` call or tail-jump the stock getter 0x6005e971, never the
  stub. Every non-WB key passes straight through.
- **Getter before the registry is ready: unlikely.** The stub calls the getter only when the site itself was about to
  read 0x84F9 or 0x9679. That means the registry is live and the same getter, CPU translation (0x6005c8cf) and context
  are already in use.
  - The new part is up to 4 extra keys: 33057, 38017, 40209 (mode 6 only), and 63153 or 63281.
  - If any of them is not readable from that core or context (the bundles design avoided the getter in image code for
    exactly this reason, V02_BUNDLES "fallback choice"), the getter faults inside a live-view callback.
- **Stack.** +16 B per site. The live-view task's stack margin is unknown.
- **Inert with the personal bundle.** The table at 0x60210900 has wb_flags = 0, so every call ends in `wb_pass`. The
  only boot-time difference is therefore the extra property reads.

### 3. MONO-colour: Low-medium

- The **chroma hook 0x603b134e** is in stage 0x603b132a. That stage is called (0x603b1508) from the stage list
  0x603b1466 (← 0x603b17ff/181a). The stage list may serve live view. The hook runs for **all** picture modes.
  - It dereferences context and request fields that stock already dereferences (context+52, context+4 → request
    +1802…).
  - It writes nothing until mode == 12, `REQ_JOB` matches and the marker 0xB2 is present. Live-view frames carry no
    marker.
- **`sel` 0x603b02bf** only replays the displaced bytes for mode ≠ 12.
- **`fg` 0x60353db9** is in the job packer, which runs at capture only.
- Its code is in section 7. Section 7 is always loaded before section 2 code runs, and the guard is ruled out. So
  placement is not a problem.
- Residual risk: only an untested live-view context with mode 12.

### 4. Grain and bloom: Low

- Grain: the work-list builder 0x6035749f and the combiner selector 0x603b5249 belong to the still-job path. The
  compact and live-view jobs use 0x6030ed1b/0x6032438a (GRAIN_PORT).
- Bloom:
  - The flag converter 0x603eab39 is reached only from the capture converters (0x603e615c, 0x603e8abd).
  - The Soft-Focus weight 0x6039fee8 is reached only from 0x603a04a7/4fc (the Soft Focus art path).
  - `bloom_flag` reads capture bytes. That runs at capture time, not boot.

### 5. Bundles v0.2: Low

- **Job size 15488 → 15512.** Allocator 0x60022700 keeps class 2 (≤16384). There are no other copies or literals.
- **Converter stubs.** They run only right after the job constructor, from the 5 capture converter calls.
- **H/L hook 0x603b02d9.** It sits in the same stage list as above, mode 11 path.
  - Before its gate it reads only (4,a2) → request, request+0/+4 and the request's own record array. Stock
    0x603b1466 already dereferences context+4 unconditionally (`movbu (1808,(context+4))`), so those pointers are
    valid in every context where the stage runs.
  - It writes only after the callback, parent-job and marker checks pass.
- Runs at boot: at most a read-only gate.

### 6. Buttons: Low

- These are data edits only (10 edits, section 2).
- **Boot consumer.** The hash init 0x602ba4cc reads the sid and pointer of all 1333 records, but not the lists.
- **List lengths.** The new lists are 23 and 16 entries (46/32 B). Stock type-5 lists go up to 112 B (56 entries)
  [V]. Any consumer buffer sized for stock already fits.
- **Field use.** `elem` (+14) is the element size (2), and the patch leaves it alone. Only `bytes` (+12) changes, and
  it is a byte count consistent with the new lists.
- **Ordering.** Settings store function **codes**, not indices (BUTTONS.md §2). Every stock code is still present, so
  a stored value cannot become invalid.
- **No other references [V].** No other record and no abs32 points into the rewritten bytes (0x604cae3c+46,
  0x604cb00e+32). The only references are the 4 rewritten pointers. Sid 48's stock list 0x604cae6c lies outside the
  overwrite.

## Bisection plan (one feature group per flash; recover with the proven SD restore)

Every step starts from the proven base B = rec_limit + video_log.

1. **B + bundles-lachlan** (this is the current `releases/test4-bundles`). Low risk. It proves the table, the job
   extension and the H/L gate.
   - Shoot one COLOR frame and check that H/L applies.
2. **Step 1 + WB.** This is the most likely boot-time path after the aperture ring.
   - If it loops: retest with the 4 live-view-candidate redirects (0x6030bb5b/6e, 0x6030eb61/77) left stock.
3. **Step 2 + MONO-colour.** Also the first camera proof that the section-7 tail survives at run time.
4. **Step 3 + grain + bloom** (= test 3 minus aperture ring and buttons).
5. **Buttons** can ride along at any step. It is independent and data-only. To keep the attribution clean, add it on a
   step that has already passed.
6. **Aperture ring** (if ever un-parked): last, alone on top of a passing build.
   - First boot it with the lens removed, then with a non-ring Olympus lens, then with a ring lens.
   - If steps 1–4 all pass, the aperture ring is the culprit by elimination.

If a step loops, that group is the culprit (or an interaction with it). Split it at the hook level: for example
bloom's two hooks separately, or WB's capture vs. live-view sites.

## Proposed fixes / hardening (for when features return)

- **Aperture ring.**
  - Gate the option bit on an explicit lens-ID whitelist of known ring lenses, not on the undefined bit 0x80.
  - Only consume the ring word when the response length shows it is present. If the frame length is not available
    at the parser, skip parsing and keep the request unmodified.
  - Move the state out of the code image into proven-free RAM, or keep it in section 1 but document the alias.
  - Ship an AE-only diagnostic variant first: no request change, ring value fixed at 0x8000. It should be
    behaviourally stock.
- **WB.**
  - Ship capture-only first (the 10 0x60302xxx sites). Add the live-view sites after a separate camera test.
  - Optionally gate the extra property reads behind the cheap table check: read `wb_flags` of *any* enabled slot
    first, so a table with all flags off never touches the getter beyond the stock call.
- **MONO-colour, bundles, grain, bloom.** No change needed for boot safety. Keep the "hook target section ≤ highest
  section waited for" rule anyway.
- **General.** Each test package should add one feature group. Test 3 added 7 groups at once.

## Answer for the next flash

- **Buttons alone (rec_limit + video_log + buttons) is safe to flash: Low risk** (data-only; analysis above).
- The current `releases/test4-bundles` (rec_limit + video_log + bundles) is also **Low risk** at boot. Its only code
  that can run before a shot is a read-only gate.
