#!/usr/bin/env python3
"""Emulator verification of a BUILT fixed-H/L package (the exact bytes that would ship).

Builds the package in memory from an edits.json via tools/build_package.build(), decodes the
patched main payload, and runs the native COLOR selector from the PATCHED image (hook + routine
taken from the package itself) against the same synthetic job run on STOCK code.

Passes only if: hue/light of all 12 output records == recipe native rows; saturation, control
word and every other output byte == stock run; selector returns to caller with stack and
callee-saved registers intact; context unchanged; no fault. Offline; emulator only.
"""
import argparse, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
import ep7_color_probe as PR  # noqa: E402
from penf_emulator import Region  # noqa: E402

BASE = 0x60020020


def selector_run(main, sat):
    """Run selector 0x603b0252 from `main` (decoded payload) with a valid COLOR job."""
    job = bytearray(PR.JOB_SIZE + 24)
    req, rec = PR.REQ_IN_JOB, PR.RECORDS_IN_JOB + PR.REC_STRIDE * 5
    struct.pack_into('<I', job, req, PR.CALLBACK)
    struct.pack_into('<I', job, req + 4, PR.JOB + rec)
    struct.pack_into('<I', job, rec, PR.JOB)
    job[req + 8:req + 12] = bytes([0, 0, 11, 0])
    job[req + 1816:req + 1828] = struct.pack('<12b', *sat)
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, PR.JOB + req)
    struct.pack_into('<I', ctx, 12, PR.OUTPUT)
    code = main[PR.BUILDER - BASE:PR.SELECTOR_END - BASE]
    tail = main[0x6055e5b0 - BASE:0x6055e800 - BASE]
    regions = [PR.caller(PR.SELECTOR, 0xf0, 20), Region('stack', PR.STACK, bytes(0x2000), 'rw'),
               Region('table', PR.TABLE, main[PR.TABLE - BASE:PR.TABLE - BASE + PR.TABLE_SIZE]),
               Region('job', PR.JOB, bytes(job), 'rw', True), Region('ctx', PR.CONTEXT, bytes(ctx), 'rw', True),
               Region('out', PR.OUTPUT, bytes(5212), 'rw', True), Region('code', PR.BUILDER, code, 'rx'),
               Region('tail', 0x6055e5b0, tail, 'rx')]
    regions += PR.gain_regions(main)
    regs = {'pc': PR.CALLER, 'sp': PR.STACK + 0x1800, 'a0': PR.CONTEXT,
            'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}
    r, mem = PR.run(regions, regs, PR.CALLER + 7)
    rr = r['registers']
    ok = (rr['pc'] == PR.CALLER + 7 and rr['sp'] == PR.STACK + 0x1800 and not r['fault'] and
          (rr['d2'], rr['d3'], rr['a2'], rr['a3']) == (0x2222, 0x3333, 0xa2a2, 0xa3a3))
    return ok, mem, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('edits', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    stock_bytes = BP.STOCK.read_bytes()
    pkg, restore, info = BP.build(spec, stock_bytes)
    patched = oc.parse(pkg)[0].payload
    stock = oc.parse(restore)[0].payload
    # changed bytes are exactly the edit spans
    import numpy as np
    sa, pa = np.frombuffer(stock, np.uint8), np.frombuffer(patched, np.uint8)
    idx = np.nonzero(sa != pa)[0] + BASE
    spans = [(int(e['addr'], 16), int(e['addr'], 16) + len(bytes.fromhex(e['new']))) for e in spec['edits']]
    in_spans = all(any(s <= x < t for s, t in spans) for x in idx)
    results = []
    for sat in ([0] * 12, [3, -2, 0, 1, 0, 0, -5, 0, 2, 0, 0, 4], [5] * 12, [-5] * 12):
        ok_s, m_s, _ = selector_run(stock, sat)
        ok_p, m_p, r_p = selector_run(patched, sat)
        rs, rp = PR.records(m_s['out']), PR.records(m_p['out'])
        exp = spec['native_rows']
        hl_ok = all(rp[i]['hue'] == exp[i][0] and rp[i]['light'] == exp[i][1] for i in range(12))
        sat_ok = all(rp[i]['sat'] == rs[i]['sat'] for i in range(12))
        o_s, o_p = bytearray(m_s['out']), bytearray(m_p['out'])
        for i in range(12):   # mask hue/light fields; everything else must match stock
            for off in (18, 22):
                p = PR.OUT_RECORDS + 24 * i + off
                o_s[p:p + 2] = o_p[p:p + 2] = b'\0\0'
        rest_ok = o_s == o_p
        ctx_ok = m_s['ctx'] == m_p['ctx']
        passed = ok_s and ok_p and hl_ok and sat_ok and rest_ok and ctx_ok
        results.append(passed)
        print(f"{'PASS' if passed else 'FAIL'} sat={sat}: returned/stack/regs={ok_p} H/L={hl_ok} "
              f"sat==stock={sat_ok} other-bytes==stock={rest_ok} ctx==stock={ctx_ok} insns={r_p['completed']}")
    print(f"{'PASS' if in_spans else 'FAIL'} changed bytes ({len(idx)}) all inside edit spans; package {info}")
    sys.exit(0 if all(results) and in_spans else 1)


if __name__ == '__main__':
    main()
