#!/usr/bin/env python3
"""Build the E-P7 1.1 SD-card look loader v2 edit spec (offline, no camera).

  .venv/bin/python -I patches/sd_bundles_v2/build.py --out generated/sd_bundles_v2

Writes <out>/edits.json (for tools/build_package.py, tools/merge_specs.py and
tools/ep7_verify_sd_bundles_v2.py), routine.s, routine.lst, routine.bin, symbols.json, format.json.

v2 replaces v1 (patches/sd_bundles, dead hook 0x60863e90; REVIEW_v04 H1-new/H2-new). Design and proofs:
docs/SD_BUNDLES_V2.md. In short:
  - hook: 0x602c805f `call 0x602c818c,[d2,d3,a2,a3],36` (5 B, appevent release-notice tracker inside the
    appevent get 0x602c7f5a, executed by the HLS_EVENT task) -> `jmp sd_hook`; sd_hook replays the call and
    jumps back to 0x602c8064. Nothing new runs unless an event with low16 0x100/0x101 (shutter) arrives.
  - loader: section-3 FF tail (section 3 is copied before section 5/6 code, which is the only code that can
    reach the hook). It acts once per power-on, on the first canonical TRIG1-press event (0x02000100), and
    only when all 9 sections are loaded, the caller is HLS_EVENT, and a medium reports MOUNT OK.
  - file format, path, CRC and per-byte ranges: identical to v1 (imported from patches/sd_bundles/build.py),
    so tools/ep7_bundles_bin.py writes files for both.
"""
import argparse, hashlib, importlib.util, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V1 = _load('ep7_sd_bundles_build', ROOT / 'patches/sd_bundles/build.py')   # file format, ranges, helpers
TC = V1.TC
MAIN, MAIN_SHA, BASE = V1.MAIN, V1.MAIN_SHA, V1.BASE

# --- hook site (re-checked against the decoded main below)
SITE = 0x602c805f                    # call 0x602c818c,[d2,d3,a2,a3],36   (call16, 5 bytes)
SITE_STOCK = 'cd2d01f024'
SITE_RET = 0x602c8064                # stock continuation: mov (16,sp),d0
TRIG = 0x602c818c                    # api_event_check_release_notice (a0 = event pointer)
GET_FN = 0x602c7f5a                  # appevent get (frame [d2,d3,a2,a3],88), sole caller 0x60770224
# Pinned context: 0x602c8045..0x602c8064 (the low16 0x100/0x101 gate, a0 = (12,sp), the call, reload)
SITE_CONTEXT = (0x602c8045, '5810fae0fffffac80001c80e5810fae0fffffac80101c9095c0ccd2d01f0245810')
EV_PRESS = 0x02000100                # canonical TRIG1 pressed (bset 1 in 0x61f9f1c8)

# --- runtime guards (all [V] addresses, see docs/SD_BUNDLES_V2.md)
SECBITS = 0xa272e420                 # bit n-1 set by 0x600457e7 after section n is copied
HLS_TID = 0x622cbcc0                 # event manager 0x622cbc14 +172: HLS_EVENT tid (init -1 at 0x6076fa6a)
GET_TID = 0x600317ac                 # a0 = &u16 out -> d0 0 ok / -25 not a task (used by fileif 0x60643765)
MEDIA_STATUS = (0x61fa8fb8, 0x61fa8fc0, 0x61fa8fc8, 0x61fa8fd0)   # 0x6077d590 per-medium status words

SERVICES = dict({k: v for k, v in V1.SERVICES.items() if k != 'ep7_mount_set'},
                ep7_trig=TRIG, ep7_trig_ret=SITE_RET, ep7_get_tid=GET_TID, ep7_secbits=SECBITS,
                ep7_hls_tid=HLS_TID, ep7_ms_a=MEDIA_STATUS[0], ep7_ms_b=MEDIA_STATUS[1],
                ep7_ms_c=MEDIA_STATUS[2], ep7_ms_d=MEDIA_STATUS[3])
CALL_FRAMES = dict(ep7_get_tid=(0x20, 4))   # in addition to V1's file services

# --- code space: section-3 FF tail 0x605b7180..0x605b7800 (stock data ends 0x605b717f)
SEC3 = (0x6057b200, 0x40bfb200, 0x605b7800)        # load start, flash source, load end
SEC3_DESC, SEC3_END_STUB = 0x60027068 + 2 * 12, None
CODE_AT, CODE_END = 0x605b7400, 0x605b7780          # guards 0x605b73f0..400 and 0x605b7780..800 stay FF

