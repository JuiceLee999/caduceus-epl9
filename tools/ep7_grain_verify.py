#!/usr/bin/env python3
"""Emulator verification of a BUILT per-profile COLOR-grain package v0.4 (offline; emulator only; no camera).

Builds the package in memory from an edits.json (tools/build_package.build), decodes the
patched main payload and runs native code from the PATCHED image vs the STOCK image. Works on a
grain-only spec (a synthetic bundle table is injected) or on a merged spec (the real table is also used).

  T1 combiner selector 0x603b5200 over a key/kind/stage/effect matrix: identical result
     except key 11 + kind 0 + stage 0x0902 -> 32; stack and callee-saved regs intact.
  T2 work-list builder from 0x6035749f (real 0x6035739e/0x603573d3), per-profile cases: key 11 gets
     grain_mod on the development entry ONLY for marker 0xB2 + mode 11 + profile 1..4 + slot grain 1..3;
     every other case (no marker, wrong marker, mode 12, profile 0/5/255, grain 0/4/0xFF) is
     byte-identical to stock. Keys != 11 identical to stock.
  T6 (review v0.3 H1) job-type gate vs stock MONO: capture kinds 0x2001/0x2006 (both (206) values and both
     0x603ed45a results), 0x1008/0x1006 and others run through the stock mapper 0x603ea909 -> job type,
     plus a direct sweep of types. For each type and job class (job+11320 = 0 / 4): patched COLOR (key 11,
     grain slot) attaches grain iff stock MONO (key 12, full stock handler 0x6035778b) grains that job
     (single-pass modifier 0x60359e5e or the two-pass mask route). Class 4: patched list == stock MONO's
     with grain_mod in place of 0x60359e5e. No grain: patched == stock COLOR exactly.
  T3 request modifier vs stock 0x60359e5e (called with CALLS like 0x60356d72): valid slot -> stage 0x0902 +
     level byte = slot grain; invalid slot or kind 3 -> request untouched; returns 0; job untouched.
  T4 end to end: combiner config 0x603a013b on a COLOR request after the modifier: slot level L ->
     handler 32 with gain table[L-1], bank byte-identical to stock MONO key 12 + stage 0x0902; L = 0 -> stock.
     With the v0.16 grain boost (spec 'grain_boost'): COLOR gain = our table[L-1] (e.g. 220/600/1200) and the
     bank equals stock MONO 0x0902 except the gain word (+136).
  T8 (grain boost) handler 32/31 for every non-COLOR key (MONO 12, art 0x01010068, 0, 5, 10) x stage 0x0901/0x0902
     x level 0..3: bank, RAM counter, regs byte-identical to stock; COLOR with an erased (no) table -> stock.
  T5 changed bytes all inside edit spans.
  T7 (merged spec only) the real bundle table in the image: per COLOR slot, attach + level follow its grain byte.
"""
import argparse, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
import ep7_color_probe as PR  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402
import ep7_sdv3_env as SDV3  # noqa: E402  (SD loader v3: state RAM the --sd-v3 readers read)
execute = SDV3.wrap(execute)

BASE = 0x60020020
SEGS = [('code', 0x60340000, 0x603c0000, 'rx'), ('data', 0x60520000, 0x60540000, 'r'),
        ('gain', 0x604ec000, 0x604ed000, 'r'), ('tail', 0x6055e5b0, 0x6055e800, 'rx'),
        ('mapper', 0x603ea900, 0x603eaa00, 'rx'), ('evf0', 0x601e3800, 0x601e3a00, 'rx')]   # v0.22 grain C stubs
