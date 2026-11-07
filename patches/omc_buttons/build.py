#!/usr/bin/env python3
"""Button remapping + arrow-pad widening on v0.28, test o1 (issue #26). Offline. docs/OMC_FEATURES.md, docs/BUTTONS.md.

Our own data-only patch from patches/buttons (v0.5 era, dropped with the Test 3 bootloop bisect, never camera-tested on
its own), re-applied on v0.28. No code or data from azqeurio's om-c-firmware is used (none is published).

  .venv/bin/python -I patches/omc_buttons/build.py releases/v0.28/edits.json --out generated/omc/t1/edits.json
  .venv/bin/python -I tools/build_package.py generated/omc/t1/edits.json --out generated/omc/t1/pkg
  .venv/bin/python -I patches/omc_buttons/verify.py releases/v0.28/edits.json generated/omc/t1/edits.json generated/omc/t1/pkg

apply(spec, version='0.28o1') -> spec. 10 in-place section-2 edits (validator lists + 5 record fields) + the version label.
  sids 47/48/49 (full buttons)  -> 23 codes: + AF Home, RAW, Test picture, Keystone, HDR, BKT, ISO/WB, WB/ISO,
                                   Multi Function, Level, IS mode
  sids 51/53 (arrow right/down) -> 16 codes: + ISO/WB, WB/ISO, Peaking, Magnify, Level, tele-con, Multi Function, RAW
"""
import argparse, copy, importlib.util, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = 'patches/omc_buttons'


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


BT = _load('ep7_buttons_build', ROOT / 'patches/buttons/build.py')
FV = _load('fw_version_build', ROOT / 'patches/fw_version/build.py')
BASE = BT.B


def image(spec, stock):
    im = bytearray(stock)
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16) - BASE
            nb = bytes.fromhex(e['new']); im[a:a + len(nb)] = nb
    return bytes(im)


def apply(spec, version='0.28o1'):
    stock = BT.img()
    spec = copy.deepcopy(spec)
    if spec.get('sharp_off', {}).get('slot_byte') != 51 or spec.get('fw_version', {}).get('value') != '0.28':
        raise SystemExit('base is not v0.28')
    if 'buttons' in spec or any(e.get('source') == SRC for e in spec['edits']):
        raise SystemExit('base already has button edits')
    bad = [n for n, ok, _ in BT.static_checks(stock) if not ok]
    if bad:
        raise SystemExit(f'stock preconditions fail: {bad}')
    spec = FV.apply(spec, version)
    im = image(spec, stock)
    for e in BT.edits(stock):
        a, n = int(e['addr'], 16), len(e['new']) // 2
        if im[a - BASE:a - BASE + n].hex() != e['expect']:
            raise SystemExit(f'{a:#x} not stock in base')
        for o in spec['edits']:
            if not o['addr'].startswith('off:'):
                oa, on = int(o['addr'], 16), len(o['new']) // 2
                if oa < a + n and a < oa + on:
                    raise SystemExit(f'{a:#x} overlaps edit {o["addr"]}')
        spec['edits'].append(dict(e, source=SRC))
    meta = BT.spec()['buttons']
    spec['buttons'] = meta
    spec['omc_buttons'] = dict(built_by=SRC, test='o1', version=version, issue=26,
                               sites=[e['addr'] for e in spec['edits'] if e.get('source') == SRC])
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--version', default='0.28o1')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()), a.version)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['omc_buttons']))
