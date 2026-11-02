#!/usr/bin/env python3
"""v0.19 release spec (offline): v0.18 + patches/tone_ends + SD loader accepts Blacks/Whites + fw label 0.19.

  .venv/bin/python -I patches/v019/build.py [--base releases/v0.18/edits.json] --out releases/v0.19/edits.json

1. patches/tone_ends (per-COLOR-slot Blacks +47 / Whites +48 on the luminance tone LUT, docs/TONE_ENDS.md).
2. SD loader v3 (edit at 0x605b7400): data only. Its per-byte range table (sd_lo[64] + sd_span[64]) is swapped
   from the released rule (bytes 47..63 must be 0) to range_table(tone=True): +47/+48 accept -5..5 in every slot.
   The MONO-zero rule (patches/sd_bundles table_ok(tone=True)) is enforced by the desktop tools only; on the
   camera a MONO slot's +47/+48 is never read (the tone hook reads COLOR slots 0..3 only). Code bytes, sd_back
   and every label stay byte-identical (checked).
3. patches/v019/tone_x.s.in: Extras sectors 6 "Blacks" / 7 "Whites" in the colour editor (slot +47/+48), four
   same-size redirects inside the released look-extras blob (each site's v0.18 bytes checked) + 0x601e123c (dead
   EVF step-13 G table; only reference: step-table word 0x601e3d54, checked).
4. patches/fw_version --mod-version v0.19 (replaces the 0.18 label edits).
5. patches/v019/look_tone.s.in: a Film pick applies the look's tone (LOOKS.BIN v3 tone block, tools/ep7_looks_bin.py):
   lt_post at the dead EVF step-7 R/G tables 0x601e233c (only refs: step-table words 0x601e3cf0/f4, checked), entered
   from fm_ui's final jump 0x601e2e93 (was jmp fm_post; chains on to it); the editor's ed_cfg_fm word -> lt_mod;
   fm_core's LOOKS.BIN range table +35..37 -> -7..7 (data, same size).
"""
import argparse, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


TE = _load('ep7_tone_ends_build', ROOT / 'patches/tone_ends/build.py')
SB = _load('ep7_sd_bundles_build', ROOT / 'patches/sd_bundles/build.py')
FW = _load('ep7_fw_version_build', ROOT / 'patches/fw_version/build.py')
SB3 = _load('ep7_sd_bundles_v3_build', ROOT / 'patches/sd_bundles_v3/build.py')
LOADER_AT, SD_BACK, SD_BACK_JMP = 0x605b7400, 0x605b7420, 'dc20ffffff'


def b8(v):
    return bytes(x & 0xff for x in v)


def loader_swap(spec):
    lay = SB.layout()
    lo0, sp0, _ = SB.range_table(lay)
    lo1, sp1, _ = SB.range_table(lay, tone=True)
    hits = [e for e in spec['edits'] if e['kind'] == '0x100' and int(e['addr'], 16) == LOADER_AT]
    if len(hits) != 1:
        raise ValueError('loader edit not found once')
    e = hits[0]
    blob = bytes.fromhex(e['new'])
    old, new = b8(lo0) + b8(sp0), b8(lo1) + b8(sp1)
    if blob.count(old) != 1:
        raise ValueError(f'loader range table found {blob.count(old)} times (want 1)')
    i = blob.index(old)
    blob2 = blob[:i] + new + blob[i + len(old):]
    o = SD_BACK - LOADER_AT
    if blob2[o:o + 5].hex() != SD_BACK_JMP:
        raise ValueError('loader sd_back is not jmp ed_trig')
    diff = [k for k in range(len(blob)) if blob[k] != blob2[k]]
    if not diff or min(diff) < i or max(diff) >= i + len(old):
        raise ValueError('loader change outside the range table')
    e['new'] = blob2.hex()
    e['why'] += ' [v0.19: slot +47 blacks / +48 whites accept -5..5]'
    return dict(table_at=hex(LOADER_AT + i), changed=[hex(LOADER_AT + k) for k in diff])


X_AT, X_END, X_REF = 0x601e123c, 0x601e133c, 0x601e3d54
EXTRAS_AT = 0x601e323c
# site: (v0.18 bytes, entry label); targets: the layer's own labels at their released addresses
X_SITES = {0x601e32f4: ('af04c822c629', 'xg'), 0x601e3394: ('af05c405cca600', 'xs'),
           0x601e34b6: ('f8632ca004', 'xq'), 0x601e3541: ('fcde13371e60af05c66b', 'xu')}
