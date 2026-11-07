# Film grain on COLOR (Color Profile) images: E-P7 1.1

This is offline research only. Nothing here has run on a camera, and no SD-update-named file was made.
The decoded main image is `5dd9af16…6190`, with CPU base 0x60020020. Every address below was read
from that image with `tools/dis.sh` or `tools/ep7_xref.py`. The PEN-F references are fishcu's GRAIN.md
and CREATIVE_PROCESSING_JOBS.md. They were used only as a map; no code was copied.

Labels: **[V]** means verified from bytes and/or in the emulator. **[I]** means inference.

## 1. How Monochrome-Profile grain becomes processing parameters

| Step | E-P7 1.1 | Evidence |
|---|---|---|
| Setting read | Capture population `0x602a86d6`: property **0xf769** → capture+**24085**. Its neighbours are 0xf7a9 → +24084 (mono filter) and 0xf7c9 → +24086 (shading). This is the same routine as the HSL `capture_acquire` site. | [V] code |
| Mode gate | Converter `0x603e62d1` at **`0x603e66ab`**: `movbu (a3),d0; cmp 12,d0; bne` (stock `f0 43 a0 0c c9 26`). **Only mode 12 (MONO)** copies cap+24085 → params+**5551** (job+5587). Mode 11 (COLOR) copies only the 12 S values and shading (+24086 → params+5552). Same gate in the other converters: `0x603e91f2` (recording), `0x603ec1b9`, `0x603f1ab2`. | [V] code |
| Request | Packer `0x60354ce4`, at `0x60354f30`: params+5551 → **request+1828**, and params+5552 → request+1829. Request size 1884, embedded at job+11364. | [V] code |
| Work list | Builder `0x60357415` dispatches on job key **job+11308** (12 = MONO, 11 = COLOR). Keys < 12 skip the hash and go straight to the default (`0x6035749f`). Key-12 handler `0x6035778b`: **job+11320 = 0** (job classes 0–3): mask pass `0x60359bc8` (setup `0x60359e01`, stage **0x0900**), then grain-image pass `0x60359cd8` (setup `0x60359e15`, stage **0x0901**, which copies the mask descriptor to request+532). **job+11320 ≠ 0** (classes 4–9, table `0x60521ad4`): the default development entry `0x60356d7b` plus request modifier **`0x60359e5e`**, which sets stage **0x0902** on the same request (single pass). | [V] code |
| Combiner select | `0x603b5200`. For key 12: stage 0x0901 → **31**, 0x0902 → **32** (`0x603b531a`). Key 11 → default path, which looks up effect code request+1838 (= 0x0400 for development) → **0, no combiner**. Callers: `0x603a0165` and `0x60339d3c`. | [V] code + emulator T1 |
| Combiner config | `0x603a013b` → hash `0x60524508` → handler 31 `0x603a05b3` / handler 32 `0x603a065b`. Bank = base+7364. Level byte request+1828 ∈ 1..3 → gain bank+136. | [V] code + emulator T4 |
| Gain tables | **`0x604ec0ce` = 110/300/600** (combiner 31), **`0x604ec0d4` = 50/75/100** (combiner 32). These match PEN-F's two tables exactly. | [V] bytes |
| Seed | 31: halfword read from the mask descriptor (request+276…) \| 0x80000000. 32: RAM counter `0xa27393f8`, incremented each time \| 0x80000000 → bank+172. | [V] code + emulator |
| Mask curve | **`0x605003aa`**: 256 halfwords, 0 through index 36, 1023 from 120 on. These are fishcu's values. Returned by the tone selector `0x603b04fa` for key 12, stage 0x0900 (table `0x60532738`), so it is the LUT for the **mask pass only**. | [V] bytes/code |

**Grainy Film art filter: not resolved.** Nothing else references either gain table. Art filters use keys
0x0101xxxx/0x0102xxxx (Type I/II) and combiners 1, 4, 5/6, 34/35 and 36/38. Feature bits 0x20000/0x40000
attach modifiers `0x6035b1dc`/`0x6035b2ad` (effect 0x0900 → combiner 156, constant 115 to bank+136;
0x0901 → combiner 29). I could not prove that any of these is Grainy Film. [V] for the facts, [I] for any
mapping to Grainy Film.

## 2. Why COLOR gets no grain

There are three independent gates, all [V]:
1. **Parameter:** the converter copies the grain level only for mode 12, so request+1828 is never set from the setting for COLOR.
2. **Job wiring:** key 11 takes the default work list, a single development entry with no grain pass and no grain modifier.
3. **Combiner:** the selector maps stages 0x0901/0x0902 to 31/32 only for key 12. Key 11 never gets a grain combiner.

The mono conversion is driven by picture mode/key 12, not by the grain stage [I]. In the stock 0x0902
route, grain is just a combiner on the normal development request.

Is grain applied to luma only? [I] fishcu's desktop analysis says Cb/Cr pass through. Handler 32 writes
clamp-like words that fit a Y-only noise clamp (bank+148 low = 0xffe6 ≈ −26·256, close to −6682).
Nothing here proves that the ISP leaves chroma alone.

## 3. Patch design

### v0.4: per-profile, off by default, stock job-type gate (implemented; supersedes the v0.3 placement below)
Fixes review v0.3 H1 and H2 (docs/REVIEW_v03.md). Build: `python3 -I patches/grain/build.py --out <dir>`
(no level argument any more). Needs the bundles patch in the same package; without it the table bytes are
erased (0xFF), every check fails and the output is stock.

| Edit | Address | Stock | New |
|---|---|---|---|
| Work-list hook | `0x6035749f` (7 B) | `aa0cc605cc0604` | `jmp wl_hook; nop; nop` |
| Selector hook | `0x603b5249` (7 B) | `aa0cc605cc5201` | `jmp sel_hook; nop; nop` |
| Code | `0x60210ce0–0x60210dde` (254 B, sec-1 FF tail; claim 0x60210ce0–0x60210e00) | FF | `wl_hook`, `sel_hook`, `grain_mod` |

The code moved from the section-2 tail (128 B, too small) to section 1. Section 1 loads first, so the
sec-2/sec-5 hooks can never run before it exists. The old 0x6055e680–0x6055e700 range is left FF.

- **H1, job-type gate [V emulator T6].** Before attaching anything, `wl_hook` runs the same test as
  stock key 12 at 0x6035778b: `movhu (16,a2)` = job+20; if `type&0xf0 ∈ {0x10,0x20,0x40}` or
  `type&0xf00 == 0x100`, it goes to the plain default entry 0x603578a9 (no grain). So the special
  capture jobs from capture-request kinds 0x2001/0x2006 (types 0x110/0x120 from mapper 0x603ea909) are
  never grained, exactly as stock MONO.
- **H2, per profile [V emulator T2/T3/T4].** Both `wl_hook` (a2 = job+4) and `grain_mod` (a0 = job) can
  reach the job, so both read the v0.2 transport bytes directly:
  job+15490 == 0xB2, job+15489 == 11, job+15488 = profile 1..4 → slot 0..3, then slot+24 (`grain`) must
  be 1..3. The level written to request+1828 is that byte (gain 50/75/100). Any failure (no marker,
  invalid index, mode ≠ 11, grain 0 or > 3, erased table) → stock work list / untouched request.
  `grain_mod` re-checks everything, because it uses `retf` (no calls, MDR intact); it clobbers d0 and a0
  only, and its caller (0x60356d72) uses only d0 afterwards.
- **Where the job comes from [static].** The builder 0x60357415 is reached only from 0x60356297 ←
  0x60354756 (job dispatcher), and every job is made by the constructor 0x603537eb (the only `mov 15488`).
  With the bundles patch, every job is 15512 B and its extension is zeroed, so jobs that never pass
  conv1/conv2 have no marker → stock.
