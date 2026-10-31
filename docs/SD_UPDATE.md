# E-P7 1.1 SD / USB firmware-update path

Scope: offline static analysis of the decoded E-P7 1.1 main program
(`analysis/ep7_1100/00_0100_406a0020.decoded.bin`, SHA-256 `5dd9af16…6190`, CPU base 0x60020020),
plus native emulator runs of the update validator/writer. No camera or device was contacted, and no
file with an SD-update name was created.

Tools added (our own code):
- `tools/ep7_xref.py ADDR…`: brute-force xref scan. It finds abs32 values, call/calls/jmp rel16/rel32
  and (with `--short`) rel8 branches at every byte offset.
- `tools/ep7_sd_update_probe.py`: runs the native validator 0x60c964c1 in fishcu's MN103 engine on
  synthetic `OE` containers held only in emulator RAM. Flash writes are stubbed and logged. It also
  runs the native suffix parser. Current result: **19/19 PASS**.

Notation:
- **[V]** verified: from disassembly and/or a native emulator run, with the addresses given.
- **[I]** inference: plausible, but not proven.

Section ranges (from table 0x60027068 and end getter 0x60045786, ids 1-based):

| Section | Range |
|---|---|
| base (resident) | 0x60020020–0x600d7800 |
| 1 | 0x600d7800–0x60211000 |
| 2 | 0x60280800–0x6055e800 |
| 3 | 0x6057b200–0x605b7800 |
| 4 | 0x605baa00–0x60748000 |
| 5 | 0x6075a800–0x60b9e000 |
| 6 | 0x60ba7000–0x61243000 |
| 7 | 0x612c7000–0x61379000 |
| 9 | 0x613c1000–0x6143a800 |

Section 8 is empty.

---

## 0. Correction to `docs/REVIEW_fixed_hl.md` (H1 caveat)

**[V]** The updater does **not** skip 1 MiB blocks that already match flash. The constant 0x100000 at
0x60c971ea is the **BOOT component-kind bit** (set at 0x60c965de for header kind byte 0x10). It is not
a block size.

The writer wrapper 0x60c971e5 works like this:
- **BOOT component only:** it reads the whole destination into 0xaf90e600 (0x6002144e) and runs memcmp
  (0x60022f89). If the two are equal, it logs `same result of the comparison` and skips the write.
- **Every other component, including main/USR (kind 0x100):** it goes straight to the flash writer
  0x600c4f35 for the **whole component**.

Emulator: a main-only package produces exactly one write, of `len+64` bytes, at the header address.
So a stock-on-stock "restore" **re-erases and reprograms the entire 25 MiB main**. It is not a
near-no-op.

---

## 1. How the SD updater is started

### Verified

**[V] Task identity.** The 11-byte pattern `E142????BIN` belongs to task **88 (0x58) `FIRMUP_CLI`**:
- Name table record `FIRMUP_CLI` + id 0x58 at 0x613ffb30.
- Descriptor at 0x60039370: `{id 0x58, entry 0x60c95bab, prio 45, stack 0x800}`. This has the same
  shape as PEN-F task 95 (prio 45, 2048 B).
- The shared service is task **18 (0x12) `FIRMUP_SRV`**, entry 0x60c96030 (descriptor 0x60038bc8).
- The LED task is 116 (0x74) `FIRMUP_LED`, entry 0x601e748a.

**[V] What the client does** (0x60c95bab):
1. `0x60c974c0(0)`, which writes controller register 0x98e0008c and issues command 0x20041001 via
   0x600219ab.