SEC1_LO, SEC1_HI = 0x60210800, 0x60211000
TABLE, SLOT, F_GRAIN = 0x60210900, 64, 24
EXT, MAGIC = 15488, 0xB2
JOB_SIZE = 15512
RAMCTR = 0xa27393f8
CALLER, STACK = 0x18000000, 0x18010000
CTX, REQ, BANKB, LIST, ENTRIES, JOB, OBJ = 0x1a000000, 0x1b000000, 0x1c000000, 0x1d000000, 0x1d001000, 0x1e000000, 0x1f000000
SEL, CFG, MOD_STOCK, MAPPER, ED45A = 0x603b5200, 0x603a013b, 0x60359e5e, 0x603ea909, 0x603ed45a
MASK_PASS, MASK_FINAL = 0x60359bc8, 0x60359cd8
WL_AFTER, WL_HASH = 0x603578bd, 0x603574a6
REGS0 = {'d2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}


def fixture_table(grains):
    """8 x 64-byte table; grains[i] = grain byte of slot i (COLOR1-4 = 0-3, MONO1-4 = 4-7)."""
    t = bytearray(8 * SLOT)
    for i, g in enumerate(grains):
        t[i * SLOT + F_GRAIN] = g
    return bytes(t)


def regions(main, table=None, extra=(), ed45a=0):
    s = lambda lo, hi: main[lo - BASE:hi - BASE]
    sec1 = bytearray(s(SEC1_LO, SEC1_HI))
    if table is not None:                       # None -> the image's own table (merged spec)
        sec1[TABLE - SEC1_LO:TABLE - SEC1_LO + len(table)] = table
    return ([Region(n, lo, s(lo, hi), p) for n, lo, hi, p in SEGS] +
            [Region('sec1', SEC1_LO, bytes(sec1), 'rx'),
             Region('ed45a', ED45A, bytes([0x80, ed45a, 0xdf, 0xb0, 0x14]), 'rx'),   # stub: mov ed45a,d0; ret [d2,a2,a3],20
             Region('ramctr', RAMCTR, struct.pack('<I', 0x1234), 'rw', True)] + list(extra))


def stack(words=None):
    b = bytearray(0x2000)
    for off, v in (words or {}).items():
        struct.pack_into('<I', b, 0x1800 + off, v)
    return Region('stack', STACK, bytes(b), 'rw', True)


def mem(r):
    return {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}


def regs_ok(r, stop):
    rr = r['registers']
    return (not r['fault'] and rr['pc'] == stop and rr['sp'] == STACK + 0x1800 and
            all(rr[k] == v for k, v in REGS0.items()))


def job_bytes(key=11, jtype=0, cls=4, ext=(1, 11, MAGIC)):
    j = bytearray(JOB_SIZE)
    struct.pack_into('<H', j, 20, jtype)
    struct.pack_into('<I', j, 11308, key)
    j[11320] = cls
    if ext is not None:
        j[EXT:EXT + 3] = bytes(ext)
    return j


def request(kind, stage, effect=0, level=0):
    r = bytearray(1884)
    r[8:12] = bytes([0, 0, 11, 0])
    struct.pack_into('<H', r, 12, stage)
    r[16] = kind
    r[1828] = level
    struct.pack_into('<H', r, 1838, effect)
    struct.pack_into('<H', r, 656, effect)
    return r


def caller_calls(target):   # 'calls d32' then nop: what 0x60356d72 does via calls (a2)
    return Region('caller', CALLER, b'\xfc\xff' + struct.pack('<i', target - CALLER) + b'\xcb', 'rx')


# ------------------------------------------------------------------ T1
def t1_selector(stock, patched, table):
    rows, ok = [], True
    for key in (0, 5, 11, 12, 0x01010078, 0x0101007c):
        for kind in (0, 3):
            for stage in (0, 0x0901, 0x0902, 0xf00f):
                for effect in (0, 0x0400, 0x0900, 0x0c00):
                    ctx = bytearray(128)
                    struct.pack_into('<I', ctx, 4, REQ)
                    struct.pack_into('<I', ctx, 52, key)
                    out = []
                    for main in (stock, patched):
                        rg = regions(main, table, [stack(), PR.caller(SEL, 0xa0, 12), Region('ctx', CTX, bytes(ctx), 'rw', True),
                                                   Region('req', REQ, bytes(request(kind, stage, effect)), 'rw', True)])
                        r = execute(rg, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CTX, **REGS0}, CALLER + 7, limit=5000)
                        m = mem(r)
                        out.append((r['registers']['d0'], regs_ok(r, CALLER + 7), m['ctx'], m['req']))
                    (s0, sok, sc, sr), (p0, pok, pc, pr) = out
                    want = 32 if (key == 11 and kind == 0 and stage == 0x0902) else s0
                    if GRAIN_C and key == 11 and kind == 0 and stage == 0x0901:
                        want = 31                     # v0.22: COLOR on the MONO mask route (as key 12)
                    good = sok and pok and p0 == want and sc == pc and sr == pr
                    ok &= good
                    if not good or want != s0:
                        rows.append(dict(key=hex(key), kind=kind, stage=hex(stage), effect=hex(effect),
                                         stock=s0, patched=p0, ok=good))
    return ok, rows


