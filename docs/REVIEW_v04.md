# Independent review: E-P7 1.1 custom firmware v0.4 full build (`edits_full.json`, 138 edits, main 0x100 only)

Reviewer: independent and adversarial, offline only. No device was contacted, no `E142*`-named file was created,
nothing was committed. This file is the only one written in the repo. Scratch work (builds, scanners) is in the
session scratchpad (`rv4/`).

Method: everything below was re-derived from bytes:
- `mn10300-elf-objdump -m am33-2` on the stock decoded main and on the patched payload taken from the rebuilt package;
- a numpy brute-force scan of every relative branch/call encoding (c0–ca, cc/cd, dc/dd, f8 e8–eb, fa ff, fc ff) at
  every byte, plus abs32 values (0x6… and 0xA… aliases), run on the **patched** image;
- an independent package check (fishcu's `oly_container` parser, plus my own word sums).

The authors' documents were used only as a map. [V] = verified here from bytes. [I] = inference.

## Inputs

| Item | sha256 / result |
|---|---|
| `releases/v0.4-candidate/edits_full.json` | `b707fee3…ab38` (matches the README) |
| Stock container | `9d161012…eaeb`; decoded main `5dd9af16…` == stock main payload [V] |
| Rebuilt `patched.pkg.bin` | `6517c741…da48` (matches the README) |
| Rebuilt `restore-stock.pkg.bin` | `245b9c8f…2612` == `stock[0:26214400]` byte for byte [V] |

## Verdict

**Not cleared for flashing, combined or feature by feature, until the install and recovery paths are shown to
work (B1).** The code has improved since v0.3:
- H1 (grain gate) and M1 (aspect alignment) are fixed in the bytes.
- H2 (load) is mostly mitigated: grain and bloom are now per slot and mostly off. However, WB overrides are **on**
  by default in all four COLOR slots (M2-new).
- I found no instruction-boundary, stack, register or code-space defect in any v0.4 hook.

The main new finding: **the SD bundle loader can never run.** Its hook sits on a statically dead path (H1-new). In
safety terms that makes it inert. But its whole verification is moot, and the obvious fix (re-hooking the live
mount path) would bring in the risks listed under H2-new.

## Findings

### Blocker

**B1. No demonstrated install path and no demonstrated recovery path (procedural; supersedes v0.3 H4).**
- The SD updater rejected both the exact stock main-only file and the official full 1.1 file (SD_REJECT.md). The
  cause is open, and the leading hypothesis is that the OK+power updater is not the FIRMUP_CLI that was analysed.
  So there is currently **no known way to install any patched package**. The SD_REJECT recommendation not to try
  patched files over SD is correct.
- Recovery "via OM Workspace over USB" is [I]:
  - The USB PTP handlers (0x9121/0x9123 …, 0x60c4…) live in **main**. Any patch that breaks boot before the PTP
    stack is up also kills USB recovery.
  - OM Workspace is a host application that normally offers only a *newer* official firmware. Whether it will
    re-flash 1.1 onto a camera that reports 1.1 is undemonstrated (SD_UPDATE.md §5 says so itself).
- The flash writer programs the **whole** main component (dst 0x806a0000, size 0x1900000; SD_REJECT §1). So the
  torn-write exposure is all 25 MiB for *any* main flash, including the restore. The "changed 1-MiB blocks" metric
  (now 10, versus 8 for v0.3) does not reduce that risk.
- Required before anything goes on the camera:
  1. Find a path that writes main and has been demonstrated with stock bytes.
  2. Demonstrate a same-version restore through it.
  3. Separately confirm that OM Workspace will offer or perform a 1.1 → 1.1 re-flash.

### High

**H1-new. The SD loader hook is on a dead path: the loader never executes.** [V]
- In method 0x60863da7, `(20,sp)` is written exactly once (0x60863db0, the old value of `obj+164`). At 0x60863e4b:
  ```
  60863e4b  58 14        mov (20,sp),d0
  60863e4d  a0 03        cmp 3,d0
  60863e4f  c8 13        beq 0x60863e62      ; only reached with d0 == 3
  ...
  60863e62  a0 00        cmp 0,d0           ; d0 is still 3
  60863e64  c9 33        bne 0x60863e97     ; always taken
  60863e66  …            (0x60863e66–0x60863e94, incl. the hooked call 0x60863e90: unreachable)
  ```
- The scanner finds no other branch, call, jmp or abs32 reference to any address in 0x60863e64–0x60863e94.
  0x60863e62 is reached only from 0x60863e4f, and 0x60863e81 only from 0x60863e6f/0x60863e79, which are inside the
  dead block.
- The live mount-status writes to 0x6077d590 are elsewhere: 0x608658f6, a loop over 4 media that logs first, and
  0x6093a318/0x6093a368.
- `ep7_verify_sd_bundles.py` starts the emulator *at* pc 0x60863e90, so it cannot see this. SD_BUNDLES.md §2 calls
  the site "[V] runs exactly when the app records a successful mount". That is not supported.
- Consequences:
  - The 4-byte edit and the 564-byte blob are dead weight. They are harmless, but the planned first camera check
    ("a valid file changes COLOR1") will fail.
  - **Remove `sd_bundles` from every camera build** until it is re-hooked and re-reviewed.

**H2-new. Conditions for any re-hook of the SD loader (these are design defects if the hook is simply moved to
0x608658f6).**
1. **Section-load order.** Sections load asynchronously. 0x600457e7 copies one section and sets bit n−1 in
   0xa272e420. Tasks wait in 0x6004586c(n), which spins on that bit; boot calls it for n = 2…9 at
   0x60190e18/0x60191347…0x60191bce. The order is 1,7,2,3,4,5,6,8,9.
   - The live mount code is in **section 5**, and the loader is in **section 6**, which loads *after* 5.
   - At boot, with a card inserted, a section-5 mount callback that runs before section 6 is loaded would jump into
     uncopied RAM.
   - The same function also programs the 0x99700000 unit with region [start(sec n+1), end(sec 9)] until n = 9
     (0x60058c66 → regs 0x99700058/5c). Its semantics are unknown (access monitor or attribute region) [I].
   - So the loader code must live in a section that loads before the hooking section (sec 1 or 7: sec 7 has 116 B
     free, sec 1 has 146 B), or the hook must be proven to run only after wait(9).
2. **Task context and deadlock.** The task that runs the live path is unproven. If it is FILEFGND, or any task
   FILECLBK waits on synchronously, the six blocking fileif round trips deadlock at every boot with a card in.
   - Escape: remove the card, which keeps the hook from firing.
   - Stock precedent that helps: section-5 app code already calls fopen (0x60765cc8).
3. **The live site is inside a 4-iteration loop with a logger call before it.** The frame and d2/d3 contract
   differ from the dead site, so the register/stack proof has to be redone.
4. The write targets were checked and are fine:
   - The 0x60210900–0x60210aff table does not share a cache line with code (v0.2 code starts at 0x60210b00, which
     is 256-aligned).
   - Sections are loaded only by the boot loader 0x600457e7 (9 callers, all in 0x60044f2d–0x600451d0), so nothing
     reloads them over a runtime write.

**H3 (v0.3) Aspect, carried unchanged.** The persisted id 6/7 still drives a partially re-geometried pipeline
from boot, with no physical escape.
- The ×16 rounding (below) removes the alignment concern only.
- The untraced consumers listed in v0.3 (grid selector, Art/bracketing/tele-converter, 18 key-0x3081 sites, ratio
  codes 0x1841/0x0915, runtime `.data` rewrites) are all still untraced. The u16whcode rows still carry the new
  ratio codes 6209/2325.
- With B1 unresolved, this remains the single riskiest feature. Test it last.

### Medium

**M1-new. MONO grain on colour-rendered MONO slots.** MONO-colour leaves the mode-12 grain work-list and
request+1828/1829 in place (MONO_COLOUR.md admits this).
- A colour MONO slot with the user's MONO grain or shading on therefore runs stock's two-pass MONO grain/mask route
  over a colour development. Stock never does that.
- This is an ISP path combination that has never run, comparable to v0.3 H1.
- Not active in the shipped table (no slot has `colour == 1`). Mitigation: force grain/shading Off in MONO-colour
  tests, or gate the mode-12 grain list on `colour != 1`.

**M2-new. WB override is on by default for COLOR1–4** (`wb_flags` = 1; A/G = +2/+1, +3/+1, 0/0, +2/0) [V].
- In every non-CWB WB mode, including Flash (idx 15) and Auto (idx 1), it silently replaces the user's stored
  fine-tune. COLOR3's 0/0 cancels any stored fine-tune.
- This runs against the H2 "off by default" principle. It also contaminates any "single feature" camera test built
  from `edits_full.json`.
- Live view is not covered (WB_PATCH.md), so the EVF may not match the file.

**M3-new. The 0x99700000 region guard covers section 7 until wait(7).** [I]
- The MONO-colour stubs (section 7) are reached from section-2 hooks: selector 0x603b02bf, chroma 0x603b134e, packer
  0x60353db9.
- If any of them ran during boot before wait(7), they would be inside the guarded region. In practice they are
  shot-time paths. Stock code in section 7 is also called early (0x612c7754), which suggests the guard does not trap
  execution.
- Recorded so that the rule is "hook target section must be ≤ the section number already waited for", not merely
  "loaded earlier".

**M4 (v0.3 M2) Stored aspect 6/7 survives a restore.** Unchanged.
- v0.4 adds no other persisted setting:
  - WB, MONO-colour, grain and bloom only read stock properties and the flash table;
  - video log uses only stock values;
  - the SD loader stores nothing.
- Set 4:3 before any restore, re-flash or saved/custom set.

**M5 (v0.3 M3/M4) Video log, live-view path and profile encoding 1..4.** Unchanged and still undemonstrated. The
profile-encoding assumption now also governs WB and MONO-colour slot selection.

### Low

**L1. WB getter redirect (14 sites) is sound** [V]:
- All 14 rel32s point to 0x6055e700. The RAW sites 0x60c68a45/59 are stock.
- Each site is `mov 0,a0 … call 0x6005e971,[d2,d3],12`. The stub exits either through a tail jump to the stock
  getter on the site frame (pass path) or `ret [d2,d3],12`.
- Its helper calls go through the real getter, and every key it uses has stock reads (33057, 38017, 40209, 63153 and
  63281 via `mov imm32` at 0x602a85a3/af etc.).
- Extra cost per redirected read: 3–4 getter calls and +16 B of stack, in the same contexts as stock. There is no
  state and no lock.
- Consumers store the result with movhu/movbu, and the sign extension matches the type-9 getter.

**L2. MONO-colour stubs.** [V]
- Each stub moves sp before storing to it.
- `sel` runs the colour branch only for mode 12 + the request guard + marker 0xB2 + `colour == 1` + all ranges.
- The stock tail after 0x603b02de uses only a2, so the different a3 (slot.sat) is dead.
- `fg` writes job+5564/5565, the same bytes stock writes through `params+5528` (a2 = job+36). 0x60353de9 overwrites
  d0.
- Inert with the shipped table.

**L3. Bookkeeping.**
- The MONO-colour builder's reservation list still names the v0.3 layout. It doesn't matter for the bytes: the
  packager rejects overlaps, and I re-checked all ranges.
- SD_BUNDLES.md §2 and CODE_SPACE_MAP should mark the SD site as dead (H1-new).

## v0.3 findings: status

| v0.3 item | Status in v0.4 | Evidence |
|---|---|---|
| H1 grain job-type gate | **Fixed** [V] | wl_hook 0x60210cee–0x60210d0a replicates 0x6035778b exactly (`movhu (16,a2)`; `&0xf0 ∈ {0x10,0x20,0x40}` or `&0xf00 == 0x100` → default 0x603578a9). It then requires marker 0xB2, ext mode 11, profile 1..4, and a slot grain of 1..3. |
| H2 per-shot load | **Mostly mitigated** [V] | Shipped table: grain only on COLOR3 (low); bloom on no slot (COLOR4 effect_id 2 = halation, not consumed); MONO colour on no slot. Remaining per-shot additions: COLOR3 combiner 32, and the WB override (M2-new). |
| M1 aspect alignment | **Fixed** [V] | All 86 id-6/7 rows decode from the `new` bytes to the stated values, and every width and height is a multiple of 16. Thumbnail 160×64 sits in a class whose stock heights are 120/108/90/114, so it is in family. |
| H3 aspect mixing | Open | Unchanged (see above). |
| H4 restore/update | **Worse in practice** | Now B1: the SD path rejects even stock files, and USB recovery is undemonstrated. |
| M2 aspect persists | Open | Now M4. No new persisted values. |
| M3 video log / M4 stock assumptions | Open | Now M5. |

## Code space, loaders and references [V]

Loader descriptors 0x60027068: dst == src + 0x1F980000 for all 9 sections, so every section loads in place.
Section ends come from end getter 0x60045786 / table 0x60046780.

| Section | Load range | Stock data ends | v0.4 placements | Gaps |
|---|---|---|---|---|
| 1 | 0x600d7800–0x60211000 | 0x602108eb | 0x60210900–c70 (v0.2), c90–cba (vlog), ce0–dde (grain), e10–eea (bloom), f00–f6e (aspect) | all FF |
| 2 | 0x60280800–0x6055e800 | 0x6055e5af | 0x6055e700–7a4 (WB) | all FF; the old grain/bloom ranges are FF |
| 6 | 0x60ba7000–0x61243000 | 0x612429af | 0x61242a00–c34 (SD, dead), f00–f60 (aspect list) | all FF |
| 7 | 0x612c7000–0x61379000 | 0x61378c67 | 0x61378c80–f7c (MONO-colour) | all FF |

- References into each tail from outside, in the patched image, are only the intended hook sources (8 into
  section 1, 14 WB sites into section 2, 3 MONO hooks into section 7, the SD hook into section 6) plus the aspect
  jump entries and descriptor and the table address constants.
- Every other hit was checked by disassembly and is a data false positive: 0x6020ec90 (pointer table),
  0x6055e59d–a9 (pointer table), 0x611e2a34/b28/bdc/cd0/d84 (12-B record table), 0x607a21ea.
- No branch of any encoding and no abs32 lands inside any code-hook span. One hit, 0x60302ff7 → 0x60302f90+, starts
  mid-instruction (`cmp 155,d0`).

## Interactions [V unless noted]

- **Table readers.** v0.2 H/L, WB, grain, bloom and MONO-colour all read the 0x60210900 table, each range-checking
  its own bytes. The SD loader's range table matches `layout.json` (colour 0..1, sat −5..5, …). It is dead anyway.
- **Section-2 hooks.** COLOR selector: MONO-colour `sel` hands mode 11 back to 0x603b02c5, which falls into the
  v0.2 jmp at 0x603b02d9, so the paths stay disjoint. On the colour path `sel` calls the builder itself and does
  not go through 0x603b02d9.
- **Grain and bloom vs MONO-colour.** Grain and bloom key on ext mode 11 only, so a MONO-colour slot gets neither,
  but it does get stock MONO grain (M1-new).
- **WB vs MONO-colour.** WB applies to MONO slots by profile, independent of `colour`. That is fine.
- **v0.2 converter/transport.** Unchanged from v0.3: the 880-B blob differs from v0.3 in one table byte only
  (0x60210958, COLOR2 grain 1 → 0), and the transport sites are identical.

## Package and restore [V]

- The single component is 0x100.
- Header == stock, trailer[0:28] == stock; only trailer[28:32] (the checksum) differs, and it validates.
- The decoded payload == stock + the 138 edits exactly (every `expect` matches). There are 3,504 changed bytes.
- The restore is exactly `stock[0:26214400]`.

## Recommended camera test order (only after B1 is resolved; one feature per package, with a stock restore between)

0. Prove a write path and a same-version stock restore. Confirm whether OM Workspace will re-flash 1.1 → 1.1.
   Full battery, card formatted in camera, aspect 4:3, picture mode not COLOR/MONO, mode dial off movie.
1. **rec_limit** (4 B, movie only). This proves the patched-install path at minimal risk.
2. **video_log**. It runs at boot but is tiny and verified. Stills in Muted, then 4K/FHD movie.
3. **bundles v0.2 alone**. Converters run on every shot. P/Natural first, then COLOR1–4 single frames.
4. **bundles + WB** (one slot with `wb`, the rest `null`). Check the capture A/G against the menu values, the EVF,
   and Flash/Auto.
5. **bundles + grain** (COLOR3 low). Single frames, then special capture modes and burst.
6. **bundles + bloom** (one slot, strength 1). Single frames, then sequential/burst stress.
7. **bundles + MONO-colour** (one colour slot, MONO grain/shading Off). Single frames, then with MONO grain on, only
   if M1-new is accepted.
8. **aspect**, last and alone. Every size, JPEG/ORF, LV/info screens, playback. Return to 4:3 before any further
   flash.
9. **SD loader:** excluded. Re-hook it under the H2-new conditions and get a fresh review first.
10. Combined build only after 1–8 pass and the restore has been re-proven.
