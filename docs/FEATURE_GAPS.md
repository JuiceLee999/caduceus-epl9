# E-P7 feature opportunities

Evidence levels: **[code]** = string/code found in the E-P7 main program (block 0);
**[menu]** = English UI string in the OSD resource (block 1, possibly shared across models,
so presence ≠ feature); **[spec]** = speculation. Offsets are decoded-file offsets unless
written as CPU addresses (0x60…).

## Ranked

| # | Feature | Evidence | Feasibility | Value |
|---|---|---|---|---|
| 1 | **Per-sector HSL + film-sim recipes** | [code] COLOR builder/table mapped; fixed-H/L patch built + emulator-verified (docs/HSL_PORT.md) | Moderate (in progress) | Very high |
| 2 | **Video recording-length limit** | [code] routine `0x60319139`: modes 3/6/8/9 → `mov 1740,d0` @`0x60319156`, mode 4 → `mov 7200,d0` @`0x6031915b` — same shape as PEN-F `60566309` whose published patch sets 32400 | Easy (4 operand bytes; PEN-F/E-M5 II precedent). Chapter/file/thermal limits may remain | Medium |
| 3 | **Colour film grain** | [code] `COLORTONE_GRAINY_FILM*`, Film Grain Effect (Mono Profile) [menu 2772–2776]; grain HW combiner (fishcu GRAIN.md) | Moderate: enable grain job on COLOR path | High (Fuji users love grain) |
| 4 | **Extra aspect ratios / frame lines (XPan 65:24, 21:9)** | [menu] Image Aspect 4:3/3:2/16:9/1:1/3:4; per-aspect LV grid bitmaps (720×405, 480×480…) | Moderate–hard: aspect table + JPEG crop + overlay; RAW stays full sensor | High |
| 5 | **Flat picture mode** (video/grading base) | [menu] `@A077@Flat` (2886), `@A0C0@Flat` (3258), "Flat & Muted" | Unknown: need to find picture-mode table in main and whether Flat's tone LUT exists | High for video |
| 6 | **Focus bracketing** | [code] `fcs_calc_focus_bracket_info` (0x6f6936); [menu] Focus Bracketing / Focus Stacking (3344/3272) | Unknown–moderate: check whether the bracket engine is gated by model flag or absent | High (macro) |
| 7 | **High Res Shot (pixel shift)** | [code] `HIGH_RES`, `HAND_HIGH_RES` (0x6cd88f/0x6cd8b2), `iseqPixshiftSrCbGetHighResolution*`; [menu] High Res Shot (2438) | Hard/risky: needs sub-pixel IBIS control + compositing; may be library stubs | Very high if real |
| 8 | **Pro Capture** | [code] `[pro_cap] …Plural_Cursor_Move_Set_Mode_Actuator` (0x1163a90); [menu] Pro Capture High/Low (3141/3142) | Hard: pre-buffer memory/throughput | Medium |
| 9 | C4K video | [code] `MOVIE_C4K` (0x1aa2e2); [menu] C4K (3224) | Hard: sensor readout/encoder/thermal | Low–medium |
| 10 | Timecode | [code] 145 timecode strings | Unknown | Low |

**Absent (would need new code — infeasible for now):** Live ND (0 hits), Starry Sky AF (0),
OM-Log (0), zebras (0), false colour/waveform (0), anamorphic desqueeze (0).

**Already present on E-P7:** Live Bulb/Time/Composite, peaking (+colour), HDR BKT,
interval/time-lapse, keystone, fisheye correction, COLOR4/MONO4 profiles.

## Notes
- "High-end lens only" gating: on E-M1-class bodies focus *stacking* had a lens allowlist
  (historical patches removed the branch). On E-P7 the question is whether the bracketing
  engine exists at all; item 6 is the first thing to trace.
- The OSD resource looks multi-model (strings for features the E-P7 never shipped), so
  every [menu]-only item needs a [code] trace before it counts.
- Next steps: (a) port item 2 (tiny, precedent); (b) trace picture-mode table for Flat;
  (c) trace focus-bracket gating; (d) colour grain job on COLOR path.

