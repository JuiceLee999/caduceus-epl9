#!/usr/bin/env python3
"""Offline emulator checks of the E-P7 1.1 COLOR builder/selector and the H/L hook contract.

Reuses fishcu's strict MN103 runner (external/oly_fw_analysis, libsim based) through its
generic `execute()` entry; every memory region is supplied explicitly from OUR decoded
E-P7 main. Nothing here writes firmware files: the test stub is assembled to a temp
directory and only ever exists inside the emulator's RAM model.

Checks:
  A  native builder 0x603b0068: output records at +688 (24 B), hue at rec+18, L at rec+22,
     control word at +976; table H/L overrides propagate to those fields.
  B  native selector 0x603b0252 with a synthetic job/request/context, unmodified.
  C  same, with the 5-byte call at 0x603b02d9 replaced (in emulator RAM only) by a 5-byte
     jmp to a test stub placed at a candidate code-space address. The stub re-issues the
     builder call, validates callback/record/parent exactly as the native job layout
     requires (E-P7 offsets), then writes H/L from job+15488 into the output records.
     Confirms: hook site, rejoin 0x603b02de, register contract (a2 = context after the
     call), request = job+11364, records = request+3212 stride 56 x16, parent at record+0,
     output hue offset 706 (=688+18), trailer offset 15488, and the selector's own
     return/stack. Also negative controls: wrong callback / foreign record -> untouched.

Usage: tools/ep7_color_probe.py [--json out.json]
"""
import argparse, hashlib, json, os, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
from penf_emulator import execute, Region  # noqa: E402  (generic runner; no PEN-F image used)

MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
BASE = 0x60020020
TC = Path(os.environ.get('MN10300_BIN', Path.home() / 'ep7fw-toolchains/mn10300/bin'))

TABLE, TABLE_SIZE, GAINS = 0x6051de2c, 3028, 0x60531810
BUILDER, SELECTOR, SELECTOR_END = 0x603b0068, 0x603b0252, 0x603b0345
HOOK, RESUME, CALLBACK = 0x603b02d9, 0x603b02de, 0x60355fd4
REQ_IN_JOB, RECORDS_IN_JOB, REC_STRIDE, N_REC = 11364, 14576, 56, 16
JOB_SIZE = 15488           # stock allocation (mov 15488,d0 at 0x603537f0)
OUT_RECORDS, OUT_CONTROL = 688, 976
STUB_AT = 0x6055e5c0       # candidate: section-2 FF suffix (0x6055e5b0..0x6055e800)

# Synthetic RAM (not camera addresses)
CALLER, STACK, SAT = 0x18000000, 0x18010000, 0x10000000
OUTPUT, CONTEXT, JOB = 0x19000000, 0x1a000000, 0x1b000000

STUB_SRC = r"""
 .am33_2
 .text
 .global _start
_start:
 call ep7_builder,[d2,d3,a2,a3],96 /* displaced stock instruction (PC-relative, resolved by ld) */
 add -28,sp
 mov d0,(0,sp)
 mov d1,(4,sp)
 mov a0,(8,sp)
 mov a1,(12,sp)
 mov a2,(16,sp)
 mov a3,(20,sp)
 mov d2,(24,sp)
 mov (4,a2),a1                     /* context+4 -> request */
 mov (a1),d0
 cmp {callback},d0
 bne out
 mov (4,a1),d0                     /* request+4 -> selected record */
 mov a1,a0
 add {rec_off},a0
 mov {n_rec},d2
scan:
 cmp a0,d0
 beq hit
 add {stride},a0
 add -1,d2
 bne scan
 bra out
hit:
 mov (a0),d1                       /* record+0 = parent job */
 mov a1,a0
 add -{req_in_job},a0
 cmp a0,d1
 bne out
 mov (12,a2),a3                    /* context+12 -> colour output */
 add {hue_off},a3                  /* record 0 hue halfword */
 mov a0,a2
 add {trailer},a2                  /* job trailer: 12 x H then 12 x L, wheel order */
 clr d2                            /* d2 = table record r = 0..11 */
rec:
 mov d2,d0                         /* wheel index = 2*(r%6) + r/6 */
 clr d1
 cmp 6,d0
 blt lo
 add -6,d0
 mov 1,d1
lo:
 add d0,d0
 add d1,d0
 mov a2,a0
 add d0,a0
 movbu (a0),d0                     /* H (signed byte), test scale: H*1000 */
 extb d0
 mov d0,d1
 asl 10,d0                         /* *1024 ... */
 sub d1,d0                         /* -H  -> *1023 (test value, not a tuned LUT) */
 movhu d0,(a3)
 movbu (12,a0),d0                  /* L (signed byte), test scale: L*50 */
 extb d0
 mov d0,d1
 asl 6,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0
 sub d1,d0                         /* 64L-14L = 50L */
 movhu d0,(4,a3)
 add 24,a3
 inc d2
 cmp 12,d2
 bne rec
out:
 mov (0,sp),d0
 mov (4,sp),d1
 mov (8,sp),a0
 mov (12,sp),a1
 mov (16,sp),a2
 mov (20,sp),a3
 mov (24,sp),d2
 add 28,sp
 jmp ep7_resume
"""


