#!/usr/bin/env python3
"""Aspect SCP value cell (docs/ASPECT.md 1j): Panorama (id 6) / Wide (id 7) in the Super Control Panel aspect cell. Offline.

  .venv/bin/python -I patches/aspect_scp/build.py generated/combo/b1/edits.json --out generated/aspect_scp/t1/edits.json
  .venv/bin/python -I tools/build_package.py generated/aspect_scp/t1/edits.json --out generated/aspect_scp/t1/pkg
  .venv/bin/python -I patches/aspect_scp/verify.py generated/combo/b1/edits.json generated/aspect_scp/t1/edits.json generated/aspect_scp/t1/pkg

The cell is not drawn from the strip lists. Two SCP cell builders (0x60e00ba9, and Legacy_Detail_Scp_Viewer 0x60e071ae) look
GetValue(270) up in a 6-entry {value, index} list (0x6116e1ec / 0x6117135c: 1,3,2,4,9,10 -> 2,6,3,5,4,7) and store a
kind-0 cell index; widget record 0x610a3c38 (395,272 106x32) draws part index-2 from its 5-part list 0x610a0798
(106x31 bitmaps 5871 4:3, 5870 3:2, 5869 3:4, 5868 1:1, 5867 16:9). 6/7 miss -> index 0 -> setPart ignores it -> the
widget keeps part 0 (4:3).

apply(spec, version='0.28c1') -> spec:
  - one 8-entry {value, index} list for both builders = the stock 6 + (6 -> 7) + (7 -> 8), written over the old part list
    0x610a0798 (dead after the record moves; its only reference is the record);
  - both builder sites: list pointer + count 6 -> 8 (6 B each);
  - record 0x610a3c38 +0x34: count 5 -> 7, parts -> 0x601e1d80, u16 array -> 0x601e1df0;
  - a 7-part list (stock 5 + 5866 + 5889) and its 7 zero u16 at 0x601e1d80..0x601e1e00 (dead EVF step-9 R tail);
  - OSD, in place: 5866 (17:9 cell icon, 17:9 is not selectable for stills) -> "XP"; 5889 ("50M F", a High Res Shot
    quality icon; the E-P7 has no High Res Shot) -> "21:9", descriptor width 169 -> 106. Payload <= original, colour key
    stays 7, no directory or bitmap-table edit.
"""
import argparse, copy, importlib.util, json, struct, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'patches/aspect'), str(ROOT / 'external/oly_fw_analysis/tools')]
import osd_extract as X      # noqa: E402
import osd_icons as OI       # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


AF = _load('aspect_fix_build_scp', ROOT / 'patches/aspect_fix/build.py')
FV, STOCK = AF.FV, AF.STOCK
BASE, SRC = 0x60020020, 'patches/aspect_scp'
FONT = '/usr/share/fonts/TTF/FiraSans-Bold.ttf'

# cell builders: (site of `mov imm32,a1` imm, stock list, stock count) -> imm32 + `mov 8,d1`
SITES = {0x60e00bdf: 0x6116e1ec, 0x60e071e4: 0x6117135c}
STOCK_LIST = [(1, 2), (3, 6), (2, 3), (4, 5), (9, 4), (10, 7)]
NEW_LIST = STOCK_LIST + [(6, 7), (7, 8)]
LIST_AT = 0x610a0798                       # old part list of the record (80 B), referenced only by the record
REC = 0x610a3c38                           # widget record: +0x34 u8 2, u8 count; +0x38 parts; +0x3c u16[count]
REC_STOCK = struct.pack('<4B2I', 2, 5, 0, 0, 0x610a0798, 0x610a07e8)
PARTS_AT, PARTS_END = 0x601e1d80, 0x601e1e00   # dead EVF step-9 R tail (art stub ends 0x601e1d78; 0xa01e1e01 word stays outside)
STEP9 = (0x601e1d3c, 0x601e3d10)          # table start, its step-table word
STOCK_PARTS = (5871, 5870, 5869, 5868, 5867)
XP_ID, W219_ID = 5866, 5889
PARTS = STOCK_PARTS + (XP_ID, W219_ID)     # index 2..8; 6 -> 7 -> XP, 7 -> 8 -> 21:9
U16_AT = PARTS_AT + 16 * len(PARTS)


