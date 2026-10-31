# Per-profile WB fine-tune and MONO slots rendering colour (E-P7 1.1)

Offline static analysis plus emulator runs only. No camera or device was contacted, no SD-update-named file
was created, and nothing was committed. Main image `5dd9af16…6190`, CPU base 0x60020020.

Labels: **[V]** = read from bytes/disassembly, or run in the emulator on stock code. **[I]** = inference.

Tools (ours):
- `tools/ep7_wb_probe.py`: Part A. Covers the stub unit test, the native capture WB segment stock vs patched, and the native gain function.
- `tools/ep7_mono_probe.py`: Part B. Runs the selector mode 12 vs 11 and the chroma-override stage.

Both exit 0 when every check passes (current state: all PASS).

---

## Part A: WB fine-tune

### A1. Which settings hold A–B / G–M [V]

The prior candidates are **wrong**:

| Candidate | What it actually is |
|---|---|
| 324/325, 326–328, 329/330 (props 2332–2336) + 323/670–675 (prop 2331, 7 bytes) | A group of 1 master + 6 enable flags with ±7 values. It goes to capture+24142..24155, and then `0x60301c1e..0x60301d13` builds records `{id 0x200/0x100/0x300-0x302/0x400/0x500, v, −7, +7}` at capture+3208 (another copy at `0x603eac60`). It has no path into WB. Identity unknown [I]. |
| 130/131 (props 2405/2406) → capture+24054/55 → params+5528/29 → request+1802/1803 | **Mono filter / picture tone.** `0x6030ec90` zeroes them unless picture mode ∈ {5, 12, 104}. request+1803 indexes the toning vectors used by the chroma stage `0x603b1280` (Part B). |

**The real storage is two s8 arrays with one entry per WB mode.** Both use type 9 (signed byte), range ±7 (descriptor table `0x604cd5f8`), and have 20 entries.

- **A–B:** property **2127**, key **0x84F9** (34041).
- **G–M:** property **2407**, key **0x9679** (38521).

| idx | WB mode (from RAW-dev map `0x60c689c6` + capture switch `0x604ddefc`) | A–B setting | G–M setting |
|---|---|---|---|
| 0 | "current" slot. No range descriptor; capture uses it for presets / one-touch / cat 4 | 39 | 132 |
| 1 | Auto (category 0) | 91 | 133 |
| 2 | Incandescent 3000 K (preset 0) | 92 | 134 |
| 6 | Fluorescent 4000 K (preset 4) | 93 | 135 |
| 10 | Sunny 5300 K (preset 8) | 94 | 136 |
| 11 | Cloudy 6000 K (preset 9) | 95 | 137 |
| 13 | Shade 7500 K (preset 11) | 96 | 138 |
| 14 / 16 / 17 / 18 | One-touch 1–4 (category 2) | 144 / 213 / 574 / 576 | 145 / 215 / 575 / 577 |
| 15 | Flash 5500 K (preset 13) | 212 | 214 |
| 19 | category 4 (probably Underwater [I]) | 338 | 339 |
| 3–5, 7–9, 12 | Settings 1508–1514 / 1533–1539. No consumer found | | |

**Answer: the fine-tune is stored per WB mode.**
- **CWB (category 3) has no fine-tune at all.** Capture forces 0/0 (`0x60302e92`), and so does RAW dev.
- **Index 0 [I].** It has no user range, and capture reads it for every preset except Flash. It therefore looks like an "effective / current" value that the settings layer keeps up to date. I did **not** find the writer.
- **Why "A2 G2 affects everything" [I].** Either the user set it through *All*, or the camera writes [0] and capture applies [0] to every preset. Auto ([1]) and Flash ([15]) are read directly. I cannot distinguish these statically.

### A2. Where the fine-tune becomes WB gains

