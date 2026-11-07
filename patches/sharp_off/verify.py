#!/usr/bin/env python3
"""Emulator checks for sharp_off t1 (real firmware code; the property getter and slot lookup are stubbed). Offline.

  .venv/bin/python -I patches/sharp_off/verify.py releases/v0.27/edits.json generated/sharp/t1/edits.json [generated/sharp/t1/pkg]

  S  stills: the real capture site 0x602a7ed1..ee7 through sh_get and v0.25's sc_slot: -5 only for COLOR1-4 with +51 == 1, else == v0.27
  G  gain: stock stage 0x603ac0c1 gives gain 0 for key 11 at Sharpness -5 (every ISO field, still and resize branches); stage code == v0.27
  M  movie: the real message site 0x60315900 -> sh_msg -> mv_msg -> 0x60315908: message +18 = -5 only for movie + Vivid + Movie slot +51 == 1;
     every other message byte and register == v0.27, also with no table, bad magic, no P2
  E  Extras: sector 10 get/set/guide, other sectors == v0.27, "Extras: 1-10 only" for 11-12
  K  +51 stays as the user set it: Film pick (look, own, Stock), the `*` compare, defaults (any reset)
  F  files: SD loader span +51 = 1, mv_load zero check +52..63, tools/ep7_bundles_bin.py and tools/ep7_movie_bin.py accept 0..1 and reject 2
  Y  alignment: data labels, block start, every word / halfword address the block uses in these runs
  P  anti-brick: package reparses, restore == stock, decoded == stock + edits, only our sites differ from v0.27
"""
import importlib.util, json, struct, subprocess, sys, tempfile, zlib
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


SH = _load('sharp_off_build', ROOT / 'patches/sharp_off/build.py')
SB3, MV = SH.SB3, SH.MV
BASE = 0x60020020
CALLER, STK, CAP, SLOTS, ALLOC, JOB, REC, MSG, P2 = 0x18000000, 0x18010000, 0x1a000000, 0x1b000000, 0x1d000000, 0x1e000000, 0x1c000000, 0x1c100000, 0x1c200000
P_AT, H = 0xa1f8d800, 0x80                # pool handle used by the grain checks: state word H + 1
EMARK, AXIS, DIRTY = 680, 684, 685
TRACES = []                               # (image, result) of every run, for the alignment check


def image(spec):
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    return [b for b in oc.parse(pkg) if b.kind == 0x100][0].payload, pkg, rst, info


def R(q, name, lo, hi, perm='rx'):
    return Region(name, lo, q[lo - BASE:hi - BASE], perm)


def mem(r):
    return {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}


def ex(regions, regs, stop, limit=4000, q=None):
    r = execute(regions, regs, stop, limit=limit, trace_limit=min(limit, 100000))
    if q is not None:
        TRACES.append((q, r))
    return r


def run(regions, regs, stop, limit=4000, q=None):
    return ex(regions, regs, stop, limit, q)


# ------------------------------------------------------------------ S: stills
def fake_getter(vals):
    """Getter stand-in at 0x6005e971: key -> value; returns as the real one ([d2,d3],12)."""
    lines = []
    for i, (k, v) in enumerate(vals.items()):
        lines.append(f' cmp {k},d0\n bne 1{i}f\n mov {v},d0\n ret [d2,d3],12\n1{i}:')
    src = ' .am33_2\n .text\n .global _start\n_start:\n' + '\n'.join(lines) + '\n mov 0x7777,d0\n ret [d2,d3],12\n'
    return SB3.assemble(src, SH.GETTER, {})[0]


TBL_STUB = None


def tbl_stub():
    global TBL_STUB
    if TBL_STUB is None:   # d0 = slot 0..3 -> a0 = SLOTS + 64*slot; called `call 0x6055e7b0,[d2,d3],8`
        TBL_STUB = SB3.assemble(f' .am33_2\n .text\n .global _start\n_start:\n asl2 d0\n asl2 d0\n asl2 d0\n mov d0,a0\n add {SLOTS},a0\n ret [d2,d3],8\n', 0x6055e7b0, {})[0]
    return TBL_STUB


