#!/usr/bin/env python3
"""Build the film-sims page "Film" (docs/FILM_MENU_V2.md) as a layer over a 12e look-editor (+ extras) spec. Offline.

  .venv/bin/python -I patches/film_menu_v2/build.py --base generated/look_extras_12e/merged.json \
      --out generated/film_menu_v2_12e [--card generated/film_menu_v2_12e/card]

Adds fm.s.in at sec 9 0x6143a410 (FF; guards 0x6143a400..a410, 0x6143a7f0..a800), re-points the COLOR1-4 record
Up/Down words (+12/+16) to fm_up/fm_down, and sets the editor's two layer words ed_cfg_fv / ed_cfg_fl (in its
ed_keys blob) to fm_valid / fm_load. --card writes EP7MOD/LOOKS.BIN with the colour looks of bundles/library_v1.json.
"""
import argparse, hashlib, importlib.util, json, re, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


B3 = _load('ep7_sd_bundles_v3_build_fm', ROOT / 'patches/sd_bundles_v3/build.py')
LB = _load('ep7_looks_bin_fm', ROOT / 'tools/ep7_looks_bin.py')
BASE, MAIN, MAIN_SHA = B3.BASE, B3.MAIN, B3.MAIN_SHA

CLAIM = (0x6143a400, 0x6143a800)
CODE = (0x6143a410, 0x6143a7f0)
UI = (0x601e2c3c, 0x601e2f3c)            # sec 1: dead EVF gamma step-4 R/G/B tables
UI_REFS = {0x601e2c3c: 0x601e3cc0, 0x601e2d3c: 0x601e3cc4, 0x601e2e3c: 0x601e3cc8}
RECORDS = {0x13b3: 0x61185bdc, 0x13b4: 0x61185c14, 0x13b5: 0x61185c4c, 0x140c: 0x61185c84}
UP, DOWN = 0x60e20e0a, 0x60e2107a
UP_OFF, DOWN_OFF = 12, 16
STOCK = dict(ep7_up=UP, ep7_down=DOWN, **{k: v for k, v in B3.SERVICES.items()
                                          if k in ('ep7_malloc', 'ep7_free', 'ep7_fopen', 'ep7_fclose', 'ep7_fread',
                                                   'ep7_fseek', 'ep7_ftell')})
EMARK, AXIS, DIRTY = 680, 684, 685
EMAGIC = struct.unpack('<I', b'EP7E')[0]
LMAGIC, FMAGIC, XMAGIC = (struct.unpack('<I', m)[0] for m in (b'EP7L', b'EP7F', b'EP7X'))
L_SIZE = 2048
LLIM = B3.POOL_END - B3.POOL - L_SIZE + 1
OFF = dict(lptr=1016, fmark=1020, ltag=1408, lback=1412, n=1416, pos=1417, snap=1421, snaps=1428, stage=1752)
FILM_AXIS = 3


def bytes_lines(b):
    return '\n'.join(' .byte ' + ','.join(str(x) for x in b[i:i + 16]) for i in range(0, len(b), 16))


def source(name):
    lo, span, _ = LB.SB.range_table(LB.SB.layout())
    hdr = LB.header(1)
    sub = dict(state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL), npool=hex(-B3.POOL & 0xffffffff),
               llim=hex(LLIM), bmagic=hex(B3.MAGIC), nmagic=hex(B3.NMAGIC), emark=EMARK, emagic=hex(EMAGIC),
               axis=AXIS, dirty=DIRTY, lmagic=hex(LMAGIC), fmagic=hex(FMAGIC), xmagic=hex(XMAGIC),
               hdr_bytes=bytes_lines(hdr), lo_bytes=bytes_lines(bytes(v & 0xff for v in lo[:45])),
               span_bytes=bytes_lines(bytes(span[:45])))
    return B3.subst((HERE / name).read_text(), sub)


def u32(d, a):
    return struct.unpack_from('<I', d, a - BASE)[0]


def image(spec):
    d = bytearray(MAIN.read_bytes())
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    stock = bytes(d)
    for e in spec['edits']:
        if e['kind'] != '0x100':
            continue
        a, exp, new = int(e['addr'], 16), bytes.fromhex(e['expect']), bytes.fromhex(e['new'])
        if stock[a - BASE:a - BASE + len(exp)] != exp:
            raise ValueError(f'edit {a:#x}: stock bytes differ')
        d[a - BASE:a - BASE + len(new)] = new
    return stock, bytes(d)