**Still capture [V]:**
1. **WB resolution.** The capture routine segment `0x60302c0f..0x60302fc9` switches on category capture+24006 (prop 33057) and preset capture+24002 (prop 33073). It writes fine-tune **A → capture+24098, G → +24100** (halfwords).
   - A nonzero fine-tune clears the preset code at capture+1874 (`0x60302e00`), so computed gains are used instead of the preset table.
2. **WB bracketing.** `0x603e1a40..` adds the BKT step and writes capture+3028/3030.
3. **Converter.** `0x603e62d1` @ `0x603e6566` writes params+5520/5521 (bytes) from capture+3028/3030, or straight from 24098/24100 when the job type is 19.
4. **Packer.** At `0x60354050..0x60354122` the bytes params+5520/5521 are passed as d0/d1 to the gain calculator **`0x603b5769`**. It is called twice: base params+4466 → job+11322, and params+4474 → job+11330.

**Gain calculator `0x603b5769`** (no prologue; entered with `call 0x603b5769,[d2,d3,a2,a3],80`):
- **Inputs:** d0 = A (s8), d1 = G (s8), a0 = output (4×u16), a1 = base gains (4×u16, [R,B,G1,G2] [I]). Five stack words follow at the caller's (4..20,sp); all 0 on the capture path.
- **Processing:** it normalises the base gains by min(G) (`0x603b5675`). When A or G ≠ 0 it applies the coefficient table `0x6050dea4` = {−2, 100, 2, 100}.
- **Other callers:** recording `0x603511ce/f0` (A/G from converter `0x603e8fc9` → +325/326), the stack-request builder `0x60352d72` → `0x60352ea7/ec8`, and the multi-frame wrapper `0x60348a2a` ← `0x603ee0a2/1ab`.

**Live view / EVF: not proven to use the same function.**
- **[V]** There are only 16 reads of keys 0x84F9/0x9679 in the whole image, all `call 0x6005e971,[d2,d3],12`:
  - 10 in the capture segment above;
  - **`0x6030bb5b/6e`**: idx 0 → the 980-byte "compact" ring slot (+97/+99), index `(0xa273104c)`;
  - **`0x6030eb61/6f`**: idx 0 → params+5520/5521 of a second params builder `0x6030e9d1` (← `0x60329080`), which feeds the same packer/gain path;
  - **`0x60c68a45/59`**: RAW dev, per-mode index.
- **[I]** The EVF almost certainly takes its fine-tune from one of the two idx-0 readers. That is most likely the compact slot, which also carries the picture-mode/saturation fields (HSL_PORT "compact ring"). Its downstream consumer was not traced.
- **Conclusion:** gains are computed from one shared upstream source (the getter reads), but I could not show that capture and live view share a single gain function.

### A3. Hook design: substitute at the property read (recommended)

There is no single gain function proven to feed both paths. The one point that provably feeds **every** image-pipeline consumer, the compact/live candidates included, is the property read.

The 16 call sites are byte-identical in form, **`dd <rel32> c0 0c`** → 0x6005e971. Redirecting each rel32 to a stub `wb_get` with the **same contract** costs one 4-byte data edit per site. No instruction is displaced and the registers are unchanged.

**Contract** (same as the getter, which the stub calls itself):
- **Inputs:** d0 = key, d1 = idx, a0 = 0.
- **Returns:** d0 = value (sign-extended s8).
- **Registers:** clobbers d1/a0/a1 like the getter. d2/d3 are restored by `ret [d2,d3],12`; a2/a3 are untouched.

**Logic:**
1. `v = getter(key, idx)`.
2. If the key is 0x84F9 or 0x9679:
   - `m = getter(38017)` (if m == 6, `m = getter(40209)`);
   - m == 11 → slot = getter(63153) − 1; m == 12 → slot = 4 + getter(63281) − 1. The profile must be 1..4, otherwise stock.
   - If `bundle[slot].wb_flags & 1`, `v = (s8) bundle[slot].wb_ab` (or `.wb_gm`).
3. Return v.

