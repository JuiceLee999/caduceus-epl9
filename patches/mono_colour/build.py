#!/usr/bin/env python3
"""Build the E-P7 1.1 "MONO slot renders colour" edit spec (offline; never contacts a camera).

  .venv/bin/python -I patches/mono_colour/build.py --out generated/mono_colour

Emits <out>/edits.json for tools/build_package.py / tools/merge_specs.py (merge it with a spec
that contains patches/bundles v0.2, e.g. releases/v0.3/edits.json), plus routine.s/.lst/.bin.

The patch has no data of its own: which MONO slot renders colour, and with what saturation and
hue/light, comes from the v0.2 bundle table (patches/bundles/layout.json: colour @+32,
sat[12] @+33, flags bit1 + hue/light @+0/+12), built by patches/bundles/build.py from a slot
with "render_colour": true.

Edits (all in main, component 0x100):
  0x603b02bf  or d2,d1; cmp 11,d1; bne 0x603b02f9      -> jmp sel; nop     (selector 0x603b0252)
  0x603b134e  call 0x603b11fb,[d2,d3,a2],16            -> jmp chroma      (chroma stage 0x603b132a)
  0x60353db9  mov (11308,a0),d0; cmp 12,d0; bne 0x60353de9 -> jmp fg; nop x3 (packer mono-filter merge)
  0x61378c80  section-7 FF tail -> LUTs + code
"""
import argparse, hashlib, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'patches/bundles'))
import build as BB  # noqa: E402  (patches/bundles/build.py: LUTs, offsets, job extension)

TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN, MAIN_SHA, BASE = BB.MAIN, BB.MAIN_SHA, BB.BASE

# --- hook sites (stock bytes verified below against the decoded main)
SEL, SEL_STOCK = 0x603b02bf, bytes.fromhex('f219a50bc936')          # or d2,d1; cmp 11,d1; bne 0x603b02f9
SEL_COLOR, SEL_OTHER, SEL_RESUME = 0x603b02c5, 0x603b02f9, 0x603b02de
CHROMA, CHROMA_STOCK = 0x603b134e, bytes.fromhex('cdadfee010')       # call 0x603b11fb,[d2,d3,a2],16
TONE_LOOKUP, CHROMA_RESUME = 0x603b11fb, 0x603b1353
FG, FG_STOCK = 0x60353db9, bytes.fromhex('fa002c2ca00cc92a')         # mov (11308,a0),d0; cmp 12,d0; bne
FG_MONO, FG_SKIP = 0x60353dc1, 0x60353de9
BUILDER, COLOR_TABLE, CTRL_WORD = BB.BUILDER, 0x6051de2c, 0x6051e9fc
# stock COLOR call setup this patch replays (checked byte-exact below)
SEL_COLOR_STOCK = bytes.fromhex('f8060cfad318079dfcacfce95160fcdc2cde5160cd8ffdf060')   # 0x603b02c5..0x603b02de
JOB_MODE, FILTER_IN_JOB, TONE_IN_JOB = 11308, 36 + 5528, 36 + 5529
FG_STOCK_CTX = {0x60353dcb: bytes.fromhex('fad0bc15'),      # add 5564,a0 (stock: job+5564 = params+5528)
                0x60353de5: bytes.fromhex('fa529815'),      # movbu d0,(5528,a2) (stock filter clear)
                0x60353d2e: bytes.fromhex('5e28'), 0x60353d33: bytes.fromhex('2224')}   # a2 = job + 36

# --- code space: section-7 FF tail 0x61378c68..0x61379000 (docs/CODE_SPACE_MAP.md)
CODE_AT, TAIL_LO, TAIL_HI = 0x61378c80, 0x61378c68, 0x61379000
SEC7_DESC_INDEX, SEC7_START = 6, 0x612c7000
END_GETTER, END_GETTER_TABLE, END_GETTER_SEC7 = 0x60045786, 0x60046780, 0x600457c4
GUARD = 16
COLOUR_OFF, SAT_OFF, FLAGS_OFF = BB.COLOUR_OFF, BB.SAT_OFF, 31


