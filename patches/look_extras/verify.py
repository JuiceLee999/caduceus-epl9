#!/usr/bin/env python3
"""Emulator verification of the look-extras layer (patches/look_extras, docs/LOOK_EXTRAS.md). Offline only.

  .venv/bin/python -I patches/look_extras/verify.py --editor generated/look_editor_12c/merged.json \
      --layered generated/look_extras/merged.json [--part S,G,W,E,V,M] [--jobs 16] [--json out.json]

Differential against the editor build it layers on (BASE = the --editor spec, LAY = --layered): every run enters
through the real edited words/sites of the image (facade vtable, setter site, COLOR record word, view part word),
with the image-range regions mapped read-only (any store into 0x60020020..0x6191ffe0 faults).

  S  static: LAY differs from BASE only in the extras region + the retargeted words; region bytes were the EVF
     step-2/1 tables; nothing else in the image points into the region; store audit (build) has no absolute store
  G  GetValue/GetDefault: not X -> LAY == BASE (same stop, registers, live stack, *out); X -> the model value / 0
  W  setter: not X -> LAY == BASE; X -> heap == model (grain/effect/WB/dirty; nothing in ALL or sectors 4..11), and
     the state entering 0x60827443 == BASE's stock S edit of that id to its S value (the editor's 12c refresh)
  E  axis key through the record word: H(x_prev) + key + guards -> axis X, child refresh 1..12, ed_poke facade
     get/set of the cursor, d0 1; everything else (other axes, events, guard failures, heap states) LAY == BASE
  V  guide part: not X -> LAY == BASE; X -> kind 5 + the field name of the cursor sector (or the ALL text)
  M  source mutations of the layer: each must make a reduced suite fail
"""
import argparse, importlib.util, json, struct, sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    sys.modules[name] = m
    s.loader.exec_module(m)
    return m


EV = _load('ep7_verify_look_editor_x', ROOT / 'tools/ep7_verify_look_editor.py')   # helpers only (read-only use)
XB = _load('ep7_look_extras_build', HERE / 'build.py')
LE, Region, asm, run, img, mem = EV.LE, EV.Region, EV.asm, EV.run, EV.img, EV.mem
BASE, SENT, SP0, STK = EV.BASE, EV.SENT, EV.SP0, EV.STK
DRV, OUT, PAR, LOG, VOBJ = EV.DRV, EV.OUT, EV.PAR, EV.LOG, EV.VOBJ
H_OK, AXIS, DIRTY, EMARK, EMAGIC = EV.H_OK, EV.AXIS, EV.DIRTY, EV.EMARK, EV.EMAGIC
FACR = EV.FACR
G = {}                                   # per-process globals: base, lay, meta


def init(editor, layered):
    G['base'] = EV.images(json.loads(Path(editor).read_text()))[1]
    sp = json.loads(Path(layered).read_text())
    G['stock'], G['lay'] = EV.images(sp)
    G['m'] = sp['look_extras']
    G['X'] = G['m']['x_axis']
    G['XP'] = G['m']['x_prev']


def init_mut(editor, lay_bytes, meta):
    G['base'] = EV.images(json.loads(Path(editor).read_text()))[1]
    G['lay'], G['m'] = lay_bytes, meta
    G['X'], G['XP'] = meta['x_axis'], meta['x_prev']


def code_regions(im):
    lo, hi = (int(x, 16) for x in G['m']['region'])
    out = [img(im, lo, hi, 'xreg'), img(im, LE.CORE[0], LE.CORE[1], 'core'), img(im, LE.UI[0], LE.UI[1], 'ui'),
           img(im, LE.VIEW[0], LE.VIEW[1], 'view'), img(im, LE.KEYS[0], LE.KEYS[1], 'keys')]
    return out


def allf(all_on):
    return Region('allf', 0x61fc3800, struct.pack('<II', all_on, 0), 'r')


# ------------------------------------------------------------------ model
def s8(b):
    return b - 256 if b >= 128 else b


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def model_get(blk, slot, sec):
    b = blk[32 + 64 * slot:32 + 64 * slot + 64]
    if sec == 0:
        return b[24] if b[24] < 4 else 0
    if sec == 1:
        if 1 <= b[29] <= 5 and b[28] in (1, 2, 3):
            return b[29] if b[28] == 3 else -b[29]
        return 0
    if sec in (2, 3):
        return clamp(s8(b[24 + sec]), -5, 5) if b[25] & 0x81 == 1 else 0
    if sec == 4:                                  # test13b bloom colour +45 (effect 2 with 0 shows red)
        return b[45] if 1 <= b[45] <= 4 else (1 if b[45] == 0 and b[28] == 2 else 0)
    return 0


