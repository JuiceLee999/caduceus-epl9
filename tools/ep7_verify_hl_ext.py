#!/usr/bin/env python3
"""Lean emulator checks for the v0.17 extended hue/light (patches/hl_ext; offline, emulator only, no camera).

  .venv/bin/python -I tools/ep7_verify_hl_ext.py releases/v0.17/edits.json --base releases/v0.16/edits.json [--json out]

  X  capture reader (selector -> hl -> builder, native): a table with values across -15..15 on all COLOR slots ->
     hue/L of the 12 records == HUE_LUT_X/L_LUT_X rows; saturation, other output bytes, job, context, registers ==
     stock run.
  O  old values identical: the base (v0.16) table and a dense -7..7 table give byte-identical output, job, context,
     stack and registers on the new image and on the base image (capture and live view).
  R  range guards: +16, -16, +127, -128 in hue or light -> output == stock (capture and live view).
  V  live view (lv, getter native): extended table, job without transport == capture job, rows == extended LUT.
  T  range tables: the image's loader sd_lo/sd_span and fm_lo/fm_span == patches/sd_bundles RANGES; desktop mirrors
     (BUNDLES.BIN / LOOKS.BIN) accept -15..15 and the base release's card files, reject 16; sd_back -> 0x605b7340.
  B  anti-brick: every component of the package == stock + edits, the restore package == stock, changed bytes only
     inside the edit spans, labels of the reader / loader / lv unchanged vs base.
"""
import argparse, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import ep7_verify_bundles as VB  # noqa: E402
import ep7_verify_lv_bundles as LVV  # noqa: E402
BP, oc, PR, BB = VB.BP, VB.oc, VB.PR, VB.BB
import importlib.util  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


SB = _load('ep7_sd_bundles_build', ROOT / 'patches/sd_bundles/build.py')
BBIN = _load('ep7_bundles_bin', ROOT / 'tools/ep7_bundles_bin.py')
LOOKS = _load('ep7_looks_bin', ROOT / 'tools/ep7_looks_bin.py')
BASE = 0x60020020
SAT = VB.SATS[1]


def s8(b):
    return [x - 256 if x > 127 else x for x in b]


def ext_table(base_hex):
    t = bytearray(bytes.fromhex(base_hex))
    for s in range(4):
        for i in range(12):
            t[64 * s + i] = (((i * 5 + s * 7) % 31) - 15) & 0xff
            t[64 * s + 12 + i] = (((i * 11 + s * 3 + 4) % 31) - 15) & 0xff
        t[64 * s + 31] |= BB.FLAG_HL
    t[0] = 15 & 0xff; t[1] = -15 & 0xff; t[12] = 15 & 0xff; t[13] = -15 & 0xff   # endpoints
    return bytes(t)


def legacy_table(base_hex):
    t = bytearray(bytes.fromhex(base_hex))
    for s in range(4):
        for i in range(24):
            t[64 * s + i] = (((i * 4 + s * 3) % 15) - 7) & 0xff
        t[64 * s + 31] |= BB.FLAG_HL
    return bytes(t)


def rows(t, slot):
    e = t[64 * slot:64 * slot + 64]
    return BB.native_rows(s8(e[0:12]), s8(e[12:24]))


def cap(img, sat, p, **kw):
    """Capture job (transport marker 0xB2, profile p) through the full release selector path (hl and lv mapped)."""
    return LVV.run(img, sat, profile=0, magic=BB.MAGIC, ext_profile=p, reg=False, **kw)