def stills(q, pm, cpm, prof, b51, sharp):
    slots = bytearray(256)
    for k in range(4):
        slots[64 * k + 51] = b51[k]
    g = fake_getter({38017: pm, 40209: cpm, 63153: prof, 33049: sharp & 0xffff})
    rg = [R(q, 'site', 0x602a7ec0, 0x602a7f00), R(q, 'sh', 0x601de000, 0x601de400), R(q, 'v25', 0x601e3900, 0x601e3b3c), Region('get', SH.GETTER, g, 'rx'),
          Region('tbl', 0x6055e7b0, tbl_stub(), 'rx'), Region('slots', SLOTS, bytes(slots), 'r'), Region('cap', CAP, bytes(24100), 'rw', True), Region('stk', STK, bytes(0x2000), 'rw')]
    r = run(rg, {'pc': 0x602a7ed1, 'sp': STK + 0x1000, 'd3': CAP, 'd2': 0x2222}, 0x602a7ee7, q=q)
    ok = r['registers']['pc'] == 0x602a7ee7 and not r['fault']
    return ok, struct.unpack_from('<H', mem(r)['cap'], 24010)[0], r['registers']['d2'], r['registers']['d3']


def t_stills(old, new):
    bad, n = [], 0
    for pm, cpm in ((11, 0), (6, 11), (2, 0), (12, 0), (6, 2), (1, 0)):
        for prof in (0, 1, 2, 3, 4, 5, 255):
            for b51 in ((1, 1, 1, 1), (0, 0, 0, 0), (2, 2, 2, 2), (1, 0, 1, 0), (0, 1, 0, 1)):
                for sharp in (-2, 0, 2):
                    a, b = stills(old, pm, cpm, prof, b51, sharp), stills(new, pm, cpm, prof, b51, sharp)
                    hit = (pm == 11 or (pm == 6 and cpm == 11)) and 1 <= prof <= 4 and b51[prof - 1] == 1
                    want = 0xfffb if hit else sharp & 0xffff
                    n += 1
                    if not a[0] or not b[0] or b[1] != want or a[1] != sharp & 0xffff or b[2:] != a[2:]:
                        bad.append((pm, cpm, prof, b51, sharp, a, b))
    return bad, n


# ------------------------------------------------------------------ G: the stage
def stage(q, eid, sharp, iso=0, lv=False):
    req = bytearray(2048); struct.pack_into('<H', req, 1610, iso); req[1795] = sharp & 0xff
    ctx = bytearray(256)
    struct.pack_into('<III', ctx, 4, 0x1b800000, 0, 0x1b900000); struct.pack_into('<I', ctx, 52, eid)
    if lv:
        struct.pack_into('<H', ctx, 80, 0x0c0); ctx[106] = 1; ctx[107] = 1
    wr = b'\xdd' + struct.pack('<i', 0x603ac0c1 - CALLER) + b'\xf0\x1c\xcb'
    rg = [Region('c', CALLER, wr, 'rx'), R(q, 'code', 0x603a0000, 0x603c0000), R(q, 'data', 0x604e0000, 0x60540000, 'r'), Region('stk', STK, bytes(0x2000), 'rw'),
          Region('ctx', 0x1a800000, bytes(ctx), 'rw'), Region('req', 0x1b800000, bytes(req), 'rw'), Region('regs', 0x1b900000, bytes(128), 'rw', True)]
    r = execute(rg, {'pc': CALLER, 'sp': STK + 0x1000, 'a0': 0x1a800000}, CALLER + 7, limit=200000)
    w = struct.unpack_from('<I', mem(r)['regs'], 12)[0]
    return r['registers']['pc'] == CALLER + 7 and not r['fault'], (w >> 16) & 0xff, mem(r)['regs']


def t_gain(old, new):
    bad, n = [], 0
    n += 1
    if old[0x603a0000 - BASE:0x603c0000 - BASE] != new[0x603a0000 - BASE:0x603c0000 - BASE] or old[0x604e0000 - BASE:0x60540000 - BASE] != new[0x604e0000 - BASE:0x60540000 - BASE]:
        bad.append('stage code or tables differ from v0.27')
    for lv in (False, True):
        for iso in (0, 200, 800, 1600, 3200, 6400, 0x2000, 0xffff):
            ok, g, _ = stage(new, 11, -5, iso, lv); n += 1
            if not ok or g:
                bad.append(('off', lv, iso, ok, g))
            for s in (-2, 0, 2):
                a, b = stage(old, 11, s, iso, lv), stage(new, 11, s, iso, lv); n += 1
                if not a[0] or a[1:] != b[1:]:
                    bad.append(('stock', lv, iso, s))
    return bad, n


