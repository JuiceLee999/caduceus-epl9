# Live-view bundle H/L (E-P7 1.1)

Offline only. Nothing here has run on a camera. No package was flashed and nothing was committed.
Status: **built and emulator-verified against the test12c base; not yet integrated (test12d) or camera-tested.**

[V] = read from the decoded main (disassembly, byte dumps) or run in the emulator. [I] = inference.

- Build: `.venv/bin/python -I patches/lv_bundles/build.py --base releases/test12c-editor/edits.json --out generated/lv_bundles/t12c`
- Verify: `.venv/bin/python -I tools/ep7_verify_lv_bundles.py generated/lv_bundles/t12c/merged.json --jobs 16 --json <out>`
  (run inside `systemd-run --user --scope -p MemoryMax=8G -p MemoryHigh=7G -q`).
- Files: `patches/lv_bundles/lv_bundles.s.in`, `patches/lv_bundles/build.py`, `tools/ep7_verify_lv_bundles.py`.

## 1. Problem

The bundle H/L table (flashed, or the SD heap copy through the v3 accessor) only reaches captures. In-camera H/L
edits (look editor 12c) and card looks do not show in live view, while stock COLOR saturation edits do.

## 2. The live-view colour path (trace)

### 2.1 Same coefficient builder for live view and capture

- The per-sector COLOR coefficients (12 output records at output+688, hue +18, sat +20, L +22) are built by
  **`0x603b0068`** from the request's 12 saturation bytes (request+1816) and the COLOR table `0x6051de2c`. [V]
- `0x603b0068` has one caller, the COLOR selector **`0x603b0252`** (call at 0x603b02d9, which is the bundles `hl`
  hook). The COLOR table `0x6051de2c` is referenced only there. [V]
- The selector has one caller, the stage list `0x603b1466`, which `0x603b17e6`/`0x603b1819` run for request kinds
  0/16 (sub-kinds 1/2) from the stage dispatcher `0x603aaced` (callers `0x60339870`, `0x603399d7`). [V]
- So there is **no separate live-view coefficient builder**. Live view and capture both run 0x603b0068 through
  the selector. The difference is the input and the transport. [V for the call graph; I strong that the
  live-view job takes this route, because nothing else reads the COLOR table and S edits do show in LV]
- The alternate builder `0x603afb94` (request+1524 ≠ 0 and context+60 bit 28) uses a table supplied by the
  request object (art-filter tables). A job-embedded request has +1524 = 0 after the packer clears it. [I]

### 2.2 Where the live-view saturation comes from

| Step | Address | What |
|---|---|---|
| Live-view / movie development job created | `0x60321d36` (IPCR development-request handler) → constructor `0x603537eb` at **0x60321ea8** | Same constructor as stills, so the job has the 24-byte bundle extension, zeroed. [V] |
| Job parameters from the live-view request R | `0x603220e5` → **`0x60324071`** (call at 0x60322155) | R+2119..2130 → params+5538..5549 (12 × S), R+2117/2118 → 5536/5537, R+2131..2133 → 5550..5552 (loop at 0x6032435e). [V] |
| R filled on the sender side | `0x60314b7a` (from `0x60315a69`) | message+21..32 → R+2119 when message+20 ≠ 0. [V] |
| Packer | `0x60355409` → `0x60354ce4` | params+5538 → request+1816 (same as stills). [V] |
| Builder | `0x603b0252` → `0x603b0068` | as 2.1 |

Stills differ only upstream: converters `0x603e62d1`/`0x603e8af1` copy capture+24058 → params+5538, and the
bundles transport (conv1/conv2) writes job+15488 profile, +15489 mode, +15490 = 0xB2. **Live-view jobs never
pass a converter, so the marker is 0 and `hl` leaves them stock** (V02 residual risk 2). Neither R, params nor
the request carries the profile number (PROFILE_INDEX_WB §1). [V]

### 2.3 Settings manager → live-view colour

Chain for an S edit (and for 12c's `ed_set` re-entry with the unchanged S value):

1. GUI setter `0x607fa355` → **`0x60827440`** (settings manager) → `0x602af890` → `0x602b0bc9` (set) →
   `0x602b9deb` (store) → `0x602b143e` (post-set). [V]
2. **The listener is the per-ID descriptor callback at descriptor+24**, called unconditionally by `0x602b143e`.
   Descriptors are 60-B records (`+0` id): ID 927 at 0x60435af0, …, 938; their +24 word is **`0x602b5e91`**
   (COLOR1), IDs 939–950 → `0x602b5eaa` (COLOR2), 951–962 → `0x602b5ec3` (COLOR3), 1655–1666 → `0x602b5edc`
   (COLOR4). Each one reads picture mode (setting 111) and, when it is that profile's mode (54/55/56/64),
   calls **`0x602b8916(0)`**. [V]
3. `0x602b8916` → **`0x602b7b71`**: the effective-parameter builder. It reads the active profile's 12 S
   (927–938 etc., jump table by mode at 0x60460458) and writes them to the effective settings (915–926 =
   property 0xF6EA) through `0x602b2250`. [V]
4. The live-view side reads the effective S with the getter `0x6005e971(0xF6EA, i, 0)` at `0x6030bd54`
   (compact slot fill `0x6030bcde`, called from `0x6030bccc` ← `0x6030ba2b` ← `0x6032cbf8`). [V]
   From there to R+2119 and the next live-view development is [I] (record/message chain not traced end to end).

No old == new comparison was found on the set path (`0x602b0bc9`, `0x602b9deb`, `0x602b143e`,
`0x602cbc74`, `0x6005ea22`): an unchanged value runs the same descriptor callback and the same effective
refresh as a real change. [V for these functions; I that nothing downstream filters an unchanged S]

## 3. Design: one hook after the builder

`lv` runs at **0x603b02de**, the selector's resume point after the builder (and after `hl`, which ends with
`jmp 0x603b02de`). It replays `mov (60,a2),d0; btst 2,d0` and resumes at the `beq` at 0x603b02e4.

