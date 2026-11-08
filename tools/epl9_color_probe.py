#!/usr/bin/env python3
"""Offline emulator checks of the E-PL9 1.101 COLOR builder/selector and the colour hook contract.

The E-PL9 counterpart of tools/ep7_color_probe.py. It uses the same strict MN103 runner
(external/oly_fw_analysis, libsim based) with every memory region taken from OUR decoded E-PL9 main.
Nothing here writes firmware files: the test stub is assembled to a temp directory and only ever
exists inside the emulator's RAM model, at a synthetic address (not a code-space claim).

All addresses are E-PL9 RUNTIME addresses: its main image loads at 0x60400020 (the E-P7's at 0x60020020),
so file offset = address - 0x60400020. Every absolute pointer agrees (callback, key-hash handlers, table,
gains). Older notes that used the E-P7 base list E-PL9 code 0x3e0000 lower.

E-PL9 differences from the E-P7 (all found statically, then exercised here):
  * COLOR table 0x608ee360, gains 0x60900230 (E-P7 0x6051de2c / 0x60531810).
  * Saturation bytes at request+1813 (E-P7 +1816).
  * Job: size 14552 (constructor `mov 14552,d0` at 0x6074df09), request at job+10440
    (0x6074f961), records at job+13640 = request+3200. E-P7: 15488 / 11364 / 14576 = request+3212.
  * Job callback 0x607504f6 (request-header init 0x6074f225; E-P7 0x60355fd4).

Checks:
  A  native builder 0x6079e9e2: output records at +688 (24 B), table H/L overrides propagate.
  B  native selector 0x6079ebcc, mode 11, unmodified code.
  C  same, with the 5-byte call at 0x6079ec53 replaced (emulator RAM only) by a jmp to a test stub
     that re-issues the builder call, validates callback/record/parent with the E-PL9 job layout,
     writes H/L from job+14552 into the output records and rejoins at 0x6079ec58.
     Negative controls: wrong callback / foreign parent -> output equals stock. Record index 0 and 15.
  D  gate: which request mode words reach the builder (stock code). Also the 0xf00d bypass.
  E  stock selector with an edited RUNTIME table (0x608ee360): per-hue H (+12) and L (+16) edits reach
     the output; +14 does not (output saturation comes from request+1813 x gains).

Usage: tools/epl9_color_probe.py [--json out.json]   (run under Linux/WSL; needs the built engine)
"""
import argparse, hashlib, json, os, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
from penf_emulator import execute, Region  # noqa: E402  (generic runner; no PEN-F image used)

MAIN = ROOT / 'analysis/epl9_1101/00_0100_406e0020.decoded.bin'
MAIN_SHA = '8e39c335d54fd8ddea189db82fe708159f43f9995bba42c2cd47dd22b8814267'
BASE = 0x60400020          # E-PL9 main load address (E-P7: 0x60020020)
TC = Path(os.environ.get('MN10300_BIN', Path.home() / 'ep7fw-toolchains/mn10300/bin'))

TABLE, TABLE_SIZE, GAINS = 0x608ee360, 3028, 0x60900230
BUILDER, SELECTOR, SELECTOR_END = 0x6079e9e2, 0x6079ebcc, 0x6079ecbf
HOOK, RESUME, CALLBACK = 0x6079ec53, 0x6079ec58, 0x607504f6
REQ_IN_JOB, RECORDS_IN_JOB, REC_STRIDE, N_REC = 10440, 13640, 56, 16
JOB_SIZE = 14552
SAT_IN_REQ = 1813
OUT_RECORDS, OUT_CONTROL = 688, 976
STUB_AT = 0x1c000000       # synthetic emulator address; a real code-space home is separate work

# Synthetic RAM (not camera addresses)
CALLER, STACK, SAT = 0x18000000, 0x18010000, 0x10000000
OUTPUT, CONTEXT, JOB = 0x19000000, 0x1a000000, 0x1b000000

STUB_SRC = r"""
 .am33_2
 .text
 .global _start
_start:
 call epl9_builder,[d2,d3,a2,a3],96 /* displaced stock instruction (PC-relative, resolved by ld) */
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
 clr d2
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
 movbu (a0),d0                     /* H (signed byte), test scale: H*1023 */
 extb d0
 mov d0,d1
 asl 10,d0
 sub d1,d0
 movhu d0,(a3)
 movbu (12,a0),d0                  /* L (signed byte), test scale: L*50 = 64L - 14L */
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
 sub d1,d0
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
 jmp epl9_resume
"""


def main_image():
    d = MAIN.read_bytes()
    assert hashlib.sha256(d).hexdigest() == MAIN_SHA, 'unexpected E-PL9 main'
    return d


def code(d, lo, hi):
    return d[lo - BASE:hi - BASE]


def data(d, lo, n):
    return d[lo - BASE:lo - BASE + n]


def stock_table(d):
    return bytearray(data(d, TABLE, TABLE_SIZE))


def gain_regions(d):
    regs = [Region('gain_ptrs', GAINS, data(d, GAINS, 48), 'r')]
    for p in sorted(set(struct.unpack('<12I', data(d, GAINS, 48)))):
        regs.append(Region(f'gain_{p:x}', p, data(d, p, 4), 'r'))
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


