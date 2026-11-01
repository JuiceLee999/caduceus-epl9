#!/usr/bin/env python3
"""Build the E-P7 1.1 COLOR-grain edit spec v0.4 (offline; no camera; no SD-named output).

  python3 -I patches/grain/build.py --out generated/grain-v04

Produces <out>/edits.json (for tools/build_package.py / tools/merge_specs.py /
tools/ep7_grain_verify.py), routine.s, routine.lst, routine.bin, symbols.json.

v0.4 (review v0.3 H1/H2): no build-time level. Grain is per profile and OFF by default:
the level (1 low / 2 medium / 3 high -> gain 50/75/100, stock table 0x604ec0d4) is read
at run time from the active COLOR slot's `grain` byte (+24) of the v0.2 bundle table
(patches/bundles/layout.json), selected by the job extension written by the bundles
converter stubs. The work-list hook also replicates the stock MONO job-type gate
(0x6035778b), so special capture jobs never get grain.

Needs the bundles patch (patches/bundles) in the same package for any grain to appear.
Without it the table is erased (0xFF -> rejected) and the output is stock.
"""
import argparse, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
CODE_AT, CODE_END = 0x60210ce0, 0x60210e00          # docs/CODE_SPACE_MAP.md (sec-1; 16-B FF guards both sides)
SEC1_END = 0x60211000
WL_HOOK, SEL_HOOK = 0x6035749f, 0x603b5249
WL_STOCK, SEL_STOCK = bytes.fromhex('aa0cc605cc0604'), bytes.fromhex('aa0cc605cc5201')
SYMS = dict(ep7_wl_add_final=0x6035739e, ep7_wl_attach=0x603573d3, ep7_wl_after=0x603578bd,
            ep7_wl_hash=0x603574a6, ep7_wl_default=0x603578a9,
            ep7_sel_hash=0x603b5250, ep7_sel_default=0x603b539f)
STAGE_GATE = 'type&0xf0 in {0x10,0x20,0x40} or type&0xf00 == 0x100 -> no grain (stock 0x6035778b)'


def layout():
    lay = json.loads((ROOT / 'patches/bundles/layout.json').read_text())
    je = lay['job_extension']
    v = dict(table=int(lay['bundle_table'], 16), slot_bytes=lay['slot_bytes'], grain=lay['fields']['grain'][0],
             ext_profile=je['profile'], ext_mode=je['picture_mode'], ext_magic=je['marker'],
             magic=int(je['marker_value'], 16))
    if v['slot_bytes'] != 64 or v['grain'] != 24:
        raise SystemExit('layout.json: grain code assumes 64-byte slots and grain at +24')
    return v


TBL_GRAIN_FLASH = """ asl 6,d0                         /* slot * 64 */
 mov {table_grain},\\job           /* bundle_table + 24 */
 movbu (d0,\\job),d0"""
# --sd-v3 (docs/SD_BUNDLES_V3.md): the slot comes from the SD loader v3 accessor. MDR is saved in d1
# (free at both GLEVEL sites) and restored, because grain_mod returns with retf. In grain_mod (sp0=1) the
# accessor call also overwrote the CALLS return word at (sp); it equals MDR at entry, so it is put back.
TBL_GRAIN_SDV3 = """ .ifnc \\job,a0
 .err
 .endif
 mov mdr,d1                       /* sd v3: keep MDR */
 call ep7_tbl_idx,[d2,d3],8       /* a0 = slot d0 of the active table (SD-loaded or flashed) */
 mov d1,mdr
 .if \\sp0
 mov d1,(0,sp)                    /* restore the caller's return word (== MDR at entry) */
 .endif
 movbu (24,a0),d0                 /* grain byte (+24) */"""