2. Unmount (FILECLBK msg 18), then mount with up to 5 retries (msg 97).
3. Walk an 11-entry table at 0x60f2cbf0. Each entry has a pattern-list pointer into RAM 0x61fb01xx,
   initialised from 0x602483fc. The order is:

   | Order | Pattern(s) | Kind |
   |---|---|---|
   | 0 | `S142` | 0x14 |
   | 1 | `N142` | 7 |
   | 2 | `A142` | 0 |
   | 3 | `M142` | 5 |
   | 4 | `V142` | 0xa |
   | 5 | `T142` | 0xf |
   | 6 | `DATE` | 0xb |
   | 7 | `I142` | 0x12 |
   | 8 | `F???` | 9 |
   | 9 | `K142` | 0x11 |
   | 10 | {`E142`,`G142`,`H142`,`W142`}`????BIN` | **1** |

   - Every group with a match is processed in turn.
   - The search is in directory `DCOLYMP` (0x60c95ed6 compares the name against `DCOLYMP    `).
   - Within the E group, the first pattern with any match wins. E comes before G, H and W.
4. For each file found, it reads the file into 0xa43a3ec0. It then posts `{buffer, size, kind}` to
   FIRMUP_SRV (mailbox 0x60040dca) and waits for the reply (0x60040d22).
5. After all groups:
   - At least one file was processed → `0x601e7094(3,2)`, which prints "UPDATE SUCCESS".
   - Nothing was found → `0x601e7186(3)`. This sends controller command 10, shuts peripherals down
     (0x6006aff1), logs `exit` and ends the task.

   There is **no fallback into the normal UI**. That points to a special boot mode rather than an
   in-app feature.

**[V] No static activation of task 88 was found anywhere in the 26 MB image.**
- The ID variable 0x60040988 (task-ID table 0x600408d8 + 2·id) has no abs32 reference.
- The entry 0x60c95bab is referenced only by its descriptor.
- None of the ~190 callers of the start wrapper 0x60051873, or of the kernel start 0x6003071f, loads
  id 88. This includes the cross-core start dispatcher 0x60053f11 and the debug-shell `tsk sta`
  0x60057d08.
- Every immediate-88 + call site leads to malloc (0x60022700/0x60022782) or to unrelated APIs.
- This matches fishcu's PEN-F result: task 95 is "not connected end to end".

**[V] No boot-time button check that branches to the updater was found.** The startup code is linear:
- BOOT_CPU0 0x60052158 → 0x60044afb → 0x60045223.
- The section loader runs 1, 7, 2, 3, 4, 5, 6, 8, 9 unconditionally (0x60044f2b–0x600451d0).
- USRSTART5 0x60191b74 is one straight-line function.

Related inputs the firmware does read:
- **Wake reason:** 0x60066740 decodes controller register 0x98e00048 into 0xa271601a, with values
  1–9 (getter 0x6006683d). The consumers found (0x60044a00, 0x60066ea3…, 0x6019174f) are logging and
  power/standby logic. None leads to FIRMUP_CLI.
- **Button levels:** 0x600668b4 packs bit 31 of controller registers 0x98e00058/5c/60/64/68 into a
  5-bit value. On PEN-F, 0x98e00068 is OK. The updater itself uses this only at the end, to wait for
  the power switch.

### Inference

- **[I]** The physical trigger (button combo held at power-on) is chosen outside the code we can see.
  Candidates:
  - pre-main boot code, which is not part of the E142 file;
  - the sub-CPU (power controller at 0x98e00000);
  - a computed task start we have not resolved.
- The community report "hold a button combo at power-on, file `DCOLYMP/E????9999.BIN`" fits the
  client's behaviour (directory, 8.3 pattern, highest hex suffix). **The key combination itself is not
  confirmed by this firmware.** A menu item for SD update does not exist in the strings: the in-app
  "firmup" strings are USB/Wi-Fi/lens.

---

## 2. Acceptance rules

All of these are in validator 0x60c964c1(buf, size, mode, out).
- SD requests use mode 0: kind 1 (E group) and kind 0x14 (S142) both go here (jump table 0x60f2d878
  → 0x60c96100 / 0x60c9612d).
- USB FirmwareCheck uses mode 2 (kind 3 → 0x60c96364).
- USB commit uses mode 1 (kind 4 → 0x60c96392).

