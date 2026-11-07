#!/usr/bin/env python3
"""Anti-brick checks for page_order (0.29p1). Offline. Reuses tools/ep7_verify_look_editor.py (E/I harness).

  .venv/bin/python -I patches/page_order/verify.py BASE.json NEW.json [PKG_DIR]

  P  package reparses; decoded == stock + edits; restore == stock; only page_order + version-label sites differ from BASE
  I  open (record +4 -> po_init -> stock init 0x60e20a54): registers, mdr and live stack == stock run; heap: Film
     (marker set on a first use) when fm_valid and ALL off, else ed_init's rule; fm_valid stand-in, ed_fm_none and
     the real v0.29 fm_valid (no LOOKS.BIN); invalid heap: nothing
  E  INFO through record +44 (ed_info): the cycle from the opened state, with and without LOOKS.BIN, every key;
     each axis x ALL flags; no marker; stock declining; guards -> stock with state == stock run
  F  0.29p2 only (spec page_order.film_poly): patches/look_editor/verify_poly.py on the real site 0x609330f9 with
     the Film page (axis 3) expected on the stock path: it reaches the stock saturation read 0x602afa81 with
     registers + live stack == the stock run (what the Saturation page shows; a stills Film pick writes those
     settings, v0.24). Light/Hue/Extras keep their values; misses stay stock.
"""
import importlib.util, inspect, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'external/oly_fw_analysis/tools')]
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


VL = _load('ep7_verify_look_editor', ROOT / 'tools/ep7_verify_look_editor.py')
PO = _load('page_order_build', ROOT / 'patches/page_order/build.py')
LE, Region = VL.LE, VL.Region
AXIS, EMARK, DIRTY, STATUS, EMAGIC = VL.AXIS, VL.EMARK, VL.DIRTY, VL.STATUS, VL.EMAGIC
FM_UI = (0x601e2c3c, 0x601e2f3c)


def next_page(ax, cfg_x, fv):
    """0.29p1: F(3) -> S(0) -> [S-All, stock] -> H(2) -> L(1) -> X(cfg_x) -> F (LOOKS.BIN) / S."""
    return {0: 2, 2: 1, 3: 0, 1: cfg_x}.get(ax, 3 if fv else 0)


VL.next_page = next_page
_src = inspect.getsource(VL.ev_case)
for a, b in (("if fv is not False and ax == 1 and fvlog", "if fv is not False and ax not in (0, 1, 2, 3) and fvlog"),
             ("if (ax != 1 or fv is False) and fvlog", "if (ax in (0, 1, 2, 3) or fv is False) and fvlog")):
    if a not in _src:
        raise SystemExit(f'ev_case changed: {a!r}')
    _src = _src.replace(a, b)
exec(compile(_src, 'ev_case(page_order)', 'exec'), VL.__dict__)


