#!/usr/bin/env python3
"""Desktop model of the E-P7 colour pipeline (ORF -> JPEG-like render).

This is an approximation for previewing and testing colour features, not a
bit-exact ISP emulation. Stages:

  1. develop(): LibRaw demosaic, camera WB, camera->linear sRGB (half size).
  2. tone: a 1-D luminance curve (gradation / contrast / tone levels).
  3. colour_profile(): 12-sector chroma engine using the *firmware's* own
     sector angles, widths and saturation gains (tools/ep7_color_table.py).
     Optional H/L per sector = the planned HSL extension.
  4. grain(): the Olympus xorshift32 luminance grain (fishcu GRAIN.md).
  5. crop(): extra aspect ratios (XPan 65:24, 21:9, ...).

All images are float32 arrays in [0,1], HxWx3.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
TABLE_JSON = ROOT / 'generated/color/ep7_color_table.json'

# Sector names in EXIF / wheel order (UI index 0..11).
SECTORS = ['yellow', 'orange', 'orange-red', 'red', 'magenta', 'violet',
           'blue', 'blue-cyan', 'cyan', 'green-cyan', 'green', 'yellow-green']

# Hue step: fishcu H_native = -1000*slider; if 32768 == 360 deg that is 11 deg/step.
# Direction and true scale unverified on camera -> use half (5.5 deg/step) for previews.
HUE_DEG_PER_STEP = 5.5

# Raw is 5200x3904, camera JPEG 5184x3888: assume a centred 8 px border.
RAW_BORDER = 8


# ---------------------------------------------------------------- stage 1
def develop(orf: Path, half: bool = True, orient: bool = False) -> np.ndarray:
    """Linear sRGB render with camera WB, no auto-brightening.

    orient=False keeps sensor orientation (matches camera JPEG pixel data, used
    for calibration); orient=True applies the EXIF/LibRaw flip for previews.
    """
    with rawpy.imread(str(orf)) as r:
        flip = r.sizes.flip
        rgb = r.postprocess(use_camera_wb=True, output_color=rawpy.ColorSpace.sRGB,
                            gamma=(1, 1), no_auto_bright=True, output_bps=16,
                            half_size=half, user_flip=0)
    b = RAW_BORDER // 2 if half else RAW_BORDER
    rgb = rgb[b:-b, b:-b]
    if orient:
        rgb = {3: np.rot90(rgb, 2), 5: np.rot90(rgb, 1), 6: np.rot90(rgb, -1)}.get(flip, rgb)
    return np.ascontiguousarray(rgb).astype(np.float32) / 65535.0


def load_jpeg(path: Path, size: tuple[int, int] | None = None) -> np.ndarray:
    im = Image.open(path)  # pixel data unrotated; ORF also unrotated (user_flip=0)
    if size:
        im = im.resize(size, Image.BILINEAR)
    return np.asarray(im, dtype=np.float32) / 255.0


def resize(img: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    out = np.empty((size[1], size[0], 3), np.float32)
    for c in range(3):
        out[..., c] = np.asarray(Image.fromarray(img[..., c]).resize(size, Image.BILINEAR))
    return out


# ---------------------------------------------------------------- colour maths
def srgb_encode(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def srgb_decode(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.04045, x / 12.92, np.power((x + 0.055) / 1.055, 2.4))


def rgb_to_ycc(rgb):  # BT.601 full range, on gamma-encoded values (as JPEG)
    m = np.array([[0.299, 0.587, 0.114], [-0.168736, -0.331264, 0.5], [0.5, -0.418688, -0.081312]], np.float32)
    return rgb @ m.T


def ycc_to_rgb(ycc):
    m = np.array([[1, 0, 1.402], [1, -0.344136, -0.714136], [1, 1.772, 0]], np.float32)
    return ycc @ m.T


def _lab_f(t):
    return np.where(t > (6 / 29) ** 3, np.cbrt(t), t / (3 * (6 / 29) ** 2) + 4 / 29)


def srgb_to_lab(rgb_gamma):
    lin = srgb_decode(rgb_gamma)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]], np.float32)
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883], np.float32)
    f = _lab_f(xyz)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def delta_e76(a_gamma, b_gamma):
    return np.linalg.norm(srgb_to_lab(a_gamma) - srgb_to_lab(b_gamma), axis=-1)


# ---------------------------------------------------------------- stage 2: tone
@dataclass
class ToneCurve:
    """Monotone 1-D curve on luma: input linear luma -> output gamma luma."""
    xs: np.ndarray
    ys: np.ndarray

    def __call__(self, y):
        return np.interp(y, self.xs, self.ys)

    @staticmethod
    def fit(sim_linear: np.ndarray, target_gamma: np.ndarray, n: int = 64) -> 'ToneCurve':
        """Histogram-matching fit (robust to small misalignment)."""
        ys_in = (sim_linear @ np.array([0.2126, 0.7152, 0.0722], np.float32)).ravel()
        ys_out = rgb_to_ycc(target_gamma)[..., 0].ravel()
        q = np.linspace(0.0005, 0.9995, n)
        xs = np.quantile(ys_in, q)
        ys = np.quantile(ys_out, q)
        xs = np.concatenate([[0], xs, [max(1.0, xs[-1] * 1.01)]])
        ys = np.concatenate([[0], np.maximum.accumulate(ys), [1.0]])
        return ToneCurve(xs, ys)

    def to_json(self):
        return dict(xs=self.xs.tolist(), ys=self.ys.tolist())


def apply_tone(linear: np.ndarray, curve: ToneCurve) -> np.ndarray:
    """Map luma through the curve, keep chroma ratios (gamma-domain output)."""
    w = np.array([0.2126, 0.7152, 0.0722], np.float32)
    y = linear @ w
    y_out = curve(y)                        # gamma-encoded target luma
    base = srgb_encode(linear)              # gamma-encoded colour
    ycc = rgb_to_ycc(base)
    scale = np.where(ycc[..., 0] > 1e-4, y_out / np.maximum(ycc[..., 0], 1e-4), 1.0)
    ycc[..., 0] = y_out
    ycc[..., 1:] *= np.clip(scale, 0, 4)[..., None]
    return np.clip(ycc_to_rgb(ycc), 0, 1)


# ---------------------------------------------------------------- stage 3: colour
@dataclass
class ColorSettings:
    sat: list[int] = field(default_factory=lambda: [0] * 12)    # stock -5..+5 (ext -7..+7)
    hue: list[int] = field(default_factory=lambda: [0] * 12)    # HSL extension -7..+7
    light: list[int] = field(default_factory=lambda: [0] * 12)  # HSL extension -7..+7


class ColorEngine:
    """12-sector chroma engine parameterised from the firmware COLOR table.

    Firmware record word0 = sector centre angle (0..32767 == 0..360 deg in the
    ISP's chroma plane), word1 = half-width-like value, gains (+/-) scale the
    slider into a coefficient (fishcu: yellow S=+5 -> 225 with gain 240..).
    The chroma-plane rotation vs. BT.601 CbCr is unknown; `angle_offset` is a
    calibrated parameter (see calibrate.py), not a firmware fact.
    """

    def __init__(self, table_json: Path = TABLE_JSON, angle_offset_deg: float = 15.0,
                 sat_scale: float = 1.5, base_chroma: float = 1.1):
        t = json.loads(Path(table_json).read_text())
        recs = sorted(t['records'], key=lambda r: r['ui_index'])
        self.centre = np.array([r['words_i16'][0] / 32768 * 360 for r in recs])
        self.width = np.array([r['words_i16'][1] / 32768 * 360 for r in recs])
        self.gain_pos = np.array([r['gain_pos_neg'][0] for r in recs], float)
        self.gain_neg = np.array([r['gain_pos_neg'][1] for r in recs], float)
        self.angle_offset = angle_offset_deg
        self.sat_scale = sat_scale
        self.base_chroma = base_chroma   # camera base rendering vs LibRaw (calibrated)

    def weights(self, hue_deg: np.ndarray) -> np.ndarray:
        """Per-pixel sector weights (..., 12), normalised raised-cosine."""
        c = (self.centre + self.angle_offset) % 360
        d = (hue_deg[..., None] - c + 180) % 360 - 180
        w = np.clip(np.cos(np.clip(d / np.maximum(self.width, 1) * (np.pi / 2), -np.pi / 2, np.pi / 2)), 0, None)
        s = w.sum(-1, keepdims=True)
        return np.where(s > 1e-6, w / np.maximum(s, 1e-6), 1 / 12)

    def sat_coeff(self, sat):
        s = np.asarray(sat, float)
        g = np.where(s >= 0, self.gain_pos, self.gain_neg)
        return s * g / 5.0 * self.sat_scale          # ~ firmware coefficient units

    def apply(self, rgb_gamma: np.ndarray, cs: ColorSettings) -> np.ndarray:
        ycc = rgb_to_ycc(rgb_gamma)
        cb, cr = ycc[..., 1], ycc[..., 2]
        hue = np.degrees(np.arctan2(cr, cb)) % 360
        w = self.weights(hue)
        sat_mult = 1 + (w @ self.sat_coeff(cs.sat)) / 1000.0
        hue_shift = w @ (np.asarray(cs.hue, float) * HUE_DEG_PER_STEP)
        l_tab = np.array([-300, -250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250, 300], float)
        l_native = l_tab[np.clip(np.asarray(cs.light, int), -7, 7) + 7]
        chroma = np.hypot(cb, cr)
        light = (w @ l_native) / 4096.0 * np.clip(chroma / 0.25, 0, 1)
        ang = np.radians(hue + hue_shift)
        ch = chroma * self.base_chroma * np.clip(sat_mult, 0, 3)
        ycc[..., 1], ycc[..., 2] = ch * np.cos(ang), ch * np.sin(ang)
        ycc[..., 0] = ycc[..., 0] + light
        return np.clip(ycc_to_rgb(ycc), 0, 1)


# ---------------------------------------------------------------- stage 4: grain
def grain(rgb_gamma: np.ndarray, strength: str = 'medium', seed: int = 10, colour: bool = True,
          full_width: int = 5184) -> np.ndarray:
    """Olympus creative grain (xorshift32, brightness mask). fishcu GRAIN.md.

    Applied to 16-bit luma; chroma passes through (colour=True keeps colour).
    The formula is per full-resolution pixel; for a downscaled preview the
    noise std is scaled by (preview_width / full_width) to match the look of
    a full-res image viewed at the same size.
    """
    gain = dict(low=110, medium=300, high=600)[strength]
    h, w, _ = rgb_gamma.shape
    n = h * w
    # vectorised xorshift32 stream: seed per pixel from a counter, as an
    # approximation of the sequential stream (statistically equivalent).
    state = (np.arange(n, dtype=np.uint64) * 2654435761 + seed) & 0xffffffff
    state = state.astype(np.uint32)
    for _ in range(3):
        state ^= (state << np.uint32(13))
        state ^= (state >> np.uint32(17))
        state ^= (state << np.uint32(5))
    rnd = (state & 0xffff).astype(np.int64) - 32768
    ycc = rgb_to_ycc(rgb_gamma)
    y16 = np.clip(ycc[..., 0] * 65535, 0, 65535).astype(np.int64).ravel()
    idx = y16 >> 8
    mask_curve = np.clip((np.arange(256) - 36) / (120 - 36), 0, 1) * 1023   # 0 to 36, 1023 by 120
    m = (mask_curve[idx] * 64).astype(np.int64)
    weight = (m + ((m >> 15) & 1)) >> 6
    noise = (((gain * weight) >> 10) * rnd) >> 10
    noise = np.clip(noise, -6682, 65535) * min(1.0, w / full_width)
    y_out = np.clip(y16 + noise.astype(np.int64), 0, 65535).reshape(h, w) / 65535.0
    ycc[..., 0] = y_out
    if not colour:
        ycc[..., 1:] = 0
    return np.clip(ycc_to_rgb(ycc), 0, 1)


# ---------------------------------------------------------------- stage 5: crop
ASPECTS = {'4:3': 4 / 3, '3:2': 3 / 2, '16:9': 16 / 9, '1:1': 1.0, '3:4': 3 / 4,
           '21:9': 64 / 27, 'xpan': 65 / 24, '6:7': 6 / 7}


def crop(img: np.ndarray, aspect: str) -> np.ndarray:
    h, w = img.shape[:2]
    r = ASPECTS[aspect]
    if w / h > r:
        nw = int(round(h * r)); x = (w - nw) // 2
        return img[:, x:x + nw]
    nh = int(round(w / r)); y = (h - nh) // 2
    return img[y:y + nh]


def save(img: np.ndarray, path: Path, quality: int = 92):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8)).save(path, quality=quality)
