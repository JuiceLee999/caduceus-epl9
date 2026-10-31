#!/usr/bin/env python3
"""Offline emulator checks for the per-profile WB fine-tune override (E-P7 1.1, main 5dd9af16...).

Design under test (docs/WB_AND_MONO.md, Part A): every image-pipeline read of the WB fine-tune
properties goes through `call 0x6005e971,[d2,d3],12` (7 bytes, `dd rel32 c0 0c`). Redirecting the rel32
of those calls to a stub `wb_get` (same contract: d0=key, d1=idx, a0=0 -> d0) lets the stub return
bundle[slot].wb_ab / wb_gm when picture mode is 11/12 and bundle[slot].wb_flags & 1, otherwise the stock
value. GUI/settings code never reads these keys through the getter, so menus keep the stored values.

Checks (nothing is written to firmware files; the stub only exists in emulator RAM):
  S  stub unit test with a fake property getter mapped at 0x6005e971 (our test code): override,
     pass-through for other keys, flag clear, non-COLOR/MONO modes, out-of-range profile, mode 6
     re-resolution via 40209, MONO slot = 4 + profile-1; d2/d3/a2/a3/sp preserved.
  W  native capture WB resolution segment 0x60302c0f..0x60302fc9 (stock code), stock vs the 10
     call sites redirected to the stub: per WB category, diff the whole capture block. Expect only
     capture+24098/+24100 (A/G) and the stock-derived flags +1874 (preset code) / +1916 (fine-tune on)
     to differ, and only when the override is active.
  G  native gain calculator 0x603b5769 (unmodified) on synthetic base gains with the A/G pairs from W:
     output changes only through the A/G inputs.

Usage: tools/ep7_wb_probe.py [--json out.json] [--bundle-at 0x...]
"""
import argparse, json, os, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import ep7_color_probe as PR  # noqa: E402
from penf_emulator import Region  # noqa: E402

BASE = 0x60020020
TC = Path(os.environ.get('MN10300_BIN', Path.home() / 'ep7fw-toolchains/mn10300/bin'))
GETTER = 0x6005e971
KEY_A, KEY_G = 0x84F9, 0x9679            # props 2127 / 2407 (s8 arrays, 20 entries, per WB mode)
KEY_PMODE, KEY_PMODE6 = 38017, 40209     # picture mode; mode 6 re-resolved (capture population 0x602a857e)
KEY_COLOR_PROF, KEY_MONO_PROF = 63153, 63281
STUB_AT = 0x6055e700                     # sec-2 FF tail after grain (0x6055e680..0x6055e6fa); guard to 0x6055e7f0
SEG_LO, SEG_HI, SEG_ENTRY, SEG_STOP = 0x60302b00, 0x60303100, 0x60302c0f, 0x60302fc9
JTAB = 0x604ddefc                         # 14-entry preset jump table used at 0x60302c84
CAPTURE_SITES = [0x60302c46, 0x60302c60, 0x60302da3, 0x60302db8, 0x60302e35, 0x60302e4b,
                 0x60302f23, 0x60302f3b, 0x60302f8f, 0x60302fa8]
OTHER_SITES = [0x6030bb5b, 0x6030bb6e, 0x6030eb61, 0x6030eb77, 0x60c68a45, 0x60c68a59]
GAIN_FN, GAIN_END, NORM_FN = 0x603b5769, 0x603b5d3b, 0x603b5675
COEF = 0x6050dea4

# synthetic RAM
FAKE_TAB, BUNDLE_SYN, CAPTURE = 0x11000000, 0x12000000, 0x13000000
CAP_SIZE = 25000

STUB_SRC = r"""
 .am33_2
 .text
 .global _start
/* wb_get: entered by `call wb_get,[d2,d3],12` exactly like 0x6005e971; d0=key d1=idx a0=0 -> d0 */
_start:
 mov d0,d2                 /* d2 = key (callee-saved by our call frame) */
 call ep7_getter,[d2,d3],12
 mov d0,d3                 /* d3 = stock value */
 mov d2,d0
 cmp {key_a},d0
 beq key_ok
 cmp {key_g},d0
 bne pass
key_ok:
 mov {k_pmode},d0
 clr d1
 mov 0,a0
 call ep7_getter,[d2,d3],12
 extbu d0
 cmp 6,d0
 bne m11
 mov {k_pmode6},d0
 clr d1
 mov 0,a0
 call ep7_getter,[d2,d3],12
 extbu d0
m11:
 cmp 11,d0
 bne m12
 mov {k_color},d0
 clr d1
 mov 0,a0
 call ep7_getter,[d2,d3],12
 extbu d0
 add -1,d0
 cmp 4,d0
 bcc pass
 bra have
m12:
 cmp 12,d0
 bne pass
 mov {k_mono},d0
 clr d1
 mov 0,a0
 call ep7_getter,[d2,d3],12
 extbu d0
 add -1,d0
 cmp 4,d0
 bcc pass
 add 4,d0
have:
 asl 6,d0                  /* 64-byte entries */
 mov {bundle},a0
 add d0,a0
 movbu (25,a0),d1          /* wb_flags */
 btst 1,d1
 beq pass
 mov d2,d0
 cmp {key_a},d0
 bne is_g
 movbu (26,a0),d3          /* wb_ab */
 bra sx
is_g:
 movbu (27,a0),d3          /* wb_gm */
sx:
 extb d3
pass:
 mov d3,d0
 ret [d2,d3],12
"""

