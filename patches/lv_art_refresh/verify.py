#!/usr/bin/env python3
"""Emulator verification of the v0.14 LV art refresh (patches/lv_art_refresh). Offline only.

  .venv/bin/python -I patches/lv_art_refresh/verify.py --base BASE.json --new releases/v0.14/edits.json [--jobs 4]

BASE = v0.14 before this fix (git show 97ccd59:releases/v0.14/edits.json). Image ranges read-only.
  S  static: NEW differs from BASE only at the 3 sites + the code edit; code bytes were stock; loader sd_back
     0x605b7420 -> ed_trig 0x605b7340
  W  real setter site 0x607fa355 -> ex_set (manager 0x60827440 = logging stub, stock getter = stub):
     art sector, byte changes   -> manager log == [(111, S(111), a0, a1)] + BASE log; heap/regs/stack == BASE
     art sector, same byte      -> log, heap, regs, stack == BASE (no 111 call)
     other sectors, ALL mode, no card table / bad heap -> == BASE (no 111 call)
  F  fm_pre / fm_post (u_apply sites): old byte stashed at L+1832, replayed store; changed -> facade
     GetValue(111) then SetValue(111, 0, v) once, then ed_poke with a3/sp intact; same -> straight to ed_poke;
     GetValue failing -> no SetValue
  P  package: tools/build_package.build(NEW) decodes to the emulated NEW image; restore == stock
"""
import argparse, importlib.util, json, struct, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m
    s.loader.exec_module(m)
    return m


LX = _load('ep7_lx_verify', ROOT / 'patches/look_extras/verify.py')
RB = _load('ep7_lv_art_refresh_build', ROOT / 'patches/lv_art_refresh/build.py')
EV, Region, run, img, mem, asm = LX.EV, LX.Region, LX.run, LX.img, LX.mem, LX.asm
LE, BASE = EV.LE, EV.BASE
G = LX.G
LOG = 0x18c00000
MGR_STUB = f"""
 mov {LOG:#x},a2
 mov (a2),d3
 mov d3,d2
 asl 4,d2
 add 4,d2
 add d2,a2
 mov d0,(a2)
 mov d1,(4,a2)
 mov a0,(8,a2)
 mov a1,(12,a2)
 inc d3
 mov {LOG:#x},a2
 mov d3,(a2)
 ret [d2,d3,a2],16
"""


def log_of(r):
    b = mem(r, 'log')
    n = struct.unpack_from('<I', b, 0)[0]
    return [struct.unpack_from('<IiII', b, 4 + 16 * i) for i in range(min(n, 8))]


def init(base, new):
    G['base'] = EV.images(json.loads(Path(base).read_text()))[1]
    sp = json.loads(Path(new).read_text())
    G['stock'], G['lay'] = EV.images(sp)
    G['m'] = sp['look_extras']
    G['X'], G['XP'] = G['m']['x_axis'], G['m']['x_prev']
    G['rf'] = sp['lv_art_refresh']


def code_regions(im):
    return LX.code_regions(im)          # its 'xreg' (0x601e323c..0x601e383c) holds our code too


def set_run(im, idv, val, h, blk, all_on):
    gcode, _ = asm(EV.STUB_SGET, LE.STOCK['ep7_sget'])
    mcode, _ = asm(MGR_STUB, 0x60827440)
    src = f' mov {idv:#x},d0\n mov {val & 0xffffffff:#x},d1\n mov 0x0a0a0a0a,a0\n mov 0x1a1a1a1a,a1\n jmp site\n'
    code = asm(src, EV.DRV, dict(site=LE.SET_SITE))[0]
    regs = [Region('drv', EV.DRV, code, 'rx'), img(im, LE.SET_SITE, LE.SET_SITE + 7, 'site'),
            Region('mgr', 0x60827440, mcode, 'rx'), Region('sget', LE.STOCK['ep7_sget'], gcode, 'rx'),
            Region('log', LOG, bytes(4 + 16 * 8), 'rw', True), LX.allf(all_on)] + code_regions(im) + EV.state_regions(h, blk)
    return run(regs, {'pc': EV.DRV}, LE.SET_SITE + 7)


def wrap(v):
    v = max(-6, min(11, v))
    v = v + 6 if v < 0 else v
    return v - 6 if v >= 6 else v


def w_case(args):
    idv, val, label, h, blk, all_on, art_slot = args
    tag = f'W {label} id {idv} v {val} all {all_on}'
    b = set_run(G['base'], idv, val, h, blk, all_on)
    p = set_run(G['lay'], idv, val, h, blk, all_on)
    for n, r in (('base', b), ('new', p)):
        if r['fault'] or r['registers']['pc'] != LE.SET_SITE + 7:
            return tag, f'{n} run {r["fault"]} pc {r["registers"]["pc"]:#x}'
    e = LX.diff_state(b, p, skip=())
    if e:
        return tag, f'state {e}'
    if blk is not None and mem(b, 'heap') != mem(p, 'heap'):
        return tag, 'heap differs'
    lb, lp = log_of(b), log_of(p)
    if len(lb) != 1:
        return tag, f'base log {lb}'
    changed = False
    if art_slot is not None and not all_on:
        o = 32 + 64 * art_slot + 46
        changed = blk[o] != wrap(val)
        if mem(p, 'heap')[o] != wrap(val):
            return tag, 'art byte not written'
    want = ([(111, EV.s_value(111), 0x0a0a0a0a, 0x1a1a1a1a)] if changed else []) + lb
    if lp != want:
        return tag, f'log {lp} != {want}'
    return tag, None


