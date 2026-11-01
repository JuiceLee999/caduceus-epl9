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

--clarity (needs --sd-v3; docs/CLARITY.md): template bloom_clarity.s.in, placed in the section-2 FF tail
0x6055e5c0..0x6055e6f0 instead of 0x60210e10. Adds bundle effect_id 3 = clarity: same flag 0x80 / Soft Focus
passes; the weight getter returns --clarity-weights (> 1024, unsharp mask) when called from combiner 11 and 1024
from any other caller (combiner 12). Bloom (id 1) behaviour is unchanged.
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
EFFECT_BLOOM, EFFECT_CLARITY = 1, 3
# clarity (docs/CLARITY.md): code in the section-2 FF tail (stock data ends 0x6055e5af; retired HSL v0.1 + grain v0.3
# reservations; 16-B FF guards: 0x6055e5b0..0x6055e5c0 and 0x6055e6f0..0x6055e700 before the WB stub)
CL_CODE_AT, CL_CODE_END, SEC2_TAIL, WB_AT = 0x6055e5c0, 0x6055e6f0, 0x6055e5b0, 0x6055e700
C11_CALL, C12_CALL = 0x603a04a7, 0x603a04fc          # combiner 11 / 12: call16 0x6039fee8,[],0 (5 B)
C11_RET = C11_CALL + 5
# strength 1..5 -> k = (w-1024)/1024 = 0.074 / 0.15 / 0.23 / 0.31 / 0.39 (docs/FUJI_GAPS.md section 3)
CLARITY_W = [1100, 1180, 1260, 1340, 1420]
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


TBL_FLASH = """ asl 6,d0
 mov {table},a0
 add d0,a0"""
# --sd-v3 (docs/SD_BUNDLES_V3.md): slot from the SD loader v3 accessor. d1 is free at both sites; MDR is
# kept in it. bloom_w returns with retf and was entered by call ...,[],0, so the accessor call also
# overwrote the return word at (sp) (== MDR at entry): it is put back.
TBL_FLAG_SDV3 = """ mov mdr,d1                       /* sd v3: keep MDR */
 call ep7_tbl_idx,[d2,d3],8       /* a0 = slot d0 of the active table (SD-loaded or flashed) */
 mov d1,mdr"""
TBL_W_SDV3 = TBL_FLAG_SDV3 + """
 mov d1,(0,sp)                    /* restore the caller's return word (== MDR at entry) */"""


def assemble(weights, sd_v3=False, extra=None, clarity=None, at=CODE_AT):
    lay = layout()
    sub = dict(tbl_flag=TBL_FLAG_SDV3 if sd_v3 else TBL_FLASH, tbl_w=TBL_W_SDV3 if sd_v3 else TBL_FLASH, cap_mode=CAP_MODE, cap_profile=CAP_PROFILE, table=hex(lay['table']), f_effect=lay['f_effect'],
               f_strength=lay['f_strength'], callback=hex(CALLBACK), rec_off=RECORDS_IN_JOB - REQ_IN_JOB,
               n_rec=N_REC, stride=REC_STRIDE, req_in_job=REQ_IN_JOB, ext_magic=lay['ext_magic'],
               ext_mode=lay['ext_mode'], ext_profile=lay['ext_profile'], magic=hex(lay['magic']),
               w_lut=','.join(str(int(w)) for w in weights))
    if clarity is not None:
        sub.update(c11_ret=hex(C11_RET), c11_lut=','.join(str(int(w)) for w in clarity), c12_lut=','.join(['1024'] * 5))
    src = (Path(__file__).parent / ('bloom_clarity.s.in' if clarity is not None else 'bloom.s.in')).read_text()
    for k, v in sub.items():
        src = src.replace('{' + k + '}', str(v))
    left = re.findall(r'\{[a-z_]+\}', src)
    if left:
        raise SystemExit(f'unsubstituted template fields {left}')
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in dict(SYMS, **(extra or {})).items()], '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        syms = {n: int(a, 16) for a, _, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3)}
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        return (t / 'p.bin').read_bytes(), src, (t / 'p.lst').read_text() + '\n' + dis, syms, lay


