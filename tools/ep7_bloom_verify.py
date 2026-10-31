#!/usr/bin/env python3
"""Emulator verification of a BUILT COLOR-bloom package (offline; emulator only; no camera).

Works on a bloom-only spec or on a merged spec (grain + v0.1 + rec_limit + bloom). Builds the
package in memory (tools/build_package.build), decodes the patched main payload and runs native
code from the PATCHED image vs the STOCK image:

  T1 converter 0x603eab39 (art effect -> job flags), called like 0x603e615c: patched flags ==
     stock flags | 0x80 exactly when params key == 11; key/art-effect/24054 matrix; regs/stack intact.
  T2 work-list builder from 0x6035749f with the flags T1 produces: key 11 + flag 0x80 gives the stock
     Soft Focus entries (class 0: dev, pass 0x6035c9c1, pending entry 0x6035ca31/cb 0x6035cbaa; class 5:
     pending 0x6035cc1b/0x6035cd94) on BOTH images; patched == stock except the grain modifier slot
     when grain is merged. Also checks shading (flag 0x80000) then falls back to its own entry.
  T3 combiner selector 0x603b5200 on kind-3 stage 0xf005 requests (effect 0x0400..0x0403) for keys
     11 / 12 / 0x01010065 / 0x01010078: patched == stock; key 11 -> 0x0402:11, 0x0403:12.
  T4 combiner config 0x603a013b: key 11 kind-3 0x0402/0x0403 -> handler 11/12 with weights
     (W, 1024-W); every other bank byte identical to stock key 11 (Art Effect w=600) and to the stock
     Soft Focus filter (key 0x01010065) bank; other keys byte-identical to stock.
  T5 changed bytes all inside edit spans.
"""
import argparse, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
import ep7_color_probe as PR  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402

BASE = 0x60020020
SEGS = [('code', 0x60340000, 0x603c0000, 'rx'), ('conv', 0x603ea000, 0x603ec000, 'rx'),
        ('data', 0x60520000, 0x60540000, 'r'), ('gain', 0x604ec000, 0x604ed000, 'r'),
        ('tail', 0x6055e5b0, 0x6055e800, 'rx')]
CALLER, STACK = 0x18000000, 0x18010000
CTX, REQ, BANKB, LIST, ENTRIES, JOB, CAP, PST = (0x1a000000, 0x1b000000, 0x1c000000, 0x1d000000,
                                                 0x1d001000, 0x1e000000, 0x1f000000, 0x1f100000)
