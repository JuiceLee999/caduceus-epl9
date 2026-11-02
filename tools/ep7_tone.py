#!/usr/bin/env python3
"""Reference model of the per-profile Blacks / Whites luminance-LUT remap (patches/tone_ends, docs/TONE_ENDS.md §6).

remap(lut, B, W) is bit-exact with the camera routine (tools/ep7_verify_tone_ends.py checks the assembled code
against it on every case). Importable by sim/ and the web app (no dependencies).

  lut   256 stock LUT values (u16, 10-bit 0..1023; the active LUT after contrast / gradation / tone control / art)
  B     Blacks  -5..5 (slot byte +47, s8)   >0 lifts the black point to 8*B (matte), <0 crushes the toe
  W     Whites  -5..5 (slot byte +48, s8)   <0 rolls the white point down to 1023-10*|W|, >0 pushes the shoulder
A value outside -5..5 counts as 0. B = W = 0 returns the LUT unchanged (the camera does not even copy it).

Per knot, integer only:
  y  = min(y, 1023)
  t  = 1023 - y;  y -= cB * (((t*t >> 10) * t) >> 10) >> 10,  y = max(y, 0)      cB = 12*|B| for B < 0, else 0
                  y += cW * (((y*y >> 10) * y) >> 10) >> 10,  y = min(y, 1023)   cW = 12*W   for W > 0, else 0
  y  = lo + ((y * K + 0xFFFFF) >> 20)    lo = 8*B (B > 0) else 0, hi = 1023 - 10*|W| (W < 0) else 1023,
                                         K = (hi - lo) * 1025, so 0 -> lo, 1023 -> hi, identity when lo=0, hi=1023
  y  = max(y, previous output)           (running max: the result is monotone)
"""

LIMIT = 5


def params(B, W):
    """-> (lo, hi, cB, cW) for slot values B, W (out-of-range values count as 0)."""
    B = B if -LIMIT <= B <= LIMIT else 0
    W = W if -LIMIT <= W <= LIMIT else 0
    lo = 8 * B if B > 0 else 0
    hi = 1023 + 10 * W if W < 0 else 1023
    cB = -12 * B if B < 0 else 0
    cW = 12 * W if W > 0 else 0
    return lo, hi, cB, cW


def active(B, W):
    return params(B, W) != (0, 1023, 0, 0)


def remap(lut, B, W):
    """256 LUT values -> remapped list (or an unchanged copy when B = W = 0 after the range rule)."""
    lut = list(lut)
    if len(lut) != 256:
        raise ValueError('LUT must have 256 entries')
    if not active(B, W):
        return lut
    lo, hi, cB, cW = params(B, W)
    K = (hi - lo) * 1025
    prev, out = 0, []
    for y in lut:
        y = min(y & 0xffff, 1023)
        t = 1023 - y
        y -= (cB * ((((t * t) >> 10) * t) >> 10)) >> 10
        y = max(y, 0)
        y += (cW * ((((y * y) >> 10) * y) >> 10)) >> 10
        y = min(y, 1023)
        y = lo + ((y * K + 0xFFFFF) >> 20)
        y = max(y, prev)
        prev = y
        out.append(y)
    return out


if __name__ == '__main__':
    ident = [round(k * 1023 / 255) for k in range(256)]
    for B, W in ((0, 0), (5, 0), (-5, 0), (0, -5), (0, 5), (3, -2)):
        y = remap(ident, B, W)
        print(f'B={B:+d} W={W:+d}:', [y[k] for k in (0, 8, 16, 32, 64, 128, 192, 224, 240, 255)])