# ------------------------------------------------------------------ work list runner
def wl_run(main, table, key, job, stop=None):
    """Run the builder from the hook site. Default stop: WL_HASH for keys >= 12, else WL_AFTER.
    stop=WL_AFTER with key 12 runs the full stock MONO handler (0x6035778b)."""
    if stop is None:
        stop = WL_HASH if key >= 12 else WL_AFTER
    lst = bytearray(32)
    lst[4] = 1
    struct.pack_into('<I', lst, 16, ENTRIES)
    rg = regions(main, table, [stack({4: JOB, 8: JOB + 11308}), Region('list', LIST, bytes(lst), 'rw', True),
                               Region('entries', ENTRIES, bytes(12 * 16), 'rw', True),
                               Region('job', JOB, bytes(job), 'rw', True)])
    regs = {'pc': 0x6035749f, 'sp': STACK + 0x1800, 'd2': key, 'd3': 0x3333, 'a2': JOB + 4, 'a3': LIST}
    r = execute(rg, regs, stop, limit=20000)
    rr, m = r['registers'], mem(r)
    good = (not r['fault'] and rr['pc'] == stop and rr['sp'] == STACK + 0x1800 and
            rr['a2'] == JOB + 4 and rr['a3'] == LIST)
    if stop == WL_HASH or key < 12:
        good &= rr['d2'] == key and rr['d3'] == 0x3333
    n = struct.unpack_from('<H', m['list'], 0)[0]
    ents = [struct.unpack_from('<III', m['entries'], 12 * i) for i in range(min(n, 16))]
    return dict(ok=good, fault=r['fault'], list=m['list'], entries=m['entries'], ents=ents,
                pending=struct.unpack_from('<II', m['list'], 8), job_same=m['job'] == bytes(job))


def mod0(w):
    return struct.unpack_from('<I', w['entries'], 4)[0]


def has_mod(w, mod):
    return mod0(w) == mod or any(e[1] == mod for e in w['ents'])


def stock_mono_grains(w):
    return mod0(w) == MOD_STOCK or any(e[0] == MASK_PASS for e in w['ents']) or w['pending'][0] == MASK_FINAL


# ------------------------------------------------------------------ T2
T2_CASES = [  # (label, ext bytes (profile, mode, marker) or None, slot grain bytes, expected level)
    ('COLOR1 grain 1', (1, 11, MAGIC), [1, 0, 0, 0], 1),
    ('COLOR2 grain 2', (2, 11, MAGIC), [0, 2, 0, 0], 2),
    ('COLOR4 grain 3', (4, 11, MAGIC), [0, 0, 0, 3], 3),
    ('COLOR3 slot off (others on)', (3, 11, MAGIC), [3, 3, 0, 3], 0),
    ('no marker (ext all 0)', (0, 0, 0), [3] * 8, 0),
    ('ext absent (zero)', None, [3] * 8, 0),
    ('wrong marker 0xB3', (1, 11, 0xB3), [3] * 8, 0),
    ('mode 12 (MONO)', (1, 12, MAGIC), [3] * 8, 0),
    ('profile 0', (0, 11, MAGIC), [3] * 8, 0),
    ('profile 5 (MONO1 slot)', (5, 11, MAGIC), [3] * 8, 0),
    ('profile 255', (255, 11, MAGIC), [3] * 8, 0),
    ('grain 4 (out of range)', (1, 11, MAGIC), [4, 0, 0, 0], 0),
    ('grain 0xFF (erased table)', (2, 11, MAGIC), [0xff] * 8, 0),
]
T2_CASES_5 = [c for c in T2_CASES if not c[0].startswith('grain 4')] + [   # v0.21: slot grain 0..5
    ('COLOR1 grain 4', (1, 11, MAGIC), [4, 0, 0, 0], 4),
    ('COLOR3 grain 5', (3, 11, MAGIC), [0, 0, 5, 0], 5),
    ('grain 6 (out of range)', (1, 11, MAGIC), [6, 0, 0, 0], 0),
]
LEVELS = 3
GRAIN_C = False


def cases():
    return T2_CASES_5 if LEVELS == 5 else T2_CASES


