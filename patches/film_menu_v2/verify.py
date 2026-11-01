#!/usr/bin/env python3
"""Emulator checks of the film page (patches/film_menu_v2, docs/FILM_MENU_V2.md). Offline only.

  .venv/bin/python -I patches/film_menu_v2/verify.py --base generated/look_extras_12e/merged.json \
      --layered generated/film_menu_v2_12e/merged.json [--part V,U,P,L,H,T] [--jobs 8]

Our code runs natively from the layered image, entered through the real edited words (COLOR record +12/+16, the
editor's ed_cfg_fv / ed_cfg_fl words); image regions are mapped read-only (a store into them faults the run).
  V  fm_valid: every handle condition (marker, alignment, pool bounds, L tag, back-pointer) -> 0; valid -> 1;
     callee-saved registers kept
  U  Up/Down without a usable film state (no P, no EP7B/EP7E, page != Film, each bad handle, other editor key):
     the stock Up/Down handler is reached with registers + live stack == the run on the base image (= 12e without
     the film layer), heap and L unchanged
  P  picks: a full wrap Up and Down on each COLOR key (own -> 16 looks -> Stock -> own); the slot entry ==
     tools/ep7_looks_bin.place(look, k) and the name == the look's; own restores the snapshot; EP7N, dirty;
     d0 1 and the editor's cursor poke; a library with mono looks skips them; no names section in P
  L  fm_load: the card LOOKS.BIN loads (EP7F, L tags, n, resume positions from the slot names); every reject
     (sizes, header, n/payload, CRC, ranges, class/mask/reserved, name rules), no file, malloc fail, fseek fail,
     short read -> EP7X, L freed, nothing else; EP7F/EP7X already set -> no call at all
  H  half-press (loader sd_back -> ed_trig): fm_load runs once (the second press makes no file call)
  M  (13) fm_mod via the editor's ed_cfg_fm word: 0 while the slot entry == place(picked look), 1 after any byte
     changes; own / Stock / bad handle / k 4 -> 0; registers kept. The Film label through ed_guide: "Film: <name>"
     or "Film: <name>*" (16-character rule) on the layered image
  T  pick -> half-press save: BUNDLES.NEW/.BIN images == the heap table (+ names CRC) and pass the camera rules
     (tools/ep7_bundles_bin.check_file) with the picked look's name
"""
import argparse, importlib.util, json, struct, sys, zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


EV = _load('ep7_verify_look_editor_fm', ROOT / 'tools/ep7_verify_look_editor.py')
FB = _load('ep7_film_menu_v2_build_v', ROOT / 'patches/film_menu_v2/build.py')
LB, LE, B3 = FB.LB, EV.LE, EV.B3
Region, run, asm, img, mem = EV.Region, EV.run, EV.asm, EV.img, EV.mem
BASE, H_OK, P_OK, NMAGIC = EV.BASE, EV.H_OK, EV.P_OK, EV.NMAGIC
DRV, OUT, PAR, SENT, SP0, STK = EV.DRV, EV.OUT, EV.PAR, EV.SENT, EV.SP0, EV.STK
O = FB.OFF
L_AT = B3.POOL + 0x8000                     # the L block (inside the class-1 pool)
FSC = 0x18d00000                            # film file-service control / log / file
G = {}


def init(base, layered):
    G['base_spec'] = json.loads(Path(base).read_text())
    G['spec'] = json.loads(Path(layered).read_text())
    _, G['base'] = EV.images(G['base_spec'])
    G['stock'], G['lay'] = EV.images(G['spec'])
    G['fs'] = {k: int(v, 16) for k, v in G['spec']['film_menu_v2']['symbols'].items()}
    G['es'] = {k: int(v, 16) for k, v in G['spec']['look_editor']['symbols'].items()}
    # test13b: the release card library (v2: CineStill800 carries bloom colour red at record +47)
    G['looks'] = LB.compile_looks(FB.colour_library(ROOT / 'bundles/library_v2.json'))[0]
    G['looks_all'] = LB.compile_looks(json.loads((ROOT / 'bundles/library_v1.json').read_text()))[0]


def code_regions(im):
    fs = G['spec']['film_menu_v2']
    ui0 = int(fs['ui'][0], 16)
    return [img(im, FB.CODE[0], FB.CODE[1], 'fmcore'), img(im, ui0, FB.UI[1], 'fmui'),
            img(im, 0x61185b00, 0x61185d00, 'rec', 'r'), img(im, LE.UI[0], LE.UI[1], 'ui'),
            img(im, LE.KEYS[0], LE.KEYS[1], 'keys')]