| Rule | Where | Result |
|---|---|---|
| Split into components of `len+64` bytes (header 32 + payload + trailer 32), at most 32 components | 0x600fa4ce | 0x3321 if the file overruns ("TYPE_FIRMUP_SEARCH_ERROR") **[V]** |
| Per component, modes 0 and 2: descramble in place if header byte 21 == 1, i.e. kind 0x1xx (0x60c95b0c; needs `(len+64)%16==0` and `>64`, else 0x3201). Header words 0–4 must equal trailer words 0–4 (else 0x3202). 32-bit word sum over header + **decoded** payload + trailer must be 0 (else `usr_checksum_error`, **0x3211** for `E`). For a BOOT component the sum skips the header. | 0x60c9718c → 0x60c95a43 | **[V]** emulator |
| Byte 0 must be `O` (`OLY` if byte 22 == 1) | 0x600fa51e | 0x3202 **[V]** |
| Byte 1 must be `E` for body components. `A/V/T/D/I/L/F/M/K/Q` are other device types (lens, flash, BURE, GPS…). | 0x60c96595 | |
| **Model** bytes 2–3 must equal **0x1420** (big-endian "14 20") | 0x60c965c7 | else 0x3202 **[V]** (PEN-F 0x1220 rejected in emulator) |
| Kind byte 20 maps to a write bit: 0x00 USR (main), 0x01 OSD, 0x02 PIC, 0x03 WAV, 0x04 FRAME, 0x05 ADJSLF, 0x06 RESCOM, 0x07 SCPU, 0x08 C3D, 0x09 GUIDE, 0x0a BEAUTY, 0x0b GPS, 0x0c PSES, 0x0d GPSMOD, 0x0e LUKE, 0x10 BOOT | 0x60c965d0–0x60c9678b | anything else → `NO_KIND_ERROR` |
| **Version/build field (offset 16): never read** by the SD/USB validator | n/a | **same version, downgrade, 0x0000 and 0xffff are all accepted [V]** (emulator) |
| **Component subset:** any non-empty subset is accepted, and **main-only is accepted** | n/a | **[V]** (emulator: main-only and OSD+main) |
| Duplicate `E` kinds are **not** rejected; the last copy wins | n/a | **[V]** (emulator). Only non-`E` types check "TOO MANY". |
| **Every component is validated before the first write.** The write loop starts only after the validation loop and the error flag at 0x60c96a82. | | **[V]** emulator: main + corrupt OSD in mode 0 → status 0x3211, **0 flash writes** |
| Mode 2 returns after validation. Only modes 0 and 1 write. Mode 1 skips the checksum. | 0x60c96a90 | **[V]** |

The stock E-P7 components fit this table: 0x100 main, 0x101 OSD, 0x106 RESCOM, 0x10e LUKE (header
address 0, sent to a sub-processor) and 0x102 PIC.

**Filename suffix [V]:**
- The 4 characters after `E142` are parsed by 0x60c95fd8 as hex: `0-9 A-F a-f`.
- Characters in `'0'..'f'` that are not hex count as 0. Any character outside that range stops the
  parse.
- The directory callback 0x60c95f05 keeps the file with the **largest value > 0**. The best value
  starts at 0 and the test is `best >= new → skip`.
- So `E1429999.BIN` → 0x9999 and is selected. **`E1420000.BIN` is never selected.**
- Emulator results: `9999`→0x9999, `0000`→0, `00A1`→0xa1, `G001`→1, `" 999"`→0.
- The suffix has nothing to do with the internal build number.

**On error [V]:**
- FIRMUP_SRV replies with the code. The client calls `0x601e71b6(3,3)` ("UPDATE FAIL").
- LED goes to mode 3: blink, d1 = 100 at 0x601e73c3.
- It then waits until the power-switch input bit clears (0x601e758c mode 3, mask 8 or 1 depending on
  model parameter 0x5241) and powers off.
- Nothing is written when the failure is in validation.

