#!/usr/bin/env python3
"""Emulator verification of a BUILT SD-card bundle loader package (offline; emulator only; no camera).

Takes an edits spec that contains the sd_bundles patch (patches/sd_bundles/build.py), e.g. a
tools/merge_specs.py result with the v0.2 bundles table. Builds the package in memory with
tools/build_package.build(), decodes the patched and the restore (= stock) main payloads, and runs
code from THOSE payloads (fishcu penf_emulator, strict: only the regions below exist):

  site      0x60863e80..0x60863ea0 (the mount-OK `call 0x6077d590,[d2],20`; patched rel32 -> sd_hook)
  loader    0x61242a00..0x61242d00 (rwx; sd_state lives at its end)
  mount_set 0x6077d590..0x6077d6a0 REAL stock code (status word store + "MOUNT OK" log call)
  table     0x60210800..0x60211000 (the flashed v0.2 table at 0x60210900 and its neighbours)
Run from pc = site with d0 = media type, d1 = d2 = 0xF000, stopped at site+7; the same fixture
runs on the stock payload (site -> 0x6077d590 directly) as the reference.

Stubs (our own MN103 code, assembled here with gas): 5-byte `jmp` trampolines at the REAL service
entries (malloc 0x60022782, free 0x600227b4, fopen 0x60634fbc, fclose 0x60634fc5, fread 0x6063514b,
ftell 0x606351d9, fseek 0x60635243, and the logger 0x60767ee5 that 0x6077d590 calls) jump to bodies
that serve an in-memory file and log every call (id, d0, d1, a0, a1, sp, return address, caller's
(4/8/12,sp), mdr). Each body returns with the stock frame of its call sites (`ret [regs],F`), keeps
d2/d3/a2/a3, and is hostile like a real callee: it clobbers d0/d1/a0/a1 (except the result), mdr and
the caller's argument spill words (4,sp)/(8,sp). fseek/ftell/fread keep a real file position
(whence 2 SET / 0 CUR / 1 END). A self-test checks the fread stub alone first.

  S  static: site rel32 -> sd_hook, rest of the site stock; loader bytes == spec; FF to 0x61242d00;
     the loader's service call frames == the dominant frame at stock call sites of that service.
  V  valid files (tools/ep7_bundles_bin.py build(): bundles/mono_colour_example.json, example.json;
     plus all-lo / all-hi boundary tables): table == payload exactly, nothing else in 0x60210800..
     0x60211000 changes; call sequence malloc(1024) fopen(path,"r") fseek(h,0,END) ftell(h)
     fseek(h,0,SET) fread(buf,1,544,h) fclose(h) free(buf); media types 1/4/8/32/0.
  R  rejects: magic, version, header length, build, payload length, CRC (value, byte order,
     payload bit flip), SHA prefix, reserved bytes, every one of the 64 slot bytes at lo-1 and hi+1
     (header/range cases carry a CORRECT CRC so only the intended check can reject), file size
     0/543/545/1024, short reads, ftell -1, fseek END/SET errors, missing file, fopen error, malloc
     failure: table byte-identical; file closed exactly once on every path that opened it, and no
     file call after fclose; buffer freed iff allocated; desktop check_file() agrees.
  C  every run: registers d0-d3, a0-a3, sp, pc, mdr, psw, lir, lar at site+7 == stock run; stack
     from the site frame (sp-20) up == stock; mount_set status memory and its log call (d0, string,
     args, return address, sp) == stock; heap outside the 1024-byte buffer untouched; loader region
     changes only at sd_state; service return addresses inside the loader; peak stack depth reported.
  L  load-once: valid -> sd_state 0, a second mount does nothing; no file / fopen error / malloc fail
     -> sd_state stays 0xFF and the next mount loads; a rejected (opened) file -> sd_state 0, never
     re-read; entry with d1 != 0xF000 -> stock.
  M  mutations of the patched loader (CRC compare flipped / removed, length checks, range check,
     header check, sd_state store, error-path fclose, a0/a1 restore, d0/d1 restore, table address):
     each must make the core suite fail.

Usage: tools/ep7_verify_sd_bundles.py SPEC.json [--json out.json] [--no-mutations]
"""
import argparse, importlib.util, json, struct, subprocess, sys, tempfile, zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


SB = _load('ep7_sd_bundles_build', ROOT / 'patches/sd_bundles/build.py')
BIN = _load('ep7_bundles_bin', ROOT / 'tools/ep7_bundles_bin.py')

TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE = 0x60020020
STACK, SP0, STACK_FILL = 0x18010000, 0x18011800, 0xa5
CTL, LOG, LOG_N, LOG_SZ = 0x1c000000, 0x1c000100, 64, 48
FILE_AT = 0x1c100000
HEAP, HEAP_LEN, HEAP_FILL = 0x1c200000, 0x1000, 0xcc
BUF = HEAP + 0x400                                   # malloc result (1024 B), guards around
STUBS = 0x1c300000
CALLER = 0x18000000
TAB_LO, TAB_HI = 0x60210800, 0x60211000
MS_LO, MS_HI = 0x6077d590, 0x6077d6a0
MD_LO, MD_HI = 0x61fa8f00, 0x61fa9100                # 0x6077d590 data: status words, 0x61fa9024, 0x61fa9028[5]
LOGGER = 0x60767ee5                                  # called by 0x6077d590 with [d2,a2],12
ALL_REGS = ['d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'pc', 'mdr', 'psw', 'lir', 'lar']
INIT = dict(d3=0x33333333, a0=0xa0a0a0a0, a1=0xa1a1a1a1, a2=0xa2a2a2a2, a3=0xa3a3a3a3, mdr=0x3d3d3d3d)
# control block offsets
C_LOGP, C_MALLOC, C_FOPEN, C_SIZE, C_POS, C_SEEK_END, C_SEEK_SET, C_TELL_FAIL, C_READMAX, C_FILE = range(0, 40, 4)
IDS = {1: 'malloc', 2: 'free', 3: 'fopen', 4: 'fclose', 5: 'fseek', 6: 'ftell', 7: 'fread', 8: 'log'}
FILE_OPS = ('fseek', 'ftell', 'fread', 'fclose')
HANDLE = 0x1c0f0000

STUB_SRC = r"""
 .am33_2
 .text
 .set CTL, 0x1c000000
.macro ENTER id, F
 movm [d2,d3,a2,a3],(sp)
 mov (CTL),a3
 mov \id,d2
 mov d2,(0,a3)
 mov d0,(4,a3)
 mov d1,(8,a3)
 mov a0,(12,a3)
 mov a1,(16,a3)
 mov sp,a2
 add 16,a2
 mov a2,(20,a3)
 mov (\F,a2),d2
 mov d2,(24,a3)
 mov (\F+4,a2),d2
 mov d2,(28,a3)
 mov (\F+8,a2),d2
 mov d2,(32,a3)
 mov (\F+12,a2),d2
 mov d2,(36,a3)
 mov mdr,d2
 mov d2,(40,a3)
 add 48,a3
 mov a3,(CTL)
.endm
.macro LEAVE F, clob
 .if \clob
 mov 0x5a5a5a5a,d2
 mov d2,(16+\F+4,sp)
 mov d2,(16+\F+8,sp)
 mov d2,mdr
 .endif
 movm (sp),[d2,d3,a2,a3]
.endm
 .global _start
_start:
s_malloc:
 ENTER 1,4
 mov (CTL+4),a0
 mov 0xbad0d000,d0
 mov 0xbad0d100,d1
 mov 0xbad0a100,a1
 LEAVE 4,1
 ret [],4
s_free:
 ENTER 2,4
 mov 0xbad0d000,d0
 mov 0xbad0d100,d1
 mov 0xbad0a000,a0
 mov 0xbad0a100,a1
 LEAVE 4,1
 ret [],4
s_fopen:
 ENTER 3,4
 clr d2
 mov d2,(CTL+16)
 mov (CTL+8),a0
 mov 0xbad0d000,d0
 mov 0xbad0d100,d1
 mov 0xbad0a100,a1
 LEAVE 4,1
 ret [],4
s_fclose:
 ENTER 4,16
 clr d0
 mov 0xbad0d100,d1
 mov 0xbad0a000,a0
 mov 0xbad0a100,a1
 LEAVE 16,1
 ret [d2,a2,a3],16
s_fseek:
 ENTER 5,20
 cmp 1,d1
 bne 1f
 mov (CTL+12),d2
 add d0,d2
 mov d2,(CTL+16)
 mov (CTL+20),d0
 bra 9f
1:
 cmp 2,d1
 bne 2f
 mov d0,(CTL+16)
 mov (CTL+24),d0
 bra 9f
2:
 cmp 0,d1
 bne 3f
 mov (CTL+16),d2
 add d0,d2
 mov d2,(CTL+16)
 clr d0
 bra 9f
3:
 mov -1,d0
9:
 mov 0xbad0d100,d1
 mov 0xbad0a000,a0
 mov 0xbad0a100,a1
 LEAVE 20,1
 ret [d2,d3,a2,a3],20
s_ftell:
 ENTER 6,16
 mov (CTL+28),d2
 cmp 0,d2
 beq 1f
 mov -1,d0
 bra 9f
1:
 mov (CTL+16),d0
9:
 mov 0xbad0d100,d1
 mov 0xbad0a000,a0
 mov 0xbad0a100,a1
 LEAVE 16,1
 ret [d2,a2,a3],16
s_fread:
 ENTER 7,24
 cmp 1,d0
 beq 1f
 clr d0
 bra 9f
1:
 mov (CTL+12),d2
 mov (CTL+16),d3
 sub d3,d2
 cmp 0,d2
 bge 2f
 clr d2
2:
 cmp d1,d2
 ble 3f
 mov d1,d2
3:
 mov (CTL+32),d1
 cmp d1,d2
 ble 4f
 mov d1,d2
4:
 mov (CTL+36),a2
 add d3,a2
 mov d2,d0
 add d2,d3
 mov d3,(CTL+16)
 cmp 0,d2
 beq 9f
5:
 movbu (a2),d1
 movbu d1,(a0)
 inc a2
 inc a0
 add -1,d2
 bne 5b
9:
 mov 0xbad0d100,d1
 mov 0xbad0a000,a0
 mov 0xbad0a100,a1
 LEAVE 24,1
 ret [d2,d3,a2,a3],24
s_log:
 ENTER 8,12
 LEAVE 12,0
 ret [d2,a2],12
"""
TRAMPS = dict(malloc=0x60022782, free=0x600227b4, fopen=0x60634fbc, fclose=0x60634fc5, fread=0x6063514b,
              ftell=0x606351d9, fseek=0x60635243, log=LOGGER)


def assemble_stubs():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 's.s').write_text(STUB_SRC)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 's.o', t / 's.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(STUBS), '-e', '_start', '-o', t / 's.elf', t / 's.o'],
                       check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 's.elf', t / 's.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 's.elf'], check=True, capture_output=True, text=True).stdout
        syms = {n: int(a, 16) for a, ty, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3)}
        return (t / 's.bin').read_bytes(), {k: syms['s_' + k] for k in TRAMPS}


