#!/usr/bin/env python3
"""Emulator checks for grain_fast t1 (real code, synthetic request; says nothing about pixels). Offline.

  .venv/bin/python -I patches/grain_fast/verify.py releases/v0.26/edits.json generated/grain_fast/t1/edits.json [generated/grain_fast/t1/pkg]

  G  gate: stub + real selector from the site. On only for kind 0, type 0x1000, key 11, stage 0, effect 0, one entry, marker,
     mode 11, profile 2..4; every other case (MONO, live view, Movie slot, Glow, Shading) == v0.26, memory and registers
  R  real runner 0x60334db4: COLOR1 and the Movie slot == v0.26; COLOR2/3/4 bank == stock MONO 0x0902 outside the colour stages,
     gain 50/75/100, colour stages == v0.26 COLOR and MONO's grey chroma word absent; HSL, tone, chroma run before the site; one driver pass
  W  real work-list builder: list == v0.26; Glow/Clarity and Art Effect flags are not one entry
  P  anti-brick: package reparses, restore == stock, decoded == stock + edits, only our sites differ from v0.26
"""
import json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools')); sys.path.insert(0, str(ROOT / 'patches/grain_c'))
from penf_emulator import Region, execute  # noqa: E402
import build_package as BP, oly_container as oc  # noqa: E402
import map as M, ep7_grain_verify as GV  # noqa: E402

BASE, SITE, BLOCK = 0x60020020, 0x60339d3c, 0x60210f80
CALLER, STK, JOB, CTX, BANK = 0x18000000, 0x18010000, 0x1e000000, 0x1a000000, 0x1c000000
REQ = JOB + 11364
EARLY = {'HSL COLOR branch': 0x603b02c5, 'tone': 0x603b14ff, 'chroma': 0x603b132a}
BUILDER, RUNNER, AFTER = 0x603396dd, 0x60334db4, 0x60334e0b
GAIN = 7364 + 136                         # bank+7364 = combiner block (0x603a013f), +136 = gain
TABLES = (1696, 6696)                     # colour-stage words of the bank fixture; other bank words are routing and combiner
GREY = 1768                               # chroma stage word: MONO 0x00808001 (constant chroma), COLOR 0
ART = {'Soft Focus / Glow / Clarity': 0x80, 'Pin Hole': 0x400, 'Frame': 0x8000, 'White Edge': 0x2000, 'Star Light': 0x40, 'Art 0x100': 0x100, 'Art 0x200': 0x200, 'Art 0x800': 0x800, 'Art 0x1000': 0x1000}


def image(spec):
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    return [b for b in oc.parse(pkg) if b.kind == 0x100][0].payload, pkg, rst, info


def job(key=11, kind=0, stage=0, jtype=0x1000, effect=0, level=0, profile=2, mode=11, mark=0xb2, n=1, w=5184, h=3888, outs=1):
    j = bytearray(15512)
    j[11314:11316] = struct.pack('<H', n)
    struct.pack_into('<I', j, 11308, key)
    j[15488:15491] = bytes((profile, mode, mark))
    r = bytearray(1884)
    r[8:12] = bytes(((key >> 24) & 255, (key >> 16) & 255)) + struct.pack('<H', key & 0xffff)
    struct.pack_into('<HH', r, 12, stage, jtype)
    r[16] = kind
    r[1828] = level
    struct.pack_into('<H', r, 1838, effect)

    def d(at, base, fmt):
        struct.pack_into('<I', r, at, base)
        struct.pack_into('<HHHH', r, at + 8, fmt, w, w, h)
    d(20, 0x30000000, 0x0104)
    for i in range(outs):
        d(916 + 56 * i, 0x31000000 + i * 0x1000000, 0x0302)
    j[11364:11364 + 1884] = r
    return j


