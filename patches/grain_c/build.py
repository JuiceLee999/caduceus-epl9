#!/usr/bin/env python3
"""v0.22 probe: COLOR stills through the stock full-size MONO grain route (GRAIN_PORT "Approach C"). Offline.

  python3 -I patches/grain_c/build.py releases/v0.21/edits.json --out releases/v0.22/edits.json
  python3 -I patches/fw_version/build.py releases/v0.22/edits.json --mod-version 0.22

Stock key 12, job class 0 (0x603577d4): work list = mask pass 0x60359bc8 (0x60357363) + grain image pass 0x60359cd8
(0x6035739e, no single-shot variant, attach flag 0); the feature chain then adds post-pass ENTRIES (not modifiers),
whose last one writes the output. Gain = request+1828 (packed from params+5551 = job+5587) -> handler 31, table
0x604ec0ce 110/300/600, mask LUT 0x605003aa (tone selector, stage 0x0900).

For key 11 the same route is taken when (all, else the v0.21 single-pass 0x0902 route, unchanged):
  the v0.21 wl_hook already passed (job-type gate, marker, COLOR slot grain 1..5), job class job+11320 == 0, and
  job+16 has 0x80000 (stock COLOR creative-shading bit, 0x60353bcf: always set for keys 9/11) -> the chain is sure
  to append the shading post-pass entry 0x6035b529 after the grain pass (the pass that outputs; same shape as MONO).
Edits on top of v0.21:
  wl hook   grain blob 0x60210d41 (7 B `mov a3,a0; mov 0x60356d7b,a1` on the success path) -> jmp gc_wl; gc_wl writes
            job+5587 = min(level,3) (MONO Low/Med/High = slot 1/2/3; 4/5 = High), adds the two stock MONO entries
            exactly as 0x603577d4 and jumps to the stock feature chain 0x603578bd
  selector  0x603b5249 hook re-pointed to gc_sel: key 11 + kind 0 + stage 0x0901 -> 31 (as key 12), else v0.21 sel_hook
  tone      0x603b04b6 (7 B `cmp 12,d1; bcc; jmp 0x603b06b5`) -> jmp gc_tone: key 11 + kind 0 + stage 0x0900 -> mask
            LUT 0x605003aa (as key 12 at 0x603b04fa), else replayed
Code: 0x601e3890.. (dead EVF step-0 R table, after the v0.21 grain labels; only ref: step-table word 0x601e3c80).
"""
import argparse, copy, json, struct, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE, SRC = 0x60020020, 'patches/grain_c'
CODE_AT, CODE_END = 0x601e3890, 0x601e3930
WL_SITE, WL_OLD, WL_RESUME = 0x60210d41, bytes.fromhex('9cfcdd7b6d3560'), 0x60210d48
SEL_HOOK, SEL_OLD_TGT = 0x603b5249, 0x60210d74
TONE_HOOK, TONE_STOCK = 0x603b04b6, bytes.fromhex('a50cc605ccfb01')
SYMS = dict(ep7_add=0x60357363, ep7_final=0x6035739e, ep7_chain=0x603578bd, ep7_sel_old=SEL_OLD_TGT,
            ep7_tone_def=0x603b06b5, ep7_tone_hash=0x603b04bd, ep7_wl_resume=WL_RESUME)

ASM = """
 .am33_2
 .text
 .global _start
_start:
gc_wl:                           /* from the v0.21 wl_hook success path: d0 = slot level 1..5, d2 = 11, a2 = job+4, a3 = list */
 movbu (11316,a2),d1             /* job class job+11320 */
 cmp 0,d1
 bne 9f
 mov (12,a2),d1                  /* job flags job+16 */
 btst 0x80000,d1                 /* COLOR shading bit: the chain appends the output post-pass */
 beq 9f
 cmp 3,d0
 bls 1f
 mov 3,d0                        /* MONO scale: 1/2/3 = 110/300/600; 4/5 -> 3 */
1:
 movbu d0,(5583,a2)              /* params+5551 (job+5587) -> request+1828 in every pass (packer 0x60354f30) */
 mov a3,a0
 mov 0x60359bc8,a1               /* stock MONO mask pass */
 call ep7_add,[a2,a3],8
 mov a3,a0
 mov 0x60359cd8,a1               /* stock MONO grain image pass, no single-shot variant */
 clr d1
 clr d0
 call ep7_final,[d2,d3,a2,a3],16
 jmp ep7_chain                   /* 0x603578bd: stock feature chain */
9:
 mov a3,a0                       /* replay the 7 bytes: v0.21 single-pass route */
 mov 0x60356d7b,a1
 jmp ep7_wl_resume

gc_sel:                          /* combiner selector hook 0x603b5249: d2 = key, a2 = ctx+4 */
 cmp 11,d2
 bne 8f
 mov (a2),a1
 movbu (16,a1),d0
 cmp 0,d0
 bne 8f
 movhu (12,a1),d0
 cmp 2305,d0                     /* 0x0901: MONO grain image pass */
 bne 8f
 mov 31,d0
 ret [d2,a2],12
8:
 jmp ep7_sel_old                 /* v0.21 sel_hook (0x0902 -> 32, stock targets) */

gc_tone:                         /* tone selector 0x603b04b6: d1 = key, a0 = request, a1 = request+12 */
 cmp 11,d1
 bne 7f
 movhu (a1),d0
 cmp 2304,d0                     /* 0x0900: mask pass */
 bne 7f
 movbu (4,a1),d0                 /* kind (request+16) */
 cmp 0,d0
 bne 7f
 mov 0x605003aa,a0               /* stock MONO mask curve (as 0x603b0505) */
 ret [d2,d3,a2,a3],24
7:
 cmp 12,d1
 bcc 6f
 jmp ep7_tone_def
6:
 jmp ep7_tone_hash
"""