# Byte-offset abs32 hits into the claim that are NOT references (checked by disassembly; context pinned):
#   0x601262cb / 0x601273c9: `mov d3,mdr` (f2 fe) ; `divu d1,d2` (f2 76) ; `mov (96,sp),d3` (5b 60)
#   -> bytes f2 76 5b 60 read as 0x605b76f2 only across instruction boundaries.
FALSE_HITS = {0x601262cb: '600cf2fef2765b60f292f2ae', 0x601273c9: '600cf2fef2765b60f292f2ae'}

RESERVED = V1.RESERVED + [
    (0x605b7190, 0x605b73f0, 'provisional ORF/wifi placements (HSL_PORT.md) - keep clear'),
    (0x60863e90, 0x60863e97, 'v1 dead hook site (v1 and v2 are mutually exclusive)'),
    (0x61242a00, 0x61242d00, 'v1 loader placement')]


def source():
    lay = V1.layout()
    lo, span, _ = V1.range_table(lay)
    sub = dict(path=V1.PATH, path_asm=V1.PATH.replace('\\', '\\\\'), file_len=V1.FILE_LEN, buf_size=V1.BUF_SIZE,
               hdr_len=V1.HDR_LEN, payload_len=V1.PAYLOAD_LEN, crc_tail=V1.FILE_LEN - 20, table=lay['bundle_table'],
               hdr_bytes=V1.fmt_bytes(V1.header(0)), lo_bytes=V1.fmt_bytes(lo), span_bytes=V1.fmt_bytes(span),
               ev_press=hex(EV_PRESS))
    src = (Path(__file__).parent / 'sd_bundles_v2.s.in').read_text()
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


def abs32_hits(d, lo, hi):
    """32-bit values at any byte offset pointing into [lo,hi) via the cached, uncached, flash-logical
    or flash-uncached alias of section 3."""
    logical = SEC3[1] - SEC3[0]
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
    # section 3 loads in place, ends at 0x605b7800 (descriptor table + end-getter jump table)
    s, src, dst = struct.unpack_from('<3I', d, SEC3_DESC - BASE)
    if (s, src, dst) != (SEC3[0], SEC3[1], SEC3[0]):
        raise ValueError('section-3 descriptor differs (not loaded in place)')
    stub = struct.unpack_from('<I', d, 0x60046780 + 2 * 4 - BASE)[0]
    if d[stub - BASE:stub - BASE + 6] != b'\xfc\xcc' + struct.pack('<I', SEC3[2]):
        raise ValueError('section-3 end constant differs')
    # load order: 1,7,2,3,4,5,6,8,9 in one function (0x60044f2d .. 0x600451d0); 3 is copied before 5
    order = [(0x60044f2b, 1), (0x60044f64, 7), (0x60045005, 2), (0x600450d5, 3), (0x600450f8, 4),
             (0x60045141, 5), (0x60045164, 6), (0x600451aa, 8), (0x600451ce, 9)]
    for a, n in order:
        o = a - BASE
        tgt = a + 2 + struct.unpack_from('<h', d, o + 3)[0]
        if d[o:o + 2] != bytes([0x80, n]) or d[o + 2] != 0xcd or tgt != 0x600457e7:
            raise ValueError(f'section load call for {n} at {a:#x} differs')
    if CODE_AT + code_len > CODE_END:
        raise ValueError(f'loader ({code_len} B) does not fit {CODE_AT:#x}..{CODE_END:#x}')
    if set(d[CODE_AT - 16 - BASE:SEC3[2] - BASE]) != {0xff} or d[0x605b717f - BASE] == 0xff:
        raise ValueError('placement (+guards) not erased FF, or stock data end moved')
    o = SITE - BASE
    if d[o:o + 5].hex() != SITE_STOCK or SITE + struct.unpack_from('<h', d, o + 1)[0] != TRIG:
        raise ValueError('hook site bytes differ')
    a, ctx = SITE_CONTEXT
    if d[a - BASE:a - BASE + len(bytes.fromhex(ctx))].hex() != ctx:
        raise ValueError('hook site context differs')
    # nothing branches into the middle of the 5 replaced bytes
    XR = _load('ep7_xref', ROOT / 'tools/ep7_xref.py')
    import numpy as np
    inner = XR.scan(np.frombuffer(d, dtype=np.uint8), list(range(SITE + 1, SITE + 5)), short=True)
    if any(inner.values()):
        raise ValueError(f'branch into the hook span: {inner}')
    hits = [(at, v) for at, v in abs32_hits(d, CODE_AT - 16, SEC3[2])
            if not (at in FALSE_HITS and d[at - BASE - 4:at - BASE + 8].hex() == FALSE_HITS[at])]
    if hits:
        raise ValueError(f'abs32 references into the placement: {[(hex(x), hex(v)) for x, v in hits[:8]]}')
    # the guard words the loader reads are what the doc says they are
    if d[0x6004585b - BASE:0x60045869 - BASE].hex() != 'fca520e472a2f214fc8120e472a2':
        raise ValueError('section bit store at 0x6004585b differs')
    if d[0x6076fd57 - BASE:0x6076fd5b - BASE].hex() != 'fad2ac00' or d[0x6076fd95 - BASE:0x6076fd97 - BASE].hex() != 'f072':
        raise ValueError('HLS_EVENT tid store (mgr+172) differs')
    if d[0x6076fc20 - BASE:0x6076fc26 - BASE] != b'\xfc\xdc' + struct.pack('<I', 0x622cbc14):
        raise ValueError('event manager singleton address differs')
    if d[GET_TID - BASE:GET_TID - BASE + 3].hex() != '305080':
        raise ValueError('get_tid entry differs')
    for w, addr in zip(MEDIA_STATUS, (0x6077d5bb, 0x6077d5b3, 0x6077d5ab, 0x6077d5a3)):
        if d[addr - BASE:addr - BASE + 6] != b'\xfc\x85' + struct.pack('<I', w):
            raise ValueError(f'media status store {w:#x} differs')


