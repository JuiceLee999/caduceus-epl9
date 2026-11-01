#!/usr/bin/env python3
"""Emulator check of bloom colour (test13b) and red bloom (effect_id 2; patches/bloom --halation,
docs/HALATION_RED.md section 8). Offline only.

  .venv/bin/python -I tools/ep7_halation_verify.py SPEC.json --base OLD_SPEC.json

Images are built from the edit specs (decoded main + edits), image segments mapped read-only (a store into them
faults). Fixtures and the combiner run (config 0x603a013b -> getter 0x6039fee8 -> combiner 11/12 handler -> our
halo stub at the combiner-11 tail) come from tools/ep7_clarity_verify.py / ep7_bloom_verify.py.
  F  converter 0x603eab39: effect_id 2 strength 1..5 on COLOR1-4 -> job flag 0x80 (as bloom); strength 0/6,
     MONO profile, mode 12 -> == stock
  W  combiner banks for bloom (effect 1) with tint 1..4 and red bloom (effect 2, tint 0 -> red): w = W[s] + tint,
     combiner 11 -> Y gains w / 1024-w, chroma B_c = min(k_c b / 8, 1024) (b = 1024-w), A = 1024-B per channel;
     combiner 12 -> the plain w pack (no halo); rest of the bank == stock key 11; caller's live stack == stock;
     tint 5 / 255 -> stock key-11 bank (w 600)
  D  differential vs OLD_SPEC (the release before this change): bloom 1/3/5 tint 0, clarity (tint ignored), all
     off, erased and guard-failure tables -> converter params and full banks byte-identical
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


CV = _load('ep7_clarity_verify_h', ROOT / 'tools/ep7_clarity_verify.py')
EV = _load('ep7_verify_look_editor_h', ROOT / 'tools/ep7_verify_look_editor.py')
BLD = _load('ep7_bloom_build_h', ROOT / 'patches/bloom/build.py')
BV, ft, bank_run, MAGIC = CV.BV, CV.ft, CV.bank_run, CV.MAGIC
ROWS = BLD.tint_rows(BLD.STRENGTH_W)


def ftt(slots):
    """slots: {slot: (effect, strength, tint)}"""
    t = bytearray(ft({k: v[:2] for k, v in slots.items()}))
    for k, v in slots.items():
        t[64 * k + BLD.F_TINT] = v[2]
    return bytes(t)


def halo_exp(s, comb, tint):
    w = ROWS[tint][s - 1]
    b = 1024 - w
    if comb == 12:
        (pa, wa), (pb, wb) = CV.pk(1024 - w), CV.pk(w)
        return {92: pa, 96: wa, 136: pb, 140: wb}
    kcb, kcr = BLD.TINT_K[tint - 1]
    bcb, bcr = min(kcb * b // 8, 1024), min(kcr * b // 8, 1024)
    return {92: w | (1024 - bcb) << 16, 96: 1024 - bcr, 136: b | bcb << 16, 140: bcr}


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
    for s in (0, 1, 5, 6):
        for prof in (1, 4, 5):
            for mode in (11, 12):
                tb = ft({prof - 1: (2, s)}) if prof <= 4 else ft({4: (2, s)})
                ok_, flags, _, capok = BV.conv_run(img, tb, 11, mode, prof)
                sok, sflags, _, _ = BV.conv_run(stock, tb, 11, mode, prof)
                on = mode == 11 and prof <= 4 and 1 <= s <= 5
                want = sflags | 0x80 if on else sflags
                n += 1
                if not (ok_ and sok and capok and flags == want):
                    fails.append(f'F s{s} prof{prof} mode{mode}: {flags:#x} want {want:#x}')
    res['F'] = (n, fails)
    # W
    n, fails = 0, []
    off = CV.live_from(stock)
    for eff, comb in ((0x0402, 11), (0x0403, 12)):
        sg, sb, sstk = bank_run(stock, ft({}), 11, eff)
        for eid, tint, want_t in ((1, 1, 1), (1, 2, 2), (1, 3, 3), (1, 4, 4), (2, 0, 1), (2, 4, 4)):
          for s in (1, 3, 5):
            for prof, rec in ((1, 0), (4, 3)):
                    tb = ftt({prof - 1: (eid, s, tint)})
                    pg, pb, pstk = bank_run(img, tb, 11, eff, ext=(prof, 11, MAGIC), rec=rec)
                    got, exp = BV.weights_of(pb), halo_exp(s, comb, want_t)
                    n += 1
                    if not (pg and got == exp and BV.mask_w(pb) == BV.mask_w(sb) and pstk[off:] == sstk[off:]):
                        fails.append(f'W comb{comb} e{eid} t{tint} s{s} prof{prof} rec{rec}: {({k: hex(v) for k, v in got.items()})} '
                                     f'want {({k: hex(v) for k, v in exp.items()})}')
        for label, tb, jk in (('no marker', ft({0: (2, 3)}), dict(ext=None)),
                              ('mode 12', ft({0: (2, 3)}), dict(ext=(1, 11 + 1, MAGIC))),
                              ('wrong callback', ft({0: (2, 3)}), dict(ext=(1, 11, MAGIC), callback=BV.CALLBACK + 1)),
                              ('tint 5', ftt({0: (1, 3, 5)}), dict(ext=(1, 11, MAGIC))),
                              ('tint 255', ftt({0: (2, 3, 255)}), dict(ext=(1, 11, MAGIC))),
                              ('effect 2 strength 6', ftt({0: (2, 6, 1)}), dict(ext=(1, 11, MAGIC)))):
            pg, pb, _ = bank_run(img, tb, 11, eff, **jk)
            n += 1
            if not (pg and pb == sb):
                fails.append(f'W comb{comb} guard {label}: bank != stock')
    res['W'] = (n, fails)
    # D
    n, fails = 0, []
    tables = [('all off', bytes(512)), ('erased', b'\xff' * 512), ('effect 4', ft({0: (4, 3)})),
              ('halation 0/6', ft({0: (2, 0), 1: (2, 6)}))]
    tables += [(f'bloom {s}', ft({i: (1, s) for i in range(4)})) for s in (1, 3, 5)]
    tables += [(f'clarity {s} tint 3', ftt({i: (3, s, 3) for i in range(4)})) for s in (1, 5)]
    for label, tb in tables:
        for prof in (0, 1, 4):
            for mode in (11, 12):
                x, y = BV.conv_run(base, tb, 11, mode, prof), BV.conv_run(img, tb, 11, mode, prof)
                n += 1
                if not (x[0] and y[0] and x[1:] == y[1:]):
                    fails.append(f'D conv {label} prof{prof} mode{mode}')
            for eff in (0x0402, 0x0403):
                x = bank_run(base, tb, 11, eff, ext=(prof, 11, MAGIC), rec=3)
                y = bank_run(img, tb, 11, eff, ext=(prof, 11, MAGIC), rec=3)
                n += 1
                if not (x[0] and y[0] and x[1] == y[1] and x[2] == y[2]):
                    fails.append(f'D bank {label} prof{prof} eff{eff:#x}')
    for key, eff, lv in ((CV.SF_KEY, 0x0402, 0), (CV.SF_KEY, 0x0402, 5), (CV.SF_KEY, 0x0403, -5), (12, 0x0402, 0)):
        x, y = bank_run(stock, ft({0: (2, 3)}), key, eff, lv), bank_run(img, ft({0: (2, 3)}), key, eff, lv, ext=(1, 11, MAGIC))
        n += 1
        if not (x[0] and y[0] and x[1] == y[1]):
            fails.append(f'D stock key {key:#x} eff {eff:#x} lv {lv}: bank != stock')
    res['D'] = (n, fails)
    ok = True
    for p, (n, f) in res.items():
        print(f'{p}: {n - len(f)}/{n} {"PASS" if not f else "FAIL"}')
        for x in f[:10]:
            print('   ', x)
        ok &= not f
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