def w_cases():
    X = G['X']
    out = []
    art_ids = [(931, 0), (943, 1), (955, 2), (1659, 3)]
    for idv, k in art_ids:
        for old in (0, 2, 5):
            blk = LX.xblock(X)
            blk[32 + 64 * k + 46] = old
            for val in (-7, -1, 0, 1, 2, 3, 5, 6, 8, 12):
                out.append((idv, val, f'art k{k} old {old}', LX.H_OK, bytes(blk), 0, k))
        out.append((idv, 3, f'art k{k} ALL', LX.H_OK, bytes(LX.xblock(X)), 1, k))
    for idv in (927, 928, 929, 930, 932, 933, 938, 941, 1656):
        out.append((idv, 2, 'other sector', LX.H_OK, bytes(LX.xblock(X)), 0, None))
    for label, h, blk, isx in LX.heap_states():
        if not isx:
            for idv in (931, 1659, 927, 111):
                out.append((idv, 3, label, h, None if blk is None else bytes(blk), 0, None))
    out.append((111, 55, 'picture mode, no table', 0, None, 0, None))
    return out


# ------------------------------------------------------------------ F
FAC, VT, SETL, GETL, PAR = 0x18d00000, 0x18d00100, 0x18d00200, 0x18d00300, 0x18e00000
PBLK, LBLK = 0x18f00000, 0x19000000


def f_case(args):
    k, old, new, get_rc = args
    tag = f'F k{k} old {old} new {new} get {get_rc}'
    im = G['lay']
    rf = {kk: int(v, 16) for kk, v in G['rf']['symbols'].items()}
    fac = asm(f' mov {FAC:#x},a0\n ret [],4\n', 0x607f9062)[0]
    gst = asm(f' mov {GETL:#x},a0\n mov d0,(a0)\n mov a1,(4,a0)\n mov 4,d1\n mov d1,(a1)\n mov {get_rc},d0\n'
              f' mov 0xbad0a1a1,a1\n rets\n', VT + 0x40)[0]
    sst = asm(f' mov {SETL:#x},a0\n mov d0,(a0)\n mov d1,(4,a0)\n mov a1,(8,a0)\n mov (12,a0),d0\n inc d0\n'
              f' mov d0,(12,a0)\n mov 0xbad0a1a1,a1\n rets\n', VT + 0x80)[0]
    vt = struct.pack('<IIIII', VT + 0x80, 0, VT + 0x40, 0, 0)
    P = bytearray(1024)
    P[1016:1020] = struct.pack('<I', LBLK)
    entry = 32 + 64 * k
    P[entry + 46], P[entry + 31] = old, 2
    L = bytearray(2048)
    T = LBLK + 1752
    L[1752 + 46] = new
    regs = [Region('fac', 0x607f9062, fac, 'rx'), Region('vt', VT, vt + bytes(0x40 - len(vt)) + gst + bytes(0x40 - len(gst)) + sst, 'rx'),
            Region('facobj', FAC, struct.pack('<I', VT), 'r'), Region('setl', SETL, bytes(16), 'rw', True),
            Region('getl', GETL, bytes(16), 'rw', True), Region('P', PBLK, bytes(P), 'rw', True), Region('L', LBLK, bytes(L), 'rw', True),
            img(im, 0x601e2c3c, 0x601e2edc, 'fmui'), img(im, RB.CODE_AT, RB.CODE_END, 'rf'),
            img(im, 0x61242a00, 0x61242a10, 'poke')]
    # 1) fm_pre from its site: d0 = entry, a1 = T
    r1 = run(regs, {'pc': 0x601e2e35, 'd0': PBLK + entry, 'a0': 0x0a0a0a0a, 'a1': T}, 0x601e2e3b)
    if r1['fault'] or r1['registers']['pc'] != 0x601e2e3b:
        return tag, f'pre run {r1["fault"]}'
    q = r1['registers']
    lm, pm = mem(r1, 'L'), mem(r1, 'P')
    if lm[1832] != old or pm[entry + 31] != 0 or q['d0'] != 0 or q['a0'] != PBLK + entry or q['a1'] != T \
            or any(q[x] != EV.SENT[x] for x in ('d2', 'd3', 'a2', 'a3')) or q['sp'] != EV.SP0:
        return tag, 'pre: stash/replay/registers wrong'
    if bytes(pm[:entry + 31]) != bytes(P[:entry + 31]) or bytes(lm[:1832]) != bytes(L[:1832]):
        return tag, 'pre: stray store'
    # 2) the copy writes the new byte; fm_post from the final jmp site
    P2 = bytearray(pm)
    P2[entry + 46] = new
    regs2 = [x for x in regs if x.name not in ('P', 'L')] + [Region('P', PBLK, bytes(P2), 'rw', True), Region('L', LBLK, bytes(lm), 'rw', True)]
    r2 = run(regs2, {'pc': 0x601e2e93, 'a2': PBLK, 'd3': k, 'a3': PAR, 'd0': 1}, 0x61242a00)
    if r2['fault'] or r2['registers']['pc'] != 0x61242a00:
        return tag, f'post run {r2["fault"]} pc {r2["registers"]["pc"]:#x}'
    q = r2['registers']
    if q['a3'] != PAR or q['sp'] != EV.SP0 or q['d3'] != k:
        return tag, 'post: a3/sp/d3 not intact'
    g, s = mem(r2, 'getl'), mem(r2, 'setl')
    gid = struct.unpack_from('<I', g, 0)[0]
    sid, sv1, sval, scount = struct.unpack_from('<IIII', s, 0)
    if old == new:
        if gid or scount:
            return tag, 'same byte but facade called'
    else:
        if gid != 111:
            return tag, 'changed but no GetValue(111)'
        if get_rc == 0 and (scount != 1 or sid != 111 or sv1 != 0 or sval != 4):
            return tag, f'SetValue {sid} {sv1} {sval} x{scount}'
        if get_rc != 0 and scount:
            return tag, 'GetValue failed but SetValue called'
    if mem(r2, 'P') != bytes(P2) or mem(r2, 'L') != bytes(lm):
        return tag, 'post: heap store'
    return tag, None