# ------------------------------------------------------------------ models
def n_of(looks):
    return (len(looks) - 64) // 64


def rec(looks, j):
    return looks[64 + 64 * j:128 + 64 * j]


def loaded_L(looks, blk):
    """L as fm_load leaves it (bytes past the file: 0xee filler as mapped)."""
    L = bytearray([0xee]) * 2048
    L[:len(looks)] = looks
    n = n_of(looks)
    struct.pack_into('<II', L, O['ltag'], FB.LMAGIC, P_OK)
    L[O['n']] = n
    for k in range(8):
        L[O['pos'] + k] = 0
    if struct.unpack_from('<I', blk, 672)[0] == NMAGIC:
        for k in range(4):
            nm = bytes(blk[544 + 16 * k:560 + 16 * k])
            if nm[0] == 0:
                continue
            for j in range(n):
                r = rec(looks, j)
                if r[46] & 1 and r[48:64] == nm:
                    L[O['pos'] + k] = j + 1
                    break
    return L


def film_block(axis=3, names=True, looks=None, L_addr=L_AT, fmark=FB.FMAGIC):
    b = EV.card_block(axis=axis, names=names)
    struct.pack_into('<II', b, O['lptr'], L_addr, fmark)
    return b


def step_model(blk, L, k, d):
    n = L[O['n']]
    pos = L[O['pos'] + k]
    while True:
        pos += d
        if pos < 0:
            pos = n + 1
        if pos > n + 1:
            pos = 0
        if pos in (0, n + 1) or L[64 * pos + 46] & 1:
            break
    L[O['pos'] + k] = pos
    names = struct.unpack_from('<I', blk, 672)[0] == NMAGIC
    if not L[O['snap'] + k]:
        L[O['snap'] + k] = 1
        sn = bytes(blk[32 + 64 * k:96 + 64 * k]) + (bytes(blk[544 + 16 * k:560 + 16 * k]) if names else bytes(16))
        L[O['snaps'] + 80 * k:O['snaps'] + 80 * k + 80] = sn
    if pos == 0:
        T = bytes(L[O['snaps'] + 80 * k:O['snaps'] + 80 * k + 80])
    elif pos == n + 1:
        T = bytes(80)
    else:
        r = bytes(L[64 * pos:64 * pos + 64])
        T = r[:32] + bytes(13) + r[47:48] + bytes(18) + r[48:64]      # test13b: +45 = record +47 (bloom colour)
        if T[:64] != LB.place(r, k):
            raise AssertionError(f'model entry != place() for look {pos - 1} slot {k}')
    L[O['stage']:O['stage'] + 80] = T
    blk[32 + 64 * k:96 + 64 * k] = T[:64]
    if not names:
        blk[544:672] = bytes(128)
    blk[544 + 16 * k:560 + 16 * k] = T[64:]
    struct.pack_into('<I', blk, 672, NMAGIC)
    blk[LE.DIRTY] = 1
    return pos


# ------------------------------------------------------------------ V
def v_case(args):
    label, blk, L, want = args
    src = f' mov {G["fs"]["fm_valid"]:#x},a1\n mov {P_OK:#x},a2\n calls (a1)\n'
    code, sy = asm(src, DRV)
    regions = [Region('drv', DRV, code, 'rx'), Region('L', L_AT, bytes(L), 'r')] + code_regions(G['lay']) + \
        EV.state_regions(H_OK, blk, 'r')
    r = run(regions, {'pc': DRV}, sy['done'])
    if r['fault'] or r['registers']['pc'] != sy['done']:
        return label, f'run {r["fault"]}'
    rg = r['registers']
    if rg['d0'] != want or rg['a2'] != P_OK or rg['d2'] != SENT['d2'] or rg['d3'] != SENT['d3'] or rg['a3'] != SENT['a3'] \
            or rg['sp'] != SP0:
        return label, f'd0 {rg["d0"]} want {want} / registers'
    return label, None


def bad_handles():
    """(label, blk, L) with exactly one handle condition broken."""
    looks = G['looks']
    good = film_block()
    L = loaded_L(looks, good)
    out = []
    for lab, mark in (('EP7X', FB.XMAGIC), ('zero mark', 0), ('EP7F-1', FB.FMAGIC - 1)):
        out.append((lab, film_block(fmark=mark), L))
    for lab, la in (('L misaligned', L_AT + 2), ('L below pool', B3.POOL - 4), ('L past pool', B3.POOL + FB.LLIM),
                    ('L null', 0)):
        out.append((lab, film_block(L_addr=la), L))
    L2 = bytearray(L)
    L2[O['ltag']] ^= 1
    out.append(('bad L tag', film_block(), L2))
    L3 = bytearray(L)
    struct.pack_into('<I', L3, O['lback'], P_OK + 4)
    out.append(('bad back-pointer', film_block(), L3))
    return out


