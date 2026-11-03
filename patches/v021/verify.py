#!/usr/bin/env python3
"""Targeted emulator checks for v0.21 (5 COLOR grain levels). Offline; emulator only.

  .venv/bin/python -I patches/v021/verify.py releases/v0.20/edits.json releases/v0.21/edits.json

  R  loader ranges: the real per-byte range loops of the SD loader v3 (BUNDLES.BIN, 0x605b75e7) and fm_check
     (LOOKS.BIN, 0x6143a607) for slot grain 0..7: v0.21 accepts 0..5, rejects 6/7; v0.20 accepts 0..3 (control)
  G  look extras ex_get grain read (0x601e32c8): byte 0..5 -> value, 6+ -> 0 (v0.20: 4+ -> 0)
  S  ex_set grain clamp (0x601e33bc): wheel value -7..8 -> clamp 0..5 (v0.20: 0..3)
  L  sector-1 label (0x601e355e): 0 "1 Grain Off", 1..5 "1 Grain 1".."1 Grain 5", 6+ -> no label (q_out)
  B  Blur off (issue #20), v0.21 vs the v0.20 control:
     B1 still converter 0x603eab39 (native, via tools/ep7_bloom_verify.conv_run): art 3 (Blur) on a key-11 COLOR job
        gives exactly the flags of art 0 (no 0x100, 0x200 untouched); every other art value / key / mode / profile /
        effect / erased table == v0.20 (Star Light 0x40, Pin Hole 0x400 kept); control: v0.20 adds 0x100 for art 3
     B2 lv_art hook (patches/lv_art/verify.hook_run): art 3 -> job == art 0 (no 0x100); art 2 Pin Hole 0x400 kept;
        all other values == v0.20; control: v0.20 adds 0x100
     B3 ex_get art read (0x601e3318): byte 0,1,2 -> itself, 3..6/255 -> 0 (v0.20: 3 -> 3)
     B4 ex_set art write (0x601e339f): wheel -7..8 -> clamp -3..5, wrap modulo 3 (Off/Star Light/Pin Hole);
        v0.20: clamp -4..7, modulo 4
  P  anti-brick: build_package decodes to stock + edits, restore == stock
(Grain gains per level / MONO stock: tools/ep7_grain_verify.py.)
"""
import json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402

BASE, BUF, STK = 0x60020020, 0x18000000, 0x18010000


def image(spec):
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    return [b for b in oc.parse(pkg) if b.kind == 0x100][0].payload, pkg, rst, info


def seg(im, lo, hi):
    return Region(f'i{lo:x}', lo, im[lo - BASE:hi - BASE], 'rx')


def run(im, segs, regs, stop, buf=b'', limit=5000):
    rg = [seg(im, lo, hi) for lo, hi in segs] + [Region('buf', BUF, bytes(buf).ljust(0x400, b'\0'), 'rw', True),
                                                 Region('stk', STK, bytes(0x200), 'rw', True)]
    r = execute(rg, dict(sp=STK + 0x100, **regs), stop, limit=limit)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    return r['registers'], m.get('buf', b''), r['fault']


def r_ranges(im, hi_ok):
    bad = []
    for g in range(8):
        t = bytearray(512); t[24] = g                     # SD loader: whole 8x64 table, slot 0 grain byte
        rr, _, f = run(im, [(0x605b7400, 0x605b7800)], dict(pc=0x605b75e7, a0=BUF), 0x605b760c, t, 20000)
        sd_ok = rr['pc'] == 0x605b760c and not f
        rec = bytearray(64); rec[24] = g                  # fm_check: one 64-B record, bytes 0..44
        rr, _, f = run(im, [(0x6143a400, 0x6143a800)], dict(pc=0x6143a607, a2=BUF), 0x6143a626, rec, 5000)
        fm_ok = rr['pc'] == 0x6143a626 and not f
        if sd_ok != (g <= hi_ok) or fm_ok != (g <= hi_ok):
            bad.append((g, sd_ok, fm_ok))
    return bad


EX = [(0x601e323c, 0x601e383c), (0x601e383c, 0x601e38a0)]