## Aspect ratios (traced 2026-11-01)
[code] Three parallel tables list **9 still aspects**; the E-P7 menu exposes only 4:3/3:2/16:9/1:1/3:4.
- u32 table `0x60b8cb60`: (id, w, h): 1 4:3 5184×3888 · 2 3:2 5184×3456 · 3 16:9 5184×2920 · 4 1:1 3888×3888 ·
  **5 5:4 4864×3888 · 6 7:6 4544×3888 · 7 6:5 4672×3888 · 8 7:5 5184×3704** · 9 3:4 2912×3888.
- u16 copy `0x60b0a518` (id,0,w,h); u16 table `0x604e92c6` (w,h,code) with ratio codes 0x304, 0x203, 0x910,
  0x606, 0x405, 0x607, 0x506, 0x507, 0x403, plus **0x911 = 17:9 5184×2734**.
- Plan: unhide hidden ids (find menu allowed-value mask), then repurpose two hidden slots to **XPan 65:24
  (5184×1914)** and **21:9 (5184×2222)**. Needs: menu mask, crop/LV overlay, EXIF ratio. Not yet patched.
- **Update:** traced and built in docs/ASPECT.md + patches/aspect (ids 6/7 → 5184×1912 / 5184×2224, codes 0x1841/0x0915; menu is a
  per-setting option list, relocated; 136 emulator/parse checks pass; untested on camera; icon lists not patched).

## Issue #10 unlock leads (re-traced 2026-11-05)

Static reads only; nothing built or run. **[V]** = bytes or disassembly, **[I]** = inference. Offsets in the table above
for these rows are decoded-file offsets; the CPU addresses below are the ones to use.

| Lead | Real code? | Gate | Verdict |
|---|---|---|---|
| **Focus bracketing** | **Yes, and it looks stock on the E-P7** | Sequencer `0x609352c9`: sid 605 == 1 and (sid 860 == 1 or sid 24 ∈ {207, 216}) → FOCUS_BKT | **Check camera first; easy or nothing to do** |
| Flat | Yes, movie only | Hidden properties; shipped log hook has a Flat option | **Easy, movies only: one more trigger on the shipped hook** |
| High Res Shot | Code present | sid 775 / 758, menu visibility filter; IBIS unknown | **Hard, research** |
| Pro Capture | Code present | Internal sids 1158 / 764 / 1493; drive list | **Hard, research** |

### Focus bracketing: real [V]

- **Sequencer:** the block at `0x609352c9` reads sid 605 (`0x604cff24` record 686, [0, 1], Shooting 2 menu item `{605,
  string 76 "Bracketing"}`), sid 860, and sid 24, then sets d2 bit 0x8000 and logs "FOCUS_BKT" (`0x60b4103f`).
- **Menu rows:**
  - Bracketing sub-list `0x6116a840`: 611 WB, 614 FL, 606 ISO, 616 ART, **860 "Focus BKT"** (string 2664, at `0x6116a870`).
    Sid 860 has validator record 851, [0, 1].
  - Shooting-mode lists `0x6115c118` and `0x6115c304`: value 207 string 3348 "Multi Focus Shot" and value 216 string
    3344 "Focus Bracketing", help 3423. **Both values are in the sid 24 validator list** `0x604cc68a` [V].
  - Same strings in further list copies: `0x611644e8`, `0x6116462c`, `0x61190c90`, `0x61190e7c`, `0x61192d34`, `0x61192f20`.
- **Engine:** `fcs_calc_focus_bracket_info` print at `0x606602d7`; `fcs_bracket_check_stop` strings `0x607168c1`;
  `startFocusBktSubAppMdlStillShooting` `0x60cf1ad2` (state 20748); `getFocusBracketingStatus` call at `0x60cd4f81`, in the
  MF-clutch bracket code ("changeMfClutchBktMode").
- **Stacking is separate:** `fcs_check_focus_stacking_enable` at `0x606604a2` with a lens-ID list `0x60716991`: 0x1012,
  0x1019, 0x1020, 0x1023–0x1027, 0x1034 [V; "lens IDs" I]. `recordMediaFocusStacking` print at `0x60a3de76`.

