# Lens aperture ring (Panasonic/Leica) on the E-P7 1.1

Status: **built and emulator-verified. Not tested on a camera.** Code: `patches/aperture_ring/`. Verifier:
`tools/ep7_verify_aperture_ring.py`.

Tags used below: **[V]** = verified from E-P7 bytes, by disassembly or in the emulator. **[P]** = verified
from PEN-F 3.1 bytes (the official `OLY_E_122_3101_0000_0000.BIN`, SHA-256 `77398610b379f80238117f31a6d5bbf65d608b49ec563666c64d84367e969f2c`, fetched from OM's
public catalogue the same way `tools/fetch_stock.sh` fetches E-P7 firmware, then decoded in the scratchpad and
not kept in the repo). **[R]** = reported by the PEN-F PR contributor; camera evidence that we cannot check.
**[I]** = inference.

## Source and prior art

- fishcu/oly_fw_analysis PR #4 (flickering-star), "Add PEN-F electronic aperture-ring support". It targets PEN-F
  3.1 only and the repo has no licence, so we read it to understand the approach and wrote our own E-P7 code.
  The PR reports A/M ring control, DOF preview and correct f/1.7 display on the Leica 15 mm, 10–25 mm and 25–50 mm
  **[R]**. It supplies no measurements of the iris or of exposure.
- A web search found no other firmware project that enables the ring on Olympus/OM bodies. Panasonic documents
  the ring as working only on Panasonic bodies.

## How it works (PEN-F, from the PR, checked against PEN-F bytes)

1. **Request.** A lens status request has its command bytes at req+18/19 and option bytes at req+20/21
   **[P]**. The PR sets option bit `req+21 |= 0x01` on `C1 80` and `81 E3` status requests when req+12 == 0, the
   IS-extra bit `0x08` is clear and the lens advertises capability bit `0x80` (device+0x23c on PEN-F). The lens
   then appends a little-endian ring word. Stock firmware never requests it, which is why the ring is "ignored".
2. **Parse.** The status parser reads, in order: status, ZM/FC enc, OBJdst, APACT, DIS_ZMENC, DIS_FCENC, [ring
   word], LAF data… **[P]** (field order). The PR reads the word straight after DIS_FCENC and publishes it.
3. **Use.** In the AE snapshot, the `InfoGet(0x80ca)` "aperture point" read is replaced, in exposure modes 4 (A)
   and 6 (M), by the ring Av clamped to the lens's official zoom-dependent min/max (the `av_official` cache). Ring
   value `0x8000` means the ring is at A/auto, and then the body value is kept. Units are APEX Av × 256 (`0x0188`
   is about f/1.7).

## E-P7 mapping

| Role | PEN-F 3.1 | E-P7 1.1 | Evidence |
|---|---|---|---|
| Lens-request dispatcher (`mov a0,a3; clr d2; cmp 0,a3`…) | 0x60175f48 | **0x601f9df3** | [V] the body is byte-identical apart from call targets |
| Status parser, DIS_FCENC store | 0x60165276 | **0x601f5ed7** | [V] same field sequence; E-P7 parser is restructured (see below) |
| AE snapshot aperture-point read | 0x605ddb6c (inline `InfoGet(0x80ca)`) | **0x60427ae7** `call 0x60429548,[],4` (wrapper = `InfoGet(0x80ca)` via 0x6005e971) | [V] identical neighbour reads 0x30ea/0x30fa/0x310a and store pattern |
| AE config pointer; mode byte +2 from 0xc011 getter | caller (4,sp) | **a3** (0x6042777e), +2 from 0x6020e0e3 | [V] 0x6020e0e3 ≡ PEN-F 0x605deff5 (same setting 0xc011) |
| Lens device pointer (connected check inside) | 0x60160fdf → (0xa1c40090) | **0x601f2761** → (0xa271ca70) | [V] |
| Capability word | device+0x23c | **device+0x440** | [V] stock bit tests 0x20000/0x40 at +0x440 (0x601f4732/50) match PEN-F +0x23c tests (0x60163a67/ace). Zoom table moved by the same +0x204 (640 → 1156) |
| Official Av min / max cache | 0x6184d706 / 708 | **0x621cf64e / 0x621cf650** | [V] producer 0x601ede5e ≡ PEN-F 0x6015a895, byte for byte apart from addresses |
| Exposure modes A / M | 4 / 6 | 4 / 6 | [R] on PEN-F + [I] for E-P7: same setting and same getter. E-P7 0x6042514d tests `mode == 6` for an M-only path |

### Differences that matter (the PR does not port as-is)

1. **Response "kind" encoding changed [V].** The parser's 5th argument carries the response kind. PEN-F: id 0x45
   (C1 80) → 0, 0x4b → 1, 0x51/0x58 (C1 00) → 2/3, 0x54 (81 E3) → **6**. E-P7 (handler 0x601fc989): 0x45 → 0,
   0x4b → 1, 0x51/0x58 → 2/3, 0x54 → **4**, 0x5a → **5**, plus new flag bits 0x08/0x10/0x20. The PR's rule
   `kind & 6 ∈ {0,6}` would skip the ring word on E-P7 81 E3 responses that had requested it, which would
   misparse every later field. Our rule is `(kind & 2) == 0`, which covers kinds 0,1,4,5. Builder switch
   0x601fc6b4/6c3 + jump table 0x6020ec48: ids 69/75 = C1 80 and 84/90 = 81 E3 are exactly the requests
   we extend.
