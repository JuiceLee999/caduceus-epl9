#!/usr/bin/env python3
"""Emulator verification of the look editor phase 1 + 1s (patches/look_editor, docs/LOOK_EDITOR.md). Offline only.

Takes a merged spec (base + look editor, from patches/look_editor/build.py --base). Applies every edit to the
decoded stock main (expect bytes checked) and runs OUR code natively from the patched image, entering through the
real edited words/sites (facade vtable 0x60acb0dc, setter site 0x607fa355, COLOR records, loader sd_back).
All image-range regions are mapped READ-ONLY, so any store into 0x60020020..0x6191ffe0 faults the run.

  S  static: edits apply to stock; code fits the claims with FF guards; store audit (no absolute stores)
  G  GetValue / GetDefault through the vtable: every miss (id, handle, magic, marker, axis) stops at the stock
     method with registers + stack == the stock run; hits return the heap value (clamped -5..5) / 0, regs kept
  W  setter site: miss -> 0x60827440 with the state at 0x60827443 == stock; hit -> d0 1, exactly the value byte,
     the slot flags bit 1 and dirty change; -6/+6 refused with no heap change
  E  Delete through the COLOR record word: S->L->H->S, child refresh (stub at 0x60de3670) on children 1..12 in
     order; every guard failure and every other event -> stock 0x60e22191 with registers + stack == stock run
     Movie (0x9012) through the record +52 word (stock 0 -> .data default 0x60e228fb): same cycle, guard
     failures -> stock 0x60e228fb with registers + stack == stock run; router 0x60e20cdc with the parent slots
     built as init 0x60e207f7 does: INFO 0x9014 / OK / 0x9015 reach the stock handlers unchanged
  I  init word: axis reset to S, then stock 0x60e20a54 with state == stock run
  T  save from the loader's sd_back: stub file service (ours) at the real fileif/malloc entries; files .NEW .BAK
     .BIN; checks the call sequence, file images (tools/ep7_bundles_bin.check_file + name CRC), read-back, and the
     failure cases (no memory, fopen/fwrite fail, short write, corrupt read-back, no old .BIN), non-press events,
     dirty clear; registers d0-a3 and sp at 0x602c8064 == entry
  M  source mutations of our code: each must make a reduced suite fail

Usage: tools/ep7_verify_look_editor.py MERGED.json [--part S,G,W,E,I,T,M] [--json out.json]
"""
import argparse, importlib.util, json, struct, subprocess, sys, tempfile, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
from penf_emulator import Region, execute  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


LE = _load('ep7_look_editor_build', ROOT / 'patches/look_editor/build.py')
B3 = LE.B3
BIN = _load('ep7_bundles_bin', ROOT / 'tools/ep7_bundles_bin.py')
BASE, TC = B3.BASE, B3.TC
STATE, POOL, LIM, MAGIC, NMAGIC = B3.STATE, B3.POOL, B3.LIM, B3.MAGIC, B3.NMAGIC
EMARK, AXIS, DIRTY, STATUS, EMAGIC = LE.EMARK, LE.AXIS, LE.DIRTY, LE.STATUS, LE.EMAGIC
H_OK = 0x401
P_OK = POOL + H_OK - 1
DRV, OUT, STK, SP0 = 0x18000000, 0x18100000, 0x18200000, 0x18201f00
PAR, LOG = 0x18300000, 0x18400000
S_BUF, FS, STUBS = 0x18500000, 0x18600000, 0x18700000
SENT = dict(d2=0x22222222, d3=0x33333333, a2=0xa2a2a2a2, a3=0xa3a3a3a3, mdr=0x3d3d3d3d)
REGS = ['d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'mdr']
IMG_LO, IMG_HI = 0x60020020, 0x6191ffe0


# ------------------------------------------------------------------ images
def images(spec):
    stock = bytearray(B3.MAIN.read_bytes())
    patched = bytearray(stock)
    for e in spec['edits']:
        if e['kind'] != '0x100':
            continue
        a, exp, new = int(e['addr'], 16), bytes.fromhex(e['expect']), bytes.fromhex(e['new'])
        if bytes(stock[a - BASE:a - BASE + len(exp)]) != exp:
            raise ValueError(f'edit {a:#x}: stock bytes differ')
        patched[a - BASE:a - BASE + len(new)] = new
    return bytes(stock), bytes(patched)


def img(im, lo, hi, name=None, perm='rx'):
    return Region(name or f'i{lo:x}', lo, im[lo - BASE:hi - BASE], perm)


def asm(src, at, syms=None):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'd.s').write_text(' .am33_2\n .text\n .global _start\n_start:\n' + src + '\ndone:\n nop\n nop\n')
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'd.o', t / 'd.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in (syms or {}).items()], '-o', t / 'd.elf', t / 'd.o'],
                       check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'd.elf', t / 'd.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'd.elf'], check=True, capture_output=True, text=True).stdout
        sy = {l.split()[2]: int(l.split()[0], 16) for l in nm.splitlines() if len(l.split()) == 3}
        return (t / 'd.bin').read_bytes(), sy


def state_regions(h, block, perm='rw'):
    regs = [Region('state', STATE - 2, struct.pack('<HH', 0x4242, h), 'r')]
    if block is not None:
        regs.append(Region('heap', P_OK, bytes(block), perm, True))
    return regs


def mem(r, name):
    for x in r['memory']:
        if x['name'] == name:
            return bytes.fromhex(x['hex'])
    return None


def run(regions, regs, stop, limit=2_000_000):
    base = dict(SENT, sp=SP0, d0=0, d1=0, a0=0, a1=0)
    base.update(regs)
    stack = Region('stack', STK, bytes([0x5c]) * 0x2000, 'rw', True)
    return execute([stack] + regions, base, stop, limit=limit, timeout=120)


def live_stack(r):
    """stack bytes at and above sp (below sp is dead stack: our pushes leave residue there)."""
    st, sp = mem(r, 'stack'), r['registers']['sp']
    return st[sp - STK:] if STK <= sp < STK + len(st) else st


def same_state(s, p, skip=('a2',)):
    """registers (the calls target register a2 excluded) and the live stack equal."""
    for k in REGS:
        if k not in skip and s['registers'][k] != p['registers'][k]:
            return f'{k} {p["registers"][k]:#x} != stock {s["registers"][k]:#x}'
    if live_stack(s) != live_stack(p):
        return 'live stack differs'
    return None


def card_block(axis=1, marker=True, names=True):
    data = BIN.build(ROOT / 'bundles/lachlan_v3_names.json')[0]
    blk = bytearray(1024)
    blk[:len(data)] = data
    blk[544:680] = bytes(136)                       # what the --names loader leaves: names, EP7N, +676.. zero
    if names and len(data) == 680:
        blk[544:672] = data[544:672]
        blk[672:676] = struct.pack('<I', NMAGIC)
    for k in range(4):                               # distinct H/L values (-5..5) so every offset matters
        for i in range(12):
            blk[32 + 64 * k + i] = (((i * 3 + k) % 11) - 5) & 0xff
            blk[32 + 64 * k + 12 + i] = (((i * 5 + k + 1) % 11) - 5) & 0xff
    if marker:
        blk[EMARK:EMARK + 4] = struct.pack('<I', EMAGIC)
    blk[AXIS] = axis
    for i in range(688, 1024):
        blk[i] = 0xa5                                # stale heap
    return blk


