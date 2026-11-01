#!/usr/bin/env python3
"""Build the E-P7 1.1 SD-card bundle loader edit spec (phase 1, data only; offline, no camera).

  .venv/bin/python -I patches/sd_bundles/build.py --out generated/sd_bundles

Writes <out>/edits.json (for tools/build_package.py, tools/merge_specs.py and
tools/ep7_verify_sd_bundles.py), routine.s, routine.lst, routine.bin, symbols.json, format.json.

What it does (docs/SD_BUNDLES.md):
  - 0x60863e90: rel32 of the app media manager's `call 0x6077d590,[d2],20` (reached only when the
    mount status is 0xF000 = MOUNT OK) -> sd_hook. 4-byte edit at 0x60863e91.
  - sd_hook / sd_load / sd_check / sd_crc + constants at CODE_AT in the section-6 FF tail.
    Once per power cycle it reads C:\\EP7MOD\\BUNDLES.BIN through the firmware file API and, only if
    the whole file validates, copies its 512-byte payload over the v0.2 bundle table (layout.json).
The bundle table itself (and the code that reads it) comes from patches/bundles; this spec only
replaces the table at run time. A package with this spec but without the bundles spec is refused by
tools/ep7_verify_sd_bundles.py ("requires").
The file format is defined here (FORMAT) and written by tools/ep7_bundles_bin.py.
"""
import argparse, hashlib, json, struct, subprocess, sys, tempfile, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
LAYOUT = ROOT / 'patches/bundles/layout.json'
BASE = 0x60020020

# --- hook site (static facts re-checked against the decoded main below)
SITE = 0x60863e90                                   # call 0x6077d590,[d2],20
SITE_STOCK = 'dd0097f1ff8014'
SITE_CONTEXT = (0x60863e81, 'fcca00f00000c9109ccdaef9000489')   # cmp 61440,d2; bne +; mov a3,a0; call 0x60863838; mov d2,d1
MOUNT_SET = 0x6077d590                              # app media status setter (d0 type, d1 status) -> ret [d2],20

# --- firmware services (call frames copied from stock call sites, see docs/SD_BUNDLES.md)
SERVICES = dict(ep7_malloc=0x60022782,   # call ...,[],4                 d0 size -> a0 (0 = fail)
                ep7_free=0x600227b4,     # call ...,[],4                 a0
                ep7_fopen=0x60634fbc,    # call ...,[],4                 a0 path, a1 mode -> a0 handle (0 = fail)
                ep7_fclose=0x60634fc5,   # call ...,[d2,a2,a3],16        a0 handle
                ep7_fseek=0x60635243,    # call ...,[d2,d3,a2,a3],20     a0 handle, d0 off, d1 whence (2 SET,0 CUR,1 END) -> d0 0 ok
                ep7_ftell=0x606351d9,    # call ...,[d2,a2,a3],16        a0 handle -> d0 pos (-1 fail)
                ep7_fread=0x6063514b,    # call ...,[d2,d3,a2,a3],24     a0 buf, d0 size, d1 count, a1 handle -> d0 read
                ep7_mount_set=MOUNT_SET)

# --- code space: section-6 FF tail. Stock data ends 0x612429af; aspect owns 0x61242f00..0x61242f60.
CODE_AT, CODE_END = 0x61242a00, 0x61242d00
SEC6 = (0x60ba7000, 0x41227000, 0x61243000)        # load start, flash source, load end
SEC6_DESC, SEC6_END_GETTER = 0x60027068 + 5 * 12, 0x600457bc

# --- file format v1 (little-endian)
PATH = 'C:\\EP7MOD\\BUNDLES.BIN'
MAGIC = b'EP7B'
VERSION, HDR_LEN, FW_BUILD, PAYLOAD_LEN = 1, 32, 1100, 512
FILE_LEN = HDR_LEN + PAYLOAD_LEN
BUF_SIZE = 1024
SHA_PREFIX = bytes.fromhex(MAIN_SHA[:8])           # decoded main SHA-256, first 4 bytes, as stored bytes

