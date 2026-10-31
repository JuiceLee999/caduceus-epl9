#!/usr/bin/env python3
"""Film-simulation recipes on the E-P7 desktop pipeline.

A recipe uses ONLY controls the camera has (stock) or that the planned
firmware adds (per-sector hue/lightness, +/-7 saturation, colour grain,
vignette), so a preview here is a fair stand-in for in-camera output.

Recipe JSON keys (all optional):
  sat[12], hue[12], light[12]   -7..7, sector order = pipeline.SECTORS
  tone {highlights, shadows, midtones}  -7..7   (stock tone levels)
  contrast   -5..5            wb_shift {a_b, g_m}  -7..7 (A+ warmer, G+ greener)
  grain      off/low/medium/high      vignette  -5..5 (negative darkens corners)
  base_saturation  -5..5      notes

Usage:
  .venv/bin/python -I sim/film.py --recipes sim/recipes/fuji_like.json \
      --images testdata/PA211064.ORF testdata/PA221247.ORF --out generated/film
"""
import argparse, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline as P  # noqa: E402

# ---- uncalibrated stock-control models (documented guesses; refine with test shots)
TONE_STEP = 0.010      # gamma-luma shift per tone-level step at the band peak
CONTRAST_STEP = 0.035  # S-curve strength per contrast step
WB_STEP = 0.015        # channel gain per WB fine-tune step
SAT_STEP = 0.06        # global chroma per saturation step


def neutral_curve():
    """Camera base curve: median of curves fitted to 12 E-P7 JPEGs (sim/base_curve.json)."""
    f = Path(__file__).resolve().parent / 'base_curve.json'
    if f.exists():
        j = json.loads(f.read_text())
        return P.ToneCurve(np.array(j['xs']), np.array(j['ys']))
    return _fallback_curve()


def _fallback_curve():
    """Default display tone curve for previews when no camera JPEG is available:
    sRGB gamma + mild filmic shoulder (stand-in for Olympus 'Normal' gradation)."""
    xs = np.linspace(0, 1, 257) ** 2.2 * 1.6
    ys = P.srgb_encode(np.clip(xs, 0, None) / (1 + 0.12 * xs))
    ys = ys / ys[-1]
    return P.ToneCurve(xs, np.maximum.accumulate(ys))


def tone_levels(y, hl=0, sh=0, mid=0, contrast=0):
    """Apply stock-style tone controls to gamma-luma y in [0,1]."""
    band_h = np.clip((y - 0.55) / 0.45, 0, 1) ** 1.5
    band_s = np.clip((0.45 - y) / 0.45, 0, 1) ** 1.5
    band_m = np.exp(-((y - 0.5) / 0.2) ** 2)
    y = y + TONE_STEP * (hl * band_h * 2.2 + sh * band_s * 2.2 + mid * band_m * 1.5)
    if contrast:
        k = CONTRAST_STEP * contrast
        y = y + 0.5 * k * np.sin(2 * np.pi * (y - 0.5))  # S-curve: darker shadows, brighter highlights
    return np.clip(y, 0, 1)


def render(lin, recipe, curve=None, seed=10):
    r = recipe
    lin = lin.copy()
    wb = r.get('wb_shift', {})
    ab, gm = wb.get('a_b', 0), wb.get('g_m', 0)
    lin[..., 0] *= 1 + WB_STEP * ab
    lin[..., 2] *= 1 - WB_STEP * ab
    lin[..., 1] *= 1 + WB_STEP * gm
    img = P.apply_tone(lin, curve or neutral_curve())
    ycc = P.rgb_to_ycc(img)
    t = r.get('tone', {})
    y_new = tone_levels(ycc[..., 0], t.get('highlights', 0), t.get('shadows', 0), t.get('midtones', 0),
                        r.get('contrast', 0))
    ratio = np.where(ycc[..., 0] > 1e-3, y_new / np.maximum(ycc[..., 0], 1e-3), 1)
    ycc[..., 0] = y_new
    ycc[..., 1:] *= np.clip(ratio, 0.5, 1.5)[..., None] ** 0.5 * (1 + SAT_STEP * r.get('base_saturation', 0))
    img = np.clip(P.ycc_to_rgb(ycc), 0, 1)
    eng = P.ColorEngine()
    img = eng.apply(img, P.ColorSettings(sat=r.get('sat', [0] * 12), hue=r.get('hue', [0] * 12),
                                         light=r.get('light', [0] * 12)))
    v = r.get('vignette', 0)
    if v:
        h, w = img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        d = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)) / np.sqrt(2)
        img = np.clip(img * (1 + 0.08 * v * d[..., None] ** 2), 0, 1)
    g = r.get('grain', 'off')
    if g and g != 'off':
        img = P.grain(img, g, seed=seed, colour=True)
    return img


def label(img, text):
    from PIL import Image, ImageDraw
    im = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 8 + 7 * len(text), 18], fill=(0, 0, 0))
    d.text((4, 3), text, fill=(255, 255, 255))
    return np.asarray(im, np.float32) / 255


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--recipes', type=Path, required=True)
    ap.add_argument('--images', type=Path, nargs='+', required=True)
    ap.add_argument('--out', type=Path, default=P.ROOT / 'generated/film')
    ap.add_argument('--width', type=int, default=900)
    a = ap.parse_args()
    recipes = json.loads(a.recipes.read_text())
    if isinstance(recipes, dict) and 'recipes' in recipes:
        recipes = recipes['recipes']
    if isinstance(recipes, dict):
        recipes = [dict(name=k, **v) for k, v in recipes.items()]
    for img_path in a.images:
        lin = P.develop(img_path, orient=True)
        h, w = lin.shape[:2]
        lin = P.resize(lin, (a.width, int(a.width * h / w)))
        tiles = [label(render(lin, {}), 'E-P7 neutral (sim)')]
        for rc in recipes:
            out = render(lin, rc)
            P.save(out, a.out / img_path.stem / f"{rc['name'].replace(' ', '_').replace('/', '-')}.jpg")
            tiles.append(label(out, rc['name']))
        cols = 3
        while len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.concatenate([np.concatenate(tiles[i:i + cols], 1) for i in range(0, len(tiles), cols)], 0)
        P.save(sheet, a.out / f'{img_path.stem}_contact.jpg', quality=88)
        print('wrote', a.out / f'{img_path.stem}_contact.jpg')


if __name__ == '__main__':
    main()
