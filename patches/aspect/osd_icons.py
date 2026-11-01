#!/usr/bin/env python3
"""E-P7 1.1 aspect v8: new Panorama ("XPAN") and Wide ("21:9") aspect icons in the OSD component (kind 0x101).

OFFLINE. Library used by patches/aspect/build.py (and runnable alone for previews). docs/ASPECT.md §1g.

Format (docs/OSD.md, tools/osd_extract.py): bitmap id -> u32 descriptor pointer in the bank-0 bitmap table (runtime
0xa34f0164); fmt-14 descriptor {u16 14, w, h, field6 = 8 (index bits), 0, 0, u32 encoded bytes, u32 payload, u32 extra};
payload = mode-11 RLE (4-byte header, 12-bit tokens index<<4 | run-1, 5 per 64-bit group, runs break at row ends),
indices into the 8-bit OSD palette. `encode()` reproduces all 4976 stock mode-11 payloads byte for byte (checked).

The new icons are made from the stock aspect icons themselves:
  * 21:9  = the stock '2' (from 3:2) + '1', ':', '9' (from 16:9), pixel-exact glyph copies with the 16:9 spacing,
            centred like the stock labels, on the stock box/background (white 50x38 = 476 / green 64x48 = 471).
  * XPAN  = Fira Sans Condensed Bold (no X/P/A/N exists in the aspect-icon glyph set) at the stock cap height and row
            band, supersampled and quantised to the indices the stock icon uses (white: 4/5/6/16 ramp; green: each row's
            background index blended toward the stock text black 16 and its stock anti-alias indices).
Placement: the four payloads + descriptors are appended after resource 69 (the last OSD resource; the component is
zero there) and resource 69's directory size grows to cover them. The bitmap-bank loader 0x6015ad92 copies exactly
`size` bytes (rounded to 16) from the directory to 0xa3611000; its bound is 0xf26140 (= 0xa3091000..0xa3fb7140, the
OSD bitmap region below the font base 0xa3fb7540); bank 69 ends at 0xa3e22600, so a few KB more stay inside it [I].
Four unused placeholder ids (fmt-1, 0x0, no payload) get their table entry pointed at the new descriptors.
"""
import struct, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import osd_extract as X  # noqa: E402

COMP_ADDR = X.COMPONENT_ADDR
FONT = Path('/usr/share/fonts/TTF/FiraSansCondensed-Bold.ttf')
# new bitmap ids: stock placeholders (fmt 1, 0x0, no payload) with no typed reference in main (no type-3 option entry,
# no u32 in the sec-6 UI data, no mov imm16 in the UI code; build.py check O3). Ids are not provably unused [I].
NEW_IDS = {('xpan', 'white'): 5687, ('xpan', 'green'): 5685, ('219', 'white'): 4859, ('219', 'green'): 4431}
SRC = {'white': dict(box=476, three=478, text=(16, 5, 6), x0=4, x1=46, y0=6, y1=31),
       'green': dict(box=471, three=473, text=(16, 45, 89, 90), x0=5, x1=59, y0=9, y1=38)}
GREEN_SET = (472, 471, 473, 2421, 475)
WHITE_SET = (477, 476, 478, 2422, 479)


