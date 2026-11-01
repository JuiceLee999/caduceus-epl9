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
# --halation (docs/HALATION_RED.md): effect_id 2 = red bloom. Luma blur as bloom, but on weights no other path returns
# (the combiner-11 halo stub keys on them); chroma gains rewritten at the combiner-11 tail 0x603a04e8.
EFFECT_HALO = 2
HALO_HOOK, HALO_STOCK = 0x603a04e8, bytes.fromhex('fa178800fa1f8c00')    # mov d1,(136,a3); mov d3,(140,a3)
HALO_TAIL = (0x603a04f0, bytes.fromhex('dff014'))                      # ret [d2,d3,a2,a3],20
# test13b bloom colour (docs/HALATION_RED.md section 8): slot byte +45 bloom_tint 0 neutral, 1 red, 2 amber, 3 warm,
# 4 cool (effect_id 2 with tint 0 = red). Weight rows: tint 0 = STRENGTH_W (plain bloom), tint t = STRENGTH_W + t.
# Chroma spread factors (kcb, kcr) in eighths of the luma blur share b: B_c = min(k b / 8, 1024).
TINTS = ['neutral', 'red', 'amber', 'warm', 'cool']
TINT_K = [(4, 28), (16, 24), (10, 16), (24, 6)]                       # red 0.5/3.5, amber 2/3, warm 1.25/2, cool 3/0.75
F_TINT = 45
# stubs in the dead EVF gamma step-6 R table (step-table word 0x601e3ce0 is the only ref; build-checked)
HALO_AT, HALO_END = 0x601e263c, 0x601e273c
HALO_REF = 0x601e3ce0
STEP6 = (0x601e3b3c + 320 + 16 * 6, (6, 0x601e263c, 0x601e273c, 0x601e283c))
# --red-probe (docs/HALATION_RED.md section 10): red tint -> mask route. Code grows into the dead EVF step-6 G table
# (0x601e273c..0x601e283c, only ref: step-table word 0x601e3ce4); blend-setup hook 0x6035caad (the 0x1000 entry's
# width/height loads) -> probe_set copies job buffer 0x1060's descriptor to request+148.
PROBE_END, PROBE_REF = 0x601e283c, 0x601e3ce4
PS_HOOK, PS_STOCK, PS_BACK = 0x6035caad, bytes.fromhex('f8670cf86b0e'), 0x6035cab3
PROBE_COLOUR = 0x00C060D0                                              # Y 0xD0, Cb 0x60, Cr 0xC0 (orange-red; order [I])
MASK_ID, BUF_TAB = 0x1060, 6592
# --art (v0.14, docs/HALATION_RED.md section 11): slot +46 Art Effect -> stock converter flag, stub in EVF step-9 R.
ART_AT, ART_END = 0x601e1d3c, 0x601e1e3c
ART_REFS = (0x601e3d10, 0x601e3d14, 0x601e3d18)
F_ART = 46
ART_FLAGS = {1: (0xffffffff, 0x40), 2: (0xffffffff, 0x400), 3: (0xfffffcff, 0x100), 4: (0xffffffff, 0x2000), 5: (0xffffffff, 0x8000)}
SF_W = [600, 653, 707, 760, 680, 520, 440, 360, 280, 200, 1024]       # stock Soft Focus table 0x604ec02e, A-effect, A-only


def tint_rows(weights):
    return [[w + t for w in weights] for t in range(5)]


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