# ------------------------------------------------------------------ images (106x31, mode 11, cut-out text on index 22)
def box_of(a):
    nz = np.nonzero(a)
    return int(nz[0].min()), int(nz[0].max()) + 1, int(nz[1].min()), int(nz[1].max()) + 1


def gmask(a):
    y0, y1, x0, x1 = box_of(a)
    m = np.zeros(a.shape, bool)
    m[y0 + 1:y1 - 1, x0 + 1:x1 - 1] = a[y0 + 1:y1 - 1, x0 + 1:x1 - 1] != 22
    return m


def clean(a):
    out = a.copy()
    out[gmask(a)] = 22
    return out


def make_219(o):
    a169, a32 = OI.bitmap(o, 5867), OI.bitmap(o, 5870)
    m169, m32 = gmask(a169), gmask(a32)
    g169, g32 = OI.segments(m169), OI.segments(m32)
    assert len(g169) == 4 and len(g32) == 3, (g169, g32)
    glyphs = [(a32, m32, g32[2]), (a169, m169, g169[0]), (a169, m169, g169[2]), (a169, m169, g169[3])]   # 2 1 : 9
    gaps = [g169[k + 1][0] - g169[k][1] for k in range(3)]
    width = sum(e - b for _, _, (b, e) in glyphs) + sum(gaps)
    x = int(round((g169[0][0] + g169[-1][1]) / 2 - width / 2))
    out = clean(a169)
    for k, (a, m, (b, e)) in enumerate(glyphs):
        sub = m[:, b:e]
        out[:, x:x + e - b][sub] = a[:, b:e][sub]
        x += e - b + (gaps[k] if k < 3 else 0)
    return out


def make_xp(o):
    """'XP' cut out of the stock 4:3 box at the stock digit band; coverage -> 22 / 23 / 24 / 0 (hole) like the stock edges."""
    from PIL import Image, ImageDraw, ImageFont
    ref = OI.bitmap(o, 5871)
    rm = gmask(ref)
    rows, cols = np.nonzero(rm.any(1))[0], np.nonzero(rm.any(0))[0]
    y0, y1, x0s, x1s = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
    SS, H, gap = 8, y1 - y0, 3
    f = ImageFont.truetype(FONT, size=int(H * SS / 0.689))   # Fira cap height = 0.689 em
    letters = []
    for ch in 'XP':
        l, t, r, b = f.getbbox(ch)
        im = Image.new('L', (r - l + 4 * SS, b - t + 4 * SS), 0)
        ImageDraw.Draw(im).text((2 * SS - l, 2 * SS - t), ch, font=f, fill=255)
        im = im.crop(im.getbbox())
        w = max(1, round(im.width / SS))
        letters.append(np.asarray(im.resize((w * SS, H * SS), Image.LANCZOS).resize((w, H), Image.BOX), float) / 255)
    cov = np.zeros((H, letters[0].shape[1] + gap + letters[1].shape[1]))
    cov[:, :letters[0].shape[1]] = letters[0]
    cov[:, letters[0].shape[1] + gap:] = letters[1]
    assert cov.shape[1] <= x1s - x0s + 4, cov.shape
    x0 = int(round((x0s + x1s) / 2 - cov.shape[1] / 2))
    out = clean(ref)
    for yy in range(H):
        for xx in range(cov.shape[1]):
            c = cov[yy, xx]
            out[y0 + yy, x0 + xx] = 22 if c < 0.15 else 23 if c < 0.46 else 24 if c < 0.81 else 0
    return out


def images(o):
    return {XP_ID: make_xp(o), W219_ID: make_219(o)}


