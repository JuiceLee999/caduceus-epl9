#!/usr/bin/env python3
"""Emulator verification of a BUILT per-profile WB package (offline; emulator only; no camera).

Takes an edits spec that contains the WB patch (patches/wb/build.py) AND a v0.2 bundle table
(patches/bundles/build.py), e.g. a tools/merge_specs.py result. Builds the package in memory with
tools/build_package.build(), decodes the patched and the restore (= stock) main payloads, and runs
code from THOSE payloads, stock vs patched on the same fixture.

The property getter 0x6005e971 is NOT faked: the real getter, registry lookup 0x6005d924, typed
read 0x6005efbd and per-core translation 0x6005c8cf (CPU 0 -> retf identity) run natively from the
payload over a synthetic registry (0xa26ffa88 + 8*(key>>4), entry+4 = data pointer; overlay flag
0xa26ffa84 = 0; CPU id (0x8050) = 0). A key missing from the registry faults (error path unmapped).

Expected values come from rebuilding the table from the bundle JSON (patches/bundles/build.py
build_table), independent of the image; the package table must equal it.

  U  every redirected site (the 7-byte call from the payload), 8 slots x mode/profile states, CWB,
     invalid profile/mode, mode 6 via 40209, WB categories; plus a hostile table (out-of-range
     values, erased 0xFF flags, bit0 clear, bit7 set). Override -> d0 = slot value; otherwise d0
     and ALL registers (d0-d3, a0-a3, sp, pc, mdr, psw, lir, lar) == stock. Override: all
     registers == stock except d0 (value), a0 and psw (caller-saved scratch). Stack above the
     call frame byte-identical; peak depth reported.
  K  a key other than A-B/G-M through the stub -> identical to the stock getter.
  W  native capture WB segment 0x60302c0f..0x60302fc9 (stock code, redirected sites): per WB
     category x state, whole 25000-byte capture block diffed; only +24098/+24100 (A/G) and +1874
     (preset code, cleared by stock for a nonzero fine-tune) may differ, only when active.
  C  native compact-slot (0x6030bb52..0x6030bb7d) and params-builder (0x6030eb58..0x6030eb84)
     sequences: bytes written == slot values (active) / stock (inactive); runs past each site
     until a0 is rewritten.
  G  native gain calculator 0x603b5769 (unchanged bytes): output depends only on the A/G inputs.
  S  stub bytes / site rel32 / RAW sites stock / changed bytes inside edit spans.
  M  mutations of the patched payload: each must make U/W/C fail.

Usage: tools/ep7_verify_wb.py SPEC.json [--json out.json] [--no-mutations]
"""
import argparse, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'patches/bundles'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
import build as BB  # noqa: E402  (patches/bundles/build.py)
from penf_emulator import Region, execute  # noqa: E402
import ep7_sdv3_env as SDV3  # noqa: E402  (SD loader v3: state RAM the --sd-v3 readers read)
execute = SDV3.wrap(execute)

