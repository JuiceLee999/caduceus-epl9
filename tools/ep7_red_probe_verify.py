#!/usr/bin/env python3
"""Emulator check of the red-tint mask-route probe (patches/bloom --red-probe, docs/HALATION_RED.md section 10). Offline.

  .venv/bin/python -I tools/ep7_red_probe_verify.py SPEC.json --base OLD_SPEC.json

  S  blend setup hook 0x6035caad -> probe_set -> 0x6035cab3: red-tint slots (effect 1 tint 1, effect 2 tint 0/1) with job
     buffer 0x1060 present copy its 64-B descriptor to request+148 and +680 = 1024; replayed d1/d2 loads, d3/a2/a3/sp kept;
     no other job byte changes. No 0x1060, other tints, tint 0, clarity, no marker, mode 12 -> no store at all.
  B  combiner 11 (0x0402) bank: red + request+148 == 0x1060 descriptor -> the release's halo bank with the mask-route
     fields (+4 0x1002, +88 0, +92/+96 1024, +120 colour, +132 0x151500, +136/+140 2b, +180 3); a mismatching +148, no
     0x1060 entry, other tints, tint 0, clarity, and combiner 12 -> byte-identical to OLD_SPEC (fail safe = current bloom).
"""
import argparse, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


HV = _load('ep7_halation_verify_p', ROOT / 'tools/ep7_halation_verify.py')
BV, EV, BLD, MAGIC = HV.BV, HV.EV, HV.BLD, HV.MAGIC
Region = BV.Region if hasattr(BV, 'Region') else HV.CV.Region
JOB, REQ, RIJ = BV.JOB, BV.REQ, BV.REQ_IN_JOB
IDX = 5                                                     # 0x1060's slot in the job buffer table
DESC = bytes(range(0x40, 0x80))                             # a recognisable 64-B descriptor


def job(slot_eff, mask=True, req148=None, ext=(1, 11, MAGIC), eff=0x0402):
    j = BV.job_with_request(11, eff, ext=ext, rec=3)
    for k in range(48):                                      # ids: 0x1000 at 0, 0x1061 at 1, 0x1060 at IDX
        e = BLD.BUF_TAB + 88 * k
        struct.pack_into('<I', j, e + 76, {0: 0x1000, 1: 0x1061}.get(k, 0x1060 if (k == IDX and mask) else 0x2000 + k))
        j[e:e + 64] = DESC if k == IDX else bytes([k]) * 64
    if req148 is not None:
        j[RIJ + 148:RIJ + 212] = req148
    return j


def bank(img, table, j, eff=0x0402):
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, REQ)
    struct.pack_into('<I', ctx, 8, BV.BANKB)
    struct.pack_into('<I', ctx, 52, 11)
    r = BV.execute(BV.regions(img, table, [BV.stack(), BV.PR.caller(0x603a013b, 0xf0, 20),
                                           Region('ctx', BV.CTX, bytes(ctx), 'rw', True),
                                           Region('job', JOB, bytes(j), 'rw', True),
                                           Region('bank', BV.BANKB, bytes(7364 + 256), 'rw', True)]),
                   {'pc': BV.CALLER, 'sp': BV.STACK + 0x1800, 'a0': BV.CTX, **BV.REGS0}, BV.CALLER + 7, limit=40000)
    m = BV.mem(r)
    return BV.regs_ok(r, BV.CALLER + 7) and m['job'] == bytes(j), m['bank'][7364:7364 + 184]