def encode(px, w, h):
    """Mode-11 RLE stream (inverse of osd_extract.decode_rle; byte-exact on every stock mode-11 bitmap)."""
    toks = []
    for y in range(h):
        row = px[y * w:(y + 1) * w]
        i = 0
        while i < w:
            v, r = row[i], 1
            while i + r < w and row[i + r] == v and r < 16:
                r += 1
            toks.append((v << 4) | (r - 1))
            i += r
    out = bytearray([(h - 1) & 255, ((h - 1) >> 8) & 3 | ((w - 1) & 15) << 4, ((w - 1) >> 4) & 63, 11])
    for g in range(0, len(toks), 5):
        word = 0
        for k, t in enumerate(toks[g:g + 5]):
            word |= t << (12 * k)
        n = len(toks[g:g + 5])
        out += word.to_bytes(8, 'little')[:8 if n == 5 else (12 * n + 7) // 8]
    return bytes(out)


def bitmap(o, i):
    r = o.descriptor(i)
    px, _, _ = o.decode_bitmap(r)
    return np.frombuffer(px, np.uint8).reshape(r['height'], r['width']).copy()


def palette(o):
    p = o.palette(X.DEFAULT_PALETTE8) if hasattr(o, 'palette') else None
    if p is None:
        off = X.DEFAULT_PALETTE8 - X.MAIN_BASE
        p = [struct.unpack_from('<I', o.main, off + 4 * k)[0] for k in range(256)]
    return np.array([[(c >> 16) & 255, (c >> 8) & 255, c & 255] for c in p], float)


def glyph_mask(a, kind):
    s = SRC[kind]
    m = np.isin(a, s['text'])
    m[:, :s['x0'] + 2] = False
    m[:, s['x1'] - 2:] = False
    m[:s['y0']] = False
    m[s['y1']:] = False
    return m


def segments(m):
    cols = m.any(0)
    out, x = [], 0
    while x < len(cols):
        if cols[x]:
            e = x
            while e < len(cols) and cols[e]:
                e += 1
            out.append((x, e))
            x = e
        else:
            x += 1
    return out


def clean_box(o, kind):
    """The stock 16:9 box with its label removed: each text pixel takes the value of the nearest text-free pixel in
    the same row whose column is congruent mod 12 (the green gradient rows carry a 3- or 4-column dither), else mod 4,
    else the nearest text-free pixel of the row (the white box is flat index 4)."""
    s = SRC[kind]
    a = bitmap(o, s['box'])
    m = glyph_mask(a, kind)
    out = a.copy()
    for y, x in zip(*np.nonzero(m)):
        free = [c for c in range(s['x0'] + 2, s['x1'] - 2) if not m[y, c]]
        for per in (12, 4, 1):
            cs = [c for c in free if (c - x) % per == 0]
            if cs:
                out[y, x] = a[y, min(cs, key=lambda c: abs(c - x))]
                break
    return out


def make_219(o, kind):
    s = SRC[kind]
    box = clean_box(o, kind)
    a169, a32 = bitmap(o, s['box']), bitmap(o, s['three'])
    m169, m32 = glyph_mask(a169, kind), glyph_mask(a32, kind)
    g169, g32 = segments(m169), segments(m32)
    assert len(g169) == 4 and len(g32) == 3, (g169, g32)
    glyphs = [(a32, m32, g32[2]), (a169, m169, g169[0]), (a169, m169, g169[2]), (a169, m169, g169[3])]   # 2 1 : 9
    gaps = [g169[k + 1][0] - g169[k][1] for k in range(3)]                                              # 16:9 spacing
    width = sum(e - b for _, _, (b, e) in glyphs) + sum(gaps)
    c169 = (g169[0][0] + g169[-1][1]) / 2
    x = int(round(c169 - width / 2))
    out = box.copy()
    for k, (a, m, (b, e)) in enumerate(glyphs):
        sub = m[:, b:e]
        out[:, x:x + e - b][sub] = a[:, b:e][sub]
        x += e - b + (gaps[k] if k < 3 else 0)
    return out


def make_text(o, kind, text, pal):
    """Font-rendered label at the stock cap band, quantised to the stock icon's own indices."""
    from PIL import Image, ImageDraw, ImageFont
    s = SRC[kind]
    box = clean_box(o, kind)
    ref = bitmap(o, s['box'])
    rm = glyph_mask(ref, kind)
    rows = np.nonzero(rm.any(1))[0]
    cy0, cy1 = int(rows[0]), int(rows[-1]) + 1                  # stock digit band (cap height)
    cols = np.nonzero(rm.any(0))[0]
    cx0, cx1 = int(cols[0]), int(cols[-1]) + 1                  # stock 16:9 label span (widest stock label)
    SS = 8
    capH = (cy1 - cy0) * SS
    f = ImageFont.truetype(str(FONT), size=int(capH / 0.689))   # Fira cap height = 0.689 em
    l, t, r, b = f.getbbox(text)
    im = Image.new('L', (r - l + 4 * SS, b - t + 4 * SS), 0)
    ImageDraw.Draw(im).text((2 * SS - l, 2 * SS - t), text, font=f, fill=255)
    bb = im.getbbox()
    im = im.crop(bb)
    tw = min(cx1 - cx0 + (2 if kind == 'white' else 2), round(im.width / SS))   # squash to the stock label width
    im = im.resize((tw * SS, capH), Image.LANCZOS).resize((tw, cy1 - cy0), Image.BOX)
    cov = np.asarray(im, float) / 255
    x0 = int(round((cx0 + cx1) / 2 - tw / 2))
    out = box.copy()
    black = pal[16]
    aa = [i for i in s['text'] if i != 16]
    for yy in range(cov.shape[0]):
        y = cy0 + yy
        for xx in range(tw):
            c = cov[yy, xx]
            if c < 0.12:
                continue
            x = x0 + xx
            bgi = box[y, x]
            want = pal[bgi] * (1 - c) + black * c
            cands = [bgi, 16] + (aa if kind == 'white' else
                                 sorted(set(int(v) for v in ref[y][rm[y]]) | set(aa)))
            out[y, x] = min(cands, key=lambda i: ((pal[i] - want) ** 2).sum())
    return out


def build_images(o):
    pal = palette(o)
    return {('xpan', k): make_text(o, k, 'XPAN', pal) for k in ('white', 'green')} | \
           {('219', k): make_219(o, k) for k in ('white', 'green')}


def osd_edits(o, imgs):
    """Append payload+descriptor pairs after resource 69, grow its size, repoint the four placeholder ids.
    Returns (edits for build_package (kind 0x101, off: addresses), {key: (id, descriptor ptr, payload ptr, size)})."""
    d = o.data
    r69 = o.resources[69]
    end = r69['offset'] + r69['size']
    blob, info = bytearray(), {}
    rt = o.base69 + r69['size']                       # runtime address of the first appended byte
    for key in (('xpan', 'white'), ('xpan', 'green'), ('219', 'white'), ('219', 'green')):
        a = imgs[key]
        h, w = a.shape
        st = encode(a.tobytes(), w, h)
        px, *_ = X.decode_rle(st, w, h)
        assert px == a.tobytes()
        pay = rt + len(blob)
        blob += st
        blob += bytes(-len(blob) % 4)
        desc = rt + len(blob)
        blob += struct.pack('<6H3I', 14, w, h, 8, 0, 0, len(st), pay, 0)
        info[key] = (NEW_IDS[key], desc, pay, len(st))
    new_size = r69['size'] + ((len(blob) + 0x1ff) & ~0x1ff)
    assert d[end:end + new_size - r69['size']] == bytes(new_size - r69['size'])
    edits = [dict(kind='0x101', addr=hex(end).replace('0x', 'off:0x'), expect=bytes(len(blob)).hex(), new=bytes(blob).hex(),
                  why=f'aspect v8: 4 new aspect icons (XPAN/21:9 x white 50x38/green 64x48) appended after OSD resource 69 '
                      f'(runtime {rt:#x}..{rt + len(blob):#x})')]
    dir69 = 16 * 69 + 4
    old = d[dir69:dir69 + 4]
    assert struct.unpack('<I', old)[0] == r69['size']
    edits.append(dict(kind='0x101', addr=f'off:{dir69:#x}', expect=old.hex(), new=struct.pack('<I', new_size).hex(),
                      why=f'aspect v8: OSD resource 69 directory size {r69["size"]:#x} -> {new_size:#x} (loader copies size bytes)'))
    tab = o.bitmap_table - o.base0 + r69['offset'] * 0 + o.resources[0]['offset']
    for key, (i, desc, _, _) in sorted(info.items(), key=lambda kv: kv[1][0]):
        row = o.descriptor(i)
        assert row['kind'] == 'placeholder', (i, row)
        off = tab + 4 * i
        old = d[off:off + 4]
        assert struct.unpack('<I', old)[0] == row['descriptor']
        edits.append(dict(kind='0x101', addr=f'off:{off:#x}', expect=old.hex(), new=struct.pack('<I', desc).hex(),
                          why=f'aspect v8: bitmap table id {i} (placeholder) -> new {key[0].upper()} {key[1]} icon {desc:#x}'))
    return edits, info


def apply_osd(data, edits):
    p = bytearray(data)
    for e in edits:
        a = int(e['addr'][4:], 16)
        n = bytes.fromhex(e['new'])
        assert p[a:a + len(n)] == bytes.fromhex(e['expect'])
        p[a:a + len(n)] = n
    return bytes(p)


def save_previews(o, imgs, out_dir, scale=6):
    """PNG sheet: stock aspect icons and the new ones, white row then green row (candidate palette, docs/OSD.md)."""
    from PIL import Image
    pal = palette(o).astype(np.uint8)
    out_dir.mkdir(parents=True, exist_ok=True)

    def rgba(a):
        rgb = pal[a]
        alpha = np.where(a == 0, 0, 255).astype(np.uint8)
        return Image.fromarray(np.dstack([rgb, alpha]), 'RGBA')
    rows = [[bitmap(o, i) for i in WHITE_SET] + [imgs[('xpan', 'white')], imgs[('219', 'white')]],
            [bitmap(o, i) for i in GREEN_SET] + [imgs[('xpan', 'green')], imgs[('219', 'green')]]]
    W = sum(a.shape[1] + 6 for a in rows[1]) + 20
    sheet = Image.new('RGBA', (W, 38 + 48 + 18), (48, 48, 48, 255))
    y = 6
    for r in rows:
        x = 6
        for k, a in enumerate(r):
            if k == 5:
                x += 14
            sheet.alpha_composite(rgba(a), (x, y))
            x += a.shape[1] + 6
        y += r[0].shape[0] + 4
    sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST).save(out_dir / 'aspect_icons_stock_vs_new.png')
    for (t, k), a in imgs.items():
        rgba(a).resize((a.shape[1] * scale, a.shape[0] * scale), Image.NEAREST).save(out_dir / f'new_{t}_{k}.png')
        Image.fromarray(a, 'P').save(out_dir / f'new_{t}_{k}_indices.png')


if __name__ == '__main__':
    o = X.OSD()
    imgs = build_images(o)
    save_previews(o, imgs, Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'generated/aspect_icons')
    ed, info = osd_edits(o, imgs)
    for k, v in info.items():
        print(k, v[0], hex(v[1]), hex(v[2]), v[3])