def assemble(weights, sd_v3=False, extra=None, clarity=None, at=CODE_AT, halo=False, template=None, probe=False, art=False, eff2=False):
    lay = layout()
    sub = dict(tbl_flag=TBL_FLAG_SDV3 if sd_v3 else TBL_FLASH, tbl_w=TBL_W_SDV3 if sd_v3 else TBL_FLASH, cap_mode=CAP_MODE, cap_profile=CAP_PROFILE, table=hex(lay['table']), f_effect=lay['f_effect'],
               f_strength=lay['f_strength'], callback=hex(CALLBACK), rec_off=RECORDS_IN_JOB - REQ_IN_JOB,
               n_rec=N_REC, stride=REC_STRIDE, req_in_job=REQ_IN_JOB, ext_magic=lay['ext_magic'],
               ext_mode=lay['ext_mode'], ext_profile=lay['ext_profile'], magic=hex(lay['magic']),
               w_lut=','.join(str(int(w)) for w in weights))
    if clarity is not None:
        sub.update(c11_ret=hex(C11_RET), c11_lut=','.join(str(int(w)) for w in clarity), c12_lut=','.join(['1024'] * 5))
    sub.update(art=int(bool(art)), f_art=F_ART, eff2=int(bool(eff2)))
    sub.update(probe=int(bool(probe)), colour=hex(PROBE_COLOUR), mask_id=hex(MASK_ID), buf_tab=BUF_TAB - REQ_IN_JOB)
    sub.update(halo=int(bool(halo)), f_tint=F_TINT, t_w=','.join(str(w) for r in tint_rows(weights) for w in r),
               t_k=','.join(str(k) for p in TINT_K for k in p))
    src = (Path(__file__).parent / (template or ('bloom_clarity.s.in' if clarity is not None else 'bloom.s.in'))).read_text()
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


