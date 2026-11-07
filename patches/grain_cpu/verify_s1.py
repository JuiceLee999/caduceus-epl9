#!/usr/bin/env python3
"""Emulator checks for grain_cpu s1 and s3 (s3: the level reaches the work list through the block, +95) (real lock, mapper, lookup, builder; malloc, free, blend setup and flush stubbed). Offline.

  .venv/bin/python -I patches/grain_cpu/verify_s1.py releases/v0.26/edits.json generated/grain_cpu/s1/edits.json [generated/grain_cpu/s1/pkg]

  M  gc_grain == the model below, each window class, rows at the 0xd0000000 edge with the real residue; record fields; 4 rows per lock; mode restored; image read-only
  F  guards: image untouched, buffers balanced
  L  lists: Grain Off == v0.26 for every flag set and key; plain Grain = dev(gc_nomod) + gc_ob; Glow and Art keep their passes; marked only if plain
  O  output route: gc_ob waits, grains, then runs the stock pass; grain 0 and unmarked: straight to stock
  A  flag gate: Grain Off == v0.26; plain Grain: no 0x80; Art + Grain: 0x80
  E  Extras: sector 1 read and write +50 clamped 0..3, sector 9 read and write +24 as the old sector 1, labels, others unchanged
  K  Film pick keeps +24 and +50; the `*` ignores them and still sees other changes; loader and MOVIE.BIN ranges
  T, C, B, P  half-press file, next capture, real blend setup, anti-brick
  W  s3 hand-off: the flag hook leaves the level at block +95 (plain looks only); the builder takes it once, before any job marker exists
  X  alignment: every word and halfword access our block makes in these runs is aligned (the camera faults where the emulator doesn't)
"""
import importlib.util, json, struct, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V = _load('gc_verify', ROOT / 'patches/grain_cpu/verify.py')
D = _load('gc_verify_d3', ROOT / 'patches/grain_cpu/verify_d3.py')
M, GV = V.M, V.GV
GV.SEGS.append(('blk', 0x601df000, 0x601e3800, 'rx'))
Region, execute = V.Region, V.execute
BASE, CALLER, STK, JOB, ALLOC, HEAP_U, HEAP_C = V.BASE, V.CALLER, V.STK, V.JOB, V.ALLOC, V.HEAP_U, V.HEAP_C
P_AT, H = D.P_AT, D.H
S = {1: 23, 2: 55, 3: 91}
OB, SF = 0x6035b529, 0x6035ca31
TABLE = 0x60210900


# ------------------------------------------------------------------ the model
def table(s, c=991):
    y = np.arange(256)[:, None]; h = np.arange(32)[None, :]
    return np.clip(y + (((64 * h - c) * V.G[:, None] * s + 131072) >> 18), 0, 255).astype(np.uint8)


def xs(r):
    r ^= (r << 13) & 0xffffffff; r ^= r >> 17; r ^= (r << 5) & 0xffffffff
    return r


def expected(pic, w, h, st, s, seed):
    ring = np.zeros(16384, dtype=np.int64); prev, r, i = 15, seed, 0
    for _ in range(4096):
        r = xs(r); x = r
        for _ in range(4):
            n = (x & 15) + ((x >> 4) & 15)
            ring[i] = (n + prev + 1) >> 1; prev = n; i += 1; x >>= 8
    span = 16383 - w
    t = table(s)
    a = np.frombuffer(pic, dtype=np.uint8).copy().reshape(h, st * 2)
    r = xs(r); po = (((r >> 8) & 0xffff) * span) >> 16
    for y in range(h):
        r = xs(r); o = (((r >> 8) & 0xffff) * span) >> 16
        n = (ring[o:o + w] + ring[po:po + w] + 1) >> 1
        a[y, 0:2 * w:2] = t[a[y, 0:2 * w:2], n]
        po = o
    return a.tobytes(), r


def slot_table(grain=(0, 2, 2, 2), effect=0, strength=0, art=0, nr=0):
    t = bytearray(512)
    for i, g in enumerate(grain):
        t[i * 64 + 50] = g; t[i * 64 + 28] = effect; t[i * 64 + 29] = strength; t[i * 64 + 46] = art; t[i * 64 + 24] = nr
    return bytes(t)


def stubbed(new, gc, table_):
    q = bytearray(V.stubbed(new, gc))
    q[TABLE - BASE:TABLE - BASE + 512] = table_
    q[OB - BASE:OB - BASE + 2] = b'\xf0\xfc'                     # the stock pass: rets
    return bytes(q)


