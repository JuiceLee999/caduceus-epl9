#!/usr/bin/env python3
"""Verify the E-PL9 look patch (patches/epl9_look) offline: static checks + emulator runs of patched vs stock code.

  python3 -I tools/epl9_look_verify.py [--spec generated/epl9_look/edits.json] [--json out.json]

Run under Linux/WSL (needs the strict MN103 engine and mn10300 binutils). Nothing here writes firmware files.

Checks
  S1  every edit's `expect` equals the stock bytes; no overlaps; the patched image differs only inside the edits
  S2  the stub lies inside the section-2 FF tail with FF guards before and after; the hook is a jmp d32 to it
  S3  store audit: the stub's only stores are its 16-B stack frame and (a0)/(4,a0) in the record loop
  C1  patched selector, mode 11: returns cleanly; d2/d3/a2/a3 preserved; context identical to stock;
      hue/light of all 12 records = the spec's native values; saturation = the stock builder's result for the
      look's saturation bytes
  C2  patched selector, modes 0..19 except 11, and the 0xf00d bypass: output, context and registers byte-identical
      to stock
  T1  capture-population fragment 0x60693ce6..0x60693d3c with a fake property getter: picture modes 1..5, 7..9,
      100, 124 byte-identical to stock; Custom (6, any base 1..5) -> capture byte 11 and the COLOR profile number
      read into capture+22985 (the stock mode-11 path)
  T2  slot-fill fragment 0x606955e4..0x6069561f: the same modes identical; Custom -> slot mode byte 11, slot
      byte 1 untouched
"""
import argparse, hashlib, json, os, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import epl9_color_probe as P  # noqa: E402  (constants, fixtures and the emulator wrapper)
from penf_emulator import Region  # noqa: E402

BASE = P.BASE
TC = Path(os.environ.get('MN10300_BIN', Path.home() / 'ep7fw-toolchains/mn10300/bin'))
STUB_AT, TAIL_FROM, TAIL_END = 0x6092c6b0, 0x6092c6a8, 0x6092c800
GETTER = 0x6043e62b
CAP, ANS = 0x1d000000, 0x1e000000
KEY_PM, KEY_BASE, KEY_PROF = 38017, 40209, 63153

FAKE_GETTER = r"""
 .am33_2
 .text
 .global _start
_start:
 mov {ans},a1
 cmp {k_pm},d0
 bne g1
 mov (0,a1),d0
 ret [d2,d3],12
g1:
 cmp {k_base},d0
 bne g2
 mov (4,a1),d0
 ret [d2,d3],12
g2:
 cmp {k_prof},d0
 bne g3
 mov (8,a1),d0
 ret [d2,d3],12
g3:
 mov (12,a1),d0
 ret [d2,d3],12
"""


def tool(name):
    return str(TC / f'mn10300-elf-{name}')


def assemble(src, at):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 's.s').write_text(src)
        subprocess.run([tool('as'), '-o', t / 's.o', t / 's.s'], check=True)
        subprocess.run([tool('ld'), '-Ttext', hex(at), '-e', '_start', '-o', t / 's.elf', t / 's.o'], check=True)
        subprocess.run([tool('objcopy'), '-O', 'binary', '-j', '.text', t / 's.elf', t / 's.bin'], check=True)
        return (t / 's.bin').read_bytes()


