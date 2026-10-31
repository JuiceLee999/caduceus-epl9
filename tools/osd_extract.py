#!/usr/bin/env python3
"""Extract E-P7 1.1 (build 1100) OSD resources (component kind 0x101). Read-only.

Exports bitmaps, inline text symbols, language font glyphs, English UI strings
and the candidate OSD palettes (from the main program) into generated/osd/.

Everything is derived from the decoded component; runtime bases are found by
structural search and asserted unique, not hard-coded. Decoders are strict:
exact pixel count, header dimensions equal to descriptor dimensions, zero
group/trailing padding. A strict decode is structural evidence only; visual
validation is recorded separately in docs/OSD.md.

Colours in exported PNGs come from a *candidate* palette (see docs/OSD.md).
PNGs are palette ("P") images whose pixel values are the raw firmware indices,
so the indices survive even if the candidate colours are wrong.

Run:  .venv/bin/python -I tools/osd_extract.py            (writes generated/osd)
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / 'analysis/ep7_1100'
COMPONENT = ANALYSIS / '01_0101_421a0020.decoded.bin'
MAIN = ANALYSIS / '00_0100_406a0020.decoded.bin'
COMPONENT_SHA = '8606cb90e06b67aee31a1b4319b585905b66e4e3ee29c903bd328aa33b362868'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
COMPONENT_ADDR = 0x421a0020   # directory pointers are absolute in this space
MAIN_BASE = 0x60020020        # verified CPU mapping of the main program (WORKLOG)

# Candidate palettes in the main program (CPU addresses of entry 0). Unverified
# runtime selection: chosen because they render the visually checked icons
# plausibly and are the only fully populated opaque 128-/16-entry blocks.
DEFAULT_PALETTE8 = 0x61110e7c
DEFAULT_PALETTE4 = 0x6111570c
GLYPH_FG = 4  # palette 4/5/6 = fefefe/aaaaaa/555555 (white ramp)

# Stream mode byte (4th header byte) -> (index bits, run bits, token bits).
# Tokens are little-endian inside 64-bit groups, floor(64/token bits) per
# group; unused top bits of each group must be zero. For 4- and 8-bit tokens
# this is the same as a plain nibble/byte stream. run = (token & runmask) + 1,
# index = token >> run bits.  Mode 3 is fishcu's PEN-F format-3 (not seen on
# E-P7). Modes 1, 9, 10, 11 are validated on E-P7 data (see docs/OSD.md).
MODES = {1: (2, 2, 4), 3: (8, 2, 10), 9: (2, 6, 8), 10: (4, 4, 8), 11: (8, 4, 12)}


class FormatError(ValueError):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def stream_header(data):
    """Return (width, height, mode) from a 4-byte RLE stream header."""
    height = (data[0] | ((data[1] & 3) << 8)) + 1
    width = ((data[1] >> 4) | ((data[2] & 63) << 4)) + 1
    return width, height, data[3]


def decode_rle(data, width=None, height=None, exact_extent=True):
    """Decode one RLE stream. Returns (indices bytes, width, height, mode, used bytes).

    exact_extent=True: `data` is the whole allocated extent; every byte after
    the last token must be zero. False: `data` may continue with other data
    (font glyph streams are packed back to back); used length is returned.
    """
    if len(data) < 4:
        raise FormatError('stream shorter than header')
    w, h, mode = stream_header(data)
    if width is not None and (w, h) != (width, height):
        raise FormatError(f'header {w}x{h} != descriptor {width}x{height}')
    if mode not in MODES:
        raise FormatError(f'unsupported stream mode {mode}')
    ibits, rbits, tbits = MODES[mode]
    per = 64 // tbits
    rmask, tmask = (1 << rbits) - 1, (1 << tbits) - 1
    total = w * h
    out = bytearray()
    t = 0
    word = 0
    group_off = -1
    while len(out) < total:
        g, slot = divmod(t, per)
        off = 4 + 8 * g
        if off != group_off:
            chunk = data[off:off + 8]
            need = (tbits * (slot + 1) + 7) // 8
            if len(chunk) < need:
                raise FormatError(f'truncated after {len(out)}/{total} pixels')
            word = int.from_bytes(chunk, 'little')
            if len(chunk) == 8 and word >> (tbits * per):
                raise FormatError('nonzero group padding')
            group_off = off
        tok = (word >> (tbits * slot)) & tmask
        run = (tok & rmask) + 1
        if len(out) + run > total:
            raise FormatError('run crosses declared image end')
        out += bytes([tok >> rbits]) * run
        t += 1
    used_bits = 32 + 64 * ((t - 1) // per) + tbits * ((t - 1) % per + 1)
    used = (used_bits + 7) // 8
    if exact_extent:
        # bits after the last token in its group (incl. group padding), then
        # every byte after that group, must be zero
        if slot + 1 < per and word >> (tbits * (slot + 1)):
            raise FormatError('nonzero bits after last token')
        if any(data[group_off + 8:]):
            raise FormatError('nonzero trailing padding')
    return bytes(out), w, h, mode, used


class OSD:
    """Parsed view of the E-P7 OSD component plus palettes from main."""

    def __init__(self, component=COMPONENT, main=MAIN, check_hash=True):
        self.data = Path(component).read_bytes()
        self.main = Path(main).read_bytes()
        if check_hash:
            if sha256(self.data) != COMPONENT_SHA:
                raise SystemExit('OSD component hash mismatch: need stock E-P7 1.1 kind 0x101')
            if sha256(self.main) != MAIN_SHA:
                raise SystemExit('main component hash mismatch: need stock E-P7 1.1 kind 0x100')
        self.resources = self._directory()
        r0 = self.resources[0]
        self.bank0 = self.data[r0['offset']:r0['offset'] + r0['size']]
        hdr = struct.unpack_from('<5I', self.bank0, 0)
        self.bank0_header = hdr
        self.symbol_table, self.bitmap_table = hdr[0], hdr[4]
        self.base0 = self._find_bank0_base()
        r69 = self.resources[69]
        self.bank69 = self.data[r69['offset']:r69['offset'] + r69['size']]
        self.bitmap_count = (self.symbol_table - self.bitmap_table) // 4
        self.base69 = self._find_bank69_base()
        self.symbol_count = self._symbol_count()
        self._palettes = None

    # ---------- directory and address resolution ----------
    def _directory(self):
        first, = struct.unpack_from('<I', self.data, 0)
        n = (first - COMPONENT_ADDR) // 16
        out = {}
        for i in range(n):
            p, size, x, y = struct.unpack_from('<4I', self.data, 16 * i)
            if size == 0:
                continue
            if x or y:
                raise FormatError(f'directory record {i} has nonzero reserved words')
            off = p - COMPONENT_ADDR
            if not (16 * n <= off and off + size <= len(self.data)):
                raise FormatError(f'directory record {i} out of bounds')
            out[i] = dict(index=i, address=p, offset=off, size=size)
        return out

    def _find_bank0_base(self):
        """Unique base b such that the symbol table at header[0]-b points at
        (w,h,ptr) descriptors whose streams carry matching header dimensions."""
        bank, size, p0 = self.bank0, len(self.bank0), self.symbol_table
        hits = []
        for t in range(0, size - 16, 4):
            b = p0 - t
            ok = True
            for k in range(4):
                e, = struct.unpack_from('<I', bank, t + 4 * k)
                o = e - b
                if not 0 <= o <= size - 8:
                    ok = False
                    break
                w, h, ptr = struct.unpack_from('<HHI', bank, o)
                s = ptr - b
                if not (0 <= s < o and o - s < 65536) or stream_header(bank[s:s + 4])[:2] != (w, h):
                    ok = False
                    break
            if ok:
                hits.append(b)
        if len(hits) != 1:
            raise FormatError(f'bank 0 base not unique: {[hex(h) for h in hits]}')
        return hits[0]

    def _bitmap_pointers(self):
        b = self.base0
        return [struct.unpack_from('<I', self.bank0, self.bitmap_table - b + 4 * i)[0]
                for i in range(self.bitmap_count)]

    def _find_bank69_base(self):
        """Unique base for resource 69 such that every bitmap descriptor
        pointer outside bank 0 lands on a well-formed descriptor."""
        lo, hi = self.base0, self.base0 + len(self.bank0)
        outside = [p for p in self._bitmap_pointers() if p and not lo <= p < hi]
        size = len(self.bank69)
        q0 = min(outside)
        cands = []
        for pos in range(0, size - 24, 2):
            if struct.unpack_from('<H', self.bank69, pos)[0] in (1, 5, 14):
                b = q0 - pos
                if max(outside) - b <= size - 20:
                    cands.append(b)
        sample = outside[::max(1, len(outside) // 64)]

        def plausible(b, q):
            f = struct.unpack_from('<6H2I', self.bank69, q - b)
            if f[0] == 1:
                return f[1] == f[2] == f[6] == f[7] == 0
            if f[0] in (5, 14):
                return b <= f[7] and 0 <= q - f[7] - f[6] < 8
            return False
        hits = [b for b in cands if all(plausible(b, q) for q in sample)]
        if len(hits) != 1:
            raise FormatError(f'bank 69 base not unique: {[hex(h) for h in hits]}')
        return hits[0]

    def read(self, pointer, size):
        """Read from bank 0 or bank 69 by runtime pointer, bounds-checked."""
        for base, bank in ((self.base0, self.bank0), (self.base69, self.bank69)):
            off = pointer - base
            if 0 <= off and off + size <= len(bank):
                return bank[off:off + size]
        raise FormatError(f'pointer {pointer:#x}+{size} outside banks 0/69')

    def component_offset(self, pointer):
        for base, bank, res in ((self.base0, self.bank0, 0), (self.base69, self.bank69, 69)):
            off = pointer - base
            if 0 <= off < len(bank):
                return self.resources[res]['offset'] + off
        return None

    # ---------- bitmaps ----------
    def descriptor(self, index):
        if not 0 <= index < self.bitmap_count:
            raise IndexError(index)
        p, = struct.unpack('<I', self.read(self.bitmap_table + 4 * index, 4))
        if p == 0:
            return dict(id=index, descriptor=0, kind='null')
        fmt, w, h, f6, u1, u2, size, payload = struct.unpack('<6H2I', self.read(p, 20))
        row = dict(id=index, descriptor=p, bank=0 if self.base0 <= p < self.base0 + len(self.bank0) else 69,
                   descriptor_offset=self.component_offset(p), fmt=fmt, width=w, height=h,
                   field6=f6, reserved=[u1, u2], encoded_bytes=size, payload=payload)
        if fmt == 14:   # 24-byte record; meaning of the last word unknown
            row['extra'], = struct.unpack('<I', self.read(p + 20, 4))
        if fmt == 1 and not (w or h or size or payload):
            row['kind'] = 'placeholder'
        elif fmt in (5, 14) and payload:
            row['kind'] = 'rle'
            row['payload_offset'] = self.component_offset(payload)
        else:
            row['kind'] = 'unknown'
        return row

    def decode_bitmap(self, row):
        data = self.read(row['payload'], row['encoded_bytes'])
        px, w, h, mode, used = decode_rle(data, row['width'], row['height'])
        if MODES[mode][0] != row['field6']:
            raise FormatError(f'field6={row["field6"]} but stream mode {mode} has {MODES[mode][0]}-bit indices')
        return px, mode, data

    # ---------- inline text symbols (@A0xx@) ----------
    def _symbol_count(self):
        n = 0
        while True:
            p, = struct.unpack('<I', self.read(self.symbol_table + 4 * n, 4))
            if not self.base0 <= p < self.base0 + len(self.bank0):
                return n
            n += 1

    def symbol(self, index):
        p, = struct.unpack('<I', self.read(self.symbol_table + 4 * index, 4))
        w, h, ptr = struct.unpack('<HHI', self.read(p, 8))
        if not ptr < p:
            raise FormatError('symbol stream does not precede descriptor')
        data = self.read(ptr, p - ptr)
        px, _w, _h, mode, _used = decode_rle(data, w, h)
        return dict(code=f'A{index:03X}', token=f'@A{index:03X}@', width=w, height=h,
                    descriptor=p, payload=ptr, payload_offset=self.component_offset(ptr),
                    encoded_bytes=len(data), mode=mode), px

    # ---------- language strings ----------
    def string_resources(self):
        return [i for i in range(1, 35) if i in self.resources]

    def _solve_string_base(self, res):
        r = self.resources[res]
        blob = self.data[r['offset']:r['offset'] + r['size']]
        p0, p1 = struct.unpack_from('<2I', blob, 0)
        hits = set()
        for t in range(0, len(blob) - 4, 2):
            e0, = struct.unpack_from('<I', blob, t)
            for k in (8, 10):          # first string follows the 8-byte header
                if p0 - (e0 - k) == t:
                    hits.add(e0 - k)
        if len(hits) != 1:
            raise FormatError(f'string resource {res} base not unique: {hits}')
        return hits.pop(), blob, p0, p1

    def strings(self, res):
        base, blob, p0, p1 = self._solve_string_base(res)
        out = []
        for k in range((p1 - p0) // 4):
            e, = struct.unpack_from('<I', blob, p0 - base + 4 * k)
            q = e - base
            if not 0 <= q < len(blob):
                out.append(None)
                continue
            z = q
            while blob[z:z + 2] != b'\0\0':
                z += 2
            out.append(blob[q:z].decode('utf-16le'))
        return base, out

    # ---------- language fonts ----------
    def font_resources(self):
        return [i for i in range(35, 69) if i in self.resources]

    FONT_BASE = 0xa3fb7540   # inferred, see docs/OSD.md; checked per resource below

    def font(self, res):
        """Return (info, glyphs) for a language font resource (35..68).

        Glyph streams (mode 9) are packed back to back after a block of
        16-byte size records and zero padding. The start is located by
        scanning for the first 4-aligned offset (>= 8) from which
        a chain of three streams decodes; then streams are decoded until the
        next byte is not a valid stream header.
        """
        r = self.resources[res]
        blob = self.data[r['offset']:r['offset'] + r['size']]
        p0, p1 = struct.unpack_from('<2I', blob, 0)
        base = self.FONT_BASE
        if not (0 < p0 - base < len(blob) and 0 < p1 - base < len(blob)):
            raise FormatError(f'font resource {res}: header pointers outside resource under base {base:#x}')
        cnt, size_key, rec_ptr = struct.unpack_from('<3I', blob, p0 - base)
        if not 8 <= rec_ptr - base < len(blob):
            raise FormatError(f'font resource {res}: record pointer outside resource')
        start = None
        for s0 in range(8, min(len(blob), 0x1000), 4):
            if blob[s0 + 3] != 9:
                continue
            try:
                pos = s0
                for _ in range(3):
                    pos += decode_rle(blob[pos:], exact_extent=False)[4]
            except FormatError:
                continue
            start = s0
            break
        if start is None:
            raise FormatError(f'font resource {res}: no glyph stream chain found')
        pos = start
        glyphs = []
        while pos + 4 <= len(blob) and blob[pos + 3] in MODES:
            px, w, h, mode, used = decode_rle(blob[pos:], exact_extent=False)
            glyphs.append(dict(index=len(glyphs), offset=r['offset'] + pos, width=w, height=h,
                               mode=mode, encoded_bytes=used, pixels=px))
            pos += used
        info = dict(resource=res, base=base, glyph_start=r['offset'] + start,
                    glyph_start_rel=start, header_struct=dict(word0=cnt, word1=size_key, record_ptr=hex(rec_ptr)),
                    glyph_count=len(glyphs), glyph_data_end=r['offset'] + pos)
        return info, glyphs

    # ---------- palettes in the main program ----------
    def palettes(self):
        """256-entry AARRGGBB blocks: [u32 0x100][u32 self-0x408][256 x u32]."""
        if self._palettes is None:
            import re
            m, out = self.main, []
            for hit in re.finditer(rb'\x00\x01\x00\x00....\xff\xff\xff\x00', m, re.DOTALL):
                off = hit.start() + 8
                if off % 4 or off + 1024 > len(m):
                    continue
                addr = MAIN_BASE + off
                if struct.unpack_from('<I', m, off - 4)[0] == addr - 0x408:
                    ent = list(struct.unpack_from('<256I', m, off))
                    out.append(dict(address=addr, offset=off, entries=ent,
                                    populated=sum(e != 0x01010101 for e in ent)))
            self._palettes = out
        return self._palettes

    def palette(self, address):
        off = address - MAIN_BASE
        return list(struct.unpack_from('<256I', self.main, off))


# ---------- image helpers ----------
def argb_to_rgba(v):
    if v == 0x01010101:            # unpopulated entry marker (shown magenta)
        return (255, 0, 255, 255)
    return ((v >> 16) & 255, (v >> 8) & 255, v & 255, v >> 24)


def palette_image(px, w, h, argb):
    """P-mode image: raw indices + candidate palette with alpha (tRNS)."""
    from PIL import Image
    im = Image.frombytes('P', (w, h), px)
    rgba = [argb_to_rgba(v) for v in argb[:256]]
    im.putpalette([c for rgb in rgba for c in rgb[:3]])
    im.info['transparency'] = bytes(c[3] for c in rgba)
    return im


def level_palette(argb8, fg=GLYPH_FG):
    """2-bit glyph levels -> palette [0, fg+2, fg+1, fg] (PEN-F rule, see docs)."""
    return [argb8[0], argb8[fg + 2], argb8[fg + 1], argb8[fg]]


def rgba_image(px, w, h, argb):
    from PIL import Image
    im = Image.new('RGBA', (w, h))
    lut = [argb_to_rgba(v) for v in argb]
    im.putdata([lut[v] for v in px])
    return im


def checker(w, h, cell=8):
    from PIL import Image, ImageDraw
    im = Image.new('RGBA', (w, h), (58, 58, 58, 255))
    d = ImageDraw.Draw(im)
    for y in range(0, h, cell):
        for x in range((y // cell) % 2 * cell, w, 2 * cell):
            d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(78, 78, 78, 255))
    return im


def contact_sheet(items, path, cols=20, cell=(80, 64), label=lambda it: str(it[0])):
    """items: list of (key, RGBA image)."""
    from PIL import ImageDraw
    cw, ch = cell
    rows = max(1, (len(items) + cols - 1) // cols)
    sheet = checker(cols * cw, rows * ch)
    d = ImageDraw.Draw(sheet)
    for k, it in enumerate(items):
        im = it[1].copy()
        im.thumbnail((cw - 2, ch - 12))
        x, y = (k % cols) * cw, (k // cols) * ch
        sheet.alpha_composite(im, (x + 1, y + 11))
        d.text((x + 1, y - 1), label(it), fill=(255, 255, 0, 255))
    sheet.save(path)


# Visual identifications (role is a judgement from the decoded picture, not
# from code references). See docs/OSD.md before relying on any of these.
IDENTIFIED = {
    'color_profile_badges': {'ids': [4344, 4345, 4346, 4350, 4351, 4352, 7531, 7530, 4534, 4535, 4536],
                             'note': '"COLOR 1..4" badges, yellow (selected?) and white variants'},
    'mono_profile_badges': {'ids': [4347, 4348, 4349, 4353, 4354, 4355, 7529, 7528, 4537, 4538],
                            'note': '"MONO 1..4" badges'},
    'profile_mode_icons': {'ids': [714, 715, 716, 717, 718, 1095, 1096, 1097, 1098, 1099],
                           'note': 'rainbow (likely Color Profile), split orange/blue, black/white (likely Monochrome), two unknown'},
    'reset_guides': {'ids': [7567, 3509, 3510], 'note': '"ALL Reset / OK Hold", "Reset", "OK Hold" button guides'},
    'colour_edit_text_labels': {'ids': [4215, 4216, 4221, 4222, 4223, 4224, 4225, 4226],
                                'note': 'Highlight, Shadow, Color, Vivid, Color Filter, Level, Off, All (pre-rendered text)'},
    'colour_swatches': {'ids': [4227, 4228, 4229, 4230, 4231, 4232, 4233] + list(range(7552, 7566)),
                        'note': 'solid colour chips; role unidentified (filter/mono colour?)'},
    'tone_curves': {'ids': list(range(4155, 4215)) + [7574, 7575],
                    'note': 'Highlight&Shadow curve graphics (262x266 / 131x136) and grid'},
    'aspect_icons': {'ids': [16, 17, 18, 471, 472, 473, 474, 475, 476, 477, 478, 479, 2421, 2422, 2423,
                             2630, 989, 1584, 4988, 4989, 5866, 5867, 5868, 5869, 5870, 5871],
                     'note': '16:9 4:3 3:2 3:4 1:1 17:9 labels'},
    'aspect_sized_grids': {'ids': [5996, 5997, 5998, 6000, 6002, 6010, 6011, 6012, 6013, 6014, 6084, 6118],
                           'note': 'live-view grid overlays sized per aspect: 720x480 (3:2), 640x480 (4:3), '
                                   '720x405 (16:9), 480x480 (1:1), 360x480 (3:4); 6xx/7xx x474 variants'},
    'menu_selection_frames': {'ids': [4656, 4776, 4800, 5149, 5150, 6309, 6313, 6389, 6557, 5574],
                              'note': 'blue cell with yellow/orange border (selected item backgrounds)'},
    'menu_tab_icons': {'ids': list(range(4706, 4746)), 'note': 'shooting/video/playback/custom/setup tab icons'},
    'button_guides': {'ids': [1387, 1388, 1389, 1185, 1186, 5543, 5544, 5545], 'note': 'OK / MENU / INFO guides'},
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, default=ROOT / 'generated/osd')
    ap.add_argument('--component', type=Path, default=COMPONENT)
    ap.add_argument('--main', type=Path, default=MAIN)
    ap.add_argument('--palette8', type=lambda s: int(s, 0), default=DEFAULT_PALETTE8)
    ap.add_argument('--palette4', type=lambda s: int(s, 0), default=DEFAULT_PALETTE4)
    ap.add_argument('--no-bitmap-pngs', action='store_true', help='catalog/atlas only')
    args = ap.parse_args()

    osd = OSD(args.component, args.main)
    out = args.out
    for sub in ('bitmaps', 'symbols', 'fonts', 'atlas'):
        (out / sub).mkdir(parents=True, exist_ok=True)
    pal8, pal4 = osd.palette(args.palette8), osd.palette(args.palette4)
    glyph_pal = level_palette(pal8)

    # Bitmaps
    bitmaps, thumbs, failures = [], [], []
    for i in range(osd.bitmap_count):
        row = osd.descriptor(i)
        if row['kind'] == 'rle':
            try:
                px, mode, data = osd.decode_bitmap(row)
            except FormatError as e:
                row.update(status='undecoded', error=str(e))
                failures.append(row)
            else:
                pal = pal8 if MODES[mode][0] == 8 else pal4
                row.update(status='decoded', stream_mode=mode, index_bits=MODES[mode][0],
                           indices_used=sorted(set(px)), payload_sha256=sha256(data),
                           png=f'bitmaps/b{i:04d}.png')
                if not args.no_bitmap_pngs:
                    palette_image(px, row['width'], row['height'], pal).save(out / row['png'], optimize=True)
                im = rgba_image(px, row['width'], row['height'], pal)
                im.thumbnail((78, 52))
                thumbs.append((i, im))
        else:
            row['status'] = row['kind']
        for k in ('descriptor', 'payload', 'descriptor_offset', 'payload_offset'):
            if row.get(k) is not None:
                row[k] = hex(row[k])
        bitmaps.append(row)
    per = 280
    for s in range(0, len(thumbs), per):
        contact_sheet(thumbs[s:s + per], out / f'atlas/bitmaps_{s // per:02d}.png')
    thumbs = None

    # Symbols
    symbols, sym_imgs = [], []
    for i in range(osd.symbol_count):
        row, px = osd.symbol(i)
        row['png'] = f'symbols/{row["code"]}.png'
        palette_image(px, row['width'], row['height'], glyph_pal).save(out / row['png'])
        sym_imgs.append((row['token'], rgba_image(px, row['width'], row['height'], glyph_pal)))
        for k in ('descriptor', 'payload', 'payload_offset'):
            row[k] = hex(row[k])
        symbols.append(row)
    contact_sheet(sym_imgs, out / 'atlas/symbols.png', cols=16, cell=(90, 56))

    # Fonts
    fonts = []
    for res in osd.font_resources():
        info, glyphs = osd.font(res)
        imgs = [(g['index'], rgba_image(g['pixels'], g['width'], g['height'], glyph_pal)) for g in glyphs]
        contact_sheet(imgs, out / f'fonts/font_r{res}.png', cols=24, cell=(48, 56))
        if res == 35:
            (out / 'fonts/r35').mkdir(exist_ok=True)
            for g in glyphs:
                palette_image(g['pixels'], g['width'], g['height'], glyph_pal).save(out / f'fonts/r35/g{g["index"]:03d}.png')
        info['base'] = hex(info['base'])
        info['glyph_start'] = hex(info['glyph_start'])
        info['glyph_data_end'] = hex(info['glyph_data_end'])
        info['glyphs'] = [dict(index=g['index'], offset=hex(g['offset']), width=g['width'],
                               height=g['height'], mode=g['mode'], encoded_bytes=g['encoded_bytes'])
                          for g in glyphs]
        info['sheet'] = f'fonts/font_r{res}.png'
        fonts.append(info)
    font35 = osd.font(35)[1]
    contact_sheet([(chr(0x20 + g['index']) if g['index'] < 95 else g['index'],
                    rgba_image(g['pixels'], g['width'], g['height'], glyph_pal)) for g in font35],
                  out / 'atlas/font_r35.png', cols=16, cell=(48, 60), label=lambda it: str(it[0]))

    # Strings (English = resource 8, identified by content)
    string_meta = {}
    for res in osd.string_resources():
        base, s = osd.strings(res)
        string_meta[res] = dict(base=hex(base), count=len(s), sample=s[2749] if len(s) > 2749 else None)
        if res == 8:
            (out / 'strings_en.json').write_text(json.dumps(s, ensure_ascii=False, indent=0) + '\n')

    # Palettes
    pals = osd.palettes()
    pal_rows = [dict(address=hex(p['address']), offset=hex(p['offset']), populated=p['populated'],
                     entries=['%08x' % e for e in p['entries']]) for p in pals]
    (out / 'palettes.json').write_text(json.dumps(pal_rows, indent=1) + '\n')
    from PIL import Image, ImageDraw
    sw = checker(256 * 3 + 90, 14 * len(pals))
    d = ImageDraw.Draw(sw)
    for k, p in enumerate(pals):
        d.text((2, 14 * k + 1), hex(p['address']), fill=(255, 255, 0, 255))
        for j, e in enumerate(p['entries']):
            d.rectangle([90 + 3 * j, 14 * k, 90 + 3 * j + 2, 14 * k + 12], fill=argb_to_rgba(e))
    sw.save(out / 'atlas/palettes.png')

    # Curated sheet of identified assets
    cur = []
    for group, info in IDENTIFIED.items():
        for i in info['ids']:
            row = osd.descriptor(i)
            if row['kind'] != 'rle':
                continue
            px, mode, _ = osd.decode_bitmap(row)
            cur.append((f'{i} {group[:14]}', rgba_image(px, row['width'], row['height'],
                                                        pal8 if MODES[mode][0] == 8 else pal4)))
    contact_sheet(cur, out / 'atlas/identified.png', cols=12, cell=(130, 90))

    status = {}
    for b in bitmaps:
        status[b['status']] = status.get(b['status'], 0) + 1
    catalog = dict(
        source=dict(component=str(args.component), component_sha256=COMPONENT_SHA,
                    main=str(args.main), main_sha256=MAIN_SHA,
                    tool_sha256=sha256(Path(__file__).read_bytes())),
        structure=dict(
            component_address=hex(COMPONENT_ADDR),
            resources={i: dict(offset=hex(r['offset']), size=hex(r['size']), address=hex(r['address']))
                       for i, r in osd.resources.items()},
            bank0=dict(resource=0, runtime_base=hex(osd.base0),
                       header=[hex(x) for x in osd.bank0_header],
                       symbol_table=hex(osd.symbol_table), bitmap_table=hex(osd.bitmap_table)),
            bank69=dict(resource=69, runtime_base=hex(osd.base69)),
            bitmap_count=osd.bitmap_count, symbol_count=osd.symbol_count,
            stream_modes={m: dict(index_bits=v[0], run_bits=v[1], token_bits=v[2]) for m, v in MODES.items()}),
        palettes=dict(candidate_8bit=hex(args.palette8), candidate_4bit=hex(args.palette4),
                      glyph_levels_to_indices=[0, GLYPH_FG + 2, GLYPH_FG + 1, GLYPH_FG],
                      blocks=len(pals), note='runtime palette selection NOT verified; see docs/OSD.md'),
        bitmap_status=status,
        failures=[dict(id=f['id'], error=f['error']) for f in failures],
        identified=IDENTIFIED,
        strings=string_meta,
        fonts=fonts,
        symbols=symbols,
        bitmaps=bitmaps)
    (out / 'catalog.json').write_text(json.dumps(catalog, indent=1) + '\n')
    print(json.dumps(dict(out=str(out), bitmaps=status, symbols=len(symbols),
                          fonts={f['resource']: f['glyph_count'] for f in fonts},
                          bank0_base=hex(osd.base0), bank69_base=hex(osd.base69),
                          palettes=len(pals), failures=len(failures))))


if __name__ == '__main__':
    main()
