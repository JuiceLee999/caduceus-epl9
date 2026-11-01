#!/usr/bin/env python3
"""v0.15 emulator checks for the MONO-colour capture path on a BUILT package (offline; emulator only; no camera).

Runs tools/ep7_mono_colour_verify.py's parts on the merged v0.15 spec and adds the v0.15 cases
(docs/MONO_COLOUR.md "v0.15"):

  A  the v0.3-era parts S/C/P/R/X (flashed table, loader state 0 = before the first half-press)
  L  S/C/P/R again with the table SD-loaded (heap pool buffer, flashed copy poisoned: tools/ep7_sdv3_env.py)
  B  boot / no card / corrupt state: loader state 0, 0xFFFF, misaligned handle, handle past the pool limit,
     buffer without 'EP7B', each with a hostile all-colour table in the heap buffer -> the accessor falls back to
     the flashed table (MONO slots colour 0) -> selector, chroma stage and packer == STOCK for MONO1-4
  V  live-view style jobs (no capture transport: marker 0, also an lv_art-style key-11 transport on a key-12
     request) on a loaded all-colour table -> == stock, every MONO profile, every tone
  N  native capture setup per slot type: the real converter transport (conv1 and conv2 segments of the package)
     writes the job extension from a capture record (mode 11 COLOR1-4, mode 12 MONO1-4); that job then runs the
     packer segment, the selector and the chroma stage. Table = the v0.15 default card layout (COLOR1-4 H/L,
     MONO1/2 colour, MONO3/4 mono), flashed and SD-loaded:
       COLOR k        selector == base build (no mono_colour), chroma/packer == stock
       MONO colour    selector == mode-11 reference with request sat = slot sat; chroma out+76 = 0; filter/tone = 0
       MONO mono      selector, chroma, packer == stock
Every image region is mapped read-only/execute (a store into the image faults the run).

Usage: tools/ep7_mono_colour_v15_verify.py SPEC.json [--json out.json]
"""
import argparse, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


MV = _load('ep7_mono_colour_verify', ROOT / 'tools/ep7_mono_colour_verify.py')
SDV3, BB, VB, BP, oc = MV.SDV3, MV.BB, MV.VB, MV.BP, MV.oc
from penf_emulator import Region  # noqa: E402

_EXEC = MV.execute
_extra = []


def _exec(regions, registers, stop_pc, **kw):
    return _EXEC(list(_extra) + list(regions), registers, stop_pc, **kw)


MV.execute = _exec
BUF = SDV3.POOL + 0x2400


def state_regions(state, table, magic=b'EP7B', buf=BUF):
    return [Region('sdv3_state', SDV3.STATE_LO, struct.pack('<HHI', 0, state, 0), 'r'),
            Region('sdv3_pool', buf, magic + bytes(28) + bytes(table), 'r')]


def default_card_table(base_table):
    """COLOR1-4 with H/L, MONO1/2 colour looks (own sat), MONO3/4 plain mono (all zero)."""
    t = bytearray(base_table)
    for k in range(4):
        o = 64 * k
        t[o:o + 64] = bytes(64)
        t[o:o + 24] = struct.pack('<24b', *[((k * 5 + i) % 15) - 7 for i in range(24)])
        t[o + 31] = BB.FLAG_HL
    m = MV.mono_slots()
    t = bytearray(MV.slot_table(bytes(t), {4: m[4], 5: m[5]}))
    for s in (6, 7):
        t[64 * s:64 * s + 64] = bytes(64)
    return bytes(t)


def cmp_stock(stock, img, kw, tones=(0, 1, 4)):
    """selector, chroma (tones) and packer of img == stock for a mode-12 job kw."""
    ok_s, m_s, r_s = MV.sel_run(stock, mode=12, **kw)
    ok_p, m_p, r_p = MV.sel_run(img, mode=12, **kw)
    good = ok_s and ok_p and m_s['out'] == m_p['out'] and m_s['ctx'] == m_p['ctx'] and m_s['job'] == m_p['job'] \
        and MV.regs_of(r_s) == MV.regs_of(r_p) and MV.above_sp(m_s) == MV.above_sp(m_p)
    for tone in tones:
        a = MV.chroma_run(stock, mode=12, tone=tone, **kw)
        b = MV.chroma_run(img, mode=12, tone=tone, **kw)
        good &= a[0] and b[0] and a[1]['out'] == b[1]['out'] and a[1]['job'] == b[1]['job'] and \
            MV.regs_of(a[2]) == MV.regs_of(b[2]) and MV.above_sp(a[1]) == MV.above_sp(b[1])
    pk = {k: v for k, v in kw.items() if k in ('profile', 'ext_mode', 'magic')}
    if set(kw) <= {'profile', 'ext_mode', 'magic'}:
        a = MV.packer_run(stock, mode=12, **pk)
        b = MV.packer_run(img, mode=12, **pk)
        good &= a[0] and b[0] and a[1]['job'] == b[1]['job'] and MV.regs_of(a[2]) == MV.regs_of(b[2])
    return good