- **Remaining difference from stock MONO [I, risk 1 below].** For job classes 0–3 (job+11320 == 0) stock
  MONO uses the two-pass mask route; COLOR still uses the single-pass 0x0902 combiner. T6 checks that
  grain is present for exactly the same job types in both, and for classes 4–9 that the work list is
  identical to stock MONO's (with `grain_mod` in place of 0x60359e5e).

### v0.3 Approach B: fixed level (superseded by v0.4)

### Approach B: fixed level (implemented: `patches/grain/`)
The patch adds the stock single-pass MONO configuration to COLOR jobs.

| Edit | Address | Stock | New |
|---|---|---|---|
| Work-list hook | `0x6035749f` (7 B) | `aa0cc605cc0604` (`cmp 12,d2; bcc; jmp 0x603578a9`) | `jmp wl_hook; nop; nop` |
| Selector hook | `0x603b5249` (7 B) | `aa0cc605cc5201` (`cmp 12,d2; bcc; jmp 0x603b539f`) | `jmp sel_hook; nop; nop` |
| Code | `0x6055e680–0x6055e6fa` (123 B) | FF | `wl_hook`, `sel_hook`, `grain_mod` |

- **wl_hook.** Entry state: d2 = key, a3 = list, a2 = job+4, inside the frame of 0x60357415.
  - Keys ≥ 12 → `0x603574a6`. Keys ≠ 11 → `0x603578a9`.
  - Key 11 rebuilds the default entry: `call 0x6035739e,[d2,d3,a2,a3],16` with a1 = 0x60356d7b, d1 = 0x60356cc6, d0 = 1.
  - It then calls `0x603573d3,[a2,a3],8` with a1 = `grain_mod`, and jumps to `0x603578bd`.
  - This is the same sequence as stock key 12 at 0x603577b6..0x603578a7.
- **sel_hook.** Entry state: d2 = key, a2 = ctx+4, frame `[d2,a2],12`.
  - Key 11 with a kind-0 request and stage 0x0902 → `mov 32,d0; ret [d2,a2],12`.
  - Everything else goes to the stock targets 0x603b5250/0x603b539f. Only d0/a1 are clobbered, which is the same as the stock paths.
- **grain_mod.** Called as `calls (a2)` from 0x60356d72 with a0 = job, a1 = request.
  - For a kind-0 request it writes request+1828 = LEVEL and stage = 0x0902, then `retf [],0`.
  - It uses only d0, which matches 0x60359e5e.
- **Result:** gain = 50/75/100 for `--level 1/2/3`.
- **Coexists with v0.1:** v0.1 uses 0x603b02d9 (+5) and 0x6055e5c0–0x6055e677. The 16-byte guard to 0x6055e800 is kept.
- Code and hooks are both in section 2.

### Approach A: reuse the Mono-profile setting (designed; modifier built; converter hooks not written)
- Build with `--level mono`. The modifier then keeps request+1828 as packed and does nothing when it is 0 (Off).
- The level also has to reach params+5551 for mode 11. Hook each converter gate with a 6-byte `jmp` + `nop`:
  - `0x603e66ab` `f0 43 a0 0c c9 26`; resume at mono 0x603e66b1 or skip at 0x603e66d5.
  - `0x603e91f2` `f0 40 a0 0c c9 26`.
  - `0x603ec1b9` `f0 43 a0 0c c9 64`.
  - `0x603f1ab2` `f0 41 a0 0c c9 3a`.
  - Each stub does: `if mode==11: params[5551] = cap[24085]`. In 0x603e62d1 that is `(20,sp)` = capture and `d3` = params; registers differ per site.
- **Open question [I]:** whether property 0xf769 still holds the Mono-profile grain value while COLOR is selected. It is a single-valued property (count 1 in the table at `0x600bde88`), which suggests "effective, current". Needs a capture-population trace with mode 11.

### Approach C: full-res parity with MONO (not attempted)
This would use the mask pass (0x0900, LUT 0x605003aa) + grain pass (0x0901, gains 110/300/600) for COLOR.
It needs the mask job, a 0302 intermediate plus an output pass, and a key-11 → 31 rule. fishcu notes that
the mask wrapper forces a mono word and the buffers are about 96 MiB. It is much larger.

### v0.16: COLOR-only gain boost (patches/grain_boost; releases/v0.16)
Camera feedback: COLOR grain (combiner 32, 50/75/100) is far too weak. The blanket fix (table pointer at 0x603a06dd
→ 0x604ec0ce) would also change stock MONO small-job grain, so the boost is keyed on the job key instead:
hook A 0x603a065b (handler-32 entry) replays its two loads and puts the key (52,ctx) in d2 (free in handler 32;
restored by `ret [d2,d3,a2,a3],20`); hook B 0x603a06dd adds 0x604ec0d4 and, for key 11 only, subtracts 6 →
0x604ec0ce. COLOR levels 1/2/3 → gain **110/300/600** (MONO full-size values; no mask pass, so the look is not
identical to the mask route). Key 11 reaches combiner 32 only via our sel_hook, so MONO/art keep stock banks.
Verifier (`tools/ep7_grain_verify.py`): T4 COLOR gain 110/300/600, bank == stock MONO 0902 except +136; new T8:
keys 12/0x01010068/0/5/10 × stages 0x0901/0x0902 × levels 0–3 byte-identical to stock, erased table → stock.
Negative control (unconditional strong table) fails T8.
**v0.16c (camera: High still too weak): COLOR gains 220/600/1200** from our own 3 × u16 table `gb_tab` (0x60210e38;
`patches/grain_boost/build.py --gains`). Gain field = bank+136 low halfword; stock packs signed halfwords there
(+1024, and −1024 = 0xFC00 in combiner 6), so it is ≥ 12-bit signed: ≤ 2047 cannot wrap (build limit). No CPU clamp
on the gain; the noise clamp −6682 (bank+148) already saturates at 600, so higher gains add mostly bright-side
grain and lift the mean slightly. Desktop estimate: `sim/grain_boost_preview.py`
(model uncalibrated to camera; midtone std ×2.2/×4/×6 vs the old levels).

### v0.22 test build (dropped): COLOR stills on the stock MONO full-size route (Approach C; patches/grain_c)
Camera: S and L frames in colour but no visible grain. **Replaced by v0.22 noise filter per look** (patches/v022: slot byte → stock Noise Filter, setting 1334: 0 Global = untouched, 6 Std = 0, 1 Low = −1, 2..5 Off = −2; labels `1 Noise Global/Std/Low/Off`; combiner COLOR grain inert, GLEVEL bounds 0). Verify: `patches/v022/verify.py` R 8 / G 9 / S 16 / K 40 / W 24 / L / D / P.

