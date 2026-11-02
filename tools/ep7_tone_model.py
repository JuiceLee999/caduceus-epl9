#!/usr/bin/env python3
"""Camera luminance tone LUT for Highlight / Shadow / Midtone (+ Blacks / Whites), bit-exact model.

E-P7 1.1, docs/TONE_ENDS.md section 1. The stock tone control (H/S/M, -7..7 per Colour Profile) bends the
luminance LUT (256 x u16, 0..1023, display/gamma domain) in two native steps, both reproduced here exactly:

  1. 0x6034fcd2  knots:  q_f = trunc(v_f * 4096 / 7) for f in H, M, S (tone block +4, +6, +8);
                         w[j] = floor(sum_f G_f[j] * q_f / 4096), j = 0..7  (G = tools/data/tone_hsm.json "gains",
                         the knot words at v = +7; this linear form matched every emulated case exactly).
  2. 0x6034ff93  bend:   fixed-point natural cubic splines (solver 0x6034fdad, evaluator 0x6034fee7):
                         curve A (x 0,204,473,832,1023; y[1] -= w2, y[3] += w2) on the LUT sampled at
                         k = 0,10,...,250,255 (27 points); then, if w5 == 0 (and flag != 1), curve B
                         (x 0,130,473,474,476,477,832,1023; y[1] += w3, y[6] += w4), else curve C
                         (x 0,130,473,832,1023; y[1] += w6, y[2] += w5, y[3] += w7), each output clamped 0..1023
                         and running-max; then a 27-knot spline back to 256 entries (even k from the spline,
                         odd k = mean of neighbours), clamped and monotone.
     All zero -> the camera keeps the ROM LUT (no bend).

Superposition of per-field LUT deltas does NOT hold (curve C replaces curve B as soon as Midtones != 0, and
the curves compose), max error 28 codes on the mixed checks; so the model stores the knot gains and runs the
splines. Verified against the emulator (--verify-emulator): 42 single-field runs, 12 mixed, 40 random combos
and 5 contrast +2 runs, all bit-exact (max error 0).

Blacks / Whites (-5..5, our end-point remap, patches/tone_ends) are applied after H/S/M by tools/ep7_tone.py
remap() when that module is present.

  tools/ep7_tone_model.py --check                 verify the stored test vectors (no emulator needed)
  tools/ep7_tone_model.py --verify-emulator       re-run the native code in the MN103 emulator and compare
  tools/ep7_tone_model.py --write-data            regenerate tools/data/tone_hsm.json from the emulator
  tools/ep7_tone_model.py H S M [B W]             print the LUT at a few knots
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'tools/data/tone_hsm.json'
sys.path.insert(0, str(ROOT / 'tools'))

try:                                    # Blacks / Whites reference (patches/tone_ends); optional
    import ep7_tone as _ends
except ImportError:                     # HOOK: without tools/ep7_tone.py, Blacks / Whites are ignored
    _ends = None

LIMIT = 7
SAMPLES = list(range(0, 251, 10)) + [255]          # ROM 0x604e9380
CURVE_A = [0, 204, 473, 832, 1023]                 # ROM 0x604e93b6
CURVE_B = [0, 130, 473, 474, 476, 477, 832, 1023]  # ROM 0x604e93c0
CURVE_C = [0, 130, 473, 832, 1023]                 # ROM 0x604e93d0
FIELDS = ('highlights', 'midtones', 'shadows')     # tone block +4, +6, +8

_data = None


def data():
    global _data
    if _data is None:
        _data = json.loads(DATA.read_text())
    return _data


def base_lut():
    """Contrast-0 ROM LUT 0x604fa082."""
    return list(data()['base_lut'])


# ---------------------------------------------------------------- fixed-point helpers (MN103 semantics)
def _i32(v):
    v &= 0xffffffff
    return v - (1 << 32) if v & 0x80000000 else v


def _div(a, b):                          # signed div, truncates toward zero
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _s16(v):
    v &= 0xffff
    return v - 65536 if v & 0x8000 else v


def _solve(xs, ys):                      # 0x6034fdad
    n = len(xs); M = [0] * n; H = [0] * n; P = [0] * (n + 1)
    for i in range(n - 1):
        H[i] = xs[i + 1] - xs[i]
        P[i + 1] = _i32(_div(_i32((ys[i + 1] - ys[i]) << 10), H[i]))
    M[1] = _i32(P[2] - P[1]); P[1] = 2 * (xs[2] - xs[0])
    for i in range(1, n - 2):
        r = _div(_i32(H[i] << 10), P[i])
        M[i + 1] = _i32(P[i + 2] - P[i + 1] - (_i32(r * M[i]) >> 10))
        P[i + 1] = _i32(2 * (xs[i + 2] - xs[i]) - (_i32(H[i] * r) >> 10))
    M[n - 2] = _i32(M[n - 2] - _i32(H[n - 2] * M[n - 1]))
    for k in range(n - 2, 0, -1):
        M[k] = _div(_i32(_i32(M[k] << 10) - _i32(H[k] * M[k + 1])), P[k])
    return M


def _eval(x, xs, ys, M):                 # 0x6034fee7
    lo, hi = 0, len(xs) - 1
    while lo < hi:
        mid = (lo + hi) >> 1
        if xs[mid] < x:
            lo = mid + 1
        else:
            hi = mid
    k = lo - 1 if lo > 0 else 0
    h = xs[k + 1] - xs[k]; t = x - xs[k]
    b = _i32(_div(_i32((ys[k + 1] - ys[k]) << 20), h) - _i32((2 * M[k] + M[k + 1]) * h))
    c = _div(_i32((M[k + 1] - M[k]) * t), h)
    v = _i32(t * _i32(_i32(t * (3 * M[k] + c)) + b))
    return _i32(v + _i32(ys[k] << 20) + 524288) >> 20


# ---------------------------------------------------------------- the two native steps
def knots(h=0, s=0, m=0):
    """0x6034fcd2: H/S/M (-7..7) -> 8 knot words (C+64)."""
    g = data()['gains']
    v = dict(highlights=h, midtones=m, shadows=s)
    q = {f: _div(v[f] << 12, 7) for f in FIELDS}
    return [sum(g[f][j] * q[f] for f in FIELDS) >> 12 for j in range(8)]


def bend(lut, w, flag=0):
    """0x6034ff93: bend a 256-entry LUT by knot words w (flag = R+1802 bit 7, 0 in normal use)."""
    ya = list(CURVE_A); ya[1] -= w[2]; ya[3] += w[2]
    ma = _solve(CURVE_A, ya)
    smp = [_s16(_eval(lut[x], CURVE_A, ya, ma)) for x in SAMPLES]
    if w[5] == 0 and flag != 1:
        xs = CURVE_B; ys = list(xs); ys[1] += w[3]; ys[6] += w[4]
    else:
        xs = CURVE_C; ys = list(xs); ys[1] += w[6]; ys[3] += w[7]; ys[2] += w[5]
    mc = _solve(xs, ys)
    out, prev = [], 0
    for i, x in enumerate(smp):
        v = _s16(_eval(x, xs, ys, mc))
        prev = (0 if v <= 0 else min(v, 1023)) if i == 0 else (prev if v <= prev else min(v, 1023))
        out.append(prev)
    md = _solve(SAMPLES, out)
    L = [0] * 256; d3 = out[0]; L[0] = d3; j = 1
    for a in range(2, 255, 2):
        if a < SAMPLES[j]:
            v = _s16(_eval(a, SAMPLES, out, md))
        else:
            v = out[j]; j += 1
        d2 = d3 if v <= d3 else min(v, 1023)
        L[a - 1] = (d3 + d2) >> 1; L[a] = d2; d3 = d2
    v = out[26]
    L[255] = d3 if v <= d3 else min(v, 1023)
    return L


def _clamp(v, lim):
    return max(-lim, min(lim, int(v)))


def hsm_lut(h=0, s=0, m=0, base=None):
    """Camera LUT for tone H/S/M on `base` (default contrast-0 ROM LUT). Values clamp to -7..7."""
    base = base_lut() if base is None else list(base)
    h, s, m = (_clamp(v, LIMIT) for v in (h, s, m))
    if not (h or s or m):
        return base
    return bend(base, knots(h, s, m))


def tone_lut(h=0, s=0, m=0, blacks=0, whites=0, base=None):
    """H/S/M bend, then the Blacks / Whites end-point remap (if tools/ep7_tone.py is present)."""
    lut = hsm_lut(h, s, m, base)
    if (blacks or whites) and _ends is not None:
        lut = _ends.remap(lut, blacks, whites)
    return lut


def from_tone(t, base=None):
    """LUT for a look's "tone" dict {highlights, shadows, midtones, blacks, whites} (missing keys = 0)."""
    t = t or {}
    return tone_lut(t.get('highlights', 0), t.get('shadows', 0), t.get('midtones', 0),
                    t.get('blacks', 0), t.get('whites', 0), base)