def control(out):
    return struct.unpack_from('<I', out, OUT_CONTROL)[0]


def check_builder(d):
    table = stock_table(d)
    struct.pack_into('<h', table, 28 * 3 + 12, 1234)   # record 3 hue
    struct.pack_into('<h', table, 28 * 7 + 16, -321)   # record 7 lightness
    regions = [caller(BUILDER, 0xf0, 96), Region('builder', BUILDER, code(d, BUILDER, SELECTOR), 'rx'),
               Region('stack', STACK, bytes(0x2000), 'rw'), Region('table', TABLE, bytes(table)),
               Region('sat', SAT, bytes(12)), Region('out', OUTPUT, bytes(5212), 'rw', True)] + gain_regions(d)
    r, mem = run(regions, {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': TABLE, 'a1': SAT, 'd1': OUTPUT,
                           'd0': struct.unpack_from('<H', table, 3024)[0]}, CALLER + 7)
    recs = records(mem['out'])
    ok = r['registers']['pc'] == CALLER + 7 and r['registers']['sp'] == STACK + 0x1800
    ok &= recs[3]['hue'] == 1234 and recs[7]['light'] == -321
    ok &= all(recs[i]['hue'] == struct.unpack_from('<h', table, 28 * i + 12)[0] for i in range(12))
    ok &= control(mem['out']) == 0xfff
    return dict(check='A native builder', passed=bool(ok), status=r['status'], instructions=r['completed'],
                fault=r['fault'], records=recs, control=hex(control(mem['out'])))


def assemble_stub():
    src = STUB_SRC.format(callback=hex(CALLBACK), rec_off=RECORDS_IN_JOB - REQ_IN_JOB, n_rec=N_REC,
                          stride=REC_STRIDE, req_in_job=REQ_IN_JOB, hue_off=OUT_RECORDS + 18, trailer=JOB_SIZE)
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 's.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 's.o', t / 's.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(STUB_AT), '-e', '_start', f'--defsym=epl9_builder={BUILDER:#x}',
                        f'--defsym=epl9_resume={RESUME:#x}', '-o', t / 's.elf', t / 's.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 's.elf', t / 's.bin'], check=True)
        return (t / 's.bin').read_bytes()