# ------------------------------------------------------------------ M: movie message
def pool_block(table=True, vm=True, p2=True):
    p = bytearray(2048)
    if table:
        p[0:4] = b'EP7B'
    if vm:
        struct.pack_into('<I', p, MV.VM, MV.VMAGIC)
    struct.pack_into('<I', p, MV.VP, P2 if p2 else 0)
    return p


def movie(q, movie_f, vivid, b51, state=H + 1, **kw):
    rec = bytearray(1024); struct.pack_into('<I', rec, 176, movie_f); rec[294] = vivid; rec[941 + 3] = 0x5a
    msg = bytearray(64); msg[16:20] = bytes((3, 1, 0xfe, 2)); msg[20] = 0x77
    p2 = bytearray(1024); p2[224 + 51] = b51
    st = bytearray(8); struct.pack_into('<H', st, 2, state)
    rg = [R(q, 'site', 0x60315800, 0x60315a00), R(q, 'sh', 0x601de000, 0x601de400), R(q, 'mv', 0x601e25ec, 0x601e283c), Region('rec', REC, bytes(rec), 'r'),
          Region('msg', MSG, bytes(msg), 'rw', True), Region('pool', P_AT + H, bytes(pool_block(**kw)), 'r'), Region('p2', P2, bytes(p2), 'r'), Region('st', 0x622cbcc0, bytes(st), 'r'),
          Region('stk', STK, bytes(0x2000), 'rw')]
    regs = {'pc': 0x60315900, 'sp': STK + 0x1000, 'd3': REC + 941, 'a1': MSG, 'd1': 0x1111, 'd2': 0x2222, 'a2': 0x3333, 'a3': 0x4444, 'd0': 0x55, 'a0': 0x66}
    r = run(rg, regs, 0x60315908, q=q)
    reg = {k: r['registers'][k] for k in ('d1', 'd2', 'd3', 'a1', 'a2', 'a3', 'sp', 'pc')}
    return not r['fault'] and r['registers']['pc'] == 0x60315908, mem(r)['msg'], reg, r['registers']['a0'], r['registers']['d0']


def t_movie(old, new):
    bad, n = [], 0
    envs = [dict(), dict(state=0), dict(state=0xffff), dict(state=H + 1 + 8), dict(table=False), dict(vm=False)]
    for env in envs:
        for mf in (0, 1, 2):
            for viv in (0, 1, 2, 11):
                for b51 in (0, 1, 2):
                    a, b = movie(old, mf, viv, b51, **env), movie(new, mf, viv, b51, **env)
                    hit = not env and mf == 1 and viv == 1 and b51 == 1
                    n += 1
                    want = bytearray(a[1])
                    if hit:
                        want[18] = 0xfb
                    if not a[0] or not b[0] or b[1] != bytes(want) or b[2] != a[2] or (b[3], b[4]) != (a[3], a[4]):
                        bad.append((env, mf, viv, b51, a[0], b[0], a[1][16:21].hex(), b[1][16:21].hex()))
    return bad, n


# ------------------------------------------------------------------ E, K: Extras
def p_block(slot=None):
    p = bytearray(2048); p[0:4] = b'EP7B'
    struct.pack_into('<I', p, EMARK, struct.unpack('<I', b'EP7E')[0]); p[AXIS] = 4
    if slot:
        p[32 + 64:32 + 128] = slot
    return p


def ex_regions(q, p, extra=()):
    st = bytearray(8); struct.pack_into('<H', st, 2, H + 1)
    return [R(q, 'blk', 0x601de000, 0x601e4000), Region('stk', STK, bytes(0x4000), 'rw', True), Region('pool', P_AT + H, bytes(p), 'rw', True), Region('st', 0x622cbcc0, bytes(st), 'rw'),
            Region('all', 0x61fc3800, bytes(16), 'r'), Region('out', ALLOC, bytes(16), 'rw', True)] + list(extra)


def ex_get(q, sector, p, entry=0x601e32a3):
    wr = b'\xfc\xff' + struct.pack('<i', entry - CALLER) + b'\xcb'
    r = ex(ex_regions(q, p, [Region('c', CALLER, wr, 'rx')]), {'pc': CALLER, 'sp': STK + 0x3000, 'd0': 939 + sector, 'a1': ALLOC}, CALLER + 6, limit=3000, q=q)
    return r['fault'], struct.unpack_from('<I', mem(r)['out'], 0)[0]


