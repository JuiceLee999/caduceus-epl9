#!/usr/bin/env python3
"""Emulator verification of a BUILT v0.2 profile-bundle package (offline; emulator only; no camera).

Builds the package in memory from an edits.json (tools/build_package.build; a merged spec from
tools/merge_specs.py is fine), decodes the patched main payload, and runs native code from the
PATCHED payload against the same fixture on the STOCK payload. Expected H/L values are derived
independently from the bundle JSON (patches/bundles/build.py: build_table), not read back from
the image.

  A  selector 0x603b0252 -> hook -> v0.2 routine, mode 11, COLOR profile 1..4, several saturation
     sets: 12 output records' hue/L == that slot's table; saturation, control word and every
     other output byte == stock; context, job == stock; all registers (d0-d3, a0-a3, sp, pc,
     mdr, psw, lir, lar) at return == stock; no fault.
  B  invalid / missing transport -> output byte-identical to stock: profile 0, 5, 255; marker
     absent (job without capture record); ext mode 12 / 0; wrong callback; foreign parent; slot
     disabled; table value out of range. Run with a HOSTILE table (all 8 slots enabled, non-zero)
     so only the index/flag checks can keep the output stock. Record indices 0 and 15 accepted.
  C  converter transport, native code segments from the patched payload:
       0x603e6681..0x603e66d5 (converter 0x603e62d1) and 0x603e91c3..0x603e921c (0x603e8af1)
     on synthetic capture/params fixtures, picture modes 11/12/5/6 and profile bytes:
     job+15488/15489/15490 == capture+24083, capture+24053, 0xB2; every other job/capture/stack
     byte and every register at the stop PC == stock.
  D  job constructor 0x603537eb (native, patched vs stock) up to the tail memset, with a stub
     allocator and stub memset: requested size 15512 vs 15488; job+15472..15511 zeroed; nothing
     beyond 15512 touched; all other bytes as stock. Static: alloc imm, memset base+len, class-2
     bound, extension offsets; no branch/abs32 reference into the interior of any hook span.
  E  mutation tests (applied to the decoded patched payload): each must make A-D FAIL.
  F  changed payload bytes all inside the edit spans.

Usage: tools/ep7_verify_bundles.py SPEC.json [--json out.json] [--no-mutations]
"""
import argparse, json, struct, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'patches/bundles'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
import ep7_color_probe as PR  # noqa: E402
import build as BB  # noqa: E402  (patches/bundles/build.py)
from penf_emulator import Region, execute  # noqa: E402

