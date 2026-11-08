# E-PL9: firmware update and recovery (research, 2026-11-07)

Offline only. No camera was contacted, and no file with an SD-update name was created. [V] = read from the decoded
E-PL9 1.101 main or run in the emulator. [C-E-P7] = proven on an E-P7 camera (`docs/INSTALL.md`). [I] = inference.
[?] = open.

## 1. Answer

- **Update file:** `DCOLYMP/E133????BIN` on the card, highest hex suffix wins, so use **`DCOLYMP/E1339999.BIN`** [V].
- **Restore:** the main-only stock package `restore-stock.pkg.bin` from `tools/build_package.py --body epl9` is
  accepted by the E-PL9's own validator (same version, main only) and rewrites the whole main [V].
- **Trigger: camera test 2026-11-07 (step 1 done).** With `dryrun-badsum.pkg.bin` as `DCOLYMP/E1339999.BIN`, the updater started (LED steady, then **fast** blink = refused) and the camera then booted normally on firmware 1.1 [C]. The user reported the result after the step-1 instructions, whose first combination is **hold OK and switch on**. The earlier note follows: the trigger was **not confirmed for the E-PL9** [?]. The E-P7 uses **hold OK and
  switch on** [C-E-P7]. Its updater code is the same as the E-PL9's (below), but the trigger lives outside the main
  image (`docs/SD_UPDATE.md` §1). We find it safely with a file the camera must refuse before writing anything (§4,
  step 1).
- **Boot risk of the look patch:** with the picture mode set to anything but Custom, **no patched instruction
  runs** (§3). A boot failure would need something outside the patched code.
- **What can't be recovered over SD:** an **interrupted** write (main is erased in full before programming), or a
  fault that stops startup before the updater can run. Then only OM service, or possibly OM Workspace over USB [?],
  can help.

## 2. The E-PL9 updater (verified)

Same design as the E-P7 (`docs/SD_UPDATE.md`), model 133 instead of 142:

| Item | E-PL9 1.101 | E-P7 1.1 |
|---|---|---|
| Tasks | `FIRMUP_CLI`, `FIRMUP_SRV` (name table `0x61780d5a`, `0x61780624`) | same names |
| Folder | `DCOLYMP` (`0x61328037`) | same |
| Pattern table | `S133`, then `E133`/`G133`/`H133`/`W133` `????BIN` (`0x61327e58`…) | `…142` |
| Validator | `0x6100440a` (10 callers, frame `[d2,d3,a2,a3],16`) | `0x60c964c1` |
| Suffix parser | `0x61003e2d` (identical code) | `0x60c95fd8` |
| Writer wrapper → flash write | `0x6100511c` → `0x604a0f8b` | `0x60c971e5` → `0x600c4f35` |

`tools/epl9_sd_update_probe.py` runs the native validator and suffix parser in the emulator (flash writes stubbed
and logged): **20/20 PASS**.

| Case | Result |
|---|---|
| Main-only, build 0x1101 / 0x1000 / 0x0000 / 0xffff | accepted (the version is not checked) |
| Bad checksum | `0x3211` |
| Header/trailer mismatch; E-P7 model `1420` | `0x3202` |
| SD mode: main-only valid | 1 write: whole component to `0x806e0000` (flash alias of `0x406e0000`) |
| SD mode: main + corrupt second component | `0x3211`, **0 writes** |
| **SD mode: main-only, bad checksum (the dry run)** | **`0x3211`, 0 writes** |
| Duplicate main | accepted; only the last copy is written |
| File names `E1339999` / `E1330000` / `E13300A1` / `E133ffff` / `E133G001` / `E133 999` | 0x9999 / 0 (never chosen) / 0xa1 / 0xffff / 0x1 / 0 |

The probe's container encoder matches the real stock file (self-check). The real packages satisfy the same rules:

| File (`generated/epl9_look/pkg/`) | Model | Address | Version | Header = trailer | Checksum |
|---|---|---|---|---|---|
| `patched.pkg.bin` | 1330 | `0x406e0000` | 1101 | yes | valid |
| `restore-stock.pkg.bin` | 1330 | `0x406e0000` | 1101 | yes | valid |
| `dryrun-badsum.pkg.bin` (`tools/epl9_dryrun_pkg.py`) | 1330 | `0x406e0000` | 1101 | yes | **invalid** (1 byte flipped, the last) |

