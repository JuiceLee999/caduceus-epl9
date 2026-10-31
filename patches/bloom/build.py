#!/usr/bin/env python3
"""Build the E-P7 1.1 COLOR-bloom edit spec (offline; no camera; no SD-named output).

  python3 -I patches/bloom/build.py --strength 2 --out generated/bloom-S2

Produces <out>/edits.json (for tools/build_package.py, tools/merge_specs.py and
tools/ep7_bloom_verify.py), routine.s, routine.lst, routine.bin, symbols.json.

--strength 1..5 = bundle effect_strength -> first-input mix weight w (Q10) for the stock
Soft Focus blend (combiner 11/12): blur share s = 1 - w/1024 (ASSUMES the first input is
the sharp image; see docs/BLOOM_HALATION.md). --weight N overrides (0..1024).
Stock references: Soft Focus Art Effect w = 600; Soft Focus filter w = table 0x604ec02e.
"""
import argparse, json, struct, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
CODE_AT, CODE_END = 0x6055e7b0, 0x6055e7f0         # docs/CODE_SPACE_MAP.md row; 16-B guard to 0x6055e800 kept
FLAG_HOOK, W_HOOK = 0x603eabd7, 0x6039fee8
FLAG_STOCK, W_STOCK = bytes.fromhex('fa43f65da000'), bytes.fromhex('f824342c5802')
SYMS = dict(ep7_bf_back=0x603eabdd, ep7_bw_back=0x6039feee)
# effect_strength -> blur share 8/14/20/27/35 %  (w = 1024 - round(1024*s))
STRENGTH_W = {1: 942, 2: 881, 3: 819, 4: 748, 5: 666}


def assemble(weight):
    src = (Path(__file__).parent / 'bloom.s.in').read_text().replace('{weight}', str(int(weight)))
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
        return (t / 'p.bin').read_bytes(), src, (t / 'p.lst').read_text() + '\n' + dis, syms


def build_spec(weight, strength=None):
    if not 0 <= weight <= 1024:
        raise SystemExit('weight must be 0..1024')
    code, src, lst, syms = assemble(weight)
    d = MAIN.read_bytes()
    for at, stock in ((FLAG_HOOK, FLAG_STOCK), (W_HOOK, W_STOCK)):
        if d[at - BASE:at - BASE + len(stock)] != stock:
            raise SystemExit(f'stock bytes differ at {at:#x}')
    if CODE_AT + len(code) > CODE_END:
        raise SystemExit(f'code ({len(code)} B) does not fit {CODE_AT:#x}..{CODE_END:#x}')
    tail = d[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    if set(tail) != {0xff}:
        raise SystemExit('tail not erased (FF)')
    jmp = lambda src_, dst: b'\xdc' + struct.pack('<i', dst - src_) + b'\xcb'   # jmp d32; nop
    edits = [
        dict(kind='0x100', addr=hex(FLAG_HOOK), expect=FLAG_STOCK.hex(), new=jmp(FLAG_HOOK, syms['bloom_flag']).hex(),
             why='art-effect flag converter 0x603eab39: key 11 -> job flag 0x80 (Soft Focus pipeline)'),
        dict(kind='0x100', addr=hex(W_HOOK), expect=W_STOCK.hex(), new=jmp(W_HOOK, syms['bloom_w']).hex(),
             why=f'Soft Focus mix-weight getter 0x6039fee8: key 11 -> w={weight}'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
             why=f'COLOR-bloom stubs ({len(code)} B) in section-2 FF tail'),
    ]
    meta = dict(weight=weight, strength=strength, code_at=hex(CODE_AT),
                symbols={k: hex(v) for k, v in syms.items() if k in ('bloom_flag', 'bloom_w')})
    spec = dict(components=['0x100'], patch='color_bloom', bloom=meta, edits=edits)
    return spec, code, src, lst, syms


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--strength', type=int, choices=sorted(STRENGTH_W))
    g.add_argument('--weight', type=int)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    weight = STRENGTH_W[a.strength] if a.strength else a.weight
    spec, code, src, lst, syms = build_spec(weight, a.strength)
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    (a.out / 'symbols.json').write_text(json.dumps({k: hex(v) for k, v in syms.items()}, indent=1) + '\n')
    print(f'code {len(code)} B at {CODE_AT:#x}..{CODE_AT + len(code):#x}; bloom_flag {syms["bloom_flag"]:#x} '
          f'bloom_w {syms["bloom_w"]:#x}; w={weight} (blur share {1 - weight / 1024:.1%}); wrote {a.out}')


if __name__ == '__main__':
    main()
