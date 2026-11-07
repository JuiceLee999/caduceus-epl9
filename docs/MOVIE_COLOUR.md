# Colour Profile looks in movie mode (E-P7 1.1): feasibility

Research only (2026-11-06). Nothing built, emulated or flashed. Addresses are main CPU addresses (base `0x60020020`).
**[V]** = read from bytes or code. **[C]** = camera data already in `testdata/`. **[I]** = inference.

Request: take over the movie Vivid picture mode and make it a Colour Profile editor, so video has a separate graded mode.

**Built since this research; see "As built" at the end. It differs from slice 1 below: the record's picture mode stays Vivid and only the job key changes.**

## Verdict

**Feasible, medium-high confidence for the settings and menu side. Whether the look reaches the recorded file is not proven.**
No look has ever been recorded. Stock movie mode never uses picture mode 11 (COLOR), and every look hook requires it.

Smallest useful slice: **movie Vivid renders COLOR4's look, edited in stills mode, no format change, 1–2 agent sessions.**
Before that, try a **2-byte probe** that lets movie mode follow the Profile Control lever. If it works, it may give looks
in movie and the stock wheel with no Vivid takeover. The main risk is that picture mode 11 on movie jobs is a combination
stock never runs.

## 1. Does the look reach the movie path?

**Correction: `docs/LV_ART_PREVIEW.md` §4.5 says a bloom/H/L slot "will also be recorded into movies made in that profile".
That cannot happen in stock routing.** In movie mode the picture mode is never 11 (§2). No test clip contains a look.

What the movie path reads:

| Step | Site | Fact |
|---|---|---|
| Picture mode in | `0x603263d5` → `0x6031c1fe` | Reads property `0x9481` (sid 111) into rec68+29, through pointer `0xa27354a0` [V] |
| To the message | `0x60326439` → `0x6030b160` → `0x6030d93e` → store at `0x6030d969` | A+354 = that value. `0x6030d89e` may force it to 2 (Natural), and Custom (6) re-resolves through key `0x9d11` [V] |
| To the record | `0x6030c452` | A+352.. copied to record +292.., so A+354 = record +294 [V] |
| To the job key | `0x60316bc7` → `0x60324d6b` → `0x60349297` | Record +294 and +925 → effect id. Log reaches recordings this way [V code, C] |
| Job | `0x60321d36` → constructor `0x60321ea8` → `0x603220e5` → `0x60324071` | Same constructor as stills. R+2119 → params+5538 (12 S) → request+1816 [V, LV_BUNDLES] |
| Colour stage | `0x603aaced` → `0x603b17e6/19` → `0x603b1466` → selector `0x603b0252` | **COLOR builder `0x603b0068` runs only if key == 11** (`0x603b02c1`). Other keys go to `0x603afd26` when flagged [V] |

Each look element:

| Element | Reaches stills live view? | Reaches a recording today? | If the key were 11 in movie |
|---|---|---|---|
| Per-sector S | Yes [C] | No | Comes from effective S `0xF6EA` (`0x6030bd54`). With sid 111 ≠ COLOR this is not COLOR4's S; needs a read override or a real mode 11 [I] |
| Per-sector H/L | Yes: `lv` at `0x603b02de` [C] | No: key gate | Runs, reads `0xF6B1` for the slot [V] |
| Tone, Blacks/Whites | Yes: `tone` at `0x603b14ff`; LV compounding seen on camera proves that stage runs in LV [C] | No: key gate | Runs, same `0xF6B1` read [V] |
| WB shift | Untraced in LV | No: `wb_get` gates on `0x9481` = 11/12 [V] | Works only if `0x9481` itself is 11, otherwise `wb_get` needs a movie case |
| Glow | Yes: `lv_art` flag 0x80 [C LV] | No | `lv_art` gate excludes type 0x40 recording jobs [V]. Others get a preview-size pass. Keep off in the slice |
| Clarity | No: combiner 12 gets w = 1024, invisible (LV_ART §2) | No | Not reachable without new work |
| Grain, Art Effects | Art yes; grain not by default | No | Keep off in the slice |

Unresolved and important:
- **Whether the stage list runs on recording frames.** Log proves the effect id reaches the gamma on recordings, but the
  gamma is fetched by two routes: `0x6039a97b` (no colour builder) and the stage list `0x603b1466` (has it) [V].
  Which one recording uses is not traced. If only the first, colour may not reach the file.
