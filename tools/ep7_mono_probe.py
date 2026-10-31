#!/usr/bin/env python3
"""Emulator diff of the E-P7 1.1 colour-parameter selector 0x603b0252 for picture mode 12 (MONO)
vs mode 11 (COLOR) on otherwise identical synthetic requests.

Runs the stock selector (unmodified code) under fishcu's libsim runner with our decoded main.
Mode 11 -> COLOR builder 0x603b0068 (table 0x6051de2c, saturation at request+1816).
Mode 12 -> hash lookup 0x603af871 (key 12 is not in the 64x8 hash at 0x60532510, so it falls to the
default descriptor 0x60530eb8/0x60530eec chosen by request+1800) -> general builder 0x603afd26.

Variants: mode 11; mode 12; mode 12 with request+1828/1829 (mono grain/shading) set; mode 12 with
request+1800=1 (alternate default table); mode 12 with the saturation array filled.
Whole 5212-byte output block is captured and every changed 32-bit word is listed.

Second check: the chroma-override stage 0x603b132a (called from 0x603b1508 right after the selector in
the development parameter sequence 0x603b1466). It writes output+76 = {enable, Cb, Cr} from the
picture-tone vector table 0x6050f06e (indexed by request+1803) when 0x603b11fb matches the mode word
(ctx+52; key 12 -> hash 0x60532b88 slot 8 -> 0x603b1280), else clears it via 0x603b1311.
Mode 11 -> 0; mode 12 -> 0x00808001 (neutral constant chroma = greyscale) or a toning vector.
Nothing here writes firmware files.

Usage: tools/ep7_mono_probe.py [--json out.json]
"""
import argparse, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import ep7_color_probe as PR  # noqa: E402
from penf_emulator import Region  # noqa: E402

BASE = PR.BASE
SELECTOR = 0x603b0252
CODE_LO, CODE_HI = 0x603a0000, 0x603c0000        # selector, 0x603af871, both builders, 0x603b551d
DATA_LO, DATA_HI = 0x604e0000, 0x60540000        # descriptors, hash, tables, jump tables
OUT_SIZE = 5212
TABLE_PTRS = {3124: 336, 3128: 1680, 3132: 720, 3136: 1104, 3140: 2064, 3144: 2448,
              3148: 1296, 3152: 2640, 3156: 1488, 3160: 2832}
KNOWN_TABLES = {0x6051de2c: 'COLOR table', 0x605120ec: 'default A (req+1800=0)',
                0x60512cc0: 'default B (req+1800!=0)'}


def fixture(d, mode, *, sat=(0,) * 12, b1800=0, b1828=0, b1829=0, ctx60=0x2):
    job = bytearray(PR.JOB_SIZE + 24)
    req = PR.REQ_IN_JOB
    struct.pack_into('<I', job, req + 0, PR.CALLBACK)
    job[req + 8:req + 12] = bytes([0, 0, mode, 0])      # mode word: b0<<24|b1<<16|LE halfword(+10..11)
    struct.pack_into('<H', job, req + 12, 0)
    struct.pack_into('<H', job, req + 14, 0)
    struct.pack_into('<I', job, req + 1524, 0)
    job[req + 1816:req + 1828] = struct.pack('<12b', *sat)
    job[req + 1800] = b1800
    job[req + 1828] = b1828
    job[req + 1829] = b1829
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, PR.JOB + req)
    struct.pack_into('<I', ctx, 12, PR.OUTPUT)
    struct.pack_into('<I', ctx, 60, ctx60)
    regions = [PR.caller(SELECTOR, 0xf0, 20), Region('stack', PR.STACK, bytes(0x2000), 'rw'),
               Region('code', CODE_LO, d[CODE_LO - BASE:CODE_HI - BASE], 'rx'),
               Region('data', DATA_LO, d[DATA_LO - BASE:DATA_HI - BASE], 'r'),
               Region('job', PR.JOB, bytes(job), 'rw', True), Region('ctx', PR.CONTEXT, bytes(ctx), 'rw', True),
               Region('out', PR.OUTPUT, bytes(OUT_SIZE), 'rw', True)]
    regs = {'pc': PR.CALLER, 'sp': PR.STACK + 0x1800, 'a0': PR.CONTEXT, 'd2': 0x2222, 'd3': 0x3333,
            'a2': 0xa2a2, 'a3': 0xa3a3}
    r, mem = PR.run(regions, regs, PR.CALLER + 7)
    rr = r['registers']
    ok = (rr['pc'] == PR.CALLER + 7 and rr['sp'] == PR.STACK + 0x1800 and not r['fault']
          and (rr['d2'], rr['d3'], rr['a2'], rr['a3']) == (0x2222, 0x3333, 0xa2a2, 0xa3a3))
    return dict(ok=ok, insns=r['completed'], fault=r['fault'], out=mem['out'])


CHROMA_FN = 0x603b132a          # chroma-override stage: output+76 = {enable, Cb, Cr} via 0x603b11fb
TONE_VECS = 0x6050f06e          # 5 x 5 B: N/Sepia/Blue/Purple/Green {1, Cb, Cr, Cb', Cr'}


