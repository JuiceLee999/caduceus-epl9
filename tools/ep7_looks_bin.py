#!/usr/bin/env python3
"""Write / check the look-picker card files EP7MOD/LOOKS.BIN and EP7MOD/SLOTS.BIN (offline desktop tool, no camera).

  .venv/bin/python -I tools/ep7_looks_bin.py bundles/library_v1.json --out generated/look_picker/card
      -> <out>/EP7MOD/LOOKS.BIN (and SLOTS.BIN with --slots COLOR1=velvia,MONO2=stock,...)
  .venv/bin/python -I tools/ep7_looks_bin.py --check <dir>/EP7MOD/LOOKS.BIN [--slots-file <dir>/EP7MOD/SLOTS.BIN]

Design: docs/LOOK_PICKER.md. The looks come from the same library JSON as tools/ep7_library.py (LIBRARY.BIN
v2): same recipes, same names, same canonical bundle and the same placement rule P(look, slot). LOOKS.BIN is the
compact v3 form the camera keeps in one 2048-byte heap block (at most 20 looks):

  header 64 B: 'EP7B', u16 version 3, u16 64, u32 1100, u32 payload (= 64 n), u32 CRC-32 (zlib over bytes 0..15
               then 20..end, the v1 rule), SHA prefix of the decoded main (4 B), u16 n (1..20), u16 64,
               u32 layout_crc (tools/ep7_library.layout_crc), 32 zero bytes
  record 64 B: +0..44 canonical bundle bytes 0..44 (layout.json ABI; bundle bytes 46..63 are always 0),
               +45 class (0 colour, 1 mono), +46 slot mask (bit0 COLOR, bit1 MONO; colour 1 or 3, mono 2),
               +47 bloom_tint 0..4 (test13b; placed at bundle +45; 0 in older files), +48 name[16] (1..15 printable ASCII except '@', NUL-padded, byte 15 NUL)

SLOTS.BIN (20 B) is what the camera writes back when the picker changes a slot (and what it reads at power-on):
  'EP7S', u32 LOOKS.BIN CRC (binds the map to one library), assign[8] (COLOR1-4, MONO1-4: 0..n-1 = look,
  0xFF = stock (all-zero entry), 0xFE = untouched (keep BUNDLES.BIN's slot)), u32 CRC-32 (zlib) of bytes 0..15.
An invalid assign byte is treated as 0xFE by the camera; a bad SLOTS.BIN is ignored as a whole.
Never writes into DCOLYMP/ and never writes an SD-update name.
"""
import argparse, importlib.util, json, struct, sys, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


LIB = _load('ep7_library', ROOT / 'tools/ep7_library.py')
SB = LIB.SB
MAGIC, VERSION, HDR_LEN, REC_LEN, MAX_LOOKS = b'EP7B', 3, 64, 64, 20
BUNDLE_USED = 45
CLASS_OFF, MASK_OFF, NAME_OFF, NAME_LEN = 45, 46, 48, 16
# test13b: record +47 = bloom_tint (0..4; old files have 0 = neutral), placed at bundle byte +45 (layout.json bloom_tint)
TINT_OFF, TINT_BUNDLE, TINT_MAX = 47, 45, 4
SMAGIC, SLOTS_LEN = b'EP7S', 20
STOCK, UNTOUCHED = 0xFF, 0xFE
PATH_LOOKS, PATH_SLOTS = 'C:\\EP7MOD\\LOOKS.BIN', 'C:\\EP7MOD\\SLOTS.BIN'
SLOTS = LIB.SLOTS


def header(n, crc=0):
    h = MAGIC + struct.pack('<HHII', VERSION, HDR_LEN, SB.FW_BUILD, REC_LEN * n) + struct.pack('<I', crc)
    h += SB.SHA_PREFIX + struct.pack('<HHI', n, REC_LEN, LIB.layout_crc())
    return h + bytes(HDR_LEN - len(h))


