#!/usr/bin/env python3
"""Emulator checks for grain_cpu t1 (real firmware lock, flush, mapper and buffer lookup; synthetic job and image). Offline.

  .venv/bin/python -I patches/grain_cpu/verify.py releases/v0.26/edits.json generated/grain_cpu/t1/edits.json [generated/grain_cpu/t1/pkg]

  M  bit-exact: Y bytes == the model below (same formula as the OM-3 port's research/grain/model.py) at S 28/68/112, direct and
     through each window class; Cb, Cr and row padding untouched; seed carries to the next photo; window mode restored
  F  guards: bad format, offsets, width, stride, rows, size, bus range, malloc failures, blend error, no record, other jobs:
     image untouched, buffers freed, result and registers as stock
  G  flag gate and weight: COLOR2-4 ordinary stills get 0x80 and w 1024; COLOR1, MONO, special kinds == v0.26; Glow keeps its weight
  W  work list: the blend word points to gc_gs, other flags' lists == v0.26
  B  real blend setup: waits for its request, frees its sources; lookup 0x1000 then finds the new 0x0302 record
  P  anti-brick: package reparses, restore == stock, decoded == stock + edits, only our sites differ from v0.26
"""
import json, struct, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools')); sys.path.insert(0, str(ROOT / 'patches/grain_c'))
from penf_emulator import Region, execute  # noqa: E402
import build_package as BP, oly_container as oc  # noqa: E402
import map as M, ep7_grain_verify as GV  # noqa: E402

BASE, SF, MALLOC, FREE, FLUSH = 0x60020020, 0x6035ca31, 0x60022782, 0x600227b4, 0x60066fc0
CALLER, STK, JOB, ALLOC, HEAP_U, HEAP_C = 0x18000000, 0x18010000, 0x1e000000, 0x1d000000, 0xa5000000, 0x65000000
FLAG_SITE, FLAG_RET, W_SITE = 0x603eabd7, 0x603eabdd, 0x6039fee8
S = {1: 28, 2: 68, 3: 112}
MODES = 0xa2716034                        # per-CPU window mode array read by 0x600672ee
CLASSES = {'direct': (0xa4000000, 0x64000000, 0), 'b0': (0xb1000000, 0x71000000, 0), 'b8': (0xb9000000, 0x79000000, 0),
           'c8': (0xc8100000, 0x70100000, 3), 'c4': (0xc4100000, 0x74100000, 2), 'd0': (0xd0100000, 0x70100000, 4), 'd8': (0xd8100000, 0x78100000, 4)}