STUB_BIN, STUB_SYMS = assemble_stubs()


def stub_regions():
    regs = [Region('stubs', STUBS, STUB_BIN, 'rx')]
    for k, a in TRAMPS.items():
        regs.append(Region('t_' + k, a, b'\xdc' + struct.pack('<i', STUB_SYMS[k] - a), 'rx'))
    return regs


def sl(main, lo, hi):
    return bytes(main[lo - BASE:hi - BASE])


def sx(v):
    return v - (1 << 32) if v & 0x80000000 else v


# ------------------------------------------------------------------ fixture / run
class Case:
    def __init__(self, name, file=None, *, malloc_ok=True, fopen_ok=None, tell_fail=False, seek_end=0, seek_set=0,
                 readmax=0x10000, media=4, d1=0xF000, expect=None, stale=None, table_fill=None):
        self.name, self.file, self.malloc_ok = name, file, malloc_ok
        self.fopen_ok = (file is not None) if fopen_ok is None else fopen_ok
        self.tell_fail, self.seek_end, self.seek_set, self.readmax = tell_fail, seek_end, seek_set, readmax
        self.media, self.d1 = media, d1
        self.expect = expect           # 'load' / 'reject' / None (derive)
        self.stale = stale             # bytes left in the malloc buffer by an earlier user
        self.table_fill = table_fill   # pre-load table bytes (stands in for a different flashed table)


def model(case, state):
    """Independent model of the specified loader: -> (call ids, load?, new state)."""
    if case.d1 != 0xF000 or state == 0:
        return [], False, state
    if not case.malloc_ok:
        return ['malloc'], False, state
    if not case.fopen_ok:
        return ['malloc', 'fopen', 'free'], False, state
    seq = ['malloc', 'fopen', 'fseek']
    size = len(case.file)
    if case.seek_end:
        return seq + ['fclose', 'free'], False, 0
    seq.append('ftell')
    if case.tell_fail or size != SB.FILE_LEN:
        return seq + ['fclose', 'free'], False, 0
    seq.append('fseek')
    if case.seek_set:
        return seq + ['fclose', 'free'], False, 0
    seq += ['fread', 'fclose', 'free']
    if min(case.readmax, size) != SB.FILE_LEN:
        return seq, False, 0
    ok = not BIN.check_file(case.file)
    if case.expect is not None and (case.expect == 'load') != ok:
        raise AssertionError(f'{case.name}: desktop check_file() disagrees with the case label')
    return seq, ok, 0


def ctl_block(case):
    c = bytearray(0x100 + LOG_N * LOG_SZ)
    struct.pack_into('<10I', c, 0, LOG, BUF if case.malloc_ok else 0, HANDLE if case.fopen_ok else 0,
                     len(case.file or b''), 0xdead, case.seek_end & 0xffffffff, case.seek_set & 0xffffffff,
                     int(case.tell_fail), case.readmax, FILE_AT)
    return bytes(c)


def mount_data():
    d = bytearray((0x11 * i) & 0xff for i in range(MD_HI - MD_LO))
    struct.pack_into('<I', d, 0x61fa9024 - MD_LO, 0x0dd0beef)
    struct.pack_into('<5I', d, 0x61fa9028 - MD_LO, 0x60a80000, 0x60a80010, 0x60a80020, 0x60a80030, 0x60a80040)
    return bytes(d)


MOUNT_DATA = mount_data()


def heap_init(case):
    h = bytearray([HEAP_FILL]) * HEAP_LEN
    if case.stale:
        h[BUF - HEAP:BUF - HEAP + len(case.stale)] = case.stale
    return bytes(h)


