#!/usr/bin/env python3
"""Mod version on the Setup > Firmware screen (display only). Offline.

  .venv/bin/python -I patches/fw_version/build.py releases/v0.15/edits.json --mod-version v0.15 [--out OUT.json]

The Firmware screen builder (Confirm_Based_Version_Viewer, 0x60df5285) fills GUI data 140, a 1004-B block: four 74-B
row-label items (Body / Lens / Flash / Acc) and the "%X.%X" version strings in 4-wchar fields (+300.. single-version
rows, +940.. / +972.. two-version rows). The fields are too small to extend, so the builder, its sprintf and the block
stay stock. v0.15a: the label stays the stock localised "Body" (v0.15 replaced it with a kind-5 "Body Caduceus vX",
which the label widget clipped). v0.16b (camera: "1.1 Caduceus v0.16" clipped in the narrow value box): the Body row
label is kind 5 "Caduceus" (descriptor 0x6115d5e8 -> ASCII at 0x61242fc0, sec-6 FF tail; "Body Caduceus" mostly fit)
and fw_val shows only "<ver>" (e.g. "v0.16") in place of a non-empty Body value; an empty field passes through.

The view 0x60d7f0a4 (reads GUI data 140) hands each field to the text setter 0x60d4c9df(widget, wstr), which copies
the string into a heap buffer of its own length. This patch redirects the two Body value calls (+940 two-version
row, 0x60d7f271; +300 single-version row, 0x60d7f2cd) to `fw_val`, which copies the field (<= 4 wchars) to a stack
buffer, appends " Caduceus <ver>" and calls the real setter. An empty field is passed through unchanged. Code sits in
the dead EVF gamma step-10 B table 0x601e1c3c (only ref: step-table word 0x601e3d28). The version numbers, the
updater / version-check code and the EXIF Software template ("Version x.x", 0x604ddeb4) are untouched.
"""
import argparse, json, re, struct, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE = 0x60020020
SETTER = 0x60d4c9df                     # text setter (widget a0, wchar string a1), call [d2,d3,a2,a3],24
SITES = {0x60d7f271: '+940 (two-version Body value, widget 26)',
         0x60d7f2cd: '+300 (single-version Body value, widget 18)'}
FRAME = 88                              # fw_val frame: 16 B regs + 72 B locals ((sp) = return slot of the inner call, 64-B buffer at sp+4)
CODE_AT, CODE_END = 0x601e1c40, 0x601e1d00   # dead EVF step-10 B table 0x601e1c3c..0x601e1d3c (guards stay stock)
MAXSFX = 27                             # 4 + 27 + NUL = 32 wchars = 64 B buffer
SRC = 'patches/fw_version'


DESC, DESC_STOCK = 0x6115d5e8, bytes.fromhex('0400bd06e4d51561')   # Body row label {u16 kind, u16 id, u32 text}
LABEL, STR_AT, STR_END = 'Caduceus', 0x61242fc0, 0x61242fe0     # sec-6 FF tail (aspect list B ends 0x61242fb4)


def suffix(ver):
    if not re.fullmatch(r'v\d+\.\d+[A-Za-z0-9.\-]*', ver):
        raise SystemExit(f'--mod-version {ver!r}: expected e.g. v0.15')
    t = ver
    if len(t) > MAXSFX:
        raise SystemExit(f'suffix {t!r} longer than {MAXSFX}')
    return t


def asm(src, at, syms=None):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'a.s').write_text(' .am33_2\n .text\n .global _start\n_start:\n' + src + '\n')
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'a.o', t / 'a.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in (syms or {}).items()], '-o', t / 'a.elf', t / 'a.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'a.elf', t / 'a.bin'], check=True)
        return (t / 'a.bin').read_bytes()


def code(ver):
    wide = ''.join(f' .short {ord(c)}\n' for c in ver) + ' .short 0\n'
    return asm(f"""
 cmp 0,a1
 beq 9f
 movhu (a1),d0
 cmp 0,d0
 beq 9f
 mov wver,a1                     /* non-empty Body value -> L"{ver}" */
9:
 call setter,[d2,d3,a2,a3],24
 ret [d2,d3,a2,a3],{FRAME}
 .balign 2
wver:
{wide}""", CODE_AT, {'setter': SETTER})


def call_bytes(at, target, imm):
    return bytes([0xdd]) + ((target - at) & 0xffffffff).to_bytes(4, 'little') + bytes([0xf0, imm])


def strip(spec):
    spec.pop('fw_version', None)
    spec['edits'] = [e for e in spec['edits'] if e.get('source') != SRC]
    return spec


def apply(spec, ver):
    sfx = suffix(ver)
    stock = STOCK.read_bytes()
    strip(spec)
    c = code(sfx)
    lab = LABEL.encode('ascii') + b'\0'
    lab += b'\0' * (-len(lab) % 4)
    if CODE_AT + len(c) > CODE_END:
        raise SystemExit(f'fw_val {len(c)} B overflows {CODE_END:#x}')
    for e in spec['edits']:
        if e['addr'].startswith('off:'):
            continue
        a, n = int(e['addr'], 16), len(e['new']) // 2
        if (a < 0x601e1d3c and 0x601e1c3c < a + n or any(a < s + 7 and s < a + n for s in SITES)
                or a < STR_END and STR_AT - 8 < a + n or a < DESC + 8 and DESC < a + n):
            raise SystemExit(f'placement overlaps edit {e["addr"]}')
    edits = []
    for at, what in SITES.items():
        exp = stock[at - BASE:at - BASE + 7]
        if exp != call_bytes(at, SETTER, 24):
            raise SystemExit(f'call site {at:#x} not stock')
        edits.append(dict(kind='0x100', addr=hex(at), expect=exp.hex(), new=call_bytes(at, CODE_AT, FRAME).hex(),
                          why=f'fw_version: Firmware screen {what} setter call -> fw_val (value "{sfx}")', source=SRC))
    exp = stock[CODE_AT - BASE:CODE_AT - BASE + len(c)]
    edits.append(dict(kind='0x100', addr=hex(CODE_AT), expect=exp.hex(), new=c.hex(),
                      why=f'fw_version: fw_val ({len(c)} B, dead EVF step-10 B table) + L"{sfx}"', source=SRC))
    if stock[DESC - BASE:DESC - BASE + 8] != DESC_STOCK or set(stock[STR_AT - 8 - BASE:STR_END - BASE]) != {0xff}:
        raise SystemExit('label descriptor / string range not stock')
    edits.append(dict(kind='0x100', addr=hex(DESC), expect=DESC_STOCK.hex(), new=struct.pack('<HHI', 5, 0x6bd, STR_AT).hex(),
                      why=f'fw_version: Firmware screen Body row label -> kind 5 text "{LABEL}" (display only)', source=SRC))
    edits.append(dict(kind='0x100', addr=hex(STR_AT), expect=stock[STR_AT - BASE:STR_AT - BASE + len(lab)].hex(), new=lab.hex(),
                      why=f'fw_version: label text "{LABEL}" (sec-6 FF tail)', source=SRC))
    spec['edits'] += edits
    spec['fw_version'] = dict(mod_version=ver, value=sfx, label=LABEL, desc=hex(DESC), str_at=hex(STR_AT), code_at=hex(CODE_AT), code_len=len(c),
                              sites=[hex(s) for s in SITES], frame=FRAME)
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--mod-version', required=True)
    ap.add_argument('--out', type=Path, help='default: rewrite spec in place')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()), a.mod_version)
    (a.out or a.spec).write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['fw_version'], indent=1))
