#!/usr/bin/env python3
"""Build the E-PL9 1.101 look patch edit spec (offline; no camera; no SD-named output).

  python3 -I patches/epl9_look/build.py [--look test_strong] [--out generated/epl9_look]

Writes <out>/edits.json (for tools/epl9_look_verify.py and the E-PL9 packager), c_stub.s, c_stub.lst,
c_stub.bin and symbols.json. Needs mn10300 binutils (tools/setup_toolchain.sh), so run it under Linux/WSL.

Design: docs/EPL9_LOOK_HOOK.md (v1: Custom becomes mode 11, one look baked in).
  T1  0x60693d02  capture population: Custom (6) stores 11 instead of resolving the base mode (0x9d11).
  T2  0x6069560c  slot fill: same for slot 0's mode byte.
  T3  0x607210af  live-view record (A+353): same, so the preview shows the look too.
  C   0x6079ec53  `call builder` -> `jmp c_stub` (5 B).
  S   0x6092c6b0  c_stub + look data, in the section-2 FF tail (tools/epl9_code_space.py: 0x6092c6a8..0x6092c800,
                  no literal or relative references). 0x6092c6a8..0x6092c6b0 and everything after the stub stay FF.
"""
import argparse, hashlib, json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/epl9_1101/00_0100_406e0020.decoded.bin'
MAIN_SHA = '8e39c335d54fd8ddea189db82fe708159f43f9995bba42c2cd47dd22b8814267'
BASE = 0x60400020

BUILDER = 0x6079e9e2
HOOK, RESUME = 0x6079ec53, 0x6079ec58
STUB_AT, STUB_LIMIT = 0x6092c6b0, 0x6092c800          # sec 2 load end is 0x6092c800
FF_FROM = 0x6092c6a8                                   # first FF byte of the tail (kept as guard up to STUB_AT)
OUT_RECORDS, HUE_OFF, LIGHT_OFF = 688, 18, 22

# In-place edits: (name, addr, stock bytes, new bytes, why)
FIXED = [
    ('T1', 0x60693d02, 'fccc119d0000', '800bca0ecbcb',
     'capture population: Custom (6) -> mov 11,d0; bra 0x60693d12 (store), instead of reading 0x9d11'),
    ('T2', 0x6069560c, 'fccc119d0000', '800bf052ca0f',
     'slot fill: Custom (6) -> slot mode byte 11 (movbu d0,(a2)); bra 0x6069561f'),
    ('T3', 0x607210af, 'dd654fffff0000', '800bcbcbcbcbcb',
     'live-view record: Custom (6) -> mov 11,d0 + 5 nop instead of `call 0x60716014` (Custom base); '
     'the next movbu d0,(a2) stores 11 at record A+353'),
]
HOOK_STOCK = 'cd8ffdf060'    # call 0x6079e9e2,[d2,d3,a2,a3],96

HUE_PER_UI = -1000                                                      # E-P7 HUE_LUT
L_LUT = [-300, -250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250, 300]   # E-P7, ui -7..7

# Looks: 12 values each in UI (wheel) order. hue/light -7..7, sat -5..5 (stock COLOR profile ranges).
LOOKS = {
    # v1 camera test: unmistakable on any subject. Every hue rotated by +6 (about 66 degrees), saturation +3,
    # lightness unchanged, so the effect does not depend on knowing which UI sector is which colour.
    'test_strong': dict(hue=[6] * 12, sat=[3] * 12, light=[0] * 12,
                        note='v1 camera test: global hue rotation +6, saturation +3'),
}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def native(look):
    for k, lim in (('hue', 7), ('light', 7), ('sat', 5)):
        v = look[k]
        if len(v) != 12 or any(not isinstance(x, int) or abs(x) > lim for x in v):
            raise ValueError(f'{k}: need 12 integers in -{lim}..{lim}')
    recs = []
    for r in range(12):
        w = 2 * (r % 6) + r // 6                     # physical record r <- wheel index w (E-P7 perm)
        recs.append((HUE_PER_UI * look['hue'][w], L_LUT[look['light'][w] + 7]))
    return recs


