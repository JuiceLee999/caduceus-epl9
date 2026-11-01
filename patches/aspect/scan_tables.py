#!/usr/bin/env python3
"""Inventory every per-aspect (w,h) table in E-P7 1.1 main (offline, read-only).

A table = 9 consecutive records (ids 1..9) whose (w,h) ratios match
4:3,3:2,16:9,1:1,5:4,7:6,6:5,7:5,3:4 within 3.5 %. Record layouts tried:
u16 (w,h) stride 4; u16 (x,y,w,h,...) stride 16; u16 (id,0,w,h) stride 8;
u16 (w,h,code) stride 6; u32 (id,w,h) stride 12. Prints address of the id-1 record.
"""
import json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
B = 0x60020020
R = [4/3, 3/2, 16/9, 1, 5/4, 7/6, 6/5, 7/5, 3/4]
LAYOUTS = [  # name, stride, struct fmt, index of w, index of h
    ('u16wh', 4, '<HH', 0, 1), ('rect16', 16, '<HHHH', 2, 3), ('u16id0wh', 8, '<HHHH', 2, 3),
    ('u16whcode', 6, '<HHH', 0, 1), ('u32idwh', 12, '<III', 1, 2)]


def scan(d):
    out = []
    n = len(d)
    for name, st, fmt, iw, ih in LAYOUTS:
        sz = struct.calcsize(fmt)
        for off in range(0, n - 9 * st, 2):
            ok = True
            for k in range(9):
                rec = struct.unpack_from(fmt, d, off + k * st)
                w, h = rec[iw], rec[ih]
                if w < 64 or h < 64 or w > 20000 or h > 20000 or abs(w / h / R[k] - 1) > 0.035:
                    ok = False
                    break
            if ok:
                out.append(dict(layout=name, stride=st, id1=hex(B + off),
                                rows=[list(struct.unpack_from(fmt, d, off + k * st)) for k in range(9)]))
    return out


if __name__ == '__main__':
    d = (ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes()
    res = scan(d)
    for t in res:
        print(t['layout'], t['id1'], [tuple(r) for r in t['rows']][:3], '...', tuple(t['rows'][5]), tuple(t['rows'][6]))
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(json.dumps(res, indent=1))
