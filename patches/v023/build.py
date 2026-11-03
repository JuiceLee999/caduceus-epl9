#!/usr/bin/env python3
"""v0.23 = releases/v0.22 (byte level) + Film-page duplicate fix + "Film: " label back. Offline.

  python3 -I patches/v023/build.py releases/v0.22/edits.json --out releases/v0.23/edits.json
  python3 -I patches/fw_version/build.py releases/v0.23/edits.json --mod-version 0.23

1. Duplicate look on the Film page. fm_up/fm_down step a slot over [own, looks 1..n, Stock]. "own" is the slot's entry
   snapshotted at the first step. When the slot resumed on a library look (name match at load) and is unmodified,
   own is a byte copy of that look, so the dial showed the look twice ("Velvia ... Stock, Velvia, Velvia, Astia").
   fd_first (hook 0x601e2d51, before the step loop): first step for this slot (snap 0) on a library look (pos != 0)
   and the editor's modified test (ed_cfg_fm word = lt_mod, keeps d2/d3/a2/a3) says 0 -> snap = 2 ("own hidden";
   the snapshot code only runs for snap 0, and pos 0 is never reached, so the snapshot is never read).
   fd_own (hook 0x601e2d67, the loop's own/Stock test): pos 0 with snap 2 -> keep stepping (loop top 0x601e2d5d).
   A modified slot keeps its own entry (the user's edits) in the cycle as before.
2. Film-page guide label "Film: <name>" again: the first byte of ed_t_film (0x60b9dee3) and ed_t_film2 (0x60b9deea)
   NUL -> 'F', and the label cap 16 -> 19 (ed_guide `mov 16,d3`, 0x60b9de65; buffer 33 units) with both prefix
   thresholds 11 -> 14, so every library name (<= 12 + '*') reads "Film: <name>[*]". Mono unchanged.
Code: 96 B after fm_ui in its own dead EVF step-4 table (0x601e2edc..0x601e2f3c, film_menu_v2 UI limit).
"""
import argparse, copy, json, struct, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE, SRC = 0x60020020, 'patches/v023'
CODE_AT, CODE_END = 0x601e2edc, 0x601e2f3c
FIRST_SITE, FIRST_OLD = 0x601e2d51, bytes.fromhex('fa44480844')      # movbu (2120,a0),d1 ; inc d1
OWN_SITE, OWN_OLD = 0x601e2d67, bytes.fromhex('a000c815a4')          # cmp 0,d0 ; beq 2d7e ; cmp d1,d0
LABELS = [(0x60b9dee3, b'\0', b'F', 'Film page label "Film: " (ed_t_film)'),
          (0x60b9deea, b'\0', b'F', 'Film page label "Film " (ed_t_film2)'),
          (0x60b9de3c, b'\x0b', b'\x0e', 'Film page: "Film: " for name + star up to 13 (was 10)'),
          (0x60b9de46, b'\x0b', b'\x0e', 'Film page: "Film " only for 14 (was 11)'),
          (0x60b9de66, b'\x10', b'\x13', 'guide label cap 19 characters (was 16; text buffer is 33)')]
SYMS = dict(ed_cfg_fm=0x601e3160, loop_top=0x601e2d5d, loop_out=0x601e2d7e, after_first=0x601e2d56,
            stock_beq=0x601e2d6c, look_test=0x601e2d6e)

ASM = """
 .am33_2
 .text
 .global _start
_start:
fd_first:                        /* a0 = L, a2 = P, d3 = k, d2 = step; d0/d1/a1 free */
 mov a0,a1
 add d3,a1
 movbu (2125,a1),d0              /* snap: 0 = first step */
 cmp 0,d0
 bne 1f
 movbu (2121,a1),d0              /* pos: own (0) -> nothing to hide */
 cmp 0,d0
 beq 1f
 mov d3,d1
 mov (ed_cfg_fm),a0
 calls (a0)                      /* lt_mod(P, k): keeps d2/d3/a2/a3 */
 mov (1016,a2),a0                /* a0 = L again (FVAL-checked by fm_up) */
 and 1,d0
 bne 1f                          /* modified: own stays (the user's edits) */
 mov a0,a1
 add d3,a1
 mov 2,d0
 movbu d0,(2125,a1)              /* snap 2: own hidden, no snapshot */
1:
 movbu (2120,a0),d1              /* replayed: d1 = n + 1 */
 inc d1
 jmp after_first

fd_own:                          /* d0 = candidate pos, d1 = n + 1, a0 = L; d3/a1 scratch; (4,sp) = k */
 cmp 0,d0
 bne 2f
 mov (4,sp),d3
 mov a0,a1
 add d3,a1
 movbu (2125,a1),d3
 cmp 2,d3
 bne 3f
 jmp loop_top                    /* own hidden: keep stepping */
3:
 jmp loop_out                    /* own */
2:
 cmp d1,d0
 jmp stock_beq                   /* replayed: beq loop_out (Stock), flags kept */
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
        return (t / 'a.bin').read_bytes(), {n: int(a, 16) for a, _, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3)}


def covering(spec, addr, n=1):
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16)
            if a <= addr and addr + n <= a + len(e['new']) // 2:
                return e, addr - a
    raise SystemExit(f'{addr:#x}: no covering edit')


def put(spec, addr, old, new, what):
    e, o = covering(spec, addr, len(old))
    b = bytearray.fromhex(e['new'])
    if bytes(b[o:o + len(old)]) != old:
        raise SystemExit(f'{addr:#x}: {b[o:o + len(old)].hex()} != {old.hex()} ({what})')
    b[o:o + len(new)] = new
    e['new'] = b.hex(); e['why'] += f' [v0.23: {what}]'


def jmp(at, dst):
    return b'\xdc' + struct.pack('<i', dst - at)


def apply(spec):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    code, syms = assemble()
    if CODE_AT + len(code) > CODE_END:
        raise SystemExit(f'code too big ({len(code)})')
    for e in spec['edits']:
        if not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a < CODE_END and CODE_AT < a + n:
                raise SystemExit(f'overlap {e["addr"]}')
    put(spec, FIRST_SITE, FIRST_OLD, jmp(FIRST_SITE, syms['fd_first']), 'step start -> fd_first (hide an unmodified own)')
    put(spec, OWN_SITE, OWN_OLD, jmp(OWN_SITE, syms['fd_own']), 'own/Stock test -> fd_own (skip hidden own)')
    for a, o, n, w in LABELS:
        put(spec, a, o, n, w)
    spec['edits'].append(dict(kind='0x100', addr=hex(CODE_AT), expect=stock[CODE_AT - BASE:CODE_AT - BASE + len(code)].hex(),
                              new=code.hex(), source=SRC, why=f'v0.23 Film page: fd_first / fd_own ({len(code)} B, dead EVF step-4 table after fm_ui)'))
    spec['v023'] = dict(built_by=SRC, base='releases/v0.22/edits.json', code_at=hex(CODE_AT), code_len=len(code),
                        symbols={k: hex(v) for k, v in syms.items() if k.startswith('fd_')},
                        sites=[hex(FIRST_SITE), hex(OWN_SITE)] + [hex(a) for a, *_ in LABELS], snap_hidden=2)
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['v023']))
