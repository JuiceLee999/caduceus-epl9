#!/usr/bin/env python3
"""Emulator checks for v0.27 (real firmware code; malloc, free, blend setup and flush stubbed). Offline.

  .venv/bin/python -I patches/v027/verify.py releases/v0.26/edits.json generated/grain_cpu/r1/edits.json [generated/grain_cpu/r1/pkg]

  M  the pass == patches/grain_cpu/model_r1.py, Low/Med/High, every window class, the real 0xd0000000 edge residue; record; mode restored
  F  guards: image untouched, buffers freed (incl. the half-res rows' buffer, guard 0x33)
  O  output route; L work lists (Off == v0.26); A flag gate; W level hand-off before the job marker exists
  E  Extras: sector 1 Grain +50, sector 9 NR +24, the others == v0.26, labels
  K  Grain and NR stay as the user set them: Film pick (look, own, Stock), the `*`, defaults (any reset) and the file ranges
  N  no card writes: sd_back as v0.26, no call from the block to the file API
  Y  word / halfword data labels aligned; X  every word / halfword access the block makes in these runs is aligned
  B, P  real blend setup, anti-brick
"""
import importlib.util, json, re, struct, sys
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


B = _load('gc_verify_s1', ROOT / 'patches/grain_cpu/verify_s1.py')
MOD = _load('gc_model_r1', ROOT / 'patches/grain_cpu/model_r1.py')
V, D = B.V, B.D
BASE = V.BASE


def expected(pic, w, h, st, level, seed):
    n, r = MOD.noise(w, h, seed)
    t = MOD.table(MOD.STRENGTH[level])
    a = np.frombuffer(pic, dtype=np.uint8).copy().reshape(h, st * 2)
    a[:, 0:2 * w:2] = t[a[:, 0:2 * w:2], n]
    return a.tobytes(), r


B.expected = expected
B.S = {1: 1, 2: 2, 3: 3}


def t_model(q, gc):
    TABLE = B.TABLE
    bad, n = [], 0
    ob, sg = int(gc['gc_ob'], 16), int(gc['gc_gs'], 16)
    for name, (bus, cached, m) in B.V.CLASSES.items():
        for lv, entry in ((1, sg), (2, ob), (3, ob)):
            w, h, st = 128, 9, 160
            pic = B.V.picture(w, h, st)
            r = B.run(q, gc, entry, B.job(bus, w=w, h=h, stride=st, profile=2), cached, pic, tbl=B.slot_table((0, lv, 0, 0)))
            want, sd = B.expected(pic, w, h, st, B.S[lv], 0x12345678)
            f = r['f']; cl = 0 if bus < 0xb0000000 else (2 if m else 1)
            locks = 3
            n += 1
            if not (r['ok'] and r['pic'] == want and r['frees'] == 3 and r['mallocs'] == 4 and (f['stage'], f['guard']) == (7, 0) and f['seed'] == sd and f['rows'] == h and f['cls'] & 15 == cl and r['flushes'] == locks * (2 if m else 1) + (2 if not m else 2) + (0 if not m else 0)):
                bad.append((name, lv, r['fault'], r['pic'] == want, f['stage'], hex(f['guard']), r['flushes'], f['cls']))
    edge, real, pitch = 0xd0000000, 0xce9d4b80, 10368
    k = (edge - real) % pitch
    bus = edge - k - 2 * pitch
    rows, st = 6, 5184
    pic = B.V.picture(5184, rows, st)
    cut = edge - bus
    j = B.job(bus, w=5184, h=rows, stride=st, profile=3)
    r = B.run(q, gc, ob, j, 0x70000000 | (bus & 0x07ffffff), pic[:cut], pic2=(0x70000000, pic[cut:]))
    want, sd = B.expected(pic, 5184, rows, st, B.S[2], 0x12345678)
    f = r['f']; n += 1
    if not (r['ok'] and r['m']['pic'] + r['m']['pic2'] == want and f['rows'] == rows and f['split'] == 1 and struct.unpack_from('<I', r['m']['modes'], V.MODES & 0xff)[0] == 0):
        bad.append(('edge', r['fault'], r['m']['pic'] + r['m']['pic2'] == want, f['rows'], f['split']))
    return bad, n



