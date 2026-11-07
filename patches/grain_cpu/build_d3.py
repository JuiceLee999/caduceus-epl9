#!/usr/bin/env python3
"""grain_cpu d3: t1 + a record of each capture in C:\\EP7MOD\\GRAIND.BIN + a dark band on COLOR4. docs/GRAIN_PORT.md. Offline.

  .venv/bin/python -I patches/grain_cpu/build_d3.py releases/v0.26/edits.json --out generated/grain_cpu/d3/edits.json
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
AT, END = 0x601dff3c, 0x601e0b3c           # t1's block grows down by two dead tables
REFS = T1.REFS + (0x601e3b70, 0x601e3b74, 0x601e3b78, 0x601e3b80, 0x601e3b84, 0x601e3b88)
SD_BACK = MV.SD_BACK


def part(src, first, last):
    a = src.index('\n' + first + ':')
    b = src.index('\n' + last + ':') if last else len(src)
    a2 = src.rfind('/*', 0, a)
    return src[a2 if a - a2 < 400 else a:b]


def source():
    t1 = (HERE / 'gc.s.in').read_text()
    g = T1.weights()
    lines = '\n'.join(' .byte ' + ','.join(map(str, g[i:i + 16])) for i in range(0, 256, 16))
    # gc_open and the leaf routines stay t1's text; gc_open takes the bus address in d0 (already set)
    op = t1[t1.index('\ngc_open:'):t1.index('/* gc_grain:')]
    sh = t1[t1.index('/* gc_cach:'):t1.index('gc_mtab:')]
    s = (HERE / 'gd3.s.in').read_text()
    return (s.replace('{gc_open}', op).replace('{gc_shared}', sh).replace('{g_bytes}', lines).replace('{cap_mode}', str(T1.CAP_MODE)).replace('{cap_profile}', str(T1.CAP_PROFILE))
            .replace('{state}', hex(MV.STATE)).replace('{lim}', hex(MV.LIM)).replace('{pool}', hex(MV.POOL)).replace('{bmagic}', hex(MV.BMAGIC)).replace('{ev_press}', hex(SB3.EV_PRESS)))


def apply(spec):
    stock = T1.STOCK.read_bytes()
    spec = FV.apply(copy.deepcopy(spec), '0.27d3')
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
    code, lst, s, _ = SB3.assemble(source(), AT, dict(T1.SYMS, ep7_bloom_flag=bf, ep7_mv_trig=mt, ep7_wfile=int(spec['look_editor']['symbols']['ed_wfile'], 16)))
    if AT + len(code) > END:
        raise SystemExit(f'{len(code)} B does not fit {END - AT}')
    ins = SB3.disasm(code, AT, s['gc_btab'])
    if any(k == 'abs' for _, _, k, _ in SB3.store_audit(ins)):
        raise SystemExit('absolute store')
    if any(op in T1.BAD for _, op, _ in ins) or any(code[a - AT] == 0xfb for a, _, _ in ins):
        raise SystemExit('forbidden instruction or fb-prefixed form: ' + str([(hex(a), op) for a, op, _ in ins if code[a - AT] == 0xfb or op in T1.BAD][:6]))
    tail = im[bw - BASE:bw + 0x100 - BASE]
    pat = bytes.fromhex('2c5802de0000')
    at = bw + tail.index(pat)
    MV.put(spec, stock, at, b'\x2c\x58\x02', b'\x2c\x00\x04', 'grain_cpu: bw_default 600 -> 1024')
    spec['edits'].append(dict(kind='0x100', addr=hex(AT), expect=stock[AT - BASE:AT - BASE + len(code)].hex(), new=code.hex(), source=SRC,
                              why=f'grain_cpu d3 ({len(code)} B, dead EVF gamma tables)'))
    spec['edits'].append(dict(kind='0x100', addr=hex(T1.SF_WORD), expect=struct.pack('<I', T1.SF).hex(), new=struct.pack('<I', s['gc_gs']).hex(), source=SRC, why='grain_cpu d3: work-list word -> gc_gs'))
    MV.put(spec, stock, T1.FLAG_SITE + 1, struct.pack('<i', bf - T1.FLAG_SITE), struct.pack('<i', s['gc_flag'] - T1.FLAG_SITE), 'grain_cpu d3: flag hook -> gc_flag')
    MV.put(spec, stock, SD_BACK + 1, struct.pack('<i', mt - SD_BACK), struct.pack('<i', s['gc_trig'] - SD_BACK), 'grain_cpu d3: sd_back -> gc_trig')
    spec['grain_cpu'] = dict(built_by=SRC, test='d3', code_at=hex(AT), code_len=len(code), bw_default=hex(at), symbols={k: hex(v) for k, v in s.items() if k.startswith('gc_')}, strengths=[28, 68, 112])
    return spec


FALSE_POS = {0x6014f1b2: 'f0031e60f003', 0x60522232: '02001e6002002560', 0x60fa632e: '00001e601f00', 0x6107a5d6: 'f4011ea00761'}   # unaligned, inside u16 runs, dis-checked


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps({k: v for k, v in spec['grain_cpu'].items() if k != 'symbols'}))
