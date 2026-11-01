# Test 7 crash: SD loader v2 on the first half-press (offline root-cause analysis)

Offline only. No device was contacted, no `E142*`-named file was created, nothing was committed.
Inputs: `releases/test7-sdloader/edits.json` (the hook and loader bytes are identical to
`generated/sd_bundles_v2/edits.json`), the decoded main `analysis/ep7_1100/00_0100_406a0020.decoded.bin`
(base 0x60020020), `tools/dis.sh`, `tools/ep7_xref.py`, and a full linear-sweep disassembly of 0x60020020–0x6191ffe0
(scratch only).

Tags: **[V]** = read from the bytes here. **[I]** = inference. **[C]** = camera observation (from the user).

## 0. Observation [C]

- Test 7 = test 6 (camera-proven) + SD loader v2. It booted normally.
- The **first shutter half-press** crashed the camera, which restarted immediately.
- The card was mounted (DCIM present). There was no `EP7MOD` folder and no `BUNDLES.BIN`.

**What this does and does not discriminate.** The hook at 0x602c805f runs on *every* shutter TRIG event, gated or
not (§1, step 1). So the first half-press is the first time that **any** of the following ran on the camera:
- section-3 tail code;
- the gate;
- the `sd_state` store;
- malloc/fopen from HLS_EVENT.

The crash alone does not tell these apart. §4 does.

## 1. Exact execution trace: card mounted, no file [V unless marked]

The event is 0x02000100 (TRIG1 press). The task is HLS_EVENT, inside 0x602c7f5a. Let **S0** = sp of 0x602c7f5a
(its frame was opened by `call 0x602c7f5a,[d2,d3,a2,a3],88` at 0x60770224).

1. **0x602c8045–0x602c805b**: low16 0x100 passes. 0x602c805d `mov (12,sp),a0` (a0 = S0+16, the event word).
   0x602c805f `jmp 0x605b7400` (patched `dc a1 f3 2e 00`).
2. **0x605b7400 `call 0x602c818c,[d2,d3,a2,a3],36`**: the displaced tracker call, on the same frame.
   - The return address 0x605b7407 goes to (S0). In stock it would be 0x602c8064. 0x602c7f5a never reads (S0); it
     leaves with `ret [d2,d3,a2,a3],88` at 0x602c8159, which reads its own return slot at S0+88.
   - The tracker preserves d2/d3/a2/a3 through the call/ret pair. It reads and writes only (a0) = S0+16 and its
     state byte 0x61f9f1c8. That byte holds all 8 bits: the low nibble is current, the high nibble previous
     (0x602c8294–0x602c82d1).
3. 0x605b7407: `mov (16,sp),d0` → 0x02000100 (a press canonicalised by the tracker). 0x605b7411: `movbu
   (0x605b7692),d0` reads **0xFF**, the flash image value in section-3 RAM. So the code goes on to
   `call 0x605b7425 (sd_gate),[d2,d3,a2,a3],36`:
   - return address 0x605b7420 → (S0);
   - regs saved just below S0;
   - gate sp = S0−36.
4. **Section check.** 0x605b7425 `mov (0xa272e420),d0; and 511; cmp 511`. Bit n−1 is set by the loader at
   0x6004585b after each copy, so this is 0x1ff after boot.
5. **Task-id check.** a0 = sp+12 = S0−24. `call 0x600317ac,[a2],4` (get_tid):
   - return address → (S0−36), a2 saved at S0−40;
   - it reads the per-CPU kernel block, writes the **halfword** tid to (a0) = S0−24 (aligned), returns d0 = 0 (or
     −25 outside a task), `retf [a2],4` (MDR was set by the call).
   - Then `movhu (0x622cbcc0),d1` (HLS id, written by 0x6076fd95 at task creation), checks ≠ 0 and sign clear, then
     `movhu (12,sp),d0; cmp d1,d0`. This passes in HLS_EVENT.
6. **Mount-status read.** `mov (0x61fa8fb8|c0|c8|d0),d0` against 0xF000. These are aligned 32-bit RAM reads. With a
   mounted card one of them matches [I: the card was mounted].
7. **`sd_state` write.** 0x605b7483 `clr d0`, then **0x605b7484 `movbu d0,(0x605b7692)`**. This is a byte store into
   section-3 RAM through the cached alias. It is the **first store on the path to anything other than the stack**.
