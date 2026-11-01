#!/usr/bin/env python3
"""E-P7 1.1 Log View Assist (trigger T-D) and its camera probe P-VA0. Offline; no camera.

Design: docs/LOG_VIEW_ASSIST.md ("Trigger measurement"). Never writes SD-update-named files.

Edits (section 1 only; hook and code in the same section):
  0x601751f4  5 B  display reply tail `movhu (44,sp),d0; clr d2; mov d0,d1` -> jmp va_hook
  0x601e383c 256 B VA LUT (row-0 gamma o inverse id-2001 log gamma; tools/ep7_view_assist_probe.py C1)
                   in dead EVF step-0 R table
  0x601e393c  n B  va_hook in dead EVF step-0 G table
  0x601e3c40 12 B  TFT step-17 slot R/G/B pointers (stock NULL) -> VA LUT
Variants:
  full  (test10):  want = TFT through image on && record[(0xa273104c)<5].+925 == 2
  probe (P-VA0):   want = TFT through image on          (no +925 test: shows the playback signal)

Verification (native code in fishcu's MN103 runner; every image region read-only, so any store into
the image faults; the stub's state inputs are read-only too):
  S  stub matrix through the patched hook with a spy at the programmer: call/no-call and step id,
     replayed registers, d3/a2/a3/sp preserved, dispatcher frame above sp untouched, no VSC access at
     all while the TFT is not running (IO unmapped).
  P  full chain with the REAL stock programmer 0x60187439 + LUT/mode writers: want on -> VSC TFT bank 1
     = VA LUT words and mode 0x111; second pass -> nothing written (loads once); through off or log off
     -> mode 0 (bypass).
  M  source mutations of the stub: every mutant must fail S or P.

  python3 -I patches/view_assist/build_and_verify.py
  python3 -I patches/view_assist/build_and_verify.py --package releases/probe-VA0/patched.pkg.bin probe
"""
import json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import ep7_view_assist_probe as VA  # noqa: E402
from penf_emulator import execute, Region  # noqa: E402

TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE = 0x60020020
HOOK, HOOK_STOCK, RET = 0x601751f4, bytes.fromhex('f8bc2c0881'), 0x601751f9
LUT_AT, CODE_AT, CODE_LIMIT = 0x601e383c, 0x601e393c, 0x601e3a3c
STEP_TABLE = 0x601e3b3c
STEP16, STEP17 = STEP_TABLE + 16 * 15, STEP_TABLE + 16 * 16       # TFT slots 15/16 = steps 16/17
PTR17 = STEP17 + 4
PROG, MODE_GET = 0x60187439, 0x60189198
SYMS = dict(ep7_mode_get=MODE_GET, ep7_prog=PROG, ep7_ret=RET, ep7_step16=STEP16, ep7_step17=STEP17)
RUN, THR, IDX, RING, NREC, OFF925 = 0xa272c40c, 0xa272c418, 0xa273104c, 0xa2731098, 5, 925
IO, MODE_REG = 0x9c000000, 0x9c000204
STACK, SP0 = 0x18000000, 0x18000800
SPY = 0x1c000000
OUT = ROOT / 'generated/view_assist'

WANT_FULL = ''' movhu (0xa273104c),d0             /* current 980-B settings record (ring of 5) */
 cmp 5,d0
 bcc want_off
 mov 980,d1
 mul d1,d0
 mov d0,a0
 add 0xa2731098,a0
 movbu (925,a0),d0                 /* +925: 2 = log (id 2001) */
 cmp 2,d0
 bne want_off'''


def gas(src, at, syms=None):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'p.o', t / 'p.s'], check=True, capture_output=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in (syms or {}).items()], '-o', t / 'p.elf', t / 'p.o'],
                       check=True, capture_output=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        return (t / 'p.bin').read_bytes(), dis


def stub_src(variant, mutate=None):
    src = (Path(__file__).parent / 'view_assist.s.in').read_text()
    src = src.replace('{want_code}', WANT_FULL if variant == 'full' else '')
    src = src.replace('{want_extra}', '&& +925 == 2' if variant == 'full' else '(probe: no +925 test)')
    if mutate:
        old, new = mutate
        assert src.count(old) >= 1, old
        src = src.replace(old, new, 1)
    return src