def fmt_words(vals):
    return '\n'.join(' .hword ' + ','.join(str(v) for v in vals[i:i + 8]) for i in range(0, len(vals), 8))


TBL_MONO_FLASH = """ asl 6,d0
 mov {bundle_table},a0
 add d0,a0"""
CH_COLOUR_FLASH = """ mov (0,sp),d0
 mov (4,sp),d1
 mov (8,sp),d2
 add 16,sp
 mov 0,a0                           /* colour slot: no grey / toning vector */
 jmp ep7_chroma_resume"""
# --sd-v3 (docs/SD_BUNDLES_V3.md): slot from the SD loader v3 accessor. MDR is kept in d2 (free here; the
# call itself preserves d2, and JOB_SLOT reloads it right after). chroma / fg hold a saved register at (0,sp),
# so the call is made 4 bytes lower (wrap=1). In sel (wrap=0) (0,sp) is the saved d0, which is dead on both
# exits (0x603b02f9 and the builder path reload d0; checked in make_spec). The chroma colour exit is folded
# into ch_keep (a0 = 0 goes through the saved slot) to pay for the two wraps: same total size.
TBL_MONO_SDV3 = """ mov mdr,d2                         /* sd v3: keep MDR */
 .if \\wrap
 add -4,sp                          /* keep (0,sp): a saved register lives there */
 .endif
 call ep7_tbl_idx,[d2,d3],8         /* a0 = slot d0 of the active table (SD-loaded or flashed) */
 .if \\wrap
 add 4,sp
 .endif
 mov d2,mdr"""
CH_COLOUR_SDV3 = """ mov 0,a0                           /* colour slot: no grey / toning vector ... */
 mov a0,(12,sp)                     /* ... restored as a0 by ch_keep */"""


def source(sd_v3=False):
    lay = json.loads((ROOT / 'patches/bundles/layout.json').read_text())
    f = lay['fields']
    if (int(lay['bundle_table'], 16), lay['slot_bytes'], f['colour'][0], f['sat'][0], f['sat'][1], f['flags'][0],
            f['hue'][0], f['light'][0], lay['slots'][4:]) != \
            (BB.BUNDLE_TABLE, 64, COLOUR_OFF, SAT_OFF, 12, FLAGS_OFF, 0, 12, ['MONO1', 'MONO2', 'MONO3', 'MONO4']):
        raise ValueError('patches/bundles/layout.json disagrees with this patch')
    ext = lay['job_extension']
    if (ext['profile'], ext['picture_mode'], ext['marker'], int(ext['marker_value'], 16)) != \
            (BB.EXT_PROFILE, BB.EXT_MODE, BB.EXT_MAGIC, BB.MAGIC):
        raise ValueError('job extension layout disagrees')
    sub = dict(bundle_table=hex(BB.BUNDLE_TABLE), ext_magic=BB.EXT_MAGIC, ext_mode=BB.EXT_MODE,
               ext_profile=BB.EXT_PROFILE, magic=hex(BB.MAGIC), colour_off=COLOUR_OFF, sat_off=SAT_OFF,
               sat_end=SAT_OFF + 12, flags_off=FLAGS_OFF, flag_hl=BB.FLAG_HL, callback=hex(BB.CALLBACK),
               rec_off=BB.RECORDS_IN_JOB - BB.REQ_IN_JOB, n_rec=BB.N_REC, stride=BB.REC_STRIDE,
               req_in_job=BB.REQ_IN_JOB, hue_off=BB.OUT_RECORDS + 18, ctrl_word=hex(CTRL_WORD),
               color_table=hex(COLOR_TABLE), job_mode=JOB_MODE, filter_in_job=FILTER_IN_JOB,
               tone_in_job=TONE_IN_JOB, hue_lut=fmt_words(BB.HUE_LUT), light_lut=fmt_words(BB.L_LUT),
               perm=BB.fmt_bytes(bytes(BB.PERM)))
    src = (Path(__file__).parent / 'mono_colour.s.in').read_text()
    src = src.replace('{tbl_mono}', TBL_MONO_SDV3 if sd_v3 else TBL_MONO_FLASH)
    src = src.replace('{ch_colour}', CH_COLOUR_SDV3 if sd_v3 else CH_COLOUR_FLASH)
    for k, v in sub.items():
        src = src.replace('{' + k + '}', str(v))
    if '{' in src or '}' in src:
        raise ValueError('unsubstituted template field')
    return src