def regions(q, gc, entry, j, cached, pic, fail=0, sf=0, pool=True, pic2=None, tbl=None):
    wr = b'\xfc\xff' + struct.pack('<i', entry - CALLER) + b'\xcb'
    p = bytearray(2048); p[0:4] = b'EP7B'; p[32:32 + 512] = tbl or slot_table()
    st = bytearray(8); struct.pack_into('<H', st, 2, H + 1 if pool else 0)
    r = [Region('low', 0x60020020, q[:0x60100000 - BASE], 'rx'), Region('blk', 0x601df000, q[0x601df000 - BASE:0x601e4000 - BASE], 'rx'), Region('isp', 0x60350000, q[0x60350000 - BASE:0x60360000 - BASE], 'rx'),
         Region('sec1', 0x60210000, q[0x60210000 - BASE:0x60211000 - BASE], 'rx'), Region('sec2', 0x6055e000, q[0x6055e000 - BASE:0x6055f000 - BASE], 'rx'),
         Region('caller', CALLER, wr, 'rx'), Region('stk', STK, bytes(0x4000), 'rw', True), Region('job', JOB, bytes(j), 'rw', True),
         Region('alloc', ALLOC, struct.pack('<IIIIII', HEAP_U, fail, 0, sf, 0, 0) + bytes(64), 'rw', True), Region('heap', HEAP_C, bytes(0x40000), 'rw'),
         Region('heapu', HEAP_U, bytes(0x400), 'rw', True), Region('pool', P_AT + H, bytes(p), 'rw', True), Region('st', 0x622cbcc0, bytes(st), 'rw'),
         Region('pic', cached, bytes(pic), 'rw', True), Region('cpu', 0x8000, bytes(0x100), 'rw'), Region('magic', 0x8ff00000, bytes(0x1000), 'rw'),
         Region('c0', 0x28900000, bytes(0x1000), 'rw'), Region('c1', 0x28980000, bytes(0x1000), 'rw'), Region('c2', 0x28a00000, bytes(0x1000), 'rw'), Region('c3', 0x28a80000, bytes(0x1000), 'rw'),
         Region('win', 0x98100000, bytes(0x1000), 'rw', True), Region('modes', V.MODES & ~0xff, bytes(0x100), 'rw', True)]
    if pic2:
        r.append(Region('pic2', pic2[0], pic2[1], 'rw', True))
    return r