def tiny(src, at):
    return gas(' .am33_2\n .text\n .global _start\n_start:\n' + src + '\n', at)[0]


def patched_image(stock, code, lut):
    d = bytearray(stock)
    o = lambda a: a - BASE
    assert d[o(HOOK):o(HOOK) + 5] == HOOK_STOCK
    assert d[o(PTR17):o(PTR17) + 12] == bytes(12) and d[o(STEP17)] == 17 and d[o(STEP16)] == 16
    assert len(code) <= CODE_LIMIT - CODE_AT and len(lut) == 256
    jmp = b'\xdc' + struct.pack('<i', CODE_AT - HOOK)
    d[o(HOOK):o(HOOK) + 5] = jmp
    d[o(LUT_AT):o(LUT_AT) + 256] = lut
    d[o(CODE_AT):o(CODE_AT) + len(code)] = code
    d[o(PTR17):o(PTR17) + 12] = struct.pack('<3I', LUT_AT, LUT_AT, LUT_AT)
    return bytes(d), jmp


def img(d, name, lo, hi, perm='rx'):
    return Region(name, lo, d[lo - BASE:hi - BASE], perm)


def state_regions(run, thr, idx, v925):
    st = bytearray(0x40)
    struct.pack_into('<I', st, RUN - 0xa272c400, run)
    struct.pack_into('<I', st, THR - 0xa272c400, thr)
    ring = bytearray(RING - 0xa2731040 + 980 * NREC)                     # ends exactly at 0xa27323bc
    struct.pack_into('<H', ring, IDX - 0xa2731040, idx)
    for k in range(NREC):
        ring[RING - 0xa2731040 + 980 * k + OFF925] = 0                   # other slots: not log
    if idx < NREC:
        ring[RING - 0xa2731040 + 980 * idx + OFF925] = v925
    return [Region('state', 0xa272c400, bytes(st), 'r'), Region('ring', 0xa2731040, bytes(ring), 'r')]


def frame():
    s = bytearray((i * 37 + 11) & 0xff for i in range(0x1000))
    struct.pack_into('<H', s, SP0 - STACK + 44, 0x0002)                 # (44,sp) reply kind
    return bytes(s)


REGS = dict(pc=HOOK, sp=SP0, d3=0x33333333, a2=0x2a2a2a2a, a3=0x3a3a3a3a, d0=0xd0d0d0d0, d1=0xd1d1d1d1,
            d2=0xd2d2d2d2, a0=0xa0a0a0a0, a1=0xa1a1a1a1)


def regs_ok(r, f0, mem):
    g = r['registers']
    return (not r['fault'] and g['pc'] == RET and g['sp'] == SP0 and g['d0'] == 2 and g['d1'] == 2
            and g['d2'] == 0 and g['d3'] == REGS['d3'] and g['a2'] == REGS['a2'] and g['a3'] == REGS['a3']
            and mem['stack'][SP0 - STACK + 4:] == f0[SP0 - STACK + 4:])   # (0..3,sp) = call return slot (stock MN103 call semantics)


# ---------------------------------------------------------------- S: stub matrix with spy programmer
def spy_code():
    return tiny(f''' mov d0,({SPY:#x})
 movbu (a0),d1
 movbu d1,({SPY + 4:#x})
 mov 1,d1
 movbu d1,({SPY + 5:#x})
 mov 0x55555555,d0
 mov d0,a0
 mov d0,a1
 mov d0,d1
 ret [d2,d3,a2,a3],92''', PROG)