**Reading [I]:** it is a stock shooting mode (AP/SCN lists), and the Bracketing page probably has the row too, unless the
run-time visibility filter hides it (LOOK_MENUS §2 #9). Which screens these lists belong to was not traced.

**Camera test (5 min, stock or current build):**
1. Dial AP and SCN: is Focus BKT / Focus Bracketing there?
2. Shooting Menu 2 → Bracketing: is there a Focus BKT row, and does it work with the dial on P/A/M?
3. Use an AF lens, confirm the focus steps and frame count.

If 1 or 2 works, reply on #10 with where it lives; there may be nothing to unlock. If only AP works and PASM is wanted:
the sequencer already accepts sid 860 in any mode [V], so only the row's visibility is missing, a small edit once the
filter is found. Risk low (it only drives stock AF moves); filter effort unknown.

### Flat: covered by docs/VIDEO_LOG.md

- Not a menu picture mode: `COLORTONE_FLAT` / `COLORTONE_SUPERFLAT` at `0x60ab0cc3` / `0x60ab0e7d` are only entries in a
  debug name switch (`0x607c1664`, `0x607c1718`) [V]. Strings 2886 / 3258 are in the shared OSD resource.
- Real path: hidden properties `0x4501` and `0x91b1`[0], MovPicMode 254 → effect id 2000 (Flat), 255 → 2001 (OM-Log), with
  a dedicated gamma table [V, VIDEO_LOG]. Movie path only: stills hard-wire b6 = 0 [V, VIDEO_LOG].
- **Log already ships:** v0.24 has the hook (`0x6030df3d` → `vlog_hook` at `0x60210c90`, 43 B: movie and picture mode 3 →
  +925 = 2, id 2001) [V `releases/v0.24/edits.json`], and the README lists it as camera-tested.
- **Flat is the same hook with one more trigger:** `patches/video_log --trig-flat N` gives +925 = 1, id 2000, 53 B
  (CODE_SPACE_MAP), inside the 64-B claim `0x60210c90–0x60210cd0` [V]. It has not been camera-tested. Needs a choice of
  which movie picture mode to use as the trigger, since that mode's normal look is lost in movies.
- Rating: **easy, movies only**, about 10 B more code. Stills Flat is a different job: stills hard-wire b6 = 0 [V VIDEO_LOG],
  so it would need a real look or LUT instead.
- Camera test: movie mode, set the trigger mode, record a high-range scene next to Muted (log) and a stock mode; check
  that Flat sits between them and Muted still gives log.

### High Res Shot: hard

- [V] Present: `iseqPixshiftSr*` callbacks (names `0x60702f48..`, table `0x60705b90`), sensor mode names `HIGH_RES`,
  `HAND_HIGH_RES` (`0x606ed8af`, `0x606ed8d2`), Shooting 2 item `{775, string 2438}` (`0x6117a1b0`, validator [0, 1]), and
  a drive list entry value 18 (`0x611674e4`).
- [V] Gates: sequencer `0x6093531d` tests **sid 758**, which has no validator record. Its other readers are `0x6076ab45`,
  `0x6078a2c1`, `0x6079341b`, `0x6088bca4`, `0x6088bcdf`, `0x6091676e`, `0x60935640`. The only sid 775 read found through
  the setting getters is `0x6082a8ec`. What links 775 to 758 is untraced.
- Unknown: whether the E-P7's IBIS can do the sub-pixel moves, and whether its sensor tables are populated for this mode.
  The name list also contains `DIGITAL_ND`, which this body lacks, so names prove little [I]. Compared with focus
  bracketing there is much more to prove, and a wrong IBIS command is a hardware-side risk that nothing can test offline.
  **Rating: hard, research. Do not start before the other items.**

### Pro Capture: hard

- [V] Present: `CmpSqp_SequencePartsZeroLag.cpp` (`0x60b5c3bc`), `executeTakePictureForZeroLag`, `checkZeroLagBuffgering`
  print `0x60b32097`, `SCENE_PROGRAM_ZERO_TIME_LAG_*`, and drive list entries value 20 "Pro Capture High", 21 "Pro Capture
  Low" (`0x611673f4`, `0x61167400`). [I] "Zero Lag" is the internal name; the strings do not state it.
- [V] Gate: sequencer `0x609353c2`: sid 1158 == 1 and sid 764 == 1, reached when sid 1493 ∈ {0, 2} → "Zero Lag",
  d2 bit 0x20000. Sids 1158, 764 and 1493 have no validator records, and 1158 and 1493 have no menu entries, so [I] they
  are set internally.
- Unknown: the drive setting's sid (no validator holding 20 and 21 matched a drive list), the pre-buffer memory (full-size
  frames, on a body that never shipped it [I]), and read-out speed. **Rating: hard, research.**

