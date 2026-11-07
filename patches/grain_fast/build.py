#!/usr/bin/env python3
"""COLOR grain on the image processor, test t1. docs/GRAIN_PORT.md last section. Offline.

  .venv/bin/python -I patches/grain_fast/build.py releases/v0.26/edits.json --mod-version 0.27t1 --out generated/grain_fast/t1/edits.json

apply(spec, mod_version=None) -> spec. One 4-byte edit (the selector call's rel32 at 0x60339d3c) and one stub in section 1.
Idea from androidfanman/caduceus-om3 xb_dev (Apache-2.0, camera-tested on the OM-3 by that project's account); code is ours.
"""
import argparse, copy, importlib.util, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V19 = _load('ep7_v019_build', ROOT / 'patches/v019/build.py')
SB3 = V19.SB3
FV = _load('fw_version_build', ROOT / 'patches/fw_version/build.py')
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE, SRC = 0x60020020, 'patches/grain_fast'
AT, END = 0x60210f80, 0x60210ff0          # section 1 FF tail, also the unbuilt aperture ring claim; 0x60210f77..f80 and ff0.. stay FF
SITE, SEL, FRAME = 0x60339d3c, 0x603b5200, b'\xa0\x0c'
BAD = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}


def img_of(spec, stock):
    im = bytearray(stock)
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16) - BASE; n = bytes.fromhex(e['new']); im[a:a + len(n)] = n
    return bytes(im)


def apply(spec, mod_version=None):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    im = img_of(spec, stock)
    if im[SITE - BASE] != 0xdd or SITE + struct.unpack_from('<i', im, SITE + 1 - BASE)[0] != SEL or im[SITE + 5 - BASE:SITE + 7 - BASE] != FRAME:
        raise SystemExit('selector call site differs')
    if set(im[AT - 9 - BASE:END + 16 - BASE]) != {0xff} or set(stock[AT - 9 - BASE:END + 16 - BASE]) != {0xff}:
        raise SystemExit('stub range not FF')
    for e in spec['edits']:
        if not e['addr'].startswith('off:') and e['kind'] == '0x100':
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a < END and AT < a + n or a < SITE + 7 and SITE < a + n:
                raise SystemExit(f'overlap with edit {e["addr"]}')
    code, lst, s, _ = SB3.assemble((HERE / 'gf.s.in').read_text(), AT, {'ep7_sel': SEL})
    if AT + len(code) > END:
        raise SystemExit(f'{len(code)} B does not fit {END - AT}')
    ins = SB3.disasm(code, AT, s['gf_end'])
    if any(op in BAD for _, op, _ in ins) or any(k == 'abs' for _, _, k, _ in SB3.store_audit(ins)):
        raise SystemExit('forbidden instruction or absolute store')
    if any(code[a - AT] == 0xfb for a, _, _ in ins):
        raise SystemExit('fb-prefixed form: misbehaved on the OM-3 camera')
    spec['edits'].append(dict(kind='0x100', addr=hex(AT), expect=stock[AT - BASE:AT - BASE + len(code)].hex(), new=code.hex(), source=SRC,
                              why=f'grain_fast t1: gf_dev ({len(code)} B, section 1 FF tail)'))
    spec['edits'].append(dict(kind='0x100', addr=hex(SITE + 1), expect=stock[SITE + 1 - BASE:SITE + 5 - BASE].hex(), new=struct.pack('<i', s['gf_dev'] - SITE).hex(), source=SRC,
                              why='grain_fast t1: selector call in the request driver -> gf_dev (rel32 only)'))
    spec['grain_fast'] = dict(built_by=SRC, test='t1', gf_dev=hex(s['gf_dev']), code_len=len(code), site=hex(SITE), levels={'COLOR1': 0, 'COLOR2': 1, 'COLOR3': 2, 'COLOR4': 3})
    if mod_version:
        spec['edits'] = [e for e in spec['edits'] if e.get('source') != FV.SRC]
        spec = FV.apply(spec, mod_version)
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--mod-version')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()), a.mod_version)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['grain_fast']), spec['fw_version']['value'])
