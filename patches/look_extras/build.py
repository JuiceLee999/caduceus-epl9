#!/usr/bin/env python3
"""Build the look-extras layer (X axis: grain / glow-clarity / WB A-B / WB G-M) over a look-editor build.
Design: docs/LOOK_EXTRAS.md. Offline only.

  .venv/bin/python -I patches/look_extras/build.py --editor generated/look_editor_12c/merged.json \
      --key-word 52 --events 0x9012,0x9016 --out generated/look_extras

The input is a merged spec from patches/look_editor/build.py --base (12c or later: it must carry ed_get, ed_default,
ed_set, ed_poke and ed_guide). The layer does not touch the editor's code bytes. It re-points 1 + 2 + 1 + 4 words /
sites that the editor build already owns to our entries, which fall through to the editor's routine on a miss:

  0x60acb0e4 facade GetValue   ed_get     -> ex_get
  0x60acb174 facade GetDefault ed_default -> ex_default
  0x607fa355 GUI setter call   ed_set     -> ex_set
  0x6025aa98 view part 3       ed_guide   -> ex_guide
  COLOR1-4 record +KEY_WORD    (editor's axis-key handler, or stock) -> ex_event
and adds ex_core + ex_ui in the dead EVF step-2/1 gamma tables 0x601e323c..0x601e383c (section 1, 1536 B).

Writes OUT/merged.json (editor merged spec with the layer applied) and OUT/look_extras.lst.
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


B3 = _load('ep7_sd_bundles_v3_build_x', ROOT / 'patches/sd_bundles_v3/build.py')
V1 = B3.V1
BASE, MAIN, MAIN_SHA = B3.BASE, B3.MAIN, B3.MAIN_SHA

REGION = (0x601e323c, 0x601e383c)        # EVF gamma steps 2 and 1, R/G/B tables (6 x 256 B); only refs: step table
STEPTAB = 0x601e3b3c                     # 2 devices x 20 slots x {u8 step, R*, G*, B*}; device 1 = EVF (absent)
REGION_REFS = {0x601e323c + 256 * i: STEPTAB + 320 + 16 * (2 - i // 3) + 4 + 4 * (i % 3) for i in range(6)}
VT_GET, VT_DEF = 0x60acb0e4, 0x60acb174
SET_SITE = 0x607fa355
GUIDE_WORD = 0x6025aa98
RECORDS = {0x13b3: 0x61185bdc, 0x13b4: 0x61185c14, 0x13b5: 0x61185c4c, 0x140c: 0x61185c84}
DEF_IMG = 0x6025bad0                     # .data init image of the parent +48..+88 defaults (record +12..+52)
STOCK = dict(ep7_get=0x607f9549, ep7_default=0x607f964a, ep7_manager=0x60827440, ep7_sget=0x602af887,
             ep7_refresh=0x60de3670, ep7_facade=0x607f9062, ep7_guide=0x60decbfc)
EMARK, AXIS, DIRTY = 680, 684, 685
EMAGIC = struct.unpack('<I', b'EP7E')[0]
ALL_FLAGS = (0x61fc3800, 0x61fc3804)


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


def call_target(d, at):
    if d[at - BASE] != 0xdd:
        raise ValueError(f'{at:#x} is not a call d32')
    return at + struct.unpack_from('<i', d, at - BASE + 1)[0]


def check_stock(stock):
    for st in (1, 2):
        got = struct.unpack_from('<B3xIII', stock, STEPTAB + 320 + 16 * st - BASE)
        if got != (st,) + tuple(REGION[1] - 768 * st + 256 * c for c in range(3)):
            raise ValueError(f'EVF step-{st} slot differs')
    for t, ref in REGION_REFS.items():
        hits = [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', t)), stock)]
        if hits != [ref]:
            raise ValueError(f'{t:#x} referenced at {[hex(h) for h in hits]}')
    # nothing in the image points INTO the region except those three table starts
    import numpy as np
    lo, hi = REGION
    for off in range(4):
        w = np.frombuffer(stock[off:off + (len(stock) - off) // 4 * 4], dtype='<u4')
        idx = np.nonzero((w >= lo) & (w < hi))[0]
        for k in idx:
            at = BASE + off + 4 * int(k)
            if int(w[k]) not in REGION_REFS or REGION_REFS[int(w[k])] != at:
                raise ValueError(f'abs32 into the EVF region at {at:#x} -> {int(w[k]):#x}')
    if stock[SET_SITE - BASE:SET_SITE - BASE + 7].hex() != 'ddebd00200e010':
        raise ValueError('setter site differs')


def loader_allows_clarity(patched):
    """The loader's per-byte span table (64 B) in the patched image must give effect_id (+28) span 3."""
    lo, span, _ = V1.range_table(V1.layout())
    want = bytes(span)
    hits = [m.start() for m in re.finditer(re.escape(want), patched)]
    if len(hits) != 1:                           # a base built before art_effect (+46, v0.14): span 0 there
        w2 = bytearray(span)
        w2[46] = 0
        hits = [m.start() for m in re.finditer(re.escape(bytes(w2)), patched)]
    if len(hits) != 1:                           # ... and before bloom_tint (+45, test13b)
        w2[45] = 0
        hits = [m.start() for m in re.finditer(re.escape(bytes(w2)), patched)]
    if len(hits) == 1:
        return True
    old = bytearray(span)
    old[28] = 2
    old[45] = old[46] = 0
    if bytes(old) in patched:
        return False
    raise ValueError(f'loader span table found {len(hits)} times')