def check_step6(d, end=None, refs=(HALO_REF,)):
    """The dead EVF step-6 R table: its only abs32 reference is the step-table word (as patches/mono_presets)."""
    import numpy as np
    at, want = STEP6
    if struct.unpack_from('<B3xIII', d, at - BASE) != want:
        raise SystemExit('EVF step-6 slot differs')
    for off in range(4):
        w = np.frombuffer(d[off:off + (len(d) - off) // 4 * 4], dtype='<u4')
        for k in np.nonzero((w >= HALO_AT) & (w < (end or HALO_END)))[0]:
            a = BASE + off + 4 * int(k)
            if a not in refs:
                raise SystemExit(f'abs32 reference into the step-6 R table at {a:#x}')


def sdv3_accessor():
    import importlib.util
    spec = importlib.util.spec_from_file_location('ep7_sd_bundles_v3_build', ROOT / 'patches/sd_bundles_v3/build.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.accessor_symbols()


def build_spec(weights=STRENGTH_W, sd_v3=False, clarity=None, halo=False, probe=False, art=False, eff2=False):
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
    if halo and clarity is None:
        raise SystemExit('--halation needs --clarity (section-2 routine; the halo stub takes the sec-1 block)')
    d = MAIN.read_bytes()
    extra = {'ep7_tbl_idx': acc['tbl_idx']} if sd_v3 else {}
    if halo:
        tw = [w for r in tint_rows(weights)[1:] for w in r]
        if len(set(tw)) != 20 or set(tw) & set(weights + list(clarity or []) + SF_W) or max(tw) > 1023:
            raise SystemExit('bloom-colour weights must differ from every other weight')
        if probe and not sd_v3:
            raise SystemExit('--red-probe needs --sd-v3 --clarity --halation')
        hend = PROBE_END if probe else HALO_END
        check_step6(d, hend, (HALO_REF, PROBE_REF) if probe else (HALO_REF,))
        hextra = dict(ep7_tbl_idx=acc['tbl_idx'], ep7_ps_back=PS_BACK) if probe else None
        hcode, hsrc, hlst, hsyms, _ = assemble(weights, extra=hextra, template='halo.s.in', at=HALO_AT, halo=True, probe=probe)
        extra['ep7_bw_tint'] = hsyms['bw_tint']
    if art:
        if not (sd_v3 and clarity is not None):
            raise SystemExit('--art needs --sd-v3 --clarity')
        st9 = 0x601e3b3c + 320 + 16 * 9
        if struct.unpack_from('<B3xIII', d, st9 - BASE) != (9, 0x601e1d3c, 0x601e1e3c, 0x601e1f3c):
            raise SystemExit('EVF step-9 slot differs')
        import numpy as np
        for off in range(4):
            w_ = np.frombuffer(d[off:off + (len(d) - off) // 4 * 4], dtype='<u4')
            for k in np.nonzero((w_ >= ART_AT) & (w_ < ART_END))[0]:
                if BASE + off + 4 * int(k) not in ART_REFS:
                    raise SystemExit(f'abs32 reference into the step-9 R table at {BASE + off + 4 * int(k):#x}')
        # two passes: bloom routine (bf_art) <-> art stub (art); every external jmp is the fixed d32 form
        extra = dict(extra, ep7_art=ART_AT)
        _, _, _, syms0, _ = assemble(weights, sd_v3, extra, clarity, code_at, halo, art=True, eff2=eff2)
        acode, asrc, alst, asyms, _ = assemble(weights, extra=dict(ep7_art_back=syms0['bf_art']), template='art.s.in', at=ART_AT)
        if asyms['art'] != ART_AT or ART_AT + len(acode) > ART_END:
            raise SystemExit('art stub layout')
        tab = acode[asyms['art_tab'] - ART_AT:asyms['art_end'] - ART_AT]
        if tab != b''.join(struct.pack('<II', *ART_FLAGS[k]) for k in range(1, 6)):
            raise SystemExit('art table bytes wrong')
    if eff2 and (halo or clarity is None):
        raise SystemExit('--eff2-bloom needs --clarity and no --halation')
    code, src, lst, syms, lay = assemble(weights, sd_v3, extra or None, clarity, code_at, halo, art=art, eff2=eff2)
    if art and syms['bf_art'] != syms0['bf_art']:
        raise SystemExit('bf_art moved between passes')
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
    if halo:
        if HALO_AT + len(hcode) > hend:
            raise SystemExit(f'halo stubs ({len(hcode)} B) do not fit {HALO_AT:#x}..{hend:#x}')
        if d[HALO_HOOK - BASE:HALO_HOOK - BASE + 8] != HALO_STOCK or d[HALO_TAIL[0] - BASE:HALO_TAIL[0] - BASE + 3] != HALO_TAIL[1]:
            raise SystemExit('combiner-11 tail bytes differ')
        tw = hcode[hsyms['t_w'] - HALO_AT:hsyms['t_w'] - HALO_AT + 50]
        if struct.unpack('<25H', tw) != tuple(w for r in tint_rows(weights) for w in r) or \
                hcode[hsyms['t_k'] - HALO_AT:hsyms['t_end'] - HALO_AT] != bytes(k for p in TINT_K for k in p) or \
                hsyms['t_k'] != hsyms['t_w'] + 50:
            raise SystemExit('t_w / t_k bytes wrong')
        if any(k * (1024 - w) // 8 > 1024 * 8 for p in TINT_K for k in p for w in weights):
            raise SystemExit('k b overflow')
        ins = [l.split('\t')[2].split()[0] for l in hlst.splitlines() if l.count('\t') >= 2 and l.split('\t')[0].strip().endswith(':')]
        bad = {'mul', 'mulu', 'div', 'divu', 'setlb', 'call', 'calls'} & set(ins)
        if bad - ({'call'} if probe else set()) or (probe and ins.count('call') != 3):
            raise SystemExit('forbidden instruction in the halo stubs')
        edits.append(dict(kind='0x100', addr=hex(HALO_HOOK), expect=HALO_STOCK.hex(),
                          new=(b'\xdc' + struct.pack('<i', hsyms['halo'] - HALO_HOOK) + b'\xcb\xcb\xcb').hex(),
                          why='combiner-11 tail 0x603a04e8: gain stores -> jmp halo (bloom colour chroma gains)'))
        edits.append(dict(kind='0x100', addr=hex(HALO_AT), expect=d[HALO_AT - BASE:HALO_AT - BASE + len(hcode)].hex(),
                          new=hcode.hex(), why=f'bloom colour stubs bw_tint + halo ({len(hcode)} B) in the dead EVF step-6 R table'))
        if probe:
            if max(2 * (1024 - w) for r in tint_rows(weights)[1:] for w in r) > 1024:
                raise SystemExit('red probe: beta = 2b > 1024')
            if d[PS_HOOK - BASE:PS_HOOK - BASE + 6] != PS_STOCK:
                raise SystemExit('blend setup bytes differ at 0x6035caad')
            edits.append(dict(kind='0x100', addr=hex(PS_HOOK), expect=PS_STOCK.hex(),
                              new=jmp(PS_HOOK, hsyms['probe_set']).hex(),
                              why='Soft Focus blend setup 0x6035ca31: -> probe_set (red tint: buffer 0x1060 descriptor -> request+148)'))
        lst += '\n' + hlst
    if art:
        edits.append(dict(kind='0x100', addr=hex(ART_AT), expect=d[ART_AT - BASE:ART_AT - BASE + len(acode)].hex(), new=acode.hex(),
                          why=f'COLOR Art Effect stub ({len(acode)} B, slot +46 -> stock converter flag) in the dead EVF step-9 R table'))
        lst += '\n' + alst
    meta = dict(mode='bundle', strength_w=weights, effect_id=EFFECT_BLOOM, code_at=hex(code_at),
                table=hex(lay['table']), f_effect=lay['f_effect'], f_strength=lay['f_strength'],
                ext=dict(profile=lay['ext_profile'], mode=lay['ext_mode'], marker=lay['ext_magic'], magic=lay['magic']),
                cap=dict(profile=CAP_PROFILE, mode=CAP_MODE),
                guard=dict(callback=hex(CALLBACK), req_in_job=REQ_IN_JOB, records=RECORDS_IN_JOB, stride=REC_STRIDE, n=N_REC),
                symbols={k: hex(v) for k, v in syms.items() if k in ('bloom_flag', 'bloom_w', 'w_lut', 'c11_lut', 'c12_lut')})
    if clarity is not None:
        meta['clarity'] = dict(effect_id=EFFECT_CLARITY, strength_w=clarity, other_caller_w=1024, c11_ret=hex(C11_RET),
                               code_end=hex(code_at + len(code)), claim=[hex(CL_CODE_AT), hex(CL_CODE_END)])
    if halo:
        meta['halation'] = dict(effect_id=EFFECT_HALO, legacy='effect 2 with tint 0 = red', tint_byte=F_TINT, tints=TINTS,
                                tint_w=tint_rows(weights), tint_k_eighths=dict(zip(TINTS[1:], TINT_K)), hook=hex(HALO_HOOK),
                                stub=hex(HALO_AT), stub_len=len(hcode), channels='Y,Cb,Cr [I]',
                                symbols={k: hex(v) for k, v in hsyms.items() if k in ('bw_tint', 'halo', 'h_go', 't_w', 't_k', 't_end', 'probe_bank', 'probe_set', 'pb_no', 'h_chroma')})
        if probe:
            meta['halation']['red_probe'] = dict(hook=hex(PS_HOOK), colour=hex(PROBE_COLOUR), mask_buffer=hex(MASK_ID),
                                                 port='request+148', mode=0x1002, beta='2b', claim=[hex(HALO_AT), hex(PROBE_END)])
    if eff2:
        meta['eff2_bloom'] = 'effect_id 2 -> plain bloom (flag and weight); bloom_tint +45 ignored (no halo hook)'
    if art:
        meta['art'] = dict(byte=F_ART, values=['off', 'star_light', 'pin_hole', 'blur', 'white_edge', 'frame'],
                           flags={k: [hex(a), hex(o)] for k, (a, o) in ART_FLAGS.items()}, stub=hex(ART_AT), stub_len=len(acode),
                           return_to=hex(syms['bf_art']))
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
    ap.add_argument('--halation', action='store_true', help='effect_id 2 = red bloom (needs --clarity; docs/HALATION_RED.md)')
    ap.add_argument('--eff2-bloom', action='store_true', help='effect_id 2 renders as plain bloom, tint ignored (v0.14)')
    ap.add_argument('--art', action='store_true', help='slot +46 Art Effect for COLOR stills (v0.14; section 11)')
    ap.add_argument('--red-probe', action='store_true', help='red tint -> mask route probe (docs/HALATION_RED.md section 10)')
    ap.add_argument('--clarity-weights', help='5 comma-separated Q10 weights > 1024 for clarity strength 1..5')
    a = ap.parse_args()
    weights = [int(x) for x in a.weights.split(',')] if a.weights else STRENGTH_W
    clarity = ([int(x) for x in a.clarity_weights.split(',')] if a.clarity_weights else CLARITY_W) if a.clarity else None
    spec, code, src, lst, syms = build_spec(weights, a.sd_v3, clarity, a.halation, a.red_probe, a.art, a.eff2_bloom)
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
