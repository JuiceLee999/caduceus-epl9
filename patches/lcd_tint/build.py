#!/usr/bin/env python3
"""LCD green/magenta trim (display only, data edit only). Offline.

  .venv/bin/python -I patches/lcd_tint/build.py releases/v0.20/edits.json [--green-pct 8] [--out OUT.json]

The rear LCD's brightness and Monitor Adjust colour temperature are panel registers sent over SPI, not the VSC
display gamma (that LUT route, 0x60187439, is the one View Assist used and must not be touched). 0x60184360 copies a
70-B command template (.data 0x61f9ea38) and fills it from a 15 x 15 x 26-B row table (.data 0x61f9d31e,
row = brightness*390 + colourtemp*26): row words 0..3 -> panel command 0xd9 data [mode, R, G, B], words 4..7 ->
command 0x91 data (word 7 = brightness). Steps 0..6/8..14 use mode 0x80 with R/G/B gains; step 7 (Monitor Adjust 0)
uses mode 0x91 with [0x00, 0xe0, 0x00]. Every stock step attenuates G (0xab..0xe0) against R/B, which matches the
magenta cast. The two panel-open init sequences (.data 0x61f9d128, 0x61f9d1ec) also send 0xd9 [0x91,0,0xe0,0].

This patch multiplies the G byte of every 0xd9 payload (225 table rows, 2 init sequences, the template) by
1 + green_pct/100 (rounded, clamped to 0xff). Words keep their 0x1xx data marker. Nothing else changes.
.data init image = .data address - 0x1d67d40 (the delta the look-editor patches use). Only references:
0x601843fa (table) and 0x60184368 (template). The panel is the LCD only: HDMI (VSC channel 1), the ISP, JPEG and the
movie encoder never read these bytes.
"""
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
DELTA = 0x1d67d40
SRC = 'patches/lcd_tint'
TABLE = 0x61f9d31e - DELTA          # init image 0x602355de, 225 rows x 26 B, G = row byte 4
ROWS, ROW = 225, 26
# 0xd9 payload G bytes outside the table (init sequences, template)
SINGLE = [0x61f9d12e - DELTA, 0x61f9d1f2 - DELTA, 0x61f9ea6a - DELTA]
DEFAULT_PCT = 8.0


def trim(g, pct):
    return max(0, min(0xff, int(g * (1 + pct / 100) + 0.5)))


def edits(pct, stock):
    rd = lambda a, n: stock[a - BASE:a - BASE + n]
    out = []
    old = rd(TABLE, ROWS * ROW)
    new = bytearray(old)
    for r in range(ROWS):
        o = r * ROW + 4
        assert old[o + 1] == 1 and old[o - 4:o - 2] in (b'\x80\x01', b'\x91\x01'), r
        new[o] = trim(old[o], pct)
    out.append(dict(kind='0x100', addr=hex(TABLE), expect=old.hex(), new=bytes(new).hex(), source=SRC,
                    why=f'LCD panel 0xd9 G gain x{1 + pct / 100:.3f}, all brightness x colour-temp rows'))
    for a in SINGLE:
        b = rd(a, 2)
        assert b == b'\xe0\x01' and rd(a - 6, 6) == bytes.fromhex('d90091010001'), hex(a)
        out.append(dict(kind='0x100', addr=hex(a), expect=b[:1].hex(), new=bytes([trim(b[0], pct)]).hex(),
                        source=SRC, why='LCD panel 0xd9 G gain (init/template, step-7 value)'))
    return out


def apply(spec, pct):
    stock = STOCK.read_bytes()
    spec['edits'] = [e for e in spec['edits'] if e.get('source') != SRC]
    new = edits(pct, stock)
    for n in new:
        a, l = int(n['addr'], 16), len(n['new']) // 2
        for e in spec['edits']:
            if e['addr'].startswith('off:'):
                continue
            b, m = int(e['addr'], 16), len(e['new']) // 2
            if a < b + m and b < a + l:
                raise SystemExit(f'lcd_tint {n["addr"]} overlaps {e["addr"]}')
    spec['edits'] += new
    spec['lcd_tint'] = {'green_pct': pct, 'table': hex(TABLE), 'rows': ROWS}
    return spec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--green-pct', type=float, default=DEFAULT_PCT, help='G gain boost vs R/B, percent (default 8)')
    ap.add_argument('--out', type=Path, help='default: rewrite spec in place')
    a = ap.parse_args()
    if not -20 <= a.green_pct <= 20:
        raise SystemExit('--green-pct outside -20..20')
    spec = apply(json.loads(a.spec.read_text()), a.green_pct)
    (a.out or a.spec).write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['lcd_tint']))


if __name__ == '__main__':
    main()
