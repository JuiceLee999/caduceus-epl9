#!/usr/bin/env python3
"""Build the E-P7 1.1 lens aperture-ring edit spec (offline; no camera; no SD-named output).

  python3 -I patches/aperture_ring/build.py --out generated/aperture_ring

Produces <out>/edits.json (tools/build_package.py, tools/merge_specs.py, tools/ep7_verify_aperture_ring.py),
routine.s, routine.lst, symbols.json.

Design and evidence: docs/APERTURE_RING.md. Approach studied from the PEN-F 3.1 proposal (fishcu/oly_fw_analysis
PR #4); this is an independent E-P7 implementation with E-P7 addresses, its own code and two E-P7-specific
differences (81 E3 response kind is 4/5 on E-P7, not 6; no discovery-reset hook).

Edits (all stock bytes verified before patching):
  0x601f9df7  5 B  dispatcher entry `bne +5; jmp null` (after stock `mov a0,a3; clr d2; cmp 0,a3`) -> jmp disp_hook
                                                                                                    (section 1)
  0x601f5ed7  8 B  status parser `movbu (a3),d0; mov (4,sp),a0; inc a3; movbu d0,(17,a0)`
                   -> call parse_hook,[],0; nop                                                         (section 1)
  0x60427ae7  5 B  AE snapshot `call 0x60429548,[],4` (aperture point 0x80ca) -> jmp ae_hook          (section 2)
  .lens code  at 0x60210f80 (section-1 FF tail), state halfword at 0x60210ffe = 0x8000 (uncached alias 0xa0210ffe)
  .ae code    at 0x61378f9c (section-7 FF tail; section 7 loads before section 2)
"""
import argparse, hashlib, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
BASE = 0x60020020
UNCACHED = 0x40000000

# ---- E-P7 landmarks (docs/APERTURE_RING.md, "Verified" table) ----
DISP_FN = 0x601f9df3                                     # `mov a0,a3; clr d2; cmp 0,a3` stays stock
DISP_SITE, DISP_STOCK = 0x601f9df7, 'c905cc8500'        # bne 0x601f9dfc; jmp 0x601f9e7e
DISP_CONT, DISP_NULL = 0x601f9dfc, 0x601f9e7e
PARSE_SITE, PARSE_STOCK = 0x601f5ed7, 'f0435c044df85011'
AE_SITE, AE_STOCK = 0x60427ae7, 'cd611a0004'            # call 0x60429548,[],4
AE_WRAP, AE_CONT = 0x60429548, 0x60427aec
AE_WRAP_STOCK = 'fccc ca800000 fca07c0a2a62 04 dd1c54c3ffc00c 18 df0004'.replace(' ', '')
DEV_GET = 0x601f2761                                     # d0=0 -> a0 = 0xa271ca70 device if lens connected, else 0
DEV_GET_STOCK = '821eaa02c234aa00c91788ddde4ff0ff0000'
CAP_OFF, CAP_BIT = 0x440, 0x80                           # PEN-F +0x23c (+0x204 struct growth, same as zoom table)
AV_MIN, AV_MAX = 0x621cf64e, 0x621cf650                  # official zoom-row limits (producer 0x601ede5e)
STATE_INIT = 0x8000                                      # = lens ring at A/auto: AE keeps stock

LENS_AT, LENS_END = 0x60210f80, 0x60210ff8               # section 1 ends 0x60211000
STATE = 0x60210ffe
AE_AT, AE_END = 0x61378f9c, 0x61379000                   # section 7 ends 0x61379000; MONO-colour guard to 0x61378f8c
SEC1, SEC2, SEC7 = (0x600d7800, 0x60211000), (0x60280800, 0x6055e800), (0x612c7000, 0x61379000)

# Other patches' claims (docs/CODE_SPACE_MAP.md): never overlap.
RESERVED = [(0x60210900, 0x60210c80, 'bundles v0.2'), (0x60210c80, 0x60210cd0, 'video_log'),
            (0x60210cd0, 0x60210e00, 'grain v0.4'), (0x60210e00, 0x60210f00, 'bloom v0.4'),
            (0x60210f00, 0x60210f80, 'aspect'), (0x61378c68, 0x61378f8c, 'MONO-colour + guards'),
            (0x6055e5c0, 0x6055e800, 'section-2 tail claims'),
            (0x603b02d9, 0x603b02de, 'HSL/bundles'), (0x60319157, 0x6031915e, 'rec_limit'),
            (0x6030df3d, 0x6030df42, 'video_log'), (0x6035749f, 0x603574a6, 'grain'),
            (0x603b5249, 0x603b5250, 'grain'), (0x603eabd7, 0x603eabdd, 'bloom'), (0x6039fee8, 0x6039feee, 'bloom'),
            (0x603b02bf, 0x603b02c5, 'MONO-colour'), (0x603b134e, 0x603b1353, 'MONO-colour'),
            (0x60353db9, 0x60353dc1, 'MONO-colour'), (0x603537f0, 0x603537f3, 'bundles'),
            (0x6035390c, 0x6035390e, 'bundles'), (0x603e66ab, 0x603e66b1, 'bundles'), (0x603e91f0, 0x603e91f6, 'bundles'),
            (0x60863e91, 0x60863e95, 'sd_bundles'), (0x6117af14, 0x6117af1c, 'aspect')]


