#!/usr/bin/env python3
"""v0.24 checks (emulator only): real Film picks (fm_up/fm_down -> lt_post -> sp_tail -> ng_pick -> ed_poke).
  .venv/bin/python -I patches/v024/verify.py releases/v0.23/edits.json releases/v0.24/edits.json
P  full wheel on each COLOR slot: facade log == H,M,S, sat[12] ids + values (when the marker is set), Noise Filter, poke
O  a v0.23 LOOKS.BIN (no marker): no saturation writes at all
R  fm_check range table == tools/ep7_looks_bin; D  image diff vs v0.23 only at the v0.24 sites and the version label
K  anti-brick: package parses, restore == stock, decoded main == the emulated image
"""
import hashlib, importlib.util, json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


LT = _load('ep7_lt', ROOT / 'tools/ep7_verify_look_tone.py')
FV, EV, LB, LE, FB, G, O = LT.FV, LT.EV, LT.LB, LT.LE, LT.FB, LT.G, LT.O
LT.init(sys.argv[1], sys.argv[2])
G['new_looks'] = (ROOT / 'releases/v0.24/card/EP7MOD/LOOKS.BIN').read_bytes()
G['old_looks'] = (ROOT / 'releases/v0.23/card/EP7MOD/LOOKS.BIN').read_bytes()
base_regions = LT.code_regions
FV.code_regions = lambda im: base_regions(im) + [LT.img(im, 0x601e1b00, 0x601e1c40, 'ng2'), LT.img(im, 0x601e3890, 0x601e393c, 'ng1')]
SAT = (927, 939, 951, 1655)
B2U, U2NF = [0, 2, 3, 3, 3, 3, 1], [0, 0, -1, -2]


def want_extra(blk, L, k, pos, marker):
    n, out = L[O['n']], []
    if marker and 0 < pos <= n:
        r = bytes(L[64 * pos:64 * pos + 64])
        if r[32] == 1 and r[44] == 1:
            for s in range(12):
                v = (r[38 + s // 2] >> (4 * (s & 1))) & 15
                out.append((2, SAT[k] + s, 0, (v - 16 if v > 7 else v) & 0xffffffff))
    g = blk[32 + 64 * k + 24]
    if g < 7 and B2U[g]:
        out.append((2, 1334, 0, U2NF[B2U[g]] & 0xffffffff))
    return out


def wheel(label, key, d, which):
    looks = G[which]
    blk = FV.film_block()
    k = LT.KEYS.index(key)
    blk[32 + 64 * k + 47], blk[32 + 64 * k + 48] = 2, 0xfd
    L = FV.loaded_L(looks, blk)
    mb, mL = bytearray(blk), bytearray(L)
    n, sats, seen = FV.n_of(looks), 0, []
    for i in range(n + 3):
        pos, sets = LT.step_model(mb, mL, k, d)
        extra = want_extra(mb, mL, k, pos, which == 'new_looks')
        r, sy = FV.hit_run(key, d, blk, L)
        rg = r['registers']
        if r['fault'] or rg['pc'] != sy['done']:
            return f'{label} step {i}: {r["fault"]} pc {rg["pc"]:#x}'
        if rg['d0'] != 1 or rg['sp'] != LT.SP0 or any(rg[x] != LT.SENT[x] for x in ('d2', 'd3', 'a3')):
            return f'{label} step {i}: return state'
        fc = [x[:2] if x[0] == 1 else tuple(x) for x in EV.fac_log(r)]
        want = sets + extra + [(1, LT.CUR[key]), (2, LT.CUR[key], 0, 7)]
        if fc != want:
            return f'{label} step {i} pos {pos}:\n got {fc}\n want {want}'
        sats += sum(1 for x in fc if x[0] == 2 and SAT[k] <= x[1] < SAT[k] + 12)
        blk, L = bytearray(LT.mem(r, 'heap')), bytearray(LT.mem(r, 'L'))
        if blk != mb or L != mL:
            return f'{label} step {i} pos {pos}: heap/L differ'
        seen.append(pos)
    colour = sum(1 for j in range(n) if looks[64 + 64 * j + 46] & 1)
    expect = 12 * colour if which == 'new_looks' else 0
    if sats < expect or (which == 'old_looks' and sats):
        return f'{label}: {sats} saturation writes, wanted {expect}'
    if 0 not in seen or n + 1 not in seen:
        return f'{label}: wrap {seen}'
    return None


bad = []
cases = [(f'Up {key:#x}', key, 1, 'new_looks') for key in LT.KEYS] + [('Down COLOR2', 0x13b4, -1, 'new_looks')] + \
        [(f'old file {key:#x}', key, 1, 'old_looks') for key in (0x13b3, 0x140c)]
for c in cases:
    e = wheel(*c)
    print(c[0], 'FAIL' if e else 'ok', flush=True)
    if e:
        bad.append(e)
B = 0x60020020
im, base = G['lay'], G['base']
lo, span, _ = LB.SB.range_table(LB.SB.layout())
for o, (l, sp) in {**LB.TONE_RANGE, **LB.SAT_RANGE}.items():
    lo[o], span[o] = l, sp
FL, FS = 0x6143a788, 0x6143a7b5
r_ok = bytes(im[FL - B:FL - B + 45]) == bytes(v & 0xff for v in lo[:45]) and bytes(im[FS - B:FS - B + 45]) == bytes(span[:45])
print('R range table', r_ok)
spec = G['spec']
allowed = [(0x601e23e3, 0x601e23ea), (0x601e248c, 0x601e24ec), (FL + 38, FL + 44), (FS + 38, FS + 44)]
diff = [i + B for i in range(len(im)) if im[i] != base[i]]
rest = [hex(a) for a in diff if not any(x <= a < y for x, y in allowed)]
print('D', len(diff), 'bytes differ; outside v0.24 sites:', rest)
import build_package as BP, oly_container as oc
pkg, rst, _ = BP.build(spec, BP.STOCK.read_bytes())
parts = oc.parse(pkg)
k = dict(reparses=[b.kind for b in parts] == [int(x, 16) for x in spec['components']],
         restore_is_stock=hashlib.sha256(oc.parse(rst)[0].payload).hexdigest() == FB.MAIN_SHA, decoded_is_emulated=bytes(parts[0].payload) == bytes(im))
print('K', k)
if bad or not r_ok or not all(k.values()) or len(rest) > 16:
    print('\n'.join(bad)); sys.exit('VERIFY FAILED')
print('ALL OK')