**Stub:** 166 B at **0x6055e700**, in the sec-2 FF tail after grain (`0x6055e680–6fa`), leaving the 16-byte guard to 0x6055e800. All sites are in sec 2 except RAW dev (sec 6, which loads after sec 2).

**Sites** (stock 7 bytes; only bytes +1..+4 change):

| Site | Stock | Role |
|---|---|---|
| 0x60302c46 / 0x60302c60 | `dd2bbdd5ffc00c` / `dd11bdd5ffc00c` | capture, preset/cat 1, idx 0 |
| 0x60302da3 / 0x60302db8 | `ddcebbd5ffc00c` / `ddb9bbd5ffc00c` | capture, Flash idx 15 |
| 0x60302e35 / 0x60302e4b | `dd3cbbd5ffc00c` / `dd26bbd5ffc00c` | capture, one-touch idx 0 |
| 0x60302f23 / 0x60302f3b | `dd4ebad5ffc00c` / `dd36bad5ffc00c` | capture, cat 4 idx 0 |
| 0x60302f8f / 0x60302fa8 | `dde2b9d5ffc00c` / `ddc9b9d5ffc00c` | capture, Auto idx 1 |
| 0x6030bb5b / 0x6030bb6e | `dd162ed5ffc00c` / `dd032ed5ffc00c` | compact slot (live candidate) |
| 0x6030eb61 / 0x6030eb77 | `dd10fed4ffc00c` / `ddfafdd4ffc00c` | params builder 0x6030e9d1 |
| 0x60c68a45 / 0x60c68a59 | `dd2c5f3fffc00c` / `dd185f3fffc00c` | RAW dev (optional; global profile, see risks) |

**Properties of this design:**
- **Menus are unaffected.** GUI/settings code never reads these keys through the getter, so menus keep showing the stored values and nothing is written back.
- **CWB stays without fine-tune**, as in stock, because capture never reads the property for it.
- **WB-BKT still works**, because the steps are added after the read.
- **Bundle table:** 512 B (8×64) does not fit in the sec-2 tail. Either place it elsewhere (stub constant `bundle`), or compact the WB part to 8×3 bytes inside the stub's tail.

**Emulator results** (`tools/ep7_wb_probe.py`, all PASS) [V]:

1. **S, stub unit test** with a fake getter mapped at 0x6005e971 (our test code). These cases behave as expected:
   - COLOR2 override of A and G;
   - flag clear → stock;
   - MONO3 → slot 6;
   - mode 5 → stock;
   - mode 6 resolved via 40209;
   - profile 0/5 → stock;
   - other key passes through.

   d2/d3/a2/a3/sp are preserved.
2. **W, native capture segment `0x60302c0f→0x60302fc9`**, run on stock code vs the 10 redirected sites, for 6 WB categories × 4 profile states. In the whole 25 000-byte capture block, only these bytes differ:
   - **24098/24100** (A/G);
   - **1874** (the preset code that stock clears for a nonzero fine-tune, e.g. Sunny 9 → 0), and only when the override is active;
   - nothing at all for flag-clear, mode 5 and CWB.
3. **G, native `0x603b5769`** (unmodified), base gains (600, 450, 300, 300):

   | A/G | Output |
   |---|---|
   | 0/0 | (600, 450, 300, 300) |
   | +1/−1 | (623, 447, …) |
   | +3/−2 | (658, 438, …) |
   | −4/+5 | (494, 435, …) |

   The output changes only through the A/G inputs.

**Risks:**
- Live-view coverage is inferred: the compact-slot consumer is not traced.
- Profile and mode come from the global properties (option A race in PROFILE_INDEX_WB.md), and for RAW dev the global profile may differ from the one the RAW was shot with. Leave the 0x60c68a45/59 sites stock to avoid this.
- Up to 4 extra getter calls per read.
- When the compact slot refreshes after a profile change has not been checked.

---

## Part B: MONO slots rendering colour