def check_stock(stock, patched):
    if stock[CLAIM[0] - BASE:CLAIM[1] - BASE] != b'\xff' * (CLAIM[1] - CLAIM[0]):
        raise ValueError('sec-9 claim not FF in stock')
    if patched[CLAIM[0] - BASE:CLAIM[1] - BASE] != b'\xff' * (CLAIM[1] - CLAIM[0]):
        raise ValueError('sec-9 claim already used by the base spec')
    for k, a in RECORDS.items():
        if u32(stock, a) != k or u32(stock, a + UP_OFF) != UP or u32(stock, a + DOWN_OFF) != DOWN:
            raise ValueError(f'record {k:#x} Up/Down words differ')
        if u32(patched, a + UP_OFF) != UP or u32(patched, a + DOWN_OFF) != DOWN:
            raise ValueError(f'record {k:#x} Up/Down words already edited by the base spec')
    for t in (UP, DOWN):            # data refs only: the 5 records 0x61185bb0..c90 + two other editors (stay stock)
        hits = [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', t)), stock)]
        want = {a + (UP_OFF if t == UP else DOWN_OFF) for a in RECORDS.values()}
        if not want <= set(hits) or len(hits) != 7:
            raise ValueError(f'{t:#x} refs {[hex(h) for h in hits]}')
    # nothing points into the claims (the step-4 tables only from their step-table words)
    import numpy as np
    if struct.unpack_from('<B3xIII', stock, 0x601e3b3c + 320 + 16 * 4 - BASE) != (4, 0x601e2c3c, 0x601e2d3c, 0x601e2e3c):
        raise ValueError('EVF step-4 slot differs')
    if patched[UI[0] - BASE:UI[1] - BASE] != stock[UI[0] - BASE:UI[1] - BASE]:
        raise ValueError('EVF step-4 tables already used by the base spec')
    for off in range(4):
        w = np.frombuffer(stock[off:off + (len(stock) - off) // 4 * 4], dtype='<u4')
        if len(np.nonzero((w >= CLAIM[0]) & (w < CLAIM[1]))[0]):
            raise ValueError('abs32 reference into the sec-9 claim')
        for k in np.nonzero((w >= UI[0]) & (w < UI[1]))[0]:
            if UI_REFS.get(int(w[k])) != BASE + off + 4 * int(k):
                raise ValueError('abs32 reference into the step-4 tables')


def build(base_spec):
    spec = json.loads(Path(base_spec).read_text()) if not isinstance(base_spec, dict) else base_spec
    meta = spec.get('look_editor') or spec.get('meta', {}).get('look_editor')
    if not meta:
        raise ValueError('not a look-editor spec')
    esym = {k: int(v, 16) for k, v in meta['symbols'].items()}
    for k in ('ed_cfg_fv', 'ed_cfg_fl', 'ed_cfg_fm', 'ed_poke', 'ed_fm_none'):
        if k not in esym:
            raise ValueError(f'editor build lacks {k} (needs 12e)')
    if meta.get('pages', {}).get('F') != FILM_AXIS:
        raise ValueError('editor page values differ')
    stock, patched = image(spec)
    check_stock(stock, patched)
    for k in ('ed_cfg_fv', 'ed_cfg_fl', 'ed_cfg_fm'):
        if u32(patched, esym[k]) != esym['ed_fm_none']:
            raise ValueError(f'{k} is not the editor default (another film layer?)')
    ui, ui_lst, ui_syms, _ = B3.assemble(source('fm_ui.s.in'), UI[0], dict(STOCK, ed_poke=esym['ed_poke']))
    if ui_syms['fm_valid'] != UI[0] or UI[0] + len(ui) > UI[1]:
        raise ValueError(f'fm_ui: {len(ui)} B does not fit {UI[1] - UI[0]}')
    code, lst, syms, _ = B3.assemble(source('fm_core.s.in'), CODE[0], dict(STOCK))
    if syms['fm_load'] != CODE[0] or CODE[0] + len(code) > CODE[1]:
        raise ValueError(f'fm_core: {len(code)} B does not fit {CODE[1] - CODE[0]}')
    bad = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}
    audit = []
    for nm, c, at, stop in (('ui', ui, UI[0], ui_syms['fm_ui_end']), ('core', code, CODE[0], syms['fm_data'])):
        ins = B3.disasm(c, at, stop)
        if any(op in bad for _, op, _ in ins):
            raise ValueError(f'fm {nm}: forbidden instruction')
        for a, t, kind, tgt in B3.store_audit(ins):
            if kind == 'abs':
                raise ValueError(f'fm {nm}: absolute store at {a:#x}: {t}')
            audit.append((hex(a), t, kind))
    fs = {k: v for k, v in {**syms, **ui_syms}.items() if not k.startswith(('_', '.'))}
    lst = ui_lst + '\n' + lst
    new = [dict(kind='0x100', addr=hex(CODE[0]), expect='ff' * len(code), new=code.hex(),
                why='film menu v2 core: fm_load / fm_check / fm_crc + LOOKS.BIN rules (sec 9)'),
           dict(kind='0x100', addr=hex(UI[0]), expect=stock[UI[0] - BASE:UI[0] - BASE + len(ui)].hex(), new=ui.hex(),
                why='film menu v2 ui: fm_valid / fm_up / fm_down (sec 1, dead EVF step-4 gamma tables)')]
    for k, a in RECORDS.items():
        new.append(dict(kind='0x100', addr=hex(a + UP_OFF), expect=struct.pack('<I', UP).hex(),
                        new=struct.pack('<I', fs['fm_up']).hex(), why=f'record {k:#x} Up (+12) -> fm_up'))
        new.append(dict(kind='0x100', addr=hex(a + DOWN_OFF), expect=struct.pack('<I', DOWN).hex(),
                        new=struct.pack('<I', fs['fm_down']).hex(), why=f'record {k:#x} Down (+16) -> fm_down'))
    for e in new:
        e['source'] = 'patches/film_menu_v2'
    words = {esym['ed_cfg_fv']: fs['fm_valid'], esym['ed_cfg_fl']: fs['fm_load'], esym['ed_cfg_fm']: fs['fm_mod']}
    edits, done = [], set()
    for e in spec['edits']:
        a, n = int(e['addr'], 16), len(e['new']) // 2
        hit = [w for w in words if a <= w and w + 4 <= a + n]
        if hit:
            nb = bytearray.fromhex(e['new'])
            for w in hit:
                struct.pack_into('<I', nb, w - a, words[w])
                done.add(w)
            e = dict(e, new=nb.hex(), why=e['why'] + ' + film menu v2: ed_cfg_fv/fl/fm -> fm_valid/fm_load/fm_mod')
        for lo, hi in (CLAIM, UI):
            if a < hi and lo < a + n:
                raise ValueError(f'edit {a:#x} overlaps a film claim')
        edits.append(e)
    if done != set(words):
        raise ValueError('editor layer words not found in an editor edit')
    fmeta = dict(code=[hex(CODE[0]), len(code)], ui=[hex(UI[0]), len(ui)], claim=[hex(CLAIM[0]), hex(CLAIM[1])],
                 symbols={k: hex(v) for k, v in fs.items()}, offsets=OFF, l_size=L_SIZE, axis=FILM_AXIS,
                 stock={k: hex(v) for k, v in STOCK.items()}, stores=audit)
    merged = dict(spec, edits=edits + new, film_menu_v2=fmeta)
    merged.setdefault('meta', {})['film_menu_v2'] = fmeta
    return merged, lst


def colour_library(path=ROOT / 'bundles/library_v1.json'):
    """library_v1 restricted to its colour looks (mono looks cannot go in a COLOR slot)."""
    cfg = json.loads(Path(path).read_text())
    recipes = LB.LIB.BB.load_recipes()
    keep = {}
    for k, v in cfg['looks'].items():
        r96, _ = LB.LIB.look_record(k, v, recipes)
        if LB.record(r96)[LB.CLASS_OFF] == 0:
            keep[k] = v
    return dict(cfg, looks=keep)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True, type=Path, help='12e look-editor (+ extras) merged spec')
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--card', type=Path, help='write <card>/EP7MOD/LOOKS.BIN (16 colour looks of library_v1)')
    a = ap.parse_args()
    merged, lst = build(a.base)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'merged.json').write_text(json.dumps(merged, indent=1) + '\n')
    (a.out / 'film_menu_v2.lst').write_text(lst)
    m = merged['film_menu_v2']
    print(f"fm_core {m['code'][1]} B @ {m['code'][0]}, fm_ui {m['ui'][1]} B @ {m['ui'][0]}; {len(merged['edits'])} edits")
    if a.card:
        data, keys, names = LB.compile_looks(colour_library())
        if 'DCOLYMP' in str(a.card).upper():
            raise SystemExit('refusing DCOLYMP')
        d = a.card / 'EP7MOD'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'LOOKS.BIN').write_bytes(data)
        print(f'LOOKS.BIN {len(data)} B, {len(names)} looks: {", ".join(names)}')


if __name__ == '__main__':
    main()
