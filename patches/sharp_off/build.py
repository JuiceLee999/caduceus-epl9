#!/usr/bin/env python3
"""Sharpening off per COLOR profile, test t1: Extras sector 10 "Sharp", slot byte +51, stills and the Movie slot. Offline.
docs/SHARPENING_OFF.md.

  .venv/bin/python -I patches/sharp_off/build.py releases/v0.27/edits.json --out generated/sharp/t1/edits.json
  .venv/bin/python -I tools/build_package.py generated/sharp/t1/edits.json --out generated/sharp/t1/pkg
  .venv/bin/python -I patches/sharp_off/verify.py releases/v0.27/edits.json generated/sharp/t1/edits.json generated/sharp/t1/pkg

apply(spec, version='0.28t1') -> spec, layered on v0.27 (grain r1: sector 1 Grain +50, sector 9 NR +24).
"""
import argparse, copy, importlib.util, json, re, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


MV = _load('ep7_v026_movie', ROOT / 'patches/v026_movie/build.py')
FV = _load('fw_version_build', ROOT / 'patches/fw_version/build.py')
SB3, STOCK = MV.SB3, MV.STOCK
BASE, SRC = 0x60020020, 'patches/sharp_off'
AT, END = 0x601de13c, 0x601de33c          # the two lowest dead EVF gamma tables; only refs: their step-table words
REFS = (0x601e3c20, 0x601e3c24)
FALSE_POS = {0x606c81c5: 'cce21da0'}      # jmp 0x606c9fa7 bytes, dis-checked
GETTER, KEY = 0x6005e971, 0x8119
CAP_SITE = 0x602a7eda                     # capture: mov 0x8119,d0; call getter,[d2,d3],12; movhu d0,(24010,d3)
MSG_SITE, MSG_RET = 0x60315900, 0x60315908   # message +20 site (v0.26 jmp mv_msg); message +18 = Sharpness written just before
SG_SITE, SS_SITE, SU_SITE = 0x601e1263, 0x601e128b, 0x601e12ea   # tone_x: jmp gc_sg9 / gc_ss9 / gc_su9
DEF_SITE = 0x601e3348                     # ex_default hit tail: jmp gc_def
X_SITE, X_OLD = 0x601e12a8, 0x601e3713    # tone_x: mov "Extras: 1-9 only",a2
RANGE = 0x605b7721                        # SD loader v3 per-byte span table (slot byte n at +n)
MVL_OFF, MVL_CNT = 0x601e0d12, 0x601e0d15 # mv_load: add 867,a0 (zero check from +51); mov 13,d0
SLOT_BYTE, SECTOR = 51, 10
BAD = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}


def rel(at, dst):
    return struct.pack('<i', dst - at)


def img_of(spec, stock):
    return MV.img_of(spec, stock)


def put(spec, stock, addr, old, new, why):
    """Into the edit that covers addr, else a new edit. old = the bytes there now (checked)."""
    im = img_of(spec, stock)
    if im[addr - BASE:addr - BASE + len(old)] != old:
        raise SystemExit(f'{addr:#x}: {im[addr - BASE:addr - BASE + len(old)].hex()} != {old.hex()} ({why})')
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a <= addr and addr + len(new) <= a + n:
                b = bytearray.fromhex(e['new']); b[addr - a:addr - a + len(new)] = new; e['new'] = b.hex()
                e['why'] += f' [sharp_off: {why}]'
                return
            if a < addr + len(new) and addr < a + n:
                raise SystemExit(f'{addr:#x}: straddles edit {e["addr"]}')
    spec['edits'].append(dict(kind='0x100', addr=hex(addr), expect=stock[addr - BASE:addr - BASE + len(new)].hex(), new=new.hex(), source=SRC, why=f'sharp_off {why}'))