def source():
    sub = dict(disp_site=hex(DISP_SITE), parse_site=hex(PARSE_SITE), ae_site=hex(AE_SITE), cap_off=CAP_OFF,
               cap_bit=hex(CAP_BIT), state_unc=hex(STATE + UNCACHED),
               av_min=hex(AV_MIN), av_max=hex(AV_MAX))
    src = (Path(__file__).parent / 'aperture_ring.s.in').read_text()
    for k, v in sub.items():
        src = src.replace('{' + k + '}', str(v))
    if '{' in src or '}' in src:
        raise ValueError('unsubstituted template field')
    return src


def assemble(src):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        syms = dict(dev_get=DEV_GET, ae_wrap=AE_WRAP, ae_cont=AE_CONT, disp_cont=DISP_CONT, disp_null_cont=DISP_NULL)
        subprocess.run([TC / 'mn10300-elf-ld', f'--section-start=.lens={LENS_AT:#x}', f'--section-start=.ae={AE_AT:#x}',
                        '-e', 'disp_hook', *[f'--defsym={k}={v:#x}' for k, v in syms.items()],
                        '-o', t / 'p.elf', t / 'p.o'], check=True)
        out = {}
        for sec in ('lens', 'ae'):
            subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.' + sec, t / 'p.elf', t / f'{sec}.bin'], check=True)
            out[sec] = (t / f'{sec}.bin').read_bytes()
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        sy = {n: int(a, 16) for a, ty, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3) if ty in 'tT'}
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        return out, (t / 'p.lst').read_text() + '\n' + dis, sy


def rel32(frm, to):
    return struct.pack('<i', to - frm)


def jmp32(at, to):
    return b'\xdc' + rel32(at, to)


def call32(at, to, regs, imm):
    return b'\xdd' + rel32(at, to) + bytes([regs, imm])


def sl(d, a, n):
    return d[a - BASE:a - BASE + n]


