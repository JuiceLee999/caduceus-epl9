"""Desktop estimate of the v0.16 COLOR grain boost (offline; sim only, not camera pixels).

  systemd-run --user --scope -p MemoryMax=8G -q .venv/bin/python sim/grain_boost_preview.py generated/grain_boost

Old COLOR grain = combiner 32 gains 50/75/100; v0.16 COLOR = 110/300/600 (stock MONO full-size table 0x604ec0ce).
Uses the library sim grain model (xorshift luma noise, brightness weight, clamp -6682; sim/library_preview.cam_grain)
on the cached half-res develops. 100 % crops are 2x upsampled to full-res pixels. Writes crops_100pct.jpg,
frame_fit.jpg and stats.json (luma noise std in 8-bit codes, midtones, full-res pixels).
"""
import sys, json
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
import library_preview as L, pipeline as P, film as F

ROWS = [('off', None), ('old L 50', 50), ('old M 75', 75), ('old H 100', 100),
        ('new L 110', 110), ('new M 300', 300), ('new H 600', 600)]
IMGS = ['valley', 'roof', 'flower']


def grain(img, gain, full_width):
    if gain is None:
        return img
    L.COLOUR_GAIN['x'] = gain
    return L.cam_grain(img, 'x', False, full_width)


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    crops, fits, stats = [], [], {}
    for name in IMGS:
        lin, fw = L.prep(name, L.IMAGES[name])
        h, w = lin.shape[:2]
        disp = F.render(lin, {}, full_width=fw)                 # neutral COLOR render
        c = disp[h // 2 - 75:h // 2 + 75, w // 2 - 100:w // 2 + 100]
        c = P.resize(np.ascontiguousarray(c), (400, 300))       # full-res pixels (cache is half res)
        f = L.fit(disp, 400, 300)
        rc, rf = [], []
        for lab, g in ROWS:
            gc = grain(c, g, 400)                               # factor 1: per full-res pixel
            rc.append(L.label(gc, lab)); rf.append(L.label(grain(f, g, fw), lab))
            if g:
                y0, y1 = (P.rgb_to_ycc(x)[..., 0] for x in (c, gc))
                mid = (y0 > 0.3) & (y0 < 0.7)
                stats.setdefault(lab, []).append(round(float(np.std((y1 - y0)[mid]) * 255), 2))
        crops.append(np.concatenate(rc, 1)); fits.append(np.concatenate(rf, 1))
    for fn, rows in (('crops_100pct.jpg', crops), ('frame_fit.jpg', fits)):
        Image.fromarray((np.clip(np.concatenate(rows, 0), 0, 1) * 255 + .5).astype(np.uint8)).save(out / fn, quality=92)
    s = {k: dict(per_image=v, mean=round(float(np.mean(v)), 2)) for k, v in stats.items()}
    (out / 'stats.json').write_text(json.dumps(s, indent=1))
    for k, v in s.items():
        print(f'{k:10s} midtone luma noise std {v["mean"]:5.2f} /255 (100 % crop)')


if __name__ == '__main__':
    main()
