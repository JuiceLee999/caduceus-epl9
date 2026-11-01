#!/usr/bin/env python3
"""Emulator verification of a BUILT aperture-ring package (offline; emulator only; no camera).

Takes an edits spec containing the aperture-ring patch (patches/aperture_ring/build.py), alone or merged
(tools/merge_specs.py). Builds the package in memory with tools/build_package.build(), decodes the patched
and restore (= stock) main payloads and runs code from THOSE payloads, stock vs patched, on the same fixture.
Only explicit synthetic RAM exists (unknown accesses fault). Nothing here models the lens bus, task
scheduling, caches or the exposure solver.

  D  dispatcher window 0x601f9df3 -> 0x601f9dfc (or the NULL exit 0x601f9e7e), every request command x
     req+12 x option byte x connection x device x capability: request bytes and registers vs stock. The
     only allowed difference is req+21 |= 0x01, exactly for C1 80 / 81 E3, req+12 == 0, no option 0x08,
     connected lens, capability bit 0x80.
  P  status-parser window 0x601f5dfb -> 0x601f5f02 (through DIS_FCENC and the LAF loop), kinds 0..5 with the
     E-P7 flag bits 0x08/0x10/0x20 and 0x621d014e states, option byte with/without 0x01 and 0x02 (LAF):
     - request without 0x01, or kinds 2/3: patched == stock on the same response (record, a3, regs, state);
     - request with 0x01, kinds 0/1/4/5: response WITH the ring word inserted after DIS_FCENC parses to the
       same record/LAF values as stock on the response without it, a3 ends 2 bytes further, and the state
       halfword equals the ring word.
  A  AE snapshot window 0x60427ae7 -> 0x60427aec with the native aperture-point wrapper + property getter:
     modes 0..7, connection, capability, state (initial 0x8000 from the image, in range, below/above limits,
     negative), limits (normal, reversed, signed): d0 == clamp(ring, min, max) only for modes 4/6 with a
     connected capable lens and a published ring; otherwise d0 and all callee-saved registers == stock.
  S  static: hook bytes, code inside its claims, state initial value.
  M  mutations of the patched payload must make D/P/A fail.

Usage: tools/ep7_verify_aperture_ring.py SPEC.json [--json out.json] [--no-mutations]
"""
import argparse, itertools, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402

BASE = 0x60020020
GETTER_CODE = (0x6005c8c0, 0x6005f010)
XLATE = (0x60078968, 0x60078978)
CPUID, REG_FLAG, REG_BASE, REG_END = 0x8050, 0xa26ffa84, 0xa26ffa88, 0xa2707a88
PROPDATA = 0x15000000
STACK, SP0, FILL = 0x18010000, 0x18011800, 0xa5
DEV, DEV_SIZE = 0x14000000, 0x600
CONN = 0xa2726b60
DEVPTR = 0xa271ca70
REQ = 0x16000000
RESP = 0x16100000
AECFG = 0x16200000
KEY_AV = 0x80ca
ALL = ['d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp']
SAVED = ['d2', 'd3', 'a2', 'a3', 'sp']


def sl(main, lo, hi):
    return bytes(main[lo - BASE:hi - BASE])


def sx16(v):
    v &= 0xffff
    return v - 0x10000 if v & 0x8000 else v


def mem(r):
    return {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}


class Ctx:
    def __init__(self, spec):
        m = spec.get('aperture_ring') or spec['meta']['aperture_ring']['aperture_ring']
        self.m = m
        g = lambda k: int(m[k], 16)  # noqa: E731
        self.disp_site, self.disp_cont, self.disp_null = 0x601f9df3, g('disp_cont'), g('disp_null')
        self.parse_site, self.ae_site, self.ae_cont, self.ae_wrap = g('parse_site'), g('ae_site'), g('ae_cont'), g('ae_wrap')
        self.dev_get, self.cap_off, self.cap_bit = g('dev_get'), g('cap_off'), g('cap_bit')
        self.av_min, self.av_max = g('av_min'), g('av_max')
        self.state, self.state_unc, self.state_init = g('state'), g('state_uncached'), g('state_init')
        self.lens_at, self.lens_len, self.ae_at, self.ae_len = g('lens_at'), m['lens_len'], g('ae_at'), m['ae_len']


