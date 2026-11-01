#!/usr/bin/env python3
"""Emulator verification of patches/lv_art (live-view look preview, phase 1; offline; emulator only).

Builds the package for MERGED (base + lv_art, from patches/lv_art/build.py) and for BASE (the same spec without the
lv_art edits) with tools/build_package.build, decodes the main payloads and runs native code:

  S  static: hook bytes, no branch/abs32 into the hook interior, the only reference into the placement is the EVF
     step-13 R pointer, store audit of the routine, changed bytes inside edit spans, rest of the dead LUT stock.
  F  frame: the real constructor 0x603537eb entered from the real call at 0x60321ea8 (and from a still converter call
     site) runs to 0x60353915 with alloc/memset stubs; the return word the hook reads, (44,sp), is the call's return.
  H  hook matrix, from 0x60353c6f to 0x60353c75 with a stub dispatcher at 0x60354709 (returns its a0): PATCHED vs
     BASE on the same job/stack/registry. Job == base job except job+16 bit 0x80 and the 3 transport bytes, which
     must match the model (return word, key, type, profile, slot fields, build features); registers, sp, the
     dispatcher's a0 (= job) and the caller's stack == base. Gate cases (other return words, keys, types,
     profiles, missing registry entry) must be byte-identical to base.
  C  CPU id 1 (getter through the per-core translator): H subset.
  D  SD loader v3 loaded mode (table served from the pool buffer, flashed copy poisoned): H subset.
  R  readers: the stock-path bloom weight getter (base image, combiner 12 = the classes 4-8 single-pass entry)
     returns the slot's bloom weight for a job carrying the transport lv_art writes, and 600 without it.
  M  mutations of the routine / hook: each must make S/F/H/C/D fail.

Usage: patches/lv_art/verify.py MERGED.json [--json out.json] [--no-mutations] [--jobs N]
"""
import argparse, json, struct, subprocess, sys, tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'patches/bundles'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
import build as BB  # noqa: E402  (patches/bundles/build.py)
from penf_emulator import Region, execute as _execute  # noqa: E402
import ep7_sdv3_env as SDV3  # noqa: E402
import ep7_verify_bundles as VB  # noqa: E402
import ep7_verify_lv_bundles as LVB  # noqa: E402  (getter / registry fixtures; read-only use)
import ep7_bloom_verify as BV  # noqa: E402  (combiner bank runs; read-only use)

execute = SDV3.wrap(_execute)
BASE = 0x60020020
HOOK, RESUME, DISPATCH, LV_RET = 0x60353c6f, 0x60353c75, 0x60354709, 0x60321eaf
CODE_AT, CODE_END, EVF_SLOT13_R = 0x601e113c, 0x601e123c, 0x601e3b3c + 320 + 13 * 16 + 4
STACK, SP0 = 0x18010000, 0x18010000 + 0x1000
JOB = 0x1b000000
NEW_SIZE = BB.JOB_SIZE + BB.EXT
EXT = BB.EXT_PROFILE
FAKE_DISPATCH = bytes.fromhex('f1d0dfb010')          # mov a0,d0; ret [d2,a2,a3],16
R0 = {'d2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': JOB}
STILL_SITE = 0x603e6d3e                               # still converter path: call 0x603537eb


def sl(m, lo, hi):
    return m[lo - BASE:hi - BASE]


def fixture(slots):
    """slots: {slot: dict(hl=bool, eff=, s=, grain=)} -> 512-B table (8 x 64)."""
    t = bytearray(512)
    for i, v in slots.items():
        b = i * 64
        t[b + 31] = 2 if v.get('hl') else 0
        t[b + 28], t[b + 29], t[b + 24] = v.get('eff', 0), v.get('s', 0), v.get('grain', 0)
    return bytes(t)


TABLES = {
    'T1': fixture({0: dict(hl=True, eff=1, s=3), 1: dict(eff=1, s=5), 2: dict(hl=True, grain=2), 3: dict(eff=3, s=4),
                   4: dict(hl=True, eff=1, s=2), 5: dict(eff=1, s=1)}),
    'T2': fixture({0: dict(grain=1), 1: dict(eff=1, s=0), 2: dict(eff=1, s=6), 3: dict(hl=True, eff=1, s=1)}),
    'T3': fixture({0: dict(eff=1, s=1, grain=3), 1: dict(hl=True, eff=2, s=3), 2: dict(grain=4, eff=1, s=2),
                   3: dict(hl=True, eff=1, s=5, grain=1)}),
    'erased': b'\xff' * 512,
}


