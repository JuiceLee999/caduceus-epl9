#!/usr/bin/env python3
"""v0.29a = v0.29 + Film-first page order and the Film page saturation polygon (patches/page_order). Offline.

  .venv/bin/python -I patches/v029a/build.py releases/v0.28/edits.json --out generated/v029a/edits.json
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
    spec = _load('v029', ROOT / 'patches/v029/build.py').apply(spec)
    po = _load('page_order', ROOT / 'patches/page_order/build.py')
    return po.apply_film_poly(po.apply(spec, '0.29a'), '0.29a')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(apply(json.loads(a.spec.read_text())), indent=1))
