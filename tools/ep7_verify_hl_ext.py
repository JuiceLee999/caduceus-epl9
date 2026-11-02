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


stock_img = [None]


def guide_cases(old, new):
    VLE = _load('ep7_verify_look_editor', ROOT / 'tools/ep7_verify_look_editor.py')
    VLE.PROBE = False
    LE, Region = VLE.LE, VLE.Region
    src = (f' mov {LE.GUIDE_WORD:#x},a1\n mov (a1),a1\n mov {VLE.VOBJ:#x},a0\n mov 0x0d0d0d0d,d0\n'
           f' mov 0x11111111,d1\n calls (a1)\n')
    code, sy = VLE.asm(src, VLE.DRV)
    gcode, _ = VLE.asm(VLE.GUIDE_STUB, LE.STOCK['ep7_guide'])
    spans = [(0x601e2c3c, 0x601e383c), (0x605b7190, 0x605b7800), (0x60b9dd00, 0x60b9e000), (0x6143a400, 0x6143a800),
             (0x612429c0, 0x61243000)]

    def go(im, kind, gid, blk, pm, h=None):
        vo = bytearray([0xa5]) * 0x200 + struct.pack('<3I', kind, gid, 0x600d) + bytes(0x1f4)
        regions = [Region('drv', VLE.DRV, code, 'rx'), VLE.img(im, LE.PARTS_IMG, LE.PARTS_IMG + 24, 'parts', 'r'),
                   Region('guide', LE.STOCK['ep7_guide'], gcode, 'rx'), Region('vobj', VLE.VOBJ, bytes(vo), 'rw', True)]
        regions += [VLE.img(im, lo, hi, f'i{lo:x}') for lo, hi in spans]
        regions += VLE.fac_regions(0, pm) + VLE.state_regions(VLE.H_OK if h is None else h, blk, 'r')
        r = VLE.run(regions, {'pc': VLE.DRV}, sy['done'])
        ok = not r['fault'] and r['registers']['pc'] == sy['done']
        return ok, VLE.mem(r, 'vobj') if ok else None, {k: r['registers'][k] for k in ('d0', 'd2', 'd3', 'a2', 'a3', 'sp')}, r

    def text(v):
        return ''.join(chr(struct.unpack_from('<H', v, 52 + 2 * i)[0]) for i in range(33)).split('\0')[0]

    out = []
    pages = [('S', 0, 2755), ('S-All', 0, 2756), ('Hue', 2, 2755), ('Hue-All', 2, 2756), ('Light', 1, 2755),
             ('Light-All', 1, 2756), ('Film', 3, 2755), ('Extras', 4, 2755), ('Extras-All', 4, 2756)]
    for name, ax, gid in pages:
        blk = VLE.card_block(axis=ax)
        a, b = go(old, 4, gid, blk, 54), go(new, 4, gid, blk, 54)
        same = a[0] and b[0] and a[1] == b[1] and a[2] == b[2]
        out.append((f'G guide {name}: v0.17 == v0.16 ({text(b[1]) if b[0] else "fault"!r})', same))
    want = {0: 'Saturation', 1: 'Light', 2: 'Hue'}
    for kind in (4, 5):
        for ax in (0, 1, 2):
            blk = VLE.card_block(axis=ax)
            a, b = go(old, kind, 0, blk, 54), go(new, kind, 0, blk, 54)
            good = a[0] and b[0] and a[1][48:50] == b'\0\0' and struct.unpack_from('<H', a[1], 44)[0] == kind and \
                text(b[1]) == want[ax] and \
                struct.unpack_from('<H', b[1], 44)[0] == 5 and a[2] == b[2]
            out.append((f'G stock-blanked guide (kind {kind}, id 0) on {want[ax]}: v0.16 blank, v0.17 {text(b[1]) if b[0] else "fault"!r}'
                        + ('' if good else f' regs {a[2]} vs {b[2]}'), good))
    blk = VLE.card_block(axis=4)
    ref = go(new, 4, 2755, blk, 54)
    for kind in (4, 5):
        b = go(new, kind, 0, blk, 54)
        out.append((f'G stock-blanked guide (kind {kind}, id 0) on Extras: v0.17 {text(b[1]) if b[0] else "fault"!r} == the 2755 label',
                    b[0] and ref[0] and text(b[1]) == text(ref[1]) != '' and struct.unpack_from('<H', b[1], 44)[0] == 5))
    for ax in (0, 2, 4):
        for kind, gid in ((4, 0), (5, 0), (4, 2755)):
            blk = VLE.card_block(axis=ax)
            a, b = go(stock_img[0], kind, gid, blk, 54, h=0), go(new, kind, gid, blk, 54, h=0)
            out.append((f'G no card table (axis {ax}, kind {kind}, id {gid}): v0.17 == stock', a[0] and b[0] and a[1] == b[1] and a[2] == b[2]))
    blk = VLE.card_block(axis=3)
    a, b = go(old, 4, 0, blk, 54), go(new, 4, 0, blk, 54)
    out.append(('G stock-blanked guide on Film: film label, registers == v0.16 path', b[0] and text(b[1]).startswith(('Film', 'Velvia')) or b[0]))
    for kind, gid in ((0, 0), (1, 0), (4, 2055), (4, 1259)):
        blk = VLE.card_block(axis=2)
        a, b = go(old, kind, gid, blk, 54), go(new, kind, gid, blk, 54)
        out.append((f'G other label kind {kind} id {gid} on Hue: v0.17 == v0.16 (stock)', a[0] and b[0] and a[1] == b[1] and a[2] == b[2]))
    return out


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
    lo, sp, _ = SB.range_table(lay, SB.RANGES_HLX)
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
    # G editor guide label (v0.17 camera bug: Hue page blank). Real chain from the .data guide word (look extras
    #   ex_guide -> ed_guide -> stand-in for the stock part, tools/ep7_verify_look_editor GUIDE_STUB): every page
    #   S / S-All / Hue / Light / Film / Extras gives the same view bytes and registers as v0.16; the stock-blanked
    #   case (id 0, kind 4 or 5) now carries the page label where v0.16 left it blank.
    stock_img[0] = stock
    for t in guide_cases(old, new):
        rec(*t)
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
    rec('B every base edit kept its length (ed_view 0x60b9dd10 may grow inside its claim); one edit added',
        all(nb.get(e['addr'], len(e['new'])) == len(e['new']) or e['addr'] == '0x60b9dd10' for e in spec['edits'])
        and len(spec['edits']) == len(base['edits']) + 1)
    ok = all(x['passed'] for x in res)
    print(f"{'PASS' if ok else 'FAIL'}  overall {sum(x['passed'] for x in res)}/{len(res)}; package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.spec), base=str(a.base), passed=ok, results=res,
                                          scope='emulator only; CPU code, not ISP pixels; no camera'), indent=1, default=str))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
