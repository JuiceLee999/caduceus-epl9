#!/usr/bin/env python3
"""Offline emulator + static checks for the E-P7 1.1 tone path (docs/VIDEO_LOG.md).

Read-only. Never writes firmware. Runs native E-P7 code in fishcu's MN103 runner
(external/oly_fw_analysis, generic `execute()`), with every region taken from OUR decoded main.

Checks
  T1  bank A (RGB gamma, 256 x u16, 12-bit in/out): identity curve at 0x604edc78 ~= 4095*k/255.
  T2  bank B (luminance tone, 256 x u16, 10-bit): Normal/contrast-0 LUT 0x604fa082 ~= 4*k.
  E1  effect-id mapper 0x60349297: input byte +6 = 0/1/2 -> output id = picture mode / 2000 / 2001.
  G1  RGB-gamma selector 0x603ae354 (native): id 2 (ordinary mode) -> row-0 curve 0x604ede78;
      id 2000 -> 0x604f4278; id 2001 -> 0x604f4478 (same pointer to all three outputs).
  L1  luminance-tone selector 0x603b039b (native): id 2, contrast 0 -> 0x604fa082 (or its
      flag variant); id 2000/2001 -> 0x604fa082 whatever the contrast byte says.
  C1  curve analysis of the two hidden curves: codes per stop, log fit, 8-bit steps.

Usage: tools/ep7_video_log_probe.py [--json out.json]
"""
import argparse, hashlib, json, math, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
from penf_emulator import execute, Region  # noqa: E402  (generic runner; no PEN-F image used)

MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
BASE = 0x60020020

GAMMA_ID, GAMMA_LOG2000, GAMMA_LOG2001, GAMMA_ROW0 = 0x604edc78, 0x604f4278, 0x604f4478, 0x604ede78
GAMMA_ROW0_FLAG = 0x604ee078
LUM_NORMAL, LUM_NORMAL_FLAG = 0x604fa082, 0x604fa282
GAMMA_ROWS, N_ROWS = 0x60530b6c, 25

CALLER, STACK, REQ, OUTS = 0x18000000, 0x18010000, 0x1b000000, 0x1c000000


def main_image():
    d = MAIN.read_bytes()
    assert hashlib.sha256(d).hexdigest() == MAIN_SHA, 'unexpected E-P7 main'
    return d


def u16s(d, a, n=256):
    return list(struct.unpack_from(f'<{n}H', d, a - BASE))


def img(d, name, lo, hi, perm='r'):
    return Region(name, lo, d[lo - BASE:hi - BASE], perm)


def caller(target, mask, frame):
    return Region('caller', CALLER, b'\xdd' + struct.pack('<i', target - CALLER) + bytes((mask, frame)) + b'\xcb', 'rx')