### B4. Selector, mode 12 vs 11 (`tools/ep7_mono_probe.py`) [V]
- **Mode 11** uses the COLOR builder: table 0x6051de2c, control word 0xfff.
- **Mode 12** goes through `0x603af871`. Key 12 is not in hash 0x60532510, so it gets the default descriptor 0x60530eb8: table **0x605120ec**, control word **0xb8f**. With request+1800 ≠ 0 it gets 0x60530eec instead: table 0x60512cc0, control word 0x3cf. Then the general builder `0x603afd26` runs.
- **Diff, 11 vs 12:** 82 words, at output 688..720 and 724..980 (records/control) and 3124..3164 (10 LUT pointers).
- **Inputs the mode-12 output ignores:** request+1816 (S) and request+1828/1829.
- **The mode-12 table is an ordinary colour table** (23 words from the key-1 table). **The selector does not make the image grey.**

### B5. Where mono actually happens, and every other mode-12 site

| # | Site (stock bytes) | Mode-12 effect | Needed for MONO→colour? |
|---|---|---|---|
| 1 | **`0x603b132a`** chroma stage, called at 0x603b1508 from dev sequence 0x603b1466 (request kind 0/16). Hook at **`0x603b134e` `cdadfee010`** (`call 0x603b11fb`; a0 = vector or 0) | Writes output+76 = {1, Cb, Cr} from 0x6050f06e[request+1803]. Emulator: mode 12 0x00808001, sepia 0x008d7501, mode 11 0. **This is the grey/toning stage** [V code+emu; "constant chroma" meaning I] | **Yes:** return a0 = 0 for a colour slot |
| 2 | Selector `0x603b02c1` `a50bc936` | Mode 12 → general builder; S never filled for mode 12 | **Yes:** redirect to the COLOR builder with bundle S |
| 3 | Mono-filter merge `0x60353db9` `fa002c2c a00c c92a` | If job+11308 == 12 and filter ≠ 0, sets params+5564 \|= 0x80\|f<<4, which goes to request+1790 and then the curve generator 0x6039d279 | **Yes**, unless the filter is N (guard or hook) |
| 4 | Converter gates `0x603e66ab` / `0x603e91f2` / `0x603ec1b9` / `0x603f1ab2` | Mode 12 copies filter/grain/shading and skips S | No (the selector stub supplies S) |
| 5 | Work list `0x6035749f`, combiner `0x603b5249` | Mode 12 adds the grain passes | No (luma grain on colour, arguably wanted; output unchecked) |
| 6 | `0x60367ee3` `fa002c2c a00c c85f` | Key 12 **skips** an extra pass (0xff11 / effect 0xfe00, meaning unknown) | Review: a colour MONO slot would lack it |
| 7 | `0x60356b8d` | key 11 → 1, key 12 → 0; no reader found | Probably no [I] |
| 8 | Tone/other selectors 0x603b04fa, 0x603a9914, 0x603ade14, 0x603aa50c, 0x603b0a70 | Same for 11 and 12, except the grain-mask stage | No |
| 9 | `0x613f9322` | Debug printf of capture+24083, **not EXIF** | No. EXIF/makernote still says Monotone (not traced, cosmetic) |
| 10 | Live view: request kind 4 `0x603b18cd` sets defaults with chroma off (0x603b1904) | Unknown whether the EVF uses kind 0/16 or the compact path | **Unverified**: the EVF may stay mono |

### B6. Verdict: feasible, but risky

The selector redirect alone is **not enough**, because grey comes from the chroma stage, not the selector. The minimum is:
1. the selector redirect at `0x603b02c1`;
2. a chroma override at `0x603b134e` (a0 = 0 for a colour slot);
3. a guard or hook at `0x60353db9` for a non-neutral mono filter.

All three are in sec 2.

Open items:
- the skipped 0xfe00 pass (#6);
- live view not traced;
- EXIF still says Monotone;
- the art path calls 0x603b11fb separately (0x603b13e4/0x603b1416), which matters only for art requests.

**Not proven anywhere:** ISP pixel output and on-camera behaviour.
