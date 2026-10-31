#!/usr/bin/env python3
"""Film-look effects for the desktop pipeline (halation, bloom, grain v2, film curve,
subtractive saturation, Color-Chrome-like density).

Background, parameter choices and the in-camera (ISP) mapping are in docs/FILM_LOOK.md.

Conventions
-----------
* ``lin``  : scene-linear RGB from ``pipeline.develop`` (camera WB, sRGB primaries).
             Sensor clip is 1.0; E-P7 JPEG mid-grey (sRGB 0.46) comes from lin ~0.07.
* ``img``  : display-referred, sRGB-encoded RGB in [0, 1].
* All spatial sizes are given as a **percentage of image width** (or, for grain, in
  full-resolution sensor pixels), so a 900 px preview and a 20 MP render match when
  viewed at the same size.

Only numpy (+ PIL for resampling) is used: no scipy.  Large Gaussian blurs are done on a
downsampled copy (the blur removes the detail anyway) with a 3-pass box filter, which is
O(N) regardless of radius.  At 5184x3888 a 1.5 %-width halation takes ~1 s.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

LUMA709 = np.array([0.2126, 0.7152, 0.0722], np.float32)


# ------------------------------------------------------------------ helpers
def _srgb_encode(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def _srgb_decode(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4)).astype(np.float32)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / max(e1 - e0, 1e-6), 0, 1)
    return t * t * (3 - 2 * t)


def _resize_plane(p: np.ndarray, size: tuple[int, int], resample) -> np.ndarray:
    return np.asarray(Image.fromarray(np.ascontiguousarray(p, np.float32), mode='F').resize(size, resample))


def _resize(img: np.ndarray, size: tuple[int, int], resample=Image.BILINEAR) -> np.ndarray:
    if img.ndim == 2:
        return _resize_plane(img, size, resample)
    return np.stack([_resize_plane(img[..., c], size, resample) for c in range(img.shape[2])], -1)


def _box_axis(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """Box filter of width 2r+1 along `axis`, edge-replicated, via cumulative sum."""
    if r < 1:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode='edge'), axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return ((hi - lo) / (2 * r + 1)).astype(np.float32)


def gaussian_blur(img: np.ndarray, sigma: float) -> np.ndarray:
    """Approximate Gaussian blur (3 box passes; downsample first when sigma is large).

    sigma in pixels of `img`.  Error vs a true Gaussian is < 3 % of peak, which is
    invisible for glow effects.  This is also what a camera would do: Olympus Art
    Filters blur a reduced-size copy and blend it back (docs/FILM_LOOK.md section 4).
    """
    if sigma < 0.3:
        return img
    h, w = img.shape[:2]
    f = max(1, int(sigma / 3))                      # keep >= 3 px of sigma after reduction
    small = img if f == 1 else _resize(img, (max(1, w // f), max(1, h // f)), Image.BOX)
    s = sigma / f
    r = max(1, int(round(np.sqrt(12 * s * s / 3 + 1) / 2 - 0.5)))  # 3 boxes of width 2r+1
    out = small
    for _ in range(3):
        out = _box_axis(_box_axis(out, r, 0), r, 1)
    return out if f == 1 else _resize(out, (w, h), Image.BILINEAR)


def multi_blur(img: np.ndarray, sigma: float, tail: float = 0.0) -> np.ndarray:
    """Gaussian core plus an optional long tail (sum of Gaussians at 2x and 4x sigma).

    Real scatter PSFs (diffusion filters, film halation, lens veiling glare) have much
    longer tails than a Gaussian; `tail` in 0..1 is the weight moved into the wide terms.
    """
    core = gaussian_blur(img, sigma)
    if tail <= 0:
        return core
    wide = 0.6 * gaussian_blur(img, 2 * sigma) + 0.4 * gaussian_blur(img, 4 * sigma)
    return (1 - tail) * core + tail * wide


def _highlight_source(lin: np.ndarray, threshold: float, knee: float, clip_boost: float) -> np.ndarray:
    """Energy that feeds a glow: pixels above `threshold`, which is given on the
    *display* (sRGB-encoded) luminance scale so 0.8 means 'brighter than ~sRGB 204'.

    Pixels near sensor clip are multiplied by `clip_boost` to stand in for the scene
    radiance the sensor could not record (a clipped sun is >> 1.0 in reality).
    """
    y = lin @ LUMA709
    t_lin = float(_srgb_decode(np.float32(threshold)))
    k_lin = float(_srgb_decode(np.float32(max(threshold - knee, 0))))
    m = smoothstep(k_lin, t_lin, y)
    boost = 1 + (clip_boost - 1) * smoothstep(0.85, 0.98, lin.max(-1))
    return lin * (m * boost)[..., None]


# ------------------------------------------------------------------ halation
def halation(lin: np.ndarray, strength: float = 0.4, threshold: float = 0.8, radius_pct: float = 1.0,
             tint=(1.0, 0.35, 0.1), knee: float = 0.25, tail: float = 0.4, clip_boost: float = 3.0,
             ring: float = 0.0) -> np.ndarray:
    """Film halation: light that passes through the emulsion, reflects off the back of the
    film base and re-exposes (mostly) the bottom, red-sensitive layer around highlights.

    strength   : glow added, as a fraction of the source energy (0.1 subtle .. 1.0 CineStill)
    threshold  : display-luma where the source starts (0.7..0.9)
    radius_pct : Gaussian sigma as % of image width. 35 mm: 0.13 mm base -> ~0.3..1.5 %.
    tint       : per-channel weight of the re-exposure (red layer closest to base)
    tail       : weight of the long-tail PSF terms
    ring       : 0..1 subtract a narrow core so the halo is ring-shaped (thick-base look)
    Additive in scene-linear exposure (before the tone curve), as on film.
    """
    src = _highlight_source(lin, threshold, knee, clip_boost)
    src_y = src @ LUMA709                              # halation re-exposes by luminance
    sigma = radius_pct / 100 * lin.shape[1]
    glow = multi_blur(src_y, sigma, tail)
    if ring > 0:
        glow = np.maximum(glow - ring * gaussian_blur(src_y, sigma * 0.35), 0)
    return lin + strength * glow[..., None] * np.asarray(tint, np.float32)


# ------------------------------------------------------------------ bloom / diffusion
def bloom(lin: np.ndarray, strength: float = 0.2, radius_pct: float = 1.5, threshold: float = 0.0,
          knee: float = 0.3, tail: float = 0.5, clip_boost: float = 2.0, tint=(1.0, 1.0, 1.0)) -> np.ndarray:
    """Energy-conserving scatter, as from a diffusion filter (Pro-Mist/Glimmerglass), lens
    veiling glare, or emulsion/print scatter.

    threshold == 0 : *mist* model, a fraction `strength` of ALL light goes into the wide PSF.
                     Lifts shadows near bright areas, lowers contrast (Black Pro-Mist 1/4
                     ~ strength 0.05..0.1, 1/2 ~ 0.15, 1 ~ 0.3).
    threshold  > 0 : *glow* model, only highlights scatter (like a digital bloom).
    out = lin - s*src + s*PSF*src, so total energy is preserved (no global brightening).
    """
    src = lin if threshold <= 0 else _highlight_source(lin, threshold, knee, 1.0)
    if clip_boost != 1:
        src = src * (1 + (clip_boost - 1) * smoothstep(0.85, 0.98, lin.max(-1)))[..., None]
    sigma = radius_pct / 100 * lin.shape[1]
    spread = multi_blur(src, sigma, tail) * np.asarray(tint, np.float32)
    return np.maximum(lin + strength * (spread - src), 0)


# ------------------------------------------------------------------ grain v2
FUJI_GRAIN = {  # (strength, size in full-res px) estimates for Fuji Grain Effect, see FILM_LOOK.md
    'weak_small': (0.25, 1.0), 'strong_small': (0.45, 1.0),
    'weak_large': (0.25, 2.2), 'strong_large': (0.45, 2.2),
}


def _grain_field(shape, cell: float, rng: np.random.Generator) -> np.ndarray:
    """Unit-variance band-limited noise with correlation length `cell` output pixels.
    cell < 1 (grain smaller than an output pixel, e.g. preview of a 20 MP image): white
    noise attenuated by `cell`, which is what averaging cell^-2 grains per pixel gives."""
    h, w = shape
    if cell <= 1:
        return rng.standard_normal((h, w), np.float32) * cell
    gh, gw = max(2, int(np.ceil(h / cell)) + 1), max(2, int(np.ceil(w / cell)) + 1)
    g = rng.standard_normal((gh, gw), np.float32)
    up = _resize_plane(g, (int(gw * cell), int(gh * cell)), Image.BICUBIC)[:h, :w]
    up = gaussian_blur(up, 0.35 * cell)
    return (up / (up.std() + 1e-6)).astype(np.float32)


def grain_v2(img: np.ndarray, strength: float = 0.3, size: float = 1.0, colour: float = 0.0,
             layer_size=(1.0, 1.0, 1.0), shadow: float = 1.0, highlight: float = 0.35, peak: float = 0.45,
             full_width: int = 5184, seed: int = 10, preset: str | None = None) -> np.ndarray:
    """Film-like grain on a display-referred sRGB image.

    strength : std of grain at the luminance peak in sRGB code values x 0.1
               (0.3 -> 3 % ~ 8/255 at full res; Fuji 'Strong' ~ 0.45)
    size     : grain correlation length in *full-resolution* pixels (1 small, 2..3 large)
    colour   : 0 mono (luminance) grain .. 1 fully independent per-channel (dye-cloud) grain
    layer_size: per-channel size multipliers (R,G,B); fast colour films have the coarsest
                grain in the blue-sensitive top layer, e.g. (1.0, 1.0, 1.4)
    shadow / highlight : relative amplitude at black / white vs the peak (density response)
    full_width: sensor width the size refers to; a preview gets the correctly averaged look.
    preset   : 'weak_small' | 'strong_small' | 'weak_large' | 'strong_large' (Fuji-like)
    """
    if preset:
        strength, size = FUJI_GRAIN[preset]
    h, w = img.shape[:2]
    k = w / full_width                         # output px per sensor px
    rng = np.random.default_rng(seed)
    y = img @ np.array([0.299, 0.587, 0.114], np.float32)
    # amplitude vs display luma: piecewise-smooth bump, `shadow` at 0, 1 at `peak`, `highlight` at 1
    a = np.where(y < peak, shadow + (1 - shadow) * smoothstep(0, peak, y),
                 1 + (highlight - 1) * smoothstep(peak, 1, y)).astype(np.float32)
    amp = 0.1 * strength * a
    mono = _grain_field((h, w), size * k, rng) if colour < 1 else 0
    out = img.copy()
    for c in range(3):
        n = mono
        if colour > 0:
            ind = _grain_field((h, w), size * layer_size[c] * k, rng)
            n = np.sqrt(1 - colour) * mono + np.sqrt(colour) * ind
        out[..., c] += amp * n
    return np.clip(out, 0, 1)


# ------------------------------------------------------------------ film curve
def _smin(a, b, k):
    k = max(k, 1e-3)
    return -k * np.logaddexp2(-a / k, -b / k)


def _smax(a, b, k):
    return -_smin(-a, -b, k)


def film_curve(lin: np.ndarray, slope=1.6, toe: float = 0.3, black=0.002, shoulder: float = 0.9,
               white=1.0, mid_in: float = 0.07, mid_out: float = 0.18, exposure: float = 0.0,
               per_channel: float = 0.5, clip_in: float = 1.0) -> np.ndarray:
    """Parametric characteristic curve in log-exposure, returns sRGB-encoded display RGB.

    With t = log2(x / mid_in) (stops from mid-grey) and d the output in stops from mid_out:
        d = smax( smin(slope*t, W, shoulder), B, toe )
    slope    : log-log contrast at mid-grey. Defaults (1.6, toe 0.3, shoulder 0.9, mid_in 0.07)
               fit the E-P7 base curve (sim/base_curve.json) to within 0.03. Eterna-like ~1.2
    shoulder : softness of highlight roll-off in stops (0.2 hard clip .. 1.5 very soft)
    toe      : softness of the shadow knee in stops
    black    : output floor (display linear). 0.002 = deep; 0.01..0.02 = faded/matte print
    white    : output asymptote; W is solved so the sensor clip (`clip_in`) lands exactly on
               `white`, i.e. the shoulder rolls off without grey whites
    per_channel: 0 = curve applied to luminance (hue/sat preserving), 1 = applied to each of
               R,G,B like three dye layers (highlights desaturate, mids saturate). Film ~0.5..1
    slope/black/white accept [r,g,b] lists -> crossover (e.g. green-cyan shadows, warm highs)
    In-camera: a per-channel 1-D LUT ("RGB gamma") + a luminance LUT.
    """
    lin = np.maximum(lin, 0) * 2.0 ** exposure
    slope, black, white = (np.broadcast_to(np.asarray(v, np.float32), (3,)) for v in (slope, black, white))

    def curve(x, c):
        t = np.log2(np.maximum(x, 1e-6) / mid_in)
        dw = np.log2(white[c] / mid_out)
        t1 = slope[c] * np.log2(clip_in * 2.0 ** exposure / mid_in)
        if t1 > dw + 0.05:   # anchor: clip -> white
            W = -shoulder * np.log2(max(2 ** (-dw / shoulder) - 2 ** (-t1 / shoulder), 1e-12))
        else:
            W = dw
        d = _smin(slope[c] * t, W, shoulder)
        d = _smax(d, np.log2(max(black[c], 1e-5) / mid_out), toe)
        return mid_out * 2.0 ** d

    out_pc = np.stack([curve(lin[..., c], c) for c in range(3)], -1)
    if per_channel < 1:
        y = lin @ LUMA709
        yo = np.stack([curve(y, c) for c in range(3)], -1)     # per-channel params, luminance input
        out_l = lin * (yo / np.maximum(y, 1e-6)[..., None])
        out = per_channel * out_pc + (1 - per_channel) * out_l
    else:
        out = out_pc
    return _srgb_encode(out)


# ------------------------------------------------------------------ colour density
def subtractive_saturation(lin: np.ndarray, amount: float = 0.3, density: float = 0.0) -> np.ndarray:
    """Dye-like saturation: raise saturation by adding density to the *non-dominant*
    channels, so saturated colours get darker instead of brighter (unlike a YCbCr chroma
    gain, which brightens/clips them).

    rgb' = max * (rgb / max) ** (1 + amount)          (dominant channel kept)
    then  rgb' *= 1 - density * s ** 1.5              (extra darkening by HSV saturation)
    amount 0.2..0.5, density 0..0.25.  Neutrals are untouched.
    """
    mx = lin.max(-1, keepdims=True)
    ratio = np.clip(lin / np.maximum(mx, 1e-6), 0, 1)
    out = mx * ratio ** (1 + amount)
    if density:
        s = 1 - ratio.min(-1, keepdims=True)
        out = out * (1 - density * s ** 1.5)
    return out


def _hsv_hue_sat(lin):
    mx, mn = lin.max(-1), lin.min(-1)
    c = mx - mn
    r, g, b = lin[..., 0], lin[..., 1], lin[..., 2]
    cs = np.maximum(c, 1e-6)
    h = np.where(mx == r, ((g - b) / cs) % 6, np.where(mx == g, (b - r) / cs + 2, (r - g) / cs + 4)) * 60
    s = c / np.maximum(mx, 1e-6)
    return h, s


def _hue_bump(h, centre, half_width):
    d = (h - centre + 180) % 360 - 180
    return np.clip(np.cos(np.clip(d / half_width, -1, 1) * np.pi / 2), 0, 1)


CCE_LEVEL = {'off': 0.0, 'weak': 0.5, 'strong': 1.0}


def color_chrome(lin: np.ndarray, effect='strong', fx_blue='off', max_darken: float = 0.30,
                 sat_lo: float = 0.35, sat_hi: float = 0.85) -> np.ndarray:
    """Fuji Color Chrome Effect / FX Blue model: darken highly saturated colours.

    Per pixel, gain = 1 - max_darken * level * w_sat * w_hue * w_lum, applied equally to
    R,G,B (hue and HSV saturation preserved, lightness reduced -> 'deeper' colour that
    keeps gradation instead of clipping).
      w_sat : smoothstep(sat_lo, sat_hi, HSV saturation in linear RGB)
      w_hue : CCE  - reds/oranges/yellows/greens 1.0, magentas 0.6, blues/cyans 0.25
              FX Blue - cosine bump at 225 deg (+-55) for sky blues
      w_lum : 0.5 + 0.5*luma^0.5, stronger in bright saturated areas where clipping bites
    max_darken 0.30 at 'strong' ~ -0.5 EV ~ -8 L* on a saturated red (our estimate; Fuji
    publishes no numbers). effect / fx_blue: 'off'|'weak'|'strong' or a float 0..1.
    """
    lv = lambda v: CCE_LEVEL[v] if isinstance(v, str) else float(v)
    e, b = lv(effect), lv(fx_blue)
    if not e and not b:
        return lin
    h, s = _hsv_hue_sat(lin)
    ws = smoothstep(sat_lo, sat_hi, s)
    wl = 0.5 + 0.5 * np.sqrt(np.clip(lin @ LUMA709, 0, 1))
    w_cce = np.maximum.reduce([_hue_bump(h, 30, 110), 0.6 * _hue_bump(h, 320, 50), np.full_like(h, 0.25)])
    w_blue = _hue_bump(h, 225, 55)
    d = max_darken * ws * wl * (e * w_cce + b * w_blue)
    return lin * np.clip(1 - d, 0.3, 1)[..., None]


# ------------------------------------------------------------------ registry for recipes
def _kw(spec, allowed):
    return {k: v for k, v in spec.items() if k in allowed}


HALATION_KEYS = {'strength', 'threshold', 'radius_pct', 'tint', 'knee', 'tail', 'clip_boost', 'ring'}
BLOOM_KEYS = {'strength', 'radius_pct', 'threshold', 'knee', 'tail', 'clip_boost', 'tint'}
GRAIN_KEYS = {'strength', 'size', 'colour', 'layer_size', 'shadow', 'highlight', 'peak', 'full_width',
              'seed', 'preset'}
CURVE_KEYS = {'slope', 'toe', 'black', 'shoulder', 'white', 'mid_in', 'mid_out', 'exposure', 'per_channel',
              'clip_in'}
SUBSAT_KEYS = {'amount', 'density'}
CCE_KEYS = {'effect', 'fx_blue', 'max_darken', 'sat_lo', 'sat_hi'}
