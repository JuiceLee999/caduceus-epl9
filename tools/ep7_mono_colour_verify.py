#!/usr/bin/env python3
"""Emulator verification of the MONO-colour patch on a BUILT package (offline; emulator only; no camera).

Builds the package in memory from a merged edits spec (must contain patches/bundles v0.2 and
patches/mono_colour, e.g. releases/v0.3 + generated/mono_colour via tools/merge_specs.py), decodes
three main payloads and runs native code from them on identical fixtures:
  patched  = the package's main payload (exact bytes);
  base     = the same spec without the mono_colour edits (e.g. plain v0.3);
  stock    = the restore payload.
Bundle tables other than the package's own are written into emulator RAM only.

  S  selector 0x603b0252 (whole function, incl. builder / general builder):
     S1 colour slot (MONO1-4, 4 sat sets, H/L on and off): output, context, job and ALL registers at
        return == a mode-11 run whose COLOR slot has the same H/L and whose request sat == slot sat;
        H/L == rows derived independently from the slot values; request+1816 junk is ignored.
     S2 not a colour slot (profile 0/5/255, marker absent/wrong, ext mode 11/0, wrong callback,
        foreign parent, colour 0/2/0xFF, sat +6/-6/-128, H/L +8 with flag, alt default table, the
        package's own table): byte-identical to STOCK mono (output, context, job, all registers),
        on a hostile table with all four MONO slots set to colour.
     S3 mode 11 (COLOR1-4 x sats, real and hostile table) == base; modes 1/5 == stock.
  C  chroma stage 0x603b132a: colour slot -> out+76, output, context, job, live stack == mode-11 run
     (0) for every tone and both request+1800 values; registers == mode-11 run except a1/LIR/LAR,
     which the re-issued stock tone lookup leaves for key 12 (never read by the caller); non-colour -> == stock (grey 0x00808001 / toning vectors) incl. registers
     (MDR too); mode 11 == stock.
  P  packer segment 0x60353db7..0x60353de9: colour slot -> filter/tone (params+5528/5529) = 0, merge
     skipped, nothing else written, registers == stock mode-11 run except d0/psw; non-colour -> ==
     stock incl. registers; mode 11 == stock.
  R  the package's own table: every MONO slot with colour == 1 matches its mode-11 reference, every
     other MONO slot == stock.
  X  static: no branch / loop / abs32 reference into the interior of the three hook spans; changed
     payload bytes all inside edit spans; patch requires the bundles edits.
  E  mutations of the patched payload: each must make S/C/P FAIL.

Usage: tools/ep7_mono_colour_verify.py SPEC.json [--json out.json] [--no-mutations]
"""
import argparse, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
import ep7_color_probe as PR  # noqa: E402
import ep7_verify_bundles as VB  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402
import ep7_sdv3_env as SDV3  # noqa: E402  (SD loader v3: state RAM the --sd-v3 readers read)
execute = SDV3.wrap(execute)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BB = VB.BB                                              # patches/bundles/build.py
MC = _load('ep7_mono_colour_build', ROOT / 'patches/mono_colour/build.py')
BASE = 0x60020020
CODE_LO, CODE_HI = 0x603a0000, 0x603c0000
DATA_LO, DATA_HI = 0x604e0000, 0x60540000
T1_LO, T1_HI = 0x602108ec, 0x60211000
T7_LO, T7_HI = MC.TAIL_LO, MC.TAIL_HI
T2_LO, T2_HI = 0x6055e5b0, 0x6055e800          # section-2 tail: SD loader v3 accessor
CALLER, STACK = 0x18000000, 0x18010000
OUTPUT, CONTEXT, JOB = 0x19000000, 0x1a000000, 0x1b000000
NEW_SIZE = BB.JOB_SIZE + BB.EXT
REQ = BB.REQ_IN_JOB
REGS = VB.REGS_ALL
SATS = ([0] * 12, [3, -2, 0, 1, 0, 0, -5, 0, 2, 0, 0, 4], [5] * 12, [-5, 4, -3, 2, -1, 0, 1, -2, 3, -4, 5, -5])
TABLE = BB.BUNDLE_TABLE
CHROMA_FN = 0x603b132a
CHROMA_LOOKUP_REGS = ('a1', 'lir', 'lar')
SP_OFF = 0x1800                                          # sp at entry/return, offset in the stack region


