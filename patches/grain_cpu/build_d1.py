#!/usr/bin/env python3
"""grain_cpu d1: t1 + a readout on the Firmware screen + a dark band on COLOR4. docs/GRAIN_PORT.md. Offline.

  .venv/bin/python -I patches/grain_cpu/build_d1.py releases/v0.26/edits.json --out generated/grain_cpu/d1/edits.json
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
AT, END = 0x601e023c, 0x601e0b3c           # t1's block grows down by one dead table
REFS = T1.REFS + (0x601e3b70, 0x601e3b74, 0x601e3b78)
FW_SITES = tuple(FV.SITES)


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
    s = (HERE / 'gd.s.in').read_text()
    return (s.replace('{gc_open}', op).replace('{gc_shared}', sh).replace('{g_bytes}', lines).replace('{cap_mode}', str(T1.CAP_MODE)).replace('{cap_profile}', str(T1.CAP_PROFILE))
            .replace('{state}', hex(MV.STATE)).replace('{lim}', hex(MV.LIM)).replace('{pool}', hex(MV.POOL)).replace('{bmagic}', hex(MV.BMAGIC)))


def apply(spec):
    stock = T1.STOCK.read_bytes()
    spec = FV.apply(copy.deepcopy(spec), '0.27d1')
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
    code, lst, s, _ = SB3.assemble(source(), AT, dict(T1.SYMS, ep7_bloom_flag=bf, ep7_setter=FV.SETTER))
    if AT + len(code) > END:
        raise SystemExit(f'{len(code)} B does not fit {END - AT}')
    ins = SB3.disasm(code, AT, s['gc_pg'])
    if any(op in T1.BAD for _, op, _ in ins) or any(code[a - AT] == 0xfb for a, _, _ in ins):
        raise SystemExit('forbidden instruction or fb-prefixed form: ' + str([(hex(a), op) for a, op, _ in ins if code[a - AT] == 0xfb or op in T1.BAD][:6]))
    tail = im[bw - BASE:bw + 0x100 - BASE]
    pat = bytes.fromhex('2c5802de0000')
    at = bw + tail.index(pat)
    MV.put(spec, stock, at, b'\x2c\x58\x02', b'\x2c\x00\x04', 'grain_cpu: bw_default 600 -> 1024')
    spec['edits'].append(dict(kind='0x100', addr=hex(AT), expect=stock[AT - BASE:AT - BASE + len(code)].hex(), new=code.hex(), source=SRC,
                              why=f'grain_cpu d1 ({len(code)} B, dead EVF gamma tables)'))
    spec['edits'].append(dict(kind='0x100', addr=hex(T1.SF_WORD), expect=struct.pack('<I', T1.SF).hex(), new=struct.pack('<I', s['gc_gs']).hex(), source=SRC, why='grain_cpu d1: work-list word -> gc_gs'))
    MV.put(spec, stock, T1.FLAG_SITE + 1, struct.pack('<i', bf - T1.FLAG_SITE), struct.pack('<i', s['gc_flag'] - T1.FLAG_SITE), 'grain_cpu d1: flag hook -> gc_flag')
    code_fw = int(spec['fw_version']['code_at'], 16)
    for a in FW_SITES:
        MV.put(spec, stock, a + 1, struct.pack('<i', code_fw - a), struct.pack('<i', s['gc_fw'] - a), 'grain_cpu d1: Body value -> gc_fw')
    spec['grain_cpu'] = dict(built_by=SRC, test='d1', code_at=hex(AT), code_len=len(code), bw_default=hex(at), symbols={k: hex(v) for k, v in s.items() if k.startswith('gc_')}, strengths=[28, 68, 112])
    return spec


FALSE_POS = {0x6014f1b2: 'f0031e60f003'}   # unaligned, inside a u16 run, dis-checked


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps({k: v for k, v in spec['grain_cpu'].items() if k != 'symbols'}))
