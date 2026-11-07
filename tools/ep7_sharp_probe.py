#!/usr/bin/env python3
"""Read-only emulator probe for docs/SHARPENING_OFF.md.

Runs stock stage setup 0x603ac0c1 (which calls the gain helper 0x603ab8fe) on a synthetic request and prints the
edge-enhancement register word regs+12: byte 0, byte 1 (ISO-dependent, likely coring) and byte 2 (the gain).
Usage: tools/ep7_sharp_probe.py
"""
import struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
from penf_emulator import execute, Region
BASE = 0x60020020
d = (ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes()
CALLER, STACK, CTX, REQ, REGS = 0x18000000, 0x18010000, 0x1a000000, 0x1b000000, 0x1c000000
def img(name, lo, hi, perm='r'): return Region(name, lo, d[lo-BASE:hi-BASE], perm)
def caller(t, mask, frame): return Region('caller', CALLER, b'\xdd'+struct.pack('<i', t-CALLER)+bytes((mask, frame))+b'\xcb', 'rx')
def run(eid, sharp, iso=0, kind=0x1010070, fmt=0):
    q = bytearray(2048)
    struct.pack_into('<H', q, 12, fmt); struct.pack_into('<H', q, 1610, iso)
    q[1795] = sharp & 0xff
    ctx = bytearray(256)
    struct.pack_into('<I', ctx, 4, REQ); struct.pack_into('<I', ctx, 12, REGS); struct.pack_into('<I', ctx, 52, eid)
    regions = [caller(0x603ac0c1, 0xf0, 28), img('code', 0x603a0000, 0x603c0000, 'rx'), img('data', 0x604e0000, 0x60540000),
               Region('stack', STACK, bytes(0x2000), 'rw'), Region('ctx', CTX, bytes(ctx), 'rw'),
               Region('req', REQ, bytes(q), 'rw'), Region('regs', REGS, bytes(128), 'rw', True)]
    r = execute(regions, {'pc': CALLER, 'sp': STACK+0x1000, 'a0': CTX}, CALLER+7, limit=200000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    w = struct.unpack_from('<I', mem['regs'], 12)[0]
    ok = r['registers']['pc'] == CALLER+7
    return ok, r['fault'], w & 0xff, (w >> 8) & 0xff, (w >> 16) & 0xff, struct.unpack_from('<I', mem['regs'], 16)[0]
if __name__ == '__main__':
    for eid in (1, 2, 3, 4, 11, 12, 2001):
        row = []
        for s in (-8, -5, -4, -3, -2, -1, 0, 1, 2):
            ok, f, b0, b1, b2, m = run(eid, s)
            row.append(f'{s:+d}:{b2}' if ok else f'{s:+d}:ERR')
        print(f'eid {eid:5d} byte0/1 {b0}/{b1} mode {m:#x} gain by sharpness ->', ' '.join(row))
    for iso in (0, 200, 400, 800, 1600, 3200, 6400, 0x2000, 0xffff):
        print('eid 11 iso field', iso, [run(11, s, iso)[2:5] for s in (-5, -2, 0, 2)])
    for eid in (0x1010068, 0x1020068, 0x1010072):
        print('art key', hex(eid), [run(eid, s)[2:5] for s in (-2, 0, 2)])
