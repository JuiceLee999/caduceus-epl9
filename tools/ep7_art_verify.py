#!/usr/bin/env python3
"""Emulator check of COLOR Art Effect (patches/bloom --art, slot +46; docs/HALATION_RED.md section 11). Offline.

  .venv/bin/python -I tools/ep7_art_verify.py SPEC.json --base OLD_SPEC.json

  F  still converter 0x603eab39 (native, both images): COLOR (mode 11) profile 1..4, key 11, art 1..5 -> flags ==
     OLD | the stock converter's own update for the matching stock Art Effect id (run on stock with capture+24785 = id);
     art 0 / 6 / 255, erased table, MONO profile, mode 12, other keys, capture-record and params bytes -> == OLD.
     Combined with bloom / clarity slots: the bloom flag as before.
  L  work-list builder 0x6035749f -> ret 0x60357c92 (native, full run): for each art flag, the entries/pending a
     key-11 COLOR job gets == OLD with the same flags, and the entries the flag adds on key 11 == the entries it
     adds on an Art-filter key (0x01010064 Pop Art) in stock (the ART-mode path), classes 0 and 5.
  S  kind-3 selector 0x603b5200 for effects 0x0000..0x0fff (stage 0xf005): key 11 == Pop Art key for every effect
     the Art Effects' passes could use, i.e. whatever the passes are, they get the same combiner on COLOR as in ART mode.
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


HV = _load('ep7_halation_verify_a', ROOT / 'tools/ep7_halation_verify.py')
BV, EV, CV = HV.BV, HV.EV, HV.CV
Region = CV.Region
ART_KEY = 0x01010064
STOCK_ID = {1: 5, 2: 2, 3: 6, 4: 4, 5: 3}       # our art value -> stock Art Effect id
END = 0x60357c92


def table(slots, art):
    t = bytearray(BV.fixture_table({k: v for k, v in slots.items()}))
    for k, a in art.items():
        t[64 * k + 46] = a
    return bytes(t)


def wl(main, key, cls, flags):
    lst = bytearray(32)
    lst[4] = 1
    struct.pack_into('<I', lst, 16, BV.ENTRIES)
    job = BV.job_bytes(flags, cls, (1, 11, BV.MAGIC) if key == 11 else None, key)
    r = BV.execute(BV.regions(main, None, [BV.stack({4: BV.JOB, 8: BV.JOB + 11308}), Region('list', BV.LIST, bytes(lst), 'rw', True),
                                          Region('entries', BV.ENTRIES, bytes(12 * 16), 'rw', True),
                                          Region('job', BV.JOB, bytes(job), 'rw', True)]),
                   {'pc': 0x6035749f, 'sp': BV.STACK + 0x1800, 'd2': key, 'd3': 0x3333, 'a2': BV.JOB + 4, 'a3': BV.LIST},
                   END, limit=200000)
    m = BV.mem(r)
    n = struct.unpack_from('<H', m['list'], 0)[0]
    ents = [struct.unpack_from('<III', m['entries'], 12 * i) for i in range(min(n, 16))]
    return (not r['fault'] and r['registers']['pc'] == END), ents, struct.unpack_from('<II', m['list'], 8), m['job']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec')
    ap.add_argument('--base', required=True)
    a = ap.parse_args()
    stock, img = EV.images(json.loads(Path(a.spec).read_text()))
    _, base = EV.images(json.loads(Path(a.base).read_text()))
    res = {}
    # F
    n, fails = 0, []
    for art in (0, 1, 2, 3, 4, 5, 6, 255):
        for eff in ((0, 0), (1, 3), (3, 2), (2, 4)):
            for prof in (1, 4, 5):
                for mode in (11, 12):
                    for key in (11, ART_KEY):
                        for erased in (False, True):
                            slots = {i: eff for i in range(8)}
                            tb = b'\xff' * 512 if erased else table(slots, {i: art for i in range(8)})
                            ok1, f1, p1, c1 = BV.conv_run(img, tb, key, mode, prof)
                            ok0, f0, p0, c0 = BV.conv_run(base, tb, key, mode, prof)
                            want = f0
                            if 1 <= art <= 5 and not erased and mode == 11 and prof <= 4 and key == 11:
                                oks, fs, _, _ = BV.conv_run(stock, tb, key, mode, prof, art=STOCK_ID[art])
                                oks0, fs0, _, _ = BV.conv_run(stock, tb, key, mode, prof, art=0)
                                want = f0 | (fs & ~fs0)
                                want &= ~(fs0 & ~fs)            # Blur clears 0x200 (never set here)
                                if not (oks and oks0):
                                    fails.append(f'F stock run art{art}')
                            n += 1
                            if not (ok1 and ok0 and c1 and c0 and f1 == want and p1[:12] == p0[:12] and p1[16:] == p0[16:]):
                                fails.append(f'F art{art} eff{eff} prof{prof} mode{mode} key{key:#x} erased{erased}: '
                                             f'{f1:#x} want {want:#x} (old {f0:#x})')
    res['F'] = (n, fails)
    # L
    n, fails = 0, []
    for art in range(1, 6):
        bit = {1: 0x40, 2: 0x400, 3: 0x100, 4: 0x2000, 5: 0x8000}[art]
        for cls in (0, 5):
            for extra in (0, 0x80):
                fl = 0x80000 | extra
                o1, e1, p1, j1 = wl(img, 11, cls, fl | bit)
                o0, e0, p0, j0 = wl(base, 11, cls, fl | bit)
                ok_c, c0, cp0, _ = wl(base, 11, cls, fl)
                oa, a1, ap1, _ = wl(stock, ART_KEY, cls, fl | bit)
                ob, a0, ap0, _ = wl(stock, ART_KEY, cls, fl)
                add11 = [e[0] for e in e1 if e not in c0] + [x for x in p1 if x not in cp0]
                addA = [e[0] for e in a1 if e not in a0] + [x for x in ap1 if x not in ap0]
                n += 1
                if not (o1 and o0 and ok_c and oa and ob and e1 == e0 and p1 == p0 and j1 == j0 and add11 == addA):
                    fails.append(f'L art{art} cls{cls} extra{extra:#x}: ok={o1},{o0},{ok_c},{oa},{ob} same_as_old={e1 == e0 and p1 == p0} '
                                 f'added key11={[hex(x) for x in add11]} artkey={[hex(x) for x in addA]}')
    res['L'] = (n, fails)
    # V: LV job classes 5..8 (lv_art previews 2 Pin Hole / 3 Blur / 4 White Edge / 5 Frame; 1 Star Light not)
    n, fails = 0, []
    for art, bit in ((1, 0x40), (2, 0x400), (3, 0x100), (4, 0x2000), (5, 0x8000)):
        for cls in (5, 6, 7, 8):
            o1, e1, p1, _ = wl(img, 11, cls, 0x80000 | bit)
            o0, e0, p0, _ = wl(img, 11, cls, 0x80000)
            oa, a1, ap1, _ = wl(stock, ART_KEY, cls, 0x80000 | bit)
            ob, a0, ap0, _ = wl(stock, ART_KEY, cls, 0x80000)
            add11 = [e[0] for e in e1 if e not in e0] + [x for x in p1 if x not in p0]
            addA = [e[0] for e in a1 if e not in a0] + [x for x in ap1 if x not in ap0]
            n += 1
            lv = art != 1
            if not (o1 and o0 and oa and ob and add11 == addA and (bool(add11) if lv else (cls == 8 or not add11))):
                fails.append(f'V art{art} cls{cls}: key11 {[hex(x) for x in add11]} artkey {[hex(x) for x in addA]}')
    res['V'] = (n, fails)
    # S
    n, fails, diff = 0, [], []
    for eff in range(0, 0x1000):
        out = []
        for key in (11, ART_KEY):
            ctx = bytearray(128)
            struct.pack_into('<I', ctx, 4, BV.CTX + 0x100)
            struct.pack_into('<I', ctx, 52, key)
            ctx += bytes(0x100 - len(ctx)) + BV.request(3, 0xf005, eff, key=key)
            r = BV.execute(BV.regions(img, None, [BV.stack(), BV.PR.caller(0x603b5200, 0xa0, 12), Region('ctx', BV.CTX, bytes(ctx), 'rw', True)]),
                           {'pc': BV.CALLER, 'sp': BV.STACK + 0x1800, 'a0': BV.CTX, **BV.REGS0}, BV.CALLER + 7, limit=5000)
            out.append((BV.regs_ok(r, BV.CALLER + 7), r['registers']['d0']))
        n += 1
        if not (out[0][0] and out[1][0]):
            fails.append(f'S {eff:#x}: run failed')
        elif out[0][1] != out[1][1]:
            diff.append((hex(eff), out[0][1], out[1][1]))
    res['S'] = (n, fails)
    for k, (n, f) in res.items():
        print(f'{k}: {n - len(f)}/{n} ' + ('PASS' if not f else 'FAIL'))
        for x in f[:10]:
            print('   ', x)
    print('S key-11 vs Pop Art differences (kind 3):', diff[:40], len(diff))
    bad = sum(len(f) for _, f in res.values())
    print('ALL PASS' if not bad else 'FAILURES')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