def disasm(blob, at):
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / 'b.bin'
        p.write_bytes(blob)
        out = subprocess.run([tool('objdump'), '-b', 'binary', '-m', 'am33-2', '-D', f'--adjust-vma={at:#x}', p],
                             check=True, capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split('\t')
        if len(parts) >= 3 and parts[0].strip().endswith(':'):
            rows.append((int(parts[0].strip()[:-1], 16), parts[2].strip() + (' ' + parts[3].strip() if len(parts) > 3 else '')))
    return rows


def apply(stock, spec):
    img = bytearray(stock)
    spans = []
    for e in spec['edits']:
        a = int(e['addr'], 16) - BASE
        old, new = bytes.fromhex(e['expect']), bytes.fromhex(e['new'])
        assert len(old) == len(new) and stock[a:a + len(old)] == old, e['addr']
        img[a:a + len(new)] = new
        spans.append((a, a + len(new)))
    return bytes(img), sorted(spans)


# ---------------------------------------------------------------- static

def static_checks(stock, img, spans, spec, syms):
    res = []
    overl = any(b[0] < a[1] for a, b in zip(spans, spans[1:]))
    # every changed byte must lie inside an edit: count both ways
    diff =sum(1 for lo, hi in spans for i in range(lo, hi) if stock[i] != img[i])
    whole = sum(1 for x, y in zip(stock, img) if x != y)
    res.append(dict(check='S1 edits match stock, no overlap, no change outside edits', passed=not overl and diff == whole,
                    edits=len(spans), changed_bytes=whole))
    stub = [e for e in spec['edits'] if int(e['addr'], 16) == STUB_AT][0]
    n = len(stub['new']) // 2
    end = STUB_AT + n
    guard_lo = img[TAIL_FROM - BASE:STUB_AT - BASE] == b'\xff' * (STUB_AT - TAIL_FROM)
    guard_hi = img[end - BASE:TAIL_END - BASE] == b'\xff' * (TAIL_END - end) and TAIL_END - end >= 16
    hook = [e for e in spec['edits'] if int(e['addr'], 16) == P.HOOK][0]
    hb = bytes.fromhex(hook['new'])
    hook_ok = hb[0] == 0xdc and P.HOOK + struct.unpack_from('<i', hb, 1)[0] == STUB_AT
    res.append(dict(check='S2 stub inside the sec-2 FF tail with guards; hook = jmp d32 to it',
                    passed=bool(guard_lo and guard_hi and hook_ok), stub=f'{STUB_AT:#x}..{end:#x}', free_after=TAIL_END - end))
    code_end = int(syms['look_sat'], 16)
    rows = disasm(img[STUB_AT - BASE:code_end - BASE], STUB_AT)
    stores = [(hex(a), t) for a, t in rows if t.split(' ', 1)[0].startswith(('mov', 'movhu', 'movbu'))
              and ',(' in t and not t.split(' ', 1)[1].startswith('(')]
    allowed = {'mov d0,(sp)', 'mov d1,(4,sp)', 'mov a0,(8,sp)', 'mov a1,(12,sp)', 'movhu d0,(a0)', 'movhu d0,(4,a0)'}
    norm = lambda t: t.replace('\t', ' ').replace('(0,sp)', '(sp)')
    bad = [s for s in stores if norm(s[1]) not in allowed]
    res.append(dict(check='S3 stub store audit', passed=not bad and len(stores) == 6, stores=stores, unexpected=bad))
    return res


# ---------------------------------------------------------------- colour hook

def selector(img, sat, h, l, *, mode=11, f00d=False):
    stock = img is None
    src = P.main_image() if stock else img
    job = bytearray(P.JOB_SIZE + 24)
    req, rec = P.REQ_IN_JOB, P.RECORDS_IN_JOB + P.REC_STRIDE * 5
    struct.pack_into('<I', job, req, P.CALLBACK)
    struct.pack_into('<I', job, req + 4, P.JOB + rec)
    struct.pack_into('<I', job, rec, P.JOB)
    job[req + 8:req + 12] = bytes([(mode >> 24) & 0xff, (mode >> 16) & 0xff]) + struct.pack('<H', mode & 0xffff)
    struct.pack_into('<H', job, req + 12, 0xf00d if f00d else 0)
    job[req + P.SAT_IN_REQ:req + P.SAT_IN_REQ + 12] = struct.pack('<12b', *sat)
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, P.JOB + req)
    struct.pack_into('<I', ctx, 12, P.OUTPUT)
    regions = [P.caller(P.SELECTOR, 0xf0, 20), Region('stack', P.STACK, bytes(0x2000), 'rw'),
               Region('table', P.TABLE, bytes(P.stock_table(src))),
               Region('job', P.JOB, bytes(job), 'rw', True), Region('ctx', P.CONTEXT, bytes(ctx), 'rw', True),
               Region('out', P.OUTPUT, bytes(5212), 'rw', True),
               Region('code', P.BUILDER, src[P.BUILDER - BASE:P.SELECTOR_END - BASE], 'rx')] + P.gain_regions(src)
    if not stock:
        regions.append(Region('stub', STUB_AT, img[STUB_AT - BASE:TAIL_END - BASE], 'rx'))
    regs = {'pc': P.CALLER, 'sp': P.STACK + 0x1800, 'a0': P.CONTEXT, 'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}
    r, mem = P.run(regions, regs, P.CALLER + 7)
    rr = r['registers']
    ok = (rr['pc'] == P.CALLER + 7 and rr['sp'] == P.STACK + 0x1800 and
          (rr['d2'], rr['d3'], rr['a2'], rr['a3']) == (0x2222, 0x3333, 0xa2a2, 0xa3a3) and not r['fault'])
    return r, mem, ok


def builder_sat(stock, look_sat):
    """Saturation the stock builder computes for the look's bytes (native selector, request carries them)."""
    r, mem, ok = selector(None, look_sat, [0] * 12, [0] * 12)
    return [x['sat'] for x in P.records(mem['out'])], ok


def colour_checks(stock, img, spec):
    res = []
    look = spec['look_values']
    want = spec['native_records']
    sat_want, ok_ref = builder_sat(stock, look['sat'])
    user_sat = [1, -2, 0, 4, -1, 0, 2, 0, -3, 5, 0, -5]      # whatever the request carries must not matter
    r0, m0, ok0 = selector(None, user_sat, [0] * 12, [0] * 12)
    r1, m1, ok1 = selector(img, user_sat, [0] * 12, [0] * 12)
    got = P.records(m1['out'])
    vals_ok = all(got[i]['hue'] == want[i]['hue'] and got[i]['light'] == want[i]['light'] and got[i]['sat'] == sat_want[i]
                  for i in range(12))
    ctx_same = m1['ctx'] == m0['ctx']
    ctl = P.control(m1['out']) == P.control(m0['out']) == 0xfff
    res.append(dict(check='C1 patched selector, mode 11: look values in all 12 records, clean return, context as stock',
                    passed=bool(ok_ref and ok0 and ok1 and vals_ok and ctx_same and ctl),
                    instructions=(r0['completed'], r1['completed']), records=got, sat_expected=sat_want))
    bad = []
    for mode in [m for m in range(20) if m != 11] + ['f00d']:
        kw = dict(f00d=True) if mode == 'f00d' else dict(mode=mode)
        a_r, a_m, a_ok = selector(None, user_sat, [0] * 12, [0] * 12, **kw)
        b_r, b_m, b_ok = selector(img, user_sat, [0] * 12, [0] * 12, **kw)
        same = (a_m == b_m and a_r['registers'] == b_r['registers'] and a_r['completed'] == b_r['completed'] and a_ok and b_ok)
        if not same:
            bad.append(mode)
    res.append(dict(check='C2 patched selector, modes != 11 and 0xf00d: byte-identical to stock', passed=not bad, differing=bad))
    return res


# ---------------------------------------------------------------- trigger fragments

def fragment(img, start, stop, regs_extra, pm, base, prof=3, other=0):
    getter = assemble(FAKE_GETTER.format(ans=hex(ANS), k_pm=KEY_PM, k_base=KEY_BASE, k_prof=KEY_PROF), GETTER)
    lo, hi = start - 0x40, stop + 0x40
    regions = [Region('code', lo, img[lo - BASE:hi - BASE], 'rx'), Region('getter', GETTER, getter, 'rx'),
               Region('stack', P.STACK, bytes(0x2000), 'rw', True),
               Region('cap', CAP, b'\xaa' * 0x6000, 'rw', True),
               Region('ans', ANS, struct.pack('<4I', pm, base, prof, other), 'r')]
    regs = dict({'pc': start, 'sp': P.STACK + 0x1800}, **regs_extra)
    r = P.execute(regions, regs, stop, limit=5000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return r, mem


def trigger_checks(stock, img):
    res = []
    cases = [(pm, 1) for pm in (1, 2, 3, 4, 5, 7, 8, 9, 100, 124)] + [(6, b) for b in (1, 2, 3, 4, 5)]
    # T1: capture population, d3 = capture base
    bad, custom = [], []
    for pm, b in cases:
        rs, ms = fragment(stock, 0x60693ce6, 0x60693d3c, {'d3': CAP}, pm, b)
        rp, mp = fragment(img, 0x60693ce6, 0x60693d3c, {'d3': CAP}, pm, b)
        okrun = rs['registers']['pc'] == rp['registers']['pc'] == 0x60693d3c and not rs['fault'] and not rp['fault']
        if pm != 6:
            if not (okrun and ms['cap'] == mp['cap']):
                bad.append(pm)
        else:
            s_mode, p_mode = ms['cap'][22955], mp['cap'][22955]
            p_prof = mp['cap'][22985]
            custom.append(dict(base=b, stock_mode=s_mode, patched_mode=p_mode, patched_profile=p_prof))
            if not (okrun and s_mode == b and p_mode == 11 and p_prof == 3):
                bad.append(f'6/{b}')
    res.append(dict(check='T1 capture population: other modes identical, Custom -> 11 + profile read', passed=not bad,
                    differing=bad, custom=custom))
    # T2: slot fill, a3 = capture base
    bad, custom = [], []
    for pm, b in cases:
        rs, ms = fragment(stock, 0x606955e4, 0x6069561f, {'a3': CAP}, pm, b)
        rp, mp = fragment(img, 0x606955e4, 0x6069561f, {'a3': CAP}, pm, b)
        okrun = rs['registers']['pc'] == rp['registers']['pc'] == 0x6069561f and not rs['fault'] and not rp['fault']
        if pm != 6:
            if not (okrun and ms['cap'] == mp['cap']):
                bad.append(pm)
        else:
            slot_s, slot_p = ms['cap'][23714:23716], mp['cap'][23714:23716]
            custom.append(dict(base=b, stock_slot=slot_s.hex(), patched_slot=slot_p.hex()))
            if not (okrun and slot_s == bytes([6, b]) and slot_p == bytes([11, 0xaa])):
                bad.append(f'6/{b}')
    res.append(dict(check='T2 slot fill: other modes identical, Custom -> slot mode 11', passed=not bad,
                    differing=bad, custom=custom))
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--spec', type=Path, default=ROOT / 'generated/epl9_look/edits.json')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.spec.read_text())
    syms = json.loads((a.spec.parent / 'symbols.json').read_text())
    stock = P.main_image()
    assert spec['main_sha256'] == P.MAIN_SHA and int(spec['main_base'], 16) == BASE
    img, spans = apply(stock, spec)
    results = static_checks(stock, img, spans, spec, syms) + colour_checks(stock, img, spec) + trigger_checks(stock, img)
    for x in results:
        print(f"{'PASS' if x['passed'] else 'FAIL'}  {x['check']}")
        for k in ('differing', 'unexpected', 'custom', 'stub', 'free_after', 'changed_bytes'):
            if x.get(k):
                print(f'      {k}: {x[k]}')
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.spec), patched_sha256=hashlib.sha256(img).hexdigest(),
                                          results=results), indent=1, default=str))
    sys.exit(0 if all(x['passed'] for x in results) else 1)


if __name__ == '__main__':
    main()
