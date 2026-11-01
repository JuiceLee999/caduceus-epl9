#!/usr/bin/env python3
"""Build the E-P7 1.1 per-profile WB fine-tune edit spec (offline; no camera; no SD-named output).

  .venv/bin/python -I patches/wb/build.py --out generated/wb

Produces <out>/edits.json (for tools/build_package.py, tools/merge_specs.py and tools/ep7_verify_wb.py),
routine.s, routine.lst, routine.bin, symbols.json.

Design: docs/WB_AND_MONO.md Part A3, as built: docs/WB_PATCH.md.
  - wb_get stub at 0x6055e700 (section-2 FF tail, reservation 0x6055e700..0x6055e7a6).
  - 14 of the 16 `call 0x6005e971,[d2,d3],12` reads of keys 0x84F9 / 0x9679 get their rel32
    pointed at wb_get (4-byte edit per site, bytes +1..+4). The 2 RAW-development reads
    (0x60c68a45 / 0x60c68a59) stay stock: the global profile may not be the one the RAW was shot with.
  - The bundle table address and the wb_* field offsets come from patches/bundles/layout.json (the
    v0.2 ABI); nothing here hard-codes them.
The table contents are NOT part of this spec: they come from the bundles spec (patches/bundles/build.py).
Without a bundles spec merged in, the table area is erased FF. The stub treats wb_flags with bit7 set
(0xFF = erased) as "no override", so a WB-only package is stock; the spec still records the bundles
requirement ("requires") and tools/ep7_verify_wb.py refuses a package without a bundles table.
"""
import argparse, hashlib, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
LAYOUT = ROOT / 'patches/bundles/layout.json'
BASE = 0x60020020

GETTER = 0x6005e971
KEY_A, KEY_G = 0x84F9, 0x9679            # props 2127 / 2407: s8[20] per WB mode, range -7..7
KEY_WBCAT, CWB = 33057, 3                # WB category (capture+24006; 3 = CWB, no fine-tune in stock)
KEY_PMODE, KEY_PMODE6 = 38017, 40209     # picture mode; 6 re-resolved via 40209 (as capture 0x602a857e)
KEY_COLOR, KEY_MONO = 63153, 63281       # effective COLOR / MONO profile number (settings 908 / 973)

CODE_AT, CODE_END = 0x6055e700, 0x6055e7a6     # docs/CODE_SPACE_MAP.md reservation
GUARD_END = 0x6055e7b0                         # bloom starts here; gap must stay FF

# (site, stock 7 bytes, address of the `mov 0,a0` (90 00) that sets a0 for this call, key, idx, role)
SITES = [
    (0x60302c46, 'dd2bbdd5ffc00c', 0x60302c43, KEY_A, 0, 'capture: preset / cat 1'),
    (0x60302c60, 'dd11bdd5ffc00c', 0x60302c5e, KEY_G, 0, 'capture: preset / cat 1'),
    (0x60302da3, 'ddcebbd5ffc00c', 0x60302d99, KEY_A, 15, 'capture: Flash'),
    (0x60302db8, 'ddb9bbd5ffc00c', 0x60302db4, KEY_G, 15, 'capture: Flash'),
    (0x60302e35, 'dd3cbbd5ffc00c', 0x60302e32, KEY_A, 0, 'capture: one-touch'),
    (0x60302e4b, 'dd26bbd5ffc00c', 0x60302e49, KEY_G, 0, 'capture: one-touch'),
    (0x60302f23, 'dd4ebad5ffc00c', 0x60302f20, KEY_A, 0, 'capture: cat 4'),
    (0x60302f3b, 'dd36bad5ffc00c', 0x60302f2c, KEY_G, 0, 'capture: cat 4'),
    (0x60302f8f, 'dde2b9d5ffc00c', 0x60302f8b, KEY_A, 1, 'capture: Auto'),
    (0x60302fa8, 'ddc9b9d5ffc00c', 0x60302f98, KEY_G, 1, 'capture: Auto'),
    (0x6030bb5b, 'dd162ed5ffc00c', 0x6030bb58, KEY_A, 0, 'compact ring slot +97 (live-view candidate)'),
    (0x6030bb6e, 'dd032ed5ffc00c', 0x6030bb6b, KEY_G, 0, 'compact ring slot +99 (live-view candidate)'),
    (0x6030eb61, 'dd10fed4ffc00c', 0x6030eb5f, KEY_A, 0, 'params builder 0x6030e9d1 -> params+5520'),
    (0x6030eb77, 'ddfafdd4ffc00c', 0x6030eb75, KEY_G, 0, 'params builder 0x6030e9d1 -> params+5521'),
]
RAW_SITES = [(0x60c68a45, 'dd2c5f3fffc00c'), (0x60c68a59, 'dd185f3fffc00c')]   # left stock on purpose