def run(main, case, code=None, table=None, state_override=None):
    site = SB.SITE
    code = bytearray(code if code is not None else sl(main, SB.CODE_AT, SB.CODE_END))
    if state_override is not None:
        code[STATE - SB.CODE_AT] = state_override
    regions = [Region('site', site - 16, sl(main, site - 16, site + 16), 'rx'),
               Region('loader', SB.CODE_AT, bytes(code), 'rwx', True),
               Region('mount_set', MS_LO, sl(main, MS_LO, MS_HI), 'rx'),
               Region('mount_data', MD_LO, MOUNT_DATA, 'rw', True),
               Region('table', TAB_LO, bytes(table) if table is not None else sl(main, TAB_LO, TAB_HI), 'rw', True),
               Region('ctl', CTL, ctl_block(case), 'rw', True),
               Region('heap', HEAP, heap_init(case), 'rw', True),
               Region('stack', STACK, bytes([STACK_FILL]) * 0x2000, 'rw', True)] + stub_regions()
    if case.file:
        regions.append(Region('file', FILE_AT, bytes(case.file)))
    r = execute(regions, dict(INIT, pc=site, sp=SP0, d0=case.media, d1=case.d1, d2=case.d1), site + 7,
                limit=2_000_000, timeout=120)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    ctl = m['ctl']
    n = (struct.unpack_from('<I', ctl, C_LOGP)[0] - LOG) // LOG_SZ
    log = []
    for i in range(max(0, min(n, LOG_N))):
        v = struct.unpack_from('<11I', ctl, 0x100 + i * LOG_SZ)
        log.append(dict(fn=IDS.get(v[0], v[0]), d0=v[1], d1=v[2], a0=v[3], a1=v[4], sp=v[5], ret=v[6],
                        arg4=v[7], arg8=v[8], arg12=v[9], mdr=v[10]))
    stk = m['stack']
    lo = next((i for i, b in enumerate(stk) if b != STACK_FILL), len(stk))
    return dict(fault=r['fault'], regs={k: r['registers'][k] for k in ALL_REGS}, log=log, mem=m,
                above=stk[SP0 - 20 - STACK:], depth=SP0 - STACK - lo, insns=r.get('completed'))


def cstr(code, addr):
    o = addr - SB.CODE_AT
    if not 0 <= o < len(code):
        return None
    e = code.find(b'\0', o)
    return code[o:e] if e >= 0 else None


def check_run(case, s, p, state_in, table_in, code_in, code_len):
    """-> (ok, problems, new_state). s = stock run, p = patched run on the same fixture."""
    probs = []
    seq, load, st_exp = model(case, state_in)
    if s['fault'] or p['fault']:
        return False, [f"fault stock={s['fault']} patched={p['fault']}"], None
    if p['regs']['pc'] != SB.SITE + 7:
        probs.append('did not return to the site')
    slog = [e for e in s['log'] if e['fn'] == 'log']
    plog = [e for e in p['log'] if e['fn'] == 'log']
    # When the stock routine makes its own logger call (media types 1/4/8/32) that call re-sets mdr
    # and rewrites the whole 20-byte site frame, so both must equal stock. For other media types the
    # stock routine returns at once: mdr and the (dead, below-sp) site frame then hold the loader's
    # last call; the method continues to calls / `ret` (never retf/mdr), so that is reported only.
    full = bool(slog)
    d = [k for k in ALL_REGS if s['regs'][k] != p['regs'][k] and (full or k != 'mdr')]
    if d:
        probs.append(f'registers != stock: {d}')
    if s['above'][20:] != p['above'][20:] or (full and s['above'] != p['above']):
        probs.append('stack (live stack' + (' and site frame' if full else '') + ') != stock')
    if s['mem']['mount_data'] != p['mem']['mount_data']:
        probs.append('mount_set status memory != stock')
    if slog != plog:
        probs.append(f'MOUNT log call != stock ({len(slog)}/{len(plog)})')
    if plog and p['log'][-1]['fn'] != 'log':
        probs.append('a service call after the stock mount routine')
    calls = [e for e in p['log'] if e['fn'] != 'log']
    if [e['fn'] for e in calls] != seq:
        probs.append(f"calls {[e['fn'] for e in calls]} != expected {seq}")
    # arguments
    for e in calls:
        if not SB.CODE_AT <= e['ret'] < SB.CODE_AT + code_len:
            probs.append(f"{e['fn']} returns to {e['ret']:#x}, outside the loader")
        if e['fn'] == 'malloc' and e['d0'] != SB.BUF_SIZE:
            probs.append(f"malloc({e['d0']})")
        if e['fn'] == 'fopen' and (cstr(code_in, e['a0']) != SB.PATH.encode() or cstr(code_in, e['a1']) != b'r'):
            probs.append(f"fopen({cstr(code_in, e['a0'])}, {cstr(code_in, e['a1'])})")
        if e['fn'] in FILE_OPS and (e['a1'] if e['fn'] == 'fread' else e['a0']) != HANDLE:
            probs.append(f"{e['fn']} on a wrong handle")
        if e['fn'] == 'free' and e['a0'] != BUF:
            probs.append(f"free({e['a0']:#x})")
    seeks = [(sx(e['d0']), e['d1']) for e in calls if e['fn'] == 'fseek']
    if seeks and seeks != [(0, 1), (0, 2)][:len(seeks)]:
        probs.append(f'fseek args {seeks}')
    for e in calls:
        if e['fn'] == 'fread' and (e['a0'], e['d0'], e['d1']) != (BUF, 1, SB.FILE_LEN):
            probs.append(f"fread(a0={e['a0']:#x}, {e['d0']}, {e['d1']})")
    names = [e['fn'] for e in calls]
    if 'fopen' in names and case.fopen_ok:
        if names.count('fclose') != 1 or any(x in FILE_OPS for x in names[names.index('fclose') + 1:]):
            probs.append('file not closed exactly once / used after fclose')
    elif 'fclose' in names:
        probs.append('fclose without a successful fopen')
    if ('free' in names) != (case.malloc_ok and 'malloc' in names):
        probs.append('free mismatch')
    # memory effects
    tab_out = p['mem']['table']
    want = bytearray(table_in)
    if load:
        want[0x60210900 - TAB_LO:0x60210900 - TAB_LO + SB.PAYLOAD_LEN] = case.file[SB.HDR_LEN:]
    if tab_out != bytes(want):
        diff = [i for i in range(len(want)) if tab_out[i] != want[i]]
        probs.append(f"table {'not replaced exactly' if load else 'changed'} ({len(diff)} bytes, first "
                     f"{TAB_LO + diff[0]:#x})")
    heap, h0 = p['mem']['heap'], heap_init(case)
    if heap[:BUF - HEAP] != h0[:BUF - HEAP] or heap[BUF - HEAP + SB.BUF_SIZE:] != h0[BUF - HEAP + SB.BUF_SIZE:]:
        probs.append('heap written outside the buffer')
    cout = p['mem']['loader']
    so = STATE - SB.CODE_AT
    if cout[:so] + cout[so + 1:] != bytes(code_in[:so] + code_in[so + 1:]):
        probs.append('loader region changed outside sd_state')
    if cout[so] != st_exp:
        probs.append(f'sd_state {cout[so]:#x} != {st_exp:#x}')
    return not probs, probs, cout[so]