## Features for the build after v0.24 (researched 2026-11-05)

Static reads only; nothing built, emulated or run. **[V]** = bytes or disassembly, **[I]** = inference.

| Rank | Item | Verdict | Size |
|---|---|---|---|
| 1 | Per-look NR, read-site override on the **stills** Noise Filter | **Build now** (it also fixes a v0.22 bug) | 2 rel32, 2 single bytes, stub 30–40 B shared or about 90 B alone |
| 2 | Flat for movies | **Build now** | 11 B |
| – | Focus bracketing | **No patch**: already stock | 0 |
| – | ISO Auto in movie M | Later: gate not found | unknown |
| – | ART dial as silent switch | Later | unknown |
| – | Other per-profile settings | None worth it now | – |

### Correction for the vignette build: sid 61 has a fifth read

docs/VIDEO_HIDDEN.md §5.1 says exactly four reads of key `0x8c21`. There is a fifth [V]:

| Key load | Call | Stock call bytes | Function |
|---|---|---|---|
| `0x605554b3` | `0x605554bc` | `dd b5 94 b0 ff c0 0c` | `0x6055545e`, 13 callers (`0x60290348`, `0x6029526f`, `0x60295446`, `0x60297f8b`, `0x6029f302`, `0x6029f32d`, `0x6029f7d1`, `0x602a540f`, `0x602a546d`, `0x602a54b4`, `0x602abbf3`, `0x6054cc2a`, `0x6054d76a`) |

It has the same logic as R2: record +4 bit 8 and key == 1 → request flag 0x2000 [V]. Redirect it with the others.

### 1. Noise reduction per look: v0.22 writes the movie setting

**Finding [V]: the stills Noise Filter is sid 143, not sid 1334, which v0.22 writes.**

| | Stills | Movie |
|---|---|---|
| Sid, key | **143**, `0x9719` | **1334**, `0x9309` |
| Validator | record 359, list `0x604cb4ed` (-2..1) | record 360, same list |
| Menu row | `0x6117df74`: string 188 "Noise Filter", help 2882 "...for still photography...", options `0x6117bc84` Off/Low/Standard/High | `0x611beb14` / `0x611cc280`: string 2879 "@A006@Noise Filter"; help 2881 "...for video recording..." (`0x611c2b70`, `0x611d030c`) |
| Reader | capture +24036, see below | only `0x6030ecac`, params builder `0x6030e9d1` |

Consequences:
- [V] `ng_set` and `ng_put` (`patches/v022/build.py`) pass 1334, so Extras sector 1 and a Film pick change the movie Noise Filter.
- [V] Stills use capture +24036, filled from key `0x9719` at `0x602a8095`. Debug dumps `0x613e77b2` and `0x613f096c` name the params field +5526 `chNf`. Four job builders copy +24036 to it: `0x603e3fc0` (`rec_ePortrait.c` nearby), `0x603e65d3`, `0x603e911c` (`rec_imgpro_callback.c` nearby), `0x6060e2a7` (`iseq_swpa_*` nearby).
- [I strong] **Per-look NR has done nothing to stills since v0.22, and it overwrites the user's movie Noise Filter.** No stock link from 1334 to 143 was found (the only non-UI read of `0x9309` is the builder). The FILM_LIBRARY §5.3 line "1334 ... affects stills" and the README text need correcting at the next README update.

