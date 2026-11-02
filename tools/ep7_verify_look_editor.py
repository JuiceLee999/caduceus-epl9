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
  E  12d INFO (0x9014) through the COLOR record +44 word (stock 0x60e22579, stand-in that toggles ALL at
     0x61fc3800/04 as stock does): S.Single -> stock (ALL on), S.All -> stock INFO called, ALL off, axis L;
     L/H(/>=3) -> next axis (>= 3 -> S); refresh 1..12 + cursor poke, d0 1; stock declining -> its d0, nothing
     else; guards, no table, other events -> stock 0x60e22579 with registers + stack == stock run; router:
     0x9014 -> ed_info, every other event (incl. 0x9012/0x9016, whose record words are stock again) unchanged
  W  12c: a hit then enters 0x60827440 with (id, S value from the stock getter 0x602af887, a0, a1): the state
     at 0x60827443 == the stock run of an S edit to that same value
  V  guide hook (.data init word 0x6025aa98, view part 3): misses leave the view and registers == stock; hits
     rewrite only kind (5) and the 33 text units with the CURRENT state ("Sat Single 9012", "Lgt All o9004", ...)
  K  12d key probe (only when built with it): editor vtable +0 / +68 words log the event code at P+1002 / P+1000
     by the filter rule, then the stock routine with registers + stack == stock run; invalid heap: no store
  I  init word: axis reset to S, then stock 0x60e20a54 with state == stock run
  T  save from the loader's sd_back: stub file service (ours) at the real fileif/malloc entries; files .NEW .BAK
     .BIN; checks the call sequence, file images (tools/ep7_bundles_bin.check_file + name CRC), read-back, and the
     failure cases (no memory, fopen/fwrite fail, short write, corrupt read-back, no old .BIN), non-press events,
     dirty clear; registers d0-a3 and sp at 0x602c8064 == entry
  M  source mutations of our code: each must make a reduced suite fail