def t2_worklist(stock, patched, mod_addr):
    res, ok = [], True
    for label, ext, grains, lv in cases():
        table = fixture_table(grains)
        for key in ((0, 5, 10, 11, 12, 0x01010068) if label == 'COLOR1 grain 1' else (11,)):
            job = job_bytes(key=key, ext=ext)
            s, p = wl_run(stock, table, key, job), wl_run(patched, table, key, job)
            if key == 11 and lv:
                exp_e = bytearray(s['entries'])
                struct.pack_into('<I', exp_e, 4, mod_addr)
                exp_l = bytearray(s['list'])
                exp_l[7] = 0                   # attach consumed the modifier slot
                same = p['list'] == bytes(exp_l) and p['entries'] == bytes(exp_e) and s['pending'] == (0x60356d7b, 0x60356cc6)
            else:
                same = s['list'] == p['list'] and s['entries'] == p['entries'] and not has_mod(p, mod_addr)
            good = s['ok'] and p['ok'] and same and p['job_same']
            ok &= good
            res.append(dict(case=label, key=hex(key), grain_attached=has_mod(p, mod_addr), expected=bool(key == 11 and lv),
                            ok=good))
    return ok, res


# ------------------------------------------------------------------ T6 (H1)
CAPTURE_KINDS = [(0x2001, 1, 0), (0x2001, 2, 0), (0x2006, 1, 0), (0x2006, 2, 0), (0x2001, 1, 1), (0x2006, 2, 1),
                 (0x1008, 0, 0), (0x1006, 0, 0), (0x1001, 0, 0), (0x3001, 0, 0), (0x0000, 0, 0)]
EXTRA_TYPES = [0x0000, 0x0010, 0x0020, 0x0030, 0x0040, 0x0050, 0x0080, 0x00f0, 0x0100, 0x0101, 0x0110, 0x0120,
               0x0130, 0x0200, 0x0210, 0x0300, 0x0f00, 0x1000, 0x1100, 0x1110, 0x2000, 0xffff]


