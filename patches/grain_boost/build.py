#!/usr/bin/env python3
"""COLOR-only grain boost (v0.16). Offline; adds 3 edits to an existing merged spec.

  python3 -I patches/grain_boost/build.py releases/v0.16/edits.json [--out OUT.json]

Our COLOR grain (patches/grain) runs the stock single-pass combiner 32 (handler 0x603a065b), whose gain comes
from table 0x604ec0d4 = 50/75/100. Stock MONO full-size stills use the mask route (combiner 31, handler
0x603a05b3) with table 0x604ec0ce = 110/300/600, so COLOR grain is 2-6x weaker than MONO Low/Med/High.

Patching the shared table pointer at 0x603a06dd would also change stock MONO grain on small jobs (classes 4-9),
so this patch only changes the gain for key-11 (COLOR) requests:
  hook A 0x603a065b (6 B, handler-32 entry `mov (8,a2),d0; mov (4,a2),a2`) -> jmp gb_a; nop
    gb_a replays both loads and also loads the job key (52,ctx) into d2, then jumps back to 0x603a0661.
    d2 is free in handler 32 (never read; 0x6039fdf0 saves it) and every exit is `ret [d2,d3,a2,a3],20`
    (0x603a0771), which restores the caller's d2.
  hook B 0x603a06dd (6 B, `add 0x604ec0d4,a0`, a0 = 2*level, level already checked 1..3) -> jmp gb_b; nop
    gb_b: a0 += 0x604ec0d4; if d2 == 11: a0 -= 6 (-> stock 0x604ec0ce = 110/300/600); jmp 0x603a06e3.
Key 11 reaches combiner 32 only through our sel_hook (stock maps key 11 to no grain combiner), so every key-12
(MONO) and art-filter request keeps the stock table and an identical bank. Level 0 / >3 never reach hook B.
Code: 0x60210e10.. (section 1, the v0.4 sec-1 bloom block, FF in clarity builds; guards e00-e10 and to e80 FF).
"""
import argparse, json, struct, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE = 0x60020020
SRC = 'patches/grain_boost'
HOOK_A, HOOK_A_STOCK, RET_A = 0x603a065b, bytes.fromhex('f80208f82a04'), 0x603a0661
HOOK_B, HOOK_B_STOCK, RET_B = 0x603a06dd, bytes.fromhex('fcd0d4c04e60'), 0x603a06e3
WEAK, STRONG = 0x604ec0d4, 0x604ec0ce
CODE_AT, CODE_END = 0x60210e10, 0x60210e40     # claim; 0x60210e00-e10 and e40-e90 stay FF

SRC_ASM = f"""
 .am33_2
 .text
 .global _start
_start:
gb_a:                       /* from 0x603a065b, a2 = combiner context */
 mov (8,a2),d0
 mov (52,a2),d2             /* job key (context+52, as the selector 0x603b5246 reads it) */
 mov (4,a2),a2
 jmp gb_ret_a               /* 0x603a0661 */
gb_b:                       /* from 0x603a06dd, a0 = 2*level (1..3) */
 add {WEAK:#x},a0
 cmp 11,d2
 bne 1f
 add -6,a0                  /* COLOR: {STRONG:#x} = 110/300/600 (stock MONO full-size) */
1:
 jmp gb_ret_b               /* 0x603a06e3 */
"""


def assemble():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'a.s').write_text(SRC_ASM)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'a.o', t / 'a.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start', f'--defsym=gb_ret_a={RET_A:#x}', f'--defsym=gb_ret_b={RET_B:#x}', '-o', t / 'a.elf', t / 'a.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'a.elf', t / 'a.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'a.elf'], check=True, capture_output=True, text=True).stdout
        syms = {n: int(a, 16) for a, _, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3)}
        return (t / 'a.bin').read_bytes(), syms


def jmp(at, dst):
    return b'\xdc' + struct.pack('<i', dst - at) + b'\xcb'      # jmp d32; nop


def apply(spec):
    stock = STOCK.read_bytes()
    spec.pop('grain_boost', None)
    spec['edits'] = [e for e in spec['edits'] if e.get('source') != SRC]
    code, syms = assemble()
    if CODE_AT + len(code) > CODE_END:
        raise SystemExit(f'code {len(code)} B overflows {CODE_END:#x}')
    if set(stock[CODE_AT - 16 - BASE:CODE_END + 0x40 - BASE]) != {0xff}:
        raise SystemExit('placement + guards not FF in stock')
    if struct.unpack_from('<3H', stock, STRONG - BASE) != (110, 300, 600) or struct.unpack_from('<3H', stock, WEAK - BASE) != (50, 75, 100):
        raise SystemExit('gain tables not stock')
    claims = [(CODE_AT - 16, CODE_END + 0x40), (HOOK_A, HOOK_A + 6), (HOOK_B, HOOK_B + 6)]
    for e in spec['edits']:
        if e['addr'].startswith('off:'):
            continue
        a, n = int(e['addr'], 16), len(e['new']) // 2
        if any(a < hi and lo < a + n for lo, hi in claims):
            raise SystemExit(f'overlaps edit {e["addr"]} ({e["why"][:60]})')
    for at, exp in ((HOOK_A, HOOK_A_STOCK), (HOOK_B, HOOK_B_STOCK)):
        if stock[at - BASE:at - BASE + 6] != exp:
            raise SystemExit(f'stock bytes differ at {at:#x}')
    spec['edits'] += [
        dict(kind='0x100', addr=hex(HOOK_A), expect=HOOK_A_STOCK.hex(), new=jmp(HOOK_A, syms['gb_a']).hex(), source=SRC,
             why='grain boost: combiner-32 handler entry loads -> jmp gb_a (replayed + job key -> d2)'),
        dict(kind='0x100', addr=hex(HOOK_B), expect=HOOK_B_STOCK.hex(), new=jmp(HOOK_B, syms['gb_b']).hex(), source=SRC,
             why='grain boost: combiner-32 gain table add -> jmp gb_b (key 11: 110/300/600, else stock 50/75/100)'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=stock[CODE_AT - BASE:CODE_AT - BASE + len(code)].hex(), new=code.hex(),
             source=SRC, why=f'grain boost: gb_a/gb_b ({len(code)} B) in section-1 FF tail (v0.4 sec-1 bloom block)'),
    ]
    spec['grain_boost'] = dict(code_at=hex(CODE_AT), code_len=len(code), gb_a=hex(syms['gb_a']), gb_b=hex(syms['gb_b']),
                               hooks=[hex(HOOK_A), hex(HOOK_B)], color_table=hex(STRONG), color_gains=[110, 300, 600],
                               other_table=hex(WEAK), other_gains=[50, 75, 100])
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, help='default: rewrite spec in place')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    (a.out or a.spec).write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['grain_boost'], indent=1))