def model(feats, table, *, ret, key, jtype, profile):
    """-> (transport profile or None, flag 0x80 added)."""
    if ret != LV_RET or key != 11 or jtype & 0xf0 != 0x30 or jtype & 0xf00 == 0x100:
        return None, False
    if profile is None or not 1 <= profile <= 4:
        return None, False
    s = table[(profile - 1) * 64:profile * 64]
    want = 0
    if 'hl' in feats and s[31] & 2:
        want |= 1
    if 'bloom' in feats and s[28] in (1, 2) and 1 <= s[29] <= 5:
        want |= 3
    if 'grain' in feats:
        if 1 <= s[24] <= 3:
            want |= 1
    elif s[24]:
        want = 0
    return (profile if want else None), bool(want & 2)


def job_bytes(key, jtype, flags=0x00080000):
    j = bytearray(NEW_SIZE)
    for i in range(0, 15488, 4):
        struct.pack_into('<I', j, i, 0x5a000000 | i)       # non-zero filler (any stray store shows)
    struct.pack_into('<I', j, 16, flags)
    struct.pack_into('<H', j, 20, jtype)
    struct.pack_into('<I', j, 11308, key)
    j[15488:] = bytes(NEW_SIZE - 15488)
    return bytes(j)


def hook_run(img, spec, table, *, ret=LV_RET, key=11, jtype=0x38, profile=1, reg=True, reg_kw=None, cpu=0):
    if table is not None:
        img = VB.with_table(img, spec, table)
    st = bytearray(0x2000)
    for o in range(0, 0x2000, 4):
        struct.pack_into('<I', st, o, 0xc0de0000 | o)
    struct.pack_into('<I', st, SP0 - STACK + 44, ret)
    regions = [Region('ctor', HOOK, sl(img, HOOK, HOOK + 16), 'rx'),
               Region('dispatch', DISPATCH, FAKE_DISPATCH, 'rx'),
               Region('lvcode', CODE_AT, sl(img, CODE_AT, CODE_END), 'rx'),
               Region('stack', STACK, bytes(st), 'rw', True),
               Region('job', JOB, job_bytes(key, jtype), 'rw', True),
               VB.tail1(img), VB.tail2(img),
               Region('getter', LVB.GETTER_LO, sl(img, LVB.GETTER_LO, LVB.GETTER_HI), 'rx'),
               Region('xlate', LVB.XLATE_LO, sl(img, LVB.XLATE_LO, LVB.XLATE_HI), 'rx'),
               Region('xtab', LVB.XTAB, sl(img, LVB.XTAB, LVB.XTAB + 32), 'r'),
               Region('logger', LVB.LOGGER, bytes.fromhex('dff070'), 'rx'),
               LVB.cpu_region(cpu)]
    if reg:
        regions += LVB.registry(profile, **(reg_kw or {}))
    regs = {'pc': HOOK, 'sp': SP0, 'd0': 0xd0d0, 'd1': 0xd1d1, 'a0': 0xa0a0, 'a1': 0xa1a1, 'mdr': 0x5a5a5a5a, **R0}
    r = execute(regions, regs, RESUME, limit=60000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    rr = r['registers']
    ok = (not r['fault'] and rr['pc'] == RESUME and rr['sp'] == SP0 and rr['d0'] == JOB and
          all(rr[k] == v for k, v in R0.items()))
    return ok, m, rr


def compare(feats, pr, br, table, **case):
    """patched run vs base run against the model."""
    (pok, pm, _), (bok, bm, _) = pr, br
    tp, fl = model(feats, table, **case)
    pj, bj = bytearray(pm['job']), bytearray(bm['job'])
    exp = bytearray(bj)
    if tp is not None:
        exp[EXT:EXT + 3] = bytes([tp, 11, BB.MAGIC])
    if fl:
        struct.pack_into('<I', exp, 16, struct.unpack_from('<I', bj, 16)[0] | 0x80)
    caller_stack_same = pm['stack'][SP0 - STACK + 4:] == bm['stack'][SP0 - STACK + 4:]
    good = pok and bok and bytes(pj) == bytes(exp) and caller_stack_same
    return good, dict(expect_transport=tp, expect_flag=fl, patched_ext=list(pj[EXT:EXT + 3]),
                      flags=hex(struct.unpack_from('<I', pj, 16)[0]), ran_ok=(pok, bok), stack_same=caller_stack_same)


def H_cases(img, base, spec, feats, *, cpu=0, tag='H', tables=None, quick=False):
    rows, ok = [], True
    tables = tables or list(TABLES)
    # profile x table matrix on the live-view gate
    for tn in tables:
        t = TABLES[tn]
        for p in ((0, 1, 2, 3, 4, 5) if quick else (0, 1, 2, 3, 4, 5, 255)):
            case = dict(ret=LV_RET, key=11, jtype=0x38, profile=p)
            g, info = compare(feats, hook_run(img, spec, t, cpu=cpu, **case), hook_run(base, spec, t, cpu=cpu, **case), t, **case)
            ok &= g
            rows.append(dict(table=tn, profile=p, ok=g, **info))
    if quick and tag != 'H':
        return [dict(test=f'{tag} matrix (quick)', passed=ok, rows=[r for r in rows if not r['ok']][:6])]
    out = [dict(test=f'{tag} profile x table matrix ({len(rows)} runs)', passed=ok,
                rows=[r for r in rows if not r['ok']][:6] or rows[:3])]
    # gates: everything here must equal the base run (T1 COLOR1 = H/L + bloom, i.e. would act if the gate opened)
    t = TABLES['T1']
    gates = ([dict(ret=r) for r in (0x603e6d45, 0x60321eb0, 0, LV_RET + 0x100)] +
             [dict(key=k) for k in (12, 9, 0x01010065, 0x0b, 0x10b)] +
             [dict(jtype=x) for x in (0x30, 0x31, 0x35, 0x3f, 0x2030, 0x8038, 0x130, 0x1030, 0x40, 0x10, 0x20, 0x00, 0x48)])
    rows, gok = [], True
    for gk in gates:
        case = dict(ret=LV_RET, key=11, jtype=0x38, profile=1)
        case.update(gk)
        if case['key'] == 0x10b:
            case['key'] = 0x0000010b
        g, info = compare(feats, hook_run(img, spec, t, **case), hook_run(base, spec, t, **case), t, **case)
        gok &= g
        rows.append(dict(case={k: hex(v) for k, v in gk.items()}, ok=g, transport=info['expect_transport']))
    out.append(dict(test=f'{tag} gates: return word / key / type ({len(rows)} cases)', passed=gok, rows=rows))
    rows, nok = [], True
    for label, kw in (('registry entry missing', dict(reg_kw=dict(missing=True))),
                      ('overlay flag, no overlay entry', dict(reg_kw=dict(overlay=True)))):
        pr, br = hook_run(img, spec, t, **kw), hook_run(base, spec, t, **kw)
        exp_p = None if 'missing' in label else 1
        g, info = compare(feats, pr, br, t, ret=LV_RET, key=11, jtype=0x38, profile=exp_p)
        nok &= g
        rows.append(dict(case=label, ok=g, **info))
    out.append(dict(test=f'{tag} getter edge cases', passed=nok, rows=rows))
    return out


def objdump(code, at):
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / 'c.bin'
        p.write_bytes(code)
        o = subprocess.run([BB.TC / 'mn10300-elf-objdump', '-b', 'binary', '-m', 'am33-2', '-D',
                            f'--adjust-vma={at:#x}', p], check=True, capture_output=True, text=True).stdout
    return [l for l in o.splitlines() if ':\t' in l]


def store_audit(code):
    allowed = {f'({BB.EXT_PROFILE},a3)', f'({BB.EXT_MODE},a3)', f'({BB.EXT_MAGIC},a3)', '(16,a3)', '(4,sp)', '(8,sp)'}
    stores, bad = [], []
    for l in objdump(code, CODE_AT):
        f = l.split('\t')
        if len(f) < 4:
            continue
        op, args = f[2].strip(), f[3].strip()
        if op not in ('mov', 'movbu', 'movhu'):
            continue
        src, _, dst = args.partition(',')
        if src.startswith('(') or not dst.strip().startswith('('):
            continue
        stores.append(f'{op} {args}')
        if dst.strip() not in allowed:
            bad.append(f'{op} {args}')
    return stores, bad


def S_static(img, stock, spec):
    la = spec['lv_art']
    code = sl(img, CODE_AT, CODE_AT + la['code_len'])
    want = b'\xdc' + struct.pack('<i', CODE_AT - HOOK) + b'\xcb'
    s = dict(hook=sl(img, HOOK, HOOK + 6) == want, stock_hook=sl(stock, HOOK, HOOK + 6) == bytes.fromhex('9ccd990ab010'),
             resume_stock=sl(img, RESUME, RESUME + 4) == sl(stock, RESUME, RESUME + 4),
             evf_ptr=struct.unpack_from('<I', img, EVF_SLOT13_R - BASE)[0] == CODE_AT,
             tail_after_code_stock=sl(img, CODE_AT + len(code), CODE_END) == sl(stock, CODE_AT + len(code), CODE_END))
    hits = VB.branch_refs(stock, set(range(HOOK + 1, HOOK + 6)))
    s['no_refs_into_hook_interior'] = not hits
    into = VB.branch_refs(stock, set(range(CODE_AT, CODE_END)))
    others = [h for h in into if not (h[0] == 'abs32' and h[1] == hex(EVF_SLOT13_R))
              and not (0x601de13c <= int(h[1], 16) < 0x601e3b3c)]
    s['only_evf13_ptr_references_placement'] = not others
    stores, bad = store_audit(code)
    s['store_audit'] = not bad and len(stores) == 6
    s['changed_bytes_in_spans'] = VB.spans_check(spec, stock, img)[0]
    return [dict(test='S static', passed=all(s.values()), **s, interior_hits=hits, placement_refs=others, stores=stores, bad=bad)]


def frame_run(main, site):
    """Real constructor from the real call instruction at `site` up to 0x60353915; -> (44,sp) there, call length."""
    ins = sl(main, site, site + 7)
    assert ins[0] == 0xdd and struct.unpack_from('<i', ins, 1)[0] + site == 0x603537eb, hex(site)
    alloc = (b'\xfc\xdc' + struct.pack('<I', JOB) + b'\xfc\x81' + struct.pack('<I', VB.SIZE_CELL) + b'\xdf\x00\x04')
    desc = bytes(range(32)) + bytes(16)
    regions = [Region('caller', site, ins + b'\xcb', 'rx'),
               Region('ctor', 0x603537eb, sl(main, 0x603537eb, 0x60353920), 'rx'),
               Region('alloc', VB.ALLOC_STUB, alloc, 'rx'), Region('memset', VB.MEMSET_STUB, VB.MEMSET_CODE, 'rx'),
               Region('size', VB.SIZE_CELL, bytes(4), 'rw', True), Region('desc', 0x1e000000, desc, 'rw'),
               Region('status', 0x1e001000, bytes(4), 'rw', True),
               Region('job', JOB, b'\xaa' * VB.BLOCK, 'rw', True), Region('stack', STACK, bytes(0x2000), 'rw', True)]
    r = execute(regions, {'pc': site, 'sp': SP0, 'd0': 0, 'a0': 0x1e000000, 'a1': 0x1e001000},
                0x60353915, limit=2_000_000, timeout=120)
    st = bytes.fromhex(next(x['hex'] for x in r['memory'] if x['name'] == 'stack'))
    sp = r['registers']['sp']
    return (not r['fault'] and r['registers']['pc'] == 0x60353915, struct.unpack_from('<I', st, sp - STACK + 44)[0], sp)


def F_frame(img):
    rows, ok = [], True
    for site in (0x60321ea8, STILL_SITE):
        good, word, sp = frame_run(img, site)
        exp = site + 7
        g = good and word == exp and sp == SP0 - 44
        ok &= g
        rows.append(dict(site=hex(site), ran=good, word_44_sp=hex(word), expected=hex(exp), ok=g))
    return [dict(test='F constructor frame: (44,sp) = return word at the hook (real ctor, real call sites)',
                 passed=ok and rows[0]['word_44_sp'] == hex(LV_RET), rows=rows)]


def R_readers(base):
    """Bloom weight getter on the base image (stock path + bloom_w), combiner 12, with/without lv_art's transport."""
    rows, ok = [], True
    W = [942, 881, 819, 748, 666]                          # bloom w_lut (combiner 12: +140 = w, +96 = 1024-w)
    for s in (1, 3, 5):
        t = BV.fixture_table({1: (1, s)})
        g1, b1 = BV.bank_run(base, t, 11, 0x0403, ext=(2, 11, BB.MAGIC))
        g0, b0 = BV.bank_run(base, t, 11, 0x0403, ext=None)
        w1, w0 = BV.weights_of(b1), BV.weights_of(b0)
        g = g1 and g0 and w1[140] == W[s - 1] and w1[96] == 1024 - W[s - 1] and w0[140] == 600 and w0[96] == 424
        ok &= g
        rows.append(dict(strength=s, with_transport=w1, without=w0, ok=g))
    t = BV.fixture_table({1: (3, 4)})                       # clarity slot: c12 -> 1024 (no visible change in LV)
    g1, b1 = BV.bank_run(base, t, 11, 0x0403, ext=(2, 11, BB.MAGIC))
    w1 = BV.weights_of(b1)
    g = g1 and w1[140] == 1024 and w1[96] == 0
    ok &= g
    rows.append(dict(clarity_strength=4, with_transport=w1, ok=g, note='why lv_art does not flag clarity slots'))
    return [dict(test='R bloom weight getter, combiner 12 (classes 4-8): slot W with transport, 600 without', passed=ok, rows=rows)]


def all_checks(img, base, stock, spec, quick=False):
    feats = set(spec['lv_art']['features'])
    out = S_static(img, stock, spec)
    out += F_frame(img)
    out += H_cases(img, base, spec, feats, quick=quick)
    out += H_cases(img, base, spec, feats, cpu=1, tag='C cpu1', tables=['T1', 'T3'], quick=True)
    SDV3.set_loaded(True)
    try:
        out += H_cases(img, base, spec, feats, tag='D sd-loaded', tables=['T1', 'T3'], quick=True)
    finally:
        SDV3.set_loaded(False)
    if not quick:
        out += R_readers(base)
    return out


def mutations(img, spec):
    la = spec['lv_art']
    lo, hi = CODE_AT, CODE_AT + la['code_len']
    out = []

    def mut(name, pat, new):
        m = bytearray(img)
        i = VB.find_once(m, pat, lo, hi)
        m[i:i + len(new)] = new
        out.append((name, bytes(m)))
    mut('return word off by one', struct.pack('<I', LV_RET), struct.pack('<I', LV_RET + 1))
    mut('return word read at (52,sp)', bytes.fromhex('5838'), bytes.fromhex('5834'))
    mut('key 11 -> 12', bytes.fromhex('a00b'), bytes.fromhex('a00c'))
    mut('type nibble 0x30 -> 0x40', bytes.fromhex('a530'), bytes.fromhex('a540'))
    mut('0x100 strip test dropped', bytes.fromhex('fac80001'), bytes.fromhex('fac80002'))
    mut('property 0xF6B1 -> 0xF6B2', struct.pack('<I', 0xF6B1), struct.pack('<I', 0xF6B2))
    mut('profile bound 4 -> 5', bytes.fromhex('a004c6'), bytes.fromhex('a005c6'))
    mut('marker 0xB2 -> 0xB3', bytes.fromhex('2cb200'), bytes.fromhex('2cb300'))
    mut('flag 0x80 -> 0x40', bytes.fromhex('f8e480'), bytes.fromhex('f8e440'))
    mut('mode 11 -> 12', bytes.fromhex('800b'), bytes.fromhex('800c'))
    mut('bloom strength bound 5 -> 6', bytes.fromhex('a005c6'), bytes.fromhex('a006c6'))
    mut('d2 not restored', bytes.fromhex('5a04'), bytes.fromhex('5a08'))
    if 'hl' in la['features']:
        mut('H/L bit 2 -> 1', bytes.fromhex('f8401ff8ec02'), bytes.fromhex('f8401ff8ec01'))
    m = bytearray(img); h = HOOK - BASE; m[h:h + 6] = bytes.fromhex('9ccd990ab010'); out.append(('hook left stock', bytes(m)))
    m = bytearray(img); h = HOOK - BASE; m[h + 1:h + 5] = struct.pack('<i', CODE_AT + 0x9d - HOOK); out.append(('hook jumps to out', bytes(m)))
    return out


def _mut_worker(args):
    name, img, base, stock, spec = args
    r = all_checks(img, base, stock, spec, quick=True)
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
    if 'lv_art' not in spec:
        sys.exit('spec lacks lv_art metadata (use <out>/merged.json from patches/lv_art/build.py)')
    base_spec = dict(spec, edits=[e for e in spec['edits'] if e.get('source') != 'patches/lv_art'])
    img, stock, info = payload(spec)
    base, stock2, _ = payload(base_spec)
    if stock != stock2:
        sys.exit('restore payloads differ')
    results = all_checks(img, base, stock, spec)
    ok = all(x['passed'] for x in results)
    for x in results:
        print(f"{'PASS' if x['passed'] else 'FAIL'}  {x['test']}" +
              ('' if x['passed'] else '  ' + json.dumps({k: v for k, v in x.items() if k not in ('test', 'passed')},
                                                         default=str)[:900]))
    print(f"{sum(x['passed'] for x in results)}/{len(results)} functional checks pass")
    mres = []
    if not a.no_mutations:
        jobs = [(n, m, base, stock, spec) for n, m in mutations(img, spec)]
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
