#!/usr/bin/env python3
"""v0.28 = v0.27's layers with the finer grain (patches/v027/build.py, grain r2) + sharpening off per COLOR profile
(patches/sharp_off, Extras sector 10, slot +51). Offline. docs/SHARPENING_OFF.md, docs/GRAIN_PORT.md.

  .venv/bin/python -I patches/v028/build.py releases/v0.26/edits.json --out generated/v028/edits.json
"""
import argparse, importlib.util, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def apply(spec):
    spec = _load('v027', ROOT / 'patches/v027/build.py').apply(spec)
    return _load('sharp_off', ROOT / 'patches/sharp_off/build.py').apply(spec, version='0.28')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(apply(json.loads(a.spec.read_text())), indent=1))