def eq(a, b, ext=False):
    return all(LVV.same(a, b, ext).values())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spec', type=Path)
    ap.add_argument('--base', type=Path, required=True)
    ap.add_argument('--card', type=Path, help='base release card dir (EP7MOD/...) whose files must still pass')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    spec, base = json.loads(a.spec.read_text()), json.loads(a.base.read_text())
    stock_raw = BP.STOCK.read_bytes()
    pkg, restore, info = BP.build(spec, stock_raw)
    bpkg, _, _ = BP.build(base, stock_raw)
    new, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    old = oc.parse(bpkg)[0].payload
    LVV.STOCK_IMG[0] = stock
    res = []

    def rec(name, ok, **kw):
        res.append(dict(test=name, passed=bool(ok), **kw))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ('' if ok else f'  {kw}'))

    xt, lt, bt = ext_table(spec['table_hex']), legacy_table(spec['table_hex']), bytes.fromhex(base['table_hex'])
    imgx = VB.with_table(new, spec, xt)
    # X capture
    for p in (1, 2, 3, 4):
        for sat in (VB.SATS[0], SAT):
            okp, mp, rp = cap(imgx, sat, p)
            oks, ms, rs = cap(stock, sat, p)
            r_p, r_s = PR.records(mp['out']), PR.records(ms['out'])
            want = rows(xt, p - 1)
            hl = all((r_p[i]['hue'], r_p[i]['light']) == want[i] for i in range(12))
            rest = VB.mask_hl(mp['out']) == VB.mask_hl(ms['out']) and all(r_p[i]['sat'] == r_s[i]['sat'] for i in range(12))
            good = okp and oks and hl and rest and mp['job'] == ms['job'] and mp['ctx'] == ms['ctx'] and \
                VB.regs_of(rp) == VB.regs_of(rs)
            rec(f'X capture COLOR{p} sat={sat[:2]}.. extended rows', good, hl=hl, rest=rest)
    nc = cap(old, SAT, 1, table=xt, spec=base)
    st1 = cap(stock, SAT, 1)
    rec('X control: base (v0.16) image renders the extended table stock', nc[0] and nc[1]['out'] == st1[1]['out'])
    m = bytearray(imgx); m[BB.HLX_AT + 2 * 30 - BASE] ^= 1        # hue LUT[+15] corrupted
    rec('X control: corrupted extended LUT is detected', not all(
        (PR.records(cap(bytes(m), SAT, 1)[1]['out'])[i]['hue'], 0) == (rows(xt, 0)[i][0], 0) for i in range(12)))
    # O old values identical (capture + live view), new vs base image
    for tn, tb in (('v0.16 table', bt), ('dense -7..7', lt)):
        for p in (1, 2, 3, 4):
            a1 = cap(new, SAT, p, table=tb, spec=spec)
            a0 = cap(old, SAT, p, table=tb, spec=base)
            rec(f'O capture {tn} COLOR{p} new == base', eq(a1, a0))
            l1 = LVV.run(new, SAT, profile=p, magic=0, table=tb, spec=spec)
            l0 = LVV.run(old, SAT, profile=p, magic=0, table=tb, spec=base)
            rec(f'O live view {tn} COLOR{p} new == base', eq(l1, l0))
    # V live view extended
    for p in (1, 2, 3, 4):
        lv = LVV.run(new, SAT, profile=p, magic=0, table=xt, spec=spec)
        cp = cap(new, SAT, p, table=xt, spec=spec)
        r = PR.records(lv[1]['out'])
        want = rows(xt, p - 1)
        hl = all((r[i]['hue'], r[i]['light']) == want[i] for i in range(12))
        rec(f'V live view COLOR{p} extended == capture, rows', hl and eq(lv, cp, ext=True), hl=hl)
    # R guards
    for name, off, v in (('hue[3]=+16', 3, 16), ('hue[7]=-16', 7, -16), ('light[2]=+127', 14, 127),
                         ('light[11]=-128', 23, -128)):
        t = bytearray(xt); t[64 + off] = v & 0xff
        c = cap(new, SAT, 2, table=bytes(t), spec=spec)
        st = cap(stock, SAT, 2)
        rec(f'R capture COLOR2 {name} -> stock', c[0] and c[1]['out'] == st[1]['out'] and VB.regs_of(c[2]) == VB.regs_of(st[2]))
        lv = LVV.run(new, SAT, profile=2, magic=0, table=bytes(t), spec=spec)
        ls = LVV.run(stock, SAT, profile=2, magic=0, reg=False)
        rec(f'R live view COLOR2 {name} -> stock', lv[0] and lv[1]['out'] == ls[1]['out'])
    # T range tables + desktop mirrors
    lay = SB.layout()
    lo, sp, _ = SB.range_table(lay)
    lo0, sp0, _ = SB.range_table(lay, SB.RANGES_LEGACY)
    b8 = lambda v: bytes(x & 0xff for x in v)  # noqa: E731
    ld = new[0x605b7400 - BASE:0x605b7400 - BASE + 865]
    rec('T loader sd_lo/sd_span == RANGES (-15..15), legacy gone', ld.count(b8(lo) + b8(sp)) == 1 and b8(lo0) + b8(sp0) not in ld)
    fm_at = int(spec['hl_ext']['film_menu_edit'], 16)
    fm = new[fm_at - BASE:fm_at - BASE + 978]
    rec('T fm_lo/fm_span == RANGES[:45]', fm.count(b8(lo[:45])) == 1 and fm.count(b8(sp[:45])) == 1)
    rec('T sd_back 0x605b7420 -> jmp 0x605b7340', new[0x605b7420 - BASE:0x605b7425 - BASE].hex() == 'dc20ffffff')
    t = bytearray(xt)
    rec('T table_ok accepts -15..15', SB.table_ok(bytes(t), lo, sp))
    t[5] = 16
    rec('T table_ok rejects +16', not SB.table_ok(bytes(t), lo, sp))
    t[5] = (-16) & 0xff
    rec('T table_ok rejects -16', not SB.table_ok(bytes(t), lo, sp))
    if a.card:
        bb = (a.card / 'EP7MOD/BUNDLES.BIN').read_bytes()
        rec('T base card BUNDLES.BIN table passes the new ranges', SB.table_ok(bb[SB.HDR_LEN:SB.FILE_LEN], lo, sp))
        lk = (a.card / 'EP7MOD/LOOKS.BIN').read_bytes()
        rec('T base card LOOKS.BIN passes the new rules', LOOKS.check_file(lk) == [])
    sys.path.insert(0, str(ROOT / 'sim'))
    import pipeline as SIM
    rec('T sim LUTs == firmware LUTs', SIM.HUE_LUT_X == BB.HUE_LUT_X and SIM.L_LUT_X == BB.L_LUT_X)
    # B anti-brick
    sk = {c.kind: c.payload for c in oc.parse(stock_raw)}
    pk = {c.kind: c.payload for c in oc.parse(pkg)}
    rk = {c.kind: c.payload for c in oc.parse(restore)}
    kinds = [int(k, 16) for k in spec['components']]
    ok_b = set(pk) == set(rk) == set(kinds)
    for k in kinds:
        m = bytearray(sk[k])
        for e in spec['edits']:
            if int(e['kind'], 16) != k:
                continue
            o = BP.resolve(k, e["addr"])
            n = bytes.fromhex(e['new'])
            ok_b &= bytes(m[o:o + len(n)]) == bytes.fromhex(e['expect'])
            m[o:o + len(n)] = n
        rec(f'B component {k:#x}: package == stock + edits (expect bytes matched)', ok_b and bytes(m) == pk[k])
        rec(f'B component {k:#x}: restore == stock', rk[k] == sk[k])
    lab0, lab1 = BB.reader(bytes.fromhex(base['table_hex']), True, False)[3], BB.reader(bytes.fromhex(spec['table_hex']), True, True)[3]
    rec('B reader labels unchanged', lab0 == lab1 and {k: hex(v) for k, v in lab1.items()} == {k: v for k, v in base['labels'].items() if k in lab1})
    nb = {e['addr']: len(e['new']) for e in base['edits']}
    rec('B every base edit kept its length; one edit added', all(nb.get(e['addr'], len(e['new'])) == len(e['new']) for e in spec['edits'])
        and len(spec['edits']) == len(base['edits']) + 1)
    ok = all(x['passed'] for x in res)
    print(f"{'PASS' if ok else 'FAIL'}  overall {sum(x['passed'] for x in res)}/{len(res)}; package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.spec), base=str(a.base), passed=ok, results=res,
                                          scope='emulator only; CPU code, not ISP pixels; no camera'), indent=1, default=str))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
