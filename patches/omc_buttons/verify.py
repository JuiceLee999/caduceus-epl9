#!/usr/bin/env python3
"""Checks for omc_buttons o1 on v0.28 (real firmware code in the emulator, from the built package). Offline.

  .venv/bin/python -I patches/omc_buttons/verify.py releases/v0.28/edits.json generated/omc/t1/edits.json [generated/omc/t1/pkg]

  V  native validator (hash init / count / value): sids 47/48/49 and 51/53 give the new lists, stock gave the stock
     lists; ~40 neighbouring and related sids (incl. v0.28's sid 270) identical to v0.28
  N  native dial stepping walks each new list like stock (same wrap)
  A  native function -> action for every listed code equals stock, non-zero except Off; key kinds unchanged
  Y  alignment: lists on 2-byte, record ptr fields on 4-byte, size fields on 2-byte boundaries; lists fit their room
  L  version label "0.28o1"
  P  anti-brick: package reparses, decoded == stock + edits, restore == stock, only our sites differ from v0.28
"""
import importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import ep7_buttons_verify as V  # noqa: E402  (also puts patches/buttons and the emulator on sys.path)
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402

BT = V.BT
B = BT.B


def image(spec):
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    return [b for b in oc.parse(pkg) if b.kind == 0x100][0].payload, pkg, rst, info


def others_list(stock):
    near = [struct.unpack('<H', V.sl(stock, BT.VT + 20 * i, BT.VT + 20 * i + 2))[0] for i in range(BT.VT_N)]
    targets = set(BT.FULL_RECS) | set(BT.DPAD_RECS)
    idx = [near.index(s) for s in targets]
    return sorted({near[j] for k in idx for j in range(max(0, k - 4), min(BT.VT_N, k + 5))} - targets
                  | {571, 572, 573, 1266, 54, 55, 56, 1269, 1271, 1246, 1255, 1257, 158, 437, 438, 297, 270, 1, 2})


def t_validator(S, O, P, b, others):
    ok, rows = V.check_validator(S, P, b, [])
    bad = [] if ok else [r for r in rows if not r['passed']]
    for sid in others:
        try:
            same = O.listed(sid) == P.listed(sid)
        except AssertionError:      # list outside the mapped window (v0.28 moved sid 270's list to sec 1): compare bytes
            recs = [BT.VT + 20 * i for i in range(BT.VT_N) if struct.unpack('<H', V.sl(O.m, BT.VT + 20 * i, BT.VT + 20 * i + 2))[0] == sid]
            same = bool(recs)
            for ra in recs:
                r = BT.record(O.m, ra)
                same &= V.sl(O.m, ra, ra + 20) == V.sl(P.m, ra, ra + 20) and \
                    V.sl(O.m, r['ptr'], r['ptr'] + r['size']) == V.sl(P.m, r['ptr'], r['ptr'] + r['size'])
        if not same:
            bad.append(('vs v0.28', sid))
    return bad, len(rows) + len(others)


def t_align(b):
    bad = []
    for at, lst, room in ((int(b['full_at'], 16), b['full'], BT.FULL_ROOM), (int(b['dpad_at'], 16), b['dpad'], BT.DPAD_ROOM)):
        if at % 2 or 2 * len(lst) > room:
            bad.append(('list', hex(at)))
    for ra, _ in list(BT.FULL_RECS.values()) + list(BT.DPAD_RECS.values()):
        if (ra - BT.VT) % BT.VT_SZ or (ra + 4) % 4 or (ra + 12) % 2:
            bad.append(('record', hex(ra)))
    return bad, 2 + len(BT.FULL_RECS) + len(BT.DPAD_RECS)


def t_label(spec, new):
    fv = spec['fw_version']
    want = ''.join(f'{ord(c):02x}00' for c in fv['value']) + '0000'
    at = int(fv['code_at'], 16)
    blob = V.sl(new, at, at + fv['code_len']).hex()
    return ([] if fv['value'] == spec['omc_buttons']['version'] == '0.28o1' and want in blob else ['label']), 1


def t_pkg(spec, new, pkg, rst, info, disk, old):
    sb = {b.kind: b for b in oc.parse(BP.STOCK.read_bytes())}
    good = True
    for b in oc.parse(pkg):
        exp = bytearray(sb[b.kind].payload)
        for e in spec['edits']:
            if int(e['kind'], 16) == b.kind:
                o = BP.resolve(b.kind, e['addr']); nb = bytes.fromhex(e['new']); exp[o:o + len(nb)] = nb
        good &= bytes(exp) == b.payload
    for b in oc.parse(rst):
        good &= b.payload == sb[b.kind].payload
    ours = [(int(e['addr'], 16), len(e['new']) // 2) for e in spec['edits'] if e.get('source') in ('patches/omc_buttons', 'patches/fw_version')]
    diff = [B + i for i in range(len(old)) if old[i] != new[i]]
    stray = [hex(a) for a in diff if not any(s <= a < s + k for s, k in ours)]
    good &= not stray
    if disk:
        good &= (disk / 'patched.pkg.bin').read_bytes() == pkg and (disk / 'restore-stock.pkg.bin').read_bytes() == rst
    return good, f'{info["edits"]} edits, {info["changed_payload_bytes"]} B; {len(diff)} B differ from v0.28; stray {stray[:6]}'


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    old, *_ = image(base_s)
    new, pkg, rst, info = image(new_s)
    stock = [b for b in oc.parse(rst) if b.kind == 0x100][0].payload
    b = new_s['buttons']
    S, O, P = V.Img(stock), V.Img(old), V.Img(new)
    others = others_list(stock)
    ok = True
    for name, fn in (('V validator', lambda: t_validator(S, O, P, b, others)),
                     ('N stepping', lambda: (lambda r: ([x for x in r[1] if not x['passed']], len(r[1])))(V.check_next(S, P, b))),
                     ('A dispatch', lambda: (lambda r: ([x for x in r[1] if not x['passed']], len(r[1])))(V.check_dispatch(S, P, b))),
                     ('Y alignment', lambda: t_align(b)), ('L label', lambda: t_label(new_s, new))):
        bad, n = fn(); ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:4] if bad else '', flush=True)
    good, txt = t_pkg(new_s, new, pkg, rst, info, disk, old); ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: {txt}")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
