# Vertical video: recording rotation in E-P7 movie files

Research and design, 2026-11-06. **Built and emulator-checked since, not yet tried on a camera:** see "What was built" below. Sections 1 to 5 are the original research, and the build overrides them where they differ.
**[V]** = read from bytes, code or a sample file. **[I]** = inference. Addresses are E-P7 1.1 main (CPU base `0x60020020`).

Request: "When video is shot vertically, the camera should apply this to the orientation of the video; at the moment it imports sideways."

## What was built

`patches/v026_rot/` (`build.py` exports `apply(spec)`; `rot.s.in`; `verify.py`). Output: `generated/v026_rot/edits.json` and `generated/v026_rot/pkg/`, layered on v0.25. The version label is unchanged until it is composed into v0.26.

```
.venv/bin/python -I patches/v026_rot/build.py releases/v0.25/edits.json --out generated/v026_rot/edits.json
.venv/bin/python -I patches/v026_rot/verify.py releases/v0.25/edits.json generated/v026_rot/edits.json --scratch DIR
```

| Piece | Where | Does |
|---|---|---|
| `rot_start` | hook `0x603d4027`, stub `0x601e24ec` | Real getter `0x6006d157`. Latch = 3, 6 or 8, anything else 0. Stock call. d0 preserved |
| `rot_free` | hook `0x603d4053`, stub `0x601e251d` | Stock call, latch = 0. Return value d0 and d1 preserved |
| `rot_mat` | hook `0x61308ad0`, stub `0x601e253a` | Replays the 6 B, then writes all 9 matrix words from the latch |

Code is 254 of the 256 B at `0x601e24ec–0x601e25ec`.

**Changes from the design:**

- **Latch is `0x6203c8ba`, not the image.** The `0xa0210ffe`-style latch suggested in section 4 is a banned pattern (`docs/APERTURE_RING.md`). It's also a cached store, not uncached: the byte shares a cache line with live stock variables, so an uncached store could be overwritten when that line is written back [I].
- **Identity is written, not skipped.** Any latch other than 3, 6 or 8 writes the identity, the same values as the stock constant. If the trak struct is reused between clips, it can't keep an old rotation.

**Why the latch byte is unused** (`latch_evidence` in `build.py`, re-checked on every build):

