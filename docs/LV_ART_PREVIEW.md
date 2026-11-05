# Live-view preview of our looks through the Art Filter LV pipeline (E-P7 1.1)

Offline static analysis plus emulator runs. Nothing here has run on a camera, and no SD-update-named file was
made. Decoded main `5dd9af16…6190`, CPU base 0x60020020. Addresses were read with `tools/dis.sh` and
`tools/ep7_xref.py`. Phase 1 is built in `patches/lv_art/` and emulator-verified; it is **not cleared for
flashing**.

Labels: **[V]** read from bytes or disassembly, or run in the emulator. **[C]** seen on a camera.
**[I]** inference.

Coordination: `patches/lv_bundles` (another agent; there is no docs/LV_BUNDLES.md yet) previews H/L in live view
from the COLOR selector, for jobs **without** the capture transport. Phase 1 here gives live-view jobs that
transport, so the stock-path `hl` runs instead and `lv` steps aside (it returns on marker 0xB2). Both give the
same H/L, so either one or both can ship. Phase 1 does not touch lv_bundles, look_editor or look_extras files.

## 0. Short answer

- **Art Filter LV is not a separate engine.** Live view (and movie) frames are developed by the same job
  constructor `0x603537eb` and the same work-list builders as stills. They are called from the record path:
  record → 40-byte development request `0x603114e0` → IPCR handler `0x60321d3b` → constructor at `0x60321ea8`.
  Effects are the same **job flag bits**. LV jobs get a record-path job type (0x3x), which maps to **job classes
  5–8**. The work-list builders pick the **cheap variants** for those classes [V].
- **The simplification [V]:** Soft Focus in classes 4–8 is a single entry `0x6035cc1b`. It reduces the frame to
  144×108 (class 8) or 144×80 (classes 5–7), then runs **one** blend pass (effect 0x0403 → combiner 12). That
  pass upscales the small buffer as it blends. Stills use three passes: reduce to 160×120, a full-size upscale,
  then the combiner-11 blend. Grain uses the single-pass combiner 32 (stage 0x0902) in classes 4–9, and never the
  two-pass mask route.
- **Why our looks don't show in LV [V]:** every per-profile reader (bundles `hl`, `bloom_w`, grain `wl_hook`/
  `grain_mod`) checks the job's capture transport (job+15488..15490). Only the still converters write it.
  `bloom_flag` (which sets job flag 0x80) is also converter-only.
- **Can our looks drive it in COLOR modes? Yes, without any mode switch.** One hook in the constructor, just
  before dispatch, gives COLOR live-view jobs the same transport as a capture. For a bloom slot it also sets
  flag 0x80. The stock work list then attaches the LV Soft Focus pass (bloom preview), and `hl` applies the
  slot's H/L. Grain is optional. **Built:** `patches/lv_art` (177 B, 2 edits). Emulator: all functional checks
  pass and every mutation is detected (§5).
- The camera still has to show that this route really is the LCD live view, and what it costs at preview rate
  (§4).

## 1. How LV selects and configures the art-filter preview

### 1.1 Settings → record → request [V unless marked]

