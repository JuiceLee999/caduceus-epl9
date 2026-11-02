#!/usr/bin/env python3
"""Reference encoder for the web-app tests: runs the repo's own Python tools on packs the tests generate.

  python3 -I tests/py_reference.py <tools root> < cases.json  ->  JSON list of {looks, bundles, looks_check, bundles_check}
  python3 -I tests/py_reference.py <tools root> --info        ->  {"looks_version": n}

<tools root> is a checkout of the v0.16-era tools (git archive of commit e477637: tools/, patches/, sim/recipes/),
or the repo itself (the current tools: LOOKS.BIN v4 with the tone tail; looks may carry "tone").
Each case: {"recipes": {...}, "library": {...}, "slots": {"COLOR1": key, ...}, "art": {"COLOR1": n, ...}}.
LOOKS.BIN comes from tools/ep7_looks_bin.compile_looks (recipes injected); BUNDLES.BIN from LIB.place per slot,
the Art Effect byte (+46, COLOR slots), SB.make_file and ep7_bundles_bin.name_section.
"""
import importlib.util, json, sys
from pathlib import Path

root = Path(sys.argv[1])


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, root / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


LB = load('ep7_looks_bin', 'tools/ep7_looks_bin.py')
BBIN = load('ep7_bundles_bin', 'tools/ep7_bundles_bin.py')
LIB, SB = LB.LIB, LB.SB
out = []
for case in json.loads(sys.stdin.read()):
    recipes = {k: dict(v, _file='webapp-test') for k, v in case['recipes'].items()}
    LIB.BB.load_recipes = lambda: recipes
    res = {}
    try:
        data, keys, names = LB.compile_looks(case['library'])
        res['looks'] = data.hex()
        res['looks_check'] = LB.check_file(data)
        recs = {k: LB.rec(data, j) for j, k in enumerate(keys)}
        table = bytearray(512)
        slot_names = [None] * 8
        for s, k in case.get('slots', {}).items():
            i = LB.SLOTS.index(s)
            e = bytearray(LB.place(recs[k], i))
            if s.startswith('COLOR'):
                e[LIB.BB.ART_OFF] = case.get('art', {}).get(s, 0)
            table[64 * i:64 * i + 64] = e
            slot_names[i] = names[keys.index(k)]
        b = SB.make_file(bytes(table)) + BBIN.name_section(slot_names)
        res['bundles'] = b.hex()
        res['bundles_check'] = BBIN.check_file(b, tone=True) + BBIN.check_names(b[BBIN.NAMES_LO:])
    except (ValueError, AssertionError) as e:
        res['error'] = str(e)
    out.append(res)
print(json.dumps(out))
