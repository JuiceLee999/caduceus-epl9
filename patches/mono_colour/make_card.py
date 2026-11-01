#!/usr/bin/env python3
"""v0.15 default card: COLOR1-4 as on the v0.14 card, MONO1/MONO2 = colour looks, MONO3/MONO4 = plain B&W.

  .venv/bin/python -I patches/mono_colour/make_card.py --bundles releases/v0.14/card/EP7MOD/BUNDLES.BIN \
      --looks releases/v0.14/card/EP7MOD/LOOKS.BIN --out releases/v0.15/card/EP7MOD/BUNDLES.BIN \
      [--mono1 "Portra 400"] [--mono2 "Kodachrome64"]

MONO1/2 get place(look, MONOk) from LOOKS.BIN (colour byte 1, flags 3, the look's sat/hue/light) and the look's
name; MONO3/4 are all-zero entries with an empty name (stock mono rendering, stock label). The file is checked with
the loader's rules (tools/ep7_bundles_bin.py) before it is written. Offline desktop tool; never an SD-update name.
"""
import argparse, importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BIN = _load('ep7_bundles_bin', ROOT / 'tools/ep7_bundles_bin.py')
LB = _load('ep7_looks_bin', ROOT / 'tools/ep7_looks_bin.py')


def make(bundles, looks, mono1, mono2):
    if LB.check_file(looks):
        raise ValueError(f'LOOKS.BIN: {LB.check_file(looks)}')
    n = len(looks) // 64 - 1
    recs = [looks[64 * (j + 1):64 * (j + 2)] for j in range(n)]
    byname = {r[LB.NAME_OFF:LB.NAME_OFF + 16].split(b'\0')[0].decode(): r for r in recs}
    names = BIN.names_of(bundles) or [None] * 8
    table = bytearray(bundles[BIN.SB.HDR_LEN:BIN.SB.FILE_LEN])
    for k, nm in ((4, mono1), (5, mono2)):
        r = byname[nm]
        if r[LB.CLASS_OFF] != 0 or not LB.allowed(r, k):
            raise ValueError(f'{nm}: not a MONO-capable colour look')
        table[64 * k:64 * k + 64] = LB.place(r, k)
        names[k] = nm
    for k in (6, 7):
        table[64 * k:64 * k + 64] = bytes(64)
        names[k] = None
    data = BIN.SB.make_file(bytes(table)) + BIN.name_section(names)
    probs = BIN.check_file(data) + BIN.check_names(data[BIN.NAMES_LO:])
    if probs:
        raise ValueError(f'card fails the loader rules: {probs}')
    if data[BIN.SB.HDR_LEN:BIN.SB.HDR_LEN + 256] != bundles[BIN.SB.HDR_LEN:BIN.SB.HDR_LEN + 256]:
        raise ValueError('COLOR1-4 entries changed')
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--bundles', type=Path, required=True)
    ap.add_argument('--looks', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--mono1', default='Portra 400')
    ap.add_argument('--mono2', default='Kodachrome64')
    a = ap.parse_args()
    data = make(a.bundles.read_bytes(), a.looks.read_bytes(), a.mono1, a.mono2)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(data)
    print(f'{len(data)} B -> {a.out}: MONO1={a.mono1!r} MONO2={a.mono2!r} colour, MONO3/4 B&W')


if __name__ == '__main__':
    main()