These ran on small synthetic containers. The 25 MiB checksum loop itself is too long for the emulator.

## 3. Boot exposure of the look patch

Every patched instruction sits behind a stock branch that only lets it run for Custom or mode 11 [V]:

| Edit | Guarded by |
|---|---|
| T1 `0x60693d02` | `cmp 6,d0; bne` at `0x60693cfe` |
| T2 `0x6069560c` | `cmp 6,d0; bne` at `0x60695608` |
| T3 `0x607210af` (live view, runs from power-on) | `cmp 6,d0; bne` at `0x607210ab` |
| C `0x6079ec53` → stub | selector `cmp 11,d1; bne` before the call (emulator check D: only mode 11 reaches it) |

So with the picture mode **not** on Custom, the patched firmware runs the stock instruction stream. The only
differences are bytes that never execute and the stub in the formerly FF section-2 tail. Nothing references that tail
(`tools/epl9_code_space.py`), and we keep 8 FF bytes before it. Set the camera to Natural (or anything but Custom)
before flashing, and switch to Custom only once it has booted.

## 4. Procedure (for later; needs your go-ahead at every step)

0. **Prepare.** Full battery. A small card formatted in the camera. Keep the official 1.1 file
   (`stock_firmware/epl9/OLY_E_133_1101_0000_0000.BIN`) and OM Workspace on the computer. Camera on firmware 1.1
   (Setup › Firmware), picture mode **not** Custom.
1. **Find the trigger (no write possible).** Copy `dryrun-badsum.pkg.bin` to the card as `DCOLYMP/E1339999.BIN`.
   It must be the only `E/G/H/W/S133` file. With the camera off, hold **OK** and switch on (the E-P7 combination).
   - If the updater starts: the LED lights, then fails (E-P7: **fast** blink), and nothing is written. Switch off,
     boot normally and check that it still shows 1.1.
   - If nothing happens: try other combinations the same way. Each try is safe for the same reason.
   - If no combination works, stop. SD recovery isn't available, and flashing the patch would depend on OM
     Workspace or service.
2. **Prove recovery (a real write of stock).** Replace the file with `restore-stock.pkg.bin` as
   `DCOLYMP/E1339999.BIN` and use the trigger from step 1. Expect a long steady LED (25 MiB erase and program), then
   the end signal (E-P7: slow blink). Boot, check 1.1, delete the file. This proves the trigger, main-only and
   same-version acceptance, and a full write cycle on this camera.
3. **Flash the look (v1).** Same steps with `patched.pkg.bin`, picture mode not Custom, never interrupted. Boot,
   check that Natural/Vivid look stock, then select Custom: the test look should be obvious in live view and photos.
   Keep the restore file ready on the computer.

## 5. Open points

- ~~The button combination~~: the updater runs and refuses the dry-run file (step 1, §1). Fast blink = refused, as on the E-P7.
- LED meaning on the E-PL9 (assumed as on the E-P7).
- Whether OM Workspace re-flashes a camera that already has 1.1 or a modified 1.1 (a host-side check) [?]. If not,
  OM service is the only route after an interrupted write.
- The largest file the updater reads into its buffer (the E-P7 open item). Our files are the stock main size.

Sources consulted for the trigger: no public E-PL9 description found. General Olympus SD-update cautions (don't
interrupt, keep power) match the analysis above.

## 6. Camera results and what they do and don't show (2026-11-07)

| Step | File as `DCOLYMP/E1339999.BIN` | Result |
|---|---|---|
| 1 | `dryrun-badsum.pkg.bin` (broken checksum) | LED steady, then fast blink; camera still boots on 1.1 |
| 2 | `restore-stock.pkg.bin` (valid, stock main only) | **the same**: LED steady, then fast blink; still 1.1 |

**Correction to §1:** because a valid file failed exactly like the broken one, step 1 did **not** prove that the
updater found and refused our file. A fast blink only shows that the updater ran and ended in an error. "No file
found", a mount failure, a battery check and a refusal all look alike. What is proven: **holding OK at power-on
starts the SD updater** (no normal start-up, LED activity) and nothing was written.

