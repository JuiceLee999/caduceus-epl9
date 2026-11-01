#!/usr/bin/env python3
"""Emulator verification of the live-view bundle H/L patch (patches/lv_bundles; offline; emulator only).

Builds the package for MERGED (base + lv, from patches/lv_bundles/build.py) and for BASE (the same spec without
the lv edits) with tools/build_package.build, decodes the main payloads (patched, base, stock = restore) and runs
the real COLOR selector 0x603b0252 (-> bundles `hl` at 0x603b02d9 -> builder 0x603b0068 -> lv at 0x603b02de)
natively on synthetic job/request/context fixtures, as tools/ep7_verify_bundles.py does. The property getter
0x6005e971 runs natively too (0x6005d924 registry lookup, 0x6005efbd width, 0x6005c8cf per-core translation)
on a fixture registry that holds the effective COLOR profile (key 0xF6B1). Every image region is mapped
read-only/executable (a store into image RAM faults); only stack, job, context, output and fixtures are writable.

  S  static: hook bytes, placement, no branch/abs32 into the hook interior, the only references into the
     placement are the EVF step-14 R/G pointers, store audit of the lv code, changed bytes inside edit spans.
  L  live view == capture: for COLOR1-4 x 4 saturation sets x 2 tables (the base bundle table and a test table
     with every COLOR slot on), a job WITHOUT capture transport (marker 0, profile from the getter) gives
     byte-identical colour output, job (except the 3 extension bytes), context and registers as the same job
     WITH transport (marker 0xB2, profile in job+15488); H/L == the slot's rows rebuilt from the table bytes.
  K  capture unchanged: capture jobs on MERGED == the same run on BASE (output, job, context, all registers).
  N  no table / guards == stock: all COLOR slots off with the registry UNMAPPED (a getter call would fault);
     profile 0/5/255; registry entry missing (getter error path, stub logger); value out of range; slot off;
     wrong callback; foreign parent; request key 12 -> output/job/context/registers == stock image.
  C  CPU id 1 (getter through the core-1/2 translator 0x60067100): L subset.
  D  SD loader v3 loaded mode (tools/ep7_sdv3_env.py: table moved to a pool buffer, flashed copy poisoned):
     L subset with expectations from the real table.
  M  mutations of the lv code / hook: each must make S/L/K/N/C/D fail.

Usage: tools/ep7_verify_lv_bundles.py MERGED.json [--json out.json] [--no-mutations] [--jobs N]
"""
import argparse, json, struct, subprocess, sys, tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'patches/bundles'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
import ep7_color_probe as PR  # noqa: E402
import build as BB  # noqa: E402  (patches/bundles/build.py)
from penf_emulator import Region, execute as _execute  # noqa: E402
import ep7_sdv3_env as SDV3  # noqa: E402
import ep7_verify_bundles as VB  # noqa: E402

execute = SDV3.wrap(_execute)
BASE = 0x60020020
CALLER, STACK = 0x18000000, 0x18010000
OUTPUT, CONTEXT, JOB = 0x19000000, 0x1a000000, 0x1b000000
NEW_SIZE = BB.JOB_SIZE + BB.EXT
REGS_ALL = VB.REGS_ALL
SATS = VB.SATS
HOOK, RESUME, CODE_AT, CODE_END = 0x603b02de, 0x603b02e4, 0x601e0e3c, 0x601e103c
EVF_SLOT14 = 0x601e3b3c + 320 + 14 * 16
GETTER_LO, GETTER_HI = 0x6005c8c0, 0x6005f010      # 0x6005c8cc translator0, 0x6005c8cf, 0x6005d924, getter, width
XLATE_LO, XLATE_HI = 0x60067100, 0x60067146         # core-1/2 translator
XTAB, LOGGER = 0x60078968, 0x60061808
REG_LO, REG_FLAG, REG_TAB = 0xa26ffa80, 0xa26ffa84, 0xa26ffa88
PROP = 0xF6B1
PROP_DATA = 0xa2800000
TC = BB.TC


def sl(main, lo, hi):
    return main[lo - BASE:hi - BASE]


def regs_of(r):
    return {k: r['registers'][k] for k in REGS_ALL}


