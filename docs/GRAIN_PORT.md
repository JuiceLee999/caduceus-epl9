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

## 4. Verification (emulator; `tools/ep7_grain_verify.py`, fishcu's libsim runner)
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
1. **[I] Combiner 32 runs on full-size stills.** Stock uses it only for job classes 4–9 (job+11320 ≠ 0). Full-res MONO uses the mask route. The internal-mask path may have width or line-buffer limits, and could fail or corrupt output on full-size COLOR images. This is the main unknown.
2. **[I] Chroma preservation and the look are unproven.** The weighting uses no 0x605003aa mask, and gains 50/75/100 are lower than 110/300/600, so grain will probably be finer and weaker than MONO Low/Med/High.
3. **[V] Modifier slot.** Our modifier takes the development entry's single modifier slot (0x603573d3). Later feature modifiers on COLOR jobs then use the stock fallback, a separate entry. Stock MONO 0902 behaves the same way, but this means an extra pass and more memory for COLOR + features. Not traced for the COLOR shading path.
4. Not covered by this patch:
   - other job paths: compact/live view (0x6030ed1b, 0x6032438a) and CPU2 converter;
   - RAW-edit applies, because it shares key 11 and the work list [I];
   - movie;
   - the second builder bypass from HSL_PORT.md (it is not related to grain).
5. Inherited from v0.1 (`docs/REVIEW_fixed_hl.md`): the update/restore path is untested, the persistence of the FF tail is unproven, and container validity does not prove the package boots.