| Item | Where | Notes |
|---|---|---|
| Picture mode | property `0x9481` → rec68+29 (VIDEO_LOG X1); in the record block A+352.. copied to **record+292..309**: +292 MovPicModeType, +293 MovPicMode, **+294 picture mode** (11 COLOR, 12 MONO, **≥ 100 = art filter**), **+295** art sub-variant/level byte (tested `== 0` by `0x60316bc7`), **+296 Art Effect id** 0..9 | offsets from `0x60312f42` / `0x60316bc7`; the meanings of +292/+293 come from VIDEO_LOG [V]. The +295 meaning is [I] |
| COLOR profile number | property **0xF6B1** (setting 908), stock getter `0x6005e971` | not in the record; patches/lv_bundles reads it the same way |
| Key (job+11308) | `0x60316bc7` → mapper `0x60324d6b` → `0x60349297`. Art filters → `0x0101_00yy` (I) / `0x0102_00yy` (II) / `0x0103…` (III); COLOR → 11; MONO (rec+817 == 143) → key 12 | the per-filter id table is in BLOOM_HALATION §1 |
| Effect bitfield (request+20, 12 bits) | **`0x60312f42`**: clears bits 0–7 and 9, then sets bit 11 if picture mode == 12. **Only if picture mode ≥ 100** (and the record test `(24,sp)` == 0 and the caller's d0 == 0) does it map the Art Effect through the jump table `0x604e18f0`: 1 Soft Focus → bit 1, 2 Pin Hole → bit 4, 3 Frame → bit 9, 4 White Edge → bit 7, 5 Star Light → bit 0 (only if rec+176 == 0 and rec+902 ≠ 8), 6/7 Diorama → bits 2/3, 8/9 Shade → bits 5–6 = 1/2 | **This is why COLOR in LV never gets an effect: the Art Effect is ignored unless an art filter is selected** |
| Request → params | `0x60321d3b` (synchronous, `call` from `0x6031178a`): the bitfield becomes the **same job flags** as stills (bit 0 → 0x40, 1 → 0x80, 2–3 → 0x300, 4 → 0x400, 5–6 → 0x1800, 7 → 0x2000, 8 → 0x4000, 9 → 0x8000, 10 → 0x10000, 11 → 0x800000) into params+12; the key goes to params+8, and the job type (msg+24) to params+16 | `0x60321d97–0x60321e52` |
| Job type | `0x60313931` (record): low nibble from rec+878 (6 → 4, 3 → 3, 4/7 → 2, 8/9 → 5); high nibble **0x30** (rec+808 == 1, or rec+902 ≠ 8), **0x40** (rec+902 == 8), 0x00 + 0x2000 (`0x6031353f` == 1); +0x100 if rec+276 ≠ 0 | |
| Job class (job+11341) | `0x603b551d`: type 0x3x → by params+30 (from rec+902 via `0x60323911`): 15/17 → 5 or 6, 22/23 → 7, 14 → 5/6/7, 18/19/20 → 5, **else 8**; 0x4x → **9** | Still converters produce types 0x0/0x110/0x120/0x1000 (GRAIN_PORT T6) → classes 0–3 |

[I] Class 8 (4:3, 144×108 reduce) is stills-mode LV, classes 5–7 (16:9, 144×80) are movie formats, and type 0x40
(class 9) is a recording job. Basis: the reduce-size table `0x604eb450` (144×108 for 4/8/9, 144×80 for 5/6/7), the
type-0x40 strip (it removes almost every effect, as stock movie does for some formats), and the Star Light test on
rec+902.

### 1.2 Constructor: key → flags, strips [V]

`0x603537eb`:
- **Art keys** (key byte 0 == 1): hash `0x60521a54` ORs per-filter flags. Soft Focus 0x01010065 → 0x80;
  Pin Hole I/II/III → 0x200000/0x400000/0x600000 (skipped when params+23 == 1); Diorama → 0x100/0x200;
  Vintage → 0x20000/0x40000; Rough Mono / Dramatic Tone II → 0x800000; 0x01010073 → 0x40. Then the type
  strip `0x60353b15`: type&0xf0 == 0x40 or type&0xf00 == 0x100 clears 0x40/0x80/0x300/0x4000/0x40000/
  0x100000, and type 0x40 also clears 0x400/0x1800/0x2000/0x8000/0x20000/0x600000. Classes 4–7 clear 0x40
  (Star Light).
- **Key 9/11** → 0x80000 (COLOR shading); **key 12** → 0x80000 | 0x800000. Type 0x40 and params+22/+26 ≠ 0
  clear 0x80000. **The art strip never runs for key 11**, so a key-11 flag survives in every type.
- Dispatch `0x60354709` (pre-dispatch hook point `0x60353c6f`): params+22 ∉ {0,4} → `0x6035d9f7`;
  params+27 ≠ 0 → `0x603562a0`; key byte 0 == 1, or key byte 0 ∈ {0,2} with flag 0x80000 → builder
  `0x60356297` → `0x60357415` (the per-key work list, then the effect bits); otherwise `0x603666c7`.

### 1.3 Stages in the LV classes

| Stage | Flag / key | LV variant (classes 4–8) | Status |
|---|---|---|---|
| Soft Focus glow | 0x80 | `0x6035cc1b`/cb `0x6035cd94`: reduce `0x6035cee6` (0x1000 → 0x1060, 144×108 or 144×80, 4 B/px) + **one** kind-3 pass stage 0xf005 effect **0x0403** with request+20 = image and request+84 = reduced buffer (format 0x0302) → **combiner 12** (weights swapped vs combiner 11) | [V] code |
| Soft Focus weight | getter `0x6039fee8` | 0x01010065: table `0x604ec02e` by level (request+1832/+708); key 11: 600 (stock) or `bloom_w` (bundle W) | [V] |
| Grain | key 12 / our `grain_mod` | single-pass stage 0x0902 → combiner 32 (gain 50/75/100). Stock MONO LV has level 0 (the LV params never carry +5551), which is why the manual says grain "cannot be previewed" | [V] code, [I] reason |
| Star Light | 0x40 | stripped in classes 4–7; class 8 keeps it | [V] |
| Diorama / Pin Hole / Shade / Frame / White Edge | 0x100–0x8000 | same flag → same work-list code; their class 4–9 variants were not traced | [I] |
| Colour / tone (art colour curves, Pop Art, Pale, etc.) | per key | the same selector/colour builder and tone selectors as stills (`0x603b0252`, `0x603b039b`, `0x603ae354`), keyed on the job key; no LV-specific tables seen | [V] same code path; [I] no LV-only simplification |
| Our H/L | `hl` at `0x603b02d9` | runs for every key-11 development; acts only with the transport | [V] (patches/lv_bundles verifier L/K) |

## 2. Can the LV path run in COLOR modes with our parameters?

**Yes, for bloom, H/L and grain, through the transport, with no mode switch** (the key stays 11, so COLOR's
colour and tone are untouched).

| Look element | LV route | Confidence |
|---|---|---|
| Bloom (effect 1) | flag 0x80 → stock LV Soft Focus entry (combiner 12); transport → `bloom_w` returns the slot's W (942…666) instead of 600 | **High** for the CPU side [V emulator]; medium that it reaches the screen at preview rate |
| H/L | transport → bundles `hl` (identical to the capture output; patches/lv_bundles' L test shows that capture-path `hl` output == the slot) | **High** CPU side; medium-high for the screen |
| Grain | transport → grain `wl_hook`/`grain_mod` (type 0x3x passes its job-type gate) → 0x0902 single pass. **Opt-in** (`--features …,grain`) | Medium (stock never runs grain in LV; the hardware path is the same one stock MONO uses for classes 4–9) |
| Clarity (effect 3) | combiner 12 gets w = 1024 from `bloom_w` (c12_lut, chosen deliberately in CLARITY §2.2) → no visible change. lv_art therefore **does not set 0x80 for clarity**. Phase 2b below | High that it is invisible now |
| WB A–B / G–M | not a job stage: the WB patch already redirects the compact-record WB reads (`0x6030bb5b/6e`, `0x6030eb61/77`) through `wb_get`. When LV refreshes them is untraced (LOOK_EXTRAS §4) | Medium (separate trace) |
| Hue/light approximation through art colour curves | not needed: `hl` runs in LV once the transport is present | – |
| Halation, vignette | not built for stills either | – |

**Rejected:** switching the key to an art filter (e.g. 0x01010065) to get its LV path. That would replace COLOR's
colour/tone tables with the filter's, and the Soft Focus key's weight comes from the art level, not the bundle.

## 3. Hook list

| # | Site | What | Confidence | Status |
|---|---|---|---|---|
| H1 | **`0x60353c6f`** (6 B, `9c cd990ab010` = `mov a3,a0; call 0x60354709,[d2,a2,a3],16`), constructor pre-dispatch | gate: return word (44,sp) == **`0x60321eaf`** (the only constructor call in the IPCR handler), key 11, type&0xf0 == 0x30 and type&0xf00 ≠ 0x100, profile 1..4 from 0xF6B1; slot wants H/L or bloom (grain only if built in) → transport job+15488..15490; bloom → job+16 \|= 0x80; replay; resume `0x60353c75` | High (CPU) [V F/H/C/D] | **built** (`patches/lv_art`) |
| H2 | `0x60312f42` tail (Art-Effect switch, picture mode ≥ 100 gate) | alternative to H1's flag: set request bit 1 for COLOR | Medium | not needed (H1 covers it) |
| H3 | `bloom_w` c12_lut (patches/bloom) | LV clarity: return w > 1024 for combiner 12 **only** for jobs whose type is 0x3x | Medium-low (combiner-12 input order and the sign in mode 0x00200001 are unproven) | design |
| H4 | compact WB reads (WB patch sites) | LV WB follows the slot | Medium | trace needed |
| H5 | reduce-size table `0x604eb450` | larger LV glow radius | Low (global: changes stock Soft Focus) | no |

Placement: H1 code is in the dead EVF gamma **step-13 R** table `0x601e113c–0x601e123c`. Its only reference is the
step-table word `0x601e3d50`. The argument is the same as for View Assist (test 11 [C]), lv_bundles (step 14) and
look_extras (steps 1–2). It avoids every claimed range, including 0x601e323c–0x601e383c, 0x60b9dd10–0x60b9e000 and
0x6143a400–0x6143a800.

## 4. Cost and risks

1. **[I] Is this route the LCD live view?** The evidence is structural. The IPCR handler is the only
   constructor caller outside the still converters (`0x603e39c7`, `0x603e6d3e`, `0x603ebcac`, `0x603f0e60`,
   `0x603f283e`, `0x603f2bb9`) and RAW edit (`0x6060dbe3`). Its effect bitfield is honoured only for art
   filters, and only Art-Filter LV/movie can show Art Effects. It produces the 0x3x types that select the
   144×108/144×80 LV variants. Its mapper `0x60316bc7` drives the camera-proven log movie (test 2 [C]).
   There is also a per-frame **stream job** (`0x60350e0d`, 15440 B, pointer `0xa27326fc`, run by
   `0x6031106f` → `0x60350eff`). It carries no key/flags work list and was not tied to the development job.
   If live view in stills mode were developed only through it, H1 would preview nothing (stock look, no
   harm). **The first camera test decides this.**
2. **[I] Frame rate.** The bloom preview adds a 144×108 reduce and one blend pass at LV size. This is exactly
   stock Soft Focus LV, which the E-P7 runs live (only Diorama and Dramatic Tone are reported to slow LV).
   H/L costs nothing (tables). Grain adds one combiner on the development pass.
3. **[I] Buffers.** The reduce needs a small 0x1060 buffer (~62 KB) from the job buffer pool (`0x60350560` ≥ 48
   → error 0x9ec3/0x9ece). Stock Soft Focus LV does the same. A failure is an LV job error, not a write.
4. **[I] AF / LV processing.** Contrast-AF evaluation and exposure run on pre-development data, not on the
   developed through-image. Stock Soft Focus LV keeps AF working, so the glow should not change AF. Face
   detection may see the softened image, as it does in stock Soft Focus.
5. **[V] When it runs.** Every key-11 record-path job of type 0x3x is built through H1. That covers stills LV,
   and probably movie-mode LV and FHD recording (classes 5–7). **So the bloom/H/L slot will also be recorded
   into movies made in that profile** (type 0x40 recording jobs are excluded). Movie Art filters in stock are
   limited to non-4K/non-high-speed. Before release, test 4K and 120p in a bloom profile. A follow-up can
   restrict H1 to class 8 (stills LV) in one compare if needed.
6. **[I] Refresh.** Whether the LV job is rebuilt per frame or per settings change is untraced. If per change,
   switching COLOR1→COLOR2 rebuilds it (the record changes with the profile's S values). An editor change to a
   bundle (look editor) would show at the next rebuild.
7. **[V] State.** No RAM state, no stores outside the job and our stack frame, and no stores into
   0x60020020–0x6191ffe0. The getter call is the same stock read patches/lv_bundles uses, made from the record
   task, where this module already calls it natively (the WB sites `0x6030bb5b`, `0x6030eb61`).
8. **Mode switching:** none. The picture mode stays COLOR, and stills are unaffected (the still converters' call
   sites fail the return-word gate [V F/H]).

## 5. Phase 1 build and verification (`patches/lv_art`, `generated/lv_art/`)

```
.venv/bin/python -I patches/lv_art/build.py --base releases/test12c-editor/edits.json --out generated/lv_art/default
.venv/bin/python -I patches/lv_art/build.py --base releases/test12c-editor/edits.json --out generated/lv_art/grain --features hl,bloom,grain
.venv/bin/python -I patches/lv_art/verify.py generated/lv_art/default/merged.json --jobs 8 --json generated/lv_art/default/verify.json
```

| Check | Result |
|---|---|
| S static: hook bytes; no branch/abs32 into the hook interior; only `0x601e3d50` references the placement; store audit = 2 stack + 3 transport bytes + job+16; changed bytes in spans; rest of the LUT stock | PASS |
| F real constructor from the real call at `0x60321ea8` (and still site `0x603e6d3e`) with alloc/memset stubs: (44,sp) at the hook == `0x60321eaf` (resp. `0x603e6d45`) | PASS |
| H patched vs base, 4 tables × profiles 0–5/255 (28 runs; 24 in the mutation quick set): job == base except the transport/flag, which equal the model; regs, sp, dispatcher a0 and caller stack == base | PASS |
| H gates (22): other return words, keys 12/9/0x01010065, types 0x40/0x10/0x20/0x00/0x1xx/…, missing registry entry → byte-identical to base | PASS |
| C CPU 1 (getter via the per-core translator), D SD-loaded table (flashed copy poisoned) | PASS |
| R `bloom_w` on combiner 12 (base image): with the transport +140 = W (942/819/666), +96 = 1024 − W; without it 600/424; a clarity slot gets 1024/0 | PASS |
| M mutations (15: return word, frame offset, key, type nibble, 0x100 test, property id, profile bound, marker, flag bit, mode, strength bound, d2 restore, H/L bit, hook left stock, hook skips the routine) | **15/15 detected** (default and grain builds) |

Package: test12c + lv_art = 104 edits. No test package or card file was made.

**Camera test plan (when cleared):** (1) A slot with bloom 5 and H/L off: in live view, compare COLOR (that slot)
with the stock Soft Focus art filter. Expect a gentle glow, much weaker than Soft Focus at level 0. (2) A slot with
an obvious H/L (greens +7): live view should match the shot. (3) Half-press AF, burst, and movie FHD/4K/120 in the
bloom slot. Watch frame rate, AF and the recorded file. (4) Grain build only after 1–3.

## 6. Phased plan (cheapest visible win first)

| Phase | What | Size | Confidence | Status |
|---|---|---|---|---|
| **1** | H1: transport + flag 0x80 → **LV bloom + LV H/L** (grain opt-in) | 177 B + 6 B hook | High CPU / medium screen | **built, emulator-verified** |
| 1b | camera test; if movies must stay clean, add a class-8-only gate (job+11341 == 8) | +6 B | – | after test |
| 2 | LV WB: trace when the compact-record WB reads run in LV; if they run only at LV start, add a refresh | trace | medium | open |
| 2b | LV clarity: `bloom_w` c12 path returns w > 1024 only for type 0x3x jobs; flag clarity slots in H1 | ~20 B in patches/bloom | medium-low (input order, sign) | design |
| 3 | grain in LV (`--features hl,bloom,grain`) | built | medium | after phase 1 on camera |
| 4 | larger LV glow radius / halation preview | – | low | not planned |

## 7. Refresh trace: why the preview goes stale, and the smallest trigger (answers §4 item 6)

Static only; nothing built or run. Labels as above. Function "entries" are the address after the `call`-saved frame.

**Answer to §4.6: neither per frame nor per settings change.** The job is rebuilt only when a stock comparator says so.

| Step | Site | Fact |
|---|---|---|
| Rebuild comparator | **`0x60311278`** (only caller `0x60329b9b`, in the slot loop `0x60329b2e` ← `0x6032a257`, when rec+832 == 0) | Compares current record `0x60309eb9(1)` with previous `0x60309eab`. Result per slot: 0 no job, 1 unchanged, **2 rebuild**. Q+53 == 2 → 2; Q+53 ≥ 3 → 1 [V] |
| **What stock tests for Art Effect** | **`0x603113cc`** | **rec+296 (Art Effect id) differs → 2**; if id ≠ 0, also rec+808+19/+20 [V]. Others in the chain: `0x603135ee`, `0x603136d9`, `0x603138f0`, `0x603136f5`, rec+652, `0x60313809`, `0x6031385b` (not read) |
| Store | `0x60329bb0..bc8` | Only if the state word is 1: Q+24 (slot 0) / Q+26 (slot 1) = comparator result; Q+28/+30 = its second output [V] |
| Act | `0x6032a706` (← `0x6032a6d8` ← `0x6032b7dd` ← `0x6032b72f` ← `0x6032b2d9` ← `0x6032a958` ← `0x6032a1d6` ← `0x6032936a`) | Word 1 → return, no build (`0x6032a741`). Word 2 → delete `0x60311440` (`0x6032a7df`) then build `0x603114e0` (`0x6032a830`). Other → build (`0x6032a88b`). Then word = 1 [V] |
| Build | `0x603114e0` → `0x6031178a` → IPCR `0x60321d3b` → constructor `0x60321ea8` → lv_art H1 | Other `0x60321d3b` callers: `0x6031b38b` (`0x6031b1a7`, from `0x6032fe40/51`), `0x60313354` (`0x603132ca`, a fixed job for Rec View, no record key seen), `0x6030ff78` [V] |
| Unchanged path | `0x603118d6` (from `0x6032b3db`, `0x6032b9cb`) → `0x60321f75` (reads job+4 **including the job flags**) → `0x603220e5` (writes job+36) | New image parameters on the **existing** job. No constructor, so no work-list or flag change [V] |
| Event 0 | Record state table rows `0x604e3190` + 0xE0·n, 28 events × 8 B; event 0 = `0x6032dd61` / `0x6032ddb2` / `0x6032de23` / `0x6032de8e` / `0x6032dee6`, each starting with `0x6032cba8` | `0x6032cba8` → `0x6030ba2b` is the only LV reader chain of the effective S (LV_BUNDLES §2.3), so a visible S edit implies event 0 [I] |

**Why it goes stale [V code, I that this is the camera symptom]:** lv_art sets flags in the constructor. The art byte is not in
the record, so the comparator says "unchanged" (1) and the job is never rebuilt. A capture rebuilds it. The S nudge in
`patches/lv_art_refresh` does cause event 0, but S is not one of the comparator's rebuild causes as far as read, so it reaches
only `0x603118d6`. H/L still updates because it does not depend on the job flags [I].

**What stock does for a real Art Effect in ART mode [V code]:** the record gets the new rec+296; on event 0 the comparator
returns 2; `0x6032a706` deletes and rebuilds; `0x60312f42` maps the id to flag bits inside `0x603114e0` (`0x60311661`).

**Corrections to the `art_rf.s.in` header [V]:**
- `0x6266a354` = 1 does not trigger a reissue. It means "Rec View developing" (set `0x60332799`, cleared `0x6033289c`), and it makes
  the gate `0x6031d189` **skip** ("E_skip recview", `0x604e2468`).
- `0x6032b997` / `0x6032ba6d` / `0x6031c883(1)` do not reissue the LV job. They post to the Rec View mailbox `0x600410be`
  (ISSUES_19_20).

### Smallest correct trigger (design, not built)

Stateless hook after the comparator, so stock's own rebuild path does the work:

| Item | Value |
|---|---|
| Site | **`0x60329ba2`**, 6 B `f1 e1 81 1d a5 00` (`mov d0,a1; mov d0,d1; exthu d1; cmp 0,d1`) [V bytes]. Replay, then resume at `0x60329ba8` (the `bne`). No branch target in the span by the listing; check with `ep7_xref.py --short` when building |
| In scope | d3 = slot index, a2 = &result (`(a2)` = 1 unchanged, 2 rebuild), d0 = error. Keep d0/d1/a1/PSW for the replay |
| Logic | if d0 == 0, `(a2)` == 1, rec+294 == 11: job = `(0x626693e8 + 8·d3)`; same gate as lv_art (job key 11, type nibble 0x30, not 0x1xx); want = lv_art's flags for the current slot (`0xF6B1` + `tbl_idx`; bloom 0x80, Pin Hole 0x400); if `job+16 & 0x480` ≠ want → `(a2)` = 2 |
| Size | 6 B hook + about 80–110 B stub; no RAM state. Keep lv_art_refresh's nudge as the event-0 source |
| Unverified | job handle in the table == job pointer, as `0x60353cf5` suggests [I]; rec+832 == 0 in stills LV [I]; stub must mirror lv_art's build features exactly |
| Risk | A mismatch that never clears rebuilds the job on every event 0 (LV flicker, not per frame). Stock's own delete + rebuild path, so failure is an LV job error, not a write. Exclude recording (type gate). Emulator check: stub want == lv_art result for every slot/table |
| Alternative | Make `art_rf` nudge the real Art Effect property so rec+296 changes. No hook, but unproven that COLOR's record carries +296, and it touches the user's ART setting. Second choice |

**Camera test:** change Art to Pin Hole in Extras and back to live view: vignette appears at once, without a shot. Same for a Film
pick with/without bloom. Then half-press, burst and a 4K clip on that slot.