Usage: tools/ep7_verify_look_editor.py MERGED.json [--base BASE.json] [--part S,G,W,E,V,K,I,T,M] [--jobs N] [--json out.json]
(--jobs runs the parts and the mutations in one fork pool.)
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
FACR, VOBJ = 0x18900000, 0x18a00000             # 12c: fake facade + call log; fake view object
S_BUF, FS, STUBS = 0x18500000, 0x18600000, 0x18700000
SENT = dict(d2=0x22222222, d3=0x33333333, a2=0xa2a2a2a2, a3=0xa3a3a3a3, mdr=0x3d3d3d3d)
REGS = ['d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'mdr']
IMG_LO, IMG_HI = 0x60020020, 0x6191ffe0


# ------------------------------------------------------------------ images
PROBE = True                                    # key probe built in (spec look_editor.probe); set by images()
SYMS = {}                                       # the editor's symbols (spec look_editor.symbols)
FILM_NAME_ONLY = False                          # v0.18: Film guide = the name alone (spec look_editor.film_label 'name')


def images(spec):
    global PROBE, SYMS, FILM_NAME_ONLY
    m = spec.get('look_editor') or spec.get('meta', {}).get('look_editor') or {}
    if m:
        PROBE, SYMS = bool(m.get('probe', False)), m['symbols']
        FILM_NAME_ONLY = m.get('film_label') == 'name'
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
    for (at, n), (lo, hi) in ((m['core'], LE.CORE), (m['ui'], LE.UI), (m['view'], LE.VIEW)):
        at = int(at, 16)
        if not (at == lo and at + n <= hi):
            fails.append(f'{at:#x}+{n} outside claim')
        if patched[at + n - BASE:hi - BASE] != b'\xff' * (hi - at - n):
            fails.append(f'claim tail {at + n:#x} not FF')
    diff = [i + BASE for i in range(len(stock)) if stock[i] != patched[i]]
    ours = [(LE.CORE[0], LE.CORE[1]), (LE.UI[0], LE.UI[1]), (LE.SET_SITE, LE.SET_SITE + 7), (LE.VT_GET, LE.VT_GET + 4),
            (LE.VT_DEF, LE.VT_DEF + 4), (LE.SD_BACK, LE.SD_BACK + 5), (LE.VIEW[0], LE.VIEW[1]),
            (LE.GUIDE_WORD, LE.GUIDE_WORD + 4), (LE.KEYS[0], LE.KEYS[1])] + \
        [(a + o, a + o + 4) for a in LE.RECORDS.values() for o in (4, LE.INFO_OFF)] + \
        ([(LE.VT_ENTRY, LE.VT_ENTRY + 4), (LE.VT_ROUTER, LE.VT_ROUTER + 4)] if m.get('probe') else [])
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
    for a in LE.RECORDS.values():                    # 12e: +36 = ed_page (page key), +52 Movie stock
        for o in (LE.MOVIE_OFF, 12, 16, 48, LE.PAGE_OFF):
            if patched[a + o - BASE:a + o + 4 - BASE] != stock[a + o - BASE:a + o + 4 - BASE]:
                fails.append(f'record {a:#x}+{o} not stock')
    kat, kn = int(m['keys'][0], 16), m['keys'][1]
    if kat != LE.KEYS[0] or kat + kn > LE.KEYS[1] or patched[kat + kn - BASE:LE.KEYS[1] - BASE] != stock[kat + kn - BASE:LE.KEYS[1] - BASE]:
        fails.append('keys claim')
    if patched[int(m['symbols']['ed_cfg_x'], 16) - BASE] != 0 or \
            struct.unpack_from('<I', patched, int(m['symbols']['ed_cfg_fv'], 16) - BASE)[0] != int(m['symbols']['ed_fm_none'], 16) or \
            struct.unpack_from('<I', patched, int(m['symbols']['ed_cfg_fl'], 16) - BASE)[0] != int(m['symbols']['ed_fm_none'], 16):
        fails.append('layer words are not the editor defaults (run S on the editor-only spec)')
        if struct.unpack_from('<I', patched, a + LE.INFO_OFF - BASE)[0] != int(m['symbols']['ed_info'], 16):
            fails.append(f'record {a:#x}+44 is not ed_info')
    vt = [struct.unpack_from('<I', patched, w - BASE)[0] for w in (LE.VT_ENTRY, LE.VT_ROUTER)]
    want_vt = [int(m['symbols']['ed_oprobe'], 16), int(m['symbols']['ed_rprobe'], 16)] if m.get('probe') else \
        [LE.STOCK['ep7_entry'], LE.STOCK['ep7_router']]
    if vt != want_vt:
        fails.append(f'editor vtable words {[hex(x) for x in vt]}')
    parts = [struct.unpack_from('<I', patched, LE.PARTS_IMG + 4 * i - BASE)[0] for i in range(6)]
    if parts != LE.PARTS[:2] + [int(m['symbols']['ed_guide'], 16)] + LE.PARTS[3:]:
        fails.append(f'view part table {[hex(x) for x in parts]}')
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
# stock settings getter 0x602af887 (call, ret [],4): S(id) = (id & 7) - 3; clobbers d1/a0/a1, keeps d2/d3/a2/a3
STUB_SGET = """
 exthu d0
 and 7,d0
 add -3,d0
 mov 0xbad0d1d1,d1
 mov 0xbad0a0a0,a0
 mov 0xbad0a1a1,a1
 ret [],4
"""


def s_value(idv):
    return ((idv & 0xffff) & 7) - 3


def set_case(stock, patched, idv, val, h, blk, mode):
    """mode: 'stock' fallback, 'hit' (12c: heap write, then the stock manager with the id's S value), 'bad' (refused)."""
    stop_ret = LE.SET_SITE + 7
    stop_fb = 0x60827443
    gcode, _ = asm(STUB_SGET, LE.STOCK['ep7_sget'])
    res = {}
    for name, im in (('stock', stock), ('patched', patched)):
        v = s_value(idv) if (mode == 'hit' and name == 'stock') else val
        src = f' mov {idv:#x},d0\n mov {v & 0xffffffff:#x},d1\n mov 0x0a0a0a0a,a0\n mov 0x1a1a1a1a,a1\n jmp site\n'
        code, sy = asm(src, DRV, dict(site=LE.SET_SITE))
        regions = [Region('drv', DRV, code, 'rx'), img(im, LE.SET_SITE, LE.SET_SITE + 7, 'site'),
                   img(im, 0x60827440, 0x60827450, 'mgr'), img(im, LE.CORE[0], LE.CORE[1], 'core'),
                   Region('sget', LE.STOCK['ep7_sget'], gcode, 'rx')] + state_regions(h, blk)
        stop = stop_ret if (mode == 'bad' and name == 'patched') else stop_fb
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
    hp = mem(p, 'heap')
    exp = bytearray(blk)
    if mode == 'hit':
        if pr['pc'] != stop_fb:
            return f'hit did not reach the manager (pc {pr["pc"]:#x})'
        e = same_state(s, p, skip=())               # == stock S edit of the same id to its current S value
        if e:
            return f'hit: state at 0x60827443: {e}'
        slot, sec = next((s_, c) for i, s_, c in IDS_HIT + [(928, 0, 1), (945, 1, 6)] if i == idv)
        exp[32 + 64 * slot + sec + (12 if blk[AXIS] == 1 else 0)] = val & 0xff
        exp[32 + 64 * slot + 31] |= 2
        exp[DIRTY] = 1
    else:
        if pr['pc'] != stop_ret or pr['sp'] != SP0 or any(pr[k] != SENT[k] for k in ('d2', 'd3', 'a2', 'a3')):
            return f'refused: return state wrong (pc {pr["pc"]:#x})'
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


# 12c facade stand-in at FACR: +0 object (-> vtable +0x40), vtable +0 SetValue, +8 GetValue; control +0x80
# (GetValue result, value it returns); call log at +0x100 (ptr), entries of 16 B: tag (1 get / 2 set), d0, d1, a1.
FAC_STUB = f"""
 .set FACR, {FACR:#x}
s_fac:
 mov FACR,a0
 ret [],4
.macro FLOG tag
 mov (FACR+0x100),a2
 mov \\tag,d3
 mov d3,(a2)
 mov d0,(4,a2)
 mov d1,(8,a2)
 mov a1,(12,a2)
 add 16,a2
 mov a2,(FACR+0x100)
.endm
s_get:
 movm [d2,d3,a2,a3],(sp)
 FLOG 1
 mov (FACR+0x84),d3
 mov d3,(a1)
 mov (FACR+0x80),d0
 mov 0xbad0d1d1,d1
 mov 0xbad0a0a0,a0
 mov 0xbad0a1a1,a1
 ret [d2,d3,a2,a3],16
s_set:
 movm [d2,d3,a2,a3],(sp)
 FLOG 2
 mov 1,d0
 mov 0xbad0d1d1,d1
 mov 0xbad0a0a0,a0
 mov 0xbad0a1a1,a1
 ret [d2,d3,a2,a3],16
"""
FAC_AT = 0x18980000


def fac_regions(getret=0, curval=7):
    code, sy = asm(FAC_STUB, FAC_AT)
    fac = bytearray(0x400)
    struct.pack_into('<I', fac, 0, FACR + 0x40)
    struct.pack_into('<I', fac, 0x40, sy['s_set'])
    struct.pack_into('<I', fac, 0x48, sy['s_get'])
    struct.pack_into('<II', fac, 0x80, getret, curval)
    struct.pack_into('<I', fac, 0x100, FACR + 0x104)
    return [Region('facstub', FAC_AT, code, 'rx'), Region('fac', FACR, bytes(fac), 'rw', True),
            Region('t_fac', LE.STOCK['ep7_facade'], b'\xdc' + struct.pack('<i', sy['s_fac'] - LE.STOCK['ep7_facade']), 'rx')]


def fac_log(r):
    f = mem(r, 'fac')
    end = struct.unpack_from('<I', f, 0x100)[0] - FACR
    return [struct.unpack_from('<4I', f, o) for o in range(0x104, end, 16)]


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


# 12d: stand-in for the stock INFO handler 0x60e22579 (calls entry, ret [d2,d3,a2,a3],56). Logs (d0, d1, a0) at
# ILOG+4.. (ptr at ILOG); ILOG+0x40: decline (1 = leave ALL as it is), ILOG+0x44: the d0 it returns. Otherwise it
# toggles ALL as stock does: either flag set -> both 0, else 0x61fc3800 = 1.
ILOG = 0x18b00000
INFO_STUB = f"""
 .set IL, {ILOG:#x}
 movm [d2,d3,a2,a3],(sp)
 add -40,sp
 mov (IL),a2
 mov d0,(a2)
 mov d1,(4,a2)
 mov a0,(8,a2)
 add 12,a2
 mov a2,(IL)
 mov (IL+0x40),d0
 cmp 0,d0
 bne 2f
 mov (0x61fc3800),d0
 mov (0x61fc3804),d1
 or d1,d0
 beq 1f
 clr d0
 mov d0,(0x61fc3800)
 mov d0,(0x61fc3804)
 bra 2f
1:
 mov 1,d0
 mov d0,(0x61fc3800)
2:
 mov 0x2d2d2d2d,d2
 mov d2,d3
 mov d2,a2
 mov d2,a3
 mov (IL+0x44),d0
 mov 0xbad0d1d1,d1
 mov 0xbad0a0a0,a0
 mov 0xbad0a1a1,a1
 ret [d2,d3,a2,a3],56
"""


def ilog(r):
    m = mem(r, 'ilog')
    end = struct.unpack_from('<I', m, 0)[0] - ILOG
    return [struct.unpack_from('<3I', m, o) for o in range(4, end, 12)]


FVS = 0x18c00000                                 # stand-in fm_valid: logs a2 at FVS+0x100, returns (FVS+0x104)
FV_STUB = f"""
 mov a2,({FVS + 0x100:#x})
 mov ({FVS + 0x104:#x}),d0
 mov 0xbad0d1d1,d1
 mov 0xbad0a0a0,a0
 rets
"""


def cfg_image(im, cfg_x=0, fv=False):
    """the patched image with the layer words set as the extras / film builds set them (ed_cfg_x byte, ed_cfg_fv
    word -> the fm_valid stand-in at FVS)."""
    if 'ed_cfg_x' not in SYMS:
        return im
    b = bytearray(im)
    b[int(SYMS['ed_cfg_x'], 16) - BASE] = cfg_x
    if fv is not None:
        struct.pack_into('<I', b, int(SYMS['ed_cfg_fv'], 16) - BASE, FVS if fv is not False else int(SYMS['ed_fm_none'], 16))
    return bytes(b)


def next_page(ax, cfg_x, fv):
    """12e page order S(0) -> H(2) -> L(1) -> F(3, film loaded) -> X(cfg_x, extras) -> S."""
    if ax == 0:
        return 2
    if ax == 2:
        return 1
    if ax == 1 and fv:
        return 3
    if ax in (1, 3):
        return cfg_x
    return 0


def page_model(blk, flags, ev, cfg_x=0, fv=False, valid=True):
    """-> (expect, new axis). expect: 'stock', 'step', 'swallow' (INFO off the Saturation page: d0 1, nothing else)."""
    if not valid:
        return 'stock', None
    marker = struct.unpack_from('<I', blk, EMARK)[0] == EMAGIC
    ax = blk[AXIS] if marker else 0
    all_on = bool(flags[0] or flags[1])
    if ax == 0 and not all_on:
        return 'stock', None                         # Saturation: stock INFO turns ALL on
    return 'step', next_page(ax, cfg_x, fv)


def ev_case(stock, patched, key_rec, ev, h, blk, po, expect, flags=(0, 0), getret=0, decline=0, iret=1, valid=True,
            cfg_x=0, fv=False, word=None):
    """an event through the record +44 (INFO) or +36 (page key, every other event) word. expect: 'stock' (both
    images stop at the stock handler of that word with equal state), 'step' (page step: refresh 1..12, cursor poke,
    d0 1), 'swallow' (d0 1, nothing else) or 'declined' (ALL on, the stock INFO handler left it on: its d0 back,
    nothing else). -> (err, heap after, flags after)."""
    if word is None:
        word = LE.INFO_OFF if ev == 0x9014 else LE.PAGE_OFF
    rec = LE.RECORDS[key_rec] + word
    stop_stock = LE.STOCK['ep7_info'] if word == LE.INFO_OFF else LE.STOCK['ep7_event']
    src = (f' mov {rec:#x},a1\n mov (a1),a1\n mov {PAR:#x},a0\n mov {ev:#x},d0\n mov 0x11111111,d1\n'
           f' mov a1,({OUT:#x})\n mov ({OUT:#x}),a2\n mov 0x1a1a1a1a,a1\n calls (a2)\n')
    code, sy = asm(src, DRV)
    scode, _ = asm(STUB_REFRESH, 0x60de3670)
    icode, _ = asm(INFO_STUB, LE.STOCK['ep7_info'])
    fcode, _ = asm(FV_STUB, FVS)
    res = {}
    keys = LE.KEYS
    for name, im in (('stock', stock), ('patched', cfg_image(patched, cfg_x, fv))):
        regions = [Region('drv', DRV, code, 'rx'), Region('out', OUT, bytes(64), 'rw'),
                   img(im, 0x61185b00, 0x61185d00, 'rec', 'r'), img(im, LE.UI[0], LE.UI[1], 'ui'),
                   img(im, keys[0], keys[1], 'keys'),
                   Region('par', PAR, bytes(po), 'r'), Region('refresh', 0x60de3670, scode, 'rx'),
                   Region('log', LOG, struct.pack('<I', LOG + 4) + bytes(124), 'rw', True),
                   Region('info', LE.STOCK['ep7_info'], icode, 'rx'),
                   Region('evt', LE.STOCK['ep7_event'], b'\x00' * 16, 'rx'),
                   Region('ilog', ILOG, struct.pack('<I', ILOG + 4) + bytes(60) + struct.pack('<II', decline, iret)
                          + bytes(56), 'rw', True),
                   Region('fvs', FVS, fcode, 'rx'),
                   Region('fvd', FVS + 0x100, struct.pack('<II', 0, int(bool(fv))) + bytes(0xf8), 'rw', True),
                   Region('allf', 0x61fc3800, struct.pack('<II', *flags) + bytes(8), 'rw', True)] + \
            fac_regions(getret) + state_regions(h, blk)
        stop = stop_stock if (expect == 'stock' or name == 'stock') else sy['done']
        res[name] = run(regions, {'pc': DRV}, stop)
    s, p = res['stock'], res['patched']
    if s['fault'] or s['registers']['pc'] != stop_stock:
        return f'stock run {s["fault"]}', None, None
    if p['fault']:
        return f'patched fault {p["fault"]}', None, None
    hp, fl = mem(p, 'heap'), struct.unpack('<II', mem(p, 'allf')[:8])
    lg = mem(p, 'log')
    calls = [struct.unpack_from('<I', lg, 4 + 4 * i)[0] for i in range((struct.unpack_from('<I', lg, 0)[0] - LOG - 4) // 4)]
    exp = None if blk is None else bytearray(blk)
    if valid and blk is not None and struct.unpack_from('<I', blk, EMARK)[0] != EMAGIC:
        exp[EMARK:EMARK + 4] = struct.pack('<I', EMAGIC)      # first use since the load: marker, page S
        exp[AXIS] = exp[DIRTY] = exp[STATUS] = 0
    fvlog = struct.unpack_from('<I', mem(p, 'fvd'), 0)[0]
    if expect == 'stock':
        if p['registers']['pc'] != stop_stock:
            return f'patched pc {p["registers"]["pc"]:#x}', hp, fl
        e = same_state(s, p)
        if e:
            return f'fallback: {e}', hp, fl
        if blk is not None and hp != bytes(exp if valid else blk):
            return 'fallback changed the heap', hp, fl
        if calls or fac_log(p) or ilog(p) or fl != tuple(flags) or fvlog:
            return 'fallback did something (refresh/facade/stock INFO/flags/fm_valid)', hp, fl
        return None, hp, fl
    pr = p['registers']
    if pr['pc'] != sy['done'] or pr['sp'] != SP0 or pr['d2'] != SENT['d2'] or pr['d3'] != SENT['d3'] \
            or pr['a3'] != SENT['a3']:
        return f'return state wrong pc {pr["pc"]:#x} d0 {pr["d0"]:#x}', hp, fl
    il = ilog(p)
    all_on = bool(flags[0] or flags[1])
    if expect == 'swallow':
        if pr['d0'] != 1 or calls or fac_log(p) or il or fl != tuple(flags) or hp != bytes(exp) or fvlog:
            return f'swallow: d0 {pr["d0"]:#x} refresh {len(calls)} facade {fac_log(p)} info {il} flags {fl}', hp, fl
        return None, hp, fl
    if il != ([(0x9014, 0x11111111, PAR)] if all_on else []):
        return f'stock INFO calls {il}', hp, fl
    if expect == 'declined':
        if pr['d0'] != iret or calls or fac_log(p) or fl != tuple(flags) or fvlog:
            return f'declined: d0 {pr["d0"]:#x} refresh {len(calls)} facade {fac_log(p)} flags {fl}', hp, fl
        if hp != bytes(exp):
            return 'declined changed the heap', hp, fl
        return None, hp, fl
    if pr['d0'] != 1:
        return f'step d0 {pr["d0"]:#x}', hp, fl
    if fl != (0, 0):
        return f'ALL not off after a step: {fl}', hp, fl
    if calls != [child_addr(i) for i in range(1, 13)]:
        return f'refresh calls {[hex(c) for c in calls]}', hp, fl
    cur = {0x13b3: 1091, 0x13b4: 1096, 0x13b5: 1097, 0x140c: 1686}[struct.unpack_from('<H', po, 100)[0]]
    fc = fac_log(p)
    want = [(1, cur)] + ([(2, cur, 0, 7)] if getret == 0 else [])
    got = [x[:2] if x[0] == 1 else x for x in fc]
    if got != want or (fc and not (STK <= fc[0][3] < SP0)):
        return f'facade calls {got} != {want}', hp, fl
    ax = exp[AXIS]
    if fv is not False and ax == 1 and fvlog != P_OK:
        return f'fm_valid not called with a2 = P ({fvlog:#x})', hp, fl
    if (ax != 1 or fv is False) and fvlog:
        return 'fm_valid called off the Light page', hp, fl
    exp[AXIS] = next_page(ax, cfg_x, fv)
    if hp != bytes(exp):
        d = [i for i in range(len(hp)) if hp[i] != exp[i]]
        return f'heap after step differs at {d[:6]} (axis {hp[AXIS]} want {exp[AXIS]})', hp, fl
    return None, hp, fl


PAGE_NAMES = {0: 'S', 1: 'L', 2: 'H', 3: 'F', 4: 'X'}


def t_event(stock, patched, quick=False):
    """12e: page key (MENU 0x900e / PLAYBACK 0x9010 via record +36) cycles S -> H -> L -> (F) -> (X) -> S; INFO (record
    +44) is the stock ALL toggle on S and does nothing elsewhere; guards, no table == stock; router."""
    fails, n = [], 0

    def one(label, *a, **kw):
        nonlocal n
        n += 1
        e, hp, fl = ev_case(stock, patched, *a, **kw)
        if e:
            fails.append(f'E {label}: {e}')
        return e, hp, fl
    # full INFO cycles with each layer configuration (state carried); the stock step S.Single -> S.All is emulated
    for cfg_x, fv, want in ((0, False, 'S1 SA H L S1'), (4, False, 'S1 SA H L X S1'), (0, True, 'S1 SA H L F S1'),
                            (4, True, 'S1 SA H L F X S1')):
        for key in ((0x13b3,) if quick else tuple(LE.RECORDS)):
            blk, fl, seen = card_block(axis=0), (0, 0), ['S1']
            for step in range(len(want.split()) - 1):
                exp, _ = page_model(blk, fl, 0x9014, cfg_x, fv)
                e, hp, fl2 = one(f'cycle x{cfg_x} fv{int(fv)} key {key:#x} step {step}', key, 0x9014, H_OK, blk,
                                 parent_obj2(key=key), exp, flags=fl, cfg_x=cfg_x, fv=fv)
                if e:
                    break
                blk = bytearray(hp)
                fl = (1, 0) if exp == 'stock' else fl2
                p = PAGE_NAMES.get(blk[AXIS], '?')
                seen.append(p + ('A' if fl[0] or fl[1] else '1') if p == 'S' else p)
            if ' '.join(seen) != want and not fails:
                fails.append(f'E cycle x{cfg_x} fv{int(fv)} key {key:#x}: {seen} != {want}')
    for ax in ((0, 1, 2, 3, 4) if quick else (0, 1, 2, 3, 4, 5, 255)):
        for flags in ((0, 0), (1, 0)) if quick else ((0, 0), (1, 0), (0, 1), (1, 1)):
            for cfg_x, fv in (((4, True),) if quick else ((0, False), (4, True), (4, False), (0, True))):
                blk = card_block(axis=ax)
                exp, _ = page_model(blk, flags, 0x9014, cfg_x, fv)
                one(f'axis {ax} flags {flags} x{cfg_x} fv{int(fv)}', 0x13b4, 0x9014, H_OK, blk,
                    parent_obj2(key=0x13b4), exp, flags=flags, cfg_x=cfg_x, fv=fv)
    one('no marker', 0x13b5, 0x9014, H_OK, card_block(axis=2, marker=False), parent_obj2(key=0x13b5), 'stock')
    one('no marker ALL on', 0x13b5, 0x9014, H_OK, card_block(axis=2, marker=False), parent_obj2(key=0x13b5), 'step',
        flags=(1, 0))
    one('declined', 0x140c, 0x9014, H_OK, card_block(axis=0), parent_obj2(key=0x140c), 'declined', flags=(1, 0),
        decline=1, iret=3)
    one('declined axis 2', 0x13b3, 0x9014, H_OK, card_block(axis=2), parent_obj2(), 'declined', flags=(0, 1),
        decline=1, iret=0)
    one('poke get-fail', 0x13b5, 0x9014, H_OK, card_block(axis=1), parent_obj2(key=0x13b5), 'step', getret=0xf0000016)
    guards = [('key 13a9', dict(key=0x13a9)), ('count 12', dict(count=12)), ('state16', dict(st16=1)),
              ('state44', dict(st44=3)), ('child id', dict(bad_child=5)), ('null child', dict(null_child=12)),
              ('null child 1', dict(null_child=1))]
    for label, kw in guards:
        for ax, flags in ((1, (0, 0)), (0, (1, 0)), (3, (0, 0))):
            one(f'guard {label} axis {ax}', 0x13b3, 0x9014, H_OK, card_block(axis=ax), parent_obj2(**kw), 'stock',
                flags=flags, valid=False, cfg_x=4, fv=True)
    for label, h, blk, _ in heap_states()[:5]:
        for flags in ((0, 0), (1, 0)):
            one(f'heap {label} flags {flags}', 0x140c, 0x9014, h, blk, parent_obj2(key=0x140c), 'stock', flags=flags,
                valid=False, cfg_x=4, fv=True)
    for ev in (0x900e, 0x9010, 0x9015, 0x9012, 0x9016, 0x9004, 0x900c, 0x9014 + 0x10000, 0):
        one(f'+44 event {ev:#x}', 0x13b3, ev, H_OK, card_block(axis=1), parent_obj2(), 'stock', valid=False,
            word=LE.INFO_OFF, cfg_x=4, fv=True)
    # router 0x60e20cdc with parent+48..+88 built from the records as init 0x60e207f7 does
    for key in ((0x13b3,) if quick else tuple(LE.RECORDS)):
        for ev, want in ((0x9014, 'info'), (0x900c, 'same'), (0x9015, 'same'), (0x9012, 'same'), (0x9004, 'same'),
                         (0x900e, 'same'), (0x9010, 'same'), (0x9016, 'same')):
            e = router_case(stock, patched, key, ev, want)
            n += 1
            if e:
                fails.append(f'ER key {key:#x} ev {ev:#x}: {e}')
    return fails, n


def router_case(stock, patched, key, ev, want):
    """want: 'same' = both images reach the same stock handler with equal state; 'info' = parent+80 target
    (stock 0x60e22579, patched ed_info); 'page' = parent+72 (stock 0x60e22191, patched ed_page)."""
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
    ours = {int(v, 16) for v in SYMS.values()}
    if want == 'info':
        if (ts, tp) != (LE.STOCK['ep7_info'], int(SYMS['ed_info'], 16)):
            return f'targets {ts:#x}/{tp:#x}'
    elif want == 'page':
        if (ts, tp) != (LE.STOCK['ep7_event'], int(SYMS['ed_page'], 16)):
            return f'targets {ts:#x}/{tp:#x}'
    elif ts != tp or ts in ours:
        return f'targets {ts:#x}/{tp:#x}, want the same stock handler'
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
                if PROBE and label in ('axis 2', 'no marker'):
                    exp[LE.PROBE_R:LE.PROBE_O + 2] = bytes(4)       # probe slots cleared on open
                if mem(p, 'heap') != bytes(exp):
                    err = 'heap'
            if err:
                fails.append(f'I {label} key {key:#x}: {err}')
    return fails, 16


# ------------------------------------------------------------------ V (12c guide label)
# Stand-in for the stock part 0x60decbfc (calls entry, ret [d2,d3,a2,a3],60): writes the guide label the way its
# tail 0x60decfdc does (kind/id from a control block at VOBJ+0x200, (6) = 2) plus two neighbouring state bytes,
# clobbers every register and returns the control value in d0.
GUIDE_STUB = f"""
 .set CT, {VOBJ + 0x200:#x}
 movm [d2,d3,a2,a3],(sp)
 add -44,sp
 mov a0,a3
 mov (CT),d0
 movhu d0,(44,a3)
 mov (CT+4),d0
 movhu d0,(48,a3)
 mov 2,d0
 movhu d0,(50,a3)
 mov 1,d0
 movbu d0,(43,a3)
 movbu d0,(118,a3)
 mov 0x2d2d2d2d,d2
 mov d2,d3
 mov d2,a2
 mov d2,a3
 mov (CT+8),d0
 mov 0xbad0d1d1,d1
 mov 0xbad0a0a0,a0
 mov 0xbad0a1a1,a1
 ret [d2,d3,a2,a3],60
"""
# 12d: stock writes 2755 when ALL is off (0x60decf5b) and 2756 when ALL is on (0x60decf21): the label shows the
# CURRENT state.
PAGE_TXT = {0: 'Saturation', 1: 'Light', 2: 'Hue'}
SUFFIX = {2755: '', 2756: ' - All'}
PM_SLOT = {54: 0, 55: 1, 56: 2, 64: 3}


def probe_suffix(blk):
    """the key-probe text ed_probe appends ('' without the probe)."""
    if not PROBE:
        return ''
    r, o = struct.unpack_from('<HH', blk, LE.PROBE_R)
    return f' {r:04X}' if r == o else f' o{o:04X}'


def film_text(blk, k, star=False):
    if struct.unpack_from('<I', blk, 672)[0] == NMAGIC and blk[544 + 16 * k]:
        nm = bytes(blk[544 + 16 * k:560 + 16 * k]).split(b'\0')[0].decode()
    else:
        nm = 'Stock' if blk[32 + 64 * k + 31] == 0 else 'Custom'
    ln = len(nm) + (1 if star else 0)                  # 13: '*' = the slot differs from its picked look
    pre = '' if FILM_NAME_ONLY else 'Film: ' if ln <= 10 else 'Film ' if ln == 11 else ''
    return (pre + nm)[:16 - (1 if star else 0)] + ('*' if star else '')


def guide_text(gid, axis, blk, pm=54, star=False):
    """None = the stock label stays."""
    if axis == 3:
        if pm not in PM_SLOT:
            return None
        return film_text(blk, PM_SLOT[pm], star)
    return (PAGE_TXT[axis] + SUFFIX[gid] + probe_suffix(blk))[:16]


def guide_case(stock, patched, kind, gid, h, blk, want_axis, pm=54, getret=0, extra=None, star=False):
    """want_axis None: label stays stock; 0..3: kind 5 with guide_text()."""
    src = (f' mov {LE.GUIDE_WORD:#x},a1\n mov (a1),a1\n mov {VOBJ:#x},a0\n mov 0x0d0d0d0d,d0\n'
           f' mov 0x11111111,d1\n calls (a1)\n')
    code, sy = asm(src, DRV)
    gcode, _ = asm(GUIDE_STUB, LE.STOCK['ep7_guide'])
    vo = bytearray([0xa5]) * 0x200 + struct.pack('<3I', kind, gid, 0x600d) + bytes(0x1f4)
    res = {}
    for name, im in (('stock', stock), ('patched', patched)):
        regions = [Region('drv', DRV, code, 'rx'), img(im, LE.PARTS_IMG, LE.PARTS_IMG + 24, 'parts', 'r'),
                   img(im, LE.VIEW[0], LE.VIEW[1], 'view'), Region('guide', LE.STOCK['ep7_guide'], gcode, 'rx'),
                   Region('vobj', VOBJ, bytes(vo), 'rw', True)] + fac_regions(getret, pm) + state_regions(h, blk, 'r')
        regions += extra(im) if extra else [img(im, LE.KEYS[0], LE.KEYS[1], 'keys')]   # 13: ed_cfg_fm word
        res[name] = run(regions, {'pc': DRV}, sy['done'])
    s, p = res['stock'], res['patched']
    for r in (s, p):
        if r['fault'] or r['registers']['pc'] != sy['done']:
            return f'run {r["fault"]} pc {r["registers"]["pc"]:#x}'
    for k in ('d0', 'd2', 'd3', 'a2', 'a3', 'sp'):             # the caller 0x60dec790 needs no others
        if s['registers'][k] != p['registers'][k]:
            return f'{k} {p["registers"][k]:#x} != stock {s["registers"][k]:#x}'
    if live_stack(s) != live_stack(p):
        return 'live stack differs'
    sv, pv = mem(s, 'vobj'), mem(p, 'vobj')
    exp = bytearray(sv)
    txt = None
    if want_axis is not None and getret == 0:
        txt = guide_text(gid, want_axis, blk, pm, star)
    if txt is not None:
        struct.pack_into('<H', exp, 44, 5)
        exp[52:118] = b''.join(struct.pack('<H', ord(c)) for c in txt).ljust(66, b'\0')
    if pv != bytes(exp):
        d = [i for i in range(len(pv)) if pv[i] != exp[i]]
        got = ''.join(chr(struct.unpack_from('<H', pv, 52 + 2 * i)[0]) for i in range(33)).rstrip('\0')
        return f'view bytes differ at {d[:8]} (want {txt!r}, got {got!r})'
    if txt is not None and len(txt) > 16:
        return 'label longer than 16'
    return None


def film_blocks():
    """(label, block) variants for the Film label: names of every length class, empty names, no names section."""
    out = []
    for nm in ('Velvia', 'Cl. Chrome', 'Classic Neg', 'Kodachrome64', 'CineStill800', 'A', 'Fifteen chars!!'):
        b = card_block(axis=3)
        for k in range(4):
            b[544 + 16 * k:560 + 16 * k] = nm.encode().ljust(16, b'\0')
        out.append((f'name {nm!r}', b))
    b = card_block(axis=3)
    b[544:560] = bytes(16)
    b[32 + 31] = 0
    out.append(('empty name, stock entry', b))
    b = card_block(axis=3)
    b[544:560] = bytes(16)
    b[32 + 31] = 2
    out.append(('empty name, custom entry', b))
    b = card_block(axis=3, names=False)
    b[672:676] = bytes(4)
    for k in range(4):
        b[32 + 64 * k + 31] = k & 1
    out.append(('no names section', b))
    return out


def t_guide(stock, patched, quick=False):
    fails, n = [], 0
    labels = [(4, 2755, True), (4, 2756, True), (4, 2055, False), (4, 1259, False), (0, 0, False), (5, 2756, False),
              (4, 2757, False), (4, 2754, False), (1, 2756, False)]
    states = [(label, h, blk, None if not ok else 0) for label, h, blk, ok in heap_states()[:5]]
    states.append(('no EP7E (first use)', H_OK, card_block(axis=2, marker=False), 0))
    for ax, want in ((0, 0), (1, 1), (2, 2), (4, None), (5, None), (255, None)):
        states.append((f'axis {ax}', H_OK, card_block(axis=ax), want))
    for label, h, blk, want in (states[5:9] + states[-2:] if quick else states):
        for kind, gid, hit in (labels[:3] if quick else labels):
            e = guide_case(stock, patched, kind, gid, h, blk, want if hit else None)
            n += 1
            if e:
                fails.append(f'V {label} kind {kind} id {gid}: {e}')
    # Film page: slot from the picture mode, every name class; misses (not a COLOR mode, facade error) -> stock
    for label, blk in (film_blocks()[:4] if quick else film_blocks()):
        for pm in ((54, 64, 7) if quick else (54, 55, 56, 64, 7, 0)):
            for gid in (2755, 2756):
                e = guide_case(stock, patched, 4, gid, H_OK, blk, 3, pm=pm)
                n += 1
                if e:
                    fails.append(f'V film {label} pm {pm} id {gid}: {e}')
    for getret in (0xf0000016, 1):
        e = guide_case(stock, patched, 4, 2755, H_OK, film_blocks()[0][1], 3, pm=54, getret=getret)
        n += 1
        if e:
            fails.append(f'V film getret {getret:#x}: {e}')
    return fails, n


# ------------------------------------------------------------------ K (12d key probe)
def probe_case(stock, patched, word, ev, h, blk):
    """one event through the editor vtable word (+0 entry / +68 router). Both images stop at the stock routine with
    equal state; -> (err, heap after)."""
    stop = LE.STOCK['ep7_entry'] if word == LE.VT_ENTRY else LE.STOCK['ep7_router']
    src = (f' mov {PAR:#x},a0\n mov {ev & 0xffffffff:#x},d0\n mov 0x11111111,d1\n mov ({word:#x}),a1\n calls (a1)\n')
    code, _ = asm(src, DRV)
    res = {}
    for name, im in (('stock', stock), ('patched', patched)):
        regions = [Region('drv', DRV, code, 'rx'), img(im, LE.VTAB, LE.VTAB + 72, 'vt', 'r'),
                   img(im, LE.UI[0], LE.UI[1], 'ui')] + state_regions(h, blk)
        res[name] = run(regions, {'pc': DRV}, stop)
    s, p = res['stock'], res['patched']
    for r in (s, p):
        if r['fault'] or r['registers']['pc'] != stop:
            return f'run {r["fault"]} pc {r["registers"]["pc"]:#x}', None
    e = same_state(s, p, skip=('a1',))              # a1 = the vtable word itself
    return (f'state at {stop:#x}: {e}' if e else None), mem(p, 'heap')


def klog_model(prev, ev):
    c = ev & 0xffffffff
    if not 0x9000 <= c < 0x9100 or c in (0x9014, 0x9015) or c == prev + 1:
        return prev
    return c


def t_probe(stock, patched, quick=False):
    fails, n = [], 0
    if not PROBE:
        return fails, n
    seq = [0x9012, 0x9013, 0x9012, 0x9014, 0x9015, 0x9004, 0x9005, 0x9005, 0x9100, 0x8fff, 0xf855, 0x9016, 0x90ff,
           0x1009012, 0x9000, 0x9001]
    for word, off in ((LE.VT_ROUTER, LE.PROBE_R), (LE.VT_ENTRY, LE.PROBE_O)):
        blk = card_block(axis=1)
        struct.pack_into('<HH', blk, LE.PROBE_R, 0x1111, 0x2222)
        for ev in (seq[:6] if quick else seq):
            e, hp = probe_case(stock, patched, word, ev, H_OK, blk)
            n += 1
            prev = struct.unpack_from('<H', blk, off)[0]
            exp = bytearray(blk)
            struct.pack_into('<H', exp, off, klog_model(prev, ev))
            if e or hp != bytes(exp):
                fails.append(f'K word {word:#x} ev {ev:#x}: {e or "heap differs"} '
                             f'(slot {struct.unpack_from("<H", hp, off)[0]:#x} want {klog_model(prev, ev):#x})')
                break
            blk = bytearray(hp)
        for label, h, b, _ in heap_states()[:5]:
            e, hp = probe_case(stock, patched, word, 0x9012, h, b)
            n += 1
            if e or (b is not None and hp != bytes(b)):
                fails.append(f'K word {word:#x} {label}: {e or "heap changed"}')
    return fails, n


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
               img(patched, LE.UI[0], LE.UI[1], 'ui'), img(patched, LE.KEYS[0], LE.KEYS[1], 'keys'),
               Region('fs', FS, bytes(fs), 'rw', True),
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
        ('ed_ui.s.in', ' mov 524,d0', ' mov 523,d0', 'T'),
        ('ed_ui.s.in', ' xor 0xedb88320,d1', ' xor 0xedb88321,d1', 'T'),
        ('ed_ui.s.in', ' cmp d0,d1\n bne w_fail', ' cmp d0,d1\n nop\n nop', 'T'),   # read-back compare removed
        ('ed_core.s.in', ' movbu d0,({dirty},a2)            /* one attempt', ' nop\n nop\n nop /* one attempt', 'T'),
        ('ed_core.s.in', ' mov (8,sp),a0\n mov (12,sp),a1', ' mov (8,sp),a0\n mov (8,sp),a1', 'T'),
        # 12c: refresh after an H/L write
        ('ed_core.s.in', ' add 63,d2', ' add 62,d2', 'W'),
        ('ed_core.s.in', ' call ep7_sget,[],4               /* d0', ' mov d1,d0 /* d0', 'W'),
        ('ed_core.s.in', ' add -4,sp                        /* its', ' nop /* its', 'W'),
        ('ed_core.s.in', ' mov a2,a1\n jmp ep7_manager', ' jmp ep7_manager', 'W'),
        ('ed_core.s.in', ' mov d3,a0\n mov a2,a1', ' mov d3,a1\n mov a2,a1', 'W'),
        ('ed_core.s.in', ' mov d0,mdr', ' nop', 'W'),
        # 12d: INFO cycle (ed_info), cursor poke (ed_ui)
        ('ed_view.s.in', ' cmp 0x9014,d0\n bne f_no', ' cmp 0x9015,d0\n bne f_no', 'E'),
        ('ed_view.s.in', ' mov (0x61fc3804),d3\n or d3,d0', ' mov (0x61fc3800),d3\n or d3,d0', 'E'),
        ('ed_view.s.in', ' cmp 0,d1\n beq f_no', ' cmp 1,d1\n beq f_no', 'E'),
        ('ed_view.s.in', ' bne i_ret', ' nop', 'E'),
        ('ed_view.s.in', ' mov d0,(0,sp)\n mov (0x61fc3800),d1', ' nop\n mov (0x61fc3800),d1', 'E'),
        ('ed_view.s.in', ' cmp 3,d0\n bcs 6f', ' cmp 4,d0\n bcs 6f', 'E'),
        ('ed_view.s.in', ' cmp 176,d2', ' cmp 172,d2', 'E'),
        ('ed_view.s.in', ' mov (16,a3),d0                   /* no held-key / timer gesture in progress */\n cmp 0,d0\n bne f_no',
         ' mov (16,a3),d0\n cmp 0,d0\n nop', 'E'),
        ('ed_view.s.in', ' cmp 13,d0\n bne f_no', ' cmp 12,d0\n bne f_no', 'E'),
        ('ed_view.s.in', ' movbu d0,({axis},a2)\n movbu d0,({dirty},a2)', ' nop\n movbu d0,({dirty},a2)', 'E'),
        ('ed_view.s.in', ' jmp ed_poke ', ' mov 1,d0\n ret [d2,d3,a2,a3],28 ', 'E'),
        ('ed_view.s.in', ' mov (4,sp),d1\n mov (8,sp),a1\n mov (0,sp),d0\n add 12,sp',
         ' mov (4,sp),d1\n mov (4,sp),a1\n mov (0,sp),d0\n add 12,sp', 'E'),
        ('ed_ui.s.in', ' mov 1096,d2', ' mov 1095,d2', 'E'),
        ('ed_ui.s.in', ' bne 2f                           /* no value', ' nop /* no value', 'E'),
        ('ed_ui.s.in', ' clr d1\n mov (4,sp),a1', ' mov 1,d1\n mov (4,sp),a1', 'E'),
        # 12d: state label (ed_guide) and probe text (ed_probe)
        ('ed_view.s.in', ' cmp 2756,d0', ' cmp 2757,d0', 'V'),
        ('ed_view.s.in', ' mov ed_t_one,a1', ' mov ed_t_all,a1', 'V'),
        ('ed_view.s.in', ' cmp 4,d0\n bne g_out', ' cmp 4,d0\n nop', 'V'),
        ('ed_view.s.in', ' cmp 3,d1\n bcc g_out', ' cmp 4,d1\n bcc g_out', 'V'),
        ('ed_view.s.in', ' mov 33,d3', ' mov 30,d3', 'V'),
        ('ed_view.s.in', ' mov 5,d0\n movhu d0,(44,a3)', ' mov 6,d0\n movhu d0,(44,a3)', 'V'),
        ('ed_view.s.in', ' bne 2f                           /* no cycle yet', ' nop /* no cycle yet', 'V'),
        ('ed_view.s.in', 'g_out:\n mov (8,sp),d0', 'g_out:\n mov (4,sp),d0', 'V'),
        ('ed_view.s.in', ' mov ed_t_sep,a1\n PUT\n mov (0,sp),a1', ' mov (0,sp),a1', 'V'),
        ('ed_view.s.in', ' add 7,d0', ' add 6,d0', 'V'),
        ('ed_view.s.in', ' cmp d0,d1\n beq 4f', ' cmp d0,d1\n bra 4f', 'V'),
        ('ed_view.s.in', ' lsr 12,d0', ' lsr 8,d0', 'V'),
        ('ed_view.s.in', ' mov 4,d2\n5:', ' mov 3,d2\n5:', 'V'),
        # 12d: key probe (ed_ui) and its clear on open
        ('ed_ui.s.in', ' cmp 0x9100,d0', ' cmp 0x9200,d0', 'K'),
        ('ed_ui.s.in', ' cmp 0x9015,d0\n beq 93f', ' cmp 0x9016,d0\n beq 93f', 'K'),
        ('ed_ui.s.in', ' inc d3\n cmp d3,d0', ' nop\n cmp d3,d0', 'K'),
        ('ed_ui.s.in', ' KLOG {probe_o}', ' KLOG {probe_r}', 'K'),
        ('ed_ui.s.in', ' movm (sp),[d3,a2]\n jmp ep7_router', ' movm (sp),[d3]\n jmp ep7_router', 'K'),
        ('ed_ui.s.in', ' mov d3,({probe_r},a2)', ' mov d3,({probe_o},a2)', 'I')]


def _mut_one(args):
    spec_base, f, old, new, part = args
    orig = LE.source
    txt = (LE.HERE / f).read_text()
    if txt.count(old) != 1:
        return dict(mutation=f'{f}: {old!r}', detected=None, note='pattern not unique/found')

    def src(name, probe=True, f=f, old=old, new=new):
        s = orig(name, probe)
        if name == f:
            o = B3.subst(old, LE.sub(probe)) if '{' in old else old
            n_ = B3.subst(new, LE.sub(probe)) if '{' in new else new
            s = s.replace(o, n_)
        return s
    LE.source = src
    try:
        _, merged, _ = LE.build(spec_base)
    finally:
        LE.source = orig
    st, pa = images(merged)
    fn = dict(G=lambda: t_get(st, pa), W=lambda: t_set(st, pa), E=lambda: t_event(st, pa),
              T=lambda: t_save(st, pa), V=lambda: t_guide(st, pa), K=lambda: t_probe(st, pa),
              I=lambda: t_init(st, pa))[part]
    try:
        fl, _ = fn()
    except Exception as e:  # noqa: BLE001
        fl = [f'exception {e}']
    return dict(mutation=f'{f}: {old.strip()[:40]!r} -> {new.strip()[:40]!r}', part=part, detected=bool(fl))


def _spec_mut(args):
    spec_base, label = args
    _, merged, _ = LE.build(spec_base)
    es = merged['edits']
    iw = {hex(a + LE.INFO_OFF) for a in LE.RECORDS.values()}
    if label == 'record +44 edits dropped':
        es, fn, part = [e for e in es if e['addr'] not in iw], t_event, 'E'
    elif label == 'record +44 -> stock event 0x60e22191':
        es = [dict(e, new=struct.pack('<I', LE.STOCK['ep7_event']).hex()) if e['addr'] in iw else e for e in es]
        fn, part = t_event, 'E'
    elif label == 'guide word 0x6025aa98 left stock':
        es, fn, part = [e for e in es if e['addr'] != hex(LE.GUIDE_WORD)], t_guide, 'V'
    else:                                            # probe vtable words left stock
        es, fn, part = [e for e in es if e['addr'] not in (hex(LE.VT_ENTRY), hex(LE.VT_ROUTER))], t_probe, 'K'
    st, pa = images(dict(merged, edits=es))
    try:
        fl, _ = fn(st, pa, quick=True)
    except Exception as e:  # noqa: BLE001
        fl = [f'exception {e}']
    return dict(mutation=f'spec: {label}', part=part, detected=bool(fl))


SPEC_MUTS = ['record +44 edits dropped', 'record +44 -> stock event 0x60e22191', 'guide word 0x6025aa98 left stock',
             'probe vtable words left stock']
PARTS = dict(S=lambda: (t_static(SPEC, STOCK_IM, PATCHED_IM), 1), G=lambda: t_get(STOCK_IM, PATCHED_IM),
             W=lambda: t_set(STOCK_IM, PATCHED_IM), E=lambda: t_event(STOCK_IM, PATCHED_IM),
             V=lambda: t_guide(STOCK_IM, PATCHED_IM), K=lambda: t_probe(STOCK_IM, PATCHED_IM),
             I=lambda: t_init(STOCK_IM, PATCHED_IM), T=lambda: t_save(STOCK_IM, PATCHED_IM))
SPEC = STOCK_IM = PATCHED_IM = None


def _task(t):
    """one pool task: ('part', name) | ('mut', args) | ('spec', args). Fork pool: globals are inherited."""
    kind, arg = t
    if kind == 'part':
        images(SPEC)                                  # restore this spec's PROBE/SYMS (a mutant may have run here)
        fails, n = PARTS[arg]()
        return dict(part=arg, runs=n, passed=not fails, fails=fails[:20])
    return _mut_one(arg) if kind == 'mut' else _spec_mut(arg)


def main():
    global SPEC, STOCK_IM, PATCHED_IM
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--base', type=Path, help='base spec (for M: rebuild mutants on it)')
    ap.add_argument('--part', default='S,G,W,E,V,K,I,T,M')
    ap.add_argument('--json', type=Path)
    ap.add_argument('--jobs', type=int, default=1, help='processes for the parts and M mutations (each ~0.3 GB)')
    a = ap.parse_args()
    SPEC = json.loads(a.spec.read_text())
    STOCK_IM, PATCHED_IM = images(SPEC)
    parts = a.part.split(',')
    tasks = [('part', p) for p in ('G', 'W', 'E', 'V', 'K', 'I', 'T', 'S') if p in parts]
    if 'M' in parts:
        if not a.base:
            sys.exit('M needs --base')
        tasks += [('mut', (a.base,) + m) for m in MUTS] + [('spec', (a.base, l)) for l in SPEC_MUTS]
    if a.jobs > 1:
        import multiprocessing as mp
        with mp.get_context('fork').Pool(min(a.jobs, len(tasks)), maxtasksperchild=4) as pool:
            out = pool.map(_task, tasks, chunksize=1)
    else:
        out = [_task(t) for t in tasks]
    results = [r for r in out if 'runs' in r]
    order = 'SGWEVKIT'
    for r in sorted(results, key=lambda r: order.index(r['part'])):
        print(f'{r["part"]}: {"PASS" if r["passed"] else "FAIL"} ({r["runs"]} runs)' + ''.join('\n   ' + f for f in r['fails'][:10]),
              flush=True)
    results.sort(key=lambda r: order.index(r['part']))
    m = [r for r in out if 'runs' not in r]
    if m:
        det = sum(1 for x in m if x['detected'])
        results.append(dict(part='M', mutations=m, detected=det, total=len(m)))
        print(f'M: {det}/{len(m)} detected' + ''.join(f'\n   MISSED {x["mutation"]} {x.get("note", "")}' for x in m if not x['detected']))
    ok = all(r.get('passed', True) for r in results) and all(r.get('detected', 0) == r.get('total', 0) for r in results)
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.spec), results=results, ok=ok), indent=1) + '\n')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
