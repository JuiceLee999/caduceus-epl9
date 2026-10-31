#!/usr/bin/env python3
"""Calibrate/validate sim/pipeline.py against camera JPEGs (testdata/).

For each ORF+JPEG pair: develop the ORF, fit the tone curve to the JPEG,
apply the colour engine with the shot's EXIF Color Profile sliders, and
report median CIE76 dE vs the camera JPEG. Then grid-search the two unknown
engine parameters (chroma-plane angle offset, saturation scale).

Usage: .venv/bin/python -I sim/calibrate.py [--search]
"""
import argparse, glob, json, re, subprocess, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline as P  # noqa: E402

ROOT = P.ROOT
EXIFTOOL = Path.home() / 'ep7fw-toolchains/src/exiftool/exiftool'
SIZE = (648, 486)
OUT = ROOT / 'generated/calibration'


def exif(jpg):
    j = json.loads(subprocess.check_output([str(EXIFTOOL), '-j', '-PictureMode', '-ColorProfileSettings',
                                            '-ToneLevel', '-ContrastSetting', str(jpg)]))[0]
    sat = [0] * 12
    m = re.findall(r'(-?\d+)', j.get('ColorProfileSettings', ''))
    if len(m) >= 14:
        sat = [int(x) for x in m[2:14]]
    return dict(mode=j.get('PictureMode', ''), sat=sat, tone=j.get('ToneLevel', ''),
                contrast=j.get('ContrastSetting', ''))


def load_pairs():
    pairs = []
    for orf in sorted(glob.glob(str(ROOT / 'testdata/*.ORF'))):
        stem = Path(orf).stem
        jpg = [p for p in glob.glob(str(ROOT / f'testdata/{stem}*.JPG'))][0]
        lin = P.resize(P.develop(Path(orf)), SIZE)
        tgt = P.load_jpeg(Path(jpg), SIZE)
        pairs.append(dict(name=Path(jpg).stem, lin=lin, tgt=tgt, exif=exif(jpg)))
    return pairs


def score(pair, engine, use_colour=True):
    if 'base' not in pair:
        pair['base'] = P.apply_tone(pair['lin'], P.ToneCurve.fit(pair['lin'], pair['tgt']))
    base = pair['base']
    out = engine.apply(base, P.ColorSettings(sat=pair['exif']['sat'])) if use_colour else base
    # colour-only metric: compare 8x-downsampled images (removes detail/sharpening/alignment)
    small = (SIZE[0] // 8, SIZE[1] // 8)
    de = P.delta_e76(P.resize(out, small), P.resize(pair['tgt'], small))
    return float(np.median(de)), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--search', action='store_true')
    a = ap.parse_args()
    pairs = load_pairs()
    eng = P.ColorEngine()
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{'shot':48s} {'mode':18s} dE(tone only) dE(+colour)")
    for p in pairs:
        d0, _ = score(p, eng, False)
        d1, out = score(p, eng, True)
        P.save(np.concatenate([out, p['tgt']], 1), OUT / f"{p['name'][:8]}_sim_vs_cam.jpg")
        print(f"{p['name'][:48]:48s} {p['exif']['mode'][:18]:18s} {d0:6.2f}       {d1:6.2f}")
    if a.search:
        cp = [p for p in pairs if any(p['exif']['sat'])]
        best = None
        for bc in (1.0, 1.1, 1.2, 1.3, 1.4):
            for off in range(-60, 61, 15):
                for sc in (0.0, 1.0, 2.0, 3.0, 4.0, 6.0):
                    e = P.ColorEngine(angle_offset_deg=off, sat_scale=sc, base_chroma=bc)
                    m = float(np.mean([score(p, e)[0] for p in cp]))
                    if best is None or m < best[0]:
                        best = (m, off, sc, bc)
        print('best mean dE %.3f at angle_offset=%d sat_scale=%.1f base_chroma=%.1f' % best)
        nat = [p for p in pairs if 'Natural' in p['exif']['mode']]
        for bc in (1.0, 1.1, 1.2, 1.3):
            print('Natural shot base_chroma %.1f dE %.3f' % (bc, score(nat[0], P.ColorEngine(base_chroma=bc))[0]))


if __name__ == '__main__':
    main()
