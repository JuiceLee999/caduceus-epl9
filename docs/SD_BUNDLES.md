# SD-card bundle loading, phase 1 (data only)

Offline only. Nothing here was run on a camera. No SD-update-named file was created and nothing was committed.
**Status: built and statically checked. The emulator verification has NOT been done: no verifier exists yet. Do not
flash this until it has been.**

[V] means verified from the disassembly of the decoded main (SHA `5dd9af16…`). [I] means inference.

## 1. The firmware file API (task 1)

- **[V] fileif API**, section 4. Every wrapper first classifies the caller with 0x60643765:
  - (0x8050) ≠ 0, i.e. another CPU: returns 2, message path with a copy of the path.
  - Inside FILECLBK (task 16, entry 0x6062fc44, prio 55): returns 0, and the implementation is called directly.
  - Inside one extra task listed at 0xa2786068: also returns 0.
  - Any other CPU0 task: returns 1. The wrapper `malloc`s a 128-byte request and sends message 0x1000x to FILECLBK's mailbox
    (0x60040d20) through 0x60054b33. That function creates a temporary reply mailbox, sends, waits with timeout −1
    (forever), deletes the mailbox and returns the status.
  - So a call **blocks the calling task until FILECLBK replies**. It is re-entrant across tasks, and FILECLBK serialises
    the calls.

| Function | Address | Stock call frame | Arguments → result |
|---|---|---|---|
| fopen | 0x60634fbc (→0x60636358, msg 0x10001) | `[],4` | a0 path, a1 mode ("r") → a0 handle, 0 on failure |
| fclose | 0x60634fc5 (0x10002) | `[d2,a2,a3],16` | a0 handle |
| fread | 0x6063514b (0x10005) | `[d2,d3,a2,a3],24` | a0 buf, d0 size, d1 count, a1 handle → d0 |
| ftell | 0x606351d9 (0x10007) | `[d2,a2,a3],16` | a0 → d0 position (−1 on failure) |
| fseek | 0x60635243 (0x10008) | `[d2,d3,a2,a3],20` | a0, d0 off, d1 whence → d0 0 ok |
| malloc / free | 0x60022782 / 0x600227b4 | `[],4` | fixed-block pools of ≤128, ≤2048 and ≤16384 bytes |

- **fseek whence [V]** (implementation 0x6064610d): 2 = SET, 0 = CUR, 1 = END. The size is at handle+268 and the
  position at +308.
- **Drive [V]:** drive index 0 is `C:` (0x60646851 adds 67). The stock card log writers use index 0.
- **Stock precedent [V]:** the "load arm linux from sd" routine at 0x6005a509 does
  fopen → ftell/fseek(END)/ftell → fseek(SET) → fread(buf,1,size) → fclose. Our loader follows the same sequence.
- **Message protocol below fileif [V]:** FILECLBK dispatches by class at 0x6062fc44:
  - 0x0000xxxx: low-level ops (unmount 18, mount 97, sector read 83) via the table at 0x6070a410;
  - 0x0001xxxx: fileif;
  - 0x0002xxxx and 0x0008/0x0010xxxx: other services.
  The SD updater uses only the low-level messages.
- **Mount timing [I]:** no stock code sends mount (97) at boot apart from the updater, so the boot mount is
  asynchronous inside the file system. The app learns of it in the media manager (section 5). Method 0x60863da7 records
  the status through 0x6077d590 (d0 = media type, d1 = status). 0xF000 means "MOUNT OK" ([V]: the string table and the
  0x6092554a "MOUNT OK" log).

## 2. Hook point (task 2)

- **[V]** The call `0x60863e90 call 0x6077d590,[d2],20` is reached only behind `0x60863e81 cmp 61440,d2; bne`. So it runs
  exactly when the app records a successful mount, at boot and again on every later card mount.
- The patch redirects the rel32 of that call (4 bytes at 0x60863e91) to `sd_hook`. Every path through `sd_hook` ends by
  **tail-jumping into the stock 0x6077d590 on the same frame**, with the original d0/d1. The loader restores a0/a1.
- **Task context [I]:** this C++ media manager almost certainly runs in task 61 HIGHLEVEL_MAIN (entry 0x60767d89,
  36 KB stack, the app framework). This is not proven.
