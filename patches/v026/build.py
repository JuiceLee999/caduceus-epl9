#!/usr/bin/env python3
"""v0.26 = releases/v0.25 + vertical video rotation + movie colour mode. Offline.

  .venv/bin/python -I patches/v026/build.py releases/v0.25/edits.json --out generated/v026/wheel/edits.json
  .venv/bin/python -I patches/v026/build.py releases/v0.25/edits.json --no-wheel --out generated/v026/nowheel/edits.json
"""
import argparse, importlib.util, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def apply(spec, wheel=True):
    spec = _load('v026_rot', ROOT / 'patches/v026_rot/build.py').apply(spec)
    return _load('v026_movie', ROOT / 'patches/v026_movie/build.py').apply(spec, wheel=wheel)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--no-wheel', action='store_true')
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(apply(json.loads(a.spec.read_text()), not a.no_wheel), indent=1))
