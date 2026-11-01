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

## 4. Verification (emulator; `tools/ep7_grain_verify.py`, fishcu's libsim runner)

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
