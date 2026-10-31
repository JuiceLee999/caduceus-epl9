# Active profile index, WB fine-tune, MONO slots (E-P7 1.1)

Offline static analysis only. No camera contact. No package built. Nothing committed.
"Verified" means read directly from the decoded main (`tools/dis.sh` or a byte dump). "Inferred" means
deduced and not executed.

## 1. Active profile index

### Verified
- **Settings ID → property table** at `0x604d6c14`: 1769 entries of `{u16 key, u16 index}`, indexed by
  settings ID 0..1768 (bounds `cmp 1768`; users `0x602cbd4a`, `0x602cbf96`). Property key = `id<<4 | type`.
  Type low 3 bits give the width (1 = byte, 2 = half, 4 = word); bit 3 means signed (`0x6005efbd`).
- **Setting 908 ↔ property key `0xF6B1` (63153)**, index 0. This is the effective COLOR profile number.
  It matches PEN-F 912 with the same −4 shift as saturation (PEN-F 931 → E-P7 927).
- **Setting 973 ↔ key `0xF731` (63281)**: the effective MONO profile number.
- **Settings 915..926 ↔ key `0xF6EA` (63210)**, index 0..11: the effective 12-sector saturation
  (PEN-F 919..930).
- **Property getter `0x6005e971`**: `d0` = key, `d1` = index, `a0` = 0 for a global lookup.
  - Lookup goes through `0x6005d924`. That reads the RAM registry `0xa26ffa88 + 8*(key>>4)` (or the
    overlay at `0xa2707a88` when `(0xa26ffa84)≠0`); the data pointer is at entry+4.
  - The address is translated per core through `0x6005c8cf` (CPU id at `0x8050`).
  - There are no locks on this path; it only reads.
  - Storage is heap- or registry-allocated, so **there is no fixed RAM address** for setting 908.
    ACTIVE bank access is object `(0x62253594)`, key `0x8B64`, index `part*1769+id` (`0x602cc0a7`).
- **Capture population** `0x602a857e..0x602a85c0`:
  - Picture mode is property 38017 → `capture+24053`. Mode 6 is re-resolved via 40209.
  - If mode == 11, key 63153 is read; if mode == 12, key 63281. Either result is stored as a byte at
    **`capture+24083`**.
  - Saturation (63210 ×12) → `capture+24058`.
  - Mono-related settings 990/980/994 → `capture+24084/24085/24086`.
- **RAW development** (`0x60c6710b..0x60c67132`) fills `capture+24083` the same way, from the same
  global properties (`a0 = 0`).
- **Bracket variant copy**: `0x603f2102` saves `capture+24083` into variant+13, and `0x603e2084`
  restores it. So the field is per-frame, including in picture-mode bracketing.
- **Converter `0x603e62d1` does NOT copy `capture+24083` into the job.**
  - Mode 11 copies S → `params+5538..5549` (params = job+36) and 24086 → `params+5552`.
  - Mode 12 copies 24084/85/86 → `params+5550/5551/5552`.
  - The only readers of +24083 are `0x603f1eda`, `0x603f2159` (bracket) and `0x613f9322` (sec 9,
    probably EXIF/makernote).
- **Packer `0x60354ce4`** clears the 1884-byte request, then copies fields from params:
  - S `params+5538` → `request+1816`
  - 5551 → 1828
  - 5552 → 1829
  - `params+5550` is **not** copied into the request.
  - Request picture mode (`request+8..11`) comes from job+12..15 (`0x60354cb9`).
- **Conclusion: the request and job carry no profile index.** The hook at `0x603b02d9` can only get it
  from (a) a new job field, or (b) the global property.

### Options at the hook (design)
| Option | Cost | Correct for frame? | RAW dev | Live view |
|---|---|---|---|---|
| A. Call `0x6005e971(63153,0,0)` in the routine (global) | ~10 insns plus a call; no other edits | Wrong if the profile changes between capture population and processing (burst, buffered writes) | Probably correct: dev populates from the same global and is modal (inferred) | Correct: the current setting is what the user is looking at |
| B. Job trailer byte (PEN-F precedent) | Constructor edits `0x603537f0` `2c803c`→`2c983c` and `0x6035390c` `8510`→`8528`, plus converter hooks at `0x603e669f` (`5c14fa40165e`) and `0x603e91e4` (`5c18fa40165e`) that write `capture+24083` into job+15488 | Yes | Yes (dev uses the same capture field) | No: the compact/live path has no capture params, so it falls back to A |

**Recommendation:** B, with A as the fallback when the trailer byte is 0. The routine would check the
trailer first and then call the getter. A alone is acceptable as a first experiment, with the race
documented.

The trailer is only valid when the job parent check passes. The guard is in HSL_PORT.md:
- callback `0x60355fd4`
- records at request+3212, 56 bytes × 16
- parent = request − 11364

