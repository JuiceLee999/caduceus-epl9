#!/usr/bin/env python3
"""Build the E-P7 1.1 COLOR-grain edit spec (offline; no camera; no SD-named output).

  python3 -I patches/grain/build.py --level 2 --out generated/grain-color-L2           # approach B
  python3 -I patches/grain/build.py --level 2 --merge generated/hsl-fixed-test/edits.json \
          --out generated/grain-color-L2+hl                                               # + v0.1 H/L

Produces <out>/edits.json (for tools/build_package.py / tools/ep7_grain_verify.py),
routine.s, routine.lst, routine.bin, symbols.json.
--level 1|2|3 = fixed grain level (gain 50/75/100 from stock table 0x604ec0d4).
--level mono  = approach A modifier (uses request+1828 as packed; needs a converter
                patch that is NOT included - see docs/GRAIN_PORT.md).
"""
import argparse, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
CODE_AT, TAIL_END = 0x6055e680, 0x6055e800          # section-2 FF tail; v0.1 uses ..0x6055e677
WL_HOOK, SEL_HOOK = 0x6035749f, 0x603b5249
WL_STOCK, SEL_STOCK = bytes.fromhex('aa0cc605cc0604'), bytes.fromhex('aa0cc605cc5201')
SYMS = dict(ep7_wl_add_final=0x6035739e, ep7_wl_attach=0x603573d3, ep7_wl_after=0x603578bd,
            ep7_wl_hash=0x603574a6, ep7_wl_default=0x603578a9,
            ep7_sel_hash=0x603b5250, ep7_sel_default=0x603b539f)


def level_code(level):
    if level == 'mono':
        return (' movbu (1828,a1),d0               /* A: level as packed from params+5551 */\n'
                ' cmp 0,d0\n beq mod_done                     /* Off: no grain stage */')
    return f' mov {int(level)},d0\n movbu d0,(1828,a1)               /* B: fixed level */'


def assemble(level):
    src = (Path(__file__).parent / 'color_grain.s.in').read_text().replace('{level_code}', level_code(level))
    src = src.replace('{level}', str(level))
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


def build_spec(level, merge=None):
    code, src, lst, syms = assemble(level)
    d = MAIN.read_bytes()
    for at, stock in ((WL_HOOK, WL_STOCK), (SEL_HOOK, SEL_STOCK)):
        if d[at - BASE:at - BASE + len(stock)] != stock:
            raise SystemExit(f'stock bytes differ at {at:#x}')
    if CODE_AT + len(code) + 16 > TAIL_END:
        raise SystemExit('code does not fit tail with 16-byte guard')
    tail = d[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    if set(tail) != {0xff}:
        raise SystemExit('tail not erased (FF)')
    jmp = lambda src_, dst: b'\xdc' + struct.pack('<i', dst - src_) + b'\xcb\xcb'   # jmp d32; nop; nop
    edits = [
        dict(kind='0x100', addr=hex(WL_HOOK), expect=WL_STOCK.hex(), new=jmp(WL_HOOK, syms['wl_hook']).hex(),
             why='work-list builder: key<12 branch -> jmp wl_hook (key 11 adds grain modifier)'),
        dict(kind='0x100', addr=hex(SEL_HOOK), expect=SEL_STOCK.hex(), new=jmp(SEL_HOOK, syms['sel_hook']).hex(),
             why='combiner selector: key<12 branch -> jmp sel_hook (key 11 + stage 0x0902 -> 32)'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
             why=f'COLOR-grain hooks + modifier ({len(code)} B) in section-2 FF tail'),
    ]
    spec = dict(components=['0x100'], patch='color_grain', level=level, code_at=hex(CODE_AT),
                symbols={k: hex(v) for k, v in syms.items() if k in ('wl_hook', 'sel_hook', 'grain_mod')},
                edits=edits)
    if merge:
        other = json.loads(Path(merge).read_text())
        spans = [(int(e['addr'], 16), int(e['addr'], 16) + len(bytes.fromhex(e['new']))) for e in edits]
        for e in other['edits']:
            a = int(e['addr'], 16); b = a + len(bytes.fromhex(e['new']))
            if any(a < y and x < b for x, y in spans):
                raise SystemExit(f'merge overlap at {e["addr"]}')
        spec['edits'] = other['edits'] + edits
        spec['merged_from'] = str(merge)
        for k in ('native_rows', 'recipe', 'hue_ui', 'light_ui'):
            if k in other:
                spec[k] = other[k]
    return spec, code, src, lst, syms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--level', required=True, choices=['1', '2', '3', 'mono'])
    ap.add_argument('--merge', type=Path, help='existing edits.json (e.g. v0.1 fixed-H/L) to combine')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    level = a.level if a.level == 'mono' else int(a.level)
    spec, code, src, lst, syms = build_spec(level, a.merge)
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