def sub(x_axis, x_prev, ev_a, ev_b):
    return dict(state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL), bmagic=hex(B3.MAGIC), emark=EMARK,
                emagic=hex(EMAGIC), axis=AXIS, dirty=DIRTY, x_axis=x_axis, x_prev=x_prev, ev_a=hex(ev_a), ev_b=hex(ev_b))


def source(name, override=None):
    return (override or {}).get(name) or (HERE / name).read_text()


def build(editor_spec, key_word=0, events=(0x9012, 0x9016), x_axis=4, x_prev=2, override=None):
    spec = json.loads(Path(editor_spec).read_text()) if not isinstance(editor_spec, dict) else editor_spec
    meta = spec.get('look_editor') or spec.get('meta', {}).get('look_editor')
    if not meta:
        raise ValueError('not a look-editor merged spec')
    esym = {k: int(v, 16) for k, v in meta['symbols'].items()}
    need = ('ed_get', 'ed_default', 'ed_set', 'ed_poke', 'ed_guide') + (('ed_cfg_x',) if key_word == 0 else ('ed_probe',))
    for k in need:
        if k not in esym:
            raise ValueError(f'editor build lacks {k} (12e: ed_cfg_x)')
    if key_word not in (0, 36, 44, 48, 52):
        raise ValueError('key word must be 0 (12e: the editor steps to X) or a record event slot (+36/+44/+48/+52)')
    if not (0 < x_axis < 256 and 0 <= x_prev < 256 and x_axis != x_prev):
        raise ValueError('bad axis values')
    stock, patched = image(spec)
    check_stock(stock)
    if not loader_allows_clarity(patched):
        raise ValueError('base loader rejects effect_id 3 (clarity): build the base with patches/bloom --clarity')
    # the words the editor owns must hold the editor's symbols (else this layer was built for another editor)
    owned = {VT_GET: esym['ed_get'], VT_DEF: esym['ed_default'], GUIDE_WORD: esym['ed_guide']}
    for a, want in owned.items():
        if u32(patched, a) != want:
            raise ValueError(f'{a:#x} holds {u32(patched, a):#x}, not the editor symbol {want:#x}')
    if call_target(patched, SET_SITE) != esym['ed_set']:
        raise ValueError('setter site does not call ed_set')
    syms = dict(STOCK, ed_get=esym['ed_get'], ed_default=esym['ed_default'], ed_set=esym['ed_set'],
                ed_poke=esym['ed_poke'], ex_guide_next=esym['ed_guide'])
    if key_word:
        nexts = set()
        for k, rec in RECORDS.items():
            w = u32(patched, rec + key_word)
            nexts.add(w if w else u32(stock, DEF_IMG + key_word - 12))
        if len(nexts) != 1:
            raise ValueError(f'record +{key_word} words differ: {[hex(x) for x in nexts]}')
        syms.update(ex_event_next=nexts.pop(), ed_probe=esym['ed_probe'])
    elif patched[esym['ed_cfg_x'] - BASE] != 0:
        raise ValueError('editor ed_cfg_x is not 0 (another X layer?)')
    s = sub(x_axis, x_prev, *events)
    core, core_lst, core_syms, _ = B3.assemble(B3.subst(source('ex_core.s.in', override), s), REGION[0], syms)
    ui_at = REGION[0] + (len(core) + 3) // 4 * 4
    ui, ui_lst, ui_syms, _ = B3.assemble(B3.subst(source('ex_ui.s.in', override), s), ui_at, dict(syms, ex_get=core_syms['ex_get']))
    if ui_at + len(ui) > REGION[1]:
        raise ValueError(f'core {len(core)} + ui {len(ui)} B do not fit {REGION[1] - REGION[0]}')
    if core_syms['ex_find'] != REGION[0] or ui_syms[('ex_event' if key_word else 'ex_guide')] != ui_at:
        raise ValueError('entry layout')
    xs = {k: v for k, v in {**core_syms, **ui_syms}.items() if not k.startswith(('_', '.'))}
    bad = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}
    audit = []
    for name, code, at, stop in (('core', core, REGION[0], core_syms['ex_core_end']),
                                 ('ui', ui, ui_at, ui_syms['ex_ui_data'])):
        ins = B3.disasm(code, at, stop)
        if any(op in bad for _, op, _ in ins):
            raise ValueError(f'{name}: forbidden instruction')
        for a, t, kind, tgt in B3.store_audit(ins):
            if kind == 'abs':
                raise ValueError(f'{name}: absolute store at {a:#x}: {t}')
            audit.append((hex(a), t, kind))
    blob = core + b'\xff' * (ui_at - REGION[0] - len(core)) + ui
    rec = struct.pack
    layer = [
        dict(kind='0x100', addr=hex(REGION[0]), expect=stock[REGION[0] - BASE:REGION[0] - BASE + len(blob)].hex(),
             new=blob.hex(), why='look extras ex_core + ex_ui (sec 1, dead EVF step-2/1 gamma tables)'),
    ]
    retarget = {VT_GET: rec('<I', xs['ex_get']), VT_DEF: rec('<I', xs['ex_default']),
                GUIDE_WORD: rec('<I', xs['ex_guide']),
                SET_SITE: b'\xdd' + rec('<i', xs['ex_set'] - SET_SITE) + b'\xe0\x10'}
    if key_word:
        for a in RECORDS.values():
            retarget[a + key_word] = rec('<I', xs['ex_event'])
    edits, seen = [], set()
    cfg_done = key_word != 0
    for e in spec['edits']:
        a = int(e['addr'], 16)
        n = len(e['new']) // 2
        if not key_word and a <= esym['ed_cfg_x'] < a + n:      # 12e: the editor's page cycle gets the X stop
            nb = bytearray.fromhex(e['new'])
            nb[esym['ed_cfg_x'] - a] = x_axis
            e = dict(e, new=nb.hex(), why=e['why'] + f' + look extras: ed_cfg_x = {x_axis}')
            cfg_done = True
        if a in retarget:
            new = retarget[a]
            if len(bytes.fromhex(e['new'])) != len(new):
                raise ValueError(f'edit {a:#x} length')
            e = dict(e, new=new.hex(), why=e['why'] + ' -> look extras layer', source='patches/look_extras')
            seen.add(a)
        edits.append(e)
    if not cfg_done:
        raise ValueError('ed_cfg_x not inside an editor edit')
    for a, new in retarget.items():
        if a not in seen:                        # e.g. +44 INFO words the editor leaves stock
            edits.append(dict(kind='0x100', addr=hex(a), expect=stock[a - BASE:a - BASE + len(new)].hex(),
                              new=new.hex(), why='look extras retarget', source='patches/look_extras'))
    for e in layer:
        e['source'] = 'patches/look_extras'
    # no layer code may overlap any other edit
    for e in edits:
        a, n = int(e['addr'], 16), len(e['new']) // 2
        if a < REGION[1] and REGION[0] < a + n:
            raise ValueError(f'edit {a:#x} overlaps the extras region')
    xmeta = dict(region=[hex(REGION[0]), hex(REGION[1])], core=[hex(REGION[0]), len(core)], ui=[hex(ui_at), len(ui)],
                 symbols={k: hex(v) for k, v in xs.items()}, next={k: hex(v) for k, v in syms.items()},
                 key_word=key_word, events=[hex(x) for x in events], x_axis=x_axis, x_prev=x_prev,
                 stores=audit, editor_spec=str(editor_spec) if not isinstance(editor_spec, dict) else '(dict)')
    merged = dict(spec, edits=edits + layer, look_extras=xmeta)
    merged.setdefault('meta', {})['look_extras'] = xmeta
    return merged, core_lst + '\n' + ui_lst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--editor', required=True, type=Path, help='look-editor merged spec (12c or later)')
    ap.add_argument('--key-word', type=int, default=0, help='0 (12e: the editor page key steps to X) or the COLOR record word of an axis key (52 Movie, 44 INFO)')
    ap.add_argument('--events', default='0x9012,0x9016', help='two event codes that step H -> X')
    ap.add_argument('--x-axis', type=int, default=4)
    ap.add_argument('--x-prev', type=int, default=2)
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()
    ev = tuple(int(x, 0) for x in a.events.split(','))
    if len(ev) == 1:
        ev = ev * 2
    merged, lst = build(a.editor, a.key_word, ev, a.x_axis, a.x_prev)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'merged.json').write_text(json.dumps(merged, indent=1) + '\n')
    (a.out / 'look_extras.lst').write_text(lst)
    m = merged['look_extras']
    print(f"core {m['core'][1]} B @ {m['core'][0]}, ui {m['ui'][1]} B @ {m['ui'][0]} "
          f"(region {m['region'][0]}..{m['region'][1]}); {len(merged['edits'])} edits; next {m['next'].get('ex_event_next', 'none (ed_cfg_x)')}")


if __name__ == '__main__':
    main()
