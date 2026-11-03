#!/usr/bin/env python3
"""Targeted emulator checks for v0.22 natural grain (Noise Filter). Offline; emulator only.

  .venv/bin/python -I patches/v022/verify.py releases/v0.21/edits.json releases/v0.22/edits.json

  R  loader ranges: SD loader v3 / fm_check accept grain 0..6, reject 7
  G  ex_get grain read through g_val/rets (real CALLS frame, image read-only): byte 0 / 6 / 1 / 2..5 -> OUT = u
     0 Global / 1 Std / 2 Low / 3 Off; 7+ -> 0; a1/d2/d3/a2 kept (regression: the first v0.22 build clobbered a1)
  S  Extras grain edit (ex_set from 0x601e33bc, wheel value -7..8): u = clamp 0..3, slot byte 0/6/1/2; manager
     0x60827440 once with (1334, 0 Standard / -1 Low / -2 Off, ex_set's a0, a1) for u 1..3, never for Global;
     d0/d1/a0/a1, MDR, sp restored at s_dirty
  K  Film pick (lt_post tail 0x601e2341), slot k 0..3 x grain byte 0..7 (+ k 4): facade SetValue(1334, 0, v) once
     with the byte's Noise Filter value, never for Global (0, 7) / k >= 4; d2/d3/a2/a3 kept; reaches fm_post
  L  sector-1 labels by u: "1 Grain Global" / "Off" / "Fine" / "Film" (4/5 Film), 6/7 -> no label
  W  COLOR combiner grain inert: work list for COLOR slot grain 0..5 == stock COLOR; MONO (key 12) == stock
  D  diff vs v0.21 only inside the v0.22 sites; P anti-brick
"""
import json, struct, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'patches/v021'))
import ep7_grain_verify as GV  # noqa: E402
import build_package as BP, oly_container as oc  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402
import verify as V21  # noqa: E402

BASE, TC = 0x60020020, Path.home() / 'ep7fw-toolchains/mn10300/bin'
CAP, BUF, STK, FAKE = 0x18040000, 0x18000000, 0x18010000, 0x18030000


def asm(src, at):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'a.s').write_text(' .am33_2\n .text\n .global _start\n_start:\n' + src + '\n')
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'a.o', t / 'a.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start', '-o', t / 'a.elf', t / 'a.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'a.elf', t / 'a.bin'], check=True)
        return (t / 'a.bin').read_bytes()


REC = f""" mov ({CAP:#x}),a2
 add 1,a2
 mov a2,({CAP:#x})
 mov d0,({CAP + 4:#x})
 mov d1,({CAP + 8:#x})
 mov a0,({CAP + 12:#x})
 mov a1,({CAP + 16:#x})
"""
MGR = REC + ' ret [d2,d3,a2],16'                   # manager: entered by call ...,[d2,d3,a2],16
SETV = REC.replace('a2', 'a3') + ' rets'          # facade SetValue: calls (a2); keep a2 (it is the callee pointer)


def image(spec):
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    return [b for b in oc.parse(pkg) if b.kind == 0x100][0].payload, pkg, rst, info


def segs(im, extra):
    s = lambda lo, hi: Region(f'i{lo:x}', lo, im[lo - BASE:hi - BASE], 'rx')
    return [s(0x601e1b00, 0x601e1c40), s(0x601e2000, 0x601e3a00)] + extra + [Region('cap', CAP, bytes(64), 'rw', True)]


def cap(m):
    c = m['cap']
    return struct.unpack_from('<I', c, 0)[0], struct.unpack_from('<iiII', c, 4)


U2B, B2U, U2NF = [0, 6, 1, 2], [0, 2, 3, 3, 3, 3, 1], [None, 0, -1, -2]