---

## 3. Write behaviour

**[V] Order of writes** (bits tested in sequence from 0x60c96aa0):
1. BOOT
2. LENS
3. FLASH
4. BURE
5. LUKE
6. LANG
7. ADJSLF
8. FRAME
9. WAV
10. GPS
11. C3D
12. PSES
13. GUIDE
14. BEAUTY
15. PIC
16. RESCOM
17. OSD
18. **USR (main) last** (0x60c97074)

For the stock set that means LUKE (sent to a sub-processor via 0x60c972a7), then PIC, RESCOM, OSD and
finally main. A main-only package does a single write.

**[V] Per-component rewrite.**
- Destination: `0x60067102(header address)`, which maps 0x40xxxxxx → 0x80xxxxxx. Main goes to
  0x806a0000 (seen in the emulator).
- Source: header + **descrambled** payload + trailer. The emulator confirmed that the flash buffer
  holds the decoded payload.
- Size: `len + 64`.
- There is **no block-level skip**. Only the BOOT kind does a whole-component compare-and-skip.

**[V] Flash sequence** 0x600c4f35 (mode 1) → 0x60021621:
1. **Erase the whole range** (0x600218a9) → error 0x3103.
2. **Program** (0x6002173b) → error 0x3104.
3. **Read back** via 0x600c4e80 → 0x6002144e (flash into the source buffer) → error 0x3105.

**[I]** No compare instruction exists on that read-back path. "Verify" is therefore only read-back
success, not a byte comparison.

**[V] No rollback.** A failing component aborts the remaining writes (`jmp 0x60c97185`).

**[V/I] What the user sees.**
- The SD client passes display mode **3**, which means **LED only**. The bitmap branch (images
  0xa01/0xa02 through 0x60c64bd2) runs only in mode 4, which is the USB/app path.
- LED sequence [V for the mode numbers, I for how they look]:
  - during work: mode 1 (code 255), probably steady;
  - success: mode 2 (code 250), a longer blink period;
  - failure: mode 3 (code 100), a shorter blink period.
  - The period is derived as 15686/(1000/code)/4 at 0x601e7440–0x601e7456.
- Then it waits for the power switch to go off and powers off ("Power OFF"). There is no auto-reboot
  in mode 3.
- Which physical lamp this is (LED channel 0, 0x6006c8x8) is **[I]** unverified.

---

## 4. Recovery reach

**[V] Code the SD updater needs:**

| Where | What |
|---|---|
| section 6 | client, service, validator, writer wrapper, pattern table, strings, jump table |
| section 1 | header helpers 0x600fa4xx, LED/report 0x601e7xxx, pattern-pointer initialiser data 0x602483fc |
| section 4 | file system and FILECLBK task 16 (0x6062fc44, 0x60628c81, 0x6064a846) |
| base image | flash driver 0x600c4f35/0x60021621, kernel |

- One call level from the SD (mode 3) path reaches **no section-2 code**. The section-2 callees
  (0x603dbe63, 0x602bf0fd, 0x602c8db9) are only in the display mode-4 branch and in neighbouring
  routines.
- **[V] FIRMUP_SRV (task 18) is started in exactly one place:** 0x601922f0, inside the straight-line
  startup task USRSTART5 (0x60191b74). USRSTART5 runs only after the normal startup chain.
- In that same chain, section-2 initializers (list 0x6055e580, 48 B) run through
  `0x6004586c(2)` → 0x6004591f → 0x6018e19e, called at 0x60190e18 at the very start of USRSTART2.
- The section loader also loads section 2 before section 6 (order 1, 7, 2, 3, 4, 5, 6, 8, 9).
- **Consequence [V/I]:** the client cannot do anything until FIRMUP_SRV is running. That requires the
  normal startup to have loaded section 2 **and run its initializers**, and to have got through
  USRSTART2 → USRSTART5.
  - A section-2 fault that kills startup (a torn write over the hook or routine, or a crashing
    initializer) therefore very probably makes the SD updater unreachable.
  - A fault that only fires in COLOR image processing does not.