def chroma_fixture(d, mode, *, tone=0, b1800=0, b1801=0, ctx60=0x2):
    req = bytearray(1884)
    req[8:12] = bytes([0, 0, mode, 0])
    req[1800], req[1801], req[1803] = b1800, b1801, tone
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, PR.JOB)
    struct.pack_into('<I', ctx, 12, PR.OUTPUT)
    struct.pack_into('<I', ctx, 52, mode)      # ctx+52 = mode word (as read by 0x603b5246 / 0x603b1337)
    struct.pack_into('<I', ctx, 60, ctx60)
    out = bytearray(OUT_SIZE)
    struct.pack_into('<I', out, 76, 0xdeadbeef)
    regions = [PR.caller(CHROMA_FN, 0xb0, 20), Region('stack', PR.STACK, bytes(0x2000), 'rw'),
               Region('code', CODE_LO, d[CODE_LO - BASE:CODE_HI - BASE], 'rx'),
               Region('data', DATA_LO, d[DATA_LO - BASE:DATA_HI - BASE], 'r'),
               Region('req', PR.JOB, bytes(req), 'rw', True), Region('ctx', PR.CONTEXT, bytes(ctx), 'rw', True),
               Region('out', PR.OUTPUT, bytes(out), 'rw', True)]
    r, mem = PR.run(regions, {'pc': PR.CALLER, 'sp': PR.STACK + 0x1800, 'a0': PR.CONTEXT, 'd2': 0x2222,
                              'a2': 0xa2a2, 'a3': 0xa3a3}, PR.CALLER + 7)
    rr = r['registers']
    ok = rr['pc'] == PR.CALLER + 7 and rr['sp'] == PR.STACK + 0x1800 and not r['fault']
    return ok, struct.unpack_from('<I', mem['out'], 76)[0], r['completed']


def summarise(out):
    recs = [struct.unpack_from('<6I', out, 688 + 24 * i) for i in range(12)]
    ptrs = {o: struct.unpack_from('<I', out, o)[0] for o in TABLE_PTRS}
    base = None
    for o, rel in TABLE_PTRS.items():
        if ptrs[o]:
            base = ptrs[o] - rel
            break
    return dict(control=hex(struct.unpack_from('<I', out, 976)[0]), table=hex(base) if base else None,
                table_name=KNOWN_TABLES.get(base, '?'), lut_ptrs={o: hex(v) for o, v in ptrs.items()},
                record0=[hex(x) for x in recs[0]], record6=[hex(x) for x in recs[6]])


def diff(a, b):
    return [(o, struct.unpack_from('<I', a, o)[0], struct.unpack_from('<I', b, o)[0])
            for o in range(0, OUT_SIZE - 3, 4) if a[o:o + 4] != b[o:o + 4]]


def ranges(offs):
    out, s, p = [], None, None
    for o in offs:
        if s is None:
            s = p = o
        elif o == p + 4:
            p = o
        else:
            out.append((s, p + 4)); s = p = o
    if s is not None:
        out.append((s, p + 4))
    return [f'{a}..{b}' for a, b in out]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    d = PR.main_image()
    sat = (3, -2, 0, 1, 0, 0, -5, 0, 2, 0, 0, 4)
    cases = {
        'm11': fixture(d, 11, sat=sat),
        'm12': fixture(d, 12, sat=sat),
        'm12_sat0': fixture(d, 12),
        'm12_grain_shading': fixture(d, 12, sat=sat, b1828=3, b1829=2),
        'm12_b1800': fixture(d, 12, sat=sat, b1800=1),
        'm11_b1800': fixture(d, 11, sat=sat, b1800=1),
        'm1_natural': fixture(d, 1, sat=sat),           # key 1 = hash slot 26 (Natural-class path)
    }
    res = {}
    for k, c in cases.items():
        res[k] = dict(ok=c['ok'], insns=c['insns'], fault=c['fault'], **summarise(c['out']))
        print(f"{'PASS' if c['ok'] else 'FAIL'} {k:18s} {c['insns']:6d} insns  table={res[k]['table']} "
              f"({res[k]['table_name']}) control={res[k]['control']}")
    o = {k: c['out'] for k, c in cases.items()}
    comps = [('m11', 'm12'), ('m12', 'm12_sat0'), ('m12', 'm12_grain_shading'), ('m12', 'm12_b1800'),
             ('m11', 'm11_b1800'), ('m12', 'm1_natural')]
    res['diffs'] = {}
    for x, y in comps:
        dd = diff(o[x], o[y])
        res['diffs'][f'{x}_vs_{y}'] = dict(changed_words=len(dd), ranges=ranges([t[0] for t in dd]))
        print(f'  {x} vs {y}: {len(dd)} words differ  {ranges([t[0] for t in dd])[:12]}')
    res['identical_m12_sat_ignored'] = o['m12'] == o['m12_sat0']
    res['identical_m12_grain_ignored'] = o['m12'] == o['m12_grain_shading']
    res['identical_m12_vs_natural_key1'] = o['m12'] == o['m1_natural']
    print('mode-12 output ignores request+1816 S array:', res['identical_m12_sat_ignored'])
    print('mode-12 output ignores request+1828/1829   :', res['identical_m12_grain_ignored'])
    print('mode-12 output == key-1 output             :', res['identical_m12_vs_natural_key1'])
    res['chroma_stage'] = {}
    print('chroma-override stage 0x603b132a, output+76 = {enable | Cb<<8 | Cr<<16}:')
    for name, kw in (('m11', dict(mode=11)), ('m11_b1801', dict(mode=11, b1801=1)), ('m12_tone0', dict(mode=12)),
                     ('m12_sepia', dict(mode=12, tone=1)), ('m12_green', dict(mode=12, tone=4)),
                     ('m5_monotone', dict(mode=5)), ('m12_ctx60_0', dict(mode=12, ctx60=0))):
        ok, v, n = chroma_fixture(d, **kw)
        res['chroma_stage'][name] = dict(ok=ok, out76=hex(v), insns=n)
        cases[name + '_chroma'] = dict(ok=ok)
        print(f"{'PASS' if ok else 'FAIL'} {name:14s} out+76={v:#010x}")
    if a.json:
        a.json.write_text(json.dumps(res, indent=1, default=str))
    sys.exit(0 if all(cases[k]['ok'] for k in cases) else 1)


if __name__ == '__main__':
    main()
