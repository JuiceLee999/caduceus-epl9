#!/usr/bin/env python3
"""LCD green/magenta trim check (patches/lcd_tint; offline; emulator only).

  .venv/bin/python -I tools/ep7_verify_lcd_tint.py releases/v0.20/edits.json [--base releases/v0.19/edits.json]

  D  diff vs base package: every component other than main byte-identical; main differs only in the lcd_tint
     G bytes and the fw_version label bytes; no tint byte in the VSC display-gamma route (LUT/step data
     0x601de13c-0x601e3c3c, which also hosts fw_version code; loader..writer 0x60187400-0x60189200 identical) and the ISP/JPEG/movie code (0x60330000-0x60540000) byte-identical.
  T  table: per row only the 0xd9 [mode,R,G,B] bytes change, = step_rgb(colour step) (G/M axis, step 7 = 0x91
     mode with the trimmed G); 0x91 words (brightness), high data-marker bytes and the tail identical.
  X  refs: every 32-bit word in all components pointing into the edited .data (panel sequences, table, template)
     sits in the panel routine 0x60184000-0x60184800 (i.e. no ISP/encoder/HDMI reader).
  E  emulator: the patched panel routine 0x60184360 for all 15 colour-temp x 3 brightness steps builds the same
     70-B SPI command buffer as stock except the 0xd9 [mode,R,G,B] low bytes (= step_rgb), returns to the send call, no
     fault.
"""
import argparse, json, subprocess, sys, tempfile
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
sys.path.insert(0, str(ROOT / 'patches/lcd_tint'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402
import build as LT  # noqa: E402  (patches/lcd_tint/build.py)

BASE = 0x60020020
DELTA = LT.DELTA
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MEMCPY = 0x47001052
STACK = 0x20000000
RAM = 0x62233400
DATA_LO, DATA_HI = 0x61f9d060, 0x61f9ea80
COINCIDENT = {0x60937d2d, 0x6096a171, 0x60a3230f}


def sl(m, lo, hi):
    return m[lo - BASE:hi - BASE]


def memcpy_stub():
    src = """
 .text
 .global _start
_start:
 cmp 0,d0
 beq 2f
1:
 movbu (a1),d1
 movbu d1,(a0)
 inc a0
 inc a1
 add -1,d0
 bne 1b
2:
 ret [d2,d3,a2,a3],28
"""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'a.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'a.o', t / 'a.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(MEMCPY), '-e', '_start', '-o', t / 'a.elf', t / 'a.o'],
                       check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'a.elf', t / 'a.bin'], check=True)
        return (t / 'a.bin').read_bytes()


