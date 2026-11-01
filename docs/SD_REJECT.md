# Why the SD updater rejected the stock main-only package (E-P7 1.1)

Status: **open**. This was offline analysis only. No device was contacted, no `E142*.BIN` file was created and nothing was committed.
Notation: **[V]** verified (disassembly or native emulator run); **[I]** inference.

## Camera observation (user report)

- Holding OK at power-on gives a solid LED for about 15 s, then a fast blink of about 2 Hz. The camera then boots normally and still reports 1.1.
- The result was identical for two files placed as `DCOLYMP/E1429999.BIN`:
  - (1) the stock main-only package with one checksum byte flipped;
  - (2) the exact stock main-only package, `OLY_E_142_1100_0000_0000.BIN[0:26214400]`.
- The battery was at about 50%.

## 1. The validator accepts file (2) [V]

The native validator 0x60c964c1 was run on the **real 26,214,400 stock bytes**. Runs were chained in the MN103 engine, about 162 M instructions each. The flash writer 0x600c4f35 was stubbed.
The script is `/tmp/claude-1000/-mnt-Storage-Projects---software-Firmware-Olympus-E-P7/ca7a5b2b-a0cb-49f7-8a33-fbf59936fbd5/scratchpad/chain.py` (scratch, not in repo), a variant of `tools/ep7_sd_update_probe.py` that resumes 100 M-instruction chunks.

| Input | Mode | Status | Flash writes |
|---|---|---|---|
| stock main-only (2) | 2 (check) | 0 | 0 |
| stock main-only (2) | 0 (SD) | 0 | 1: dst 0x806a0000, size 0x1900000, mode 1 |
| (2) with the last trailer byte flipped (1) | 0 (SD) | 0x3211 | 0 |

So nothing in the validator rejects (2). That rules out the following, **as far as the validator goes**:

- (b) a component-set requirement;
- (c) a version or date check;
- (d) a size check.

## 2. Client and server checks other than the validator [V]

**Client** FIRMUP_CLI 0x60c95bab:
- 0x60c95e06 is a stub that returns 0.
- 0x60c974c0(0) has its result ignored.
- Unmount and mount (5 retries). On failure it calls `0x601e7186(3)`.
- Then the 11-group search and read.
  - Status 0xe00 or 0xe0c means "none", and the group is skipped.
  - Any other error leads to `0x601e7186(3)`.
- `0x601e7186` sends controller command 10, shuts peripherals down, logs `exit` and ends the task.
  **It sets no LED mode.** Mount, search and read failures therefore do *not* give the fail blink.
- The client sets LED mode 1 (`0x601e739f(1)`) **only after the whole file has been read**. It then posts to FIRMUP_SRV and waits.
- A non-zero reply leads to `0x601e71b6(3,3)`, which is LED mode 3 (fail).

**File read** (0x60c95f52):
- The whole file is read in one FILECLBK message 83, of `ceil(size/512)` sectors, into 0xa43a3ec0.
- The size passed to the server is the directory-entry size. The client applies no size cap.
- A full 111,017,984-byte file would end at 0xaad83ec0, which is below the 0xab000ead marker.

**E-group table entry** 0x60f2ccb8: `{drv 0, flag 0, patterns 0x61fb0140, count 4, kind 1}`. Flag 0 means the server replies through the mailbox; the display mode-4 path is not used.

**Server** FIRMUP_SRV 0x60c96030, before dispatch:
- `0x6006757a` runs once. It reads a task state and posts a mode request; it does not return a status.
- `0x6015bafd(1)` stores a flag at 0xa272c3f4; it performs no check.
- Size 0 makes the server log "Size is 0" and set its error flag.
- Kind 1 jumps through table 0x60f2d878 to 0x60c96100, which calls the validator in mode 0. **The server has no date, version or battery check.**

**Other strings:**
- `FIRMUP_DATE_ERROR` belongs to the `DATE????BIN` handler, kind 0xb (0x60c96331). That handler writes the file to 0x40440000.
- `TYPE_FIRMUP_CHECK` is USB kind 3 (validator mode 2).
- Neither is on the E-file path.

## 3. Flash writer, before the first erase [V]

Path: 0x600c4f35 (mode 1) → 0x600c5016 → 0x60021621 → erase 0x600218a9 → 0x60021137.

The only checks before the erase are:
- an address-region check, which leads to error 0x3109 or a log message;
- the mode switch;
- taking the flash semaphore (0x6002195b);
- trace logging;
- a loop over 128 KiB blocks.