def model_set(blk, slot, sec, v, all_on):
    e = bytearray(blk)
    if all_on or sec >= 5:
        return e
    o = 32 + 64 * slot
    v = clamp(v, -5, 5)
    if sec == 0:
        e[o + 24] = clamp(v, 0, 3)
    elif sec == 1:
        if e[o + 28] == 2 and e[o + 45] == 0:
            e[o + 45] = 1
        e[o + 28], e[o + 29] = (0, 0) if v == 0 else ((3, v) if v > 0 else (1, -v))
    elif sec == 4:
        e[o + 45] = clamp(v, 0, 4)
    else:
        if e[o + 25] & 0x81 != 1:
            e[o + 26] = e[o + 27] = 0
        e[o + 24 + sec] = v & 0xff
        e[o + 25] = 1 if (e[o + 26] | e[o + 27]) else 0
    e[DIRTY] = 1
    return e


FIELDS = [  # (grain, effect id, strength, wb flags, ab, gm) per slot: every reader branch
    (2, 1, 3, 1, 0xfe, 7), (3, 3, 5, 0, 4, 0xfb), (7, 2, 3, 0x81, 1, 2), (0, 1, 0, 3, 0xf9, 0x80)]
FIELDS2 = [(4, 3, 6, 1, 0x7f, 0x80), (0xff, 0, 0, 0xff, 0xff, 0xff), (0, 1, 5, 1, 6, 0xfa), (3, 3, 1, 2, 3, 3)]


TINTS = {id(FIELDS): (0, 3, 0, 9), id(FIELDS2): (4, 0xff, 1, 0)}   # bloom colour +45 per slot


def xblock(axis, fields=FIELDS, marker=True):
    b = EV.card_block(axis=axis, marker=marker)
    for k, (gr, eid, st, fl, ab, gm) in enumerate(fields):
        o = 32 + 64 * k
        b[o + 24], b[o + 25], b[o + 26], b[o + 27], b[o + 28], b[o + 29] = gr, fl, ab, gm, eid, st
        b[o + 45] = TINTS.get(id(fields), (0, 0, 0, 0))[k]
    return b


def heap_states(quick=False):
    """(label, h, block, is_x)"""
    X = G['X']
    out = [('h=0', 0, None, False), ('h misaligned', H_OK + 1, xblock(X), False), ('h=lim+1', EV.LIM + 1, xblock(X), False)]
    b = xblock(X)
    b[0] ^= 1
    out.append(('no EP7B', H_OK, b, False))
    out.append(('no EP7E', H_OK, xblock(X, marker=False), False))
    for ax in sorted({0, 1, 2, G['XP'], X, X + 1, 255}):
        out.append((f'axis {ax}', H_OK, xblock(ax), ax == X))
    out.append(('axis X, fields 2', H_OK, xblock(X, FIELDS2), True))
    return out[3:6] + out[-3:] if quick else out


IDS = [(927, 0, 0), (928, 0, 1), (929, 0, 2), (930, 0, 3), (931, 0, 4), (938, 0, 11), (939, 1, 0), (940, 1, 1),
       (941, 1, 2), (942, 1, 3), (950, 1, 11), (951, 2, 0), (952, 2, 1), (953, 2, 2), (954, 2, 3), (962, 2, 11),
       (1655, 3, 0), (1656, 3, 1), (1657, 3, 2), (1658, 3, 3), (1666, 3, 11)]
IDS_MISS = [926, 963, 1654, 1667, 111, 1091, 1686, 0, 0xffff, 0x103a3]
IDS_ALL = [(927 + 12 * k + c if k < 3 else 1655 + c, k, c) for k in range(4) for c in range(12)]


def diff_state(s, p, skip=('a2',)):
    for k in EV.REGS:
        if k not in skip and s['registers'][k] != p['registers'][k]:
            return f'{k} {p["registers"][k]:#x} != base {s["registers"][k]:#x}'
    if EV.live_stack(s) != EV.live_stack(p):
        return 'live stack differs'
    return None


def dual(regions_fn, regs, stops):
    """run BASE until the first stop it reaches cleanly, then LAY with that stop."""
    for st in stops:
        b = run(regions_fn(G['base']), regs, st)
        if not b['fault'] and b['registers']['pc'] == st:
            return b, run(regions_fn(G['lay']), regs, st), st
    return None, None, None


