#!/usr/bin/env python3
"""v0.14 in place: LV refresh after an Art Effect change (art_rf.s.in). Offline.

  .venv/bin/python -I patches/lv_art_refresh/build.py releases/v0.14/edits.json [--check]

Re-points three sites inside existing v0.14 edits (look_extras ex_set art write, film_menu_v2 fm_ui u_apply and
its final jmp ed_poke) and adds one code edit in the unused tail of the look_extras claim (0x601e3758..0x601e383c,
dead EVF gamma LUT bytes, stock until now). Refuses if already applied or any byte is not as expected.
"""
import argparse, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE = 0x60020020
CODE_AT, CODE_END = 0x601e3758, 0x601e383c
SITES = {  # site: (bytes in v0.14, target label)
    'ex_art': (0x601e33b7, bytes.fromhex('f8564eca6e'), 'ex_art'),
    'fm_pre': (0x601e2e35, bytes.fromhex('f1e000f8501f'), 'fm_pre'),
    'fm_post': (0x601e2e93, bytes.fromhex('dc6dfb0501'), 'fm_post'),
}
SYMS = dict(ep7_sget=0x602af887, ep7_manager=0x60827440, ep7_facade=0x607f9062, ed_poke=0x61242a00,
            ex_s_dirty=0x601e3428, fm_resume=0x601e2e3b)
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'


def assemble():
    src = (HERE / 'art_rf.s.in').read_text()
    for k, (a, _, _) in SITES.items():
        src = src.replace('{' + k + '_site}', hex(a))
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'a.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'a.o', t / 'a.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in SYMS.items()], '-o', t / 'a.elf', t / 'a.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'a.elf', t / 'a.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'a.elf'], check=True, capture_output=True, text=True).stdout
        sy = {l.split()[2]: int(l.split()[0], 16) for l in nm.splitlines() if len(l.split()) == 3}
        return (t / 'a.bin').read_bytes(), sy


def jmp(site, target, n):
    return b'\xdc' + struct.pack('<i', target - site) + b'\xcb' * (n - 5)


def apply(spec):
    code, sy = assemble()
    if CODE_AT + len(code) > CODE_END:
        raise SystemExit(f'code {len(code)} B does not fit')
    if 'lv_art_refresh' in spec:
        raise SystemExit('already applied')
    stock = STOCK.read_bytes()
    for e in spec['edits']:
        a, n = int(e['addr'], 16), len(e['new']) // 2
        if a < CODE_END and CODE_AT < a + n:
            raise SystemExit(f'placement overlaps edit {e["addr"]}')
    for name, (site, want, lab) in SITES.items():
        hit = [e for e in spec['edits'] if int(e['addr'], 16) <= site and site + len(want) <= int(e['addr'], 16) + len(e['new']) // 2]
        if len(hit) != 1:
            raise SystemExit(f'{name}: site not inside exactly one edit')
        e = hit[0]
        new = bytearray.fromhex(e['new'])
        o = site - int(e['addr'], 16)
        if bytes(new[o:o + len(want)]) != want:
            raise SystemExit(f'{name}: bytes {new[o:o + len(want)].hex()} != {want.hex()}')
        new[o:o + len(want)] = jmp(site, sy[lab], len(want))
        e['new'] = new.hex()
        e['why'] += f' [v0.14 LV art refresh: {name} site {site:#x} -> {lab}]'
    exp = stock[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    spec['edits'].append(dict(kind='0x100', addr=hex(CODE_AT), expect=exp.hex(), new=code.hex(),
                              why='v0.14 LV art refresh: ex_art / fm_pre / fm_post (stock id-111 set after an art-byte change), '
                                  'tail of the look_extras EVF claim', source='patches/lv_art_refresh'))
    spec['lv_art_refresh'] = dict(code_at=hex(CODE_AT), code_len=len(code), sites={k: hex(v[0]) for k, v in SITES.items()},
                                  symbols={k: hex(v) for k, v in sy.items() if not k.startswith(('_', '.'))},
                                  stock=dict((k, hex(v)) for k, v in SYMS.items()))
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, help='default: rewrite spec in place')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    (a.out or a.spec).write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['lv_art_refresh'], indent=1))
