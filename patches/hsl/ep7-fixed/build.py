#!/usr/bin/env python3
"""Build the E-P7 fixed-H/L edit spec from a recipe (offline; no camera).

  .venv/bin/python -I patches/hsl/ep7-fixed/build.py --recipe classic_neg --out generated/hsl-fixed-classic_neg

Produces <out>/edits.json (for tools/build_package.py), routine.bin, routine.lst.
"""
import argparse, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
HOOK, RESUME, BUILDER = 0x603b02d9, 0x603b02de, 0x603b0068
HOOK_STOCK = bytes.fromhex('cd8ffdf060')
ROUTINE_AT, TAIL_END = 0x6055e5c0, 0x6055e800          # section 2 FF tail (verified loaded)
HUE_OFF = 688 + 18
L_LUT = [-300, -250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250, 300]


def native_table(hue_ui, light_ui):
    rows = []
    for r in range(12):                       # physical record r <- UI index w
        w = 2 * (r % 6) + r // 6
        h, l = int(hue_ui[w]), int(light_ui[w])
        if not (-7 <= h <= 7 and -7 <= l <= 7):
            raise ValueError('hue/light must be -7..7')
        rows.append((-1000 * h, L_LUT[l + 7]))
    return rows


def assemble(rows):
    src = (Path(__file__).parent / 'fixed_hl.s.in').read_text()
    table = '\n'.join(f' .hword {h},{l}   /* rec {r} */' for r, (h, l) in enumerate(rows))
    src = src.replace('{hue_off}', str(HUE_OFF)).replace('{table}', table)
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(ROUTINE_AT), '-e', '_start',
                        f'--defsym=ep7_builder={BUILDER:#x}', f'--defsym=ep7_resume={RESUME:#x}',
                        '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        return (t / 'p.bin').read_bytes(), src, (t / 'p.lst').read_text()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--recipe', required=True)
    ap.add_argument('--recipes', type=Path, default=ROOT / 'sim/recipes/fuji_like.json')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    rc = json.loads(a.recipes.read_text())['recipes'][a.recipe]
    rows = native_table(rc.get('hue', [0] * 12), rc.get('light', [0] * 12))
    code, src, lst = assemble(rows)
    d = MAIN.read_bytes()
    if d[HOOK - BASE:HOOK - BASE + 5] != HOOK_STOCK:
        sys.exit('hook stock bytes differ')
    if ROUTINE_AT + len(code) > TAIL_END:
        sys.exit('routine does not fit tail')
    tail = d[ROUTINE_AT - BASE:ROUTINE_AT - BASE + len(code)]
    if set(tail) != {0xff}:
        sys.exit('tail not erased (FF)')
    jmp = b'\xdc' + struct.pack('<i', ROUTINE_AT - HOOK)
    spec = dict(components=['0x100'], recipe=a.recipe, hue_ui=rc.get('hue'), light_ui=rc.get('light'),
                native_rows=rows, edits=[
        dict(kind='0x100', addr=hex(HOOK), expect=HOOK_STOCK.hex(), new=jmp.hex(),
             why='COLOR builder call -> jmp fixed-H/L routine'),
        dict(kind='0x100', addr=hex(ROUTINE_AT), expect=tail.hex(), new=code.hex(),
             why=f'fixed-H/L routine + table ({len(code)} B) in section-2 FF tail')])
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    print(f'routine {len(code)} B at {ROUTINE_AT:#x}; hook {jmp.hex()}; wrote {a.out}')


if __name__ == '__main__':
    main()