def ex_set(q, sector, val, p):
    sets = next(a for a in range(0x601e3340, 0x601e3366) if q[a - BASE:a - BASE + 3] == b'\xf8\xfe\xfc')
    wr = b'\xdd' + struct.pack('<i', sets - CALLER) + b'\xe0\x10'
    extra = [Region('c', CALLER, wr, 'rx'), Region('sget', 0x602af887, b'\x80\x00\xdf\x00\x04', 'rx'), Region('mgr', 0x60827440, b'\xdf\xe0\x10', 'rx'),
             R(q, 'sec3', 0x605b7000, 0x605b7800), R(q, 'sec6', 0x61242000, 0x61243000)]
    r = ex(ex_regions(q, p, extra), {'pc': CALLER, 'sp': STK + 0x3000, 'd0': 939 + sector, 'd1': val & 0xffffffff, 'a0': 0x11, 'a1': 0x22}, CALLER + 7, limit=3000, q=q)
    return r['fault'], mem(r)['pool'], r['registers']['pc'] == CALLER + 7


def guide(q, sector, p):
    """tone_x's guide code from 0x601e12a8 (a2 = the 'only' text) to the text writer: -> the label it gets."""
    stk = bytearray(0x4000); struct.pack_into('<I', stk, 0x3008, 939)
    rg = ex_regions(q, p)
    rg[1] = Region('stk', STK, bytes(stk), 'rw', True)
    r = ex(rg, {'pc': 0x601e12a8, 'sp': STK + 0x3000, 'd3': sector}, 0x601e35b4, limit=3000, q=q)
    if r['fault'] or r['registers']['pc'] != 0x601e35b4:
        return None
    a = r['registers']['a2']
    return q[a - BASE:a - BASE + 24].split(b'\0')[0]


def t_extras(old, new):
    bad, n = [], 0
    for b51, want in ((0, 0), (1, 1), (2, 0), (200, 0)):
        s = bytearray(64); s[51] = b51; s[50] = 2; s[24] = 6
        f, v = ex_get(new, 9, p_block(s)); n += 1
        if f or v != want:
            bad.append(('get 10', b51, f, v))
    for sec in (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 11):
        s = bytearray(64); s[24] = 6; s[25] = 1; s[26] = 2; s[27] = 3; s[28] = 3; s[29] = 2; s[46] = 1; s[47] = 1; s[48] = 2; s[49] = 1; s[50] = 2; s[51] = 1
        n += 1
        if ex_get(old, sec, p_block(s)) != ex_get(new, sec, p_block(s)):
            bad.append(('other get', sec))
    for val, want in ((-3, 0), (-1, 0), (0, 0), (1, 1), (2, 1), (5, 1)):
        s = bytearray(64); s[50] = 2; s[24] = 6; s[51] = 0 if val > 0 else 1
        f, m, ok = ex_set(new, 9, val, p_block(s)); n += 1
        exp = bytearray(p_block(s)); exp[32 + 64 + 51] = want; exp[DIRTY] = 1
        if f or not ok or m != bytes(exp):
            bad.append(('set 10', val, f, ok, m[32 + 64 + 51]))
    for sec, val in ((0, 2), (8, 3), (7, 1), (10, 1), (11, -1), (2, 3)):
        s = bytearray(64); s[51] = 1; s[50] = 1; s[24] = 6
        a, b = ex_set(old, sec, val, p_block(s)), ex_set(new, sec, val, p_block(s)); n += 1
        if a[0] or b[0] or a[1:] != b[1:] or b[1][32 + 64 + 51] != 1:
            bad.append(('other set', sec, val))
    for b51, want in ((0, b'10 Sharp Camera'), (1, b'10 Sharp Off'), (5, b'10 Sharp Camera')):
        s = bytearray(64); s[51] = b51
        g = guide(new, 9, p_block(s)); n += 1
        if g != want:
            bad.append(('label 10', b51, g))
    for sec in (10, 11):
        n += 1
        g, go = guide(new, sec, p_block()), guide(old, sec, p_block())
        if g != b'Extras: 1-10 only' or go != b'Extras: 1-9 only':
            bad.append(('label', sec, g, go))
    for sec in (7, 8):
        s = bytearray(64); s[24] = 1; s[49] = 1
        n += 1
        if guide(new, sec, p_block(s)) != guide(old, sec, p_block(s)):
            bad.append(('label other', sec))
    return bad, n


