#!/usr/bin/env python3
"""Build the E-P7 1.1 SD-card look loader v3 edit spec (offline, no camera).

  .venv/bin/python -I patches/sd_bundles_v3/build.py --out generated/sd_bundles_v3

Writes <out>/edits.json (for tools/merge_specs.py, tools/build_package.py, tools/ep7_verify_sd_bundles_v3.py),
loader.s/.lst/.bin, tbl.s/.lst/.bin, symbols.json, format.json.

Design: docs/SD_V2_CRASH.md section 3, docs/SD_BUNDLES_V3.md. Three edits:
  - 0x602c805f `call 0x602c818c,[d2,d3,a2,a3],36` -> `jmp sd_hook` (the v2 / probe hook, unchanged)
  - loader at 0x605b7400 (section-3 FF tail, the v2 placement): v2 hook + gate verbatim; state is the u16 at
    0x622cbcc2 (probe P2's store target); the file buffer is kept and published as a 16-bit pool handle
    instead of being copied over the flashed table. No store into the loaded image.
  - accessor tbl_idx / tbl_off at 0x6055e7b0 (section-2 FF tail, the retired v0.3 bloom reservation): the one
    place that turns the handle into a table address. The reader patches (bundles, wb, grain, bloom,
    mono_colour) built with --sd-v3 call it instead of using 0x60210900.
File format, path, CRC and ranges: v1/v2 (patches/sd_bundles/build.py), so tools/ep7_bundles_bin.py writes files.
"""
import argparse, hashlib, importlib.util, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V2 = _load('ep7_sd_bundles_v2_build', ROOT / 'patches/sd_bundles_v2/build.py')
V1, TC = V2.V1, V2.TC
BASE, MAIN, MAIN_SHA = V2.BASE, V2.MAIN, V2.MAIN_SHA
SITE, SITE_STOCK, SITE_RET, TRIG, EV_PRESS = V2.SITE, V2.SITE_STOCK, V2.SITE_RET, V2.TRIG, V2.EV_PRESS
CODE_AT, CODE_END = V2.CODE_AT, V2.CODE_END          # 0x605b7400..0x605b7780 (section 3)

STATE = 0x622cbcc2                   # OlyHfwEventManager 0x622cbc14 +174 (probe P2; patches/sd_probe pad_evidence)
POOL, POOL_END = 0xa1f8d800, 0xa1f98540   # class-1 pool (malloc 129..2048 B), free() range checks 0x600227c9/d1
BUF_SIZE, HDR_LEN, FILE_LEN, PAYLOAD_LEN = V1.BUF_SIZE, V1.HDR_LEN, V1.FILE_LEN, V1.PAYLOAD_LEN
LIM = POOL_END - POOL - BUF_SIZE + 1      # valid h - 1 range is 0..LIM-1  -> buffer entirely inside the pool
MAGIC = struct.unpack('<I', V1.MAGIC)[0]  # 'EP7B' = the file's first word
TABLE = 0x60210900                         # flashed bundle table (patches/bundles/layout.json)
TABLE_END = TABLE + PAYLOAD_LEN
NAMES_LO, NAMES_HI = 544, 680              # FILM_LIBRARY.md 8.3: names[8][16] at +544, u32 'EP7N' at +672
IMAGE = (0x60020020, 0x6191ffe0)           # loaded image: never stored to (cached and uncached aliases)

# accessor: section-2 FF tail. Section 2 = 0x60280800..0x6055e800 (descriptor 1, end getter 0x600457a4).
SEC2 = (0x60280800, 0x40900800, 0x6055e800)
ACC_AT, ACC_END = 0x6055e7b0, 0x6055e7f0   # WB stub ends <= 0x6055e7a6 (its guard ends 0x6055e7b0); FF to 0x6055e800

SERVICES = dict(V2.SERVICES)
RESERVED = V2.RESERVED + [(0x6055e5c0, 0x6055e680, 'HSL v0.1'), (0x6055e680, 0x6055e6fb, 'grain v0.3 placement'),
                          (0x6055e700, 0x6055e7a6, 'per-profile WB stub'), (0x605b7400, 0x605b7780, 'loader (this patch)')]