def common(main, ctx, connected=1, devptr=DEV, cap=0x80, state=None, rw_state=True):
    dev = bytearray(DEV_SIZE)
    struct.pack_into('<I', dev, ctx.cap_off, cap)
    st = bytearray([FILL] * 0x2000)
    sreg = bytearray(sl(main, ctx.state & ~7, (ctx.state & ~7) + 8))
    struct.pack_into('<H', sreg, ctx.state & 7, (ctx.state_init if state is None else state) & 0xffff)
    return [Region('devget', 0x601f2724, sl(main, 0x601f2724, 0x601f27a0), 'rx'),
            Region('conn_fn', 0x600f773e, sl(main, 0x600f773e, 0x600f7770), 'rx'),
            Region('conn', CONN, bytes([connected, 0, connected, 0, 0, 0, 0, 0])),
            Region('devptr', DEVPTR, struct.pack('<II', devptr, 0)),
            Region('dev', DEV, bytes(dev), 'rw', True),
            Region('state', ctx.state_unc & ~7, bytes(sreg), 'rw' if rw_state else 'r', True),
            Region('stack', STACK, bytes(st), 'rw', True)]


def hookcode(main, ctx):
    return [Region('lens_code', 0x60210f00, sl(main, 0x60210f00, 0x60211000), 'rx'),
            Region('ae_code', 0x61378f00, sl(main, 0x61378f00, 0x61379000), 'rx')]


# ------------------------------------------------------------------ D: dispatcher
CMDS = [(0xc1, 0x80), (0x81, 0xe3), (0xc1, 0x00), (0xc1, 0x12), (0x81, 0xf1), (0xc3, 0xf0), (0x60, 0x80), (0xa0, 0x80),
        (0x80, 0xc1), (0xe3, 0x81)]


def disp_run(main, ctx, req, null=False, **kw):
    regs = common(main, ctx, **kw) + hookcode(main, ctx) + [
        Region('disp', 0x601f9d00, sl(main, 0x601f9d00, 0x601f9f00), 'rx')]
    a0 = 0 if null else REQ
    if not null:
        regs.append(Region('req', REQ, bytes(req), 'rw', True))
    r = execute(regs, {'pc': ctx.disp_site, 'sp': SP0, 'a0': a0, 'd0': 0xd0d0, 'd1': 0xd1d1, 'd2': 0x2222, 'd3': 0x3333,
                       'a1': 0xa1a1, 'a2': 0xa2a2, 'a3': 0xa3a3},
                ctx.disp_null if null else ctx.disp_cont, limit=5000)
    m = mem(r)
    return dict(fault=r['fault'], pc=r['registers']['pc'], regs={k: r['registers'][k] for k in ALL},
                req=m.get('req'), state=m['state'], dev=m['dev'], stack=m['stack'][0x1800:])


def check_dispatch(ctx, stock, patched, out):
    n = bad = 0
    for (c1, c2), r12, opt21, conn, devp, cap in itertools.product(CMDS, (0, 1), (0x00, 0x02, 0x06, 0x08, 0x0a, 0x01),
                                                               (1, 0), (DEV, 0), (0x80, 0x7f, 0xffffffff, 0)):
        req = bytearray(64)
        struct.pack_into('<H', req, 12, r12)
        req[18], req[19], req[20], req[21] = c1, c2, 0x5a, opt21
        kw = dict(connected=conn, devptr=devp, cap=cap)
        s, p = disp_run(stock, ctx, req, **kw), disp_run(patched, ctx, req, **kw)
        want = bytearray(req)
        on = ((c1, c2) in ((0xc1, 0x80), (0x81, 0xe3)) and r12 == 0 and not opt21 & 8 and conn == 1 and devp
              and cap & 0x80)
        if on:
            want[21] |= 1
        ok = (not s['fault'] and not p['fault'] and s['pc'] == p['pc'] == ctx.disp_cont and s['req'] == bytes(req)
              and p['req'] == bytes(want) and p['state'] == s['state'] and p['dev'] == s['dev']
              and all(p['regs'][k] == s['regs'][k] for k in ('d2', 'd3', 'a2', 'a3', 'sp'))
              and p['stack'][4:] == s['stack'][4:])
        n += 1
        if not ok:
            bad += 1
            if bad <= 5:
                out.append(f'D FAIL cmd {c1:02x} {c2:02x} r12 {r12} opt {opt21:02x} conn {conn} dev {devp:#x} cap {cap:#x}: '
                           f'stock {s["fault"]} {s["pc"]:#x} patched {p["fault"]} {p["pc"]:#x} req {p["req"].hex() if p["req"] else None}')
    # NULL request
    s, p = disp_run(stock, ctx, None, null=True), disp_run(patched, ctx, None, null=True)
    n += 1
    if s['fault'] or p['fault'] or p['pc'] != ctx.disp_null or any(p['regs'][k] != s['regs'][k] for k in ALL):
        bad += 1
        out.append('D FAIL NULL request path')
    return n, bad