# ---------------------------------------------------------------- emulator (optional)
def _emulator():
    import struct
    sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
    from penf_emulator import Region, execute
    img = (ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes()
    BASE, CALLER, STACK = 0x60020020, 0x18000000, 0x18010000

    def call(fn, regs_extra, bufs):
        regs = [Region('caller', CALLER, b'\xdd' + struct.pack('<i', fn - CALLER) + bytes((0, 16)) + b'\xcb', 'rx'),
                Region('code', 0x60340000, img[0x60340000 - BASE:0x60360000 - BASE], 'rx'),
                Region('data', 0x604e0000, img[0x604e0000 - BASE:0x60540000 - BASE], 'r'),
                Region('stack', STACK, bytes(0x2000), 'rw')] + bufs
        r = execute(regs, dict(pc=CALLER, sp=STACK + 0x1800, **regs_extra), CALLER + 7, limit=3000000)
        assert r['status'] == 'returned', r
        return {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}

    def run(h, s, m, base_addr=0x604fa082):
        base = list(struct.unpack_from('<256H', img, base_addr - BASE))
        blk = struct.pack('<5h', 0, 0, h, m, s) + bytes(118)
        m1 = call(0x6034fcd2, {'a0': 0x1b000000, 'a1': 0x1c000000},
                  [Region('blk', 0x1b000000, blk, 'rw'), Region('ctx', 0x1c000000, bytes(64), 'rw', True)])
        m2 = call(0x6034ff93, {'a0': 0x1d000000, 'a1': 0x1c000000, 'd0': 0},
                  [Region('lut', 0x1d000000, struct.pack('<256H', *base), 'rw', True),
                   Region('ctx', 0x1c000000, m1['ctx'], 'rw')])
        return base, list(struct.unpack_from('<8h', m1['ctx'])), list(struct.unpack('<256H', m2['lut']))
    return run


MIXED = [(7, 7, 7), (-7, -7, -7), (7, -7, 0), (-7, 7, 0), (0, 7, -7), (3, -2, 5), (-4, 5, -3), (2, 2, -6),
         (-5, -5, 4), (6, -3, -7), (-2, 3, 3), (4, 4, 4)]          # (H, S, M)


def write_data():
    run = _emulator()
    base, _, _ = run(0, 0, 0)
    gains = {'highlights': run(7, 0, 0)[1], 'shadows': run(0, 7, 0)[1], 'midtones': run(0, 0, 7)[1]}
    global _data
    _data = {'base_lut': base, 'gains': gains}
    vectors = [dict(h=h, s=s, m=m, lut=run(h, s, m)[2]) for h, s, m in [(7, 0, 0), (0, -7, 0), (0, 0, 3), (3, -2, 5),
                                                                          (-4, 5, -3), (-7, 7, 0)]]
    doc = {
        '_comment': ('E-P7 1.1 stock tone control (Highlights/Shadows/Midtones, -7..7) as a bit-exact model of the '
                     'camera luminance LUT (256 x u16, 0..1023, display/gamma domain). Reference: '
                     'tools/ep7_tone_model.py (docs/TONE_ENDS.md section 1, docs/LIBRARY_V1.md "v0.19 tone").'),
        'algorithm': [
            'base_lut: contrast-0 ROM LUT 0x604fa082 (index k = display luminance knot, value 0..1023).',
            'If H = S = M = 0 the camera keeps base_lut unchanged.',
            'knots: q_f = trunc(v_f*4096/7) (C-style toward zero); w[j] = floor((gains.highlights[j]*q_H + '
            'gains.midtones[j]*q_M + gains.shadows[j]*q_S) / 4096), j = 0..7 (arithmetic shift >> 12).',
            'bend: see tools/ep7_tone_model.py bend(): int32 fixed-point natural cubic splines (solve/eval), '
            'curve A x=curve_a_x (y[1]-=w2, y[3]+=w2) on base_lut sampled at samples_k; then curve B x=curve_b_x '
            '(y[1]+=w3, y[6]+=w4) if w5 == 0, else curve C x=curve_c_x (y[1]+=w6, y[2]+=w5, y[3]+=w7); each '
            'sample clamped 0..1023 and running-max; then a spline through (samples_k, result) gives even k, odd k = '
            '(prev + next) >> 1, k=255 = last sample; all clamped and monotone.',
            'Per-field LUT deltas do not superpose (max error 28 codes), so a port must run the splines; '
            'test_vectors give exact expected LUTs.',
            'Blacks/Whites: tools/ep7_tone.py remap(lut, B, W) applied to the result.'],
        'fields': {'highlights': 'tone block +4', 'midtones': 'tone block +6', 'shadows': 'tone block +8'},
        'samples_k': SAMPLES, 'curve_a_x': CURVE_A, 'curve_b_x': CURVE_B, 'curve_c_x': CURVE_C,
        'gains': gains, 'base_lut': base, 'test_vectors': vectors,
    }
    DATA.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(doc, indent=1)
    txt = re.sub(r'\[\s*(-?\d+(?:,\s*-?\d+)*)\s*\]', lambda mo: '[' + re.sub(r'\s+', ' ', mo.group(1)) + ']', txt)
    DATA.write_text(txt + '\n')
    print('wrote', DATA)


def verify_emulator():
    import random
    run = _emulator()
    cases = [(v if f == 0 else 0, v if f == 1 else 0, v if f == 2 else 0, 0x604fa082)
             for f in range(3) for v in range(-7, 8) if v]
    cases += [(h, s, m, 0x604fa082) for h, s, m in MIXED]
    rnd = random.Random(19)
    cases += [(rnd.randint(-7, 7), rnd.randint(-7, 7), rnd.randint(-7, 7), 0x604fa082) for _ in range(40)]
    cases += [(h, s, m, 0x604fb482) for h, s, m in [(0, 0, 3), (2, -3, 0), (-7, 7, 7), (5, 5, -5), (1, 0, 0)]]
    worst = worst_sup = 0
    singles = {}
    for h, s, m, ba in cases:
        base, w, lut = run(h, s, m, ba)
        e = max(abs(a - b) for a, b in zip(hsm_lut(h, s, m, base), lut))
        worst = max(worst, e)
        if ba == 0x604fa082 and [h, s, m].count(0) == 2:
            singles[(h, s, m)] = [a - b for a, b in zip(lut, base)]
        elif ba == 0x604fa082 and (h, s, m) in MIXED:
            d = [singles.get((h, 0, 0), [0] * 256), singles.get((0, s, 0), [0] * 256), singles.get((0, 0, m), [0] * 256)]
            sup = [min(1023, max(0, base[k] + d[0][k] + d[1][k] + d[2][k])) for k in range(256)]
            worst_sup = max(worst_sup, max(abs(a - b) for a, b in zip(sup, lut)))
    print(f'{len(cases)} emulator cases: model max error {worst}; per-field LUT superposition max error {worst_sup}')
    return worst == 0


def check():
    bad = 0
    for v in data()['test_vectors']:
        if hsm_lut(v['h'], v['s'], v['m']) != v['lut']:
            bad += 1
    print(f"{len(data()['test_vectors'])} test vectors, {bad} mismatches; Blacks/Whites remap "
          f"{'tools/ep7_tone.py' if _ends else 'NOT AVAILABLE (hook)'}")
    return bad == 0


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[:1] == ['--check']:
        sys.exit(0 if check() else 1)
    if a[:1] == ['--verify-emulator']:
        sys.exit(0 if verify_emulator() else 1)
    if a[:1] == ['--write-data']:
        write_data(); sys.exit(0)
    vals = [int(x) for x in a] + [0] * (5 - len(a))
    lut = tone_lut(*vals[:5])
    K = (0, 8, 16, 32, 64, 96, 128, 160, 192, 224, 240, 255)
    print('k   ', K); print('base', [base_lut()[k] for k in K]); print('tone', [lut[k] for k in K])