# ------------------------------------------------------------------ G
def get_case(args):
    slot_off, idv, label, h, blk, is_x = args
    src = (f' mov 0x60acb0dc,a3\n mov ({slot_off},a3),a3\n mov 0x0a0a0a0a,a0\n mov {OUT:#x},a1\n'
           f' mov {idv:#x},d0\n mov 0x11111111,d1\n mov a3,(0x{OUT + 64:x})\n mov {SENT["a3"]:#x},a3\n'
           f' mov (0x{OUT + 64:x}),a2\n calls (a2)\n')
    code, sy = asm(src, DRV)
    stock_t = LE.STOCK['ep7_get'] if slot_off == 8 else LE.STOCK['ep7_default']

    def regions(im):
        return [Region('drv', DRV, code, 'rx'), Region('out', OUT, b'\x77' * 128, 'rw', True),
                img(im, 0x60acb0d0, 0x60acb180, 'vt', 'r')] + code_regions(im) + EV.state_regions(h, blk, 'r')
    hit = next(((s, c) for i, s, c in IDS_ALL if i == idv & 0xffff), None) if is_x else None   # ids are u16 (stock exthu)
    tag = f'G{slot_off} {label} id {idv}'
    if hit is None:
        b, p, st = dual(regions, {'pc': DRV}, [stock_t, sy['done']])
        if b is None:
            return tag, 'base reached no stop'
        if p['fault'] or p['registers']['pc'] != st:
            return tag, f'lay pc {p["registers"]["pc"]:#x} fault {p["fault"]} (base {st:#x})'
        e = diff_state(b, p)
        if e or mem(b, 'out')[:64] != mem(p, 'out')[:64]:
            return tag, f'not X but differs: {e or "out"}'
        return tag, None
    p = run(regions(G['lay']), {'pc': DRV}, sy['done'])
    if p['fault'] or p['registers']['pc'] != sy['done']:
        return tag, f'X run {p["fault"]} pc {p["registers"]["pc"]:#x}'
    want = model_get(blk, *hit) if slot_off == 8 else 0
    pr = p['registers']
    out = struct.unpack_from('<i', mem(p, 'out'), 0)[0]
    if out != want or pr['d0'] != 0:
        return tag, f'X out {out} d0 {pr["d0"]:#x}, want {want}'
    if pr['sp'] != SP0 or any(pr[k] != SENT[k] for k in ('d2', 'd3', 'a3')) or pr['a0'] != 0x0a0a0a0a or \
            pr['a1'] != OUT or pr['d1'] != 0x11111111:
        return tag, 'X: registers not preserved'
    if mem(p, 'out')[4:64] != b'\x77' * 60:
        return tag, 'X wrote beyond *out'
    return tag, None


def g_cases(quick=False):
    ids = [927, 928, 940, 941, 952, 954, 1658, 931, 926, 111] if quick else [i for i, _, _ in IDS] + IDS_MISS
    return [(off, idv, lab, h, blk, x) for off in (8, 152) for lab, h, blk, x in heap_states(quick) for idv in ids]