def osd_edits(o, imgs):
    out, info = [], {}
    for i, a in imgs.items():
        r = o.descriptor(i)
        assert r['kind'] == 'rle' and r['fmt'] == 14 and r['field6'] == 8 and r['extra'] == 7 and r['height'] == a.shape[0]
        st = OI.encode(a.tobytes(), a.shape[1], a.shape[0])
        cap = r['encoded_bytes']
        assert len(st) <= cap, (i, len(st), cap)
        po, dp = r['payload_offset'], r['descriptor_offset']
        what = 'XP' if i == XP_ID else '21:9'
        out.append(dict(kind='0x101', addr=f'off:{po:#x}', expect=o.data[po:po + cap].hex(), new=(st + bytes(cap - len(st))).hex(),
                        source=SRC, why=f'aspect_scp: bitmap {i} -> SCP value-cell "{what}" 106x31, in place, {len(st)}/{cap} B'))
        if r['width'] != a.shape[1]:
            out.append(dict(kind='0x101', addr=f'off:{dp + 2:#x}', expect=o.data[dp + 2:dp + 6].hex(),
                            new=struct.pack('<HH', a.shape[1], a.shape[0]).hex(), source=SRC,
                            why=f'aspect_scp: bitmap {i} descriptor {r["width"]}x{r["height"]} -> {a.shape[1]}x{a.shape[0]}'))
        out.append(dict(kind='0x101', addr=f'off:{dp + 12:#x}', expect=o.data[dp + 12:dp + 16].hex(),
                        new=struct.pack('<I', len(st)).hex(), source=SRC,
                        why=f'aspect_scp: bitmap {i} descriptor encoded size {cap} -> {len(st)}'))
        info[i] = dict(label=what, stream=len(st), capacity=cap, width=a.shape[1], height=a.shape[0], was=[r['width'], r['height']])
    return out, info