# Other patches' claims (docs/CODE_SPACE_MAP.md): never overlap.
RESERVED = [(0x6055e5c0, 0x6055e680, 'HSL v0.1'), (0x6055e680, 0x6055e6fb, 'grain'),
            (0x6055e7b0, 0x6055e7f0, 'bloom'), (0x60210900, 0x60210c80, 'bundles v0.2'),
            (0x6035749f, 0x603574a6, 'grain'), (0x603b5249, 0x603b5250, 'grain'),
            (0x603eabd7, 0x603eabdd, 'bloom'), (0x6039fee8, 0x6039feee, 'bloom'),
            (0x60319157, 0x60319159, 'rec_limit'), (0x6031915c, 0x6031915e, 'rec_limit'),
            (0x6030df3d, 0x6030df42, 'video_log'), (0x603b02d9, 0x603b02de, 'bundles'),
            (0x603537f0, 0x603537f3, 'bundles'), (0x6035390c, 0x6035390e, 'bundles'),
            (0x603e66ab, 0x603e66b1, 'bundles'), (0x603e91f0, 0x603e91f6, 'bundles')]


def layout():
    lay = json.loads(LAYOUT.read_text())
    f = lay['fields']
    out = dict(bundle_table=int(lay['bundle_table'], 16), slot_bytes=lay['slot_bytes'], slots=lay['slots'],
               f_flags=f['wb_flags'][0], f_ab=f['wb_ab'][0], f_gm=f['wb_gm'][0])
    if out['slot_bytes'] != 64 or len(out['slots']) != 8 or out['slots'][4] != 'MONO1':
        raise ValueError('layout.json: stub assumes 8 slots x 64 B, COLOR1-4 then MONO1-4 (asl2 x3)')
    if [f['wb_flags'][1], f['wb_ab'][1], f['wb_gm'][1]] != [1, 1, 1]:
        raise ValueError('layout.json: wb fields must be single bytes')
    return out


def s16(k):
    if not 0 < k < 0x10000:
        raise ValueError(f'key {k} not 16-bit')
    return k - 0x10000 if k & 0x8000 else k


def source(lay):
    for k in (KEY_WBCAT, KEY_PMODE, KEY_PMODE6, KEY_COLOR, KEY_MONO):
        if k & 0xf != 1:      # wb_prop relies on type 1 = unsigned byte (no sign extension)
            raise ValueError(f'key {k} is not type 1 (u8)')
    sel = (KEY_A ^ KEY_G) & 0x80
    if not sel or not KEY_A & 0x80:
        raise ValueError('A/G selector bit assumption broken')
    sub = dict(key_a=s16(KEY_A), key_g=s16(KEY_G), k_wbcat=s16(KEY_WBCAT), cwb=CWB, k_pmode=s16(KEY_PMODE),
               k_pmode6=s16(KEY_PMODE6), k_color=s16(KEY_COLOR), k_mono=s16(KEY_MONO),
               bundle_table=hex(lay['bundle_table']), f_flags=lay['f_flags'], f_ab=lay['f_ab'], f_gm=lay['f_gm'],
               sel_bit=hex(sel), sel_a=hex(KEY_A & 0xff), sel_g=hex(KEY_G & 0xff))
    src = (Path(__file__).parent / 'wb_get.s.in').read_text()
    for k, v in sub.items():
        src = src.replace('{' + k + '}', str(v))
    if '{' in src or '}' in src:
        raise ValueError('unsubstituted template field')
    return src