def part_b(stock, patched, base_table):
    res = []
    hos = MV.hostile(base_table)
    h = SDV3.handle(BUF)
    states = [('state 0 (before the first half-press)', 0, b'EP7B'), ('state 0xFFFF (no table)', 0xFFFF, b'EP7B'),
              ('handle misaligned (h+2)', h + 2, b'EP7B'), ('handle past the limit (0xa942)', 0xa942, b'EP7B'),
              ('handle 0xFFFE', 0xFFFE, b'EP7B'), ('valid handle, buffer magic EP7b', h, b'EP7b'),
              ('valid handle, buffer zero magic', h, bytes(4))]
    own = patched[MV.TABLE - MV.BASE:MV.TABLE - MV.BASE + 512]
    flashed_mono_off = all(own[64 * s + MV.MC.COLOUR_OFF] != 1 for s in range(4, 8))
    res.append(dict(test='B flashed table: every MONO slot colour != 1 (stock without a card table)',
                    passed=flashed_mono_off))
    for name, st, magic in states:
        _extra[:] = state_regions(st, hos, magic)
        for p in (1, 2, 3, 4):
            good = cmp_stock(stock, patched, dict(profile=p))
            res.append(dict(test=f'B {name}: heap table all-colour, MONO{p} -> stock mono', passed=good))
    _extra[:] = state_regions(h, hos)                       # control: the same heap table, valid handle -> colour
    ok_c, m_c, _ = MV.sel_run(patched, mode=12, profile=2)
    ok_s, m_s, _ = MV.sel_run(stock, mode=12, profile=2)
    res.append(dict(test='B control: valid handle + EP7B -> the heap colour slot is used (selector != stock)',
                    passed=ok_c and ok_s and m_c['out'] != m_s['out']))
    _extra[:] = []
    return res


def part_v(stock, patched, base_table):
    res = []
    SDV3.set_loaded(True)
    img = MV.with_table(patched, MV.hostile(base_table))
    try:
        for p in (1, 2, 3, 4):
            for name, kw in (('LV job (marker 0)', dict(profile=p, magic=0)),
                             ('LV job, lv_art-style key-11 transport on a key-12 request', dict(profile=p, ext_mode=11)),
                             ('LV job, marker 0 + stale profile 0', dict(profile=0, magic=0))):
                good = cmp_stock(stock, img, kw, tones=(0, 1, 2, 3, 4))
                res.append(dict(test=f'V {name} MONO{p}, loaded all-colour table -> stock', passed=good))
    finally:
        SDV3.set_loaded(False)
    return res


def conv_ext(img, which, mode, profile):
    r, mem, _ = VB.conv_run(img, which, mode, profile)
    e = BB.EXT_PROFILE
    return (not r['fault']), mem['job'][e:e + 3]