- **Deadlock reasoning:**
  - [V] The FS library (0x60613000–0x60650000) makes no calls into section 5, apart from a constant getter.
  - [I] Therefore FILECLBK does not wait on the app task.
  - The cost is that the UI task blocks for 6 file round trips at mount time. That could be long if FILECLBK is busy
    with a post-mount DCF scan.
- **Ruled out:**
  - FILEFGND (task 17): it delivers driver completions, so blocking there would deadlock.
  - The image pipeline.
  - USRSTART: mount state is unknown at that point, and its message 53 to FILECLBK is a power-off DCF op inside
    0x6006109f.
- **SD updater untouched [V]:** the updater (FIRMUP_CLI) uses low-level messages and never fopen. `build.py` refuses any
  edit that overlaps updater code or data or the FS library.

## 3. Target (task 3)

- The patch writes the 512-byte v0.2 table in place at 0x60210900, through the cached alias only.
- **[I] Writable:** section 1 is copied into DRAM by the boot loader. I found no MMU or protection setup, but this is
  not proven. If a write faulted, the camera would crash at mount only when a valid file is present. Removing the card
  or the file would recover it.
- **[I] Coherency:** if a table reader runs on another core with a stale cache line, the old look may persist for a
  while. It cannot crash: every reader range-checks every byte, and any old/new mix is still a valid table.

## 4. Loader and file format (task 4), as built

- **Code:** `patches/sd_bundles/sd_bundles.s.in`, 564 bytes at 0x61242a00. The section-6 FF tail is claimed for
  0x61242a00–0x61242d00. Stock data ends at 0x612429af, and aspect owns 0x61242f00.
- **Sequence:**
  1. malloc(1024).
  2. fopen("C:\EP7MOD\BUNDLES.BIN","r").
  3. Set sd_state = 0 (no further attempts this power cycle).
  4. fseek(END), then ftell must equal 544; fseek(SET).
  5. fread(buf,1,544) must return 544.
  6. fclose.
  7. Validate: header bytes, CRC-32, per-byte ranges.
  8. Copy the payload.
  9. free.
- **Failure handling:**
  - malloc failure or no file: retry at the next mount.
  - Any other failure: the table is left untouched.
- **Code constraints:** no mul/div/setlb.
- **File, 544 bytes, little-endian:**

  | Offset | Content |
  |---|---|
  | 0 | `EP7B` |
  | 4 | u16 version = 1 |
  | 6 | u16 header length = 32 |
  | 8 | u32 firmware build = 1100 |
  | 12 | u32 payload length = 512 |
  | 16 | u32 CRC-32 (zlib) over bytes 0–15 followed by 20–543 |
  | 20 | main SHA-256 prefix `5dd9af16` |
  | 24–31 | zero |
  | 32 | the 8×64 table |

- **Per-byte ranges:** generated from `layout.json`, for example hue/light −7..7, grain 0..3, sat −5..5. Unclaimed bytes
  must be 0.
- **Build:** `.venv/bin/python -I patches/sd_bundles/build.py --out generated/sd_bundles`. It checks the stock site
  bytes and the guard, the section-6 descriptor and load end, that the placement is FF, abs32 references into the
  placement (two pinned false positives), and the reservations.
- **Desktop tool:**
  `.venv/bin/python -I tools/ep7_bundles_bin.py bundles/example.json --out <dir>` writes `<dir>/EP7MOD/BUNDLES.BIN`.
  `--check FILE` validates a file. It uses `patches/bundles/build.py build_table()`.

## 5. Still to do before any flash

1. **Emulator verification.** Not written. Stub the file service at its real entries with matching frames. Cases:
   - valid file → table replaced;
   - bad magic, version, build, length, CRC or range;
   - wrong size;
   - fseek, ftell or fread error;
   - fopen or malloc failure → table untouched.
   In every case, registers, stack and the status variable must equal stock, and sd_state must behave as specified.
   Add mutations.
2. Merge with the bundles spec. `tools/merge_specs.py` keeps the metadata under `meta.sd_bundles`.
3. Confirm the [I] items: HIGHLEVEL_MAIN as the context, that the section-1 table is writable, and cache coherency.
   First camera check: a valid file changes COLOR1, and booting with no card, or with a corrupt file, behaves as stock.
