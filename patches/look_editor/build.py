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
  - COLOR1-4 parent records: +4 init (0x60e20a54) -> ed_init, +44 INFO/0x9014 (0x60e22579) -> ed_info (12d;
    the 12b/12c +36/+52 Delete/Movie words are stock again)
  - ed_view (sec 5, 0x60b9dd10..0x60b9dff0): ed_guide / ed_info / ed_poke (+ ed_rprobe / ed_oprobe) + strings
  - 0x6025aa98 (.data init image of the Color Profile view part table 0x61fc27d0, entry 3)
    0x60decbfc -> ed_guide (current state in the guide label)
  - key probe (default on, --no-probe drops it): editor parent vtable 0x61187534 +0 (0x60dd5250) -> ed_oprobe,
    +68 (0x60e20cdc, the router) -> ed_rprobe; codes shown in the guide label
"""
import argparse, hashlib, importlib.util, json, re, struct, sys
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
KEYS = (0x601e2f3c, 0x601e323c)          # sec 1: dead EVF gamma step-3 R/G/B tables (only refs: step-table words
KEYS_REFS = {0x601e2f3c: 0x601e3cb0, 0x601e303c: 0x601e3cb4, 0x601e313c: 0x601e3cb8}   # 0x601e3cb0/b4/b8)
VIEW = (0x60b9dd10, 0x60b9dff0)          # sec 5 FF tail (stock data ends 0x60b9dcff; sec 5 load ends 0x60b9e000)
GUARDS = [(0x605b7180, 0x605b7190), (0x605b73f0, 0x605b7400), (0x612429b0, 0x612429c0), (0x61242cf0, 0x61242d00),
          (0x60b9dd00, 0x60b9dd10), (0x60b9dff0, 0x60b9e000)]
SET_SITE, SET_STOCK = 0x607fa355, 'ddebd00200e010'
VT_GET, VT_DEF = 0x60acb0e4, 0x60acb174
STOCK = dict(ep7_get=0x607f9549, ep7_default=0x607f964a, ep7_manager=0x60827440, ep7_event=0x60e22191,
             ep7_init=0x60e20a54, ep7_movie=0x60e228fb, ep7_refresh=0x60de3670, ep7_trig_ret=B3.SITE_RET,
             ep7_malloc=0x60022782, ep7_free=0x600227b4, ep7_fopen=0x60634fbc, ep7_fclose=0x60634fc5,
             ep7_fread=0x6063514b, ep7_fwrite=0x60635041,
             ep7_guide=0x60decbfc, ep7_facade=0x607f9062, ep7_sget=0x602af887,
             ep7_info=0x60e22579, ep7_router=0x60e20cdc, ep7_entry=0x60dd5250, ep7_aget=0x602afa81)
# 13: wheel polygon. C3d request producer 0x60932fa6 (vtable +4972 of the 10 view vtables that hold 0x609394be at
# +1056), case 1 (COLOR wheel): 12 x `call 0x602afa81,[],4` on the sector ids of table 0x60b40c4c row (1648).
POLY_SITE, POLY_STOCK = 0x609330f9, 'dd88c997ff0004'
POLY_PIN = {0x60932fa6: 'cff0fafe70ff', 0x609330bc: '2c7006', 0x609330e6: 'dd9bc997ff0004f8530c',
            0x60933100: 'f44b4c8e1faf0cc0ed', 0x60932faf: 'fcde4c0cb460'}
POLY_VTABS = [0x60b3b870, 0x60b3df34, 0x60b49240, 0x60b4b9f8, 0x60b4f134, 0x60b51904, 0x60b54448, 0x60b5754c,
              0x60b59d28, 0x60b5e2e8]
# Color Profile view part table: .data 0x61fc27d0 (init image 0x6025aa90) = 5 parts + 0, copied (24 B) to view+4 by
# 0x60dec77c; the view update 0x60dec790 `calls` each with a0 = view. Entry 3 (0x60decbfc) builds the guide label.
PARTS_IMG, PARTS_DATA = 0x6025aa90, 0x61fc27d0
PARTS = [0x60dec842, 0x60decabd, 0x60decbfc, 0x60decfeb, 0x60ded033, 0]
GUIDE_WORD = PARTS_IMG + 8
RECORDS = {0x13b3: 0x61185bdc, 0x13b4: 0x61185c14, 0x13b5: 0x61185c4c, 0x140c: 0x61185c84}   # key word address
MOVIE_OFF = 52                           # record +52 -> parent+88 (router: 0x9012); stock again in 12d
INFO_OFF = 44                            # record +44 -> parent+80 (router: 0x9014, INFO press)
PAGE_OFF = 36                            # record +36 -> parent+72 (router: every other event; 12e page key)
KEY_MENU, KEY_PLAY = 0x900e, 0x9010      # GUI key table 0x6113e938: index 0x17 MENU press 0x900e (0x18 long 0x9040,
                                         # 0x19 release 0x900f), 0x1a PLAY press 0x9010 (0x1b release 0x9011)
PAGES = dict(S=0, L=1, H=2, F=3, X=4)    # axis byte values; page order S -> H -> L -> F -> X -> S
VTAB = 0x61187534                        # editor parent vtable (constructor 0x60e20691/0x60e206a9)
VT_ENTRY, VT_ROUTER = VTAB, VTAB + 68    # +0 event entry 0x60dd5250, +68 router 0x60e20cdc
PROBE_R, PROBE_O = 1000, 1002            # heap P+1000/+1002: last router / outer code (u16); past the loader
                                         # (<= +815) and 12c (+680..686), below the film-menu plan (+1016..)
DEF_IMG = 0x6025bad0                     # .data 0x61fc3810 init image: defaults for parent+48..+88
REC_TABLE, REC_N = 0x6118474c, 167
SD_BACK, SD_BACK_STOCK = 0x605b7420, 'dc440cd1ff'      # loader v3 sd_back: jmp 0x602c8064
LOADER_AT = 0x605b7400
# heap block offsets (P = loader block): 'EP7E' marker, axis, dirty, status (after the names/L pointer +544..679)
EMARK, AXIS, DIRTY, STATUS = 680, 684, 685, 686
EMAGIC = struct.unpack('<I', b'EP7E')[0]
OLD, RBD = 688, 1368                       # save scratch S (2048 B): image 0, old .BIN 688, read-back 1368


def sub(probe=True):
    return dict(probe=int(bool(probe)), key_a=hex(KEY_MENU), key_b=hex(KEY_PLAY), probe_r=PROBE_R, probe_o=PROBE_O, state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL), bmagic=hex(B3.MAGIC), nmagic=hex(B3.NMAGIC),
                emark=EMARK, emagic=hex(EMAGIC), axis=AXIS, dirty=DIRTY, status=STATUS, ev_press=hex(B3.EV_PRESS),
                old=OLD, rbd=RBD)


def source(name, probe=True):
    return B3.subst((HERE / name).read_text(), sub(probe))


def u32(d, a):
    return struct.unpack_from('<I', d, a - BASE)[0]


def check_stock(d):
    got = struct.unpack_from('<B3xIII', d, 0x601e3b3c + 320 + 16 * 3 - BASE)
    if got != (3, 0x601e2f3c, 0x601e303c, 0x601e313c):
        raise ValueError('EVF step-3 slot differs')
    import numpy as np
    for off in range(4):
        w = np.frombuffer(d[off:off + (len(d) - off) // 4 * 4], dtype='<u4')
        for k in np.nonzero((w >= KEYS[0]) & (w < KEYS[1]))[0]:
            at = BASE + off + 4 * int(k)
            if KEYS_REFS.get(int(w[k])) != at:
                raise ValueError(f'abs32 into the step-3 tables at {at:#x}')
    for lo, hi in [CORE, UI, VIEW] + GUARDS:
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
        if u32(d, a + INFO_OFF) != STOCK['ep7_info']:
            raise ValueError(f'record {k:#x} +44 is not the INFO handler')
    if d[POLY_SITE - BASE:POLY_SITE - BASE + 7].hex() != POLY_STOCK:
        raise ValueError('polygon site bytes differ')
    for a, hx in POLY_PIN.items():
        if d[a - BASE:a - BASE + len(hx) // 2].hex() != hx:
            raise ValueError(f'polygon producer bytes at {a:#x} differ')
    if any(u32(d, v + 4972) != 0x60932fa6 or u32(d, v + 1056) != 0x609394be for v in POLY_VTABS):
        raise ValueError('polygon producer vtables differ')
    if u32(d, 0x60acb0dc) != 0x607fa129 or d[0x607f9062 - BASE:0x607f9062 - BASE + 6].hex() != 'fca0ac96fa61':
        raise ValueError('facade singleton differs')
    if u32(d, VT_ENTRY) != STOCK['ep7_entry'] or u32(d, VT_ROUTER) != STOCK['ep7_router']:
        raise ValueError('editor parent vtable differs')
    if [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', VTAB)), d)] != [0x60e20691, 0x60e206a9] or \
            [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', STOCK['ep7_router'])), d)] != [VT_ROUTER]:
        raise ValueError('editor parent vtable / router referenced elsewhere')
    pin2 = {0x60e22579: 'cff0f8fed8', 0x60e228e6: 'dff038',            # INFO handler: movm/add -40 ... ret 56
            0x60e226ca: 'fca50038fc61', 0x60e226d7: 'fca50438fc61',    # it reads the ALL flags 0x61fc3800/04
            0x60dd5541: 'fca0ac1bfc61b000c90d9c8cf004f82544f0f1'}     # entry: Movie -> router iff (0x61fc1bac)==0
    for a, hx in pin2.items():
        if d[a - BASE:a - BASE + len(hx) // 2].hex() != hx:
            raise ValueError(f'stock bytes at {a:#x} differ')
    if u32(d, DEF_IMG + MOVIE_OFF - 12) != STOCK['ep7_movie'] or d[STOCK['ep7_movie'] - BASE:STOCK['ep7_movie'] - BASE + 4].hex() != '00de0000':
        raise ValueError('parent+88 default is not 0x60e228fb `clr d0; retf`')
    # 12c guide hook: part table, its copy into the view, and the stock guide writer it wraps
    if [u32(d, PARTS_IMG + 4 * i) for i in range(6)] != PARTS or PARTS_DATA - PARTS_IMG != 0x61fc3810 - DEF_IMG:
        raise ValueError('view part table differs')
    pin = {0x60dec77c: '9450fcddd027fc618018',            # mov a1,a0; inc4 a0; mov 0x61fc27d0,a1; mov 24,d0
           0x60dec7f4: 'f0049cf0f1',                      # mov (a0),a1; mov a3,a0; calls (a1)
           0x60decbfc: 'cff0f8fed4',                      # movm [d2,d3,a2,a3],(sp); add -44,sp (calls entry)
           0x60decf52: '5f0c2cc40a53',                    # mov (12,sp),a3; mov 2756,d0; inc4 a3  (a3 = view+44)
           0x60decf75: '5f0c2cc30a53',                    # ... 2755
           0x60decfdc: 'f873048004f0738002f87306dff03c',  # id +4, kind 4, (6) = 2, ret [d2,d3,a2,a3],60
           0x602af887: '1ccdc012f014df0004'}              # exthu d0; call 0x602b0b48,[d2,d3,a2,a3],20; ret [],4
    for a, hx in pin.items():
        if d[a - BASE:a - BASE + len(hx) // 2].hex() != hx:
            raise ValueError(f'stock bytes at {a:#x} differ')
    if [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', STOCK['ep7_guide'])), d)] != [GUIDE_WORD]:
        raise ValueError('0x60decbfc referenced elsewhere')
    keys = [struct.unpack_from('<H', d, REC_TABLE + 56 * i - BASE)[0] for i in range(REC_N)]
    if any(keys.count(k) != 1 for k in RECORDS) or [REC_TABLE + 56 * keys.index(k) for k in RECORDS] != list(RECORDS.values()):
        raise ValueError('COLOR records not unique in the record table')
    # only one reference each to the redirected stock targets from data (the words we edit)
    for t, where in ((STOCK['ep7_get'], [VT_GET]), (STOCK['ep7_default'], [VT_DEF])):
        hits = [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', t)), d)]
        if hits != where:
            raise ValueError(f'{t:#x} referenced at {[hex(h) for h in hits]}')
    # the four COLOR records are the only records using 0x60e22191 as event callback
    hits = [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', STOCK['ep7_event'])), d)]
    # also used by the 0x13a9 (CRT-like) and 0x1413/0x1414 records, which stay stock; ed_event checks the key
    if not set(a + 36 for a in RECORDS.values()) <= set(hits) or len(hits) != 7:
        raise ValueError(f'0x60e22191 data refs {[hex(h) for h in hits]}')


def build(base_spec=None, probe=False):
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    check_stock(d)
    ui, ui_lst, ui_syms, ui_dis = B3.assemble(source('ed_ui.s.in', probe), UI[0], STOCK)
    if ui_syms['ed_init'] != UI[0] or UI[0] + len(ui) > UI[1]:
        raise ValueError(f'ed_ui: {len(ui)} B does not fit {UI[1] - UI[0]}')
    keys, keys_lst, keys_syms, _ = B3.assemble(source('ed_keys.s.in', probe), KEYS[0], dict(STOCK, ed_poke=ui_syms['ed_poke']))
    if keys_syms['ed_info'] != KEYS[0] or KEYS[0] + len(keys) > KEYS[1]:
        raise ValueError(f'ed_keys: {len(keys)} B does not fit {KEYS[1] - KEYS[0]}')
    view, view_lst, view_syms, _ = B3.assemble(source('ed_view.s.in', probe), VIEW[0], dict(STOCK, ed_poke=ui_syms['ed_poke'], ed_cfg_fm=keys_syms['ed_cfg_fm']))
    if view_syms['ed_guide'] != VIEW[0] or VIEW[0] + len(view) > VIEW[1]:
        raise ValueError(f'ed_view: {len(view)} B does not fit {VIEW[1] - VIEW[0]}')
    core, core_lst, core_syms, core_dis = B3.assemble(source('ed_core.s.in', probe), CORE[0], dict(STOCK, ed_save=ui_syms['ed_save'], ed_cfg_fl=keys_syms['ed_cfg_fl']))
    if core_syms['ed_get'] != CORE[0] or CORE[0] + len(core) > CORE[1]:
        raise ValueError(f'ed_core: {len(core)} B does not fit')
    syms = {k: v for k, v in {**core_syms, **ui_syms, **keys_syms, **view_syms}.items() if not k.startswith('_') and not k.startswith('.')}
    for name, code, at, stop in (('core', core, CORE[0], core_syms['ed_core_end']),
                                 ('ui', ui, UI[0], ui_syms['ed_p_new']),
                                 ('view', view, VIEW[0], view_syms['ed_view_data']),
                                 ('keys', keys, KEYS[0], keys_syms['ed_keys_data'])):
        ins = B3.disasm(code, at, stop)
        bad = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}
        if any(op in bad for _, op, _ in ins):
            raise ValueError(f'{name}: forbidden instruction')
        for a, t, kind, tgt in B3.store_audit(ins):
            if kind == 'abs':
                raise ValueError(f'{name}: absolute store at {a:#x}: {t}')
    poly_new = b'\xdd' + struct.pack('<i', syms['ed_poly'] - POLY_SITE) + b'\x00\x04'
    rel = syms['ed_set'] - SET_SITE
    set_new = b'\xdd' + struct.pack('<i', rel) + b'\xe0\x10'
    edits = [
        dict(kind='0x100', addr=hex(CORE[0]), expect='ff' * len(core), new=core.hex(), why='look editor core (sec 3)'),
        dict(kind='0x100', addr=hex(UI[0]), expect='ff' * len(ui), new=ui.hex(), why='look editor UI + save (sec 6)'),
        dict(kind='0x100', addr=hex(VIEW[0]), expect='ff' * len(view), new=view.hex(),
             why='look editor axis indicator + refresh (sec 5)'),
        dict(kind='0x100', addr=hex(KEYS[0]), expect=d[KEYS[0] - BASE:KEYS[0] - BASE + len(keys)].hex(), new=keys.hex(),
             why='look editor page key + INFO (sec 1, dead EVF step-3 gamma tables)'),
        dict(kind='0x100', addr=hex(GUIDE_WORD), expect=struct.pack('<I', STOCK['ep7_guide']).hex(),
             new=struct.pack('<I', syms['ed_guide']).hex(), why='Color Profile view part 3 (guide label) -> ed_guide'),
        dict(kind='0x100', addr=hex(SET_SITE), expect=SET_STOCK, new=set_new.hex(), why='GUI setter -> ed_set'),
        dict(kind='0x100', addr=hex(POLY_SITE), expect=POLY_STOCK, new=poly_new.hex(),
             why='wheel polygon producer: sector value read -> ed_poly (page values)'),
        dict(kind='0x100', addr=hex(VT_GET), expect=struct.pack('<I', STOCK['ep7_get']).hex(),
             new=struct.pack('<I', syms['ed_get']).hex(), why='facade GetValue -> ed_get'),
        dict(kind='0x100', addr=hex(VT_DEF), expect=struct.pack('<I', STOCK['ep7_default']).hex(),
             new=struct.pack('<I', syms['ed_default']).hex(), why='facade GetDefault -> ed_default'),
    ]
    for k, a in RECORDS.items():
        edits.append(dict(kind='0x100', addr=hex(a + 4), expect=struct.pack('<I', STOCK['ep7_init']).hex(),
                          new=struct.pack('<I', syms['ed_init']).hex(), why=f'record {k:#x} init -> ed_init'))
        edits.append(dict(kind='0x100', addr=hex(a + INFO_OFF), expect=struct.pack('<I', STOCK['ep7_info']).hex(),
                          new=struct.pack('<I', syms['ed_info']).hex(), why=f'record {k:#x} INFO (0x9014) -> ed_info'))
    if probe:
        edits.append(dict(kind='0x100', addr=hex(VT_ENTRY), expect=struct.pack('<I', STOCK['ep7_entry']).hex(),
                          new=struct.pack('<I', syms['ed_oprobe']).hex(), why='editor vtable +0 -> ed_oprobe (key probe)'))
        edits.append(dict(kind='0x100', addr=hex(VT_ROUTER), expect=struct.pack('<I', STOCK['ep7_router']).hex(),
                          new=struct.pack('<I', syms['ed_rprobe']).hex(), why='editor vtable +68 -> ed_rprobe (key probe)'))
    for e in edits:
        e['source'] = 'patches/look_editor'
    back_new = (b'\xdc' + struct.pack('<i', syms['ed_trig'] - SD_BACK)).hex()
    meta = dict(keys=[hex(KEYS[0]), len(keys)], keys_region=[hex(KEYS[0]), hex(KEYS[1])], page_keys=[hex(KEY_MENU), hex(KEY_PLAY)],
                pages=PAGES, core=[hex(CORE[0]), len(core)], ui=[hex(UI[0]), len(ui)], view=[hex(VIEW[0]), len(view)], symbols={k: hex(v) for k, v in syms.items()},
                stock={k: hex(v) for k, v in STOCK.items()}, heap=dict(emark=EMARK, axis=AXIS, dirty=DIRTY, status=STATUS, probe_r=PROBE_R, probe_o=PROBE_O), probe=bool(probe),
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
    return spec, merged, core_lst + '\n' + ui_lst + '\n' + keys_lst + '\n' + view_lst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--no-probe', action='store_true', help='drop the key probe (default since 12e)')
    ap.add_argument('--probe', action='store_true', help='build the 12d key probe in (codes in the label)')
    a = ap.parse_args()
    spec, merged, lst = build(a.base, probe=a.probe and not a.no_probe)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'look_editor.lst').write_text(lst)
    if merged:
        (a.out / 'merged.json').write_text(json.dumps(merged, indent=1) + '\n')
    m = spec['look_editor']
    print(f"core {m['core'][1]} B @ {m['core'][0]}, ui {m['ui'][1]} B @ {m['ui'][0]}, view {m['view'][1]} B @ {m['view'][0]}; "
          f"{len(spec['edits'])} edits"
          + (f"; merged {len(merged['edits'])} edits" if merged else ''))


if __name__ == '__main__':
    main()