def check_free(spec, stock):
    import numpy as np
    for e in spec['edits']:
        if not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a < END and AT < a + n:
                raise SystemExit(f'overlap with edit {e["addr"]}')
    for off in range(4):
        w = np.frombuffer(stock[off:off + (len(stock) - off) // 4 * 4], dtype='<u4')
        for k in np.nonzero(((w >= AT) & (w < END)) | ((w >= AT + 0x40000000) & (w < END + 0x40000000)))[0]:
            at = BASE + off + 4 * int(k)
            if at in FALSE_POS and stock[at - BASE:at - BASE + 4].hex() == FALSE_POS[at]:
                continue
            if at not in REFS:
                raise SystemExit(f'reference into {AT:#x}..{END:#x} at {at:#x}')


def data_alignment(src, syms):
    """Each label whose first directive is .long / .hword / .short must sit on a 4 / 2 boundary (grain s1 crashed on one)."""
    bad, label = [], None
    for line in src.splitlines():
        m = re.match(r'^(\w+):', line)
        if m:
            label = m.group(1)
            continue
        d = line.split('/*')[0].strip()
        if label and d:
            need = 4 if d.startswith('.long') or d.startswith('.word') else 2 if (d.startswith('.hword') or d.startswith('.short')) else 0
            if need and syms.get(label, 0) % need:
                bad.append((label, hex(syms[label])))
            label = None
    return bad


def source(spec):
    sub = dict(state=hex(MV.STATE), lim=hex(MV.LIM), pool=hex(MV.POOL), bmagic=hex(MV.BMAGIC), vm=MV.VM, vp=MV.VP, vmagic=hex(MV.VMAGIC))
    return SB3.subst((HERE / 'sh.s.in').read_text(), sub)


def symbols(spec):
    v25, gc, mv = spec['v025']['symbols'], spec['grain_cpu']['symbols'], spec['v026_movie']['symbols']
    return dict(ep7_getter=GETTER, ep7_sc_slot=int(v25['sc_slot'], 16), ep7_sc_real=int(v25['sc_real'], 16), ep7_mv_msg=int(mv['mv_msg'], 16),
                ep7_gc_sg9=int(gc['gc_sg9'], 16), ep7_gc_ss9=int(gc['gc_ss9'], 16), ep7_gc_su9=int(gc['gc_su9'], 16), ep7_gc_def=int(gc['gc_def'], 16),
                ep7_g_val=0x601e3322, ep7_s_dirty=0x601e3428, ep7_ex_get=0x601e32a3, ep7_q_put0=0x601e35b4, ep7_q_out=0x601e35ea)


def apply(spec, version='0.28t1'):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    if spec.get('grain_cpu', {}).get('slot_byte') != 50 or spec['grain_cpu'].get('sector_nr') != 9 or not spec['v026_movie'].get('wheel'):
        raise SystemExit('base is not v0.27 (grain +50, NR sector 9, Movie slot wheel)')
    spec = FV.apply(spec, version)
    im = img_of(spec, stock)
    check_free(spec, stock)
    # +51 must be unused: flashed table zero, no reader in our blocks besides ours (checked by verify), loaders reject it today
    if any(im[0x60210900 + 64 * k + SLOT_BYTE - BASE] for k in range(8)) or im[RANGE + SLOT_BYTE - BASE] != 0:
        raise SystemExit('slot byte +51 not free in this base')
    syms = symbols(spec)
    src = source(spec)
    code, lst, s, _ = SB3.assemble(src, AT, syms)
    if AT + len(code) > END:
        raise SystemExit(f'{len(code)} B does not fit {END - AT}')
    ins = SB3.disasm(code, AT, s['sh_cam'])
    if any(op in BAD for _, op, _ in ins) or any(k == 'abs' for _, _, k, _ in SB3.store_audit(ins)) or any(code[a - AT] == 0xfb for a, _, _ in ins):
        raise SystemExit('forbidden instruction, fb-prefixed form or absolute store')
    bad_al = data_alignment(src, s)
    if bad_al or AT % 4 or s['sh_cam'] % 4:
        raise SystemExit(f'misaligned data: {bad_al}')
    spec['edits'].append(dict(kind='0x100', addr=hex(AT), expect=stock[AT - BASE:AT - BASE + len(code)].hex(), new=code.hex(), source=SRC,
                              why=f'sharp_off t1 ({len(code)} B, two lowest dead EVF gamma tables)'))
    p = lambda addr, old, new, why: put(spec, stock, addr, old, new, why)
    # stills: the capture Sharpness read
    if im[CAP_SITE - 6 - BASE:CAP_SITE - BASE] != b'\xfc\xcc' + struct.pack('<I', KEY) or im[CAP_SITE - BASE] != 0xdd or im[CAP_SITE + 5 - BASE:CAP_SITE + 7 - BASE] != b'\xc0\x0c':
        raise SystemExit('capture site differs')
    p(CAP_SITE + 1, rel(CAP_SITE, GETTER), rel(CAP_SITE, s['sh_get']), 'capture Sharpness read -> sh_get')
    # movie: chain the message hook
    mvm = syms['ep7_mv_msg']
    p(MSG_SITE, b'\xdc' + rel(MSG_SITE, mvm), b'\xdc' + rel(MSG_SITE, s['sh_msg']), 'message hook jmp mv_msg -> sh_msg (then mv_msg)')
    # Extras sector 10
    for site, old, new in ((SG_SITE, 'ep7_gc_sg9', 'sh_sg'), (SS_SITE, 'ep7_gc_ss9', 'sh_ss'), (SU_SITE, 'ep7_gc_su9', 'sh_su'), (DEF_SITE, 'ep7_gc_def', 'sh_def')):
        p(site, b'\xdc' + rel(site, syms[old]), b'\xdc' + rel(site, s[new]), f'{old[4:]} -> {new}')
    p(X_SITE, b'\xfc\xde' + struct.pack('<I', X_OLD), b'\xfc\xde' + struct.pack('<I', s['sh_x']), 'sectors 11-12 label -> "Extras: 1-10 only"')
    # saved files: BUNDLES.BIN +51 0..1; MOVIE.BIN zero check from +52
    p(RANGE + SLOT_BYTE, b'\x00', b'\x01', 'SD loader v3 range: slot +51 0..1')
    p(MVL_OFF, struct.pack('<H', 867), struct.pack('<H', 868), 'mv_load: zero check from +52')
    p(MVL_CNT, b'\x0d', b'\x0c', 'mv_load: zero check 12 B')
    spec['sharp_off'] = dict(built_by=SRC, test='t1', version=version, code_at=hex(AT), code_len=len(code), slot_byte=SLOT_BYTE, sector=SECTOR, value=-5,
                             symbols={k: hex(v) for k, v in s.items() if k.startswith('sh_')},
                             sites=[hex(x) for x in (CAP_SITE + 1, MSG_SITE, SG_SITE, SS_SITE, SU_SITE, DEF_SITE, X_SITE + 2, RANGE + SLOT_BYTE, MVL_OFF, MVL_CNT)])
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--version', default='0.28t1')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()), a.version)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps({k: v for k, v in spec['sharp_off'].items() if k != 'symbols'}))