def v_cases(quick=False):
    good = film_block()
    out = [('valid', good, loaded_L(G['looks'], good), 1)]
    out += [(lab, b, L, 0) for lab, b, L in bad_handles()]
    return out


# ------------------------------------------------------------------ U / P
def ud_run(im, key, ev, word, blk, L, getret=0):
    rec_a = LE.RECORDS[key] + word
    po = EV.parent_obj2(key=key)
    src = (f' mov {rec_a:#x},a1\n mov (a1),a1\n mov {PAR:#x},a0\n mov {ev:#x},d0\n mov 0x11111111,d1\n'
           f' mov a1,({OUT:#x})\n mov ({OUT:#x}),a2\n mov 0x1a1a1a1a,a1\n calls (a2)\n')
    code, sy = asm(src, DRV)
    stop_stock = FB.UP if word == FB.UP_OFF else FB.DOWN
    regions = [Region('drv', DRV, code, 'rx'), Region('out', OUT, bytes(64), 'rw'), Region('par', PAR, bytes(po), 'r'),
               Region('L', L_AT, bytes(L), 'rw', True)] + code_regions(im) + EV.fac_regions(getret) + \
        EV.state_regions(H_OK, blk)
    return run(regions, {'pc': DRV}, stop_stock), sy, stop_stock


def u_case(args):
    label, key, word, blk, L = args
    ev = 0x9004 if word == FB.UP_OFF else 0x9006
    rb, _, stop = ud_run(G['base'], key, ev, word, blk, L)
    rp, _, _ = ud_run(G['lay'], key, ev, word, blk, L)
    for r in (rb, rp):
        if r['fault'] or r['registers']['pc'] != stop:
            return label, f'run {r["fault"]} pc {r["registers"]["pc"]:#x}'
    e = EV.same_state(rb, rp)
    if e:
        return label, f'state at stock: {e}'
    if mem(rp, 'heap') != bytes(blk) or mem(rp, 'L') != bytes(L) or EV.fac_log(rp):
        return label, 'heap / L / facade touched'
    return label, None


def u_cases(quick=False):
    looks = G['looks']
    out = []
    good = film_block()
    L = loaded_L(looks, good)
    keys = (0x13b3,) if quick else tuple(LE.RECORDS)
    for word in (FB.UP_OFF, FB.DOWN_OFF):
        for key in keys:
            for ax in (0, 1, 2, 4, 255):
                out.append((f'axis {ax} key {key:#x} w{word}', key, word, film_block(axis=ax), L))
        for lab, b, LL in bad_handles():
            out.append((f'{lab} w{word}', 0x13b4, word, b, LL))
        b = film_block()
        b[0] ^= 1
        out.append((f'no EP7B w{word}', 0x13b5, word, b, L))
        out.append((f'no EP7E w{word}', 0x140c, word, _nomark(), L))
    return out


def _nomark():
    b = film_block()
    b[LE.EMARK:LE.EMARK + 4] = bytes(4)
    return b


def hit_run(key, d, blk, L):
    word = FB.UP_OFF if d > 0 else FB.DOWN_OFF
    ev = 0x9004 if d > 0 else 0x9006
    rec_a = LE.RECORDS[key] + word
    po = EV.parent_obj2(key=key)
    src = (f' mov {rec_a:#x},a1\n mov (a1),a1\n mov {PAR:#x},a0\n mov {ev:#x},d0\n mov 0x11111111,d1\n'
           f' mov a1,({OUT:#x})\n mov ({OUT:#x}),a2\n mov 0x1a1a1a1a,a1\n calls (a2)\n')
    code, sy = asm(src, DRV)
    regions = [Region('drv', DRV, code, 'rx'), Region('out', OUT, bytes(64), 'rw'), Region('par', PAR, bytes(po), 'r'),
               Region('L', L_AT, bytes(L), 'rw', True)] + code_regions(G['lay']) + EV.fac_regions(0) + \
        EV.state_regions(H_OK, blk)
    return run(regions, {'pc': DRV}, sy['done']), sy