- `0x6030e9d1` (from `0x60329080`) is a params fill that **zeroes S** (`0x6030ed02`) while reading WB and picture settings [V].
  FEATURE_GAPS labels it "movie"; its role is not traced. If movie frames use it, S is lost and only H/L and tone arrive [I].
- The "View Assist LUT baked into recordings" finding is still unproven (LOG_VIEW_ASSIST), so what the encoder taps is not settled.

Hooks while recording:
- Proven active: `rec_limit` [C] and `vlog_hook` at `0x6030df3d` (per settings message, not per frame) [C].
- Compiled in but inert or unproven: `hl`, `lv`, `tone` (key gate), `lv_art` (key and type gate), `wb_get`, `sc_get` (mode gate).

## 2. How the movie picture mode is stored

**There is no separate movie picture mode setting. Movie mode uses sid 1645, the same value stills use with the lever off.** [V]

| Sid | Key | Holds | Values |
|---|---|---|---|
| 1645 | `0xc9b2`[0] | Normal list | 7, 1, 2, 3, 4, 5, 6, 8, 9, then art 100–124. No 11 or 12 [V, validator `0x604cd5e4`, list `0x604ca3fc`] |
| 1646 | `0xc9b2`[1] | Profile list | 8 rows: MONO 12 + slot, COLOR 11 + slot 1–4 [V, `0x604ca1fc`] |
| 15272 | virtual | Which of the two is active | 1645 or 1646 [V] |
| 111 | `0x9481` | Effective picture mode, what the pipeline reads | Derived by the table at `0x6043dfec` (rows {15272 == 1645, 1645 == v}) [V] |

The switch is `0x602b6b4f`: **sid 44 == 1 (movie) forces 1645** (`0x602b6b92`, `bf01 c853`). Otherwise 1646 applies when sid
15271 ≠ 0 and sids 109, 278, 24 allow it [V]. Sid 15271 being the Profile Control lever is [I].

Camera proof, `testdata/camera_v014*/EP7MOD/LOGDBG.TXT` [C]:
- Movie: A+354 = rec68+29 = 3 (`00 FE 03 03 .. 01`).
- Leaving movie: `03/03` → `03/0B` → `0B/0B`, then the movie flag clears. So `0x9481` changes with the dial, and A+354 follows one
  message later, because +925 is derived at `0x6032641f` before A+354 is written at `0x60326439` [V].

This revises two earlier notes:
- VIDEO_LOG's "A+354 is the movie setting" and the v0.14 comment "stills pm ≠ movie pm" describe the lever, not a second store. Stills on
  the lever use 1646; movie always uses 1645. Test 5 worked because the lever was off [I].
- **Vivid = 1 in 1645 and the record; GUI sid 111 uses 0** (see "Wheel"). [V value and list order; name I]. List order is i-Enhance 7, Vivid 1, Natural 2, Muted 3, Portrait 4, Monotone 5,
  Custom 6, e-Portrait 8, Underwater 9. VIDEO_LOG's "5 i-Enhance" looks wrong: `0x6030ec9e` keeps filter and tone only for
  104, 5 and 12, so 5 is Monotone [I].

**Log:** `vlog_hook` at `0x60210c90`: A+352 == 0, A+332 == 1, A+354 == 3 → +925 = 2. Mapper gives id 2001 [V, v0.25 edits].
Vivid (1) does not touch it.

The dial-to-movie trigger that re-evaluates 15272 is not traced: `0x602b6b4f` is only wired to sid 15271's descriptor (`0x60431d64`) [V].

## 3. Can movie Vivid open the wheel?

**Yes in principle. A built template exists, but it was never camera-tested.**

- Stock Video menu (page `0x6117b1ec`, 13 items: sids 162, 5014, 5089–5091, 102, 1276, 1441, 1442, 291, 826, 651, 652) has **no picture
  mode row** [V]. The orphaned string 2872 "Picture Mode" has no user (VIDEO_LOG).
- Picture mode is edited through Live Control / SCP: Lv_Control row {sid 111, 75 entries} (`0x61176e70` row 2) [V].
- List builder `0x60de477b`: if 15272 == 1646, 8 rows at `0x61152c80`. Otherwise by sid 26: 25 rows at `0x61151f90` for 16/76/90/77/89 [V].
  That 1646 test comes first, so the 8-row list should show in movie if 15272 == 1646 [I].
  Sid 44 == 1 with sid 1337 ≠ 0 forces a one-row list (`0x60de4812`); sid 1337 is untraced [V].