def registry(profile, *, missing=False, overlay=False):
    """Fixture: global property registry with key 0xF6B1 -> one byte = profile. Read-only."""
    k = PROP >> 4
    size = (REG_TAB - REG_LO) + 8 * (k + 1)
    reg = bytearray(size)
    if overlay:
        struct.pack_into('<H', reg, REG_FLAG - REG_LO, 1)   # overlay table set, but no overlay entry: falls back
    if not missing:
        struct.pack_into('<II', reg, REG_TAB - REG_LO + 8 * k, PROP, PROP_DATA)
    out = [Region('registry', REG_LO, bytes(reg), 'r'), Region('prop', PROP_DATA, bytes([profile & 0xff, 0xa5, 0x5a, 0xc3]) + bytes(12), 'r')]
    if overlay:
        out.append(Region('overlay', 0xa2707a88 + 8 * k, bytes(8), 'r'))
    return out


def cpu_region(cpu):
    b = bytearray(32)
    struct.pack_into('<I', b, 0x10, cpu)                    # 0x8040 + 0x10 = (0x8050) CPU id
    return Region('cpuid', 0x8040, bytes(b), 'r')


def run(main, sat, *, profile=1, magic=0, ext_profile=None, key=11, callback=PR.CALLBACK, record_index=5,
        foreign_parent=False, reg=True, reg_kw=None, cpu=0, table=None, spec=None, ctx60=0):
    """Selector run. magic 0xB2 + ext_profile = capture job; magic 0 = live-view job (profile via registry)."""
    if table is not None:
        main = VB.with_table(main, spec, table)
    job = bytearray(NEW_SIZE)
    req, rec = PR.REQ_IN_JOB, PR.RECORDS_IN_JOB + PR.REC_STRIDE * record_index
    struct.pack_into('<I', job, req, callback)
    struct.pack_into('<I', job, req + 4, JOB + rec)
    struct.pack_into('<I', job, rec, JOB + (64 if foreign_parent else 0))
    job[req + 8:req + 12] = bytes([0, 0, key, 0])
    job[req + 1816:req + 1828] = struct.pack('<12b', *sat)
    job[BB.EXT_PROFILE] = ext_profile if ext_profile is not None else 0
    job[BB.EXT_MODE] = 11 if magic else 0
    job[BB.EXT_MAGIC] = magic
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, JOB + req)
    struct.pack_into('<I', ctx, 12, OUTPUT)
    struct.pack_into('<I', ctx, 60, ctx60)
    struct.pack_into('<I', ctx, 108, 0xffffffff)
    regions = [PR.caller(PR.SELECTOR, 0xf0, 20), Region('stack', STACK, bytes(0x2000), 'rw', True),
               Region('table', PR.TABLE, sl(main, PR.TABLE, PR.TABLE + PR.TABLE_SIZE)),
               Region('job', JOB, bytes(job), 'rw', True), Region('ctx', CONTEXT, bytes(ctx), 'rw', True),
               Region('out', OUTPUT, bytes(5212), 'rw', True),
               Region('code', PR.BUILDER, sl(main, PR.BUILDER, PR.SELECTOR_END), 'rx'),
               VB.tail1(main), VB.tail7(main), VB.tail2(main), VB.hlx(main),
               Region('lvcode', CODE_AT, sl(main, CODE_AT, CODE_END), 'rx'),
               Region('getter', GETTER_LO, sl(main, GETTER_LO, GETTER_HI), 'rx'),
               Region('xlate', XLATE_LO, sl(main, XLATE_LO, XLATE_HI), 'rx'),
               Region('xtab', XTAB, sl(main, XTAB, XTAB + 32), 'r'),
               Region('logger', LOGGER, bytes.fromhex('dff070'), 'rx'),
               cpu_region(cpu)]
    regions += PR.gain_regions(main)
    if reg:
        regions += registry(profile, **(reg_kw or {}))
    regs = {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CONTEXT, 'd0': 0xd0d0, 'd1': 0xd1d1, 'a1': 0xa1a1,
            'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3, 'mdr': 0x5a5a5a5a}
    r = execute(regions, regs, CALLER + 7, limit=60000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    rr = r['registers']
    ok = (not r['fault'] and rr['pc'] == CALLER + 7 and rr['sp'] == STACK + 0x1800 and
          (rr['d2'], rr['d3'], rr['a2'], rr['a3']) == (0x2222, 0x3333, 0xa2a2, 0xa3a3))
    return ok, mem, r


def job_noext(j):
    b = bytearray(j)
    b[BB.EXT_PROFILE:BB.EXT_MAGIC + 1] = bytes(3)
    return bytes(b)


def rows_of(table, slot):
    e = table[64 * slot:64 * slot + 64]
    hue = [x - 256 if x > 127 else x for x in e[0:12]]
    light = [x - 256 if x > 127 else x for x in e[12:24]]
    on = bool(e[31] & 2) and all(-7 <= v <= 7 for v in hue + light)
    return on, (BB.native_rows(hue, light) if on else None)


def test_table(spec):
    """Base table with every COLOR slot on and distinct in-range values (MONO slots as in the base)."""
    t = bytearray(bytes.fromhex(spec['table_hex']))
    for s in range(4):
        for i in range(12):
            t[64 * s + i] = ((i * 3 + s * 5) % 15 - 7) & 0xff
            t[64 * s + 12 + i] = ((i * 7 + s * 2 + 3) % 15 - 7) & 0xff
        t[64 * s + 31] |= BB.FLAG_HL
    return bytes(t)


def same(a, b, ext=False):
    (oa, ma, ra), (ob, mb, rb) = a, b
    j = (job_noext(ma['job']) == job_noext(mb['job'])) if ext else ma['job'] == mb['job']
    return dict(both_ok=oa and ob, out=ma['out'] == mb['out'], job=j, ctx=ma['ctx'] == mb['ctx'],
                stack=ma['stack'][0x1800:] == mb['stack'][0x1800:], regs=regs_of(ra) == regs_of(rb))


def L_cases(img, spec, tables, *, cpu=0, sats=SATS, tag='L', ctx60=0):
    res = []
    for tname, tb in tables:
        for sat in sats:
            for p in (1, 2, 3, 4):
                lv = run(img, sat, profile=p, magic=0, cpu=cpu, table=tb, spec=spec, ctx60=ctx60)
                cap = run(img, sat, profile=0, magic=BB.MAGIC, ext_profile=p, cpu=cpu, table=tb, spec=spec, reg=False,
                          ctx60=ctx60)
                sm = same(lv, cap, ext=True)
                on, rows = rows_of(tb, p - 1)
                recs = PR.records(lv[1]['out'])
                if on:
                    hl = all((recs[i]['hue'], recs[i]['light']) == rows[i] for i in range(12))
                else:
                    stock = run(STOCK_IMG[0], sat, profile=p, magic=0, reg=False, ctx60=ctx60)
                    hl = lv[1]['out'] == stock[1]['out']
                good = all(sm.values()) and hl
                res.append(dict(test=f'{tag} {tname} COLOR{p} sat={sat[:3]}.. lv==capture', passed=good, hl=hl,
                                slot_on=on, **sm, insns=lv[2]['completed'],
                                regdiff={k: (hex(lv[2]['registers'][k]), hex(cap[2]['registers'][k])) for k in REGS_ALL
                                         if lv[2]['registers'][k] != cap[2]['registers'][k]}))
    return res


def K_cases(img, base_img, spec, tables):
    res = []
    for tname, tb in tables:
        for sat in SATS[:2]:
            for p in (1, 2, 3, 4, 0, 5):
                a = run(img, sat, magic=BB.MAGIC, ext_profile=p, table=tb, spec=spec, reg=False)
                b = run(base_img, sat, magic=BB.MAGIC, ext_profile=p, table=tb, spec=spec, reg=False)
                sm = same(a, b)
                res.append(dict(test=f'K {tname} capture profile {p} sat={sat[:3]}.. == base build', passed=all(sm.values()), **sm))
    return res


def N_cases(img, stock, spec, ttab):
    res = []
    sat = SATS[1]
    off = bytearray(ttab)
    for s in range(4):
        off[64 * s + 31] &= ~BB.FLAG_HL & 0xff
    off = bytes(off)
    bad = bytearray(ttab); bad[2 * 64 + 5] = 8; bad = bytes(bad)
    bad2 = bytearray(ttab); bad2[3 * 64 + 23] = 0x80; bad2 = bytes(bad2)
    mono_on = bytearray(ttab); mono_on[4 * 64:4 * 64 + 24] = bytes(range(1, 8)) * 3 + bytes(3); mono_on[4 * 64 + 31] |= BB.FLAG_HL
    mono_on = bytes(mono_on)
    one_off = bytearray(ttab); one_off[1 * 64 + 31] &= ~BB.FLAG_HL & 0xff; one_off = bytes(one_off)
    cases = [('all COLOR slots off, registry unmapped (no getter call)', dict(table=off, reg=False, profile=1)),
             ('all COLOR slots off, registry mapped', dict(table=off, profile=2)),
             ('profile 0', dict(table=ttab, profile=0)), ('profile 5', dict(table=ttab, profile=5)),
             ('profile 255', dict(table=ttab, profile=255)),
             ('profile 5 with MONO1 slot H/L on', dict(table=mono_on, profile=5)),
             ('registry entry missing (getter error path)', dict(table=ttab, profile=1, reg_kw=dict(missing=True))),
             ('COLOR3 hue[5]=+8', dict(table=bad, profile=3)), ('COLOR4 light[11]=-128', dict(table=bad2, profile=4)),
             ('COLOR2 slot off', dict(table=one_off, profile=2)),
             ('wrong callback', dict(table=ttab, profile=1, callback=PR.CALLBACK + 1)),
             ('foreign parent', dict(table=ttab, profile=1, foreign_parent=True)),
             ('request key 12 (MONO)', dict(table=ttab, profile=1, key=12)),
             ('request key 5', dict(table=ttab, profile=1, key=5))]
    for name, kw in cases:
        a = run(img, sat, magic=0, spec=spec, **kw)
        kw2 = {k: v for k, v in kw.items() if k not in ('reg', 'reg_kw', 'profile')}
        b = run(stock, sat, magic=0, reg=False, **{k: v for k, v in kw2.items() if k != 'table'})
        sm = same(a, b)
        res.append(dict(test=f'N {name} -> stock', passed=all(sm.values()), **sm, fault=a[2]['fault']))
    # overlay flag set but no overlay entry: falls back to the main registry -> H/L applied (== capture)
    a = run(img, sat, profile=2, magic=0, table=ttab, spec=spec, reg_kw=dict(overlay=True))
    c = run(img, sat, magic=BB.MAGIC, ext_profile=2, table=ttab, spec=spec, reg=False)
    sm = same(a, c, ext=True)
    res.append(dict(test='N registry overlay flag set, no overlay entry -> main registry, lv==capture',
                    passed=all(sm.values()), **sm))
    return res


# ------------------------------------------------------------------ static
def objdump(code, at):
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / 'c.bin'
        p.write_bytes(code)
        out = subprocess.run([TC / 'mn10300-elf-objdump', '-b', 'binary', '-m', 'am33-2', '-D',
                              f'--adjust-vma={at:#x}', p], check=True, capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.strip()[:8].endswith(':') or ':\t' in l]


def store_audit(code):
    """Every memory store in the lv code: destination must be (n,sp) or the output records via a3."""
    bad, stores = [], []
    for l in objdump(code, CODE_AT):
        if ':\t' not in l:
            continue
        f = l.split('\t')
        if len(f) < 4:
            continue
        parts = [f[2].strip(), f[3].strip()]
        ins = ' '.join(parts)
        if parts[0] not in ('mov', 'movbu', 'movhu'):
            continue
        src, _, dst = parts[1].partition(',')
        if not dst.strip().startswith('(') and not dst.strip().endswith(')'):
            continue                                        # register destination
        if src.strip().startswith('('):
            continue
        stores.append(ins)
        if not (dst.endswith(',sp)') or dst.strip() in ('(sp)', '(a3)') or dst.endswith(',a3)')):
            bad.append(ins)
    return stores, bad


def check_static(stock, img, spec):
    res = []
    lv = spec['lv_bundles']
    code = sl(img, CODE_AT, CODE_AT + lv['code_len'])
    hook = sl(img, HOOK, HOOK + 6)
    want = b'\xdc' + struct.pack('<i', CODE_AT - HOOK) + b'\xcb'
    s = dict(hook=hook == want, stock_hook=sl(stock, HOOK, HOOK + 6) == bytes.fromhex('f8023cf8ec02'),
             resume_stock=sl(img, RESUME, RESUME + 2) == bytes.fromhex('c854'),
             evf_ptrs=struct.unpack_from('<2I', img, EVF_SLOT14 + 4 - BASE) == (CODE_AT, CODE_AT + 256),
             tail_after_code_stock=sl(img, CODE_AT + len(code), CODE_END) == sl(stock, CODE_AT + len(code), CODE_END))
    hits = VB.branch_refs(stock, set(range(HOOK + 1, HOOK + 6)))
    s['no_refs_into_hook_interior'] = not hits
    into = VB.branch_refs(stock, set(range(CODE_AT, CODE_END)))
    allowed = {hex(EVF_SLOT14 + 4), hex(EVF_SLOT14 + 8)}
    # brute-force hits whose source lies inside the gamma LUT data block 0x601de13c..0x601e3b3c are LUT bytes
    others = [h for h in into if not (h[0] == 'abs32' and h[1] in allowed)
              and not (0x601de13c <= int(h[1], 16) < 0x601e3b3c)]
    s['only_evf_ptrs_reference_placement'] = not others
    stores, bad = store_audit(code)
    s['store_audit'] = not bad and len(stores) > 0
    in_spans, nchg = VB.spans_check(spec, stock, img)
    s['changed_bytes_in_spans'] = in_spans
    res.append(dict(test='S static', passed=all(s.values()), **s, interior_hits=hits, placement_refs=others,
                    stores=stores, bad_stores=bad, changed=nchg))
    return res


STOCK_IMG = [None]


def all_checks(img, base_img, stock, spec, quick=False):
    t0 = bytes.fromhex(spec['table_hex'])
    tt = test_table(spec)
    tables = [('base-table', t0), ('test-table', tt)]
    STOCK_IMG[0] = stock
    out = check_static(stock, img, spec)
    out += L_cases(img, spec, tables if not quick else tables[1:], sats=SATS if not quick else SATS[1:2])
    out += K_cases(img, base_img, spec, tables if not quick else tables[1:])
    out += N_cases(img, stock, spec, tt)
    out += L_cases(img, spec, [('test-table', tt)], cpu=1, sats=SATS[1:3], tag='C cpu1')
    out += L_cases(img, spec, [('test-table', tt)], sats=SATS[1:2], tag='L ctx+60 bit2', ctx60=2)
    for p in (1, 0):
        sm = same(run(img, SATS[1], profile=p, magic=0, table=tt, spec=spec, ctx60=2),
                  run(stock if p == 0 else base_img, SATS[1], profile=p, magic=0, reg=False, ctx60=2,
                      **({} if p == 0 else dict(table=tt, spec=spec))))
        if p == 1:   # base build leaves lv stock: compare only control flow (ctx/regs/stack), output differs by H/L
            sm.pop('out')
        out.append(dict(test=f'L ctx+60 bit2 profile {p}: flow == reference', passed=all(sm.values()), **sm))
    # negative control: the BASE build (no lv) leaves live-view jobs stock, so lv != capture there
    lv0 = run(base_img, SATS[1], profile=1, magic=0, table=tt, spec=spec)
    cap0 = run(base_img, SATS[1], magic=BB.MAGIC, ext_profile=1, table=tt, spec=spec, reg=False)
    st0 = run(stock, SATS[1], magic=0, reg=False)
    out.append(dict(test='X negative control: base build live-view job == stock, != capture',
                    passed=lv0[0] and lv0[1]['out'] == st0[1]['out'] and lv0[1]['out'] != cap0[1]['out']))
    SDV3.set_loaded(True)
    try:
        out += L_cases(img, spec, [('test-table', tt)], sats=SATS[1:2], tag='D sd-loaded')
    finally:
        SDV3.set_loaded(False)
    return out


def mutations(img, spec):
    lv = spec['lv_bundles']
    lo, hi = CODE_AT, CODE_AT + lv['code_len']
    out = []

    def mut(name, pat, new, a=lo, b=hi):
        m = bytearray(img)
        i = VB.find_once(m, pat, a, b)
        m[i:i + len(new)] = new
        out.append((name, bytes(m)))
    mut('marker 0xB2 -> 0xB3 (capture jobs treated as live view)', bytes.fromhex('fac8b200'), bytes.fromhex('fac8b300'))
    mut('key compare 11 -> 12', bytes.fromhex('a50b'), bytes.fromhex('a50c'))
    mut('property key 0xF6B1 -> 0xF6B2 (halfword read)', struct.pack('<I', 0xF6B1), struct.pack('<I', 0xF6B2))
    mut('property key 0xF6B1 -> 0xF6C1 (other entry)', struct.pack('<I', 0xF6B1), struct.pack('<I', 0xF6C1))
    mut('no -1 on profile', bytes.fromhex('28ffa004'), bytes.fromhex('2800a004'))
    mut('profile bound 4 -> 5', bytes.fromhex('28ffa004'), bytes.fromhex('28ffa005'))
    mut('any-slot check skipped', bytes.fromhex('f214f8ec02'), bytes.fromhex('f214f8ec00'))
    mut('slot flag check skipped', bytes.fromhex('f8401ff8ec02'), bytes.fromhex('f8401ff8ec00'))
    mut('hue offset 706 -> 708', bytes.fromhex('fad3c202'), bytes.fromhex('fad3c402'))
    mut('record loop 12 -> 11', bytes.fromhex('aa0cc9'), bytes.fromhex('aa0bc9'))
    mut('value check 15 -> 16', bytes.fromhex('a00fc6'), bytes.fromhex('a010c6'))
    mut('frame restore a0 from (20,sp)', bytes.fromhex('5c10'), bytes.fromhex('5c14'))
    mut('MDR not restored', bytes.fromhex('f2f2'), bytes.fromhex('cbcb'))
    mut('displaced btst 2 -> btst 4', bytes.fromhex('f8023cf8ec02dc'), bytes.fromhex('f8023cf8ec04dc'))
    mut('callback off-by-one', struct.pack('<I', PR.CALLBACK), struct.pack('<I', PR.CALLBACK + 1))
    mut('L stored at hue+6', bytes.fromhex('f87f04'), bytes.fromhex('f87f06'))
    m = bytearray(img); h = HOOK - BASE; m[h + 1:h + 5] = struct.pack('<i', CODE_AT + 3 - HOOK); out.append(('hook skips frame setup', bytes(m)))
    m = bytearray(img); h = HOOK - BASE; m[h:h + 6] = bytes.fromhex('f8023cf8ec02'); out.append(('hook left stock', bytes(m)))
    return out


def _mut_worker(args):
    name, img, base_img, stock, spec = args
    r = all_checks(img, base_img, stock, spec, quick=True)
    failed = [x['test'] for x in r if not x['passed']]
    return dict(mutation=name, detected=bool(failed), n_failing=len(failed), failing_tests=failed[:4])


def payload(spec):
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    return oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload, info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('merged', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--no-mutations', action='store_true')
    ap.add_argument('--jobs', type=int, default=1)
    a = ap.parse_args()
    spec = json.loads(a.merged.read_text())
    if 'lv_bundles' not in spec:
        sys.exit('spec lacks lv_bundles metadata (use <out>/merged.json from patches/lv_bundles/build.py)')
    base_spec = dict(spec, edits=[e for e in spec['edits'] if e.get('source') != 'patches/lv_bundles'])
    img, stock, info = payload(spec)
    base_img, stock2, _ = payload(base_spec)
    if stock != stock2:
        sys.exit('restore payloads differ')
    results = all_checks(img, base_img, stock, spec)
    ok = all(x['passed'] for x in results)
    for x in results:
        print(f"{'PASS' if x['passed'] else 'FAIL'}  {x['test']}" +
              ('' if x['passed'] else '  ' + json.dumps({k: v for k, v in x.items() if k not in ('test', 'passed')},
                                                         default=str)[:700]))
    print(f"{sum(x['passed'] for x in results)}/{len(results)} functional checks pass")
    mres = []
    if not a.no_mutations:
        jobs = [(n, m, base_img, stock, spec) for n, m in mutations(img, spec)]
        if a.jobs > 1:
            with ProcessPoolExecutor(a.jobs) as ex:
                mres = list(ex.map(_mut_worker, jobs))
        else:
            mres = [_mut_worker(j) for j in jobs]
        for m in mres:
            print(f"{'PASS' if m['detected'] else 'FAIL'}  M mutation '{m['mutation']}' detected by "
                  f"{m['n_failing']} test(s): {m['failing_tests'][:2]}")
        ok &= all(m['detected'] for m in mres)
        print(f"{sum(m['detected'] for m in mres)}/{len(mres)} mutations detected")
    print(f"{'PASS' if ok else 'FAIL'}  overall; package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.merged), package=info, passed=ok, results=results, mutations=mres,
                                          scope='emulator only; synthetic fixtures; CPU code, not ISP/pixels; '
                                                'no camera contacted'), indent=1, default=str))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
