#!/usr/bin/env python3
"""Targeted emulator checks for v0.22 grain C (COLOR stills on the stock MONO full-size grain route). Offline.

  .venv/bin/python -I patches/grain_c/verify.py releases/v0.21/edits.json releases/v0.22/edits.json

  W  work list (real builder 0x6035749f .. finalize 0x60357c91): key 11, class 0, flags 0x80000 (+Soft Focus 0x80,
     +Pin Hole 0x400), slot grain 1..5 -> entries == stock MONO (key 12) for the same flags, job+5587 = min(g,3);
     grain 0, no 0x80000, class 4, LV-type gate, keys 12/0/5 -> == v0.21 (byte-identical list, entries, job)
  T  tone selector 0x603b039b, keys 11/12/0 x stages 0/0x0900/0x0901/0x0902 x kind 0/3: == stock except key 11 kind 0
     0x0900 -> mask LUT 0x605003aa (== stock key 12)
  C  combiner config 0x603a013b: key 11 stage 0x0901 level 0..3 (as packed) -> bank, counter == stock key 12
  F  allocation failure in the stock passes: mask pass (0x60350560 -> 48) -> 40643, grain pass (mask lookup 0x60350975
     -> 48) -> 40654; registers/stack intact, job untouched (the stock MONO error path; no buffer is taken)
  P  anti-brick: decode == stock + edits, restore == stock
"""
import json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'patches/grain_c'))
import ep7_grain_verify as GV  # noqa: E402
import map as M  # noqa: E402
import build_package as BP, oly_container as oc  # noqa: E402

BASE = 0x60020020


def image(spec):
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    return [b for b in oc.parse(pkg) if b.kind == 0x100][0].payload, pkg, rst, info


def w_list(stock, old, new):
    bad, n = [], 0
    for flags in (0x80000, 0x80080, 0x80400):
        ref, re_ = M.build(stock, 12, 0, feat=flags)
        for g in range(6):
            t = GV.fixture_table([g] * 4 + [0] * 4)
            p, pe = M.build(new, 11, 0, feat=flags, table=t)
            o, oe = M.build(old, 11, 0, feat=flags, table=t)
            n += 1
            if g:
                want = ref['ok'] and p['ok'] and pe == re_ and p['job'][5587] == min(g, 3)
                jd = [i for i in range(len(p['job'])) if p['job'][i] != o['job'][i]]
                want &= jd in ([5587], [5587, 11314]) and p['job'][11314:11316] == ref['job'][11314:11316]
            else:
                want = p['ok'] and pe == oe and p['job'] == o['job'] and p['list'] == o['list']
            if not want:
                bad.append((hex(flags), g, ref['ok'], p['ok'], pe == re_, p['job'][5587],
                            [i for i in range(len(p['job'])) if p['job'][i] != o['job'][i]][:6], [tuple(map(hex, e[:2])) for e in re_]))
    t = GV.fixture_table([3] * 4 + [0] * 4)
    for key, cls, flags, jtype in ((11, 0, 0, 0), (11, 0, 0x80, 0), (11, 4, 0x80000, 0), (11, 0, 0x80000, 0x110),
                                   (11, 0, 0x80000, 0x40), (12, 0, 0x80000, 0), (0, 0, 0x80000, 0), (5, 0, 0x80000, 0)):
        p, pe = M.build(new, key, cls, feat=flags, table=t, jtype=jtype)
        o, oe = M.build(old, key, cls, feat=flags, table=t, jtype=jtype)
        n += 1
        if not (p['ok'] and o['ok'] and pe == oe and p['job'] == o['job'] and p['list'] == o['list']):
            bad.append(('same-as-v0.21', key, cls, hex(flags), hex(jtype)))
    return bad, n


def tone(main, key, stage, kind):
    req = GV.request(kind, stage, 0x0400)
    struct.pack_into('>I', req, 8, key)                       # key bytes: [8]<<24 | [9]<<16 | u16 [10]
    req[8:12] = bytes([(key >> 24) & 255, (key >> 16) & 255]) + struct.pack('<H', key & 0xffff)
    rg = GV.regions(main, None, [GV.stack(), GV.PR.caller(0x603b039b, 0xf0, 24), GV.Region('req', GV.REQ, bytes(req), 'rw', True),
                                 GV.Region('flag', GV.OBJ, bytes(16), 'rw', True),
                                 GV.Region('lut', 0x60500000, main[0x60500000 - BASE:0x60520000 - BASE], 'r')])
    r = GV.execute(rg, {'pc': GV.CALLER, 'sp': GV.STACK + 0x1800, 'a0': GV.REQ, 'a1': GV.OBJ, 'd0': 0, **GV.REGS0}, GV.CALLER + 7, limit=20000)
    return r['registers']['a0'], GV.regs_ok(r, GV.CALLER + 7), r['fault']