def f_cases():
    return [(k, o, n, rc) for k in range(4) for o in (0, 3, 5) for n in (0, 3, 5) for rc in (0, 1)]


# ------------------------------------------------------------------ S / P
def s_check(base_spec, new_spec):
    b, n = G['base'], G['lay']
    diff = [i + BASE for i in range(len(b)) if b[i] != n[i]]
    ok_spans = [(a, a + len(w)) for a, w, _ in RB.SITES.values()] + [(RB.CODE_AT, RB.CODE_AT + G['rf']['code_len'])]
    bad = [hex(a) for a in diff if not any(lo <= a < hi for lo, hi in ok_spans)]
    st = G['stock']
    code_was_stock = b[RB.CODE_AT - BASE:RB.CODE_END - BASE] == st[RB.CODE_AT - BASE:RB.CODE_END - BASE]
    sb = n[0x605b7420 - BASE:0x605b7425 - BASE]
    sd_ok = sb[0] == 0xdc and 0x605b7420 + struct.unpack_from('<i', sb, 1)[0] == 0x605b7340
    tail_stock = n[RB.CODE_AT + G['rf']['code_len'] - BASE:RB.CODE_END - BASE] == st[RB.CODE_AT + G['rf']['code_len'] - BASE:RB.CODE_END - BASE]
    res = dict(only_sites_and_code=not bad, code_region_was_stock=code_was_stock, sd_back_to_ed_trig=sd_ok,
               claim_tail_stock=tail_stock, bad=bad[:5])
    return all(v for k, v in res.items() if k != 'bad'), res


def p_check(new_path):
    sys.path.insert(0, str(ROOT / 'tools'))
    sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
    import build_package as BP
    import oly_container as oc
    stock = BP.STOCK.read_bytes()
    pkg, restore, _ = BP.build(json.loads(Path(new_path).read_text()), stock)
    main = next(b for b in oc.parse(pkg) if b.kind == 0x100).payload
    rmain = next(b for b in oc.parse(restore) if b.kind == 0x100).payload
    smain = next(b for b in oc.parse(stock) if b.kind == 0x100).payload
    return bytes(main) == G['lay'] and bytes(rmain) == bytes(smain) == G['stock'], len(pkg)


def _w(a):
    return w_case(a)


def _f(a):
    return f_case(a)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--new', required=True)
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--json')
    a = ap.parse_args()
    init(a.base, a.new)
    out = {}
    sok, sres = s_check(a.base, a.new)
    out['S'] = dict(passed=sok, **sres)
    with ProcessPoolExecutor(min(a.jobs, 4), initializer=init, initargs=(a.base, a.new)) as ex:
        wr = list(ex.map(_w, w_cases(), chunksize=8))
        fr = list(ex.map(_f, f_cases(), chunksize=4))
    for name, rs in (('W', wr), ('F', fr)):
        fails = [(t, e) for t, e in rs if e]
        out[name] = dict(passed=not fails, cases=len(rs), fails=fails[:10])
    pok, plen = p_check(a.new)
    out['P'] = dict(passed=pok, package_bytes=plen)
    print(json.dumps(out, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1) + '\n')
    sys.exit(0 if all(v['passed'] for v in out.values()) else 1)


if __name__ == '__main__':
    main()