REGS0 = {'d2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}
SF_KEY = 0x01010065


def regions(main, extra):
    s = lambda lo, hi: main[lo - BASE:hi - BASE]
    return ([Region(n, lo, s(lo, hi), p) for n, lo, hi, p in SEGS] +
            [Region('ramctr', 0xa27393f8, struct.pack('<I', 0x1234), 'rw', True)] + extra)


def stack(words=None):
    b = bytearray(0x2000)
    for off, v in (words or {}).items():
        struct.pack_into('<I', b, 0x1800 + off, v)
    return Region('stack', STACK, bytes(b), 'rw', True)


def mem(r):
    return {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}


def regs_ok(r, stop):
    rr = r['registers']
    return (not r['fault'] and rr['pc'] == stop and rr['sp'] == STACK + 0x1800 and
            all(rr[k] == v for k, v in REGS0.items()))


def key_bytes(key):
    return bytes([key >> 24 & 0xff, key >> 16 & 0xff]) + struct.pack('<H', key & 0xffff)


def t1_converter(stock, patched):
    ok, rows, flags_out = True, [], {}
    for key in (0, 5, 11, 12, SF_KEY, 0x01010078, 0x000b0000):
        for art in (0, 1, 5, 9):
            for f24054 in (0, 1):
                params = bytearray(64)
                params[8:12] = key_bytes(key)
                struct.pack_into('<I', params, 12, 0x00080000)          # COLOR jobs carry 0x80000 (shading)
                cap = bytearray(24800)
                cap[24785], cap[24054] = art, f24054
                pst = bytearray(64)
                struct.pack_into('<I', pst, 28, CAP)
                out = []
                for main in (stock, patched):
                    r = execute(regions(main, [stack(), PR.caller(0x603eab39, 0x30, 20),
                                               Region('params', PST + 0x1000, bytes(params), 'rw', True),
                                               Region('cap', CAP, bytes(cap), 'rw', True),
                                               Region('pst', PST, bytes(pst), 'r')]),
                                {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': PST, 'a1': PST + 0x1000 + 12, **REGS0},
                                CALLER + 7, limit=5000)
                    m = mem(r)
                    out.append((regs_ok(r, CALLER + 7), struct.unpack_from('<I', m['params'], 12)[0], m['params'], m['cap']))
                (sg, sf, sp_, sc), (pg, pf, pp, pc) = out
                want = sf | (0x80 if key == 11 else 0)
                good = sg and pg and pf == want and sp_[:12] == pp[:12] and sp_[16:] == pp[16:] and sc == pc
                ok &= good
                flags_out[(key, art, f24054)] = pf
                if not good or pf != sf:
                    rows.append(dict(key=hex(key), art=art, f24054=f24054, stock=hex(sf), patched=hex(pf), ok=good))
    return ok, rows, flags_out


def t2_worklist(stock, patched, flags, grain_mod):
    res, ok = [], True
    stop_after_sf, stop_after_shade = 0x603579c8, 0x60357b29
    for key, cls, fl, stop in ((11, 0, flags, stop_after_sf), (11, 5, flags, stop_after_sf),
                               (11, 0, flags | 0x80000, stop_after_shade), (11, 0, 0x80000, stop_after_shade),
                               (5, 0, flags & ~0x80, stop_after_sf)):
        lst = bytearray(32)
        lst[4] = 1
        struct.pack_into('<I', lst, 16, ENTRIES)
        job = bytearray(11400)
        struct.pack_into('<I', job, 16, fl)
        job[11341] = cls
        out = []
        for main in (stock, patched):
            r = execute(regions(main, [stack({4: JOB}), Region('list', LIST, bytes(lst), 'rw', True),
                                       Region('entries', ENTRIES, bytes(12 * 16), 'rw', True),
                                       Region('job', JOB, bytes(job), 'rw', True)]),
                        {'pc': 0x6035749f, 'sp': STACK + 0x1800, 'd2': key, 'd3': 0x3333, 'a2': JOB + 4, 'a3': LIST},
                        stop, limit=8000)
            rr, m = r['registers'], mem(r)
            good = not r['fault'] and rr['pc'] == stop and rr['sp'] == STACK + 0x1800 and rr['a2'] == JOB + 4 and rr['a3'] == LIST
            ents = [struct.unpack_from('<II', m['entries'], 12 * i) for i in range(struct.unpack_from('<H', m['list'], 0)[0])]
            out.append(dict(ok=good, n=len(ents), entries=[(hex(a), hex(b)) for a, b in ents],
                            pending=tuple(hex(x) for x in struct.unpack_from('<II', m['list'], 8)), attach=m['list'][7],
                            raw=(m['list'], m['entries'])))
        s, p = out
        if fl & 0x80 and key == 11:
            exp = (['0x60356d7b', '0x6035c9c1'], ('0x6035ca31', '0x6035cbaa')) if cls == 0 else \
                  (['0x60356d7b'], ('0x6035cc1b', '0x6035cd94'))
            if fl & 0x80000 and stop == stop_after_shade:     # shading cannot attach to the kind-3 blend entry -> own fallback entry
                exp = (exp[0] + ['0x6035ca31'], ('0x6035b517', '0x6035b529'))
            sf_ok = all([e[0] for e in x['entries']] == exp[0] and x['pending'] == exp[1] for x in (s, p))
        else:
            sf_ok = True
        if grain_mod:
            # grain merged: the dev entry's modifier slot (entries[0]+4) holds grain_mod. With bloom the
            # entry sequence must equal stock. Without bloom, stock shading attaches to the dev entry while
            # the grain build sends it to its fallback entry (docs/GRAIN_PORT.md risk 3) -> not compared here.
            mod0 = struct.unpack_from('<I', p['raw'][1], 4)[0]
            if fl & 0x80 and key == 11:
                same = (mod0 == grain_mod and [e[0] for e in p['entries']] == [e[0] for e in s['entries']]
                        and p['pending'] == s['pending'] and p['entries'][1:] == s['entries'][1:])
            else:
                same = key != 11 and s['raw'] == p['raw'] or key == 11 and mod0 == grain_mod
        else:
            same = s['raw'] == p['raw']
        good = s['ok'] and p['ok'] and sf_ok and same
        ok &= good
        for x in (s, p):
            x.pop('raw')
        res.append(dict(key=key, cls=cls, flags=hex(fl), soft_focus_entries_ok=sf_ok, patched_matches_stock=same,
                        stock=s, patched=p, ok=good))
    return ok, res


def request(kind, stage, effect, level=0, key=11):
    r = bytearray(1884)
    r[8:12] = key_bytes(key)
    struct.pack_into('<H', r, 12, stage)
    r[16] = kind
    struct.pack_into('<H', r, 1838 if kind == 0 else 656, effect)
    struct.pack_into('<h', r, 1832 if kind == 0 else 708, level)
    return r


def t3_selector(stock, patched):
    ok, rows = True, []
    want = {0x0400: 0, 0x0401: 0, 0x0402: 11, 0x0403: 12}
    for key in (11, 12, SF_KEY, 0x01010078):
        for eff in want:
            ctx = bytearray(128)
            struct.pack_into('<I', ctx, 4, REQ)
            struct.pack_into('<I', ctx, 52, key)
            out = []
            for main in (stock, patched):
                r = execute(regions(main, [stack(), PR.caller(0x603b5200, 0xa0, 12), Region('ctx', CTX, bytes(ctx), 'rw', True),
                                           Region('req', REQ, bytes(request(3, 0xf005, eff, key=key)), 'rw', True)]),
                            {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CTX, **REGS0}, CALLER + 7, limit=5000)
                out.append((regs_ok(r, CALLER + 7), r['registers']['d0']))
            (sg, s0), (pg, p0) = out
            good = sg and pg and s0 == p0 and (key != 11 or p0 == want[eff])
            ok &= good
            rows.append(dict(key=hex(key), effect=hex(eff), stock=s0, patched=p0, ok=good))
    return ok, rows


def bank_run(main, key, eff, level=0):
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, REQ)
    struct.pack_into('<I', ctx, 8, BANKB)
    struct.pack_into('<I', ctx, 52, key)
    r = execute(regions(main, [stack(), PR.caller(0x603a013b, 0xf0, 20), Region('ctx', CTX, bytes(ctx), 'rw', True),
                               Region('req', REQ, bytes(request(3, 0xf005, eff, level, key)), 'rw', True),
                               Region('bank', BANKB, bytes(7364 + 256), 'rw', True)]),
                {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CTX, **REGS0}, CALLER + 7, limit=20000)
    return regs_ok(r, CALLER + 7), mem(r)['bank'][7364:7364 + 184]


WEIGHT_OFFS = (92, 96, 136, 140)


def weights(bank):
    return {o: struct.unpack_from('<I', bank, o)[0] for o in WEIGHT_OFFS}


def mask_w(bank):
    b = bytearray(bank)
    for o in WEIGHT_OFFS:
        b[o:o + 4] = bytes(4)
    return bytes(b)


def t4_combiner(stock, patched, W):
    ok, rows = True, []
    pair = lambda v: v | v << 16
    for eff, comb in ((0x0402, 11), (0x0403, 12)):
        sg, sb = bank_run(stock, 11, eff)
        pg, pb = bank_run(patched, 11, eff)
        rg, rb = bank_run(stock, SF_KEY, eff, 0)            # stock Soft Focus filter, level 0 (w=600)
        a, b = (W, 1024 - W) if comb == 11 else (1024 - W, W)
        exp = {92: pair(a), 96: a, 136: pair(b), 140: b}
        good = sg and pg and rg and weights(pb) == exp and mask_w(pb) == mask_w(sb) == mask_w(rb) and sb == rb
        ok &= good
        rows.append(dict(effect=hex(eff), combiner=comb, mode_word=hex(struct.unpack_from('<I', pb, 4)[0]),
                         stock_key11_w=weights(sb), patched_key11_w=weights(pb), expected=exp,
                         rest_of_bank_identical=mask_w(pb) == mask_w(sb), stock_key11_equals_stock_softfocus_L0=sb == rb,
                         ok=good))
    for key, eff, lv in ((SF_KEY, 0x0402, 0), (SF_KEY, 0x0402, 5), (SF_KEY, 0x0402, -5), (0x01010078, 0x0402, 0),
                         (12, 0x0402, 0), (11, 0x0c00, 0), (11, 0x0400, 0)):
        sg, sb = bank_run(stock, key, eff, lv)
        pg, pb = bank_run(patched, key, eff, lv)
        good = sg and pg and (sb == pb) == (not (key == 11 and eff in (0x0402, 0x0403)))
        ok &= good
        rows.append(dict(key=hex(key), effect=hex(eff), level=lv, identical=sb == pb, w=weights(pb), ok=good))
    return ok, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    W = spec['bloom']['weight']
    grain_mod = int(spec['symbols']['grain_mod'], 16) if 'symbols' in spec and 'grain_mod' in spec['symbols'] else 0
    import numpy as np
    idx = np.nonzero(np.frombuffer(stock, np.uint8) != np.frombuffer(patched, np.uint8))[0] + BASE
    spans = [(int(e['addr'], 16), int(e['addr'], 16) + len(bytes.fromhex(e['new']))) for e in spec['edits']]
    in_spans = bool(all(any(s <= x < t for s, t in spans) for x in idx))
    results = {}
    ok1, rows1, flags = t1_converter(stock, patched)
    results['T1 converter flag'] = dict(passed=ok1, rows=rows1)
    color_flags = flags[(11, 0, 0)]
    for name, fn in (('T2 work list', lambda: t2_worklist(stock, patched, color_flags, grain_mod)),
                     ('T3 selector', lambda: t3_selector(stock, patched)),
                     ('T4 combiner config', lambda: t4_combiner(stock, patched, W))):
        ok, rows = fn()
        results[name] = dict(passed=ok, rows=rows)
    results['T5 spans'] = dict(passed=in_spans, changed=len(idx), spans=len(spans))
    for k, v in results.items():
        print(f"{'PASS' if v['passed'] else 'FAIL'} {k}")
        if not v['passed'] or k.startswith(('T1', 'T4')):
            for row in v.get('rows', [])[:12]:
                print('     ', row)
    print(f"     T5: {len(idx)} changed bytes, {len(spans)} edit spans; package {info}; grain merged: {bool(grain_mod)}")
    if a.json:
        a.json.write_text(json.dumps(dict(scope='emulator only; synthetic fixtures; no ISP pixels; no camera',
                                          weight=W, package=info, results=results), indent=1, default=str))
    sys.exit(0 if all(v['passed'] for v in results.values()) else 1)


if __name__ == '__main__':
    main()
