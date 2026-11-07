#!/usr/bin/env python3
"""Write / check EP7MOD/MOVIE.BIN, the movie Vivid slot (offline, no camera). docs/MOVIE_COLOUR.md "Movie slot".

  .venv/bin/python -I tools/ep7_movie_bin.py --out generated/v026/movie1/card/EP7MOD/MOVIE.BIN [--name Movie]
  .venv/bin/python -I tools/ep7_movie_bin.py --check path/to/MOVIE.BIN

96 B: 'EP7V', u32 version 1, u32 80, u32 CRC-32 of bytes 16..95; +16 slot (64 B, COLOR slot layout, patches/bundles/layout.json); +80 name (15 chars + NUL).
Same limits as the camera's loader: hue/light +0..23 and WB +26/27 -7..7; sat +33..44 and blacks/whites +47/48 -5..5; +49 anything (a Film pick sets it), +50..63 zero.
"""
import argparse, struct, sys, zlib
from pathlib import Path


def build(slot=bytes(64), name='Movie'):
    n = name.encode('ascii')
    if len(n) > 15 or len(slot) != 64:
        sys.exit('name over 15 characters, or slot not 64 B')
    body = bytes(slot) + n.ljust(16, b'\0')
    return b'EP7V' + struct.pack('<III', 1, 80, zlib.crc32(body)) + body


def check(d):
    s8 = lambda b: b - 256 if b > 127 else b
    if len(d) != 96 or d[:4] != b'EP7V' or struct.unpack_from('<II', d, 4) != (1, 80) or struct.unpack_from('<I', d, 12)[0] != zlib.crc32(d[16:96]):
        return 'bad size, header or CRC'
    s = d[16:80]
    if any(abs(s8(x)) > 7 for x in s[:24] + s[26:28]) or any(abs(s8(x)) > 5 for x in s[33:45] + s[47:49]) or any(s[50:64]) or d[95]:
        return 'value out of range'


ap = argparse.ArgumentParser()
ap.add_argument('--out', type=Path)
ap.add_argument('--name', default='Movie')
ap.add_argument('--check', type=Path)
a = ap.parse_args()
if a.check:
    e = check(a.check.read_bytes())
    sys.exit(e or print('ok'))
d = build(name=a.name)
assert check(d) is None
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_bytes(d)
print(a.out, len(d), 'B')