There are **no battery, voltage-ADC, write-protect or lens/accessory reads** before the erase in this driver.
- Error codes on this path: 0x3103 (erase), 0x3104 (program), 0x3105 (read-back), 0x310d (passed through from the driver).
- **[I]** Any of those after a started erase would leave main damaged. The camera booted fine, so the write either never started or completed.

## 4. Battery threshold (a)

- **[V]** No battery or voltage check exists anywhere in the FIRMUP_CLI → FIRMUP_SRV → validator → flash-driver chain.
- **[V]** A battery check does exist elsewhere:
  - names `Maintenance::cardFirmWareBatteryCheck` and `CardFirmwareBatteryCheck`;
  - a script/API binding at 0x607d7367 (table 0x60aa4fe8), next to `canUpdateFirmwareCard` and `getFirmwareVersionFromCard`;
  - this belongs to the in-app card-update API.
  - It dispatches through a vtable (offset 76), so its threshold and units were **not resolved**.
- **[V]** No call from the section-6 updater code reaches it.
- **[I]** That API looks like it serves a menu- or app-driven card update, not the OK-at-power-on path. Whether 50% fails it is unknown.

## 5. LED meaning (e)

**[V]** Mode 2 (success) uses code 250 and mode 3 (fail) uses code 100. Both go through the same blink setup (0x601e741c…), with the parameter `15686/(1000/code)/4`:

| Mode | Code | Parameter |
|---|---|---|
| 2 (success) | 250 | 980 |
| 3 (fail) | 100 | 392 |

- Mode 3 is about 2.5× faster than mode 2. The units of the 0x6006c848 PWM parameter are **not decoded**.
- **[I]** If the units are milliseconds per period, fail is about 2.5 Hz and success about 1 Hz. The observed ~2 Hz fits **fail**.

## 6. What the evidence points to

We could not find any code that would reject (2) **if the camera were running FIRMUP_CLI**. The candidates, most likely first:

1. **[I] The OK-at-power-on updater is not FIRMUP_CLI.**
   - SD_UPDATE.md §1 found no static start of task 88 and no button branch into it.
   - A pre-main or sub-CPU updater with its own rules would explain why the corrupt and the valid file look identical.
   - Its rules might require the full 5-component file, a battery level, or a different name or location.
2. **[I] The file read returns success with incomplete data.**
   - One 51,200-sector FILECLBK read may be limited by the driver. The stale buffer tail would then fail the checksum with 0x3211 for *any* file.
   - The FILECLBK message-83 limit is not yet traced. The dispatcher starts at 0x6062fc44.
3. **[I] Misread LED.**
   - In this case (2) was written successfully. The ~15 s timing being equal for a rejected file and a 25 MiB erase and program argues against this.
4. Battery: there is no evidence that it gates this path. Charging to 100% is cheap and harmless, but it is not indicated by the code.

## 7. Recommendations

- **Same-version restore now:** use **OM Workspace over USB** with the official full 1.1 file. That path's validator rules are known (SD_UPDATE.md §5).
  - **[I]** The SD route is not understood well enough to rely on. The full 111 MB `E1429999.BIN` goes through the same visible code. If cause 1 or 2 is true it may behave differently, but we cannot predict how.
- **Patched main-only packages:** **do not try them over SD.** Whatever rejects stock (2) will also reject a patched file, so it is pointless. If the cause is not what we think, the risk is unknown.
- **Zero-write tests that tell the causes apart** (user's choice; all use files the visible validator rejects before any erase):
  1. **No E-file on the card, OK held at power-on.** Visible code: no LED mode, just an exit and shutdown. If you still get ~15 s solid then a fast blink, the camera is not running FIRMUP_CLI (cause 1).
  2. **A tiny E-file**, e.g. a 1 KiB copy of (1) truncated with a bad header. Visible code: a read of well under 1 s, then the fail blink. If it still takes ~15 s, the delay does not come from the file read.
  3. **The corrupt file (1) with the battery at 100%.** Same blink as before means no battery gate on rejection. This test does not prove anything about the valid-file case.

## Open items

- FILECLBK message-83 maximum transfer size (cause 2).
- The `Maintenance::cardFirmWareBatteryCheck` threshold and units (vtable target).
- Units of the LED PWM parameter.
- Where the OK-at-power-on trigger actually lives (pre-main or sub-CPU).