**Reads of `0x9719`: three in the whole image** [V: 24 raw byte hits; the only instruction loads are these three]. All are `call 0x6005e971,[d2,d3],12` with a0 = 0, d1 = 0.

| # | Load | Call (edit rel32 at call+1) | Stock bytes | Role | Action |
|---|---|---|---|---|---|
| N1 | `0x602a808c` | `0x602a8095` | `dd dc 68 db ff c0 0c` | Capture setup `0x602a7ea0`, 10+ callers → +24036 | **Redirect** |
| N2 | `0x6028d084` | `0x6028d08a` | `dd e7 18 dd ff c0 0c` | Stores {value, -2, 1} at +52 beside "OLYMPUS DIGITAL" code. [I] MakerNote NoiseFilter, value/min/max | **Redirect**, so the file reports what was applied |
| N3 | `0x60c6704a` | `0x60c67053` | `dd 1e 79 3f ff c0 0c` | `play_exif_get_default_raw`, playback RAW edit | Leave stock |

Also a static table lists the key: `0x604e094c` (with `0x9309` at `0x604e0954`); its reader was not found. The key `0xdf79` read at `0x60c67c25` (sids 513/514) goes to the same +24036 in the RAW-edit path; leave it.

**Paths:**
- Capture: yes, through N1, every still job above [V]. None of N1–N3 overlaps `releases/v0.24/edits.json` [V].
- Live view and movie: the builder reads 1334, not 143 [V], and stays stock. [I] NR is not meaningfully visible in live view, so no preview is lost.
- A profile switch applies at the next capture, since N1 runs in capture setup [I: per capture, same family as the WB reads].

**Patch:**
- Stub: resolve the COLOR slot as `wb_get` does (picture mode 11, profile 1..4, MONO and other modes pass). Read slot +24. Map with the shipped tables: `ng_b2u` `0x601e1bca` then `ng_u2nf` `0x601e1bd1`. u == 0 or byte ≥ 7: tail-jump to `0x6005e971`. Otherwise return the sign-extended value (0, -1, -2), which the list already allows.
- Share the resolver with the vignette stub (`0x601e393c`), entered by a key test or a second entry: 30–40 B extra. Standalone about 90 B.
- Remove the writes: `0x601e38ae` `c8` → `ca` (`ng_set`) and `0x601e1baf` `c8` → `ca` (`ng_pick`), each `beq` → `bra` past the settings call [V from v0.24 bytes]. `ng_put` and the 1334 immediates become dead. Do this or the user's movie setting keeps being overwritten.
- Storage: **none**. Uses the existing +24 and sector 1. Film picks and LOOKS.BIN already carry it.

**Side effects:**
- Looks that hold NR Low or Off start changing stills for the first time. Expect more visible noise at high ISO, which is the intended behaviour but new to users. Say so in the release notes.
- The stock menu row keeps the user's value while a look overrides it, the same as vignette.

**Risk:** low. Image and metadata only, stock-legal values, no writes, no boot path. Same technique as `wb_get`.

**Camera test:**
1. Now, on v0.24: Extras NR Off, then check both menus. Prediction: Custom menu Noise Filter unchanged, movie Noise Filter becomes Off. This confirms the finding.
2. Build: COLOR1 NR Off, COLOR2 NR Std, ISO 6400, same scene. Switch profile without opening Extras; the JPEG noise must differ. `exiftool -NoiseFilter` should follow [I].
3. NR Camera: follows the menu. MONO: follows the menu. Movie Noise Filter stays where it was set.

**Emulator:** native run `0x602a808c`→`0x602a80a2` (pattern of `tools/ep7_verify_wb.py` C/W): bytes 0, 1, 2, 5, 6, 7, 0xFF × COLOR, MONO, other modes; check +24036, MDR, sp, d1. Same for N2. Update the expected call list at `patches/v024/verify.py` line 43, since 1334 is no longer written. Scan: exactly 2 sites redirected and the rest of the image unchanged.

### 2. Flat for movies

