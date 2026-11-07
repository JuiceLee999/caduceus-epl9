"""Grain model of v0.27 (patches/grain_cpu, r1), our own; the camera code is bit-exact to it (patches/v027/verify.py M).

Noise at half resolution, then bilinear x2:
  ring[16384]: one xorshift32 per 4 bytes, n = low + high nibble of each byte (0..30, triangular), ring[x] = (n[x] + n[x-1] + 1) >> 1, n[-1] = 15
  half-res row k: offset o_k = ((r >> 8) & 0xffff) * span >> 16 (r steps once per row, span = 16383 - (W/2 + 2)),
                  g_k[i] = (ring[o_k + i] + ring[o_{k-1} + i] + 1) >> 1, i = 0 .. W/2
  output row 2k:   h = g_k[i], then (g_k[i] + g_k[i+1] + 1) >> 1
  output row 2k+1: h = (g_k[i] + g_{k+1}[i] + 1) >> 1, then (g_k[i] + g_k[i+1] + g_{k+1}[i] + g_{k+1}[i+1] + 2) >> 2
  Y' = T[Y][h], T = clamp(Y + (((64 h - C) * G[Y] * S + 2^17) >> 18)), G as the OM-3 port's model.py (midtone weighted).
"""
import numpy as np

C = 996
STRENGTH = (0, 40, 102, 180)


def _ss(t):
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


G = np.array([round(255 * (0.08 + 0.92 * _ss((y - 25) / 75)) * (1 - 0.25 * _ss((y - 200) / 55))) for y in range(256)], dtype=np.int64)


def table(s, c=C):
    y = np.arange(256)[:, None]; h = np.arange(32)[None, :]
    return np.clip(y + (((64 * h - c) * G[:, None] * s + 131072) >> 18), 0, 255).astype(np.uint8)


def xs(r):
    r ^= (r << 13) & 0xffffffff; r ^= r >> 17; r ^= (r << 5) & 0xffffffff
    return r


def ring(seed):
    out = np.zeros(16384, dtype=np.int64); prev, r, i = 15, seed, 0
    for _ in range(4096):
        r = xs(r); x = r
        for _ in range(4):
            n = (x & 15) + ((x >> 4) & 15)
            out[i] = (n + prev + 1) >> 1; prev = n; i += 1; x >>= 8
    return out, r


def noise(w, h, seed):
    """-> h x w noise (0..30) and the final r."""
    rg, r = ring(seed)
    hw = w // 2
    span = 16383 - (hw + 2)
    off = lambda r: (((r >> 8) & 0xffff) * span) >> 16
    r = xs(r); po = off(r)
    g = []
    for k in range(h // 2 + 1):
        r = xs(r); o = off(r)
        g.append((rg[o:o + hw + 1] + rg[po:po + hw + 1] + 1) >> 1)
        po = o
    out = np.zeros((h, w), dtype=np.int64)
    for y in range(h):
        k = y >> 1
        a = g[k]
        if y & 1 == 0:
            out[y, 0::2] = a[:hw]
            out[y, 1::2] = (a[:hw] + a[1:hw + 1] + 1) >> 1
        else:
            b = g[k + 1]
            out[y, 0::2] = (a[:hw] + b[:hw] + 1) >> 1
            out[y, 1::2] = (a[:hw] + a[1:hw + 1] + b[:hw] + b[1:hw + 1] + 2) >> 2
    return out, r


def apply(Y, level, seed=0x12345678):
    n, _ = noise(Y.shape[1], Y.shape[0], seed)
    return table(STRENGTH[level])[Y, n]