Camera (v0.21): combiner 32 adds nothing visible on COLOR stills, full size or S, even at gain 1800. Mapping run
(`patches/grain_c/map.py`, real builder to finalize 0x60357c91): stock key 12 class 0 = mask pass 0x60359bc8 + grain
image pass 0x60359cd8 (pending, no single-shot variant), and the feature chain then appends post-pass *entries*; the
last one outputs. Every COLOR job carries 0x80000 (creative shading, 0x60353bcf), whose entry 0x6035b529 follows.
v0.22: when the v0.21 wl_hook accepts a COLOR job (gate, marker, slot grain 1..5) **and** class 0 **and** job+16 has
0x80000, `gc_wl` writes params+5551 (job+5587) = min(level,3) and adds the two stock MONO entries (as 0x603577d4);
`gc_sel`: key 11 stage 0x0901 → 31; `gc_tone`: key 11 kind-0 stage 0x0900 → mask LUT 0x605003aa. Else v0.21.
Gains = stock MONO 110/300/600 (slot 1/2/3; 4/5 = 600). Buffers: the passes' own job+10992 records, released by the
dispatcher (0x6035490d/0x60354930) as for MONO. `patches/grain_c/verify.py`: W 26 (list == stock MONO for the same
flags; grain 0 / no 0x80000 / class 4 / gated types / other keys == v0.21), T 24, C 4, F 2 (stock alloc-failure
returns 40643/40654), P. **Unproven on camera:** chroma through the 0x0302 grain image pass with key 11, memory
with bloom/clarity entries, burst/RAW+JPEG timing (same entry shapes as MONO).
 (emulator; `tools/ep7_grain_verify.py`, fishcu's libsim runner)

**v0.4 (current verifier, `generated/v04/grain/verify.json`).** A synthetic bundle table is injected at
0x60210900; on a merged spec the real table is also used (T7).

| Test | v0.4 result |
|---|---|
| T1 selector matrix | **PASS**, as v0.3 |
| T2 work list, 13 per-profile cases | **PASS.** Grain only for marker+mode 11+profile 1..4+slot grain 1..3; no marker, wrong marker, mode 12, profile 0/5/255, grain 0/4/0xFF → byte-identical to stock. Keys 0/5/10/12/0x01010068 identical to stock |
| **T6 job-type gate vs stock MONO (H1)** | **PASS (77 rows).** Capture kinds 0x2001/0x2006 ((206) = 1/2, 0x603ed45a = 0/1), 0x1008/0x1006/0x1001/0x3001/0 run through the stock mapper 0x603ea909 (types 0x110, 0x120, 0x1000, 0x0), plus 22 direct types, each at job class 0 and 4. Patched COLOR grains a job **iff** the full stock key-12 handler grains it (two-pass mask route at class 0, single-pass 0x0902 at class 4); class-4 lists equal stock MONO's except the modifier address; gated jobs equal stock COLOR exactly. Negative control: the v0.3 grain build FAILS T2/T3/T4/T6 |
| T3 modifier, 13 cases × kind 0/3 × 2 input levels | **PASS.** Valid slot → stage 0x0902 + level; else untouched; job untouched |
| T4 combiner config, slot grain 0..3 | **PASS.** 1..3 → handler 32, gain 50/75/100, bank identical to stock MONO 0x0902; 0 → stock |
| T5 spans | **PASS** (264 B in 3 spans) |
| T7 real table (merged) | **PASS** on `releases/v0.4-candidate/edits.json` (see its README) |

v0.3 results (fixed level) for reference:
These runs check CPU-side configuration only; they say nothing about pixels. Each one builds the real
package in memory with `tools/build_package.build` and runs patched vs stock code.

| Test | Result (levels 1, 2, 3, mono) |
|---|---|
| T1 selector: 6 keys × 2 kinds × 4 stages × 4 effect codes | **PASS.** Identical to stock except key 11 / kind 0 / stage 0x0902 → 32 (stock 0, 156 or 33). Stack, d2/d3/a2/a3, ctx and request unchanged. |
| T2 work list from 0x6035749f, real 0x6035739e/0x603573d3 | **PASS.** Keys 0/5/10 match stock byte for byte. Keys 12 and 0x01010068 reach 0x603574a6 unchanged. Key 11 matches stock except that the entry's modifier is `grain_mod` and the attach flag is consumed. Stack and regs intact. |
| T3 modifier vs stock 0x60359e5e | **PASS.** Only request bytes 12–13 and 1828 change (mono: 12–13, and only if level ≠ 0). Kind 3 is untouched. Returns 0. |
| T4 combiner config 0x603a013b on a key-11 request | **PASS.** Patched → handler 32: gain = 50/75/100, seed 0x80000000\|(ctr+1), counter incremented. **The bank is byte-identical to stock MONO key 12 + stage 0x0902.** Stock COLOR → default handler, counter untouched. Mono/Off → identical to stock. |
| T5 | **PASS.** 130 changed bytes, all inside 3 spans. Merged with v0.1 (`--merge generated/hsl-fixed-test/edits.json`): 239 bytes in 5 spans. `ep7_verify_package.py` H/L checks PASS 4/4 on the merged image. |
| Interior xrefs | No branch or call targets inside either 7-byte hook span or into the new code (`ep7_xref.py --short`). |

Example output: `generated/grain-color-L2/{edits.json,verify.json}`.

## 5. Risks (highest first)
0. **v0.4 load (H2).** Grain now runs only on COLOR profiles whose bundle slot sets `"grain"`. A bundle with no grain gives stock COLOR jobs.
1. **[I] Combiner 32 runs on full-size stills.** Stock uses it only for job classes 4–9 (job+11320 ≠ 0). Full-res MONO uses the mask route. The internal-mask path may have width or line-buffer limits, and could fail or corrupt output on full-size COLOR images. This is the main unknown.
2. **[I] Chroma preservation and the look are unproven.** The weighting uses no 0x605003aa mask, and gains 50/75/100 are lower than 110/300/600, so grain will probably be finer and weaker than MONO Low/Med/High.
3. **[V] Modifier slot.** Our modifier takes the development entry's single modifier slot (0x603573d3). Later feature modifiers on COLOR jobs then use the stock fallback, a separate entry. Stock MONO 0902 behaves the same way, but this means an extra pass and more memory for COLOR + features. Not traced for the COLOR shading path.
4. Not covered by this patch:
   - other job paths: compact/live view (0x6030ed1b, 0x6032438a) and CPU2 converter;
   - RAW-edit applies, because it shares key 11 and the work list [I];
   - movie;
   - the second builder bypass from HSL_PORT.md (it is not related to grain).
5. Inherited from v0.1 (`docs/REVIEW_fixed_hl.md`): the update/restore path is untested, the persistence of the FF tail is unproven, and container validity does not prove the package boots.

## Issue #5 verdict: own grain generation on colour (research, nothing built)

**Hard. Not feasible as a CPU pass until CPU access to image memory is mapped; an ISP texture pass is unproven.**

- **CPU pass over the YCC buffer:** blocked. Reading an image buffer through a job descriptor address crashed the camera (HALATION_RED
  §10e) [V camera, I cause], and the CPU address map of image memory is unknown. Time, if it were mapped: about 20 MP × 2 planes,
  [I] order of 1–3 s per shot on uncached memory, at several cycles per pixel. CPU clock and memory speed were not measured; this is a
  guess, and it blocks the record task during burst. Hook point would be after development, before JPEG; not traced.
- **Grain on the JPEG file:** not possible without a full decode and re-encode.
- **ISP combiner + noise texture:** combiner 136 is a stock additive A + B, kind 3, with B from a request buffer (BLOOM_HALATION §4, §7)
  [V]. Cost [I]: one full-image pass, about one Soft Focus blend, plus a buffer of about 40 MB. Blockers:
  - who fills B: the CPU can write the vignette mask format (128×128 u16, stock generator `0x60338d49`), but that is too coarse for grain, and tiling is unproven (HALATION_RED §10b);
  - grain needs per-pixel detail, and the upscale pass interpolates, so a low-resolution texture gives blotches [I];
  - needs a CPU-writable address for a full-size buffer, which is the same unknown map.
- **Stock route:** combiner 32 and the MONO route (v0.21, v0.22 test) showed nothing visible on colour at any gain [camera].

**Next cheap question:** the CPU-visible address of a job buffer. Without it, no route exists. Camera tests would be needed for any of
this; a garbled frame or crash is the failure mode, not a brick.

## OM-3 v0.21 colour grain: what it changes for the E-P7 (read 2026-11-07, repo `41e7e8b`, nothing built here)

[androidfanman/caduceus-om3](https://github.com/androidfanman/caduceus-om3) (Apache-2.0) reports working grain on COLOR, camera-tested on the OM-3 only. It has two routes. Both contradict the "blocked" verdicts above, so those are now open questions on the E-P7, not dead ends. `[V]` = read here, `[I]` = inference, and OM-3 results are as stated by that project.

**Fast route (no added save time):** `xb_dev` hooks the call into the combiner selector. On a kind 0, output 0x1000, key 11 request with Grain 1..3 and no Glow or Art, it writes the grain level, sets request+10 = 12 and sets context key = 12. The request stays colour.

| Item | OM-3 | E-P7 |
|---|---|---|
| Selector call | `0x604955f1`, 7 B | `0x60339d3c`, same shape [V] |
| Context key | +48 | +52 [V, selector] |
| Grain level | request+1751 | request+1828 [V] |
| Kind, output, key | +16, +14, +10 | +16 and +14 read by the selector [V]; +10 unchecked |

Our earlier tests differ: v0.21 and v0.22 kept key 11 and forced the combiner or added passes. Changing the key on the one request was never tried.

Open points:
- **The mechanism isn't explained.** The E-P7 selector returns 31/32 for key 12 only when request+12 is 0x0901/0x0902 [V `0x603b531a`], and `xb_dev` doesn't write +12 [V]. Trace what the key change reaches in the emulator before trusting a port.
- **Our COLOR hooks may skip the request.** Hooks that test key 11 (HSL, tone, combiners) could stop applying after the change. The OM-3 had to widen its tone gate to accept key 12 with +1731 == 0.

**CPU route (Glow, Clarity or Art with Grain; about 3 s per photo, no fast burst):** after the Soft Focus blend setup, it rewrites Y through a bus window. This answers the "CPU-visible address of a job buffer" question above for the OM-3: 0xa0000000..0xb7ffffff direct, anything else via this CPU's window register, under the firmware's lock (`xb_open`).

Where the time goes [I, instruction counts from `xb_p1s` and `xb_p2s`, timings from its comments]:
- About 0.63 ms per row × 3888 rows ≈ 2.4 s. Cached rows are already used (1.08 ms uncached).
- Noise generation is about 45% of the loop instructions, the table lookup about 55%.
- K=2 saved 0.3 s over K=1, so about 0.3 s of flushing remains.

Speed-up options, best first (all estimates, none tested):
1. **ISP grain on Glow's first development request.** No CPU pass, so no added time, and the blend is mostly the sharp layer, so grain should survive slightly softened. His route is gated to output 0x1000, and his public docs don't say whether this was tried. If it works, the CPU route isn't needed.
2. **Pre-generated noise tile.** Replaces per-row noise with a tile (about 1 MB) and a per-photo offset, for roughly 3 s → 2 s. Check for visible repetition. Still too slow for burst.
3. **Larger K.** At most about 0.2 s saved, with interrupts masked for longer. Not worth the risk.
4. **Additive combiner 136 with a CPU-filled noise buffer.** The bus window removes one blocker, but it needs a full-size buffer of about 40 MB and is the most work.

**E-P7 first test:** the fast route alone, emulator trace first, then one camera build. A crash or garbled frame is the expected failure mode. Credit the OM-3 port in `NOTICE` if it is used.

## Fast route on the E-P7: emulator trace and test t1 (2026-11-07, not camera-tested)

Build: `patches/grain_fast/`, output `generated/grain_fast/t1/` (v0.26 + 110 B). Idea from the OM-3 port's `xb_dev` (Apache-2.0, repo `41e7e8b`); the code is ours. Credit it in `NOTICE` if this ships. `[V]` = read or emulated here, with the real runner `0x60334db4` on a synthetic request and bank allocator and lock stubbed. `[I]` = inference. The OM-3 image was not used.

**1. What the key change reaches**
- `[V]` The key is request+8..+11 (+10 is its low halfword). `0x60344a1e` builds context+52 from it once per run. The stock two-pass path `0x6033513d` reuses the context, but only for stage 0xB009/0xB00A or type low nibble 5, not type 0x1000 stills. Request+14 is the job type (job+20; mapper `0x603ea909` gives 0x1000 for ordinary stills).
- `[V]` **The literal OM-3 recipe does nothing here.** Level, +10 = 12 and context key = 12 leave the bank byte-identical to stock COLOR, because the selector returns 0 at stage 0. The only stock reader of the level is handlers 31/32. Why it makes grain on the OM-3 is unexplained.
- `[V]` **The E-P7 also needs request+12 = 0x0902.** With it, 33 bank words change (combiner block and routing), and the bank equals stock MONO key 12 + 0x0902 except for the colour stages. MONO's chroma word (bank+1768 = 0x00808001, grey) stays 0.
- `[V]` This bank equals the v0.21 route's except for the gain word. **The difference is the job:** v0.21's modifier took the slot of Shading's `0x6035b03a`, so its job had two entries (`dev` + `0x6035b529`). A plain COLOR job has one, `0x60356cc6`, and t1 keeps it. `[I]` That is the only reason to expect a different camera result from v0.21, which measured grain 5 == grain off at full size.

**2. Colour edits:** `[V]` no compensation needed. The stage list runs before the site (trace position: HSL COLOR branch 3728, tone 5570, chroma 5822, site 11336), and every word in the colour-stage range matches v0.26 COLOR. WB and the bloom flag are capture-side, and t1 skips any job with Glow. The OM-3's tone-gate change has no counterpart here. Handler 32 sees key 12, so the v0.16 boost doesn't apply and gains are stock 50/75/100.

**3. Ordering:** `[V]` the stub is in section 1 and calls nothing but the stock selector. It uses d0, d1 and a1, with no stack frame and no `fb` forms. Only the call's rel32 changes. The stub also runs on live view requests, and leaves at the type test.

**4. Glow (not built):** `[V]` the first entry of a Glow job is `0x60356d7b`, kind 0, with its modifier slot free and effect 0x0400 (no combiner). The type is also 0x1000, so on the E-P7 the entry count separates it, not +14. Selector and bank would work the same way. `[I]` It has the same shape as v0.21 (development to a buffer, then more passes), so expect no grain unless a t1 result changes that view. Test it only if t1 shows grain.

**Gate:** kind 0, type 0x1000, 32-bit key 11, stage 0, effect 0, job+11314 == 1, job+15490 == 0xB2, job+15489 == 11, profile 2..4 -> level 1..3. `[V]` Effect 0x0c00 (Shading not 0) skips grain, which keeps Shading.

**Verifier** (`patches/grain_fast/verify.py`): G 62/62, R 10/10, W 30/30, P pass. Package `22bc3b82…4320`; restore `963f4dfe…2327`, as v0.26.

**Not proven:** whether the processor shows grain on the direct route, its look and strength, real request contents (synthetic fixture), timing, and JPEG size. `[I]` Luma only, from fishcu's analysis.

**Camera result, `grain_fast` t1 (`22bc3b82`), 2026-11-07:** no grain visible or measured. Same look (Provia 400, same NR, no Glow) on COLOR1-4, ISO 200, 1/60, f/3.5, PB071844..47. High-pass Y noise in flat blocks: Y 30-70: 0.84 / 0.74 / 0.76 / 0.76; Y 70-110: 0.93 / 0.80 / 0.82 / 0.77. JPEG size falls with level: 7967 / 7583 / 7472 / 7442 KB. No hang or corruption in these frames. Limits: the scene had no flat blocks above Y 110; the camera moved or the light changed between frames; the test can't tell "gate didn't fire" from "the processor ignored it"; gains were stock 50/75/100. Save time and burst weren't compared, as there was no grain to cost anything.

## CPU grain on the E-P7: map and test t1 (2026-11-07, not camera-tested)

Build: `patches/grain_cpu/`, output `generated/grain_cpu/t1/` (v0.26 + 1401 B, version `0.27c1`). Method and algorithm from the OM-3 port (`xblock.s`, `research/grain/model.py`, Apache-2.0, repo `41e7e8b`); the code is ours. Credit it in `NOTICE` if this ships. `[V]` = read or emulated here. `[I]` = inference.

| Item | OM-3 | E-P7 | Evidence |
|---|---|---|---|
| Lock / unlock | `0x60075f73` / `0x60075fbc` | `0x6006a922` / `0x6006a96b` | `[V]` masks this CPU's interrupts through PSW (`0x60054d9f`, level 0). Other CPUs keep running |
| Cache flush | `0x60070e69` | `0x60066fc0` | `[V]` read; same call shape. Its busy bit needs hardware, so the emulator counts calls instead of running it |
| Window mapper | `0x60071018` | `0x60067146` | `[V]` run in the emulator. Below 0xb0000000 returns 0 (direct); refuses 0xc0000000..0xc3ffffff and 0xe0000000 up |
| Window registers | `0x98100058` + CPU stride | `0x98100058` / `458` / `858` and `4c`, 3 CPUs | `[V]`. Mode array `0xa2716034`, get `0x600672ee`, set `0x600672fe`. Different layout: the selector is bits 8-15, not the top byte |
| Cached alias | - 0x40000000 | same, 0xa0..0xbf (`0x600670bc`) | `[V]` |
| Blend setup, word | `0x604be2aa`, `0x604b9288` | `0x6035ca31`, `0x603579b8` (only reference) | `[V]` |
| Record of 0x1000 | job+10276 list, 104 B | job+6592, 88 B, lookup `0x60350975` | `[V]` (0) bus, (8) format, (10) stride in px, (12) Hw, (14) rows, (72) size |
| Format | 0x0c02 | **0x0302**, 2 B/px | `[V]` value and size; **byte order `[I]`** |

**Buffer complete on return** `[V]`: the real `0x6035ca31` run in the emulator submits once, waits once (`0x6035490d` -> `0x6035486d`), and clears its source records. Lookup 0x1000 then finds the new record. Stock frees the sources right after that wait, so the wait covers the blend.

**Y in even bytes is not proven on this body.** Nothing here reads 0x0302 on the CPU. The camera check is whether Cb and Cr noise stays flat. If the order is wrong, the grain lands in chroma: visible, not dangerous.

**Bus address range is not proven.** The route handles 0xa0..0xaf directly and 0xb0..0xdf through the window. §10e read through a descriptor address with no mapping. Stock code maps first (`0x603cc0c8`). Unlike the OM-3, a different window mode is restored before each unlock, because another task on this CPU may be relying on it. That adds up to two flushes per lock, only if the buffers need a non-default mode.

**The code doesn't need a cached trampoline:** this block is in section 1, already cached. No `fb` forms (build check). The 16 KB limit holds: 3 Hw + T, with Hw capped at 5461, because above 16 KB malloc logs an error.

**Work lists** `[V]`, real builder:
- Plain with forced 0x80: `dev, reduce, blend + grain, 0x6035b529`.
- Glow, Clarity: the same.
- Star Light: art passes, then blend + grain, so grain comes after them.
- Pin Hole: `dev, reduce, blend + grain, 0x6035b4ab, 0x6035b529`, so **Pin Hole is applied after the grain**.

**Neutral weight** `[V]`: `bw_default` is now 1024, so a key-11 Soft Focus pass with no effect on the slot passes the sharp input (B gain 0, `0x603a04de`). A Glow or Clarity slot keeps its weight (emulated == v0.26). A failed guard on a Glow slot now gives no glow instead of stock 600. Forcing the flag skips capture kinds 0x2001, 0x2006, 0x1008 and 0x1006, and `gc_gs` requires job type 0x1000 and the marker. Live view uses `0x6035cc1b`, not this word.

**Task and burst**
- `[V]` `0x60354214` runs the work list synchronously, with `calls (a1)` at `0x6035428e`, from `0x603e624d` in the capture code. So the grain pass blocks the task that runs the job. The stock wait in `0x6035486d` already blocks it for each pass.
- `[I]` Task name not proven; `REC_EXEC_MAIN` and `TAKE_MAIN` exist. Whether another exposure can start during the pass isn't shown. It depends on a separate shutter task and on job memory, and the camera check measures it.
- Interrupts: `[V]` masked only for 2 rows of `gc_p2` plus one flush, on this CPU only; noise rows are made outside the lock. `[I]` About 1-2 ms each time (OM-3: 0.63 ms a row, about 55% of it table lookup, plus flush), about 1944 times per photo.

**Extra cost of forced passes on plain looks** `[V]` structure, `[I]` time: from one direct pass to a development pass, a reduce to 160x120, two more full-size passes (upscale, blend) and an output pass, with two more 40 MB buffers (0x1061, new 0x1000, each 40,310,784 B at full size). Test 5 noted "slight write lag" with the same bloom passes. Not separately timed.

**Speed-ups for the next build, best first** (estimates, none tested)
1. **Skip the Soft Focus passes on plain looks.** `dev + 0x6035b529` is a real list shape (v0.21's job, `[V]`), with the grain hook before the output pass plus a wait on the pending request. That saves the upscale and blend. The CPU pass doesn't change.
2. **A noise tile.** `gc_p1` is about 8.3 of about 19 loop instructions per pixel (`[V]` count), about 40%. Class-2 malloc caps at 16 KB, about one row, so a tile needs another source: the job buffer pool (`0x60350560`, the same call that allocates 40 MB) `[V]`, freed by `0x60350843`, reached through the same window. Check for repetition. It competes with burst memory `[I]`.
3. **Fewer flushes.** One full-cache flush per K rows. The OM-3 saw 0.3 s from K = 1 to 2, so K = 4 saves about 0.15 s at about twice the masked time. Small gain.
4. **A second CPU.** Window registers are per CPU `[V]`, and `FCS_IMG_2NDCPU_MAIN` shows such tasks exist. Could split the rows, roughly halving the time `[I]`. Largest gain, most risk, nothing traced.

**New custom effects** `[I]`: yes, if t1 works. Any per-pixel change to Y, Cb and Cr at the blend output becomes possible (film LUTs on Y, chroma curves, vignette shapes). Cost: emulated `gc_p2` is about 10.5 instructions per pixel, so a simple LUT pass is about 210 M instructions per photo, roughly 1.4 s at the OM-3's per-row time. A 3D LUT would be about 3x that. Neighbouring-row effects need row buffers beyond class-2's 16 KB, so from the job pool. Every effect blocks the job task and rules out fast burst.

**Gate:** `gc_flag` and `gc_gs` as above; profile 2/3/4 -> S 28/68/112; level 1 is COLOR2. Guards skip grain on: format, offsets, width, stride, rows, buffer size, bus range, malloc, blend error, mapper refusal.

**Verifier** (`patches/grain_cpu/verify.py`): M 22/22 (bit-exact against the model, all window classes; the model checked once against the OM-3 `model.py`), F 27/27, G 203/203, W 35/35, B pass, P pass. CPU cost 21.8 instructions per pixel, about 439 M per 5184x3888 photo, flush excluded. Package `15f2ad90…011f`; restore `963f4dfe…2327`.

**Not proven:** byte order, real bus range, whether the cached window view works on this body, real flush timing, photo time, whether the output pass keeps the grain intact, and the task name.

**Camera result, `grain_cpu` t1 (`15f2ad90`), 2026-11-07:** no grain measured. Provia 400 on all four slots, ISO 3200, M series PB071852..55 at 1/60, f/5.3. High-pass Y noise, Y 30-70 / 70-110 / 110-170: COLOR1 2.81 / 2.67 / 2.29; COLOR2 2.50 / 2.21 / 1.95; COLOR3 2.52 / 2.28 / 1.98; COLOR4 2.51 / 2.23 / 1.95. Cb and Cr noise flat, sizes flat (10778 / 10494 / 10553 / 10546 KB), no crash or speckle reported or measured. COLOR2-4 show no level steps. COLOR1 was also noisiest in the fast-route test, so its gap isn't evidence that the passes ran. Slots differ only at +49 (COLOR4 0). Not known yet: whether the pass ran and the output lost it, or a guard skipped it. A guard readout is the next step.

## CPU grain diagnostic d1 (2026-11-07, not camera-tested)

Build: `patches/grain_cpu/gd.s.in`, `build_d1.py`, `verify_d1.py`; output `generated/grain_cpu/d1/`. Same route as t1. Adds a readout and, on COLOR4, a dark band in Y (16) on rows 0..127 in place of grain. All guards as t1.

**Record:** 64 B from malloc (uncached heap), pointer at heap P+1000, magic `GDIA`. Written and read only through its uncached address, so the pipeline CPU and the GUI CPU see the same bytes. `[V]` P+1000 has no user in v0.26: the key probe that used it isn't built. **Not in the image:** stock never writes its image and test 7a crashed on such a store (`docs/APERTURE_RING.md`). **t1's `gc_seed` was that banned store;** d1 keeps the seed in the record, and the next build must too. No heap P (no card file) means no record and stock behaviour; the screen shows `----`.

**Stage** keeps the highest value reached; a read marks the record, and the next capture clears it. Counts show how many jobs passed each point.

**No timer:** no free-running counter was proven, so none is recorded.

**Verifier:** M 21/21, F 24/24, R 18/18 (all pages, wrap, empty field, no block), G 203/203, W 35/35, B pass, P pass.

**Decode** (Firmware screen, Body value, `<letter><3 hex>`, next letter on each opening):

| Page | Field |
|---|---|
| a | stage, guard (2 hex) |
| b | F, G, R: counts of flag hook, `gc_gs`, `gc_grain` |
| c | format, low 12 bits |
| d, e, f | Hw / 4, stride / 4, rows / 4 |
| g, h | bus address bits 31..20, 19..8 |
| i | class (0 direct, 1 window, 2 window after a mapper call, 3 refused), band, window mode |
| j | CPU address bits 31..20 |
| k | rows done / 2 |
| l | x OR y |
| m | blend result, low 12 bits |
| n | size in MB |

Stages: 0 no capture; 1 flag hook; 2 `gc_gs`; 3 blend returned; 4 `gc_grain` checks; 5 work buffers; 6 writing rows; 7 done.

Guards: 00 none. Stage 1: 01 key, 02 key high, 03 not COLOR, 04 profile not 2..4, 05..08 kinds 0x2001, 0x2006, 0x1008, 0x1006. Stage 2: 10 marker, 11 mode, 12 type, 13 job key, 14 profile. Stage 3: 15 blend error, 16 no 0x1000 record. Stage 4: 20 format, 21 x, 22 y, 23 width < 4, 24 width > 5461, 25 width not a multiple of 4, 26 stride, 27 rows 0, 28 rows > 8192, 29 buffer too small, 2a bus low, 2b direct range overrun, 2c bus high, 2d mapper's refused range, 2e window edge, 2f malloc V+H, 30 malloc T. Stage 6: 31 mapper refused.

## CPU grain diagnostic d2 (2026-11-07, not camera-tested)

Build: `patches/grain_cpu/gd2.s.in`, `build_d2.py`, `verify_d2.py`; output `generated/grain_cpu/d2/`, label `0.27d2`. Decoder: `tools/ep7_graind.py`. The pass, band and guards are d1's. The Firmware pages are gone.

**File:** on a half-press, in `HLS_EVENT` before `mv_trig` (hook `sd_back`), if the record changed: `C:\EP7MOD\GRAIND.BIN`, 656 B, through `ed_wfile` with its own 2048 B scratch buffer. Only that path is written. It never writes during capture: the flag hook only copies inside the heap block. Failures are silent. `[I]` A half-press while the buffer is flushing to the card can wait, as a MOVIE.BIN save can.

**Format:** 16 B header (`GRND`, u16 version, captures, record size 80, slots 8, writes, then a change flag and a pad byte), then 8 records of 80 B. Slot = capture number & 7. Field offsets are in the header comment of `gd2.s.in`; a record is the live block's first 80 B.

**Low bus route: left out, on code evidence.**
- `[V]` The E-P7 mapper `0x60067146` returns 0 below 0xb0000000 and programs nothing. It accepts 0xb0000000..0xdfffffff except 0xc0000000..0xc3ffffff.
- `[V]` Its register values allow only 0x7600, 0x8700, 0x9800, 0xa900 and 0xba00. Going by the mapping it uses, these select slices from about 0xb0 up `[I]`. Nothing in the firmware selects a slice near 0x41. So it isn't the OM-3's register: writing a low value ourselves would be an untested hardware setting.
- `[V]` On this firmware 0x40000000 up is the logical flash range: the loaders read 0x406a0000, 0x41fa0000 and 0x421a0000 (`0x60020714`, `0x600207a3`), and 0x47000000 up holds boot code. A direct CPU write there is a real brick risk `[I]`, so guard 0x2a stays.
- `[I]` A real buffer inside flash space doesn't make sense, so "41x" on the clipped screen may be misread, or an ISP-side address needing a translation not yet found. The file gives the full address plus the buffers before the blend.

**Banned stores:** none. The build rejects absolute stores; M, F, T and C run with the image regions read-only, so a store into the image would fault. t1's `gc_seed` store is gone. Stores go to the heap block, the stack, work buffers and the image buffer.

**Verifier:** M 21/21, F 24/24, T 8/8, C 1/1, G 203/203, W 35/35, B pass, P pass. `ed_wfile` itself is stubbed here; the code is camera-proven through MOVIE.BIN.

Also `[V]`: 2398 B at 0x601dff3c (dead EVF tables, refs 0x601e3b50..3b88 only, false positives pinned in `build_d2.py`).

## CPU grain d3: the real record and the window path (2026-11-07, not camera-tested)

Build: `patches/grain_cpu/gd3.s.in`, `build_d3.py`, `verify_d3.py`; output `generated/grain_cpu/d3/`, label `0.27d3`. Decoder `tools/ep7_graind.py` reads d2 and d3 files (header version 1 or 3).

**The d2 stop was my error, not a real offset.** `[V]` Record layout (`0x60354aee`, the copy `0x60350560` makes before allocating): +8 format, +10 stride, +12 width, +14 height, **+16 active width, +18 active height, +20 x, +22 y**, +24/+26 half sizes. The camera's "x|y = 0x1f70" is 5184 | 3888. The guards read the wrong fields. The real blend setup in the emulator gives +16 = (5184, 3888, 0, 0) with this layout; earlier tests only checked the first four fields. x and y are written as 0 by the blend setup (`0x6035cad6`).

**Pixel 0 is at `bus`** `[V]`: rec+0 = the allocation's start, (64,rec) (`0x60350631`), with x and y 0. Bus 0xce9d4b80 isn't page-aligned because the allocator carves blocks off a free list (`0x60350334`). The size equals stride x rows x 2.

**Guards:** 0x21 and 0x22 now test +20 and +22. Whole-buffer bounds: in the direct range, or inside the mapper's range and clear of 0xc0000000..0xc3ffffff (0x2c, 0x2d, new 0x32 for the end). Guard 0x2e is gone, because:

**The real buffer crosses a mapping boundary** `[V]`: 0xce9d4b80 + 40310784 = 0xd1046380, across 0xd0000000 (mode 3 below, mode 4 above). 0x2e would have refused the whole image. Rows 0..2241 use mode 3, row 2242 splits at byte 896 (word-aligned), and the rest use mode 4. Passes that cross an edge go one row at a time with their own lock per piece.

**Window path with the real value** `[V]`, real lock and mapper: mapper called with 0xce9d4b80, register selector 0xa9 (mode 3), CPU address 0xb69d4b80, cached view 0x769d4b80. An edge test with the same residue, at full width, matches the model across the split, and restores mode 0.

**Cost note** `[I]`: mode 0 is what the emulator starts from, and the record will show what the camera holds. If it differs from what's needed on every lock, each pair of rows takes three flushes (map, write-back, restore). Holding the mode for the whole pass would cut that, but another task on the CPU could be relying on the old mode, so keep it until timing says otherwise.

**The longer save in t1 and d1** `[V]`/`[I]`: guard 0x21 fired before any work buffer or pixel, so no CPU pass ran. Any added time on COLOR2-4 came from the forced Soft Focus work. The camera job has 5 entries (`0x00080080`), against 1 for plain COLOR.

**Record additions:** x and y separately, active size, mode before and after the mapper, rows split. Two flag hook calls per shot are normal (d2 file).

**Verifier:** M 21/21, F 26/26, X 3/3, T 8/8, C 1/1, G 203/203, W 35/35, B pass (now includes +16..+22), P pass. Package `1aca93e2…abcc`; restore `963f4dfe…2327`.

**Not proven:** the cached view through a window on this body, real flush timing, whether the image reaches the JPEG, and Y byte order. The band answers the last two.

**Camera result, `grain_cpu` d3 (`1aca93e2`), 2026-11-07:** works. Four matched-look shots at ISO 3200, `testdata/camera_grain_d3/`, PB071863..66. Record: stage 7, rows done 3888, window after a mapper call, final mode 4, mode before 0, rows split 1. High-pass Y noise, Y 70-110 / 110-170: COLOR1 2.26 / 2.13, COLOR2 3.58 / 3.56, COLOR3 7.28 / 7.49, COLOR4 11.42 / 12.14. Cb noise flat (0.32 to 0.46), so Y is in the even bytes. COLOR4 band dark (top rows about 17, against about 75). JPEG 11077 / 12402 / 14384 / 14009 KB. About 5 s to save with grain by the owner's report, no crash.

## CPU grain s1: the control and the faster pass (2026-11-07, not camera-tested)

Build: `patches/grain_cpu/gs1.s.in`, `build_s1.py`, `verify_s1.py`; output `generated/grain_cpu/s1/`, label `0.27s1`. Decoder `tools/ep7_graind.py`.

**Control.** Extras sector 1 = Grain, slot +50, Off / Low / Med / High. Sector 9 = NR, slot +24, same values as before (`9 NR Camera`, `Std`, `Low`, `Off`). `[V]` Sector index 8 is an existing wheel id with no field, as sector 8's was (`Extras: 1-9 only` for 10..12). A Film pick and the `*` ignore +24 (u_apply stub `gc_ua`, compare stub `gc_um`); +50 is past u_apply's bound and lt_mod's. `[V]` BUNDLES.BIN accepts +50 0..3, MOVIE.BIN's zero check starts at +51 (+50 unchecked on the camera, 0..3 in the tool). Files with Grain set are rejected by v0.26 and older. `webapp/` not updated.

**Movie slot:** the sector works and saves, and the byte does nothing: no still converter, and job type 0x3x fails every grain check.

**Off is v0.26** `[V]`: same job flag and work list for every flag set tested; output and blend words go straight to stock. Only the record differs.

**Plain looks skip the Soft Focus passes** `[V]`: a modifier that does nothing holds the development entry's slot, which gives the list `dev + 0x6035b529`, the shape of every COLOR grain job through v0.21. `gc_wl` builds it only when job+16 has the shading bit and nothing among 0x40..0x40000. `gc_ob` then waits for the development request (`0x60354930`, as stock at `0x603544f5`), and runs the pass on 0x1000 before the output pass. The dev buffer record has the same layout and format: `0x60350639` (`mov 770`, or `0x60354aee`). Glow, Clarity and Art keep their passes, using the blend hook. **The real dev buffer's format has not been seen in a record:** a guard would show it.

**Flushes:** K = 4, and on a window-mode change the restore's own flush replaces the explicit one. Per pass: 972 locks, 1944 flushes, against 5832. **Mode held across locks: not done.** It can't be shown that no other task on the CPU uses the window at mode 0 (`0x6005abb8` writes 0xb0000000 directly), and the gain over this is about 0.3 s `[I]`. Masked time about 2.3 ms per lock on this CPU `[I]`, against about 1.3 ms in d3.

**Noise:** a 16 KB heap ring, refilled per photo with `n` pair-filtered, cached. Row noise = (ring[o + x] + ring[previous o + x] + 1) >> 1, random `o` per row, so neighbouring rows share half their noise. No per-pixel generator: 15 instructions per pixel against 18.75. **Job pool rejected:** a tile there is only reachable through a window, which can't also show the image unless both fall in the same mode's slices. Strengths 23/55/91, centre 991, to match the old statistics. Not bit-exact with `model.py`, by request.

| Simulation, flat Y 128, High, 5184 x 3888 | d3 | s1 |
|---|---|---|
| Mean shift, Y | 0.22 | 0.12 |
| Std | 18.68 | 18.79 |
| Correlation, 1 right / 1 down / 2 down / diagonal | 0.496 / 0.495 / 0.247 / 0.248 | 0.496 / 0.497 / 0.000 / 0.248 |
| Excess kurtosis | -0.21 | -0.15 |
| Largest off-centre 2-D autocorrelation | 0.004 | 0.033 |
| Row 1000 against rows 1002, 1500, 2500, 3800, best shift | 0.28, 0.06, 0.06, 0.06 | 0.41, 0.35, 0.18, 0.43 |

The 0.033 is the ring's own sampling correlation at one lag, repeated in every row; it changes each photo. Low and Med std: 4.7 and 11.3 in both.

**Estimate per photo** `[I]`, from the OM-3's 0.63 ms a row and 0.15 ms a flush; E-P7 speed is unmeasured:

| | d3 | + K = 4, fewer flushes | + ring |
|---|---|---|---|
| Window and flush | 0.87 s | 0.29 s | 0.29 s |
| Noise | 1.07 s | 1.07 s | 0.01 s |
| Lookup | 1.36 s | 1.36 s | 1.94 s (includes the two ring reads) |
| CPU pass | 3.3 s | 2.7 s | 2.2 s |

Skipping the passes removes the upscale and blend, about 1 s or more of the rest of d3's 5 s `[I]`.

**Next shot:** still blocked by the same thing `[V]`: the job's entries run synchronously in the capture task (`0x60354214`), and the pass is part of them. Whether another exposure starts meanwhile isn't shown by the code; time it.

**Strength:** High S = 112 in d3 is the OM-3 port's MONO High from its own camera shots. Noise above COLOR1 (d3, root of difference of squares, Y 70-110 / 110-170): Low 2.8 / 2.9, Med 6.9 / 7.2, High 11.2 / 12.0. **No stock MONO High shot on the E-P7 has been measured here.** Its stock gain table is the same as the OM-3's `[V]`, so a match is plausible `[I]`.

**Verifier** (`verify_s1.py`): M 22/22, F 11/11, O 4/4, L 56/56, A 96/96, E 37/37, K 5/5, T 8/8, B pass, P pass.

## s2 camera result and s3 (2026-11-07, s3 not camera-tested)

**s2** (s1 + `.balign 4` before `gc_t1`; s1 crashed opening Extras on a misaligned word read at `0x601e356c`): Extras and the +50 save work. No grain on any shot, fast saves. `testdata/camera_grain_s2/GRAIND.BIN`, PB071868..72: COLOR2-4 stage 1, guard 0, flag hook 2, `gc_gs` 0, `gc_grain` 0.

**Cause** `[V]`: the work list is built inside the constructor (`0x603e6d3e` -> `0x603537eb` -> `0x60353c70` -> `0x60354709` -> `0x60354756` -> `0x60356297`). The converter writes job+15488..15490 (profile, mode, marker) only after that, at `0x603e6d50` -> `0x603e66ab`. So `gc_wl`'s level check found no marker and fell through to the old route every time. The same order affects the v0.4..v0.21 `wl_hook`, which needed the marker as well: `[I]` a strong reason why that grain never showed on full-size photos. My emulator fixtures had set the marker ahead of time.

**s3** (`generated/grain_cpu/s3/`, label `0.27s3`):
- The flag hook, which runs before the constructor in the same call chain, leaves the plain look's level at block +95, cleared on every flag-hook call. `gc_wl` takes it once, only on a key-11 job of stills type (live view jobs never touch it). Then it checks job+16.
- `gc_ob` runs after the converter, so its own checks still read the marker.
- New stage-1 guards in `GRAIND.BIN`: 0x43 other job flags, 0x44 no shading bit, 0x4f route built.

**Checks added:**
- W: the real builder with no marker, as on the camera: level 1..3 gives the list; no level, live view, MONO, Glow and no shading bit give v0.26's list; the flag hook leaves 2 or 3 for plain looks and 0 for Art and Off.
- Y: every label that starts a `.long` / `.hword` table is aligned (also a build check). It reports `gc_t1` at 0x601e0763 on s1's symbols.
- X: 1188 traced word and halfword accesses by the block's own code, all aligned.

**Verifier:** M 22, F 11, O 4, L 56, A 96, E 37, K 5, T 8, W 13, Y 1, X 1188, B, P: all pass. Package `d2022b5e…4746`.

**Camera result, s3 (`d2022b5e`), 2026-11-07:** works. COLOR4/3/2/1 at ISO 200, `testdata/camera_grain_s3/` PB071873..76: stage 7, route output, mode 3, rows split 0, 3888 rows. High-pass Y noise, Y 70-110: High 9.69, Med 6.03, Low 2.69, Off 0.89. Chroma flat. Owner: "decently slow but workable"; High still looks fine-grained.

## v0.27 release candidate r1 (2026-11-07, not camera-tested)

Build: `patches/v027/build.py` (`apply(spec)` on `releases/v0.26/edits.json`, label `0.27`) -> layer `patches/grain_cpu/build_r1.py` (source `gr1.s.in`, model `model_r1.py`); `patches/v027/verify.py`. Output `generated/grain_cpu/r1/`, package `d774f62a…1483`, restore `963f4dfe…2327`.

**Coarser, stronger grain.**
- The noise is now made at half resolution (s3's ring scheme on a half-res grid) and enlarged 2x bilinearly, luma only, with the same midtone weighting and table. Model in `model_r1.py`; the camera code is bit-exact to it (verify M).
- Strengths 40 / 102 / 180 (were 23 / 55 / 91), centre 996.
- Simulated on flat Y 128 (std = total grain; 3x3 high-pass = pixel minus its 3x3 mean; footprint = autocorrelation lags above 0.5 / 0.25):

| Level | model.py (d3) | s3 | r1 |
|---|---|---|---|
| Low | std 4.70, high-pass 3.17 | 4.66, 3.04 | 7.17 (x1.54), 2.01 |
| Med | 11.27, 7.60 | 11.16, 7.26 | 18.19 (x1.63), 5.07 |
| High | 18.67, 12.58 | 18.44, 12.00 | 32.17 (x1.74), 8.94 |
| Footprint | 1 / 5 px | 1 / 5 px | 13 / 29 px (half-width 3 px against 1) |

- Clumps are about 2.4x wider (from the 0.25 footprint). The strength targets were set on total std; **a fine high-pass measure like the camera numbers above will read lower than s3** (High about 0.75x), because the grain is coarser.
- Preview `generated/grain_cpu/r1/preview.png`: Off | model.py High | s3 High | r1 High, a 192 x 192 crop of PB071876 at 2x.

**Speed.** 14.6 instructions per pixel against 15.1 in s3 (emulated), about 3% less: half-res rows are generated once per two output rows outside the lock. Nothing else found safe: holding the window mode across locks is still unproven (see s1). Interrupt-masked time per lock is about the same as s3.

**Cleanup.**
- `GRAIND.BIN` and the half-press writer are gone (sd_back as v0.26). Verify N checks that no call from the block reaches the file API.
- The record stays in RAM only (128 B, cleared at each flag-hook call).
- `ex_default` now answers sectors 1 and 9 with their current value, so a reset to defaults leaves Grain and NR alone.

**Verifier:** M 22, F 13, O 4, L 56, A 96, W 13, E 37, K 17 (look, own and Stock picks, the `*`, defaults, file ranges), N 2, Y 1, X 637, B, P: all pass.

### Release notes (v0.27)
- **Grain** (Extras sector 1, per COLOR profile): Off / Low / Med / High.
  - Real film-like grain on COLOR stills, added to the finished photo's brightness; colour is untouched.
  - Off means exactly v0.26 behaviour and speed.
  - Not in live view, movies, the Movie slot or MONO.
- **NR** moves to Extras sector 9, with the same values and the same saved byte.
- **Grain and NR are yours.** Picking a look, Own, Stock or resetting never changes them. NR stored in LOOKS.BIN is ignored.
- **Saving takes longer with grain on.** On the E-P7 a plain look took about 3 to 5 s per photo in tests (owner: "decently slow but workable"). Burst with grain on is slow. Off costs nothing.
- **Glow, Clarity and Art Effect looks keep their own passes**, and the grain is added after them. Pin Hole is the exception: its vignette pass runs after the grain.
- **Files:** BUNDLES.BIN and MOVIE.BIN with Grain set are rejected by v0.26 and older. Set Grain to Off before going back.
- The Control Panel sets Grain and NR per COLOR profile (firmware option "v0.27 or later").

## v0.27 r2: s3's grain back (2026-11-07, not camera-tested as a whole)

Owner on r1: far too much grain, "step it back to how it was before". **r2 = r1 with s3's grain**:
- full-resolution noise (16 KB ring, two row offsets);
- strengths 23 / 55 / 91, centre 991;
- the model in `grain_cpu/verify_s1.py` `expected()`, camera-tested in PB071873..76.

Everything else is r1's:
- no `GRAIND.BIN` and no card writes, record in RAM only;
- Extras 1 Grain and 9 NR;
- picks, Own, Stock and defaults keep Grain and NR;
- the alignment checks;
- label `0.27`.

Source `patches/grain_cpu/gr2.s.in` is made from s3's `gs1.s.in` with only r1's cleanup edits. These routines are instruction-for-instruction s3's: `gc_grain`, `gc_fill`, `gc_next`, `gc_p2`, `gc_tbl`, `gc_open`, `gc_cach`, `gc_cls`, `gc_gs`, `gc_ob`, `gc_wl`, `gc_lvl`, `gc_pend`, `gc_route`, `gc_nomod`, and the tables. Changed: `gc_flag`, which clears the record instead of syncing a file slot; `gc_mark`, with a 128-B block and no file header; plus `gc_def` added and `gc_sync` / `gc_trig` / `gc_path` removed.

`patches/v027/build.py` now builds r2 (`build_r2.py`). Package `generated/grain_cpu/r2/`, `ac831658…5eac`; restore `963f4dfe…2327`. Verify (`patches/v027/verify.py`): M 22 (bit-exact to s3's model), F 11, O 4, L 56, A 96, W 13, E 37, K 17, N 2, Y 1, X 637, B, P: all pass. The r1 notes above (coarser grain, 40 / 102 / 180) are superseded. `model_r1.py`, `gr1.s.in` and `build_r1.py` stay only as a record.

### Release notes (v0.27), as built from r2
- **Grain** (Extras sector 1, per COLOR profile): Off / Low / Med / High.
  - Film grain on COLOR stills, added to the photo's brightness, colour untouched.
  - Off means exactly v0.26 behaviour and speed.
  - Not in live view, movies, the Movie slot or MONO.
- **NR** moves to Extras sector 9, with the same values and the same saved byte.
- **Grain and NR are yours:** picking a look, Own, Stock or resetting never changes them. NR stored in LOOKS.BIN is ignored.
- **Saving takes longer with grain on:** "decently slow but workable" on the E-P7 (s3 build). Burst with grain on is slow. Off costs nothing.
- **Glow, Clarity and Art Effect looks keep their own passes**, and the grain is added after them. Pin Hole is the exception: its vignette pass runs after the grain.
- **Files:** BUNDLES.BIN and MOVIE.BIN with Grain set are rejected by v0.26 and older. Set Grain to Off before going back.
- The Control Panel (`webapp/`) doesn't know +50 or the NR move yet.
