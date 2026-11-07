#!/usr/bin/env python3
"""Emulator checks for grain_cpu d1 (real lock, mapper, lookup; malloc, free, blend setup and flush stubbed). Offline.

  .venv/bin/python -I patches/grain_cpu/verify_d1.py releases/v0.26/edits.json generated/grain_cpu/d1/edits.json [generated/grain_cpu/d1/pkg]

  M  COLOR2/3 == model; COLOR4 first 128 rows Y = 16 then == model; block fields (stage, guard, record, window class, CPU, rows, band), each window class
  F  each guard has its own id; image untouched; buffers balanced; stock result kept
  R  readout: the page text for all 14 pages, wrap, empty field passes through, no block -> ----, clear after a read keeps the seed
  G, W, B, P  as verify.py (flag gate and weight, work list, real blend setup, anti-brick)
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
Region, execute = V.Region, V.execute
BASE, CALLER, STK, JOB, ALLOC, HEAP_U, HEAP_C = V.BASE, V.CALLER, V.STK, V.JOB, V.ALLOC, V.HEAP_U, V.HEAP_C
P_AT, H = 0xa1f8d800, 0x80
SETTER = 0x60d4c9df
NAMES = 'abcdefghijklmn'


def regions(q, gc, j, cached, pic, fail=0, sf=0, heap=None, pool=True):
    wr = b'\xfc\xff' + struct.pack('<i', int(gc['gc_gs'], 16) - CALLER) + b'\xcb'
    p = bytearray(2048); p[0:4] = b'EP7B'
    st = bytearray(8); struct.pack_into('<H', st, 2, H + 1 if pool else 0)
    return [V.slice_(q, 0x60020020, 0x60100000, 'low'), V.slice_(q, 0x601e0000, 0x601e4000, 'blk'), V.slice_(q, 0x60350000, 0x60360000, 'isp'),
            Region('caller', CALLER, wr, 'rx'), Region('stk', STK, bytes(0x4000), 'rw', True), Region('job', JOB, bytes(j), 'rw', True),
            Region('alloc', ALLOC, struct.pack('<IIIIII', HEAP_U, fail, 0, sf, 0, 0) + bytes(64), 'rw', True), Region('heap', HEAP_C, bytes(0x40000), 'rw'),
            Region('heapu', HEAP_U, bytes(heap) if heap else bytes(0x100), 'rw', True), Region('pool', P_AT + H, bytes(p), 'rw', True), Region('st', 0x622cbcc0, bytes(st), 'rw'),
            Region('pic', cached, bytes(pic), 'rw', True), Region('cpu', 0x8000, bytes(0x100), 'rw'), Region('magic', 0x8ff00000, bytes(0x1000), 'rw'),
            Region('c0', 0x28900000, bytes(0x1000), 'rw'), Region('c1', 0x28980000, bytes(0x1000), 'rw'), Region('c2', 0x28a00000, bytes(0x1000), 'rw'), Region('c3', 0x28a80000, bytes(0x1000), 'rw'),
            Region('win', 0x98100000, bytes(0x1000), 'rw', True), Region('modes', V.MODES & ~0xff, bytes(0x100), 'rw', True)]


def run(q, gc, j, cached, pic, **kw):
    rg = regions(q, gc, j, cached, pic, **kw)
    r = execute(rg, {'pc': CALLER, 'sp': STK + 0x3000, 'a0': JOB, 'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}, CALLER + 6, limit=8000000, timeout=200)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    rr = r['registers']
    al = struct.unpack('<IIIIII', m['alloc'][:24])
    return dict(ok=not r['fault'] and rr['pc'] == CALLER + 6 and rr['sp'] == STK + 0x3000 and (rr['d2'], rr['d3'], rr['a2'], rr['a3']) == (0x2222, 0x3333, 0xa2a2, 0xa3a3),
                fault=r['fault'], d0=rr['d0'], pic=m['pic'], blk=m['heapu'][:64], ptr=struct.unpack_from('<I', m['pool'], 1000)[0], frees=al[2], mallocs=(al[0] - HEAP_U) // 0x10000, flushes=al[5], n=r['attempted'], mem=m)


def fields(b):
    u = lambda o, f='<H': struct.unpack_from(f, b, o)[0]
    return dict(magic=b[:4], guard=b[4], stage=b[5], read=b[6], page=b[7], counts=u(8), ret=u(12), rows=u(14), fmt=u(16), stride=u(18), hw=u(20), n=u(22), xy=u(24), bus=u(28, '<I'), size=u(32, '<I'), mode=b[36] & 15, band=b[36] >> 4, cls=b[37], cpu=u(40, '<I'), seed=u(44, '<I'))


def t_model(q, gc):
    bad, n = [], 0
    for name, (bus, cached, m) in V.CLASSES.items():
        for lv in (1, 2):
            w, h, st = 128, 5, 160
            pic = V.picture(w, h, st)
            r = run(q, gc, V.job_bytes(bus, profile=lv + 1, w=w, h=h, stride=st), cached, pic)
            want, sd = V.expected(pic, w, h, st, V.S[lv], 0x12345678)
            f = fields(r['blk'])
            cl = 0 if bus < 0xb0000000 else (2 if m else 1)
            n += 1
            if not (r['ok'] and r['pic'] == want and r['frees'] == 2 and r['mallocs'] == 3 and f['magic'] == b'GDIA' and (f['stage'], f['guard']) == (7, 0) and f['seed'] == sd and f['rows'] == h
                    and (f['fmt'], f['stride'], f['hw'], f['n'], f['bus'], f['cls'], f['band']) == (0x0302, st, w, h, bus, cl, 0) and f['counts'] == 0x01 and r['flushes'] >= 5):
                bad.append((name, lv, r['fault'], r['pic'] == want, f))
        w, h, st = 16, 132, 16
        pic = V.picture(w, h, st)
        r = run(q, gc, V.job_bytes(bus, profile=4, w=w, h=h, stride=st), cached, pic)
        want, sd = V.expected(pic, w, h, st, 112, 0x12345678)
        a = np.frombuffer(want, dtype=np.uint8).copy().reshape(h, st * 2)
        a[:128, 0:2 * w:2] = 16
        f = fields(r['blk'])
        n += 1
        if not (r['ok'] and r['pic'] == a.tobytes() and f['band'] == 1 and f['seed'] == sd and (f['stage'], f['guard']) == (7, 0)):
            bad.append(('band', name, r['fault'], r['pic'] == a.tobytes(), f))
    return bad, n


def t_guards(q, gc):
    bad, n = [], 0
    w, h, st, bus, c = 128, 5, 160, 0xa4000000, 0x64000000
    pic = V.picture(w, h, st)
    cases = [(4, 0x20, dict(fmt=0x0305)), (4, 0x21, dict(xy=4)), (4, 0x23, dict(w=0)), (4, 0x24, dict(w=5464, stride=5472)), (4, 0x25, dict(w=126)), (4, 0x26, dict(stride=64)), (4, 0x27, dict(h=0)),
             (4, 0x28, dict(h=8193)), (4, 0x29, dict(size=100)), (4, 0x2a, dict(bus=0x90000000)), (4, 0x2b, dict(bus=0xafffff00)), (4, 0x2c, dict(bus=0xe0000000)), (4, 0x2d, dict(bus=0xc1000000)), (4, 0x2e, dict(bus=0xb7ffff00)),
             (3, 0x16, dict(rec_id=4097)), (2, 0x10, dict(mark=0)), (2, 0x11, dict(mode=12)), (2, 0x12, dict(jtype=0x30)), (2, 0x13, dict(key=12)), (2, 0x14, dict(profile=1))]
    for stage, gid, kw in cases:
        kw = dict(dict(w=w, h=h, stride=st, bus=bus), **kw)
        b = kw.pop('bus')
        r = run(q, gc, V.job_bytes(b, **kw), c, pic)
        f = fields(r['blk'])
        n += 1
        # (a first mark on a no-block path makes the block, as on the camera)
        if not (r['ok'] and r['pic'] == pic and (f['stage'], f['guard']) == (stage, gid) and r['frees'] == 0 and r['d0'] == 0 and r['mallocs'] == 1):
            bad.append((hex(gid), r['fault'], r['pic'] == pic, f['stage'], hex(f['guard']), r['frees'], r['mallocs']))
    for gid, fail, frees in ((0x2f, 2, 0), (0x30, 3, 1)):
        r = run(q, gc, V.job_bytes(bus, w=w, h=h, stride=st), c, pic, fail=fail)
        f = fields(r['blk'])
        n += 1
        if not (r['ok'] and r['pic'] == pic and (f['stage'], f['guard']) == (4, gid) and r['frees'] == frees):
            bad.append((hex(gid), r['fault'], f['stage'], hex(f['guard']), r['frees']))
    r = run(q, gc, V.job_bytes(bus, w=w, h=h, stride=st), c, pic, sf=40654)
    f = fields(r['blk'])
    n += 1
    if not (r['ok'] and r['pic'] == pic and (f['stage'], f['guard']) == (3, 0x15) and f['ret'] == 40654 and r['d0'] & 0xffff == 40654):
        bad.append(('blend', r['fault'], f))
    # no heap P: stock blend, nothing else
    r = run(q, gc, V.job_bytes(bus, w=w, h=h, stride=st), c, pic, pool=False)
    n += 1
    if not (r['ok'] and r['pic'] == pic and r['mallocs'] == 0 and r['d0'] == 0 and r['ptr'] == 0):
        bad.append(('no P', r['fault'], r['mallocs']))
    return bad, n


def read(q, gc, blk, text=b'1\0.\x001\0\0\0', pool=True):
    p = bytearray(2048); p[0:4] = b'EP7B'; struct.pack_into('<I', p, 1000, HEAP_U)
    st = bytearray(8); struct.pack_into('<H', st, 2, H + 1 if pool else 0)
    fw = int(gc['gc_fw'], 16)
    wr = b'\xdd' + struct.pack('<i', fw - CALLER) + b'\xf0\x58'
    rg = [V.slice_(q, 0x601e0000, 0x601e4000, 'blk'), Region('caller', CALLER, wr, 'rx'), Region('stk', STK, bytes(0x4000), 'rw', True), Region('heapu', HEAP_U, bytes(blk), 'rw', True),
          Region('pool', P_AT + H, bytes(p), 'rw'), Region('st', 0x622cbcc0, bytes(st), 'rw'), Region('txt', ALLOC, bytes(text) + bytes(16), 'r'), Region('setter', SETTER, b'\xcb\xcb', 'rx')]
    r = execute(rg, {'pc': CALLER, 'sp': STK + 0x3000, 'a0': 0x77770000, 'a1': ALLOC if text else 0}, SETTER, limit=2000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    a1, a0 = r['registers']['a1'], r['registers']['a0']
    t = ''
    if STK <= a1 < STK + 0x4000:
        o = a1 - STK
        while True:
            c = struct.unpack_from('<H', m['stk'], o)[0]
            if not c:
                break
            t += chr(c); o += 2
    return r['fault'], r['registers']['pc'] == SETTER and a0 == 0x77770000, a1, t, m['heapu']


def t_read(q, gc):
    bad, n = [], 0
    b = bytearray(64); b[:4] = b'GDIA'
    b[4], b[5] = 0x2a, 7
    struct.pack_into('<H', b, 8, 0x123); struct.pack_into('<H', b, 12, 0x0abc); struct.pack_into('<H', b, 14, 3888)
    struct.pack_into('<HHHHH', b, 16, 0x0302, 5184, 5184, 3888, 0x0ff)
    struct.pack_into('<I', b, 28, 0xc8123456); struct.pack_into('<I', b, 32, 40310784); b[36] = 0x13; b[37] = 2; struct.pack_into('<I', b, 40, 0xb0123456)
    want = ['a72a', 'b123', 'c302', 'd510', 'e510', 'f3cc', 'gc81', 'h234', 'i213', 'jb01', 'k798', 'l0ff', 'mabc', 'n026']
    cur = bytes(b)
    for i in range(16):
        f, ok, a1, t, cur = read(q, gc, cur)
        n += 1
        if f or not ok or t != want[i % 14] or cur[6] != 1:
            bad.append((i, f, ok, t, want[i % 14]))
    f, ok, a1, t, _ = read(q, gc, cur, text=b'\0\0\0\0'); n += 1
    if f or not ok or a1 != ALLOC:
        bad.append(('empty', f, ok, hex(a1)))
    f, ok, a1, t, _ = read(q, gc, cur, pool=False); n += 1
    if f or not ok or a1 != int(gc['gc_none'], 16):
        bad.append(('none', f, ok, hex(a1)))
    return bad, n


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    old, *_ = V.image(base_s)
    new, pkg, rst, info = V.image(new_s)
    gc = new_s['grain_cpu']['symbols']
    q = V.stubbed(new, gc)
    ok = True
    for name, fn in (('M model + block', lambda: t_model(q, gc)), ('F guards', lambda: t_guards(q, gc)), ('R readout', lambda: t_read(new, gc)), ('G gate', lambda: V.t_gate(old, new)), ('W list', lambda: V.t_list(old, new, gc))):
        bad, n = fn(); ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:4] if bad else '')
    good, txt = V.t_blend(new); ok &= good
    print(f"{'PASS' if good else 'FAIL'} B blend setup: {txt}")
    good, txt = V.t_pkg(base_s, new_s, new, pkg, rst, info, disk, old); ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: {txt}")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