def pool_check(d):
    """free()'s class-1 range test: cmp POOL,d0; bcs; cmp POOL_END,d0; bcc (0x600227c9..0x600227d7)."""
    want = b'\xfc\xc8' + struct.pack('<I', POOL) + b'\xc4\x0e' + b'\xfc\xc8' + struct.pack('<I', POOL_END) + b'\xc6\x06'
    if d[0x600227c9 - BASE:0x600227c9 - BASE + len(want)] != want:
        raise ValueError('class-1 pool bounds in free() differ')
    # malloc(d0 <= 2048, > 128) -> class 1
    if d[0x6002278b - BASE:0x60022793 - BASE].hex() != 'fac80008c5068001':
        raise ValueError('malloc class-1 size test differs')
    if not BUF_SIZE > 128 or not BUF_SIZE <= 2048 or LIM <= 0 or LIM > 0xfffe:
        raise ValueError('buffer size / pool span assumptions broken')


def subst(text, sub):
    for k, v in sub.items():
        text = text.replace('{' + k + '}', str(v))
    if '{' in text or '}' in text:
        raise ValueError('unsubstituted template field')
    return text


def v2_part(start, end):
    s = (ROOT / 'patches/sd_bundles_v2/sd_bundles_v2.s.in').read_text()
    a, b = s.index('\n' + start), s.index('\n' + end)
    return s[a + 1:b].rstrip('\n')


def loader_source():
    lay = V1.layout()
    lo, span, _ = V1.range_table(lay)
    v2 = V2.source()                       # substituted v2 text: gate and sd_check/sd_crc are copied from it
    gate = v2[v2.index('\nsd_gate:') + 1:v2.index('\nsd_go:')].rstrip('\n')
    check = v2[v2.index('\n/* sd_check:') + 1:v2.index('\nsd_path:')].rstrip('\n')
    if not FILE_LEN <= NAMES_LO < NAMES_HI <= BUF_SIZE:
        raise ValueError('name area outside the buffer')
    sub = dict(state=hex(STATE), lim=hex(LIM), pool=hex(POOL), pool_end=hex(POOL_END), neg_pool=hex(-POOL),
               names_lo=NAMES_LO, names_hi=NAMES_HI,
               buf_size=BUF_SIZE, file_len=FILE_LEN, ev_press=hex(EV_PRESS), gate=gate, check=check,
               path_asm=V1.PATH.replace('\\', '\\\\'), hdr_bytes=V1.fmt_bytes(V1.header(0)),
               lo_bytes=V1.fmt_bytes(lo), span_bytes=V1.fmt_bytes(span))
    return subst((HERE / 'sd_bundles_v3.s.in').read_text(), sub)


def tbl_source():
    sub = dict(state=hex(STATE), lim=hex(LIM), pool=hex(POOL), magic=hex(MAGIC), hdr_len=HDR_LEN, table=hex(TABLE))
    return subst((HERE / 'tbl.s.in').read_text(), sub)


def assemble(src, at, syms):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in syms.items()], '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        out = {n: int(a, 16) for a, ty, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3) if ty in 'tT'}
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        return (t / 'p.bin').read_bytes(), (t / 'p.lst').read_text() + '\n' + dis, out, dis


def accessor():
    """-> (code bytes, symbols). Used by the reader builds (--sd-v3) for the call targets."""
    code, lst, syms, dis = assemble(tbl_source(), ACC_AT, {})
    if syms['tbl_idx'] != ACC_AT or ACC_AT + len(code) > ACC_END:
        raise ValueError(f'accessor layout: tbl_idx {syms["tbl_idx"]:#x}, {len(code)} B > {ACC_END - ACC_AT}')
    return code, dict(tbl_idx=syms['tbl_idx'], tbl_off=syms['tbl_off']), lst, dis


def accessor_symbols():
    return accessor()[1]


def check_accessor_place(d, n):
    s, src, dst = struct.unpack_from('<3I', d, 0x60027068 + 12 - BASE)
    if (s, src, dst) != (SEC2[0], SEC2[1], SEC2[0]):
        raise ValueError('section-2 descriptor differs')
    stub = struct.unpack_from('<I', d, 0x60046780 + 4 - BASE)[0]
    if d[stub - BASE:stub - BASE + 6] != b'\xfc\xcc' + struct.pack('<I', SEC2[2]):
        raise ValueError('section-2 end constant differs')
    if set(d[0x6055e700 - BASE:SEC2[2] - BASE]) != {0xff}:
        raise ValueError('section-2 tail 0x6055e700..0x6055e800 not erased FF')
    if ACC_AT + n > ACC_END or ACC_END + 16 > SEC2[2]:
        raise ValueError('accessor does not fit')
    # no abs32 word (any alias, any byte offset) points into the accessor claim
    import numpy as np
    a = np.frombuffer(d, np.uint8).astype(np.int64)
    w = a[:-3] | (a[1:-2] << 8) | (a[2:-1] << 16) | (a[3:] << 24)
    logical = SEC2[1] - SEC2[0]
    for off in (0, 0x40000000, logical, logical + 0x40000000):
        hits = np.nonzero((w >= ACC_AT - 16 + off) & (w < SEC2[2] + off))[0]
        if len(hits):
            raise ValueError(f'abs32 reference into the accessor claim at {hex(int(hits[0]) + BASE)}')


