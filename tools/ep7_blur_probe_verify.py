#!/usr/bin/env python3
"""Emulator check of the read-only blur-buffer probe (patches/bloom --blur-probe, docs/HALATION_RED.md section 10d).

  .venv/bin/python -I tools/ep7_blur_probe_verify.py SPEC.json --base OLD_SPEC.json

  S  blend setup 0x6035caad -> bp_set -> 0x6035cab3 on SPEC vs OLD_SPEC: same registers (d1/d2 replayed, d3/a2/a3/sp
     kept), same job/request/buffer bytes (the image pipeline is untouched). The record R = L+1920 is written only for
     red-tint jobs with a valid P/L: magic, job, flags, descriptor words, 5 samples, counter. Red without 0x1060 ->
     flags 0, no samples. Other tints, tint 0, clarity, off, no marker, mode 12, MONO profile, no P, no L -> R untouched.
  C  blend callback 0x6035cbaa -> bp_cb -> 0x6035cbaf: registers and stack == OLD_SPEC; R+72.. samples and R+5 only
     when R holds 'EP7Q' and this job; another job / no record -> untouched.
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


HV = _load('ep7_halation_verify_b', ROOT / 'tools/ep7_halation_verify.py')
BV, EV, BLD, MAGIC, CV = HV.BV, HV.EV, HV.BLD, HV.MAGIC, HV.CV
B3 = BLD._sdv3()
Region = CV.Region
JOB, REQ, RIJ = BV.JOB, BV.REQ, BV.REQ_IN_JOB
P, L = B3.POOL, B3.POOL + 0x1000
BUF = 0x1b800000
W_, H_, STRIDE = 160, 120, 160
IDX = 5
QM, FM = struct.unpack('<I', b'EP7Q')[0], struct.unpack('<I', b'EP7F')[0]
PTS = [(2, 2), (1, 1), (3, 1), (1, 3), (3, 3)]


def job(mask=True, ext=(1, 11, MAGIC)):
    j = BV.job_with_request(11, 0x0402, ext=ext, rec=3)
    for k in range(48):
        e = BLD.BUF_TAB + 88 * k
        j[e:e + 64] = bytes([k]) * 64
        struct.pack_into('<I', j, e + 76, {0: 0x1000, 1: 0x1061}.get(k, 0x1060 if (k == IDX and mask) else 0x2000 + k))
    e = BLD.BUF_TAB + 88 * IDX
    j[e:e + 64] = bytes(64)
    struct.pack_into('<I', j, e, BUF)
    struct.pack_into('<HHHH', j, e + 8, 0x0305, STRIDE, W_, H_)
    return j


def buf():
    return bytes((i * 7 + 3) & 0xff for i in range(STRIDE * H_ * 4))


def heap(p_ok=True, l_ok=True, table=None):
    pb, lb = bytearray(1024), bytearray(2048)
    if table is not None:
        pb[B3.HDR_LEN:B3.HDR_LEN + 512] = table[:512]   # the SD-loaded table (the accessor's source when P is valid)
    if p_ok:
        pb[0:4] = struct.pack('<I', B3.MAGIC)
    if l_ok:
        struct.pack_into('<II', pb, 1016, L, FM)
    return pb, lb


def regions(img, table, j, pb, lb, stackw=None):
    st = bytearray(8)
    struct.pack_into('<H', st, 2, 1)                       # h = 1 -> P = pool
    pool = bytearray(0x1800)
    pool[0:1024] = pb
    pool[0x1000:0x1800] = lb
    return BV.regions(img, table, [BV.stack(stackw), Region('job', JOB, bytes(j), 'rw', True),
                                   Region('state', B3.STATE - 2, bytes(st), 'r'),
                                   Region('pool', P, bytes(pool), 'rw', True),
                                   Region('buf', BUF, buf(), 'r')])


def run_set(img, table, j, pb, lb):
    a3 = JOB + BLD.BUF_TAB
    r = BV.execute(regions(img, table, j, pb, lb, {8: JOB}),
                   {'pc': BLD.PS_HOOK, 'sp': BV.STACK + 0x1800, 'a2': REQ, 'a3': a3, 'd3': 0x3333, 'd2': 7,
                    'd0': 0xdead, 'd1': 0xbeef, 'a0': 0xa0a0, 'a1': 0xa1a1}, BLD.PS_BACK, limit=40000)
    m = BV.mem(r)
    rr = r['registers']
    keep = {k: rr[k] for k in ('pc', 'sp', 'a2', 'a3', 'd1', 'd2', 'd3')}
    return not r['fault'], keep, m['job'], m['pool']


def run_cb(img, table, j, pb, lb):
    r = BV.execute(regions(img, table, j, pb, lb), {'pc': BLD.BC_HOOK, 'sp': BV.STACK + 0x1800, 'a0': JOB, 'd2': 0x2222,
                                                     'a2': 0xa2a2, 'a3': 0xa3a3, 'd3': 0x3333}, BLD.BC_BACK, limit=40000)
    m, rr = BV.mem(r), r['registers']
    return not r['fault'], {k: rr[k] for k in ('pc', 'sp', 'a0', 'd3')}, m['stack'], m['job'], m['pool']


def samples():
    b = buf()
    out = b''
    for fx, fy in PTS:
        off = ((fy * H_ >> 2) * STRIDE + (fx * W_ >> 2)) * 4
        out += b[off:off + 8]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec')
    ap.add_argument('--base', required=True)
    a = ap.parse_args()
    _, img = EV.images(json.loads(Path(a.spec).read_text()))
    _, base = EV.images(json.loads(Path(a.base).read_text()))
    res, R = {}, 0x1000 + BLD.BP_R_OFF
    red = [(1, 4, 1), (2, 4, 0), (2, 5, 1)]
    other = [(1, 4, 0), (1, 4, 2), (1, 4, 4), (3, 2, 1), (0, 0, 1), (2, 4, 3)]
    n, fails = 0, []
    for (e, s, t) in red + other:
        for mask in (True, False):
            for ext in ((1, 11, MAGIC), (4, 11, MAGIC), (1, 12, MAGIC), (1, 11, 0), (5, 11, MAGIC)):
                for p_ok, l_ok in ((True, True), (True, False), (False, True)):
                    prof = ext[0]
                    tb = HV.ftt({min(prof, 4) - 1: (e, s, t)}) if prof <= 4 else HV.ftt({0: (e, s, t), 4: (e, s, t)})
                    j = job(mask, ext)
                    pb, lb = heap(p_ok, l_ok, tb)
                    ok1, k1, j1, p1 = run_set(img, tb, j, pb, lb)
                    ok0, k0, j0, p0 = run_set(base, tb, j, pb, lb)
                    want = bytearray(p0)
                    if (e, s, t) in red and ext[1] == 11 and ext[2] == MAGIC and prof <= 4 and p_ok and l_ok:
                        struct.pack_into('<IBBB1xII', want, R, QM, 1, 0, 1, JOB, 1 if mask else 0)   # +6 LOGDBG pending
                        if mask:
                            struct.pack_into('<IIII', want, R + 16, BUF, 0x0305 | STRIDE << 16, W_ | H_ << 16, 0)
                            want[R + 32:R + 72] = samples()
                    n += 1
                    if not (ok1 and ok0 and k1 == k0 and j1 == j0 and p1 == bytes(want)):
                        fails.append(f'S e{e} s{s} t{t} mask{mask} ext{ext} P{p_ok} L{l_ok}: ok={ok1},{ok0} regs={k1 == k0} '
                                     f'job={j1 == j0} pool diff={[i for i in range(len(p1)) if p1[i] != want[i]][:6]}')
    res['S'] = (n, fails)
    n, fails = 0, []
    tb = HV.ftt({0: (1, 4, 1)})
    for case in ('recorded', 'other job', 'no record', 'no 0x1060', 'no L'):
        j = job(case != 'no 0x1060')
        pb, lb = heap(True, case != 'no L')
        if case in ('recorded', 'other job', 'no 0x1060', 'no L'):
            struct.pack_into('<IBB2xI', lb, BLD.BP_R_OFF, QM, 1, 0, JOB if case != 'other job' else JOB + 0x100)
        ok1, k1, s1, j1, p1 = run_cb(img, tb, j, pb, lb)
        ok0, k0, s0, j0, p0 = run_cb(base, tb, j, pb, lb)
        want = bytearray(p0)
        if case in ('recorded', 'no 0x1060'):
            want[R + 5] = 1
            want[R + 6] = 1                                 # LOGDBG pending
            if case == 'recorded':
                want[R + 72:R + 112] = samples()
        # (sp) after the replayed frame is call scratch (stock calls overwrite it too): compared from sp+4
        n += 1
        if not (ok1 and ok0 and k1 == k0 and j1 == j0 and p1 == bytes(want) and s1[0x1800 - 16:] == s0[0x1800 - 16:]):
            fails.append(f'C {case}: ok={ok1},{ok0} regs={k1},{k0} job={j1 == j0} stack={s1[0x1800-16:] == s0[0x1800-16:]} '
                         f'pool diff={[i for i in range(len(p1)) if p1[i] != want[i]][:6]}')
    res['C'] = (n, fails)
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