# ------------------------------------------------------------------ case lists
def refix(b):
    b = bytearray(b)
    struct.pack_into('<I', b, 16, zlib.crc32(bytes(b[:16] + b[20:])) & 0xffffffff)
    return bytes(b)


def poke(b, off, val, fix=True):
    b = bytearray(b)
    b[off] = val & 0xff
    return refix(b) if fix else bytes(b)


def files():
    mono, _, _ = BIN.build(ROOT / 'bundles/mono_colour_example.json')
    example, _, _ = BIN.build(ROOT / 'bundles/example.json')
    lo, span, who = SB.range_table(SB.layout())
    lo_t = bytes((lo[k % 64]) & 0xff for k in range(512))
    hi_t = bytes((lo[k % 64] + span[k % 64]) & 0xff for k in range(512))
    return dict(mono=mono, example=example, all_lo=SB.make_file(lo_t), all_hi=SB.make_file(hi_t)), (lo, span, who)


def cases(F, rng):
    lo, span, who = rng
    v = F['mono']
    out = [Case('valid mono_colour_example.json (ep7_bundles_bin)', v, expect='load'),
           Case('valid example.json (== flashed table)', F['example'], expect='load'),
           Case('valid all-lo boundary table', F['all_lo'], expect='load'),
           Case('valid all-hi boundary table', F['all_hi'], expect='load')]
    out += [Case(f'valid, media type {t}', v, media=t, expect='load') for t in (1, 8, 32, 0, 2)]
    out += [Case('valid over a 0xEE-filled table', v, table_fill=0xee, expect='load'),
            Case('valid all-lo over a 0xEE-filled table', F['all_lo'], table_fill=0xee, expect='load'),
            Case('valid, stale garbage in the buffer', v, stale=bytes(range(256)) * 4, expect='load')]
    R = lambda n, f, **kw: Case(n, f, expect='reject', **kw)
    out += [R('magic EP7C', poke(v, 3, ord('C'))), R('magic ep7b', refix(b'ep7b' + v[4:])),
            R('version 2', poke(v, 4, 2)), R('version 0x0101', poke(v, 5, 1)), R('header length 33', poke(v, 6, 33)),
            R('build 1101', poke(v, 8, 1101 & 0xff)), R('build 1100+65536', poke(v, 10, 1)),
            R('payload length 511', refix(v[:12] + struct.pack('<I', 511) + v[16:])),
            R('payload length 513', refix(v[:12] + struct.pack('<I', 513) + v[16:])),
            R('CRC value +1', v[:16] + struct.pack('<I', (struct.unpack_from('<I', v, 16)[0] + 1) & 0xffffffff) + v[20:]),
            R('CRC big-endian', v[:16] + v[16:20][::-1] + v[20:]),
            R('CRC zero', v[:16] + bytes(4) + v[20:]),
            R('SHA prefix byte 20 ^1', poke(v, 20, v[20] ^ 1)), R('SHA prefix byte 23 ^0x80', poke(v, 23, v[23] ^ 0x80)),
            R('reserved byte 24 = 1', poke(v, 24, 1)), R('reserved byte 31 = 0xff', poke(v, 31, 0xff))]
    # payload bit flip that stays in range, CRC left stale -> only the CRC can reject
    k = next(k for k in range(512) if span[k % 64] > 0 and (v[32 + k] ^ 1) - (256 if v[32 + k] ^ 1 >= 128 else 0)
             - lo[k % 64] in range(0, span[k % 64] + 1))
    out.append(R(f'payload byte {k} ^1 (in range), stale CRC', poke(v, 32 + k, v[32 + k] ^ 1, fix=False)))
    for off in range(64):
        slot = off % 8
        a, b = lo[off] - 1, lo[off] + span[off] + 1
        if a >= -128:
            out.append(R(f'range slot {slot} byte {off} ({who[off]}) = {a}', poke(v, 32 + slot * 64 + off, a)))
        if b <= 127 or (lo[off] >= 0 and b <= 255):
            out.append(R(f'range slot {slot} byte {off} ({who[off]}) = {b}', poke(v, 32 + slot * 64 + off, b)))
    out += [R('file size 0', b''), R('file size 543', v[:-1]), R('file size 545', v + b'\0'),
            R('file size 1024', v + bytes(480)),
            R('short read 543', v, readmax=543),
            R('short read 543 over a stale copy of the same file', v, readmax=543, stale=v),
            R('short read 32 over a stale copy of the same file', v, readmax=32, stale=v), R('short read 0', v, readmax=0), R('short read 32', v, readmax=32),
            R('ftell -1', v, tell_fail=True), R('fseek END error', v, seek_end=-1), R('fseek SET error', v, seek_set=-1),
            R('fseek SET returns 1', v, seek_set=1),
            Case('missing file (fopen -> 0)', None), Case('fopen error with a valid file present', v, fopen_ok=False),
            Case('malloc failure', v, malloc_ok=False)]
    return out