# Per-field value ranges (inclusive, as s8/u8 numbers) of the bundle-table ABI. Must cover every
# field of patches/bundles/layout.json; bytes no field claims must be 0. These are the ranges
# patches/bundles/build.py can emit (it rejects anything else), so every table it builds passes.
RANGES = {'hue': (-7, 7), 'light': (-7, 7), 'grain': (0, 3), 'wb_flags': (0, 1), 'wb_ab': (-7, 7),
          'wb_gm': (-7, 7), 'effect_id': (0, 3), 'effect_strength': (0, 5), 'vignette': (-5, 5),
          'flags': (0, 3), 'colour': (0, 1), 'sat': (-5, 5)}

# Other patches' claims (docs/CODE_SPACE_MAP.md) and the SD-updater code/data (docs/SD_UPDATE.md §4):
# never overlap them.
RESERVED = [(0x61242f00, 0x61242f60, 'aspect option list'), (0x60c95a00, 0x60c97300, 'SD updater client/service/validator'),
            (0x60f2cbf0, 0x60f2cd00, 'SD updater pattern table'), (0x60f2d800, 0x60f2d900, 'FIRMUP_SRV jump table'),
            (0x600fa450, 0x600fa560, 'SD updater header helpers'), (0x601e7000, 0x601e7800, 'FIRMUP LED/report'),
            (0x60613000, 0x60650000, 'file system / FILECLBK'), (0x60210900, 0x60210c80, 'bundles v0.2 (written at run time only)')]


def layout():
    lay = json.loads(LAYOUT.read_text())
    if lay['slot_bytes'] != 64 or len(lay['slots']) != 8 or int(lay['bundle_table'], 16) != 0x60210900:
        raise ValueError('layout.json: loader assumes 8 x 64-byte slots at 0x60210900')
    return lay


def range_table(lay):
    """-> (lo[64] s8, span[64] u8, per-byte field names)."""
    lo, hi, who = [0] * 64, [0] * 64, ['(unused, must be 0)'] * 64
    fields = lay['fields']
    missing = set(fields) - set(RANGES)
    if missing:
        raise ValueError(f'layout.json fields without a loader range: {sorted(missing)}')
    for name, (off, n, *_) in fields.items():
        a, b = RANGES[name]
        if not -128 <= a <= b <= 255 or (a < 0 and b > 127):
            raise ValueError(f'bad range for {name}')
        for k in range(off, off + n):
            if who[k] != '(unused, must be 0)':
                raise ValueError(f'layout.json: byte {k} claimed twice')
            lo[k], hi[k], who[k] = a, b, name
    span = [h - l for l, h in zip(lo, hi)]
    return lo, span, who


def table_ok(table, lo, span):
    """Python mirror of sd_check's range rule (used by the desktop tool and the verifier)."""
    if len(table) != PAYLOAD_LEN:
        return False
    for k, b in enumerate(table):
        v = b - 256 if b >= 128 else b
        if not 0 <= v - lo[k % 64] <= span[k % 64]:
            return False
    return True


def header(crc=0):
    return MAGIC + struct.pack('<HHII', VERSION, HDR_LEN, FW_BUILD, PAYLOAD_LEN) + struct.pack('<I', crc) + \
        SHA_PREFIX + bytes(HDR_LEN - 24)


def make_file(table):
    if len(table) != PAYLOAD_LEN:
        raise ValueError('table must be 512 bytes')
    body = header(0) + bytes(table)
    crc = zlib.crc32(body[:16] + body[20:]) & 0xffffffff
    out = header(crc) + bytes(table)
    assert len(out) == FILE_LEN
    return out


def fmt_bytes(b):
    return '\n'.join(' .byte ' + ','.join(f'0x{x & 0xff:02x}' for x in b[i:i + 16]) for i in range(0, len(b), 16))