def p_case(args):
    label, key, d, looks, names = args
    blk = film_block(names=names)
    if not names:
        blk[544:680] = bytes(136)
    L = loaded_L(looks, blk)
    mb, mL = bytearray(blk), bytearray(L)
    seen = []
    n = n_of(looks)
    start = L[O['pos'] + list(LE.RECORDS).index(key)]
    cur = {0x13b3: 1091, 0x13b4: 1096, 0x13b5: 1097, 0x140c: 1686}[key]
    k = list(LE.RECORDS).index(key)
    for i in range(n + 3):
        pos = step_model(mb, mL, k, d)
        r, sy = hit_run(key, d, blk, L)
        rg = r['registers']
        if r['fault'] or rg['pc'] != sy['done']:
            return label, f'step {i}: run {r["fault"]} pc {rg["pc"]:#x}'
        if rg['d0'] != 1 or rg['sp'] != SP0 or rg['d2'] != SENT['d2'] or rg['d3'] != SENT['d3'] or rg['a3'] != SENT['a3']:
            return label, f'step {i}: return state d0 {rg["d0"]:#x}'
        fc = [x[:2] if x[0] == 1 else x for x in EV.fac_log(r)]
        if fc != [(1, cur), (2, cur, 0, 7)]:
            return label, f'step {i}: cursor poke {fc}'
        blk, L = bytearray(mem(r, 'heap')), bytearray(mem(r, 'L'))
        if blk != mb:
            dd = [j for j in range(len(blk)) if blk[j] != mb[j]]
            return label, f'step {i} pos {pos}: heap differs at {dd[:8]}'
        if L != mL:
            dd = [j for j in range(len(L)) if L[j] != mL[j]]
            return label, f'step {i} pos {pos}: L differs at {dd[:8]}'
        seen.append(pos)
    want_len = n + 2 - sum(1 for j in range(n) if not rec(looks, j)[46] & 1)
    if seen[want_len - 1] != start or len(set(seen[:want_len])) != want_len or 0 not in seen or n + 1 not in seen:
        return label, f'wrap {seen}'
    return label, None


def p_cases(quick=False):
    out = []
    for key in ((0x13b3,) if quick else tuple(LE.RECORDS)):
        for d in (1, -1):
            out.append((f'wrap key {key:#x} d {d}', key, d, G['looks'], True))
    out.append(('mono skipped up', 0x13b4, 1, G['looks_all'], True))
    out.append(('mono skipped down', 0x140c, -1, G['looks_all'], True))
    out.append(('no names section', 0x13b5, 1, G['looks'], False))
    return out


# ------------------------------------------------------------------ L (fm_load)
FS_STUB = f"""
 .set C, {FSC:#x}
.macro LOG id
 mov (C),a3
 mov \\id,d3
 mov d3,(a3)
 mov d0,(4,a3)
 mov d1,(8,a3)
 mov a0,(12,a3)
 mov a1,(16,a3)
 add 20,a3
 mov a3,(C)
.endm
.macro CLOB
 mov 0xbad0d100,d1
 mov 0xbad0a100,a1
.endm
s_malloc:
 movm [d2,d3,a2,a3],(sp)
 LOG 1
 mov (C+4),a0
 mov 0xbad0d000,d0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [],4
s_free:
 movm [d2,d3,a2,a3],(sp)
 LOG 2
 mov 0xbad0a000,a0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [],4
s_fopen:
 movm [d2,d3,a2,a3],(sp)
 LOG 3
 mov (C+8),a0                     /* handle or 0 */
 clr d0
 mov d0,(C+0x20)                  /* pos */
 mov 0xbad0d000,d0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [],4
s_fclose:
 movm [d2,d3,a2,a3],(sp)
 LOG 4
 clr d0
 mov 0xbad0a000,a0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [d2,a2,a3],16
s_fseek:
 movm [d2,d3,a2,a3],(sp)
 LOG 7
 cmp 1,d1
 bne 1f
 mov (C+0x10),d0                  /* END */
 bra 2f
1:
2:
 mov d0,(C+0x20)
 mov (C+0x14),d0                  /* seek result */
 mov 0xbad0a000,a0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [d2,d3,a2,a3],20
s_ftell:
 movm [d2,d3,a2,a3],(sp)
 LOG 8
 mov (C+0x20),d0
 mov 0xbad0a000,a0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [d2,a2,a3],16
s_fread:
 movm [d2,d3,a2,a3],(sp)
 LOG 6
 mov (C+0x10),d2                  /* min(n, size - pos, readmax) */
 mov (C+0x20),d3
 sub d3,d2
 cmp d1,d2
 ble 1f
 mov d1,d2
1:
 mov (C+0x18),d1
 cmp d1,d2
 ble 2f
 mov d1,d2
2:
 mov d2,d0
 cmp 0,d2
 beq 4f
 mov C+0x1000,a2
 add d3,a2
3:
 movbu (a2),d1
 movbu d1,(a0)
 inc a0
 inc a2
 add -1,d2
 bne 3b
4:
 mov 0xbad0a000,a0
 CLOB
 movm (sp),[d2,d3,a2,a3]
 ret [d2,d3,a2,a3],24
"""
TRAMPS = dict(malloc=0x60022782, free=0x600227b4, fopen=0x60634fbc, fclose=0x60634fc5, fread=0x6063514b,
              fseek=0x60635243, ftell=0x606351d9)
