"""Camera-feasible preview renderer for the look library (desktop sim only, docs/LIBRARY_V1.md).

  systemd-run --user --scope -p MemoryMax=3G -q .venv/bin/python sim/library_preview.py \
      sim/recipes/library_v1.json generated/library [key1,key2,...]

Also takes a bundles library (bundles/library_v3.json: look recipe + the look's grain/effect/tone overrides).
Renders only what the camera can do: sat/hue/light, tone levels (camera LUT model incl. Blacks/Whites), contrast, WB shift (sim/film.py),
then bloom as the Soft Focus blend (share 8/14/20/27/35 % of a 160-px-wide blurred copy,
docs/BLOOM_HALATION.md) and grain with the v0.4 colour gains 50/75/100 or stock mono 110/300/600.
Writes sheet_<image>.jpg (all looks), overview.jpg (look x image) and detail_portrait_50pct.jpg.
"""
import sys, json, importlib.util
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'sim'))
import pipeline as P, film as F, effects as FX
CACHE = ROOT / 'generated/library/cache'
IMAGES = {'portrait': 'testdata/camera_t5/PB010074.ORF', 'roof': 'testdata/camera_t5/PB010073.ORF',
          'sunset': 'testdata/PA211064.ORF', 'valley': 'testdata/PA211089.ORF',
          'flower': 'testdata/camera_t5/PB010024.ORF'}
TW, TH = 400, 300
BLOOM_SHARE = [0.08, 0.14, 0.20, 0.27, 0.35]          # docs/BLOOM_HALATION.md W = 942..666
COLOUR_GAIN = dict(low=50, medium=75, high=100)        # grain v0.4 colour combiner 32 (GRAIN_PORT.md)
MONO_GAIN = dict(low=110, medium=300, high=600)        # stock mono grain


def load_looks(path):
    """sim/recipes/*.json -> recipes; a bundles library (bundles/library_v3.json) -> each look's recipe with the
    look's own overrides (grain, effect, tone incl. v0.19 Blacks/Whites) and name."""
    j = json.loads(Path(path).read_text())
    if 'looks' not in j:
        return j['recipes']
    rec = {}
    for f in sorted((ROOT / 'sim/recipes').glob('library_v*.json')):
        rec.update(json.loads(f.read_text())['recipes'])
    out = {}
    for k, look in j['looks'].items():
        r = dict(rec[look['recipe']])
        r.update({kk: v for kk, v in look.items() if kk not in ('recipe', 'notes')})
        out[k] = r
    return out


def prep(name, rel, full=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f'{name}.npy'
    if not f.exists():
        lin = P.develop(ROOT / rel, orient=True)
        np.save(f, lin)
    lin = np.load(f)
    h, w = lin.shape[:2]
    return lin, 2 * w


def fit(lin, tw, th):
    h, w = lin.shape[:2]
    r = tw / th
    if w / h > r:
        nw = int(h * r); lin = lin[:, (w - nw) // 2:(w - nw) // 2 + nw]
    else:
        nh = int(w / r); lin = lin[(h - nh) // 2:(h - nh) // 2 + nh]
    return P.resize(np.ascontiguousarray(lin), (tw, th))


def cam_bloom(img, strength, ref_w):
    """Soft Focus blend: share s of a 160x120-derived blurred copy (display domain)."""
    s = BLOOM_SHARE[strength - 1]
    h, w = img.shape[:2]
    sw = max(8, int(round(160 * w / ref_w * (ref_w / w))))  # 160 px across the full frame
    sh = max(6, int(round(sw * h / w)))
    small = FX._resize(img, (sw, sh), Image.BOX)
    small = FX.gaussian_blur(small, 1.2)
    blur = FX._resize(small, (w, h), Image.BILINEAR)
    return np.clip((1 - s) * img + s * blur, 0, 1)


def cam_grain(img, level, mono, full_width, seed=10):
    gain = (MONO_GAIN if mono else COLOUR_GAIN)[level]
    h, w, _ = img.shape
    n = h * w
    st = ((np.arange(n, dtype=np.uint64) * 2654435761 + seed) & 0xffffffff).astype(np.uint32)
    for _ in range(3):
        st ^= st << np.uint32(13); st ^= st >> np.uint32(17); st ^= st << np.uint32(5)
    rnd = (st & 0xffff).astype(np.int64) - 32768
    ycc = P.rgb_to_ycc(img)
    y16 = np.clip(ycc[..., 0] * 65535, 0, 65535).astype(np.int64).ravel()
    mask = np.clip((np.arange(256) - 36) / (120 - 36), 0, 1) * 1023
    m = (mask[y16 >> 8] * 64).astype(np.int64)
    wt = (m + ((m >> 15) & 1)) >> 6
    noise = (((gain * wt) >> 10) * rnd) >> 10
    noise = np.clip(noise, -6682, 65535) * min(1.0, w / full_width)
    ycc[..., 0] = np.clip(y16 + noise, 0, 65535).reshape(h, w) / 65535.0
    return np.clip(P.ycc_to_rgb(ycc), 0, 1)


def render(lin, rc, full_width):
    r = {k: rc[k] for k in ('sat', 'hue', 'light', 'tone', 'contrast', 'wb_shift', 'mono_filter') if rc.get(k) is not None}
    img = F.render(lin, r, full_width=full_width)
    eff = rc.get('effect')
    if eff and eff.get('type') == 'bloom':
        img = cam_bloom(img, eff['strength'], img.shape[1])
    g = rc.get('grain', 'off')
    if g and g != 'off':
        img = cam_grain(img, g, bool(rc.get('mono_filter')), full_width)
    return img


def label(img, text, big=False):
    im = Image.fromarray((np.clip(img, 0, 1) * 255 + .5).astype(np.uint8))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 10 + 6 * len(text), 15], fill=(0, 0, 0))
    d.text((5, 2), text, fill=(255, 255, 255))
    return np.asarray(im, np.float32) / 255


def grid(tiles, cols):
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.concatenate(tiles[i:i + cols], 1) for i in range(0, len(tiles), cols)]
    return np.concatenate(rows, 0)


def main():
    recipes = load_looks(sys.argv[1])
    out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    only = sys.argv[3].split(',') if len(sys.argv) > 3 else None
    keys = [k for k in recipes if not only or k in only]
    per_look = {k: [] for k in keys}
    for iname, rel in IMAGES.items():
        lin, fw = prep(iname, rel)
        small = fit(lin, TW, TH)
        tiles = [label(F.render(small, {}), 'E-P7 neutral (sim)')]
        for k in keys:
            t = render(small, recipes[k], fw)
            per_look[k].append(t)
            tiles.append(label(t, recipes[k]['name']))
        P.save(grid(tiles, 5), out / f'sheet_{iname}.jpg', quality=86)
    # look x image overview (small tiles)
    rows = []
    for k in keys:
        row = np.concatenate([P.resize(t, (240, 180)) for t in per_look[k]], 1)
        rows.append(label(row, recipes[k]['name']))
    P.save(np.concatenate(rows, 0), out / 'overview.jpg', quality=86)
    # 1:2 detail crop (portrait) to judge grain / bloom
    lin, fw = prep('portrait', IMAGES['portrait'])
    h, w = lin.shape[:2]
    crop = np.ascontiguousarray(lin[h // 2 - 300:h // 2 + 0, w // 2 - 200:w // 2 + 200])
    tiles = [label(render(crop, recipes[k], fw), recipes[k]['name']) for k in keys]
    P.save(grid(tiles, 5), out / 'detail_portrait_50pct.jpg', quality=88)
    print('ok', out)


if __name__ == '__main__':
    main()