- Route below superseded; see "Wheel" under As built.
- Route: `mc` (v0.15, `patches/mono_colour/mc_ui.s.in`) already remaps one editor key to the COLOR wheel: screen lookups `0x60e4cea8`
  / `0x60e4cf21`, type-7 word `0x61140398`, GetValue(111) spoof at 13 return addresses. Keys: COLOR 0x13b3, 0x13b4, 0x13b5, 0x140c [V].
  Not in v0.25 [V edits]. Vivid's own editor key is not traced.

**Slot and persistence.** Reuse a slot; no new storage.
- COLOR4 (sid 64, S at 1655–1666) as the video slot needs no format change. Stills can still use COLOR4, so it is shared, not private.
- S persists as stock settings [V]. H/L, tone and WB live in the heap table from `BUNDLES.BIN`, saved by the half-press save [C].
- **Catch [V, SD_BUNDLES_V3 §3]: the card table loads on the first half-press after power-on.** Press record first and the clip uses the
  flashed table. Half-press once first, or add a loader trigger on movie entry.
- A user-chosen movie slot would be 1 byte, slot +50. Bytes 49..63 otherwise stay 0 and the loader has a range table, so v0.25 and older likely
  reject a file with it set [I].

## 4. Slices

| Slice | What | Size | Effort | Difficulty |
|---|---|---|---|---|
| **P** Lever probe | `0x602b6b94` `c853` → `cbcb`: movie follows the lever. Mode 11 is then real, so S, slot, WB and maybe the stock wheel all work unchanged | 2 B | 1 session | Easy to build. Unknown if it takes effect (§2), and MONO in movie is also opened. Shares the stills slot; not separate |
| **1** Movie Vivid = COLOR4, edit in stills | A+354 stub at `0x6030d965`: movie and pm 1 → 11. Getter redirects for `0xF6B1` in `lv` / `tone`, S at `0x6030bd5d`, `wb_get` movie case. `lv_art` off in movie | about 150–250 B | 1–2 sessions | Medium. Emulator can prove the gates, not the file |
| **2** Half-press-free load | Loader trigger on movie entry | small | 1 session | Medium, new loader risk (deadlock class, SD_V2_CRASH) |
| **3** Wheel from movie Vivid | Port `mc` routing and spoof for Vivid → COLOR4 | about 1–2 KB | 2–3 sessions | Hard, many GUI sites. Largest free block `0x601e1d78` 1476 B, about 3.9 KB free in dead EVF tables, split [V v0.25] |
| **4** Glow in movie | `lv_art` in movie, FHD only | small | 1 session + test | Hard to judge, real-time |

Easy: finding the trigger, log coexistence, no format change. Hard: proving the colour reaches the file; the panel.

Alternative to spoofing key 11: hook the selector as MONO-colour did (`0x603b02bf`) and keep key 1. That avoids new-key side effects, but Vivid's
own contrast family and saturation offsets stay, so the look would not match stills [I].

## 5. Risks

- **Stability (main):** key 11 on movie job classes 5–7 and 9 is unused by stock. Key 11 sets flag 0x80000, which sends FHD jobs to work-list builder
  `0x60356297` instead of `0x603666c7`; type 0x40 clears the flag [V]. Stock art filters use that builder in movie, so it is not foreign [I]. Failure
  would be a job error or a stopped recording, recoverable by battery pull and restore [I]. Clearing 0x80000 for movie is a cheap fallback.
- **Real-time and thermal:** H/S/L, tone and WB are tables, with no extra ISP passes [V for the stages, I for load]. Glow, grain and Art Effects add passes, so
  they stay off. 4K (95 Mbit/s here [C]) has no known thermal margin (VIDEO_HIDDEN), so a long test is needed. More saturation may raise bitrate slightly [I].
- **Getter in pipeline context:** `lv` and `tone` already do this in stills LV [C]; recording adds no new kind of read [I].
- **Log:** no conflict; different picture mode. Keep log's trigger as is. With P, the lever selects look versus Muted log. Both inherit the one-message lag, which is harmless [I].
- **Metadata:** the clip's recorded picture mode would read COLOR, not Vivid [I].
- **Stale record mismatch:** A+354 = 11 while rec68+29 = 1 stays permanent. The ring shows this mismatch is harmless briefly [C]; no compare between them was seen, but not exhaustively [I].
- **Control Panel (AGENTS.md):** Slices P and 1–3 need no format change: no new look field, share code or `LAYOUT_CRC` change. A panel label "COLOR4 is your video slot" is enough. A selectable slot belongs in
  `color_fields` as a slot byte, not per look. Other bodies are unaffected.