def t_guards_more(q, gc):
    bad, n = B.t_guards(q, gc)
    ob = int(gc['gc_ob'], 16)
    w, h, st, bus, c = 128, 5, 160, 0xa4000000, 0x64000000
    pic = V.picture(w, h, st)
    r = B.run(q, gc, ob, B.job(bus, w=w, h=h, stride=st), c, pic, fail=4); n += 1
    if not (r['ok'] and r['pic'] == pic and r['f']['guard'] == 0x33 and r['frees'] == 2):
        bad.append(('0x33', r['fault'], hex(r['f']['guard']), r['frees']))
    r = B.run(q, gc, ob, B.job(bus, w=w, h=h, stride=st), c, pic); n += 1
    if not (r['ok'] and r['frees'] == 3 and r['mallocs'] == 4):
        bad.append(('frees', r['frees'], r['mallocs']))
    return bad, n


def t_keep(old, new, new_s, gc):
    """Grain (+50) and NR (+24) only change through sectors 1 and 9."""
    bad, n = B.t_pick(old, new, gc, new_s)
    # u_apply for each kind of pick: a look record, own (a snapshot), Stock (zeros): T differs only in content
    for name, T in (('look', bytes((i * 7 + 3) & 0x7f for i in range(64))), ('own', bytes(range(64))), ('Stock', bytes(64))):
        slot = bytearray(64); slot[24] = 2; slot[50] = 3
        rg = [B.Region('a', 0x601e2e00, new[0x601e2e00 - BASE:0x601e2e4f - BASE], 'rx'), B.Region('b', 0x601e3700, new[0x601e3700 - BASE:0x601e3800 - BASE], 'rx'),
              B.Region('c', 0x601df000, new[0x601df000 - BASE:0x601e0b3c - BASE], 'rx'), B.Region('t', B.ALLOC, bytes(T) + bytes(64), 'rw', True), B.Region('s', B.JOB, bytes(slot), 'rw', True),
              B.Region('tail', 0x601e2e4f, b'\xcb\xcb', 'rx'), B.Region('stk', B.STK, bytes(0x4000), 'rw')]
        r = B.execute(rg, {'pc': 0x601e2e35, 'sp': B.STK + 0x3000, 'a1': B.ALLOC, 'd0': B.JOB}, 0x601e2e4f, limit=3000)
        s2 = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}['s']
        n += 1
        if r['fault'] or s2[24] != 2 or s2[50] != 3:
            bad.append(('pick', name, r['fault'], s2[24], s2[50]))
    # defaults: what a reset writes. Sectors 1 and 9 answer the current value; the others 0, as v0.26
    dflt = next(a for a in range(0x601e3330, 0x601e3348) if new[a - BASE:a - BASE + 4] == b'\xb5\x00\xc8\x1f') if False else 0x601e3333
    for sec, field, val, want in ((0, 50, 2, 2), (0, 50, 9, 0), (8, 24, 6, 1), (8, 24, 1, 2), (8, 24, 2, 3), (8, 24, 0, 0), (1, 28, 3, 0), (4, 46, 1, 0), (5, 47, 3, 0)):
        s = bytearray(64); s[field] = val
        f, v = B.ex_get(new, dflt, sec, B.p_block(s)); n += 1
        fo, vo = B.ex_get(old, dflt, sec, B.p_block(s))
        if f or v != want or (sec not in (0, 8) and v != vo):
            bad.append(('default', sec, val, f, v, vo))
    return bad, n


def t_nocard(old, new, new_s):
    bad = []
    at, n_ = int(new_s['grain_cpu']['code_at'], 16), new_s['grain_cpu']['code_len']
    if new[0x605b7420 - BASE:0x605b7425 - BASE] != old[0x605b7420 - BASE:0x605b7425 - BASE]:
        bad.append('sd_back differs from v0.26')
    st = new_s['look_editor']['stock']
    api = {int(st[k], 16) for k in ('ep7_fopen', 'ep7_fclose', 'ep7_fread', 'ep7_fwrite')} | {int(new_s['look_editor']['symbols']['ed_wfile'], 16)}
    b = _load('gc_b', ROOT / 'patches/grain_cpu/build.py')
    for a, op, args in b.SB3.disasm(new[at - BASE:at - BASE + n_], at, None):
        m = re.match(r'(0x[0-9a-f]+)', args)
        if op in ('call', 'calls', 'jmp') and m and int(m.group(1), 16) in api:
            bad.append((hex(a), op, args))
    return bad, 2