LOGN = {1: 'malloc', 2: 'free', 3: 'fopen', 4: 'fclose', 6: 'fread', 7: 'fseek', 8: 'ftell'}


def fs_regions(data, malloc=L_AT, handle=0x18e00000, seek=0, readmax=0x7fffffff, size=None):
    code, sy = asm(FS_STUB, 0x18d80000)
    regs = [Region('fstub', 0x18d80000, code, 'rx')]
    for k, a in TRAMPS.items():
        regs.append(Region('t_' + k, a, b'\xdc' + struct.pack('<i', sy['s_' + k] - a), 'rx'))
    c = bytearray(0x1000 + 0x800)
    struct.pack_into('<IIIIIIII', c, 0, FSC + 0x100, malloc, 0 if data is None else handle, 0,
                     len(data or b'') if size is None else size, seek, readmax, 0)
    c[0x1000:0x1000 + len(data or b'')] = data or b''
    regs.append(Region('fsc', FSC, bytes(c), 'rw', True))
    return regs


def fs_log(r):
    c = mem(r, 'fsc')
    end = struct.unpack_from('<I', c, 0)[0] - FSC
    return [(LOGN.get(struct.unpack_from('<I', c, o)[0], '?'),) + struct.unpack_from('<4I', c, o + 4)
            for o in range(0x100, end, 20)]


def load_run(blk, data, **fsk):
    src = f' mov {G["fs"]["fm_load"]:#x},a1\n mov {P_OK:#x},a2\n calls (a1)\n'
    code, sy = asm(src, DRV)
    regions = [Region('drv', DRV, code, 'rx'), Region('L', L_AT, b'\xee' * 2048, 'rw', True)] + \
        code_regions(G['lay']) + fs_regions(data, **fsk) + EV.state_regions(H_OK, blk)
    return run(regions, {'pc': DRV}, sy['done'], limit=20_000_000), sy


def l_case(args):
    label, data, want, fsk = args
    blk = EV.card_block(axis=0)
    blk[O['lptr']:O['lptr'] + 8] = bytes([0xa5]) * 8
    if want == 'skip':
        struct.pack_into('<I', blk, O['fmark'], fsk.pop('mark'))
    r, sy = load_run(blk, data, **fsk)
    rg = r['registers']
    if r['fault'] or rg['pc'] != sy['done']:
        return label, f'run {r["fault"]} pc {rg["pc"]:#x}'
    if rg['a2'] != P_OK or rg['d2'] != SENT['d2'] or rg['d3'] != SENT['d3'] or rg['a3'] != SENT['a3'] or rg['sp'] != SP0:
        return label, 'callee-saved registers'
    hp, L, lg = mem(r, 'heap'), mem(r, 'L'), fs_log(r)
    calls = [x[0] for x in lg]
    if want == 'skip':
        return label, (None if not lg and hp == bytes(blk) else f'calls {calls} / heap changed')
    exp = bytearray(blk)
    if want == 'ok':
        struct.pack_into('<II', exp, O['lptr'], L_AT, FB.FMAGIC)
        eL = loaded_L(data, blk)
        if L != bytes(eL):
            d = [i for i in range(2048) if L[i] != eL[i]]
            return label, f'L differs at {d[:8]}'
        if calls != ['malloc', 'fopen', 'fseek', 'ftell', 'fseek', 'fread', 'fclose']:
            return label, f'calls {calls}'
        op = lg[1]
        path = G['lay'][op[3] - BASE:op[3] - BASE + 20].split(b'\0')[0]
        mode = G['lay'][op[4] - BASE:op[4] - BASE + 2].split(b'\0')[0]
        if path != b'C:\\EP7MOD\\LOOKS.BIN' or mode != b'r':
            return label, f'fopen {path} {mode}'
    else:
        struct.pack_into('<I', exp, O['fmark'], FB.XMAGIC)
        mf = fsk.get('malloc', L_AT)
        if mf == L_AT and calls[-1:] != ['free'] or (mf == L_AT and lg[-1][3] != L_AT):
            return label, f'L not freed: {calls}'
        if calls.count('fopen') != calls.count('fclose') + (data is None):
            return label, f'open/close {calls}'
    if hp != bytes(exp):
        d = [i for i in range(len(hp)) if hp[i] != exp[i]]
        return label, f'heap differs at {d[:8]}'
    return label, None