def assemble(sd_v3=False, extra=None):
    lay = layout()
    sub = dict(tbl_grain=TBL_GRAIN_SDV3 if sd_v3 else TBL_GRAIN_FLASH, ext_magic=lay['ext_magic'], ext_mode=lay['ext_mode'], ext_profile=lay['ext_profile'],
               magic=hex(lay['magic']), table_grain=hex(lay['table'] + lay['grain']))
    src = (Path(__file__).parent / 'color_grain.s.in').read_text()
    for k, v in sub.items():
        src = src.replace('{' + k + '}', str(v))
    import re
    left = re.findall(r'\{[a-z_]+\}', src)
    if left:
        raise SystemExit(f'unsubstituted template fields {left}')
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start',
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


def build_spec(sd_v3=False):
    acc = sdv3_accessor() if sd_v3 else {}
    code, src, lst, syms, lay = assemble(sd_v3, {'ep7_tbl_idx': acc['tbl_idx']} if sd_v3 else None)
    d = MAIN.read_bytes()
    for at, stock in ((WL_HOOK, WL_STOCK), (SEL_HOOK, SEL_STOCK)):
        if d[at - BASE:at - BASE + len(stock)] != stock:
            raise SystemExit(f'stock bytes differ at {at:#x}')
    if CODE_AT + len(code) > CODE_END or CODE_END + 16 > SEC1_END:
        raise SystemExit(f'code ({len(code)} B) does not fit {CODE_AT:#x}..{CODE_END:#x}')
    if set(d[CODE_AT - 16 - BASE:CODE_END - BASE]) != {0xff}:
        raise SystemExit('section-1 placement (+16-B guard) not erased (FF)')
    tail = d[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    jmp = lambda src_, dst: b'\xdc' + struct.pack('<i', dst - src_) + b'\xcb\xcb'   # jmp d32; nop; nop
    edits = [
        dict(kind='0x100', addr=hex(WL_HOOK), expect=WL_STOCK.hex(), new=jmp(WL_HOOK, syms['wl_hook']).hex(),
             why='work-list builder: key<12 branch -> jmp wl_hook (key 11: stock job-type gate + bundle slot grain)'),
        dict(kind='0x100', addr=hex(SEL_HOOK), expect=SEL_STOCK.hex(), new=jmp(SEL_HOOK, syms['sel_hook']).hex(),
             why='combiner selector: key<12 branch -> jmp sel_hook (key 11 + stage 0x0902 -> 32)'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
             why=f'per-profile COLOR-grain hooks + modifier ({len(code)} B) in section-1 FF tail'),
    ]
    spec = dict(components=['0x100'], patch='color_grain_sdv3' if sd_v3 else 'color_grain', level='bundle', code_at=hex(CODE_AT),
                requires=['bundles-v0.2'], grain_gate=STAGE_GATE,
                grain_layout=dict(table=hex(lay['table']), slot_bytes=lay['slot_bytes'], field=lay['grain'],
                                  ext_profile=lay['ext_profile'], ext_mode=lay['ext_mode'],
                                  ext_magic=lay['ext_magic'], magic=lay['magic']),
                symbols={k: hex(v) for k, v in syms.items() if k in ('wl_hook', 'sel_hook', 'grain_mod')},
                edits=edits)
    if sd_v3:
        spec['sd_v3'] = dict(accessor={k: hex(v) for k, v in acc.items()}, requires='sd_bundles_v3 (accessor edit)')
    return spec, code, src, lst, syms


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--sd-v3', action='store_true', help='read the table through the SD loader v3 accessor')
    a = ap.parse_args()
    spec, code, src, lst, syms = build_spec(a.sd_v3)
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    (a.out / 'symbols.json').write_text(json.dumps({k: hex(v) for k, v in syms.items()}, indent=1) + '\n')
    print(f'code {len(code)} B at {CODE_AT:#x}..{CODE_AT + len(code):#x}; '
          f'wl_hook {syms["wl_hook"]:#x} sel_hook {syms["sel_hook"]:#x} grain_mod {syms["grain_mod"]:#x}; wrote {a.out}')


if __name__ == '__main__':
    main()
