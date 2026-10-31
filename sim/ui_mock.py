#!/usr/bin/env python3
"""Render a data-driven PNG mock of the E-P7 rear LCD (720x480 logical canvas).

A screen is a JSON file: canvas, background and an ordered list of elements.
Firmware assets (bitmaps, @A0xx@ symbols, font glyphs, English strings,
candidate palette) are decoded on the fly from the stock components through
tools/osd_extract.py; nothing is copied into this repo.

Element types (all coordinates in canvas pixels, origin top-left):
  bitmap       {"id": 7567, "x", "y", "anchor"?}         OSD bitmap by table index
  symbol       {"code": "A017", "x", "y"}                 inline text symbol
  text         {"text": "...", | "string_id": 2749, "x", "y", "fg"?: 4,
                "scale"?: 1.0, "anchor"?: "tl"|"tc"|"tr"|"cl"|"cc"...}
               firmware font resource 35 (ASCII only) + @A0xx@ tokens
  rect         {"box": [x, y, w, h], "fill"?: c, "outline"?: c, "width"?: 1}
  color_wheel  {"cx", "cy", "r_outer", "r_inner", "values": [12], "selected",
                "range": 5, "start_deg"?: 90}   PROCEDURAL approximation
  aspect_frame {"aspect": "65:24", "mask"?: c, "line"?: c, "label"?: bool}
  watermark    {"text": "MOCK", "fg"?: 13}
Colours "c" are palette indices (int) into the candidate 8-bit palette or
"#AARRGGBB" strings.

Run:  .venv/bin/python -I sim/ui_mock.py sim/screens/color_profile.json
      (writes generated/mock/<screen name>.png; --scale 2 for a larger view)
"""
import argparse
import colorsys
import importlib.util
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def load_extractor():
    spec = importlib.util.spec_from_file_location('osd_extract', ROOT / 'tools/osd_extract.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Assets:
    def __init__(self, palette8=None, palette4=None):
        self.m = load_extractor()
        self.osd = self.m.OSD()
        self.pal8 = self.osd.palette(palette8 or self.m.DEFAULT_PALETTE8)
        self.pal4 = self.osd.palette(palette4 or self.m.DEFAULT_PALETTE4)
        self._font = None
        self._strings = None
        self._cache = {}

    def color(self, c):
        if isinstance(c, int):
            v = self.pal8[c]
            if v == 0x01010101:
                raise ValueError(f'palette index {c} is unpopulated in the candidate palette')
            return self.m.argb_to_rgba(v)
        if isinstance(c, str) and c.startswith('#') and len(c) == 9:
            v = int(c[1:], 16)
            return ((v >> 16) & 255, (v >> 8) & 255, v & 255, v >> 24)
        raise ValueError(f'bad colour {c!r}')

    def bitmap(self, index):
        key = ('b', index)
        if key not in self._cache:
            row = self.osd.descriptor(index)
            if row['kind'] != 'rle':
                raise ValueError(f'bitmap {index} has no decodable payload ({row["kind"]})')
            px, mode, _ = self.osd.decode_bitmap(row)
            pal = self.pal8 if self.m.MODES[mode][0] == 8 else self.pal4
            self._cache[key] = self.m.rgba_image(px, row['width'], row['height'], pal)
        return self._cache[key]

    def _levels(self, fg):
        return self.m.level_palette(self.pal8, fg)

    def symbol(self, code, fg=4):
        key = ('s', code, fg)
        if key not in self._cache:
            row, px = self.osd.symbol(int(code[1:], 16))
            self._cache[key] = self.m.rgba_image(px, row['width'], row['height'], self._levels(fg))
        return self._cache[key]

    def glyph(self, ch, fg=4):
        if self._font is None:
            self._font = self.osd.font(35)[1]
        cp = ord(ch)
        if not 0x20 <= cp <= 0x7e:
            raise ValueError(f'character {ch!r}: only ASCII 0x20-0x7E has a verified glyph mapping')
        key = ('g', cp, fg)
        if key not in self._cache:
            g = self._font[cp - 0x20]
            self._cache[key] = self.m.rgba_image(g['pixels'], g['width'], g['height'], self._levels(fg))
        return self._cache[key]

    def string(self, index):
        if self._strings is None:
            self._strings = self.osd.strings(8)[1]
        return self._strings[index]


def tokenize(text):
    """Split into ('char', c) and ('sym', 'A0xx') items; @A0xx@ = symbol."""
    out, i = [], 0
    while i < len(text):
        if text[i] == '@' and i + 5 < len(text) and text[i + 5] == '@' and text[i + 1] in 'Aa':
            out.append(('sym', 'A' + text[i + 2:i + 5].upper()))
            i += 6
        else:
            out.append(('char', text[i]))
            i += 1
    return out


def render_text(assets, text, fg=4, scale=1.0, spacing=1):
    """Lay out firmware glyphs on a 40-px line; symbols are vertically centred."""
    parts = []
    for kind, v in tokenize(text):
        if kind == 'char' and v in '\r\n':
            v = ' '
        parts.append(assets.glyph(v, fg) if kind == 'char' else assets.symbol(v, fg))
    line_h = max([40] + [p.height for p in parts])
    width = sum(p.width + spacing for p in parts)
    img = Image.new('RGBA', (max(1, width), line_h))
    x = 0
    for p in parts:
        img.alpha_composite(p, (x, (line_h - p.height) // 2))
        x += p.width + spacing
    if scale != 1.0:   # host-side resampling; the camera draws native sizes
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                         Image.Resampling.LANCZOS)
    return img


def place(canvas, img, x, y, anchor='tl'):
    ax = {'l': 0, 'c': img.width // 2, 'r': img.width}[anchor[1]]
    ay = {'t': 0, 'c': img.height // 2, 'b': img.height}[anchor[0]]
    canvas.alpha_composite(img, (int(x - ax), int(y - ay)))


def draw_wheel(assets, canvas, e):
    """Procedural 12-sector wheel. The stock wheel is drawn at runtime by the
    C3D engine (BackGroundCtrl::drawC3dAsync); its geometry/colours are NOT
    known. This is an approximation for layout only."""
    cx, cy, ro, ri = e['cx'], e['cy'], e['r_outer'], e['r_inner']
    rng, values = e.get('range', 5), e['values']
    start = e.get('start_deg', 90)          # sector 0 centre angle (math convention)
    layer = Image.new('RGBA', canvas.size)
    d = ImageDraw.Draw(layer)
    for k in range(12):                       # hue ring
        a0 = -(start + 30 * k) - 15
        r, g, b = colorsys.hsv_to_rgb((k / 12.0) % 1, 0.85, 1.0)
        d.pieslice([cx - ro, cy - ro, cx + ro, cy + ro], a0, a0 + 30,
                   fill=(int(r * 255), int(g * 255), int(b * 255), 255))
    d.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], fill=assets.color(e.get('inner_fill', '#cc000000')))
    guide = assets.color(e.get('guide', 6))
    r0 = ri * 0.08
    for lv in range(-rng, rng + 1):            # level guide circles
        rr = r0 + (lv + rng) / (2 * rng) * (ri * 0.92 - r0)
        if lv in (-rng, 0, rng):
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=guide, width=1)
    pts = []
    for k, v in enumerate(values):
        ang = math.radians(start + 30 * k)
        rr = r0 + (v + rng) / (2 * rng) * (ri * 0.92 - r0)
        pts.append((cx + rr * math.cos(ang), cy - rr * math.sin(ang)))
        d.line([(cx, cy), (cx + ri * math.cos(ang), cy - ri * math.sin(ang))], fill=guide, width=1)
    d.polygon(pts, outline=assets.color(e.get('polygon', 4)), width=2)
    for p in pts:
        d.ellipse([p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3], fill=assets.color(4))
    sel = e.get('selected')
    if sel is not None:
        a0 = -(start + 30 * sel) - 15
        d.arc([cx - ro - 3, cy - ro - 3, cx + ro + 3, cy + ro + 3], a0, a0 + 30,
              fill=assets.color(e.get('select_colour', 1)), width=6)
        ang = math.radians(start + 30 * sel)
        d.line([(cx, cy), (cx + ri * math.cos(ang), cy - ri * math.sin(ang))],
               fill=assets.color(e.get('select_colour', 1)), width=2)
    canvas.alpha_composite(layer)


def draw_aspect_frame(assets, canvas, e):
    """Centre a W:H frame inside the canvas (full width or full height)."""
    aw, ah = (float(x) for x in e['aspect'].split(':'))
    W, H = canvas.size
    if W / H > aw / ah:
        h, w = H, round(H * aw / ah)
    else:
        w, h = W, round(W * ah / aw)
    x0, y0 = (W - w) // 2, (H - h) // 2
    layer = Image.new('RGBA', canvas.size)
    d = ImageDraw.Draw(layer)
    mask = assets.color(e.get('mask', '#99000000'))
    for box in ([0, 0, W, y0], [0, y0 + h, W, H], [0, 0, x0, H], [x0 + w, 0, W, H]):
        if box[2] > box[0] and box[3] > box[1]:
            d.rectangle([box[0], box[1], box[2] - 1, box[3] - 1], fill=mask)
    d.rectangle([x0, y0, x0 + w - 1, y0 + h - 1], outline=assets.color(e.get('line', 4)), width=1)
    canvas.alpha_composite(layer)
    if e.get('label', True):
        place(canvas, render_text(assets, e['aspect'], 4, 0.6), x0 + 6, y0 + 4)
    return dict(aspect=e['aspect'], box=[x0, y0, w, h])


def placeholder_background(size):
    """Synthetic stand-in for live view (no firmware or photo content)."""
    w, h = size
    img = Image.new('RGBA', size)
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = y / h
            px[x, y] = (int(40 + 50 * t + 20 * (x / w)), int(55 + 40 * t), int(70 + 10 * t), 255)
    d = ImageDraw.Draw(img)
    d.text((8, 70), 'live view placeholder', fill=(150, 150, 150, 255))
    return img


def render(screen, assets):
    W, H = screen.get('canvas', [720, 480])
    bg = screen.get('background', {'type': 'placeholder'})
    if bg['type'] == 'solid':
        canvas = Image.new('RGBA', (W, H), assets.color(bg['colour']))
    elif bg['type'] == 'image':
        # live-view stand-in: any rendered photo (e.g. a film-sim render), centre-cropped to the canvas
        im = Image.open(Path(bg['path']) if Path(bg['path']).is_absolute() else ROOT / bg['path']).convert('RGBA')
        sc = max(W / im.width, H / im.height)
        im = im.resize((round(im.width * sc), round(im.height * sc)), Image.BILINEAR)
        x, y = (im.width - W) // 2, (im.height - H) // 2
        canvas = im.crop((x, y, x + W, y + H))
    else:
        canvas = placeholder_background((W, H))
    log = []
    for e in screen['elements']:
        t = e['type']
        if t == 'bitmap':
            place(canvas, assets.bitmap(e['id']), e['x'], e['y'], e.get('anchor', 'tl'))
        elif t == 'symbol':
            place(canvas, assets.symbol(e['code'], e.get('fg', 4)), e['x'], e['y'], e.get('anchor', 'tl'))
        elif t == 'text':
            text = e['text'] if 'text' in e else assets.string(e['string_id'])
            place(canvas, render_text(assets, text, e.get('fg', 4), e.get('scale', 1.0)),
                  e['x'], e['y'], e.get('anchor', 'tl'))
        elif t == 'rect':
            x, y, w, h = e['box']
            layer = Image.new('RGBA', canvas.size)
            ImageDraw.Draw(layer).rectangle(
                [x, y, x + w - 1, y + h - 1],
                fill=assets.color(e['fill']) if 'fill' in e else None,
                outline=assets.color(e['outline']) if 'outline' in e else None,
                width=e.get('width', 1))
            canvas.alpha_composite(layer)
        elif t == 'color_wheel':
            draw_wheel(assets, canvas, e)
        elif t == 'aspect_frame':
            log.append(draw_aspect_frame(assets, canvas, e))
        elif t == 'watermark':
            img = render_text(assets, e.get('text', 'MOCK'), e.get('fg', 13), e.get('scale', 1.0))
            place(canvas, img, e.get('x', W // 2), e.get('y', 4), e.get('anchor', 'tc'))
        else:
            raise ValueError(f'unknown element type {t!r}')
    return canvas, log


def with_caption(canvas, lines):
    """Notes go in a strip below the 720x480 canvas, never on it."""
    if not lines:
        return canvas
    out = Image.new('RGBA', (canvas.width, canvas.height + 14 * len(lines) + 6), (20, 20, 20, 255))
    out.alpha_composite(canvas)
    d = ImageDraw.Draw(out)
    for k, line in enumerate(lines):
        d.text((6, canvas.height + 4 + 14 * k), line, fill=(220, 220, 120, 255))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('screens', nargs='+', type=Path)
    ap.add_argument('--out', type=Path, default=ROOT / 'generated/mock')
    ap.add_argument('--scale', type=int, default=1, help='nearest-neighbour upscale of the output')
    args = ap.parse_args()
    assets = Assets()
    args.out.mkdir(parents=True, exist_ok=True)
    for path in args.screens:
        screen = json.loads(path.read_text())
        canvas, log = render(screen, assets)
        img = with_caption(canvas, screen.get('notes', []))
        if args.scale > 1:
            img = img.resize((img.width * args.scale, img.height * args.scale), Image.Resampling.NEAREST)
        dest = args.out / f'{screen["name"]}.png'
        img.save(dest)
        print(json.dumps(dict(screen=str(path), png=str(dest), frames=log)))


if __name__ == '__main__':
    main()
