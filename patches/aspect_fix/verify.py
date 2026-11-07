#!/usr/bin/env python3
"""Emulator checks for aspect_fix t1 (real firmware code, callees stubbed or stopped at). Offline.

  .venv/bin/python -I patches/aspect_fix/verify.py releases/v0.28/edits.json generated/aspect_fix/t1/edits.json [generated/aspect_fix/t1/pkg]

  A  AF target selector 0x60dd5ce5..0x60dd5d89 (GetValue stubbed), keys 0/1, (8,sp) 0/100, aspects 1,2,3,4,9,10,6,7:
     mask (64,obj) / style (68,obj). 1-4/9/10 == v0.28; 6/7: v0.28 leaves both unwritten, t1 == the 16:9 entry
  D  AF rows/cols switches 0x60663863 / 0x606638d5: 1-4/9/10 == v0.28 (d2,d3 at the store 0x60663943); 6/7: v0.28 reaches the
     log case, t1 stores the 16:9 dims; other misses (0,5,8) still reach the stock log case with (4,sp) = 3
  W  AF window table 0x607175b4/e0: ids 6/7 == id 3, every other entry == v0.28
  G  AF/LV driver ratio globals, the 3 real writers (0x605d5280 / 0x605e2776 / 0x605e6643): stock pairs and 5:4 stored as is,
     65:24 / 21:9 / 7:6 / 6:5 -> 16:9; every register == v0.28 at the resume address
  U  AUTO pair switches 0x605d25e4.. / 0x605d27a5..: stock pairs reach the same case as v0.28; wide pairs reach the 16:9 case
     (t1) instead of the log case (v0.28); 5:4 still logs
  L  local remaps ag1/ag2/mt/sv: 6/7 -> 3, other values unchanged, resume address and other registers == v0.28's replaced code
  B  boot clamp removed: 0x601929a4 / 0x60210e90 == stock bytes
  Y  alignment: block start, every word/halfword access made from the stub block in these runs; no fault in any run
  P  anti-brick: package reparses, decoded == stock + edits, restore == stock, only our sites (and fw_version) differ from v0.28
"""
import importlib.util, json, re, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
from penf_emulator import Region, execute  # noqa: E402
import build_package as BP, oly_container as oc  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


AF = _load('aspect_fix_build', ROOT / 'patches/aspect_fix/build.py')
SB3 = AF.SB3
BASE = 0x60020020
STK, OBJ, GET, PAIR, GLB = 0x18010000, 0x1a000000, 0x1b000000, 0x1c000000, 0xa276f000
TRACES = []
SENT = 0x5a5a5a5a


def image(spec):
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    return [b for b in oc.parse(pkg) if b.kind == 0x100][0].payload, pkg, rst, info


def R(q, name, lo, hi, perm='rx'):
    return Region(name, lo, q[lo - BASE:hi - BASE], perm)


def mem(r):
    return {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}


def ex(q, regions, regs, stops, limit=20000):
    r = execute(regions, regs, 0xfffffff0, limit=limit, trace_limit=min(limit, 100000), breakpoints=list(stops))
    TRACES.append((q, r))
    return r


def code_regions(q, extra):
    return [R(q, 'stub', AF.AT, AF.END)] + extra