def g_get(im, hi_ok):
    bad = []
    for g in range(9):
        buf = bytearray(64); buf[56] = g
        rr, _, f = run(im, EX, dict(pc=0x601e32c8, a2=BUF), 0x601e3322, buf)
        got = rr['d0'] if rr['pc'] == 0x601e3322 and not f else None
        zero = (not f) and rr['pc'] == 0x601e3322 and rr['d0'] == 0 or (got is None)
        want = g if g <= hi_ok else 0
        if got != want and not (want == 0 and zero):
            bad.append((g, got))
    return bad


def s_set(im, hi_ok):
    bad = []
    for v in range(-7, 9):
        rr, buf, f = run(im, EX, dict(pc=0x601e33bc, d1=v & 0xffffffff, d3=0, a2=BUF), 0x601e33da, b'\xee' * 64)
        if f or rr['pc'] != 0x601e33da or buf[56] != min(max(v, 0), hi_ok):
            bad.append((v, buf[56] if buf else None))
    return bad


def l_label(im):
    bad, seen = [], []
    for v in range(8):
        stk = STK + 0x100
        rg_regs = dict(pc=0x601e355e, d3=0)
        rg = [seg(im, lo, hi) for lo, hi in EX] + [Region('stk', STK, bytes(0x104) + struct.pack('<I', v) + bytes(0xf8), 'rw', True)]
        r = execute(rg, dict(sp=stk, **rg_regs), 0x601e35b4, limit=200)
        pc, a2 = r['registers']['pc'], r['registers']['a2']
        if v <= 5:
            txt = im[a2 - BASE:a2 - BASE + 16].split(b'\0')[0].decode() if pc == 0x601e35b4 else None
            want = '1 Grain Off' if v == 0 else f'1 Grain {v}'
            seen.append(txt)
            if txt != want:
                bad.append((v, txt))
        elif pc == 0x601e35b4:
            bad.append((v, 'label shown'))
    return bad, seen


def _load(name, rel):
    import importlib.util
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
    return m


def b_conv(im1, im0):
    BV = _load('bv21', 'tools/ep7_bloom_verify.py')
    bad, n, ctl = [], 0, 0
    for art in (0, 1, 2, 3, 4, 5, 6, 255):
        for eff in ((0, 0), (1, 3), (3, 2)):
            for erased in (False, True):
                t = bytearray(BV.fixture_table({i: eff for i in range(8)}))
                for k in range(8):
                    t[64 * k + 46] = art
                t0 = bytearray(t)
                for k in range(8):
                    t0[64 * k + 46] = 0
                tb, tb0 = (b'\xff' * 512, b'\xff' * 512) if erased else (bytes(t), bytes(t0))
                for key in (11, 0x01010064, 12):
                    for mode in (11, 12):
                        for prof in (1, 4, 5):
                            o1, f1, p1, c1 = BV.conv_run(im1, tb, key, mode, prof)
                            o0, f0, p0, c0 = BV.conv_run(im0, tb, key, mode, prof)
                            want = f0
                            if art == 3 and not erased:
                                oa, fa, _, _ = BV.conv_run(im0, tb0, key, mode, prof)
                                want = fa
                                ctl += (f0 & 0x100) != 0 and key == 11 and mode == 11 and prof <= 4
                            n += 1
                            if not (o1 and o0 and c1 and c0 and f1 == want and p1[:12] == p0[:12] and p1[16:] == p0[16:]):
                                bad.append((art, eff, erased, hex(key), mode, prof, hex(f1), hex(want)))
    if ctl == 0:
        bad.append('control: v0.20 never set 0x100 for Blur')
    return n, bad