- Cost confirmed [V]: `patches/video_log/build_and_verify.py` adds `cmp N,d0; bne stock; mov 1,d0; jmp ep7_store_ret`, 11 B per CODE_SPACE_MAP. v0.24 hook: `0x60210c90`, 43 B, entered from `0x6030df3d` (stock `26 60 01 f1 72`). 54 B fits the 64-B claim to `0x60210cd0`.
- Not a duplicate [V, VIDEO_LOG]: id 2000 uses gamma `0x604f4278`, log (id 2001) uses `0x604f4478`. [I] Flat is the gentle option, usable without a heavy grade, while log needs a LUT and about -2 EV.
- Trigger: **Portrait (4)** [I: mode ids inferred, Muted = 3 proven by the log test]. It is the movie mode people use least [I]. The normal movie Portrait is lost; stills are untouched (A+332 movie gate) [V].
- Storage: none. Risk: low, same hook as the camera-tested log.
- Emulator: the script's H/M/G/L checks. It writes `edits.json`, so run it at build time.
- Camera test: movie, high-range scene, Portrait vs Muted vs Natural. Flat must sit between; Muted must still give log; a Portrait still must look stock.

### 3. Focus bracketing: no patch

- Search result text from the E-P7 manual p. 69 says focus bracketing ends if the zoom moves, stops at infinity and uses the electronic shutter. The page itself could not be fetched (bot block), so the menu path is unread. Source: <https://manualshive.com/en/manual/olympus/pen-e-p7/734679?page=69>
- [V] The firmware has the row (sid 860 at `0x6116a870`, string 2664 "Focus BKT"), and `0x6061f1a6` tests 860 == 1 and 605 == 1. Both reads are stock.
- Stacking stays separate and lens-listed (above). Action: the 5-minute camera check above, then answer #10. No build work.

### 4. Silent switch and per-profile overrides

Read counts are `0x6005e971` calls within 16 B of an instruction load of the key; reads through the facade by sid are not counted.

| Setting | Sid, key | Reads | Verdict |
|---|---|---|---|
| Peaking Color | 566, `0xe341` | 1 (`0x6054db03`) | Cheap, but little use per look. Later |
| Color Space | 60, `0x8bf1` | 2 (`0x602a8187`, `0x60c67067` playback) | Cheap; sRGB/AdobeRGB per look is rare. Later |
| Noise Reduct. (long exposure) | 35, `0x8441` | 4 (`0x6029b548`, `0x6029badf`, `0x602a71d0`, `0x603ece4e`) | Not a look property. No |
| Image aspect | 270, `0x3081` | 14, with live view and buffers | Most wanted, but not a safe read override. No |
| Silent / anti-shock | drive list `0x611673f4`, row ref `0x6116b21c`; sid not resolved | unknown | Later |

ART dial as silent: it needs a dial-position test plus a drive override. Shooting-mode sid 24 alone has 18 reads, and silent changes shutter sequencing. Not a read-site job.

### 5. ISO Auto in movie M: later

Not found in the time box. The direct reads of key `0x810a` (sid 6) are `0x6029aa5e`, `0x602a7eb9`, `0x603ecd44`, `0x60429526`, `0x613ebbde`. `0x60429526` calls `0x603f3968` when flag `0x622a076a` == 1 and ISO == 0 [V; I: the Auto branch], a place to start. No names ("ISO_AUTO", "IsoAuto" and similar) exist in the image. Still 1–3 sessions.

## Film-photographer feature ideas (researched 2026-11-05)

Static reads only; nothing built, emulated or run. **[V]** = disassembly, bytes or a real JPEG, **[I]** = inference.
All sites below are free in `releases/v0.25/edits.json` [V]. Free code in the v0.25 claim: `0x601e3a73–0x601e3b3c`, 201 B (CODE_SPACE_MAP).