def assemble(src, extra=None):
    syms = dict(ep7_builder=BUILDER, ep7_sel_color=SEL_COLOR, ep7_sel_other=SEL_OTHER, ep7_sel_resume=SEL_RESUME,
                ep7_tone_lookup=TONE_LOOKUP, ep7_chroma_resume=CHROMA_RESUME, ep7_fg_skip=FG_SKIP,
                ep7_fg_mono=FG_MONO, **(extra or {}))
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in syms.items()], '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        labels = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines())
                  if len(p) == 3 and p[1] in 'tT' and not p[2].startswith('.L')}
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True,
                             text=True).stdout
        return (t / 'p.bin').read_bytes(), (t / 'p.lst').read_text() + '\n' + dis, labels


def check_section7(d, code_len):
    """Section 7 loads in place up to 0x61379000; placement (+guards) is erased FF; no abs32 into the tail."""
    s, src, dst = struct.unpack_from('<3I', d, BB.SECTION_TABLE + 12 * SEC7_DESC_INDEX - BASE)
    if (s, dst) != (SEC7_START, SEC7_START) or src != SEC7_START - BASE + 0x406a0020:
        raise ValueError('section-7 descriptor differs')
    if struct.unpack_from('<I', d, END_GETTER_TABLE + 4 * 6 - BASE)[0] != END_GETTER_SEC7 or \
            d[END_GETTER_SEC7 - BASE:END_GETTER_SEC7 - BASE + 2] != b'\xfc\xcc' or \
            struct.unpack_from('<I', d, END_GETTER_SEC7 + 2 - BASE)[0] != TAIL_HI:
        raise ValueError('section-7 end constant differs')
    # the end getter indexes the jump table with (id-1)*4 at 0x60046780 (0x60045792 mov 0x60046780,a0)
    if d[END_GETTER - BASE + 12:END_GETTER - BASE + 18] != b'\xfc\xdc' + struct.pack('<I', END_GETTER_TABLE):
        raise ValueError('end getter differs')
    lo, hi = CODE_AT - GUARD, CODE_AT + code_len + GUARD
    if lo < TAIL_LO or hi > TAIL_HI:
        raise ValueError('code does not fit the section-7 tail (with guards)')
    if set(d[TAIL_LO - BASE:TAIL_HI - BASE]) != {0xff}:
        raise ValueError('section-7 tail not erased')
    import numpy as np
    a = np.frombuffer(d, np.uint8).astype(np.int64)
    w = a[:-3] | (a[1:-2] << 8) | (a[2:-1] << 16) | (a[3:] << 24)
    for alias in (0, 0x40000000):
        hits = np.nonzero((w >= TAIL_LO + alias) & (w < TAIL_HI + alias))[0]
        if len(hits):
            raise ValueError(f'abs32 reference into the section-7 tail at {hex(int(hits[0]) + BASE)}')
    return d[CODE_AT - BASE:CODE_AT - BASE + code_len]


def jmp_d32(at, target, length):
    b = b'\xdc' + struct.pack('<i', target - at)
    return b + b'\xcb' * (length - len(b))


BASE_SPEC = ROOT / 'releases/v0.3/edits.json'


def reserved():
    """Every edit span of the base spec (--base; default releases/v0.3) and the per-profile WB patch: never overlap them."""
    out = []
    v03 = json.loads(BASE_SPEC.read_text())
    for e in v03['edits']:
        a = int(e['addr'], 16)
        out.append((a, a + len(bytes.fromhex(e['new'])), e.get('source', 'v0.3')))
    out += [(lo, hi, 'wb') for lo, hi in BB.wb_reserved()]
    return out