# ------------------------------------------------------------------ P
def t_pkg(base_s, new_s, disk):
    B = BP.MAIN_BASE
    pkg0, _, _ = BP.build(base_s, BP.STOCK.read_bytes())
    pkg, rst, info = BP.build(new_s, BP.STOCK.read_bytes())
    pl = lambda p: [b for b in oc.parse(p) if b.kind == 0x100][0].payload
    old, new = pl(pkg0), pl(pkg)
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
    ours = [(int(e['addr'], 16), len(e['new']) // 2) for e in new_s['edits'] if e.get('source') in (PO.SRC, 'patches/fw_version')]
    ours.append((PO.K_STEP, PO.K_SET - PO.K_STEP))
    if new_s['page_order'].get('film_poly'):
        ours.append((int(new_s['page_order']['film_poly']['at'], 16), 1))
    diff = [B + i for i in range(len(old)) if old[i] != new[i]]
    stray = [hex(a) for a in diff if not any(x <= a < x + n for x, n in ours)]
    good &= not stray
    if disk:
        good &= (disk / 'patched.pkg.bin').read_bytes() == pkg and (disk / 'restore-stock.pkg.bin').read_bytes() == rst
    print(f"{'PASS' if good else 'FAIL'} P package: {info['edits']} edits; {len(diff)} B differ from base; stray {stray[:6]}")
    return good


# ------------------------------------------------------------------ I
def init_case(stock, patched, key, h, blk, flags, fv):
    """fv: False (ed_fm_none), True (stand-in -> 1), 'stub0' (stand-in -> 0), 'real' (v0.29 fm_valid). -> (err, heap)."""
    rec = LE.RECORDS[key] + 4
    src = (f' mov {rec:#x},a1\n mov (a1),a1\n mov a1,({VL.OUT:#x})\n mov {VL.PAR:#x},a0\n mov {key:#x},d0\n'
           f' mov 0x11111111,d1\n mov 0x1a1a1a1a,a1\n mov ({VL.OUT:#x}),a2\n calls (a2)\n')
    code, _ = VL.asm(src, VL.DRV)
    fcode, _ = VL.asm(VL.FV_STUB, VL.FVS)
    ret = 1 if fv is True else 0
    im = VL.cfg_image(patched, 4, None if fv == 'real' else (fv in (True, 'stub0')))
    res = {}
    for name, img in (('stock', stock), ('patched', im)):
        regions = [Region('drv', VL.DRV, code, 'rx'), Region('out', VL.OUT, bytes(64), 'rw'),
                   VL.img(img, 0x61185b00, 0x61185d00, 'rec', 'r'), VL.img(img, LE.KEYS[0], LE.KEYS[1], 'keys'),
                   VL.img(img, FM_UI[0], FM_UI[1], 'fmui'),
                   Region('fvs', VL.FVS, fcode, 'rx'),
                   Region('fvd', VL.FVS + 0x100, struct.pack('<II', 0, ret) + bytes(0xf8), 'rw', True),
                   Region('allf', 0x61fc3800, struct.pack('<II', *flags) + bytes(8), 'r')] + VL.state_regions(h, blk)
        res[name] = VL.run(regions, {'pc': VL.DRV}, LE.STOCK['ep7_init'])
    s, p = res['stock'], res['patched']
    if s['fault'] or p['fault'] or p['registers']['pc'] != LE.STOCK['ep7_init']:
        return f'fault/pc {p["fault"]} {p["registers"]["pc"]:#x}', None
    e = VL.same_state(s, p)
    if e:
        return f'state at stock init: {e}', None
    hp = VL.mem(p, 'heap')
    fvlog = struct.unpack_from('<I', VL.mem(p, 'fvd'), 0)[0]
    valid = h == VL.H_OK and blk is not None and blk[:4] == struct.pack('<I', VL.MAGIC)
    all_on = bool(flags[0] or flags[1])
    if fv in (True, 'stub0') and valid and not all_on and fvlog != VL.P_OK:
        return f'fm_valid not called with a2 = P ({fvlog:#x})', hp
    if (not valid or all_on or fv not in (True, 'stub0')) and fvlog:
        return 'fm_valid called when it should not be', hp
    if blk is None:
        return None, hp
    exp = bytearray(blk)
    if valid:
        want = 3 if fv is True and not all_on else 0
        marker = struct.unpack_from('<I', blk, EMARK)[0] == EMAGIC
        if marker:
            exp[AXIS] = want
        elif want:
            exp[EMARK:EMARK + 4] = struct.pack('<I', EMAGIC)
            exp[AXIS], exp[DIRTY], exp[STATUS] = want, 0, 0
    if hp != bytes(exp):
        d = [i for i in range(len(hp)) if hp[i] != exp[i]]
        return f'heap differs at {d[:6]}', hp
    return None, hp


def t_init(stock, patched):
    fails, n = [], 0
    for key in LE.RECORDS:
        for fv in (False, True, 'stub0', 'real'):
            for flags in ((0, 0), (1, 0), (0, 1)):
                for label, blk in (('marker axis 2', VL.card_block(axis=2)), ('no marker', VL.card_block(axis=2, marker=False))):
                    blk[DIRTY], blk[STATUS] = 1, 2
                    n += 1
                    e, _ = init_case(stock, patched, key, VL.H_OK, blk, flags, fv)
                    if e:
                        fails.append(f'I {label} key {key:#x} fv {fv} flags {flags}: {e}')
        bad = VL.card_block(axis=2)
        bad[1] ^= 4
        for label, h, blk in (('h=0', 0, VL.card_block(axis=2)), ('no EP7B', VL.H_OK, bad), ('h past pool', VL.LIM + 1, None), ('h misaligned', VL.H_OK + 1, None)):
            n += 1
            e, _ = init_case(stock, patched, key, h, blk, (0, 0), True)
            if e:
                fails.append(f'I {label} key {key:#x}: {e}')
    return fails, n


# ------------------------------------------------------------------ E
NAMES = {0: 'S', 1: 'L', 2: 'H', 3: 'F', 4: 'X'}


def t_event(stock, patched):
    fails, n = [], 0

    def one(label, *a, **kw):
        nonlocal n
        n += 1
        e, hp, fl = VL.ev_case(stock, patched, *a, **kw)
        if e:
            fails.append(f'E {label}: {e}')
        return e, hp, fl
    for fv, want in ((True, 'F S1 SA H L X F S1'), (False, 'S1 SA H L X S1')):
        for key in LE.RECORDS:
            for flags0 in ((0, 0), (1, 0)):          # opened with ALL off / ALL on (closed on Saturation - All)
                blk = VL.card_block(axis=2, marker=False)
                e, blk = init_case(stock, patched, key, VL.H_OK, blk, flags0, fv)
                if e:
                    fails.append(f'E open key {key:#x} fv {fv}: {e}')
                    continue
                blk, fl = bytearray(blk), flags0
                marker = struct.unpack_from('<I', blk, EMARK)[0] == EMAGIC
                ax = blk[AXIS] if marker else 0
                seen = [NAMES[ax] + ('A' if fl[0] or fl[1] else '1') if ax == 0 else NAMES[ax]]
                w = want if not flags0[0] else 'SA H L X ' + want.split(' X ', 1)[1]
                for step in range(len(w.split()) - 1):
                    exp, _ = VL.page_model(blk, fl, 0x9014, 4, fv)
                    e, hp, fl2 = one(f'cycle fv{int(fv)} all{flags0[0]} key {key:#x} step {step}', key, 0x9014, VL.H_OK, blk,
                                     VL.parent_obj2(key=key), exp, flags=fl, cfg_x=4, fv=fv)
                    if e:
                        break
                    blk = bytearray(hp)
                    fl = (1, 0) if exp == 'stock' else fl2
                    p = NAMES.get(blk[AXIS], '?')
                    seen.append(p + ('A' if fl[0] or fl[1] else '1') if p == 'S' else p)
                if ' '.join(seen) != w:
                    fails.append(f'E cycle fv{int(fv)} all{flags0[0]} key {key:#x}: {" ".join(seen)} != {w}')
    for ax in (0, 1, 2, 3, 4, 5, 255):
        for flags in ((0, 0), (1, 0), (0, 1)):
            for fv in (False, True):
                blk = VL.card_block(axis=ax)
                exp, _ = VL.page_model(blk, flags, 0x9014, 4, fv)
                one(f'axis {ax} flags {flags} fv{int(fv)}', 0x13b4, 0x9014, VL.H_OK, blk, VL.parent_obj2(key=0x13b4), exp,
                    flags=flags, cfg_x=4, fv=fv)
    one('no marker', 0x13b5, 0x9014, VL.H_OK, VL.card_block(axis=2, marker=False), VL.parent_obj2(key=0x13b5), 'stock',
        cfg_x=4, fv=True)
    one('declined on S-All', 0x140c, 0x9014, VL.H_OK, VL.card_block(axis=0), VL.parent_obj2(key=0x140c), 'declined',
        flags=(1, 0), decline=1, iret=3, cfg_x=4, fv=True)
    for label, kw in (('key 13a9', dict(key=0x13a9)), ('count 12', dict(count=12)), ('state16', dict(st16=1)),
                      ('null child', dict(null_child=12))):
        for ax in (3, 1):
            one(f'guard {label} axis {ax}', 0x13b3, 0x9014, VL.H_OK, VL.card_block(axis=ax), VL.parent_obj2(**kw), 'stock',
                valid=False, cfg_x=4, fv=True)
    for label, h, blk, _ in VL.heap_states()[:5]:
        one(f'heap {label}', 0x140c, 0x9014, h, blk, VL.parent_obj2(key=0x140c), 'stock', valid=False, cfg_x=4, fv=True)
    return fails, n


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    ok = t_pkg(base_s, new_s, disk)
    stock, patched = VL.images(new_s)
    for name, fn in (('I', t_init), ('E', t_event)):
        fails, n = fn(stock, patched)
        ok &= not fails
        print(f"{'PASS' if not fails else 'FAIL'} {name} {n - len(fails)}/{n}")
        for f in fails[:12]:
            print('   ', f)
    if new_s['page_order'].get('film_poly'):
        VP = _load('verify_poly_page_order', ROOT / 'patches/look_editor/verify_poly.py')
        src = inspect.getsource(VP.check)
        old = "film = any('film' in (e.get('source') or '') for e in spec['edits'])"
        if old not in src:
            raise SystemExit('verify_poly.check changed')
        src = src.replace(old, "film = False   # 0.29p2: Film page -> stock path, as Saturation")
        exec(compile(src, 'check(page_order p2)', 'exec'), VP.__dict__)
        f_ok = VP.check(sys.argv[2])
        ok &= f_ok
        print(f"{'PASS' if f_ok else 'FAIL'} F Film page polygon = stock saturation read")
    print('ALL PASS' if ok else 'FAILED')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
