#!/usr/bin/env python3
"""Scan decoded E-P7 components for monotone u16 curve tables (tone/gamma LUT candidates).

Reports maximal runs of little-endian u16 (2-byte aligned) that are non-decreasing,
start low and end high. Offline, read-only.

Usage: tools/ep7_curve_scan.py [--min-len 128] [--component FILE ...]
"""
import argparse, json, pathlib
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
A = ROOT / "analysis/ep7_1100"
COMPONENTS = {
    "main": ("00_0100_406a0020.decoded.bin", 0x60020020),
    "0x101": ("01_0101_421a0020.decoded.bin", None),
    "0x106": ("02_0106_43aa0020.decoded.bin", None),
    "0x10e": ("03_010e_00000020.decoded.bin", None),
    "0x102": ("04_0102_467e0020.decoded.bin", None),
}


def runs(d16, min_len, min_top):
    inc = np.diff(d16.astype(np.int32)) >= 0
    # run boundaries
    out = []
    n = len(inc)
    i = 0
    edges = np.flatnonzero(~inc)
    starts = np.concatenate(([0], edges + 1))
    ends = np.concatenate((edges + 1, [len(d16)]))  # exclusive
    for s, e in zip(starts, ends):
        L = e - s
        if L < min_len:
            continue
        seg = d16[s:e]
        # trim leading constant run and trailing constant run
        if seg[-1] < min_top or seg[-1] - seg[0] < min_top // 2:
            continue
        nuniq = len(np.unique(seg))
        if nuniq < L // 4:
            continue
        out.append((s, L, int(seg[0]), int(seg[-1]), nuniq))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-len", type=int, default=128)
    ap.add_argument("--min-top", type=int, default=200)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    res = []
    for name, (fn, base) in COMPONENTS.items():
        b = (A / fn).read_bytes()
        for phase in (0, 1):
            raw = b[phase:]
            raw = raw[: len(raw) // 2 * 2]
            d16 = np.frombuffer(raw, dtype="<u2")
            for s, L, lo, hi, nu in runs(d16, args.min_len, args.min_top):
                off = phase + 2 * s
                res.append(dict(component=name, offset=hex(off),
                                cpu=hex(base + off) if base else None,
                                length=int(L), first=lo, last=hi, unique=int(nu)))
    if args.json:
        print(json.dumps(res, indent=1))
    else:
        for r in res:
            print(r)


if __name__ == "__main__":
    main()