def stack(words=None, size=0x2000):
    b = bytearray(struct.pack('<I', SENT) * (size // 4))
    for off, v in (words or {}).items():
        struct.pack_into('<I', b, 0x1000 + off, v & 0xffffffff)
    return bytes(b)


# ------------------------------------------------------------------ A: AF target selector
def getter(val):   # GetValue(d0, a1) stand-in: *a1 = val; rets
    return SB3.assemble(f' .am33_2\n .text\n .global _start\n_start:\n mov {val},d0\n mov d0,(a1)\n clr d0\n rets\n', GET, {})[0]


def sel(q, key, mode, asp):
    rg = code_regions(q, [R(q, 'ui', 0x60dd5000, 0x60dd6000), R(q, 'lists', 0x61140000, 0x61142000, 'r'),
                          Region('get', GET, getter(asp), 'rx'), Region('stk', STK, stack({8: mode, 12: key}), 'rw'),
                          Region('obj', OBJ, struct.pack('<I', SENT) * 32, 'rw', True)])
    r = ex(q, rg, {'pc': 0x60dd5ce5, 'sp': STK + 0x1000, 'a1': STK + 0x1000 + 24, 'a2': GET, 'a3': OBJ}, [0x60dd5d89])
    if r['status'] != 'breakpoint' or r['fault']:
        return ('fault', r['status'])
    o = mem(r)['obj']
    return struct.unpack_from('<I', o, 64)[0], struct.unpack_from('<H', o, 68)[0]


def t_sel(old, new):
    bad, n = [], 0
    for key in (0, 1):
        for mode in (0, 100):
            ref3 = sel(old, key, mode, 3)
            for asp in (1, 2, 3, 4, 9, 10, 6, 7):
                a, b = sel(old, key, mode, asp), sel(new, key, mode, asp)
                n += 1
                if asp in (6, 7):
                    ok = a == (SENT, SENT & 0xffff) and b == ref3
                else:
                    ok = a == b and a[0] != SENT
                if not ok:
                    bad.append((key, mode, asp, a, b))
    return bad, n


# ------------------------------------------------------------------ D: AF rows/cols
def dims(q, start, asp):
    rg = code_regions(q, [R(q, 'af', 0x60663000, 0x60664000), Region('asp', PAIR, bytes([asp]) * 16, 'r'),
                          Region('stk', STK, stack(), 'rw', True)])
    r = ex(q, rg, {'pc': start, 'sp': STK + 0x1000, 'a2': PAIR}, [0x60663943, 0x606638a1, 0x6066390d])
    g = r['registers']
    return r['status'], hex(g['pc']), g['d2'], g['d3'], struct.unpack_from('<I', mem(r)['stk'], 0x1004)[0]


def t_dims(old, new):
    bad, n = [], 0
    for start in (0x60663863, 0x606638d5):
        ref3 = dims(old, start, 3)
        for asp in (1, 2, 3, 4, 9, 10, 6, 7, 0, 5, 8):
            a, b = dims(old, start, asp), dims(new, start, asp)
            n += 1
            if asp in (6, 7):
                ok = a[1] in ('0x606638a1', '0x6066390d') and b == ref3
            elif asp in (0, 5, 8):
                ok = a == b and a[1] in ('0x606638a1', '0x6066390d') and a[4] == 3
            else:
                ok = a == b and a[1] == '0x60663943'
            if not ok:
                bad.append((hex(start), asp, a, b))
    return bad, n


def t_win(old, new):
    bad, n = [], 0
    for t in AF.AFWIN:
        o = [struct.unpack_from('<HH', old, t - BASE + 4 * i) for i in range(11)]
        w = [struct.unpack_from('<HH', new, t - BASE + 4 * i) for i in range(11)]
        for i in range(11):
            n += 1
            exp = o[3] if i in (6, 7) else o[i]
            if w[i] != exp or (i in (6, 7) and o[i] != (0, 0)):
                bad.append((hex(t), i, o[i], w[i]))
        n += 1
        if (t + 24) % 4:
            bad.append(('align', hex(t + 24)))
    return bad, n


# ------------------------------------------------------------------ G: ratio globals
PAIRS = [(4, 3), (16, 9), (3, 2), (6, 6), (3, 4), (17, 9), (5, 4), (65, 24), (21, 9), (7, 6), (6, 5)]
WIDE = {(65, 24), (21, 9), (7, 6), (6, 5)}
WRITERS = [  # start, resume, (W offset, H offset), base register, stack word for the base
    (0x605d5280, 0x605d52a1, (84, 85), None, 68),
    (0x605e2776, 0x605e2795, (84, 85), 'a0', None),
    (0x605e6643, 0x605e665e, (72, 73), 'a2', None),
]


def writer(q, w, pair):
    start, stop, (ow, oh), reg, sw = w
    s = bytearray(256); s[ow], s[oh] = pair; s[90] = 0x11; s[74] = 0x11; s[92] = 0x22
    rg = code_regions(q, [R(q, 'drv', 0x605d0000, 0x605e8000), Region('s', PAIR, bytes(s), 'r'),
                          Region('stk', STK, stack({sw: PAIR} if sw is not None else {}), 'rw', True),
                          Region('glb', GLB, bytes(0x1000), 'rw', True)])
    regs = {'pc': start, 'sp': STK + 0x1000, 'd2': 0x1234, 'd3': 0x5678, 'a3': STK + 0x1000}
    if reg:
        regs[reg] = PAIR
    r = ex(q, rg, regs, [stop])
    g = mem(r)['glb']
    return r['status'], {k: v for k, v in r['registers'].items() if k in ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'pc')}, \
        (g[0x955], g[0x956]), mem(r)['stk'][0x1000:]


def t_glob(old, new):
    bad, n = [], 0
    for w in WRITERS:
        for p in PAIRS:
            a, b = writer(old, w, p), writer(new, w, p)
            n += 1
            exp = (16, 9) if p in WIDE else p
            ok = a[0] == b[0] == 'breakpoint' and a[1] == b[1] and a[3] == b[3] and a[2] == p and b[2] == exp
            if not ok:
                bad.append((hex(w[0]), p, a[:3], b[:3]))
    return bad, n


# ------------------------------------------------------------------ U: AUTO pair switches
def auto_mask(q, pair):
    s = bytearray(256); s[204], s[205] = pair
    st = {44: PAIR + 204, 52: PAIR + 205, 68: 0, 40: 0, 64: 5, 32: OBJ, 48: OBJ + 1}
    rg = code_regions(q, [R(q, 'drv', 0x605d0000, 0x605e8000), Region('s', PAIR, bytes(s), 'r'), Region('stk', STK, stack(st), 'rw'),
                          Region('obj', OBJ, bytes(16), 'rw', True)])
    r = ex(q, rg, {'pc': 0x605d25de, 'sp': STK + 0x1000, 'a3': OBJ + 8, 'a2': OBJ + 12}, [0x605d2676, 0x605d2681, 0x605d269e])
    return r['status'], hex(r['registers']['pc']), r['registers']['d0'], r['registers']['a0']


def auto_thr(q, pair):
    s = bytearray(256); s[204], s[205] = pair
    rg = code_regions(q, [R(q, 'drv', 0x605d0000, 0x605e8000), Region('s', PAIR, bytes(s), 'r'), Region('stk', STK, stack({72: PAIR, 20: 0}), 'rw')])
    r = ex(q, rg, {'pc': 0x605d27a5, 'sp': STK + 0x1000, 'a2': OBJ}, [0x605d2825, 0x605d2837])
    return r['status'], hex(r['registers']['pc']), r['registers']['d0'], r['registers']['d1']


def t_auto(old, new):
    bad, n = [], 0
    for fn, hits, miss in ((auto_mask, ('0x605d2676', '0x605d269e'), '0x605d2681'), (auto_thr, ('0x605d2825',), '0x605d2837')):
        ref = fn(old, (16, 9))
        for p in PAIRS:
            a, b = fn(old, p), fn(new, p)
            n += 1
            if p in WIDE:
                ok = a[1] == miss and b == ref
            elif p in ((5, 4), (17, 9)):        # stock misses stay misses: same resume, d0 = the log id (log case)
                ok = a[:3] == b[:3] and a[1] == miss and a[2] in (1022, 1895)
            else:
                ok = a == b and a[1] in hits
            if not ok:
                bad.append((fn.__name__, p, a, b))
    return bad, n


# ------------------------------------------------------------------ L: local remaps
LOCAL = [  # site, resume, set-up(value) -> (regs, stack words, obj words), the checked register
    (0x60df798a, 0x60df798f, lambda v: ({'a3': OBJ}, {}, {228: v}), 'a0'),
    (0x60df7b55, 0x60df7b5a, lambda v: ({'a3': OBJ}, {}, {228: v}), 'a0'),
    (0x60e32899, 0x60e3289e, lambda v: ({}, {52: v}, {}), 'd0'),
    (0x60e3bde8, 0x60e3bdee, lambda v: ({}, {8: OBJ}, {4: v}), 'd2'),
]


def local(q, site, stop, setup, v):
    regs, sw, ow = setup(v)
    o = bytearray(256)
    for k, x in ow.items():
        struct.pack_into('<I', o, k, x)
    rg = code_regions(q, [R(q, 'site', site & ~0xfff, (site & ~0xfff) + 0x1000), Region('stk', STK, stack(sw), 'rw'), Region('obj', OBJ, bytes(o), 'r')])
    base = {'d0': 0x11, 'd1': 0x22, 'd2': 0x33, 'd3': 0x44, 'a0': 0x55, 'a1': 0x66, 'a2': 0x77}
    base.update(regs)
    r = ex(q, rg, dict(base, pc=site, sp=STK + 0x1000), [stop])
    return r['status'], {k: v for k, v in r['registers'].items() if k in ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'pc')}