def check_stock(d):
    for a, hx, what in [(DISP_FN, '9308bf00' + DISP_STOCK, 'dispatcher entry'), (PARSE_SITE, PARSE_STOCK, 'parser DIS_FCENC'),
                        (AE_SITE, AE_STOCK, 'AE aperture-point call'), (AE_WRAP, AE_WRAP_STOCK, 'aperture-point wrapper'),
                        (DEV_GET, DEV_GET_STOCK, 'lens device getter')]:
        if sl(d, a, len(hx) // 2).hex() != hx:
            raise ValueError(f'{what} {a:#x}: stock bytes differ ({sl(d, a, len(hx) // 2).hex()})')
    if AE_SITE + 5 + struct.unpack_from('<h', d, AE_SITE + 1 - BASE)[0] - 5 != AE_WRAP:
        raise ValueError('AE call target is not the 0x80ca wrapper')
    # dispatcher: the stock bne at +4 lands exactly on DISP_CONT, the jmp at +6 on DISP_NULL
    if DISP_SITE + d[DISP_SITE + 1 - BASE] != DISP_CONT:
        raise ValueError('dispatcher bne target moved')
    if DISP_SITE + 2 + struct.unpack_from('<h', d, DISP_SITE + 3 - BASE)[0] != DISP_NULL:
        raise ValueError('dispatcher NULL jmp target moved')
    # device getter reads +0x440: confirm a stock capability test at that offset (0x601f4732 `mov (1088,a0),d1`)
    if sl(d, 0x601f4732, 4).hex() != 'fa044004':
        raise ValueError('capability offset witness 0x601f4732 differs')
    # cache producer writes the two limit words
    for a, w in [(0x601ede84, AV_MIN), (0x601edecb, AV_MAX)]:
        if sl(d, a, 2).hex() != 'fc83' or struct.unpack_from('<I', d, a + 2 - BASE)[0] != w:
            raise ValueError(f'limit producer store {a:#x} differs')
    for lo, hi in [(LENS_AT - 16, SEC1[1]), (AE_AT - 16, AE_END)]:
        if set(sl(d, lo, hi - lo)) != {0xff}:
            raise ValueError(f'code space {lo:#x}..{hi:#x} not erased')


def make_spec():
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    check_stock(d)
    src = source()
    code, lst, syms = assemble(src)
    if syms['disp_hook'] != LENS_AT or syms['ae_hook'] != AE_AT:
        raise ValueError('entry symbols misplaced')
    if LENS_AT + len(code['lens']) > LENS_END:
        raise ValueError(f".lens {len(code['lens'])} B exceeds {LENS_AT:#x}..{LENS_END:#x}")
    if AE_AT + len(code['ae']) > AE_END:
        raise ValueError(f".ae {len(code['ae'])} B exceeds {AE_AT:#x}..{AE_END:#x}")
    if not (SEC1[0] <= DISP_SITE < SEC1[1] and SEC1[0] <= PARSE_SITE < SEC1[1] and SEC2[0] <= AE_SITE < SEC2[1]
            and SEC1[0] <= LENS_AT and LENS_END <= SEC1[1] and SEC7[0] <= AE_AT and AE_END <= SEC7[1]):
        raise ValueError('section placement rule broken')
    disp = jmp32(DISP_SITE, syms['disp_hook'])
    parse = call32(PARSE_SITE, syms['parse_hook'], 0x00, 0) + b'\xcb'
    ae = jmp32(AE_SITE, syms['ae_hook'])
    edits = [
        dict(kind='0x100', addr=hex(DISP_SITE), expect=DISP_STOCK, new=disp.hex(),
             why='lens dispatcher `bne; jmp null` -> jmp disp_hook (request ring option 0x01 on C1 80 / 81 E3)'),
        dict(kind='0x100', addr=hex(PARSE_SITE), expect=PARSE_STOCK, new=parse.hex(),
             why='status parser after DIS_FCENC -> call parse_hook,[],0 (consume + publish ring word)'),
        dict(kind='0x100', addr=hex(AE_SITE), expect=AE_STOCK, new=ae.hex(),
             why='AE snapshot aperture-point call -> jmp ae_hook (ring Av in A/M)'),
        dict(kind='0x100', addr=hex(LENS_AT), expect=sl(d, LENS_AT, len(code['lens'])).hex(), new=code['lens'].hex(),
             why=f"aperture-ring lens hooks ({len(code['lens'])} B, section-1 FF tail)"),
        dict(kind='0x100', addr=hex(STATE), expect='ffff', new=struct.pack('<H', STATE_INIT).hex(),
             why='aperture-ring published ring word, initial 0x8000 = A/auto (run-time, written via uncached alias)'),
        dict(kind='0x100', addr=hex(AE_AT), expect=sl(d, AE_AT, len(code['ae'])).hex(), new=code['ae'].hex(),
             why=f"aperture-ring AE hook ({len(code['ae'])} B, section-7 FF tail)"),
    ]
    spans = []
    for e in edits:
        a, n = int(e['addr'], 16), len(bytes.fromhex(e['new']))
        if len(bytes.fromhex(e['expect'])) != n:
            raise ValueError(f"edit {e['addr']}: expect/new length differ")
        for lo, hi, who in RESERVED:
            if a < hi and lo < a + n:
                raise ValueError(f"edit {e['addr']} overlaps {who} {lo:#x}..{hi:#x}")
        for lo, hi in spans:
            if a < hi and lo < a + n:
                raise ValueError(f"edit {e['addr']} overlaps another aperture-ring edit")
        spans.append((a, a + n))
    meta = dict(disp_site=hex(DISP_SITE), disp_cont=hex(DISP_CONT), disp_null=hex(DISP_NULL),
                parse_site=hex(PARSE_SITE), ae_site=hex(AE_SITE), ae_wrap=hex(AE_WRAP), ae_cont=hex(AE_CONT),
                dev_get=hex(DEV_GET), cap_off=hex(CAP_OFF), cap_bit=hex(CAP_BIT), av_min=hex(AV_MIN), av_max=hex(AV_MAX),
                state_init=hex(STATE_INIT), state=hex(STATE), state_uncached=hex(STATE + UNCACHED),
                lens_at=hex(LENS_AT), lens_len=len(code['lens']), ae_at=hex(AE_AT), ae_len=len(code['ae']),
                modes={'4': 'A', '6': 'M'}, symbols={k: hex(v) for k, v in syms.items()})
    spec = dict(components=['0x100'], patch='aperture_ring', aperture_ring=meta, edits=edits)
    return spec, src, lst, syms, code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    try:
        spec, src, lst, syms, code = make_spec()
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'symbols.json').write_text(json.dumps({k: hex(v) for k, v in syms.items()}, indent=1) + '\n')
    print(f".lens {len(code['lens'])} B at {LENS_AT:#x}, .ae {len(code['ae'])} B at {AE_AT:#x}, state {STATE:#x}; "
          f"{len(spec['edits'])} edits -> {a.out}")


if __name__ == '__main__':
    main()
