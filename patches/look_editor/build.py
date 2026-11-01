#!/usr/bin/env python3
"""Build the E-P7 1.1 look editor phase 1 + 1s edit spec (offline, no camera). Design: docs/LOOK_EDITOR.md.

  .venv/bin/python -I patches/look_editor/build.py --base releases/test8-filmmenu/edits.json --out generated/look_editor

Writes OUT/edits.json (this patch alone, for merging) and OUT/merged.json (base + this patch, with the base
loader edit at 0x605b7400 carrying the 5-byte sd_back retarget 0x605b7420 `jmp 0x602c8064` -> `jmp ed_trig`).
Edits:
  - ed_core (sec 3, 0x605b71a0..0x605b73e0): ed_get / ed_default / ed_set
  - ed_ui   (sec 6, 0x61242a10..0x61242cf0): ed_event / ed_init / ed_trig / ed_save / ed_wfile / ed_crc
  - 0x607fa355  `call 0x60827440,[d2,d3,a2],16` -> `call ed_set,[d2,d3,a2],16`
  - 0x60acb0e4 / 0x60acb174  facade vtable GetValue / GetDefault -> ed_get / ed_default
  - COLOR1-4 parent records: +36 event (0x60e22191) -> ed_event, +4 init (0x60e20a54) -> ed_init,
    +52 Movie/0x9012 slot (0 = .data default 0x60e228fb) -> ed_event
"""
import argparse, hashlib, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


B3 = _load('ep7_sd_bundles_v3_build', ROOT / 'patches/sd_bundles_v3/build.py')
TC, BASE, MAIN, MAIN_SHA = B3.TC, B3.BASE, B3.MAIN, B3.MAIN_SHA

CORE = (0x605b7190, 0x605b73f0)          # sec 3; guard 0x605b7180..7190 (stock data ends 0x605b717f); 0x605b73f0..7400 = loader guard
UI = (0x612429c0, 0x61242cf0)            # sec 6; guards 0x612429b0..29c0 (stock data ends 0x612429af), 0x61242cf0..d00
GUARDS = [(0x605b7180, 0x605b7190), (0x605b73f0, 0x605b7400), (0x612429b0, 0x612429c0), (0x61242cf0, 0x61242d00)]
SET_SITE, SET_STOCK = 0x607fa355, 'ddebd00200e010'
VT_GET, VT_DEF = 0x60acb0e4, 0x60acb174
STOCK = dict(ep7_get=0x607f9549, ep7_default=0x607f964a, ep7_manager=0x60827440, ep7_event=0x60e22191,
             ep7_init=0x60e20a54, ep7_movie=0x60e228fb, ep7_refresh=0x60de3670, ep7_trig_ret=B3.SITE_RET,
             ep7_malloc=0x60022782, ep7_free=0x600227b4, ep7_fopen=0x60634fbc, ep7_fclose=0x60634fc5,
             ep7_fread=0x6063514b, ep7_fwrite=0x60635041)
RECORDS = {0x13b3: 0x61185bdc, 0x13b4: 0x61185c14, 0x13b5: 0x61185c4c, 0x140c: 0x61185c84}   # key word address
MOVIE_OFF = 52                           # record +52 -> parent+88 (router: 0x9012)
DEF_IMG = 0x6025bad0                     # .data 0x61fc3810 init image: defaults for parent+48..+88
REC_TABLE, REC_N = 0x6118474c, 167
SD_BACK, SD_BACK_STOCK = 0x605b7420, 'dc440cd1ff'      # loader v3 sd_back: jmp 0x602c8064
LOADER_AT = 0x605b7400
# heap block offsets (P = loader block): 'EP7E' marker, axis, dirty, status (after the names/L pointer +544..679)
EMARK, AXIS, DIRTY, STATUS = 680, 684, 685, 686
EMAGIC = struct.unpack('<I', b'EP7E')[0]
OLD, RBD = 688, 1368                       # save scratch S (2048 B): image 0, old .BIN 688, read-back 1368


def sub():
    return dict(state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL), bmagic=hex(B3.MAGIC), nmagic=hex(B3.NMAGIC),
                emark=EMARK, emagic=hex(EMAGIC), axis=AXIS, dirty=DIRTY, status=STATUS, ev_press=hex(B3.EV_PRESS),
                old=OLD, rbd=RBD)