def part_n(stock, base, patched, base_table, loaded):
    res = []
    tag = 'loaded' if loaded else 'flashed'
    tab = default_card_table(base_table)
    if loaded:
        SDV3.set_loaded(True)
    img_p, img_b = MV.with_table(patched, tab), MV.with_table(base, tab)
    try:
        for slot in range(8):
            mode, prof = (11, slot + 1) if slot < 4 else (12, slot - 3)
            for which in (1, 2):
                okc, ext = conv_ext(img_p, which, mode, prof)
                good = okc and ext == bytes([prof, mode, BB.MAGIC])
                kw = dict(profile=ext[0], ext_mode=ext[1], magic=ext[2])
                e = tab[64 * slot:64 * slot + 64]
                if slot < 4:
                    sat = MV.SATS[1]
                    a = MV.sel_run(img_b, mode=11, sat=sat, **kw)
                    b = MV.sel_run(img_p, mode=11, sat=sat, **kw)
                    good &= a[0] and b[0] and a[1]['out'] == b[1]['out'] and MV.regs_of(a[2]) == MV.regs_of(b[2])
                    for tone in (0, 1):
                        c1 = MV.chroma_run(stock, mode=11, tone=tone, **kw)
                        c2 = MV.chroma_run(img_p, mode=11, tone=tone, **kw)
                        good &= c1[0] and c2[0] and c1[1]['out'] == c2[1]['out'] and MV.regs_of(c1[2]) == MV.regs_of(c2[2])
                    p1, p2 = MV.packer_run(stock, mode=11, **kw), MV.packer_run(img_p, mode=11, **kw)
                    good &= p1[0] and p2[0] and p1[1]['job'] == p2[1]['job']
                    what = 'COLOR: selector == base, chroma/packer == stock'
                elif e[MV.MC.COLOUR_OFF] == 1:
                    v = dict(colour=1, sat=list(struct.unpack('<12b', e[33:45])), hue=list(struct.unpack('<12b', e[0:12])),
                             light=list(struct.unpack('<12b', e[12:24])), hl=bool(e[31] & BB.FLAG_HL))
                    ref = MV.with_table(patched, MV.ref_table(tab, {slot: v}))
                    a = MV.sel_run(img_p, mode=12, **kw)
                    b = MV.sel_run(ref, mode=11, sat=v['sat'], **dict(kw, ext_mode=11))
                    s = MV.sel_run(stock, mode=12, **kw)
                    good &= a[0] and b[0] and a[1]['out'] == b[1]['out'] and a[1]['out'] != s[1]['out']
                    for tone in (0, 1, 3):
                        c = MV.chroma_run(img_p, mode=12, tone=tone, **kw)
                        good &= c[0] and c[3] == 0
                    pk = MV.packer_run(img_p, mode=12, filt=2, tone=3, **kw)
                    F = 36 + 5528
                    good &= pk[0] and pk[1]['job'][F] == 0 and pk[1]['job'][F + 1] == 0
                    what = 'MONO colour: selector == mode-11 ref, chroma 0, filter/tone 0'
                else:
                    good &= cmp_stock(stock, img_p, kw, tones=(0, 1, 2))
                    what = 'MONO mono: == stock'
                res.append(dict(test=f'N {tag} conv{which} slot {BB.SLOTS[slot] if hasattr(BB, "SLOTS") else slot}: {what}',
                                passed=bool(good)))
    finally:
        if loaded:
            SDV3.set_loaded(False)
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    if 'mono_colour' not in spec:
        sys.exit("spec lacks 'mono_colour' metadata")
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    bpkg, _, _ = BP.build(dict(spec, edits=[e for e in spec['edits'] if e.get('owner') != 'mono_colour']),
                          BP.STOCK.read_bytes())
    base = oc.parse(bpkg)[0].payload
    table = patched[MV.TABLE - MV.BASE:MV.TABLE - MV.BASE + 512]
    results = [dict(r, test='A ' + r['test']) for r in MV.static_checks(stock, patched, spec)]
    _, r = MV.run_all(stock, base, patched, table)
    results += [dict(x, test='A ' + x['test']) for x in r]
    results += [dict(x, test='A ' + x['test']) for x in MV.check_real_table(stock, patched, table)[1]]
    SDV3.set_loaded(True)
    try:
        _, r = MV.run_all(stock, base, patched, table)
        results += [dict(x, test='L ' + x['test']) for x in r]
        results += [dict(x, test='L ' + x['test']) for x in MV.check_real_table(stock, patched, table)[1]]
        st = SDV3.stats()
    finally:
        SDV3.set_loaded(False)
    results.append(dict(test=f"L loaded mode relocated the table in {st.get('relocated')} of {st.get('runs')} runs",
                        passed=st.get('relocated', 0) > 0))
    results += part_b(stock, patched, table)
    results += part_v(stock, patched, table)
    results += part_n(stock, base, patched, table, False)
    results += part_n(stock, base, patched, table, True)
    ok = all(x['passed'] for x in results)
    parts = {}
    for x in results:
        k = x['test'].split()[0]
        parts.setdefault(k, [0, 0])
        parts[k][0] += x['passed']
        parts[k][1] += 1
    for x in results:
        if not x['passed']:
            print('FAIL ', x['test'], json.dumps({k: v for k, v in x.items() if k not in ('test', 'passed')}, default=str)[:400])
    print(' '.join(f'{k} {v[0]}/{v[1]}' for k, v in parts.items()))
    print(f"{'PASS' if ok else 'FAIL'}  overall ({sum(x['passed'] for x in results)}/{len(results)}); package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.edits), package=info, passed=ok, parts=parts, results=results,
                                          scope='emulator only; synthetic fixtures; CPU code, not ISP/pixels; no camera'),
                                     indent=1, default=str))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
