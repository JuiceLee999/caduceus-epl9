#!/usr/bin/env python3
"""Emulator verification of the button-function widening (patches/buttons) in a BUILT package.

OFFLINE; emulator only; never contacts a camera. Builds the package in memory from SPEC with
tools/build_package.build(), decodes the patched and the restore (= stock) main payloads, and runs
firmware code from THOSE payloads (stock vs patched, same fixture):

  S  static: every changed byte inside the validator region lies in the patch's lists/records;
     all 1333 validator records are byte-identical to stock except the 5 targeted fields.
  V  native validator: hash init 0x602ba4cc, then count 0x602b9f70 and value-by-index 0x602b9fdb
     (the API behind the menu enumerators 0x60886900/0x60bda9b0 and validation) for the targeted
     sids and ~24 others. Targeted sids return exactly the new lists over [0, count); every other
     sid is identical to stock.
  N  native stepping 0x602b9cda (d1=1: previous value) over every list entry: walks the whole new
     list in order; same wrap behaviour at the first entry as stock on the stock list.
  A  native dispatcher pieces: function -> action 0x60cc885c for every code in the new lists equals
     stock and is non-zero (except Off); sid -> key-kind 0x60cc8838: 47/48/49 full (1), 51/53
     arrow pad (0, so the flag-1 filter 0x60cc8ad3 is not applied to arrows).
  M  mutations of the patched payload (list byte, size field, pointer) must make V fail.

Usage: tools/ep7_buttons_verify.py SPEC.json [--json out.json]
"""
import argparse, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'patches/buttons'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
import build as BT  # noqa: E402  (patches/buttons/build.py)
from penf_emulator import Region, execute  # noqa: E402

B = BT.B
CALLER, STACK, SP0 = 0x18000000, 0x18010000, 0x18011800
RAM_LO, RAM_HI = 0x62248000, 0x6224c000            # hash buckets 0x62248528, nodes 0x62248728
API_CODE = (0x602b9c00, 0x602ba600)
VT_DATA = (0x604c0000, 0x604d4000)
DISP_CODE, DISP_DATA = (0x60cc8838, 0x60cc8878), (0x60f389a8, 0x60f38e00)
INIT, COUNT, VALUE, NEXT = 0x602ba4cc, 0x602b9f70, 0x602b9fdb, 0x602b9cda
FUNC2ACT, SID2KIND = 0x60cc885c, 0x60cc8838


def sl(m, lo, hi):
    return m[lo - B:hi - B]


def call(target, mask, frame):
    return Region('caller', CALLER, b'\xdd' + struct.pack('<i', target - CALLER) + bytes([mask, frame]), 'rx')


