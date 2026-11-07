#!/usr/bin/env python3
"""CPU film grain on COLOR stills, test t1. docs/GRAIN_PORT.md last section. Offline.

  .venv/bin/python -I patches/grain_cpu/build.py releases/v0.26/edits.json --mod-version 0.27c1 --out generated/grain_cpu/t1/edits.json

apply(spec, mod_version=None) -> spec. Source of the method: androidfanman/caduceus-om3 (Apache-2.0, repo 41e7e8b),
firmware/src/xblock.s, research/grain/model.py. The code here is ours; credit it in NOTICE if this ships.
"""
import argparse, copy, importlib.util, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


MV = _load('ep7_v026_movie', ROOT / 'patches/v026_movie/build.py')
SB3, FV = MV.SB3, _load('fw_version_build', ROOT / 'patches/fw_version/build.py')
STOCK = MV.STOCK
BASE, SRC = 0x60020020, 'patches/grain_cpu'
AT, END = 0x601e053c, 0x601e0b3c          # dead EVF gamma tables, unclaimed
REFS = (0x601e3b50, 0x601e3b54, 0x601e3b58, 0x601e3b60, 0x601e3b64, 0x601e3b68)   # the step-table words, and nothing else
FALSE_POS = {0x60020865: 'cd081ea018', 0x6005d0c1: 'cd091ea014', 0x603db3cf: 'cd091ea00c', 0x6062097d: 'dd051ea0ff', 0x608ebdcf: 'b4081ea000', 0x6100a55a: '64071ea000'}   # instruction bytes, dis-checked
SF_WORD, SF = 0x603579b8, 0x6035ca31      # work-list word `mov 0x6035ca31,a1`
FLAG_SITE, FLAG_RET = 0x603eabd7, 0x603eabdd
SYMS = dict(ep7_sf=SF, ep7_bufidx=0x60350975, ep7_lock=0x6006a922, ep7_unlock=0x6006a96b, ep7_winmap=0x60067146, ep7_modeget=0x600672ee,
            ep7_modeset=0x600672fe, ep7_flush=0x60066fc0, ep7_malloc=0x60022782, ep7_free=0x600227b4)
CAP_PROFILE, CAP_MODE = 24083, 24053
BAD = {'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}


def weights():
    ss = lambda t: (lambda t: t * t * (3 - 2 * t))(min(max(t, 0.0), 1.0))
    return [round(255 * (0.08 + 0.92 * ss((y - 25) / 75)) * (1 - 0.25 * ss((y - 200) / 55))) for y in range(256)]


def source():
    g = weights()
    lines = '\n'.join(' .byte ' + ','.join(map(str, g[i:i + 16])) for i in range(0, 256, 16))
    return (HERE / 'gc.s.in').read_text().replace('{g_bytes}', lines).replace('{cap_mode}', str(CAP_MODE)).replace('{cap_profile}', str(CAP_PROFILE))


def check_refs(stock):
    import numpy as np
    for off in range(4):
        w = np.frombuffer(stock[off:off + (len(stock) - off) // 4 * 4], dtype='<u4')
        for k in np.nonzero(((w >= AT) & (w < END)) | ((w >= AT + 0x40000000) & (w < END + 0x40000000)))[0]:
            at = BASE + off + 4 * int(k)
            if at in FALSE_POS and stock[at - BASE:at - BASE + len(FALSE_POS[at]) // 2].hex() == FALSE_POS[at]:
                continue
            if at not in REFS:
                raise SystemExit(f'reference into the block at {at:#x}: {stock[at - BASE - 2:at - BASE + 6].hex()}')


def apply(spec, mod_version=None):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    im = MV.img_of(spec, stock)
    check_refs(stock)
    for e in spec['edits']:
        if not e['addr'].startswith('off:') and e['kind'] == '0x100':
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a < END and AT < a + n:
                raise SystemExit(f'overlap with edit {e["addr"]}')
    if stock[SF_WORD - 2 - BASE:SF_WORD + 4 - BASE] != b'\xfc\xdd' + struct.pack('<I', SF) or im[SF_WORD - BASE:SF_WORD + 4 - BASE] != struct.pack('<I', SF):
        raise SystemExit('work-list word differs')
    bf = int(spec['bloom']['symbols']['bloom_flag'], 16)
    bw = int(spec['bloom']['symbols']['bloom_w'], 16)
    if im[FLAG_SITE - BASE] != 0xdc or FLAG_SITE + struct.unpack_from('<i', im, FLAG_SITE + 1 - BASE)[0] != bf:
        raise SystemExit('flag hook differs')
    code, lst, s, _ = SB3.assemble(source(), AT, dict(SYMS, ep7_bloom_flag=bf))
    if AT + len(code) > END:
        raise SystemExit(f'{len(code)} B does not fit {END - AT}')
    ins = SB3.disasm(code, AT, s['gc_mtab'])
    if any(op in BAD for _, op, _ in ins) or any(code[a - AT] == 0xfb for a, _, _ in ins):
        raise SystemExit('forbidden instruction or fb-prefixed form')
    # the default weight on a key-11 Soft Focus pass: 600 -> 1024, so forced passes leave the sharp image alone
    tail = im[bw - BASE:bw + 0x100 - BASE]
    pat = bytes.fromhex('2c5802de0000')
    if tail.count(pat) != 1:
        raise SystemExit('bw_default not found')
    at = bw + tail.index(pat)
    MV.put(spec, stock, at, b'\x2c\x58\x02', b'\x2c\x00\x04', 'grain_cpu: bw_default 600 -> 1024')
    spec['edits'].append(dict(kind='0x100', addr=hex(AT), expect=stock[AT - BASE:AT - BASE + len(code)].hex(), new=code.hex(), source=SRC,
                              why=f'grain_cpu t1: gc_flag, gc_gs, gc_grain ({len(code)} B, dead EVF gamma tables)'))
    spec['edits'].append(dict(kind='0x100', addr=hex(SF_WORD), expect=struct.pack('<I', SF).hex(), new=struct.pack('<I', s['gc_gs']).hex(), source=SRC,
                              why='grain_cpu t1: work-list word, blend setup -> gc_gs'))
    MV.put(spec, stock, FLAG_SITE + 1, struct.pack('<i', bf - FLAG_SITE), struct.pack('<i', s['gc_flag'] - FLAG_SITE), 'grain_cpu: flag hook -> gc_flag')
    spec['grain_cpu'] = dict(built_by=SRC, test='t1', code_at=hex(AT), code_len=len(code), bw_default=hex(at), symbols={k: hex(v) for k, v in s.items() if k.startswith('gc_')},
                             levels=dict(COLOR1=0, COLOR2=1, COLOR3=2, COLOR4=3), strengths=[28, 68, 112])
    if mod_version:
        spec['edits'] = [e for e in spec['edits'] if e.get('source') != FV.SRC]
        spec = FV.apply(spec, mod_version)
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--mod-version')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()), a.mod_version)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps({k: v for k, v in spec['grain_cpu'].items() if k != 'symbols'}), spec['fw_version']['value'])