## 6. Camera tests

1. **P probe:** lever on COLOR, dial on movie. Does Live Control list profiles? Does the LCD show the look? Record FHD and 4K, then frame-grab against a stills JPEG of the same scene using an obvious look
   (greens hue +7). **This is the one test that answers everything: does colour reach the file?** Also check lever off + Muted still gives log (p1 and p50 as PB021401).
2. **Slice 1:** movie Vivid with COLOR4 look: same frame-grab. Half-press first, then repeat without it. Stills Vivid must stay stock. Muted must stay log.
3. Stability: 4K 30p for 20+ minutes, HD 120p, stop and start, mode dial cycling, playback.

If colour shows on the LCD but not in the file, the stage list is not the recording route. Trace `0x6039a97b` and stop before building the panel.

## As built (v0.26 movie layer, not camera-tested)

`patches/v026_movie/`: `apply(spec, wheel=True)` in `build.py`, checks in `verify.py`. Specs: `generated/v026_movie/{wheel,nowheel}/edits.json`, packages in `generated/v026_movie/pkg/{wheel,nowheel}/`. Composes with `patches/v026_rot` in either order. No card format, Control Panel or LOOKS.BIN change. COLOR4 is the slot.

**Condition:** valid card table, record +176 == 1 (movie; the copy of A+332 that log uses, `0x6030c36d`), record +294 == 1 (Vivid). Otherwise every path is v0.25.

### Design: change the job key, not the mode

Slice 1 proposed A+354 = 11. Built instead: record +294 stays 1 and only the key given to the mapper becomes 11. That leaves every record-path decision, and the clip's metadata, on Vivid, and removes the stale-mismatch risk.

| Site | Change | Effect |
|---|---|---|
| `0x60316bfb` (7 B) | `mv_key` | Mapper input 1 → 11. This is the route log's id 2001 takes to recordings [C] |
| `0x6030bd5d` rel32 | `mv_s` | Effective S read → COLOR4 S (`0xF6FA`, 36 + i) |
| `0x60315900` (8 B) | `mv_msg` | Message +20 = 4. **New finding:** this byte is `0xF6B1`; when it is 0, R+2119 is zeroed (`0x60314e79`), so S alone would never arrive [V] |
| `0x6030bb5b`, `0x6030bb6e` rel32 | `mv_wb` | Compact WB reads use COLOR4 through `wb_get`'s own slot path. `0x6030eb61/77` stay stock |
| `lv` `0x601e0ed5`, `tone` `0x601e10fd` rel32 | `mv_prof` | `0xF6B1` == 0, job type 0x3x/0x4x, real mode 1 → 4 |
| `0x60353c6f` jmp target | `mv_cons` | IPCR job, key 11, real mode 1 → clear job flag 0x80000 and skip `lv_art` |

**Encoder path.** Flag 0x80000 is what sends key 11 to work list `0x60357415`, and it adds the creative shading pass (`0x6035b03a`). Clearing it gives the movie job stock Vivid's builder `0x603666c7` → `0x60368e97`, with the same packer (`0x60355409`, so S reaches request+1816) and the same callback (`0x60368b30`), so the `lv` and `tone` guards pass. The difference from stock Vivid is then the selector's choice of colour table, plus `tone`'s LUT remap when the slot sets Blacks/Whites [V code; camera unproven].

**Art, glow, grain, clarity: forced off in movie.** Chosen because they add passes that could stall the encoder. `mv_cons` skips `lv_art`, so there is no transport and no flag 0x80, and grain, bloom and clarity all require the transport. Record +294 < 100 means Art Effect bits stay off (`0x60312f42`). Shading and NR overrides also don't apply; they gate on the real mode.

### What reads the mode in the movie path (checked)

