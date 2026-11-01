#!/usr/bin/env python3
"""Mod version on the Setup > Firmware screen (display only). Offline.

  .venv/bin/python -I patches/fw_version/build.py releases/v0.15/edits.json --mod-version v0.15 [--out OUT.json]

The Firmware screen (Confirm_Based_Version_Viewer, builder 0x60df5285) fills a 1004-B block: four 74-B row-label
items (Body / Lens / Flash / Acc) + the "%X.%X" version strings (4-wchar buffers at +940 / +972, too small to extend).
Row labels come from the 8-B descriptors 0x6115d5e8.. (kind 4 = string id 0x6bd "Body") via the copier 0x60df25b5;
kind 5 copies an ASCII C string (pointer at +4) inline into the item's 33-wchar text field (the same item kind the
look editor's guide label uses on camera). This patch turns the Body descriptor into kind 5 pointing at
"Body Caduceus <ver>" (sec-6 FF tail 0x61242fc0). The version number, its sprintf, the updater / version-check code
and the EXIF Software template ("Version x.x", 0x604ddeb4) are untouched. The label becomes English-only.
"""
import argparse, json, re, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
DESC = 0x6115d5e8                      # row-0 (Body) label descriptor {u16 kind, u16 id, u32 text}
DESC_STOCK = bytes.fromhex('0400bd06e4d51561')
STR_AT, STR_END = 0x61242fc0, 0x61242fe0   # sec-6 FF tail (aspect list B ends 0x61242fb4; load end 0x61243000)
MAXLEN = 31                            # item text field = 33 wchars (memset 66 B); copier has no bound
SRC = 'patches/fw_version'


def label(ver):
    if not re.fullmatch(r'v\d+\.\d+[A-Za-z0-9.\-]*', ver):
        raise SystemExit(f'--mod-version {ver!r}: expected e.g. v0.15')
    t = f'Body Caduceus {ver}'
    if len(t) > MAXLEN or len(t) + 1 > STR_END - STR_AT:
        raise SystemExit(f'label {t!r} longer than {MAXLEN}')
    return t


def strip(spec):
    spec.pop('fw_version', None)
    spec['edits'] = [e for e in spec['edits'] if e.get('source') != SRC]
    return spec


def apply(spec, ver):
    text = label(ver)
    stock = STOCK.read_bytes()
    strip(spec)
    if stock[DESC - BASE:DESC - BASE + 8] != DESC_STOCK:
        raise SystemExit('descriptor not stock')
    for e in spec['edits']:
        if e['addr'].startswith('off:'):
            continue
        a, n = int(e['addr'], 16), len(e['new']) // 2
        if (a < STR_END + 8 and STR_AT - 8 < a + n) or (a < DESC + 8 and DESC < a + n):
            raise SystemExit(f'placement overlaps edit {e["addr"]}')
    s = text.encode('ascii') + b'\0'
    s += b'\0' * (-len(s) % 4)
    exp = stock[STR_AT - BASE:STR_AT - BASE + len(s)]
    if exp != b'\xff' * len(s):
        raise SystemExit('string range not FF')
    new_desc = struct.pack('<HHI', 5, 0x6bd, STR_AT)
    spec['edits'].append(dict(kind='0x100', addr=hex(DESC), expect=DESC_STOCK.hex(), new=new_desc.hex(),
                              why=f'fw_version: Firmware screen Body label -> kind 5 text "{text}" (display only)', source=SRC))
    spec['edits'].append(dict(kind='0x100', addr=hex(STR_AT), expect=exp.hex(), new=s.hex(),
                              why=f'fw_version: label text "{text}" (sec-6 FF tail)', source=SRC))
    spec['fw_version'] = dict(mod_version=ver, text=text, desc=hex(DESC), str_at=hex(STR_AT), str_len=len(s))
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--mod-version', required=True)
    ap.add_argument('--out', type=Path, help='default: rewrite spec in place')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()), a.mod_version)
    (a.out or a.spec).write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['fw_version'], indent=1))