def t_local(old, new):
    bad, n = [], 0
    for site, stop, setup, reg in LOCAL:
        for v in (1, 2, 3, 4, 9, 10, 0, 5, 8, 6, 7):
            a, b = local(old, site, stop, setup, v), local(new, site, stop, setup, v)
            n += 1
            exp = dict(a[1]); exp[reg] = 3 if v in (6, 7) else a[1][reg]
            if not (a[0] == b[0] == 'breakpoint' and b[1] == exp and a[1][reg] == v):
                bad.append((hex(site), v, a, b))
    return bad, n


def t_clamp(new):
    st = AF.STOCK.read_bytes()
    bad = [hex(a) for a, k in ((AF.CLAMP_HOOK, 6), (AF.CLAMP_AT, 56)) if new[a - BASE:a - BASE + k] != st[a - BASE:a - BASE + k]]
    return bad, 2


# ------------------------------------------------------------------ Y, P
def t_align(new_s):
    sym = {k: int(v, 16) for k, v in new_s['aspect_fix']['symbols'].items()}
    at, end = AF.AT, sym['af_end']
    bad, n = ([] if at % 4 == 0 else ['block start']), 1
    for q, r in TRACES:
        n += 1
        if r['fault']:
            bad.append(('fault', r['fault']))
        ins = {a: (op, args) for a, op, args in SB3.disasm(q[at - BASE:end - BASE], at, end)}
        for row in r['trace']:
            if row['pc'] not in ins:
                continue
            op, args = ins[row['pc']]
            size = {'mov': 4, 'movhu': 2}.get(op)
            m = re.search(r'\(([^)]*)\)', args)
            if not size or not m:
                continue
            parts = [x.strip() for x in m.group(1).split(',')]
            regs = {k: row[k] for k in ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp')}
            addr = sum(regs[x] if x in regs else int(x, 0) for x in parts) & 0xffffffff
            n += 1
            if addr % size:
                bad.append((hex(row['pc']), op, args, hex(addr)))
    return bad, n


def t_pkg(new_s, new, pkg, rst, info, disk, old):
    sb = {b.kind: b for b in oc.parse(BP.STOCK.read_bytes())}
    good = True
    for b in oc.parse(pkg):
        exp = bytearray(sb[b.kind].payload)
        for e in new_s['edits']:
            if int(e['kind'], 16) == b.kind:
                o = BP.resolve(b.kind, e['addr']); nb = bytes.fromhex(e['new']); exp[o:o + len(nb)] = nb
        good &= bytes(exp) == b.payload
    for b in oc.parse(rst):
        good &= b.payload == sb[b.kind].payload
    ours = [(int(e['addr'], 16), len(e['new']) // 2) for e in new_s['edits'] if e.get('source') in ('patches/aspect_fix', 'patches/fw_version')]
    ours += [(AF.CLAMP_HOOK, 6), (AF.CLAMP_AT, 56)]
    diff = [BASE + i for i in range(len(old)) if old[i] != new[i]]
    stray = [hex(a) for a in diff if not any(s_ <= a < s_ + k for s_, k in ours)]
    good &= not stray
    if disk:
        good &= (disk / 'patched.pkg.bin').read_bytes() == pkg and (disk / 'restore-stock.pkg.bin').read_bytes() == rst
    return good, f'{info["edits"]} edits, {info["changed_payload_bytes"]} B; {len(diff)} B differ from v0.28; stray {stray[:6]}'


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    old, *_ = image(base_s)
    new, pkg, rst, info = image(new_s)
    ok = True
    for name, fn in (('A AF selector', lambda: t_sel(old, new)), ('D AF rows/cols', lambda: t_dims(old, new)), ('W AF windows', lambda: t_win(old, new)),
                     ('G ratio globals', lambda: t_glob(old, new)), ('U AUTO pairs', lambda: t_auto(old, new)), ('L local remaps', lambda: t_local(old, new)),
                     ('B clamp removed', lambda: t_clamp(new)), ('Y alignment/faults', lambda: t_align(new_s))):
        bad, n = fn(); ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:3] if bad else '', flush=True)
    good, txt = t_pkg(new_s, new, pkg, rst, info, disk, old); ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: {txt}")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