BASE = 0x60020020
GETTER = 0x6005e971
GETTER_CODE = (0x6005c8c0, 0x6005f010)       # 0x6005c8cc retf, 0x6005c8cf, 0x6005d924, getter, 0x6005efbd
XLATE = (0x60078968, 0x60078978)
CPUID, REG_FLAG, REG_BASE, REG_END = 0x8050, 0xa26ffa84, 0xa26ffa88, 0xa2707a88
DATA = 0x15000000
STACK, SP0, STACK_FILL = 0x18010000, 0x18011800, 0xa5
CALLER = 0x18000000
SEG_LO, SEG_HI, SEG_ENTRY, SEG_STOP = 0x60302b00, 0x60303100, 0x60302c0f, 0x60302fc9
JTAB = 0x604ddefc
CAPTURE, CAP_SIZE = 0x13000000, 25000
COMPACT = (0x6030bb40, 0x6030bb90, 0x6030bb52, 0x6030bb7d)   # lo, hi, entry, stop (after mov 0,a0)
PARAMS = (0x6030eb40, 0x6030eb90, 0x6030eb58, 0x6030eb84)    # entry = clr d3 (idx); stop after movbu (5521,a0)
CBUF, CSRC, PBUF = 0x16000000, 0x16001000, 0x17000000
GAIN_FN, GAIN_END, NORM_FN, COEF = 0x603b5769, 0x603b5d3b, 0x603b5675, 0x6050dea4
REGS0 = {'d2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}
ALL_REGS = ['d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'pc', 'mdr', 'psw', 'lir', 'lar']

# Stored WB fine-tune (distinct per index so a wrong index is visible), s8 x 20.
STORED_A = [((i * 3) % 13) - 6 for i in range(20)]
STORED_G = [((i * 5) % 11) - 5 for i in range(20)]
STORED_A[0], STORED_G[0], STORED_A[1], STORED_G[1] = 2, -1, 1, -3


class Ctx:
    def __init__(self, spec):
        w = spec['wb']
        self.keys = w['keys']
        self.ka, self.kg = self.keys['a_b'], self.keys['g_m']
        self.table_at = int(w['layout']['bundle_table'], 16)
        self.f = (w['layout']['wb_flags'], w['layout']['wb_ab'], w['layout']['wb_gm'])
        self.sites = [(int(s['site'], 16), s['key'], s['idx'], s['role']) for s in w['sites']]
        self.raw_sites = [int(s, 16) for s in w['raw_sites_stock']]
        self.code_at, self.code_len = int(w['code_at'], 16), w['code_len']


def s8(v):
    return v - 256 if v >= 128 else v


def sx32(v):
    return struct.unpack('<i', struct.pack('<I', v & 0xffffffff))[0]


def expected_slots(ctx, table):
    """slot -> (ab, gm) when the table entry is a valid override, else None."""
    out = {}
    for s in range(8):
        e = table[s * 64:(s + 1) * 64]
        fl, ab, gm = e[ctx.f[0]], s8(e[ctx.f[1]]), s8(e[ctx.f[2]])
        out[s] = (ab, gm) if (fl & 0x81) == 1 and -7 <= ab <= 7 and -7 <= gm <= 7 else None
    return out


# ------------------------------------------------------------------ registry / regions
def props_for(ctx, wbcat=1, mode=11, mode6=11, color=1, mono=1):
    k = ctx.keys
    return {k['a_b']: bytes(v & 0xff for v in STORED_A), k['g_m']: bytes(v & 0xff for v in STORED_G),
            k['wb_category']: bytes([wbcat]), k['picture_mode']: bytes([mode]), k['picture_mode6']: bytes([mode6]),
            k['color_profile']: bytes([color]), k['mono_profile']: bytes([mono]), 63210: bytes([0xfd] * 12)}


def registry(props):
    reg = bytearray(REG_END - (REG_FLAG - 4) + 8)
    data = bytearray()
    for key, vals in props.items():
        ent = REG_BASE + 8 * (key >> 4) - (REG_FLAG - 4)
        struct.pack_into('<II', reg, ent, key, DATA + len(data))
        data += vals + bytes(-len(vals) % 32 or 32)
    return [Region('registry', REG_FLAG - 4, bytes(reg)), Region('propdata', DATA, bytes(data))]


def sl(main, lo, hi):
    return main[lo - BASE:hi - BASE]


def base_regions(main, props, table=None, stack_words=None):
    st = bytearray([STACK_FILL] * 0x2000)
    for off, v in (stack_words or {}).items():
        struct.pack_into('<I', st, 0x1800 + off, v)
    regs = [Region('getter', GETTER_CODE[0], sl(main, *GETTER_CODE), 'rx'), Region('xlate', XLATE[0], sl(main, *XLATE)),
            Region('cpuid', CPUID, bytes(4)), *registry(props),
            Region('stub', 0x6055e600, sl(main, 0x6055e600, 0x6055e800), 'rx'),
            Region('stack', STACK, bytes(st), 'rw', True)]
    tab_bytes = table if table is not None else sl(main, CTX.table_at, CTX.table_at + 512)
    regs.append(Region('table', CTX.table_at, bytes(tab_bytes)))
    return regs


def stack_info(stk, keep=8):
    """(live stack from SP0-keep up, peak depth below SP0). keep=8: the site's call frame minus
    its 4-byte callee scratch word at (0,sp) (the getter/stub store their own call return addresses
    there); keep=0: from the running function's sp up."""
    lo = next((i for i, b in enumerate(stk) if b != STACK_FILL), len(stk))
    return stk[0x1800 - keep:], 0x1800 - lo


def mem(r):
    return {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}


# ------------------------------------------------------------------ U: sites
def site_run(main, site, key, idx, props, table=None):
    code = Region('site', site - 16, sl(main, site - 16, site + 16), 'rx')
    r = execute([code] + base_regions(main, props, table),
                {'pc': site, 'sp': SP0, 'd0': key, 'd1': idx, 'a0': 0, 'a1': 0xa1a1, **REGS0}, site + 7, limit=5000)
    m = mem(r)
    above, depth = stack_info(m['stack'])
    return dict(fault=r['fault'], regs={k: r['registers'][k] for k in ALL_REGS}, d0=sx32(r['registers']['d0']),
                above=above, depth=depth)


def u_states(ctx, exp):
    """(name, props kwargs, expected slot or None for stock)."""
    st = []
    for s in range(8):
        mode, prof = (11, s + 1) if s < 4 else (12, s - 3)
        kw = dict(mode=mode, color=prof if mode == 11 else 1, mono=prof if mode == 12 else 1)
        st.append((f'{ctx_slot(s)} (mode {mode} profile {prof})', kw, s if exp[s] else None))
    first = next((s for s in range(8) if exp[s]), None)
    fm = (11 if first is None or first < 4 else 12)
    fp = 1 if first is None else first % 4 + 1
    fkw = dict(mode=fm, color=fp if fm == 11 else 1, mono=fp if fm == 12 else 1)
    st += [(f'CWB (cat 3), {ctx_slot(first)}', dict(fkw, wbcat=3), None),
           (f'Auto (cat 0), {ctx_slot(first)}', dict(fkw, wbcat=0), first),
           (f'one-touch (cat 2), {ctx_slot(first)}', dict(fkw, wbcat=2), first),
           (f'cat 4, {ctx_slot(first)}', dict(fkw, wbcat=4), first),
           ('mode 6 -> 40209=11, COLOR2', dict(mode=6, mode6=11, color=2), 1 if exp[1] else None),
           ('mode 6 -> 40209=12, MONO1', dict(mode=6, mode6=12, mono=1), 4 if exp[4] else None),
           ('mode 6 -> 40209=5', dict(mode=6, mode6=5, color=1), None),
           ('mode 6 -> 40209=6', dict(mode=6, mode6=6, color=1), None),
           ('COLOR profile 0', dict(mode=11, color=0), None), ('COLOR profile 5', dict(mode=11, color=5), None),
           ('COLOR profile 255', dict(mode=11, color=255), None), ('MONO profile 0', dict(mode=12, mono=0), None),
           ('MONO profile 5', dict(mode=12, mono=5), None),
           ('mode 5 (Natural)', dict(mode=5, color=1), None), ('mode 0', dict(mode=0, color=1), None),
           ('mode 13', dict(mode=13, color=1), None), ('mode 104', dict(mode=104, color=1), None),
           ('mode 10', dict(mode=10, color=1), None)]
    return st


def ctx_slot(s):
    return BB.SLOTS[s] if s is not None else 'no-override-slot'


def slot_kw(slot):
    mode, prof = (11, slot + 1) if slot < 4 else (12, slot - 3)
    return dict(mode=mode, color=prof if mode == 11 else 1, mono=prof if mode == 12 else 1)


def hostile_cases(ctx):
    """[(name, table bytes, props kwargs, expected (ab, gm) or None)] - tables the bundle builder
    would never emit, to reach the stub's defensive checks."""
    def tab(entries):
        t = bytearray(512)
        for s_, (fl, ab, gm) in entries.items():
            t[s_ * 64 + ctx.f[0]], t[s_ * 64 + ctx.f[1]], t[s_ * 64 + ctx.f[2]] = fl, ab & 0xff, gm & 0xff
        return bytes(t)
    per_slot = {0: (1, 8, 0, False), 1: (1, 0, -8, False), 2: (1, -128, 127, False), 3: (0xff, -1, -1, False),
                4: (0x02, 3, 3, False), 5: (0x81, 3, 3, False), 6: (0x03, 7, -7, True), 7: (0x01, -7, 7, True)}
    t1 = tab({s_: v[:3] for s_, v in per_slot.items()})
    cases = [(f'slot {s_} flags={fl:#x} ab={ab} gm={gm}', t1, slot_kw(s_), (ab, gm) if ov else None)
             for s_, (fl, ab, gm, ov) in per_slot.items()]
    valid = tab({s_: (1, 5, -5) for s_ in range(8)})
    cases += [('wb_gm = +8', tab({0: (1, 0, 8)}), slot_kw(0), None),
              ('wb_ab = -8', tab({0: (1, -8, 0)}), slot_kw(0), None),
              ('all slots valid, COLOR profile 5', valid, dict(mode=11, color=5), None),
              ('all slots valid, MONO profile 5', valid, dict(mode=12, mono=5), None),
              ('all slots valid, COLOR profile 0', valid, dict(mode=11, color=0), None),
              ('all slots valid, mode 5', valid, dict(mode=5, color=1), None),
              ('all slots valid, CWB', valid, dict(slot_kw(0), wbcat=3), None),
              ('MONO1 valid (5,-5)', valid, slot_kw(4), (5, -5)),
              ('MONO4 valid (5,-5)', valid, slot_kw(7), (5, -5))]
    return cases


def compare_site(s, p, want, key_is_a):
    """want: None (stock) or (ab, gm)."""
    if s['fault'] or p['fault']:
        return False, 'fault'
    if s['regs']['pc'] != p['regs']['pc'] or s['above'] != p['above']:
        return False, 'pc/stack differ'
    if want is None:
        diff = [k for k in ALL_REGS if s['regs'][k] != p['regs'][k]]
        return not diff, f'regs differ {diff}' if diff else 'stock-identical'
    v = want[0] if key_is_a else want[1]
    diff = [k for k in ALL_REGS if k not in ('d0', 'a0', 'psw') and s['regs'][k] != p['regs'][k]]
    if p['d0'] != v:
        return False, f'd0 {p["d0"]} != {v}'
    return not diff, f'override {v}' + (f'; regs differ {diff}' if diff else '')


def check_sites(ctx, stock, patched, exp, cache, sites=None, hostile=True):
    rows, ok, depth = [], True, [0, 0]
    sites = sites or ctx.sites
    for site, key, idx, role in sites:
        for name, kw, slot in u_states(ctx, exp):
            props = props_for(ctx, **kw)
            ck = ('u', site, name)
            if ck not in cache:
                cache[ck] = site_run(stock, site, key, idx, props)
            s = cache[ck]
            p = site_run(patched, site, key, idx, props)
            want = exp[slot] if slot is not None else None
            good, why = compare_site(s, p, want, key == ctx.ka)
            stored = (STORED_A if key == ctx.ka else STORED_G)[idx]
            good &= s['d0'] == stored
            ok &= good
            depth = [max(depth[0], s['depth']), max(depth[1], p['depth'])]
            if not good or slot is not None or 'CWB' in name:
                rows.append(dict(site=hex(site), key=hex(key), idx=idx, state=name, stock=s['d0'], patched=p['d0'],
                                 ok=bool(good), why=why))
        if hostile:
            for hname, tab, kw, want in hostile_cases(ctx):
                props = props_for(ctx, **kw)
                ck = ('h', site, hname)
                if ck not in cache:
                    cache[ck] = site_run(stock, site, key, idx, props)
                s = cache[ck]
                p = site_run(patched, site, key, idx, props, tab)
                good, why = compare_site(s, p, want, key == ctx.ka)
                ok &= good
                rows.append(dict(site=hex(site), key=hex(key), state=f'hostile: {hname}',
                                 stock=s['d0'], patched=p['d0'], ok=bool(good), why=why))
    return ok, rows, dict(stock_peak_depth=depth[0], patched_peak_depth=depth[1])


# ------------------------------------------------------------------ K: other key through the stub
def check_other_key(ctx, stock, patched):
    rows, ok = [], True
    for key, idx in ((63210, 3), (ctx.keys['picture_mode'], 0)):
        props = props_for(ctx, mode=11, color=1)
        res = []
        for main, target in ((stock, GETTER), (patched, ctx.code_at)):
            call = Region('caller', CALLER, b'\xdd' + struct.pack('<i', target - CALLER) + b'\xc0\x0c\xcb', 'rx')
            r = execute([call] + base_regions(main, props), {'pc': CALLER, 'sp': SP0, 'd0': key, 'd1': idx, 'a0': 0,
                                                             'a1': 0xa1a1, **REGS0}, CALLER + 7, limit=5000)
            res.append(r)
        s, p = res
        diff = [k for k in ALL_REGS if s['registers'][k] != p['registers'][k]]
        good = not s['fault'] and not p['fault'] and not diff and \
            stack_info(mem(s)['stack'])[0] == stack_info(mem(p)['stack'])[0]
        ok &= good
        rows.append(dict(key=key, idx=idx, stock=sx32(s['registers']['d0']), patched=sx32(p['registers']['d0']),
                         regs_differ=diff, ok=bool(good)))
    return ok, rows


# ------------------------------------------------------------------ W: native capture segment
def run_segment(main, props, cap_init, table=None):
    cap = bytearray(CAP_SIZE)
    for off, (fmt, v) in cap_init.items():
        struct.pack_into(fmt, cap, off, v)
    regions = base_regions(main, props, table, {8: CAPTURE}) + [
        Region('seg', SEG_LO, sl(main, SEG_LO, SEG_HI), 'rx'), Region('jtab', JTAB, sl(main, JTAB, JTAB + 56)),
        Region('cap', CAPTURE, bytes(cap), 'rw', True)]
    r = execute(regions, {'pc': SEG_ENTRY, 'sp': SP0, **REGS0}, SEG_STOP, limit=20000)
    m = mem(r)
    return r, m['cap'], stack_info(m['stack'], 0)[0]


def h16(cap, off):
    return struct.unpack_from('<h', cap, off)[0]


CATS = {'Auto (cat 0)': (0, {24006: ('<H', 0)}), 'Sunny preset 8 (cat 1)': (1, {24006: ('<H', 1), 24002: ('<H', 8)}),
        'Flash preset 13 (cat 1)': (1, {24006: ('<H', 1), 24002: ('<H', 13)}),
        'One-touch 2 (cat 2)': (2, {24006: ('<H', 2), 24130: ('<H', 2)}),
        'CWB (cat 3)': (3, {24006: ('<H', 3), 24004: ('<H', 5600), 24132: ('<H', 1)}),
        'cat 4': (4, {24006: ('<H', 4)}),
        'global CWB, capture forced cat 1': (3, {24006: ('<H', 1), 24002: ('<H', 8)})}


def w_states(exp):
    st = []
    for s in range(8):
        mode, prof = (11, s + 1) if s < 4 else (12, s - 3)
        st.append((ctx_slot(s), dict(mode=mode, color=prof if mode == 11 else 1, mono=prof if mode == 12 else 1),
                   s if exp[s] else None))
    st += [('COLOR profile 0', dict(mode=11, color=0), None), ('mode 5', dict(mode=5, color=1), None),
           ('mode 6 -> 11 COLOR2', dict(mode=6, mode6=11, color=2), 1 if exp[1] else None)]
    return st


def check_segment(ctx, stock, patched, exp, cache, cats=None, states=None):
    rows, ok, ag = [], True, set()
    allowed = {24098, 24099, 24100, 24101, 1874, 1875, 1916, 1917}
    for cname, (gcat, ci) in (cats or CATS).items():
        for mname, kw, slot in (states or w_states(exp)):
            props = props_for(ctx, wbcat=gcat, **kw)
            ck = ('w', cname, mname)
            if ck not in cache:
                cache[ck] = run_segment(stock, props, ci)
            rs, cs, ss = cache[ck]
            rp, cp, sp_ = run_segment(patched, props, ci)
            diff = sorted(i for i in range(CAP_SIZE) if cs[i] != cp[i])
            active = slot is not None and gcat != 3 and ci[24006][1] != 3
            regs_same = all(rs['registers'][k] == rp['registers'][k] for k in ('d2', 'd3', 'a2', 'a3', 'sp', 'pc', 'mdr'))
            good = (not rs['fault'] and not rp['fault'] and rs['registers']['pc'] == SEG_STOP and regs_same and ss == sp_)
            if active:
                good &= set(diff) <= allowed and (h16(cp, 24098), h16(cp, 24100)) == exp[slot]
            else:
                good &= not diff
            ok &= bool(good)
            why = dict(fault=(rs['fault'], rp['fault']), regs_same=regs_same, stack_same=ss == sp_)
            ag.add((h16(cs, 24098), h16(cs, 24100)))
            ag.add((h16(cp, 24098), h16(cp, 24100)))
            rows.append(dict(category=cname, state=mname, active=active, ok=bool(good), why=why,
                             stock=dict(A=h16(cs, 24098), G=h16(cs, 24100), code_1874=h16(cs, 1874)),
                             patched=dict(A=h16(cp, 24098), G=h16(cp, 24100), code_1874=h16(cp, 1874)),
                             changed_offsets=diff[:8]))
    return ok, rows, ag


# ------------------------------------------------------------------ C: compact slot / params builder
def run_compact(main, props, table=None):
    lo, hi, entry, stop = COMPACT
    regions = base_regions(main, props, table) + [Region('code', lo, sl(main, lo, hi), 'rx'),
                                                  Region('buf', CBUF, bytes(256), 'rw', True),
                                                  Region('src', CSRC, bytes(range(64)))]
    r = execute(regions, {'pc': entry, 'sp': SP0, 'd2': 0x2222, 'd3': 0x3333, 'a2': CBUF, 'a3': CSRC}, stop, limit=5000)
    m = mem(r)
    return r, m['buf'], stack_info(m['stack'], 0)[0]


def run_params(main, props, table=None):
    lo, hi, entry, stop = PARAMS
    regions = base_regions(main, props, table, {28: PBUF}) + [Region('code', lo, sl(main, lo, hi), 'rx'),
                                                              Region('buf', PBUF, bytes(5600), 'rw', True)]
    r = execute(regions, {'pc': entry, 'sp': SP0, 'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}, stop, limit=5000)
    m = mem(r)
    return r, m['buf'], stack_info(m['stack'], 0)[0]


def check_cp(ctx, stock, patched, exp, cache):
    rows, ok = [], True
    for fname, fn, offs in (('compact slot', run_compact, (75, 77)), ('params builder', run_params, (5520, 5521))):
        for mname, kw, slot in w_states(exp) + [('CWB', dict(mode=11, color=1, wbcat=3), None)]:
            props = props_for(ctx, **kw)
            ck = ('c', fname, mname)
            if ck not in cache:
                cache[ck] = fn(stock, props)
            rs, bs, ss = cache[ck]
            rp, bp, sp_ = fn(patched, props)
            stop = (COMPACT if fname == 'compact slot' else PARAMS)[3]
            regs_same = all(rs['registers'][k] == rp['registers'][k] for k in ALL_REGS if k != 'psw')
            good = not rs['fault'] and not rp['fault'] and rp['registers']['pc'] == stop and ss == sp_
            vals = (s8(bp[offs[0]]), s8(bp[offs[1]]))
            if slot is not None:
                diff = [i for i in range(len(bs)) if bs[i] != bp[i]]
                good &= vals == exp[slot] and set(diff) <= set(offs) and \
                    all(rs['registers'][k] == rp['registers'][k] for k in ALL_REGS if k not in ('psw', 'd0'))
            else:
                good &= bs == bp and regs_same
            good &= (s8(bs[offs[0]]), s8(bs[offs[1]])) == (STORED_A[0], STORED_G[0])
            ok &= bool(good)
            rows.append(dict(seq=fname, state=mname, stock=(s8(bs[offs[0]]), s8(bs[offs[1]])), patched=vals, ok=bool(good)))
    return ok, rows


# ------------------------------------------------------------------ G: gain calculator
def gains(main, a, g, base=(600, 450, 300, 300)):
    out, src = 0x14000000, 0x14001000
    call = Region('caller', CALLER, b'\xdd' + struct.pack('<i', GAIN_FN - CALLER) + bytes((0xf0, 80)) + b'\xcb', 'rx')
    st = bytearray(0x2000)
    r = execute([call, Region('stack', STACK, bytes(st), 'rw'), Region('gain', NORM_FN, sl(main, NORM_FN, GAIN_END), 'rx'),
                 Region('coef', COEF, sl(main, COEF, COEF + 24)), Region('src', src, struct.pack('<4H', *base)),
                 Region('out', out, bytes(8), 'rw', True)],
                {'pc': CALLER, 'sp': SP0, 'd0': a & 0xffffffff, 'd1': g & 0xffffffff, 'a0': out, 'a1': src, **REGS0},
                CALLER + 7, limit=20000)
    good = not r['fault'] and r['registers']['pc'] == CALLER + 7 and r['registers']['sp'] == SP0 and \
        all(r['registers'][k] == v for k, v in REGS0.items())
    return good, struct.unpack('<4H', mem(r)['out'])


def check_gains(stock, patched, ag):
    rows, ok = [], True
    same_code = sl(stock, NORM_FN, GAIN_END) == sl(patched, NORM_FN, GAIN_END) and \
        sl(stock, COEF, COEF + 24) == sl(patched, COEF, COEF + 24)
    pairs = sorted(ag | {(0, 0), (7, 7), (-7, -7), (7, -7), (-7, 7)})
    outs = {}
    for a, g in pairs:
        gs, os_ = gains(stock, a, g)
        gp, op = gains(patched, a, g)
        good = gs and gp and os_ == op
        ok &= good
        outs[(a, g)] = op
        rows.append(dict(A=a, G=g, out=op, ok=bool(good)))
    zero = outs[(0, 0)]
    moves = all(o != zero for k, o in outs.items() if k != (0, 0))
    # output is a function of (A, G) only: identical inputs -> identical outputs on both images
    return bool(ok and same_code and moves), rows, dict(code_identical=same_code, nonzero_moves=moves)


# ------------------------------------------------------------------ S: static
def check_static(ctx, spec, stock, patched):
    import numpy as np
    idx = np.nonzero(np.frombuffer(stock, np.uint8) != np.frombuffer(patched, np.uint8))[0] + BASE
    spans = [(int(e['addr'], 16), int(e['addr'], 16) + len(bytes.fromhex(e['new']))) for e in spec['edits']]
    in_spans = bool(all(any(s <= x < t for s, t in spans) for x in idx))
    sites_ok = all(patched[s - BASE] == 0xdd and patched[s + 5 - BASE:s + 7 - BASE] == b'\xc0\x0c' and
                   s + struct.unpack_from('<i', patched, s + 1 - BASE)[0] == ctx.code_at and
                   stock[s - BASE:s - BASE + 7][5:] == b'\xc0\x0c' and
                   s + struct.unpack_from('<i', stock, s + 1 - BASE)[0] == GETTER for s, *_ in ctx.sites)
    raw_ok = all(patched[s - BASE:s + 7 - BASE] == stock[s - BASE:s + 7 - BASE] and
                 s + struct.unpack_from('<i', stock, s + 1 - BASE)[0] == GETTER for s in ctx.raw_sites)
    tail = sl(patched, ctx.code_at + ctx.code_len, 0x6055e7b0)
    guard_ok = set(tail) <= {0xff} and ctx.code_at + ctx.code_len <= 0x6055e7a6
    return dict(in_spans=in_spans, changed=len(idx), spans=len(spans), sites_redirected=sites_ok,
                raw_sites_stock=raw_ok, reservation_and_gap_ok=guard_ok), in_spans and sites_ok and raw_ok and guard_ok


# ------------------------------------------------------------------ M: mutations
def find_once(buf, pat, lo, hi):
    seg = buf[lo - BASE:hi - BASE]
    i = seg.find(pat)
    if i < 0 or seg.find(pat, i + 1) >= 0:
        raise ValueError(f'mutation pattern {pat.hex()} not unique')
    return lo + i


def mutations(ctx, patched):
    lo, hi = ctx.code_at, ctx.code_at + ctx.code_len
    out = []

    def mut(name, pat, new, nth_after=None):
        at = find_once(patched, pat, nth_after or lo, hi)
        m = bytearray(patched)
        m[at - BASE:at - BASE + len(new)] = new
        out.append((name, bytes(m)))

    k = ctx.keys
    s16 = lambda v: struct.pack('<h', v - 0x10000 if v & 0x8000 else v)
    mut('CWB check 3 -> 0x7f', b'\xa0\x03\xc8', b'\xa0\x7f')
    mut('mode 12 -> 13', b'\xa0\x0c\xc9', b'\xa0\x0d')
    mut('mode 11 -> 10', b'\xa0\x0b\xc8', b'\xa0\x0a')
    color = find_once(patched, b'\x2c' + s16(k['color_profile']), lo, hi)
    mut('COLOR profile bound 4 -> 5', b'\xa0\x04\xc6', b'\xa0\x05', color)
    mut('COLOR no -1 on profile', b'\x28\xff', b'\x28\x00', color)
    mut('MONO slot +4 -> +3', b'\x28\x04', b'\x28\x03')
    mut('flags mask 0x81 -> 0x01 (erased table accepted)', b'\xf8\xe0\x81', b'\xf8\xe0\x01')
    mut('flags test cmp 1 -> cmp 0', b'\xa0\x01\xc9', b'\xa0\x00')
    mut('wb_ab range 15 -> 16', b'\xa0\x0f\xc6', b'\xa0\x10')
    mut('wb_gm range 15 -> 16', b'\xa5\x0f\xc6', b'\xa5\x10')
    mut('A/G selector inverted', b'\xf8\xee\x80\xc9', b'\xf8\xee\x80\xc8')
    mut(f'wb_ab offset {ctx.f[1]} -> {ctx.f[2]}', b'\xf8\x40' + bytes([ctx.f[1]]), b'\xf8\x40' + bytes([ctx.f[2]]))
    mut('slot stride 64 -> 16 (one asl2 nop)', b'\x54\x54\x54', b'\x54\x54\xcb')
    mut('mode-6 key 40209 -> 38017', b'\x2c' + s16(k['picture_mode6']), b'\x2c' + s16(k['picture_mode']))
    mut('G key compare -> A key', b'\xfa\xca' + s16(k['g_m']), b'\xfa\xca' + s16(k['a_b']))
    mut('pass path idx from d2', b'\x8d\x90\x00\xdc', b'\x89\x90\x00\xdc')
    mut('override d1 not restored', b'\x28\xf9\x8d', b'\x28\xf9\xcb')
    mut('stub ret frame [d2,d3] -> [d2]', b'\x28\xf9\x8d\xdf\xc0', b'\x28\xf9\x8d\xdf\x80')
    m = bytearray(patched)
    s0 = ctx.sites[0][0]
    m[s0 + 1 - BASE:s0 + 5 - BASE] = struct.pack('<i', GETTER - s0)
    out.append((f'site {s0:#x} left stock (not redirected)', bytes(m)))
    m = bytearray(patched)
    s1 = next(s for s, *_ in ctx.sites if s == 0x6030bb6e)
    m[s1 + 1 - BASE:s1 + 5 - BASE] = struct.pack('<i', GETTER - s1)
    out.append((f'site {s1:#x} left stock (compact G)', bytes(m)))
    return out


CORE_SITES = (0x60302c46, 0x60302c60, 0x6030bb6e, 0x6030eb61, 0x60302db8)


def core_suite(ctx, stock, img, exp, cache):
    res = {}
    sites = [x for x in ctx.sites if x[0] in CORE_SITES]
    res['U'] = check_sites(ctx, stock, img, exp, cache, sites)[0]
    cats = {k: CATS[k] for k in ('Sunny preset 8 (cat 1)', 'CWB (cat 3)', 'Auto (cat 0)')}
    res['W'] = check_segment(ctx, stock, img, exp, cache, cats)[0]
    res['C'] = check_cp(ctx, stock, img, exp, cache)[0]
    return all(res.values()), [k for k, v in res.items() if not v]


CTX = None


def main():
    global CTX
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--no-mutations', action='store_true')
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    for k in ('wb', 'bundle', 'table_hex'):
        if k not in spec:
            sys.exit(f'spec lacks {k!r}: needs the WB patch AND a bundles table (merge with tools/merge_specs.py)')
    CTX = ctx = Ctx(spec)
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    bpath = Path(spec['bundle'])
    bundle = json.loads((bpath if bpath.is_absolute() else ROOT / bpath).read_text())
    table, slots = BB.build_table(bundle, BB.load_recipes())
    pkg_table = sl(patched, ctx.table_at, ctx.table_at + 512)
    table_ok = pkg_table == table and table.hex() == spec['table_hex']
    exp = expected_slots(ctx, table)
    print(f"expected per-slot WB (from {spec['bundle']}): " +
          ', '.join(f'{BB.SLOTS[s]}={exp[s]}' for s in range(8)))
    results, cache = [], {}
    results.append(dict(test='T table in package == table rebuilt from bundle JSON', passed=table_ok))
    st, st_ok = check_static(ctx, spec, stock, patched)
    results.append(dict(test='S static: rel32s, RAW sites stock, reservation, changed bytes in spans', passed=st_ok, detail=st))
    ok, rows, depth = check_sites(ctx, stock, patched, exp, cache)
    results.append(dict(test=f'U {len(ctx.sites)} sites x states + hostile table (real getter)', passed=ok,
                        detail=depth, rows=rows))
    ok, rows = check_other_key(ctx, stock, patched)
    results.append(dict(test='K other key through stub == stock getter', passed=ok, rows=rows))
    ok, rows, ag = check_segment(ctx, stock, patched, exp, cache)
    results.append(dict(test='W native capture WB segment', passed=ok, rows=rows))
    ok, rows = check_cp(ctx, stock, patched, exp, cache)
    results.append(dict(test='C native compact-slot / params-builder sequences', passed=ok, rows=rows))
    ok, rows, gd = check_gains(stock, patched, ag)
    results.append(dict(test='G gain calculator: output moves only with A/G', passed=ok, detail=gd, rows=rows))
    allok = all(r['passed'] for r in results)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['test']}" + (f"  {r['detail']}" if 'detail' in r else ''))
        bad = [x for x in r.get('rows', []) if not x['ok']]
        for x in bad[:8]:
            print('      BAD', x)
    for x in results[4]['rows']:
        if x['active'] or x['category'].startswith(('CWB', 'global')):
            print(f"      W {x['category']:<34} {x['state']:<20} stock A/G {x['stock']['A']:+d}/{x['stock']['G']:+d} -> "
                  f"patched {x['patched']['A']:+d}/{x['patched']['G']:+d}{'' if x['ok'] else '  BAD'}")
    mres = []
    if not a.no_mutations:
        if not allok:
            print('skipping mutations: base suite failed')
        else:
            for name, img in mutations(ctx, patched):
                good, failing = core_suite(ctx, stock, img, exp, cache)
                mres.append(dict(mutation=name, detected=not good, failing=failing))
                print(f"{'PASS' if not good else 'FAIL'}  M mutation '{name}' detected by {failing}")
            allok &= all(m['detected'] for m in mres)
    print(f"{'PASS' if allok else 'FAIL'}  overall; package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.edits), package=info, passed=allok, expected=exp, results=results,
                                          mutations=mres, scope='emulator only; synthetic registry/fixtures; real getter '
                                          'code; CPU code, not ISP/pixels; no camera contacted'), indent=1, default=str))
    sys.exit(0 if allok else 1)


if __name__ == '__main__':
    main()