def above_sp(mem):
    """Live stack (at/above sp at the stop point). Below sp is dead: our frames may leave data there."""
    return mem['stack'][SP_OFF:]
JUNK_SAT = bytes([0x7f, 0x80, 0x55, 0xaa] * 3)


def sl(img, lo, hi):
    return img[lo - BASE:hi - BASE]


def with_table(img, table):
    m = bytearray(img)
    m[TABLE - BASE:TABLE - BASE + len(table)] = table
    return bytes(m)


def regs_of(r):
    return {k: r['registers'][k] for k in REGS}


def common_regions(img):
    return [Region('code', CODE_LO, sl(img, CODE_LO, CODE_HI), 'rx'),
            Region('data', DATA_LO, sl(img, DATA_LO, DATA_HI), 'r'),
            Region('tail1', T1_LO, sl(img, T1_LO, T1_HI), 'rx'),
            Region('tail7', T7_LO, sl(img, T7_LO, T7_HI), 'rx'),
            Region('tail2', T2_LO, sl(img, T2_LO, T2_HI), 'rx')]   # SD loader v3 accessor (--sd-v3 readers)


def make_job(*, mode=12, profile=1, ext_mode=None, magic=BB.MAGIC, sat=None, b1800=0, tone=0, filt=0,
             callback=PR.CALLBACK, record_index=5, foreign_parent=False):
    job = bytearray(NEW_SIZE)
    rec = BB.RECORDS_IN_JOB + BB.REC_STRIDE * record_index
    struct.pack_into('<I', job, REQ, callback)
    struct.pack_into('<I', job, REQ + 4, JOB + rec)
    struct.pack_into('<I', job, rec, JOB + (64 if foreign_parent else 0))
    job[REQ + 8:REQ + 12] = bytes([0, 0, mode, 0])
    job[REQ + 1816:REQ + 1828] = JUNK_SAT if sat is None else struct.pack('<12b', *sat)
    job[REQ + 1800], job[REQ + 1802], job[REQ + 1803] = b1800, filt, tone
    job[BB.EXT_PROFILE], job[BB.EXT_MODE], job[BB.EXT_MAGIC] = profile, mode if ext_mode is None else ext_mode, magic
    return job


