#!/usr/bin/env python3
"""Candidate code-space audit for E-P7 1.1 main (offline, read-only).

Method follows the published CODE_SPACE.md approach (our own implementation):
  1. Parse the native section descriptor table and the native end-address getter
     (a jump table of `mov imm32,d0` stubs) instead of guessing bounds from FF runs.
  2. For each loaded section, find the 0xFF suffix that lies INSIDE the load.
  3. Search the whole main image for literal references to the suffix (runtime,
     uncached +0x40000000 alias and logical-flash source alias), and for
     PC-relative jmp/call encodings at every byte offset that land in it.
Static absence of references does not exclude computed/DMA access; see report.

Usage: tools/ep7_code_space.py [--json out.json]
"""
import argparse, hashlib, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
BASE = 0x60020020           # CPU address of decoded offset 0
CONTAINER = 0x406a0020      # logical/container address of decoded offset 0
DESCRIPTORS = 0x60027068    # 12-byte entries {start, logical source, destination}, ids 1..9
END_GETTER = 0x60045786     # d0=id; 1..9 via jump table, else 0
END_JUMP_TABLE = 0x60046780
LOADER = 0x600457e7         # reads descriptor, size=end-start, sets bit (id-1) at 0xa272e420


def u32(d, a):
    return struct.unpack_from('<I', d, a - BASE)[0]


def sections(d):
    # Verify the getter really is "clr d1; cmp 1,d0; blt; cmp 9,d0; bgt; add -1,d0; asl2 d0; mov TABLE,a0; mov (d0,a0),a0; jmp (a0)".
    g = d[END_GETTER - BASE:END_GETTER - BASE + 22]
    assert g[:9] == bytes.fromhex('04a001c05ba009c157'), g.hex()
    assert g[9:14] == bytes.fromhex('28ff54fcdc') and struct.unpack_from('<I', g, 14)[0] == END_JUMP_TABLE
    # Loader uses DESCRIPTORS with 12*(id-1) and END_GETTER (call at 0x600457ec).
    assert d[0x600457f9 - BASE:0x600457ff - BASE] == b'\xfc\xd3' + struct.pack('<I', DESCRIPTORS)
    out = []
    for sid in range(1, 10):
        stub = u32(d, END_JUMP_TABLE + 4 * (sid - 1))
        assert d[stub - BASE:stub - BASE + 2] == b'\xfc\xcc', hex(stub)
        end = u32(d, stub + 2)
        start, src, dst = struct.unpack_from('<III', d, DESCRIPTORS - BASE + 12 * (sid - 1))
        assert start == dst and start - BASE == src - CONTAINER, sid
        out.append(dict(id=sid, start=start, end=end, source=src, end_stub=stub))
    return out


def ff_suffix(d, start, end):
    i = end - BASE
    while i > start - BASE and d[i - 1] == 0xff:
        i -= 1
    j = end - BASE
    while j < len(d) and d[j] == 0xff:
        j += 1
    return BASE + i, BASE + j


def literal_refs(d, lo, hi):
    """All byte offsets holding a LE u32 in [lo,hi). Brute force over the image."""
    hits = []
    # Fast path: search for each distinct upper-3-byte prefix pattern.
    for v in range(lo & ~0xff, hi, 0x100):
        prefix = struct.pack('<I', v)[1:]
        i = d.find(prefix, 1)
        while i != -1:
            val = struct.unpack_from('<I', d, i - 1)[0]
            if lo <= val < hi:
                hits.append((BASE + i - 1, val, d[max(0, i - 3):i + 3].hex()))
            i = d.find(prefix, i + 1)
    return sorted(set(hits))


def relative_refs(d, lo, hi):
    """jmp d16 (cc), call d16 (cd), jmp d32 (dc), call d32 (dd), calls d16 (fa ff), calls d32 (fc ff)
    decoded at every byte offset; superset of real branches (data bytes included)."""
    hits = []
    n = len(d)
    for op, width, oplen in ((0xcc, 2, 1), (0xcd, 2, 1), (0xdc, 4, 1), (0xdd, 4, 1)):
        b = bytes([op]); i = d.find(b)
        while i != -1 and i + oplen + width <= n:
            disp = int.from_bytes(d[i + oplen:i + oplen + width], 'little', signed=True)
            t = BASE + i + disp
            if lo <= t < hi:
                hits.append((BASE + i, d[i:i + 7].hex(), t))
            i = d.find(b, i + 1)
    for op2, width in ((b'\xfa\xff', 2), (b'\xfc\xff', 4)):
        i = d.find(op2)
        while i != -1 and i + 2 + width <= n:
            t = BASE + i + int.from_bytes(d[i + 2:i + 2 + width], 'little', signed=True)
            if lo <= t < hi:
                hits.append((BASE + i, d[i:i + 7].hex(), t))
            i = d.find(op2, i + 1)
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    d = MAIN.read_bytes()
    assert hashlib.sha256(d).hexdigest() == MAIN_SHA, 'unexpected main payload'
    rows = []
    for s in sections(d):
        if s['end'] <= s['start']:
            rows.append(dict(s, note='zero-length section')); continue
        ff_lo, ff_hi = ff_suffix(d, s['start'], s['end'])
        lo, hi = ff_lo, s['end']
        alias = dict(runtime=(lo, hi), uncached=(lo + 0x40000000, hi + 0x40000000),
                     logical=(s['source'] + lo - s['start'], s['source'] + hi - s['start']),
                     logical_uncached=(s['source'] + lo - s['start'] + 0x40000000,
                                       s['source'] + hi - s['start'] + 0x40000000))
        lits = {k: literal_refs(d, *v) for k, v in alias.items()}
        rel = relative_refs(d, lo, hi)
        rows.append(dict(id=s['id'], load_start=hex(s['start']), load_end=hex(s['end']),
            logical_source=hex(s['source']), end_stub=hex(s['end_stub']),
            ff_suffix_start=hex(ff_lo), ff_bytes_inside_load=hi - lo,
            ff_continues_to=hex(ff_hi), ff_bytes_outside_load=ff_hi - hi,
            end_alignment_2k=(s['end'] % 0x800 == 0),
            last_nonff_bytes=d[ff_lo - BASE - 16:ff_lo - BASE].hex(),
            literal_refs={k: [dict(at=hex(x), value=hex(v), ctx=c) for x, v, c in L] for k, L in lits.items()},
            relative_ref_candidates=[dict(at=hex(x), bytes=b, target=hex(t)) for x, b, t in rel]))
    for r in rows:
        if 'ff_suffix_start' not in r:
            print(r); continue
        nlit = sum(len(v) for v in r['literal_refs'].values())
        print(f"sec{r['id']}: load {r['load_start']}..{r['load_end']}  FF suffix {r['ff_suffix_start']}..{r['load_end']}"
              f" = {r['ff_bytes_inside_load']} B (FF runs on {r['ff_bytes_outside_load']} B outside load)"
              f"  literal refs={nlit}  rel-branch candidates={len(r['relative_ref_candidates'])}")
        for k, L in r['literal_refs'].items():
            for x in L[:6]:
                print(f"    lit[{k}] {x}")
        for x in r['relative_ref_candidates'][:6]:
            print(f"    rel {x}")
    if a.json:
        a.json.write_text(json.dumps(dict(main_sha256=MAIN_SHA, descriptors=hex(DESCRIPTORS),
            end_getter=hex(END_GETTER), loader=hex(LOADER), sections=rows), indent=1))


if __name__ == '__main__':
    main()