def main_image():
    d = MAIN.read_bytes()
    assert hashlib.sha256(d).hexdigest() == MAIN_SHA, 'unexpected E-P7 main'
    return d


def img(d, name, lo, hi, perm='r'):
    return Region(name, lo, d[lo - BASE:hi - BASE], perm)


def gain_regions(d):
    regs = [img(d, 'gain_ptrs', GAINS, GAINS + 48)]
    for p in sorted(set(struct.unpack_from('<12I', d, GAINS - BASE))):
        regs.append(img(d, f'gain_{p:x}', p, p + 4))
    return regs


def caller(target, mask, frame):
    return Region('caller', CALLER, b'\xdd' + struct.pack('<i', target - CALLER) + bytes((mask, frame)) + b'\xcb', 'rx')


def run(regions, regs, stop):
    r = execute(regions, regs, stop, limit=20000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return r, mem


def records(out):
    return [dict(hue=struct.unpack_from('<h', out, OUT_RECORDS + 24 * i + 18)[0],
                 sat=struct.unpack_from('<h', out, OUT_RECORDS + 24 * i + 20)[0],
                 light=struct.unpack_from('<h', out, OUT_RECORDS + 24 * i + 22)[0]) for i in range(12)]


def check_builder(d):
    table = bytearray(d[TABLE - BASE:TABLE - BASE + TABLE_SIZE])
    struct.pack_into('<h', table, 28 * 3 + 12, 1234)   # record 3 hue
    struct.pack_into('<h', table, 28 * 7 + 16, -321)   # record 7 lightness
    regions = [caller(BUILDER, 0xf0, 96), img(d, 'builder', BUILDER, 0x603b0252, 'rx'),
               Region('stack', STACK, bytes(0x2000), 'rw'), Region('table', TABLE, bytes(table)),
               Region('sat', SAT, bytes(12)), Region('out', OUTPUT, bytes(5212), 'rw', True)] + gain_regions(d)
    r, mem = run(regions, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': TABLE, 'a1': SAT, 'd1': OUTPUT,
                           'd0': struct.unpack_from('<H', table, 3024)[0]}, CALLER + 7)
    recs = records(mem['out'])
    ok = (r['status'] in ('returned', 'stopped', 'stop') or r['registers']['pc'] == CALLER + 7)
    ok &= r['registers']['pc'] == CALLER + 7 and r['registers']['sp'] == STACK + 0x1800
    ok &= recs[3]['hue'] == 1234 and recs[7]['light'] == -321
    ok &= all(recs[i]['hue'] == struct.unpack_from('<h', table, 28 * i + 12)[0] for i in range(12))
    ok &= struct.unpack_from('<I', mem['out'], OUT_CONTROL)[0] == 0xfff
    return dict(check='A native builder', passed=bool(ok), status=r['status'], instructions=r['completed'],
                records=recs, control=hex(struct.unpack_from('<I', mem['out'], OUT_CONTROL)[0]))


def assemble_stub():
    src = STUB_SRC.format(builder=hex(BUILDER), callback=hex(CALLBACK), rec_off=RECORDS_IN_JOB - REQ_IN_JOB,
                          n_rec=N_REC, stride=REC_STRIDE, req_in_job=REQ_IN_JOB, hue_off=OUT_RECORDS + 18,
                          trailer=JOB_SIZE, resume=hex(RESUME))
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 's.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 's.o', t / 's.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(STUB_AT), '-e', '_start', f'--defsym=ep7_builder={BUILDER:#x}',
                        f'--defsym=ep7_resume={RESUME:#x}', '-o', t / 's.elf', t / 's.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 's.elf', t / 's.bin'], check=True)
        return (t / 's.bin').read_bytes()