def t_tone(stock, new):
    bad, n = [], 0
    for key in (11, 12, 0):
        for stage in (0, 0x0900, 0x0901, 0x0902):
            for kind in (0, 3):
                s, p = tone(stock, key, stage, kind), tone(new, key, stage, kind)
                want = s[0]
                if key == 11 and kind == 0 and stage == 0x0900:
                    want = tone(stock, 12, 0x0900, 0)[0]
                n += 1
                if not (p[1] and s[1] == p[1] and p[0] == want) or (key == 11 and kind == 0 and stage == 0x0900 and want != 0x605003aa):
                    bad.append((key, hex(stage), kind, hex(s[0]), hex(p[0]), s[1], p[1], s[2] or p[2]))
    return bad, n


def t_comb(stock, new):
    bad = []
    for lv in range(4):
        s, p = GV.cfg_run(stock, None, 12, 0x0901, lv), GV.cfg_run(new, None, 11, 0x0901, lv)
        if not (s['ok'] and p['ok'] and s['bank'] == p['bank'] and s['ramctr'] == p['ramctr']):
            bad.append(lv)
    return bad, 4


def t_fail(new):
    bad = []
    from penf_emulator import Region
    for fn, stub, code in ((0x60359bc8, 0x60350560, 40643), (0x60359cd8, 0x60350975, 40654)):
        job = GV.job_bytes(key=11, cls=0)
        im = bytearray(new)
        # stubs: 0x6035648e -> 1 (source found), the failing call -> 48, memset -> nop
        for a, s in ((0x6035648e, b'\x80\x01\xdf\xa0\x14'), (0x60350560, b'\x80\x30\xdf\xf0\x54'),
                     (0x60350975, (b'\x80\x30' if stub == 0x60350975 else b'\x80\x01') + b'\xdf\x80\x04')):
            im[a - BASE:a - BASE + len(s)] = s                # mov imm,d0; ret [],0
        rg = GV.regions(bytes(im), None, [GV.stack(), GV.caller_calls(fn), GV.Region('job', GV.JOB, bytes(job), 'rw', True),
                                          Region('ms', 0x4700115e, b'\xdf\xa0\x08', 'rx')])
        r = GV.execute(rg, {'pc': GV.CALLER, 'sp': GV.STACK + 0x1800, 'a0': GV.JOB, **GV.REGS0}, GV.CALLER + 7, limit=20000)
        d0 = r['registers']['d0'] & 0xffff
        if r['fault'] or r['registers']['pc'] != GV.CALLER + 7 or d0 != code or GV.mem(r)['job'] != bytes(job):
            bad.append((hex(fn), d0, r['fault']))
    return bad, 2


def main():
    old_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    stock = [b for b in oc.parse(BP.STOCK.read_bytes()) if b.kind == 0x100][0].payload
    old, *_ = image(old_s)
    new, pkg, rst, info = image(new_s)
    ok = True
    for name, fn in (('W work list', lambda: w_list(stock, old, new)), ('T tone selector', lambda: t_tone(stock, new)),
                     ('C combiner 31', lambda: t_comb(stock, new)), ('F alloc failure', lambda: t_fail(new))):
        bad, n = fn()
        ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:4] if bad else '')
    sb = {b.kind: b for b in oc.parse(BP.STOCK.read_bytes())}
    good = True
    for b in oc.parse(pkg):
        exp = bytearray(sb[b.kind].payload)
        for e in new_s['edits']:
            if int(e['kind'], 16) == b.kind:
                o = BP.resolve(b.kind, e['addr']); nb = bytes.fromhex(e['new']); exp[o:o + len(nb)] = nb
        good &= bytes(exp) == b.payload
    for b in oc.parse(rst):
        good &= b.payload == sb[b.kind].payload
    ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick ({info['edits']} edits, {info['changed_payload_bytes']} B)")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
