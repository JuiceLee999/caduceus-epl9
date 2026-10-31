#!/usr/bin/env python3
"""Extract the stock E-P7 1.1 COLOR table (12 sector records + LUTs) and saturation gains.

Addresses from fishcu cross-model comparison; layout from PEN-F docs (HSL_TABLES.md).
Writes generated/color/ep7_color_table.json. Offline, read-only.
"""
import hashlib, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
BASE, TABLE, GAINS, TABLE_BYTES = 0x60020020, 0x6051de2c, 0x60531810, 3028
# table record -> wheel/UI index (record r: UI = 2*(r%6) + r//6)
SECTOR_NAMES = ['yellow', 'orange', 'orange-red', 'red', 'magenta', 'violet',
                'blue', 'blue-cyan', 'cyan', 'green-cyan', 'green', 'yellow-green']  # EXIF order

def main():
    d = MAIN.read_bytes()
    assert hashlib.sha256(d).hexdigest() == MAIN_SHA, 'unexpected main payload'
    t = d[TABLE - BASE: TABLE - BASE + TABLE_BYTES]
    assert d.count(t) == 1, 'COLOR table not unique'
    ptrs = struct.unpack_from('<12I', d, GAINS - BASE)
    recs = []
    for r in range(12):
        raw = t[r*28:(r+1)*28]
        recs.append(dict(record=r, ui_index=2*(r % 6) + r//6,
                         ui_name=SECTOR_NAMES[2*(r % 6) + r//6],
                         words_i16=list(struct.unpack('<14h', raw)),
                         hue_i16=struct.unpack_from('<h', raw, 12)[0],
                         sat_amp_i16=struct.unpack_from('<h', raw, 14)[0],
                         light_i16=struct.unpack_from('<h', raw, 16)[0],
                         gain_pos_neg=list(struct.unpack_from('<HH', d, ptrs[r]-BASE))))
    o = 336
    lut32 = [list(struct.unpack_from('<96I', t, o + i*384)) for i in range(4)]; o += 1536
    lut16 = [list(struct.unpack_from('<96H', t, o + i*192)) for i in range(6)]; o += 1152
    out = dict(source_main_sha256=MAIN_SHA, table_addr=hex(TABLE), table_sha256=hashlib.sha256(t).hexdigest(),
               gains_ptr_table=hex(GAINS), records=sorted(recs, key=lambda x: x['ui_index']),
               lut_u32=lut32, lut_u16=lut16, trailer=t[o:o+4].hex())
    p = ROOT / 'generated/color'; p.mkdir(parents=True, exist_ok=True)
    (p / 'ep7_color_table.json').write_text(json.dumps(out, indent=1))
    for r in out['records']:
        print(f"UI{r['ui_index']:2d} {r['ui_name']:13s} rec{r['record']:2d} gain(+/-)={r['gain_pos_neg']} words={r['words_i16']}")
    print('table sha', out['table_sha256'])

if __name__ == '__main__':
    main()
