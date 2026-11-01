#!/usr/bin/env python3
"""Build the E-P7 1.1 COLOR-bloom edit spec v0.4 (offline; no camera; no SD-named output).

  python3 -I patches/bloom/build.py --out generated/bloom-v04

Produces <out>/edits.json (for tools/build_package.py, tools/merge_specs.py and
tools/ep7_bloom_verify.py), routine.s, routine.lst, routine.bin, symbols.json.

v0.4 (review v0.3 H2): no build-time strength. Bloom is per profile and OFF by default:
a COLOR slot of the v0.2 bundle table enables it with effect_id 1 and effect_strength 1..5
(bundle JSON "effect": {"type": "bloom", "strength": 1-5}). The strength picks the first-
input mix weight w (Q10) of the stock Soft Focus blend (combiner 11/12): blur share
s = 1 - w/1024 (ASSUMES the first input is the sharp image; docs/BLOOM_HALATION.md).
--weights w1,w2,w3,w4,w5 overrides the table (e.g. 1024-w if the input order is reversed).
Stock references: Soft Focus Art Effect w = 600; Soft Focus filter w = table 0x604ec02e.

Needs the bundles patch (patches/bundles) in the same package for any bloom to appear.
Without it the table is erased (0xFF -> rejected) and the output is stock.
"""
import argparse, json, re, struct, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
CODE_AT, CODE_END = 0x60210e10, 0x60210ef0         # docs/CODE_SPACE_MAP.md row (sec 1); 16-B FF guards both sides
SEC1_END = 0x60211000
FLAG_HOOK, W_HOOK = 0x603eabd7, 0x6039fee8
FLAG_STOCK, W_STOCK = bytes.fromhex('fa43f65da000'), bytes.fromhex('f824342c5802')
SYMS = dict(ep7_bf_back=0x603eabdd, ep7_bw_back=0x6039feee)
CAP_PROFILE, CAP_MODE = 24083, 24053                # capture record (docs/PROFILE_INDEX_WB.md, V02_BUNDLES.md)
CALLBACK, REQ_IN_JOB, RECORDS_IN_JOB, REC_STRIDE, N_REC = 0x60355fd4, 11364, 14576, 56, 16   # = bundles hl guard
EFFECT_BLOOM = 1
# effect_strength 1..5 -> blur share 8/14/20/27/35 %  (w = 1024 - round(1024*s))
STRENGTH_W = [942, 881, 819, 748, 666]


def layout():
    lay = json.loads((ROOT / 'patches/bundles/layout.json').read_text())
    je, f = lay['job_extension'], lay['fields']
    v = dict(table=int(lay['bundle_table'], 16), slot_bytes=lay['slot_bytes'], f_effect=f['effect_id'][0],
             f_strength=f['effect_strength'][0], ext_profile=je['profile'], ext_mode=je['picture_mode'],
             ext_magic=je['marker'], magic=int(je['marker_value'], 16))
    if v['slot_bytes'] != 64:
        raise SystemExit('layout.json: bloom code assumes 64-byte slots')
    return v


def assemble(weights):
    lay = layout()
    sub = dict(cap_mode=CAP_MODE, cap_profile=CAP_PROFILE, table=hex(lay['table']), f_effect=lay['f_effect'],
               f_strength=lay['f_strength'], callback=hex(CALLBACK), rec_off=RECORDS_IN_JOB - REQ_IN_JOB,
               n_rec=N_REC, stride=REC_STRIDE, req_in_job=REQ_IN_JOB, ext_magic=lay['ext_magic'],
               ext_mode=lay['ext_mode'], ext_profile=lay['ext_profile'], magic=hex(lay['magic']),
               w_lut=','.join(str(int(w)) for w in weights))
    src = (Path(__file__).parent / 'bloom.s.in').read_text()
    for k, v in sub.items():
        src = src.replace('{' + k + '}', str(v))
    left = re.findall(r'\{[a-z_]+\}', src)
    if left:
        raise SystemExit(f'unsubstituted template fields {left}')
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in SYMS.items()], '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        syms = {n: int(a, 16) for a, _, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3)}
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        return (t / 'p.bin').read_bytes(), src, (t / 'p.lst').read_text() + '\n' + dis, syms, lay