- **[V] S142 is not an independent path.** `S142????BIN` (kind 0x14) goes through the same
  section-6 validator (0x60c9612d → 0x60c964c1). BOOT-kind components are the only ones written with
  compare-and-skip. No immutable recovery loader is present in the main image.
- **[I]** The physical trigger lives outside the visible code (see §1). Pre-main boot code could in
  principle offer something else, but nothing in this image shows it. fishcu found the same for
  PEN-F.

---

## 5. USB (OM Workspace) path

**[V] Same opcodes as PEN-F.** They are registered at 0x60c40c5d–0x60c40d1d via 0x60c4591e:

| Opcode | Handler | Function |
|---|---|---|
| 0x911c | 0x60c49ada | GetFirmwareUpdateMode; answers 0x2001 with param 1, as on PEN-F |
| 0x9121 | 0x60c4a48c | FirmwareCheck |
| 0x9122 | 0x60c49afe | CheckStatus |
| 0x9123 | 0x60c4a5c1 | UpdateInitiate (0x9117 shares this handler) |
| 0x9119 | 0x60c4a3de | SendObjectSplit |
| 0x9120, 0x9124, 0x9125 | — | also registered |

- The strings at 0x60f175f7… (`[TPCFirmup]…`) are referenced from those handlers.
- FIRMUP_SRV kinds 3/4 run the same validator in mode 2 (check) and mode 1 (commit).
- So the USB path has the same acceptance rules, except that mode 1 skips the checksum because the
  check already ran.
- **[I]** OM Workspace may refuse same-version or modified files on the host side. That is a
  different layer.

---

## 6. Lowest-risk on-camera validation procedure

Assumptions:
- The camera reports firmware **1.1** in the menu (REVIEW H2).
- Battery is full.
- The card is formatted in-camera.
- A human prepares and names every file. Nothing here was generated.

0. **Back up.** Keep the official full 1.1 `.BIN` and a working OM Workspace install. That is the only
   recovery route if a step goes wrong.

1. **Trigger discovery with a package that cannot write (zero-write dry run).**
   - Make a copy of `restore-stock.pkg.bin` and flip one byte inside the trailer checksum word, the
     last 4 bytes.
   - Name it `DCOLYMP/E1429999.BIN`.
   - The firmware rejects this with 0x3211 **before any erase**. The emulator confirmed zero writes
     for corrupt components.
   - With the camera off, try the button combination being tested while switching on.
   - Expected if the updater runs: LED steady, then **fast** blink (failure), then switching the
     power off ends it.
   - Then confirm the camera boots normally and still reports 1.1.
   - If nothing happens with any combo, stop. The SD path is not reachable this way, so use OM
     Workspace for both the official update and any restore.

2. **Restore-only run** (this is a real full rewrite of main, not a no-op; see §0).
   - Only after step 1 has shown the trigger.
   - Put the exact stock main-only `restore-stock.pkg.bin` (== stock[0:26214400]) on the card as
     `DCOLYMP/E1429999.BIN`. Remove any other `E/G/H/W/S…142` file.
   - Expected: LED steady for the duration of the 25 MiB erase/program, then **slow** blink.
   - Switch off, then boot. Check that the version is 1.1 and that the camera works normally.
   - Delete the file afterwards.
   - This proves trigger, main-only acceptance, same-version acceptance, suffix handling and a full
     main program cycle.

3. **Only then** consider the patched package, under the same conditions:
   - set picture mode to non-COLOR first;
   - never interrupt;
   - have the step-2 file ready to re-flash.

   Interruption risk: the main range is **erased in full before programming**. Because of §4, an
   interrupted write probably cannot be recovered over SD.

Open items:
- the physical trigger;
- whether pre-main code has its own recovery;
- which LED is used;
- the maximum file size accepted by the read into 0xa43a3ec0.