| Reader | Sees | Result |
|---|---|---|
| Record +294 (`0x6030b10d`, `0x6030c978`, `0x6030dd5b`, `0x6030ed5e`, `0x6030ef73`, `0x603147aa`, `0x60318d7f`, `0x60318ebc`, `0x6031dcca`, `0x6032b815`, `0x6030a8ea`) | 1 | Stock Vivid. Compares are to 6, 7, 9, 11, 12, 105, 106, ≥100 |
| A+354 (`0x6030b423`, `0x6030fef3`, `vlog_hook`, `0x6030eb86`) | 1 | Stock. `0x6030fe11` (S-less second sender) has no +925 input, so log proves recordings don't use it [I] |
| Comparator `0x60313884`, `0x60316909` | 1 | Stock; Vivid ↔ Muted still rebuilds the job |
| Job key: `0x60356ba8/bf3`, `0x603562ba`, `0x60357415`, `0x60358036`, `0x60359ba3`, `0x6035daf7`, `0x6035efc3`, `0x6035f7cd`, `0x60367ee3` | 11 | Compares are to art ids and 12 only, or a hash with no case that this route reaches [V for those read] |
| Selector `0x603b02c1`, `hl`, `lv`, `tone` | 11 | Intended |
| Key-11 hooks `wl_hook`, `sel_hook`, `gb_*`, `0x6039fee8`, `0x603eabd7` | 11 | Inert: no transport, or the stage never runs |
| Stream job `0x6039a97b` | Key for gamma/luma, then forces key 2 for colour | Not traced further. Stock movie modes are known to differ in colour, so colour must come from the stage list [I]. Test 4 decides this |

Not read exhaustively: per-key hash tables in the ISP stages. Stills LV runs key 11 through them, but not in classes 5–7 and 9.

### No table, and the first half-press

- No EP7MOD folder or before the first half-press: `mv_key`, `mv_s`, `mv_wb` and `mv_msg` all miss, so **stock Vivid**, with no fault (run through state 0, 0xFFFF and bad magic).
- **A clip shot before the first half-press is stock Vivid, with no error.**
- The job key is fixed when the job is built, and a new-parameters update doesn't change it (`0x603118d6`). If you power on in movie and half-press, the running live view stays Vivid until a rebuild. Half-press in stills before turning the dial, or cycle the dial or Vivid ↔ another mode. Whether record start also rebuilds is not known.
- **Loader on movie entry: not built.** There is no simple trigger, and it is the deadlock class in SD_V2_CRASH.

### Wheel (`wheel=True`)

**First build (`generated/v026/wheel`) failed on camera: INFO on movie Vivid in Live Control did nothing. Two causes, both read from code [V]:**

1. **INFO never reaches any key remap.** Live Control is screen group 20, actuator `0x60e23b98`. INFO release gets rc 2 through the row's direct actuator (`0x60e2418b` → `0x60e22413`, no list for key 111 → 3 → 2), then handler `0x60e593be` tests row 111 against values 27/51/52/53, 21, 8, 9, 13, 15, 63 only. Anything else, Vivid included, falls to `0x60e59713` and the sid 281 control-mode cycle, which changes nothing. There is no movie gate on Vivid; the gate (sid 44 == 1 and sid 1337 == 1) only blocks the listed values.
2. **Wrong key and wrong value.** `0xba` is not Vivid's editor: table `0x6115a6c8` is read only for Custom, keyed by sid 211, and `0xba` is the saturation slider of Custom on Vivid. And GUI sid 111 is not the pipeline enum: **Vivid is 0** (descriptor list `0x611748f0` 7, 0, 1, 2, 5, 3, 6..; derivation `0x6043dfec` + outputs `0x6043f2fc`: 1645 == 1 → 111 == 0). The old `mv_on` tested 1, which is Natural. Record +294 == 1 in the colour path is the other enum and stays right.

**Fix.** `mv_lc`, a 6-byte jmp at `0x60e5951c`: row 111, value 0, sid 1337 ≠ 1, valid table, sid 44 == 1 → d0 = `0x140c`, into stock tail `0x60e59703`, the art-variation route ((`0x61fc4370`) = key, (`0x61fc4384`) = 1, state (4,7)). State 7's entry `0x60e59198` opens group 18 with that key, so COLOR4's screen, children and record are used directly. Screen and type-7 hooks are removed. `mv_on` now tests 0.

**Exit [V, not run].** OK returns rc 1 → (1,4), the same as a wheel opened from the SCP, which leaves to live view. State 7's exit `0x60e591ba` clears the flags.