It writes H/L only when **all** of these hold:

1. The request is embedded in a job (same callback / record / parent guard as `hl`).
2. **Marker ≠ 0xB2**, so the job has no capture transport. Capture jobs return at once, which keeps stills
   byte-identical to the base build.
3. Request key == 11 (COLOR). MONO-colour's jump to 0x603b02de has key 12.
4. Some COLOR slot 0..3 of the active table has flags bit1. If none does, the getter is never called.
5. Profile = `0x6005e971(0xF6B1, 0, a0 = 0)` (setting 908, the effective COLOR profile number). This is the
   same read the capture population does at 0x602a85a2, so it is 1..4 as on the camera-proven capture path.
6. Then the same checks and writes as `hl`: slot flags bit1, all 24 values −7..7, then 12 records through the
   bundles build's own `perm`/`hue_lut`/`light_lut` (labels from the base spec; `build.py` checks their bytes).

The table is read through the v3 accessor `tbl_idx` when the base bundles reader is `--sd-v3`; otherwise the
flashed table. **That is the same table the capture reader and `ed_set` use, so a heap H/L edit reaches the next
live-view development with no other change.**

Registers: all except d0/PSW are restored; d0 is reloaded by the replayed instruction. MDR is saved and restored.
The call return words land in the dead saved-d0 slot. Stores: the 32-B stack frame and the 12 output records
(context+12) only. **No store into 0x60020020–0x6191ffe0** (static audit plus read-only image regions in the
emulator).

### Why not a transport for live-view jobs?

Writing job+15488/15490 in the live-view job handler (0x603220e5) would also switch on every other marker
reader for live view: grain, bloom (three extra full-image passes), WB and MONO-colour. It would also still need
the same getter, in the IPCR receiver. The post-builder hook changes only H/L.

### 12c's `ed_set` trigger

Nothing changes in patches/look_editor. After an H/L heap write, `ed_set` re-enters 0x60827440 with the unchanged
S. Per §2.3 that runs the descriptor callback and the effective refresh exactly as an S edit does. If the
camera then redevelops live view (as it visibly does for S edits), the selector runs, `lv` reads the edited heap
table, and live view shows it.

## 4. Edits and code space

| Site | Stock | New |
|---|---|---|
| 0x603b02de (6 B) | `f8023c f8ec02` mov (60,a2),d0; btst 2,d0 | `dc rel32 cb` jmp lv; nop |
| 0x601e0e3c (284 B) | EVF step-14 R LUT + first 28 B of its G LUT | lv |

- The placement is the EVF (device index 1) display-gamma step-14 R/G LUTs, 0x601e0e3c–0x601e103c, in
  section 1. Section 1 loads first and holds the bundles code. The only references are the step-table pointers
  at 0x601e3c80 (R) and 0x601e3c84 (G). The verifier checks this with a brute-force branch/abs32 scan.
- EVF tables are dead on the E-P7 (no EVF). This is the same argument and the same table block as View Assist,
  which uses EVF step 0 at 0x601e383c–0x601e3a3c and ran on the camera in test 11. If that inference were ever
  wrong, the EVF step-14 gamma would load code bytes as a LUT: a display tint on a non-existent EVF, never
  executed.
- Claimed in docs/CODE_SPACE_MAP.md. The base must not edit 0x603b02de–0x603b02e3 or the placement ±16 B.
  `build.py` checks this.

## 5. Verification (generated/lv_bundles/t12c/verify.json)

`tools/ep7_verify_lv_bundles.py` builds the packages for merged (test12c + lv) and for base (test12c). It runs
the real selector → bundles `hl` → builder → `lv` natively. The getter also runs natively (registry lookup
0x6005d924, width 0x6005efbd, per-core translator 0x6005c8cf) on a fixture registry that holds key 0xF6B1. All
image regions are read-only.