def bad_files():
    good = G['looks']
    out = []

    def fix(b):                                       # recompute the CRC (so the case tests its own rule)
        b = bytearray(b)
        struct.pack_into('<I', b, 16, zlib.crc32(bytes(b[:16] + b[20:])) & 0xffffffff)
        return bytes(b)

    def mut(lab, off, val, crc=True):
        b = bytearray(good)
        b[off] = val
        out.append((lab, fix(b) if crc else bytes(b)))
    out.append(('crc flip', good[:16] + bytes([good[16] ^ 1]) + good[17:]))
    out.append(('body flip, old crc', good[:100] + bytes([good[100] ^ 2]) + good[101:]))
    for off, lab in ((0, 'magic'), (4, 'version'), (6, 'hdr len'), (8, 'fw build'), (20, 'sha'), (26, 'rec len'),
                     (28, 'layout crc'), (40, 'zero pad'), (63, 'zero pad end'), (12, 'payload'), (24, 'n')):
        mut(f'header {lab}', off, good[off] ^ 0x10)
    for off, val, lab in ((64 + 0, 8, 'hue +8'), (64 + 0, 0xf8, 'hue -8'), (64 + 24, 4, 'grain 4'), (64 + 25, 2, 'wb flags 2'),
                          (64 + 28, 4, 'effect 4'), (64 + 29, 6, 'strength 6'), (64 + 31, 4, 'flags 4'),
                          (64 + 44, 6, 'sat +6'), (64 + 45, 1, 'class mono, mask 1'), (64 + 46, 0, 'mask 0'),
                          (64 + 46, 2, 'colour mask 2'), (64 + 47, 5, 'bloom colour 5'), (64 + 48, 0, 'name empty'),
                          (64 + 49, 0x40, "name '@'"), (64 + 49, 0x7f, 'name 0x7f'), (64 + 49, 0x1f, 'name 0x1f'),
                          (64 + 63, 0x41, 'name byte 15'), (64 + 62, 0x41, 'name after NUL'),
                          (len(good) - 64 + 0, 9, 'last look hue')):
        mut(f'record {lab}', off, val)
    hdr = bytearray(good[:64])
    out.append(('size 0', b''))
    out.append(('size 63', good[:63]))
    out.append(('size 64 (n 0)', fix(bytes(hdr))))
    out.append(('size 65', fix(good + b'\0')))
    out.append(('size 1088+32', fix(good + bytes(32))))
    b = bytearray(good + good[64:64 + 64 * 5])   # 21 looks = 1408 B
    struct.pack_into('<IH', b, 12, 64 * 21, 0)
    struct.pack_into('<H', b, 24, 21)
    out.append(('21 looks (1408 B)', fix(bytes(b))))
    b = bytearray(good[:64 + 64 * 3])           # n field says 16, file has 3
    out.append(('n/payload vs size', fix(bytes(b))))
    return out


def l_cases(quick=False):
    out = [('card LOOKS.BIN', G['looks'], 'ok', {}), ('library with mono', G['looks_all'], 'ok', {})]
    one = LB.make_file([rec(G['looks'], 0)])
    out.append(('one look', one, 'ok', {}))
    full = LB.make_file([rec(G['looks_all'], j % 19) if j < 19 else rec(G['looks'], 0) for j in range(19)] +
                        [LB.record(LB.to_rec96(rec(G['looks'], 1)))[:48] + b'Twenty'.ljust(16, b'\0')])
    out.append(('20 looks', full, 'ok', {}))
    for lab, data in bad_files():
        out.append((lab, data, 'bad', {}))
    out.append(('no file', None, 'bad', {}))
    out.append(('malloc fail', G['looks'], 'bad', dict(malloc=0)))
    out.append(('malloc misaligned', G['looks'], 'bad', dict(malloc=L_AT + 2)))
    out.append(('fseek fail', G['looks'], 'bad', dict(seek=1)))
    out.append(('short read', G['looks'], 'bad', dict(readmax=len(G['looks']) - 1)))
    out.append(('EP7F already', G['looks'], 'skip', dict(mark=FB.FMAGIC)))
    out.append(('EP7X already', G['looks'], 'skip', dict(mark=FB.XMAGIC)))
    return out