**Stills-only state in the wheel:**
- **Trap, fixed:** three stock sites (`0x60e22245`, `0x60e223d6`, `0x60dec542`) do "if 15272 == 1645, set 1645 := 21", for Color Creator, which shares this record. In movie 15272 is always 1645, so OK would have switched picture mode to Color Creator. `mv_get` returns 1646 at those three return addresses only.
- GetValue(111) → 64 at the 13 `mc` sites, plus the Profile view on page 1 (`0x60e26b33`, as `mc`). Polygon profile read → 4. Sid 44 and 1337 are not read in the editor or view code.
- `0x60dec57c` stores the spoofed 64 in sid 3012, as stock stores 54.. in stills. Only the Color Creator direct key reads it [I].
- Needs the card table, so **half-press once first**, otherwise INFO stays a no-op.

**Camera: `wheel2` opens the wheel with INFO.** Film and Extras then showed "All colors[INFO]": `ed_guide` (`0x60b9ddb6`) and `ex_guide` (`0x601e34ea`) read GetValue(111) themselves, got 0, and fell back to the stock label [V]. `wheel4` adds both return addresses to `mv_get` (Mono `0x601e1761` is left alone).

**INFO hint on the strip: not built.** The strip's Vivid entry is a bitmap (lists `0x611748f0`, `0x61174c74`), so there's no text to swap. Text lists with Vivid (`0x611686d4` and two others) belong to item table `0x6116ae1c`, not this viewer. The only gated route found is hooking `0x60df250b`, which has 277 callers, and a kind-5 text in that cell is likely to clip (ASPECT §1b).

**Buttons:** movie mode, half-press once, OK for Live Control, Up/Down to Picture Mode, Left/Right to Vivid, press and release INFO. Edit, then OK to leave. Not wired: the SCP. Its Vivid cell is key `0x77`, the stock saturation slider.

Unproven:
- All of it on camera. Emulation runs the real handler, not the screen stack, so state 7 opening this viewer in movie is read from code. Art variations use that route, but only non-wheel viewers from Live Control.
- **Stills is not explained:** `0x60e593be` has no COLOR case either, so INFO on COLOR in stills Live Control should do nothing by this path, and LOOK_MENUS' "INFO/→ opens the editor" route was not found. If the wheel misbehaves, that gap is the place to look.
- Whether an edit updates live view at once. The descriptor callback doesn't refresh effective S in Vivid, so it may need leaving the panel or a half-press [I].

### Movie slot (released in v0.26; flashed and used on an E-P7, long recordings untested)

**Camera before this build:** `wheel4` opens the wheel, labels are right, and colour reaches the file. The 20+ minute run is still untested.

**Card:** `EP7MOD/MOVIE.BIN`, 96 B (`tools/ep7_movie_bin.py`): `EP7V`, version 1, 80, CRC-32 of 16..95, slot (64 B, COLOR layout), name (16 B). `BUNDLES.BIN` and `LOOKS.BIN` don't change. A BUNDLES.BIN is still required.

**No or bad file, or no BUNDLES.BIN:** every gate misses, so movie Vivid is stock Vivid and INFO does nothing. COLOR4 is never used.

**Design: a second heap block P2, not new slot code.** P2 (1024 B) is a copy of P with the Movie slot in COLOR4's row (+224) and its name at +592.
- Marks in P and P2: +960 `EP7V`, +964 P2, +968 P's handle (P2), +972/+976 ALL values, +980 tried. +688..+999 had no other user in the release code [V grep of the build constants]; +1000/1002 are the editor's probe words.
- **Wheel:** `mv_lc` writes P2's handle to the loader state word, and `mv_exit` (state 7 exit, table word `0x611a3b6c`) restores it. Editor, Extras and Film code all read the state word, so they work on P2 unchanged, including `*` and the Film pick.
- **Still in stock sids, so redirected while swapped:** S ids 1655..1666 on S and Film pages (get, set, default, polygon) → P2 +257+s; ALL 1686/1687 → P2. Writes never reach COLOR4's settings.
- **Pipeline:** `mv_key`, `mv_msg`, `mv_s`, `mv_wb` also need `EP7V`. `mv_s` reads P2 +257+i. `mv_prof` marks d1 and `mv_tbl` (lv, tone) returns P2 +224; `mv_wb` reads the same row. Unmarked reads go to stock `tbl_idx`.
- **Save:** `mv_trig` on sd_back. P2 dirty → `mv_save` (.NEW verified, old → .BAK, .BIN verified, real `ed_wfile`). `mv_gsave` on `ed_trig`'s save call refuses P2, so P2 can never become BUNDLES.BIN.