8. `call 0x605b7492 (sd_load),[d2,d3,a2,a3],36`: return address → (S0−36), load sp = S0−72.
9. **malloc.** `mov 1024,d0; call 0x60022782,[],4`. Size 1024 is pool class 1 (≤2048), the pool at
   [0xa1f8d800, 0xa1f98540): 44 KB, uncached addresses (free()'s range checks at 0x600227c9/d1). a0 = buffer, or 0
   → `jmp sd_out`.
10. **fopen.** a0 = 0x605b75da "C:\EP7MOD\BUNDLES.BIN" (2 mod 4), a1 = 0x605b75f0 "r". `call 0x60634fbc,[],4`.
    That function is `clr d0; call 0x60636358,[d2,d3,a2,a3],44; ret [],4`. Inside 0x60636358:
    - `mov a1,(4,sp)`, then classify the caller with 0x60643765:
      - (0x8050) = 0 (CPU0);
      - get_tid ≠ FILECLBK (0x600408f8);
      - 0x60618828(tid) = 0, because only 1 registered entry is compared;
      - so **class 1**.
    - It builds a request on the HLS_EVENT stack (path pointer, mode, 0) at sp+12…, then
      `call 0x60054b33,[d2,d3,a2,a3],72`. That is a synchronous RPC to queue (0x60040d20), the FILECLBK service:
      - it creates a reply queue (0x60051bad);
      - posts with 0x600514b6 (d1 = −1);
      - **waits** with 0x600513e6 (d1 = −1, no timeout);
      - deletes the queue (0x60051372).

      The path string is passed **by pointer**; FILECLBK reads it from 0x605b75da. Only the class-2 (other-CPU)
      path copies it.
    - Return: a0 = (12,sp) from the reply, or **a0 = 0 if the RPC itself fails** (0x60636427).
11. **Error handling.** 0x605b74b7 `mov a0,a3; cmp 0,a3; beq sd_free`. 0x605b752a `call 0x600227b4 (free),[],4`.
    0x605b7532 `ret [d2,d3,a2,a3],36` → 0x605b748f `ret …,36` → 0x605b7420 `jmp 0x602c8064` → stock continues
    with `mov (16,sp),d0`.

There is no fseek/ftell/fread/fclose and no table copy in this case.

**Stack.** The deepest point is inside the RPC wait: roughly S0−240 B of the 16 360-B HLS_EVENT stack [V frame
sizes; the emulator measured about 200 B with stub callees]. Nothing on the path writes at or above S0 except the
return-address slot (S0), and that slot is dead in 0x602c7f5a.

**Instruction set and encoding [V].** Every opcode form the gate and load use occurs in stock thousands of times:
`fa ed` (btst imm16,d1) 204×, `fc a8` 5873×, `fc 82` 6702×, `fc ad` 2802×, `dc` 6775×, `f8 bc` 19 233×. Nothing
exotic.

## 2. Ranked causes

| Rank | Cause | Verdict |
|---|---|---|
| 1 | (a) store into section-3 RAM faults | **Most likely, but the mechanism is not found** |
| 2 | (b) fopen RPC from HLS_EVENT | Possible; a hang is likelier than an instant reset |
| 3 | (e1) the section-3 tail code itself (first ever execution of that tail) | Low |
| 4 | (c) hook/replay register or stack contract | Very low (verified) |
| 5 | (d) alignment fault | Very low (verified) |

### (a) Write to section RAM

For:
- **[V] Stock never stores to any address inside the loaded image.** I extracted all 32 217 `mov/movbu/movhu
  reg,(abs32)` stores from a linear sweep of 0x60020020–0x6143a800, normalised the 0x6…/0xa… aliases, and matched
  them against 0x60020020–0x6191ffe0.
  - **0 hits.** Every stock static that is written lives at ≥0x61b2xxxx (heap pools, then .bss
    0x621caf00–0x62796888).
  - Section 0 also holds only read-only statics (for example the id table 0x60040ce8: 30+ readers, no writers).
  - So nothing in stock shows that image RAM is writable after load.
- [V] This store is the **first** non-stack side effect on the crashing path (§1, step 7). Everything before it is a
  read.
- [C] The only other build that ever wrote into image RAM was test 3 (aperture ring, store to 0xa0210ffe, section 1).
  It also failed: a bootloop, confounded by other features.

Against (no protection mechanism found):
- [V] The standard AM33 MMU/TLB control registers (0xc0000090 MMUCTR, 0xc00000a0/a4/b0/b4 xPTE*, 0xc0000098) are
  never referenced. All the abs32 hits I checked are mid-instruction false positives. None occur in components
  01/03/04 either.
  - The firmware runs code from 0x6…, with 0xa… as the uncached alias. 0x600670bc/0x60067102 convert between
    0x6…, 0xa… and 0x4…/0x8… purely arithmetically.
- [V] The only region-check hardware the firmware programs is the bus monitor 0x99700000. Its setup 0x60058c66 is
  called only from:
  - early init 0x6004595c, which arms channel 8 over [start(sec1), end(sec9)];
  - each wait(n) 0x600458af, which narrows it to [start(sec n+1), end(sec9)] (entry n of 0x60027068);
  - the debug console (0x60059981).

  wait(9) disables it (0x600458a6 → 0x6005915f → 0x60058b8d). So once wait(3) has run, section 3
  (0x6057b200–0x605b7800) is no longer in the armed range. The monitor cannot catch this store at half-press
  time.
- [V] No code other than the loader, wait() and the monitor init uses the section-end getter 0x60045786 or the
  descriptor table 0x60027068. That means no other runtime consumer of section bounds, such as a protection setup.
- [V] The NMI handler 0x60059a9d decodes system errors from (0x8044): MISSA (misalignment), UNIMP, MEM_ERROR,
  UNIMPEX. It prints them and then spins (`bra .` at 0x60059cec), so a watchdog has to reset the camera. MEM_ERROR
  exists as a cause, but its trigger conditions are not visible in this firmware.
- [I] A write protect could still be set outside this image, by the boot ROM or by an SDRAM-controller window
  programmed by another component. A static scan cannot exclude that.

Cache [V]:
- the store goes through the cached alias, and the line 0x605b7680–0x605b769f holds only range-table data (code
  ends at 0x605b75d9), so there is no I/D aliasing;
- the section was copied through the uncached alias (dst = 0x60067102(0x6057b200) = 0xa057b200), so no stale
  D-lines exist.

**Conclusion.** (a) stays the leading suspect because it is the only *new kind* of operation on the path, and stock
never does it. The fault mechanism is **unproven**. §4 test P1 is the single decisive experiment.

### (b) fopen or another service in HLS_EVENT

- [V] The call frames match stock (`[],4` for malloc/free/fopen, unanimous across 744/764/76 sites).
- [V] Arguments are valid: a NUL-terminated path in readable RAM, and mode "r".
- [V] The missing-file return (a0 = 0) is handled. The RPC failure path also returns 0.
- [V] The string helpers the FS uses are byte-wise (strlen 0x60022fd7/0x600daed9, strcpy 0x60022f4b,
  strncpy 0x600daeef). So the 2-mod-4 path address cannot fault.
- [V] The RPC is the generic class-1 path that every non-FILECLBK CPU0 task uses. There is no caller-task check
  beyond the classifier.
- Risks:
  - [I] The wait is unbounded, so a stall gives a **hang**: HLS_EVENT is the only consumer of appevent queue 6
    (REVIEW_SD_V2 M1). A hang only resets if a watchdog bites, which does not fit "restarted immediately" as well
    as an exception does.
  - [I] malloc(1024) draws from a 44-KB class-1 pool. Whether 0x60022a61 fails or blocks when the pool is empty
    was not traced. The code handles 0.
  - [I] Unknown FILECLBK-side behaviour for a nonexistent directory (`EP7MOD`), for example an error-notify post to
    queue 6 with infinite timeout (0x6061aa93). That would also be a hang, not a reset.
- Verdict: possible, rank 2.

### (e1) Section-3 tail execution

- [V] The tail 0x605b7400–0x605b7693 lies inside section 3's copy range [0x6057b200, 0x605b7800):
  - end getter case 3 → `mov 0x605b7800` at 0x600457d4;
  - table entry 2 = (0x6057b200, src 0x40bfb200, dst 0x6057b200);
  - size = end − start, so it is copied.
- [V] Nothing references 0x605b6e00–0x605b7800 except 4 mid-instruction false positives. Stock data before the tail
  is a high-entropy blob ending at 0x605b717f.
- [C/I] Section-1 and section-2 tails have executed on the camera (vlog hook, WB stub). Section 3 has not.
- Verdict: low.

### (c) Hook and replay contract

- [V] The replayed instruction is byte-for-byte the stock call (same target, mask and frame 36, same sp, a0 = S0+16).
- [V] d2/d3/a2/a3 are restored by every `ret`. d0 is reloaded at 0x602c8064. d1/a0/a1 are dead there. (12,sp) is
  untouched.
- [V] MDR differs from stock at 0x602c8064 (0x605b7407 or a loader address, instead of 0x602c8064). But 0x602c7f5a
  makes further calls (0x602fcb69, 0x602c96f3, …), each of which resets MDR, and it returns with `ret`, not `retf`.
- [V] LIR/LAR are untouched by the loader. Callees that use `setlb` are stock code, used the same way stock uses
  them.
- [E] (SD_BUNDLES_V2 §7) The emulator compared all registers at the function return against stock.
- Verdict: very low.

### (d) Alignment

- [V] Every word or halfword access on the path is aligned:
  - the media words (0x…b8/c0/c8/d0);
  - the tid halfword at S0−24 (S0 is 4-aligned, since frames 88/36 are multiples of 4);
  - the stack saves;
  - the `sd_state` access, which is a byte.
- [V] The path string is byte-accessed (see (b)).
- Verdict: very low.

### (e2) Other

- The test-7 base includes per-profile WB (test 6). REVIEW_SD_V2 asked for the loader to go on the test-5 base.
  That matters for M4 (the SD file enabling WB), not for this crash: no file was present, so no table write
  happened.
- Deadlock (REVIEW_SD_V2 M1) gives a hang, not a reset [I].

## 3. Fix: no runtime writes to flash-loaded section RAM

### 3.1 Loader state → padding in the HLS event-manager object (proven-writable cache line)

**Address: 0x622cbcc2, 2 bytes.** This is struct padding inside the event-manager singleton 0x622cbc14
("OlyHfwEventManager", returned by 0x6076fbed). The same object holds the HLS tid that the loader already reads.

Evidence [V]:
- **Layout.** The constructor 0x6076fa1f:
  - writes vtable +0;
  - initialises 5 list heads at +112/+124/+136/+148/+160 (12 B each, ending at +172);
  - writes `movhu d0,(172,a2)` (tid, −1) and `mov d0,(176,a2)` (word, 0).

  So +174..+175 is alignment padding between a u16 and a u32. The next static object starts at 0x622cbcc8: its
  bytes are written one by one by 0x607707b1…df, and 0x622cbcd0 is a separate imm base. The object is 0xb4 bytes.
- **Never accessed.** No abs32 reference anywhere touches 0x622cbcc2/3. Within this class, +172 is accessed only as
  a halfword: 0x6076fa6a, 0x6076fd5b, 0x6076fd95, 0x6076fd9c. The 32-bit `(172,aN)`/`(176,aN)` accesses at
  0x60776bbb etc. belong to another class (vtable 0x60a7f32c, its own allocator).
- **Writable at runtime, by stock, in the same 32-byte cache line** 0x622cbcc0–0x622cbcdf:
  - 0x622cbcc0 (tid, `movhu` at task creation 0x6076fd95);
  - 0x622cbcc4 (+176);
  - 0x622cbcc8–cf (0x607707b1…).
- **Initial value.** The object is in the .bss range 0x621caf00–0x62796888 that boot clears via
  0x6002046d(0x621caf00, 0xa2796888) (call at 0x60020074). [I] 0x6002046d is a hardware fill-to-zero (it programs
  0x9c100000). The constructor does not write the padding, so it is **0 at power-on** [I, strong].

Semantics change (0 instead of 0xFF):
- `0x0000` = not attempted;
- non-zero = attempted (or a table handle, see §3.2).

Code change in `sd_hook`/`sd_go`: replace `movbu (sd_state)` / `movbu d0,(sd_state)` with `movhu (0x622cbcc2)`,
test == 0, and `movhu dX,(0x622cbcc2)`. Being 2-aligned, the halfword access is legal.

There are no other writes. The hook already depends on this object's tid field, so it adds no new dependency.

Rejected alternatives [V]:
- the tracker byte 0x61f9f1c8: all 8 bits are used;
- every 4-byte "gap" between stock .bss scalars: all lie within 0x400–0x1000 of an imm/data base pointer (struct or
  array interiors), so unusedness cannot be proven;
- a word at the image end (0x6191ffe0–0x61b20fe0): unreferenced but unexplained (DMA/other-CPU use cannot be
  excluded).

### 3.2 Bundle-table override through an indirection (no section-1 writes)

The 16-bit slot cannot hold a 32-bit pointer, but it can hold a **pool offset**:
- On a valid file, keep the malloc(1024) buffer (do not free it). It comes from class-1 pool
  [0xa1f8d800, 0xa1f98540), whose span is 0xad40 < 0xffff [V, free() range checks].
- Store `h = buf − 0xa1f8d800 + 1` (1…0xad40).
- Encoding of 0x622cbcc2:
  - **0** = not attempted;
  - **0xFFFF** = attempted, use the flashed table;
  - **1…0xad40** = loaded, table at `0xa1f8d800 + h − 1 + 32`.
- Before storing, verify that `buf` lies inside the pool (and malloc ≠ 0). Otherwise free it and store 0xFFFF.

The buffer is **uncached** (0xa1…), so readers on any core see the new table without cache maintenance (this fixes
REVIEW_SD_V2 M3 coherency too).

Readers: replace each `mov 0x60210900,aN` with a call to a new helper `tbl_base` (section-1 code, about 20 B), which
returns aN = the override if 1 ≤ h ≤ 0xad40, else 0x60210900. The sites are:
- `patches/bundles/bundles.s.in:125` (H/L);
- `patches/wb/wb_get.s.in:71`;
- `patches/mono_colour/mono_colour.s.in:60`;
- `patches/bloom/bloom.s.in:53,109`;
- `patches/grain/color_grain.s.in:43` (`{table_grain}` = table+24, which becomes base+24).

Each reader's register and stack contract changes, so each needs the emulator check again. The converter stubs
read the table through the H/L code; check this when editing.

Costs and risks:
- [I] One class-1 block (≤2 KB of 44 KB) is leaked per power-on, and only when a valid file loads. Pool headroom
  under stock load is unknown.
- Fallback if headroom is a concern: allocate from class 2 ([0xa1dd8d40, 0xa1e85800), span 0xacac0) and store
  `(buf − base) >> 4`. This works only if class-2 blocks are 16-aligned, which is not yet verified.

Minimal interim option: ship 3.1 only, and make a valid file a no-op (log-free) until 3.2 is built and verified.
The test plan below does not need 3.2.

## 4. Camera test plan (one flash each, test-6 base, card in, no `EP7MOD` unless stated)

Each probe changes only the loader routine, never the hook site. Any probe fails at a half-press, not at boot, and
recovery is the proven SD restore.

| Probe | Loader body after the tracker replay and the event/state test | Interpretation |
|---|---|---|
| **P1** | Full gate + **`movbu 0,(0x605b7692)` (section-3 store)**, then return. No malloc, no fopen. | **Crash → the store, the gate or the tail.** Go to P2. **No crash** (and second, third half-press fine) → (a) is ruled out. Skip to P3. |
| **P2** (if P1 crashes) | Same as P1, but the store goes to **0x622cbcc2** (§3.1) | **Pass → (a) confirmed** and the new state location is camera-proven. Crash → the gate or tail: flash **P2b** = tracker replay + `jmp` back only, no gate. P2b crashes → the tail or hook (e1/c). P2b passes → a gate read (bisect the media/tid reads). |
| **P3** | State at 0x622cbcc2 + gate + malloc(1024)/free, no fopen | Crash → malloc in HLS_EVENT |
| **P4** | P3 + fopen("C:\EP7MOD\BUNDLES.BIN") (missing) + free | Crash or hang → fileif RPC from HLS_EVENT (b) |
| **P5** | Full loader with §3.1 (+ §3.2, or file loading disabled), then: no file → bad file → valid file | Release candidate |

Notes:
- P1 is the decisive probe. If budget allows only one flash, flash P1.
- Repeat each probe for at least 5 power-cycles × several half-presses, plus one movie start, before calling it a
  pass.
- If a probe crashes, note whether the camera **hangs first** (watchdog after a delay) or **resets instantly**. A
  hang suggests the NMI spin or an RPC deadlock; an instant reset suggests an exception or reboot path.

## 5. Verified vs inferred (summary)

**Verified:**
- the trace in §1, including frames, the RPC mechanism, the NULL handling and byte-wise strings;
- zero stock abs32 stores into image RAM;
- no MMU register use;
- bus-monitor scope (sec 3 is unarmed after wait(3), everything is off after wait(9));
- the section-3 copy range covers the tail;
- the encodings are stock-common;
- the event-manager layout and the padding being unused in direct references;
- the pool ranges.

**Inferred:**
- that a section-RAM write can fault at all (mechanism unknown);
- .bss zero-fill semantics of 0x6002046d;
- FILECLBK behaviour on a missing directory;
- malloc behaviour on pool exhaustion;
- that no memcpy or bulk access touches the event-manager padding;
- class-1 pool headroom.
