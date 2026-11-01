# SD-card look loader v3 (no stores into the loaded image)

Offline only. Nothing here was run on a camera, no SD-update-named file was created.
**Status: built, statically checked and emulator-verified (§7; bundles mutations and MONO-colour deferred). Release candidate `releases/test7b-sdloader-v3`
(test-6 base). Not independently reviewed yet. Not cleared for flashing until the coordinator/user says so.**

[V] = read from the decoded main or machine-checked by a build script / verifier. [E] = shown in the emulator.
[C] = camera observation. [I] = inference.

## 1. Why v3

v2 crashed the camera on the first half-press (test 7a [C]). docs/SD_V2_CRASH.md: the prime suspect is a store
into flash-loaded section RAM (stock never stores into 0x60020020–0x6191ffe0 [V]). Probe P2 (same hook, gates and a
single halfword store to **0x622cbcc2**) **passed on the camera** [C], so that .bss padding is writable at run
time and the hook/gate path is safe. v3 = v2's hook and gate + SD_V2_CRASH §3 fix:

- **State** = u16 at 0x622cbcc2 (event-manager +174, .bss, 0 at power-on): `0` not attempted, `0xFFFF` attempted /
  no table, `1..0xa941` = handle of the loaded table.
- **No table copy.** The file is read into a `malloc(1024)` buffer from the class-1 pool [0xa1f8d800, 0xa1f98540)
  (uncached alias; bounds from free()'s range checks at 0x600227c9, checked by the build [V]). On success the buffer
  is **kept** (one leaked 1 KiB block per power-on, only when a valid file loads) and `h = buf − pool + 1` is
  stored. The buffer must be 4-aligned and lie wholly inside the pool, else it is freed and the state stays 0xFFFF.
- **Accessor.** All 6 flashed readers call `tbl_idx` / `tbl_off` (60 B, section-2 tail **0x6055e7b0**) instead of
  using 0x60210900. It returns the loaded copy (buf + 32) when `1 ≤ h ≤ 0xa941`, `(h−1) % 4 == 0` and the buffer
  still starts with the file magic `EP7B`; otherwise the flashed table. Readers on any path, before or after the
  load, therefore read a valid table.
- **Hard rule [V][E]:** no new instruction stores into the loaded image. Static store audit over every new
  instruction (loader, accessor, reader diffs) + emulator runs with all image regions mapped read-only (§6).

## 2. Layout

| What | Where | Size |
|---|---|---|
| Hook (as v2/P2) | 0x602c805f `call 0x602c818c,[d2,d3,a2,a3],36` → `jmp 0x605b7400` | 5 B |
| Loader sd_hook/sd_gate/sd_load/sd_check/sd_crc + path/header/range tables | 0x605b7400 (section-3 tail, v2 claim to 0x605b7780) | 688 B |
| Accessor tbl_idx (0x6055e7b0) / tbl_off (0x6055e7b6) | section-2 tail, claim 0x6055e7b0–0x6055e7f0 (was the retired v0.3 bloom reservation); WB ends ≤ 0x6055e7a6, FF to 0x6055e800 | 60 B |
| State | 0x622cbcc2 (u16, .bss) | 2 B |
| Kept block P (heap) | +0 header (32 B, `EP7B`…), +32 table (512 B), +544..+679 zeroed | 1024 B |

Block layout is **compatible with docs/FILM_LIBRARY.md §8.3**: same handle encoding at 0x622cbcc2 (P = 0xa1f8d7ff + h),
table at +32, names[8][16] at +544 and the `EP7N` word at +672. BUNDLES.BIN carries no names, so the loader zeroes
+544..+679 before publishing (stale heap bytes can never look like names). Differences: v3 publishes only
`h ≤ 0xa941` (block wholly inside the pool) and 4-aligned; the menu hook's looser `h ≤ 0xad40` test accepts all of
those. A future LIBRARY.BIN loader fills the names and writes `EP7N` last, before storing h.

**Update (test 8):** `build.py --names` accepts a 680-B BUNDLES.BIN that carries the names (docs/FILM_LIBRARY.md §8.7).
The default build stays as described here.

## 3. Loader flow (first gated half-press per power-on)

Hook replays the tracker call, then only for canonical TRIG1-press with state == 0 runs v2's gate verbatim
(all 9 sections copied, caller is HLS_EVENT, a medium reports MOUNT OK). Then: state = 0xFFFF → malloc(1024) →
fopen("C:\EP7MOD\BUNDLES.BIN","r") → fseek END / ftell == 544 → fseek SET → fread == 544 → fclose → sd_check
(header, CRC-32, per-byte ranges, v1 rules) → pool/alignment check → zero +544..+679 → state = h. Any failure:
free + state stays 0xFFFF. Stores: the two `movhu` to 0x622cbcc2, the name-area clear into the buffer, stack frames.

## 4. Reader changes (`--sd-v3` builds; default builds are byte-identical to before [V])

| Reader | Change | Size |
|---|---|---|
| bundles H/L `hl` (patches/bundles) | `asl 6; mov table,a0; add` → `mov mdr,d1; call tbl_idx; mov d1,mdr` | same 11 B: all labels, branches and verifier patterns unchanged. The call's return word lands on the saved d0 at (0,sp); d0 is dead at the resume point 0x603b02de (`mov (60,a2),d0`, build-checked) |
| WB `wb_get` (patches/wb) | `mov table,a0; add` → MDR save + call16 `tbl_off` + restore; `wb_pass` moved behind the key test so every branch stays 8-bit | 164 → 165 B (≤ 0x6055e7a6) |
| grain `GLEVEL` ×2 (patches/grain) | MDR save + `call tbl_idx` + restore, `movbu (24,a0)`; grain_mod (retf) also restores the CALLS return word at (sp) | 254 → 262 B |
| bloom_flag / bloom_w (patches/bloom) | MDR save + `call tbl_idx` + restore; bloom_w (retf) also restores (sp) | 218 → 220 B |
| MONO-colour `JOB_SLOT` ×3 (patches/mono_colour) | MDR kept in d2 + `call tbl_idx`; chroma/fg wrap the call 4 B lower (a saved register lives at (0,sp)); sel needs no wrap (saved d0 dead at both exits, build-checked); chroma colour exit folded into ch_keep | 764 B (unchanged) |

Every reader still range-checks every byte it uses, exactly as before. MONO-colour is not in test 6, so it is not
in the test-7b release; its `--sd-v3` build is verified separately (§6).

## 5. Release test7b-sdloader-v3

`releases/test7b-sdloader-v3/`: edits.json (= `generated/sd_bundles_v3/t7b.json`: rec_limit, video_log,
bundles lachlan_v3 `--sd-v3`, grain `--sd-v3`, bloom `--sd-v3`, wb `--sd-v3`, sd_bundles_v3), README, SHA256SUMS;
`patched.pkg.bin` / `restore-stock.pkg.bin` and `card/EP7MOD/BUNDLES.BIN` are local only (not committed).
34 edits, 2,393 changed bytes. Restore package identical to test 6's.

Test file (`patches/sd_bundles_v3/make_test_file.py`): the flashed table + COLOR1 (flashed: stock) with H/L on and
hue +7 on green_cyan/green/yellow_green → COLOR1 greens turn teal when loaded; everything else identical.

Rebuild:
```
G=generated/sd_bundles_v3
.venv/bin/python -I patches/sd_bundles_v3/build.py --out $G/sdv3
.venv/bin/python -I patches/bundles/build.py bundles/lachlan_v3.json --out $G/bundles --sd-v3
.venv/bin/python -I patches/grain/build.py --out $G/grain --sd-v3
.venv/bin/python -I patches/bloom/build.py --out $G/bloom --sd-v3
.venv/bin/python -I patches/wb/build.py --out $G/wb --sd-v3
.venv/bin/python -I tools/merge_specs.py $G/t7b.json patches/rec_limit/edits.json patches/video_log/edits.json \
    $G/bundles/edits.json $G/grain/edits.json $G/bloom/edits.json $G/wb/edits.json $G/sdv3/edits.json
```
Run every emulator command as `systemd-run --user --scope -p MemoryMax=6G -q nice -n 15 …`, one at a time.

## 6. Verification (results in generated/sd_bundles_v3/)

`tools/ep7_verify_sd_bundles_v3.py SPEC [--part S,E,Q,A,R,M] [--quick]` — loader runs start at the real upstream
event (v2 fixture), with the section-1/2/3 tails mapped **read-only** (a store into image RAM faults):

- S: site/bytes/FF tails; every accessor call hits an entry; no reader still contains 0x60210900; store audit
  (loader: two abs stores, both 0x622cbcc2, one indirect = the buffer clear; accessor: none; readers: the only
  added stores are stack-relative); 0x622cbcc2 evidence.
- E/F: 173 v1 file cases + 6 pool-edge cases, vs stock; Q: 10 v2 power-on sequences; A: 56 accessor runs;
  R: real loader run → accessor returns the loaded table, state 0 / 0xFFFF → flashed; M: loader/accessor mutations.
- Reader verifiers on the merged spec, both **flashed** (state 0; `tools/ep7_sdv3_env.py` maps it read-only) and
  **loaded** (`tools/ep7_verify_readers_loaded.py`: table moved into a pool buffer, flashed copy poisoned).

Results table: see §7 (filled in as runs finish).

## 7. Results

| Run (generated/sd_bundles_v3/) | Result |
|---|---|
| v3 S static + store audit (v3_SARM.out) | PASS |
| v3 E/F 179 one-press power-ons + Q 10 sequences, image tails read-only (v3_EQ.out) | PASS |
| v3 A 64 accessor runs, R before/after load (v3_SARM.out) | PASS |
| v3 M mutations | 10/10 detected |
| camera test file through the real loader → COLOR1 slot = file bytes; state 0 → 0x60210900 (testfile_load.json) | PASS |
| bundles, flashed / loaded, no mutations (bundles_*_nomut.out) | PASS 56 / PASS 56 (104 of 107 runs relocated) |
| grain flashed / loaded | 7/7 / 7/7 |
| bloom flashed / loaded | 6/6 / 6/6 |
| WB flashed / loaded, with mutations | 26 PASS each; same single config-dependent miss as test 6 ('mode-6 key 40209 -> 38017') |
| negative control: loaded mode on test 6 (old readers) grain / bloom | FAIL as intended (poison table seen) |
| not yet run (memory pressure; deferred) | bundles verifier mutations; MONO-colour `--sd-v3` verify (not in test 7b) |

## 8. Risks / open

- [I] Cache coherency of the handle: written through the cached alias on CPU0 (as P2). A reader on another core
  with a stale line sees 0 → flashed table (safe fallback, never a bad pointer: the magic + bounds checks).
- [I] Pool reuse: if firmware ever re-initialised the class-1 pool, the magic check catches an overwritten header;
  a block reused with the header intact but table bytes changed would give range-checked (bounded) looks.
- [I] Unproven that nothing else uses 0x622cbcc2 (no static reference [V]; P2 [C] shows it survives a store).
- fopen RPC from HLS_EVENT (SD_V2_CRASH rank 2) is new on camera: P3/P4 were skipped. Test with the card first
  without EP7MOD (no fopen success path), then with the test file.