def t_keep(old, new, new_s):
    bad, n = [], 0
    for name, T in (('look', bytes((i * 7 + 3) & 0x7f for i in range(64))), ('own', bytes(range(64))), ('Stock', bytes(64))):
        for b51 in (0, 1):
            slot = bytearray(64); slot[24] = 2; slot[50] = 3; slot[51] = b51
            rg = [R(new, 'a', 0x601e2e00, 0x601e2e4f), R(new, 'b', 0x601e3700, 0x601e3800), R(new, 'c', 0x601df000, 0x601e0b3c),
                  Region('t', ALLOC, bytes(T) + bytes(64), 'rw', True), Region('s', JOB, bytes(slot), 'rw', True), Region('tail', 0x601e2e4f, b'\xcb\xcb', 'rx'), Region('stk', STK, bytes(0x4000), 'rw')]
            r = ex(rg, {'pc': 0x601e2e35, 'sp': STK + 0x3000, 'a1': ALLOC, 'd0': JOB}, 0x601e2e4f, limit=3000, q=new)
            s2 = mem(r)['s']; n += 1
            if r['fault'] or s2[51] != b51 or s2[50] != 3 or s2[24] != 2:
                bad.append(('pick', name, b51, r['fault'], s2[51]))
    lt = int(new_s['look_tone']['symbols']['lt_mod'], 16)
    LA = 0xa1dd9000

    def mod(q, entry):
        p = bytearray(2048); struct.pack_into('<I', p, 1020, struct.unpack('<I', b'EP7F')[0]); struct.pack_into('<I', p, 1016, LA)
        p[32:96] = entry
        L = bytearray(0x1000); struct.pack_into('<I', L, 2112, struct.unpack('<I', b'EP7L')[0]); struct.pack_into('<I', L, 2116, P_AT + H)
        L[2120] = 2; L[2121] = 1
        L[64:128] = rec
        wr = b'\xfc\xff' + struct.pack('<i', lt - CALLER) + b'\xcb'
        rg = [R(q, 'c', 0x601de000, 0x601e4000), Region('w', CALLER, wr, 'rx'), Region('stk', STK, bytes(0x4000), 'rw'), Region('p', P_AT + H, bytes(p), 'r'), Region('L', LA, bytes(L), 'r')]
        r = ex(rg, {'pc': CALLER, 'sp': STK + 0x3000, 'a2': P_AT + H, 'd1': 0}, CALLER + 6, limit=3000, q=q)
        return r['fault'], r['registers']['d0']
    rec = bytearray(64); rec[:32] = bytes(i + 1 for i in range(32))
    e = bytearray(rec[:32]) + bytes(32)
    e1 = bytearray(e); e1[51] = 1
    e2 = bytearray(e1); e2[24] = 6; e2[50] = 3
    e3 = bytearray(e1); e3[25] += 1
    for nm, en, want in (('same', e, 0), ('sharp', e1, 0), ('sharp+nr+grain', e2, 0), ('other', e3, 1)):
        a, b = mod(old, en), mod(new, en); n += 1
        if b[0] or b[1] != want or a != b:
            bad.append(('*', nm, a, b))
    # defaults (what a reset writes): sector 10 answers its current value, the others as v0.27
    for sec, field, val, want in ((9, 51, 1, 1), (9, 51, 0, 0), (9, 51, 7, 0), (0, 50, 2, None), (8, 24, 6, None), (1, 28, 3, None), (10, 51, 1, None), (11, 51, 1, None)):
        s = bytearray(64); s[51] = 1; s[field] = val
        b, a = ex_get(new, sec, p_block(s), 0x601e3333), ex_get(old, sec, p_block(s), 0x601e3333); n += 1
        if b[0] or (want is not None and b[1] != want) or (want is None and a != b):
            bad.append(('default', sec, val, a, b))
    return bad, n