def map_kind(main, kind, f206, ed45a):
    obj = bytearray(256)
    struct.pack_into('<H', obj, 194, kind)
    struct.pack_into('<H', obj, 206, f206)
    struct.pack_into('<I', obj, 28, OBJ + 128)
    rg = regions(main, fixture_table([0] * 8), [stack(), PR.caller(MAPPER, 0xa0, 12),
                                                Region('obj', OBJ, bytes(obj), 'rw', True)], ed45a=ed45a)
    r = execute(rg, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': OBJ, **REGS0}, CALLER + 7, limit=2000)
    return regs_ok(r, CALLER + 7), r['registers']['d0'] & 0xffff


def t6_jobtype(stock, patched, mod_addr):
    res, ok = [], True
    types = []
    for kind, f206, ed in CAPTURE_KINDS:
        sg, st = map_kind(stock, kind, f206, ed)
        pg, pt = map_kind(patched, kind, f206, ed)
        good = sg and pg and st == pt
        ok &= good
        types.append((f'capture kind {kind:#06x} (206)={f206} 0x603ed45a->{ed}', st))
        res.append(dict(capture_kind=hex(kind), f206=f206, ed45a=ed, job_type=hex(st), mapper_ok=good, ok=good))
    for t in EXTRA_TYPES:
        types.append((f'type {t:#06x}', t))
    table = fixture_table([2, 2, 2, 2])
    seen = {True: 0, False: 0}
    for label, t in types:
        gated = (t & 0xf0) in (0x10, 0x20, 0x40) or (t & 0xf00) == 0x100
        for cls in (0, 4):
            mono = wl_run(stock, table, 12, job_bytes(key=12, jtype=t, cls=cls), stop=WL_AFTER)
            col_s = wl_run(stock, table, 11, job_bytes(key=11, jtype=t, cls=cls))
            col_p = wl_run(patched, table, 11, job_bytes(key=11, jtype=t, cls=cls))
            mono_g, pat_g = stock_mono_grains(mono), has_mod(col_p, mod_addr)
            good = mono['ok'] and col_s['ok'] and col_p['ok'] and mono_g == pat_g == (not gated)
            if pat_g and cls:            # single-pass: same list as stock MONO, our modifier in place of 0x60359e5e
                exp_e = bytearray(mono['entries'])
                struct.pack_into('<I', exp_e, 4, mod_addr)
                good &= col_p['entries'] == bytes(exp_e) and col_p['list'] == mono['list']
            if not pat_g:                # no grain: exactly stock COLOR
                good &= col_p['list'] == col_s['list'] and col_p['entries'] == col_s['entries']
            seen[gated] += 1
            ok &= good
            res.append(dict(job=label, type=hex(t), job_class=cls, stock_mono_grain=mono_g, patched_color_grain=pat_g,
                            mono_route=('two-pass mask' if any(e[0] == MASK_PASS for e in mono['ents']) else
                                        'single-pass 0x0902' if mono_g else 'default (no grain)'),
                            mono_fault=mono['fault'], ok=good))
    ok &= seen[True] > 0 and seen[False] > 0
    return ok, res


# ------------------------------------------------------------------ T3
def t3_modifier(stock, patched, mod_addr):
    res, ok = [], True
    for label, ext, grains, lv in cases():
        table = fixture_table(grains)
        for kind in (0, 3):
            for lv_in in (0, 2):
                job = job_bytes(ext=ext)
                out = []
                for main, fn in ((stock, MOD_STOCK), (patched, mod_addr)):
                    rg = regions(main, table, [stack(), caller_calls(fn), Region('req', REQ, bytes(request(kind, 0, 0x0400, lv_in)), 'rw', True),
                                               Region('job', JOB, bytes(job), 'rw', True)])
                    r = execute(rg, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': JOB, 'a1': REQ, **REGS0}, CALLER + 7, limit=1000)
                    m = mem(r)
                    out.append((regs_ok(r, CALLER + 7), r['registers']['d0'], m['req'], m['job'] == bytes(job)))
                (sg, s0, sr, sj), (pg, p0, pr, pj) = out
                base = request(kind, 0, 0x0400, lv_in)
                exp = bytearray(base)
                if kind == 0 and lv:
                    struct.pack_into('<H', exp, 12, 0x0902)
                    exp[1828] = lv
                stock_exp = bytearray(base)
                if kind == 0:
                    struct.pack_into('<H', stock_exp, 12, 0x0902)
                good = sg and pg and sj and pj and s0 == p0 == 0 and pr == bytes(exp) and sr == bytes(stock_exp)
                ok &= good
                res.append(dict(case=label, kind=kind, level_in=lv_in, ok=good,
                                changed_offsets=[i for i in range(len(pr)) if pr[i] != base[i]]))
    return ok, res


# ------------------------------------------------------------------ T4
def t4_combiner(stock, patched, mod_addr, boost=None):
    res, ok = [], True
    gains = struct.unpack_from('<3H', stock, 0x604ec0d4 - BASE)
    if boost:   # COLOR gains = the boost table in the PATCHED image; must equal the spec's color_gains
        gains = struct.unpack_from(f'<{LEVELS}H', patched, int(boost['color_table'], 16) - BASE)
        if list(gains) != boost['color_gains']:
            return False, [dict(check='image boost table == spec color_gains', image=gains, spec=boost['color_gains'], ok=False)]
    for lv in range(LEVELS + 1):
        table = fixture_table([lv, 0, 0, 0])
        out = []
        for name, main in (('stock', stock), ('patched', patched), ('stock_mono_0902', stock)):
            req = request(0, 0, 0x0400, 0)
            if name == 'stock_mono_0902':   # reference: stock MONO (key 12) single-pass route, same level (4/5: gain 0)
                req = request(0, 0x0902, 0x0400, lv)
                req[8:12] = bytes([0, 0, 12, 0])
            if name == 'patched':
                rg = regions(main, table, [stack(), caller_calls(mod_addr), Region('req', REQ, bytes(req), 'rw', True),
                                           Region('job', JOB, bytes(job_bytes()), 'rw', True)])
                r = execute(rg, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': JOB, 'a1': REQ, **REGS0}, CALLER + 7, limit=1000)
                req = mem(r)['req']
            ctx = bytearray(128)
            struct.pack_into('<I', ctx, 4, REQ)
            struct.pack_into('<I', ctx, 8, BANKB)
            struct.pack_into('<I', ctx, 52, 12 if name == 'stock_mono_0902' else 11)
            rg = regions(main, table, [stack(), PR.caller(CFG, 0xf0, 20), Region('ctx', CTX, bytes(ctx), 'rw', True),
                                       Region('req', REQ, bytes(req), 'rw', True),
                                       Region('bank', BANKB, bytes(7364 + 256), 'rw', True)])
            r = execute(rg, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CTX, **REGS0}, CALLER + 7, limit=20000)
            m = mem(r)
            bank = m['bank'][7364:7364 + 184]
            out.append(dict(ok=regs_ok(r, CALLER + 7), gain136=struct.unpack_from('<I', bank, 136)[0],
                            w172=hex(struct.unpack_from('<I', bank, 172)[0]),
                            ramctr=hex(struct.unpack_from('<I', m['ramctr'], 0)[0]), bank=bank.hex()))
        s, p, mref = out
        if lv:
            pb, mb = bytearray.fromhex(p['bank']), bytearray.fromhex(mref['bank'])
            pb[136:140] = mb[136:140] = b'\0\0\0\0'      # gain word compared separately
            good = (s['ok'] and p['ok'] and pb == mb and (boost or p['bank'] == mref['bank']) and p['gain136'] == gains[lv - 1] and
                    p['w172'] == '0x80001235' and p['ramctr'] == '0x1235' and s['ramctr'] == '0x1234')
        else:
            good = s['ok'] and p['ok'] and p['bank'] == s['bank'] and p['ramctr'] == s['ramctr'] == '0x1234'
        ok &= good
        res.append(dict(slot_grain=lv, expected_gain=gains[lv - 1] if lv else None, patched_gain=p['gain136'],
                        stock_mono_0902_gain=mref['gain136'],
                        patched_bank_equals_stock_mono_0902=(p['bank'] == mref['bank']) if lv else None,
                        patched_equals_stock=p['bank'] == s['bank'], ok=good))
    return ok, res


# ------------------------------------------------------------------ T8 (grain boost: non-COLOR untouched)
MASKD = 0x1a100000


def cfg_run(main, table, key, stage, lv):
    req = request(0, stage, 0x0400, lv)
    struct.pack_into('<I', req, 276, MASKD)            # mask descriptor for handler 31 (stage 0x0901)
    struct.pack_into('<HHH', req, 276 + 10, 3, 1, 2)   # (10) row, (14) divisor != 0, (20) column
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, REQ)
    struct.pack_into('<I', ctx, 8, BANKB)
    struct.pack_into('<I', ctx, 52, key)
    rg = regions(main, table, [stack(), PR.caller(CFG, 0xf0, 20), Region('ctx', CTX, bytes(ctx), 'rw', True),
                               Region('req', REQ, bytes(req), 'rw', True),
                               Region('bank', BANKB, bytes(7364 + 256), 'rw', True),
                               Region('maskd', MASKD, bytes(range(256)) * 2, 'r')])
    r = execute(rg, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CTX, **REGS0}, CALLER + 7, limit=20000)
    m = mem(r)
    return dict(ok=regs_ok(r, CALLER + 7), bank=m['bank'], ramctr=m['ramctr'], req=m['req'], ctx=m['ctx'])


