#!/usr/bin/env python3
"""Cross-reference finder for the decoded E-P7 1.1 main image (MN103/AM33).

Finds candidate references to target addresses by brute-force pattern scan at
every byte offset (no instruction-boundary knowledge, so expect occasional
mid-instruction false positives; confirm with tools/dis.sh):

  abs32   any little-endian 32-bit word equal to the target (mov imm32, tables)
  call    cd d16 / dd d32           (call rel, with register mask)
  calls   fa ff d16 / fc ff d32
  jmp     cc d16 / dc d32
  bcc     c0..ca d8                 (only with --short)

Usage: tools/ep7_xref.py [--short] [--range LO HI] ADDR [ADDR ...]
"""
import argparse
import pathlib
import numpy as np

BASE = 0x60020020
IMG = pathlib.Path(__file__).resolve().parent.parent / "analysis/ep7_1100/00_0100_406a0020.decoded.bin"


def load():
    return np.frombuffer(IMG.read_bytes(), dtype=np.uint8)


def scan(d, targets, short=False):
    n = len(d)
    u = d.astype(np.int64)
    pc = np.arange(n, dtype=np.int64) + BASE
    out = {t: [] for t in targets}

    def s16(i):
        v = u[i] | (u[i + 1] << 8)
        return np.where(v >= 0x8000, v - 0x10000, v)

    def s32(i):
        v = u[i] | (u[i + 1] << 8) | (u[i + 2] << 16) | (u[i + 3] << 24)
        return np.where(v >= 0x80000000, v - 0x100000000, v)

    idx = np.arange(n - 8)
    w32 = (u[idx] | (u[idx + 1] << 8) | (u[idx + 2] << 16) | (u[idx + 3] << 24))
    # rel16/rel32 forms: (opcode bytes, displacement offset, kind, disp size)
    forms = []
    b0 = u[idx]
    b1 = u[idx + 1]
    m = b0 == 0xcd
    forms.append(("call16", idx[m], pc[idx[m]] + s16(idx[m] + 1)))
    m = b0 == 0xdd
    forms.append(("call32", idx[m], pc[idx[m]] + s32(idx[m] + 1)))
    m = b0 == 0xcc
    forms.append(("jmp16", idx[m], pc[idx[m]] + s16(idx[m] + 1)))
    m = b0 == 0xdc
    forms.append(("jmp32", idx[m], pc[idx[m]] + s32(idx[m] + 1)))
    m = (b0 == 0xfa) & (b1 == 0xff)
    forms.append(("calls16", idx[m], pc[idx[m]] + s16(idx[m] + 2)))
    m = (b0 == 0xfc) & (b1 == 0xff)
    forms.append(("calls32", idx[m], pc[idx[m]] + s32(idx[m] + 2)))
    if short:
        m = (b0 >= 0xc0) & (b0 <= 0xca)
        v = u[idx[m] + 1]
        forms.append(("b8", idx[m], pc[idx[m]] + np.where(v >= 0x80, v - 0x100, v)))
    for t in targets:
        hits = idx[w32 == t]
        out[t] += [("abs32", int(h) + BASE) for h in hits]
        for kind, where, tgt in forms:
            out[t] += [(kind, int(h) + BASE) for h in where[(tgt & 0xffffffff) == t]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--short", action="store_true")
    ap.add_argument("addr", nargs="+")
    a = ap.parse_args()
    d = load()
    ts = [int(x, 16) for x in a.addr]
    res = scan(d, ts, a.short)
    for t in ts:
        print(f"{t:#010x}: " + (", ".join(f"{k}@{w:#x}" for k, w in sorted(res[t], key=lambda r: r[1])) or "-"))


if __name__ == "__main__":
    main()