def selector_fixture(d, sat, h, l, *, hook=None, callback=CALLBACK, record_index=5, foreign_parent=False):
    job = bytearray(JOB_SIZE + 24)
    req = REQ_IN_JOB
    rec = RECORDS_IN_JOB + REC_STRIDE * record_index
    struct.pack_into('<I', job, req + 0, callback)
    struct.pack_into('<I', job, req + 4, JOB + rec)
    struct.pack_into('<I', job, rec, JOB + (64 if foreign_parent else 0))
    job[req + 8:req + 12] = bytes([0, 0, 11, 0])           # mode word 11 (big-endian bytes,halfword)
    struct.pack_into('<H', job, req + 12, 0)                # != 0xf00d bypass
    struct.pack_into('<I', job, req + 1524, 0)
    job[req + 1816:req + 1828] = struct.pack('<12b', *sat)
    job[JOB_SIZE:JOB_SIZE + 12] = struct.pack('<12b', *h)
    job[JOB_SIZE + 12:JOB_SIZE + 24] = struct.pack('<12b', *l)
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, JOB + req)
    struct.pack_into('<I', ctx, 12, OUTPUT)
    struct.pack_into('<I', ctx, 56, 0)
    struct.pack_into('<I', ctx, 60, 0)
    code = bytearray(d[BUILDER - BASE:SELECTOR_END - BASE])
    regions = [caller(SELECTOR, 0xf0, 20), Region('stack', STACK, bytes(0x2000), 'rw'),
               img(d, 'table', TABLE, TABLE + TABLE_SIZE),
               Region('job', JOB, bytes(job), 'rw', True), Region('ctx', CONTEXT, bytes(ctx), 'rw', True),
               Region('out', OUTPUT, bytes(5212), 'rw', True)] + gain_regions(d)
    if hook is not None:
        rel = STUB_AT - HOOK
        code[HOOK - BUILDER:HOOK - BUILDER + 5] = b'\xdc' + struct.pack('<i', rel)   # jmp d32 (5 bytes)
        regions.append(Region('stub', STUB_AT, hook, 'rx'))
    regions.append(Region('code', BUILDER, bytes(code), 'rx'))
    regs = {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CONTEXT, 'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}
    r, mem = run(regions, regs, CALLER + 7)
    rr = r['registers']
    callee_saved = rr['d2'] == 0x2222 and rr['d3'] == 0x3333 and rr['a2'] == 0xa2a2 and rr['a3'] == 0xa3a3
    return r, mem, dict(returned=rr['pc'] == CALLER + 7, stack_ok=rr['sp'] == STACK + 0x1800,
                        callee_saved_ok=callee_saved, instructions=r['completed'], status=r['status'],
                        fault=r['fault'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    d = main_image()
    results = [check_builder(d)]
    sat = [3, -2, 0, 1, 0, 0, -5, 0, 2, 0, 0, 4]
    h = [1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -7]
    l = [7, 6, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4]
    r0, m0, s0 = selector_fixture(d, sat, h, l)
    base = records(m0['out'])
    results.append(dict(check='B native selector (stock code)', passed=all(s0[k] for k in ('returned', 'stack_ok', 'callee_saved_ok')),
                        **s0, records=base))
    stub = assemble_stub()
    r1, m1, s1 = selector_fixture(d, sat, h, l, hook=stub)
    got = records(m1['out'])
    exp_ok = True
    for rnum in range(12):
        w = 2 * (rnum % 6) + rnum // 6
        exp_ok &= got[rnum]['hue'] == h[w] * 1023 and got[rnum]['light'] == l[w] * 50
        exp_ok &= got[rnum]['sat'] == base[rnum]['sat']          # saturation result preserved
    ctx_same = m1['ctx'] == m0['ctx']
    results.append(dict(check='C selector + hook (emulator RAM only)', stub_bytes=len(stub), stub_at=hex(STUB_AT),
                        passed=bool(exp_ok and ctx_same and all(s1[k] for k in ('returned', 'stack_ok', 'callee_saved_ok'))),
                        context_unchanged_vs_stock=ctx_same, **s1, records=got))
    for name, kw in (('C- wrong callback', dict(callback=CALLBACK + 1)), ('C- foreign parent', dict(foreign_parent=True))):
        r2, m2, s2 = selector_fixture(d, sat, h, l, hook=stub, **kw)
        same = records(m2['out']) == base
        results.append(dict(check=name, passed=bool(same and s2['returned'] and s2['stack_ok']), output_equals_stock=same, **s2))
    for i in (0, 15):
        r3, m3, s3 = selector_fixture(d, sat, h, l, hook=stub, record_index=i)
        results.append(dict(check=f'C record index {i}', passed=bool(records(m3['out']) == got and s3['returned']), **s3))
    for x in results:
        print(f"{'PASS' if x['passed'] else 'FAIL'}  {x['check']}  ({x.get('instructions')} insns, status={x.get('status')})")
    if a.json:
        a.json.write_text(json.dumps(dict(main_sha256=MAIN_SHA, scope='Emulator-only; synthetic RAM fixtures; '
                                          'no ISP/pixel/camera behaviour; stub never packaged', results=results), indent=1, default=str))
    sys.exit(0 if all(x['passed'] for x in results) else 1)


if __name__ == '__main__':
    main()
