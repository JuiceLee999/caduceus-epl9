#!/usr/bin/env python3
"""v0.24 = releases/v0.23 + a Film pick sets the look's saturation (patches/v024/sat.s.in). Offline.

  .venv/bin/python -I patches/v024/build.py releases/v0.23/edits.json --out releases/v0.24/edits.json
  .venv/bin/python -I patches/fw_version/build.py releases/v0.24/edits.json --mod-version 0.24

LOOKS.BIN: tone records carry sat[12] as nibbles at +38..43 and marker +44 = 1, so fm_check's range table takes
+38..43 any byte (data, same size; +44 keeps -5..5). A file with marker 0 leaves saturation alone.
"""
import argparse, copy, importlib.util, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V19 = _load('ep7_v019_build', ROOT / 'patches/v019/build.py')
SB3, FB, LB = V19.SB3, V19.FB, V19.LB
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
T_RET, TAIL = 0x601e23ea, 0x601e23e3   # lt_tone: t_ret; loop tail inc d2, inc a3, inc d3, cmp 3,d3, bcs loop (7 B)
FM_CORE, FM_LO, FM_SPAN = V19.FM_CORE, V19.FM_LO, V19.FM_SPAN
AT, END = 0x601e248c, 0x601e253c
SRC = 'patches/v024'


def jmp(at, dst):
    return b'\xdc' + struct.pack('<i', dst - at)


def covering(spec, addr, n=1):
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16)
            if a <= addr and addr + n <= a + len(e['new']) // 2:
                return e, addr - a
    raise SystemExit(f'{addr:#x}: no covering edit')


def apply(spec):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    if int(spec['look_tone']['symbols']['lt_end'], 16) != AT or int(spec['look_tone']['symbols']['t_ret'], 16) != T_RET:
        raise SystemExit('base symbols moved')
    e, o = covering(spec, TAIL, 7)
    b = bytearray.fromhex(e['new'])
    tail = bytes(b[o:o + 7])
    if tail != bytes.fromhex('484d4caf03c4e7'):
        raise SystemExit(f'loop tail bytes {tail.hex()}')
    loop = TAIL + 5 + struct.unpack('b', tail[6:7])[0]
    code, _, syms, _ = SB3.assemble(FB.source(str(ROOT / 'patches/v024/sat.s.in')), AT, dict(ep7_facade=0x607f9062, ep7_lt_loop=loop, ep7_t_ret=T_RET))
    if syms['sp_tail'] != AT or AT + len(code) > END:
        raise SystemExit(f'code {len(code)} B does not fit')
    print('tail', tail.hex(), 'loop', hex(loop), 'code', len(code))
    bad = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}
    ins = SB3.disasm(code, AT, syms['sp_end'])
    if any(op in bad for _, op, _ in ins) or any(k == 'abs' for _, _, k, _ in SB3.store_audit(ins)):
        raise SystemExit('forbidden instruction or absolute store')
    for x in spec['edits']:
        if not x['addr'].startswith('off:'):
            a, n = int(x['addr'], 16), len(x['new']) // 2
            if a < END and AT < a + n:
                raise SystemExit(f'overlap {x["addr"]}')
    b[o:o + 7] = jmp(TAIL, syms['sp_tail']) + b'\xcb\xcb'           # 2 nops
    e['new'] = b.hex(); e['why'] += ' [v0.24: H/M/S loop tail -> sp_tail (saturation)]'
    e, o = covering(spec, FM_CORE, 1)
    b = bytearray.fromhex(e['new'])
    lo_o, sp_o = FM_LO - FM_CORE + o, FM_SPAN - FM_CORE + o
    for off, (l, sp) in LB.SAT_RANGE.items():
        b[lo_o + off], b[sp_o + off] = l & 0xff, sp
    e['new'] = b.hex(); e['why'] += ' [v0.24: LOOKS.BIN +38..43 any byte]'
    spec['edits'].append(dict(kind='0x100', addr=hex(AT), expect=stock[AT - BASE:AT - BASE + len(code)].hex(), new=code.hex(),
                              source=SRC, why=f'v0.24 Film pick sets saturation (sp_tail, {len(code)} B, dead EVF step-7 tables)'))
    spec['v024'] = dict(built_by=SRC, base='releases/v0.23/edits.json', code_at=hex(AT), code_len=len(code),
                        symbols={k: hex(v) for k, v in syms.items() if k.startswith('sp_')}, sites=[hex(TAIL)])
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['v024']))
