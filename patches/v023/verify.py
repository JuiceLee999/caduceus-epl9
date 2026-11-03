#!/usr/bin/env python3
"""v0.23 Film-page step checks (emulator only): the fm_up/fm_down step loop 0x601e2d51 -> 0x601e2d7e with the real
lt_mod, plus the two label bytes.  .venv/bin/python -I patches/v023/verify.py releases/v0.23/edits.json"""
import json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
from penf_emulator import Region, execute  # noqa: E402

BASE, L, P, STK = 0x60020020, 0xa1dd8d40, 0x18000000, 0x18010000
spec = json.loads(Path(sys.argv[1]).read_text())
im = bytearray((ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes())
for e in spec['edits']:
    if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
        a = int(e['addr'], 16) - BASE; b = bytes.fromhex(e['new']); im[a:a + len(b)] = b
looks = (ROOT / 'releases/v0.22/card/EP7MOD/LOOKS.BIN').read_bytes()
n = (len(looks) - 64) // 64


def run(k, pos, snap, step, modified=False):
    Lb = bytearray(2540); Lb[:len(looks)] = looks
    struct.pack_into('<II', Lb, 2112, 0x4c375045, P); Lb[2120] = n; Lb[2121 + k] = pos; Lb[2125 + k] = snap
    Pb = bytearray(0x400); struct.pack_into('<II', Pb, 1016, L, 0x46375045)
    if 1 <= pos <= n:
        r = looks[64 * pos:64 * pos + 64]
        ent = bytearray(r[:32]) + bytes(32); ent[45] = r[47]
        if r[32] == 1:
            ent[47], ent[48] = r[33], r[34]      # tone record (lt_mod rule)
        if modified:
            ent[3] ^= 1
        Pb[32 + 64 * k:96 + 64 * k] = ent
    stk = bytearray(0x200); struct.pack_into('<I', stk, 0x104, k)
    rg = [Region('code', 0x601e2000, bytes(im[0x601e2000 - BASE:0x601e3a00 - BASE]), 'rx'),
          Region('L', L, bytes(Lb), 'rw', True), Region('P', P, bytes(Pb), 'rw', True), Region('stk', STK, bytes(stk), 'rw', True)]
    r = execute(rg, dict(pc=0x601e2d51, sp=STK + 0x100, a0=L, a2=P, d3=k, d2=step & 0xffffffff), 0x601e2d7e, limit=5000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    rr = r['registers']
    ok = not r['fault'] and rr['pc'] == 0x601e2d7e and rr['a0'] == L and rr['d2'] == step & 0xffffffff and rr['sp'] == STK + 0x100
    return ok, rr['d0'], m['L'][2125 + k]


S = n + 1
cases = [  # (k, pos, snap, step, modified) -> (new pos, snap)
    ((0, 1, 0, -1, False), (S, 2)),      # Velvia unmodified, step down: Stock, own hidden
    ((0, S, 2, +1, False), (1, 2)),      # Stock up: skips own -> Velvia
    ((1, 1, 0, -1, True), (0, 0)),       # Velvia modified: own kept (snapshot follows at 2d7e)
    ((2, 0, 0, +1, False), (1, 0)),      # custom slot (own): -> first look
    ((3, S, 1, +1, False), (0, 1)),      # own already snapshotted: still reachable
    ((2, 2, 0, +1, False), (3, 2)),      # Astia unmodified up: hidden own
    ((0, n - 3, 0, +1, False), (S, 2)),  # last colour look up: mono skipped -> Stock
]
bad = 0
for (a, want) in cases:
    ok, d0, sn = run(*a)
    good = ok and (d0, sn) == want
    bad += not good
    print('PASS' if good else 'FAIL', a, '->', (d0, sn), 'want', want)
lab = [bytes(im[a - BASE:a - BASE + 7]) for a in (0x60b9dee3, 0x60b9deea)]
print('PASS' if lab == [b'Film: \0', b'Film \0S'] else 'FAIL', 'labels', lab)
bad += lab != [b'Film: \0', b'Film \0S']
th = [im[a - BASE] for a in (0x60b9de3c, 0x60b9de46, 0x60b9de66)]
print('PASS' if th == [14, 14, 19] else 'FAIL', 'prefix thresholds / cap', th); bad += th != [14, 14, 19]
sys.path.insert(0, str(ROOT / 'tools'))
import build_package as BP, oly_container as oc  # noqa: E402
old = bytearray((ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes())
for e in json.loads((ROOT / 'releases/v0.22/edits.json').read_text())['edits']:
    if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
        a = int(e['addr'], 16) - BASE; b = bytes.fromhex(e['new']); old[a:a + len(b)] = b
sites = [(0x601e2d51, 5), (0x601e2d67, 5), (0x601e2edc, 96), (0x60b9dee3, 1), (0x60b9deea, 1), (0x60b9de3c, 1), (0x60b9de46, 1), (0x60b9de66, 1), (0x601e1c40, 0xc0)]
stray = [hex(i + BASE) for i in range(len(im)) if im[i] != old[i] and not any(a <= i + BASE < a + n for a, n in sites)]
print('PASS' if not stray else 'FAIL', 'D diff vs v0.22 only in v0.23 sites (+ fw label)', stray[:6]); bad += bool(stray)
pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
sb = {b.kind: b for b in oc.parse(BP.STOCK.read_bytes())}
good = True
for b in oc.parse(pkg):
    exp = bytearray(sb[b.kind].payload)
    for e in spec['edits']:
        if int(e['kind'], 16) == b.kind:
            o = BP.resolve(b.kind, e['addr']); nb = bytes.fromhex(e['new']); exp[o:o + len(nb)] = nb
    good &= bytes(exp) == b.payload
for b in oc.parse(rst):
    good &= b.payload == sb[b.kind].payload
print('PASS' if good else 'FAIL', f"P anti-brick ({info['edits']} edits, {info['changed_payload_bytes']} B)"); bad += not good
print('ALL PASS' if not bad else 'FAILURES')
sys.exit(1 if bad else 0)