# ------------------------------------------------------------------ P: status parser
PARSER, PARSE_STOP = 0x601f5dfb, 0x601f5f02


def response(ring=None, laf=True, apa=0x0234):
    b = bytearray()
    b += struct.pack('<I', 0x11223344)          # status word
    b += bytes([0x55, 0x66])                    # ZMENC, FCENC
    b += struct.pack('<H', 0x0789)              # OBJdst
    b += struct.pack('<H', apa)                 # APACT
    b += bytes([0x9a, 0xbc])                    # DIS_ZMENC, DIS_FCENC
    if ring is not None:
        b += struct.pack('<H', ring)
    if laf:
        for i in range(8):
            b += struct.pack('<H', 0x1000 + 0x111 * i)
    b += bytes(range(0xe0, 0xf0))               # whatever follows
    return bytes(b)


def parse_run(main, ctx, resp, kind, opt20, opt21, flag14e=0, **kw):
    alt = bytearray(0x40)
    regs = common(main, ctx, **kw) + hookcode(main, ctx) + [
        Region('parser', 0x601f5d00, sl(main, 0x601f5d00, 0x601f6300), 'rx'),
        Region('rd', 0x600fb180, sl(main, 0x600fb180, 0x600fb1d0), 'rx'),
        Region('resp', RESP, resp + bytes(64)),
        Region('alt', 0x621cfc40, bytes(alt), 'rw', True),
        Region('v14e', 0x621d0140, bytes([0] * 14 + [flag14e, 0]), 'rw', True)]
    stk = bytearray([FILL] * 0x2000)
    struct.pack_into('<I', stk, 0x1800 + 4, kind)             # caller's (4,sp) = 5th argument
    regs = [r if r.name != 'stack' else Region('stack', STACK, bytes(stk), 'rw', True) for r in regs]
    r = execute(regs, {'pc': PARSER, 'sp': SP0 - 44, 'd0': RESP, 'd1': opt20, 'a0': opt20, 'a1': opt21,
                       'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2},
                PARSE_STOP, limit=20000)
    m = mem(r)
    return dict(fault=r['fault'], pc=r['registers']['pc'], regs={k: r['registers'][k] for k in ALL}, dev=m['dev'],
                alt=m['alt'], state=m['state'], v14e=m['v14e'])


def check_parser(ctx, stock, patched, out):
    n = bad = 0
    ring_vals = [0x0187, 0x8000, 0x0600, 0xfff0]
    off = ctx.state_unc & 7
    for low, flags, opt21, f14e in itertools.product(range(6), (0x00, 0x08, 0x10, 0x20, 0x28), (0x00, 0x02, 0x01, 0x03),
                                                     (0, 2)):
        kind = low | flags
        for ring in (ring_vals if opt21 & 1 else [None]):
            want_ring = bool(opt21 & 1) and not low & 2
            resp_stock = response(None, laf=bool(opt21 & 2))
            resp_p = response(ring if want_ring else None, laf=bool(opt21 & 2))
            s = parse_run(stock, ctx, resp_stock, kind, 0, opt21, f14e)
            p = parse_run(patched, ctx, resp_p, kind, 0, opt21, f14e)
            ok = not s['fault'] and not p['fault'] and s['pc'] == p['pc'] == PARSE_STOP
            ok = ok and s['dev'] == p['dev'] and s['alt'] == p['alt'] and s['v14e'] == p['v14e']
            da3 = p['regs']['a3'] - s['regs']['a3']
            ok = ok and da3 == (2 if want_ring else 0)
            ok = ok and all(p['regs'][k] == s['regs'][k] for k in ('d2', 'd3', 'sp'))
            exp_state = (struct.pack('<H', ring) if want_ring else s['state'][off:off + 2])
            ok = ok and p['state'][off:off + 2] == exp_state and p['state'][:off] == s['state'][:off]
            if want_ring:   # stock on the ring-carrying response would misparse: proves the word is consumed
                s2 = parse_run(stock, ctx, resp_p, kind, 0, opt21, f14e)
                ok = ok and (s2['dev'] != p['dev'] or s2['alt'] != p['alt']) if opt21 & 2 else ok
            n += 1
            if not ok:
                bad += 1
                if bad <= 5:
                    out.append(f'P FAIL kind {kind:#x} opt21 {opt21:#x} 14e {f14e} ring {ring}: faults {s["fault"]} '
                               f'{p["fault"]} pcs {s["pc"]:#x} {p["pc"]:#x} da3 {da3} state {p["state"].hex()}')
    return n, bad


# ------------------------------------------------------------------ A: AE snapshot
def registry(props):
    reg = bytearray(REG_END - (REG_FLAG - 4) + 8)
    data = bytearray()
    for key, vals in props.items():
        ent = REG_BASE + 8 * (key >> 4) - (REG_FLAG - 4)
        struct.pack_into('<II', reg, ent, key, PROPDATA + len(data))
        data += vals + bytes(-len(vals) % 32 or 32)
    return [Region('registry', REG_FLAG - 4, bytes(reg)), Region('propdata', PROPDATA, bytes(data))]


def ae_run(main, ctx, body, mode, lim, **kw):
    cfg = bytearray(64)
    cfg[2] = mode
    cache = bytearray(32)
    struct.pack_into('<hhh', cache, 0x0c, 0x0123, *lim)       # 0x621cf64c eff, 64e min, 650 max
    regs = common(main, ctx, **kw) + hookcode(main, ctx) + registry({KEY_AV: struct.pack('<h', body)}) + [
        Region('snap', 0x60427a00, sl(main, 0x60427a00, 0x60427b40), 'rx'),
        Region('wrap', 0x60429500, sl(main, 0x60429500, 0x60429560), 'rx'),
        Region('getter', GETTER_CODE[0], sl(main, *GETTER_CODE), 'rx'),
        Region('xlate', XLATE[0], sl(main, *XLATE), 'rx'),
        Region('cpuid', CPUID, bytes(4)),
        Region('handle', 0x622a0a78, bytes(8)),
        Region('cache', 0x621cf640, bytes(cache)),
        Region('cfg', AECFG, bytes(cfg))]
    r = execute(regs, {'pc': ctx.ae_site, 'sp': SP0, 'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': AECFG,
                       'd0': 0xd0d0, 'd1': 0xd1d1, 'a0': 0xa0a0, 'a1': 0xa1a1}, ctx.ae_cont, limit=20000)
    m = mem(r)
    return dict(fault=r['fault'], pc=r['registers']['pc'], regs={k: r['registers'][k] for k in ALL},
                d0=sx16(r['registers']['d0']), stack=m['stack'][0x1800 - 0:], dev=m['dev'], state=m['state'])


def check_ae(ctx, stock, patched, out):
    n = bad = 0
    lims = [(0x0188, 0x0800), (0x0300, 0x0a00), (0x0800, 0x0188), (-0x0100, 0x0400)]
    states = [None, 0x8000, 0x0187, 0x0188, 0x0500, 0x0900, 0x0c00, 0xff00]
    for mode, conn, devp, cap, st, lim in itertools.product(range(8), (1, 0), (DEV, 0), (0x80, 0xff7f), states, lims):
        if (conn == 0 or devp == 0 or cap != 0x80) and (st not in (0x0500, None) or lim != lims[0] or mode not in (4, 6, 0)):
            continue   # trim the gated-off product
        body = 0x0345
        kw = dict(connected=conn, devptr=devp, cap=cap, state=st)
        s, p = ae_run(stock, ctx, body, mode, lim, **kw), ae_run(patched, ctx, body, mode, lim, **kw)
        ring = ctx.state_init if st is None else st
        on = mode in (4, 6) and conn == 1 and devp and cap & 0x80 and ring != 0x8000 and lim[0] <= lim[1]
        want = max(lim[0], min(lim[1], sx16(ring))) if on else body
        ok = (not s['fault'] and not p['fault'] and s['pc'] == p['pc'] == ctx.ae_cont and s['d0'] == body
              and p['d0'] == want and all(p['regs'][k] == s['regs'][k] for k in SAVED)
              and p['stack'][4:] == s['stack'][4:] and p['dev'] == s['dev'] and p['state'] == s['state'])  # A never writes
        n += 1
        if not ok:
            bad += 1
            if bad <= 5:
                out.append(f'A FAIL mode {mode} conn {conn} dev {devp:#x} cap {cap:#x} st {st} lim {lim}: '
                           f'stock {s["fault"]} d0 {s["d0"]:#x} patched {p["fault"]} d0 {p["d0"]:#x} want {want:#x}')
    return n, bad


# ------------------------------------------------------------------ S / M
def check_static(ctx, spec, stock, patched, out):
    bad = 0
    st = struct.unpack_from('<H', patched, ctx.state - BASE)[0]
    if st != ctx.state_init or struct.unpack_from('<H', stock, ctx.state - BASE)[0] != 0xffff:
        bad += 1
        out.append(f'S FAIL state initial {st:#x}')
    edits = [e for e in spec['edits'] if 'aperture-ring' in e['why'] or e.get('source', '').find('aperture') >= 0]
    for e in edits:
        a, new = int(e['addr'], 16), bytes.fromhex(e['new'])
        if sl(patched, a, a + len(new)) != new or sl(stock, a, a + len(new)).hex() != e['expect']:
            bad += 1
            out.append(f'S FAIL edit {e["addr"]}')
    return len(edits) + 1, bad


def mutate(img, addr, old, new):
    o = img.find(bytes.fromhex(old), addr - BASE, addr - BASE + 0x80)
    if o < 0:
        raise ValueError(f'mutation pattern {old} not found near {addr:#x}')
    m = bytearray(img)
    m[o:o + len(bytes.fromhex(new))] = bytes.fromhex(new)
    return bytes(m)


def mutations(ctx, stock, patched, out):
    L, A = ctx.lens_at, ctx.ae_at
    muts = [('D: capability bit 0x80 -> 0x40', L, 'f8ec80', 'f8ec40', 'D'),
            ('D: 81 E3 compare -> 81 E4', L, 'fac881e3', 'fac881e4', 'D'),
            ('D: IS-extra test removed', L, 'f8ed08', 'f8ed00', 'D'),
            ('P: kind bit test 2 -> 4 (PEN-F encoding)', L + 0x40, 'f8ec02', 'f8ec04', 'P'),
            ('P: ring high byte read from wrong offset', L + 0x40, 'f84701', 'f84700', 'P'),
            ('A: mode 6 -> 5', A, 'a006', 'a005', 'A'),
            ('A: upper clamp removed', A, 'c303', 'ca03', 'A'),
            ('A: A/auto sentinel ignored', A, 'fac90080', 'fac90180', 'A')]
    caught = 0
    for name, addr, old, new, which in muts:
        try:
            m = mutate(patched, addr, old, new)
        except ValueError as e:
            out.append(f'M SKIP {name}: {e}')
            continue
        tmp = []
        fn = {'D': check_dispatch, 'P': check_parser, 'A': check_ae}[which]
        _, b = fn(ctx, stock, m, tmp)
        caught += b > 0
        out.append(f'M {"caught" if b else "MISSED"}: {name} ({b} failing cases)')
    return len(muts), caught


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spec', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--no-mutations', action='store_true')
    a = ap.parse_args()
    spec = json.loads(a.spec.read_text())
    ctx = Ctx(spec)
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    out, res = [], {}
    for name, fn in [('S', lambda: check_static(ctx, spec, stock, patched, out)),
                     ('D', lambda: check_dispatch(ctx, stock, patched, out)),
                     ('P', lambda: check_parser(ctx, stock, patched, out)),
                     ('A', lambda: check_ae(ctx, stock, patched, out))]:
        n, b = fn()
        res[name] = dict(cases=n, failed=b)
        print(f'{name}: {n - b}/{n} PASS')
    ok = all(v['failed'] == 0 for v in res.values())
    if not a.no_mutations:
        n, c = mutations(ctx, stock, patched, out)
        res['M'] = dict(mutations=n, caught=c)
        print(f'M: {c}/{n} mutations caught')
        ok = ok and c == n
    for l in out:
        print('  ' + l)
    print('overall', 'PASS' if ok else 'FAIL')
    if a.json:
        a.json.write_text(json.dumps(dict(results=res, notes=out, overall=ok), indent=1) + '\n')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