FAKE_GETTER_SRC = r"""
 .am33_2
 .text
 .global _start
/* test-only property getter: table of (u32 key, u32 idx, s32 value), key 0 terminates */
_start:
 mov {tab},a1
loop:
 mov (a1),d2
 cmp 0,d2
 beq miss
 cmp d0,d2
 bne next
 mov (4,a1),d2
 cmp d1,d2
 bne next
 mov (8,a1),d0
 ret [d2,d3],12
next:
 add 12,a1
 bra loop
miss:
 clr d0
 ret [d2,d3],12
"""


def assemble(src, at, **sym):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 's.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 's.o', t / 's.s'], check=True)
        ds = [f'--defsym={k}={v:#x}' for k, v in sym.items()]
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start', *ds, '-o', t / 's.elf', t / 's.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 's.elf', t / 's.bin'], check=True)
        return (t / 's.bin').read_bytes()


def stub_bytes(bundle):
    src = STUB_SRC.format(key_a=hex(KEY_A), key_g=hex(KEY_G), k_pmode=KEY_PMODE, k_pmode6=KEY_PMODE6,
                          k_color=KEY_COLOR_PROF, k_mono=KEY_MONO_PROF, bundle=hex(bundle))
    return assemble(src, STUB_AT, ep7_getter=GETTER)


def fake_getter():
    return assemble(FAKE_GETTER_SRC.format(tab=hex(FAKE_TAB)), GETTER)


def prop_table(props):
    b = b''.join(struct.pack('<IIi', k, i, v) for (k, i), v in props.items())
    return b + bytes(12)


def bundle_table(entries):
    t = bytearray(8 * 64)
    for slot, (flags, ab, gm) in entries.items():
        t[slot * 64 + 25] = flags
        struct.pack_into('<bb', t, slot * 64 + 26, ab, gm)
    return bytes(t)


def base_regions(props, bundle, stub, getter):
    return [Region('getter', GETTER, getter, 'rx'), Region('ptab', FAKE_TAB, prop_table(props)),
            Region('bundle', BUNDLE_SYN, bundle), Region('stub', STUB_AT, stub, 'rx'),
            Region('stack', PR.STACK, bytes(0x2000), 'rw')]