def t_data_align(gc):
    b = _load('gc_r1b', ROOT / 'patches/grain_cpu/build_r1.py')
    return b.data_alignment(b.source(), {k: int(v, 16) for k, v in gc.items()}), 1


def t_pkg(base_s, new_s, new, pkg, rst, info, disk, old):
    sb = {b.kind: b for b in V.oc.parse(V.BP.STOCK.read_bytes())}
    good = True
    for b in V.oc.parse(pkg):
        exp = bytearray(sb[b.kind].payload)
        for e in new_s['edits']:
            if int(e['kind'], 16) == b.kind:
                o = V.BP.resolve(b.kind, e['addr']); nb = bytes.fromhex(e['new']); exp[o:o + len(nb)] = nb
        good &= bytes(exp) == b.payload
    for b in V.oc.parse(rst):
        good &= b.payload == sb[b.kind].payload
    g = new_s['grain_cpu']
    um = int(g['um'], 16)
    ours = [(int(g['code_at'], 16), g['code_len']), (0x603579b8, 4), (0x60357b1f, 4), (0x603eabd8, 4), (int(g['bw_default'], 16), 3), (0x603574a0, 4), (0x601e32c9, 4), (0x601e33d8, 4), (0x601e356e, 4),
            (0x601e1264, 4), (0x601e128c, 4), (0x601e12eb, 4), (0x601e3713, 16), (0x601e2e36, 4), (um, 5), (0x601e3348, 6), (0x605b7721 + 50, 1), (0x601e0d12, 2), (0x601e0d15, 1)] + \
        [(int(e['addr'], 16), len(e['new']) // 2) for e in new_s['edits'] if e.get('source') == 'patches/fw_version']
    diff = [BASE + i for i in range(len(old)) if old[i] != new[i]]
    stray = [hex(a) for a in diff if not any(s_ <= a < s_ + k for s_, k in ours)]
    good &= not stray
    if disk:
        good &= (disk / 'patched.pkg.bin').read_bytes() == pkg and (disk / 'restore-stock.pkg.bin').read_bytes() == rst
    return good, f'{info["edits"]} edits, {info["changed_payload_bytes"]} B; {len(diff)} B differ from v0.26; stray {stray[:6]}'


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    old, *_ = V.image(base_s)
    new, pkg, rst, info = V.image(new_s)
    gc = new_s['grain_cpu']['symbols']
    q = B.stubbed(new, gc, B.slot_table())
    at, end = int(new_s['grain_cpu']['code_at'], 16), int(new_s['grain_cpu']['code_at'], 16) + new_s['grain_cpu']['code_len']
    ok = True
    for name, fn in (('M model', lambda: t_model(q, gc)), ('F guards', lambda: t_guards_more(q, gc)), ('O route', lambda: B.t_route(q, gc)), ('L lists', lambda: B.t_list(old, new, gc)),
                     ('A flag gate', lambda: B.t_flag(old, new)), ('W hand-off', lambda: B.t_handoff(old, new, gc)), ('E Extras', lambda: B.t_extras(old, new, new_s, gc)),
                     ('K Grain/NR kept', lambda: t_keep(old, new, new_s, gc)), ('N no card writes', lambda: t_nocard(old, new, new_s)), ('Y data labels', lambda: t_data_align(gc)),
                     ('X alignment', lambda: B.t_align(at, end, gc))):
        bad, n = fn(); ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:5] if bad else '')
    good, txt = V.t_blend(new); ok &= good
    print(f"{'PASS' if good else 'FAIL'} B blend setup: {txt}")
    good, txt = t_pkg(base_s, new_s, new, pkg, rst, info, disk, old); ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: {txt}")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