def t_set(im):
    bad, n = [], 0
    mgr = Region('mgr', 0x60827440, asm(MGR, 0x60827440), 'rx')
    for v in range(-7, 9):
        stk = bytearray(0x200); struct.pack_into('<I', stk, 0x100 + 16, 0x601e9999)
        regs = dict(pc=0x601e33bc, sp=STK + 0x100, d0=1234, d1=v & 0xffffffff, d3=0, a0=0xa0a0, a1=0xa1a1, a2=BUF, mdr=0x601e9999)
        r = execute(segs(im, [mgr, Region('buf', BUF, b'\xee' * 64, 'rw', True), Region('stk', STK, bytes(stk), 'rw', True)]),
                    regs, 0x601e3428, limit=2000)
        m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
        rr = r['registers']
        u = min(max(v, 0), 3)
        cnt, args = cap(m)
        good = (not r['fault'] and rr['pc'] == 0x601e3428 and m['buf'][56] == U2B[u] and rr['sp'] == STK + 0x100 and
                rr['d0'] == 1234 and rr['d1'] == u and rr['a0'] == 0xa0a0 and rr['a1'] == 0xa1a1)
        good &= (cnt == 0) if u == 0 else (cnt == 1 and args == (1334, U2NF[u], 0xa0a0, 0xa1a1))
        n += 1
        if not good:
            bad.append((v, m['buf'][56] if 'buf' in m else None, cnt, args, r['fault']))
    return bad, n


def t_pick(im):
    bad, n = [], 0
    fac = Region('fac', 0x607f9062, asm(f' mov {FAKE:#x},a0\n ret [],4', 0x607f9062), 'rx')
    fake = bytearray(0x100)
    struct.pack_into('<II', fake, 0, FAKE + 0x10, FAKE + 0x20)       # obj -> vt ; vt+0 -> SetValue
    sv = asm(SETV, FAKE + 0x20)
    fake[0x10:0x14] = struct.pack('<I', FAKE + 0x20)
    fake[0x20:0x20 + len(sv)] = sv
    for k in range(5):
        for g in range(8):
            P = bytearray(0x400); P[32 + 64 * k + 24] = g if k < 4 else 0
            if k == 4:
                P[32 + 24] = 2
            regs = dict(pc=0x601e2341, sp=STK + 0x100, d2=0x2222, d3=k, a2=BUF, a3=0x3333)
            r = execute(segs(im, [fac, Region('fake', FAKE, bytes(fake), 'rx'), Region('buf', BUF, bytes(P), 'rw', True),
                                  Region('stk', STK, bytes(0x200), 'rw', True)]), regs, 0x601e37b4, limit=2000)
            m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
            rr = r['registers']
            cnt, args = cap(m)
            good = not r['fault'] and rr['pc'] == 0x601e37b4 and (rr['d2'], rr['d3'], rr['a2'], rr['a3'], rr['sp']) == (0x2222, k, BUF, 0x3333, STK + 0x100)
            u = B2U[g] if g < 7 else 0
            if k < 4 and u:
                good &= cnt == 1 and args[0] == 1334 and args[1] == 0 and args[3] == (U2NF[u] & 0xffffffff)
            else:
                good &= cnt == 0
            n += 1
            if not good:
                bad.append((k, g, cnt, args, [hex(rr[x]) for x in ('d2', 'd3', 'a2', 'a3', 'sp')]))
    return bad, n


def t_label(im):
    bad, seen = [], []
    want = ['1 Noise Global', '1 Noise Std', '1 Noise Low', '1 Noise Off', '1 Noise Off', '1 Noise Off']
    for v in range(8):
        rg = [Region(f'i{lo:x}', lo, im[lo - BASE:hi - BASE], 'rx') for lo, hi in V21.EX] + \
             [Region('stk', STK, bytes(0x104) + struct.pack('<I', v) + bytes(0xf8), 'rw', True)]
        r = execute(rg, dict(sp=STK + 0x100, pc=0x601e355e, d3=0), 0x601e35b4, limit=200)
        pc, a2 = r['registers']['pc'], r['registers']['a2']
        txt = im[a2 - BASE:a2 - BASE + 16].split(b'\0')[0].decode() if pc == 0x601e35b4 else None
        if v < 6:
            seen.append(txt)
            if txt != want[v]:
                bad.append((v, txt))
        elif txt is not None:
            bad.append((v, txt))
    return bad, seen


