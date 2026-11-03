#!/usr/bin/env python3
"""Mapping run: the full stock work-list builder (0x6035749f .. finalize 0x60357c91) for MONO / COLOR jobs.
  .venv/bin/python -I patches/grain_c/map.py [spec.json]   (default: stock image)"""
import json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import ep7_grain_verify as GV  # noqa: E402

END = 0x60357c91
NAMES = {0x60356d7b: 'dev(default)', 0x60356cc6: 'cb_dev_output', 0x60359bc8: 'MASK pass', 0x60359cd8: 'GRAIN image pass',
         0x60359e01: 'mod_mask(0900)', 0x60359e15: 'mod_grain(0901)', 0x60359e5e: 'mod_0902', 0x60357327: 'pre(0x60357327)'}
nm = lambda a: NAMES.get(a, hex(a)) if a else '-'


def build(main, key, cls, feat=0, ext=(1, 11, GV.MAGIC), table=None, jtype=0):
    job = GV.job_bytes(key=key, jtype=jtype, cls=cls, ext=ext)
    struct.pack_into('<I', job, 16, feat)
    lst = bytearray(32); lst[4] = 1
    struct.pack_into('<I', lst, 16, GV.ENTRIES)
    rg = GV.regions(main, table if table is not None else GV.fixture_table([2] * 8),
                    [GV.stack({4: GV.JOB, 8: GV.JOB + 11308}), GV.Region('list', GV.LIST, bytes(lst), 'rw', True),
                     GV.Region('entries', GV.ENTRIES, bytes(12 * 16), 'rw', True), GV.Region('job', GV.JOB, bytes(job), 'rw', True)])
    regs = {'pc': 0x6035749f, 'sp': GV.STACK + 0x1800, 'd2': key, 'd3': 0x3333, 'a2': GV.JOB + 4, 'a3': GV.LIST}
    x = GV.execute(rg, regs, END, limit=200000)
    m = GV.mem(x)
    n = struct.unpack_from('<H', m['list'], 0)[0]
    ents = [struct.unpack_from('<III', m['entries'], 12 * i) for i in range(n)]
    r = dict(ok=x['registers']['pc'] == END and not x['fault'], fault=x['fault'], pc=hex(x['registers']['pc']), list=m['list'], job=m['job'])
    return r, ents


def show(tag, r, ents):
    print(f'{tag}: ok={r["ok"]} pc={r["pc"]} fault={r["fault"]} n={len(ents)} job+11314={struct.unpack_from("<H", r["job"], 11314)[0]}')
    for e in ents:
        print('    fn', nm(e[0]), ' mod', nm(e[1]), ' cb', nm(e[2]))


if __name__ == '__main__':
    import build_package as BP, oly_container as oc
    stock = BP.STOCK.read_bytes()
    main = [b for b in oc.parse(stock) if b.kind == 0x100][0].payload
    if len(sys.argv) > 1:
        pkg, _, _ = BP.build(json.loads(Path(sys.argv[1]).read_text()), stock)
        main = [b for b in oc.parse(pkg) if b.kind == 0x100][0].payload
    for key, cls in ((12, 0), (12, 4), (11, 0), (11, 4)):
        show(f'key {key} class {cls}', *build(main, key, cls))
