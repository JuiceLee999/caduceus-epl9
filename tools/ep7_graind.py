#!/usr/bin/env python3
"""Decode EP7MOD/GRAIND.BIN from the grain_cpu d2, d3 or s1 diagnostic. Offline, reads the file only.

  .venv/bin/python -I tools/ep7_graind.py /path/to/GRAIND.BIN
"""
import struct, sys
from pathlib import Path

STAGE = {0: 'no capture', 1: 'flag hook only', 2: 'gc_gs', 3: 'blend returned', 4: 'gc_grain checks', 5: 'work buffers', 6: 'writing rows', 7: 'pass finished'}
GUARD = {0: 'none', 1: 'flag: key', 2: 'flag: key high bytes', 3: 'flag: not COLOR', 4: 'flag: no profile, or Grain off', 5: 'flag: kind 0x2001', 6: 'flag: kind 0x2006', 7: 'flag: kind 0x1008', 8: 'flag: kind 0x1006',
         0x10: 'job: marker', 0x11: 'job: mode', 0x12: 'job: type', 0x13: 'job: key', 0x14: 'job: profile', 0x15: 'blend error', 0x16: 'no 0x1000 record', 0x43: 'plain route: other job flags (Glow, Art, ...)', 0x44: 'plain route: no shading bit', 0x4f: 'plain route built (development + output pass)', 0x17: 'wait for the development request failed', 0x20: 'format', 0x21: 'x offset', 0x22: 'y offset',
         0x23: 'width < 4', 0x24: 'width > 5461', 0x25: 'width not a multiple of 4', 0x26: 'stride < width', 0x27: 'rows 0', 0x28: 'rows > 8192', 0x29: 'buffer too small', 0x2a: 'bus below 0xa0000000', 0x2b: 'direct range overrun',
         0x2c: 'bus from 0xe0000000', 0x2d: 'bus in the mapper\'s refused 0xc0000000..0xc3ffffff', 0x2e: 'window edge (d2 and earlier)', 0x32: 'buffer end past 0xdfffffff', 0x2f: 'malloc V+H', 0x30: 'malloc T', 0x31: 'mapper refused'}
CLASS = {0: 'direct', 1: 'window', 2: 'window after mapper call', 3: 'refused'}


def main():
    d = Path(sys.argv[1]).read_bytes()
    if d[:4] != b'GRND':
        sys.exit(f'not a GRAIND file: {d[:4]!r}')
    ver, seq, size, slots, writes = struct.unpack_from('<HHHHH', d, 4)
    print(f'version {ver}, capture counter {seq}, file writes {writes}, {len(d)} B')
    recs = []
    for i in range(slots):
        r = d[16 + i * size:16 + (i + 1) * size]
        if r[:4] == b'GDIA':
            recs.append((struct.unpack_from('<H', r, 62)[0], i, r))
    if not recs:
        print('no records')
    for no, i, r in sorted(recs):
        u16 = lambda o: struct.unpack_from('<H', r, o)[0]
        u32 = lambda o: struct.unpack_from('<I', r, o)[0]
        cnt = u16(8)
        print(f'\ncapture {no} (slot {i}): COLOR{r[39]}  mode {r[60]}  kind {u16(58):#06x}')
        print(f'  stage {r[5]} ({STAGE.get(r[5], "?")})  guard {r[4]:#04x} ({GUARD.get(r[4], "?")})')
        print(f'  reached: flag hook {cnt >> 8 & 15}, gc_gs {cnt >> 4 & 15}, gc_grain {cnt & 15}   level {r[38]}')
        print(f'  job: +16 flags {u32(48):#010x}  type {u16(52):#06x}  class {r[54]}  entries {r[55]}' + (f'  key {u16(56)}' if ver < 3 else ''))
        print(f'  before blend: buffer {u32(68):#x} bus {u32(64):#010x}; buffer {u32(76):#x} bus {u32(72):#010x}')
        print(f'  blend result {u16(12)}')
        if r[5] >= 4:
            pos = f'x|y {u16(24)}' if ver < 3 else f'x {u16(24)}  y {u16(26)}  active {u16(10)} x {u16(56)}'
            print(f'  record: format {u16(16):#06x}  Hw {u16(20)}  stride {u16(18)}  rows {u16(22)}  {pos}  size {u32(32)}')
            print(f'  bus {u32(28):#010x}')
            extra = f'  mode before {r[7]}  rows split {r[61]}' if ver >= 3 else ''
            last = f'route {("?", "blend", "output")[min(r[36] >> 4, 2)]}  CPU {r[37] >> 4}' if ver >= 4 else f'band {"yes" if r[36] >> 4 else "no"}'
            print(f'  window: {CLASS.get(r[37] & 15, "?")}  mode {r[36] & 15}{extra}  CPU address {u32(40):#010x}  {last}  rows done {u16(14)}  seed {u32(44):#010x}')


if __name__ == '__main__':
    main()