def run_stub(img_, run, thr, idx, v925, mode, spy):
    io = bytearray(0x8000)
    struct.pack_into('<I', io, MODE_REG - IO, mode)
    f0 = frame()
    regions = [img(img_, 'hook', HOOK, HOOK + 0x10), img(img_, 'stub', CODE_AT, CODE_LIMIT),
               img(img_, 'modeget', MODE_GET, MODE_GET + 0x16), img(img_, 'dev2ch', 0x60043bdd, 0x60043bf6),
               img(img_, 'steps', STEP_TABLE, STEP_TABLE + 640, 'r'),
               Region('spy_code', PROG, spy, 'rx'), Region('spy', SPY, bytes(8), 'rw', True),
               Region('stack', STACK, f0, 'rw', True), *state_regions(run, thr, idx, v925)]
    if run & 1:
        regions.append(Region('io', IO, bytes(io), 'r'))             # TFT off: IO unmapped -> any access faults
    r = execute(regions, dict(REGS), RET, limit=5000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    s = mem.get('spy', bytes(8))
    called = s[5] == 1
    return dict(ok=regs_ok(r, f0, mem), called=called, mask=struct.unpack_from('<I', s)[0] if called else None,
                step=s[4] if called else None, fault=r['fault'])


def expect(variant, run, thr, idx, v925, mode):
    if not run & 1:
        return None
    want = bool(thr & 1) and (variant == 'probe' or (idx < NREC and v925 == 2))
    if want == (mode != 0):
        return None
    return 17 if want else 16


def check_stub(img_, variant, spy):
    res, ok = [], True
    for run in (0, 1, 0x6):          # 0x6 = EVF/HDMI running, TFT not
        for thr in (0, 1, 0x4):
            for idx, v925 in ((0, 2), (3, 2), (4, 1), (0, 0), (5, 2), (0xffff, 2)):
                for mode in (0, 0x111, 0x222):
                    if not run & 1 and (thr, idx, mode) != (1, 0, 0):
                        continue     # TFT off: one representative per thr/v925 is enough
                    o = run_stub(img_, run, thr, idx, v925, mode, spy)
                    e = expect(variant, run, thr, idx, v925, mode)
                    good = o['ok'] and (o['step'] == e) and (e is None or o['mask'] == 1)
                    ok &= good
                    if not good or len(res) < 400:
                        res.append(dict(run=run, thr=thr, idx=idx, v925=v925, mode=hex(mode), expect=e,
                                        got=o['step'], regs_ok=o['ok'], fault=o['fault'], passed=bool(good)))
    return dict(check=f'S stub matrix ({variant})', passed=bool(ok), cases=res)


# ---------------------------------------------------------------- P: full chain, real programmer
def helper_stubs():
    return [Region('get_thr', 0x60175cdf, tiny(' mov 1,d0\n ret [d2,d3,a2],16', 0x60175cdf), 'rx'),
            Region('set_thr', 0x60175c01, tiny(' ret [d2,d3,a2],24', 0x60175c01), 'rx'),
            Region('memcpy', 0x47001052, tiny(' ret [d2,d3,a2,a3],28', 0x47001052), 'rx'),
            Region('memset', 0x4700115e, tiny(' ret [d2,a2],8', 0x4700115e), 'rx'),
            Region('errlog', 0x6002260d, tiny(' ret [a2,a3],12', 0x6002260d), 'rx'),
            Region('refresh', 0x601876e6, tiny(' ret [d2,d3,a2],40', 0x601876e6), 'rx')]


def run_chain(img_, io, run, thr, idx, v925):
    f0 = frame()
    regions = [img(img_, 'hook', HOOK, HOOK + 0x10), img(img_, 'luts', 0x601de13c, STEP_TABLE + 640),
               img(img_, 'modeget', MODE_GET, MODE_GET + 0x16), img(img_, 'dev2ch', 0x60043bdd, 0x60043bf6),
               img(img_, 'prog', PROG, 0x601876e6), img(img_, 'vsc', 0x601885a8, 0x60188680),
               img(img_, 'evfq', 0x6018646c, 0x60186470), *helper_stubs(),
               Region('devstate', 0xa272c538, bytes(0x2000), 'rw', True),
               Region('stack', STACK, f0, 'rw', True), Region('io', IO, bytes(io), 'rw', True),
               *state_regions(run, thr, idx, v925)]
    r = execute(regions, dict(REGS), RET, limit=200000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return regs_ok(r, f0, mem), mem.get('io', bytes(io)), mem.get('devstate'), r['fault']


def lut_words(lut):
    return [((lut[2 * i + 1] << 18) & 0xffff0000) | ((lut[2 * i] << 2) & 0xffff) for i in range(128)]


def check_chain(img_, variant, lut):
    steps, ok = [], True
    io = bytes(0x8000)
    want_words = lut_words(lut)
    seq = [('log on, live view', 1, 1, 2, 2, 'load'),
           ('again (no change)', 1, 1, 2, 2, 'same'),
           ('playback (through off)', 1, 0, 2, 2, 'bypass'),
           ('back to live view', 1, 1, 2, 2, 'load2'),
           ('log off (+925=0)', 1, 1, 2, 0, 'bypass' if variant == 'full' else 'same'),
           ('TFT not running', 0, 1, 2, 2, 'same')]
    for name, run, thr, idx, v925, what in seq:
        before = io
        good_regs, io, dev, fault = run_chain(img_, io, run, thr, idx, v925)
        mode = struct.unpack_from('<I', io, MODE_REG - IO)[0]
        banks = {b: list(struct.unpack_from('<128I', io, 0x2000 + 0x400 * ch + (0 if b == 1 else 0x200)))
                 for ch in range(3) for b in (1, 2)}
        if what == 'same':
            good = io == before
        elif what == 'bypass':
            good = mode == 0
        elif what == 'load':
            good = mode == 0x111 and all(
                list(struct.unpack_from('<128I', io, 0x2000 + 0x400 * ch)) == want_words for ch in range(3))
        else:   # load2: ping-pong to bank 2 (current 0 -> bank 1 per stock; accept either bank holding the LUT)
            good = mode in (0x111, 0x222) and all(
                list(struct.unpack_from('<128I', io, 0x2000 + 0x400 * ch + (0 if mode == 0x111 else 0x200))) == want_words
                for ch in range(3))
        good = good and good_regs and not fault
        ok &= good
        steps.append(dict(step=name, expect=what, mode=hex(mode), regs_ok=good_regs, fault=fault, passed=bool(good)))
    return dict(check=f'P full chain with stock programmer ({variant})', passed=bool(ok), steps=steps)


# ---------------------------------------------------------------- M: mutations
MUTANTS = [
    ('TFT run bit', ' btst 1,d0\n beq out', ' btst 2,d0\n beq out'),
    ('drop run gate', ' beq out                           /* TFT not running', ' nop\n nop /*'),
    ('through bit', ' btst 1,d0\n beq want_off', ' btst 2,d0\n beq want_off'),
    ('drop through gate', ' beq want_off                      /* through', ' nop\n nop /*'),
    ('load every time', ' bne out                           /* already loaded', ' nop\n nop /*'),
    ('bypass every time', ' beq out                           /* already bypass', ' nop\n nop /*'),
    ('swap steps', ' mov ep7_step17,a0', ' mov ep7_step16,a0'),
    ('wrong device', ' mov 1,d0                          /* device mask', ' mov 2,d0 /*'),
    ('replay d2', '\n clr d2', '\n mov 1,d2'),
    ('replay offset', '\n movhu (44,sp),d0', '\n movhu (48,sp),d0'),
]
MUTANTS_FULL = [
    ('log value', ' cmp 2,d0\n bne want_off', ' cmp 1,d0\n bne want_off'),
    ('ring bound', ' cmp 5,d0', ' cmp 6,d0'),
    ('record stride', ' mov 980,d1', ' mov 984,d1'),
    ('925 offset', ' movbu (925,a0),d0', ' movbu (924,a0),d0'),
    ('drop log test', ' bne want_off', ' nop\n nop'),
]


def check_mutants(stock, variant, lut, spy):
    res = []
    for name, old, new in MUTANTS + (MUTANTS_FULL if variant == 'full' else []):
        try:
            code, _ = gas(stub_src(variant, (old, new)), CODE_AT, SYMS)
        except subprocess.CalledProcessError as e:
            res.append(dict(mutant=name, caught=True, how='does not assemble'))
            continue
        im, _ = patched_image(stock, code, lut)
        s = check_stub(im, variant, spy)
        caught = not s['passed']
        if not caught:
            caught = not check_chain(im, variant, lut)['passed']
        res.append(dict(mutant=name, caught=bool(caught)))
    return dict(check=f'M mutations ({variant})', passed=all(r['caught'] for r in res), cases=res)


def verify_package(pkg_path, variant):
    """Re-run S and P on the main payload decoded from a BUILT package (the bytes that would ship)."""
    import oly_container as oc
    main = bytes(oc.parse(Path(pkg_path).read_bytes())[0].payload)
    stock = VA.main_image()
    c1, lut = VA.c1_lut(stock)
    code, _ = gas(stub_src(variant), CODE_AT, SYMS)
    ref, _ = patched_image(stock, code, bytes(lut))
    spans = [(HOOK, 5), (LUT_AT, 256), (CODE_AT, len(code)), (PTR17, 12)]
    same = all(main[a - BASE:a - BASE + n] == ref[a - BASE:a - BASE + n] for a, n in spans)
    checks = [dict(check=f'K package bytes == verified image at the 4 view-assist spans ({variant})', passed=same),
              check_stub(main, variant, spy_code()), check_chain(main, variant, bytes(lut))]
    for c in checks:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['check'] + f'  [{pkg_path}]')
    return all(c['passed'] for c in checks)


def main():
    if len(sys.argv) == 4 and sys.argv[1] == '--package':
        sys.exit(0 if verify_package(sys.argv[2], sys.argv[3]) else 1)
    stock = VA.main_image()
    c1, lut = VA.c1_lut(stock)
    lut = bytes(lut)
    assert c1['pass'] and len(lut) == 256 and lut[0] == 0 and lut[255] == 255
    spy = spy_code()
    OUT.mkdir(parents=True, exist_ok=True)
    allok = True
    for variant, patch in (('probe', 'view_assist_probe_VA0'), ('full', 'view_assist_T_D')):
        code, dis = gas(stub_src(variant), CODE_AT, SYMS)
        im, jmp = patched_image(stock, code, lut)
        checks = [check_stub(im, variant, spy), check_chain(im, variant, lut), check_mutants(stock, variant, lut, spy)]
        for c in checks:
            print(('PASS ' if c['passed'] else 'FAIL ') + c['check'])
            for k in c.get('steps', []) + (c['cases'] if c['check'].startswith('M') else [x for x in c.get('cases', []) if not x['passed']][:10]):
                print('     ', k)
        allok &= all(c['passed'] for c in checks)
        o = lambda a, n: stock[a - BASE:a - BASE + n].hex()
        edits = [dict(kind='0x100', addr=hex(HOOK), expect=HOOK_STOCK.hex(), new=jmp.hex(),
                      why='display reply tail movhu (44,sp),d0; clr d2; mov d0,d1 -> jmp va_hook (T-D reconcile)'),
                 dict(kind='0x100', addr=hex(LUT_AT), expect=o(LUT_AT, 256), new=lut.hex(),
                      why='View Assist LUT (log 2001 -> row-0 display), in dead EVF step-0 R table'),
                 dict(kind='0x100', addr=hex(CODE_AT), expect=o(CODE_AT, len(code)), new=code.hex(),
                      why=f'va_hook ({len(code)} B, {variant}) in dead EVF step-0 G table'),
                 dict(kind='0x100', addr=hex(PTR17), expect=o(PTR17, 12), new=struct.pack('<3I', LUT_AT, LUT_AT, LUT_AT).hex(),
                      why='TFT gamma step-17 slot R/G/B pointers NULL -> VA LUT')]
        spec = dict(components=['0x100'], patch=patch, variant=variant, code_at=hex(CODE_AT), code_len=len(code),
                    edits=edits)
        (OUT / f'{variant}.json').write_text(json.dumps(spec, indent=1) + '\n')
        (OUT / f'{variant}.lst').write_text(dis)
        (OUT / f'{variant}.verify.json').write_text(json.dumps(checks, indent=1) + '\n')
        print(f'{variant}: code {len(code)} B at {CODE_AT:#x}; wrote {OUT / (variant + ".json")}')
    sys.exit(0 if allok else 1)


if __name__ == '__main__':
    main()