def panel_run(img, stub, bright, ctemp):
    ram = bytearray(0x100)
    ram[0xc2], ram[0xc3] = bright, ctemp
    sp = STACK + 0x800
    regions = [Region('code', 0x60184000, sl(img, 0x60184000, 0x60184800), 'rx'),
               Region('data', DATA_LO, sl(img, DATA_LO - DELTA, DATA_HI - DELTA), 'r'),
               Region('ram', RAM, bytes(ram), 'rw'),
               Region('memcpy', MEMCPY, stub, 'rx'),
               Region('stack', STACK, bytes(0x1000), 'rw', True)]
    r = execute(regions, {'d0': 0, 'sp': sp, 'pc': 0x60184360}, 0x6018447a, limit=20000)
    st = next(c for c in r['memory'] if c['name'] == 'stack')
    data = bytes.fromhex(st['hex'])
    buf = data[0x800 + 20:0x800 + 20 + 70]
    ok = not r['fault'] and r['registers']['pc'] == 0x6018447a
    return ok, buf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--base', type=Path, default=ROOT / 'releases/v0.19/edits.json')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    spec, bspec = json.loads(a.spec.read_text()), json.loads(a.base.read_text())
    pct, span = spec['lcd_tint']['green_pct'], spec['lcd_tint']['span_pct']
    stock_bytes = BP.STOCK.read_bytes()
    pkg, restore, _ = BP.build(spec, stock_bytes)
    bpkg, _, _ = BP.build(bspec, stock_bytes)
    P, Bc, S = oc.parse(pkg), oc.parse(bpkg), oc.parse(restore)
    img, base, stock = P[0].payload, Bc[0].payload, S[0].payload
    res = {}

    # D
    lt = [e for e in spec['edits'] if e.get('source') == LT.SRC]
    fv = [e for e in spec['edits'] if e.get('source') == 'patches/fw_version']
    allowed = set()
    for e in lt + fv:
        s = int(e['addr'], 16)
        allowed.update(range(s, s + len(e['new']) // 2))
    diff = [i + BASE for i in range(len(img)) if img[i] != base[i]]
    tint_changed = [x for x in diff if any(int(e['addr'], 16) <= x < int(e['addr'], 16) + len(e['new']) // 2 for e in lt)]
    res['D'] = dict(
        other_components_identical=[p.payload for p in P[1:]] == [b.payload for b in Bc[1:]],
        main_diff_only_tint_and_label=all(x in allowed for x in diff),
        tint_bytes_changed=len(tint_changed),
        vsc_gamma_route_untouched=not any(0x601de13c <= x < 0x601e3c3c or 0x60187400 <= x < 0x60189200
                                          for x in tint_changed)
        and sl(img, 0x60187400, 0x60189200) == sl(base, 0x60187400, 0x60189200),
        isp_code_data_identical=sl(img, 0x60330000, 0x60540000) == sl(base, 0x60330000, 0x60540000))

    # T
    rows_ok, nchg = True, 0
    for r in range(LT.ROWS):
        o = LT.TABLE + r * LT.ROW
        s_, p_ = sl(stock, o, o + LT.ROW), sl(img, o, o + LT.ROW)
        want = bytearray(s_)
        for k, v in enumerate(LT.step_rgb(r % 15, pct, span)):
            want[2 * k] = v
        nchg += want != s_
        rows_ok &= p_ == bytes(want)
    singles = all(sl(img, x, x + 1)[0] == LT.trim(0xe0, pct) and sl(stock, x, x + 1) == b'\xe0' for x in LT.SINGLE)
    res['T'] = dict(rows=LT.ROWS, rows_exact=rows_ok, rows_changed=nchg, singles_exact=singles,
                    steps={c - 7: '%02x %02x %02x %02x' % LT.step_rgb(c, pct, span) for c in range(15)})

    # X
    refs = []
    for comp in P:
        u = np.frombuffer(comp.payload, np.uint8).astype(np.uint32)
        v = u[:-3] | u[1:-2] << 8 | u[2:-1] << 16 | u[3:] << 24
        for off in np.nonzero((v >= DATA_LO) & (v < DATA_HI))[0]:
            refs.append((comp.kind, int(off) + (BASE if comp is P[0] else 0), int(v[off])))
    # panel driver: 0x60182000-0x60184800 (open/close sequences, brightness/colour temp) and its init copy
    # 0x60042357 (168 B of sequence 2 -> panel RAM 0x6223340a). COINCIDENT words are bytes inside `call`
    # instructions (word = xx dd f9 61: the dd opens a call), not address loads.
    drv = lambda o: 0x60182000 <= o < 0x60184800 or o == 0x60042357
    other = [(k, o, v) for k, o, v in refs if not (k == P[0].kind and drv(o))]
    res['X'] = dict(refs=len(refs), outside_driver=[(hex(k), hex(o), hex(v)) for k, o, v in other],
                    only_panel_driver=all(k == P[0].kind and o in COINCIDENT
                                          and sl(img, o + 1, o + 4)[0] == 0xdd for k, o, v in other))

    # E
    stub = memcpy_stub()
    e_ok, cases = True, 0
    for b in (0, 7, 14):
        for c in range(15):
            ok_s, bs = panel_run(stock, stub, b, c)
            ok_p, bp = panel_run(img, stub, b, c)
            want = bytearray(bs)
            for k, v in enumerate(LT.step_rgb(c, pct, span)):   # buffer words 23..26 = 0xd9 data
                want[46 + 2 * k] = v
            good = ok_s and ok_p and bs[42:46] == bytes.fromhex('0500d900') and bp == bytes(want)
            e_ok &= good
            cases += 1
    res['E'] = dict(cases=cases, all_pass=e_ok)

    passed = (all(v for k, v in res['D'].items() if isinstance(v, bool)) and res['D']['tint_bytes_changed'] > 0
              and res['T']['rows_exact'] and res['T']['rows_changed'] == 225 and res['T']['singles_exact']
              and res['X']['only_panel_driver'] and res['E']['all_pass'])
    res['pass'] = passed
    print(json.dumps(res, indent=1))
    if a.json:
        a.json.write_text(json.dumps(res, indent=1))
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
