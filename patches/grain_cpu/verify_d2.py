#!/usr/bin/env python3
"""Emulator checks for grain_cpu d2 (real lock, mapper, lookup; malloc, free, blend setup and flush stubbed). Offline.

  .venv/bin/python -I patches/grain_cpu/verify_d2.py releases/v0.26/edits.json generated/grain_cpu/d2/edits.json [generated/grain_cpu/d2/pkg]

  M  COLOR2/3 == model; COLOR4 first 128 rows Y = 16 then == model; block fields (stage, guard, record, window class, CPU, rows, band), each window class
  F  each guard has its own id; image untouched; buffers balanced; stock result kept
  T  half-press: writes GRAIND.BIN only if the record changed; other events, no record, no P, malloc failure: nothing, registers intact
  C  next capture: last copy, next slot, clear, seed kept, no file I/O (the writer isn't mapped)
  Image regions are read-only in M, F, T and C: any store into the image faults
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
V_SB3 = _load('gc_b', ROOT / 'patches/grain_cpu/build.py').SB3
Region, execute = V.Region, V.execute
BASE, CALLER, STK, JOB, ALLOC, HEAP_U, HEAP_C = V.BASE, V.CALLER, V.STK, V.JOB, V.ALLOC, V.HEAP_U, V.HEAP_C
P_AT, H = 0xa1f8d800, 0x80
SETTER = 0x60d4c9df
WFILE, MVTRIG, EV = 0x61242b3b, 0x601e0b3c, 0


def regions(q, gc, j, cached, pic, fail=0, sf=0, pool=True):
    wr = b'\xfc\xff' + struct.pack('<i', int(gc['gc_gs'], 16) - CALLER) + b'\xcb'
    p = bytearray(2048); p[0:4] = b'EP7B'
    st = bytearray(8); struct.pack_into('<H', st, 2, H + 1 if pool else 0)
    return [Region('low', 0x60020020, q[:0x60100000 - BASE], 'rx'), Region('blk', 0x601df000, q[0x601df000 - BASE:0x601e4000 - BASE], 'rx'), Region('isp', 0x60350000, q[0x60350000 - BASE:0x60360000 - BASE], 'rx'),
            Region('caller', CALLER, wr, 'rx'), Region('stk', STK, bytes(0x4000), 'rw', True), Region('job', JOB, bytes(j), 'rw', True),
            Region('alloc', ALLOC, struct.pack('<IIIIII', HEAP_U, fail, 0, sf, 0, 0) + bytes(64), 'rw', True), Region('heap', HEAP_C, bytes(0x40000), 'rw'),
            Region('heapu', HEAP_U, bytes(0x400), 'rw', True), Region('pool', P_AT + H, bytes(p), 'rw', True), Region('st', 0x622cbcc0, bytes(st), 'rw'),
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
                fault=r['fault'], d0=rr['d0'], pic=m['pic'], blk=m['heapu'][:80], ptr=struct.unpack_from('<I', m['pool'], 1000)[0], frees=al[2], mallocs=(al[0] - HEAP_U) // 0x10000, flushes=al[5], n=r['attempted'], mem=m)


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
    rg = [Region('blk', 0x601df000, q[0x601df000 - BASE:0x601e4000 - BASE], 'rx'), Region('caller', CALLER, wr, 'rx'), Region('stk', STK, bytes(0x4000), 'rw', True), Region('heapu', HEAP_U, bytes(blk), 'rw', True),
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


def trig_run(q, gc, blk, event, wfile_ok=True, fail=0, stop_at_write=False, pool=True):
    """gc_trig from sd_back with ep7_wfile stubbed. Stops at mv_trig: every register as on entry."""
    p = bytearray(2048); p[0:4] = b'EP7B'; struct.pack_into('<I', p, 1000, HEAP_U)
    st = bytearray(8); struct.pack_into('<H', st, 2, H + 1 if pool else 0)
    s = bytearray(0x4000); struct.pack_into('<I', s, 0x3000 + 16, event)
    rg = [Region('low', 0x60020020, q[:0x60100000 - BASE], 'rx'), Region('blk', 0x601df000, q[0x601df000 - BASE:0x601e4000 - BASE], 'rx'), Region('wf', WFILE, q[WFILE - BASE:WFILE - BASE + 16], 'rx'),
          Region('stk', STK, bytes(s), 'rw', True), Region('heapu', HEAP_U, bytes(blk), 'rw', True), Region('heapb', HEAP_U + 0x10000, bytes(0x1000), 'rw'),
          Region('pool', P_AT + H, bytes(p), 'rw'), Region('st', 0x622cbcc0, bytes(st), 'rw'), Region('alloc', ALLOC, struct.pack('<IIIIII', HEAP_U + 0x10000, fail, 0, 0, 0, 0) + bytes(64), 'rw', True)]
    regs = {'pc': int(gc['gc_trig'], 16), 'sp': STK + 0x3000, 'd0': 0x1111, 'd1': 0x2222, 'd2': 0x3333, 'd3': 0x4444, 'a0': 0x5555, 'a1': 0x6666, 'a2': 0x7777, 'a3': 0x8888}
    r = execute(rg, regs, WFILE if stop_at_write else MVTRIG, limit=20000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    rr = r['registers']
    return dict(fault=r['fault'], pc=rr['pc'], kept=all(rr[k] == regs[k] for k in regs if k != 'pc'), heap=m['heapu'], d0=rr['d0'], a0=rr['a0'], a1=rr['a1'], a3=rr['a3'], stk=m['stk'], frees=struct.unpack_from('<I', m['alloc'], 8)[0])


def block(stage=7, guard=0, seq=0, seed=0x55):
    b = bytearray(736); b[:4] = b'GDIA'; b[4] = guard; b[5] = stage
    struct.pack_into('<I', b, 28, 0x41700000); struct.pack_into('<I', b, 44, seed); struct.pack_into('<H', b, 62, seq)
    b[80:84] = b'GRND'; struct.pack_into('<HHHH', b, 84, 1, seq, 80, 8)
    return b


def t_trig(q, gc):
    bad, n = [], 0
    ev = EV
    # first half-press: copies, commits, writes
    r = trig_run(q, gc, block(), ev, stop_at_write=True)
    path = q[int(gc['gc_path'], 16) - BASE:int(gc['gc_path'], 16) - BASE + 24].split(b'\0')[0]
    n += 1
    if r['fault'] or r['pc'] != WFILE or r['a1'] != HEAP_U + 80 or r['d0'] != 656 or path != b'C:\\EP7MOD\\GRAIND.BIN' or r['a3'] != HEAP_U + 0x10000:
        bad.append(('write args', r['fault'], hex(r['pc']), hex(r['a1']), r['d0'], path))
    h = bytearray(r['heap'])
    want = block()[:80]; want[6] = 1
    if h[96:176] != want or h[6] != 1 or h[94] != 0 or struct.unpack_from('<H', h, 92)[0] != 1:
        bad.append(('slot', h[96:104].hex(), h[6], h[94]))
    # the whole path, with the writer stubbed
    r = trig_run(q, gc, block(), ev); n += 1
    if r['fault'] or r['pc'] != MVTRIG or not r['kept'] or r['frees'] != 1:
        bad.append(('full', r['fault'], hex(r['pc']), r['kept'], r['frees']))
    # no change -> no write
    r2 = trig_run(q, gc, r['heap'], ev); n += 1
    if r2['fault'] or not r2['kept'] or r2['frees'] != 0:
        bad.append(('no change', r2['fault'], r2['frees']))
    # a later stage changes the record -> write again
    b = bytearray(r['heap']); b[14] = 9
    r3 = trig_run(q, gc, b, ev); n += 1
    if r3['fault'] or r3['frees'] != 1 or r3['heap'][96 + 14] != 9:
        bad.append(('change', r3['fault'], r3['frees']))
    for name, kw in (('other event', dict(event=ev + 1)), ('no record', dict(event=ev, blk=block(stage=0))), ('no P', dict(event=ev, pool=False))):
        kw = dict(dict(blk=block()), **kw)
        z = trig_run(q, gc, kw.pop('blk'), kw.pop('event'), **kw); n += 1
        if z['fault'] or z['pc'] != MVTRIG or not z['kept'] or z['frees'] != 0 or z['heap'][94] or z['heap'][96:100] == b'GDIA':
            bad.append((name, z['fault'], hex(z['pc']), z['kept'], z['frees']))
    z = trig_run(q, gc, block(), ev, fail=1); n += 1
    if z['fault'] or z['pc'] != MVTRIG or not z['kept'] or z['frees'] != 0:
        bad.append(('malloc', z['fault'], z['kept']))
    return bad, n


def flag_new(q, gc, blk):
    """gc_flag on the next capture after a commit: last copy, next slot, clear, no file I/O (the writer isn't mapped)."""
    p = bytearray(2048); p[0:4] = b'EP7B'; struct.pack_into('<I', p, 1000, HEAP_U)
    st = bytearray(8); struct.pack_into('<H', st, 2, H + 1)
    cap = bytearray(24100); cap[24053] = 11; cap[24083] = 3; struct.pack_into('<H', cap, 194, 0x1001)
    par = bytearray(32); struct.pack_into('<H', par, 10, 11)
    rg = [Region('blk', 0x601df000, q[0x601df000 - BASE:0x601e4000 - BASE], 'rx'), Region('sec1', 0x60210000, q[0x60210000 - BASE:0x60211000 - BASE], 'rx'), Region('conv', 0x603ea900, q[0x603ea900 - BASE:0x603eae00 - BASE], 'rx'),
          Region('sec2', 0x6055e000, q[0x6055e000 - BASE:0x6055f000 - BASE], 'rx'), Region('stk', STK, bytes(0x4000), 'rw'), Region('heapu', HEAP_U, bytes(blk), 'rw', True), Region('pool', P_AT + H, bytes(p), 'rw'),
          Region('st', 0x622cbcc0, bytes(st), 'rw'), Region('cap', JOB, bytes(cap), 'rw'), Region('par', ALLOC, bytes(par), 'rw', True)]
    r = execute(rg, {'pc': V.FLAG_SITE, 'sp': STK + 0x3000, 'a2': ALLOC + 12, 'a3': JOB}, V.FLAG_RET, limit=6000)
    return r['fault'], r['registers']['pc'], {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}


def t_cycle(q, gc):
    b = bytearray(trig_run(q, gc, block(), EV)['heap'])
    b[5] = 7; b[14] = 3                     # the pass went further after the half-press
    f, pc, m = flag_new(q, gc, b)
    h = m['heapu']
    good = (not f and pc == V.FLAG_RET and h[96 + 14] == 3 and h[94] == 1 and struct.unpack_from('<H', h, 86)[0] == 1 and h[5] == 1 and h[4] == 0 and h[6] == 0 and h[14] == 0 and struct.unpack_from('<I', h, 44)[0] == 0x55
            and struct.unpack_from('<H', h, 62)[0] == 1 and h[39] == 3 and struct.unpack_from('<H', h, 58)[0] == 0x1001 and h[60] == 11 and struct.unpack_from('<I', m['par'], 12)[0] & 0x80)
    return ([] if good else [('cycle', f, hex(pc), h[:16].hex())]), 1


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
    ours = [(int(g['code_at'], 16), g['code_len']), (0x603579b8, 4), (0x603eabd8, 4), (int(g['bw_default'], 16), 3), (0x605b7421, 4)] + [(int(e['addr'], 16), len(e['new']) // 2) for e in new_s['edits'] if e.get('source') == 'patches/fw_version']
    diff = [BASE + i for i in range(len(old)) if old[i] != new[i]]
    stray = [hex(a) for a in diff if not any(s <= a < s + k for s, k in ours)]
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
    q = V.stubbed(new, gc)
    global EV
    EV = V_SB3.EV_PRESS
    q2 = bytearray(q)
    code = b'\xdf\xf0\x1c'
    q2[WFILE - BASE:WFILE - BASE + 3] = code     # ep7_wfile: ret [d2,d3,a2,a3],28
    q2 = bytes(q2)
    ok = True
    for name, fn in (('M model + block', lambda: t_model(q, gc)), ('F guards', lambda: t_guards(q, gc)), ('T half-press', lambda: t_trig(q2, gc)), ('C next capture', lambda: t_cycle(q2, gc)), ('G gate', lambda: V.t_gate(old, new)), ('W list', lambda: V.t_list(old, new, gc))):
        bad, n = fn(); ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:4] if bad else '')
    good, txt = V.t_blend(new); ok &= good
    print(f"{'PASS' if good else 'FAIL'} B blend setup: {txt}")
    good, txt = t_pkg(base_s, new_s, new, pkg, rst, info, disk, old); ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: {txt}")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
