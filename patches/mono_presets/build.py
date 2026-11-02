#!/usr/bin/env python3
"""Build the mono film presets (docs/MONO_PRESETS.md) as a layer over a look-editor spec. Offline, no camera.

  .venv/bin/python -I patches/mono_presets/build.py --base generated/test13r/fm/merged.json --out generated/test13r/mp

v0.15 picker: INFO toggles a Film page in the MONO filter/shading editors (dial, arrows step presets,
label "Film: <name>[*]"); MENU/PLAYBACK stay stock. Part A code 0x601e283c, part B (label, tables) 0x601e173c.
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

CODE = (0x601e283c, 0x601e2c3c)          # part A (code): dead EVF gamma step-6 B + step-5 R/G/B tables
CODE_REFS = {0x601e283c: 0x601e3ce8, 0x601e293c: 0x601e3cd0, 0x601e2a3c: 0x601e3cd4, 0x601e2b3c: 0x601e3cd8}
CODE_B = (0x601e173c, 0x601e1b3c)        # part B (label + tables, v0.15): dead EVF gamma step-11 R/G/B + step-10 R
CODE_B_REFS = {0x601e173c: 0x601e3d30, 0x601e183c: 0x601e3d34, 0x601e193c: 0x601e3d38, 0x601e1a3c: 0x601e3d20}
FALSE_POS = 0x60d37d59                   # 08 2c 1e 60 inside two instructions (dis-checked)
INFO_F, INFO_S = 0x60e22d8b, 0x60e22fae  # stock +44 words: both `mov 3,d0; retf [],0`
REC_TABLE, REC_N = 0x6118474c, 167
KEYS_F = [0x13b6, 0x13b7, 0x13b8, 0x140d]    # MONO1-4 colour filter editors (children 987/991 ...)
KEYS_S = [0x13b9, 0x13ba, 0x13bb, 0x140e]    # MONO1-4 shading editors (995 ...)
INIT = 0x60e20a54                        # record +4 (every editor parent)
# hooked record words: offset -> (name, stock filter word, stock shading word, our symbol f, our symbol s)
HOOKS = {44: ('INFO', INFO_F, INFO_S, 'mp_info_f', 'mp_info_s')}   # v0.15b: INFO steps presets (camera-proven route)
OPS = [44]           # op = 2 act + kind, act in this record-offset order (mp.s.in mp_tramp)
DESC = 0x61186ba4                        # editor descriptor table (47 x {u16 key, u16 n, u32 children})
# per MONO m: filter, filter strength, toning, grain, shading, highlights, shadows, midtones. From the picture
# parameter builder 0x602b7b71 MONO branches (public modes 57/58/59/65) and the validator lists 0x604cc98c [V];
# Highlights / shadows / midtones: camera test 13b (PB021374/75) -> 999 = midtones, 1000 = shadows [V camera];
# MONO4 assumed the same order (1676 = midtones, 1677 = shadows) [I].
FIELDS = ['filter', 'strength', 'toning', 'grain', 'shading', 'highlights', 'shadows', 'midtones']
IDS = [[987, 991, 984, 981, 995, 998, 1000, 999],
       [988, 992, 985, 982, 996, 1001, 1003, 1002],
       [989, 993, 986, 983, 997, 1004, 1006, 1005],
       [1680, 1681, 1679, 1678, 1671, 1675, 1677, 1676]]
# filter values: matrix table 0x60531bc0 (0x603acec9) luminance weights [V]: 1 Y, 2 O, 3 R, 4 G, 5 YG, 6 Mg, 7 B, 8 Cy
FILTER = dict(none=0, yellow=1, orange=2, red=3, green=4, yellow_green=5, magenta=6, blue=7, cyan=8)
TONING = dict(none=0, sepia=1, blue=2, purple=3, green=4)      # Olympus picture-tone order [I]
GRAIN = dict(off=0, low=1, medium=2, high=3)
# v0.15 picker order (slowest film first, then the toned prints). 'lib' = take the values from library v2.
P = lambda name, f, s, t, g, sh, hl, sd, md: dict(name=name, filter=f, strength=s, toning=t, grain=g, shading=sh,
                                                  highlights=hl, shadows=sd, midtones=md)
ORDER = [
    P('Pan F 50', 'yellow', 1, 'none', 'off', 0, 1, -3, 1),         # fine, contrasty
    'Acros',
    P('T-Max 100', 'none', 1, 'none', 'off', 0, -1, 0, 1),          # fine, smooth, open mids
    P('SFX 200', 'red', 3, 'none', 'medium', -1, 2, -2, 0),          # Ilford SFX-ish deep red
    'Tri-X 400',
    'HP5 Plus',
    P('Delta 3200', 'none', 1, 'none', 'high', -2, -2, 2, 1),        # grainy, flat, dark corners
    P('Sepia Print', 'none', 1, 'sepia', 'low', -2, -1, 1, 0),
    P('Selenium', 'none', 1, 'purple', 'low', -1, 0, -2, 0),         # cool split tone, deep blacks
    P('Cyanotype', 'yellow', 1, 'blue', 'off', 0, 0, -1, 0),
]
LABEL_MAX = 20                           # guide characters (13c camera: "Preset: Red Contrast" = 20 shown)
EMARK, AXIS, DIRTY, STATUS = LE.EMARK, LE.AXIS, LE.DIRTY, LE.STATUS
MPOS, MMARK, MPAGE = 1004, 1008, 1012    # heap P: pos[4], 'EP7M', Film page byte (below the film +1016..)
MMAGIC = struct.unpack('<I', b'EP7M')[0]
# preset label: Profile view (0x60e26ab0) MONO filter page / shading page `call 0x60e26789,[],0` sites
LBL_SITES = {0x60e27209: ('mp_lbl1', '5c0891cd7df50000'), 0x60e275c1: ('mp_lbl2', '9899cdc6f10000')}
LBL_GET = (0x60e26789, 'f80154de0000')     # `mov (84,a1),d0; retf` (replayed in mp_lbl1/2)
# v0.15c SCP route: the SCP colour-filter view (factory id 0x78, vtable 0x6117f4e8) draws through a .data parts list
# (0x61fc3570, init image 0x6025b830 = .data - 0x1d67d40); part 0 0x60e11afd writes the filter name into view+20.
SCP_PART_WORD, SCP_PART = 0x6025b830, 0x60e11afd
SCP_PARTS = (0x60e11afd, 0x60e11b3c, 0x60e11b8d, 0x60e11d18, 0)
STOCK = dict(ep7_facade=0x607f9062, ep7_refresh=0x60de3670, ep7_init=INIT,
             ep7_info_f=INFO_F, ep7_info_s=INFO_S, ep7_up_f=0x60e22b0c, ep7_up_s=0x60e22d90,
             ep7_dn_f=0x60e22b55, ep7_dn_s=0x60e22dbc, ep7_lt_f=0x60e22b9e, ep7_lt_s=0x60e22de8,
             ep7_rt_f=0x60e22bca, ep7_rt_s=0x60e22dec,
             ep7_d1_f=0x60e22bf6, ep7_d1_s=0x60e22df0, ep7_scp_lbl=0x60e11afd)


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
    lib = {p['name']: p for p in library_presets()}
    return [lib[p] if isinstance(p, str) else p for p in ORDER]


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
            struct.unpack_from('<B3xIII', d, 0x601e3b3c + 320 + 16 * 6 - BASE) != (6, 0x601e263c, 0x601e273c, 0x601e283c) or \
            struct.unpack_from('<B3xIII', d, 0x601e3b3c + 320 + 16 * 11 - BASE) != (11, 0x601e173c, 0x601e183c, 0x601e193c) or \
            struct.unpack_from('<B3xIII', d, 0x601e3b3c + 320 + 16 * 10 - BASE)[:2] != (10, 0x601e1a3c):
        raise ValueError('EVF step-5/6/10/11 slot differs')
    for off in range(4):
        w = np.frombuffer(d[off:off + (len(d) - off) // 4 * 4], dtype='<u4')
        for lo, hi, refs in ((CODE[0], CODE[1], CODE_REFS), (CODE_B[0], CODE_B[1], CODE_B_REFS)):
            for k in np.nonzero((w >= lo) & (w < hi))[0]:
                at = BASE + off + 4 * int(k)
                if at == FALSE_POS and d[at - 1 - BASE:at + 4 - BASE].hex() == '5c082c1e60':
                    continue             # mid-instruction: `mov (8,sp),a0; mov 24606,d0` at 0x60d37d58 (not a ref)
                if refs.get(int(w[k])) != at:
                    raise ValueError(f'abs32 reference into a claimed EVF table at {at:#x}')
    for t in (INFO_F, INFO_S):
        if d[t - BASE:t - BASE + 5].hex() != '8003de0000':
            raise ValueError(f'{t:#x} is not `mov 3,d0; retf`')
    for a, exp in [(k, v[1]) for k, v in LBL_SITES.items()] + [LBL_GET]:
        if d[a - BASE:a - BASE + len(exp) // 2].hex() != exp:
            raise ValueError(f'label site {a:#x} differs')
    if [u32(d, SCP_PART_WORD + 4 * i) for i in range(5)] != list(SCP_PARTS) or \
            [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', SCP_PART_WORD + 0x1d67d40)), d)] != [0x60e11a38 + 2] or \
            d[SCP_PART - BASE:SCP_PART - BASE + 2].hex() != 'cf30':
        raise ValueError('SCP filter view parts list differs')
    keys = [u16(d, REC_TABLE + 56 * i) for i in range(REC_N)]
    recs = {}
    for k in KEYS_F + KEYS_S:
        if keys.count(k) != 1:
            raise ValueError(f'record {k:#x} not unique')
        a = REC_TABLE + 56 * keys.index(k)
        for off, (nm, wf, ws, _, _) in HOOKS.items():
            if u32(d, a + off) != (wf if k in KEYS_F else ws):
                raise ValueError(f'record {k:#x} +{off} ({nm}) differs')
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


def audit(code, at, data_at, what):
    ins = B3.disasm(code, at, data_at)
    if any(op in {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'} for _, op, _ in ins):
        raise ValueError(f'{what}: forbidden instruction')
    for a, t, kind, tgt in B3.store_audit(ins):
        if kind == 'abs':
            raise ValueError(f'{what}: absolute store at {a:#x}: {t}')


def label_texts(ps):
    out = ['Film[INFO]']
    for p in ps:
        out += [f'{p["name"]}*']                     # v0.18: no "Film: " prefix
    return out


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
    if len(set(p['name'] for p in ps)) != len(ps) or len(set(tuple(values(p)) for p in ps)) != len(ps):
        raise ValueError('duplicate preset names or values')
    if max(len(t) for t in label_texts(ps)) > LABEL_MAX:
        raise ValueError('label too long')
    lines = lambda b, w: '\n'.join(' .byte ' + ','.join(str(x) for x in b[i:i + w]) for i in range(0, len(b), w))
    sub = dict(state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL), bmagic=hex(B3.MAGIC), nmagic=hex(B3.NMAGIC),
               emark=EMARK, emagic=hex(LE.EMAGIC), axis=AXIS, dirty=DIRTY, status=STATUS, mpos=MPOS, mmark=MMARK,
               mpage=MPAGE, mmagic=hex(MMAGIC), n=len(ps), nf=len(FIELDS),
               ids='\n'.join(' .hword ' + ','.join(str(x) for x in row) for row in IDS), tab=lines(tab, 24))
    # part B first (self-contained), then part A against B's tables
    code_b, lst_b, syms_b, _ = B3.assemble(B3.subst((HERE / 'mp_b.s.in').read_text(), sub), CODE_B[0], STOCK)
    if syms_b['mp_lbl1'] != CODE_B[0] or CODE_B[0] + len(code_b) > CODE_B[1]:
        raise ValueError(f'mp_b: {len(code_b)} B does not fit {CODE_B[1] - CODE_B[0]}')
    if syms_b['mp_tab'] % 4 or code_b[syms_b['mp_tab'] - CODE_B[0]:syms_b['mp_tab'] - CODE_B[0] + len(tab)] != tab:
        raise ValueError('preset table bytes / alignment')
    audit(code_b, CODE_B[0], syms_b['mp_t_film'], 'mp_b')
    ext = dict(STOCK, mp_keys=syms_b['mp_keys'], mp_ids=syms_b['mp_ids'], mp_tab=syms_b['mp_tab'])
    code, lst, syms, _ = B3.assemble(B3.subst((HERE / 'mp.s.in').read_text(), sub), CODE[0], ext)
    if syms['mp_info_f'] != CODE[0] or CODE[0] + len(code) > CODE[1]:
        raise ValueError(f'mp: {len(code)} B does not fit {CODE[1] - CODE[0]}')
    if syms['mp_tramp_end'] - syms['mp_tramp'] != 8 * 2 * len(OPS):
        raise ValueError('trampolines are not 8 bytes each')
    tr = code[syms['mp_tramp'] - CODE[0]:syms['mp_tramp_end'] - CODE[0]]
    for op in range(2 * len(OPS)):
        off, kind = OPS[op // 2], op % 2
        t = tr[8 * op:8 * op + 8]
        tgt = (syms['mp_tramp'] + 8 * op + 3 + struct.unpack_from('<i', t, 4)[0]) & 0xffffffff
        if t[:4] != bytes.fromhex('9cce f0dc'.replace(' ', '')) or tgt != HOOKS[off][1 + kind]:
            raise ValueError(f'trampoline {op} {t.hex()} -> {tgt:#x}')
    audit(code, CODE[0], syms['mp_end_a'], 'mp')
    for e in spec['edits']:
        a, n = int(e['addr'], 16), len(e['new']) // 2
        for lo, hi in (CODE, CODE_B):
            if a < hi and lo < a + n:
                raise ValueError(f'edit {a:#x} overlaps a mono claim')
        for r in recs.values():
            for off in HOOKS:
                if a < r + off + 4 and r + off < a + n:
                    raise ValueError(f'edit {a:#x} overlaps a MONO record word')
        for s0, (_, exp) in list(LBL_SITES.items()) + [(SCP_PART_WORD, (0, '00' * 4))]:
            if a < s0 + len(exp) // 2 and s0 < a + n:
                raise ValueError(f'edit {a:#x} overlaps label site {s0:#x}')
    new = [dict(kind='0x100', addr=hex(CODE[0]), expect=d[CODE[0] - BASE:CODE[0] - BASE + len(code)].hex(),
                new=code.hex(), why=f'mono presets part A: picker hooks (sec 1, dead EVF step-6 B / step-5 tables)'),
           dict(kind='0x100', addr=hex(CODE_B[0]), expect=d[CODE_B[0] - BASE:CODE_B[0] - BASE + len(code_b)].hex(),
                new=code_b.hex(), why=f'mono presets part B: guide label + {len(ps)} presets (sec 1, dead EVF step-11 tables)')]
    for k, a in recs.items():
        kf = k in KEYS_F
        for off, (nm, wf, ws, sf, ss) in HOOKS.items():
            if (sf if kf else ss) is None:
                continue
            new.append(dict(kind='0x100', addr=hex(a + off), expect=struct.pack('<I', wf if kf else ws).hex(),
                            new=struct.pack('<I', syms[sf if kf else ss]).hex(),
                            why=f'MONO editor {k:#x} {nm} (+{off}) -> {sf if kf else ss}'))
    for a, (sym, exp) in LBL_SITES.items():
        rel = (syms_b[sym] - a) & 0xffffffff
        nb = b'\xdd' + struct.pack('<I', rel) + b'\0\0' + b'\xcb' * (len(exp) // 2 - 7)
        new.append(dict(kind='0x100', addr=hex(a), expect=exp, new=nb.hex(),
                        why=f'Profile view MONO page guide label -> {sym} (call {syms_b[sym]:#x},[],0)'))
    new.append(dict(kind='0x100', addr=hex(SCP_PART_WORD), expect=struct.pack('<I', SCP_PART).hex(),
                    new=struct.pack('<I', syms_b['mp_lbl3']).hex(),
                    why='SCP colour-filter view part 0 (filter name label, .data 0x61fc3570 init image) -> mp_lbl3'))
    for e in new:
        e['source'] = 'patches/mono_presets'
    allsyms = {**syms_b, **syms}
    meta = dict(code=[hex(CODE[0]), len(code)], code_b=[hex(CODE_B[0]), len(code_b)],
                symbols={k: hex(v) for k, v in allsyms.items() if not k.startswith(('_', '.'))},
                presets=[dict(p, values=values(p)) for p in ps], fields=FIELDS, ids=IDS,
                heap=dict(mpos=MPOS, mmark=MMARK, mpage=MPAGE), hooks={str(k): v[0] for k, v in HOOKS.items()},
                records={hex(k): hex(a) for k, a in recs.items()}, stock={k: hex(v) for k, v in STOCK.items()})
    merged = dict(spec, edits=spec['edits'] + new, mono_presets=meta)
    merged.setdefault('meta', {})['mono_presets'] = meta
    out.mkdir(parents=True, exist_ok=True)
    (out / 'merged.json').write_text(json.dumps(merged, indent=1) + '\n')
    (out / 'edits.json').write_text(json.dumps(dict(components=['0x100'], patch='mono_presets', edits=new, mono_presets=meta), indent=1) + '\n')
    (out / 'mono_presets.lst').write_text(lst + '\n\n' + lst_b)
    print(f'mono presets A {len(code)} B @ {CODE[0]:#x}, B {len(code_b)} B @ {CODE_B[0]:#x}, {len(ps)} presets: '
          f'{", ".join(p["name"] for p in ps)}; {len(new)} new, {len(merged["edits"])} edits')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    a = ap.parse_args()
    build(a.base, a.out)


if __name__ == '__main__':
    main()
