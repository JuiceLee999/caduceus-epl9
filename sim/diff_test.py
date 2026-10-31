#!/usr/bin/env python3
"""Differential test: same scene, two Color Profile settings (PA211063 Kodachrome vs PA211064 warm).

Compares per-hue chroma ratio cam63/cam64 against the model's sim63/sim64. Detail-free (downsampled).
"""
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline as P, calibrate as C

def hue_chroma(img):
    y = P.rgb_to_ycc(img); return np.degrees(np.arctan2(y[..., 2], y[..., 1])) % 360, np.hypot(y[..., 1], y[..., 2])

def run(engine, pairs):
    a, b = pairs['PA211063'], pairs['PA211064']
    small = (C.SIZE[0] // 4, C.SIZE[1] // 4)
    outs = {}
    for k, p in (('63', a), ('64', b)):
        base = P.apply_tone(p['lin'], P.ToneCurve.fit(p['lin'], p['tgt']))
        outs[k] = P.resize(engine.apply(base, P.ColorSettings(sat=p['exif']['sat'])), small)
    c63, c64 = P.resize(a['tgt'], small), P.resize(b['tgt'], small)
    h, ch64 = hue_chroma(c64); _, ch63 = hue_chroma(c63)
    _, s63 = hue_chroma(outs['63']); _, s64 = hue_chroma(outs['64'])
    rows = []
    for lo in range(0, 360, 30):
        m = (h >= lo) & (h < lo + 30) & (ch64 > 0.04)
        if m.sum() < 30: continue
        rows.append((lo, int(m.sum()), np.median(ch63[m] / ch64[m]), np.median(s63[m] / np.maximum(s64[m], 1e-4))))
    return rows

if __name__ == '__main__':
    pairs = {p['name'][:8]: p for p in C.load_pairs() if p['name'][:8] in ('PA211063', 'PA211064')}
    for label, eng in (('uncalibrated', P.ColorEngine()), ('calibrated', P.ColorEngine(angle_offset_deg=30, sat_scale=2.0, base_chroma=1.1)),
                       ('no sector effect', P.ColorEngine(sat_scale=0))):
        rows = run(eng, pairs)
        cam = np.array([r[2] for r in rows]); sim = np.array([r[3] for r in rows])
        print(f'== {label}: corr={np.corrcoef(cam, sim)[0,1]:.2f} mean|err|={np.mean(np.abs(cam-sim)):.3f}')
        for r in rows: print(f'  hue {r[0]:3d}-{r[0]+30:3d} n={r[1]:5d} cam63/64={r[2]:.3f} sim63/64={r[3]:.3f}')