# ------------------------------------------------------------------ main image
def refs_into(stock, lo, hi):
    """Every u32 (any alignment, cached or uncached alias) in [lo, hi)."""
    hits = []
    for off in range(4):
        w = np.frombuffer(stock[off:off + (len(stock) - off) // 4 * 4], dtype='<u4')
        for k in np.nonzero(((w >= lo) & (w < hi)) | ((w >= lo + 0x40000000) & (w < hi + 0x40000000)))[0]:
            hits.append(BASE + off + 4 * int(k))
    return hits


def main_edits(spec, stock):
    im = AF.img_of(spec, stock)
    s = lambda a, n: stock[a - BASE:a - BASE + n]
    for a, n in [(PARTS_AT, PARTS_END - PARTS_AT), (LIST_AT, 64), (REC + 0x34, 12)] + [(k - 2, 8) for k in SITES]:
        if im[a - BASE:a - BASE + n] != s(a, n):
            raise SystemExit(f'{a:#x}: base is not stock here')
    if s(REC + 0x34, 12) != REC_STOCK:
        raise SystemExit('record 0x610a3c38 is not the expected 5-part aspect widget')
    got = [struct.unpack_from('<I', stock, 0x610a0798 - BASE + 16 * k + 12)[0] for k in range(5)]
    if tuple(got) != STOCK_PARTS or s(0x610a07e8, 10) != bytes(10):
        raise SystemExit(f'stock part list differs: {got}')
    for site, lst in SITES.items():
        if s(site - 2, 8) != b'\xfc\xdd' + struct.pack('<I', lst) + b'\x85\x06':
            raise SystemExit(f'{site:#x}: not `mov {lst:#x},a1; mov 6,d1`')
        if [struct.unpack_from('<2I', stock, lst - BASE + 8 * k) for k in range(6)] != STOCK_LIST:
            raise SystemExit(f'{lst:#x}: stock list differs')
    # nothing but the record points into the old part list; nothing points into the new part block
    if [h for h in refs_into(stock, LIST_AT, LIST_AT + 80) if h != REC + 0x38]:
        raise SystemExit('other reference into the old part list')
    if refs_into(stock, PARTS_AT, PARTS_END) or refs_into(stock, STEP9[0], STEP9[0] + 1) != [STEP9[1]]:
        raise SystemExit('reference into the new part block / step-9 table')
    parts = b''.join(struct.pack('<4I', 0xffff, 7, 7, b) for b in PARTS) + bytes(2 * len(PARTS))
    parts += bytes(PARTS_END - PARTS_AT - len(parts))
    lst = b''.join(struct.pack('<2I', v, i) for v, i in NEW_LIST)
    rec = struct.pack('<4B2I', 2, len(PARTS), 0, 0, PARTS_AT, U16_AT)
    assert PARTS_AT % 16 == 0 and U16_AT % 4 == 0 and LIST_AT % 4 == 0 and (REC + 0x34) % 4 == 0 and len(parts) == 128
    out = [(PARTS_AT, parts, f'7-part list (stock 5 + {XP_ID} XP + {W219_ID} 21:9) + 7 zero u16 for record {REC:#x} (dead EVF step-9 R tail)'),
           (LIST_AT, lst, 'SCP aspect cell {value, index} list, 8 entries (stock 6 + 6->7, 7->8), over the old 5-part list'),
           (REC + 0x34, rec, f'SCP aspect widget record {REC:#x}: count 5 -> 7, parts -> {PARTS_AT:#x}, u16 -> {U16_AT:#x}')]
    for site in SITES:
        out.append((site, struct.pack('<I', LIST_AT) + b'\x85\x08', f'SCP aspect cell builder: list -> {LIST_AT:#x}, count 6 -> 8'))
    edits = []
    for a, new, why in out:
        for e in spec['edits']:
            if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
                b, n = int(e['addr'], 16), len(e['new']) // 2
                if b < a + len(new) and a < b + n:
                    raise SystemExit(f'{a:#x}: already edited by {e["addr"]}')
        edits.append(dict(kind='0x100', addr=hex(a), expect=s(a, len(new)).hex(), new=new.hex(), source=SRC, why=f'aspect_scp: {why}'))
    return edits


def apply(spec, version='0.28c1', o=None):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    if 'aspect_icons' not in spec or spec.get('sharp_off', {}).get('version') != '0.28':
        raise SystemExit('base is not v0.28 (with the v0.25 aspect icons)')
    if 'aspect_scp' in spec:
        raise SystemExit('aspect_scp already applied')
    o = o or X.OSD()
    imgs = images(o)
    oed, info = osd_edits(o, imgs)
    for e in oed:
        a, n = int(e['addr'][4:], 16), len(e['new']) // 2
        for f in spec['edits']:
            if f['kind'] == '0x101':
                b, m = int(f['addr'][4:], 16), len(f['new']) // 2
                if b < a + n and a < b + m:
                    raise SystemExit(f'OSD {e["addr"]}: already edited by {f["addr"]}')
    spec = FV.apply(spec, version)
    med = main_edits(spec, stock)
    spec['edits'] += med + oed
    spec['aspect_scp'] = dict(built_by=SRC, test='t1', version=version, list=hex(LIST_AT), parts=hex(PARTS_AT), record=hex(REC),
                              sites=[hex(k) for k in SITES], map={'6': [7, XP_ID], '7': [8, W219_ID]},
                              bitmaps={str(k): v for k, v in info.items()})
    return spec


def previews(o, d):
    from PIL import Image
    d.mkdir(parents=True, exist_ok=True)
    pal = OI.palette(o).astype(np.uint8)
    imgs = images(o)
    row = [OI.bitmap(o, i) for i in STOCK_PARTS] + [imgs[XP_ID], imgs[W219_ID]]
    sheet = Image.new('RGBA', (len(row) * 110 + 4, 36), (24, 24, 24, 255))
    for k, a in enumerate(row):
        sheet.alpha_composite(Image.fromarray(np.dstack([pal[a], np.where(a == 0, 0, 255).astype(np.uint8)]), 'RGBA'), (2 + 110 * k, 2))
    sheet.save(d / 'scp_cell_1x.png')
    sheet.resize((sheet.width * 3, sheet.height * 3), Image.NEAREST).save(d / 'scp_cell_3x.png')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--version', default='0.28c1')
    a = ap.parse_args()
    o = X.OSD()
    spec = apply(json.loads(a.spec.read_text()), a.version, o)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    previews(o, a.out.parent / 'previews')
    print(json.dumps(spec['aspect_scp']))
