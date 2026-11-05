#!/usr/bin/env python3
"""E-P7 1.1 aspect icons, second attempt (docs/ASPECT.md "2026-11-06"). OFFLINE. Layered on the pre-icon v0.25 spec
(patches/v025/build.py + patches/fw_version/build.py from v0.24) and wrote generated/aspect_icons/{edits.json, pkg/, previews/}.
Its result IS releases/v0.25/edits.json now, so BASE must point at a pre-icon spec to re-run. No SD-update-named file.

  .venv/bin/python -I patches/aspect_icons/build.py

Main: SCP lists 6/7 -> type-3 new ids; info lists 6/7 -> new ids; item-table row 16 (setting 270, never patched until
now) -> the 7-entry SCP lists. OSD: four headphone icons (the E-P7 has no headphone jack) overwritten in place, payload
no longer than the original; no table, directory or bank edit.
"""
import json, struct, subprocess, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'patches/aspect'), str(ROOT / 'external/oly_fw_analysis/tools')]
import osd_extract as X      # noqa: E402
import osd_icons as OI       # noqa: E402
import oly_container as oc   # noqa: E402

BASE = ROOT / 'releases/v0.25/edits.json'
OUT = ROOT / 'generated/aspect_icons'
MB = 0x60020020
FONT = '/usr/share/fonts/TTF/FiraSans-SemiBold.ttf'
IDS = {('xp', 'white'): 3732, ('xp', 'green'): 3725, ('219', 'white'): 5528, ('219', 'green'): 5535}
LIST_A, LIST_B, INFO_A, INFO_B = 0x61175d78, 0x61242f60, 0x601e15f0, 0x601e1628
ROW16 = 0x6116b190


def make_xp(o, kind, pal):
    """Wide 'XP' at the stock digit band, quantised to the stock icon's own indices (same method as osd_icons.make_text)."""
    from PIL import Image, ImageDraw, ImageFont
    s = OI.SRC[kind]
    box, ref = OI.clean_box(o, kind), OI.bitmap(o, s['box'])
    rm = OI.glyph_mask(ref, kind)
    rows, cols = np.nonzero(rm.any(1))[0], np.nonzero(rm.any(0))[0]
    y0, y1, x0s, x1s = int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1
    gap = 3 if kind == 'white' else 4                       # px between the two letters
    lw = (x1s - x0s - gap) // 2                             # each letter takes half the stock 16:9 label span
    SS, H = 8, y1 - y0
    f = ImageFont.truetype(FONT, size=int(H * SS / 0.689))  # Fira cap height = 0.689 em
    letters = []
    for ch in 'XP':
        l, t, r, b = f.getbbox(ch)
        im = Image.new('L', (r - l + 4 * SS, b - t + 4 * SS), 0)
        ImageDraw.Draw(im).text((2 * SS - l, 2 * SS - t), ch, font=f, fill=255)
        im = im.crop(im.getbbox()).resize((lw * SS, H * SS), Image.LANCZOS).resize((lw, H), Image.BOX)
        letters.append(np.asarray(im, float) / 255)
    cov = np.zeros((H, 2 * lw + gap))
    cov[:, :lw], cov[:, lw + gap:] = letters
    x0 = int(round((x0s + x1s) / 2 - cov.shape[1] / 2))
    out, black = box.copy(), pal[16]
    aa = [i for i in s['text'] if i != 16]
    for yy in range(H):
        y = y0 + yy
        for xx in range(cov.shape[1]):
            c = cov[yy, xx]
            if c < 0.2:
                continue
            x, bgi = x0 + xx, box[y, x0 + xx]
            want = pal[bgi] * (1 - c) + black * c
            cands = [bgi, 16] + (aa if kind == 'white' else sorted(set(int(v) for v in ref[y][rm[y]]) | set(aa)))
            out[y, x] = min(cands, key=lambda i: ((pal[i] - want) ** 2).sum())
    return out