def make_spec():
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    src = source()
    code, lst, syms, dis = assemble(src)
    if syms['sd_hook'] != CODE_AT:
        raise ValueError('sd_hook must be the first instruction')
    for bad in ('mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'retf'):
        if any(l.split('\t')[2:3] and l.split('\t')[2].split()[0:1] == [bad] for l in dis.splitlines() if l.count('\t') >= 2):
            raise ValueError(f'{bad} in loader code')
    check_image(d, len(code))
    tail = d[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    rel = struct.pack('<i', CODE_AT - SITE)
    edits = [dict(kind='0x100', addr=hex(SITE), expect=SITE_STOCK, new='dc' + rel.hex(),
                  why=f'appevent TRIG tracker call {SITE:#x} (call {TRIG:#x},[d2,d3,a2,a3],36) -> jmp sd_hook'),
             dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
                  why=f'SD look loader v2 ({len(code)} B) in section-3 FF tail')]
    for e in edits:
        a, n = int(e['addr'], 16), len(bytes.fromhex(e['new']))
        for lo_, hi_, who in RESERVED:
            if a < hi_ and lo_ < a + n:
                raise ValueError(f'edit {e["addr"]} overlaps {who} {lo_:#x}..{hi_:#x}')
    lo, span, who = V1.range_table(V1.layout())
    fmt = dict(path=V1.PATH, same_as='patches/sd_bundles/build.py (v1 format, unchanged)', file_len=V1.FILE_LEN,
               ranges=[dict(byte=k, field=who[k], lo=lo[k], hi=lo[k] + span[k]) for k in range(64)])
    meta = dict(code_at=hex(CODE_AT), code_end=hex(CODE_END), code_len=len(code), site=hex(SITE), site_ret=hex(SITE_RET),
                trig=hex(TRIG), get_fn=hex(GET_FN), ev_press=hex(EV_PRESS), secbits=hex(SECBITS), hls_tid=hex(HLS_TID),
                get_tid=hex(GET_TID), media_status=[hex(x) for x in MEDIA_STATUS],
                services={k: hex(v) for k, v in SERVICES.items()}, symbols={k: hex(v) for k, v in syms.items()},
                table=V1.layout()['bundle_table'], state=hex(syms['sd_state']), format=fmt,
                requires='bundles-v0.2 table + readers (patches/bundles/build.py output)',
                conflicts='sd_bundles (v1)')
    spec = dict(components=['0x100'], patch='sd_bundles_v2', sd_bundles_v2=meta, edits=edits)
    return spec, src, lst, code, syms, fmt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    try:
        spec, src, lst, code, syms, fmt = make_spec()
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    (a.out / 'symbols.json').write_text(json.dumps({k: hex(v) for k, v in syms.items()}, indent=1) + '\n')
    (a.out / 'format.json').write_text(json.dumps(fmt, indent=1) + '\n')
    print(f'sd loader v2 {len(code)} B at {CODE_AT:#x}..{CODE_AT + len(code):#x} (claim to {CODE_END:#x}); '
          f'hook {SITE:#x} -> jmp; file {V1.PATH} {V1.FILE_LEN} B; wrote {a.out}')


if __name__ == '__main__':
    main()