| Part | What | Result |
|---|---|---|
| S | hook/resume bytes; no branch/abs32 into the hook interior; only the EVF step-14 pointers reference the placement; store audit (10 stores: 8 stack, 2 via a3); changed bytes inside edit spans | PASS |
| L | **Live view == capture.** For COLOR1–4 × 4 S sets × 2 tables (lachlan_v3 table; a test table with every COLOR slot on), a job without transport (marker 0, profile from the getter) gives byte-identical output, context, live stack and registers (job except the 3 extension bytes) as the same job with transport. H/L == rows rebuilt from the table bytes; disabled slots == stock | 32/32 PASS |
| K | Capture jobs (profile 0..5): merged == base build (output, job, context, stack, all registers) | 24/24 PASS |
| N | **No table / guards → stock** (incl. profile 5 with a MONO1 slot enabled) (output, job, context, stack, registers == stock image): all COLOR slots off with the registry unmapped (a getter call would fault); profile 0/5/255; registry entry missing (getter error path); value out of range; slot off; wrong callback; foreign parent; key 12/5. Overlay flag without an overlay entry → main registry (lv == capture) | 15/15 PASS |
| C | CPU id 1 (getter through translator 0x60067100) | 8/8 PASS |
| D | SD v3 loaded mode (table in a pool buffer, flashed copy poisoned) | 4/4 PASS |
| X | Negative control: the base build leaves a live-view job stock (≠ capture) | PASS |
| L+ | context+60 bit 2 set (the replayed `btst` changes control flow): lv == capture and flow == reference | 6/6 PASS |
| M | 18 mutations (marker, key, property key ×2, profile −1/bound, any-slot/slot flag, offsets, loop, value range, frame/MDR restore, displaced btst, callback, hook) | **18/18 detected** |

Total **91/91 functional + 18/18 mutations** (`generated/lv_bundles/t12c/verify.out`).

Not covered (camera only, or not traceable offline):
- That the camera's live-view jobs really take the 0x60321d36 → selector route and run it after a settings
  set, including an unchanged-value set (§2.3 step 4 onwards is [I]).
- Which core runs the selector for live view. The getter supports CPU ids 0–2 (translator table 0x60078968).
  An id ≥ 3 would index string data. The capture path calls the same getter from its own context.
- ISP meaning of H/L (as for captures).

## 6. Risks

1. **Getter in the image-pipeline context (main risk).** The capture reader avoided this (V02 "fallback
   choice"). Mitigations:
   - The getter is called only for COLOR live-view developments while some COLOR slot has H/L on.
   - The getter is lock-free and read-only, and handles cores 0–2. Getter calls are common in the pipeline-control
     code (`0x6032xxxx`/`0x6033xxxx`, `0x603b6xxx`–`0x603c2xxx`).
   - A missing key returns 0 → stock.

   Failure mode if wrong: a fault in live view at power-on with a bundle that has H/L on. Recovery is the SD
   restore, as for test 3.
2. **No live-view refresh after an H/L edit** if something downstream skips redevelopment when S is unchanged
   ([I]). The fallback would be a heavier trigger in the editor (S ±1 then back), not part of this patch.
3. **Other no-transport jobs** (e.g. those built by 0x6060dbe3, which writes params+5538 itself; RAW
   development) now get the *current* profile's H/L instead of stock. RAW development also takes its saturation
   and profile from the same global properties, so this is consistent, but it is a behaviour change.
4. Profile switch race: a live-view frame developed during a profile change can use the new H/L with the old S
   for one development. This is cosmetic and transient.
5. Integration: test12d must merge this after the bundles reader (labels) and keep 0x603b02de free.
   MONO-colour (not in 12c) also jumps to 0x603b02de and is excluded by the key check.

## 7. Notes for the art-filter live-view work (docs/LV_ART_PREVIEW.md)

These are side findings from this trace. They were not followed further.
- Live-view and movie development jobs are created in the IPCR handler **`0x60321d36`**, by the constructor call
  at 0x60321ea8. That handler builds the job effect-flag word from the request+20 bitfield at
  0x60321d97–0x60321e50 (FUJI_GAPS §5). Job parameters come from the live-view request R in **`0x603220e5`**, which
  calls `0x60323a30`, then `0x60324071` (R → params, the full field list is at 0x60324081–0x603244af), then
  `0x60322f26` (blocks R+720/804/888/2160/2936 → params+4260/4324/4388/6208/6072, key 2059/772/0). [V]
- Stage dispatcher **`0x603aaced`** selects by request+16 (kind) and request+28>>8 (sub-kind):
  - kinds 0/16, sub 1/2 → `0x603b17e6`/`0x603b1819` → stage list `0x603b1466` (colour selector, gamma, …);
  - kind 3, sub 4 → `0x603b18b5`; kind 3, sub 3 → `0x603b1861` (key 772) / `0x603b1843`; kind 4 → `0x603b18cd`.

  `0x603b1843`/`0x603b18b5` run stage list `0x603b1517`, whose colour step is **`0x603b0345`**: request+52 ==
  0x0101006c with key 513 → table `0x605167e4`; 0x0101007c with key 2818 → table `0x6051d258`. Both then go to the
  alternate builder `0x603afb94`. These are art-filter-specific COLOR tables. [V code; I meaning]
- In the plain selector `0x603b0252`, request+1524 ≠ 0 with context+60 bit 0x10000000 → `0x603afb94` uses the
  table object at (request+1524)+16. That is a third art-filter colour-table route, and it bypasses both `hl` and
  `lv`. [V]
