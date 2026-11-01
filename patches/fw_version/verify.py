#!/usr/bin/env python3
"""Verify patches/fw_version on a built spec. Offline; emulator only.

  .venv/bin/python -I patches/fw_version/verify.py releases/v0.15/edits.json

  E  emulator: the real Firmware-screen builder 0x60df5285 on STOCK, PATCHED and the fw_version-stripped BASE (stubs only
     for the version getters, the logger 0x60e9e050 and memset): object + regs identical for every getter status
     combination; Body label item = kind 4 id 0x6bd ("Body", stock). Then the view's two Body value steps (real
     `mov (4,sp),a1; add OFF,a1; call` + fw_val, setter 0x60d4c9df stubbed to capture): stock "1.1", patched
     "1.1 Caduceus <ver>", empty field passed through; widget, callee-saved regs and the caller frame identical.
  S  static: spec differs from BASE only at the 3 fw_version edits; builder, label copier, Body descriptor, setter,
     sprintf format, EXIF template, version getters and updater/version-check code == stock; the view differs only
     in the 2 call words; no refs into the claim except the step-table word 0x601e3d28
  P  anti-brick: tools/build_package.build(spec) decodes to stock + edits; restore == stock
"""
import argparse, copy, importlib.util, itertools, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402

spec_ = importlib.util.spec_from_file_location('fwv_build', Path(__file__).with_name('build.py'))
FB = importlib.util.module_from_spec(spec_); spec_.loader.exec_module(FB)
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE, FN = 0x60020020, 0x60df5285
OBJ, BLK, STACK, WRAP, FAKE, MEMSET = 0x18100000, 1164, 0x18010000, 0x18020000, 0x18030000, 0x4700115e
GET_A, GET_B, LOGF = 0x607b23fb, 0x607b2dd3, 0x60e9e050


def asm(src, at):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'a.s').write_text(' .am33_2\n .text\n .global _start\n_start:\n' + src + '\n')
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'a.o', t / 'a.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start', '-o', t / 'a.elf', t / 'a.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'a.elf', t / 'a.bin'], check=True)
        return (t / 'a.bin').read_bytes()


def images(spec):
    stock = STOCK_B
    p = bytearray(stock)
    for e in spec['edits']:
        if e['kind'] != '0x100':
            continue
        a, exp, new = int(e['addr'], 16), bytes.fromhex(e['expect']), bytes.fromhex(e['new'])
        assert stock[a - BASE:a - BASE + len(exp)] == exp, e['addr']
        p[a - BASE:a - BASE + len(new)] = new
    return bytes(p)


def fakes(st_a, st_b, present):
    """FAKE: obj A (0x607b23fb): vt+16 (idx,a1) / vt+72; obj B (0x607b2dd3): vt+8; list obj: vt+4 / vt+8."""
    vt = FAKE + 0x100
    src = f"""
 .long {vt:#x}
 .long 0
 .long {vt + 0x80:#x}
 .long 0
 .long {vt + 0xc0:#x}
 .org 0x100
 .long 0,f_zero,f_zero,0,f16
 .org 0x100+72
 .long f72
 .org 0x180
 .long 0,0,f8
 .org 0x1c0
 .long 0,f_zero,f_zero
 .org 0x200
f16:
 cmp 1,d0
 bne f16n
 mov 0x1100,d1
 movhu d1,(a1)
 mov {st_a},d0
 rets
f16n:
 mov {0 if present else 1},d0
 cmp 0,d0
 bne f16x
 mov 0x1200,d1
 movhu d1,(a1)
f16x:
 rets
f72:
 mov 0x1000,d1
 movhu d1,(a1)
 mov {st_b},d0
 rets
f8:
 mov 1,d0
 mov d0,(4,a1)
 clr d0
 mov d0,(12,a1)
 rets
f_zero:
 clr d0
 rets
"""
    return asm(src, FAKE)


STUBS = {GET_A: f' mov {FAKE:#x},a0\n ret [],4', GET_B: f' mov {FAKE + 8:#x},a0\n ret [],4',
         LOGF: ' ret [a2,a3],8'}
MEMSET_SRC = ' mov a0,a2\n cmp 0,d1\n beq 2f\n1:\n movbu d0,(a2)\n inc a2\n add -1,d1\n bne 1b\n2:\n ret [d2,a2],8'