# ------------------------------------------------------------------ H / T (half-press: load, then save)
def press_run(blk, data, Lbuf=None, editor_fs=False, files=None):
    stack = bytearray([0x5c]) * 0x2000
    struct.pack_into('<I', stack, SP0 - STK + 16, B3.EV_PRESS)
    im = G['lay']
    regions = [Region('stack', STK, bytes(stack), 'rw', True), img(im, 0x605b7180, 0x605b7800, 'sec3'),
               Region('L', L_AT, bytes(Lbuf) if Lbuf is not None else b'\xee' * 2048, 'rw', True)] + \
        [x for x in code_regions(im) if x.name not in ('rec',)] + EV.state_regions(H_OK, blk)
    if editor_fs:
        fs = EV.fs_image(files or {})
        regions += [Region('fs', EV.FS, bytes(fs), 'rw', True), Region('sbuf', EV.S_BUF, b'\xcc' * 2048, 'rw', True)] + \
            EV.fs_regions()
    else:
        regions += fs_regions(data)
    regs = dict(SENT, sp=SP0, pc=LE.SD_BACK, d0=0xd0d0d0d0, d1=0xd1d1d1d1, a0=0xa0a0a0a0, a1=0xa1a1a1a1)
    return EV.execute(regions, regs, B3.SITE_RET, limit=20_000_000, timeout=120)


def h_case(args):
    label, = args
    blk = EV.card_block(axis=0)
    blk[O['lptr']:O['lptr'] + 8] = bytes([0xa5]) * 8
    r = press_run(blk, G['looks'])
    if r['fault'] or r['registers']['pc'] != B3.SITE_RET:
        return label, f'press 1: {r["fault"]}'
    for k in ('d0', 'd1', 'a0', 'a1', 'd2', 'd3', 'a2', 'a3', 'sp'):
        want = dict(SENT, sp=SP0, d0=0xd0d0d0d0, d1=0xd1d1d1d1, a0=0xa0a0a0a0, a1=0xa1a1a1a1)[k]
        if r['registers'][k] != want:
            return label, f'press 1: {k} {r["registers"][k]:#x}'
    hp = bytearray(mem(r, 'heap'))
    if struct.unpack_from('<II', hp, O['lptr']) != (L_AT, FB.FMAGIC):
        return label, 'press 1: not loaded'
    if [x[0] for x in fs_log(r)].count('fopen') != 1:
        return label, 'press 1: fopen count'
    r2 = press_run(bytes(hp), G['looks'], Lbuf=mem(r, 'L'))
    if r2['fault'] or fs_log(r2) or mem(r2, 'heap') != bytes(hp):
        return label, 'press 2: file call or heap change'
    return label, None


def t_case(args):
    label, key, steps = args
    blk = film_block()
    L = loaded_L(G['looks'], blk)
    k = list(LE.RECORDS).index(key)
    for _ in range(steps):
        r, sy = hit_run(key, 1, blk, L)
        if r['fault']:
            return label, f'pick: {r["fault"]}'
        blk, L = bytearray(mem(r, 'heap')), bytearray(mem(r, 'L'))
    pos = L[O['pos'] + k]
    look = rec(G['looks'], pos - 1)
    old = (ROOT / 'testdata/camera_t12d/EP7MOD/BUNDLES.BIN').read_bytes()
    r = press_run(bytes(blk), None, Lbuf=L, editor_fs=True, files={2: old})
    if r['fault'] or r['registers']['pc'] != B3.SITE_RET:
        return label, f'save: {r["fault"]}'
    hp = mem(r, 'heap')
    files = EV.fs_files(mem(r, 'fs'))
    want = EV.expected_image(blk)
    if files.get('NEW') != want or files.get('BIN') != want or files.get('BAK') != old:
        return label, f'files {sorted(files)} differ from the heap image'
    probs = EV.BIN.check_file(want) if hasattr(EV.BIN, 'check_file') else []
    if probs:
        return label, f'saved file rejected: {probs}'
    nm = want[544 + 16 * k:560 + 16 * k]
    if nm != look[48:64] or want[32 + 64 * k:96 + 64 * k] != LB.place(look, k) or hp[LE.DIRTY] != 0 or hp[LE.STATUS] != 1:
        return label, 'saved slot / name / dirty / status'
    return label, None


# ------------------------------------------------------------------ M (13: modified marker)
def placed_block(j, edit=None):
    """Film block whose 4 slots sit on colour look j (entry == place(), name == the look's), L positions == j+1."""
    blk = film_block()
    r = rec(G['looks'], j)
    for k in range(4):
        blk[32 + 64 * k:96 + 64 * k] = LB.place(r, k)
        blk[544 + 16 * k:560 + 16 * k] = r[48:64]
    if edit:
        edit(blk)
    L = loaded_L(G['looks'], film_block())
    for k in range(4):
        L[O['pos'] + k] = j + 1
    return blk, L