def disasm(code, at, stop=None):
    """objdump of raw bytes at CPU address `at` (code only: stop before data) -> [(addr, op, args)]."""
    import re
    with tempfile.NamedTemporaryFile(suffix='.bin') as tf:
        tf.write(code)
        tf.flush()
        out = subprocess.run([TC / 'mn10300-elf-objdump', '-b', 'binary', '-m', 'am33-2', '-D', f'--adjust-vma={at:#x}',
                              f'--stop-address={(stop or at + len(code)):#x}', tf.name],
                             capture_output=True, text=True, check=True).stdout
    return [(int(m.group(1), 16), m.group(2), m.group(3).strip())
            for m in re.finditer(r'^\s*([0-9a-f]+):\t[0-9a-f ]+\t(\S+)[ \t]*(.*)$', out, re.M)]


def store_audit(ins):
    """Every store instruction -> [(addr, text, kind, target)]. kind: 'sp' (stack-relative / movm push),
    'abs' (absolute address, target given), 'ind' (other register-indirect)."""
    import re
    out = []
    for a, op, args in ins:
        if op == 'movm' and args.endswith('(sp)'):
            out.append((a, f'{op} {args}', 'sp', None))
            continue
        m = re.fullmatch(r'([da]\d|sp|mdr|r\d+|[xe]?r\d+)\s*,\s*(\(.*\))', args)
        if op not in ('mov', 'movbu', 'movhu') or not m:
            continue
        tgt = m.group(2)
        ab = re.fullmatch(r'\(0x([0-9a-f]+)\)', tgt)
        if ab:
            out.append((a, f'{op} {args}', 'abs', int(ab.group(1), 16)))
        elif re.fullmatch(r'\((-?\d+,)?sp\)', tgt):
            out.append((a, f'{op} {args}', 'sp', None))
        else:
            out.append((a, f'{op} {args}', 'ind', None))
    return out


def in_image(addr):
    a = addr - 0x40000000 if 0xa0000000 <= addr < 0xc0000000 else addr
    return IMAGE[0] <= a < IMAGE[1]