# ------------------------------------------------------------------ the model
def ss(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


G = np.array([round(255 * (0.08 + 0.92 * ss((y - 25) / 75)) * (1 - 0.25 * ss((y - 200) / 55))) for y in range(256)], dtype=np.int64)


def table(s):
    y = np.arange(256)[:, None]; h = np.arange(32)[None, :]
    return np.clip(y + (((64 * h - 945) * G[:, None] * s + 131072) >> 18), 0, 255).astype(np.uint8)


def noise(w, h, seed):
    v = np.full(w, 15, dtype=np.int64); out = np.zeros((h, w), dtype=np.uint8); r = seed
    for yy in range(h):
        rs = []
        for _ in range(w // 4):
            r ^= (r << 13) & 0xffffffff; r ^= r >> 17; r ^= (r << 5) & 0xffffffff
            rs.append(r)
        b = np.frombuffer(np.array(rs, dtype='<u4').tobytes(), dtype=np.uint8).astype(np.int64)
        v = (v + ((b & 15) + (b >> 4))) >> 1
        out[yy] = (v + np.concatenate([[15], v[:-1]]) + 1) >> 1
    return out, r


# ------------------------------------------------------------------ the run
def image(spec):
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    return [b for b in oc.parse(pkg) if b.kind == 0x100][0].payload, pkg, rst, info


def stubbed(im, sym):
    """Replace malloc, free, the blend setup and the cache flush (its busy bit needs hardware) by stubs that count; lock, mapper and lookup are real."""
    from importlib import util
    s = util.spec_from_file_location('gc_build', ROOT / 'patches/grain_cpu/build.py'); b = util.module_from_spec(s); s.loader.exec_module(b)
    im = bytearray(im)
    for at, src in ((MALLOC, f''' mov ({ALLOC + 4:#x}),d0
 cmp 0,d0
 beq 1f
 add -1,d0
 mov d0,({ALLOC + 4:#x})
 cmp 0,d0
 bne 1f
 mov 0,a0
 ret [],4
1:
 mov ({ALLOC:#x}),d0
 mov d0,a0
 add 0x10000,d0
 mov d0,({ALLOC:#x})
 ret [],4
'''), (FREE, f''' mov ({ALLOC + 8:#x}),d0
 inc d0
 mov d0,({ALLOC + 8:#x})
 ret [],4
'''), (FLUSH, f''' mov ({ALLOC + 20:#x}),d0
 inc d0
 mov d0,({ALLOC + 20:#x})
 ret [d2,d3],16
'''), (SF, f''' mov ({ALLOC + 16:#x}),d0
 inc d0
 mov d0,({ALLOC + 16:#x})
 mov ({ALLOC + 12:#x}),d0
 rets
''')):
        code, _, _, _ = b.SB3.assemble(src, at, {})
        im[at - BASE:at - BASE + len(code)] = code
    return bytes(im)


def slice_(im, lo, hi, name, capture=False):
    return Region(name, lo, im[lo - BASE:hi - BASE], 'rwx', capture)


def job_bytes(bus, fmt=0x0302, stride=160, w=128, h=5, size=None, xy=0, jtype=0x1000, key=11, profile=2, mode=11, mark=0xb2, rec_id=4096):
    j = bytearray(15512)
    struct.pack_into('<H', j, 20, jtype); struct.pack_into('<I', j, 11308, key)
    j[15488:15491] = bytes((profile, mode, mark))
    r = 6592 + 88 * 3                     # record 3: the lookup must find it
    struct.pack_into('<I', j, r, bus)
    struct.pack_into('<HHHHHH', j, r + 8, fmt, stride, w, h, xy, 0)
    struct.pack_into('<I', j, r + 64, bus)
    struct.pack_into('<II', j, r + 72, stride * 2 * h if size is None else size, rec_id)
    return j


def run(im, j, cached, pic, mode0=0, fail=0, sf=0, seed=None, gc=None):
    q = im
    if seed is not None:
        q = bytearray(im); struct.pack_into('<I', q, int(gc['gc_seed'], 16) - BASE, seed); q = bytes(q)
    wr = b'\xfc\xff' + struct.pack('<i', int(gc['gc_gs'], 16) - CALLER) + b'\xcb'
    modes = bytearray(0x100); struct.pack_into('<I', modes, MODES - (MODES & ~0xff), mode0)
    rg = [slice_(q, 0x60020020, 0x60100000, 'low'), slice_(q, 0x601e0000, 0x601e4000, 'blk', True), slice_(q, 0x60350000, 0x60360000, 'isp'),
          Region('caller', CALLER, wr, 'rx'), Region('stk', STK, bytes(0x4000), 'rw', True), Region('job', JOB, bytes(j), 'rw', True),
          Region('alloc', ALLOC, struct.pack('<IIIIII', HEAP_U, fail, 0, sf, 0, 0) + bytes(64), 'rw', True), Region('heap', HEAP_C, bytes(0x40000), 'rw'),
          Region('pic', cached, bytes(pic), 'rw', True), Region('cpu', 0x8000, bytes(0x100), 'rw'), Region('magic', 0x8ff00000, bytes(0x1000), 'rw'),
          Region('c0', 0x28900000, bytes(0x1000), 'rw'), Region('c1', 0x28980000, bytes(0x1000), 'rw'), Region('c2', 0x28a00000, bytes(0x1000), 'rw'), Region('c3', 0x28a80000, bytes(0x1000), 'rw'),
          Region('win', 0x98100000, bytes(0x1000), 'rw', True), Region('modes', MODES & ~0xff, bytes(modes), 'rw', True)]
    r = execute(rg, {'pc': CALLER, 'sp': STK + 0x3000, 'a0': JOB, 'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}, CALLER + 6, limit=4000000, timeout=120)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    rr = r['registers']
    al = struct.unpack('<IIIIII', m['alloc'][:24])
    ok = not r['fault'] and rr['pc'] == CALLER + 6 and rr['sp'] == STK + 0x3000 and (rr['d2'], rr['d3'], rr['a2'], rr['a3']) == (0x2222, 0x3333, 0xa2a2, 0xa3a3)
    return dict(ok=ok, fault=r['fault'], d0=rr['d0'], pic=m['pic'], seed=struct.unpack_from('<I', m['blk'], int(gc['gc_seed'], 16) - 0x601e0000)[0], frees=al[2], mallocs=(al[0] - HEAP_U) // 0x10000, 
                flushes=al[5], n=r['attempted'], win=m['win'], job=m['job'], modes=m['modes'])


def picture(w, h, stride):
    rng = np.random.default_rng(7)
    return rng.integers(0, 256, size=stride * 2 * h, dtype=np.uint8).tobytes()


def expected(pic, w, h, stride, s, seed):
    n, r = noise(w, h, seed)
    t = table(s)
    a = np.frombuffer(pic, dtype=np.uint8).copy().reshape(h, stride * 2)
    a[:, 0:2 * w:2] = t[a[:, 0:2 * w:2], n]
    return a.tobytes(), r


def t_model(im, gc):
    bad, n = [], 0
    w, h, st = 128, 5, 160
    pic = picture(w, h, st)
    for name, (bus, cached, m) in CLASSES.items():
        for lv in (1, 2, 3):
            res = run(im, job_bytes(bus, profile=lv + 1, w=w, h=h, stride=st), cached, pic, gc=gc)
            want, r = expected(pic, w, h, st, S[lv], 0x12345678)
            n += 1
            mode_after = struct.unpack_from('<I', res['modes'], MODES & 0xff)[0]
            if not (res['ok'] and res['pic'] == want and res['seed'] == r and res['frees'] == 2 and res['mallocs'] == 2 and res['d0'] == 0 and mode_after == 0 and res['flushes'] >= 5 + (6 if m else 0)):
                bad.append((name, lv, res['fault'], res['pic'] == want, hex(res['seed']), hex(r), res['frees'], res['flushes'], mode_after))
    # even rows, seed from the previous photo, already in the needed mode
    res = run(im, job_bytes(0xa4000000, profile=4, w=64, h=4, stride=64), 0x64000000, picture(64, 4, 64), seed=0xdeadbeef, gc=gc)
    want, r = expected(picture(64, 4, 64), 64, 4, 64, 112, 0xdeadbeef)
    n += 1
    if not (res['ok'] and res['pic'] == want and res['seed'] == r):
        bad.append(('seed', res['fault']))
    return bad, n


def t_guards(im, gc):
    bad, n = [], 0
    w, h, st, bus, c = 128, 5, 160, 0xa4000000, 0x64000000
    pic = picture(w, h, st)
    cases = [('format', dict(fmt=0x0305)), ('format2', dict(fmt=0x0c02)), ('offset', dict(xy=4)), ('width 0', dict(w=0)), ('width odd', dict(w=126)), ('width big', dict(w=5464, stride=5472)),
             ('stride', dict(stride=64)), ('rows 0', dict(h=0)), ('rows big', dict(h=8193)), ('size', dict(size=100)), ('no record', dict(rec_id=4097)),
             ('bus low', dict(bus=0x90000000)), ('bus high', dict(bus=0xe0000000)), ('bus io', dict(bus=0xc1000000)), ('bus edge', dict(bus=0xb7ffff00)), ('direct edge', dict(bus=0xafffff00)),
             ('marker', dict(mark=0)), ('mode', dict(mode=12)), ('type lv', dict(jtype=0x30)), ('type 0', dict(jtype=0)), ('key', dict(key=12)), ('COLOR1', dict(profile=1)), ('profile 5', dict(profile=5)), ('profile 0', dict(profile=0))]
    for name, kw in cases:
        kw = dict(dict(w=w, h=h, stride=st, bus=bus), **kw)
        b = kw.pop('bus')
        res = run(im, job_bytes(b, **kw), c, pic, gc=gc)
        n += 1
        if not (res['ok'] and res['pic'] == pic and res['seed'] == 0 and res['frees'] == res['mallocs'] == 0 and res['d0'] == 0):
            bad.append((name, res['fault'], res['pic'] == pic, res['frees'], res['mallocs']))
    for name, fail, frees in (('malloc 1', 1, 0), ('malloc 2', 2, 1)):
        res = run(im, job_bytes(bus, w=w, h=h, stride=st), c, pic, fail=fail, gc=gc)
        n += 1
        if not (res['ok'] and res['pic'] == pic and res['frees'] == frees and res['d0'] == 0):
            bad.append((name, res['fault'], res['frees'], res['mallocs']))
    res = run(im, job_bytes(bus, w=w, h=h, stride=st), c, pic, sf=40654, gc=gc)
    n += 1
    if not (res['ok'] and res['pic'] == pic and res['d0'] & 0xffff == 40654 and res['mallocs'] == 0):
        bad.append(('blend error', res['fault'], hex(res['d0'])))
    return bad, n


def flag_run(im, key, mode, profile, kind, flags=0, table=None):
    cap = bytearray(24100)
    cap[24053] = mode; cap[24083] = profile
    struct.pack_into('<H', cap, 194, kind)
    par = bytearray(32)
    par[8:12] = bytes(((key >> 24) & 255, (key >> 16) & 255)) + struct.pack('<H', key & 0xffff)
    struct.pack_into('<I', par, 12, flags)
    q = bytearray(im)
    if table is not None:
        q[0x60210900 - BASE:0x60210900 - BASE + len(table)] = table
    q = bytes(q)
    rg = [slice_(q, 0x601df000, 0x601e4000, 'blk'), slice_(q, 0x60210000, 0x60211000, 'sec1'), slice_(q, 0x603ea900, 0x603eae00, 'conv'), slice_(q, 0x6055e000, 0x6055f000, 'sec2'),
          Region('stk', STK, bytes(0x4000), 'rw', True), Region('cap', JOB, bytes(cap), 'rw'), Region('par', ALLOC, bytes(par), 'rw', True), Region('st', 0x622cbcc0, bytes(8), 'r')]
    r = execute(rg, {'pc': FLAG_SITE, 'sp': STK + 0x3000, 'a2': ALLOC + 12, 'a3': JOB}, FLAG_RET, limit=4000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    return r['fault'], r['registers']['pc'] == FLAG_RET, struct.unpack_from('<I', m['par'], 12)[0]


def slot(effect=0, strength=0, art=0):
    t = bytearray(8 * 64)
    for i in range(4):
        t[i * 64 + 28] = effect; t[i * 64 + 29] = strength; t[i * 64 + 46] = art
    return bytes(t)


def w_run(im, key, profile, table, ret=0x603a04ac):
    j = bytearray(15512)
    j[15488:15491] = bytes((profile, 11, 0xb2))
    req = 11364
    struct.pack_into('<II', j, req, 0x60355fd4, JOB + 14576 + 56)
    struct.pack_into('<I', j, 14576 + 56, JOB)
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, JOB + req); struct.pack_into('<I', ctx, 52, key)
    q = bytearray(im); q[0x60210900 - BASE:0x60210900 - BASE + len(table)] = table; q = bytes(q)
    rg = [slice_(q, 0x6039fe00, 0x603a0000, 'fn'), slice_(q, 0x60210000, 0x60211000, 'sec1'), slice_(q, 0x6055e000, 0x6055f000, 'sec2'), slice_(q, 0x604ec000, 0x604ed000, 'data'),
          Region('stk', STK, bytes(0x4000), 'rw'), Region('job', JOB, bytes(j), 'rw'), Region('ctx', ALLOC, bytes(ctx), 'rw'), Region('st', 0x622cbcc0, bytes(8), 'r'),
          Region('ret', ret & ~0xfff, bytes(0x2000), 'rx')]
    r = execute(rg, {'pc': W_SITE, 'sp': STK + 0x3000, 'a0': ALLOC, 'mdr': ret}, ret, limit=2000)
    return r['fault'], r['registers']['d0'] & 0xffff


def t_gate(old, new):
    bad, n = [], 0
    for prof in range(0, 6):
        for key, mode, kind in ((11, 11, 0x1001), (11, 11, 0x3001), (11, 11, 0), (12, 12, 0x1001), (11, 12, 0x1001), (0x01010065, 11, 0x1001), (11, 11, 0x2001), (11, 11, 0x2006), (11, 11, 0x1008), (11, 11, 0x1006)):
            for art, fl in ((0, 0x80000), (1, 0x80000), (2, 0)):
                t = slot(art=art)
                a = flag_run(old, key, mode, prof, kind, fl, t); b = flag_run(new, key, mode, prof, kind, fl, t)
                on = key == 11 and mode == 11 and 2 <= prof <= 4 and kind not in (0x2001, 0x2006, 0x1008, 0x1006)
                n += 1
                if a[0] or b[0] or not b[1] or b[2] != (a[2] | 0x80 if on else a[2]):
                    bad.append((prof, key, mode, hex(kind), art, a[0], b[0], hex(a[2]), hex(b[2])))
    for prof in (1, 2, 3, 4):
        f0, w0 = w_run(new, 11, prof, slot()); n += 1
        if f0 or w0 != 1024:
            bad.append(('w plain', prof, f0, w0))
        for eff, st in ((1, 1), (1, 5), (2, 3), (3, 2)):
            a, b = w_run(old, 11, prof, slot(eff, st)), w_run(new, 11, prof, slot(eff, st)); n += 1
            if a != b or a[0]:
                bad.append(('w glow', prof, eff, st, a, b))
    for key in (12, 0x01010065, 0x01010068):
        a, b = w_run(old, key, 2, slot()), w_run(new, key, 2, slot()); n += 1
        if a != b or a[0]:
            bad.append(('w key', hex(key), a, b))
    return bad, n


def t_list(old, new, gc):
    bad, n = [], 0
    gs = int(gc['gc_gs'], 16)
    for key, cls in ((11, 0), (11, 4), (12, 0), (12, 4), (0x01010068, 0)):
        for feat in (0x80000, 0x80080, 0x800c0, 0x80480, 0x80040, 0x80400, 0):
            a, ae = M.build(old, key, cls, feat=feat)
            b, be = M.build(new, key, cls, feat=feat)
            n += 1
            swap = [tuple(gs if x == 0x6035ca31 else x for x in e) for e in ae]
            if not (a['ok'] and b['ok'] and be == swap and a['job'] == b['job']):
                bad.append((hex(key), cls, hex(feat)))
            if feat & 0x80 and key == 11 and not any(e[0] == gs for e in be):
                bad.append(('no gc_gs', cls, hex(feat)))
    return bad, n


# ------------------------------------------------------------------ B: the real blend setup
def t_blend(im):
    """Real 0x6035ca31, with buffer allocation (0x6034442b callback 19 -> bus) and submit stubbed; the wait and the frees are real.
    After it returns, lookup 0x1000 finds the new record: 0x0302, 2 B/px, stride = width rounded up to 32, source records released."""
    from importlib import util
    s = util.spec_from_file_location('gc_build', ROOT / 'patches/grain_cpu/build.py'); b = util.module_from_spec(s); s.loader.exec_module(b)
    w, h, bus = 5184, 3888, 0xc8200000
    q = bytearray(im)
    for at, src in ((0x6034442b, f""" cmp 19,d0
 bne 1f
 mov {bus:#x},d0
 mov d0,(64,a1)
1:
 mov 1,d0
 ret [a2,a3],12
"""), (0x60354bb0, f""" mov d1,a0
 mov {ALLOC + 0x100:#x},d0
 mov d0,(a0)
 mov {ALLOC + 0x110:#x},a0
 mov ({ALLOC + 0x110:#x}),d0
 inc d0
 mov d0,(a0)
 clr d0
 ret [d2,d3,a2,a3],24
"""), (0x6035486d, f""" mov ({ALLOC + 0x114:#x}),d0
 inc d0
 mov d0,({ALLOC + 0x114:#x})
 clr d0
 ret [d3,a2,a3],28
""")):
        code, _, _, _ = b.SB3.assemble(src, at, {})
        q[at - BASE:at - BASE + len(code)] = code
    j = bytearray(15512)
    for i, (rid, base) in enumerate(((4096, 0xc8000000), (4192, 0xc8100000), (4193, 0xc8180000))):
        r = 6592 + 88 * i
        struct.pack_into('<I', j, r, base)
        struct.pack_into('<HHHH', j, r + 8, 0x0302, (w + 31) & ~31, w, h)
        struct.pack_into('<I', j, r + 64, base); struct.pack_into('<II', j, r + 72, ((w + 31) & ~31) * h * 2, rid)
    wr = b'\xfc\xff' + struct.pack('<i', SF - CALLER) + b'\xcb'
    q = bytes(q)
    rg = [slice_(q, 0x60020020, 0x60100000, 'low'), slice_(q, 0x60330000, 0x60368000, 'isp'), Region('caller', CALLER, wr, 'rx'), Region('stk', STK, bytes(0x4000), 'rw', True),
          Region('job', JOB, bytes(j), 'rw', True), Region('alloc', ALLOC, bytes(0x200), 'rw', True), Region('ms', 0x47001100, bytes(0x5e) + b'\xdf\xa0\x08' + bytes(0x40), 'rx'),
          Region('cpu', 0x8000, bytes(0x100), 'rw')]
    r = execute(rg, {'pc': CALLER, 'sp': STK + 0x3000, 'a0': JOB}, CALLER + 6, limit=200000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    jb, al = m['job'], m['alloc']
    ids = [struct.unpack_from('<I', jb, 6592 + 88 * i + 76)[0] for i in range(48)]
    hit = ids.index(4096) if 4096 in ids else -1
    rec = 6592 + 88 * hit
    f = struct.unpack_from('<HHHH', jb, rec + 8) if hit >= 0 else None
    g = struct.unpack_from('<HHHH', jb, rec + 16) if hit >= 0 else None
    addr = struct.unpack_from('<I', jb, rec)[0] if hit >= 0 else 0
    size = struct.unpack_from('<I', jb, rec + 72)[0] if hit >= 0 else 0
    waits, submits = struct.unpack_from('<I', al, 0x114)[0], struct.unpack_from('<I', al, 0x110)[0]
    good = (not r['fault'] and r['registers']['pc'] == CALLER + 6 and r['registers']['d0'] & 0xffff == 0 and f == (0x0302, (w + 31) & ~31, w, h) and addr == bus and size == ((w + 31) & ~31) * h * 2
            and submits == 1 and waits >= 1 and g == (w, h, 0, 0))
    return good, f'fault {r["fault"]} ret {r["registers"]["d0"] & 0xffff} rec {hit} {f} +16 {g} bus {addr:#x} size {size} submits {submits} waits {waits} ids {[hex(x) for x in ids[:5]]}'


def t_pkg(base_s, new_s, new, pkg, rst, info, disk, old):
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
    g = new_s['grain_cpu']
    ours = [(int(g['code_at'], 16), g['code_len']), (0x603579b8, 4), (0x603eabd8, 4), (int(g['bw_default'], 16), 3)] + [(int(e['addr'], 16), len(e['new']) // 2) for e in new_s['edits'] if e.get('source') == 'patches/fw_version']
    diff = [BASE + i for i in range(len(old)) if old[i] != new[i]]
    stray = [hex(a) for a in diff if not any(s <= a < s + k for s, k in ours)]
    good &= not stray
    if disk:
        good &= (disk / 'patched.pkg.bin').read_bytes() == pkg and (disk / 'restore-stock.pkg.bin').read_bytes() == rst
    return good, f'{info["edits"]} edits, {info["changed_payload_bytes"]} B; {len(diff)} B differ from v0.26; stray {stray[:6]}'


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    old, *_ = image(base_s)
    new, pkg, rst, info = image(new_s)
    gc = new_s['grain_cpu']['symbols']
    st = stubbed(new, gc)
    ok = True
    for name, fn in (('M model', lambda: t_model(st, gc)), ('F guards', lambda: t_guards(st, gc)), ('G gate', lambda: t_gate(old, new)), ('W list', lambda: t_list(old, new, gc))):
        bad, n = fn(); ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:5] if bad else '')
    res = run(st, job_bytes(0xa4000000, w=1296, h=8, stride=1296), 0x64000000, picture(1296, 8, 1296), gc=gc)
    base = run(st, job_bytes(0xa4000000, w=1296, h=4, stride=1296), 0x64000000, picture(1296, 4, 1296), gc=gc)
    per = (res['n'] - base['n']) / 4 / 1296
    print(f'CPU cost: {per:.2f} instructions per pixel (flush not counted); 5184 x 3888: about {per * 5184 * 3888 / 1e6:.0f} M; table and setup about {base["n"] - per * 4 * 1296:.0f}')
    good, txt = t_blend(new); ok &= good
    print(f"{'PASS' if good else 'FAIL'} B blend setup: {txt}")
    good, txt = t_pkg(base_s, new_s, new, pkg, rst, info, disk, old); ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: {txt}")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