def run(image, st_a, st_b, present):
    im = bytearray(image)
    for a, s in STUBS.items():
        c = asm(s, a)
        im[a - BASE:a - BASE + len(c)] = c
    obj = bytearray(0x900)
    struct.pack_into('<I', obj, 1160, FAKE + 16)       # list object -> vt at FAKE+0x1c0
    struct.pack_into('<I', obj, 2168, 0x6115d670)      # Firmware-screen label table entry (stock pointer)
    wrap = asm(f' mov {FN:#x},a2\n mov {OBJ:#x},a0\n calls (a2)\n nop\n nop', WRAP)
    regions = [Region('img', BASE, bytes(im), 'rx'), Region('ms', MEMSET, asm(MEMSET_SRC, MEMSET), 'rx'),
               Region('fake', FAKE, fakes(st_a, st_b, present), 'rx'), Region('wrap', WRAP, wrap, 'rx'),
               Region('stack', STACK, bytes(0x1100), 'rw', capture=True), Region('obj', OBJ, bytes(obj), 'rw', capture=True)]
    r = execute(regions, {'sp': STACK + 0x1000, 'pc': WRAP, 'd2': 0x22, 'd3': 0x33, 'a3': 0x44}, WRAP + len(wrap) - 2,
                limit=2_000_000, timeout=120)
    if r['fault'] or r['registers']['pc'] != WRAP + len(wrap) - 2:
        raise SystemExit(f'run fault {r["fault"]} pc {r["registers"]["pc"]:#x}')
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return mem['obj'], {k: r['registers'][k] for k in ('d2', 'd3', 'a2', 'a3', 'sp')}


def wstr(b):
    return b.decode('utf-16le').split('\0')[0]


CAP = 0x18040000
SETTER_CAP = (f' mov {CAP:#x},a2\n1:\n movhu (a1),d0\n movhu d0,(a2)\n add 2,a1\n add 2,a2\n cmp 0,d0\n bne 1b\n'
              f' mov a0,({CAP + 0xfc:#x})\n ret [d2,d3,a2,a3],24')