def assemble(src, out):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 's.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-al=' + str(t / 's.lst'), '-o', t / 's.o', t / 's.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(STUB_AT), '-e', '_start',
                        f'--defsym=epl9_builder={BUILDER:#x}', f'--defsym=epl9_resume={RESUME:#x}',
                        '-o', t / 's.elf', t / 's.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 's.elf', t / 's.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 's.elf'], check=True, capture_output=True, text=True).stdout
        syms = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
        (out / 'c_stub.s').write_text(src)
        (out / 'c_stub.lst').write_text((t / 's.lst').read_text())
        return (t / 's.bin').read_bytes(), syms


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--look', default='test_strong', choices=sorted(LOOKS))
    ap.add_argument('--out', type=Path, default=ROOT / 'generated/epl9_look')
    a = ap.parse_args()
    d = MAIN.read_bytes()
    if sha(d) != MAIN_SHA:
        raise SystemExit('unexpected E-PL9 main')
    a.out.mkdir(parents=True, exist_ok=True)
    look = LOOKS[a.look]
    recs = native(look)
    src = (HERE / 'c_stub.s.in').read_text().format(
        hook=hex(HOOK), resume=hex(RESUME), rec0_hue=OUT_RECORDS + HUE_OFF,
        sat_bytes=', '.join(str(v) for v in look['sat']),
        hl_words=', '.join(f'{h}, {l}' for h, l in recs))
    if LIGHT_OFF - HUE_OFF != 4:
        raise ValueError('stub writes light at hue+4')
    stub, syms = assemble(src, a.out)
    if STUB_AT + len(stub) > STUB_LIMIT - 16:
        raise ValueError(f'stub too long: {len(stub)} B')
    if d[FF_FROM - BASE:STUB_LIMIT - BASE] != b'\xff' * (STUB_LIMIT - FF_FROM):
        raise ValueError('section-2 tail is not FF')

    hook_new = b'\xdc' + (STUB_AT - HOOK).to_bytes(4, 'little', signed=True)   # jmp d32: relative to the jmp itself
    edits = []
    for name, addr, old, new, why in FIXED:
        if d[addr - BASE:addr - BASE + len(old) // 2].hex() != old or len(old) != len(new):
            raise ValueError(f'{name}: stock bytes differ')
        edits.append(dict(kind='0x100', addr=hex(addr), expect=old, new=new, why=f'{name}: {why}'))
    if d[HOOK - BASE:HOOK - BASE + 5].hex() != HOOK_STOCK:
        raise ValueError('hook: stock bytes differ')
    edits.append(dict(kind='0x100', addr=hex(HOOK), expect=HOOK_STOCK, new=hook_new.hex(),
                      why=f'C: call builder -> jmp c_stub ({STUB_AT:#x})'))
    edits.append(dict(kind='0x100', addr=hex(STUB_AT), expect='ff' * len(stub), new=stub.hex(),
                      why=f'S: c_stub + look "{a.look}" ({len(stub)} B, section-2 FF tail)'))
    spans = sorted((int(e['addr'], 16), int(e['addr'], 16) + len(e['new']) // 2) for e in edits)
    if any(b[0] < a_[1] for a_, b in zip(spans, spans[1:])):
        raise ValueError('overlapping edits')

    spec = dict(body='Olympus PEN E-PL9', firmware='1.101 (OLY_E_133_1101)', main_base=hex(BASE),
                main_sha256=MAIN_SHA, design='docs/EPL9_LOOK_HOOK.md', look=a.look, look_values=look,
                native_records=[dict(record=r, hue=h, light=l) for r, (h, l) in enumerate(recs)],
                components=['0x100'], edits=edits)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'c_stub.bin').write_bytes(stub)
    keep = {k: hex(v) for k, v in syms.items() if k in ('c_stub', 'c_loop', 'look_sat', 'look_hl', 'c_end')}
    (a.out / 'symbols.json').write_text(json.dumps(dict(keep, stub_at=hex(STUB_AT), stub_bytes=len(stub)), indent=1) + '\n')
    print(f'look {a.look}: stub {len(stub)} B at {STUB_AT:#x}..{STUB_AT + len(stub):#x}; {len(edits)} edits -> {a.out / "edits.json"}')
    for e in edits:
        print(f"  {e['addr']}  {e['expect'][:24]}{'..' if len(e['expect']) > 24 else ''} -> {e['new'][:24]}{'..' if len(e['new']) > 24 else ''}  {e['why']}")


if __name__ == '__main__':
    main()