# ------------------------------------------------------------------ G
def site_run(im, j, ctxkey):
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, REQ)
    struct.pack_into('<I', ctx, 52, ctxkey)
    s = lambda lo, hi: im[lo - BASE:hi - BASE]
    rg = [Region('site', 0x60339d00, s(0x60339d00, 0x60339d80), 'rx'), Region('sel', 0x603b5000, s(0x603b5000, 0x603b5800), 'rx'),
          Region('sec1', 0x60210000, s(0x60210000, 0x60211000), 'rx'), Region('data', 0x60532000, s(0x60532000, 0x60534000), 'r'),
          Region('stk', STK, bytes(0x4000), 'rw', True), Region('job', JOB, bytes(j), 'rw', True), Region('ctx', CTX, bytes(ctx), 'rw', True)]
    r = execute(rg, {'pc': SITE, 'sp': STK + 0x2000, 'a0': CTX, 'd2': 0x2222, 'a2': 0xa2a2, 'd3': 0x3333, 'a3': 0xa3a3}, SITE + 7, limit=3000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    rr = r['registers']
    return dict(fault=r['fault'], pc=rr['pc'], d0=rr['d0'] & 255, job=m['job'], ctx=m['ctx'], kept=(rr['sp'], rr['d2'], rr['d3'], rr['a2'], rr['a3']))


def t_gate(old, new):
    on = dict(key=11, kind=0, stage=0, jtype=0x1000, effect=0, profile=2, mode=11, mark=0xb2, n=1)
    cases = [(on, 1), (dict(on, profile=3), 2), (dict(on, profile=4), 3)]
    for k, vs in (('profile', (0, 1, 5, 8, 255)), ('key', (12, 0, 10, 0x01010068, 0x0102000b)), ('jtype', (0, 0x30, 0x34, 0x110, 0x120, 0x1001, 0x1080, 0x3000)),
                  ('kind', (3, 4, 16)), ('stage', (0x0902, 0x0901, 0x0900, 0x0500)), ('effect', (0x0400, 0x0c00, 0x0900)), ('mode', (12, 0)), ('mark', (0, 0xb3)), ('n', (0, 2, 4))):
        cases += [(dict(on, **{k: v}), 0) for v in vs]
    for key in (11, 12):                    # the Movie slot and live view are key 11, marked, COLOR4
        for jt in (0x30, 0x31, 0x34, 0x38):
            for p in (2, 3, 4):
                cases.append((dict(on, key=key, jtype=jt, profile=p), 0))
    bad = []
    for c, lv in cases:
        j = job(**c)
        a, b = site_run(old, j, c['key']), site_run(new, j, c['key'])
        fine = not a['fault'] and not b['fault'] and b['pc'] == SITE + 7 and a['kept'] == b['kept']
        if lv:
            want = bytearray(a['job'])
            want[11364 + 1828] = lv
            want[11364 + 12:11364 + 14] = b'\x02\x09'
            want[11364 + 10:11364 + 12] = b'\x0c\x00'
            fine &= bytes(want) == b['job'] and struct.unpack_from('<I', b['ctx'], 52)[0] == 12 and b['d0'] == 32
        else:
            fine &= a['job'] == b['job'] and a['ctx'] == b['ctx'] and a['d0'] == b['d0']
        if not fine:
            bad.append((c, lv, a['d0'], b['d0'], b['fault']))
    return bad, len(cases)


# ------------------------------------------------------------------ R
def stubbed(im):
    im = bytearray(im)
    for a, code in {0x6034ed4c: b'\xfc\xcc' + struct.pack('<I', BANK) + b'\xdf\xf0\x14',      # bank allocator
                    0x6034442b: b'\x80\x01\xdf\x30\x0c',                                       # lock
                    0x603b1c83: b'\xfc\xdc' + struct.pack('<I', BANK + 0x18000) + b'\xdf\xf0\x24'}.items():
        im[a - BASE:a - BASE + len(code)] = code
    return bytes(im)


def run(im, j):
    wr = b'\xfc\xff' + struct.pack('<i', RUNNER - CALLER) + b'\xcb'
    rg = [Region('img', BASE, im, 'rwx'), Region('img_u', BASE + 0x40000000, im, 'rwx'), Region('stk', STK, bytes(0x4000), 'rw'),
          Region('job', JOB, bytes(j), 'rw', True), Region('bank', BANK, bytes(0x20000), 'rw', True),
          Region('r62', 0x62000000, bytes(0x1000000), 'rw'), Region('rA2', 0xa2000000, bytes(0x1000000), 'rw'),
          Region('caller', CALLER, wr, 'rx'), Region('ms', 0x47001100, bytes(0x5e) + b'\xdf\xa0\x08' + bytes(0x40), 'rx')]
    r = execute(rg, {'pc': CALLER, 'sp': STK + 0x3000, 'a0': REQ}, AFTER, limit=4000000, timeout=300, trace_limit=100000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    return dict(fault=r['fault'], pc=r['registers']['pc'], bank=m['bank'][0x18000:], job=m['job'], pcs=[t['pc'] for t in r['trace']], trunc=r['trace_truncated'])


def words(a, b, skip=False):
    return [o for o in range(0, len(a), 4) if a[o:o + 4] != b[o:o + 4] and not (skip and TABLES[0] <= o < TABLES[1])]


def t_runner(old, new, stock):
    so, sn, ss = stubbed(old), stubbed(new), stubbed(stock)
    bad, n, notes = [], 0, []
    for outs in (1, 2):
        base = run(so, job(profile=1, outs=outs))
        off = run(sn, job(profile=1, outs=outs))
        n += 1
        if base['fault'] or off['fault'] or base['pc'] != AFTER or off['bank'] != base['bank'] or off['job'] != base['job']:
            bad.append(('COLOR1', outs, off['fault'], words(base['bank'], off['bank'])[:6]))
        mv = job(profile=4, jtype=0x30, outs=outs)
        a, b = run(so, mv), run(sn, mv)
        n += 1
        if a['fault'] or b['fault'] or a['bank'] != b['bank'] or a['job'] != b['job']:
            bad.append(('Movie slot', outs, b['fault']))
        for lv, gain in ((1, 50), (2, 75), (3, 100)):
            p = run(sn, job(profile=lv + 1, outs=outs))
            mono = run(ss, job(key=12, stage=0x0902, level=lv, outs=outs))
            col = run(so, job(profile=lv + 1, outs=outs))
            n += 1
            to_mono, to_col = words(mono['bank'], p['bank'], True), words(col['bank'], p['bank'])
            g = struct.unpack_from('<I', p['bank'], GAIN)[0]
            order = [p['pcs'].index(a) if a in p['pcs'] else -1 for a in EARLY.values()]
            at = p['pcs'].index(SITE) if SITE in p['pcs'] else -1
            grey = struct.unpack_from('<I', p['bank'], GREY)[0], struct.unpack_from('<I', mono['bank'], GREY)[0]
            good = (not p['fault'] and p['pc'] == AFTER and not p['trunc'] and not to_mono and g == gain and grey == (0, 0x00808001)
                    and all(0 <= o < at for o in order) and p['pcs'].count(SITE) == 1 and p['pcs'].count(BUILDER) == 1
                    and not [o for o in to_col if TABLES[0] <= o < TABLES[1]])
            if not good:
                bad.append((lv, outs, p['fault'], hex(p['pc']), g, grey, to_mono[:6], order, at, p['pcs'].count(SITE), [o for o in to_col if TABLES[0] <= o < TABLES[1]][:6]))
            elif outs == 1 and lv == 1:
                notes.append(f'{len(to_col)} bank words change, all outside the colour stages: {to_col[:4]}..; order {order} < site {at}')
    return bad, n, notes


# ------------------------------------------------------------------ W
def t_list(old, new):
    bad, n = [], 0
    for key, cls in ((11, 0), (11, 4), (12, 0), (12, 4)):
        for feat in (0, 0x80000, 0x80080):
            a, ae = M.build(old, key, cls, feat=feat)
            b, be = M.build(new, key, cls, feat=feat)
            n += 1
            if not (a['ok'] and b['ok'] and ae == be and a['job'] == b['job']):
                bad.append((key, cls, hex(feat)))
    for name, f in ART.items():
        for cls in (0, 4):
            r, e = M.build(new, 11, cls, feat=0x80000 | f)
            n += 1
            if not r['ok'] or len(e) == 1:
                bad.append((name, cls, len(e), [hex(x[0]) for x in e]))
    return bad, n


# ------------------------------------------------------------------ P
def t_pkg(base_s, new_s, new, pkg, rst, info, disk):
    sb = {b.kind: b for b in oc.parse(BP.STOCK.read_bytes())}
    good = True
    for b in oc.parse(pkg):
        exp = bytearray(sb[b.kind].payload)
        for e in new_s['edits']:
            if int(e['kind'], 16) == b.kind:
                o = BP.resolve(b.kind, e['addr']); nb = bytes.fromhex(e['new']); exp[o:o + len(nb)] = nb
        good &= bytes(exp) == b.payload
    for b in oc.parse(rst):
        good &= b.payload == sb[b.kind].payload
    old, *_ = image(base_s)
    ours = [(0x60339d3d, 4), (BLOCK, 101)] + [(int(e['addr'], 16), len(e['new']) // 2) for e in new_s['edits'] if e.get('source') == 'patches/fw_version']
    diff = [BASE + i for i in range(len(old)) if old[i] != new[i]]
    stray = [hex(a) for a in diff if not any(s <= a < s + n for s, n in ours)]
    good &= not stray
    if disk:
        good &= (disk / 'patched.pkg.bin').read_bytes() == pkg and (disk / 'restore-stock.pkg.bin').read_bytes() == rst
    return good, f'{info["edits"]} edits, {info["changed_payload_bytes"]} B; {len(diff)} B differ from v0.26; stray {stray[:6]}'


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    stock = [b for b in oc.parse(BP.STOCK.read_bytes()) if b.kind == 0x100][0].payload
    old, *_ = image(base_s)
    new, pkg, rst, info = image(new_s)
    ok = True
    bad, n = t_gate(old, new); ok &= not bad
    print(f"{'PASS' if not bad else 'FAIL'} G gate: {n - len(bad)}/{n}", bad[:4] if bad else '')
    bad, n, notes = t_runner(old, new, stock); ok &= not bad
    print(f"{'PASS' if not bad else 'FAIL'} R runner: {n - len(bad)}/{n}", bad[:4] if bad else '', *notes)
    bad, n = t_list(old, new); ok &= not bad
    print(f"{'PASS' if not bad else 'FAIL'} W work list: {n - len(bad)}/{n}", bad[:6] if bad else '')
    good, txt = t_pkg(base_s, new_s, new, pkg, rst, info, disk); ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: {txt}")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