def selector_fixture(d, sat, h, l, *, hook=None, callback=CALLBACK, record_index=5, foreign_parent=False,
                     mode=11, f00d=False, table=None):
    job = bytearray(JOB_SIZE + 24)
    req = REQ_IN_JOB
    rec = RECORDS_IN_JOB + REC_STRIDE * record_index
    struct.pack_into('<I', job, req + 0, callback)
    struct.pack_into('<I', job, req + 4, JOB + rec)
    struct.pack_into('<I', job, rec, JOB + (64 if foreign_parent else 0))
    job[req + 8:req + 12] = bytes([(mode >> 24) & 0xff, (mode >> 16) & 0xff]) + struct.pack('<H', mode & 0xffff)
    struct.pack_into('<H', job, req + 12, 0xf00d if f00d else 0)
    struct.pack_into('<I', job, req + 1524, 0)
    job[req + SAT_IN_REQ:req + SAT_IN_REQ + 12] = struct.pack('<12b', *sat)
    job[JOB_SIZE:JOB_SIZE + 12] = struct.pack('<12b', *h)
    job[JOB_SIZE + 12:JOB_SIZE + 24] = struct.pack('<12b', *l)
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, JOB + req)
    struct.pack_into('<I', ctx, 12, OUTPUT)
    struct.pack_into('<I', ctx, 56, 0)
    struct.pack_into('<I', ctx, 60, 0)
    text = bytearray(code(d, BUILDER, SELECTOR_END))
    tbl = bytes(table if table is not None else stock_table(d))
    regions = [caller(SELECTOR, 0xf0, 20), Region('stack', STACK, bytes(0x2000), 'rw'),
               Region('table', TABLE, tbl),
               Region('job', JOB, bytes(job), 'rw', True), Region('ctx', CONTEXT, bytes(ctx), 'rw', True),
               Region('out', OUTPUT, bytes(5212), 'rw', True)] + gain_regions(d)
    if hook is not None:
        text[HOOK - BUILDER:HOOK - BUILDER + 5] = b'\xdc' + struct.pack('<i', STUB_AT - HOOK)   # jmp d32 (5 bytes)
        regions.append(Region('stub', STUB_AT, hook, 'rx'))
    regions.append(Region('code', BUILDER, bytes(text), 'rx'))
    regs = {'pc': CALLER, 'sp': STACK + 0x1800, 'a0': CONTEXT, 'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}
    r, mem = run(regions, regs, CALLER + 7)
    rr = r['registers']
    callee_saved = rr['d2'] == 0x2222 and rr['d3'] == 0x3333 and rr['a2'] == 0xa2a2 and rr['a3'] == 0xa3a3
    return r, mem, dict(returned=rr['pc'] == CALLER + 7, stack_ok=rr['sp'] == STACK + 0x1800,
                        callee_saved_ok=callee_saved, instructions=r['completed'], status=r['status'],
                        fault=r['fault'])


def clean(s):
    return all(s[k] for k in ('returned', 'stack_ok', 'callee_saved_ok'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    d = main_image()
    results = [check_builder(d)]
    sat = [3, -2, 0, 1, 0, 0, -5, 0, 2, 0, 0, 4]
    h = [1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -7]
    l = [7, 6, 5, 4, 3, 2, 1, 0, -1, -2, -3, -4]

    # B: stock selector, mode 11
    r0, m0, s0 = selector_fixture(d, sat, h, l)
    base = records(m0['out'])
    reached = control(m0['out']) == 0xfff
    results.append(dict(check='B native selector (stock code, mode 11)', passed=clean(s0) and reached,
                        builder_reached=reached, **s0, records=base))

    # C: hook stub
    stub = assemble_stub()
    r1, m1, s1 = selector_fixture(d, sat, h, l, hook=stub)
    got = records(m1['out'])
    exp_ok = True
    for rnum in range(12):
        w = 2 * (rnum % 6) + rnum // 6
        exp_ok &= got[rnum]['hue'] == h[w] * 1023 and got[rnum]['light'] == l[w] * 50
        exp_ok &= got[rnum]['sat'] == base[rnum]['sat']
    ctx_same = m1['ctx'] == m0['ctx']
    results.append(dict(check='C selector + hook (emulator RAM only)', stub_bytes=len(stub), stub_at=hex(STUB_AT),
                        passed=bool(exp_ok and ctx_same and clean(s1)), context_unchanged_vs_stock=ctx_same,
                        **s1, records=got))
    for name, kw in (('C- wrong callback', dict(callback=CALLBACK + 1)), ('C- foreign parent', dict(foreign_parent=True))):
        r2, m2, s2 = selector_fixture(d, sat, h, l, hook=stub, **kw)
        same = records(m2['out']) == base
        results.append(dict(check=name, passed=bool(same and s2['returned'] and s2['stack_ok']), output_equals_stock=same, **s2))
    for i in (0, 15):
        r3, m3, s3 = selector_fixture(d, sat, h, l, hook=stub, record_index=i)
        results.append(dict(check=f'C record index {i}', passed=bool(records(m3['out']) == got and s3['returned']), **s3))

    # D: gate
    reach = {}
    for mode in list(range(0, 20)) + [0x0100000b, 0x0001000b]:
        r4, m4, s4 = selector_fixture(d, sat, h, l, mode=mode)
        reach[hex(mode)] = dict(reached=control(m4['out']) == 0xfff, clean=clean(s4))
    r5, m5, s5 = selector_fixture(d, sat, h, l, f00d=True)
    only11 = [k for k, v in reach.items() if v['reached']] == ['0xb'] and all(v['clean'] for v in reach.values())
    f00d_skips = control(m5['out']) != 0xfff and s5['returned']
    results.append(dict(check='D gate: only mode word 11 reaches the builder; 0xf00d bypass skips it',
                        passed=bool(only11 and f00d_skips), modes=reach, f00d_reached=not f00d_skips,
                        instructions=s0['instructions'], status=s0['status']))

    # E: runtime-table edit through the stock selector
    t = stock_table(d)
    edits = {2: (12, 900), 5: (16, -400), 9: (14, 77)}                 # record: (field offset, value)
    for rnum, (off, v) in edits.items():
        struct.pack_into('<h', t, 28 * rnum + off, v)
    r6, m6, s6 = selector_fixture(d, sat, h, l, table=t)
    ed = records(m6['out'])
    changed = [i for i in range(12) if ed[i] != base[i]]
    # table +12 (hue) and +16 (lightness) pass through; +14 does not reach output saturation, which is
    # computed from the request's saturation bytes and the gains (so record 9 must stay stock)
    ok = clean(s6) and ed[2]['hue'] == 900 and ed[5]['light'] == -400 and changed == [2, 5]
    results.append(dict(check='E stock selector, edited runtime table 0x608ee360: H and L reach output, table +14 does not',
                        passed=bool(ok),
                        changed_records=changed, records=ed, table_sat_fields=[struct.unpack_from('<h', t, 28 * i + 14)[0] for i in range(12)],
                        instructions=s6['instructions'], status=s6['status']))

    for x in results:
        print(f"{'PASS' if x['passed'] else 'FAIL'}  {x['check']}  ({x.get('instructions')} insns, status={x.get('status')})")
    print('records (stock selector, mode 11):', [(r['hue'], r['sat'], r['light']) for r in base])
    print('E edited records:', [(r['hue'], r['sat'], r['light']) for r in ed], 'changed', changed)
    if a.json:
        a.json.write_text(json.dumps(dict(main_sha256=MAIN_SHA, scope='Emulator-only; synthetic RAM fixtures; '
                                          'no ISP/pixel/camera behaviour; stub never packaged', results=results), indent=1, default=str))
    sys.exit(0 if all(x['passed'] for x in results) else 1)


if __name__ == '__main__':
    main()
