#!/usr/bin/env python3
"""Write the SD loader v3 camera-test file EP7MOD/BUNDLES.BIN (offline; no camera).

  .venv/bin/python -I patches/sd_bundles_v3/make_test_file.py --bundle bundles/lachlan_v3.json --out DIR

Payload = exactly the table the release flashes (patches/bundles build_table of --bundle), plus ONE obvious
change: COLOR1 (flashed: disabled = stock) gets H/L enabled with hue +7 on the three green sectors
(green_cyan, green, yellow_green; UI order, positive = toward cyan, sim/recipes/fuji_like.json conventions)
and nothing else. So with the file loaded COLOR1 greens turn teal/cyan; without it COLOR1 is stock; every other
profile is identical either way. Written with the v1 format writer (patches/sd_bundles make_file) and re-checked
with tools/ep7_bundles_bin.py check_file (the Python mirror of the loader's rules).
The name is never an SD-update name; copy the EP7MOD folder to the card root by hand.
"""
import argparse, hashlib, importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


BB = _load('ep7_bundles_build', ROOT / 'patches/bundles/build.py')
SB = _load('ep7_sd_bundles_build', ROOT / 'patches/sd_bundles/build.py')
BIN = _load('ep7_bundles_bin', ROOT / 'tools/ep7_bundles_bin.py')
GREENS = (9, 10, 11)          # green_cyan, green, yellow_green (UI sector order)


def test_table(bundle_path):
    flashed, _ = BB.build_table(json.loads(Path(bundle_path).read_text()), BB.load_recipes())
    t = bytearray(flashed)
    if any(t[0:64]):
        raise SystemExit('COLOR1 is not empty in the flashed bundle; pick another slot')
    for i in GREENS:
        t[i] = 7                                  # hue +7
    t[31] = BB.FLAG_HL                            # H/L enabled
    return bytes(flashed), bytes(t)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--bundle', type=Path, default=ROOT / 'bundles/lachlan_v3.json')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    flashed, table = test_table(a.bundle)
    data = SB.make_file(table)
    probs = BIN.check_file(data)
    if probs:
        sys.exit(f'file rejected by the loader rules: {probs}')
    d = a.out / 'EP7MOD'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'BUNDLES.BIN').write_bytes(data)
    diff = [i for i in range(512) if flashed[i] != table[i]]
    print(f'{d / "BUNDLES.BIN"}: {len(data)} B, sha256 {hashlib.sha256(data).hexdigest()}; differs from the flashed '
          f'table only at bytes {diff} (COLOR1 hue greens +7, H/L flag)')


if __name__ == '__main__':
    main()