# ---------------------------------------------------------------- S: stub unit test
def check_stub(stub, getter):
    bundles = bundle_table({1: (1, 3, -2), 2: (0, 7, 7), 6: (1, -4, 5)})
    cases = [  # (name, props, key, idx, expected)
        ('COLOR2 override A', {(KEY_PMODE, 0): 11, (KEY_COLOR_PROF, 0): 2, (KEY_A, 1): 1}, KEY_A, 1, 3),
        ('COLOR2 override G', {(KEY_PMODE, 0): 11, (KEY_COLOR_PROF, 0): 2, (KEY_G, 1): -1}, KEY_G, 1, -2),
        ('COLOR3 flag clear -> stock', {(KEY_PMODE, 0): 11, (KEY_COLOR_PROF, 0): 3, (KEY_A, 0): 2}, KEY_A, 0, 2),
        ('MONO3 -> slot 6', {(KEY_PMODE, 0): 12, (KEY_MONO_PROF, 0): 3, (KEY_G, 0): 2}, KEY_G, 0, 5),
        ('mode 5 -> stock', {(KEY_PMODE, 0): 5, (KEY_COLOR_PROF, 0): 2, (KEY_A, 0): -6}, KEY_A, 0, -6),
        ('mode 6 -> 40209=11', {(KEY_PMODE, 0): 6, (KEY_PMODE6, 0): 11, (KEY_COLOR_PROF, 0): 2, (KEY_A, 0): 0}, KEY_A, 0, 3),
        ('profile 0 -> stock', {(KEY_PMODE, 0): 11, (KEY_COLOR_PROF, 0): 0, (KEY_A, 0): 4}, KEY_A, 0, 4),
        ('profile 5 -> stock', {(KEY_PMODE, 0): 11, (KEY_COLOR_PROF, 0): 5, (KEY_A, 0): 4}, KEY_A, 0, 4),
        ('other key pass-through', {(KEY_PMODE, 0): 11, (KEY_COLOR_PROF, 0): 2, (63210, 3): -3}, 63210, 3, -3),
    ]
    out = []
    for name, props, key, idx, exp in cases:
        caller = Region('caller', PR.CALLER, b'\xdd' + struct.pack('<i', STUB_AT - PR.CALLER) + b'\xc0\x0c\xcb', 'rx')
        regs = {'pc': PR.CALLER, 'sp': PR.STACK + 0x1800, 'd0': key, 'd1': idx, 'a0': 0,
                'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}
        r, _ = PR.run([caller] + base_regions(props, bundles, stub, getter), regs, PR.CALLER + 7)
        rr = r['registers']
        got = struct.unpack('<i', struct.pack('<I', rr['d0']))[0]
        ok = (got == exp and rr['pc'] == PR.CALLER + 7 and rr['sp'] == PR.STACK + 0x1800 and not r['fault']
              and (rr['d2'], rr['d3'], rr['a2'], rr['a3']) == (0x2222, 0x3333, 0xa2a2, 0xa3a3))
        out.append(dict(case=name, expected=exp, got=got, passed=bool(ok), instructions=r['completed']))
    return dict(check='S stub unit test', passed=all(c['passed'] for c in out), cases=out)


# ---------------------------------------------------------------- W: native capture WB segment
def run_segment(d, props, bundle, stub, getter, cap_init, patched):
    code = bytearray(d[SEG_LO - BASE:SEG_HI - BASE])
    if patched:
        for s in CAPTURE_SITES:
            o = s - SEG_LO
            assert code[o] == 0xdd and code[o + 5:o + 7] == b'\xc0\x0c'
            struct.pack_into('<i', code, o + 1, STUB_AT - s)
    cap = bytearray(CAP_SIZE)
    for off, (fmt, v) in cap_init.items():
        struct.pack_into(fmt, cap, off, v)
    stack = bytearray(0x2000)
    struct.pack_into('<I', stack, 0x1800 + 8, CAPTURE)
    regions = base_regions(props, bundle, stub, getter)
    regions[-1] = Region('stack', PR.STACK, bytes(stack), 'rw')
    regions += [Region('seg', SEG_LO, bytes(code), 'rx'), PR.img(d, 'jtab', JTAB, JTAB + 56),
                Region('cap', CAPTURE, bytes(cap), 'rw', True)]
    r, mem = PR.run(regions, {'pc': SEG_ENTRY, 'sp': PR.STACK + 0x1800}, SEG_STOP)
    return r, mem['cap']


def h(cap, off):
    return struct.unpack_from('<h', cap, off)[0]


def check_segment(d, stub, getter):
    stored = {(KEY_A, 0): 0, (KEY_G, 0): 0, (KEY_A, 1): 1, (KEY_G, 1): -1, (KEY_A, 15): -3, (KEY_G, 15): 4}
    bundle = bundle_table({1: (1, 3, -2), 2: (0, 7, 7), 6: (1, -4, 5)})
    cats = {  # name: (capture init)
        'Auto (cat 0) -> [1]': {24006: ('<H', 0)},
        'Sunny preset 8 (cat 1) -> [0]': {24006: ('<H', 1), 24002: ('<H', 8)},
        'Flash preset 13 (cat 1) -> [15]': {24006: ('<H', 1), 24002: ('<H', 13)},
        'One-touch 2 (cat 2) -> [0]': {24006: ('<H', 2), 24130: ('<H', 2)},
        'CWB (cat 3) -> forced 0': {24006: ('<H', 3), 24004: ('<H', 5600), 24132: ('<H', 1)},
        'cat 4 -> [0]': {24006: ('<H', 4)},
    }
    modes = {'COLOR2 flag set': {(KEY_PMODE, 0): 11, (KEY_COLOR_PROF, 0): 2},
             'COLOR3 flag clear': {(KEY_PMODE, 0): 11, (KEY_COLOR_PROF, 0): 3},
             'MONO3 flag set': {(KEY_PMODE, 0): 12, (KEY_MONO_PROF, 0): 3},
             'mode 5 (no bundle)': {(KEY_PMODE, 0): 5, (KEY_COLOR_PROF, 0): 2}}
    rows, ok = [], True
    allowed = {24098, 24099, 24100, 24101, 1874, 1875, 1916, 1917}
    for cname, ci in cats.items():
        for mname, mp in modes.items():
            props = {**stored, **mp}
            rs, cs = run_segment(d, props, bundle, stub, getter, ci, False)
            rp, cp = run_segment(d, props, bundle, stub, getter, ci, True)
            diff = sorted(i for i in range(CAP_SIZE) if cs[i] != cp[i])
            active = mname in ('COLOR2 flag set', 'MONO3 flag set') and not cname.startswith('CWB')
            exp = (3, -2) if mname.startswith('COLOR2') else (-4, 5)
            good = rs['registers']['pc'] == SEG_STOP and rp['registers']['pc'] == SEG_STOP and not rs['fault'] and not rp['fault']
            good &= set(diff) <= allowed
            if active:
                good &= (h(cp, 24098), h(cp, 24100)) == exp and h(cp, 1916) == 1
            else:
                good &= not diff
            ok &= bool(good)
            rows.append(dict(category=cname, mode=mname, passed=bool(good),
                             stock=dict(A=h(cs, 24098), G=h(cs, 24100), preset_code_1874=h(cs, 1874), ft_on_1916=h(cs, 1916)),
                             patched=dict(A=h(cp, 24098), G=h(cp, 24100), preset_code_1874=h(cp, 1874), ft_on_1916=h(cp, 1916)),
                             changed_offsets=diff))
    return dict(check='W native capture WB segment, stock vs redirected sites', passed=ok, rows=rows)


# ---------------------------------------------------------------- G: native gain function
def gains(d, a, g, base=(600, 450, 300, 300)):
    out, src = 0x14000000, 0x14001000
    caller = PR.caller(GAIN_FN, 0xf0, 80)
    regions = [caller, Region('stack', PR.STACK, bytes(0x2000), 'rw'),
               PR.img(d, 'gain', NORM_FN, GAIN_END, 'rx'), PR.img(d, 'coef', COEF, COEF + 24),
               Region('src', src, struct.pack('<4H', *base)), Region('out', out, bytes(8), 'rw', True)]
    r, mem = PR.run(regions, {'pc': PR.CALLER, 'sp': PR.STACK + 0x1800, 'd0': a & 0xffffffff, 'd1': g & 0xffffffff,
                              'a0': out, 'a1': src}, PR.CALLER + 7)
    ok = r['registers']['pc'] == PR.CALLER + 7 and r['registers']['sp'] == PR.STACK + 0x1800 and not r['fault']
    return ok, struct.unpack('<4H', mem['out'])


def check_gains(d):
    rows, ok = [], True
    for a, g in ((0, 0), (1, -1), (3, -2), (-4, 5), (7, 0), (0, 7)):
        good, o = gains(d, a, g)
        ok &= good
        rows.append(dict(A=a, G=g, out=o, returned=good))
    zero = rows[0]['out']
    ok &= all(r['out'] != zero for r in rows[1:])
    ok &= gains(d, 3, -2)[1] == gains(d, 3, -2)[1]
    return dict(check='G native gain calculator 0x603b5769 (unmodified)', passed=bool(ok), base=(600, 450, 300, 300), rows=rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    d = PR.main_image()
    for s in CAPTURE_SITES + OTHER_SITES:
        o = s - BASE
        assert d[o] == 0xdd and d[o + 5:o + 7] == b'\xc0\x0c' and s + struct.unpack_from('<i', d, o + 1)[0] == GETTER, hex(s)
    stub, getter = stub_bytes(BUNDLE_SYN), fake_getter()
    assert STUB_AT + len(stub) + 16 <= 0x6055e800 and len(fake_getter()) < 0x60
    res = [check_stub(stub, getter), check_segment(d, stub, getter), check_gains(d)]
    for x in res:
        print(f"{'PASS' if x['passed'] else 'FAIL'}  {x['check']}")
    for c in res[0]['cases']:
        print(f"   {'ok ' if c['passed'] else 'BAD'} {c['case']}: got {c['got']} (want {c['expected']})")
    for r in res[1]['rows']:
        print(f"   {'ok ' if r['passed'] else 'BAD'} {r['category']:<34} {r['mode']:<19} stock A/G={r['stock']['A']}/{r['stock']['G']} "
              f"code={r['stock']['preset_code_1874']} on={r['stock']['ft_on_1916']} -> patched {r['patched']['A']}/{r['patched']['G']} "
              f"code={r['patched']['preset_code_1874']} on={r['patched']['ft_on_1916']}  diff@{r['changed_offsets']}")
    for r in res[2]['rows']:
        print(f"   A={r['A']:+d} G={r['G']:+d} -> out {r['out']}")
    print(f'stub {len(stub)} B at {STUB_AT:#x}; sites: {len(CAPTURE_SITES)} capture + {len(OTHER_SITES)} other (all `dd rel32 c0 0c` -> 0x6005e971)')
    if a.json:
        a.json.write_text(json.dumps(dict(scope='emulator only; synthetic RAM; fake getter is test code', stub_hex=stub.hex(),
                                          results=res), indent=1, default=str))
    sys.exit(0 if all(x['passed'] for x in res) else 1)


if __name__ == '__main__':
    main()