# ------------------------------------------------------------------ W
def set_case(args):
    idv, val, label, h, blk, is_x, all_on = args
    stop_mgr, stop_ret = 0x60827443, LE.SET_SITE + 7
    gcode, _ = asm(EV.STUB_SGET, LE.STOCK['ep7_sget'])
    tag = f'W {label} id {idv} v {val} all {all_on}'

    def code_for(v):
        src = f' mov {idv:#x},d0\n mov {v & 0xffffffff:#x},d1\n mov 0x0a0a0a0a,a0\n mov 0x1a1a1a1a,a1\n jmp site\n'
        return asm(src, DRV, dict(site=LE.SET_SITE))[0]

    def regions_with(code, b):
        def f(im):
            return [Region('drv', DRV, code, 'rx'), img(im, LE.SET_SITE, LE.SET_SITE + 7, 'site'),
                    img(im, 0x60827440, 0x60827450, 'mgr'), Region('sget', LE.STOCK['ep7_sget'], gcode, 'rx'),
                    allf(all_on)] + code_regions(im) + EV.state_regions(h, b)
        return f
    hit = next(((s, c) for i, s, c in IDS_ALL if i == idv & 0xffff), None) if is_x else None
    if hit is None:
        b, p, st = dual(regions_with(code_for(val), blk), {'pc': DRV}, [stop_mgr, stop_ret])
        if b is None:
            return tag, 'base reached no stop'
        if p['fault'] or p['registers']['pc'] != st:
            return tag, f'lay pc {p["registers"]["pc"]:#x} fault {p["fault"]}'
        e = diff_state(b, p, skip=())
        if e or (blk is not None and mem(b, 'heap') != mem(p, 'heap')):
            return tag, f'not X but differs: {e or "heap"}'
        return tag, None
    # reference: BASE with the axis byte at S, an S edit of this id to its S value -> stock manager entry
    sblk = bytearray(blk)
    sblk[AXIS] = 0
    ref = run(regions_with(code_for(EV.s_value(idv)), sblk)(G['base']), {'pc': DRV}, stop_mgr)
    p = run(regions_with(code_for(val), blk)(G['lay']), {'pc': DRV}, stop_mgr)
    if ref['fault'] or ref['registers']['pc'] != stop_mgr:
        return tag, f'reference run {ref["fault"]}'
    if p['fault'] or p['registers']['pc'] != stop_mgr:
        return tag, f'X run {p["fault"]} pc {p["registers"]["pc"]:#x}'
    e = diff_state(ref, p, skip=())
    if e:
        return tag, f'X: state at 0x60827443 vs S edit: {e}'
    want = model_set(blk, hit[0], hit[1], val, all_on)
    hp = mem(p, 'heap')
    if hp != bytes(want):
        d = [i for i in range(len(hp)) if hp[i] != want[i]]
        return tag, f'heap differs at {d[:6]}'
    return tag, None


VALS = [-0x80000000, -128, -7, -6, -5, -3, -1, 0, 1, 2, 3, 4, 5, 6, 127, 0x7fffffff]


def w_cases(quick=False):
    ids = [927, 940, 952, 953, 955, 1658, 931, 926, 111] if quick else [927, 928, 929, 930, 931, 938, 939, 940, 941, 942, 952, 953,
                                                              954, 1655, 1656, 1657, 1658, 1666, 926, 963, 111]
    vals = [-6, -1, 0, 4] if quick else VALS
    out = []
    for lab, h, blk, x in heap_states(quick):
        for idv in ids:
            for v in vals:
                out.append((idv, v, lab, h, blk, x, 0))
    X = G['X']
    for idv in ((927, 953) if quick else (927, 940, 953, 1658)):
        for v in (-3, 2):
            out.append((idv, v, 'ALL', H_OK, xblock(X), True, 1))
            out.append((idv, v, 'ALL not X', H_OK, xblock(0), False, 1))
    return out