def t_get(im):
    """ex_get grain tail from 0x601e32c8 through g_val (`mov d0,(a1)`; movm pop; rets) with a real CALLS frame:
    OUT gets u, a1 kept, the image (read-only) is never written, returns to the caller. Bytes 0..8 + the card's."""
    bad, n = [], 0
    for g in list(range(9)) + [2, 3, 1, 3]:
        buf = bytearray(64); buf[56] = g
        stk = bytearray(0x200)
        struct.pack_into('<IIII', stk, 0x100, 0xa2a2, 0x3333, 0x2222, 0x18050000)   # movm [d2,d3,a2] frame (a2, d3, d2) + return
        rg = [Region(f'i{lo:x}', lo, im[lo - BASE:hi - BASE], 'rx') for lo, hi in ((0x601e1b00, 0x601e1c40), (0x601e3200, 0x601e3a00))] + \
             [Region('buf', BUF, bytes(buf), 'rw', True), Region('stk', STK, bytes(stk), 'rw', True),
              Region('out', CAP, b'\xee' * 16, 'rw', True), Region('ret', 0x18050000, b'\xcb' * 4, 'rx')]
        r = execute(rg, dict(sp=STK + 0x100, pc=0x601e32c8, a2=BUF, a1=CAP, d3=0, mdr=0x18050000), 0x18050000, limit=200)
        m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
        want = B2U[g] if g < 7 else 0
        rr = r['registers']
        n += 1
        if r['fault'] or rr['pc'] != 0x18050000 or struct.unpack_from('<I', m['out'], 0)[0] != want or rr['d0'] != 0 or \
           (rr['d2'], rr['d3'], rr['a2']) != (0x2222, 0x3333, 0xa2a2):
            bad.append((g, r['fault'], hex(rr['pc']), m.get('out', b'')[:4].hex(), [hex(rr[x]) for x in ('d0', 'd2', 'd3', 'a2', 'sp')]))
    return bad, n


def t_wl(stock, im):
    bad, n = [], 0
    for g in range(6):
        t = GV.fixture_table([g] * 4 + [0] * 4)
        for key, cls in ((11, 0), (11, 4), (12, 0), (12, 4)):
            job = GV.job_bytes(key=key, cls=cls)
            s, p = GV.wl_run(stock, t, key, job), GV.wl_run(im, t, key, job)
            n += 1
            if not (s['ok'] and p['ok'] and s['list'] == p['list'] and s['entries'] == p['entries'] and p['job_same']):
                bad.append((g, key, cls))
    return bad, n


def main():
    old_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    stock = [b for b in oc.parse(BP.STOCK.read_bytes()) if b.kind == 0x100][0].payload
    old, *_ = image(old_s)
    im, pkg, rst, info = image(new_s)
    ok = True
    for name, fn in (('R loader ranges 0..6', lambda: (V21.r_ranges(im, 6), 8)), ('G ex_get byte -> u', lambda: t_get(im)),
                     ('S Extras grain edit', lambda: t_set(im)), ('K Film pick', lambda: t_pick(im)), ('W combiner grain inert', lambda: t_wl(stock, im))):
        bad, n = fn()
        ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:4] if bad else '')
    bad, seen = t_label(im)
    ok &= not bad
    print(f"{'PASS' if not bad else 'FAIL'} L labels {seen}", bad or '')
    sites = [(0x605b7739, 1), (0x6143a7cd, 1), (0x601e32c8, 5), (0x601e1b90, 96), (0x60210d3c, 1), (0x60210dd3, 1), (0x601e33d2, 1), (0x601e33d6, 1), (0x601e33d7, 5), (0x601e2341, 5),
             (0x601e3840, 80), (0x601e3890, 160), (0x601e1c40, 0xc0), (0x61242fc0, 16)]       # + fw_version value
    diff = [i + BASE for i in range(len(im)) if im[i] != old[i]]
    stray = [hex(x) for x in diff if not any(a <= x < a + n for a, n in sites)]
    ok &= not stray
    print(f"{'PASS' if not stray else 'FAIL'} D diff vs v0.21: {len(diff)} B, all in the v0.22 sites", stray[:6])
    good = True
    sb = {b.kind: b for b in oc.parse(BP.STOCK.read_bytes())}
    for b in oc.parse(pkg):
        exp = bytearray(sb[b.kind].payload)
        for e in new_s['edits']:
            if int(e['kind'], 16) == b.kind:
                o = BP.resolve(b.kind, e['addr']); nb = bytes.fromhex(e['new']); exp[o:o + len(nb)] = nb
        good &= bytes(exp) == b.payload
    for b in oc.parse(rst):
        good &= b.payload == sb[b.kind].payload
    ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick ({info['edits']} edits, {info['changed_payload_bytes']} B)")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
