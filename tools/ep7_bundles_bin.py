#!/usr/bin/env python3
"""Write / check the SD-card bundle file EP7MOD/BUNDLES.BIN (offline desktop tool, no camera).

  .venv/bin/python -I tools/ep7_bundles_bin.py bundles/example.json --out generated/sdcard
      -> generated/sdcard/EP7MOD/BUNDLES.BIN (copy the EP7MOD folder to the card root by hand)
  .venv/bin/python -I tools/ep7_bundles_bin.py --check path/to/BUNDLES.BIN

The 512-byte payload is built by patches/bundles/build.py build_table() (same recipes, same
validation, same ABI as the flashed table). Header, CRC and per-byte ranges are defined in
patches/sd_bundles/build.py, the same constants the on-camera loader is assembled from; the file
is re-checked with a Python mirror of the loader's rules before it is written.
Slot names (film menu, docs/FILM_LIBRARY.md 8.7): a slot may carry "name": "Classic Neg" (1..15 printable
ASCII characters, no '@'). A slot with only a name (no "recipe") is neutral: all-zero entry = the camera's own
profile rendering, only the menu label changes. If any slot has a name, the file grows to 680 bytes: the v1
544-byte file unchanged, then names[8][16] (slot order COLOR1-4, MONO1-4, NUL-padded), "EP7N", CRC-32 of bytes
544..675. A loader built without --names rejects that size (no looks); the --names loader loads the looks
either way and shows names only if the whole name section checks out.

  {"COLOR1": {"name": "Kodachrome"}, "COLOR2": {"recipe": "classic_neg", "grain": "low", "name": "Classic Neg"}}

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


NAMES_LO, NAME_SLOTS, NAME_LEN = SB.FILE_LEN, 8, 16          # 544: name section directly after the v1 file
MARK_OFF = NAMES_LO + NAME_SLOTS * NAME_LEN                    # 672
NCRC_OFF = MARK_OFF + 4                                        # 676
FILE_LEN_N = NCRC_OFF + 4                                      # 680
NMAGIC = b'EP7N'
NAME_MAX = 15


def name_ok(n):
    return isinstance(n, str) and 1 <= len(n) <= NAME_MAX and all(0x20 <= ord(c) <= 0x7e and c != '@' for c in n)


def name_section(names):
    """names: list of 8 (str or None) in slot order -> 136 bytes (names, 'EP7N', CRC-32 of the first 132)."""
    b = bytearray()
    for n in names:
        if n is not None and not name_ok(n):
            raise ValueError(f'name {n!r}: need 1..{NAME_MAX} printable ASCII characters, no "@"')
        b += (n or '').encode('ascii').ljust(NAME_LEN, b'\0')
    b += NMAGIC
    return bytes(b) + struct.pack('<I', zlib.crc32(bytes(b)) & 0xffffffff)


def check_names(sec):
    """Mirror of the --names loader's sd_names: -> problems ([] = names would be shown)."""
    if sec[MARK_OFF - NAMES_LO:NCRC_OFF - NAMES_LO] != NMAGIC:
        return ['name marker != EP7N']
    if struct.unpack_from('<I', sec, NCRC_OFF - NAMES_LO)[0] != zlib.crc32(sec[:NCRC_OFF - NAMES_LO]) & 0xffffffff:
        return ['name CRC mismatch']
    for k in range(NAME_SLOTS):
        n, nul = sec[k * NAME_LEN:(k + 1) * NAME_LEN], False
        for i, c in enumerate(n):
            if c == 0:
                nul = True
            elif nul or i == NAME_LEN - 1 or c == 0x40 or not 0x20 <= c <= 0x7e:
                return [f'slot {k} name byte {i} = {c:#04x}']
    return []


def names_of(data):
    """-> 8 names (str or None) if the --names loader would publish them, else None."""
    if len(data) != FILE_LEN_N or check_file(data[:SB.FILE_LEN]) or check_names(data[NAMES_LO:]):
        return None
    return [data[NAMES_LO + k * NAME_LEN:NAMES_LO + (k + 1) * NAME_LEN].split(b'\0')[0].decode() or None
            for k in range(NAME_SLOTS)]


def check_file(data):
    """-> list of problems with the looks (empty = the loader would accept the table). A 680-byte file is
    checked on its first 544 bytes here; check_names() decides whether its names are shown."""
    p = []
    if len(data) == FILE_LEN_N:
        data = data[:SB.FILE_LEN]
    if len(data) != SB.FILE_LEN:
        return [f'size {len(data)} not in ({SB.FILE_LEN}, {FILE_LEN_N})']
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


def split_names(bundle):
    """-> (bundle without names, neutral name-only slots dropped; 8 names or None)."""
    out, names = {}, [None] * NAME_SLOTS
    for k, v in bundle.items():
        if k in BB.SLOTS and isinstance(v, dict) and 'name' in v:
            names[BB.SLOTS.index(k)] = v['name']
            v = {x: y for x, y in v.items() if x != 'name'}
            if not v or v.get('recipe') is None and set(v) <= {'recipe'}:
                continue                       # neutral slot: stock rendering, only the label changes
        out[k] = v
    return out, (names if any(n is not None for n in names) else None)


def build(bundle_path):
    bundle, names = split_names(json.loads(Path(bundle_path).read_text()))
    table, meta = BB.build_table(bundle, BB.load_recipes())
    data = SB.make_file(table)
    if names is not None:
        data += name_section(names)
        for m, n in zip(meta, names):
            m['name'] = n
    probs = check_file(data) + (check_names(data[NAMES_LO:]) if names is not None else [])
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
        data = a.check.read_bytes()
        probs = check_file(data)
        if not probs and len(data) == FILE_LEN_N:
            np_ = check_names(data[NAMES_LO:])
            print('names: ' + (', '.join(f'{s}={n!r}' for s, n in zip(BB.SLOTS, names_of(data)) if n) if not np_
                               else 'REJECTED (looks still load; stock labels): ' + '; '.join(np_)))
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
    nm = [f"{m['slot']}={m['name']!r}" for m in meta if m.get('name')]
    print(f'wrote {dst} ({len(data)} B, crc32 {struct.unpack_from("<I", data, 16)[0]:#010x}); slots {", ".join(on)}'
          + (f'; names {", ".join(nm)}' if nm else ''))
    if any(len(m.get('name') or '') > 12 for m in meta):
        print('note: names over 12 characters may be clipped on narrow screens (docs/FILM_LIBRARY.md 7)')


if __name__ == '__main__':
    main()
