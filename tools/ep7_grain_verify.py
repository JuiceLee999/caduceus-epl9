#!/usr/bin/env python3
"""Emulator verification of a BUILT COLOR-grain package (offline; emulator only; no camera).

Builds the package in memory from an edits.json (tools/build_package.build), decodes the
patched main payload and runs native code from the PATCHED image vs the STOCK image:

  T1 combiner selector 0x603b5200 over a key/kind/stage/effect matrix: identical result
     except key 11 + kind 0 + stage 0x0902 -> 32; stack and callee-saved regs intact.
  T2 work-list builder from the hook site 0x6035749f (real 0x6035739e/0x603573d3 code):
     same continuation PC and identical list/entries, except key 11 gets our modifier on
     the development entry 0x60356d7b; stack/regs intact.
  T3 request modifier vs stock 0x60359e5e (called with CALLS like 0x60356d72): kind 0 ->
     stage 0x0902 (+ level byte), kind 3 untouched, no other request byte changes.
  T4 end to end: combiner config 0x603a013b on a COLOR request after the modifier:
     patched -> handler 32 programs gain table[level-1] into bank+136; stock -> default.
  T5 changed bytes all inside edit spans; if the spec carries v0.1 native_rows, the v0.1
     H/L selector check (tools/ep7_verify_package.selector_run) is re-run on the same image.
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
CODE_LO, CODE_HI = 0x60340000, 0x603c0000      # job module, combiner code, selector
DATA_LO, DATA_HI = 0x60520000, 0x60540000      # dispatch tables
GAIN_LO, GAIN_HI = 0x604ec000, 0x604ed000      # grain gain tables
TAIL_LO, TAIL_HI = 0x6055e5b0, 0x6055e800
RAMCTR = 0xa27393f8
CALLER, STACK = 0x18000000, 0x18010000
CTX, REQ, BANKB, LIST, ENTRIES, JOBP = 0x1a000000, 0x1b000000, 0x1c000000, 0x1d000000, 0x1d001000, 0x1e000000
SEL, CFG, MOD_STOCK = 0x603b5200, 0x603a013b, 0x60359e5e
REGS0 = {'d2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}


def code_regions(main):
    s = lambda lo, hi: main[lo - BASE:hi - BASE]
    return [Region('code', CODE_LO, s(CODE_LO, CODE_HI), 'rx'), Region('data', DATA_LO, s(DATA_LO, DATA_HI), 'r'),
            Region('gain', GAIN_LO, s(GAIN_LO, GAIN_HI), 'r'), Region('tail', TAIL_LO, s(TAIL_LO, TAIL_HI), 'rx'),
            Region('stack', STACK, bytes(0x2000), 'rw', True), Region('ramctr', RAMCTR, struct.pack('<I', 0x1234), 'rw', True)]


def request(kind, stage, effect=0, level=0):
    r = bytearray(1884)
    r[8:12] = bytes([0, 0, 11, 0])
    struct.pack_into('<H', r, 12, stage)
    r[16] = kind
    r[1828] = level
    struct.pack_into('<H', r, 1838, effect)
    struct.pack_into('<H', r, 656, effect)
    return r


def caller_calls(target):   # 'calls d32' then nop: what 0x60356d72 does via calls (a2)
    return Region('caller', CALLER, b'\xfc\xff' + struct.pack('<i', target - CALLER) + b'\xcb', 'rx')


def regs_ok(r, stop):
    rr = r['registers']
    return (not r['fault'] and rr['pc'] == stop and rr['sp'] == STACK + 0x1800 and
            all(rr[k] == v for k, v in REGS0.items()))


def t1_selector(stock, patched):
    rows, ok = [], True
    for key in (0, 5, 11, 12, 0x01010078, 0x0101007c):
        for kind in (0, 3):
            for stage in (0, 0x0901, 0x0902, 0xf00f):
                for effect in (0, 0x0400, 0x0900, 0x0c00):
                    ctx = bytearray(128)
                    struct.pack_into('<I', ctx, 4, REQ)
                    struct.pack_into('<I', ctx, 52, key)
                    out = []
                    for main in (stock, patched):
                        regions = code_regions(main) + [PR.caller(SEL, 0xa0, 12),
                                   Region('ctx', CTX, bytes(ctx), 'rw', True),
                                   Region('req', REQ, bytes(request(kind, stage, effect)), 'rw', True)]
                        r = execute(regions, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CTX, **REGS0}, CALLER + 7, limit=5000)
                        mem = {m['name']: m['hex'] for m in r['memory']}
                        out.append((r['registers']['d0'], regs_ok(r, CALLER + 7), mem['ctx'], mem['req']))
                    (s0, sok, sc, sr), (p0, pok, pc, pr) = out
                    want = 32 if (key == 11 and kind == 0 and stage == 0x0902) else s0
                    good = sok and pok and p0 == want and sc == pc and sr == pr
                    ok &= good
                    if not good or want != s0:
                        rows.append(dict(key=hex(key), kind=kind, stage=hex(stage), effect=hex(effect),
                                         stock=s0, patched=p0, ok=good))
    return ok, rows


def t2_worklist(stock, patched, mod_addr):
    res, ok = [], True
    for key, stop in ((0, 0x603578bd), (5, 0x603578bd), (10, 0x603578bd), (11, 0x603578bd),
                      (12, 0x603574a6), (0x01010068, 0x603574a6)):
        lst = bytearray(32)
        lst[4] = 1
        struct.pack_into('<I', lst, 16, ENTRIES)
        out = []
        for main in (stock, patched):
            regions = code_regions(main) + [Region('list', LIST, bytes(lst), 'rw', True),
                                            Region('entries', ENTRIES, bytes(12 * 16), 'rw', True),
                                            Region('jobp', JOBP, bytes(64), 'rw', True)]
            regs = {'pc': 0x6035749f, 'sp': STACK + 0x1800, 'd2': key, 'd3': 0x3333, 'a2': JOBP, 'a3': LIST}
            r = execute(regions, regs, stop, limit=5000)
            rr = r['registers']
            mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
            good = (not r['fault'] and rr['pc'] == stop and rr['sp'] == STACK + 0x1800 and rr['d2'] == key and
                    rr['d3'] == 0x3333 and rr['a2'] == JOBP and rr['a3'] == LIST)
            out.append((good, mem['list'], mem['entries'], r['completed']))
        (sg, sl, se, _), (pg, pl, pe, n) = out
        if key == 11:
            # stock: pending entry fn 0x60356d7b at list+8, cb 0x60356cc6 at +12, flag(7)=1, entry[0].mod = 0
            exp_e = bytearray(se)
            struct.pack_into('<I', exp_e, 4, mod_addr)
            exp_l = bytearray(sl)
            exp_l[7] = 0                      # attach consumed the modifier slot
            same = pl == bytes(exp_l) and pe == bytes(exp_e)
            same &= struct.unpack_from('<II', sl, 8) == (0x60356d7b, 0x60356cc6)
        else:
            same = sl == pl and se == pe
        good = sg and pg and same
        ok &= good
        res.append(dict(key=hex(key), stop=hex(stop), stock_ok=sg, patched_ok=pg, list_as_expected=same, insns=n))
    return ok, res


def t3_modifier(stock, patched, mod_addr, level):
    res, ok = [], True
    for kind in (0, 3):
        for lv in (0, 1, 3):
            out = []
            for main, fn in ((stock, MOD_STOCK), (patched, mod_addr)):
                regions = code_regions(main) + [caller_calls(fn), Region('req', REQ, bytes(request(kind, 0, 0x0400, lv)), 'rw', True),
                                                Region('jobp', JOBP, bytes(16), 'rw', True)]
                r = execute(regions, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': JOBP, 'a1': REQ, **REGS0}, CALLER + 7, limit=1000)
                mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
                out.append((regs_ok(r, CALLER + 7), r['registers']['d0'], mem['req']))
            (sg, s0, sr), (pg, p0, pr) = out
            exp = bytearray(request(kind, 0, 0x0400, lv))
            if kind == 0:
                if level == 'mono':
                    if lv:
                        struct.pack_into('<H', exp, 12, 0x0902)
                else:
                    struct.pack_into('<H', exp, 12, 0x0902)
                    exp[1828] = level
            stock_exp = bytearray(request(kind, 0, 0x0400, lv))
            if kind == 0:
                struct.pack_into('<H', stock_exp, 12, 0x0902)
            good = sg and pg and s0 == p0 == 0 and pr == bytes(exp) and sr == bytes(stock_exp)
            diff = [i for i in range(len(pr)) if pr[i] != request(kind, 0, 0x0400, lv)[i]]
            ok &= good
            res.append(dict(kind=kind, level_in=lv, ok=good, changed_offsets=diff))
    return ok, res


def t4_combiner(stock, patched, mod_addr, level):
    res, ok = [], True
    gains = struct.unpack_from('<3H', stock, 0x604ec0d4 - BASE)
    for lv_in in (0, 2):
        out = []
        for name, main in (('stock', stock), ('patched', patched), ('stock_mono_0902', stock)):
            # request as it leaves the development callback: stock = untouched (stage 0),
            # patched = after our modifier (run natively first)
            req = request(0, 0, 0x0400, lv_in)
            if name == 'stock_mono_0902':   # reference: stock MONO (key 12) single-pass route, same level
                lv_ref = lv_in if level == 'mono' else level
                req = request(0, 0x0902, 0x0400, lv_ref)
                req[8:12] = bytes([0, 0, 12, 0])
            if name == 'patched':
                regions = code_regions(main) + [caller_calls(mod_addr), Region('req', REQ, bytes(req), 'rw', True)]
                r = execute(regions, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': JOBP, 'a1': REQ, **REGS0}, CALLER + 7, limit=1000)
                req = bytes.fromhex([m for m in r['memory'] if m['name'] == 'req'][0]['hex'])
            ctx = bytearray(128)
            struct.pack_into('<I', ctx, 4, REQ)
            struct.pack_into('<I', ctx, 8, BANKB)
            struct.pack_into('<I', ctx, 52, 12 if name == 'stock_mono_0902' else 11)
            regions = code_regions(main) + [PR.caller(CFG, 0xf0, 20), Region('ctx', CTX, bytes(ctx), 'rw', True),
                                            Region('req', REQ, bytes(req), 'rw', True),
                                            Region('bank', BANKB, bytes(7364 + 256), 'rw', True)]
            r = execute(regions, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CTX, **REGS0}, CALLER + 7, limit=20000)
            mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
            bank = mem['bank'][7364:7364 + 184]
            out.append(dict(ok=regs_ok(r, CALLER + 7), fault=r['fault'], w4=hex(struct.unpack_from('<I', bank, 4)[0]),
                            gain136=struct.unpack_from('<I', bank, 136)[0], w172=hex(struct.unpack_from('<I', bank, 172)[0]),
                            ramctr=hex(struct.unpack_from('<I', mem['ramctr'], 0)[0]), insns=r['completed'], bank=bank.hex()))
        s, p, m = out
        bank_eq_mono = p['bank'] == m['bank']
        for x in out:
            x.pop('bank')
        lv_eff = lv_in if level == 'mono' else level
        exp_gain = gains[lv_eff - 1] if lv_eff else None
        if exp_gain is None:      # mono mode with Off: patched must equal stock
            good = s['ok'] and p['ok'] and p == dict(s, insns=p['insns'])
        else:
            # handler 32: gain from table, seed = 0x80000000 | ++RAM counter; stock: default handler, counter untouched
            good = (s['ok'] and p['ok'] and bank_eq_mono and p['gain136'] == exp_gain and p['w172'] == '0x80001235' and
                    p['ramctr'] == '0x1235' and s['gain136'] != exp_gain and s['ramctr'] == '0x1234')
        ok &= good
        res.append(dict(level_in=lv_in, expected_gain=exp_gain, patched_bank_equals_stock_mono_0902=bank_eq_mono,
                        stock=s, patched=p, stock_mono_0902=m, ok=good))
    return ok, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    mod_addr, level = int(spec['symbols']['grain_mod'], 16), spec['level']
    import numpy as np
    idx = np.nonzero(np.frombuffer(stock, np.uint8) != np.frombuffer(patched, np.uint8))[0] + BASE
    spans = [(int(e['addr'], 16), int(e['addr'], 16) + len(bytes.fromhex(e['new']))) for e in spec['edits']]
    in_spans = bool(all(any(s <= x < t for s, t in spans) for x in idx))
    results = {}
    for name, fn in (('T1 selector', lambda: t1_selector(stock, patched)),
                     ('T2 work list', lambda: t2_worklist(stock, patched, mod_addr)),
                     ('T3 modifier', lambda: t3_modifier(stock, patched, mod_addr, level)),
                     ('T4 combiner config', lambda: t4_combiner(stock, patched, mod_addr, level))):
        ok, rows = fn()
        results[name] = dict(passed=ok, rows=rows)
        print(f"{'PASS' if ok else 'FAIL'} {name}")
        for row in rows:
            print('     ', row)
    results['T5 spans'] = dict(passed=in_spans, changed=len(idx))
    print(f"{'PASS' if in_spans else 'FAIL'} T5 changed bytes ({len(idx)}) all inside {len(spans)} edit spans; package {info}")
    if 'native_rows' in spec:
        import ep7_verify_package as VP
        ok_hl = True
        for sat in ([0] * 12, [3, -2, 0, 1, 0, 0, -5, 0, 2, 0, 0, 4]):
            ok_s, m_s, _ = VP.selector_run(stock, sat)
            ok_p, m_p, _ = VP.selector_run(patched, sat)
            rp = PR.records(m_p['out'])
            ok_hl &= ok_s and ok_p and all(rp[i]['hue'] == spec['native_rows'][i][0] and
                                           rp[i]['light'] == spec['native_rows'][i][1] for i in range(12))
        results['T5 v0.1 H/L on merged image'] = dict(passed=bool(ok_hl))
        print(f"{'PASS' if ok_hl else 'FAIL'} T5 v0.1 fixed-H/L selector check on the merged image")
    if a.json:
        a.json.write_text(json.dumps(dict(scope='emulator only; synthetic fixtures; no ISP pixels; no camera',
                                          package=info, results=results), indent=1, default=str))
    sys.exit(0 if all(v['passed'] for v in results.values()) else 1)


if __name__ == '__main__':
    main()