def build_spec(weights=STRENGTH_W):
    weights = [int(w) for w in weights]
    if len(weights) != 5 or not all(0 <= w <= 1024 for w in weights):
        raise SystemExit('need 5 weights in 0..1024')
    code, src, lst, syms, lay = assemble(weights)
    d = MAIN.read_bytes()
    for at, stock in ((FLAG_HOOK, FLAG_STOCK), (W_HOOK, W_STOCK)):
        if d[at - BASE:at - BASE + len(stock)] != stock:
            raise SystemExit(f'stock bytes differ at {at:#x}')
    if CODE_AT + len(code) > CODE_END or CODE_END + 16 > SEC1_END:
        raise SystemExit(f'code ({len(code)} B) does not fit {CODE_AT:#x}..{CODE_END:#x}')
    if set(d[CODE_AT - 16 - BASE:CODE_END + 16 - BASE]) != {0xff}:
        raise SystemExit('section-1 placement (+16-B guards) not erased (FF)')
    if struct.unpack('<5H', code[syms['w_lut'] - CODE_AT:syms['w_lut'] - CODE_AT + 10]) != tuple(weights):
        raise SystemExit('w_lut bytes wrong')
    tail = d[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    jmp = lambda src_, dst: b'\xdc' + struct.pack('<i', dst - src_) + b'\xcb'   # jmp d32; nop
    edits = [
        dict(kind='0x100', addr=hex(FLAG_HOOK), expect=FLAG_STOCK.hex(), new=jmp(FLAG_HOOK, syms['bloom_flag']).hex(),
             why='art-effect flag converter 0x603eab39: key 11 + slot effect bloom -> job flag 0x80 (Soft Focus pipeline)'),
        dict(kind='0x100', addr=hex(W_HOOK), expect=W_STOCK.hex(), new=jmp(W_HOOK, syms['bloom_w']).hex(),
             why='Soft Focus mix-weight getter 0x6039fee8: key 11 -> w from the job\'s slot strength (else 600)'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
             why=f'per-profile COLOR-bloom stubs ({len(code)} B) in section-1 FF tail'),
    ]
    meta = dict(mode='bundle', strength_w=weights, effect_id=EFFECT_BLOOM, code_at=hex(CODE_AT),
                table=hex(lay['table']), f_effect=lay['f_effect'], f_strength=lay['f_strength'],
                ext=dict(profile=lay['ext_profile'], mode=lay['ext_mode'], marker=lay['ext_magic'], magic=lay['magic']),
                cap=dict(profile=CAP_PROFILE, mode=CAP_MODE),
                guard=dict(callback=hex(CALLBACK), req_in_job=REQ_IN_JOB, records=RECORDS_IN_JOB, stride=REC_STRIDE, n=N_REC),
                symbols={k: hex(v) for k, v in syms.items() if k in ('bloom_flag', 'bloom_w', 'w_lut')})
    spec = dict(components=['0x100'], patch='color_bloom', requires=['bundles-v0.2'], bloom=meta, edits=edits)
    return spec, code, src, lst, syms


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--weights', help='5 comma-separated Q10 weights for strength 1..5')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    weights = [int(x) for x in a.weights.split(',')] if a.weights else STRENGTH_W
    spec, code, src, lst, syms = build_spec(weights)
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    (a.out / 'symbols.json').write_text(json.dumps({k: hex(v) for k, v in syms.items()}, indent=1) + '\n')
    print(f'code {len(code)} B at {CODE_AT:#x}..{CODE_AT + len(code):#x}; bloom_flag {syms["bloom_flag"]:#x} '
          f'bloom_w {syms["bloom_w"]:#x}; w(strength 1..5) = {weights}; wrote {a.out}')


if __name__ == '__main__':
    main()