# ------------------------------------------------------------------ F: files
def t_files(new, rel):
    bad, n = [], 4
    if new[SH.RANGE + 51 - BASE] != 1 or new[SH.RANGE + 50 - BASE] != 3 or new[SH.RANGE - 64 + 51 - BASE] != 0 or any(new[SH.RANGE + k - BASE] for k in range(52, 64)):
        bad.append('SD loader span table')
    if struct.unpack_from('<H', new, SH.MVL_OFF - BASE)[0] != 868 or new[SH.MVL_CNT - BASE] != 12 or new[SH.MVL_OFF - 2 - BASE:SH.MVL_OFF - BASE] != b'\xfa\xd0' or new[SH.MVL_CNT - 1 - BASE] != 0x80:
        bad.append('mv_load zero check')
    BB = _load('ep7_bundles_bin_t', ROOT / 'tools/ep7_bundles_bin.py')
    base = (rel / 'card/EP7MOD/BUNDLES.BIN').read_bytes()
    def bun(k, v):
        d = bytearray(base); d[BB.SB.HDR_LEN + 64 * k + 51] = v
        L = BB.SB.FILE_LEN
        struct.pack_into('<I', d, 16, zlib.crc32(bytes(d[:16] + d[20:L])) & 0xffffffff)
        return bytes(d)
    if BB.check_file(base, tone=True) or BB.check_file(bun(1, 1), tone=True) or BB.check_file(bun(3, 1), tone=True) or not BB.check_file(bun(1, 2), tone=True):
        bad.append(('ep7_bundles_bin', BB.check_file(bun(1, 1), tone=True), BB.check_file(bun(1, 2), tone=True)))
    mb = (rel / 'card/EP7MOD/MOVIE.BIN').read_bytes()
    def mov(i, v):
        d = bytearray(mb); d[16 + i] = v; struct.pack_into('<I', d, 12, zlib.crc32(bytes(d[16:96])))
        return bytes(d)
    with tempfile.TemporaryDirectory() as t:
        res = []
        for i, v, ok in ((51, 0, True), (51, 1, True), (51, 2, False), (52, 1, False)):
            f = Path(t) / f'm{i}{v}.bin'; f.write_bytes(mov(i, v))
            rc = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/ep7_movie_bin.py'), '--check', str(f)], capture_output=True, text=True)
            res.append((rc.returncode == 0) == ok)
        if not all(res):
            bad.append(('ep7_movie_bin', res))
    return bad, n


# ------------------------------------------------------------------ Y, P
def t_align(new_s):
    import re
    so = new_s['sharp_off']
    sym = {k: int(v, 16) for k, v in so['symbols'].items()}
    at, end = int(so['code_at'], 16), sym['sh_cam']
    bad = SH.data_alignment(SH.source(new_s), sym)
    if at % 4 or sym['sh_cam'] % 4:
        bad.append('block or string start')
    n = 2
    for q, r in TRACES:
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
            if parts[-1] == 'sp':
                continue
            regs = {k: row[k] for k in ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3')}
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
    so = new_s['sharp_off']
    ours = [(int(so['code_at'], 16), so['code_len']), (SH.CAP_SITE + 1, 4), (SH.MSG_SITE + 1, 4), (SH.SG_SITE + 1, 4), (SH.SS_SITE + 1, 4), (SH.SU_SITE + 1, 4), (SH.DEF_SITE + 1, 4),
            (SH.X_SITE + 2, 4), (SH.RANGE + 51, 1), (SH.MVL_OFF, 2), (SH.MVL_CNT, 1)] + \
        [(int(e['addr'], 16), len(e['new']) // 2) for e in new_s['edits'] if e.get('source') == 'patches/fw_version']
    diff = [BASE + i for i in range(len(old)) if old[i] != new[i]]
    stray = [hex(a) for a in diff if not any(s_ <= a < s_ + k for s_, k in ours)]
    good &= not stray
    if disk:
        good &= (disk / 'patched.pkg.bin').read_bytes() == pkg and (disk / 'restore-stock.pkg.bin').read_bytes() == rst
    return good, f'{info["edits"]} edits, {info["changed_payload_bytes"]} B; {len(diff)} B differ from v0.27; stray {stray[:6]}'


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    rel = Path(sys.argv[1]).resolve().parent
    old, *_ = image(base_s)
    new, pkg, rst, info = image(new_s)
    ok = True
    for name, fn in (('S stills', lambda: t_stills(old, new)), ('G gain', lambda: t_gain(old, new)), ('M movie', lambda: t_movie(old, new)),
                     ('E Extras', lambda: t_extras(old, new)), ('K +51 kept', lambda: t_keep(old, new, new_s)), ('F files', lambda: t_files(new, rel)), ('Y alignment', lambda: t_align(new_s))):
        bad, n = fn(); ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:4] if bad else '', flush=True)
    good, txt = t_pkg(new_s, new, pkg, rst, info, disk, old); ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: {txt}")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