# ------------------------------------------------------------------ static
def calls_to(main, targets, lo=None, hi=None):
    """{target: {(mask, frame): count}} for `call d32` (dd) and `call d16` (cd) anywhere in [lo,hi)."""
    d = np.frombuffer(main, np.uint8)
    lo_i, hi_i = (0, len(d) - 7) if lo is None else (lo - BASE, hi - BASE)
    out = {t: {} for t in targets}
    for op, n in ((0xdd, 4), (0xcd, 2)):
        idx = np.nonzero(d[lo_i:hi_i] == op)[0] + lo_i
        idx = idx[idx + n + 3 <= len(d)]
        if n == 4:
            rel = (d[idx + 1].astype(np.int64) | d[idx + 2].astype(np.int64) << 8 | d[idx + 3].astype(np.int64) << 16 |
                   d[idx + 4].astype(np.int64) << 24)
            rel = np.where(rel >= 1 << 31, rel - (1 << 32), rel)
        else:
            rel = d[idx + 1].astype(np.int64) | d[idx + 2].astype(np.int64) << 8
            rel = np.where(rel >= 1 << 15, rel - (1 << 16), rel)
        tgt = idx + BASE + rel
        for t in targets:
            for i in idx[tgt == t]:
                key = (int(d[i + n + 1]), int(d[i + n + 2]))
                out[t][key] = out[t].get(key, 0) + 1
    return out


def check_static(spec, stock, patched, code_len):
    r = {}
    site = SB.SITE
    r['site_rel32_to_sd_hook'] = site + struct.unpack_from('<i', patched, site + 1 - BASE)[0] == SB.CODE_AT
    r['site_rest_stock'] = patched[site - BASE] == 0xdd and sl(patched, site + 5, site + 7) == bytes.fromhex('8014') \
        and sl(stock, site, site + 7).hex() == SB.SITE_STOCK
    code_edit = next(e for e in spec['edits'] if int(e['addr'], 16) == SB.CODE_AT)
    r['loader_bytes_eq_spec'] = sl(patched, SB.CODE_AT, SB.CODE_AT + code_len) == bytes.fromhex(code_edit['new'])
    r['ff_to_claim_end'] = set(sl(patched, SB.CODE_AT + code_len, SB.CODE_END + 16)) == {0xff}
    r['stock_ff_at_placement'] = set(sl(stock, SB.CODE_AT - 16, SB.CODE_END + 16)) == {0xff}
    svc = {v: k for k, v in SB.SERVICES.items() if k != 'ep7_mount_set'}
    st = calls_to(stock, list(svc))
    mine = calls_to(patched, list(svc), SB.CODE_AT, SB.CODE_AT + code_len)
    frames = {}
    ok = True
    for t, name in svc.items():
        dom = max(st[t].items(), key=lambda kv: kv[1])[0] if st[t] else None
        used = set(mine[t])
        good = bool(used) and used == {dom}
        ok &= good
        frames[name] = dict(loader=[f'{m:#04x},{f}' for m, f in used], stock_dominant=f'{dom[0]:#04x},{dom[1]}',
                            stock_sites=st[t].get(dom, 0), stock_all=sum(st[t].values()), ok=good)
    r['service_frames_match_stock'] = ok
    return all(r.values()), dict(r, frames=frames)


def fread_selftest():
    """Our fread stub alone: d0 = min(count, size - pos, readmax), bytes copied, d2/d3/a2/a3 kept."""
    data = bytes(range(256)) * 3
    c = Case('selftest', data, readmax=100)
    ctl = bytearray(ctl_block(c))
    struct.pack_into('<I', ctl, C_POS, 700)                     # 68 bytes left
    call = b'\xdd' + struct.pack('<i', TRAMPS['fread'] - CALLER) + b'\xf0\x18'
    regs = [Region('caller', CALLER, call + b'\xcb', 'rx'), Region('ctl', CTL, bytes(ctl), 'rw', True),
            Region('file', FILE_AT, data), Region('heap', HEAP, bytes([HEAP_FILL]) * HEAP_LEN, 'rw', True),
            Region('stack', STACK, bytes(0x2000), 'rw')] + stub_regions()
    r = execute(regs, dict(pc=CALLER, sp=SP0, a0=BUF, d0=1, d1=200, a1=HANDLE, d2=2, d3=3, a2=0xa2, a3=0xa3), CALLER + 7)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    h = m['heap']
    g = r['registers']
    return (not r['fault'] and g['d0'] == 68 and (g['d2'], g['d3'], g['a2'], g['a3'], g['sp']) == (2, 3, 0xa2, 0xa3, SP0)
            and h[BUF - HEAP:BUF - HEAP + 68] == data[700:] and h[BUF - HEAP + 68] == HEAP_FILL
            and struct.unpack_from('<I', m['ctl'], C_POS)[0] == 768)