def b_lv(im1, im0, new, old):
    LV = _load('lv21', 'patches/lv_art/verify.py')
    bad, n, ctl = [], 0, 0
    for art in (0, 1, 2, 3, 4, 5, 6, 255):
        for extra in ({}, dict(hl=True), dict(eff=1, s=3)):
            t = LV.fixture({k: dict(art=art, **extra) for k in range(4)})
            t0 = LV.fixture({k: dict(art=0, **extra) for k in range(4)})
            for prof in (1, 3, 4, 5):
                for jt in (0x38, 0x40):
                    r1 = LV.hook_run(im1, new, t, profile=prof, jtype=jt)
                    r0 = LV.hook_run(im0, old, t, profile=prof, jtype=jt)
                    want = r0
                    if art == 3:
                        want = LV.hook_run(im0, old, t0, profile=prof, jtype=jt)
                        ctl += struct.unpack_from('<I', r0[1]['job'], 16)[0] & 0x100 != 0
                    n += 1
                    if not (r1[0] and want[0] and r1[1]['job'] == want[1]['job'] and r1[1]['stack'] == want[1]['stack']):
                        bad.append((art, extra, prof, hex(jt)))
                    if art == 2 and jt == 0x38 and prof <= 4 and not struct.unpack_from('<I', r1[1]['job'], 16)[0] & 0x400:
                        bad.append(('pin hole lost', prof))
    if ctl == 0:
        bad.append('control: v0.20 never set 0x100 for LV Blur')
    return n, bad


def b_get(im, blur):
    bad = []
    for v in (0, 1, 2, 3, 4, 5, 6, 255):
        buf = bytearray(128); buf[78] = v                 # a2 = P + 64*slot: (78,a2) = table byte 32 + slot +46
        rr, _, f = run(im, EX, dict(pc=0x601e3318, a2=BUF, d0=0x5555), 0x601e3322, buf)
        want = v if v < (4 if blur else 3) else 0
        if f or rr['pc'] != 0x601e3322 or rr['d0'] != want:
            bad.append((v, rr['d0'], want))
    return bad


def b_set(im, blur):
    bad = []
    lo, hi, m = (-4, 7, 4) if blur else (-3, 5, 3)
    for v in range(-7, 9):
        rr, _, f = run(im, EX, dict(pc=0x601e339f, d1=v & 0xffffffff, a2=BUF), 0x601e33b7)
        want = min(max(v, lo), hi) % m
        if f or rr['pc'] != 0x601e33b7 or rr['d1'] != want:
            bad.append((v, rr['d1'], want))
    return bad


def main():
    old, new = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    im0, *_ = image(old)
    im1, pkg, rst, info = image(new)
    ok = True
    for name, fn in (('R loader ranges', lambda im, h: r_ranges(im, h)), ('G ex_get', g_get), ('S ex_set clamp', s_set)):
        b1, b0 = fn(im1, 5), fn(im0, 3)
        good = not b1 and not b0
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} {name}: v0.21 0..5 {b1 or 'ok'}; v0.20 control 0..3 {b0 or 'ok'}")
    n1, bb = b_conv(im1, im0)
    ok &= not bb
    print(f"{'PASS' if not bb else 'FAIL'} B1 converter Blur -> Off: {n1 - len(bb)}/{n1} {bb[:6] or ''}")
    n2, bb = b_lv(im1, im0, new, old)
    ok &= not bb
    print(f"{'PASS' if not bb else 'FAIL'} B2 lv_art Blur -> Off: {n2 - len(bb)}/{n2} {bb[:6] or ''}")
    for name, fn in (('B3 ex_get art', b_get), ('B4 ex_set art wrap', b_set)):
        b1, b0 = fn(im1, False), fn(im0, True)
        good = not b1 and not b0
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} {name}: v0.21 Off/Star Light/Pin Hole {b1 or 'ok'}; v0.20 control 0..3 {b0 or 'ok'}")
    bl, seen = l_label(im1)
    ok &= not bl
    print(f"{'PASS' if not bl else 'FAIL'} L label: {seen}; 6/7 -> q_out {bl or 'ok'}")
    stock = {b.kind: b for b in oc.parse(BP.STOCK.read_bytes())}
    good = True
    for b in oc.parse(pkg):
        exp = bytearray(stock[b.kind].payload)
        for e in new['edits']:
            if int(e['kind'], 16) == b.kind:
                o = BP.resolve(b.kind, e['addr']); n = bytes.fromhex(e['new']); exp[o:o + len(n)] = n
        good &= bytes(exp) == b.payload
    for b in oc.parse(rst):
        good &= b.payload == stock[b.kind].payload
    ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: decode == stock + edits ({info['edits']} edits, {info['changed_payload_bytes']} B), restore == stock")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