# ------------------------------------------------------------------ E
def ev_case(args):
    key_rec, ev, label, h, blk, pk, is_trans = args
    kw = G['m']['key_word']
    rec = LE.RECORDS[key_rec] + kw
    dflt = LE.DEF_IMG + kw - 12
    po = EV.parent_obj2(**pk)
    src = (f' mov {rec:#x},a1\n mov (a1),a1\n cmp 0,a1\n bne 1f\n mov ({dflt:#x}),a1\n1:\n'
           f' mov {PAR:#x},a0\n mov {ev:#x},d0\n mov 0x11111111,d1\n'
           f' mov a1,({OUT:#x})\n mov ({OUT:#x}),a2\n mov 0x1a1a1a1a,a1\n calls (a2)\n')
    code, sy = asm(src, DRV)
    scode, _ = asm(EV.STUB_REFRESH, 0x60de3670)
    tag = f'E {key_rec:#x} ev {ev:#x} {label} {pk}'

    def regions(im):
        return [Region('drv', DRV, code, 'rx'), Region('out', OUT, bytes(64), 'rw'),
                img(im, 0x61185b00, 0x61185d00, 'rec', 'r'), img(im, LE.DEF_IMG, LE.DEF_IMG + 48, 'defs', 'r'),
                img(im, 0x60e228e0, 0x60e22900, 'dflt'), Region('par', PAR, bytes(po), 'r'),
                Region('refresh', 0x60de3670, scode, 'rx'),
                Region('log', LOG, struct.pack('<I', LOG + 4) + bytes(124), 'rw', True)] + \
            code_regions(im) + EV.fac_regions(0) + EV.state_regions(h, blk) + [allf(0)]   # 12d ed_info reads ALL
    if not is_trans:
        b, p, st = dual(regions, {'pc': DRV}, [LE.STOCK['ep7_event'], LE.STOCK['ep7_info'], sy['done']])
        if b is None:
            return tag, 'base reached no stop'
        if p['fault'] or p['registers']['pc'] != st:
            return tag, f'lay pc {p["registers"]["pc"]:#x} fault {p["fault"]}'
        e = diff_state(b, p)
        if e or mem(b, 'heap') != mem(p, 'heap') or mem(b, 'log') != mem(p, 'log') or EV.fac_log(b) != EV.fac_log(p):
            return tag, f'not a transition but differs: {e or "heap/log/facade"}'
        return tag, None
    p = run(regions(G['lay']), {'pc': DRV}, sy['done'])
    if p['fault']:
        return tag, f'fault {p["fault"]}'
    pr = p['registers']
    if pr['pc'] != sy['done'] or pr['d0'] != 1 or pr['sp'] != SP0 or any(pr[k] != SENT[k] for k in ('d2', 'd3', 'a3')):
        return tag, f'return state pc {pr["pc"]:#x} d0 {pr["d0"]:#x}'
    lg = mem(p, 'log')
    calls = [struct.unpack_from('<I', lg, 4 + 4 * i)[0] for i in range((struct.unpack_from('<I', lg, 0)[0] - LOG - 4) // 4)]
    if calls != [EV.child_addr(i) for i in range(1, 13)]:
        return tag, f'refresh calls {[hex(c) for c in calls]}'
    cur = {0x13b3: 1091, 0x13b4: 1096, 0x13b5: 1097, 0x140c: 1686}[key_rec]
    got = [x[:2] if x[0] == 1 else x for x in EV.fac_log(p)]
    if got != [(1, cur), (2, cur, 0, 7)]:
        return tag, f'facade calls {got}'
    exp = bytearray(blk)
    exp[AXIS] = G['X']
    if mem(p, 'heap') != bytes(exp):
        return tag, 'heap: more than the axis byte changed'
    return tag, None


def e_cases(quick=False):
    ev_a, ev_b = (int(x, 16) for x in G['m']['events'])
    evs = sorted({ev_a, ev_b, 0x9014, 0x900c, 0x9004})
    out = []
    keys = [0x13b3, 0x140c] if quick else list(LE.RECORDS)
    for lab, h, blk, _ in heap_states(quick):
        ax_ok = blk is not None and h == H_OK and lab.startswith('axis') and blk[AXIS] == G['XP']
        for key in keys:
            for ev in evs:
                out.append((key, ev, lab, h, blk, dict(key=key), ax_ok and ev in (ev_a, ev_b)))
    prev = xblock(G['XP'])
    guards = [dict(key=0x13b3, count=12), dict(key=0x13b3, st16=1), dict(key=0x13b3, st44=5),
              dict(key=0x13b3, bad_child=4), dict(key=0x13b3, null_child=12), dict(key=0x13b4, bad_child=0)]
    for pk in guards:
        bad = pk.get('bad_child', 99) != 0         # child 0 (cursor) is not checked, as in ed_event
        out.append((pk['key'], ev_a, 'guard', H_OK, prev, pk, not bad))
    return out


# ------------------------------------------------------------------ V
FAC2 = f"""
 .set FACR, {FACR:#x}
s_fac:
 mov FACR,a0
 ret [],4
s_get:
 movm [d2,d3,a2,a3],(sp)
 mov (FACR+0x88),d3
 cmp 111,d0
 beq 1f
 mov (FACR+0x84),d3
1:
 mov d3,(a1)
 mov (FACR+0x80),d0
 mov 0xbad0d1d1,d1
 mov 0xbad0a0a0,a0
 mov 0xbad0a1a1,a1
 ret [d2,d3,a2,a3],16
"""
# 12d: stock shows 2755 with ALL off and 2756 with ALL on; the X text is cut at 16 characters together with the
# editor's key-probe code (EV.probe_suffix, '' when the editor is built without the probe).
TXT = {'o': 'Extras: 1-5 only', 'all': 'Extras: no All'}
TINT_TXT = ['5 Bloom Neutral', '5 Bloom Red', '5 Bloom Amber', '5 Bloom Warm', '5 Bloom Cool']
GRAIN = ['1 Grain Off', '1 Grain Low', '1 Grain Medium', '1 Grain High']
SIGNED = {1: ('2 Glow ', '2 Clarity/Glow 0', '2 Clarity +'), 2: ('3 WB Blue ', '3 WB Amber/Blue', '3 WB Amber '),
          3: ('4 WB Magenta ', '4 WB Green/Mag.', '4 WB Green ')}
PM_SLOT = {54: 0, 55: 1, 56: 2, 64: 3}


def x_text(blk, mode, sec):
    """12e Extras label: sector number, field and the value ex_get returns."""
    v = model_get(blk, PM_SLOT[mode], sec)
    if sec == 0:
        return GRAIN[v]
    if sec == 4:
        return TINT_TXT[v]
    neg, zero, pos = SIGNED[sec]
    return zero if v == 0 else (pos + str(v)) if v > 0 else (neg + str(-v))


def fac2(mode, cursor):
    code, sy = asm(FAC2, 0x18980000)
    fac = bytearray(0x400)
    struct.pack_into('<I', fac, 0, FACR + 0x40)
    struct.pack_into('<I', fac, 0x48, sy['s_get'])
    struct.pack_into('<III', fac, 0x80, 0, cursor, mode)
    return [Region('facstub', 0x18980000, code, 'rx'), Region('fac', FACR, bytes(fac), 'r'),
            Region('t_fac', LE.STOCK['ep7_facade'], b'\xdc' + struct.pack('<i', sy['s_fac'] - LE.STOCK['ep7_facade']), 'rx')]


def guide_case(args):
    kind, gid, label, h, blk, is_x, mode, cursor = args
    src = (f' mov {LE.GUIDE_WORD:#x},a1\n mov (a1),a1\n mov {VOBJ:#x},a0\n mov 0x0d0d0d0d,d0\n'
           f' mov 0x11111111,d1\n calls (a1)\n')
    code, sy = asm(src, DRV)
    gcode, _ = asm(EV.GUIDE_STUB, LE.STOCK['ep7_guide'])
    vo = bytearray([0xa5]) * 0x200 + struct.pack('<3I', kind, gid, 0x600d) + bytes(0x1f4)
    tag = f'V {label} kind {kind} id {gid} mode {mode} cur {cursor}'

    def regions(im):
        return [Region('drv', DRV, code, 'rx'), img(im, LE.PARTS_IMG, LE.PARTS_IMG + 24, 'parts', 'r'),
                Region('guide', LE.STOCK['ep7_guide'], gcode, 'rx'), Region('vobj', VOBJ, bytes(vo), 'rw', True)] + \
            code_regions(im) + fac2(mode, cursor) + EV.state_regions(h, blk, 'r')
    b = run(regions(G['base']), {'pc': DRV}, sy['done'])
    p = run(regions(G['lay']), {'pc': DRV}, sy['done'])
    for r in (b, p):
        if r['fault'] or r['registers']['pc'] != sy['done']:
            return tag, f'run {r["fault"]} pc {r["registers"]["pc"]:#x}'
    for k in ('d0', 'd2', 'd3', 'a2', 'a3', 'sp'):
        if b['registers'][k] != p['registers'][k]:
            return tag, f'{k} {p["registers"][k]:#x} != base {b["registers"][k]:#x}'
    if EV.live_stack(b) != EV.live_stack(p):
        return tag, 'live stack differs'
    exp = bytearray(mem(b, 'vobj'))
    txt = None
    if is_x and kind == 4 and gid == 2756:
        txt = TXT['all']
    elif is_x and kind == 4 and gid == 2755 and mode in (54, 55, 56, 64):
        txt = x_text(blk, mode, cursor - 1) if 1 <= cursor <= 5 else TXT['o']
    if txt:
        if len(txt) > 16:
            return tag, f'label {txt!r} > 16'
        struct.pack_into('<H', exp, 44, 5)
        exp[52:118] = b''.join(struct.pack('<H', ord(c)) for c in txt).ljust(66, b'\0')
    pv = mem(p, 'vobj')
    if pv != bytes(exp):
        d = [i for i in range(len(pv)) if pv[i] != exp[i]]
        return tag, f'view differs at {d[:8]} (want {txt!r})'
    return tag, None


def v_cases(quick=False):
    labels = [(4, 2755), (4, 2756), (4, 2055), (0, 0), (5, 2756), (4, 2757)]
    mc = [(54, 1), (55, 2), (56, 3), (64, 4), (54, 5), (64, 12), (54, 0), (11, 1), (0, 2), (55, 5), (56, 5), (64, 6)]
    out = []
    for lab, h, blk, x in heap_states(quick):
        for kind, gid in (labels[:2] if quick else labels):
            for mode, cur in (mc[:6] if quick else mc):
                out.append((kind, gid, lab, h, blk, x, mode, cur))
    return out


# ------------------------------------------------------------------ S
def t_static(editor, layered):
    fails = []
    base = EV.images(json.loads(Path(editor).read_text()))[1]
    sp = json.loads(Path(layered).read_text())
    stock, lay = EV.images(sp)
    m = sp['look_extras']
    lo, hi = (int(x, 16) for x in m['region'])
    kw = m['key_word']
    words = [XB.VT_GET, XB.VT_DEF, XB.GUIDE_WORD] + ([a + kw for a in XB.RECORDS.values()] if kw else [])
    allowed = [(lo, hi), (XB.SET_SITE + 1, XB.SET_SITE + 5)] + [(w, w + 4) for w in words]
    esy = sp['look_editor']['symbols']
    if not kw:                                       # 12e: the editor's ed_cfg_x byte = X
        cx = int(esy['ed_cfg_x'], 16)
        allowed.append((cx, cx + 1))
        if lay[cx - BASE] != m['x_axis'] or base[cx - BASE] != 0:
            fails.append('ed_cfg_x not set to the X page')
        for a in XB.RECORDS.values():
            for o in (36, 44, 48, 52):
                if lay[a + o - BASE:a + o + 4 - BASE] != base[a + o - BASE:a + o + 4 - BASE]:
                    fails.append(f'record {a:#x}+{o} changed by the layer')
    for i in range(len(base)):
        if base[i] != lay[i] and not any(a <= i + BASE < b for a, b in allowed):
            fails.append(f'unexplained diff {i + BASE:#x}')
            break
    if base[lo - BASE:hi - BASE] != stock[lo - BASE:hi - BASE]:
        fails.append('base already uses the EVF region')
    try:
        XB.check_stock(stock)
    except ValueError as e:
        fails.append(str(e))
    sy = {k: int(v, 16) for k, v in m['symbols'].items()}
    if struct.unpack_from('<I', lay, XB.VT_GET - BASE)[0] != sy['ex_get'] or \
            struct.unpack_from('<I', lay, XB.VT_DEF - BASE)[0] != sy['ex_default'] or \
            struct.unpack_from('<I', lay, XB.GUIDE_WORD - BASE)[0] != sy['ex_guide'] or \
            XB.call_target(lay, XB.SET_SITE) != sy['ex_set'] or \
            (kw and any(struct.unpack_from('<I', lay, a + kw - BASE)[0] != sy['ex_event'] for a in XB.RECORDS.values())):
        fails.append('a retarget word does not point at its ex_ entry')
    if any(k == 'abs' for _, _, k in m['stores']):
        fails.append('absolute store')
    used = m['ui'][1] + int(m['ui'][0], 16) - lo
    return fails, used


# ------------------------------------------------------------------ driver
PARTS = dict(G=(g_cases, get_case), W=(w_cases, set_case), E=(e_cases, ev_case), V=(v_cases, guide_case))


def run_parts(parts, quick, jobs, initargs):
    init(*initargs)
    with ProcessPoolExecutor(jobs, initializer=init, initargs=initargs) as ex:
        res = {}
        for p in parts:
            cases_fn, fn = PARTS[p]
            cases = cases_fn(quick)
            out = list(ex.map(fn, cases, chunksize=4))
            res[p] = (len(out), [f'{t}: {e}' for t, e in out if e])
        return res


MUTS = [  # (file, old, new, label)
    ('ex_core.s.in', ' cmp {x_axis},d3\n bne f_miss', ' cmp {x_prev},d3\n bne f_miss', 'X axis compare'),
    ('ex_core.s.in', ' cmp 4,d0\n bcs g_val', ' cmp 5,d0\n bcs g_val', 'grain read bound'),
    ('ex_core.s.in', ' clr d0                           /* bloom: negative */\n sub d2,d0',
     ' mov d2,d0                        /* bloom: negative */\n nop', 'bloom sign'),
    ('ex_core.s.in', ' and 0x81,d0\n cmp 1,d0\n bne g_zero', ' and 0x01,d0\n cmp 1,d0\n bne g_zero', 'WB flag mask (get)'),
    ('ex_core.s.in', ' cmp 3,d1\n ble 6f\n mov 3,d1', ' cmp 4,d1\n ble 6f\n mov 4,d1', 'grain write clamp'),
    ('ex_core.s.in', ' mov (0x61fc3800),d3              /* ALL mode: write nothing */\n cmp 0,d3\n bne s_refresh',
     ' mov (0x61fc3800),d3              /* ALL mode: write nothing */\n cmp 0,d3\n nop\n nop', 'ALL check'),
    ('ex_core.s.in', ' movbu d2,({dirty},a2)', ' movbu d2,({axis},a2)', 'dirty byte'),
    ('ex_core.s.in', ' mov 1,d3\n9:', ' mov 2,d3\n9:', 'bloom id'),
    ('ex_core.s.in', ' beq 11f\n mov 1,d2\n11:', ' nop\n nop\n mov 1,d2\n11:', 'WB 0/0 clears override'),
    ('ex_core.s.in', ' cmp 4,d3\n bcc s_refresh', ' cmp 5,d3\n bcc s_refresh', 'sector bound (set)'),
    ('ex_core.s.in', ' mov (16,sp),d0\n mov d0,mdr\n mov d2,d0', ' mov (12,sp),d0\n mov d0,mdr\n mov d2,d0', 'MDR restore'),
    ('ex_ui.s.in', ' cmp {x_prev},d3\n bne x_no', ' cmp {x_axis},d3\n bne x_no', 'transition from'),
    ('ex_ui.s.in', ' mov {x_axis},d0\n movbu d0,({axis},a2)', ' mov 0,d0\n movbu d0,({axis},a2)', 'transition to'),
    ('ex_ui.s.in', ' cmp 13,d0\n bne x_no', ' cmp 13,d0\n nop\n nop', 'child count guard'),
    ('ex_ui.s.in', ' cmp {x_axis},d3\n bne q_out', ' cmp {x_prev},d3\n bne q_out', 'guide axis'),
    ('ex_ui.s.in', ' mov ex_t_other,a2\n cmp 4,d0', ' mov ex_t_other,a2\n cmp 3,d0', 'guide sector bound'),
]


def mut_one(args):
    editor, layered, k, quick = args
    f, old, new, lab = MUTS[k]
    src = (HERE / f).read_text()
    if src.count(old) != 1:
        return lab, 'pattern not unique'
    m = json.loads(Path(layered).read_text())['look_extras']
    try:
        merged, _ = XB.build(editor, m['key_word'], tuple(int(x, 16) for x in m['events']), m['x_axis'], m['x_prev'],
                             override={f: src.replace(old, new)})
    except Exception as e:                                   # the build itself refusing counts as detected
        return lab, f'detected (build: {e})'
    init_mut(editor, EV.images(merged)[1], merged['look_extras'])
    part = 'V' if 'guide' in lab else ('E' if 'transition' in lab or 'guard' in lab else None)
    parts = [part] if part else ['G', 'W']
    for p in parts:
        cases_fn, fn = PARTS[p]
        for c in cases_fn(True):
            if fn(c)[1]:
                return lab, 'detected'
    return lab, 'NOT detected'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--editor', required=True)
    ap.add_argument('--layered', required=True)
    ap.add_argument('--part', default='S,G,W,E,V,M')
    ap.add_argument('--quick', action='store_true')
    ap.add_argument('--jobs', type=int, default=16)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    parts = a.part.split(',')
    report, ok = {}, True
    if 'S' in parts:
        f, used = t_static(a.editor, a.layered)
        report['S'] = dict(fails=f, bytes_used=used)
        print(f'S static: {"PASS" if not f else "FAIL " + str(f)} ({used} B of the region)')
        ok &= not f
    run_p = [p for p in parts if p in PARTS]
    if run_p:
        res = run_parts(run_p, a.quick, a.jobs, (a.editor, a.layered))
        for p, (n, f) in res.items():
            report[p] = dict(n=n, fails=f)
            print(f'{p}: {n - len(f)}/{n} {"PASS" if not f else "FAIL"}')
            for x in f[:12]:
                print('   ', x)
            ok &= not f
    if 'M' in parts:
        with ProcessPoolExecutor(a.jobs) as ex:
            out = list(ex.map(mut_one, [(a.editor, a.layered, k, True) for k in range(len(MUTS))]))
        det = [o for o in out if o[1].startswith('detected')]
        report['M'] = dict(n=len(out), results=out)
        print(f'M mutations: {len(det)}/{len(out)} detected')
        for lab, r in out:
            if not r.startswith('detected'):
                print('   ', lab, r)
        ok &= len(det) == len(out)
    if a.json:
        a.json.write_text(json.dumps(report, indent=1) + '\n')
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