X_SYMS = dict(g_art=0x601e3318, g_wb=0x601e32fa, g_zero=0x601e3321, g_val=0x601e3322, s_cont=0x601e339b,
              s_refresh=0x601e343e, s_dirty=0x601e3428, q_label=0x601e34db, q_out=0x601e35ea, q_cont=0x601e34c0,
              u_cont=0x601e354b, q_put0=0x601e35b4, q_put=0x601e35b5, ex_get=0x601e32a3,
              t_other=0x601e3713)
T_OTHER_OLD, T_OTHER_NEW = b'Extras: 1-5 only\0', b'Extras: 1-7 only\0'
STOCK_MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'


def jmp(at, to, n):
    return (b'\xdc' + struct.pack('<i', to - at)).ljust(n, b'\xcb')


def extras_x(spec):
    stock = STOCK_MAIN.read_bytes()
    B = 0x60020020
    for e in spec['edits']:
        if e['addr'].startswith('off:'):
            continue
        a, n = int(e['addr'], 16), len(e['new']) // 2
        if a < X_END and X_AT - 16 < a + n:
            raise ValueError(f'tone_x region overlaps edit {e["addr"]}')
    if struct.unpack_from('<I', stock, X_REF - B)[0] != X_AT:
        raise ValueError('step-13 G word is not 0x601e123c')
    hits = [i + B for i in range(0, len(stock) - 3) if X_AT <= struct.unpack_from("<I", stock, i)[0] < X_END]
    if hits != [X_REF]:
        raise ValueError(f'references into the tone_x region: {[hex(h) for h in hits]}')
    src = (ROOT / 'patches/v019/tone_x.s.in').read_text()
    for k in X_SYMS:
        src = src.replace('{' + k + '}', 'ep7_' + k)
    if '{' in src.split('*/', 1)[1]:
        raise ValueError('unsubstituted field in tone_x.s.in')
    code, lst, syms, _ = SB3.assemble(src, X_AT, {'ep7_' + k: v for k, v in X_SYMS.items()})
    if X_AT + len(code) > X_END:
        raise ValueError(f'tone_x {len(code)} B overflows')
    ex = [e for e in spec['edits'] if e['kind'] == '0x100' and int(e['addr'], 16) == EXTRAS_AT]
    if len(ex) != 1:
        raise ValueError('look-extras edit not found once')
    blob = bytearray.fromhex(ex[0]['new'])
    for at, (old, entry) in X_SITES.items():
        o, old = at - EXTRAS_AT, bytes.fromhex(old)
        if bytes(blob[o:o + len(old)]) != old:
            raise ValueError(f'extras site {at:#x} is not the v0.18 bytes')
        blob[o:o + len(old)] = jmp(at, syms[entry], len(old))
    o = X_SYMS['t_other'] - EXTRAS_AT
    if bytes(blob[o:o + len(T_OTHER_OLD)]) != T_OTHER_OLD:
        raise ValueError('ex_t_other is not "Extras: 1-5 only"')
    blob[o:o + len(T_OTHER_NEW)] = T_OTHER_NEW
    ex[0]['new'] = blob.hex()
    ex[0]['why'] += ' [v0.19: sectors 6 Blacks / 7 Whites via patches/v019/tone_x]'
    spec['edits'].append(dict(kind='0x100', addr=hex(X_AT), expect=stock[X_AT - B:X_AT - B + len(code)].hex(),
                              new=code.hex(), source='patches/v019',
                              why=f'v0.19 Extras sectors 6 Blacks / 7 Whites (tone_x, {len(code)} B, dead EVF step-13 G table)'))
    return dict(at=hex(X_AT), len=len(code), symbols={k: hex(v) for k, v in syms.items() if not k.startswith('_')},
                sites={hex(a): v[1] for a, v in X_SITES.items()}), lst


LT_AT, LT_END, LT_REFS = 0x601e233c, 0x601e253c, {0x601e3cf0, 0x601e3cf4}
LT_SITE, FM_UI, ED_CFG_FM, FM_MOD = 0x601e2e93, 0x601e2c3c, 0x601e3160, 0x6143a6ad
FM_CORE, FM_LO, FM_SPAN = 0x6143a410, 0x6143a788, 0x6143a7b5
FB = _load('ep7_film_menu_v2_build_v019', ROOT / 'patches/film_menu_v2/build.py')
LB = FB.LB