# ------------------------------------------------------------------ S
def t_static(spec, stock, patched):
    m = spec['look_editor']
    fails = []
    for lo, hi in LE.GUARDS:
        if patched[lo - BASE:hi - BASE] != b'\xff' * (hi - lo):
            fails.append(f'guard {lo:#x} not FF')
    for (at, n), (lo, hi) in ((m['core'], LE.CORE), (m['ui'], LE.UI)):
        at = int(at, 16)
        if not (at == lo and at + n <= hi):
            fails.append(f'{at:#x}+{n} outside claim')
        if patched[at + n - BASE:hi - BASE] != b'\xff' * (hi - at - n):
            fails.append(f'claim tail {at + n:#x} not FF')
    diff = [i + BASE for i in range(len(stock)) if stock[i] != patched[i]]
    ours = [(LE.CORE[0], LE.CORE[1]), (LE.UI[0], LE.UI[1]), (LE.SET_SITE, LE.SET_SITE + 7), (LE.VT_GET, LE.VT_GET + 4),
            (LE.VT_DEF, LE.VT_DEF + 4), (LE.SD_BACK, LE.SD_BACK + 5)] + \
        [(a + o, a + o + 4) for a in LE.RECORDS.values() for o in (4, 36, LE.MOVIE_OFF)]
    others = [(int(e['addr'], 16), int(e['addr'], 16) + len(e['new']) // 2) for e in spec['edits']
              if e.get('source') != 'patches/look_editor']
    for a in diff:
        if not any(lo <= a < hi for lo, hi in ours + others):
            fails.append(f'unexplained diff {a:#x}')
            break
    for lo, hi in ours:
        for c, d in others:
            if lo < d and c < hi and not (lo == LE.SD_BACK and c == LE.LOADER_AT):
                fails.append(f'overlap {lo:#x} with {c:#x}')
    if any(c < 0x6055e7f0 and 0x6055e5c0 < d for c, d in ours):
        fails.append('overlaps clarity/bloom/WB section-2 range')
    if any(c < 0x601e3a3c and 0x601e383c < d for c, d in ours):
        fails.append('overlaps view assist EVF tables')
    if patched[LE.SD_BACK - BASE] != 0xdc or \
            LE.SD_BACK + 5 + struct.unpack_from('<i', patched, LE.SD_BACK - BASE + 1)[0] - 5 != int(m['symbols']['ed_trig'], 16):
        fails.append('sd_back does not jump to ed_trig')
    return fails


# ------------------------------------------------------------------ G
def vt_regions(im):
    return [img(im, 0x60acb0d0, 0x60acb180, 'vt', 'r'), img(im, LE.CORE[0], LE.CORE[1], 'core')]


def get_case(stock, patched, slot_off, idv, h, blk, want):
    """slot_off 8 = GetValue, 152 = GetDefault. want: None = stock fallback, else expected out value."""
    src = (f' mov 0x60acb0dc,a3\n mov ({slot_off},a3),a3\n mov 0x0a0a0a0a,a0\n mov {OUT:#x},a1\n'
           f' mov {idv:#x},d0\n mov 0x11111111,d1\n mov a3,(0x{OUT + 64:x})\n mov {SENT["a3"]:#x},a3\n'
           f' mov (0x{OUT + 64:x}),a2\n calls (a2)\n mov {SENT["a2"]:#x},d1\n')
    # a2 holds the target for calls; restore of a2 is checked against the value at the call (= target)
    code, sy = asm(src, DRV)
    stop_stock = LE.STOCK['ep7_get'] if slot_off == 8 else LE.STOCK['ep7_default']
    res = {}
    for name, im in (('stock', stock), ('patched', patched)):
        regions = [Region('drv', DRV, code, 'rx'), Region('out', OUT, b'\x77' * 128, 'rw', True)] + vt_regions(im) + \
            state_regions(h, blk, 'r')
        r = run(regions, {'pc': DRV}, stop_stock if (want is None or name == 'stock') else sy['done'])
        res[name] = r
    s, p = res['stock'], res['patched']
    if s['fault'] or s['registers']['pc'] != stop_stock:
        return f'stock run did not reach {stop_stock:#x}: {s["fault"]}'
    if p['fault']:
        return f'patched fault {p["fault"]}'
    if want is None:
        if p['registers']['pc'] != stop_stock:
            return f'patched stopped at {p["registers"]["pc"]:#x}, expected stock'
        e = same_state(s, p)
        if e or mem(s, 'out')[:64] != mem(p, 'out')[:64]:     # +64 holds the driver's call target
            return f'fallback: {e or "out differs"}'
        return None
    pr = p['registers']
    if pr['pc'] != sy['done']:
        return f'hit did not return ({pr["pc"]:#x})'
    out = struct.unpack_from('<i', mem(p, 'out'), 0)[0]
    if out != want or pr['d0'] != 0:
        return f'hit out {out} d0 {pr["d0"]:#x}, want {want}'
    # at the call: a2 = target, a3 = SENT; calls/rets keep sp; ours restores d2/d3/a2
    if pr['sp'] != SP0 or pr['d2'] != SENT['d2'] or pr['d3'] != SENT['d3'] or pr['a3'] != SENT['a3'] or \
            pr['a2'] != struct.unpack_from('<I', patched, 0x60acb0dc + slot_off - BASE)[0]:
        return 'hit: callee-saved registers / sp not preserved ' + str({k: hex(pr[k]) for k in ('sp', 'd2', 'd3', 'a2', 'a3')})
    # MDR = the calls return address (set by calls itself); our code does not use mul/div, so it is not checked
    if pr['a0'] != 0x0a0a0a0a or pr['a1'] != OUT:
        return 'hit: a0/a1 changed'
    if mem(p, 'out')[4:64] != b'\x77' * 60:
        return 'hit wrote beyond *out'
    return None


IDS_HIT = [(927, 0, 0), (938, 0, 11), (939, 1, 0), (950, 1, 11), (951, 2, 0), (962, 2, 11), (1655, 3, 0), (1666, 3, 11)]
IDS_MISS = [926, 963, 1654, 1667, 111, 1091, 0, 0xffff, 15488]


def heap_states():
    """(label, h, block, hit?)"""
    out = [('h=0', 0, None, False), ('h=ffff', 0xffff, None, False), ('h misaligned', H_OK + 1, card_block(), False),
           ('h=lim+1', LIM + 1, card_block(), False)]
    b = card_block()
    b[0] ^= 1
    out.append(('no EP7B', H_OK, b, False))
    out.append(('no EP7E', H_OK, card_block(marker=False), False))
    for ax, hit in ((0, False), (1, True), (2, True), (3, False), (255, False)):
        out.append((f'axis {ax}', H_OK, card_block(axis=ax), hit))
    return out


def t_get(stock, patched, quick=False):
    fails, n = [], 0
    for label, h, blk, hit in heap_states():
        for slot_off in (8, 152):
            ids = IDS_HIT[:3] + [(i, None, None) for i in IDS_MISS[:2]] if quick else \
                IDS_HIT + [(i, None, None) for i in IDS_MISS]
            for idv, slot, sec in ids:
                want = None
                if hit and slot is not None:
                    if slot_off == 152:
                        want = 0
                    else:
                        off = 32 + 64 * slot + sec + (12 if blk[AXIS] == 1 else 0)
                        v = struct.unpack('b', bytes([blk[off]]))[0]
                        want = max(-5, min(5, v))
                e = get_case(stock, patched, slot_off, idv, h, blk, want)
                n += 1
                if e:
                    fails.append(f'G {label} slot+{slot_off} id {idv}: {e}')
    # clamp: a +7 / -7 value reads as +5 / -5
    b = card_block(axis=2)
    b[32 + 0] = 7
    b[32 + 1] = 0xf9
    for idv, want in ((927, 5), (928, -5)):
        e = get_case(stock, patched, 8, idv, H_OK, b, want)
        n += 1
        if e:
            fails.append(f'G clamp {idv}: {e}')
    return fails, n


# ------------------------------------------------------------------ W
def set_case(stock, patched, idv, val, h, blk, mode):
    """mode: 'stock' fallback, 'hit', 'bad' (refused)."""
    stop_hit = LE.SET_SITE + 7
    stop_fb = 0x60827443
    src = f' mov {idv:#x},d0\n mov {val & 0xffffffff:#x},d1\n mov 0x0a0a0a0a,a0\n mov 0x1a1a1a1a,a1\n jmp site\n'
    code, sy = asm(src, DRV, dict(site=LE.SET_SITE))
    res = {}
    for name, im in (('stock', stock), ('patched', patched)):
        regions = [Region('drv', DRV, code, 'rx'), img(im, LE.SET_SITE, LE.SET_SITE + 7, 'site'),
                   img(im, 0x60827440, 0x60827450, 'mgr'), img(im, LE.CORE[0], LE.CORE[1], 'core')] + \
            state_regions(h, blk)
        stop = stop_fb if (mode == 'stock' or name == 'stock') else stop_hit
        res[name] = run(regions, {'pc': DRV}, stop)
    s, p = res['stock'], res['patched']
    if s['fault'] or s['registers']['pc'] != stop_fb:
        return f'stock run: {s["fault"]} pc {s["registers"]["pc"]:#x}'
    if p['fault']:
        return f'patched fault {p["fault"]}'
    if mode == 'stock':
        if p['registers']['pc'] != stop_fb:
            return f'patched pc {p["registers"]["pc"]:#x}'
        e = same_state(s, p, skip=())
        if e or (blk is not None and mem(p, 'heap') != bytes(blk)):
            return f'fallback: {e or "heap changed"}'
        return None
    pr = p['registers']
    if pr['pc'] != stop_hit or pr['sp'] != SP0 or any(pr[k] != SENT[k] for k in ('d2', 'd3', 'a2', 'a3')):
        return f'hit return state wrong (pc {pr["pc"]:#x})'
    hp = mem(p, 'heap')
    exp = bytearray(blk)
    if mode == 'hit':
        slot, sec = next((s_, c) for i, s_, c in IDS_HIT + [(928, 0, 1), (945, 1, 6)] if i == idv)
        exp[32 + 64 * slot + sec + (12 if blk[AXIS] == 1 else 0)] = val & 0xff
        exp[32 + 64 * slot + 31] |= 2
        exp[DIRTY] = 1
        if pr['d0'] != 1:
            return f'hit d0 {pr["d0"]}'
    else:
        if pr['d0'] != 0:
            return f'refused d0 {pr["d0"]}'
    if hp != bytes(exp):
        d = [i for i in range(len(hp)) if hp[i] != exp[i]]
        return f'heap bytes differ at {d[:6]}'
    return None


def t_set(stock, patched, quick=False):
    fails, n = [], 0
    for label, h, blk, hit in heap_states():
        for idv in ([927, 945, 1666, 926, 111] if quick else [927, 928, 938, 945, 962, 1655, 1666] + IDS_MISS):
            hitid = any(idv == i for i, _, _ in IDS_HIT + [(928, 0, 1), (945, 1, 6)])
            for val in ((-5, 3) if quick else (-6, -5, 0, 3, 5, 6, 7)):
                mode = 'stock' if not (hit and hitid) else ('hit' if -5 <= val <= 5 else 'bad')
                e = set_case(stock, patched, idv, val, h, blk, mode)
                n += 1
                if e:
                    fails.append(f'W {label} id {idv} v {val}: {e}')
    # flags already set / other slot bits kept
    b = card_block(axis=2)
    b[32 + 64 * 3 + 31] = 1
    e = set_case(stock, patched, 1655, -2, H_OK, b, 'hit')
    n += 1
    if e:
        fails.append(f'W flag-or: {e}')
    return fails, n


# ------------------------------------------------------------------ E / I
STUB_REFRESH = f"""
 mov ({LOG:#x}),a1
 mov a0,(a1)
 add 4,a1
 mov a1,({LOG:#x})
 mov 0x5a5a5a5a,d0
 mov d0,d1
 mov d0,a0
 mov d0,a1
 ret [d2,d3,a2,a3],60
"""


def parent_obj(key=0x13b3, count=13, st16=0, st44=0, bad_child=None, null_child=None):
    base = {0x13b3: 927, 0x13b4: 939, 0x13b5: 951, 0x140c: 1655}.get(key, 927)
    po = bytearray(0x400)
    struct.pack_into('<H', po, 100, key)
    struct.pack_into('<H', po, 120, count)
    struct.pack_into('<I', po, 16, st16)
    struct.pack_into('<I', po, 44, st44)
    for i in range(13):
        ch = PAR + 0x200 + 0x10 * i
        struct.pack_into('<I', po, 124 + 4 * i, 0 if null_child == i else ch)
        cid = (1091 if i == 0 else base + i - 1) + (1 if bad_child == i else 0)
        struct.pack_into('<H', po, 0x200 + 0x10 * i, cid)  # child + 84 is read: map children so +84 lands here
    return po


def child_addr(i):
    return PAR + 0x200 + 0x10 * i - 84


def parent_obj2(**kw):
    po = parent_obj(**kw)
    for i in range(13):
        if kw.get('null_child') != i:
            struct.pack_into('<I', po, 124 + 4 * i, child_addr(i))
    return po


def ev_case(stock, patched, key_rec, ev, h, blk, po, expect, slot=36):
    """expect: 'stock' or 'cycle'. slot: record word 36 (parent+72) or 52 (Movie, parent+88). -> (err, heap after).
    A zero record word means the parent keeps the .data default (init 0x60e207f7), read from the image."""
    rec = LE.RECORDS[key_rec] + slot
    dflt = LE.DEF_IMG + slot - 12
    stock_stop = LE.STOCK['ep7_event'] if slot == 36 else LE.STOCK['ep7_movie']
    src = (f' mov {rec:#x},a1\n mov (a1),a1\n cmp 0,a1\n bne 1f\n mov ({dflt:#x}),a1\n1:\n'
           f' mov {PAR:#x},a0\n mov {ev:#x},d0\n mov 0x11111111,d1\n'
           f' mov a1,({OUT:#x})\n mov ({OUT:#x}),a2\n mov 0x1a1a1a1a,a1\n calls (a2)\n')
    code, sy = asm(src, DRV)
    scode, _ = asm(STUB_REFRESH, 0x60de3670)
    res = {}
    for name, im in (('stock', stock), ('patched', patched)):
        regions = [Region('drv', DRV, code, 'rx'), Region('out', OUT, bytes(64), 'rw'),
                   img(im, 0x61185b00, 0x61185d00, 'rec', 'r'), img(im, LE.UI[0], LE.UI[1], 'ui'),
                   img(im, LE.DEF_IMG, LE.DEF_IMG + 48, 'defs', 'r'), Region('par', PAR, bytes(po), 'r'), Region('refresh', 0x60de3670, scode, 'rx'),
                   Region('log', LOG, struct.pack('<I', LOG + 4) + bytes(124), 'rw', True)] + state_regions(h, blk)
        stop = stock_stop if (expect == 'stock' or name == 'stock') else sy['done']
        res[name] = run(regions, {'pc': DRV}, stop)
    s, p = res['stock'], res['patched']
    if s['fault'] or s['registers']['pc'] != stock_stop:
        return f'stock run {s["fault"]}', None
    if p['fault']:
        return f'patched fault {p["fault"]}', None
    hp = mem(p, 'heap')
    if expect == 'stock':
        if p['registers']['pc'] != stock_stop:
            return f'patched pc {p["registers"]["pc"]:#x}', hp
        e = same_state(s, p)
        if e:
            return f'fallback: {e}', hp
        if blk is not None and hp != bytes(blk):
            return 'fallback changed the heap', hp
        if mem(p, 'log')[:4] != struct.pack('<I', LOG + 4):
            return 'fallback called refresh', hp
        return None, hp
    pr = p['registers']
    if pr['pc'] != sy['done'] or pr['d0'] != 1 or pr['sp'] != SP0 or pr['d2'] != SENT['d2'] or pr['d3'] != SENT['d3'] \
            or pr['a3'] != SENT['a3']:
        return f'cycle return state wrong pc {pr["pc"]:#x} d0 {pr["d0"]:#x}', hp
    lg = mem(p, 'log')
    calls = [struct.unpack_from('<I', lg, 4 + 4 * i)[0] for i in range((struct.unpack_from('<I', lg, 0)[0] - LOG - 4) // 4)]
    if calls != [child_addr(i) for i in range(1, 13)]:
        return f'refresh calls {[hex(c) for c in calls]}', hp
    old = blk[AXIS] if struct.unpack_from('<I', blk, EMARK)[0] == EMAGIC else 0
    want_axis = (old + 1) % 3 if old < 3 else 0
    exp = bytearray(blk)
    if struct.unpack_from('<I', blk, EMARK)[0] != EMAGIC:
        exp[EMARK:EMARK + 4] = struct.pack('<I', EMAGIC)
        exp[DIRTY] = exp[STATUS] = 0
    exp[AXIS] = want_axis
    if hp != bytes(exp):
        d = [i for i in range(len(hp)) if hp[i] != exp[i]]
        return f'heap after cycle differs at {d[:6]}', hp
    return None, hp


def t_event(stock, patched, quick=False):
    fails, n = [], 0
    po = parent_obj2()
    # cycle S -> L -> H -> S on each COLOR key, heap carried
    for key in ((0x13b3,) if quick else tuple(LE.RECORDS)):
        blk = card_block(axis=0)
        p = parent_obj2(key=key)
        for step in range(4):
            e, hp = ev_case(stock, patched, key, 0x9016, H_OK, blk, p, 'cycle')
            n += 1
            if e:
                fails.append(f'E cycle key {key:#x} step {step}: {e}')
                break
            blk = bytearray(hp)
        if blk[AXIS] != 1:
            fails.append(f'E key {key:#x}: axis after 4 presses {blk[AXIS]}')
    e, _ = ev_case(stock, patched, 0x13b3, 0x9016, H_OK, card_block(marker=False), po, 'cycle')   # first use
    n += 1
    if e:
        fails.append(f'E no-marker: {e}')
    guards = [('key 13a9', dict(key=0x13a9)), ('count 12', dict(count=12)), ('state16', dict(st16=1)),
              ('state44', dict(st44=3)), ('child id', dict(bad_child=5)), ('null child', dict(null_child=12))]
    for label, kw in guards:
        e, _ = ev_case(stock, patched, 0x13b3, 0x9016, H_OK, card_block(), parent_obj2(**kw), 'stock')
        n += 1
        if e:
            fails.append(f'E guard {label}: {e}')
    for label, h, blk, _ in heap_states()[:5]:
        e, _ = ev_case(stock, patched, 0x13b3, 0x9016, h, blk, po, 'stock')
        n += 1
        if e:
            fails.append(f'E heap {label}: {e}')
    for ev in ((0x9004, 0x900c) if quick else (0x9004, 0x9006, 0x9008, 0x900a, 0x900c, 0x900d, 0x900e, 0x903e,
                                                0x9017, 0x9015, 0xf855, 0x9016 + 0x10000)):
        e, _ = ev_case(stock, patched, 0x140c, ev, H_OK, card_block(), po, 'stock')
        n += 1
        if e:
            fails.append(f'E event {ev:#x}: {e}')
    f2, n2 = t_movie(stock, patched, quick)
    return fails + f2, n + n2


def t_movie(stock, patched, quick=False):
    """Movie (0x9012) through the record +52 word, and the router with the parent slots as init builds them."""
    fails, n = [], 0
    po = parent_obj2()
    for key in ((0x140c,) if quick else tuple(LE.RECORDS)):
        blk = card_block(axis=0)
        p = parent_obj2(key=key)
        for step in range(4):
            e, hp = ev_case(stock, patched, key, 0x9012, H_OK, blk, p, 'cycle', slot=52)
            n += 1
            if e:
                fails.append(f'EM cycle key {key:#x} step {step}: {e}')
                break
            blk = bytearray(hp)
        if blk[AXIS] != 1:
            fails.append(f'EM key {key:#x}: axis after 4 presses {blk[AXIS]}')
    blk = card_block(axis=0)                         # Movie and Delete share one axis
    for step, (ev, slot) in enumerate(((0x9012, 52), (0x9016, 36), (0x9012, 52))):
        e, hp = ev_case(stock, patched, 0x13b4, ev, H_OK, blk, parent_obj2(key=0x13b4), 'cycle', slot=slot)
        n += 1
        if e:
            fails.append(f'EM mixed step {step}: {e}')
            break
        blk = bytearray(hp)
    if blk[AXIS] != 0:
        fails.append(f'EM mixed: axis {blk[AXIS]} != 0')
    e, _ = ev_case(stock, patched, 0x13b5, 0x9012, H_OK, card_block(marker=False), parent_obj2(key=0x13b5), 'cycle', slot=52)
    n += 1
    if e:
        fails.append(f'EM no-marker: {e}')
    guards = [('key 13a9', dict(key=0x13a9)), ('count 12', dict(count=12)), ('state16', dict(st16=1)),
              ('state44', dict(st44=3)), ('child id', dict(bad_child=5)), ('null child', dict(null_child=12)),
              ('null child 1', dict(null_child=1))]
    for label, kw in guards:
        e, _ = ev_case(stock, patched, 0x13b3, 0x9012, H_OK, card_block(), parent_obj2(**kw), 'stock', slot=52)
        n += 1
        if e:
            fails.append(f'EM guard {label}: {e}')
    for label, h, blk, _ in heap_states()[:5]:      # (no EP7E is a first use: covered above as a cycle)
        e, _ = ev_case(stock, patched, 0x140c, 0x9012, h, blk, po, 'stock', slot=52)
        n += 1
        if e:
            fails.append(f'EM heap {label}: {e}')
    # router 0x60e20cdc (editor vtable slot) with parent+48..+88 built from the records as init 0x60e207f7 does
    for key in ((0x13b3,) if quick else tuple(LE.RECORDS)):
        for ev, want in ((0x9014, 'same'), (0x900c, 'same'), (0x9015, 'same'), (0x9004, 'same72'), (0x9016, 'same72'),
                         (0x9012, 'movie')):
            e = router_case(stock, patched, key, ev, want)
            n += 1
            if e:
                fails.append(f'ER key {key:#x} ev {ev:#x}: {e}')
    return fails, n


def router_case(stock, patched, key, ev, want):
    """want: 'same' = both images reach the same stock handler with equal state; 'same72' = parent+72 target
    (stock 0x60e22191, patched ed_event); 'movie' = stock 0x60e228fb, patched ed_event."""
    def parent(im):
        po = bytearray(parent_obj2(key=key))
        rec = LE.RECORDS[key]
        for i in range(11):
            w = struct.unpack_from('<I', im, rec + 12 + 4 * i - BASE)[0]
            if w == 0:
                w = struct.unpack_from('<I', im, LE.DEF_IMG + 4 * i - BASE)[0]
            struct.pack_into('<I', po, 48 + 4 * i, w)
        return po
    src = f' mov {PAR:#x},a0\n mov {ev:#x},d0\n mov 0x11111111,d1\n mov 0x1a1a1a1a,a1\n mov 0x60e20cdc,a2\n calls (a2)\n'
    code, sy = asm(src, DRV)
    res = {}
    for name, im in (('stock', stock), ('patched', patched)):
        po = parent(im)
        tgt = struct.unpack_from('<I', po, {0x900c: 76, 0x9014: 80, 0x9015: 84, 0x9012: 88}.get(ev, 72))[0]
        res[name] = (tgt, run([Region('drv', DRV, code, 'rx'), img(im, 0x60e20cdc, 0x60e20d3a, 'router'),
                               Region('par', PAR, bytes(po), 'r')], {'pc': DRV}, tgt))
    (ts, s), (tp, p) = res['stock'], res['patched']
    ed = LE.UI[0]
    exp = {'same': (ts, ts), 'same72': (LE.STOCK['ep7_event'], ed), 'movie': (LE.STOCK['ep7_movie'], ed)}[want]
    if (ts, tp) != exp:
        return f'targets {ts:#x}/{tp:#x}, want {exp[0]:#x}/{exp[1]:#x}'
    if want == 'same' and ts in (ed, LE.STOCK['ep7_movie']):
        return 'stock handler expected'
    for r in (s, p):
        if r['fault'] or r['registers']['pc'] != (ts if r is s else tp):
            return f'run {r["fault"]} pc {r["registers"]["pc"]:#x}'
    e = same_state(s, p, skip=('a1',))              # a1 = the slot target
    return f'state at handler: {e}' if e else None


def t_init(stock, patched):
    fails = []
    for label, h, blk, clear in [('axis 2', H_OK, card_block(axis=2), True), ('no marker', H_OK, card_block(axis=2, marker=False), False),
                                 ('h=0', 0, None, False), ('no EP7B', H_OK, None, False)]:
        if label == 'no EP7B':
            blk = card_block(axis=2)
            blk[1] ^= 4
        for key in LE.RECORDS:
            rec = LE.RECORDS[key] + 4
            src = (f' mov {rec:#x},a1\n mov (a1),a1\n mov a1,({OUT:#x})\n mov {PAR:#x},a0\n mov {key:#x},d0\n'
                   f' mov 0x11111111,d1\n mov 0x1a1a1a1a,a1\n mov ({OUT:#x}),a2\n calls (a2)\n')
            code, _ = asm(src, DRV)
            res = {}
            for name, im in (('stock', stock), ('patched', patched)):
                regions = [Region('drv', DRV, code, 'rx'), Region('out', OUT, bytes(64), 'rw'),
                           img(im, 0x61185b00, 0x61185d00, 'rec', 'r'), img(im, LE.UI[0], LE.UI[1], 'ui')] + \
                    state_regions(h, blk)
                res[name] = run(regions, {'pc': DRV}, LE.STOCK['ep7_init'])
            s, p = res['stock'], res['patched']
            err = None
            if s['fault'] or p['fault'] or p['registers']['pc'] != LE.STOCK['ep7_init']:
                err = f'fault/pc {p["fault"]} {p["registers"]["pc"]:#x}'
            elif same_state(s, p):
                err = f'state at stock init: {same_state(s, p)}'
            elif blk is not None:
                exp = bytearray(blk)
                if clear:
                    exp[AXIS] = 0
                if mem(p, 'heap') != bytes(exp):
                    err = 'heap'
            if err:
                fails.append(f'I {label} key {key:#x}: {err}')
    return fails, 16


# ------------------------------------------------------------------ T (save)
FS_SLOT = 0x800                     # per file: +0 exists, +4 size, +8 pos, +12 open mode, +16 data (1024)
# FS control at FS: +0 log ptr, +4 malloc fail, +8 fail-open-w mask, +12 fail-open-r mask, +16 writemax,
#   +20 corrupt-read mask, +24 open count; files at FS+0x1000 + FS_SLOT*k (k: 0 NEW, 1 BAK, 2 BIN); log at FS+0x100
FS_STUB = f"""
 .set FS, {FS:#x}
 .set S_BUF, {S_BUF:#x}
.macro LOG id
 mov (FS),a3
 mov \\id,d3
 mov d3,(a3)
 mov d0,(4,a3)
 mov d1,(8,a3)
 mov a0,(12,a3)
 mov a1,(16,a3)
 add 20,a3
 mov a3,(FS)
.endm
.macro CLOB
 mov 0xbad0d100,d1
 mov 0xbad0a100,a1
.endm
/* file index of path a0 by its last character (W NEW, K BAK, N BIN) -> a2 = slot, d2 = k; -1 if none */
.macro SLOT
 movbu (20,a0),d3
 mov -1,d2
 cmp 0x57,d3
 bne 81f
 clr d2
81:
 cmp 0x4b,d3
 bne 82f
 mov 1,d2
82:
 cmp 0x4e,d3
 bne 83f
 mov 2,d2
83:
 mov d2,d3
 asl 11,d3
 mov FS+0x1000,a2
 add d3,a2
.endm
s_malloc:
 movm [d2,d3,a2,a3],(sp)
 LOG 1
 mov (FS+4),d3
 mov S_BUF,a0
 cmp 0,d3
 beq 1f
 mov 0,a0
1:
 mov 0xbad0d000,d0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [],4
s_free:
 movm [d2,d3,a2,a3],(sp)
 LOG 2
 mov 0xbad0d000,d0
 mov 0xbad0a000,a0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [],4
s_fopen:
 movm [d2,d3,a2,a3],(sp)
 LOG 3
 SLOT
 cmp 0,d2
 blt 9f
 mov 1,d3
 asl d2,d3
 movbu (a1),d0
 cmp 0x77,d0
 bne 2f
 mov (FS+8),d0
 and d3,d0
 bne 9f
 mov 1,d0
 mov d0,(a2)
 clr d0
 mov d0,(4,a2)
 mov d0,(8,a2)
 mov 0x77,d0
 mov d0,(12,a2)
 mov a2,a0
 bra 8f
2:
 mov (FS+12),d0
 and d3,d0
 bne 9f
 mov (a2),d0
 cmp 0,d0
 beq 9f
 clr d0
 mov d0,(8,a2)
 mov 0x72,d0
 mov d0,(12,a2)
 mov a2,a0
 bra 8f
9:
 mov 0,a0
8:
 mov 0xbad0d000,d0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [],4
s_fclose:
 movm [d2,d3,a2,a3],(sp)
 LOG 4
 clr d0
 mov d0,(12,a0)
 mov 0xbad0a000,a0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [d2,a2,a3],16
s_fwrite:
 movm [d2,d3,a2,a3],(sp)
 LOG 5
 mov a1,a2
 mov (12,a2),d3
 cmp 0x77,d3
 bne 9f
 cmp 1,d0
 bne 9f
 mov (FS+16),d2
 cmp d2,d1
 ble 1f
 mov d2,d1
1:
 mov (8,a2),d3
 mov d1,d0
 cmp 0,d1
 beq 3f
2:
 movbu (a0),d2
 mov a2,a3
 add d3,a3
 movbu d2,(16,a3)
 inc a0
 inc d3
 add -1,d1
 bne 2b
3:
 mov d3,(8,a2)
 mov d3,(4,a2)
 bra 8f
9:
 clr d0
8:
 mov 0xbad0a000,a0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [d2,d3,a2,a3],24
s_fread:
 movm [d2,d3,a2,a3],(sp)
 LOG 6
 mov a1,a2
 mov (12,a2),d3
 cmp 0x72,d3
 bne 9f
 cmp 1,d0
 bne 9f
 mov (4,a2),d2
 mov (8,a2),d3
 sub d3,d2
 cmp d1,d2
 ble 1f
 mov d2,d2
 mov d1,d2
1:
 mov d2,d0
 cmp 0,d2
 beq 3f
2:
 mov a2,a3
 add d3,a3
 movbu (16,a3),d1
 movbu d1,(a0)
 inc a0
 inc d3
 add -1,d2
 bne 2b
3:
 mov d3,(8,a2)
 mov a2,d3                        /* corrupt read-back: flip the byte at the buffer start if this file's bit is set */
 add -(FS+0x1000),d3
 lsr 11,d3
 mov 1,d1
 asl d3,d1
 mov (FS+20),d3
 and d1,d3
 beq 8f
 sub d0,a0
 movbu (a0),d1
 xor 0x40,d1
 movbu d1,(a0)
 bra 8f
9:
 clr d0
8:
 mov 0xbad0a000,a0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [d2,d3,a2,a3],24
"""
TRAMPS = dict(malloc=0x60022782, free=0x600227b4, fopen=0x60634fbc, fclose=0x60634fc5, fwrite=0x60635041,
              fread=0x6063514b)
FILES = {0: 'NEW', 1: 'BAK', 2: 'BIN'}


def fs_regions():
    code, sy = asm(FS_STUB, STUBS)
    regs = [Region('fstubs', STUBS, code, 'rx')]
    for k, a in TRAMPS.items():
        regs.append(Region('t_' + k, a, b'\xdc' + struct.pack('<i', sy['s_' + k] - a), 'rx'))
    return regs


def fs_image(files, malloc_fail=0, fail_w=0, fail_r=0, writemax=0x7fffffff, corrupt=0):
    fs = bytearray(0x1000 + FS_SLOT * 3)
    struct.pack_into('<7I', fs, 0, FS + 0x100, malloc_fail, fail_w, fail_r, writemax, corrupt, 0)
    for k, data in files.items():
        o = 0x1000 + FS_SLOT * k
        struct.pack_into('<4I', fs, o, 1, len(data), 0, 0)
        fs[o + 16:o + 16 + len(data)] = data
    return fs


def fs_files(fs):
    out = {}
    for k in range(3):
        o = 0x1000 + FS_SLOT * k
        ex, size = struct.unpack_from('<II', fs, o)
        if ex:
            out[FILES[k]] = bytes(fs[o + 16:o + 16 + size])
    return out


def fs_log(fs):
    end = struct.unpack_from('<I', fs, 0)[0]
    names = {1: 'malloc', 2: 'free', 3: 'fopen', 4: 'fclose', 5: 'fwrite', 6: 'fread'}
    return [names.get(struct.unpack_from('<I', fs, o)[0], '?') for o in range(0x100, end - FS, 20)]


def expected_image(blk):
    n = 680 if struct.unpack_from('<I', blk, 672)[0] == NMAGIC else 544
    b = bytearray(blk[:680])
    if n == 680:
        struct.pack_into('<I', b, 676, zlib.crc32(bytes(b[544:676])) & 0xffffffff)
    struct.pack_into('<I', b, 16, zlib.crc32(bytes(b[:16] + b[20:544])) & 0xffffffff)
    return bytes(b[:n])


def save_case(patched, blk, h=H_OK, event=None, **fsargs):
    ev = B3.EV_PRESS if event is None else event
    old_bin = fsargs.pop('old_bin', None)
    files = {} if old_bin is None else {2: old_bin}
    fs = fs_image(files, **fsargs)
    stack = bytearray([0x5c]) * 0x2000
    struct.pack_into('<I', stack, SP0 - STK + 16, ev)
    regions = [Region('stack', STK, bytes(stack), 'rw', True), img(patched, 0x605b7180, 0x605b7800, 'sec3'),
               img(patched, LE.UI[0], LE.UI[1], 'ui'), Region('fs', FS, bytes(fs), 'rw', True),
               Region('sbuf', S_BUF, b'\xcc' * 2048, 'rw', True)] + fs_regions() + state_regions(h, blk)
    regs = dict(SENT, sp=SP0, pc=LE.SD_BACK, d0=0xd0d0d0d0, d1=0xd1d1d1d1, a0=0xa0a0a0a0, a1=0xa1a1a1a1)
    r = execute(regions, regs, B3.SITE_RET, limit=5_000_000, timeout=120)
    return r


def t_save(stock, patched, quick=False):
    fails, n = [], 0
    blk = card_block(axis=2)
    blk[DIRTY] = 1
    blk[32 + 3] = 4                                        # an edit
    img_n = expected_image(blk)
    old = BIN.build(ROOT / 'bundles/lachlan_v3_names.json')[0]

    def chk(label, r, want_files, want_status, want_dirty=0, want_log=None, blk_in=None):
        nonlocal n
        n += 1
        if r['fault'] or r['registers']['pc'] != B3.SITE_RET:
            fails.append(f'T {label}: fault {r["fault"]} pc {r["registers"]["pc"]:#x}')
            return
        rg = r['registers']
        want = dict(SENT, sp=SP0, d0=0xd0d0d0d0, d1=0xd1d1d1d1, a0=0xa0a0a0a0, a1=0xa1a1a1a1)
        for k in ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp'):
            if rg[k] != want[k]:
                fails.append(f'T {label}: {k} {rg[k]:#x} at 0x602c8064')
                return
        fs = mem(r, 'fs')
        files = fs_files(fs)
        if files != want_files:
            fails.append(f'T {label}: files {[(k, len(v)) for k, v in files.items()]} != {[(k, len(v)) for k, v in want_files.items()]}')
            return
        hp = mem(r, 'heap')
        if hp is not None:
            if want_status is not None and hp[STATUS] != want_status:
                fails.append(f'T {label}: status {hp[STATUS]} != {want_status}')
            if hp[DIRTY] != want_dirty:
                fails.append(f'T {label}: dirty {hp[DIRTY]}')
            exp = bytearray(blk if blk_in is None else blk_in)
            exp[DIRTY], exp[STATUS] = hp[DIRTY], hp[STATUS]
            if hp != bytes(exp):
                fails.append(f'T {label}: other heap bytes changed')
        lg = fs_log(fs)
        if lg.count('malloc') != lg.count('free') + (1 if label == 'no memory' else 0):
            fails.append(f'T {label}: malloc/free unbalanced {lg}')
        if want_log is not None and lg != want_log:
            fails.append(f'T {label}: log {lg}')
        for v in files.values():
            if v in (img_n,) and BIN.check_file(v[:544]):
                fails.append(f'T {label}: written file fails check_file {BIN.check_file(v[:544])}')

    wr = ['fopen', 'fwrite', 'fclose', 'fopen', 'fread', 'fclose']
    full = ['malloc'] + wr + ['fopen', 'fread', 'fclose'] + wr + wr + ['free']
    r = save_case(patched, blk, old_bin=old)
    chk('ok', r, {'NEW': img_n, 'BAK': old, 'BIN': img_n}, 1, want_log=full)
    if len(img_n) != 680 or BIN.check_file(img_n[:544]) or BIN.check_names(img_n[544:680]):
        fails.append(f'T ok: image invalid {BIN.check_file(img_n[:544])} {BIN.check_names(img_n[544:680])}')
    b544 = bytearray(blk)
    b544[672:676] = bytes(4)
    r = save_case(patched, b544, old_bin=old[:544])
    chk('544 no names', r, {'NEW': expected_image(b544), 'BAK': old[:544], 'BIN': expected_image(b544)}, 1, blk_in=b544)
    r = save_case(patched, blk)
    chk('no old BIN', r, {'NEW': img_n, 'BIN': img_n}, 1)
    r = save_case(patched, blk, old_bin=b'x' * 100)
    chk('odd old BIN', r, {'NEW': img_n, 'BIN': img_n}, 1)
    r = save_case(patched, blk, old_bin=old, malloc_fail=1)
    chk('no memory', r, {'BIN': old}, 2, want_log=['malloc'])
    r = save_case(patched, blk, old_bin=old, fail_w=1)
    chk('NEW open fail', r, {'BIN': old}, 3)
    r = save_case(patched, blk, old_bin=old, writemax=100)
    chk('short write', r, {'NEW': img_n[:100], 'BIN': old}, 3)
    r = save_case(patched, blk, old_bin=old, fail_r=1)
    chk('NEW readback open fail', r, {'NEW': img_n, 'BIN': old}, 3)
    r = save_case(patched, blk, old_bin=old, corrupt=1)
    chk('NEW corrupt read-back', r, {'NEW': img_n, 'BIN': old}, 3)
    r = save_case(patched, blk, old_bin=old, corrupt=4)
    bad_old = bytes([old[0] ^ 0x40]) + old[1:]     # the stub also corrupts the read of the old .BIN (-> .BAK)
    chk('BIN corrupt read-back', r, {'NEW': img_n, 'BAK': bad_old, 'BIN': img_n}, 4)
    r = save_case(patched, blk, old_bin=old, fail_w=4)
    chk('BIN open fail', r, {'NEW': img_n, 'BAK': old, 'BIN': old}, 4)
    r = save_case(patched, blk, old_bin=old, fail_w=2)
    chk('BAK fail', r, {'NEW': img_n, 'BIN': img_n}, 1)
    for label, b, ev in (('not dirty', 0, None), ('release event', 1, B3.EV_PRESS ^ 0x100), ('no marker', 2, None)):
        bb = bytearray(blk)
        if b == 0:
            bb[DIRTY] = 0
        if b == 2:
            bb[EMARK] ^= 1
        r = save_case(patched, bb, event=ev, old_bin=old)
        n += 1
        if r['fault'] or r['registers']['pc'] != B3.SITE_RET or fs_log(mem(r, 'fs')) or mem(r, 'heap') != bytes(bb):
            fails.append(f'T {label}: did something ({fs_log(mem(r, "fs")) if not r["fault"] else r["fault"]})')
    for h in (0, 0xffff, H_OK + 1):
        r = save_case(patched, blk, h=h, old_bin=old)
        n += 1
        if r['fault'] or r['registers']['pc'] != B3.SITE_RET or fs_log(mem(r, 'fs')):
            fails.append(f'T h={h:#x}: did something')
    # a second press after the attempt does nothing (dirty cleared)
    r = save_case(patched, blk, old_bin=old)
    hp = mem(r, 'heap')
    r2 = save_case(patched, hp, old_bin=old)
    n += 1
    if fs_log(mem(r2, 'fs')):
        fails.append('T second press wrote again')
    return fails, n


# ------------------------------------------------------------------ M
MUTS = [('ed_core.s.in', ' cmp 12,d2\n bcs 1f', ' cmp 13,d2\n bcs 1f', 'G'),
        ('ed_core.s.in', ' add -704,d2', ' add -703,d2', 'G'),
        ('ed_core.s.in', ' cmp 2,d3\n bcc \\miss', ' cmp 3,d3\n bcc \\miss', 'G'),
        ('ed_core.s.in', ' add 12,a2                        /* Light */', ' add 13,a2', 'G'),
        ('ed_core.s.in', ' cmp 5,d1\n bgt s_bad', ' cmp 6,d1\n bgt s_bad', 'W'),
        ('ed_core.s.in', ' or 2,d1', ' or 4,d1', 'W'),
        ('ed_core.s.in', ' movm (sp),[d2,d3,a2]\n clr d0\n rets', ' movm (sp),[d2,d3]\n clr d0\n rets', 'G'),
        ('ed_ui.s.in', ' cmp 13,d0\n bne e_no', ' cmp 12,d0\n bne e_no', 'E'),
        ('ed_ui.s.in', ' cmp 176,d2', ' cmp 172,d2', 'E'),
        ('ed_ui.s.in', ' cmp 3,d0\n bcs 5f', ' cmp 4,d0\n bcs 5f', 'E'),
        ('ed_ui.s.in', ' mov (44,a3),d0\n cmp 0,d0\n bne e_no', ' mov (44,a3),d0\n cmp 0,d0\n nop\n nop', 'E'),
        ('ed_ui.s.in', ' cmp 0x9012,d0\n beq 1f', ' cmp 0x9013,d0\n beq 1f', 'E'),
        ('ed_ui.s.in', ' btst 4,d0', ' btst 2,d0', 'E'),
        ('ed_ui.s.in', ' bne 7f', ' beq 7f', 'E'),
        ('ed_ui.s.in', ' mov d0,(0,sp)', ' nop\n nop', 'E'),
        ('ed_ui.s.in', ' mov 524,d0', ' mov 523,d0', 'T'),
        ('ed_ui.s.in', ' xor 0xedb88320,d1', ' xor 0xedb88321,d1', 'T'),
        ('ed_ui.s.in', ' cmp d0,d1\n bne w_fail', ' cmp d0,d1\n nop\n nop', 'T'),   # read-back compare removed
        ('ed_core.s.in', ' movbu d0,({dirty},a2)            /* one attempt', ' nop\n nop\n nop /* one attempt', 'T'),
        ('ed_core.s.in', ' mov (8,sp),a0\n mov (12,sp),a1', ' mov (8,sp),a0\n mov (8,sp),a1', 'T')]


def t_mut(spec_base):
    out = []
    orig = LE.source
    for f, old, new, part in MUTS:
        txt = (LE.HERE / f).read_text()
        if txt.count(old) != 1:
            out.append(dict(mutation=f'{f}: {old!r}', detected=None, note='pattern not unique/found'))
            continue

        def src(name, f=f, old=old, new=new):
            s = orig(name)
            if name == f:
                o = B3.subst(old, LE.sub()) if '{' in old else old
                n_ = B3.subst(new, LE.sub()) if '{' in new else new
                s = s.replace(o, n_)
            return s
        LE.source = src
        try:
            _, merged, _ = LE.build(spec_base)
        finally:
            LE.source = orig
        st, pa = images(merged)
        fn = dict(G=lambda: t_get(st, pa), W=lambda: t_set(st, pa), E=lambda: t_event(st, pa),
                  T=lambda: t_save(st, pa))[part]
        try:
            fl, _ = fn()
        except Exception as e:  # noqa: BLE001
            fl = [f'exception {e}']
        out.append(dict(mutation=f'{f}: {old.strip()[:40]!r} -> {new.strip()[:40]!r}', part=part, detected=bool(fl)))
    # spec mutations: the record +52 (Movie) words left stock / pointed at the stock +36 handler
    _, merged, _ = LE.build(spec_base)
    mv = {hex(a + LE.MOVIE_OFF) for a in LE.RECORDS.values()}
    for label, fix in (('record +52 edits dropped', lambda es: [e for e in es if e['addr'] not in mv]),
                       ('record +52 -> 0x60e22191', lambda es: [dict(e, new=struct.pack('<I', LE.STOCK['ep7_event']).hex())
                                                                 if e['addr'] in mv else e for e in es])):
        st, pa = images(dict(merged, edits=fix(merged['edits'])))
        try:
            fl, _ = t_movie(st, pa, quick=True)
        except Exception as e:  # noqa: BLE001
            fl = [f'exception {e}']
        out.append(dict(mutation=f'spec: {label}', part='E', detected=bool(fl)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--base', type=Path, help='base spec (for M: rebuild mutants on it)')
    ap.add_argument('--part', default='S,G,W,E,I,T,M')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.spec.read_text())
    stock, patched = images(spec)
    parts = a.part.split(',')
    results = []
    for p, fn in (('S', lambda: (t_static(spec, stock, patched), 1)), ('G', lambda: t_get(stock, patched)),
                  ('W', lambda: t_set(stock, patched)), ('E', lambda: t_event(stock, patched)),
                  ('I', lambda: t_init(stock, patched)), ('T', lambda: t_save(stock, patched))):
        if p in parts:
            fails, n = fn()
            results.append(dict(part=p, runs=n, passed=not fails, fails=fails[:20]))
            print(f'{p}: {"PASS" if not fails else "FAIL"} ({n} runs)' + ''.join('\n   ' + f for f in fails[:10]), flush=True)
    if 'M' in parts:
        if not a.base:
            sys.exit('M needs --base')
        m = t_mut(a.base)
        det = sum(1 for x in m if x['detected'])
        results.append(dict(part='M', mutations=m, detected=det, total=len(m)))
        print(f'M: {det}/{len(m)} detected' + ''.join(f'\n   MISSED {x["mutation"]}' for x in m if not x['detected']))
    ok = all(r.get('passed', True) for r in results) and all(r.get('detected', 0) == r.get('total', 0) for r in results)
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.spec), results=results, ok=ok), indent=1) + '\n')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