def run(regions, regs):
    r = execute(regions, regs, CALLER + 7, limit=20000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return r, mem


def request(effect_id, contrast=0, gradation=0, fmt=0):
    q = bytearray(1884)
    q[8:12] = bytes([(effect_id >> 24) & 0xff, (effect_id >> 16) & 0xff]) + struct.pack('<H', effect_id & 0xffff)
    struct.pack_into('<H', q, 12, fmt)            # request+12 format code (0: none of the special ones)
    struct.pack_into('<H', q, 14, 0)              # request+14 class (column 0 of a gamma row)
    q[16] = 0                                     # request kind 0 (raw development)
    struct.pack_into('<H', q, 28, 0x0100)         # type high byte 1 -> flag = bit2 of +48
    q[48] = 0                                     # flag variant off
    struct.pack_into('<I', q, 1524, 0)            # no override pointer
    q[1796] = contrast & 0xff                     # contrast (signed byte)
    q[1797] = gradation & 0xff                    # gradation (0 Normal, 1 High Key, -1 Low Key, 2 Auto)
    struct.pack_into('<H', q, 1838, 0)
    return bytes(q)


def check_mapper(d):
    res = []
    for b6, want in ((0, 3), (1, 2000), (2, 2001)):
        inp = struct.pack('<HHBBBB', 3, 0, 0, 0, b6, 0)       # picture mode 3, art 0, flags
        regions = [caller(0x60349297, 0x30, 8), img(d, 'code', 0x60349297, 0x603494d7, 'rx'),
                   img(d, 'tbl', 0x604f8a78 - 0x1000, 0x604f8a78), Region('stack', STACK, bytes(0x1000), 'rw'),
                   Region('inp', REQ, inp, 'rw'), Region('out', OUTS, bytes(8), 'rw', True)]
        r, mem = run(regions, {'pc': CALLER, 'sp': STACK + 0x800, 'a0': OUTS, 'a1': REQ})
        out = mem['out']
        got = (out[0] << 24) | (out[1] << 16) | struct.unpack_from('<H', out, 2)[0]
        res.append(dict(byte6=b6, effect_id=got, expected=want, passed=got == want and r['registers']['pc'] == CALLER + 7))
    return dict(check='E1 effect-id mapper 0x60349297', passed=all(x['passed'] for x in res), cases=res)


def gamma_regions(d):
    return [img(d, 'gsel', 0x603ae2fd, 0x603ae709, 'rx'), img(d, 'helpers', 0x603b55e3, 0x603b5675, 'rx'),
            img(d, 'switch', 0x60532110, 0x60532190), img(d, 'rows', GAMMA_ROWS, GAMMA_ROWS + 32 * N_ROWS)]


def check_gamma(d):
    res = []
    for eid, want in ((2, (GAMMA_ROW0, GAMMA_ROW0_FLAG)), (2000, (GAMMA_LOG2000,)), (2001, (GAMMA_LOG2001,))):
        regions = [caller(0x603ae354, 0xf0, 28), Region('stack', STACK, bytes(0x1000), 'rw'),
                   Region('req', REQ, request(eid), 'rw'), Region('out', OUTS, bytes(16), 'rw', True)] + gamma_regions(d)
        r, mem = run(regions, {'pc': CALLER, 'sp': STACK + 0x800, 'a0': REQ, 'd0': OUTS, 'd1': OUTS + 4, 'a1': OUTS + 8})
        p = struct.unpack_from('<3I', mem['out'])
        ok = r['registers']['pc'] == CALLER + 7 and len(set(p)) == 1 and p[0] in want
        res.append(dict(effect_id=eid, pointers=[hex(x) for x in p], expected=[hex(x) for x in want],
                        status=r['status'], fault=r['fault'], passed=bool(ok)))
    return dict(check='G1 RGB-gamma selector 0x603ae354', passed=all(x['passed'] for x in res), cases=res)


def check_lum(d):
    res = []
    cases = [(2, 0, (LUM_NORMAL, LUM_NORMAL_FLAG)), (2, 2, (0x604fb482,)), (2, -2, (0x604fb282,)),
             (2000, 0, (LUM_NORMAL,)), (2000, 2, (LUM_NORMAL,)), (2001, -2, (LUM_NORMAL,)), (2001, 2, (LUM_NORMAL,))]
    for eid, con, want in cases:
        regions = [caller(0x603b039b, 0xf0, 24), img(d, 'lsel', 0x603b039b, 0x603b07f7, 'rx'),
                   img(d, 'helpers', 0x603b55e3, 0x603b5675, 'rx'), img(d, 'switch', 0x60532738, 0x60532b38),
                   img(d, 'ctab', 0x60500db0, 0x60500db6), Region('stack', STACK, bytes(0x1000), 'rw'),
                   Region('req', REQ, request(eid, contrast=con), 'rw'), Region('flag', OUTS, bytes(4), 'rw', True)]
        r, _ = run(regions, {'pc': CALLER, 'sp': STACK + 0x800, 'a0': REQ, 'a1': OUTS})
        p = r['registers']['a0']
        ok = r['registers']['pc'] == CALLER + 7 and p in want
        res.append(dict(effect_id=eid, contrast=con, lut=hex(p), expected=[hex(x) for x in want],
                        status=r['status'], fault=r['fault'], passed=bool(ok)))
    return dict(check='L1 luminance-tone selector 0x603b039b', passed=all(x['passed'] for x in res), cases=res)


def gamma_eval(c, x):
    """Linear interpolation of a 256-knot bank-A curve at linear input x (1.0 = 12-bit full scale)."""
    t = min(max(x, 0.0), 1.0) * 4095 / 16
    i = min(int(t), 254)
    return (c[i] + (t - i) * (c[i + 1] - c[i])) / 4095


def curve_report(d, a):
    c = u16s(d, a)
    stops = [round(gamma_eval(c, 2.0 ** -k), 4) for k in range(13)]
    per = [round(stops[k] - stops[k + 1], 4) for k in range(12)]
    xs = [2.0 ** -k for k in range(1, 7)]
    ys = [gamma_eval(c, x) for x in xs]
    lx = [math.log2(x) for x in xs]
    mx, my = sum(lx) / 6, sum(ys) / 6
    slope = sum((a_ - mx) * (b - my) for a_, b in zip(lx, ys)) / sum((a_ - mx) ** 2 for a_ in lx)
    icpt = my - slope * mx
    dev = max(abs(icpt + slope * l - y) for l, y in zip(lx, ys))
    grey = {f'grey_at_-{k}EV': dict(full_8bit=round(255 * stops[k], 1), legal_8bit=round(16 + 219 * stops[k], 1))
            for k in (3, 4, 5)}
    return dict(addr=hex(a), monotone=all(b >= a_ for a_, b in zip(c, c[1:])), first_knots=c[:6], last_knots=c[-4:],
                out_vs_stops_below_clip=stops, per_stop=per, log_fit_stops_1_to_6=dict(
                    per_stop=round(slope, 4), at_clip=round(icpt, 4), max_dev=round(dev, 4)),
                eight_bit_codes_per_stop_full=[round(255 * p, 1) for p in per[:8]], grey=grey)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    args = ap.parse_args()
    d = main_image()
    ident = u16s(d, GAMMA_ID)
    dev = max(abs(v - 4095 * k / 255) for k, v in enumerate(ident))
    t1 = dict(check='T1 bank-A identity ~= 4095*k/255 (12-bit in/out)', passed=dev <= 3 and ident[-1] == 4095,
              max_abs_dev=round(dev, 2))
    lum = u16s(d, LUM_NORMAL)
    t2 = dict(check='T2 bank-B Normal LUT ~= 4*k', passed=max(abs(v - 4 * k * 1023 / 1020) for k, v in enumerate(lum)) <= 4,
              max_abs_dev=round(max(abs(v - 4 * k * 1023 / 1020) for k, v in enumerate(lum)), 1))
    checks = [t1, t2, check_mapper(d), check_gamma(d), check_lum(d)]
    rows = [[hex(x) for x in struct.unpack_from('<8I', d, GAMMA_ROWS - BASE + 32 * i)] for i in range(N_ROWS)]
    out = dict(main_sha256=MAIN_SHA, checks=checks,
               curves={'id2000': curve_report(d, GAMMA_LOG2000), 'id2001': curve_report(d, GAMMA_LOG2001),
                       'row0_default': curve_report(d, GAMMA_ROW0)},
               gamma_rows=rows)
    for c in checks:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['check'])
        for k in c.get('cases', []):
            print('     ', {kk: vv for kk, vv in k.items() if kk not in ('status', 'fault')})
    for n, c in out['curves'].items():
        print(n, c['addr'], 'log fit', c['log_fit_stops_1_to_6'], '\n   out@stops', c['out_vs_stops_below_clip'],
              '\n   grey', c['grey'])
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1))
    sys.exit(0 if all(c['passed'] for c in checks) else 1)


if __name__ == '__main__':
    main()