def source(name):
    return B3.subst((HERE / name).read_text(), sub())


def u32(d, a):
    return struct.unpack_from('<I', d, a - BASE)[0]


def check_stock(d):
    for lo, hi in [CORE, UI] + GUARDS:
        if d[lo - BASE:hi - BASE] != b'\xff' * (hi - lo):
            raise ValueError(f'{lo:#x}..{hi:#x} not FF in stock')
    if d[SET_SITE - BASE:SET_SITE - BASE + 7].hex() != SET_STOCK:
        raise ValueError('setter site bytes differ')
    if u32(d, VT_GET) != STOCK['ep7_get'] or u32(d, VT_DEF) != STOCK['ep7_default']:
        raise ValueError('facade vtable words differ')
    if u32(d, 0x60acb0dc) != 0x607fa129:
        raise ValueError('facade vtable base differs')
    for k, a in RECORDS.items():
        if u32(d, a) != k or u32(d, a + 4) != STOCK['ep7_init'] or u32(d, a + 36) != STOCK['ep7_event']:
            raise ValueError(f'record {k:#x} at {a:#x} differs')
        if u32(d, a + MOVIE_OFF) != 0:
            raise ValueError(f'record {k:#x} +52 not 0')
    if u32(d, DEF_IMG + MOVIE_OFF - 12) != STOCK['ep7_movie'] or d[STOCK['ep7_movie'] - BASE:STOCK['ep7_movie'] - BASE + 4].hex() != '00de0000':
        raise ValueError('parent+88 default is not 0x60e228fb `clr d0; retf`')
    keys = [struct.unpack_from('<H', d, REC_TABLE + 56 * i - BASE)[0] for i in range(REC_N)]
    if any(keys.count(k) != 1 for k in RECORDS) or [REC_TABLE + 56 * keys.index(k) for k in RECORDS] != list(RECORDS.values()):
        raise ValueError('COLOR records not unique in the record table')
    # only one reference each to the redirected stock targets from data (the words we edit)
    import re
    for t, where in ((STOCK['ep7_get'], [VT_GET]), (STOCK['ep7_default'], [VT_DEF])):
        hits = [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', t)), d)]
        if hits != where:
            raise ValueError(f'{t:#x} referenced at {[hex(h) for h in hits]}')
    # the four COLOR records are the only records using 0x60e22191 as event callback
    hits = [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', STOCK['ep7_event'])), d)]
    # also used by the 0x13a9 (CRT-like) and 0x1413/0x1414 records, which stay stock; ed_event checks the key
    if not set(a + 36 for a in RECORDS.values()) <= set(hits) or len(hits) != 7:
        raise ValueError(f'0x60e22191 data refs {[hex(h) for h in hits]}')


def build(base_spec=None):
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    check_stock(d)
    ui, ui_lst, ui_syms, ui_dis = B3.assemble(source('ed_ui.s.in'), UI[0], STOCK)
    if ui_syms['ed_event'] != UI[0] or UI[0] + len(ui) > UI[1]:
        raise ValueError(f'ed_ui: {len(ui)} B does not fit {UI[1] - UI[0]}')
    core, core_lst, core_syms, core_dis = B3.assemble(source('ed_core.s.in'), CORE[0], dict(STOCK, ed_save=ui_syms['ed_save']))
    if core_syms['ed_get'] != CORE[0] or CORE[0] + len(core) > CORE[1]:
        raise ValueError(f'ed_core: {len(core)} B does not fit')
    syms = {k: v for k, v in {**core_syms, **ui_syms}.items() if not k.startswith('_')}
    for name, code, at, stop in (('core', core, CORE[0], core_syms['ed_core_end']),
                                 ('ui', ui, UI[0], ui_syms['ed_p_new'])):
        ins = B3.disasm(code, at, stop)
        bad = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}
        if any(op in bad for _, op, _ in ins):
            raise ValueError(f'{name}: forbidden instruction')
        for a, t, kind, tgt in B3.store_audit(ins):
            if kind == 'abs':
                raise ValueError(f'{name}: absolute store at {a:#x}: {t}')
    rel = syms['ed_set'] - SET_SITE
    set_new = b'\xdd' + struct.pack('<i', rel) + b'\xe0\x10'
    edits = [
        dict(kind='0x100', addr=hex(CORE[0]), expect='ff' * len(core), new=core.hex(), why='look editor core (sec 3)'),
        dict(kind='0x100', addr=hex(UI[0]), expect='ff' * len(ui), new=ui.hex(), why='look editor UI + save (sec 6)'),
        dict(kind='0x100', addr=hex(SET_SITE), expect=SET_STOCK, new=set_new.hex(), why='GUI setter -> ed_set'),
        dict(kind='0x100', addr=hex(VT_GET), expect=struct.pack('<I', STOCK['ep7_get']).hex(),
             new=struct.pack('<I', syms['ed_get']).hex(), why='facade GetValue -> ed_get'),
        dict(kind='0x100', addr=hex(VT_DEF), expect=struct.pack('<I', STOCK['ep7_default']).hex(),
             new=struct.pack('<I', syms['ed_default']).hex(), why='facade GetDefault -> ed_default'),
    ]
    for k, a in RECORDS.items():
        edits.append(dict(kind='0x100', addr=hex(a + 4), expect=struct.pack('<I', STOCK['ep7_init']).hex(),
                          new=struct.pack('<I', syms['ed_init']).hex(), why=f'record {k:#x} init -> ed_init'))
        edits.append(dict(kind='0x100', addr=hex(a + 36), expect=struct.pack('<I', STOCK['ep7_event']).hex(),
                          new=struct.pack('<I', syms['ed_event']).hex(), why=f'record {k:#x} event -> ed_event'))
        edits.append(dict(kind='0x100', addr=hex(a + MOVIE_OFF), expect='00000000',
                          new=struct.pack('<I', syms['ed_event']).hex(), why=f'record {k:#x} Movie (0x9012) -> ed_event'))
    for e in edits:
        e['source'] = 'patches/look_editor'
    back_new = (b'\xdc' + struct.pack('<i', syms['ed_trig'] - SD_BACK)).hex()
    meta = dict(core=[hex(CORE[0]), len(core)], ui=[hex(UI[0]), len(ui)], symbols={k: hex(v) for k, v in syms.items()},
                stock={k: hex(v) for k, v in STOCK.items()}, heap=dict(emark=EMARK, axis=AXIS, dirty=DIRTY, status=STATUS),
                sd_back=dict(addr=hex(SD_BACK), stock=SD_BACK_STOCK, new=back_new), records={hex(k): hex(v) for k, v in RECORDS.items()})
    spec = dict(components=['0x100'], edits=edits, patch='look_editor', look_editor=meta)
    merged = None
    if base_spec is not None:
        base = json.loads(Path(base_spec).read_text())
        bedits = []
        found = False
        for e in base['edits']:
            e = dict(e)
            if int(e['addr'], 16) == LOADER_AT:
                nb = bytearray.fromhex(e['new'])
                o = SD_BACK - LOADER_AT
                if nb[o:o + 5].hex() != SD_BACK_STOCK:
                    raise ValueError('base loader: sd_back is not `jmp 0x602c8064` at 0x605b7420')
                nb[o:o + 5] = bytes.fromhex(back_new)
                e['new'] = nb.hex()
                e['why'] = e.get('why', '') + ' + look editor: sd_back -> ed_trig'
                found = True
            bedits.append(e)
        if not found:
            raise ValueError('base spec has no loader edit at 0x605b7400')
        merged = dict(base, edits=bedits + edits, look_editor=meta)
        merged.setdefault('meta', {})['look_editor'] = meta
    return spec, merged, core_lst + '\n' + ui_lst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec, merged, lst = build(a.base)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'look_editor.lst').write_text(lst)
    if merged:
        (a.out / 'merged.json').write_text(json.dumps(merged, indent=1) + '\n')
    m = spec['look_editor']
    print(f"core {m['core'][1]} B @ {m['core'][0]}, ui {m['ui'][1]} B @ {m['ui'][0]}; {len(spec['edits'])} edits"
          + (f"; merged {len(merged['edits'])} edits" if merged else ''))


if __name__ == '__main__':
    main()
