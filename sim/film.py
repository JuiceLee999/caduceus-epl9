#!/usr/bin/env python3
"""Film-simulation recipes on the E-P7 desktop pipeline.

A recipe uses ONLY controls the camera has (stock) or that the planned
firmware adds (per-sector hue/lightness, +/-7 saturation, colour grain,
vignette), so a preview here is a fair stand-in for in-camera output.

Recipe JSON keys (all optional):
  sat[12], hue[12], light[12]   -7..7, sector order = pipeline.SECTORS
  tone {highlights, shadows, midtones}  -7..7   (stock tone levels; camera LUT model, tools/ep7_tone_model.py)
       {blacks, whites}  -5..5   (v0.19 end points, tools/ep7_tone.py)  "_tone_model": "legacy" = old guess
  contrast   -5..5            wb_shift {a_b, g_m}  -7..7 (A+ warmer, G+ greener)
  grain      off/low/medium/high      vignette  -5..5 (negative darkens corners)
  base_saturation  -5..5      notes

Optional film-look keys (sim/effects.py, docs/FILM_LOOK.md). Absent = old behaviour.
Each is a dict of keyword arguments; "enabled": false skips it. Stage order:
  WB -> bloom -> halation -> subtractive_saturation -> color_chrome   (scene-linear)
     -> film_curve (replaces the camera base curve) -> tone levels -> HSL -> mono
     -> vignette -> grain_v2 (replaces "grain")
  e.g. "halation": {"strength": 0.4, "threshold": 0.8, "radius_pct": 1.5, "tint": [1, 0.35, 0.1]}

Usage:
  .venv/bin/python -I sim/film.py --recipes sim/recipes/fuji_like.json \
      --images testdata/PA211064.ORF testdata/PA221247.ORF --out generated/film
"""
import argparse, json, sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline as P  # noqa: E402
import effects as FX  # noqa: E402
sys.path.insert(0, str(P.ROOT / 'tools'))
try:
    import ep7_tone_model as TM  # noqa: E402  (bit-exact camera H/S/M LUT + Blacks/Whites)
except Exception:               # pragma: no cover  (data file missing): fall back to the legacy guess
    TM = None

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


_TONE_CACHE = {}


def camera_tone(y, t):
    """Camera tone control on display luma y in [0,1]: the contrast-0 LUT bent by H/S/M (tools/ep7_tone_model.py,
    bit-exact with the firmware) then the Blacks/Whites remap, applied as a map base LUT -> toned LUT
    (luminance only, display domain, after the base curve; zero tone = identity)."""
    key = tuple(int(t.get(f, 0)) for f in ('highlights', 'shadows', 'midtones', 'blacks', 'whites'))
    if not any(key):
        return y
    if key not in _TONE_CACHE:
        _TONE_CACHE[key] = (np.array(TM.base_lut(), np.float32) / 1023, np.array(TM.tone_lut(*key), np.float32) / 1023)
    xs, ys = _TONE_CACHE[key]
    return np.interp(y, xs, ys).astype(y.dtype)


# Monochrome Profile colour filters as luminance channel weights on gamma RGB (approximation;
# strength 1..3 blends from neutral toward the full filter).
MONO_FILTERS = {'none': (0.299, 0.587, 0.114), 'yellow': (0.42, 0.53, 0.05), 'orange': (0.52, 0.44, 0.04),
                'red': (0.65, 0.32, 0.03), 'green': (0.22, 0.70, 0.08), 'blue': (0.18, 0.47, 0.35)}


def monochrome(img, colour='none', strength=1):
    n, f = np.array(MONO_FILTERS['none']), np.array(MONO_FILTERS.get(colour, MONO_FILTERS['none']))
    wts = n + (f - n) * min(max(strength, 0), 3) / 3
    y = img @ (wts / wts.sum())
    return np.repeat(y[..., None], 3, -1)


