#!/usr/bin/env python3
"""v0.27 = releases/v0.26 + film grain on COLOR stills (Extras sector 1, slot +50) + NR moved to Extras sector 9. Offline.

  .venv/bin/python -I patches/v027/build.py releases/v0.26/edits.json --out generated/grain_cpu/r1/edits.json
  .venv/bin/python -I tools/build_package.py generated/grain_cpu/r1/edits.json --out generated/grain_cpu/r1/pkg
  .venv/bin/python -I patches/v027/verify.py releases/v0.26/edits.json generated/grain_cpu/r1/edits.json generated/grain_cpu/r1/pkg

The layer is patches/grain_cpu/build_r1.py (source gr1.s.in, model model_r1.py); this file adds the version label. docs/GRAIN_PORT.md.
"""
import argparse, importlib.util, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def apply(spec, version='0.27'):
    return _load('grain_r1', ROOT / 'patches/grain_cpu/build_r1.py').apply(spec, version)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(apply(json.loads(a.spec.read_text())), indent=1))