def view_site(image, blk, site):
    """Run the view's Body value step: `mov (4,sp),a1; add OFF,a1; call 0x60d4c9df` (site = the call). The setter is a
    stub that captures the string and the widget into CAP."""
    im = bytearray(image)
    c = asm(SETTER_CAP, FB.SETTER)
    im[FB.SETTER - BASE:FB.SETTER - BASE + len(c)] = c
    stack = bytearray(0x1100)
    struct.pack_into('<I', stack, 0x1000 + 4, OBJ + BLK)        # (4,sp) = block
    start, stop = site - 6, site + 7
    r = execute([Region('img', BASE, bytes(im), 'rx'), Region('obj', OBJ, blk, 'rw'),
                 Region('stack', STACK, bytes(stack), 'rw', capture=True), Region('cap', CAP, bytes(0x100), 'rw', capture=True)],
                {'sp': STACK + 0x1000, 'pc': start, 'a0': 0x5a5a0026, 'a3': 0x44, 'd2': 0x22, 'd3': 0x33, 'a2': 0x55},
                stop, limit=100_000, timeout=60)
    if r['fault'] or r['registers']['pc'] != stop:
        raise SystemExit(f'view run fault {r["fault"]} pc {r["registers"]["pc"]:#x}')
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    cap = mem['cap']
    regs = {k: r['registers'][k] for k in ('d2', 'd3', 'a2', 'a3', 'sp')}
    return wstr(cap[:0xfc]), struct.unpack_from('<I', cap, 0xfc)[0], regs, mem['stack'][0x1000:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.spec.read_text())
    fv = spec['fw_version']
    sfx = fv['suffix']
    patched = images(spec)
    base = images(FB.strip(copy.deepcopy(spec)))
    ok = okv = 0
    # ---- E: emulator
    for st_a, st_b, present in itertools.product((0, 1), (0, 1), (True, False)):
        so, sr = run(STOCK_B, st_a, st_b, present)
        po, pr = run(patched, st_a, st_b, present)
        bo, br = run(base, st_a, st_b, present)
        assert sr == pr == br and so == po == bo, 'builder output differs'
        blk = so[BLK:BLK + 1004]
        assert st_a or struct.unpack_from("<HHH", blk, 0) == (4, 0, 0x6bd), struct.unpack_from("<HHH", blk, 0)  # "Body"
        ok += 1
        for site, off in ((0x60d7f271, 940), (0x60d7f2cd, 300)):
            field = wstr(blk[off:off + 8])
            ts, ws, rs, ks = view_site(STOCK_B, so, site)
            tp, wp, rp, kp = view_site(patched, so, site)
            tb, wb, rb, kb = view_site(base, so, site)
            assert ts == tb == field and ws == wp == wb == 0x5a5a0026 and rs == rp == rb and ks == kp == kb
            assert tp == (field + sfx if field else field), (tp, field)
            if field and present and st_b == (0 if off == 940 else 1):
                print(f'E  {hex(site)} +{off}: stock "{ts}"  patched "{tp}"  (label item kind 4 id 0x6bd "Body")')
            okv += 1
    print(f'E  builder: {ok}/8 status combinations, object + regs byte-identical stock == patched == base')
    print(f'E  view: {okv}/16 Body value runs PASS (suffix only on a non-empty field; widget/regs/caller frame identical)')
    # ---- S: static
    d = [i for i in range(len(base)) if base[i] != patched[i]]
    rng = [(int(e['addr'], 16), len(e['new']) // 2) for e in spec['edits'] if e.get('source') == FB.SRC]
    assert all(any(a - BASE <= i < a - BASE + n for a, n in rng) for i in d) and len(rng) == 3
    assert patched[0x60df25b5 - BASE:0x60df2632 - BASE] == base[0x60df25b5 - BASE:0x60df2632 - BASE]  # copier (film-menu hookB) == base
    keep = {'builder 0x60df5285..0x60df58b8': (0x60df5285, 0x60df58b8),
            'Body descriptor 0x6115d5e8': (0x6115d5e8, 0x6115d5f0), 'old label range 0x61242fc0': (0x61242fc0, 0x61242fe0),
            'setter 0x60d4c9df': (0x60d4c9df, 0x60d4ca80),
            'fmt L"%X.%X"': (0x6115d702, 0x6115d70e), 'EXIF "Version x.x"': (0x604ddeb4, 0x604ddec0),
            'EXIF fill site': (0x603011c0, 0x60301240), 'version getters': (0x607b23fb, 0x607b2400),
            'getter B': (0x607b2dd3, 0x607b2dd8), 'firmup strings/code 0x60b6e0ca': (0x60b6e000, 0x60b6e400),
            'version-check menu 0x60cf4200': (0x60cf4200, 0x60cf4300), 'card version API 0x60aa1300': (0x60aa1300, 0x60aa1380)}
    for k, (lo, hi) in keep.items():
        assert patched[lo - BASE:hi - BASE] == base[lo - BASE:hi - BASE] == STOCK_B[lo - BASE:hi - BASE], k
    vlo, vhi = 0x60d7f0a4, 0x60d7f40f              # view: only the 2 call words changed
    vd = [i + BASE for i in range(vlo - BASE, vhi - BASE) if patched[i] != STOCK_B[i]]
    assert all(any(s <= x < s + 7 for s in FB.SITES) for x in vd), [hex(x) for x in vd]
    ca = int(fv['code_at'], 16)
    for tgt in range(0x601e1c3c, 0x601e1d3c, 4):   # no abs32 refs into the claim except the step-table word
        pat = struct.pack('<I', tgt)
        i, refs = -1, []
        while (i := patched.find(pat, i + 1)) >= 0:
            refs.append(i + BASE)
        assert refs == ([0x601e3d28] if tgt == 0x601e1c3c else []) or all(ca <= r < ca + fv['code_len'] for r in refs), \
            (hex(tgt), [hex(r) for r in refs])
    print(f'S  diff vs base = {len(d)} B, only in the 3 fw_version edits; {len(keep)} label/version/updater/EXIF ranges '
          f'== stock; view changed only at {len(vd)} B in the 2 call words; claim refs exact')
    # ---- P: anti-brick
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    blocks = {b.kind: b for b in oc.parse(pkg)}
    assert bytes(blocks[0x100].payload) == patched, 'decoded main != stock + edits'
    stock_blocks = {b.kind: b for b in oc.parse(BP.STOCK.read_bytes())}
    for k, b in blocks.items():
        if k != 0x100:
            exp = bytearray(stock_blocks[k].payload)
            for e in spec['edits']:
                if int(e['kind'], 16) == k:
                    o = BP.resolve(k, e['addr']); n = bytes.fromhex(e['new']); exp[o:o + len(n)] = n
            assert bytes(b.payload) == bytes(exp), hex(k)
    for rb in oc.parse(restore):
        assert rb.payload == stock_blocks[rb.kind].payload
    print(f'P  anti-brick: decode == stock + edits ({info["edits"]} edits, {info["changed_payload_bytes"]} B), restore == stock')
    print('ALL PASS')


STOCK_B = (ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes()
if __name__ == '__main__':
    main()