def m_cases(quick=False):
    out = []
    n = n_of(G['looks'])
    for j in (1, 9, 14):
        out.append((f'look {j} unmodified', j, None, None, 0))
        for off, lab in ((0, 'hue[0]'), (23, 'light[11]'), (28, 'effect'), (31, 'flags'), (40, 'zero zone +40'), (63, '+63')):
            out.append((f'look {j} {lab} changed', j, off, None, 1))
    out.append(('pos own', 1, 0, 0, 0))
    out.append(('pos Stock', 1, 0, n + 1, 0))
    out.append(('pos out of range', 1, 0, n + 2, 0))
    out += [(f'bad handle {lab}', 1, 0, 'bad:' + lab, 0) for lab, _, _ in bad_handles()]
    out.append(('slot k=4', 1, 0, 'k4', 0))
    # the label through ed_guide (real view code + keys word + fm_mod): '*' iff modified
    for j in (1, 9, 10, 14):
        for pm in (54, 64):
            out.append((f'label look {j} pm {pm}', j, None, 'label', 0))
            out.append((f'label look {j} pm {pm} modified', j, 5, 'label', 1))
    return out


def _bad(lab):
    for l2, b, L in bad_handles():
        if l2 == lab:
            return b, L


def m_case(args):
    label, j, off, mode, want = args
    edit = None if off is None else (lambda b: [b.__setitem__(32 + 64 * k + off, b[32 + 64 * k + off] ^ 1) for k in range(4)])
    blk, L = placed_block(j, edit)
    k = 0
    if isinstance(mode, int):
        for kk in range(4):
            L[O['pos'] + kk] = mode
    elif isinstance(mode, str) and mode.startswith('bad:'):
        b2, L2 = _bad(mode[4:])
        b2[32:96 + 192] = blk[32:96 + 192]
        b2[544:676] = blk[544:676]
        blk, L = b2, bytearray(L2)
        for kk in range(4):
            L[O['pos'] + kk] = j + 1
    elif mode == 'k4':
        k = 4
    if mode == 'label':
        pm = int(label.split('pm ')[1].split()[0])
        e = EV.guide_case(G['stock'], G['lay'], 4, 2755, H_OK, blk, 3, pm=pm, star=bool(want),
                          extra=lambda im: [Region('L', L_AT, bytes(L), 'r'), img(im, 0x601e323c, 0x601e383c, 'extras')] + code_regions(im))
        return label, e
    src = f' mov {G["es"]["ed_cfg_fm"]:#x},a1\n mov (a1),a1\n mov {P_OK:#x},a2\n mov {k},d1\n calls (a1)\n'
    code, sy = asm(src, DRV)
    regions = [Region('drv', DRV, code, 'rx'), Region('L', L_AT, bytes(L), 'r')] + code_regions(G['lay']) + \
        EV.state_regions(H_OK, blk, 'r')
    r = run(regions, {'pc': DRV}, sy['done'])
    if r['fault'] or r['registers']['pc'] != sy['done']:
        return label, f'run {r["fault"]}'
    rg = r['registers']
    if rg['d0'] != want or rg['a2'] != P_OK or any(rg[x] != SENT[x] for x in ('d2', 'd3', 'a3')) or rg['sp'] != SP0:
        return label, f'd0 {rg["d0"]} want {want} / registers'
    return label, None


PARTS = dict(M=(m_cases, m_case), V=(v_cases, v_case), U=(u_cases, u_case), P=(p_cases, p_case), L=(l_cases, l_case),
             H=(lambda q=False: [('load once',)], h_case),
             T=(lambda q=False: [(f'save key {k:#x} after {s} picks', k, s) for k, s in
                                 ((0x13b3, 2), (0x13b4, 1), (0x13b5, 10), (0x140c, 16))], t_case))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--layered', required=True)
    ap.add_argument('--part', default='V,U,P,L,H,T')
    ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--quick', action='store_true')
    a = ap.parse_args()
    init(a.base, a.layered)
    ok = True
    for p in a.part.split(','):
        cases_fn, fn = PARTS[p]
        cases = cases_fn(a.quick)
        with ProcessPoolExecutor(a.jobs, initializer=init, initargs=(a.base, a.layered)) as ex:
            res = list(ex.map(fn, cases))
        fails = [f'{lab}: {e}' for lab, e in res if e]
        print(f'{p}: {len(res) - len(fails)}/{len(res)} {"PASS" if not fails else "FAIL"}', flush=True)
        for f in fails[:12]:
            print('   ', f)
        ok &= not fails
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
