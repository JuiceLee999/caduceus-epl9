#!/usr/bin/env python3
"""Build the mono film presets (docs/MONO_PRESETS.md) as a layer over a look-editor spec. Offline, no camera.

  .venv/bin/python -I patches/mono_presets/build.py --base generated/test13r/fm/merged.json --out generated/test13r/mp

INFO in the stock MONO1-4 colour-filter and shading editors (records +44, stock `mov 3,d0; retf` = close) steps
the profile through the presets below: each sets 8 stock mono settings through the facade SetValue (the stock edit
path) and the MONO slot name in the card table (saved by the editor's half-press save). Code in the dead EVF gamma
step-5 tables 0x601e293c.. (only refs: the step-table words 0x601e3cd0/d4/d8, build-checked).
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


LE = _load('ep7_look_editor_build_mp', ROOT / 'patches/look_editor/build.py')
B3 = LE.B3
BASE, MAIN, MAIN_SHA = B3.BASE, B3.MAIN, B3.MAIN_SHA

CODE = (0x601e283c, 0x601e2c3c)          # sec 1: dead EVF gamma step-6 B + step-5 R/G/B tables (test13b: +256 B)
CODE_REFS = {0x601e283c: 0x601e3ce8, 0x601e293c: 0x601e3cd0, 0x601e2a3c: 0x601e3cd4, 0x601e2b3c: 0x601e3cd8}
FALSE_POS = 0x60d37d59                   # 08 2c 1e 60 inside two instructions (dis-checked)
INFO_F, INFO_S = 0x60e22d8b, 0x60e22fae  # stock +44 words: both `mov 3,d0; retf [],0`
REC_TABLE, REC_N = 0x6118474c, 167
KEYS_F = [0x13b6, 0x13b7, 0x13b8, 0x140d]    # MONO1-4 colour filter editors (children 987/991 ...)
KEYS_S = [0x13b9, 0x13ba, 0x13bb, 0x140e]    # MONO1-4 shading editors (995 ...)
DESC = 0x61186ba4                        # editor descriptor table (47 x {u16 key, u16 n, u32 children})
# per MONO m: filter, filter strength, toning, grain, shading, highlights, shadows, midtones. From the picture
# parameter builder 0x602b7b71 MONO branches (public modes 57/58/59/65) and the validator lists 0x604cc98c [V];
# Highlights / shadows / midtones: camera test 13b (PB021374/75, MONO1 'Red Contrast' HL +1 SH -2 MID 0 written to
# 998/999/1000) recorded makernote ToneLevel Highlights +1, Shadows 0, Midtones -2, so 999 = midtones and
# 1000 = shadows [V camera]; MONO4 assumed the same order (1676 = midtones, 1677 = shadows) [I]. Filter red /
# strength 2, grain low, shading -1 and toning none landed as written [V camera].
FIELDS = ['filter', 'strength', 'toning', 'grain', 'shading', 'highlights', 'shadows', 'midtones']
IDS = [[987, 991, 984, 981, 995, 998, 1000, 999],
       [988, 992, 985, 982, 996, 1001, 1003, 1002],
       [989, 993, 986, 983, 997, 1004, 1006, 1005],
       [1680, 1681, 1679, 1678, 1671, 1675, 1677, 1676]]
# filter values: matrix table 0x60531bc0 (0x603acec9) luminance weights [V]: 1 Y, 2 O, 3 R, 4 G, 5 YG, 6 Mg, 7 B, 8 Cy
FILTER = dict(none=0, yellow=1, orange=2, red=3, green=4, yellow_green=5, magenta=6, blue=7, cyan=8)
TONING = dict(none=0, sepia=1, blue=2, purple=3, green=4)      # Olympus picture-tone order [I]
GRAIN = dict(off=0, low=1, medium=2, high=3)
# extra OM-style presets (the library v2 mono looks come first)
EXTRA = [
    dict(name='Red Contrast', filter='red', strength=2, toning='none', grain='low', shading=-1,
         highlights=1, shadows=-2, midtones=0),
    dict(name='Sepia Print', filter='none', strength=1, toning='sepia', grain='low', shading=-2,
         highlights=-1, shadows=1, midtones=0),
    dict(name='Cyanotype', filter='yellow', strength=1, toning='blue', grain='off', shading=0,
         highlights=0, shadows=-1, midtones=0),
]
EMARK, AXIS, DIRTY, STATUS = LE.EMARK, LE.AXIS, LE.DIRTY, LE.STATUS
MPOS, MMARK = 1004, 1008                 # heap P: pos[4] (past the probe's +1000..1003, below the film +1016..)
MMAGIC = struct.unpack('<I', b'EP7M')[0]
STOCK = dict(ep7_info_f=INFO_F, ep7_info_s=INFO_S, ep7_facade=0x607f9062, ep7_refresh=0x60de3670)


def library_presets():
    lib = json.loads((ROOT / 'bundles/library_v2.json').read_text())
    rec = json.loads((ROOT / 'sim/recipes/library_v2.json').read_text())['recipes']
    out = []
    for k, v in lib['looks'].items():
        r = rec[v['recipe']]
        if not r.get('mono_filter'):
            continue
        mf, tone = r['mono_filter'], r.get('tone', {})
        out.append(dict(name=v['name'], filter=mf.get('colour', 'none'), strength=mf.get('strength', 1),
                        toning='none', grain=v.get('grain', r.get('grain', 'off')), shading=int(r.get('vignette', 0)),
                        highlights=tone.get('highlights', 0), shadows=tone.get('shadows', 0),
                        midtones=tone.get('midtones', 0)))
    return out


def presets():
    return library_presets() + EXTRA


def values(p):
    return [FILTER[p['filter'].replace('-', '_')], int(p['strength']), TONING[p['toning']], GRAIN[p['grain']],
            int(p['shading']), int(p['highlights']), int(p['shadows']), int(p['midtones'])]


def u32(d, a):
    return struct.unpack_from('<I', d, a - BASE)[0]


def u16(d, a):
    return struct.unpack_from('<H', d, a - BASE)[0]


def validator(d, sid):
    """static validator record list of setting sid (docs/BUTTONS.md §2 layout) -> list of values."""
    for i in range(1400):
        a = 0x604cc98c + 20 * i
        s, attr, lst, alt, nb, el, sub, ty = struct.unpack_from('<HHIIHHBB', d, a - BASE)
        if s == sid:
            fmt = {1: 'b', 2: 'h', 4: 'i'}[el]
            return list(struct.unpack_from(f'<{nb // el}{fmt}', d, lst - BASE))
    raise ValueError(f'no validator record for {sid}')


def check_stock(d):
    import numpy as np
    if struct.unpack_from('<B3xIII', d, 0x601e3b3c + 320 + 16 * 5 - BASE) != (5, 0x601e293c, 0x601e2a3c, 0x601e2b3c) or \
            struct.unpack_from('<B3xIII', d, 0x601e3b3c + 320 + 16 * 6 - BASE) != (6, 0x601e263c, 0x601e273c, 0x601e283c):
        raise ValueError('EVF step-5/6 slot differs')
    for off in range(4):
        w = np.frombuffer(d[off:off + (len(d) - off) // 4 * 4], dtype='<u4')
        for k in np.nonzero((w >= CODE[0]) & (w < CODE[1]))[0]:
            at = BASE + off + 4 * int(k)
            if at == FALSE_POS and d[at - 1 - BASE:at + 4 - BASE].hex() == '5c082c1e60':
                continue                 # mid-instruction: `mov (8,sp),a0; mov 24606,d0` at 0x60d37d58 (not a ref)
            if CODE_REFS.get(int(w[k])) != at:
                raise ValueError(f'abs32 reference into the step-5 tables at {at:#x}')
    for t in (INFO_F, INFO_S):
        if d[t - BASE:t - BASE + 5].hex() != '8003de0000':
            raise ValueError(f'{t:#x} is not `mov 3,d0; retf`')
    keys = [u16(d, REC_TABLE + 56 * i) for i in range(REC_N)]
    recs = {}
    for k in KEYS_F + KEYS_S:
        if keys.count(k) != 1:
            raise ValueError(f'record {k:#x} not unique')
        a = REC_TABLE + 56 * keys.index(k)
        if u32(d, a + 44) != (INFO_F if k in KEYS_F else INFO_S) or u32(d, a + 4) != 0x60e20a54:
            raise ValueError(f'record {k:#x} words differ')
        recs[k] = a
    hits = [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', INFO_F)), d)]
    if sorted(hits) != sorted(recs[k] + 44 for k in KEYS_F):
        raise ValueError(f'{INFO_F:#x} refs {[hex(h) for h in hits]}')
    # descriptor: filter editors {filter, strength}, shading editors {shading} of MONO m
    for m in range(4):
        for k, want in ((KEYS_F[m], [IDS[m][0], IDS[m][1]]), (KEYS_S[m], [IDS[m][4]])):
            for i in range(47):
                a = DESC + 8 * i
                if u16(d, a) == k:
                    p = u32(d, a + 4)
                    got = [u32(d, p + 8 * j + 4) for j in range(u16(d, a + 2))]
                    if got != want:
                        raise ValueError(f'editor {k:#x} children {got} != {want}')
    return recs


def build(base_spec, out):
    spec = json.loads(Path(base_spec).read_text())
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    recs = check_stock(d)
    ps = presets()
    if not 1 <= len(ps) <= 12:
        raise ValueError('1..12 presets')
    tab = b''
    for p in ps:
        nm = p['name'].encode('ascii')
        if not 1 <= len(nm) <= 12 or b'@' in nm or any(not 0x20 <= c <= 0x7e for c in nm) or nm != nm.strip():
            raise ValueError(f'name {p["name"]!r}')
        v = values(p)
        for m in range(4):
            for f, (sid, x) in enumerate(zip(IDS[m], v)):
                if x not in validator(d, sid):
                    raise ValueError(f'{p["name"]}: {FIELDS[f]} = {x} not in setting {sid} list {validator(d, sid)}')
        tab += nm.ljust(16, b'\0') + struct.pack('<8b', *v)
    if len(set(p['name'] for p in ps)) != len(ps):
        raise ValueError('duplicate preset names')
    lines = lambda b, w: '\n'.join(' .byte ' + ','.join(str(x) for x in b[i:i + w]) for i in range(0, len(b), w))
    sub = dict(state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL), bmagic=hex(B3.MAGIC), nmagic=hex(B3.NMAGIC),
               emark=EMARK, emagic=hex(LE.EMAGIC), axis=AXIS, dirty=DIRTY, status=STATUS, mpos=MPOS, mmark=MMARK,
               mmagic=hex(MMAGIC), n=len(ps), nf=len(FIELDS),
               ids='\n'.join(' .hword ' + ','.join(str(x) for x in row) for row in IDS), tab=lines(tab, 24))
    src = B3.subst((HERE / 'mp.s.in').read_text(), sub)
    code, lst, syms, _ = B3.assemble(src, CODE[0], STOCK)
    if syms['mp_info_f'] != CODE[0] or CODE[0] + len(code) > CODE[1]:
        raise ValueError(f'mp: {len(code)} B does not fit {CODE[1] - CODE[0]}')
    ins = B3.disasm(code, CODE[0], syms['mp_data'])
    if any(op in {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'} for _, op, _ in ins):
        raise ValueError('forbidden instruction')
    for a, t, kind, tgt in B3.store_audit(ins):
        if kind == 'abs':
            raise ValueError(f'absolute store at {a:#x}: {t}')
    if code[syms['mp_tab'] - CODE[0]:syms['mp_tab'] - CODE[0] + len(tab)] != tab:
        raise ValueError('preset table bytes')
    for e in spec['edits']:
        a, n = int(e['addr'], 16), len(e['new']) // 2
        if a < CODE[1] and CODE[0] < a + n:
            raise ValueError(f'edit {a:#x} overlaps the step-5 claim')
        for r in recs.values():
            if a < r + 48 and r + 44 < a + n:
                raise ValueError(f'edit {a:#x} overlaps a MONO record +44')
    new = [dict(kind='0x100', addr=hex(CODE[0]), expect=d[CODE[0] - BASE:CODE[0] - BASE + len(code)].hex(),
                new=code.hex(), why=f'mono presets: mp_info_f/_s + {len(ps)} presets (sec 1, dead EVF step-5 tables)')]
    for k, a in recs.items():
        new.append(dict(kind='0x100', addr=hex(a + 44), expect=struct.pack('<I', INFO_F if k in KEYS_F else INFO_S).hex(),
                        new=struct.pack('<I', syms['mp_info_f' if k in KEYS_F else 'mp_info_s']).hex(),
                        why=f'MONO editor {k:#x} INFO (+44) -> mono preset step'))
    for e in new:
        e['source'] = 'patches/mono_presets'
    meta = dict(code=[hex(CODE[0]), len(code)], symbols={k: hex(v) for k, v in syms.items() if not k.startswith(('_', '.'))},
                presets=[dict(p, values=values(p)) for p in ps], fields=FIELDS, ids=IDS, heap=dict(mpos=MPOS, mmark=MMARK),
                records={hex(k): hex(a) for k, a in recs.items()}, stock={k: hex(v) for k, v in STOCK.items()})
    merged = dict(spec, edits=spec['edits'] + new, mono_presets=meta)
    merged.setdefault('meta', {})['mono_presets'] = meta
    out.mkdir(parents=True, exist_ok=True)
    (out / 'merged.json').write_text(json.dumps(merged, indent=1) + '\n')
    (out / 'edits.json').write_text(json.dumps(dict(components=['0x100'], patch='mono_presets', edits=new, mono_presets=meta), indent=1) + '\n')
    (out / 'mono_presets.lst').write_text(lst)
    print(f'mono presets {len(code)} B @ {CODE[0]:#x}, {len(ps)} presets: {", ".join(p["name"] for p in ps)}; '
          f'{len(merged["edits"])} edits')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()
    build(a.base, a.out)


if __name__ == '__main__':
    main()
