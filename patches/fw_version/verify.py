#!/usr/bin/env python3
"""Verify patches/fw_version on a built spec. Offline; emulator only.

  .venv/bin/python -I patches/fw_version/verify.py releases/v0.15/edits.json

  E  emulator: the real Firmware-screen builder 0x60df5285 runs on the STOCK and the PATCHED image (stubs only for
     the version getters, the debug logger 0x60e9e050 and memset 0x4700115e; sprintf/strlen/label copier are real).
     Patched: Body row label item = kind 5 + "Body Caduceus <ver>"; version strings "1.1"/"1.0" unchanged; every
     other byte of the 1004-B block and the object == stock run. Also run for every getter status combination.
  S  static: spec differs from its fw_version-stripped base only at the 2 fw_version edits; the builder, sprintf
     format L"%X.%X", EXIF "Version x.x" template, version getters and updater/version-check code are byte-identical
     to stock; descriptor 0x6115d5e8 / string 0x61242fc0 have no other references
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.spec.read_text())
    fv = spec['fw_version']
    text = fv['text']
    patched = images(spec)
    base = images(FB.strip(copy.deepcopy(spec)))
    ok = 0
    # ---- E: emulator
    for st_a, st_b, present in itertools.product((0, 1), (0, 1), (True, False)):
        so, sr = run(STOCK_B, st_a, st_b, present)
        po, pr = run(patched, st_a, st_b, present)
        bo, br = run(base, st_a, st_b, present)
        assert sr == pr == br and bo == so, (sr, pr, br)
        blk_s, blk_p = so[BLK:BLK + 1004], po[BLK:BLK + 1004]
        diff = [i for i in range(len(so)) if so[i] != po[i]]
        if st_a == 0 and st_b == 0:            # Body row shown with both versions
            kind = struct.unpack_from('<H', blk_p, 0)[0]
            assert kind == 5 and wstr(blk_p[8:74]) == text, (kind, wstr(blk_p[8:74]))
            assert struct.unpack_from('<H', blk_s, 0)[0] == 4 and struct.unpack_from('<H', blk_s, 4)[0] == 0x6bd
            assert wstr(blk_p[940:948]) == wstr(blk_s[940:948]) == '1.1' and wstr(blk_p[972:980]) == wstr(blk_s[972:980]) == '1.0'
            assert all(BLK <= i < BLK + 74 for i in diff), [hex(i) for i in diff]
            if present:
                print(f'E  stock : row0 kind 4 id 0x6bd ("Body")  ver "{wstr(blk_s[940:948])}" / "{wstr(blk_s[972:980])}"')
                print(f'E  patch : row0 kind 5 "{wstr(blk_p[8:74])}"  ver "{wstr(blk_p[940:948])}" / "{wstr(blk_p[972:980])}"')
        elif st_a == 0:                        # Body row via the +300 path: label patched, version identical
            assert wstr(blk_p[8:74]) == text and wstr(blk_p[300:308]) == wstr(blk_s[300:308]) == '1.1'
            assert all(BLK <= i < BLK + 74 for i in diff)
        else:                                  # Body row absent: identical
            assert not diff, [hex(i) for i in diff]
        ok += 1
    print(f'E  {ok}/8 status combinations PASS (stock == v0.15 base run; patched regs identical, diff only in row-0 label item)')
    # ---- S: static
    d = [i for i in range(len(base)) if base[i] != patched[i]]
    rng = [(int(e['addr'], 16), len(e['new']) // 2) for e in spec['edits'] if e.get('source') == FB.SRC]
    assert all(any(a - BASE <= i < a - BASE + n for a, n in rng) for i in d) and len(rng) == 2
    assert patched[0x60df25b5 - BASE:0x60df2632 - BASE] == base[0x60df25b5 - BASE:0x60df2632 - BASE]  # copier (film-menu hookB) == base
    keep = {'builder 0x60df5285..0x60df58b8': (0x60df5285, 0x60df58b8),
            'fmt L"%X.%X"': (0x6115d702, 0x6115d70e), 'EXIF "Version x.x"': (0x604ddeb4, 0x604ddec0),
            'EXIF fill site': (0x603011c0, 0x60301240), 'version getters': (0x607b23fb, 0x607b2400),
            'getter B': (0x607b2dd3, 0x607b2dd8), 'firmup strings/code 0x60b6e0ca': (0x60b6e000, 0x60b6e400),
            'version-check menu 0x60cf4200': (0x60cf4200, 0x60cf4300), 'card version API 0x60aa1300': (0x60aa1300, 0x60aa1380)}
    for k, (lo, hi) in keep.items():
        assert patched[lo - BASE:hi - BASE] == STOCK_B[lo - BASE:hi - BASE], k
    for tgt in (FB.DESC, FB.STR_AT):
        pat = struct.pack('<I', tgt)
        refs = [i + BASE for i in range(len(patched)) if patched.startswith(pat, i)] if False else []
        i, refs = -1, []
        while (i := patched.find(pat, i + 1)) >= 0:
            refs.append(i + BASE)
        want = [0x6115d674] if tgt == FB.DESC else [FB.DESC + 4]
        assert refs == want, (hex(tgt), [hex(r) for r in refs])
    print(f'S  diff vs base = {len(d)} B, only in the 2 fw_version edits; {len(keep)} version/updater/EXIF ranges == stock; refs exact')
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