def sdv3_accessor():
    import importlib.util
    spec = importlib.util.spec_from_file_location('ep7_sd_bundles_v3_build', ROOT / 'patches/sd_bundles_v3/build.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.accessor_symbols()


def make_spec(sd_v3=False):
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    for at, stock in [(SEL, SEL_STOCK), (CHROMA, CHROMA_STOCK), (FG, FG_STOCK), (SEL_COLOR, SEL_COLOR_STOCK),
                      *FG_STOCK_CTX.items()]:
        if d[at - BASE:at - BASE + len(stock)] != stock:
            raise ValueError(f'stock bytes differ at {at:#x}')
    src = source(sd_v3)
    acc = sdv3_accessor() if sd_v3 else {}
    code, lst, labels = assemble(src, {'ep7_tbl_idx': acc['tbl_idx']} if sd_v3 else None)
    if sd_v3:
        c0, _, _ = assemble(source())
        if len(code) > len(c0):
            raise ValueError(f'--sd-v3 grew the routine ({len(code)} > {len(c0)} B)')
        for at in (SEL_OTHER, SEL_RESUME):     # sel's saved d0 is clobbered by the accessor call: dead here
            if d[at - BASE:at - BASE + 3] != bytes.fromhex('f8023c'):
                raise ValueError(f'{at:#x} no longer reloads d0')
    tail = check_section7(d, len(code))
    edits = [
        dict(kind='0x100', addr=hex(SEL), expect=SEL_STOCK.hex(), new=jmp_d32(SEL, labels['sel'], 6).hex(),
             owner='mono_colour', why='selector 0x603b0252 mode test -> jmp sel (MONO colour slot -> COLOR builder)'),
        dict(kind='0x100', addr=hex(CHROMA), expect=CHROMA_STOCK.hex(), new=jmp_d32(CHROMA, labels['chroma'], 5).hex(),
             owner='mono_colour', why='chroma stage 0x603b132a tone lookup -> jmp chroma (colour slot: no grey/toning)'),
        dict(kind='0x100', addr=hex(FG), expect=FG_STOCK.hex(), new=jmp_d32(FG, labels['fg'], 8).hex(),
             owner='mono_colour', why='packer mono-filter merge -> jmp fg (colour slot: filter/tone = 0)'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(), owner='mono_colour',
             why=f'MONO-colour LUTs + code ({len(code)} B) in section-7 FF tail'),
    ]
    for e in edits:
        a = int(e['addr'], 16)
        n = len(bytes.fromhex(e['new']))
        for lo, hi, who in reserved():
            if a < hi and lo < a + n:
                raise ValueError(f'edit {e["addr"]} overlaps {who} {lo:#x}..{hi:#x}')
    meta = dict(code_at=hex(CODE_AT), code_len=len(code), labels={k: hex(v) for k, v in labels.items()},
                sites=dict(sel=hex(SEL), chroma=hex(CHROMA), fg=hex(FG)), requires='bundles-v0.2',
                layout=dict(colour=COLOUR_OFF, sat=SAT_OFF, flags=FLAGS_OFF, bundle_table=hex(BB.BUNDLE_TABLE)))
    if sd_v3:
        meta['sd_v3'] = dict(accessor={k: hex(v) for k, v in acc.items()}, requires='sd_bundles_v3 (accessor edit)')
    spec = dict(components=['0x100'], patch='mono_colour_sdv3' if sd_v3 else 'mono_colour', mono_colour=meta, edits=edits)
    return spec, src, lst, code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--sd-v3', action='store_true', help='read the table through the SD loader v3 accessor')
    ap.add_argument('--base', type=Path, help='spec whose edit spans must not be overlapped (default releases/v0.3)')
    a = ap.parse_args()
    if a.base:
        global BASE_SPEC
        BASE_SPEC = a.base
    try:
        spec, src, lst, code = make_spec(a.sd_v3)
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    m = spec['mono_colour']
    print(f"{len(code)} B at {CODE_AT:#x} (end {CODE_AT + len(code):#x}); sel={m['labels']['sel']} "
          f"chroma={m['labels']['chroma']} fg={m['labels']['fg']}; wrote {a.out}")


if __name__ == '__main__':
    main()
