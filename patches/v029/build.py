#!/usr/bin/env python3
"""v0.29 = releases/v0.28 + button remapping (patches/omc_buttons) + XPan/21:9 AF and reboot fixes (patches/aspect_fix)
+ SCP aspect value icons (patches/aspect_scp) + right/down arrow rows (patches/btn_arrows). Offline.

  .venv/bin/python -I patches/v029/build.py releases/v0.28/edits.json --out generated/v029/edits.json
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
    for name, version in (('omc_buttons', '0.29'), ('aspect_fix', '0.29'), ('aspect_scp', '0.29'), ('btn_arrows', '0.29')):
        spec = _load(name, ROOT / f'patches/{name}/build.py').apply(spec, version=version)
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(apply(json.loads(a.spec.read_text())), indent=1))