def assemble(src):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start', f'--defsym=ep7_getter={GETTER:#x}',
                        '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        syms = {n: int(a, 16) for a, ty, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3) if ty in 'tT'}
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        return (t / 'p.bin').read_bytes(), (t / 'p.lst').read_text() + '\n' + dis, syms


def check_sites(d):
    for site, stock, a0_at, *_ in SITES + [(s, b, None) for s, b in RAW_SITES]:
        o = site - BASE
        if d[o:o + 7].hex() != stock or site + struct.unpack_from('<i', d, o + 1)[0] != GETTER:
            raise ValueError(f'site {site:#x}: stock bytes / getter target differ')
        if a0_at is not None:
            if d[a0_at - BASE:a0_at - BASE + 2] != b'\x90\x00':
                raise ValueError(f'site {site:#x}: no mov 0,a0 at {a0_at:#x}')


def make_spec():
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    lay = layout()
    src = source(lay)
    code, lst, syms = assemble(src)
    if syms['wb_get'] != CODE_AT:
        raise ValueError('wb_get must be the first instruction')
    if CODE_AT + len(code) > CODE_END:
        raise ValueError(f'stub {len(code)} B exceeds reservation {CODE_AT:#x}..{CODE_END:#x}')
    if set(d[CODE_AT - BASE:GUARD_END - BASE]) != {0xff}:
        raise ValueError('reservation + guard not erased (FF)')
    if d[CODE_AT - 4 - BASE:CODE_AT - BASE] != b'\xff' * 4:
        raise ValueError('bytes before the stub not FF')
    check_sites(d)
    tail = d[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    edits = []
    for site, stock, _, key, idx, role in SITES:
        rel = struct.pack('<i', CODE_AT - site)
        edits.append(dict(kind='0x100', addr=hex(site + 1), expect=stock[2:10], new=rel.hex(),
                          why=f'getter call {site:#x} (key {key:#x} idx {idx}) rel32 -> wb_get ({role})'))
    edits.append(dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
                      why=f'per-profile WB stub wb_get ({len(code)} B) in section-2 FF tail'))
    for e in edits:
        a = int(e['addr'], 16)
        n = len(bytes.fromhex(e['new']))
        for lo, hi, who in RESERVED:
            if a < hi and lo < a + n:
                raise ValueError(f'edit {e["addr"]} overlaps {who} {lo:#x}..{hi:#x}')
    meta = dict(code_at=hex(CODE_AT), code_len=len(code), getter=hex(GETTER),
                sites=[dict(site=hex(s), key=k, idx=i, role=r) for s, _, _, k, i, r in SITES], raw_sites_stock=[hex(s) for s, _ in RAW_SITES],
                keys=dict(a_b=KEY_A, g_m=KEY_G, wb_category=KEY_WBCAT, cwb=CWB, picture_mode=KEY_PMODE,
                          picture_mode6=KEY_PMODE6, color_profile=KEY_COLOR, mono_profile=KEY_MONO),
                layout=dict(bundle_table=hex(lay['bundle_table']), slot_bytes=lay['slot_bytes'],
                            wb_flags=lay['f_flags'], wb_ab=lay['f_ab'], wb_gm=lay['f_gm']),
                symbols={k: hex(v) for k, v in syms.items()},
                requires='bundles-v0.2 table at bundle_table (merge with patches/bundles/build.py output)')
    spec = dict(components=['0x100'], patch='wb_profile', wb=meta, edits=edits)
    return spec, src, lst, code, syms


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    try:
        spec, src, lst, code, syms = make_spec()
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    (a.out / 'symbols.json').write_text(json.dumps({k: hex(v) for k, v in syms.items()}, indent=1) + '\n')
    print(f'wb_get {len(code)} B at {CODE_AT:#x}..{CODE_AT + len(code):#x} (reservation to {CODE_END:#x}); '
          f'{len(SITES)} sites redirected, RAW sites {[hex(s) for s, _ in RAW_SITES]} stock; wrote {a.out}')


if __name__ == '__main__':
    main()
