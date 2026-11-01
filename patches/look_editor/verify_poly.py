#!/usr/bin/env python3
"""Emulator check of the 13 wheel-polygon hook (ed_poly, docs/LOOK_EDITOR.md §7). Offline only.

  .venv/bin/python -I patches/look_editor/verify_poly.py SPEC.json [SPEC.json ...]

Runs the real edited site 0x609330f9 (C3d producer 0x60932fa6, case 1: the sector value read) from the patched
image, the whole image mapped READ-ONLY (a store into 0x60020020..0x6191ffe0 faults), heap/state as the editor
verifier builds them. Per spec, for every sector id of COLOR1-4 (+ non-sector ids) and every heap state:
  - stock path (page S, no table, bad h/magic/marker, no facade, unknown page): the run reaches 0x602afa81 with
    registers + live stack == the stock run of the same site;
  - Light / Hue / Extras page: returns to 0x60933100, d0 == the facade GetValue result for that id from the same
    patched image (ex_get / ed_get chain), and for Light/Hue == the clamped table byte computed here;
  - Film page (3, only when the spec has the film layer): d0 == 0;
  - d2/d3/a2/a3/sp preserved, nothing but the stack written.
"""
import json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import importlib.util
_s = importlib.util.spec_from_file_location('vle', ROOT / 'tools/ep7_verify_look_editor.py')
V = importlib.util.module_from_spec(_s)
_s.loader.exec_module(V)
Region, BASE = V.Region, V.BASE
SITE, AFTER, AGET = 0x609330f9, 0x60933100, 0x602afa81
FAC_PTR, FAC_OBJ = 0x61fa96ac, 0x18b00000
IDS = [927 + i for i in range(36)] + [1655 + i for i in range(12)]
MISS_IDS = [926, 963, 1654, 1667, 1648, 1096]


def regions(im, h, blk, fac=True):
    r = [V.img(im, BASE, BASE + len(im), 'img', 'rx'),
         Region('facp', FAC_PTR & ~0xf, struct.pack('<4I', *[FAC_OBJ if (FAC_PTR & ~0xf) + 4 * i == FAC_PTR and fac else 0
                                                              for i in range(4)]), 'r'),
         Region('facobj', FAC_OBJ, struct.pack('<I', 0x60acb0dc) + bytes(60), 'r')]
    return r + V.state_regions(h, blk, 'r')


def site_run(im, idv, h, blk, stop, fac=True):
    return V.run(regions(im, h, blk, fac), {'pc': SITE, 'd0': idv, 'd1': 0x11111111, 'a0': 0x0a0a0a0a,
                                            'a1': 0x0b0b0b0b}, stop)


def facade_value(im, idv, h, blk):
    src = (f' mov {FAC_PTR:#x},a0\n mov (a0),a0\n mov {V.OUT:#x},a1\n mov {idv:#x},d0\n mov (0x60acb0e4),a2\n'
           f' calls (a2)\n')
    code, sy = V.asm(src, V.DRV)
    r = V.run([Region('drv', V.DRV, code, 'rx'), Region('out', V.OUT, b'\x77' * 16, 'rw', True)] + regions(im, h, blk),
              {'pc': V.DRV}, sy['done'])
    if r['fault'] or r['registers']['pc'] != sy['done']:
        raise RuntimeError(f'facade run failed {r["fault"]}')
    return struct.unpack_from('<i', V.mem(r, 'out'), 0)[0]


def table_value(blk, idv, axis):
    if 927 <= idv <= 962:
        k, s = (idv - 927) // 12, (idv - 927) % 12
    else:
        k, s = 3, idv - 1655
    v = struct.unpack('b', bytes([blk[32 + 64 * k + s + (12 if axis == 1 else 0)]]))[0]
    return max(-5, min(5, v))


def check(spec_path):
    spec = json.loads(Path(spec_path).read_text())
    stock, patched = V.images(spec)
    syms = V.SYMS
    film = any('film' in (e.get('source') or '') for e in spec['edits'])
    xpage = patched[int(syms['ed_cfg_x'], 16) - BASE]
    fails, n = [], 0
    states = [('h=0', 0, None, None), ('misaligned', V.H_OK + 1, V.card_block(), None),
              ('no EP7E', V.H_OK, V.card_block(marker=False), None)]
    b = V.card_block()
    b[0] ^= 1
    states.append(('no EP7B', V.H_OK, b, None))
    for ax in range(0, 7):
        blk = V.card_block(axis=ax)
        if xpage == ax and ax:
            for k in range(4):                         # extras bytes: grain 2, clarity 3, WB on A-B -4 / G-M 7
                o = 32 + 64 * k
                blk[o + 24], blk[o + 28], blk[o + 29], blk[o + 25], blk[o + 26], blk[o + 27] = 2, 3, 3, 1, 0xfc, 7
        if ax in (1, 2) or (ax and ax == xpage):
            want = 'chain'
        elif ax == 3 and film:
            want = 'zero'
        else:
            want = None
        states.append((f'axis {ax}', V.H_OK, blk, want))
    for label, h, blk, want in states:
        for idv in IDS + MISS_IDS:
            n += 1
            w = want if idv in IDS else None
            s = site_run(stock, idv, h, blk, AGET)
            if s['fault'] or s['registers']['pc'] != AGET:
                fails.append(f'{label} {idv}: stock run {s["fault"]}')
                continue
            p = site_run(patched, idv, h, blk, AGET if w is None else AFTER)
            if p['fault']:
                fails.append(f'{label} {idv}: fault {p["fault"]}')
                continue
            if w is None:
                e = None if p['registers']['pc'] == AGET else f'pc {p["registers"]["pc"]:#x}'
                e = e or V.same_state(s, p, skip=())
                if e:
                    fails.append(f'{label} {idv}: stock path {e}')
                continue
            r = p['registers']
            got = struct.unpack('b', bytes([r['d0'] & 0xff]))[0]
            exp = 0 if w == 'zero' else facade_value(patched, idv, h, blk)
            if w == 'chain' and int(label.split()[1]) in (1, 2) and exp != table_value(blk, idv, int(label.split()[1])):
                fails.append(f'{label} {idv}: facade {exp} != table')
            if got != exp or r['d0'] != (exp & 0xffffffff):
                fails.append(f'{label} {idv}: d0 {r["d0"]:#x} want {exp}')
            if r['pc'] != AFTER or r['sp'] != V.SP0 or any(r[k] != V.SENT[k] for k in ('d2', 'd3', 'a2', 'a3')):
                fails.append(f'{label} {idv}: regs/sp ' + str({k: hex(r[k]) for k in ('pc', 'sp', 'd2', 'd3', 'a2', 'a3')}))
    # no facade singleton (h valid, axis H) -> stock
    n += 1
    blk = V.card_block(axis=2)
    s = site_run(stock, 927, V.H_OK, blk, AGET, fac=False)
    p = site_run(patched, 927, V.H_OK, blk, AGET, fac=False)
    e = None if p['registers']['pc'] == AGET and not p['fault'] else f'pc {p["registers"]["pc"]:#x} {p["fault"]}'
    if e or V.same_state(s, p, skip=()):
        fails.append(f'no facade: {e or V.same_state(s, p, skip=())}')
    print(f'{spec_path}: film={film} x_page={xpage}: {n - len(fails)}/{n} PASS' if not fails else
          f'{spec_path}: {len(fails)} FAIL of {n}\n  ' + '\n  '.join(fails[:20]))
    return not fails


if __name__ == '__main__':
    ok = all([check(p) for p in sys.argv[1:]])
    sys.exit(0 if ok else 1)