def t8_boost_isolation(stock, patched, mod_addr):
    res, ok = [], True
    table = fixture_table([3, 3, 3, 3, 3, 3, 3, 3])
    for key in (12, 0x01010068, 0, 5, 10):
        for stage in (0x0901, 0x0902):
            for lv in range(8):         # 4..7: stock gain-0 path (hook C) must stay stock for non-COLOR keys
                s, p = cfg_run(stock, table, key, stage, lv), cfg_run(patched, table, key, stage, lv)
                good = s['ok'] and p['ok'] and all(s[k] == p[k] for k in ('bank', 'ramctr', 'req', 'ctx'))
                ok &= good
                res.append(dict(key=hex(key), stage=hex(stage), level=lv, gain136=struct.unpack_from('<I', p['bank'], 7364 + 136)[0], ok=good))
    # COLOR job with no table (erased 0xFF, as without the bundles table): modifier leaves the request alone -> stock
    erased = b'\xff' * (8 * SLOT)
    for prof in (1, 2, 3, 4):
        out = []
        for main in (stock, patched):
            rg = regions(main, erased, [stack(), caller_calls(mod_addr) if main is patched else caller_calls(MOD_STOCK),
                                        Region('req', REQ, bytes(request(0, 0, 0x0400, 0)), 'rw', True),
                                        Region('job', JOB, bytes(job_bytes(ext=(prof, 11, MAGIC))), 'rw', True)])
            r = execute(rg, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': JOB, 'a1': REQ, **REGS0}, CALLER + 7, limit=1000)
            out.append(mem(r)['req'])
        untouched = out[1] == bytes(request(0, 0, 0x0400, 0))
        s, p = cfg_run(stock, erased, 11, 0, 0), cfg_run(patched, erased, 11, 0, 0)
        good = untouched and s['ok'] and p['ok'] and all(s[k] == p[k] for k in ('bank', 'ramctr', 'req'))
        ok &= good
        res.append(dict(case=f'erased table, COLOR{prof}', request_untouched=untouched, config_equals_stock=good, ok=good))
    return ok, res


# ------------------------------------------------------------------ T7 (merged: real table)
def t7_real_table(stock, patched, mod_addr, spec):
    table = bytes.fromhex(spec['table_hex'])
    img = patched[TABLE - BASE:TABLE - BASE + len(table)]
    res, ok = [dict(check='image table == spec table_hex', ok=img == table)], img == table
    for prof in (1, 2, 3, 4):
        g = table[(prof - 1) * SLOT + F_GRAIN]
        lv = g if 1 <= g <= LEVELS else 0
        job = job_bytes(ext=(prof, 11, MAGIC))
        s, p = wl_run(stock, None, 11, job), wl_run(patched, None, 11, job)
        att = has_mod(p, mod_addr)
        rg = regions(patched, None, [stack(), caller_calls(mod_addr), Region('req', REQ, bytes(request(0, 0, 0x0400, 0)), 'rw', True),
                                     Region('job', JOB, bytes(job), 'rw', True)])
        r = execute(rg, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': JOB, 'a1': REQ, **REGS0}, CALLER + 7, limit=1000)
        rq = mem(r)['req']
        lv_ok = (rq[1828] == lv and struct.unpack_from('<H', rq, 12)[0] == 0x0902) if lv else rq == bytes(request(0, 0, 0x0400, 0))
        good = s['ok'] and p['ok'] and att == bool(lv) and regs_ok(r, CALLER + 7) and lv_ok
        ok &= good
        res.append(dict(profile=f'COLOR{prof}', slot_grain=g, grain_attached=att, level_written=rq[1828], ok=good))
    return ok, res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    mod_addr = int(spec['symbols']['grain_mod'], 16)
    global LEVELS, GRAIN_C
    LEVELS = spec.get('grain_boost', {}).get('levels', 3)
    GRAIN_C = 'grain_c' in spec
    import numpy as np
    idx = np.nonzero(np.frombuffer(stock, np.uint8) != np.frombuffer(patched, np.uint8))[0] + BASE
    spans = [(int(e['addr'], 16), int(e['addr'], 16) + len(bytes.fromhex(e['new']))) for e in spec['edits']]
    in_spans = bool(all(any(s <= x < t for s, t in spans) for x in idx))
    results = {}
    tests = [('T1 selector', lambda: t1_selector(stock, patched, fixture_table([2] * 4))),
             ('T2 work list (per-profile)', lambda: t2_worklist(stock, patched, mod_addr)),
             ('T6 job-type gate vs stock MONO (H1)', lambda: t6_jobtype(stock, patched, mod_addr)),
             ('T3 modifier (per-profile)', lambda: t3_modifier(stock, patched, mod_addr)),
             ('T4 combiner config', lambda: t4_combiner(stock, patched, mod_addr, spec.get('grain_boost')))]
    if 'grain_boost' in spec:
        tests.append(('T8 boost isolation (non-COLOR keys, erased table)', lambda: t8_boost_isolation(stock, patched, mod_addr)))
    if 'table_hex' in spec:
        tests.append(('T7 real bundle table (merged)', lambda: t7_real_table(stock, patched, mod_addr, spec)))
    for name, fn in tests:
        ok, rows = fn()
        results[name] = dict(passed=ok, rows=rows)
        print(f"{'PASS' if ok else 'FAIL'} {name} ({len(rows)} rows)")
        for row in rows:
            if not row.get('ok', True) or name.startswith('T7'):
                print('     ', row)
    results['T5 spans'] = dict(passed=in_spans, changed=len(idx))
    print(f"{'PASS' if in_spans else 'FAIL'} T5 changed bytes ({len(idx)}) all inside {len(spans)} edit spans; package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(scope='emulator only; synthetic fixtures; no ISP pixels; no camera',
                                          package=info, results=results), indent=1, default=str))
    sys.exit(0 if all(v['passed'] for v in results.values()) else 1)


if __name__ == '__main__':
    main()
