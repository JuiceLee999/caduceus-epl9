#!/usr/bin/env python3
"""Emulator verification of a BUILT per-profile COLOR-bloom package v0.4 (offline; emulator only; no camera).

Works on a bloom-only spec (a synthetic bundle table is injected) or on a merged spec (bundles + grain +
bloom + ...; the real table is also used). Builds the package in memory (tools/build_package.build),
decodes the patched main payload and runs native code from the PATCHED image vs the STOCK image:

  T1 converter 0x603eab39 (art effect -> job flags), called like 0x603e615c: patched flags ==
     stock flags | 0x80 exactly when params key == 11, capture mode (24053) == 11, capture profile (24083)
     1..4 and that slot has effect_id 1 + strength 1..5; every other case (other keys, mode 12, profile
     0/5/255, effect 0/2, strength 0/6, erased table) == stock. Params/capture/regs/stack intact.
  T2 work-list builder from 0x6035749f with the flags T1 produces: key 11 + flag 0x80 gives the stock
     Soft Focus entries (class 0: dev, pass 0x6035c9c1, pending entry 0x6035ca31/cb 0x6035cbaa; class 5:
     pending 0x6035cc1b/0x6035cd94) on BOTH images; patched == stock (grain merged: plus grain_mod on the
     dev entry only when the job's slot enables grain). Shading (flag 0x80000) falls back to its own entry.
  T3 combiner selector 0x603b5200 on kind-3 stage 0xf005 requests (effect 0x0400..0x0403) for keys
     11 / 12 / 0x01010065 / 0x01010078: patched == stock; key 11 -> 0x0402:11, 0x0403:12.
  T4 combiner config 0x603a013b with the request embedded in a job (callback/record/parent as built by
     0x60354cb9): key 11 kind-3 0x0402/0x0403, slot strength s -> handler 11/12 with weights (W[s], 1024-W[s]);
     every other bank byte identical to stock key 11. Guard failures (wrong callback, record not in the
     list, foreign parent, no/wrong marker, mode 12, profile 0/5, effect 0/2, strength 0/6, erased table)
     -> bank byte-identical to stock key 11 (w = 600). Other keys byte-identical to stock.
  T5 changed bytes all inside edit spans.
  T7 (merged spec only) the real bundle table in the image: per COLOR slot, T1 flag and T4 weight follow it.
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
SEC1_LO, SEC1_HI = 0x60210800, 0x60211000
TABLE, SLOT, F_GRAIN, F_EFF, F_STR = 0x60210900, 64, 24, 28, 29
EXT, MAGIC, JOB_SIZE = 15488, 0xB2, 15512
CAP_MODE, CAP_PROFILE = 24053, 24083
CALLBACK, REQ_IN_JOB, RECORDS, STRIDE = 0x60355fd4, 11364, 14576, 56
CALLER, STACK = 0x18000000, 0x18010000
CTX, BANKB, LIST, ENTRIES, JOB, CAP, PST = (0x1a000000, 0x1c000000, 0x1d000000, 0x1d001000, 0x1e000000,
                                            0x1f000000, 0x1f100000)
REQ = JOB + REQ_IN_JOB
REGS0 = {'d2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}
SF_KEY = 0x01010065


def fixture_table(slots):
    """slots: {slot index: (effect_id, strength[, grain])}."""
    t = bytearray(8 * SLOT)
    for i, v in slots.items():
        t[i * SLOT + F_EFF], t[i * SLOT + F_STR] = v[0], v[1]
        if len(v) > 2:
            t[i * SLOT + F_GRAIN] = v[2]
    return bytes(t)


# COLOR1 bloom 1, COLOR2 bloom 5, COLOR3 halation 3 (not bloom), COLOR4 off; MONO slots hostile (bloom 3)
MAIN_TABLE = fixture_table({0: (1, 1), 1: (1, 5), 2: (2, 3), 4: (1, 3), 5: (1, 3), 6: (1, 3), 7: (1, 3)})


def expect_w(table, prof, weights):
    """-> W for a key-11 job of this profile (None = stock path)."""
    if not 1 <= prof <= 4:
        return None
    e = table[(prof - 1) * SLOT:(prof) * SLOT]
    return weights[e[F_STR] - 1] if e[F_EFF] == 1 and 1 <= e[F_STR] <= 5 else None


def regions(main, table, extra):
    s = lambda lo, hi: main[lo - BASE:hi - BASE]
    sec1 = bytearray(s(SEC1_LO, SEC1_HI))
    if table is not None:                      # None -> the image's own table (merged spec)
        sec1[TABLE - SEC1_LO:TABLE - SEC1_LO + len(table)] = table
    return ([Region(n, lo, s(lo, hi), p) for n, lo, hi, p in SEGS] +
            [Region('sec1', SEC1_LO, bytes(sec1), 'rx'),
             Region('ramctr', 0xa27393f8, struct.pack('<I', 0x1234), 'rw', True)] + list(extra))


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


# ------------------------------------------------------------------ T1
def conv_run(main, table, key, mode, prof, art=0, f24054=0):
    params = bytearray(64)
    params[8:12] = key_bytes(key)
    struct.pack_into('<I', params, 12, 0x00080000)          # COLOR jobs carry 0x80000 (shading)
    cap = bytearray(24800)
    cap[24785], cap[24054], cap[CAP_MODE], cap[CAP_PROFILE] = art, f24054, mode, prof
    pst = bytearray(64)
    struct.pack_into('<I', pst, 28, CAP)
    r = execute(regions(main, table, [stack(), PR.caller(0x603eab39, 0x30, 20),
                                      Region('params', PST + 0x1000, bytes(params), 'rw', True),
                                      Region('cap', CAP, bytes(cap), 'rw', True),
                                      Region('pst', PST, bytes(pst), 'r')]),
                {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': PST, 'a1': PST + 0x1000 + 12, **REGS0},
                CALLER + 7, limit=5000)
    m = mem(r)
    return regs_ok(r, CALLER + 7), struct.unpack_from('<I', m['params'], 12)[0], m['params'], m['cap'] == bytes(cap)


def t1_converter(stock, patched, weights):
    ok, rows = True, []
    cases = []
    for key in (0, 5, 11, 12, SF_KEY, 0x01010078, 0x000b0000):
        for prof in ((0, 1, 2, 3, 4, 5, 255) if key == 11 else (1, 2)):
            for mode in ((11, 12) if key == 11 else (11,)):
                for art, f in ((0, 0), (1, 0), (5, 1), (9, 0)):
                    cases.append((MAIN_TABLE, 'main', key, mode, prof, art, f))
    for label, tb in (('strength 0', fixture_table({0: (1, 0)})), ('strength 6', fixture_table({0: (1, 6)})),
                      ('effect 0 strength 3', fixture_table({0: (0, 3)})), ('erased table', b'\xff' * 512)):
        cases.append((tb, label, 11, 11, 1, 0, 0))
    for tb, label, key, mode, prof, art, f in cases:
        (sg, sf, sp_, sc), (pg, pf, pp, pc) = [conv_run(m, tb, key, mode, prof, art, f) for m in (stock, patched)]
        on = key == 11 and mode == 11 and expect_w(tb, prof, weights) is not None
        want = sf | (0x80 if on else 0)
        good = sg and pg and sc and pc and pf == want and sp_[:12] == pp[:12] and sp_[16:] == pp[16:]
        ok &= good
        if not good or pf != sf or label != 'main':
            rows.append(dict(table=label, key=hex(key), mode=mode, profile=prof, art=art, f24054=f,
                             stock=hex(sf), patched=hex(pf), bloom=on, ok=good))
    n_on = sum(1 for r in rows if r['bloom'])
    ok &= n_on > 0
    return ok, rows


# ------------------------------------------------------------------ T2
def job_bytes(flags=0, cls=0, ext=None, key=11):
    j = bytearray(JOB_SIZE)
    struct.pack_into('<I', j, 16, flags)
    struct.pack_into('<I', j, 11308, key)
    j[11341] = cls
    if ext:
        j[EXT:EXT + 3] = bytes(ext)
    return j


def t2_worklist(stock, patched, flags, grain_mod):
    res, ok = [], True
    stop_after_sf, stop_after_shade = 0x603579c8, 0x60357b29
    table = fixture_table({0: (1, 2, 2), 1: (1, 2, 0)})        # COLOR1 bloom+grain, COLOR2 bloom only
    for key, cls, fl, stop in ((11, 0, flags, stop_after_sf), (11, 5, flags, stop_after_sf),
                               (11, 0, flags | 0x80000, stop_after_shade), (11, 0, 0x80000, stop_after_shade),
                               (5, 0, flags & ~0x80, stop_after_sf)):
        for ext in (None, (1, 11, MAGIC), (2, 11, MAGIC)):
            lst = bytearray(32)
            lst[4] = 1
            struct.pack_into('<I', lst, 16, ENTRIES)
            job = job_bytes(fl, cls, ext, key)
            out = []
            for main in (stock, patched):
                r = execute(regions(main, table, [stack({4: JOB, 8: JOB + 11308}), Region('list', LIST, bytes(lst), 'rw', True),
                                                  Region('entries', ENTRIES, bytes(12 * 16), 'rw', True),
                                                  Region('job', JOB, bytes(job), 'rw', True)]),
                            {'pc': 0x6035749f, 'sp': STACK + 0x1800, 'd2': key, 'd3': 0x3333, 'a2': JOB + 4, 'a3': LIST},
                            stop, limit=8000)
                rr, m = r['registers'], mem(r)
                good = not r['fault'] and rr['pc'] == stop and rr['sp'] == STACK + 0x1800 and rr['a2'] == JOB + 4 and rr['a3'] == LIST
                ents = [struct.unpack_from('<II', m['entries'], 12 * i) for i in range(struct.unpack_from('<H', m['list'], 0)[0])]
                out.append(dict(ok=good, n=len(ents), entries=[(hex(a), hex(b)) for a, b in ents],
                                pending=tuple(hex(x) for x in struct.unpack_from('<II', m['list'], 8)),
                                raw=(m['list'], m['entries'])))
            s, p = out
            if fl & 0x80 and key == 11:
                exp = (['0x60356d7b', '0x6035c9c1'], ('0x6035ca31', '0x6035cbaa')) if cls == 0 else \
                      (['0x60356d7b'], ('0x6035cc1b', '0x6035cd94'))
                if fl & 0x80000 and stop == stop_after_shade:     # shading cannot attach to the kind-3 blend entry
                    exp = (exp[0] + ['0x6035ca31'], ('0x6035b517', '0x6035b529'))
                sf_ok = all([e[0] for e in x['entries']] == exp[0] and x['pending'] == exp[1] for x in (s, p))
            else:
                sf_ok = True
            grain_on = bool(grain_mod) and key == 11 and ext == (1, 11, MAGIC)     # only COLOR1 enables grain
            mod0 = struct.unpack_from('<I', p['raw'][1], 4)[0]
            if not grain_on:
                same = s['raw'] == p['raw']
            elif fl & 0x80:
                same = (mod0 == grain_mod and [e[0] for e in p['entries']] == [e[0] for e in s['entries']]
                        and p['pending'] == s['pending'] and p['entries'][1:] == s['entries'][1:])
            else:   # grain without bloom: stock shading would attach to the dev entry; grain takes that slot (GRAIN_PORT risk 3)
                same = mod0 == grain_mod
            good = s['ok'] and p['ok'] and sf_ok and same
            ok &= good
            for x in (s, p):
                x.pop('raw')
            res.append(dict(key=key, cls=cls, flags=hex(fl), ext=ext, grain_expected=grain_on, soft_focus_entries_ok=sf_ok,
                            patched_matches_expectation=same, stock=s, patched=p, ok=good))
    return ok, res


# ------------------------------------------------------------------ T3
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
            struct.pack_into('<I', ctx, 4, CTX + 0x100)
            struct.pack_into('<I', ctx, 52, key)
            ctx += bytes(0x100 - len(ctx)) + request(3, 0xf005, eff, key=key)
            out = []
            for main in (stock, patched):
                r = execute(regions(main, MAIN_TABLE, [stack(), PR.caller(0x603b5200, 0xa0, 12), Region('ctx', CTX, bytes(ctx), 'rw', True)]),
                            {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CTX, **REGS0}, CALLER + 7, limit=5000)
                out.append((regs_ok(r, CALLER + 7), r['registers']['d0']))
            (sg, s0), (pg, p0) = out
            good = sg and pg and s0 == p0 and (key != 11 or p0 == want[eff])
            ok &= good
            rows.append(dict(key=hex(key), effect=hex(eff), stock=s0, patched=p0, ok=good))
    return ok, rows


# ------------------------------------------------------------------ T4
def job_with_request(key, eff, level=0, ext=(1, 11, MAGIC), callback=CALLBACK, rec=3, parent=None):
    j = bytearray(JOB_SIZE)
    j[REQ_IN_JOB:REQ_IN_JOB + 1884] = request(3, 0xf005, eff, level, key)
    struct.pack_into('<I', j, REQ_IN_JOB, callback)
    struct.pack_into('<I', j, REQ_IN_JOB + 4, 0 if rec is None else JOB + RECORDS + STRIDE * rec)
    for k in range(16):
        struct.pack_into('<I', j, RECORDS + STRIDE * k, 0x0badf00d)
    if rec is not None and rec < 16:
        struct.pack_into('<I', j, RECORDS + STRIDE * rec, JOB if parent is None else parent)
    if ext:
        j[EXT:EXT + 3] = bytes(ext)
    return j


def bank_run(main, table, key, eff, level=0, **jk):
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, REQ)
    struct.pack_into('<I', ctx, 8, BANKB)
    struct.pack_into('<I', ctx, 52, key)
    job = job_with_request(key, eff, level, **jk)
    r = execute(regions(main, table, [stack(), PR.caller(0x603a013b, 0xf0, 20), Region('ctx', CTX, bytes(ctx), 'rw', True),
                                      Region('job', JOB, bytes(job), 'rw', True),
                                      Region('bank', BANKB, bytes(7364 + 256), 'rw', True)]),
                {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CTX, **REGS0}, CALLER + 7, limit=20000)
    m = mem(r)
    return regs_ok(r, CALLER + 7) and m['job'] == bytes(job), m['bank'][7364:7364 + 184]


WEIGHT_OFFS = (92, 96, 136, 140)


def weights_of(bank):
    return {o: struct.unpack_from('<I', bank, o)[0] for o in WEIGHT_OFFS}


def mask_w(bank):
    b = bytearray(bank)
    for o in WEIGHT_OFFS:
        b[o:o + 4] = bytes(4)
    return bytes(b)


def t4_combiner(stock, patched, weights):
    ok, rows = True, []
    pair = lambda v: v | v << 16
    for eff, comb in ((0x0402, 11), (0x0403, 12)):
        sg, sb = bank_run(stock, MAIN_TABLE, 11, eff)
        rg, rb = bank_run(stock, MAIN_TABLE, SF_KEY, eff, 0)        # stock Soft Focus filter level 0 (w=600)
        ok &= sg and rg and sb == rb
        for s in (1, 2, 3, 4, 5):
            for rec in (0, 3, 15):
                tb = fixture_table({1: (1, s)})
                pg, pb = bank_run(patched, tb, 11, eff, ext=(2, 11, MAGIC), rec=rec)
                W = weights[s - 1]
                a, b = (W, 1024 - W) if comb == 11 else (1024 - W, W)
                exp = {92: pair(a), 96: a, 136: pair(b), 140: b}
                good = pg and weights_of(pb) == exp and mask_w(pb) == mask_w(sb)
                ok &= good
                if rec == 3 or not good:
                    rows.append(dict(effect=hex(eff), combiner=comb, strength=s, record=rec, w=W,
                                     patched=weights_of(pb), expected=exp, rest_of_bank_identical=mask_w(pb) == mask_w(sb), ok=good))
        fails = [('wrong callback', MAIN_TABLE, dict(callback=CALLBACK + 1)),
                 ('record not in list', MAIN_TABLE, dict(rec=16)), ('request+4 = 0', MAIN_TABLE, dict(rec=None)),
                 ('foreign parent', MAIN_TABLE, dict(parent=JOB + 0x40)),
                 ('no marker', MAIN_TABLE, dict(ext=None)), ('wrong marker', MAIN_TABLE, dict(ext=(1, 11, 0xB3))),
                 ('mode 12', MAIN_TABLE, dict(ext=(1, 12, MAGIC))), ('profile 0', MAIN_TABLE, dict(ext=(0, 11, MAGIC))),
                 ('profile 5 (MONO1 bloom)', MAIN_TABLE, dict(ext=(5, 11, MAGIC))),
                 ('COLOR3 halation', MAIN_TABLE, dict(ext=(3, 11, MAGIC))), ('COLOR4 off', MAIN_TABLE, dict(ext=(4, 11, MAGIC))),
                 ('strength 0', fixture_table({0: (1, 0)}), {}), ('strength 6', fixture_table({0: (1, 6)}), {}),
                 ('erased table', b'\xff' * 512, {})]
        for label, tb, jk in fails:
            pg, pb = bank_run(patched, tb, 11, eff, **jk)
            good = pg and pb == sb
            ok &= good
            rows.append(dict(effect=hex(eff), case=label, identical_to_stock_w600=pb == sb, ok=good))
    for key, eff, lv in ((SF_KEY, 0x0402, 0), (SF_KEY, 0x0402, 5), (SF_KEY, 0x0402, -5), (0x01010078, 0x0402, 0),
                         (12, 0x0402, 0), (11, 0x0c00, 0), (11, 0x0400, 0)):
        sg, sb = bank_run(stock, MAIN_TABLE, key, eff, lv)
        pg, pb = bank_run(patched, MAIN_TABLE, key, eff, lv)
        good = sg and pg and sb == pb
        ok &= good
        rows.append(dict(key=hex(key), effect=hex(eff), level=lv, identical=sb == pb, ok=good))
    return ok, rows


# ------------------------------------------------------------------ T7
def t7_real_table(stock, patched, spec, weights):
    table = bytes.fromhex(spec['table_hex'])
    img = patched[TABLE - BASE:TABLE - BASE + len(table)]
    ok, rows = img == table, [dict(check='image table == spec table_hex', ok=img == table)]
    _, sb = bank_run(stock, None, 11, 0x0402)
    for prof in (1, 2, 3, 4):
        W = expect_w(table, prof, weights)
        (sg, sf, *_), (pg, pf, *_) = [conv_run(m, None, 11, 11, prof) for m in (stock, patched)]
        pgw, pb = bank_run(patched, None, 11, 0x0402, ext=(prof, 11, MAGIC))
        flag_ok = pf == (sf | 0x80 if W else sf)
        w_ok = (weights_of(pb)[96] == W and mask_w(pb) == mask_w(sb)) if W else pb == sb
        good = sg and pg and pgw and flag_ok and w_ok
        ok &= good
        e = table[(prof - 1) * SLOT:(prof) * SLOT]
        rows.append(dict(profile=f'COLOR{prof}', effect_id=e[F_EFF], strength=e[F_STR], bloom_flag=bool(pf & 0x80 and not sf & 0x80),
                         w=weights_of(pb)[96], ok=good))
    return ok, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    weights = spec['bloom']['strength_w']
    grain_mod = int(spec['symbols']['grain_mod'], 16) if 'symbols' in spec and 'grain_mod' in spec['symbols'] else 0
    import numpy as np
    idx = np.nonzero(np.frombuffer(stock, np.uint8) != np.frombuffer(patched, np.uint8))[0] + BASE
    spans = [(int(e['addr'], 16), int(e['addr'], 16) + len(bytes.fromhex(e['new']))) for e in spec['edits']]
    in_spans = bool(all(any(s <= x < t for s, t in spans) for x in idx))
    results = {}
    ok1, rows1 = t1_converter(stock, patched, weights)
    results['T1 converter flag (per-profile)'] = dict(passed=ok1, rows=rows1)
    _, color_flags, *_ = conv_run(patched, MAIN_TABLE, 11, 11, 1)
    tests = [('T2 work list', lambda: t2_worklist(stock, patched, color_flags, grain_mod)),
             ('T3 selector', lambda: t3_selector(stock, patched)),
             ('T4 combiner config (per-profile weight)', lambda: t4_combiner(stock, patched, weights))]
    if 'table_hex' in spec:
        tests.append(('T7 real bundle table (merged)', lambda: t7_real_table(stock, patched, spec, weights)))
    for name, fn in tests:
        ok, rows = fn()
        results[name] = dict(passed=ok, rows=rows)
    results['T5 spans'] = dict(passed=in_spans and bool(color_flags & 0x80), changed=len(idx), spans=len(spans))
    for k, v in results.items():
        print(f"{'PASS' if v['passed'] else 'FAIL'} {k} ({len(v.get('rows', []))} rows)")
        for row in v.get('rows', []):
            if not row.get('ok', True) or k.startswith('T7'):
                print('     ', row)
    print(f"     T5: {len(idx)} changed bytes, {len(spans)} edit spans; package {info}; grain merged: {bool(grain_mod)}; "
          f"W(strength 1..5) = {weights}")
    if a.json:
        a.json.write_text(json.dumps(dict(scope='emulator only; synthetic fixtures; no ISP pixels; no camera',
                                          strength_w=weights, package=info, results=results), indent=1, default=str))
    sys.exit(0 if all(v['passed'] for v in results.values()) else 1)


if __name__ == '__main__':
    main()