def _fx(r, key):
    """Optional film-look stage spec: dict of kwargs, or None if absent/disabled."""
    v = r.get(key)
    if v is None or v is False or (isinstance(v, dict) and v.get('enabled', True) is False):
        return None
    return v if isinstance(v, dict) else {}


def render(lin, recipe, curve=None, seed=10, full_width=5184):
    r = recipe
    lin = lin.copy()
    wb = r.get('wb_shift', {})
    ab, gm = wb.get('a_b', 0), wb.get('g_m', 0)
    lin[..., 0] *= 1 + WB_STEP * ab
    lin[..., 2] *= 1 - WB_STEP * ab
    lin[..., 1] *= 1 + WB_STEP * gm
    if (s := _fx(r, 'bloom')) is not None:
        lin = FX.bloom(lin, **FX._kw(s, FX.BLOOM_KEYS))
    if (s := _fx(r, 'halation')) is not None:
        lin = FX.halation(lin, **FX._kw(s, FX.HALATION_KEYS))
    if (s := _fx(r, 'subtractive_saturation')) is not None:
        lin = FX.subtractive_saturation(lin, **FX._kw(s, FX.SUBSAT_KEYS))
    if (s := _fx(r, 'color_chrome')) is not None:
        lin = FX.color_chrome(lin, **FX._kw(s, FX.CCE_KEYS))
    if (s := _fx(r, 'film_curve')) is not None:
        img = FX.film_curve(lin, **FX._kw(s, FX.CURVE_KEYS))
    else:
        img = P.apply_tone(lin, curve or neutral_curve())
    ycc = P.rgb_to_ycc(img)
    t = r.get('tone') or {}
    if TM is not None and r.get('_tone_model') != 'legacy':
        y_new = camera_tone(tone_levels(ycc[..., 0], contrast=r.get('contrast', 0)), t)
    else:
        y_new = tone_levels(ycc[..., 0], t.get('highlights', 0), t.get('shadows', 0), t.get('midtones', 0),
                            r.get('contrast', 0))
    ratio = np.where(ycc[..., 0] > 1e-3, y_new / np.maximum(ycc[..., 0], 1e-3), 1)
    ycc[..., 0] = y_new
    ycc[..., 1:] *= np.clip(ratio, 0.5, 1.5)[..., None] ** 0.5 * (1 + SAT_STEP * r.get('base_saturation', 0))
    img = np.clip(P.ycc_to_rgb(ycc), 0, 1)
    eng = P.ColorEngine(hue_deg_per_1000=r.get('_hue_deg_per_1000', P.HUE_DEG_PER_STEP))   # preview-only override
    img = eng.apply(img, P.ColorSettings(sat=r.get('sat', [0] * 12), hue=r.get('hue', [0] * 12),
                                         light=r.get('light', [0] * 12)))
    mono = r.get('mono_filter') or str(r.get('base', '')).lower().startswith('monochrome')
    if mono:
        img = monochrome(img, (r.get('mono_filter') or {}).get('colour', 'none'),
                         (r.get('mono_filter') or {}).get('strength', 1))
    v = r.get('vignette', 0)
    if v:
        h, w = img.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w]
        d = np.hypot((xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)) / np.sqrt(2)
        img = np.clip(img * (1 + 0.08 * v * d[..., None] ** 2), 0, 1)
    if (s := _fx(r, 'grain_v2')) is not None:
        kw = dict(seed=seed, full_width=full_width, colour=0.0 if mono else 0.3)
        kw.update(FX._kw(s, FX.GRAIN_KEYS))
        if mono:
            kw['colour'] = 0.0
        return FX.grain_v2(img, **kw)
    g = r.get('grain', 'off')
    if g and g != 'off':
        img = P.grain(img, g, seed=seed, colour=not mono)
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
        full_w = 2 * w                    # develop() is half-size; effects scale to the sensor
        lin = P.resize(lin, (a.width, int(a.width * h / w)))
        tiles = [label(render(lin, {}), 'E-P7 neutral (sim)')]
        for rc in recipes:
            out = render(lin, rc, full_width=full_w)
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