def run(regions, regs, mask, frame, target):
    r = execute([call(target, mask, frame), Region('stack', STACK, bytes(0x2000), 'rw')] + regions,
                {'pc': CALLER, 'sp': SP0, 'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3, **regs},
                CALLER + 7, limit=2_000_000)
    good = not r['fault'] and r['registers']['pc'] == CALLER + 7 and r['registers']['sp'] == SP0
    return r, good


class Img:
    def __init__(self, m):
        self.m = m
        r, good = run([Region('code', API_CODE[0], sl(m, *API_CODE), 'rx'), Region('vt', VT_DATA[0], sl(m, *VT_DATA)),
                       Region('ram', RAM_LO, bytes(RAM_HI - RAM_LO), 'rw', True)], {}, 0xb0, 12, INIT)
        assert good, ('init', r['fault'])
        self.ram = bytes.fromhex(next(x for x in r['memory'] if x['name'] == 'ram')['hex'])

    def regions(self, extra=()):
        return [Region('code', API_CODE[0], sl(self.m, *API_CODE), 'rx'), Region('vt', VT_DATA[0], sl(self.m, *VT_DATA)),
                Region('ram', RAM_LO, self.ram, 'rw'), *extra]

    def count(self, sid):
        r, good = run(self.regions(), {'d0': sid}, 0x80, 8, COUNT)
        assert good, ('count', sid, r['fault'])
        return r['registers']['d0'] & 0xffff

    def value(self, sid, i):
        r, good = run(self.regions(), {'d0': sid, 'd1': i}, 0x80, 8, VALUE)
        assert good, ('value', sid, i, r['fault'])
        return r['registers']['d0'] & 0xffff

    def listed(self, sid):
        n = self.count(sid)
        return n, [self.value(sid, i) for i in range(n + 1)]

    def next(self, sid, cur):
        buf = 0x19000000
        r, good = run(self.regions([Region('cur', buf, struct.pack('<I', cur), 'rw')]), {'d0': sid, 'a0': buf}, 0xa0, 24, NEXT)
        assert good, ('next', sid, cur, r['fault'])
        return r['registers']['d0'] & 0xffff

    def disp(self, target, d0):
        r, good = run([Region('code', DISP_CODE[0], sl(self.m, *DISP_CODE), 'rx'),
                       Region('data', DISP_DATA[0], sl(self.m, *DISP_DATA))], {'d0': d0}, 0xc0, 8, target)
        assert good, ('disp', hex(target), d0, r['fault'])
        return r['registers']['d0']


def lists_from_spec(spec):
    b = spec.get('buttons') or spec.get('meta', {}).get('buttons', {}).get('buttons')
    if not b:
        sys.exit('spec lacks buttons metadata (build with patches/buttons/build.py, merge with tools/merge_specs.py)')
    return b


def check_static(spec, stock, patched, b):
    vt_lo, vt_hi = BT.VT, BT.VT + BT.VT_N * BT.VT_SZ
    allowed = set()
    for lo, n in ((int(b['full_at'], 16), 2 * len(b['full'])), (int(b['dpad_at'], 16), 2 * len(b['dpad']))):
        allowed |= set(range(lo, lo + n))
    for sid, (ra, _) in {**BT.FULL_RECS, **BT.DPAD_RECS}.items():
        allowed |= set(range(ra + 4, ra + 8)) | set(range(ra + 12, ra + 14))
    bad = [hex(B + i) for i in range(len(stock)) if stock[i] != patched[i]
           and (0x604cae00 <= B + i < vt_hi) and B + i not in allowed]
    rec_bad = []
    for i in range(BT.VT_N):
        a = BT.VT + BT.VT_SZ * i
        s, p = sl(stock, a, a + 20), sl(patched, a, a + 20)
        sid = struct.unpack('<H', s[:2])[0]
        if sid in BT.FULL_RECS or sid in BT.DPAD_RECS:
            if s[:4] != p[:4] or s[8:12] != p[8:12] or s[14:] != p[14:]:
                rec_bad.append(sid)
        elif s != p:
            rec_bad.append(sid)
    return not bad and not rec_bad, dict(stray=bad[:10], records=rec_bad)


def check_validator(S, P, b, others):
    rows, ok = [], True
    want = {**{s: b['full'] for s in b['full_sids']}, **{s: b['dpad'] for s in b['dpad_sids']}}
    stockw = {**{s: BT.STOCK_FULL for s in BT.FULL_RECS}, **{s: BT.STOCK_DPAD for s in BT.DPAD_RECS}}
    for sid in sorted(want):
        sn, sv = S.listed(sid)
        pn, pv = P.listed(sid)
        # index == count is NOT rejected by stock 0x602b9fdb (`cmp; ble`): it reads the u16 after the
        # list. Callers iterate idx < count (0x60886957, 0x60bda9c5), so only [0, count) is compared.
        good = (sn, sv[:-1]) == (len(stockw[sid]), stockw[sid]) and (pn, pv[:-1]) == (len(want[sid]), want[sid])
        ok &= good
        rows.append(dict(sid=sid, passed=good, stock=sv, patched=pv))
    for sid in others:
        s, p = S.listed(sid), P.listed(sid)
        good = s == p
        ok &= good
        if not good:
            rows.append(dict(sid=sid, passed=False, stock=s, patched=p))
    return ok, rows


def wrap_kind(img, sid, lst):
    """step from the FIRST element (0x602b9cda passes d1=1 = previous): 'wrap' (-> last), 'clamp'."""
    v = img.next(sid, lst[0])
    return 'wrap' if v == lst[-1] else 'clamp' if v == lst[0] else v


def check_next(S, P, b):
    rows, ok = [], True
    for sid, new, old in [(s, b['full'], BT.STOCK_FULL) for s in b['full_sids']] + \
                         [(s, b['dpad'], BT.STOCK_DPAD) for s in b['dpad_sids']]:
        seq_p = [P.next(sid, v) for v in new[1:]]     # 'previous' direction
        seq_s = [S.next(sid, v) for v in old[1:]]
        good = seq_p == new[:-1] and seq_s == old[:-1] and wrap_kind(S, sid, old) == wrap_kind(P, sid, new)
        ok &= good
        rows.append(dict(sid=sid, passed=good, wrap=wrap_kind(P, sid, new)))
    return ok, rows


def check_dispatch(S, P, b):
    rows, ok = [], True
    fa = BT.func_actions(P.m)
    for code in sorted(set(b['full'] + b['dpad'])):
        s, p = S.disp(FUNC2ACT, code), P.disp(FUNC2ACT, code)
        good = s == p == fa[code] and (p != 0 or code == 3200)
        ok &= good
        rows.append(dict(code=code, name=BT.NAMES.get(code, ''), action=p, passed=good))
    kinds = {sid: (S.disp(SID2KIND, sid), P.disp(SID2KIND, sid)) for sid in (47, 48, 49, 50, 51, 52, 53)}
    good = all(kinds[s] == (1, 1) for s in (47, 48, 49)) and all(kinds[s] == (0, 0) for s in (50, 51, 52, 53))
    ok &= good
    rows.append(dict(kind=kinds, passed=good))
    return ok, rows


def mutations(stock_img, patched, b, S):
    out, ok = [], True
    full_at = int(b['full_at'], 16)
    rec51 = BT.DPAD_RECS[51][0]
    muts = [('full list entry 3 -> 3201', full_at + 6, struct.pack('<H', 3201)),
            ('sid 51 size 32 -> 30', rec51 + 12, struct.pack('<H', 30)),
            ('sid 53 ptr -> stock list', BT.DPAD_RECS[53][0] + 4, struct.pack('<I', 0x604cb01e))]
    others = [50, 52, 571, 1269]
    for name, a, new in muts:
        m = bytearray(patched)
        m[a - B:a - B + len(new)] = new
        try:
            caught = not check_validator(S, Img(bytes(m)), b, others)[0]
        except AssertionError:
            caught = True
        ok &= caught
        out.append(dict(mutation=name, caught=caught))
    return ok, out


def verify(spec, json_out=None, do_mut=True):
    b = lists_from_spec(spec)
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    S, P = Img(stock), Img(patched)
    targets = set(BT.FULL_RECS) | set(BT.DPAD_RECS)
    near = []
    for i in range(BT.VT_N):
        sid = struct.unpack('<H', sl(stock, BT.VT + 20 * i, BT.VT + 20 * i + 2))[0]
        near.append(sid)
    idx = [near.index(s) for s in targets]
    others = sorted({near[j] for k in idx for j in range(max(0, k - 4), min(BT.VT_N, k + 5))} - targets
                    | {571, 572, 573, 1266, 54, 55, 56, 1269, 1271, 1246, 1255, 1257, 158, 437, 438, 297, 270, 1, 2})
    results = []
    ok, det = check_static(spec, stock, patched, b)
    results.append(dict(test='S validator region: changes only in patch lists/records', passed=ok, detail=det))
    ok, rows = check_validator(S, P, b, others)
    results.append(dict(test=f'V native count/value: 5 targeted sids == new lists, {len(others)} others == stock', passed=ok, rows=rows))
    ok, rows = check_next(S, P, b)
    results.append(dict(test='N native dial stepping walks the new lists like stock', passed=ok, rows=rows))
    ok, rows = check_dispatch(S, P, b)
    results.append(dict(test='A native function->action for every listed code; key kinds', passed=ok, rows=rows))
    if do_mut:
        ok, rows = mutations(stock, patched, b, S)
        results.append(dict(test='M mutations caught by V', passed=ok, rows=rows))
    allok = all(r['passed'] for r in results)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'} {r['test']}")
        if not r['passed']:
            print('   ', json.dumps(r.get('detail') or [x for x in r.get('rows', []) if not x.get('passed', x.get('caught', True))])[:1500])
    print(f"buttons verifier on {info.get('edits', len(spec['edits']))} edits: {'PASS' if allok else 'FAIL'}")
    if json_out:
        Path(json_out).write_text(json.dumps(dict(passed=allok, results=results), indent=1) + '\n')
    return allok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--no-mutations', action='store_true')
    a = ap.parse_args()
    sys.exit(0 if verify(json.loads(a.edits.read_text()), a.json, not a.no_mutations) else 1)


if __name__ == '__main__':
    main()