def fit(o, a, kind, cap):
    """If the stream is over the target's size, flatten the background dither of the busiest rows, one row at a time,
    to the row's most common index (the green box carries a dithered gradient; the white box is flat). Glyphs are not
    touched. Returns the image and the number of rows flattened."""
    s, box, a = OI.SRC[kind], OI.clean_box(o, kind), a.copy()
    h, w = a.shape
    size = lambda im: len(OI.encode(im.tobytes(), w, h))
    runs = lambda r: int((r[1:] != r[:-1]).sum())
    n = 0
    done = set()
    while size(a) > cap:
        ys = [y for y in range(s['y0'], s['y1']) if y not in done]
        if not ys:
            raise ValueError(f'{kind}: cannot fit {size(a)} > {cap}')
        y = max(ys, key=lambda v: runs(a[v]))
        done.add(y)
        xs = [x for x in range(s['x0'] + 2, s['x1'] - 2) if a[y, x] == box[y, x]]   # background pixels of this row
        if xs:
            a[y, xs] = np.bincount(box[y, xs]).argmax()
            n += 1
    return a, n


def images(o):
    pal = OI.palette(o)
    raw = {('xp', k): make_xp(o, k, pal) for k in ('white', 'green')} | {('219', k): OI.make_219(o, k) for k in ('white', 'green')}
    out, flat = {}, {}
    for key, a in raw.items():
        out[key], flat[key] = fit(o, a, key[1], o.descriptor(IDS[key])['encoded_bytes'])
    print('flattened rows', flat)
    return out


def osd_edits(o, imgs):
    out, info = [], {}
    for key, i in IDS.items():
        r, a = o.descriptor(i), imgs[key]
        assert r['kind'] == 'rle' and r['fmt'] == 14 and r['field6'] == 8 and a.shape == (r['height'], r['width'])
        st = OI.encode(a.tobytes(), a.shape[1], a.shape[0])
        cap = r['encoded_bytes']
        assert len(st) <= cap, (key, len(st), cap)
        po, dp = r['payload_offset'], r['descriptor_offset']
        out.append(dict(kind='0x101', addr=f'off:{po:#x}', expect=o.data[po:po + cap].hex(), new=(st + bytes(cap - len(st))).hex(),
                        why=f'aspect icons: bitmap {i} (headphone icon, no jack on this body) -> {key[0]} {key[1]}, in place, {len(st)}/{cap} B'))
        tail = struct.pack('<I', len(st))                   # descriptor +12 encoded size, exact as in every stock bitmap
        out.append(dict(kind='0x101', addr=f'off:{dp + 12:#x}', expect=o.data[dp + 12:dp + 16].hex(), new=tail.hex(),
                        why=f'aspect icons: bitmap {i} descriptor encoded size {cap} -> {len(st)}'))
        if r['extra']:                                      # stock aspect icons have extra (colour key) 0
            out.append(dict(kind='0x101', addr=f'off:{dp + 20:#x}', expect=o.data[dp + 20:dp + 24].hex(), new=bytes(4).hex(),
                            why=f'aspect icons: bitmap {i} descriptor colour key {r["extra"]} -> 0 (as stock aspect icons)'))
        info[key] = dict(id=i, stream=len(st), capacity=cap, bank=r['bank'], pad_zero=cap - len(st))
    return out, info


def main_edits(spec):
    want = {LIST_A: ('white', 12), LIST_B: ('green', 12), INFO_A: ('white', 8), INFO_B: ('green', 8)}
    seen = set()
    for e in spec['edits']:
        if e['addr'].startswith('off:') or int(e['addr'], 16) not in want:
            continue
        a = int(e['addr'], 16)
        kind, stride = want[a]
        b = bytearray.fromhex(e['new'])
        for row, val, key in ((5, 6, 'xp'), (6, 7, '219')):
            assert struct.unpack_from('<I', b, row * stride)[0] == val
            if stride == 12:
                struct.pack_into('<HH', b, row * 12 + 4, 3, IDS[(key, kind)])   # type 4 text -> type 3 bitmap
            else:
                struct.pack_into('<I', b, row * 8 + 4, IDS[(key, kind)])
        e['new'] = bytes(b).hex()
        e['why'] += ' [aspect icons: 6/7 -> new bitmaps]'
        seen.add(a)
    assert seen == set(want)
    return dict(kind='0x100', addr=hex(ROW16 + 4),
                expect=struct.pack('<3I', 0x611670f4, 0x61167130, 5).hex(), new=struct.pack('<3I', LIST_A, LIST_B, 7).hex(),
                why='aspect icons: item-table row 16 (setting 270 via map 0x60e0af25; SCP viewer layouts) -> the 7-entry lists, count 5 -> 7')