def record(rec96):
    """LIBRARY v2 96-byte record -> 64-byte LOOKS.BIN record."""
    b = rec96[:64]
    if any(b[TINT_BUNDLE + 1:]):
        raise ValueError('canonical bundle uses bytes 46..63 (layout.json grew: LOOKS.BIN v3 must be revised)')
    name = rec96[LIB.NAME_OFF:LIB.NAME_OFF + 16]
    return bytes(b[:BUNDLE_USED]) + bytes([rec96[LIB.CLASS_OFF], rec96[LIB.MASK_OFF], b[TINT_BUNDLE]]) + name


def to_rec96(rec64):
    """Back to the v2 form (for LIB.place())."""
    r = bytearray(LIB.LOOK_LEN)
    r[:BUNDLE_USED] = rec64[:BUNDLE_USED]
    r[TINT_BUNDLE] = rec64[TINT_OFF]
    r[LIB.NAME_OFF:LIB.NAME_OFF + 16] = rec64[NAME_OFF:NAME_OFF + 16]
    r[LIB.CLASS_OFF], r[LIB.MASK_OFF] = rec64[CLASS_OFF], rec64[MASK_OFF]
    return bytes(r)


def place(rec64, k):
    """P(look, slot k) -> 64-byte table entry (raises if the look may not go in that slot)."""
    return LIB.place(to_rec96(rec64), SLOTS[k])


def allowed(rec64, k):
    return bool(rec64[MASK_OFF] & (1 if k < 4 else 2))


def make_file(recs):
    n = len(recs)
    if not 1 <= n <= MAX_LOOKS:
        raise ValueError(f'LOOKS.BIN holds 1..{MAX_LOOKS} looks (one 2048-B heap block), got {n}')
    body = b''.join(recs)
    raw = header(n) + body
    crc = zlib.crc32(raw[:16] + raw[20:]) & 0xffffffff
    return header(n, crc) + body


def compile_looks(cfg):
    """Library JSON (tools/ep7_library.py input) -> (LOOKS.BIN bytes, look keys, names)."""
    recipes = LIB.BB.load_recipes()
    cfg = dict(cfg)
    cfg.pop('slots', None)
    looks = dict(cfg.get('looks', {}))
    inc = cfg.get('include_recipes', [])
    inc = list(recipes) if inc == 'all' else inc
    for r in inc:
        looks.setdefault(r, {'recipe': r})
    recs, keys, names = [], [], []
    for k, v in looks.items():
        r96, meta = LIB.look_record(k, v, recipes)
        recs.append(record(r96))
        keys.append(k)
        names.append(meta['name'])
    data = make_file(recs)
    probs = check_file(data)
    if probs:
        raise ValueError(f'built LOOKS.BIN fails the camera rules: {probs}')
    return data, keys, names


def file_crc(data):
    return struct.unpack_from('<I', data, 16)[0]


def make_slots(lib_crc, assign):
    if len(assign) != 8 or not all(0 <= a <= 255 for a in assign):
        raise ValueError('assign: 8 bytes')
    b = SMAGIC + struct.pack('<I', lib_crc) + bytes(assign)
    return b + struct.pack('<I', zlib.crc32(b) & 0xffffffff)


def _name_ok(nm):
    """Camera rule: first byte non-zero, 0..15 chars 0x20..0x7e except '@', then NUL to byte 15."""
    if len(nm) != 16 or nm[0] == 0 or nm[15] != 0:
        return False
    seen = False
    for c in nm:
        if c == 0:
            seen = True
        elif seen or c == 0x40 or not 0x20 <= c <= 0x7e:
            return False
    return True