def make_spec():
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    pool_check(d)
    pad = _load('ep7_sd_probe_build', ROOT / 'patches/sd_probe/build.py').pad_evidence(d)
    if not pad['ok']:
        raise ValueError(f'0x622cbcc2 evidence failed: {pad}')
    acc, acc_syms, acc_lst, acc_dis = accessor()
    check_accessor_place(d, len(acc))
    src = loader_source()
    code, lst, syms, dis = assemble(src, CODE_AT, SERVICES)
    if syms['sd_hook'] != CODE_AT:
        raise ValueError('sd_hook must be the first instruction')
    for bad in ('mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'retf'):
        for listing in (dis, acc_dis):
            if any(l.split('\t')[2:3] and l.split('\t')[2].split()[0:1] == [bad] for l in listing.splitlines() if l.count('\t') >= 2):
                raise ValueError(f'{bad} in new code')
    V2.check_image(d, len(code))           # section-3 placement, load order, site, guards, abs32 refs, guard words
    # stores: loader = only the two state stores (abs) + stack; accessor = none
    st = store_audit(disasm(code, CODE_AT, syms['sd_path']))
    abs_t = [t for _, _, k, t in st if k == 'abs']
    ind = [x for x in st if x[2] == 'ind']
    # the single indirect store is the name-area clear: movbu d0,(d2,a2) with a2 = buf (pool-checked) and
    # d2 in NAMES_LO..NAMES_HI-1 (loop bounds checked by the emulator suite)
    if [x[1] for x in ind] != ['movbu d0,(d2,a2)'] or ind[0][0] < syms['sd_z'] or ind[0][0] > syms['sd_z'] + 2 or \
            [k for _, _, k, _ in st if k not in ('sp', 'abs', 'ind')] or abs_t != [STATE, STATE]:
        raise ValueError(f'loader stores: {st}')
    if store_audit(disasm(acc, ACC_AT)):
        raise ValueError('accessor stores')
    if any(in_image(t) for t in abs_t):
        raise ValueError('store into the loaded image')
    # the gate is v2's, byte for byte apart from branch displacements; hook head == v2
    vcode, _, vsyms, _ = V2.assemble(V2.source())
    g = code[syms['sd_gate'] - CODE_AT:syms['sd_go'] - CODE_AT]
    vg = vcode[vsyms['sd_gate'] - CODE_AT:vsyms['sd_go'] - CODE_AT]
    if len(g) != len(vg) or any(g[i] != vg[i] and g[i - 1] not in (0xc8, 0xc9) for i in range(len(g))):
        raise ValueError('gate differs from v2')
    tail = d[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    acc_tail = d[ACC_AT - BASE:ACC_AT - BASE + len(acc)]
    rel = struct.pack('<i', CODE_AT - SITE)
    edits = [dict(kind='0x100', addr=hex(SITE), expect=SITE_STOCK, new='dc' + rel.hex(),
                  why=f'appevent TRIG tracker call {SITE:#x} (call {TRIG:#x},[d2,d3,a2,a3],36) -> jmp sd_hook (as v2)'),
             dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
                  why=f'SD look loader v3 ({len(code)} B) in section-3 FF tail; state u16 at {STATE:#x}, no image stores'),
             dict(kind='0x100', addr=hex(ACC_AT), expect=acc_tail.hex(), new=acc.hex(),
                  why=f'bundle-table accessor tbl_idx/tbl_off ({len(acc)} B) in section-2 FF tail (loaded table or {TABLE:#x})')]
    for e in edits:
        a, n = int(e['addr'], 16), len(bytes.fromhex(e['new']))
        for lo_, hi_, who in RESERVED:
            if who == 'loader (this patch)' and a == CODE_AT:
                continue
            if a < hi_ and lo_ < a + n:
                raise ValueError(f'edit {e["addr"]} overlaps {who} {lo_:#x}..{hi_:#x}')
    lo, span, who = V1.range_table(V1.layout())
    fmt = dict(path=V1.PATH, same_as='patches/sd_bundles/build.py (v1 format, unchanged)', file_len=FILE_LEN,
               ranges=[dict(byte=k, field=who[k], lo=lo[k], hi=lo[k] + span[k]) for k in range(64)])
    meta = dict(code_at=hex(CODE_AT), code_end=hex(CODE_END), code_len=len(code), site=hex(SITE), site_ret=hex(SITE_RET),
                trig=hex(TRIG), ev_press=hex(EV_PRESS), state=hex(STATE), state_values=dict(none=0, attempted=0xffff, handle=f'1..{LIM:#x}'),
                pool=hex(POOL), pool_end=hex(POOL_END), lim=hex(LIM), magic=hex(MAGIC), hdr_len=HDR_LEN, buf_size=BUF_SIZE,
                table=hex(TABLE), acc_at=hex(ACC_AT), acc_end=hex(ACC_END), acc_len=len(acc), accessor={k: hex(v) for k, v in acc_syms.items()},
                services={k: hex(v) for k, v in SERVICES.items()}, symbols={k: hex(v) for k, v in syms.items()},
                format=fmt, pad_evidence=dict(ok=pad['ok'], vtable_slots=pad['vtable_slots'], getter_calls=pad['getter_calls']),
                requires='bundles table + readers built with --sd-v3 (they call the accessor)',
                conflicts='sd_bundles (v1), sd_bundles_v2, sd_probe (same hook site / placement)')
    spec = dict(components=['0x100'], patch='sd_bundles_v3', sd_bundles_v3=meta, edits=edits)
    return spec, dict(loader=(src, lst, code), tbl=(tbl_source(), acc_lst, acc)), syms, fmt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    try:
        spec, parts, syms, fmt = make_spec()
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    for name, (src, lst, code) in parts.items():
        (a.out / f'{name}.s').write_text(src)
        (a.out / f'{name}.lst').write_text(lst)
        (a.out / f'{name}.bin').write_bytes(code)
    (a.out / 'symbols.json').write_text(json.dumps({k: hex(v) for k, v in syms.items()}, indent=1) + '\n')
    (a.out / 'format.json').write_text(json.dumps(fmt, indent=1) + '\n')
    m = spec['sd_bundles_v3']
    print(f"sd loader v3 {m['code_len']} B at {CODE_AT:#x}; accessor {m['acc_len']} B at {ACC_AT:#x} "
          f"(tbl_idx {m['accessor']['tbl_idx']}, tbl_off {m['accessor']['tbl_off']}); state {STATE:#x}; "
          f"pool {POOL:#x}..{POOL_END:#x} lim {LIM:#x}; wrote {a.out}")


if __name__ == '__main__':
    main()
