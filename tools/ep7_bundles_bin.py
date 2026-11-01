#!/usr/bin/env python3
"""Write / check the SD-card bundle file EP7MOD/BUNDLES.BIN (offline desktop tool, no camera).

  .venv/bin/python -I tools/ep7_bundles_bin.py bundles/example.json --out generated/sdcard
      -> generated/sdcard/EP7MOD/BUNDLES.BIN (copy the EP7MOD folder to the card root by hand)
  .venv/bin/python -I tools/ep7_bundles_bin.py --check path/to/BUNDLES.BIN

The 512-byte payload is built by patches/bundles/build.py build_table() (same recipes, same
validation, same ABI as the flashed table). Header, CRC and per-byte ranges are defined in
patches/sd_bundles/build.py, the same constants the on-camera loader is assembled from; the file
is re-checked with a Python mirror of the loader's rules before it is written.
The output name is never an SD-update name (E142*.BIN etc.): the firmware updater only looks in
DCOLYMP/ for E/G/H/W/S/N/A/M/V/T/I/K-142 and F??? patterns.
"""
import argparse, importlib.util, json, struct, sys, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BB = _load('ep7_bundles_build', ROOT / 'patches/bundles/build.py')
SB = _load('ep7_sd_bundles_build', ROOT / 'patches/sd_bundles/build.py')


def check_file(data):
    """-> list of problems (empty = the loader would accept it)."""
    p = []
    if len(data) != SB.FILE_LEN:
        return [f'size {len(data)} != {SB.FILE_LEN}']
    want = SB.header(0)
    for i in list(range(16)) + list(range(20, SB.HDR_LEN)):
        if data[i] != want[i]:
            p.append(f'header byte {i}: {data[i]:#04x} != {want[i]:#04x}')
            break
    crc = zlib.crc32(data[:16] + data[20:]) & 0xffffffff
    if struct.unpack_from('<I', data, 16)[0] != crc:
        p.append(f'crc32 {struct.unpack_from("<I", data, 16)[0]:#010x} != {crc:#010x}')
    lo, span, who = SB.range_table(SB.layout())
    tab = data[SB.HDR_LEN:]
    for k, b in enumerate(tab):
        v = b - 256 if b >= 128 else b
        if not 0 <= v - lo[k % 64] <= span[k % 64]:
            p.append(f'slot {k // 64} byte {k % 64} ({who[k % 64]}) = {v} outside {lo[k % 64]}..{lo[k % 64] + span[k % 64]}')
            break
    return p


def build(bundle_path):
    bundle = json.loads(Path(bundle_path).read_text())
    table, meta = BB.build_table(bundle, BB.load_recipes())
    data = SB.make_file(table)
    probs = check_file(data)
    if probs:
        raise ValueError(f'built file fails the loader rules: {probs}')
    return data, table, meta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('bundle', nargs='?', type=Path)
    ap.add_argument('--out', type=Path, help='card-root folder to write EP7MOD/BUNDLES.BIN into')
    ap.add_argument('--check', type=Path, help='validate an existing BUNDLES.BIN')
    a = ap.parse_args()
    if a.check:
        probs = check_file(a.check.read_bytes())
        print('OK: the loader would accept this file' if not probs else 'REJECT: ' + '; '.join(probs))
        sys.exit(1 if probs else 0)
    if not a.bundle or not a.out:
        ap.error('need BUNDLE and --out (or --check FILE)')
    try:
        data, table, meta = build(a.bundle)
    except ValueError as e:
        sys.exit(f'error: {e}')
    dst = a.out / 'EP7MOD' / 'BUNDLES.BIN'
    if dst.name.upper().startswith(('E142', 'G142', 'H142', 'W142', 'S142')):
        sys.exit('refusing an SD-update-like name')
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    on = [m['slot'] + ':' + m['recipe'] for m in meta if m.get('recipe')]
    print(f'wrote {dst} ({len(data)} B, crc32 {struct.unpack_from("<I", data, 16)[0]:#010x}); slots {", ".join(on)}')


if __name__ == '__main__':
    main()