**Camera, `movie1`: the Film page was missing** (pages went H, S, L, Extras). `fm_valid` checks L+2116 == P, and L pointed at P, not P2, so the page was skipped; the emulator checks hadn't run the real Film code. **`movie2` (`d54b64a6`, not camera-tested):** `mv_load` gives P2 its own copy of L (one more 2560 B block) with L2+2116 = P2, so Movie picks can't move COLOR4's position or snapshot. Its position resumes on a colour look with the same name, as `fm_load` does. If that allocation fails, the Movie slot has no Film page and everything else still works.

**Load point: first half-press, after the film load.** No movie-entry load: no safe point was found, and the deadlock risk (SD_V2_CRASH) stands. **A clip before the first half-press is stock Vivid.** As before, a live view already running stays Vivid until a rebuild.

Behaviour to check:
- A Film pick zeroes the slot's saturation (+33..44), because LOOKS.BIN carries none. Stills keeps its S there.
- S index order in the slot is assumed to match ids and the recording's request order (`layout.json`, `mc`) [I]. Camera check 3 covers it.

**Control Panel export (not edited):** add a Movie target that writes 96 B: slot from `color_fields` encoding, sat in +33..44 taken from the look's S values, name up to 15 ASCII, header and CRC above. Offer it alongside the existing export, to `EP7MOD/MOVIE.BIN`.

**Camera checks, in order:**
1. Copy firmware and `generated/v026/movie1/card/EP7MOD/MOVIE.BIN`. Boot, half-press, stills COLOR1 to COLOR4 shots: as `wheel4`.
2. Movie Muted clip: log as before.
3. Movie, half-press, Vivid, INFO. Edit Saturation for reds, Hue, Light, Extras, a Film pick. OK. LCD and clip follow; each sector lands on the expected colour.
4. Half-press, power cycle: values back, `MOVIE.BAK` and `MOVIE.BIN` on the card. COLOR4 in stills unchanged, including its S·All state. Mode still Vivid.
5. Remove `MOVIE.BIN`: movie Vivid is stock, INFO does nothing, no fault.
6. Hold-OK reset and `*`.
7. 4K 30p 20+ minutes.

Not emulated: the screen stack, the real film and editor code on P2, and anything about real file I/O timing.

### Checks

`verify.py`, both builds. Each runs real entry points against v0.25: K key 288, M message 192, S 288, B WB 96, P profile 72, C constructor + `lv_art` 24, wheel build: K and M with a `nofile` state, Y pipeline slot reads 45, U get/set/poly/exit 40, L real Live Control handler 240, F MOVIE.BIN load, save and `mv_trig` 18. D: bytes differ only at our sites, so loader, save and look code are identical. A: package parses, restore == stock, decoded == emulated. The emulator can't show that colour reaches the file, or that recording is stable.

### Camera test, in order (flash `nowheel` first)

Copying files to the card and flashing are the user's manual steps. The restore package equals v0.25's.

| # | Do | Pass | If it fails |
|---|---|---|---|
| 1 | Boot, half-press, menus | Normal, version 0.26 | Restore stock, then v0.25. Layer not usable |
| 2 | Stills: COLOR4 look shot; stills Vivid shot | Same as v0.25 | Layer bug. Back to v0.25 |
| 3 | Movie Muted, short clip | p1/p50 as PB021401 | Log broke: back to v0.25 |
| 4 | Half-press in stills, dial to movie, Vivid, COLOR4 with an obvious look (greens hue +7). 20 s FHD, then 20 s 4K | LCD shows look, clip records and stops normally | Recording stops, or a job error: key 11 unusable here, back to v0.25. LCD Vivid: key never reached the job; report it |
| 5 | Frame-grab vs a stills JPEG of the same scene | Hue, S, tone match approximately | LCD yes, file no: the stage list isn't the recording route. Trace `0x6039a97b`; don't ship |
| 6 | Power cycle, movie, record with no half-press | Stock Vivid clip | Note the behaviour; a fault means back to v0.25 |
| 7 | 4K 30p 20+ min, HD 120p, stop/start, dial cycling, playback | No stop, normal bitrate and heat | Stall: back to v0.25 |
| 8 | Flash `generated/v026/wheel4/pkg`. Buttons above; edit each page, OK, check the mode is still Vivid, half-press, power cycle | COLOR4 wheel, live view on exit, values persist | No-op, wrong screen or a mode change: go back to `nowheel`, which keeps movie colour |
