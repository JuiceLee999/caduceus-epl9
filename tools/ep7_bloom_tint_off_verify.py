#!/usr/bin/env python3
"""v0.14 check: bloom colour off (patches/bloom --eff2-bloom, no --halation). Combiner banks (11 and 12) for bloom
(effect 1) with tint 0..4/255 and old red bloom (effect 2) with any tint == the OLD_SPEC bank of plain bloom (effect 1,
tint 0) at the same strength; clarity 1..5, off, erased table == OLD_SPEC.

  .venv/bin/python -I tools/ep7_bloom_tint_off_verify.py SPEC.json --base OLD_SPEC.json
"""
import argparse, importlib.util, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
s = importlib.util.spec_from_file_location('hv_t', ROOT / 'tools/ep7_halation_verify.py')
HV = importlib.util.module_from_spec(s); s.loader.exec_module(HV)
ap = argparse.ArgumentParser(); ap.add_argument('spec'); ap.add_argument('--base', required=True); a = ap.parse_args()
_, img = HV.EV.images(json.loads(Path(a.spec).read_text()))
_, base = HV.EV.images(json.loads(Path(a.base).read_text()))
n, fails = 0, []
for eff in (0x0402, 0x0403):
    for s_ in range(1, 6):
        for prof, rec in ((1, 0), (4, 3)):
            want_ok, want, _ = HV.bank_run(base, HV.ftt({prof - 1: (1, s_, 0)}), 11, eff, ext=(prof, 11, HV.MAGIC), rec=rec)
            for e_, t in [(1, t) for t in (0, 1, 2, 3, 4, 255)] + [(2, t) for t in (0, 1, 4)]:
                ok, got, _ = HV.bank_run(img, HV.ftt({prof - 1: (e_, s_, t)}), 11, eff, ext=(prof, 11, HV.MAGIC), rec=rec)
                n += 1
                if not (ok and want_ok and got == want):
                    fails.append(f'bloom e{e_} t{t} s{s_} {eff:#x} prof{prof}')
            for tb, lab in ((HV.ftt({prof - 1: (3, s_, 2)}), 'clarity'), (HV.ftt({}), 'off'), (b'\xff' * 512, 'erased')):
                ok, got, _ = HV.bank_run(img, tb, 11, eff, ext=(prof, 11, HV.MAGIC), rec=rec)
                ok0, got0, _ = HV.bank_run(base, tb, 11, eff, ext=(prof, 11, HV.MAGIC), rec=rec)
                n += 1
                if not (ok and ok0 and got == got0):
                    fails.append(f'{lab} s{s_} {eff:#x} prof{prof}')
print(f'B: {n - len(fails)}/{n} ' + ('PASS' if not fails else 'FAIL'))
for f in fails[:10]:
    print('   ', f)
sys.exit(1 if fails else 0)