INIT = {'d0': 0xd0d0, 'd1': 0xd1d1, 'a1': 0xa1a1, 'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}


# ------------------------------------------------------------------ S selector
def sel_run(img, **kw):
    job = make_job(**kw)
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, JOB + REQ)
    struct.pack_into('<I', ctx, 12, OUTPUT)
    struct.pack_into('<I', ctx, 60, 2)
    regions = [PR.caller(PR.SELECTOR, 0xf0, 20), Region('stack', STACK, bytes(0x2000), 'rw', True),
               Region('job', JOB, bytes(job), 'rw', True), Region('ctx', CONTEXT, bytes(ctx), 'rw', True),
               Region('out', OUTPUT, bytes(5212), 'rw', True)] + common_regions(img)
    r = execute(regions, dict(INIT, pc=CALLER, sp=STACK + 0x1800, a0=CONTEXT), CALLER + 7, limit=80000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    rr = r['registers']
    ok = (not r['fault'] and rr['pc'] == CALLER + 7 and rr['sp'] == STACK + 0x1800 and
          all(rr[k] == INIT[k] for k in ('d2', 'd3', 'a2', 'a3')))
    mem['job_unchanged'] = mem['job'] == bytes(job)
    return ok, mem, r


def slot_table(base_table, slots):
    """slots: {slot_index: dict(colour, sat, hue, light, hl)} written over base_table."""
    t = bytearray(base_table)
    for s, v in slots.items():
        o = 64 * s
        t[o:o + 64] = bytes(64)
        t[o:o + 12] = struct.pack('<12b', *v.get('hue', [0] * 12))
        t[o + 12:o + 24] = struct.pack('<12b', *v.get('light', [0] * 12))
        t[o + 31] = (BB.FLAG_HL if v.get('hl') else 0) | (BB.FLAG_RENDER_COLOUR if v.get('colour') == 1 else 0)
        t[o + MC.COLOUR_OFF] = v.get('colour', 0) & 0xff
        t[o + MC.SAT_OFF:o + MC.SAT_OFF + 12] = bytes(x & 0xff for x in v.get('sat', [0] * 12))
    return bytes(t)


def mono_slots():
    """Four valid colour MONO slots with distinct values (MONO4 without H/L)."""
    out = {}
    for i in range(4):
        out[4 + i] = dict(colour=1, sat=SATS[i], hl=(i != 3),
                          hue=[((i * 3 + k) % 15) - 7 for k in range(12)],
                          light=[((i * 5 + 2 * k) % 15) - 7 for k in range(12)])
    return out


def ref_table(base_table, mono):
    """Mode-11 reference: COLOR slot p-1 gets MONO p's hue/light and H/L flag."""
    return slot_table(base_table, {s - 4: dict(hue=v['hue'], light=v['light'], hl=v['hl']) for s, v in mono.items()})


def sel_colour_case(patched, base_table, mono, p, sat):
    m = {k: dict(v) for k, v in mono.items()}
    m[3 + p]['sat'] = sat
    img_c = with_table(patched, slot_table(base_table, m))
    img_r = with_table(patched, ref_table(base_table, m))
    ok_c, m_c, r_c = sel_run(img_c, mode=12, profile=p)                    # request+1816 = junk
    ok_r, m_r, r_r = sel_run(img_r, mode=11, profile=p, sat=sat)
    v = m[3 + p]
    recs = PR.records(m_c['out'])
    if v['hl']:
        exp = BB.native_rows(v['hue'], v['light'])
        hl = all(recs[i]['hue'] == exp[i][0] and recs[i]['light'] == exp[i][1] for i in range(12))
    else:
        hl = True
    regd = {k: (hex(r_r['registers'][k]), hex(r_c['registers'][k])) for k in REGS
            if r_r['registers'][k] != r_c['registers'][k]}
    good = (ok_c and ok_r and m_c['out'] == m_r['out'] and m_c['ctx'] == m_r['ctx'] and not regd and hl and
            m_c['job_unchanged'] and m_r['job_unchanged'] and m_c['out'] != sel_run(patched, mode=12, profile=p)[1]['out'])
    return good, dict(out_eq=m_c['out'] == m_r['out'], ctx_eq=m_c['ctx'] == m_r['ctx'], hl=hl, regdiff=regd,
                      insns=(r_r['completed'], r_c['completed']), fault=r_c['fault'])


def hostile(base_table):
    return slot_table(base_table, mono_slots())


def breaking_cases():
    """(name, fixture kwargs, table edit fn or None) -> must equal stock mono."""
    def tedit(slot, off, val):
        def f(t):
            t = bytearray(t)
            t[64 * slot + off] = val & 0xff
            return bytes(t)
        return f
    return [('profile 0', dict(profile=0), None), ('profile 5', dict(profile=5), None),
            ('profile 255', dict(profile=255), None), ('marker absent', dict(profile=1, magic=0), None),
            ('marker wrong', dict(profile=2, magic=0xB3), None), ('ext mode 11 (request 12)', dict(profile=1, ext_mode=11), None),
            ('ext mode 0', dict(profile=3, ext_mode=0), None),
            ('wrong callback', dict(profile=1, callback=PR.CALLBACK + 1), None),
            ('foreign parent', dict(profile=2, foreign_parent=True), None),
            ('MONO1 colour 0', dict(profile=1), tedit(4, MC.COLOUR_OFF, 0)),
            ('MONO2 colour 2', dict(profile=2), tedit(5, MC.COLOUR_OFF, 2)),
            ('MONO3 colour 0xFF', dict(profile=3), tedit(6, MC.COLOUR_OFF, 0xff)),
            ('MONO1 sat[0] +6', dict(profile=1), tedit(4, MC.SAT_OFF, 6)),
            ('MONO2 sat[11] -6', dict(profile=2), tedit(5, MC.SAT_OFF + 11, -6)),
            ('MONO4 sat[5] -128', dict(profile=4), tedit(7, MC.SAT_OFF + 5, -128)),
            ('MONO3 hue[4] +8 (H/L on)', dict(profile=3), tedit(6, 4, 8)),
            ('MONO1 light[11] -8 (H/L on)', dict(profile=1), tedit(4, 23, -8)),
            ('MONO2 tone 3 filter 2, colour 0', dict(profile=2, tone=3, filt=2), tedit(5, MC.COLOUR_OFF, 0)),
            ('alt default table (1800=1), profile 0', dict(profile=0, b1800=1), None)]


def check_selector(stock, base, patched, base_table):
    res, ok = [], True
    mono = mono_slots()
    for p in (1, 2, 3, 4):
        for sat in SATS:
            good, info = sel_colour_case(patched, base_table, mono, p, sat)
            ok &= good
            res.append(dict(test=f'S1 MONO{p} colour sat={sat[:3]}.. hl={mono[3 + p]["hl"]} == mode-11 ref',
                            passed=good, **info))
    hos = hostile(base_table)
    for name, kw, te in breaking_cases():
        img = with_table(patched, te(hos) if te else hos)
        ok_s, m_s, r_s = sel_run(stock, mode=12, **kw)
        ok_p, m_p, r_p = sel_run(img, mode=12, **kw)
        good = ok_s and ok_p and m_s['out'] == m_p['out'] and m_s['ctx'] == m_p['ctx'] and \
            m_s['job'] == m_p['job'] and regs_of(r_s) == regs_of(r_p) and above_sp(m_s) == above_sp(m_p)
        ok &= good
        res.append(dict(test=f'S2 {name} -> stock mono', passed=good, out_eq=m_s['out'] == m_p['out'],
                        regdiff={k: (hex(r_s['registers'][k]), hex(r_p['registers'][k])) for k in REGS
                                 if r_s['registers'][k] != r_p['registers'][k]}))
    for tname, tb in (('real table', base_table), ('hostile table', hos)):
        for p in (1, 2, 3, 4):
            for sat in (SATS[1], SATS[3]):
                ok_b, m_b, r_b = sel_run(with_table(base, tb), mode=11, profile=p, sat=sat)
                ok_p, m_p, r_p = sel_run(with_table(patched, tb), mode=11, profile=p, sat=sat)
                good = ok_b and ok_p and m_b['out'] == m_p['out'] and m_b['ctx'] == m_p['ctx'] and \
                    regs_of(r_b) == regs_of(r_p) and m_b['job'] == m_p['job']
                ok &= good
                res.append(dict(test=f'S3 mode 11 COLOR{p} {tname} sat={sat[:2]}.. == base', passed=good))
    for mode in (1, 5):
        ok_s, m_s, r_s = sel_run(stock, mode=mode, profile=1, sat=SATS[1])
        ok_p, m_p, r_p = sel_run(with_table(patched, hos), mode=mode, profile=1, sat=SATS[1])
        good = ok_s and ok_p and m_s['out'] == m_p['out'] and regs_of(r_s) == regs_of(r_p)
        ok &= good
        res.append(dict(test=f'S3 mode {mode} == stock', passed=good))
    return ok, res


# ------------------------------------------------------------------ C chroma stage
def chroma_run(img, **kw):
    job = make_job(**kw)
    mode = kw.get('mode', 12)
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, JOB + REQ)
    struct.pack_into('<I', ctx, 12, OUTPUT)
    struct.pack_into('<I', ctx, 52, mode)
    struct.pack_into('<I', ctx, 60, 2)
    out = bytearray(5212)
    struct.pack_into('<I', out, 76, 0xdeadbeef)
    regions = [PR.caller(CHROMA_FN, 0xb0, 20), Region('stack', STACK, bytes(0x2000), 'rw', True),
               Region('job', JOB, bytes(job), 'rw', True), Region('ctx', CONTEXT, bytes(ctx), 'rw', True),
               Region('out', OUTPUT, bytes(out), 'rw', True)] + common_regions(img)
    r = execute(regions, dict(INIT, pc=CALLER, sp=STACK + 0x1800, a0=CONTEXT), CALLER + 7, limit=20000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    mem['job_unchanged'] = mem['job'] == bytes(job)
    rr = r['registers']
    ok = (not r['fault'] and rr['pc'] == CALLER + 7 and rr['sp'] == STACK + 0x1800 and
          all(rr[k] == INIT[k] for k in ('d2', 'a2', 'a3')))
    return ok, mem, r, struct.unpack_from('<I', mem['out'], 76)[0]


def check_chroma(stock, base, patched, base_table):
    res, ok = [], True
    hos = hostile(base_table)
    img = with_table(patched, hos)
    for p in (1, 2, 3, 4):
        for tone in range(5):
            for b1800 in (0, 1):
                ok_c, m_c, r_c, v_c = chroma_run(img, mode=12, profile=p, tone=tone, b1800=b1800)
                ok_r, m_r, r_r, v_r = chroma_run(img, mode=11, profile=p, tone=tone, b1800=b1800)
                _, _, _, v_s = chroma_run(stock, mode=12, profile=p, tone=tone, b1800=b1800)
                # a1 / LIR / LAR are left by the (stock, re-issued) tone lookup 0x603b11fb, whose hash
                # search runs for key 12 but not for key 11; the caller never reads them (a1 is reloaded,
                # LIR/LAR are only used by an Lcc right after a setlb).
                regd = {k: (hex(r_r['registers'][k]), hex(r_c['registers'][k])) for k in REGS
                        if k not in CHROMA_LOOKUP_REGS and r_r['registers'][k] != r_c['registers'][k]}
                good = ok_c and ok_r and v_c == v_r == 0 and m_c['out'] == m_r['out'] and \
                    m_c['ctx'][:52] == m_r['ctx'][:52] and m_c['ctx'][56:] == m_r['ctx'][56:] and \
                    m_c['job_unchanged'] and m_r['job_unchanged'] and \
                    above_sp(m_c) == above_sp(m_r) and v_s != 0 and not regd
                ok &= good
                res.append(dict(test=f'C MONO{p} colour tone={tone} 1800={b1800}: out+76 {v_c:#x} == mode 11 '
                                     f'(stock mono {v_s:#010x})', passed=good, regdiff=regd))
    for name, kw, te in breaking_cases():
        for tone in (0, 1, 4):
            kw2 = dict(kw, tone=kw.get('tone', tone))
            ok_s, m_s, r_s, v_s = chroma_run(stock, mode=12, **kw2)
            ok_p, m_p, r_p, v_p = chroma_run(with_table(patched, te(hos) if te else hos), mode=12, **kw2)
            good = ok_s and ok_p and m_s['out'] == m_p['out'] and m_s['job'] == m_p['job'] and \
                m_s['ctx'] == m_p['ctx'] and regs_of(r_s) == regs_of(r_p) and above_sp(m_s) == above_sp(m_p)
            ok &= good
            res.append(dict(test=f'C {name} tone={kw2["tone"]} -> stock {v_s:#010x}', passed=good,
                            regdiff={k: (hex(r_s['registers'][k]), hex(r_p['registers'][k])) for k in REGS
                                     if r_s['registers'][k] != r_p['registers'][k]}))
    for mode in (11, 5):
        for tone in (0, 2):
            ok_s, m_s, r_s, v_s = chroma_run(stock, mode=mode, profile=1, tone=tone)
            ok_p, m_p, r_p, v_p = chroma_run(img, mode=mode, profile=1, tone=tone)
            good = ok_s and ok_p and m_s['out'] == m_p['out'] and regs_of(r_s) == regs_of(r_p)
            ok &= good
            res.append(dict(test=f'C mode {mode} tone={tone} == stock ({v_s:#x})', passed=good))
    return ok, res


# ------------------------------------------------------------------ P packer guard
PK_LO, PK_HI, PK_START, PK_STOP = 0x60353d00, 0x60353e20, 0x60353db7, 0x60353de9


def packer_run(img, *, mode=12, profile=1, ext_mode=None, magic=BB.MAGIC, filt=2, tone=3, x=1, x_extra=0x02):
    job = make_job(mode=mode, profile=profile, ext_mode=ext_mode, magic=magic)
    for i in range(36, 11294):                       # recognisable filler in the params block
        job[i] = (i * 13 + 5) & 0xff
    struct.pack_into('<I', job, MC.JOB_MODE, mode)
    p = 36
    job[p + 5528], job[p + 5529], job[p + 5550] = filt, tone, x | (x_extra << 2 if x else 0)
    stack = bytearray(0x2000)
    sp = STACK + 0x1800
    struct.pack_into('<I', stack, sp - STACK + 40, JOB)
    regions = [Region('code', PK_LO, sl(img, PK_LO, PK_HI), 'rx'), Region('tail1', T1_LO, sl(img, T1_LO, T1_HI), 'rx'),
               Region('tail7', T7_LO, sl(img, T7_LO, T7_HI), 'rx'), Region('tail2', T2_LO, sl(img, T2_LO, T2_HI), 'rx'),
               Region('stack', STACK, bytes(stack), 'rw', True), Region('job', JOB, bytes(job), 'rw', True)]
    regs = {'pc': PK_START, 'sp': sp, 'a2': JOB + 36, 'd0': 0x1234, 'd1': 0x5678, 'd2': 0x2222, 'd3': 0x3333,
            'a0': 0xa0a0, 'a1': 0xa1a1, 'a3': 0xa3a3}
    r = execute(regions, regs, PK_STOP, limit=2000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    ok = not r['fault'] and r['registers']['pc'] == PK_STOP and r['registers']['sp'] == sp
    return ok, mem, r, bytes(job)


def check_packer(stock, base, patched, base_table):
    res, ok = [], True
    hos = hostile(base_table)
    img = with_table(patched, hos)
    F, T = 36 + 5528, 36 + 5529
    for p in (1, 2, 3, 4):
        for filt, tone, x in ((2, 3, 1), (1, 0, 3), (0, 4, 0), (3, 1, 2)):
            ok_c, m_c, r_c, j0 = packer_run(img, mode=12, profile=p, filt=filt, tone=tone, x=x)
            ok_r, m_r, r_r, j11 = packer_run(img, mode=11, profile=p, filt=filt, tone=tone, x=x)
            ok_s, m_s, r_s, _ = packer_run(stock, mode=12, profile=p, filt=filt, tone=tone, x=x)
            exp = bytearray(j0)
            exp[F] = exp[T] = 0
            regd = {k: (hex(r_r['registers'][k]), hex(r_c['registers'][k])) for k in REGS
                    if k not in ('d0', 'psw') and r_r['registers'][k] != r_c['registers'][k]}
            good = ok_c and ok_r and ok_s and m_c['job'] == bytes(exp) and m_r['job'] == j11 and \
                r_c['registers']['d0'] == 12 and above_sp(m_c) == above_sp(m_r) and not regd
            ok &= good
            res.append(dict(test=f'P MONO{p} colour filter={filt} tone={tone} x={x}: 5528/5529 -> 0, merge skipped '
                                 f'(stock mono 5528={m_s["job"][F]:#x})', passed=good, regdiff=regd))
    for name, kw, te in breaking_cases():
        kw2 = {k: v for k, v in kw.items() if k in ('profile', 'ext_mode', 'magic')}
        if set(kw) - set(kw2) - {'tone', 'filt'}:
            continue                                  # request-only cases (callback/parent/1800) do not apply
        for filt, tone, x in ((2, 3, 1), (1, 1, 0)):
            ok_s, m_s, r_s, _ = packer_run(stock, mode=12, filt=filt, tone=tone, x=x, **kw2)
            ok_p, m_p, r_p, _ = packer_run(with_table(patched, te(hos) if te else hos), mode=12, filt=filt,
                                           tone=tone, x=x, **kw2)
            good = ok_s and ok_p and m_s['job'] == m_p['job'] and above_sp(m_s) == above_sp(m_p) and \
                regs_of(r_s) == regs_of(r_p)
            ok &= good
            res.append(dict(test=f'P {name} filter={filt} x={x} -> stock', passed=good,
                            regdiff={k: (hex(r_s['registers'][k]), hex(r_p['registers'][k])) for k in REGS
                                     if r_s['registers'][k] != r_p['registers'][k]}))
    for mode in (11, 5, 0):
        ok_s, m_s, r_s, _ = packer_run(stock, mode=mode, profile=1)
        ok_p, m_p, r_p, _ = packer_run(img, mode=mode, profile=1)
        good = ok_s and ok_p and m_s['job'] == m_p['job'] and regs_of(r_s) == regs_of(r_p)
        ok &= good
        res.append(dict(test=f'P mode {mode} == stock', passed=good))
    return ok, res


# ------------------------------------------------------------------ R real table
def check_real_table(stock, patched, table):
    res, ok = [], True
    for p in (1, 2, 3, 4):
        e = table[64 * (3 + p):64 * (4 + p)]
        if e[MC.COLOUR_OFF] == 1:
            v = dict(colour=1, sat=list(struct.unpack('<12b', e[MC.SAT_OFF:MC.SAT_OFF + 12])),
                     hue=list(struct.unpack('<12b', e[0:12])), light=list(struct.unpack('<12b', e[12:24])),
                     hl=bool(e[31] & BB.FLAG_HL))
            ok_c, m_c, r_c = sel_run(patched, mode=12, profile=p)
            ok_r, m_r, r_r = sel_run(with_table(patched, ref_table(table, {3 + p: v})), mode=11, profile=p, sat=v['sat'])
            c_c = chroma_run(patched, mode=12, profile=p, tone=1)[3]
            good = ok_c and ok_r and m_c['out'] == m_r['out'] and regs_of(r_c) == regs_of(r_r) and c_c == 0
            what = 'colour == mode-11 ref'
        else:
            ok_s, m_s, r_s = sel_run(stock, mode=12, profile=p)
            ok_p, m_p, r_p = sel_run(patched, mode=12, profile=p)
            c_s, c_p = chroma_run(stock, mode=12, profile=p, tone=1)[3], chroma_run(patched, mode=12, profile=p, tone=1)[3]
            good = ok_s and ok_p and m_s['out'] == m_p['out'] and regs_of(r_s) == regs_of(r_p) and c_s == c_p
            what = 'stock mono'
        ok &= good
        res.append(dict(test=f'R package table MONO{p}: {what}', passed=good))
    return ok, res


# ------------------------------------------------------------------ driver
def run_all(stock, base, patched, table):
    out, ok = [], True
    for f in (check_selector, check_chroma, check_packer):
        g, r = f(stock, base, patched, table)
        ok &= g
        out += r
    return ok, out


def static_checks(stock, patched, spec):
    res = []
    interior = set()
    for at, n in ((MC.SEL, 6), (MC.CHROMA, 5), (MC.FG, 8)):
        interior |= set(range(at + 1, at + n))
    hits = VB.branch_refs(stock, interior)
    res.append(dict(test='X no branch/loop/abs32 reference into hook-span interiors', passed=not hits, hits=hits))
    in_spans, n = VB.spans_check(spec, stock, patched)
    res.append(dict(test=f'X changed payload bytes ({n}) all inside edit spans', passed=in_spans))
    addrs = {int(e['addr'], 16) for e in spec['edits']}
    need = {BB.ALLOC, BB.MEMSET, BB.HOOK, BB.CONV1, BB.CONV2, BB.CODE_AT}
    res.append(dict(test='X spec contains the bundles v0.2 edits (job extension, transport, table)',
                    passed=need <= addrs))
    mine = [e for e in spec['edits'] if e.get('owner') == 'mono_colour']
    res.append(dict(test='X spec contains the 4 mono_colour edits', passed=len(mine) == 4))
    return res


def find_once(buf, pat, lo, hi):
    i = buf.find(pat, lo - BASE, hi - BASE)
    if i < 0 or buf.find(pat, i + 1, hi - BASE) >= 0:
        raise ValueError(f'mutation pattern {pat.hex()} not unique in {lo:#x}..{hi:#x}')
    return i


def mutations(patched, labels):
    L = {k: int(v, 16) for k, v in labels.items()}
    sel, mono, ch, keep, fg, fgm, end = (L['sel'], L['sel_mono'], L['chroma'], L['ch_keep'], L['fg'], L['fg_mono'],
                                         L['code_end'])
    out = []

    def mut(name, pat, new, lo, hi):
        m = bytearray(patched)
        i = find_once(m, bytes.fromhex(pat), lo, hi)
        m[i:i + len(bytes.fromhex(new))] = bytes.fromhex(new)
        out.append((name, bytes(m)))
    mut('sel: colour == 1 -> == 0', 'f84020a001', 'f84020a000', sel, ch)
    mut('sel: ext mode 12 -> 11', 'fa40813ca00c', 'fa40813ca00b', sel, ch)
    mut('sel: profile -1 removed', '28ffa004', '2800a004', sel, ch)
    mut('sel: sat bound 11 -> 12', 'a00b', 'a00c', sel, ch)
    mut('sel: sat pointer +33 -> +34', '2321', '2322', sel, ch)
    mut('sel: H/L frame -28 -> -24', 'f8fee4', 'f8fee8', sel, ch)
    mut('sel: H/L skipped', 'f8ec02c83c', 'f8ec00c83c', sel, ch)
    mut('sel: H/L offset 706 -> 708', 'fad3c202', 'fad3c402', sel, ch)
    mut('sel: parent check removed', 'f191c805', 'f191ca05', sel, mono)
    mut('sel_mono: frame not released (16 -> 12)', 'f8fe10dc', 'f8fe0cdc', mono, ch)
    mut('chroma: a0 = 0 removed', '9000', 'cbcb', ch, keep)
    mut('chroma: MDR fix removed', 'f2f2', 'cbcb', ch, keep)
    mut('chroma: mode word 12 -> 11', 'f80334a00c', 'f80334a00b', ch, keep)
    mut('chroma: callback off by one', 'fcc8d45f3560', 'fcc8d55f3560', ch, keep)
    mut('chroma: parent check removed', 'f191c969', 'f191cbcb', ch, keep)
    mut('ch_keep: a0 not restored', '5c0c', '5c08', keep, fg)
    mut('fg: tone not cleared (5565 -> 5566)', 'fa50bd15', 'fa50be15', fg, fgm)
    mut('fg: filter offset 5564 -> 5563', 'fa50bc15', 'fa50bb15', fg, fgm)
    mut('fg: colour check removed', 'f84020a001c9', 'f84020a001cb', fg, fgm)
    mut('fg_mono: a0 not restored', '5c04', '5c00', fgm, end)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--no-mutations', action='store_true')
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    if 'mono_colour' not in spec:
        sys.exit("spec lacks 'mono_colour' metadata (build patches/mono_colour/build.py; merge with tools/merge_specs.py)")
    labels = spec['mono_colour']['labels']
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    bpkg, _, _ = BP.build(dict(spec, edits=[e for e in spec['edits'] if e.get('owner') != 'mono_colour']),
                          BP.STOCK.read_bytes())
    base = oc.parse(bpkg)[0].payload
    table = patched[TABLE - BASE:TABLE - BASE + 512]
    results = static_checks(stock, patched, spec)
    ok = all(x['passed'] for x in results)
    g, r = run_all(stock, base, patched, table)
    ok &= g
    results += r
    g, r = check_real_table(stock, patched, table)
    ok &= g
    results += r
    for x in results:
        print(f"{'PASS' if x['passed'] else 'FAIL'}  {x['test']}" +
              ('' if x['passed'] else '  ' + json.dumps({k: v for k, v in x.items() if k not in ('test', 'passed')},
                                                         default=str)[:600]))
    mres = []
    if not a.no_mutations:
        for name, img in mutations(patched, labels):
            g, r = run_all(stock, base, img, table)
            failed = [x['test'] for x in r if not x['passed']]
            mres.append(dict(mutation=name, detected=not g, n_failing=len(failed), failing_tests=failed[:4]))
            print(f"{'PASS' if not g else 'FAIL'}  E mutation '{name}' detected by {len(failed)} test(s): {failed[:2]}")
        ok &= all(m['detected'] for m in mres)
    n = sum(1 for x in results if x['passed'])
    print(f"{'PASS' if ok else 'FAIL'}  overall ({n}/{len(results)} tests, "
          f"{sum(m['detected'] for m in mres)}/{len(mres)} mutations); package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.edits), package=info, passed=ok, results=results, mutations=mres,
                                          scope='emulator only; synthetic fixtures; CPU code, not ISP/pixels; '
                                                'no camera contacted'), indent=1, default=str))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