# ------------------------------------------------------------------ suites
STATE = None


class Runner:
    def __init__(self, stock, code_len):
        self.stock, self.code_len, self.cache = stock, code_len, {}

    def stock_run(self, case):
        key = (case.media, case.d1)        # the stock path never touches the file service
        if key not in self.cache:
            self.cache[key] = run(self.stock, case)
        return self.cache[key]

    def one(self, img, case, code=None, table=None, state=0xff):
        code = bytearray(code if code is not None else sl(img, SB.CODE_AT, SB.CODE_END))
        code[STATE - SB.CODE_AT] = state
        table = table if table is not None else sl(img, TAB_LO, TAB_HI)
        if case.table_fill is not None:
            table = bytearray(table)
            table[0x60210900 - TAB_LO:0x60210b00 - TAB_LO] = bytes([case.table_fill]) * SB.PAYLOAD_LEN
            table = bytes(table)
        p = run(img, case, code=code, table=table)
        s = self.stock_run(case)
        if p['fault']:
            return False, [f"fault {p['fault']}"], p, None
        ok, probs, st = check_run(case, s, p, state, table, code, self.code_len)
        return ok, probs, p, st

    def sequence(self, img, steps):
        """Several mounts in one power cycle: loader + table state carried across."""
        code, table, rows, ok = sl(img, SB.CODE_AT, SB.CODE_END), sl(img, TAB_LO, TAB_HI), [], True
        state = code[STATE - SB.CODE_AT]
        for c in steps:
            g, probs, p, st = self.one(img, c, code=code, table=table, state=state)
            rows.append(dict(case=c.name, ok=g, problems=probs, state_after=st))
            ok &= g
            if p['fault']:
                break
            code, table, state = p['mem']['loader'], p['mem']['table'], st
        return ok, rows


def load_once(F):
    v, x = F['mono'], F['all_hi']
    bad = v[:16] + bytes(4) + v[20:]
    return [('valid, then a second valid file: not re-read', [Case('mount 1 valid', v), Case('mount 2 other valid', x)]),
            ('missing file, then valid: retried and loaded', [Case('mount 1 no file', None), Case('mount 2 valid', v)]),
            ('fopen error, then valid: retried and loaded', [Case('mount 1 fopen error', v, fopen_ok=False),
                                                             Case('mount 2 valid', v)]),
            ('malloc fail, then valid: retried and loaded', [Case('mount 1 malloc fail', v, malloc_ok=False),
                                                             Case('mount 2 valid', v)]),
            ('bad CRC (opened), then valid: never re-read', [Case('mount 1 bad CRC', bad, expect='reject'),
                                                             Case('mount 2 valid', v)]),
            ('wrong size (opened), then valid: never re-read', [Case('mount 1 size 545', v + b'\0'),
                                                                Case('mount 2 valid', v)]),
            ('d1 != 0xF000 (defensive path), then valid', [Case('entry d1=0x1000', v, d1=0x1000),
                                                          Case('entry d1=0', v, d1=0), Case('mount valid', v)])]


def suite(R, img, case_list, seqs):
    rows, ok, depth = [], True, 0
    for c in case_list:
        g, probs, p, st = R.one(img, c)
        depth = max(depth, p['depth']) if not p['fault'] else depth
        rows.append(dict(case=c.name, ok=g, problems=probs, state_after=st, depth=p['depth']))
        ok &= g
    srows = []
    for name, steps in seqs:
        g, r = R.sequence(img, steps)
        srows.append(dict(sequence=name, ok=g, steps=r))
        ok &= g
    return ok, rows, srows, depth


def core(F, rng):
    v = F['mono']
    pick = ('valid mono_colour_example.json (ep7_bundles_bin)', 'CRC value +1', 'file size 543', 'file size 545',
            'short read 543', 'short read 543 over a stale copy of the same file', 'valid, media type 0',
            'valid over a 0xEE-filled table', 'ftell -1', 'fseek END error', 'missing file (fopen -> 0)', 'magic EP7C')
    cl = [c for c in cases(F, rng) if c.name in pick]
    lo, span, who = rng
    k = next(o for o in range(64) if span[o] > 0 and lo[o] < 0)
    cl.append(Case('range lo-1', poke(v, 32 + k, lo[k] - 1), expect='reject'))
    cl.append(Case('range hi+1', poke(v, 32 + 64 + k, lo[k] + span[k] + 1), expect='reject'))
    return cl, load_once(F)[:2] + load_once(F)[4:5]


def find_once(buf, pat, lo, hi):
    i = buf.find(pat, lo - BASE, hi - BASE)
    if i < 0 or buf.find(pat, i + 1, hi - BASE) >= 0:
        raise ValueError(f'mutation pattern {pat.hex()} not unique in the loader')
    return i