## 2. WB fine-tune: not resolved (no hook designed)

The trace was incomplete when work stopped.

### Leads (inferred, unverified)
- Capture population reads properties 2331 (settings 323, 670–675: one value plus a 6-element array)
  → `capture+24142..24148`.
- It also reads 2332/2333 (settings 324/325) → 24149/24150, and 2335/2336 (329/330) → 24154/24155.
  These signed-byte (type 9) pairs are plausible A–B/G–M candidates.
- Settings 130/131 (properties 2405/2406) → `capture+24054/24055` → `params+5528/5529`
  → `request+1802/1803`. This assignment is conditional (zeroed for picture mode 109, and in other
  cases).
- Olympus menus offer "All > WB" compensation, which suggests per-WB-mode storage. This is not
  confirmed on the E-P7.
- The WB gain computation and whether live view (compact/CPU2 path) uses the same code are **not
  traced**.

### Next steps
1. Confirm the 324/325 and 329/330 semantics. Check their range in the descriptor table and find the
   consumer of `capture+24149..24155`.
2. Find the gain computation that reads them and the live-view equivalent.
3. Only then design the bundle override, keyed on the same profile index as section 1.

## 3. MONO slots (8-slot bundle table)

### Verified
- **Mode ids:** picture mode 12 = MONO (raw); its profile number is setting 973 / key 63281. Picture
  mode 11 = COLOR; its profile number is setting 908 / key 63153.
- **Public mode ids:** the parameter builder `0x602b7b71` jump table `0x60460458` shows public
  modes 54/55/56/64 = COLOR1..4.
  - The profile 1 branch reads settings 912, 909, 963–965, 1667 and 927–938.
  - The profile 4 branch reads 1653, 1651, 1672–1674, 1670 and the 4th-profile saturation IDs.
  - **Correction to earlier notes:** E-P7 912 is a per-profile COLOR1 setting, not the selector.
  - The MONO public ids were not mapped.
- **Divergence point:** selector `0x603b02c1`, `cmp 11,d1; bne 0x603b02f9`.
  - Mode 11 → COLOR builder `0x603b0068` (hook site `0x603b02d9`).
  - Every other mode, including 12, → `0x603af871(request)` then the general builder `0x603afd26`
    (`d0 = request+12` halfword, `d1` = output, `a1` = request), gated by a `ctx+60` mask.
  - For mode 12 the converter does not fill the S array, so `request+1816..1827` stays 0.

### Design: MONO n renders colour (not implemented, not verified)
- **Index:** `capture+24083` already holds the MONO profile when mode = 12. The same trailer transport
  (option B) therefore carries both. Set slot = profile − 1 + 4 when mode = 12, and profile − 1 for
  COLOR, giving 0..7.
- **Minimal hook:** replace the 5-byte `cmp 11,d1; bne` at `0x603b02c1` (`a50bc936`, 4 bytes plus
  context) with a jmp to a stub:
  - If `d1 == 11`, continue at `0x603b02c5`.
  - If `d1 == 12` and `bundle[4+n].colour`, load bundle saturation into a scratch 12-byte array and
    enter the COLOR call sequence at `0x603b02c5` with `a1` pointing at it.
  - Otherwise jump to `0x603b02f9`.
- **Open risk:** whether mono conversion happens only in this selector's output. Other stages may key
  on mode 12 or on `request+1828/1829` (mono filter/toning). Grayscale could also be produced
  elsewhere: the gradation/LUT stages and `0x603af871` are unknown.
- **Test before any patch:** in the emulator, run the selector with mode 12 vs mode 11 on the same
  request and diff the output blocks. Also find every consumer of `request+8..11 == 12`.
- **Bundle table:** 8 entries × 64 bytes. COLOR1–4 = 0–3, MONO1–4 = 4–7. Add `+31 flags bit0 =
  render colour` (MONO entries only). The layout is otherwise as in PROFILE_BUNDLES.md. Profile
  renaming is deferred.

## 4. Status of task 3 (v0.2 routine)
**Not implemented.** The precondition was high confidence for both the index and WB.

- **Index:** high confidence on the identity (908/973, `capture+24083`). Per-frame transport needs
  B's medium-confidence converter hooks.
- **WB:** unresolved.

No `patches/bundles/` or `tools/` files were written.

## 5. Risks
- Global-index race (A) for buffered or burst frames. Unknown behaviour of the RAW-edit property
  context.
- The converter hooks (B) are medium confidence. The compact/live path is untraced. A second builder
  path, `0x603afb94` (when `request+1524 ≠ 0`), bypasses the hook.
- The property getter depends on core id and on runtime registry state. It was not exercised in the
  emulator.
- The full set of MONO conversion stages is unknown. Forcing the COLOR builder for mode 12 may give
  partial grayscale or wrong toning.
- Raw profile values (1..4) for COLOR4 are inferred, not observed.