def source(lay):
    lo, span, _ = range_table(lay)
    sub = dict(path=PATH, path_asm=PATH.replace('\\', '\\\\'), file_len=FILE_LEN, file_len_m1=FILE_LEN - 1,
               buf_size=BUF_SIZE, hdr_len=HDR_LEN, payload_len=PAYLOAD_LEN, crc_tail=FILE_LEN - 20,
               table=lay['bundle_table'], hdr_bytes=fmt_bytes(header(0)), lo_bytes=fmt_bytes(lo), span_bytes=fmt_bytes(span))
    if BUF_SIZE < FILE_LEN or BUF_SIZE > 2048:
        raise ValueError('buffer must hold the file and stay in the 2048-byte malloc class')
    src = (Path(__file__).parent / 'sd_bundles.s.in').read_text()
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
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in SERVICES.items()], '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        syms = {n: int(a, 16) for a, ty, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3) if ty in 'tT'}
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        return (t / 'p.bin').read_bytes(), (t / 'p.lst').read_text() + '\n' + dis, syms, dis


# Byte-offset hits that are NOT references (each checked by disassembly, context bytes pinned):
#   0x60e580f5 / 0x60e58155: `mov d3,d0` (8c) ; `bra +0x2c` (ca 2c) ; `mov d3,d0; mov d0,d1` (8c 81):
#   the bytes ca 2c 8c 81 read as 0x818c2cca only across instruction boundaries.
FALSE_HITS = {0x60e580f5: '0000048cca2c8c81ddbf8aeb', 0x60e58155: '0000048cca2c8c81dd5f8aeb'}


def abs32_hits(d, lo, hi):
    """Every 32-bit value at any byte offset that points into [lo,hi) via the cached (0x6), uncached
    (0xa), flash-logical (0x4) or flash-uncached (0x8) alias of section 6."""
    logical = SEC6[1] - SEC6[0]
    wins = [(lo, hi), (lo + 0x40000000, hi + 0x40000000), (lo + logical, hi + logical),
            (lo + logical + 0x40000000, hi + logical + 0x40000000)]
    out = []
    for shift in range(4):
        n = (len(d) - shift) // 4
        vals = struct.unpack_from(f'<{n}I', d, shift)
        for i, v in enumerate(vals):
            for a, b in wins:
                if a <= v < b:
                    out.append((BASE + shift + 4 * i, v))
    return sorted(out)


def check_image(d, code_len):
    s, src, dst = struct.unpack_from('<3I', d, SEC6_DESC - BASE)
    if (s, src, dst) != (SEC6[0], SEC6[1], SEC6[0]):
        raise ValueError('section-6 descriptor differs (not loaded in place)')
    if struct.unpack_from('<I', d, 0x60046780 + 5 * 4 - BASE)[0] != SEC6_END_GETTER or \
            d[SEC6_END_GETTER - BASE:SEC6_END_GETTER - BASE + 6] != b'\xfc\xcc' + struct.pack('<I', SEC6[2]):
        raise ValueError('section-6 end constant differs')
    if CODE_AT + code_len > CODE_END or CODE_END > 0x61242f00 - 16:
        raise ValueError(f'loader ({code_len} B) does not fit {CODE_AT:#x}..{CODE_END:#x} (+guard before aspect)')
    lo, hi = CODE_AT - 16, CODE_END + 16
    if set(d[0x612429b0 - BASE:hi - BASE]) != {0xff}:
        raise ValueError('placement (+guards) not erased FF')
    if d[0x612429af - BASE] == 0xff:
        raise ValueError('stock data end moved')
    o = SITE - BASE
    if d[o:o + 7].hex() != SITE_STOCK or SITE + struct.unpack_from('<i', d, o + 1)[0] != MOUNT_SET:
        raise ValueError('hook site bytes differ')
    a, ctx = SITE_CONTEXT
    if d[a - BASE:a - BASE + len(bytes.fromhex(ctx))].hex() != ctx or a + len(bytes.fromhex(ctx)) != SITE:
        raise ValueError('hook site guard (cmp 61440,d2; bne) differs')
    if d[0x6077d697 - BASE:0x6077d697 - BASE + 3].hex() != 'df8014':
        raise ValueError('0x6077d590 no longer ends in ret [d2],20 at 0x6077d697')
    hits = []
    for at, v in abs32_hits(d, lo, hi):
        ctx = FALSE_HITS.get(at)
        if ctx is None or d[at - BASE - 4:at - BASE + 8].hex() != ctx:
            hits.append((at, v))
    if hits:
        raise ValueError(f'abs32 references into the placement: {[(hex(x), hex(v)) for x, v in hits[:8]]}')