The emulator only ran the validator function `0x6100440a`. The E-PL9 update service around it (`0x61003e85…`) is
restructured compared with the E-P7. It has new early error codes `0x3305`/`0x3303` (after `0x604313e9`, at
`0x61003edd`), a mode word read from `0x60420fac` where the E-P7 uses the constant 3, a mount-retry helper that
returns `0x3304`, and a writer wrapper that picks the write mode from new tests (`cmp 1,d1`, `cmp 16`). So
"main-only is accepted" holds for the validator only, not end to end.

**Next diagnostics (no write, then stock content only):**
- **A. No file:** OK + power on with an empty `DCOLYMP` (or no folder). If the LED does the same, the fast blink
  means "nothing usable found or processed", and our file was probably never read.
- **B. Battery:** repeat with a freshly fully charged battery (the updater may check battery level).
- **C. OM's official full file** (`OLY_E_133_1101_0000_0000.BIN`, all 5 components, unmodified) as
  `DCOLYMP/E1339999.BIN`. This is a real write, of OM's own stock content, the same as an official update. If it
  succeeds (slow blink), the SD path works for full packages, and the patch can ship as a full package (stock
  components + patched main).

**Test A result (2026-11-07):** with `DCOLYMP` empty, holding OK at power-on gave **no LED, and the camera stayed off**
(it then started normally with the power switch) [C]. That matches the client's "nothing found → shut down" path. So
in steps 1–2 the updater **found and read** `E1339999.BIN` and then failed. The name, folder and trigger (**OK +
power on**) are confirmed. The E-PL9 refuses a **main-only** package, even the unmodified stock main. The E-P7
accepts one. Next: test C (OM's official full file), which shows whether full packages are accepted.

## 7. Why the SD path refuses every file: emulation conclusion (2026-11-08)

The whole SD update path in the E-PL9 main image was traced and, where runnable, emulated:
- **Client** `0x610039fd` (FIRMUP_CLI): walks the `DCOLYMP/x133????BIN` pattern table, picks the highest suffix,
  reads the file, posts `{buffer, size, kind}` to the service. Confirmed on the camera: with a file it runs (LED +
  fast blink), with none it finds nothing and powers off (no LED, test A). So the file **is** found and read.
- **Service** `0x61003e85` (FIRMUP_SRV): dispatches on the request type (a jump table at `0x61328d70`); a body file
  (kind 1) takes `0x61003f61`, which calls the validator in mode 0 (validate-every-component-then-write).
- **Validator** `0x6100440a`: `tools/epl9_sd_update_probe.py`, 20/20 — accepts main-only and full packages, **ignores
  the version field** (build 0x1101/0x1000/0x0000/0xffff all pass), rejects only bad checksum / wrong model / torn
  components.
- **Writer wrapper** `0x6100511c` → flash write `0x604a0f8b`.

Static findings across `0x61003800–0x61005600`:
- **No version comparison** anywhere (the service never reads the installed version to compare).
- **No file-size limit / buffer cap** (no 8–256 MiB constant on the whole path).
- **No model/mode gate** a file could fail beyond the validator's model check (which model 133 passes).

So the main-image code **should accept and write** a stock, same-version file — yet the camera refused all three
real files (dry-run, stock main-only restore, OM's official full 1.1), each with a fast blink, nothing written.

**Conclusion:** the refusal is **not** in the main firmware and **cannot be satisfied by changing the file**
(OM's own file is refused identically). It lives in the layer the main image can't see — the pre-main boot code or
the sub-CPU power/mode controller — which, on this body, does not permit an SD update-and-write in the "hold OK at
power-on" state (most likely because the E-PL9's supported update method is OM Workspace over USB, and the SD
`DCOLYMP` path is gated to a service/upgrade condition we can't reproduce). `docs/SD_UPDATE.md` §1/§4 already noted
the trigger and mode arbitration live outside the main image.

**Consequence for the look patch:** it cannot be installed over SD on this E-PL9. There was never any risk to the
camera — nothing was ever written. The remaining firmware avenue is USB (the OM Workspace protocol: opcodes
`0x911c`/`0x9121`/`0x9123` are present, and the submodule carries fishcu's `camera_client`), which is a separate,
substantial investigation and uncertain (the camera-side check may still refuse a same-version image).