- It is padding in the sensor module's statics: u16 at `0x6203c8b8` (only `movhu`), then u32 at `0x6203c8bc`.
- A scan at every byte offset, in all four address aliases, finds no word equal to `0x6203c8ba` or `bb` [V].
- All references to `0x6203c89c..bc` are direct loads and stores. None takes an address, so no base-relative access reaches it [V]. Objects below it end before the module does [I].
- The boot clear `0x6002046d(0x62038100, 0x6203c934)` covers it, so it starts at 0 [I strong: the fill routine isn't emulated].
- Stock stores to `0x6203c8a0` in the same 32-byte line at run time [V].
- Not proven: that no code reaches it through a computed pointer or block copy. Any such write would have to land exactly 3, 6 or 8 to rotate a clip, and only between latch and tkhd write.

**Code space:** build fails on overlap with the incoming spec, or on any reference into the range other than the step-7 B table word `0x601e3cf8`. The scan covers absolute words (with aliases, on the v0.25 image) and call and jmp displacements. Step-7 G (word `0x601e3cf4`) starts before the range and runs into it. Apply order against other layers: `apply()` only sees edits already in the spec, so a layer applied later must make its own overlap check.

**Matrix direction, checked against EXIF.** On a scratch copy of `testdata/camera_t5/PB010042.MOV`, using the bytes the emulated serialiser produced:

| Code | EXIF meaning | Matrix (a b u / c d v / tx ty w) | ffprobe | ffmpeg frame |
|---|---|---|---|---|
| 1, unknown | as stored | identity, equal to the sample's bytes | none | 3840 × 2160 |
| 6 | rotate 90° cw | `0 1 0 / -1 0 0 / H 0 1` | -90 | 2160 × 3840 |
| 8 | rotate 90° ccw | `0 -1 0 / 1 0 0 / 0 W 1` | +90 | 2160 × 3840 |
| 3 | rotate 180° | `-1 0 0 / 0 -1 0 / W H 1` | -180 | 3840 × 2160 |

Each upright frame matches the same frame with that EXIF code applied by PIL (RMS 0.29, against 174 for the opposite direction). That proves the matrix matches EXIF. It doesn't prove movies share the stills' sensor frame: the camera test settles that.

**Emulator checks, all pass** (real sites, real getter, real serialiser, image mapped read-only, stock vs patched):

- Codes 1/3/6/8 and unknown (including `0x106`) and mute on give the right latch, with neighbouring bytes untouched.
- Registers and caller stack match stock (mdr and psw are excluded: scratch at these points).
- Horizontal tkhd bytes equal stock, also over a stale rotated struct.
- Rotated tkhd differs only in the 36 matrix bytes.
- Latch clears after REC_FREE, and re-latching to level gives identity.
- Package parses, restore == stock, decoded main == the emulated image, and the image differs from v0.25 only in the claimed bytes.

**Not proven:** everything needing the camera: the sensor task running in movie mode, REC_START timing, the moov write coming before REC_FREE (if not, clips stay sideways, which is safe), cross-task visibility of the cached byte, chapter splits, trim, time-lapse, camera playback and other players.

### Camera test (E-P7, 4K and 1080p)

Check each with `ffprobe` on a computer, and play it on the camera.

1. **Horizontal:** no rotation, and it looks as it does today.
2. **Vertical, grip up, and vertical, grip down:** one shows -90, the other +90. Each looks upright on a computer and a phone. If both are upside down, 6 and 8 need swapping.
3. **Upside-down:** ±180, upright on a computer.
4. **Horizontal straight after a vertical clip:** no rotation.
5. **Chapter split (over 4 GB, vertical):** every part has the same rotation and plays.

**If a clip won't play:** stop testing and keep the clip. Pull the battery if the camera has hung, then shoot a horizontal clip. If that fails too, flash `restore-stock.pkg.bin` through the normal update route. Send me the clip's size and what `ffprobe` says. A faulting stub at clip end looks like a power cut, so that clip may be lost. If a clip only comes out sideways, that's the safe failure: nothing is at risk, and it just means the latch was 0.

## Verdict

**Feasible, and small.** The camera writes a normal QuickTime display matrix into every clip. It is always the identity matrix, but it sits in a RAM struct that is written to the file through a simple loop. A small hook can replace it per clip. The pixels, file layout and stored size stay the same. Only the metadata changes.

Confidence: high for the file format and the write path, medium for timing. That is the first thing a camera test must settle.

## 1. Where orientation comes from

| Fact | Address | Conf. |
|---|---|---|
| Getter returns the EXIF-style code. No locks, and it clobbers only d0 and a0 | `0x6006d157` | [V] |
| It returns 1 if the setting at `0x6203c89c` is 1 (read from key 8066 at init, `0x6006d08f`). Otherwise it reads table `0x61b21858[state]` | same | [V] |
| Sensor task stores state 1–4 in `0x6203c8a0`, then sleeps 100 ms | loop `0x6006d180`, store `0x6006d416`, sleep `0x6006d42a` | [V] |
| Raw states 0, 4 and 5 all become state 1 | `0x6006d3e0..0x6006d406` | [V]; 4 and 5 meaning lens up or down is [I] |
| Stills latch the getter into capture +24168 | `0x602a9691`, `0x602a9d33` | [V] |
| EXIF builder copies +24168 to +18 only when it is 6, 3 or 8 (otherwise +18 keeps the template's 1) | `0x603029b7..0x603029cd`, template store `0x60301265` | [V] |
| EXIF tag 274 (Orientation) reads +18, 2 bytes | table row `0x604dae20` | [V] |
| Sample JPEGs: Orientation 1 × 274, 8 × 95, 6 × 1 | `testdata/` | [V] |
| Other code compares the getter with 1, 6, 3 and 8 | `0x603c7350`, `0x60bd9159` | [V] |

The getter can be read at any time because it is only two RAM reads. Whether the sensor task keeps running in movie mode is **not proven** [I]. The callers of its stop routine `0x6006d14c` are `0x6006d4e6` (in the sensor code, not read), `0x602f5a1a` (via an SDK call at `0x6076f6b9`) and `0x602f76be`, which restarts it straight away. I did not find a stop tied to movie mode, but I did not rule one out.

Table `0x61b21858` is outside the main image, so its contents were not read. The hook does not need them because it uses the getter's output.

`0x622dd8e6` (`getBodyOrientation`, `0x6086d36b`) is a different value: the UI's copy, which is kept in step with the getter. Don't use it.

## 2. The muxer

There is one muxer: "MP4 Mux Plug-in" (`CAvpiM4mMp4Mux.cpp`, name at `0x61370bb0`). A scan of the plug-in names finds no AVI or other mux [V]. It also writes `.MOV`: sample files have `ftyp qt`, and the same `udta`/`TAGS` strings are in firmware.

| Step | Address | What happens | Conf. |
|---|---|---|---|
| Identity constant | `0x613714d8` (9 words, little-endian, video track) | Audio `0x61370f30`, text `0x61371108`, tmcd `0x61371308`, movie header `0x61370dac` have their own copies. **Don't patch the constant:** it is shared by every clip | [V] |
| tkhd build (`CAvpiM4mMp4TrakVideo.cpp`) | `0x61307dd1`, from the trak init chain `0x61307c88` (called at `0x61306ad6`) | Copies the 9 words to the stack (`0x61307dfe..0x61307e06`), then with memcpy to this+144+48 (`0x61307e94`). Width and height go to +84 and +88 as 16.16 (`0x61307e9b..0x61307eaa`) | [V] |
| Stock rotation logic | none | Nothing touches the matrix between the copy and the memcpy. `X-Rotation-Info` (`0x60eec57b`) is an HTTP header and `rotationCount` (`0x60ac5f0d`) is an SDK seek argument. Neither was seen near the mux | [V] matrix path; [I] others |
| tkhd serialiser | `0x61308ab6`, called from `0x61308869` in the trak's virtual write (`0x61308810`, vtable slot `0x61371610`) | Big-endian writes. The matrix is a 9-word loop reading the struct (`0x61308ca5..0x61308ce5`). So whatever is in the struct at write time goes to the file | [V] |
| moov writer | `0x612fd494`, called from `0x612f891b`; video trak at `0x612fd624` | Runs at clip finish [I]; see section 4 | [V] call chain |

MakerNote or `udta` metadata is not needed, because tkhd can be reached.

## 3. Sample movies

All **23** `testdata/*/*.MOV` clips parse cleanly [V]:

- `ftyp`, `moov` at 0x18, `free`, then `mdat` at **0x3fff8**, so the first 256 KB is reserved for the header. Moov is about 75–90 KB here.
- Three tracks: video, audio and a chapter text track (`gmhd`). All have the identity matrix, as does `mvhd`.
- Video tkhd is 92 bytes at 0x94, version 0, matrix at file offset **0xc4**, 3840 × 2160.
- The largest clip is 469 MB, so no sample has a chapter split.

**Format test on a scratch copy, nothing kept:** I replaced the 36 matrix bytes in a copy of `camera_t5/PB010042.MOV`.

| Bytes written (a b u / c d v / tx ty w) | ffprobe rotation |
|---|---|
| `0 1 0 / -1 0 0 / 2160 0 1` | -90 |
| `0 -1 0 / 1 0 0 / 0 3840 1` | +90 |
| `-1 0 0 / 0 -1 0 / 3840 2160 1` | -180 |

For the first row, ffmpeg's decoder output 2160 × 3840 [V]. That is ffmpeg only. No other player or editor was tested.

Mapping to the getter: code 6 → first row, 8 → second, 3 → third [I]. That matches what EXIF means, assuming movies use the same sensor frame as stills. The camera test confirms it.

## 4. What to latch, and what can go wrong

**Latch at REC_START, write at the serialiser.** Don't read the sensor in the serialiser, because that runs at clip end and the camera may have turned by then. The trak build may run during REC_INIT, before the press [I, not traced], so it is the wrong place to read too.

| Hook | Site | Stock | Does |
|---|---|---|---|
| Latch | `0x603d4027` (5 B, REC_START dispatch; log string `0x60538585`) | `cd f7 01 f0 20` call `0x603d421e` | `jmp` to a stub: call the getter, store the byte, `mov a2,a0`, make the stock call, `jmp 0x603d402c` |
| Matrix | `0x61308ad0` (6 B, tkhd serialiser) | `fa d0 90 00 43 04` `add 144,a0; mov a0,(4,sp)` | `jmp; nop` to a stub: replay both. If the latch is 6, 8 or 3, store the matrix using W and H already at (84,a0) and (88,a0). Uses only a0 and d0, keeps a1. Resume `0x61308ad6`. The bcs at `0x61308ac5` targets the start of the hook, so that is safe |
| Clear | `0x603d4053` (5 B, REC_FREE dispatch; log string `0x605385a4`) | `cd 5c 03 f0 20` call `0x603d43af` | `jmp` to a stub: make the stock call, zero the latch, `jmp 0x603d4058` |

The latch is one RAM byte, with a precedent in `0xa0210ffe` (aperture ring, uncached alias). It crosses tasks, so use the uncached address [I].

**Size:** about 125 B of code + 1 B + 16 B of hook sites [I, not assembled]. In `releases/v0.25/edits.json`, unused bytes include `0x601e24ec–0x601e283c` (848 B) and `0x601e2a94–0x601e2c3c` (424 B) in the dead EVF tables [V]. Claim in `docs/CODE_SPACE_MAP.md` when built. None of the three hooks overlaps a v0.25 edit [V].

| Risk | Detail | Conf. |
|---|---|---|
| **Header timing** | `stco` and sample tables need the finished clip, and the header space is reserved up front, so moov is written at the end. A provisional earlier write would be harmless, because the last one wins | [I] strong |
| **A stub bug can lose a clip** | The matrix stub runs while moov is being built. A fault there leaves an unplayable file, like a power cut. Only the new bytes can cause this, and the stub is short | [I] |
| **REC_START hook** | A fault at the start of recording stops recording. No flash, no setting and no boot path are touched. A battery pull clears it | [I] |
| **Chapter splits** | `AVSCA_INF_DIV_FILESIZE` (`0x605374ca`), `DivStop` (`0x60538d6c`) and `GET_FILE_PATH_DIV` (`0x605390f0`) exist [V]. Each split file should get its own moov [I]. The latch lasts until REC_FREE, so all parts share one rotation. Untested: no sample over 469 MB | [I] |
| **Turning mid-clip** | The clip keeps the orientation from the press, as phones do | by design |
| **Held near level, or lens up or down** | The latch takes the last polled sensor value. Lens-down at the press gives 1 (no rotation) [I]. Worst case a clip is wrongly rotated, and any editor can fix that | [I] |
| **Other paths through the mux** | In-camera trim (`MOV_EDIT_TRIMMING`) and time-lapse movies (`Create_TimeLapseMovie`) were not traced. If they skip REC_START, the latch is 0 and they get identity, the same as today. A trim of a rotated clip would then lose its rotation. If they use REC_START, they get the camera's position at that moment | [I] |
| **Camera playback** | Stored W and H are unchanged, so the stock size checks (`0x603d80a0`, `0x608379f1`, `0x60a00b20`) still pass [V]. I did not check whether the demuxer reads the matrix. It probably ignores it, so clips look as they do today on the camera [I] | mixed |
| **Thumbnails** | The clip has two JPEGs in moov (file `0x1288`, `0x422b`) that stay landscape. Some file browsers may show them sideways. Not checked | [V] exist |
| **Editors** | Phones use this same matrix, so mainstream players and editors should honour it [I]. **None tested except ffmpeg.** A tool that ignores it shows the clip sideways, which is today's behaviour | [I] |
| **Muted orientation** | If key 8066 is set, the getter always returns 1. Sample JPEGs show 6 and 8, so it isn't set on this body | [V] |

## 5. Effort and camera test

**One agent session** to build the patch with emulator checks on the stubs, plus one camera test round. Tests can stay minimal: no setting, no UI and no change to the file's layout. A menu toggle isn't needed for a first build.

Camera test (E-P7, 1080p and 4K):

1. Landscape clip: byte-identical matrix, plays on camera.
2. Grip up and grip down clips: `ffprobe` shows ±90, and each looks upright on a computer and a phone. This settles the direction of 6 and 8.
3. Upside-down clip: 180.
4. Start vertical, rotate during the clip: stays vertical.
5. Start landscape straight after a vertical clip: identity. This proves the latch updates.
6. Rotated clip plays on the camera, and in-camera trim still works.
7. Time-lapse movie plays.
8. A clip over 4 GB: every part has the same matrix.
9. Open a rotated clip in one mainstream editor.

## Not confirmed

- **Whether the sensor task is running when movie recording starts.** Tests 2 and 5 answer this, and it's the one thing that could make the latch wrong. If it isn't running, the fix needs a read from the level sensor path instead (`0x6006fde8`).
- That REC_START arrives at the press, and not at a ready state earlier. Dispatch is `0x603d4027`; the sender was not traced.
- The order of REC_START relative to chapter handling, and whether trim and time-lapse use this path.