def check_file(data):
    """Python mirror of the camera's pk_check -> list of problems (empty = accepted)."""
    p = []
    size = len(data)
    if size < HDR_LEN + REC_LEN or size > HDR_LEN + REC_LEN * MAX_LOOKS or size % REC_LEN:
        return [f'size {size}']
    n = (size - HDR_LEN) // REC_LEN
    want = header(n)
    if data[:16] != want[:16] or data[20:HDR_LEN] != want[20:HDR_LEN]:
        p.append('header')
    if zlib.crc32(data[:16] + data[20:]) & 0xffffffff != file_crc(data):
        p.append('crc')
    lo, span, _ = SB.range_table(SB.layout())
    for j in range(n):
        r = data[HDR_LEN + REC_LEN * j:HDR_LEN + REC_LEN * (j + 1)]
        for k in range(BUNDLE_USED):
            v = r[k] - 256 if r[k] >= 128 else r[k]
            if not 0 <= v - lo[k] <= span[k]:
                p.append(f'look {j} byte {k} = {v} out of range')
                break
        cls, mask = r[CLASS_OFF], r[MASK_OFF]
        if not (cls == 0 and mask in (1, 3) or cls == 1 and mask == 2) or r[TINT_OFF] > TINT_MAX:
            p.append(f'look {j} class/mask/tint {cls}/{mask}/{r[TINT_OFF]}')
        if not _name_ok(r[NAME_OFF:NAME_OFF + 16]):
            p.append(f'look {j} name')
    return p


def check_slots(slots, looks):
    """-> (valid, effective assign[8]) as the camera derives it (0xFE for anything it would not apply)."""
    if len(slots) < SLOTS_LEN or slots[:4] != SMAGIC or struct.unpack_from('<I', slots, 4)[0] != file_crc(looks) or \
            zlib.crc32(slots[:16]) & 0xffffffff != struct.unpack_from('<I', slots, 16)[0]:
        return False, [UNTOUCHED] * 8
    n = (len(looks) - HDR_LEN) // REC_LEN
    out = []
    for k in range(8):
        a = slots[8 + k]
        if a == STOCK:
            out.append(STOCK)
        elif a < n and allowed(looks[HDR_LEN + REC_LEN * a:HDR_LEN + REC_LEN * (a + 1)], k):
            out.append(a)
        else:
            out.append(UNTOUCHED)
    return True, out


def rec(looks, j):
    return looks[HDR_LEN + REC_LEN * j:HDR_LEN + REC_LEN * (j + 1)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('library', nargs='?', type=Path)
    ap.add_argument('--out', type=Path)
    ap.add_argument('--slots', help='write SLOTS.BIN too: COLOR1=<look key>|stock,... (others untouched)')
    ap.add_argument('--check', type=Path)
    ap.add_argument('--slots-file', type=Path)
    a = ap.parse_args()
    try:
        if a.check:
            data = a.check.read_bytes()
            probs = check_file(data)
            print('LOOKS.BIN', 'OK' if not probs else f'REJECTED {probs}')
            if not probs:
                n = (len(data) - HDR_LEN) // REC_LEN
                for j in range(n):
                    r = rec(data, j)
                    print(f'  {j:2d} {r[NAME_OFF:NAME_OFF + 16].split(b"\0")[0].decode():15s} '
                          f'{"mono" if r[CLASS_OFF] else "colour"} slots {"C" if r[MASK_OFF] & 1 else "-"}{"M" if r[MASK_OFF] & 2 else "-"}')
            if a.slots_file:
                ok, eff = check_slots(a.slots_file.read_bytes(), data)
                print('SLOTS.BIN', 'OK' if ok else 'IGNORED', eff)
            sys.exit(1 if probs else 0)
        if not a.library or not a.out:
            ap.error('library and --out are required (or --check)')
        data, keys, names = compile_looks(json.loads(a.library.read_text()))
        if 'DCOLYMP' in str(a.out).upper():
            raise ValueError('refusing to write into DCOLYMP/')
        d = a.out / 'EP7MOD'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'LOOKS.BIN').write_bytes(data)
        print(f'LOOKS.BIN {len(data)} B, {len(keys)} looks: ' + ', '.join(names))
        if a.slots:
            assign = [UNTOUCHED] * 8
            for item in a.slots.split(','):
                s, v = item.split('=')
                k = SLOTS.index(s.strip())
                if v.strip() == 'stock':
                    assign[k] = STOCK
                else:
                    j = keys.index(v.strip())
                    if not allowed(rec(data, j), k):
                        raise ValueError(f'{v} cannot go in {s}')
                    assign[k] = j
            (d / 'SLOTS.BIN').write_bytes(make_slots(file_crc(data), assign))
            print('SLOTS.BIN', assign)
    except ValueError as e:
        sys.exit(f'error: {e}')


if __name__ == '__main__':
    main()