2. **E-P7 already uses req+21 bit 0x01 [V]** on ids 64 (`C3 F0`) and 70 (`C1 12`), gated on protocol ≥ 0x121a
   (0x601fc87c). Those responses never reach this parser (only ids 69/75/81/84/88/90 do), so the parse rule is
   still exact.
3. **E-P7 flag bits 0x08/0x10/0x20 [V]** only change where the APACT word and the post-LAF lists are stored.
   They come from the body-side parameter block, not from the request bytes, and they act after the ring
   position. So the bytes consumed up to LAF do not depend on them.
4. **Second status parser 0x601f6322 [V]** (no ring read) handles ids 34 (`81 F1`) and a B1/Dx path. These
   requests are never extended.
5. **No discovery-reset hook.** E-P7 has no matching reset routine. The AE side checks connection and the
   capability of the lens attached *now*. The one gap: if one ring lens is swapped for another, the first lens's
   last value applies until the new lens's first status response arrives (ms) **[I]**.
6. **No magic word.** State is one halfword that starts at `0x8000` (= A/auto → stock). Only the parser writes it.

## The patch as built (6 edits, 223 B)

- `0x601f9df7` (5 B, sec 1): the dispatcher's `bne; jmp null` is replaced by `jmp disp_hook`. The hook runs
  with the stock `cmp 0,a3` flags. It sets `req+21 |= 1` for C1 80 / 81 E3, req+12 == 0, no 0x08, connected,
  `device+0x440 & 0x80`. It then resumes at 0x601f9dfc or takes the stock NULL exit 0x601f9e7e.
- `0x601f5ed7` (8 B, sec 1): `call parse_hook,[],0; nop`. The hook replays `movbu (a3),d0; mov (4,sp),a0; inc
  a3; movbu d0,(17,a0)`. If `d2 (= req+21) & 1` and `(kind & 2) == 0`, it reads the LE word, advances a3 by 2
  and stores the halfword to 0xa0210ffe.
- `0x60427ae7` (5 B, sec 2): `jmp ae_hook` (in sec 7, which loads before sec 2). The hook runs the stock
  wrapper and keeps that value unless mode 4/6, the lens is connected and capable, the ring ≠ 0x8000 and
  min ≤ max. In that case it returns `clamp(ring, min, max)`, signed, with the official limits.
- Code: `.lens` 114 B at 0x60210f80 (sec-1 tail), state at 0x60210ffe, `.ae` 100 B at 0x61378f9c (sec-7 tail,
  up to the section end). Claimed in `docs/CODE_SPACE_MAP.md`. No overlap with v0.4 or v0.5-candidate.

## Verification (emulator; stock vs patched payloads from the built package)

`tools/ep7_verify_aperture_ring.py`. Native code, explicit synthetic RAM, nothing faked except the RAM contents.

- D, dispatcher (1921 cases): commands × req+12 × option byte × connection × device × capability. The request
  differs from stock only by `+21 |= 1`, and only in the intended case. Registers, stack and NULL path match stock.
- P, parser through the LAF loop (600 cases): kinds 0–5 × flags 0/8/0x10/0x20/0x28 × option 0/1/2/3 ×
  0x621d014e. With no ring requested, or kinds 2/3, the result is identical to stock. With the ring requested,
  a response carrying the ring word parses to the same record and LAF values as stock on the response
  without it, a3 ends +2, and the state equals the ring word.
- A, AE window with the native 0x80ca getter (298 cases): modes 0–7, connection, capability, state (initial
  0x8000, in range, below/above limits, negative), normal/reversed/signed limits. d0 = clamp only in the gated
  case. Everything else matches stock.
- M: 8/8 mutations caught (capability bit, 81 E3 compare, IS-extra test, PEN-F kind encoding, byte order, mode,
  clamp, sentinel).
- Merged with `releases/v0.4/edits.json` (`generated/v04_aperture_ring/edits.json`, 142 edits): aperture-ring,
  bundles, grain, bloom, WB and MONO-colour verifiers all PASS (logs in `generated/v04_aperture_ring/`).

## Open questions / risks (camera needed)

1. **Section-1 RAM writability [I].** Stock code never writes inside its loaded image. The PR's PEN-F state sat
   in loaded section 1 and works **[R]**. No MMU setup was found (docs/SD_BUNDLES.md). If writes fault, every
   ring-lens status response crashes. Removing the lens or using a non-ring lens avoids the write, because
   the parser writes only when the ring was requested.
2. **Lens-side behaviour [R].** That capable Panasonic lenses append the word only when asked, at that position,
   comes from PEN-F camera reports. The E-P7 talks the same protocol (same commands, same parser order) but
   is untested.
3. **Exposure correctness [I].** The aperture point feeds AE in A/M as on PEN-F. Iris position, exposure and
   EXIF have not been measured on any body. Check live view, a shot at f/1.7 and at f/8, DOF preview, and EXIF.
4. **Movie mode.** The 0xc011 getter returns other modes in movie context. Ring behaviour in movie A/M is
   unknown.
5. **Lens swap staleness** (above), and **mode numbers 4/6** are inferred for E-P7 (high confidence).
6. Test order on camera: non-ring Olympus lens (must be stock), then ring lens with the ring at A (must be
   stock), then ring at stops in A and in M, P/S (must be stock), then zooming across the min-aperture change.