def run(q, gc, entry, j, cached, pic, **kw):
    rg = regions(q, gc, entry, j, cached, pic, **kw)
    r = execute(rg, {'pc': CALLER, 'sp': STK + 0x3000, 'a0': JOB, 'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}, CALLER + 6, limit=9000000, timeout=200, trace_limit=100000 if kw.get('pic2') or len(ALIGN) < 3 else 0)
    if r['trace']:
        ALIGN.append((q, r))
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    rr = r['registers']
    al = struct.unpack('<IIIIII', m['alloc'][:24])
    return dict(ok=not r['fault'] and rr['pc'] == CALLER + 6 and rr['sp'] == STK + 0x3000 and (rr['d2'], rr['d3'], rr['a2'], rr['a3']) == (0x2222, 0x3333, 0xa2a2, 0xa3a3), fault=r['fault'], d0=rr['d0'], pc=rr['pc'], m=m, frees=al[2], mallocs=(al[0] - HEAP_U) // 0x10000,
                sf=al[4], flushes=al[5], n=r['attempted'], blk=m['heapu'][:80], f=D.fields(m['heapu'][:80]), pic=m['pic'])


def job(bus, marked=True, **kw):
    j = D.jb(bus, **kw)
    if marked:
        j[15491] = 0xa5
    return j


def t_model(q, gc):
    bad, n = [], 0
    ob, sg = int(gc['gc_ob'], 16), int(gc['gc_gs'], 16)
    for name, (bus, cached, m) in V.CLASSES.items():
        for lv, entry in ((1, sg), (2, ob), (3, ob)):
            w, h, st = 128, 9, 160
            pic = V.picture(w, h, st)
            r = run(q, gc, entry, job(bus, w=w, h=h, stride=st, profile=2), cached, pic, tbl=slot_table((0, lv, 0, 0)))
            want, sd = expected(pic, w, h, st, S[lv], 0x12345678)
            f = r['f']; cl = 0 if bus < 0xb0000000 else (2 if m else 1)
            locks = 3
            n += 1
            if not (r['ok'] and r['pic'] == want and r['frees'] == 2 and r['mallocs'] == 3 and (f['stage'], f['guard']) == (7, 0) and f['seed'] == sd and f['rows'] == h and f['cls'] & 15 == cl and r['flushes'] == locks * (2 if m else 1) + (2 if not m else 2) + (0 if not m else 0)):
                bad.append((name, lv, r['fault'], r['pic'] == want, f['stage'], hex(f['guard']), r['flushes'], f['cls']))
    edge, real, pitch = 0xd0000000, 0xce9d4b80, 10368
    k = (edge - real) % pitch
    bus = edge - k - 2 * pitch
    rows, st = 6, 5184
    pic = V.picture(5184, rows, st)
    cut = edge - bus
    j = job(bus, w=5184, h=rows, stride=st, profile=3)
    r = run(q, gc, ob, j, 0x70000000 | (bus & 0x07ffffff), pic[:cut], pic2=(0x70000000, pic[cut:]))
    want, sd = expected(pic, 5184, rows, st, S[2], 0x12345678)
    f = r['f']; n += 1
    if not (r['ok'] and r['m']['pic'] + r['m']['pic2'] == want and f['rows'] == rows and f['split'] == 1 and struct.unpack_from('<I', r['m']['modes'], V.MODES & 0xff)[0] == 0):
        bad.append(('edge', r['fault'], r['m']['pic'] + r['m']['pic2'] == want, f['rows'], f['split']))
    return bad, n


def t_guards(q, gc):
    bad, n = [], 0
    ob = int(gc['gc_ob'], 16)
    w, h, st, bus, c = 128, 5, 160, 0xa4000000, 0x64000000
    pic = V.picture(w, h, st)
    for gid, kw in ((0x20, dict(fmt=0x0305)), (0x21, dict(x=4)), (0x22, dict(y=4)), (0x24, dict(w=5464, stride=5472)), (0x26, dict(stride=64)), (0x29, dict(size=100)), (0x2a, dict(bus=0x90000000)), (0x2d, dict(bus=0xc1000000)), (0x32, dict(bus=0xdfffff00))):
        kw = dict(dict(w=w, h=h, stride=st, bus=bus), **kw); b = kw.pop('bus')
        r = run(q, gc, ob, job(b, **kw), c, pic)
        n += 1
        if not (r['ok'] and r['pic'] == pic and r['f']['guard'] == gid and r['frees'] == 0):
            bad.append((hex(gid), r['fault'], r['pic'] == pic, hex(r['f']['guard']), r['frees']))
    for gid, fail, frees in ((0x2f, 2, 0), (0x30, 3, 1)):
        r = run(q, gc, ob, job(bus, w=w, h=h, stride=st), c, pic, fail=fail); n += 1
        if not (r['ok'] and r['pic'] == pic and r['f']['guard'] == gid and r['frees'] == frees):
            bad.append((hex(gid), r['fault'], hex(r['f']['guard']), r['frees']))
    return bad, n


def t_route(q, gc):
    bad, n = [], 0
    ob = int(gc['gc_ob'], 16)
    w, h, st, bus, c = 128, 5, 160, 0xa4000000, 0x64000000
    pic = V.picture(w, h, st)
    # pending request on the previous entry: waited for (slot cleared) before the image is touched
    j = job(bus, w=w, h=h, stride=st)
    struct.pack_into('<H', j, 11312, 1); struct.pack_into('<I', j, 10992, 0)
    r = run(q, gc, ob, j, c, pic); n += 1
    if not (r['ok'] and r['pic'] != pic and r['f']['stage'] == 7 and r['f']['mode'] == 0):
        bad.append(('marked', r['fault'], r['f']['stage'], hex(r['f']['guard'])))
    for name, jb_ in (('unmarked', job(bus, marked=False, w=w, h=h, stride=st)), ('COLOR1 off', job(bus, w=w, h=h, stride=st, profile=1)), ('type', job(bus, w=w, h=h, stride=st, jtype=0x30))):
        r = run(q, gc, ob, jb_, c, pic); n += 1
        if not (r['ok'] and r['pic'] == pic and r['mallocs'] <= 1 and r['frees'] == 0):
            bad.append((name, r['fault'], r['pic'] == pic, r['mallocs']))
    return bad, n


def t_list(old, new, gc):
    bad, n = [], 0
    gs, ob, nm = int(gc['gc_gs'], 16), int(gc['gc_ob'], 16), int(gc['gc_nomod'], 16)
    sw = lambda e: tuple(gs if x == SF else (ob if x == OB else x) for x in e)
    off = slot_table((0, 0, 0, 0))
    on = slot_table((2, 2, 2, 2))
    for key, cls in ((11, 0), (11, 4), (12, 0), (12, 4), (0x01010068, 0), (5, 0)):
        for feat in (0, 0x80000, 0x80080, 0x800c0, 0x80480, 0x80040, 0x80400):
            a, ae = M.build(old, key, cls, feat=feat, table=off)
            b, be = M.build(new, key, cls, feat=feat, table=off)
            n += 1
            ok = a['ok'] and b['ok'] and be == [sw(e) for e in ae] and a['job'] == b['job']
            if not ok:
                bad.append(('off', hex(key), cls, hex(feat), [tuple(map(hex, e)) for e in be][:4]))
    for cls in (0, 4):
        b, be = M.build(new, 11, cls, feat=0x80000, table=on, jtype=0x1000); n += 1
        if not (b['ok'] and len(be) == 1 and b['job'][15491] == 0):      # no level handed over (no block): v0.26's list
            bad.append(('plain, no hand-off', cls, [tuple(map(hex, e)) for e in be]))
        for feat in (0x80080, 0x800c0, 0x80480):
            a, ae = M.build(old, 11, cls, feat=feat, table=off, jtype=0x1000)
            b, be = M.build(new, 11, cls, feat=feat, table=on, jtype=0x1000); n += 1
            if not (b['ok'] and be == [sw(e) for e in ae] and b['job'][15491] == 0):
                bad.append(('passes', cls, hex(feat)))
        for g in (0, 4, 255):
            b, be = M.build(new, 11, cls, feat=0x80000, table=slot_table((g, g, g, g)), jtype=0x1000); n += 1
            if b['job'][15491] or len(be) != 1:
                bad.append(('byte', g, len(be)))
    return bad, n


def t_flag(old, new):
    bad, n = [], 0
    for grain in (0, 1, 3, 4):
        for art, eff in ((0, 0), (1, 0), (2, 0), (0, 1)):
            for key, mode, prof, kind in ((11, 11, 2, 0x1001), (11, 11, 4, 0), (11, 11, 1, 0x1001), (12, 12, 2, 0x1001), (11, 11, 2, 0x2001), (11, 11, 2, 0x1008)):
                t = slot_table((grain,) * 4, art=art, effect=eff, strength=2 if eff else 0)
                a = V.flag_run(old, key, mode, prof, kind, 0x80000, t); b = V.flag_run(new, key, mode, prof, kind, 0x80000, t)
                force = 1 <= grain <= 3 and art in (1, 2) and key == 11 and mode == 11 and kind not in (0x2001, 0x1008)
                n += 1
                if a[0] or b[0] or not b[1] or b[2] != (a[2] | 0x80 if force else a[2]):
                    bad.append((grain, art, eff, key, prof, hex(kind), a[0], b[0], hex(a[2]), hex(b[2])))
    return bad, n


# ------------------------------------------------------------------ Extras
EMARK, AXIS, DIRTY = 680, 684, 685


def p_block(slot=None):
    p = bytearray(2048); p[0:4] = b'EP7B'
    struct.pack_into('<I', p, EMARK, struct.unpack('<I', b'EP7E')[0]); p[AXIS] = 4
    if slot:
        p[32 + 64:32 + 128] = slot
    return p


def ex_regions(q, p, extra=()):
    st = bytearray(8); struct.pack_into('<H', st, 2, H + 1)
    return [Region('blk', 0x601df000, q[0x601df000 - BASE:0x601e4000 - BASE], 'rx'), Region('stk', STK, bytes(0x4000), 'rw', True), Region('pool', P_AT + H, bytes(p), 'rw', True), Region('st', 0x622cbcc0, bytes(st), 'rw'),
            Region('all', 0x61fc3800, bytes(16), 'r'), Region('out', ALLOC, bytes(16), 'rw', True)] + list(extra)


def ex_get(q, sym, sector, p):
    wr = b'\xfc\xff' + struct.pack('<i', sym - CALLER) + b'\xcb'
    r = execute(ex_regions(q, p, [Region('c', CALLER, wr, 'rx')]), {'pc': CALLER, 'sp': STK + 0x3000, 'd0': 939 + sector, 'a1': ALLOC}, CALLER + 6, limit=3000, trace_limit=3000)
    ALIGN.append((q, r))
    return r['fault'], struct.unpack_from('<I', {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}['out'], 0)[0]


def ex_set(q, sym, sector, val, p):
    wr = b'\xdd' + struct.pack('<i', sym - CALLER) + b'\xe0\x10'     # call ex_set,[d2,d3,a2],16
    sget = Region('sget', 0x602af887, b'\x80\x00\xdf\x00\x04', 'rx')
    mgr = Region('mgr', 0x60827440, b'\xdf\xe0\x10', 'rx')
    sec3 = Region('sec3', 0x605b7000, q[0x605b7000 - BASE:0x605b7800 - BASE], 'rx')
    sec6 = Region('sec6', 0x61242000, q[0x61242000 - BASE:0x61243000 - BASE], 'rx')
    r = execute(ex_regions(q, p, [Region('c', CALLER, wr, 'rx'), sget, mgr, sec3, sec6]), {'pc': CALLER, 'sp': STK + 0x3000, 'd0': 939 + sector, 'd1': val & 0xffffffff, 'a0': 0x11, 'a1': 0x22}, CALLER + 7, limit=3000)
    return r['fault'], {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}['pool'], r['registers']['pc'] == CALLER + 7


def t_extras(old, new, new_s, gc):
    bad, n = [], 0
    get = int(new_s['look_extras']['symbols'].get('ex_get', '0x601e32a3'), 16) if isinstance(new_s.get('look_extras'), dict) and 'symbols' in new_s['look_extras'] else 0x601e32a3
    sets = next(a for a in range(0x601e3340, 0x601e3366) if new[a - BASE:a - BASE + 3] == b'\xf8\xfe\xfc')
    for g in (0, 1, 2, 3, 4, 200):
        s = bytearray(64); s[50] = g; s[24] = 6
        f, v = ex_get(new, get, 0, p_block(s)); n += 1
        if f or v != (g if g < 4 else 0):
            bad.append(('get s1', g, f, v))
    for b_, u in ((0, 0), (6, 1), (1, 2), (2, 3), (3, 3), (5, 3), (7, 0), (200, 0)):
        s = bytearray(64); s[24] = b_
        f, v = ex_get(new, get, 8, p_block(s)); n += 1
        fo, vo = ex_get(old, get, 0, p_block(s))
        if f or v != u or v != vo:
            bad.append(('get s9', b_, f, v, vo))
    for sec in (1, 2, 3, 4, 5, 6, 7, 9, 10, 11):
        s = bytearray(64); s[25] = 1; s[26] = 2; s[27] = 3; s[47] = 1; s[48] = 2; s[49] = 1; s[46] = 1; s[28] = 3; s[29] = 2
        a, b = ex_get(old, get, sec, p_block(s)), ex_get(new, get, sec, p_block(s)); n += 1
        if a != b:
            bad.append(('other', sec, a, b))
    if sets:
        for val, g in ((-3, 0), (0, 0), (1, 1), (2, 2), (3, 3), (5, 3)):
            s = bytearray(64); s[24] = 6
            f, m, ok = ex_set(new, sets, 0, val, p_block(s)); n += 1
            if f or not ok or m[32 + 64 + 50] != g or m[32 + 64 + 24] != 6 or m[DIRTY] != 1:
                bad.append(('set s1', val, f, m[32 + 64 + 50]))
        for val, b_ in ((-1, 0), (0, 0), (1, 6), (2, 1), (3, 2), (5, 2)):
            s = bytearray(64); s[50] = 2
            f, m, ok = ex_set(new, sets, 8, val, p_block(s)); n += 1
            if f or not ok or m[32 + 64 + 24] != b_ or m[32 + 64 + 50] != 2 or m[DIRTY] != 1:
                bad.append(('set s9', val, f, m[32 + 64 + 24]))
    u32 = lambda a: struct.unpack_from('<I', new, a - BASE)[0]
    txt = lambda a: new[a - BASE:a - BASE + 18].split(b'\0')[0]
    t1 = u32(0x601e356e); t9 = int(gc['gc_t9'], 16)
    want1, want9 = [b'1 Grain Off', b'1 Grain Low', b'1 Grain Med', b'1 Grain High'], [b'9 NR Camera', b'9 NR Std', b'9 NR Low', b'9 NR Off']
    n += 1
    if [txt(u32(t1 + 4 * i)) for i in range(4)] != want1 or [txt(u32(t9 + 4 * i)) for i in range(4)] != want9 or txt(0x601e3713) != b'Extras: 1-9 only':
        bad.append(('labels', [txt(u32(t1 + 4 * i)) for i in range(4)]))
    return bad, n


def t_pick(old, new, gc, new_s):
    """u_apply with the real bytes; lt_mod with a look record."""
    bad, n = [], 0
    T = bytes((i * 3 + 1) & 0x7f for i in range(64))
    T = bytearray(T); T[24] = 3
    slot = bytearray(64); slot[24] = 6; slot[50] = 2; slot[46] = 1
    tail = Region('tail', 0x601e2e4f, b'\xcb\xcb', 'rx')
    q = new
    blk = [Region('a', 0x601e2e00, q[0x601e2e00 - BASE:0x601e2e4f - BASE], 'rx'), Region('b', 0x601e3700, q[0x601e3700 - BASE:0x601e3800 - BASE], 'rx'), Region('c', 0x601df000, q[0x601df000 - BASE:0x601e0b3c - BASE], 'rx'),
           Region('t', ALLOC, bytes(T) + bytes(64), 'rw', True), Region('s', JOB, bytes(slot), 'rw', True), tail]
    rg = blk + [Region('stk', STK, bytes(0x4000), 'rw')]
    r = execute(rg, {'pc': 0x601e2e35, 'sp': STK + 0x3000, 'a1': ALLOC, 'd0': JOB}, 0x601e2e4f, limit=3000)
    s2 = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}['s']
    n += 1
    good = not r['fault'] and s2[24] == 6 and s2[50] == 2 and s2[25] == T[25] and s2[49] == T[49] and s2[51] == 0
    if not good:
        bad.append(('pick', r['fault'], s2[24], s2[50], s2[25], T[25]))
    # the `*`: record == slot apart from +24 and +50 -> 0; another byte -> 1
    lt = int(new_s['look_tone']['symbols']['lt_mod'], 16) if 'symbols' in new_s.get('look_tone', {}) else None
    LA = 0xa1dd9000
    if lt:
        def mod(entry):
            p = bytearray(2048); struct.pack_into('<I', p, 1020, struct.unpack('<I', b'EP7F')[0]); struct.pack_into('<I', p, 1016, LA)
            p[32:96] = entry
            L = bytearray(0x1000); struct.pack_into('<I', L, 2112, struct.unpack('<I', b'EP7L')[0]); struct.pack_into('<I', L, 2116, P_AT + H)
            L[2120] = 2; L[2121] = 1
            L[64:128] = rec
            wr = b'\xfc\xff' + struct.pack('<i', lt - CALLER) + b'\xcb'
            rg = [Region('c', 0x601df000, new[0x601df000 - BASE:0x601e4000 - BASE], 'rx'), Region('w', CALLER, wr, 'rx'), Region('stk', STK, bytes(0x4000), 'rw'), Region('p', P_AT + H, bytes(p), 'r'), Region('L', LA, bytes(L), 'r')]
            r = execute(rg, {'pc': CALLER, 'sp': STK + 0x3000, 'a2': P_AT + H, 'd1': 0}, CALLER + 6, limit=3000)
            return r['fault'], r['registers']['d0']
        rec = bytearray(64)
        rec[:32] = bytes(i + 1 for i in range(32))
        e = bytearray(rec[:32]) + bytes(32)
        e2 = bytearray(e); e2[24] = 6; e2[50] = 3
        e3 = bytearray(e2); e3[25] += 1
        for nm, en, want in (('same', e, 0), ('nr+grain', e2, 0), ('other', e3, 1)):
            f, v = mod(en); n += 1
            if f or v != want:
                bad.append(('mod', nm, f, v))
    # ranges
    n += 1
    if new[0x605b7721 + 50 - BASE] != 3 or new[0x605b7721 - 64 + 50 - BASE] != 0 or struct.unpack_from('<H', new, 0x601e0d12 - BASE)[0] != 867 or new[0x601e0d15 - BASE] != 13:
        bad.append(('ranges',))
    return bad, n



# ------------------------------------------------------------------ s3: the level hand-off, and alignment
def pool_regions(pending=0, have=True):
    p = bytearray(2048); p[0:4] = b'EP7B'; p[32:32 + 512] = slot_table((0, 2, 2, 2))
    if have:
        struct.pack_into('<I', p, 1000, HEAP_U)
    st = bytearray(8); struct.pack_into('<H', st, 2, H + 1)
    b = bytearray(0x400); b[:4] = b'GDIA'; b[80:84] = b'GRND'; b[95] = pending
    return [Region('pool', P_AT + H, bytes(p), 'rw', True), Region('st', 0x622cbcc0, bytes(st), 'rw'), Region('heapu', HEAP_U, bytes(b), 'rw', True)]


ALIGN = []


def wl_run(main, key, cls, feat, pending, jtype=0x1000, trace=False):
    """The real builder from the hook site, with no job marker (as on the camera at that point) and a block holding a pending level."""
    j = GV.job_bytes(key=key, jtype=jtype, cls=cls, ext=(0, 0, 0))
    struct.pack_into('<I', j, 16, feat)
    lst = bytearray(32); lst[4] = 1
    struct.pack_into('<I', lst, 16, GV.ENTRIES)
    rg = GV.regions(main, slot_table((0, 2, 2, 2)), [GV.stack({4: GV.JOB, 8: GV.JOB + 11308}), GV.Region('list', GV.LIST, bytes(lst), 'rw', True),
                    GV.Region('entries', GV.ENTRIES, bytes(12 * 16), 'rw', True), GV.Region('job', GV.JOB, bytes(j), 'rw', True)] + pool_regions(pending))
    regs = {'pc': 0x6035749f, 'sp': GV.STACK + 0x1800, 'd2': key, 'd3': 0x3333, 'a2': GV.JOB + 4, 'a3': GV.LIST}
    x = GV.execute(rg, regs, 0x60357c91, limit=200000, trace_limit=100000 if trace else 0)
    if trace:
        ALIGN.append((main, x))
    m = GV.mem(x)
    n = struct.unpack_from('<H', m['list'], 0)[0]
    ents = [struct.unpack_from('<III', m['entries'], 12 * i) for i in range(n)]
    return x['fault'], x['registers']['pc'] == 0x60357c91, ents, m['job'], m['heapu']


def t_handoff(old, new, gc):
    bad, n = [], 0
    ob, nm = int(gc['gc_ob'], 16), int(gc['gc_nomod'], 16)
    for lv in (1, 2, 3):
        f, ok, e, j, b = wl_run(new, 11, 0, 0x80000, lv, trace=(lv == 2)); n += 1
        if f or not ok or [(x[0], x[1]) for x in e] != [(0x60356d7b, nm), (ob, 0)] or j[15491] != 0xa5 or b[95] != 0 or (b[5], b[4]) != (1, 0x4f):
            bad.append(('route', lv, f, [tuple(map(hex, x)) for x in e], j[15491], b[95], b[5], hex(b[4])))
    for name, key, feat, pend, jt, guard, taken in (('no level', 11, 0x80000, 0, 0x1000, 0, False), ('level 4', 11, 0x80000, 4, 0x1000, 0, False), ('Glow', 11, 0x80080, 2, 0x1000, 0x43, True),
                                                   ('no shading bit', 11, 0, 2, 0x1000, 0x44, True), ('live view', 11, 0x80000, 2, 0x30, 0, False), ('MONO', 12, 0x80000, 2, 0x1000, 0, False)):
        f, ok, e, j, b = wl_run(new, key, 0, feat, pend, jtype=jt)
        a = M.build(old, key, 0, feat=feat, table=slot_table((0, 0, 0, 0)), jtype=jt, ext=(0, 0, 0))
        n += 1
        same = [tuple(ob if y == OB else (int(gc['gc_gs'], 16) if y == SF else y) for y in x) for x in a[1]]
        if f or not ok or e != same or j[15491] or (b[95] == 0) != (taken or pend == 0) or b[4] != guard:
            bad.append((name, f, [tuple(map(hex, x)) for x in e][:3], j[15491], b[95], hex(b[4])))
    # the flag hook: level for plain looks, 0 for Art and Off
    for grain, art, want in ((2, 0, 2), (3, 0, 3), (2, 1, 0), (0, 0, 0)):
        cap = bytearray(24100); cap[24053] = 11; cap[24083] = 2; struct.pack_into('<H', cap, 194, 0x1001)
        par = bytearray(32); struct.pack_into('<H', par, 10, 11); struct.pack_into('<I', par, 12, 0x80000)
        t = slot_table((0, grain, 0, 0), art=art)
        rg = [Region('blk', 0x601df000, new[0x601df000 - BASE:0x601e4000 - BASE], 'rx'), Region('sec1', 0x60210000, new[0x60210000 - BASE:0x60211000 - BASE], 'rx'),
              Region('conv', 0x603ea900, new[0x603ea900 - BASE:0x603eae00 - BASE], 'rx'), Region('sec2', 0x6055e000, new[0x6055e000 - BASE:0x6055f000 - BASE], 'rx'), Region('stk', STK, bytes(0x4000), 'rw'),
              Region('cap', JOB, bytes(cap), 'rw'), Region('par', ALLOC, bytes(par), 'rw', True)]
        pr = pool_regions(9)
        pp = bytearray(pr[0].data); pp[32:32 + 512] = t
        rg += [Region('pool', P_AT + H, bytes(pp), 'rw', True), pr[1], pr[2]]
        x = execute(rg, {'pc': V.FLAG_SITE, 'sp': STK + 0x3000, 'a2': ALLOC + 12, 'a3': JOB}, V.FLAG_RET, limit=6000, trace_limit=100000)
        ALIGN.append((new, x))
        m = {y['name']: bytes.fromhex(y['hex']) for y in x['memory']}
        n += 1
        fl = struct.unpack_from('<I', m['par'], 12)[0]
        if x['fault'] or m['heapu'][95] != want or bool(fl & 0x80) != (art == 1 and grain > 0):
            bad.append(('flag', grain, art, x['fault'], m['heapu'][95], hex(fl)))
    return bad, n


def t_data_align(new_s, gc):
    from importlib import util
    sp_ = util.spec_from_file_location('gc_s1b', ROOT / 'patches/grain_cpu/build_s1.py'); b = util.module_from_spec(sp_); sp_.loader.exec_module(b)
    bad = b.data_alignment(b.source(), {k: int(v, 16) for k, v in gc.items()})
    return bad, 1


def t_align(block_at, block_end, gc):
    """Every load and store inside our block, in the traced runs, checked for natural alignment."""
    import re
    from importlib import util
    sp_ = util.spec_from_file_location('gc_b', ROOT / 'patches/grain_cpu/build.py'); b = util.module_from_spec(sp_); sp_.loader.exec_module(b)
    bad, n = [], 0
    for main, x in ALIGN:
        code = main[block_at - BASE:block_end - BASE]
        ins = {a: (op, args) for a, op, args in b.SB3.disasm(code, block_at, int(gc['gc_btab'], 16))}
        for row in x['trace']:
            pc = row['pc']
            if pc not in ins:
                continue
            op, args = ins[pc]
            size = {'mov': 4, 'movhu': 2}.get(op)
            if not size:
                continue
            m = re.search(r'\(([^)]*)\)', args)
            if not m:
                continue
            parts = [p_.strip() for p_ in m.group(1).split(',')]
            if parts[-1] in ('sp',):
                continue
            regs = {k: row[k] for k in ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3')}
            addr = 0
            for p_ in parts:
                addr += regs[p_] if p_ in regs else int(p_, 0)
            n += 1
            if addr % size:
                bad.append((hex(pc), op, args, hex(addr & 0xffffffff)))
    return bad, n


def t_pkg(base_s, new_s, new, pkg, rst, info, disk, old):
    sb = {b.kind: b for b in V.oc.parse(V.BP.STOCK.read_bytes())}
    good = True
    for b in V.oc.parse(pkg):
        exp = bytearray(sb[b.kind].payload)
        for e in new_s['edits']:
            if int(e['kind'], 16) == b.kind:
                o = V.BP.resolve(b.kind, e['addr']); nb = bytes.fromhex(e['new']); exp[o:o + len(nb)] = nb
        good &= bytes(exp) == b.payload
    for b in V.oc.parse(rst):
        good &= b.payload == sb[b.kind].payload
    g = new_s['grain_cpu']
    um = int(g['um'], 16)
    ours = [(int(g['code_at'], 16), g['code_len']), (0x603579b8, 4), (0x60357b1f, 4), (0x603eabd8, 4), (int(g['bw_default'], 16), 3), (0x605b7421, 4), (0x603574a0, 4), (0x601e32c9, 4), (0x601e33d8, 4), (0x601e356e, 4), (0x601e1264, 4), (0x601e128c, 4), (0x601e12eb, 4),
            (0x601e3713, 16), (0x601e2e36, 4), (um, 5), (0x605b7721 + 50, 1), (0x601e0d12, 2), (0x601e0d15, 1)] + [(int(e['addr'], 16), len(e['new']) // 2) for e in new_s['edits'] if e.get('source') == 'patches/fw_version']
    diff = [BASE + i for i in range(len(old)) if old[i] != new[i]]
    stray = [hex(a) for a in diff if not any(s_ <= a < s_ + k for s_, k in ours)]
    good &= not stray
    if disk:
        good &= (disk / 'patched.pkg.bin').read_bytes() == pkg and (disk / 'restore-stock.pkg.bin').read_bytes() == rst
    return good, f'{info["edits"]} edits, {info["changed_payload_bytes"]} B; {len(diff)} B differ from v0.26; stray {stray[:6]}'


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    old, *_ = V.image(base_s)
    new, pkg, rst, info = V.image(new_s)
    gc = new_s['grain_cpu']['symbols']
    q = stubbed(new, gc, slot_table())
    D.EV = D.V_SB3.EV_PRESS
    q2 = bytearray(q); q2[D.WFILE - BASE:D.WFILE - BASE + 3] = b'\xdf\xf0\x1c'; q2 = bytes(q2)
    ok = True
    for name, fn in (('M model', lambda: t_model(q, gc)), ('F guards', lambda: t_guards(q, gc)), ('O route', lambda: t_route(q, gc)), ('L lists', lambda: t_list(old, new, gc)), ('A flag gate', lambda: t_flag(old, new)),
                     ('E Extras', lambda: t_extras(old, new, new_s, gc)), ('K pick and files', lambda: t_pick(old, new, gc, new_s)), ('T half-press', lambda: D.t_trig(q2, gc)), ('W hand-off', lambda: t_handoff(old, new, gc)),
                     ('Y data labels', lambda: t_data_align(new_s, gc)), ('X alignment', lambda: t_align(int(new_s['grain_cpu']['code_at'], 16), int(new_s['grain_cpu']['code_at'], 16) + new_s['grain_cpu']['code_len'], gc))):
        bad, n = fn(); ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:5] if bad else '')
    good, txt = V.t_blend(new); ok &= good
    print(f"{'PASS' if good else 'FAIL'} B blend setup: {txt}")
    good, txt = t_pkg(base_s, new_s, new, pkg, rst, info, disk, old); ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: {txt}")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