def previews(o, imgs, d):
    from PIL import Image
    d.mkdir(parents=True, exist_ok=True)
    pal = OI.palette(o).astype(np.uint8)
    rgba = lambda a: Image.fromarray(np.dstack([pal[a], np.where(a == 0, 0, 255).astype(np.uint8)]), 'RGBA')
    rows = [('white', [OI.bitmap(o, 476), OI.bitmap(o, 478), imgs[('xp', 'white')], imgs[('219', 'white')]]),
            ('green', [OI.bitmap(o, 471), OI.bitmap(o, 473), imgs[('xp', 'green')], imgs[('219', 'green')]])]
    sheet = Image.new('RGBA', (4 * 72 + 8, 38 + 48 + 18), (48, 48, 48, 255))
    y = 6
    for _, r in rows:
        x = 6
        for a in r:
            sheet.alpha_composite(rgba(a), (x, y))
            x += 72
        y += r[0].shape[0] + 6
    sheet.save(d / 'stock_16x9_3x2_vs_new_1x.png')
    sheet.resize((sheet.width * 4, sheet.height * 4), Image.NEAREST).save(d / 'stock_16x9_3x2_vs_new_4x.png')
    for (t, k), a in imgs.items():
        for s in (1, 4):
            rgba(a).resize((a.shape[1] * s, a.shape[0] * s), Image.NEAREST).save(d / f'{t}_{k}_{s}x.png')