| Rank | Idea | Sites | Size | Risk | Tonight? |
|---|---|---|---|---|---|
| 1 | **Look name in the JPEG's EXIF** | 1 rel32 `0x6030288d` | Stub about 70 B | Low, metadata | Yes |
| 2 | **Sharpness per slot** | 1 rel32 `0x602a7eda`, Extras sector 9, byte +50 | Stub about 30 B | Low, image | Yes |
| 3 | **Gradation per slot** (Fuji DR-style) | 2 rel32 `0x602a803b`, `0x6042965b`, sector 10, byte +51 | About 30 B | Low–medium, image and AE | Yes, after 2 |
| 4 | **Auto ISO ceiling per slot** | 3 rel32 `0x60426886`, `0x60427991`, `0x603ecd57`, sector 11, byte +52 | About 40 B | Low, exposure | Yes, if AE refresh is fine |
| 5 | **Exposure shift per slot** (film EI) | 2 rel32 `0x604269c1`, `0x60427a9c`, sector 12, byte +53 | About 30 B | Low, exposure | Only after a key check |

Video frame lines are ranked separately: docs/ASPECT.md §7.3.

**Storage limit for 2–5:** the bytes are per slot, not per look. LOOKS.BIN records carry bytes 0..44, and a Film pick zeroes 45..63 (VIDEO_HIDDEN §5.2) [V]. So a pick resets them to "camera". Carrying them in a look means a format change.

### 1. Look name in EXIF

The IFD0 ImageDescription field is empty today, so nothing is displaced.
- [V] Tag table at `0x604dadf0`: tag 0x10E, ASCII, 32 B, offset `0x5a8` (cap+1448). Artist `0x13b` → +1384 and Copyright `0x8298` → +1554 use the same base, and their writers at `0x60302898..0x603028b3` confirm the offsets are capture-struct offsets.
- [V] 4 real E-P7 JPEGs in testdata: IFD0 0x10E is 32 zero bytes. "OLYMPUS DIGITAL CAMERA" appears elsewhere, at TIFF offset 7596 (from key `0x8f11` into cap+2172 through `0x603032f2`).
- [V] No instruction with displacement 1448 exists in `0x602a0000..0x60330000`, so nothing writes the field in capture setup.
- **Hook:** `0x6030288d` is `call 0x6005e971,[d2,d3],12` in rel32 form, reading key `0x5ef1` (copyright enable), once per capture setup [I]. The nearer `0x603032f2` calls for key `0x8f11` (`0x60301348`, `0x603018cd`) are rel16 and cannot reach the free space [V].
- **Stub:** read cap from the caller's (8,sp), which is (20,sp) inside the frame [I: check in the emulator]. `sc_slot` gives the slot entry. That entry may be the flashed table, which has no names, so accept only a heap P. If the name at P+544+16k is valid (P+672 = `EP7N`), copy up to 16 B to cap+1448. Then tail-jump to the getter.
- Stock Exif readers just show the text [I]. RAW: same tag table, unverified whether ORF uses cap+1448.
- Not reached: the second setup path `0x60301342`, and variant jobs. `0x603ee48c` copies Artist and Copyright to variant jobs, not +1448 [V], so bracketing variants may have it blank.
- **Test:** `exiftool -ImageDescription` on JPEG and ORF for two profiles; MONO and stock looks stay empty; one bracket burst.

### 2 and 3. Sharpness and gradation: same technique as nr_get

Debug dump `0x613e7..` names the params fields, and the builder copies them from capture [V]:

| Params | Name | From | Key, sid | Reads |
|---|---|---|---|---|
| +5522 | `chSharp` | +24010 | `0x8119`, 7 | `0x602a7eda` capture, `0x6030ec09` movie, `0x60c67072` RAW edit |
| +5523 | `chContrast` | +24016 | `0x82a9`, 8 | `0x602a8025`, `0x6030ec1f`, `0x60c67086` |
| +5524 | `chTone` | +24018 | `0x8eb9`, 105 | `0x602a803b` capture, `0x6042965b` AE [I], `0x6030ec3d` movie, `0x6020da40` pointer lookup, three in `0x60c6` RAW edit |
| +5525 | `chSaturation` | +24048 | `0x8889`, 59 | `0x602a80c1`, `0x6030ec4b`, `0x60c6709a` |

