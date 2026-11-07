#!/usr/bin/env python3
"""grain_cpu s1: CPU film grain from slot byte +50 (Extras sector 1), NR on sector 9, plain looks without Soft Focus passes. docs/GRAIN_PORT.md. Offline.

  .venv/bin/python -I patches/grain_cpu/build_s1.py releases/v0.26/edits.json --out generated/grain_cpu/s1/edits.json
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


T1 = _load('grain_cpu_t1', HERE / 'build.py')
SB3, MV, FV = T1.SB3, T1.MV, T1.FV
BASE, SRC = T1.BASE, 'patches/grain_cpu'
AT, END = 0x601dfc3c, 0x601e0b3c           # t1's block grows down by three dead tables
REFS = T1.REFS + (0x601e3b70, 0x601e3b74, 0x601e3b78, 0x601e3b80, 0x601e3b84, 0x601e3b88, 0x601e3b90, 0x601e3b94, 0x601e3b98)
SD_BACK = MV.SD_BACK
WL_SITE, OB, OB_WORD, TBL_IDX, C = 0x6035749f, 0x6035b529, 0x60357b1f, 0x6055e7b0, 991


def part(src, first, last):
    a = src.index('\n' + first + ':')
    b = src.index('\n' + last + ':') if last else len(src)
    a2 = src.rfind('/*', 0, a)
    return src[a2 if a - a2 < 400 else a:b]


def source():
    t1 = (HERE / 'gc.s.in').read_text()
    g = T1.weights()
    lines = '\n'.join(' .byte ' + ','.join(map(str, g[i:i + 16])) for i in range(0, 256, 16))
    op = t1[t1.index('\ngc_open:'):t1.index('/* gc_grain:')]
    ca = t1[t1.index('/* gc_cach:'):t1.index('/* gc_tbl:')]
    tb = t1[t1.index('/* gc_tbl:'):t1.index('/* gc_p1:')].replace('-945', f'-{C}').replace('945', str(C)).replace('cmp 1103,d1', f'cmp {64 * 32 - C},d1')
    s = (HERE / 'gs1.s.in').read_text()
    return (s.replace('{gc_open}', op).replace('{gc_cach}', ca).replace('{gc_tbl}', tb).replace('{g_bytes}', lines).replace('{cap_mode}', str(T1.CAP_MODE)).replace('{cap_profile}', str(T1.CAP_PROFILE))
            .replace('{state}', hex(MV.STATE)).replace('{lim}', hex(MV.LIM)).replace('{pool}', hex(MV.POOL)).replace('{bmagic}', hex(MV.BMAGIC)).replace('{ev_press}', hex(SB3.EV_PRESS)))


def data_alignment(src, syms):
    """Each label whose first directive is .long / .hword must sit on a 4 / 2 boundary (s1 crashed on a misaligned word table)."""
    import re
    bad, label = [], None
    for line in src.splitlines():
        m = re.match(r'^(\w+):', line)
        if m:
            label = m.group(1)
            continue
        d = line.split('/*')[0].strip()
        if label and d:
            need = 4 if d.startswith('.long') else 2 if (d.startswith('.hword') or d.startswith('.short')) else 0
            if need and label in syms and syms[label] % need:
                bad.append((label, hex(syms[label])))
            label = None
    return bad


def rel(at, dst):
    return struct.pack('<i', dst - at)


def apply(spec):
    stock = T1.STOCK.read_bytes()
    spec = FV.apply(copy.deepcopy(spec), '0.27s3')
    im = MV.img_of(spec, stock)
    T1.AT, T1.END, T1.REFS = AT, END, REFS
    T1.FALSE_POS.update(FALSE_POS)
    T1.check_refs(stock)
    for e in spec['edits']:
        if not e['addr'].startswith('off:') and e['kind'] == '0x100':
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a < END and AT < a + n:
                raise SystemExit(f'overlap with edit {e["addr"]}')
    bf, bw = int(spec['bloom']['symbols']['bloom_flag'], 16), int(spec['bloom']['symbols']['bloom_w'], 16)
    mt = int(spec['v026_movie']['wheel_symbols']['mv_trig'], 16)
    v25 = spec['v025']['symbols']
    wl = int(spec['symbols']['wl_hook'], 16)
    um = next(a for a in range(0x601e2460, 0x601e2490) if im[a - BASE:a - BASE + 4] == bytes.fromhex('f419a1c9'))
    um_yes = um + 3 + struct.unpack('b', im[um + 4 - BASE:um + 5 - BASE])[0] + 0
    syms = dict(T1.SYMS, ep7_bloom_flag=bf, ep7_mv_trig=mt, ep7_wfile=int(spec['look_editor']['symbols']['ed_wfile'], 16), ep7_tbl_idx=TBL_IDX, ep7_wl_final=0x6035739e, ep7_wl_attach=0x603573d3,
                ep7_wl_after=0x603578bd, ep7_wl_hook=wl, ep7_wait=0x60354930, ep7_ob=OB, ep7_g_val=0x601e3322, ep7_s_dirty=0x601e3428, ep7_sg=int(v25['sg'], 16), ep7_ss=int(v25['ss'], 16), ep7_su=int(v25['su'], 16),
                ep7_q_put0=0x601e35b4, ep7_q_out=0x601e35ea, ep7_ex_get=0x601e32a3, ep7_ua_back=0x601e37a5, ep7_um_yes=um_yes, ep7_um_next=um + 5)
    code, lst, s, _ = SB3.assemble(source(), AT, syms)
    if AT + len(code) > END:
        raise SystemExit(f'{len(code)} B does not fit {END - AT}')
    ins = SB3.disasm(code, AT, s['gc_btab'])
    bad_al = data_alignment(source(), s)
    if bad_al:
        raise SystemExit(f'misaligned data: {bad_al}')
    if any(k == 'abs' for _, _, k, _ in SB3.store_audit(ins)):
        raise SystemExit('absolute store')
    if any(op in T1.BAD for _, op, _ in ins) or any(code[a - AT] == 0xfb for a, _, _ in ins):
        raise SystemExit('forbidden instruction or fb-prefixed form: ' + str([(hex(a), op) for a, op, _ in ins if code[a - AT] == 0xfb or op in T1.BAD][:6]))
    tail = im[bw - BASE:bw + 0x100 - BASE]
    at = bw + tail.index(bytes.fromhex('2c5802de0000'))
    p = lambda addr, old, new, why: MV.put(spec, stock, addr, old, new, why)
    p(at, b'\x2c\x58\x02', b'\x2c\x00\x04', 'grain_cpu: bw_default 600 -> 1024')
    spec['edits'].append(dict(kind='0x100', addr=hex(AT), expect=stock[AT - BASE:AT - BASE + len(code)].hex(), new=code.hex(), source=SRC, why=f'grain_cpu s1 ({len(code)} B, dead EVF gamma tables)'))
    spec['edits'].append(dict(kind='0x100', addr=hex(T1.SF_WORD), expect=struct.pack('<I', T1.SF).hex(), new=struct.pack('<I', s['gc_gs']).hex(), source=SRC, why='grain_cpu s1: blend word -> gc_gs'))
    if stock[OB_WORD - 2 - BASE:OB_WORD + 4 - BASE] != b'\xfc\xcd' + struct.pack('<I', OB):
        raise SystemExit('output pass word differs: ' + stock[OB_WORD - 2 - BASE:OB_WORD + 4 - BASE].hex())
    spec['edits'].append(dict(kind='0x100', addr=hex(OB_WORD), expect=struct.pack('<I', OB).hex(), new=struct.pack('<I', s['gc_ob']).hex(), source=SRC, why='grain_cpu s1: output pass word -> gc_ob'))
    p(T1.FLAG_SITE + 1, rel(T1.FLAG_SITE, bf), rel(T1.FLAG_SITE, s['gc_flag']), 'flag hook -> gc_flag')
    p(SD_BACK + 1, rel(SD_BACK, mt), rel(SD_BACK, s['gc_trig']), 'sd_back -> gc_trig')
    p(WL_SITE + 1, rel(WL_SITE, wl), rel(WL_SITE, s['gc_wl']), 'work-list hook -> gc_wl')
    # Extras: sector 1 Grain (+50), sector 9 NR (+24)
    p(0x601e32c9, rel(0x601e32c8, 0x601e38dd), rel(0x601e32c8, s['gc_g1']), 'sector 1 read -> gc_g1')
    p(0x601e33d8, rel(0x601e33d7, 0x601e3890), rel(0x601e33d7, s['gc_s1']), 'sector 1 write -> gc_s1')
    p(0x601e356e, struct.pack('<I', 0x601e3840), struct.pack('<I', s['gc_t1']), 'sector 1 labels -> gc_t1')
    for site, old, new in ((0x601e1263, v25['sg'], 'gc_sg9'), (0x601e128b, v25['ss'], 'gc_ss9'), (0x601e12ea, v25['su'], 'gc_su9')):
        p(site + 1, rel(site, int(old, 16)), rel(site, s[new]), f'sector 9 -> {new}')
    p(0x601e3713, b'Extras: 1-8 only', b'Extras: 1-9 only', 'Extras label')
    # A Film pick and the `*` leave NR and Grain alone (+50 was already past u_apply's bound)
    p(0x601e2e36, rel(0x601e2e35, 0x601e37a3), rel(0x601e2e35, s['gc_ua']), 'u_apply keeps +24')
    p(um, im[um - BASE:um + 5 - BASE], b'\xdc' + rel(um, s['gc_um']), 'lt_mod ignores +24')
    # Saved files: BUNDLES.BIN +50 0..3; MOVIE.BIN check starts at +51
    p(0x605b7721 + 50, b'\x00', b'\x03', 'SD loader v3 range: slot +50 0..3')
    p(0x601e0d12, struct.pack('<H', 866), struct.pack('<H', 867), 'mv_load: zero check from +51')
    p(0x601e0d15, b'\x0e', b'\x0d', 'mv_load: zero check 13 B')
    spec['grain_cpu'] = dict(built_by=SRC, test='s3', code_at=hex(AT), code_len=len(code), bw_default=hex(at), um=hex(um), symbols={k: hex(v) for k, v in s.items() if k.startswith('gc_')}, strengths=[23, 55, 91], centre=C, slot_byte=50, sector_grain=1, sector_nr=9, k=4)
    return spec


FALSE_POS = {0x6014f1b2: 'f0031e60f003', 0x60522232: '02001e6002002560', 0x60fa632e: '00001e601f00', 0x6107a5d6: 'f4011ea00761', 0x60020871: 'cdfc1da018', 0x606c81d2: 'ccfd1da023'}   # unaligned, inside u16 runs, dis-checked


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps({k: v for k, v in spec['grain_cpu'].items() if k != 'symbols'}))