def checks(spec, o, imgs, pkgdir):
    ok = []
    def C(name, cond, extra=''):
        ok.append((name, bool(cond), extra))
        print(('PASS' if cond else 'FAIL'), name, extra)
    stock = (ROOT / 'stock_firmware/OLY_E_142_1100_0000_0000.BIN').read_bytes()
    by = {b.kind: b for b in oc.parse(stock)}
    pb, rb = oc.parse((pkgdir / 'patched.pkg.bin').read_bytes()), oc.parse((pkgdir / 'restore-stock.pkg.bin').read_bytes())
    C('package parses, components main+OSD', [b.kind for b in pb] == [0x100, 0x101] and [b.kind for b in rb] == [0x100, 0x101])
    em = {0x100: bytearray(by[0x100].payload), 0x101: bytearray(by[0x101].payload)}
    for e in spec['edits']:
        k = int(e['kind'], 16)
        a = int(e['addr'][4:], 16) if e['addr'].startswith('off:') else int(e['addr'], 16) - MB
        n = bytes.fromhex(e['new'])
        em[k][a:a + len(n)] = n
    C('decoded == stock + edits', all(bytes(em[b.kind]) == bytes(b.payload) for b in pb))
    C('restore == stock main + stock OSD', all(bytes(b.payload) == bytes(by[b.kind].payload) for b in rb))
    rel = json.loads((ROOT / 'releases/v0.25/build.json').read_text())
    bj = json.loads((pkgdir / 'build.json').read_text())
    C('restore sha == v0.25 restore sha', bj['restore_sha256'] == rel['restore_sha256'], bj['restore_sha256'][:12])
    tmp = pkgdir / '_osd.tmp'
    tmp.write_bytes(bytes(em[0x101]))
    p = X.OSD(component=tmp, check_hash=False)
    bad = same = 0
    for i in range(p.bitmap_count):
        a, b = p.descriptor(i), o.descriptor(i)
        if a['kind'] == 'rle':
            try:
                pa = p.decode_bitmap(a)[0]
            except Exception:
                bad += 1
                continue
        if i in IDS.values():
            continue
        same += (b['kind'] != 'rle' and a == b) or (b['kind'] == 'rle' and a == b and pa == o.decode_bitmap(b)[0])
    tmp.unlink()
    C('patched OSD reparses, all bitmaps decode strictly', bad == 0, f'{p.bitmap_count} bitmaps')
    C('every other bitmap byte-identical', same == p.bitmap_count - 4, str(same))
    dir_same = em[0x101][:0x800] == by[0x101].payload[:0x800]
    t = o.bitmap_table - o.base0 + o.resources[0]['offset']
    C('no directory or bitmap-table edit in the OSD', dir_same and em[0x101][t:t + 4 * o.bitmap_count] == by[0x101].payload[t:t + 4 * o.bitmap_count])
    good = True
    for key, i in IDS.items():
        r = p.descriptor(i)
        px, mode, _ = p.decode_bitmap(r)
        good &= (px == imgs[key].tobytes() and mode == 11 and r['extra'] == 0 and r['encoded_bytes'] <= o.descriptor(i)['encoded_bytes'])
    C('new ids decode to the intended pixels (mode 11, key 0, size <= original)', good)
    m = bytes(em[0x100])
    r32 = lambda a, n=1: struct.unpack_from(f'<{n}I', m, a - MB)
    def lst(a):
        return {struct.unpack_from('<I', m, a - MB + 12 * i)[0]: struct.unpack_from('<HH', m, a - MB + 12 * i + 4) for i in range(7)}
    la, lb = lst(LIST_A), lst(LIST_B)
    C('SCP record 270 -> 7 entries, 6/7 type 3 new ids',
      r32(0x61176fc0, 3) == (0x7010e, LIST_A, LIST_B) and la[6] == (3, 3732) and la[7] == (3, 5528) and lb[6] == (3, 3725) and lb[7] == (3, 5535))
    C('SCP stock values unchanged', all(la[v] == (3, w) and lb[v] == (3, g) for v, w, g in ((1, 477, 472), (3, 476, 471), (2, 478, 473), (4, 2422, 2421), (9, 479, 475))))
    C('row 16 -> same lists, count 7', r32(ROW16, 4) == (16, LIST_A, LIST_B, 7))
    info = lambda a: dict(struct.unpack_from('<14I', m, a - MB)[k:k + 2] for k in range(0, 14, 2))
    ia, ib = info(INFO_A), info(INFO_B)
    C('info lists -> new ids', ia[6] == 3732 and ia[7] == 5528 and ib[6] == 3725 and ib[7] == 5535)
    return ok


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    spec = json.loads(BASE.read_text())
    assert not any(e['kind'] == '0x101' for e in spec['edits'])
    o = X.OSD()
    imgs = images(o)
    oed, info = osd_edits(o, imgs)
    row = main_edits(spec)
    spec['edits'] += [row] + oed
    spec['aspect_icons'] = dict(ids={f'{k[0]}_{k[1]}': v for k, v in info.items()}, base='releases/v0.25/edits.json')
    sp = OUT / 'edits.json'
    sp.write_text(json.dumps(spec))
    previews(o, imgs, OUT / 'previews')
    pkg = OUT / 'pkg'
    if pkg.exists():
        subprocess.check_call(['rm', '-rf', str(pkg)])
    subprocess.check_call([sys.executable, '-I', str(ROOT / 'tools/build_package.py'), str(sp), '--out', str(pkg)], stdout=subprocess.DEVNULL)
    print(json.dumps(spec['aspect_icons']['ids']))
    res = checks(spec, o, imgs, pkg)
    (OUT / 'checks.json').write_text(json.dumps(res, indent=1))
    if not all(c[1] for c in res):
        sys.exit('CHECK FAILED')
    print('ALL PASS', len(res))


if __name__ == '__main__':
    main()