def assemble():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'a.s').write_text(ASM)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'a.o', t / 'a.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in SYMS.items()], '-o', t / 'a.elf', t / 'a.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'a.elf', t / 'a.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'a.elf'], check=True, capture_output=True, text=True).stdout
        syms = {n: int(a, 16) for a, _, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3)}
        return (t / 'a.bin').read_bytes(), syms


def jmp(at, dst, n):
    return b'\xdc' + struct.pack('<i', dst - at) + b'\xcb' * (n - 5)


def covering(spec, addr, n):
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16)
            if a <= addr and addr + n <= a + len(e['new']) // 2:
                return e, addr - a
    raise SystemExit(f'{addr:#x}: no covering edit')


def apply(spec):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    code, syms = assemble()
    if CODE_AT + len(code) > CODE_END:
        raise SystemExit(f'code {len(code)} B too big')
    for e in spec['edits']:
        if not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if (a < CODE_END and CODE_AT - 6 < a + n) or (a < TONE_HOOK + 7 and TONE_HOOK < a + n):
                raise SystemExit(f'overlap {e["addr"]}')
    if stock[TONE_HOOK - BASE:TONE_HOOK - BASE + 7] != TONE_STOCK:
        raise SystemExit('tone site not stock')
    e, o = covering(spec, WL_SITE, 7)                        # v0.21 grain blob
    b = bytearray.fromhex(e['new'])
    if bytes(b[o:o + 7]) != WL_OLD:
        raise SystemExit('wl success path differs')
    b[o:o + 7] = jmp(WL_SITE, syms['gc_wl'], 7)
    e['new'] = b.hex(); e['why'] += ' [v0.22: success path -> gc_wl (class-0 MONO route)]'
    e, o = covering(spec, SEL_HOOK, 7)
    b = bytearray.fromhex(e['new'])
    if SEL_HOOK + struct.unpack_from('<i', b, o + 1)[0] != SEL_OLD_TGT:
        raise SystemExit('selector hook target differs')
    b[o:o + 7] = jmp(SEL_HOOK, syms['gc_sel'], 7)
    e['new'] = b.hex(); e['why'] += ' [v0.22: -> gc_sel (key 11 0x0901 -> 31) -> sel_hook]'
    spec['edits'] += [
        dict(kind='0x100', addr=hex(TONE_HOOK), expect=TONE_STOCK.hex(), new=jmp(TONE_HOOK, syms['gc_tone'], 7).hex(), source=SRC,
             why='v0.22 grain C: tone selector key<12 branch -> jmp gc_tone (key 11 mask pass 0x0900 -> LUT 0x605003aa)'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=stock[CODE_AT - BASE:CODE_AT - BASE + len(code)].hex(), new=code.hex(), source=SRC,
             why=f'v0.22 grain C: gc_wl / gc_sel / gc_tone ({len(code)} B, dead EVF step-0 R table)'),
    ]
    spec['grain_c'] = dict(built_by=SRC, base='releases/v0.21/edits.json', code_at=hex(CODE_AT), code_len=len(code),
                           symbols={k: hex(v) for k, v in syms.items() if k.startswith('gc_')},
                           hooks=[hex(WL_SITE), hex(SEL_HOOK), hex(TONE_HOOK)], mono_levels='slot 1/2/3/4/5 -> 1/2/3/3/3 (110/300/600)')
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['grain_c']))
