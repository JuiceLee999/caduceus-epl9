#!/usr/bin/env python3
"""v0.19 release spec (offline): v0.18 + patches/tone_ends + SD loader accepts Blacks/Whites + fw label 0.19.

  .venv/bin/python -I patches/v019/build.py [--base releases/v0.18/edits.json] --out releases/v0.19/edits.json

1. patches/tone_ends (per-COLOR-slot Blacks +47 / Whites +48 on the luminance tone LUT, docs/TONE_ENDS.md).
2. SD loader v3 (edit at 0x605b7400): data only. Its per-byte range table (sd_lo[64] + sd_span[64]) is swapped
   from the released rule (bytes 47..63 must be 0) to range_table(tone=True): +47/+48 accept -5..5 in every slot.
   The MONO-zero rule (patches/sd_bundles table_ok(tone=True)) is enforced by the desktop tools only; on the
   camera a MONO slot's +47/+48 is never read (the tone hook reads COLOR slots 0..3 only). Code bytes, sd_back
   and every label stay byte-identical (checked).
3. patches/fw_version --mod-version v0.19 (replaces the 0.18 label edits).
"""
import argparse, importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


TE = _load('ep7_tone_ends_build', ROOT / 'patches/tone_ends/build.py')
SB = _load('ep7_sd_bundles_build', ROOT / 'patches/sd_bundles/build.py')
FW = _load('ep7_fw_version_build', ROOT / 'patches/fw_version/build.py')
LOADER_AT, SD_BACK, SD_BACK_JMP = 0x605b7400, 0x605b7420, 'dc20ffffff'


def b8(v):
    return bytes(x & 0xff for x in v)


def loader_swap(spec):
    lay = SB.layout()
    lo0, sp0, _ = SB.range_table(lay)
    lo1, sp1, _ = SB.range_table(lay, tone=True)
    hits = [e for e in spec['edits'] if e['kind'] == '0x100' and int(e['addr'], 16) == LOADER_AT]
    if len(hits) != 1:
        raise ValueError('loader edit not found once')
    e = hits[0]
    blob = bytes.fromhex(e['new'])
    old, new = b8(lo0) + b8(sp0), b8(lo1) + b8(sp1)
    if blob.count(old) != 1:
        raise ValueError(f'loader range table found {blob.count(old)} times (want 1)')
    i = blob.index(old)
    blob2 = blob[:i] + new + blob[i + len(old):]
    o = SD_BACK - LOADER_AT
    if blob2[o:o + 5].hex() != SD_BACK_JMP:
        raise ValueError('loader sd_back is not jmp ed_trig')
    diff = [k for k in range(len(blob)) if blob[k] != blob2[k]]
    if not diff or min(diff) < i or max(diff) >= i + len(old):
        raise ValueError('loader change outside the range table')
    e['new'] = blob2.hex()
    e['why'] += ' [v0.19: slot +47 blacks / +48 whites accept -5..5]'
    return dict(table_at=hex(LOADER_AT + i), changed=[hex(LOADER_AT + k) for k in diff])


def make(base_path):
    _, merged, *_ = TE.make_spec(base_path)
    lr = loader_swap(merged)
    FW.apply(merged, 'v0.19')
    merged['v019'] = dict(loader_ranges=lr, built_by='patches/v019/build.py', base=str(base_path))
    return merged


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', type=Path, default=ROOT / 'releases/v0.18/edits.json')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = make(a.base)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1) + '\n')
    print(f'{len(spec["edits"])} edits -> {a.out}; loader range table at {spec["v019"]["loader_ranges"]["table_at"]}, '
          f'changed {spec["v019"]["loader_ranges"]["changed"]}')


if __name__ == '__main__':
    main()