def make_spec():
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    lay = layout()
    src = source(lay)
    code, lst, syms, dis = assemble(src)
    if syms['sd_hook'] != CODE_AT:
        raise ValueError('sd_hook must be the first instruction')
    for bad in ('mul', 'div', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs'):
        if any(l.split('\t')[2:3] and l.split('\t')[2].split()[0:1] == [bad] for l in dis.splitlines() if l.count('\t') >= 2):
            raise ValueError(f'{bad} in loader code')
    check_image(d, len(code))
    tail = d[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    rel = struct.pack('<i', CODE_AT - SITE)
    edits = [dict(kind='0x100', addr=hex(SITE + 1), expect=SITE_STOCK[2:10], new=rel.hex(),
                  why=f'mount-OK status call {SITE:#x} rel32 -> sd_hook (was {MOUNT_SET:#x})'),
             dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
                  why=f'SD bundle loader ({len(code)} B) in section-6 FF tail')]
    for e in edits:
        a, n = int(e['addr'], 16), len(bytes.fromhex(e['new']))
        for lo_, hi_, who in RESERVED:
            if a < hi_ and lo_ < a + n:
                raise ValueError(f'edit {e["addr"]} overlaps {who} {lo_:#x}..{hi_:#x}')
    lo, span, who = range_table(lay)
    fmt = dict(path=PATH, magic=MAGIC.decode(), version=VERSION, header_len=HDR_LEN, fw_build=FW_BUILD,
               payload_len=PAYLOAD_LEN, file_len=FILE_LEN, sha_prefix=SHA_PREFIX.hex(),
               crc='CRC-32/IEEE (zlib.crc32) over bytes 0..15 ++ 20..end; stored LE at 16',
               header=['0 magic "EP7B"', '4 u16 version 1', '6 u16 header_len 32', '8 u32 fw_build 1100',
                       '12 u32 payload_len 512', '16 u32 crc32', '20 4 bytes decoded-main SHA-256 prefix 5dd9af16',
                       '24..31 zero', '32..543 payload = 8 x 64-byte bundle table (patches/bundles/layout.json)'],
               ranges=[dict(byte=k, field=who[k], lo=lo[k], hi=lo[k] + span[k]) for k in range(64)])
    meta = dict(code_at=hex(CODE_AT), code_end=hex(CODE_END), code_len=len(code), site=hex(SITE), mount_set=hex(MOUNT_SET),
                services={k: hex(v) for k, v in SERVICES.items()}, symbols={k: hex(v) for k, v in syms.items()},
                table=lay['bundle_table'], state=hex(syms['sd_state']), format=fmt,
                requires='bundles-v0.2 table + readers (merge with patches/bundles/build.py output)')
    spec = dict(components=['0x100'], patch='sd_bundles', sd_bundles=meta, edits=edits)
    return spec, src, lst, code, syms, fmt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    try:
        spec, src, lst, code, syms, fmt = make_spec()
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    (a.out / 'symbols.json').write_text(json.dumps({k: hex(v) for k, v in syms.items()}, indent=1) + '\n')
    (a.out / 'format.json').write_text(json.dumps(fmt, indent=1) + '\n')
    print(f'sd loader {len(code)} B at {CODE_AT:#x}..{CODE_AT + len(code):#x} (claim to {CODE_END:#x}); '
          f'hook {SITE:#x}; file {PATH} {FILE_LEN} B; wrote {a.out}')


if __name__ == '__main__':
    main()