BASE = 0x60020020
TAIL1_LO, TAIL1_HI = 0x602108ec, 0x60211000
CALLER, STACK = 0x18000000, 0x18010000
OUTPUT, CONTEXT, JOB, CAPTURE = 0x19000000, 0x1a000000, 0x1b000000, 0x1c000000
NEW_SIZE = BB.JOB_SIZE + BB.EXT
REGS_ALL = ['d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'pc', 'mdr', 'psw', 'lir', 'lar']
SATS = ([0] * 12, [3, -2, 0, 1, 0, 0, -5, 0, 2, 0, 0, 4], [5] * 12, [-5] * 12)


def sl(main, lo, hi):
    return main[lo - BASE:hi - BASE]


def tail1(main):
    return Region('tail1', TAIL1_LO, sl(main, TAIL1_LO, TAIL1_HI), 'rx')


TAIL7_LO, TAIL7_HI = 0x61378c68, 0x61379000      # section-7 tail: patches/mono_colour (selector hook 0x603b02bf)


def tail7(main):
    return Region('tail7', TAIL7_LO, sl(main, TAIL7_LO, TAIL7_HI), 'rx')


def regs_of(r):
    return {k: r['registers'][k] for k in REGS_ALL}


# ------------------------------------------------------------------ A/B selector
def selector_run(main, sat, *, profile=1, mode=11, magic=BB.MAGIC, callback=PR.CALLBACK, record_index=5,
                 foreign_parent=False, job_size=NEW_SIZE):
    job = bytearray(job_size)
    req, rec = PR.REQ_IN_JOB, PR.RECORDS_IN_JOB + PR.REC_STRIDE * record_index
    struct.pack_into('<I', job, req, callback)
    struct.pack_into('<I', job, req + 4, JOB + rec)
    struct.pack_into('<I', job, rec, JOB + (64 if foreign_parent else 0))
    job[req + 8:req + 12] = bytes([0, 0, 11, 0])                # request picture mode 11
    job[req + 1816:req + 1828] = struct.pack('<12b', *sat)
    if job_size >= NEW_SIZE:
        job[BB.EXT_PROFILE], job[BB.EXT_MODE], job[BB.EXT_MAGIC] = profile, mode, magic
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, JOB + req)
    struct.pack_into('<I', ctx, 12, OUTPUT)
    regions = [PR.caller(PR.SELECTOR, 0xf0, 20), Region('stack', STACK, bytes(0x2000), 'rw', True),
               Region('table', PR.TABLE, sl(main, PR.TABLE, PR.TABLE + PR.TABLE_SIZE)),
               Region('job', JOB, bytes(job), 'rw', True), Region('ctx', CONTEXT, bytes(ctx), 'rw', True),
               Region('out', OUTPUT, bytes(5212), 'rw', True),
               Region('code', PR.BUILDER, sl(main, PR.BUILDER, PR.SELECTOR_END), 'rx'), tail1(main), tail7(main)]
    regions += PR.gain_regions(main)
    regs = {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CONTEXT, 'd0': 0xd0d0, 'd1': 0xd1d1, 'a1': 0xa1a1,
            'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}
    r = execute(regions, regs, CALLER + 7, limit=40000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    rr = r['registers']
    ok = (not r['fault'] and rr['pc'] == CALLER + 7 and rr['sp'] == STACK + 0x1800 and
          (rr['d2'], rr['d3'], rr['a2'], rr['a3']) == (0x2222, 0x3333, 0xa2a2, 0xa3a3))
    return ok, mem, r


def mask_hl(out):
    o = bytearray(out)
    for i in range(12):
        for off in (18, 22):
            p = PR.OUT_RECORDS + 24 * i + off
            o[p:p + 2] = b'\0\0'
    return bytes(o)


def check_selector(stock, patched, slots, hostile_patched):
    res, ok = [], True
    for sat in SATS:
        for p in (1, 2, 3, 4):
            ok_s, m_s, r_s = selector_run(stock, sat, profile=p)
            ok_p, m_p, r_p = selector_run(patched, sat, profile=p)
            meta = slots[p - 1]
            rp, rs = PR.records(m_p['out']), PR.records(m_s['out'])
            if meta['enabled']:
                exp = meta['native_rows']
                hl = all(rp[i]['hue'] == exp[i][0] and rp[i]['light'] == exp[i][1] for i in range(12))
            else:
                hl = m_p['out'] == m_s['out']
            sat_ok = all(rp[i]['sat'] == rs[i]['sat'] for i in range(12))
            rest = mask_hl(m_s['out']) == mask_hl(m_p['out'])
            same = dict(ctx=m_s['ctx'] == m_p['ctx'], job=m_s['job'] == m_p['job'],
                        regs=regs_of(r_s) == regs_of(r_p), stack_ok=ok_s and ok_p)
            good = hl and sat_ok and rest and all(same.values())
            ok &= good
            res.append(dict(test=f'A COLOR{p} sat={sat[:3]}..', passed=good, hl=hl, sat_eq=sat_ok, other_eq=rest,
                            **same, insns=r_p['completed'],
                            regdiff={k: (hex(r_s['registers'][k]), hex(r_p['registers'][k])) for k in REGS_ALL
                                     if r_s['registers'][k] != r_p['registers'][k]}))
    # B: stock-equivalence cases, run on the HOSTILE table image (all 8 slots enabled)
    sat = SATS[1]
    cases = [('profile 0', dict(profile=0)), ('profile 5', dict(profile=5)), ('profile 255', dict(profile=255)),
             ('marker absent (no capture record)', dict(magic=0)), ('marker wrong', dict(magic=0xB3)),
             ('ext mode 12', dict(mode=12)), ('ext mode 0', dict(mode=0)),
             ('wrong callback', dict(callback=PR.CALLBACK + 1)), ('foreign parent', dict(foreign_parent=True))]
    for name, kw in cases:
        ok_s, m_s, r_s = selector_run(stock, sat, **kw)
        ok_p, m_p, r_p = selector_run(hostile_patched, sat, **kw)
        good = ok_s and ok_p and m_s['out'] == m_p['out'] and m_s['job'] == m_p['job'] and \
            m_s['ctx'] == m_p['ctx'] and regs_of(r_s) == regs_of(r_p)
        ok &= good
        res.append(dict(test=f'B {name} -> stock', passed=good, out_identical=m_s['out'] == m_p['out'],
                        regs=regs_of(r_s) == regs_of(r_p)))
    for idx in (0, 15):
        _, m_a, _ = selector_run(patched, sat, profile=1)
        ok_p, m_p, _ = selector_run(patched, sat, profile=1, record_index=idx)
        good = ok_p and m_p['out'] == m_a['out'] and (m_p['out'] != selector_run(stock, sat)[1]['out']
                                                      or not slots[0]['enabled'])
        ok &= good
        res.append(dict(test=f'B record index {idx} accepted', passed=good))
    return ok, res


def table_addr(spec):
    return int(spec['labels']['bundle_table'], 16)


def with_table(main, spec, table):
    m = bytearray(main)
    a = table_addr(spec) - BASE
    m[a:a + len(table)] = table
    return bytes(m)


def check_table_guards(stock, patched, spec, slots):
    """Slot disabled and out-of-range value -> stock (patched table modified in emulator RAM only)."""
    res, ok = [], True
    sat = SATS[1]
    base = bytearray(bytes.fromhex(spec['table_hex']))
    variants = []
    t = bytearray(base); t[1 * 64 + 31] &= ~BB.FLAG_HL & 0xff; variants.append(('slot COLOR2 disabled', 2, t))
    t = bytearray(base); t[2 * 64 + 5] = 8; variants.append(('COLOR3 hue[5]=+8', 3, t))
    t = bytearray(base); t[2 * 64 + 23] = (-8) & 0xff; variants.append(('COLOR3 light[11]=-8', 3, t))
    t = bytearray(base); t[3 * 64 + 0] = 0x80; variants.append(('COLOR4 hue[0]=-128', 4, t))
    for name, p, tb in variants:
        img = with_table(patched, spec, tb)
        ok_s, m_s, r_s = selector_run(stock, sat, profile=p)
        ok_p, m_p, r_p = selector_run(img, sat, profile=p)
        good = ok_s and ok_p and m_s['out'] == m_p['out'] and regs_of(r_s) == regs_of(r_p)
        ok &= good
        res.append(dict(test=f'B {name} -> stock', passed=good))
    return ok, res


def hostile_table():
    t = bytearray(8 * 64)
    for s in range(8):
        for i in range(24):
            t[s * 64 + i] = ((s + i) % 15 - 7) & 0xff or 1
        t[s * 64 + 31] = BB.FLAG_HL
    return bytes(t)


# ------------------------------------------------------------------ C converters
def conv_run(main, which, mode, profile, stale_ext=0):
    cap = bytearray(24200)
    for i in range(len(cap)):
        cap[i] = (i * 7 + 3) & 0xff                            # recognisable filler
    cap[BB.CAP_MODE] = mode
    cap[BB.CAP_PROFILE] = profile
    for i in range(12):
        struct.pack_into('<h', cap, 24058 + 2 * i, i - 5)
    job = bytearray(NEW_SIZE)
    job[BB.EXT_PROFILE:BB.EXT_PROFILE + 3] = bytes([stale_ext] * 3)
    params = JOB + 36
    stack = bytearray(0x2000)
    sp = STACK + 0x1800
    o = sp - STACK
    if which == 1:
        lo, hi, start, stop = 0x603e6681, 0x603e66e0, 0x603e6681, 0x603e66d5
        struct.pack_into('<I', stack, o + 20, CAPTURE)
        regs = {'pc': start, 'sp': sp, 'a3': CAPTURE + BB.CAP_MODE, 'd3': params, 'a0': params,
                'd0': 0x1234, 'd1': 0x5678, 'd2': 0x2222, 'a1': 0xa1a1, 'a2': 0xa2a2}
    else:
        lo, hi, start, stop = 0x603e91c3, 0x603e9220, 0x603e91c3, 0x603e921c
        struct.pack_into('<I', stack, o + 20, params)
        struct.pack_into('<I', stack, o + 24, CAPTURE)
        struct.pack_into('<I', stack, o + 36, CAPTURE + BB.CAP_MODE)
        regs = {'pc': start, 'sp': sp, 'd0': 0x1234, 'd1': 0x5678, 'd2': 0x2222, 'd3': 0x3333,
                'a0': 0xa0a0, 'a1': 0xa1a1, 'a2': 0xa2a2, 'a3': 0xa3a3}
    regions = [Region('code', lo, sl(main, lo, hi), 'rx'), tail1(main),
               Region('stack', STACK, bytes(stack), 'rw', True), Region('cap', CAPTURE, bytes(cap), 'rw', True),
               Region('job', JOB, bytes(job), 'rw', True)]
    r = execute(regions, regs, stop, limit=5000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return r, mem, cap


def check_converters(stock, patched):
    res, ok = [], True
    for which in (1, 2):
        for mode, profile, stale in ((11, 1, 0), (11, 2, 0), (11, 3, 0), (11, 4, 0), (11, 0, 0), (11, 255, 0),
                                     (12, 3, 0), (5, 7, 0), (6, 2, 0), (11, 4, 0x55)):
            r_s, m_s, cap = conv_run(stock, which, mode, profile, stale)
            r_p, m_p, _ = conv_run(patched, which, mode, profile, stale)
            e = BB.EXT_PROFILE
            ext = m_p['job'][e:e + 3]
            exp_ext = bytes([profile, mode, BB.MAGIC])
            js, jp = bytearray(m_s['job']), bytearray(m_p['job'])
            js[e:e + 3] = jp[e:e + 3] = b'\0\0\0'
            stock_ext_untouched = m_s['job'][e:e + 3] == bytes([stale] * 3)
            good = (not r_s['fault'] and not r_p['fault'] and r_p['registers']['pc'] == r_s['registers']['pc'] and
                    ext == exp_ext and js == jp and stock_ext_untouched and m_s['cap'] == m_p['cap'] == bytes(cap)
                    and m_s['stack'] == m_p['stack'] and regs_of(r_s) == regs_of(r_p))
            ok &= good
            res.append(dict(test=f'C conv{which} mode={mode} profile={profile} stale={stale:#x}', passed=good,
                            ext=ext.hex(), expect=exp_ext.hex(), other_job_eq=js == jp,
                            regs_eq=regs_of(r_s) == regs_of(r_p), stop=hex(r_p['registers']['pc']),
                            insns=(r_s['completed'], r_p['completed']),
                            regdiff={k: (hex(r_s['registers'][k]), hex(r_p['registers'][k])) for k in REGS_ALL
                                     if r_s['registers'][k] != r_p['registers'][k]}))
    return ok, res


# ------------------------------------------------------------------ D constructor + static
ALLOC_STUB, MEMSET_STUB, SIZE_CELL, BLOCK = 0x60022700, 0x4700115e, 0x1d000000, 16384
# memset(a0 = dst, d0 = byte, d1 = len), entered by `call ...,[d2,a2],8` (our stub, assembled with gas):
#   cmp 0,d1; beq 2f; 1: movbu d0,(a0); inc a0; add -1,d1; bne 1b; 2: ret [d2,a2],8
MEMSET_CODE = bytes.fromhex('a500c809f0504129ffc9fbdfa008')


def ctor_run(main):
    alloc = (b'\xfc\xdc' + struct.pack('<I', JOB) +           # mov JOB,a0
             b'\xfc\x81' + struct.pack('<I', SIZE_CELL) +      # mov d0,(SIZE_CELL)
             b'\xdf\x00\x04')                                  # ret [],4
    # memset(a0 = dst, d0 = byte, d1 = len); entered by `call ...,[d2,a2],8`
    memset = MEMSET_CODE
    desc = bytes(range(32)) + bytes(16)                         # 8-word descriptor at a0 (copied to job+4)
    regions = [Region('caller', CALLER, b'\xdd' + struct.pack('<i', 0x603537eb - CALLER) + b'\xf0\x2c\xcb', 'rx'),
               Region('ctor', 0x603537eb, sl(main, 0x603537eb, 0x60353920), 'rx'),
               Region('alloc', ALLOC_STUB, alloc, 'rx'), Region('memset', MEMSET_STUB, memset, 'rx'),
               Region('size', SIZE_CELL, bytes(4), 'rw', True), Region('desc', 0x1e000000, desc, 'rw'),
               Region('status', 0x1e001000, bytes(4), 'rw', True),
               Region('job', JOB, b'\xaa' * BLOCK, 'rw', True), Region('stack', STACK, bytes(0x2000), 'rw')]
    r = execute(regions, {'pc': CALLER, 'sp': STACK + 0x1800, 'd0': 0, 'a0': 0x1e000000, 'a1': 0x1e001000},
                0x60353915, limit=2_000_000, timeout=120)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return r, mem


def memset_stub_selftest():
    """The memset stub is ours: check it on its own before trusting D."""
    r, mem = None, None
    ms = Region('memset', MEMSET_STUB, MEMSET_CODE, 'rx')
    buf = Region('buf', JOB, b'\xaa' * 64, 'rw', True)
    call = Region('caller', CALLER, b'\xdd' + struct.pack('<i', MEMSET_STUB - CALLER) + b'\xa0\x08\xcb', 'rx')
    r = execute([ms, buf, call, Region('stack', STACK, bytes(0x2000), 'rw')],
                {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': JOB + 8, 'd0': 0, 'd1': 40}, CALLER + 7)
    b = bytes.fromhex(r['memory'][0]['hex'])
    return not r['fault'] and b == b'\xaa' * 8 + bytes(40) + b'\xaa' * 16


def branch_refs(main, targets):
    """Brute-force: any relative branch/call/jmp, Lcc loop start, or abs32 (0x6/0xA alias) hitting targets."""
    d = np.frombuffer(main, np.uint8).astype(np.int64)
    n = len(d)
    pc = np.arange(n, dtype=np.int64) + BASE
    tset = np.array(sorted(targets), dtype=np.int64)
    hits = []

    def s8(i): return np.where(d[i] >= 0x80, d[i] - 0x100, d[i])
    def s16(i):
        v = d[i] | (d[i + 1] << 8); return np.where(v >= 0x8000, v - 0x10000, v)
    def s32(i):
        v = d[i] | (d[i + 1] << 8) | (d[i + 2] << 16) | (d[i + 3] << 24); return np.where(v >= 1 << 31, v - (1 << 32), v)
    i = np.arange(n - 6)
    forms = [('bcc8', (d[i] >= 0xc0) & (d[i] <= 0xca), lambda: pc[i] + s8(i + 1)),
             ('bcc8x', (d[i] == 0xf8) & (d[i + 1] >= 0xe8) & (d[i + 1] <= 0xeb), lambda: pc[i] + s8(i + 2)),
             ('jmp/call16', (d[i] == 0xcc) | (d[i] == 0xcd), lambda: pc[i] + s16(i + 1)),
             ('jmp/call32', (d[i] == 0xdc) | (d[i] == 0xdd), lambda: pc[i] + s32(i + 1)),
             ('calls16', (d[i] == 0xfa) & (d[i + 1] == 0xff), lambda: pc[i] + s16(i + 2)),
             ('calls32', (d[i] == 0xfc) & (d[i + 1] == 0xff), lambda: pc[i] + s32(i + 2)),
             ('setlb', d[i] == 0xdb, lambda: pc[i] + 1)]
    for name, cond, tgt in forms:
        t = (tgt() & 0xffffffff)
        m = cond & np.isin(t, tset)
        hits += [(name, hex(int(pc[k])), hex(int(t[k]))) for k in np.nonzero(m)[0]]
    w = (d[:-3] | (d[1:-2] << 8) | (d[2:-1] << 16) | (d[3:] << 24))
    for alias in (0, 0x40000000):
        m = np.isin(w, tset + alias)
        hits += [('abs32', hex(int(k + BASE)), hex(int(w[k]))) for k in np.nonzero(m)[0]]
    return hits


def check_constructor_static(stock, patched, spec):
    res, ok = [], True
    st = memset_stub_selftest()
    r_s, m_s = ctor_run(stock)
    r_p, m_p = ctor_run(patched)
    size_s, size_p = struct.unpack('<I', m_s['size'])[0], struct.unpack('<I', m_p['size'])[0]
    js, jp = m_s['job'], m_p['job']
    tail_zero = jp[15472:NEW_SIZE] == bytes(NEW_SIZE - 15472)
    beyond = jp[NEW_SIZE:] == b'\xaa' * (BLOCK - NEW_SIZE)
    stock_beyond = js[BB.JOB_SIZE:] == b'\xaa' * (BLOCK - BB.JOB_SIZE)
    others = js[:BB.JOB_SIZE] == jp[:BB.JOB_SIZE]
    good = (st and not r_s['fault'] and not r_p['fault'] and r_p['registers']['pc'] == 0x60353915 and
            size_s == BB.JOB_SIZE and size_p == NEW_SIZE and tail_zero and beyond and stock_beyond and others)
    ok &= good
    res.append(dict(test='D constructor (native, stub alloc/memset)', passed=good, memset_stub_selftest=st,
                    alloc_size=(size_s, size_p), ext_zeroed=tail_zero, untouched_beyond_new_size=beyond,
                    stock_untouched_beyond_15488=stock_beyond, bytes_below_15488_eq_stock=others,
                    insns=(r_s['completed'], r_p['completed']), fault=r_p['fault']))
    # static consistency of the size change in the PATCHED image
    imm = lambda a: struct.unpack_from('<H', patched, a - BASE)[0]
    s = dict(alloc_opcode=patched[0x603537f0 - BASE] == 0x2c and imm(0x603537f1) == NEW_SIZE,
             memset_base=patched[0x60353906 - BASE] == 0x24 and imm(0x60353907) == 15472,
             memset_len=patched[0x6035390c - BASE] == 0x85 and patched[0x6035390d - BASE] == NEW_SIZE - 15472,
             class2_bound=patched[0x60022713 - BASE:0x60022717 - BASE] == bytes.fromhex('fac80040') and NEW_SIZE <= 16384,
             ext_inside=BB.EXT_MAGIC < NEW_SIZE and BB.EXT_PROFILE >= BB.JOB_SIZE)
    # interior of every hook span must not be a branch / loop / abs32 target (span start may be)
    interior = set()
    for e in spec['edits']:
        a = int(e['addr'], 16)
        n = len(bytes.fromhex(e['new']))
        if a in (BB.HOOK, BB.CONV1, BB.CONV2):
            interior |= set(range(a + 1, a + n))
    hits_s = branch_refs(stock, interior)
    s['no_refs_into_hook_interiors'] = not hits_s
    good = all(s.values())
    ok &= good
    res.append(dict(test='D static size/branch consistency', passed=good, **s, interior_hits=hits_s))
    return ok, res


# ------------------------------------------------------------------ driver
def spans_check(spec, stock, patched):
    sa, pa = np.frombuffer(stock, np.uint8), np.frombuffer(patched, np.uint8)
    idx = np.nonzero(sa != pa)[0] + BASE
    spans = [(int(e['addr'], 16), int(e['addr'], 16) + len(bytes.fromhex(e['new']))) for e in spec['edits']]
    return all(any(s <= x < t for s, t in spans) for x in idx), len(idx)


def run_all(stock, patched, spec, slots):
    hostile = with_table(patched, spec, hostile_table())
    out, ok = [], True
    for f in (lambda: check_selector(stock, patched, slots, hostile),
              lambda: check_table_guards(stock, patched, spec, slots),
              lambda: check_converters(stock, patched),
              lambda: check_constructor_static(stock, patched, spec)):
        g, r = f()
        ok &= g
        out += r
    return ok, out


def find_once(buf, pat, lo, hi):
    i = buf.find(pat, lo - BASE, hi - BASE)
    if i < 0 or buf.find(pat, i + 1, hi - BASE) >= 0:
        raise ValueError(f'mutation pattern {pat.hex()} not unique')
    return i


def mutations(patched, spec):
    lab = {k: int(v, 16) for k, v in spec['labels'].items()}
    hl, c1, c2, tbl = lab['hl'], lab['conv1'], lab['conv2'], lab['code_end']
    out = []

    def mut(name, pat, new, lo, hi):
        m = bytearray(patched)
        i = find_once(m, pat, lo, hi)
        m[i:i + len(new)] = new
        out.append((name, bytes(m)))
    mut('hue offset 706->708', bytes.fromhex('fad3c202'), bytes.fromhex('fad3c402'), hl, tbl)
    mut('record loop 12->11', bytes.fromhex('aa0c'), bytes.fromhex('aa0b'), hl, tbl)
    mut('frame -28 -> -24 (stack)', bytes.fromhex('f8fee4'), bytes.fromhex('f8fee8'), hl, tbl)
    mut('a0 not restored', bytes.fromhex('5c10'), bytes.fromhex('5c14'), hl + 0x80, tbl)
    mut('profile bound 4 -> 5', bytes.fromhex('a004'), bytes.fromhex('a005'), hl, tbl)
    mut('no -1 on profile', bytes.fromhex('28ff'), bytes.fromhex('2800'), hl, tbl)
    mut('marker check removed', bytes.fromhex('fac8b200c970'), bytes.fromhex('fac8b200cb' + 'cb'), hl, tbl)
    mut('mode check 11 -> 12', bytes.fromhex('a00bc9'), bytes.fromhex('a00cc9'), hl, tbl)
    mut('value check 15 -> 16', bytes.fromhex('a00fc6'), bytes.fromhex('a010c6'), hl, tbl)
    mut('enable flag check skipped', bytes.fromhex('f8ec02c8'), bytes.fromhex('f8ec00c8'), hl, tbl)
    mut('callback check off-by-one', struct.pack('<I', PR.CALLBACK), struct.pack('<I', PR.CALLBACK + 1), hl, tbl)
    m = bytearray(patched); p = lab['perm'] - BASE; m[p], m[p + 1] = m[p + 1], m[p]; out.append(('perm swap r0/r1', bytes(m)))
    m = bytearray(patched); p = lab['light_lut'] - BASE + 2 * 8; m[p] ^= 1; out.append(('light LUT[+1] corrupted', bytes(m)))
    mut('conv1 profile -> job+15487', bytes.fromhex('fa505c3c'), bytes.fromhex('fa505b3c'), c1, c2)
    mut('conv1 skips mono branch', bytes.fromhex('c907'), bytes.fromhex('cb07'), c1, c2)
    mut('conv2 mode from capture+24054', bytes.fromhex('5c18fa40135e'), bytes.fromhex('5c18fa40145e'), c2, hl)
    mut('conv2 wrong compare 12->11', bytes.fromhex('a00cdc'), bytes.fromhex('a00bdc'), c2, hl)
    m = bytearray(patched); m[0x6035390d - BASE] = 39; out.append(('memset 40 -> 39', bytes(m)))
    m = bytearray(patched); struct.pack_into('<H', m, 0x603537f1 - BASE, 15488); out.append(('alloc back to 15488', bytes(m)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--no-mutations', action='store_true')
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    for k in ('bundle', 'labels', 'table_hex'):
        if k not in spec:
            sys.exit(f'spec lacks {k!r} (build with patches/bundles/build.py; merge with tools/merge_specs.py)')
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    # independent expectation: rebuild the table from the bundle JSON
    table, slots = BB.build_table(json.loads((ROOT / spec['bundle']).read_text() if not Path(spec['bundle']).is_absolute()
                                             else Path(spec['bundle']).read_text()), BB.load_recipes())
    tbl_ok = table.hex() == spec['table_hex'] and \
        patched[table_addr(spec) - BASE:table_addr(spec) - BASE + len(table)] == table
    in_spans, nchg = spans_check(spec, stock, patched)
    ok, results = run_all(stock, patched, spec, slots)
    results.insert(0, dict(test='F table in package == table rebuilt from bundle JSON', passed=tbl_ok))
    results.append(dict(test=f'F changed payload bytes ({nchg}) all inside edit spans', passed=in_spans))
    ok &= tbl_ok and in_spans
    for x in results:
        print(f"{'PASS' if x['passed'] else 'FAIL'}  {x['test']}" +
              ('' if x['passed'] else '  ' + json.dumps({k: v for k, v in x.items() if k not in ('test', 'passed')},
                                                         default=str)[:600]))
    mres = []
    if not a.no_mutations:
        for name, img in mutations(patched, spec):
            g, r = run_all(stock, img, spec, slots)
            failed = [x['test'] for x in r if not x['passed']]
            mres.append(dict(mutation=name, detected=not g, failing_tests=failed[:6], n_failing=len(failed)))
            print(f"{'PASS' if not g else 'FAIL'}  E mutation '{name}' detected by {len(failed)} test(s): {failed[:3]}")
        ok &= all(m['detected'] for m in mres)
    print(f"{'PASS' if ok else 'FAIL'}  overall; package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.edits), package=info, passed=ok, results=results, mutations=mres,
                                          scope='emulator only; synthetic fixtures; CPU code, not ISP/pixels; '
                                                'no camera contacted'), indent=1, default=str))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