def _edit_at(spec, a):
    hits = [e for e in spec['edits'] if not e['addr'].startswith('off')
            and int(e['addr'], 16) <= a < int(e['addr'], 16) + len(e['new']) // 2]
    if len(hits) != 1:
        raise ValueError(f'{a:#x}: in {len(hits)} edits')
    return hits[0], a - int(hits[0]['addr'], 16)


def look_tone(spec):
    stock = STOCK_MAIN.read_bytes()
    B = 0x60020020
    for e in spec['edits']:
        if e['addr'].startswith('off:'):
            continue
        a, n = int(e['addr'], 16), len(e['new']) // 2
        if a < LT_END and LT_AT - 16 < a + n:
            raise ValueError(f'look_tone region overlaps edit {e["addr"]}')
    hits = set()
    for off in range(4):
        for i in range(off, len(stock) - 3, 4):
            w = struct.unpack_from('<I', stock, i)[0]
            if LT_AT <= w < LT_END:
                hits.add(i + B)
    if hits != LT_REFS:
        raise ValueError(f'references into the look_tone region: {sorted(hex(h) for h in hits)}')
    fm_post = int(spec['lv_art_refresh']['symbols']['fm_post'], 16)
    code, lst, syms, _ = SB3.assemble(FB.source(str(ROOT / 'patches/v019/look_tone.s.in')), LT_AT,
                                      dict(ep7_facade=0x607f9062, ep7_fm_post=fm_post))
    if syms['lt_post'] != LT_AT or LT_AT + len(code) > LT_END:
        raise ValueError(f'look_tone {len(code)} B does not fit')
    bad = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}
    ins = SB3.disasm(code, LT_AT, syms['lt_end'])
    if any(op in bad for _, op, _ in ins):
        raise ValueError('look_tone: forbidden instruction')
    stores = [(hex(a), t, k) for a, t, k, _ in SB3.store_audit(ins)]
    if any(k == 'abs' for _, _, k in stores):
        raise ValueError('look_tone: absolute store')
    # fm_ui final jump: jmp fm_post -> jmp lt_post
    e, o = _edit_at(spec, LT_SITE)
    blob = bytearray.fromhex(e['new'])
    if bytes(blob[o:o + 5]) != jmp(LT_SITE, fm_post, 5):
        raise ValueError('fm_ui final jump is not jmp fm_post')
    blob[o:o + 5] = jmp(LT_SITE, syms['lt_post'], 5)
    e['new'] = blob.hex()
    e['why'] += ' [v0.19 look tone: final jump -> lt_post]'
    # editor ed_cfg_fm word: fm_mod -> lt_mod
    e, o = _edit_at(spec, ED_CFG_FM)
    blob = bytearray.fromhex(e['new'])
    if struct.unpack_from('<I', blob, o)[0] != FM_MOD:
        raise ValueError('ed_cfg_fm is not fm_mod')
    struct.pack_into('<I', blob, o, syms['lt_mod'])
    e['new'] = blob.hex()
    e['why'] += ' [v0.19 look tone: ed_cfg_fm -> lt_mod]'
    # fm_check range table: +35..37 (H/M/S of a tone record) -7..7
    lo, span, _ = LB.SB.range_table(LB.SB.layout())
    e, o = _edit_at(spec, FM_CORE)
    blob = bytearray.fromhex(e['new'])
    lo_o, sp_o = FM_LO - FM_CORE, FM_SPAN - FM_CORE
    if bytes(blob[lo_o:lo_o + 45]) != b8(lo[:45]) or bytes(blob[sp_o:sp_o + 45]) != bytes(span[:45]):
        raise ValueError('fm_core range tables not found')
    for off, (l, sp) in LB.TONE_RANGE.items():
        blob[lo_o + off], blob[sp_o + off] = l & 0xff, sp
    e['new'] = blob.hex()
    e['why'] += ' [v0.19 look tone: LOOKS.BIN +35..37 accept -7..7]'
    spec['edits'].append(dict(kind='0x100', addr=hex(LT_AT), expect=stock[LT_AT - B:LT_AT - B + len(code)].hex(),
                              new=code.hex(), source='patches/v019',
                              why=f'v0.19 look tone on a Film pick (lt_post / lt_mod, {len(code)} B, dead EVF step-7 R/G)'))
    return dict(at=hex(LT_AT), len=len(code), site=hex(LT_SITE), fm_post=hex(fm_post),
                symbols={k: hex(v) for k, v in syms.items() if k.startswith(('lt_', 't_', 'm_'))}, stores=stores), lst


def make(base_path):
    _, merged, *_ = TE.make_spec(base_path)
    lr = loader_swap(merged)
    tx, _ = extras_x(merged)
    merged['tone_x'] = tx
    lt, _ = look_tone(merged)
    merged['look_tone'] = lt
    FW.apply(merged, 'v0.19')
    merged['v019'] = dict(loader_ranges=lr, built_by='patches/v019/build.py', base=str(base_path))
    return merged


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', type=Path, default=ROOT / 'releases/v0.18/edits.json')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = make(a.base)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1) + '\n')
    print(f'{len(spec["edits"])} edits -> {a.out}; loader range table at {spec["v019"]["loader_ranges"]["table_at"]}, '
          f'changed {spec["v019"]["loader_ranges"]["changed"]}')


if __name__ == '__main__':
    main()