- **Sharpness:** the call has the same a0 = 0, d1 = 0 form as NR [V]. Stills change; LV and movie stay stock, like NR. Keep values to the stock ±2 until the request's limits are checked [I].
- **Gradation:** request+1797 = 1 High Key, −1 Low Key, 2 Auto (VIDEO_LOG) [V]. Redirect capture and AE so the metering and the curve agree [I]. It feeds the tone LUT choice that v0.19's `lt_post` sits on (TONE_ENDS), so test with Blacks/Whites set. `0x6020da40` caches a pointer and must be checked for a fast read path [I].
- Contrast and saturation: already covered by the look tone and colour work; not worth it.

### 4. Auto ISO ceiling per slot; the stock cap needs no patch

- **Higher Auto ISO cap: nothing to do.** Sid 112's list (`0x604ce1d8`) is 1536..3328 at 256 per stop, ISO 200–25600, the same top as sid 6 [V; the ISO mapping I]. The manual ceiling is already the sensor's.
- Key `0x949a` (sid 112): AE message fields at `0x60426886` and `0x60427991`, one at `0x603ecd57`; pointer lookup at `0x6020d7a6`; UI read `0x602b5273` [V].
- Return a stock-listed value only. AE reads pass a0 = (`0x622a0b40`), so keep the frame intact, as `sc_get` does.
- Unknown: how often those AE messages rebuild, so a profile switch may lag until the next AE update [I]. Test by switching profile at a dim scene.

### 5. Exposure shift per slot

The closest thing to rating film at a chosen EI.
- Menu item sid 273, string 129 [V]. Key `0x30ea` is read at `0x604269c1` and `0x60427a9c`, with key `0x30fa` right after it, and a pointer lookup at `0x6020d393` [V].
- **Not proven:** sid 273 is the menu row, and those two keys may be per-metering values. Read the neighbouring fields before building. A camera test against stock Exposure Shift would confirm it.

### Rejected or not ready

| Idea | Finding | Verdict |
|---|---|---|
| **ART dial as silent switch; silent on a look** | The "Silent H/L" sequencer gate at `0x6093536a` tests sid 764 with 1158 and 1493 [V]. Sid 764 (key `0xf101`) has **8 sid reads and 10 key reads**, including capture, sequencing and LV [V]. Sid 24 has about 190 reads. The ART position also loses its mode. It would need a drive write on dial change or 18 redirects, with flash and NR behaviour following | **Not cheap. Not tonight** |
| Drive sid | Still not resolved. SCP select record `{3281, 21, 0x61175b80, ..}` holds drive-style values [V]; 3281 is past the ID table. Correction: sid 758 is the High Res flag, and keys `0x8151` / `0x8161` are image size and quality classes (`0x6088bcb5`, `0x603f0a2e`) [V] | Open |
| Date stamp burnt in | No "date stamp" or imprint string in the OSD or main, and no YC text stage found [V for strings; I for the stage]. Needs a new drawing step in the job | Hard |
| Film counter ("36 exposures") | `Shooting::getRemainCountInMediaSlot` is only a debug name. The draw site was not located after one pass through `0x60d18..` and `0x60d9b..` [V]. Also needs a session count | Not cheap yet |
| Longer interval limit | Frames sid 479, key `0xde22`, read at `0x6061acfb` and `0x6061e3c8`; no validator or registry record, so the limit lives elsewhere [V] | Not located |
| Per-look aspect | 14 reads with LV and buffers (above). A write on Film pick is possible but lags a profile switch, like old NR, and needs a LOOKS.BIN byte | No |
| Movie limits | Recording limit shipped. C4K and FHD 120 stay on the README's hard list | – |
| EXIF Software tag "Caduceus" | Built from template `0x604ddeb4` "Version x.x" with digits stored at offsets 8 and 10 (`0x60301243..0x6030124e`) [V]. Needs the two stores changed too | Small and optional |

### Reference notes

- ID table `0x604d6c14` entries are 4 B `{key, index}` (PROFILE_INDEX_WB). A 2-B stride gives wrong keys.
- Grid option values and the grid draw path: docs/ASPECT.md §7.3.