def mutations(patched, code_len):
    lo, hi = SB.CODE_AT, SB.CODE_AT + code_len
    out = []

    def mut(name, pat, new, off=0):
        m = bytearray(patched)
        i = find_once(m, pat, lo, hi) + off
        m[i:i + len(new)] = new
        out.append((name, bytes(m)))
    tab = struct.pack('<I', 0x60210900)
    mut('CRC compare flipped (bne -> beq)', bytes.fromhex('adc9'), b'\xc8', 1)
    mut('CRC compare removed', bytes.fromhex('adc9'), b'\xcb\xcb', 1)
    mut('CRC init -1 -> 0', bytes.fromhex('80ff98'), b'\x80\x00')
    mut('file size check removed (ftell == 544)', bytes.fromhex('facb2002c9'), b'\xcb\xcb', 4)
    mut('file size 544 -> 545', bytes.fromhex('facb2002'), bytes.fromhex('facb2102'))
    mut('fread count check removed', bytes.fromhex('aec9'), b'\xcb\xcb', 1)
    mut('range check removed (bhi)', bytes.fromhex('acc5'), b'\xcb\xcb', 1)
    mut('range check bhi -> bcc (unsigned >= )', bytes.fromhex('acc5'), b'\xc6', 1)
    mut('header compare 0..15 removed', bytes.fromhex('a4c96e'), b'\xcb\xcb', 1)
    mut('sd_state store removed', bytes.fromhex('fc82') + struct.pack('<I', STATE), b'\xcb' * 6)
    mut('error path skips fclose', bytes.fromhex('9cdd05253fffb010'), b'\xcb' * 7, 1)
    mut('a0 not restored', bytes.fromhex('5c0c5d10'), b'\xcb\xcb')
    mut('a1 not restored', bytes.fromhex('5c0c5d10'), b'\xcb\xcb', 2)
    mut('d0 (media type) not restored', bytes.fromhex('88fccd00f00000'), b'\xcb')
    mut('d1 (0xF000) not restored', bytes.fromhex('88fccd00f00000'), b'\xcb' * 6, 1)
    mut('table address +1', b'\xfc\xdd' + tab, b'\xfc\xdd' + struct.pack('<I', 0x60210901))
    mut('payload copy 512 -> 511', bytes.fromhex('faca0002c9f7'), bytes.fromhex('faca ff01'.replace(' ', '')))
    return out


# ------------------------------------------------------------------ main
def main():
    global STATE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--no-mutations', action='store_true')
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    meta = spec.get('sd_bundles') or spec.get('meta', {}).get('sd_bundles', {}).get('sd_bundles')
    if not meta:
        sys.exit("spec lacks 'sd_bundles' (build with patches/sd_bundles/build.py; merge with tools/merge_specs.py)")
    if int(meta['code_at'], 16) != SB.CODE_AT or meta['site'] != hex(SB.SITE):
        sys.exit('spec sd_bundles metadata does not match patches/sd_bundles/build.py')
    STATE = int(meta['state'], 16)
    code_len = meta['code_len']
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    F, rng = files()
    flashed = sl(patched, 0x60210900, 0x60210b00)
    results = []
    st_ok, st = check_static(spec, stock, patched, code_len)
    results.append(dict(test='S static: site rel32, loader bytes, FF tail, service call frames == stock', passed=st_ok,
                        detail=st))
    results.append(dict(test='S fread stub self-test', passed=fread_selftest()))
    results.append(dict(test='S bundles table present (flashed table != mono test payload)',
                        passed=flashed != F['mono'][32:] and flashed == F['example'][32:],
                        detail='flashed == example.json table' if flashed == F['example'][32:] else 'flashed table differs'))
    R = Runner(stock, code_len)
    cl = cases(F, rng)
    ok, rows, srows, depth = suite(R, patched, cl, load_once(F))
    nv = sum(1 for c in cl if c.expect == 'load')
    results.append(dict(test=f'V/R/C {len(cl)} single-mount cases ({nv} valid, {len(cl) - nv} reject/no-file) vs stock',
                        passed=all(r['ok'] for r in rows), detail=f'peak stack below site sp {depth} B', rows=rows))
    results.append(dict(test=f'L load-once / retry, {len(srows)} mount sequences',
                        passed=all(r['ok'] for r in srows), rows=srows))
    allok = all(r['passed'] for r in results)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['test']}" + (f"  {r['detail']}" if 'detail' in r and
                                                                   not isinstance(r['detail'], dict) else ''))
        if isinstance(r.get('detail'), dict) and not r['passed']:
            print('      ', r['detail'])
        for x in r.get('rows', []):
            if not x['ok']:
                print('      BAD', json.dumps(x, default=str)[:400])
    mres = []
    if not a.no_mutations:
        if not allok:
            print('skipping mutations: base suite failed')
        else:
            ccl, cseq = core(F, rng)
            for name, img in mutations(patched, code_len):
                g, rws, srw, _ = suite(R, img, ccl, cseq)
                failing = [x['case'] for x in rws if not x['ok']] + [x['sequence'] for x in srw if not x['ok']]
                mres.append(dict(mutation=name, detected=not g, failing=failing))
                print(f"{'PASS' if not g else 'FAIL'}  M mutation '{name}' detected by {len(failing)}: {failing[:3]}")
            allok &= all(m['detected'] for m in mres)
    print(f"{'PASS' if allok else 'FAIL'}  overall; package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.edits), package=info, passed=allok, results=results, mutations=mres,
                                          scope='emulator only; stub file service (ours) at the real entries; real '
                                                'stock 0x6077d590; no camera contacted'), indent=1, default=str))
    sys.exit(0 if allok else 1)


if __name__ == '__main__':
    main()