def sdv3_accessor():
    import importlib.util
    spec = importlib.util.spec_from_file_location('ep7_sd_bundles_v3_build', ROOT / 'patches/sd_bundles_v3/build.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.accessor_symbols()


def build_spec(weights=STRENGTH_W, sd_v3=False, clarity=None):
    weights = [int(w) for w in weights]
    if len(weights) != 5 or not all(0 <= w <= 1024 for w in weights):
        raise SystemExit('need 5 weights in 0..1024')
    if clarity is not None:
        clarity = [int(w) for w in clarity]
        if not sd_v3:
            raise SystemExit('--clarity needs --sd-v3 (bloom_w takes the caller address from the MDR copy in d1)')
        if len(clarity) != 5 or not all(1024 < w <= 1536 for w in clarity):
            raise SystemExit('need 5 clarity weights in 1025..1536')
    code_at, code_end = (CL_CODE_AT, CL_CODE_END) if clarity is not None else (CODE_AT, CODE_END)
    acc = sdv3_accessor() if sd_v3 else {}
    code, src, lst, syms, lay = assemble(weights, sd_v3, {'ep7_tbl_idx': acc['tbl_idx']} if sd_v3 else None, clarity, code_at)
    d = MAIN.read_bytes()
    for at, stock in ((FLAG_HOOK, FLAG_STOCK), (W_HOOK, W_STOCK)):
        if d[at - BASE:at - BASE + len(stock)] != stock:
            raise SystemExit(f'stock bytes differ at {at:#x}')
    if clarity is not None:
        call = lambda at: b'\xcd' + struct.pack('<h', W_HOOK - at) + b'\x00\x00'   # call16 0x6039fee8,[],0
        for at in (C11_CALL, C12_CALL):
            if d[at - BASE:at + 5 - BASE] != call(at):
                raise SystemExit(f'combiner weight call at {at:#x} differs')
        if code_at + len(code) > code_end or code_end + 16 > WB_AT or code_at - 16 < SEC2_TAIL:
            raise SystemExit(f'code ({len(code)} B) does not fit {code_at:#x}..{code_end:#x}')
        if set(d[SEC2_TAIL - BASE:WB_AT - BASE]) != {0xff} or d[SEC2_TAIL - 1 - BASE] == 0xff:
            raise SystemExit('section-2 tail 0x6055e5b0..0x6055e700 not erased (FF) in stock')
        for lut, want in (('c11_lut', clarity), ('c12_lut', [1024] * 5)):
            if struct.unpack('<5H', code[syms[lut] - code_at:syms[lut] - code_at + 10]) != tuple(want):
                raise SystemExit(f'{lut} bytes wrong')
    else:
        if code_at + len(code) > code_end or code_end + 16 > SEC1_END:
            raise SystemExit(f'code ({len(code)} B) does not fit {code_at:#x}..{code_end:#x}')
        if set(d[code_at - 16 - BASE:code_end + 16 - BASE]) != {0xff}:
            raise SystemExit('section-1 placement (+16-B guards) not erased (FF)')
    if struct.unpack('<5H', code[syms['w_lut'] - code_at:syms['w_lut'] - code_at + 10]) != tuple(weights):
        raise SystemExit('w_lut bytes wrong')
    tail = d[code_at - BASE:code_at - BASE + len(code)]
    jmp = lambda src_, dst: b'\xdc' + struct.pack('<i', dst - src_) + b'\xcb'   # jmp d32; nop
    edits = [
        dict(kind='0x100', addr=hex(FLAG_HOOK), expect=FLAG_STOCK.hex(), new=jmp(FLAG_HOOK, syms['bloom_flag']).hex(),
             why='art-effect flag converter 0x603eab39: key 11 + slot effect bloom -> job flag 0x80 (Soft Focus pipeline)'),
        dict(kind='0x100', addr=hex(W_HOOK), expect=W_STOCK.hex(), new=jmp(W_HOOK, syms['bloom_w']).hex(),
             why='Soft Focus mix-weight getter 0x6039fee8: key 11 -> w from the job\'s slot strength (else 600)'),
        dict(kind='0x100', addr=hex(code_at), expect=tail.hex(), new=code.hex(),
             why=f'per-profile COLOR-bloom stubs ({len(code)} B) in section-1 FF tail' if clarity is None else
             f'per-profile COLOR bloom + clarity stubs ({len(code)} B) in section-2 FF tail'),
    ]
    meta = dict(mode='bundle', strength_w=weights, effect_id=EFFECT_BLOOM, code_at=hex(code_at),
                table=hex(lay['table']), f_effect=lay['f_effect'], f_strength=lay['f_strength'],
                ext=dict(profile=lay['ext_profile'], mode=lay['ext_mode'], marker=lay['ext_magic'], magic=lay['magic']),
                cap=dict(profile=CAP_PROFILE, mode=CAP_MODE),
                guard=dict(callback=hex(CALLBACK), req_in_job=REQ_IN_JOB, records=RECORDS_IN_JOB, stride=REC_STRIDE, n=N_REC),
                symbols={k: hex(v) for k, v in syms.items() if k in ('bloom_flag', 'bloom_w', 'w_lut', 'c11_lut', 'c12_lut')})
    if clarity is not None:
        meta['clarity'] = dict(effect_id=EFFECT_CLARITY, strength_w=clarity, other_caller_w=1024, c11_ret=hex(C11_RET),
                               code_end=hex(code_at + len(code)), claim=[hex(CL_CODE_AT), hex(CL_CODE_END)])
    if sd_v3:
        meta['sd_v3'] = dict(accessor={k: hex(v) for k, v in acc.items()}, requires='sd_bundles_v3 (accessor edit)')
    spec = dict(components=['0x100'], patch=('color_bloom_clarity_sdv3' if clarity is not None else 'color_bloom_sdv3') if sd_v3 else 'color_bloom', requires=['bundles-v0.2'],
                bloom=meta, edits=edits)
    return spec, code, src, lst, syms


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--weights', help='5 comma-separated Q10 weights for strength 1..5')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--sd-v3', action='store_true', help='read the table through the SD loader v3 accessor')
    ap.add_argument('--clarity', action='store_true', help='add effect_id 3 = clarity (needs --sd-v3; section-2 placement)')
    ap.add_argument('--clarity-weights', help='5 comma-separated Q10 weights > 1024 for clarity strength 1..5')
    a = ap.parse_args()
    weights = [int(x) for x in a.weights.split(',')] if a.weights else STRENGTH_W
    clarity = ([int(x) for x in a.clarity_weights.split(',')] if a.clarity_weights else CLARITY_W) if a.clarity else None
    spec, code, src, lst, syms = build_spec(weights, a.sd_v3, clarity)
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    (a.out / 'symbols.json').write_text(json.dumps({k: hex(v) for k, v in syms.items()}, indent=1) + '\n')
    at = int(spec['bloom']['code_at'], 16)
    print(f'code {len(code)} B at {at:#x}..{at + len(code):#x}; bloom_flag {syms["bloom_flag"]:#x} '
          f'bloom_w {syms["bloom_w"]:#x}; w(strength 1..5) = {weights}; wrote {a.out}')


if __name__ == '__main__':
    main()