def setup(img, table, j):
    a3 = JOB + BLD.BUF_TAB                                   # 0x1000's entry
    r = BV.execute(BV.regions(img, table, [BV.stack({8: JOB}), Region('job', JOB, bytes(j), 'rw', True)]),
                   {'pc': BLD.PS_HOOK, 'sp': BV.STACK + 0x1800, 'a2': REQ, 'a3': a3, 'd3': 0x3333, 'd2': 7,
                    'd0': 0xdead, 'd1': 0xbeef}, BLD.PS_BACK, limit=20000)
    rr, m = r['registers'], BV.mem(r)
    want_d1, want_d2 = struct.unpack_from('<HH', j, BLD.BUF_TAB + 12)
    ok = (not r['fault'] and rr['pc'] == BLD.PS_BACK and rr['sp'] == BV.STACK + 0x1800 and rr['a2'] == REQ and
          rr['a3'] == a3 and rr['d3'] == 0x3333 and rr['d1'] == want_d1 and rr['d2'] == want_d2)
    return ok, m['job']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec')
    ap.add_argument('--base', required=True)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    _, img = EV.images(spec)
    _, base = EV.images(json.loads(Path(a.base).read_text()))
    colour = int(spec['bloom']['halation']['red_probe']['colour'], 16)
    res = {}
    # S
    n, fails = 0, []
    red = [(1, 4, 1), (1, 1, 1), (2, 4, 0), (2, 5, 1)]
    other = [(1, 4, 0), (1, 4, 2), (1, 4, 4), (3, 2, 0), (3, 2, 1), (0, 0, 1), (2, 4, 3)]
    for (e, s, t) in red + other:
        for mask in (True, False):
            for ext in ((1, 11, MAGIC), (4, 11, MAGIC), (1, 12, MAGIC), (1, 11, 0), (5, 11, MAGIC)):
                prof = ext[0]
                tb = HV.ftt({min(prof, 4) - 1: (e, s, t)}) if prof <= 4 else HV.ftt({0: (e, s, t), 4: (e, s, t)})
                j = job(e, mask, ext=ext)
                ok, jo = setup(img, tb, j)
                want = bytearray(j)
                if (e, s, t) in red and mask and ext[1] == 11 and ext[2] == MAGIC and prof <= 4:
                    want[RIJ + 148:RIJ + 212] = DESC
                    struct.pack_into('<H', want, RIJ + 680, 1024)
                n += 1
                if not (ok and jo == bytes(want)):
                    fails.append(f'S e{e} s{s} t{t} mask{mask} ext{ext}: ok={ok} diff={[i for i in range(len(jo)) if jo[i] != want[i]][:6]}')
    res['S'] = (n, fails)
    # B
    n, fails = 0, []
    for (e, s, t) in red + other:
        for eff in (0x0402, 0x0403):
            for case in ('match', 'mismatch', 'nomask'):
                d = bytearray(DESC); d[60] ^= 1
                j = job(e, case != 'nomask', req148=DESC if case != 'mismatch' else bytes(d), eff=eff)
                tb = HV.ftt({0: (e, s, t)})
                okp, bp = bank(img, tb, j, eff)
                okb, bb = bank(base, tb, j, eff)
                want = bytearray(bb)
                if (e, s, t) in red and eff == 0x0402 and case == 'match':
                    b = 1024 - BLD.tint_rows(BLD.STRENGTH_W)[1][s - 1]
                    for off, v in ((4, 0x1002), (88, 0), (92, 0x04000400), (96, 1024), (120, colour), (132, 0x151500),
                                   (136, 2 * b | 2 * b << 16), (140, 2 * b), (180, 3)):
                        struct.pack_into('<I', want, off, v)
                n += 1
                if not (okp and okb and bp == bytes(want)):
                    fails.append(f'B e{e} s{s} t{t} {eff:#x} {case}: ok={okp},{okb} diff={[i for i in range(184) if bp[i] != want[i]][:8]}')
    res['B'] = (n, fails)
    bad = 0
    for k, (n, f) in res.items():
        print(f'{k}: {n - len(f)}/{n} ' + ('PASS' if not f else 'FAIL'))
        for x in f[:8]:
            print('   ', x)
        bad += len(f)
    print('ALL PASS' if not bad else 'FAILURES')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
