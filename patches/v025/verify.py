#!/usr/bin/env python3
"""v0.25 checks (emulator only). Offline, no camera.
  .venv/bin/python -I patches/v025/verify.py releases/v0.24/edits.json releases/v0.25/edits.json
U  the five Shading Comp. reads and two stills Noise Filter reads, real site through the real getter, stock vs v0.25: every picture
   mode / profile / slot byte / loaded or flashed table / d1 / a0 / setting value: d0 == the rule, every other register and the caller stack == stock
W  sector-1 edit and Film pick no longer call the settings path (the manager and facade are unmapped: a call would fault)
P  real Film picks over the whole wheel: slot == the v0.24 model + the Shading rule (look 1, keep-bit look 0, Stock 0, own snapshot); no 1334 write;
   +49 alone is not "modified"; fm_check accepts colour masks 1,3,5,7 and refuses the rest
R  loader range +49 0..1; D image diff vs v0.24 only at v0.25 sites and the version label
K  anti-brick: package parses, restore == stock, decoded main == the emulated image
"""
import hashlib, importlib.util, json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
W = _load('ep7_wb_v', ROOT / 'tools/ep7_verify_wb.py')
Region, execute, BP, oc = W.Region, W.execute, W.BP, W.oc
BASE, AT, END = 0x60020020, 0x601e393c, 0x601e3b3c
SP0, STACK, FILL = W.SP0, W.STACK, W.STACK_FILL
KEY, PM, PM6, COL = 0x8c21, 38017, 40209, 63153
SITES = (0x60303093, 0x602ab488, 0x60299b75, 0x6029fe64, 0x605554bc)
NKEY, NSITES = 0x9719, (0x602a8095, 0x6028d08a)
NR_VAL = {1: -1, 2: -2, 3: -2, 4: -2, 5: -2, 6: 0}
REGS0 = dict(d2=0x2222, d3=0x3333, a1=0xa1a1, a2=0xa2a2, a3=0xa3a3)
HANDLE, POOL = 0x41, 0xa1f8d800      # accessor: a0 = pool + handle - 1, 'EP7B' at a0, table at a0 + 32
ALT = 0x15800000

def image(spec):
    main = bytearray((ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes())
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16) - BASE; n = bytes.fromhex(e['new']); main[a:a + len(n)] = n
    return bytes(main)


def run(main, site, pr, b49, card, d1=0, a0=0, key=KEY, off=49):
    """Real site through the real getter. card: the accessor finds a loaded table; the flashed copy then holds the opposite."""
    tab, other = bytearray(512), bytearray(512)
    for k, v in enumerate(b49):
        tab[64 * k + off] = v
        other[64 * k + off] = 1 if v != 1 else 0
    for k in range(4, 8):
        tab[64 * k + off] = 1 if off == 49 else 2         # MONO entries: never read
    rg = [Region('site', site - 16, main[site - 16 - BASE:site + 16 - BASE], 'rx'),
          Region('getter', W.GETTER_CODE[0], main[W.GETTER_CODE[0] - BASE:W.GETTER_CODE[1] - BASE], 'rx'),
          Region('xlate', W.XLATE[0], main[W.XLATE[0] - BASE:W.XLATE[1] - BASE]), Region('cpuid', W.CPUID, bytes(4)), *W.registry(pr),
          Region('stub', AT, main[AT - BASE:END - BASE], 'rx'), Region('acc', 0x6055e7b0, main[0x6055e7b0 - BASE:0x6055e7f0 - BASE], 'rx'),
          Region('stack', STACK, bytes([FILL] * 0x2000), 'rw', True), Region('flashtab', 0x60210900, bytes(other if card else tab), 'r'),
          Region('state', 0x622cbcc0, struct.pack('<HHI', 0, HANDLE if card else 0, 0), 'r'),
          Region('alt', ALT, bytes(0x400), 'r')]
    if card:
        rg.append(Region('pool', POOL + HANDLE - 1, b'EP7B' + bytes(28) + bytes(tab), 'r'))
    r = execute(rg, dict(pc=site, sp=SP0, d0=key, d1=d1, a0=a0, **REGS0), site + 7, limit=8000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    above, depth = W.stack_info(m['stack'])
    return r['fault'], r['registers'], above, depth


MODES = [(11, 0), (6, 11), (12, 0), (6, 12), (6, 0), (0, 0), (100, 0), (10, 0)]
B49S = [(1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1), (0, 0, 0, 0), (1, 1, 1, 1), (2, 2, 2, 2), (255, 0xfe, 0x81, 0x80)]
REG = ('d1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'pc', 'mdr', 'psw', 'lir', 'lar')


NB = [(1, 2, 6, 0), (3, 4, 5, 7), (6, 6, 1, 1), (0, 0, 0, 0), (0xff, 0x80, 2, 6)]


def check_sites(stock, new, quick=False, sites=SITES, key=KEY, off=49):
    """off 49: shading (byte == 1 -> 0). off 24: NR (NR_VAL). Otherwise the stock value."""
    n, bad, mx, offs = 0, [], 0, 0
    bytes_ = B49S if off == 49 else NB
    modes = [(11, 0), (6, 11), (12, 0), (6, 12)] if quick else MODES
    for site in sites:
        for mode, m6 in modes:
            for col in ((0, 1, 3, 4, 5) if quick else (0, 1, 2, 3, 4, 5, 255)):
                for b in (bytes_[:2] if quick else bytes_):
                    for val in ((1,) if quick else (0, 1) if off == 49 else (0, 1, 0xfe, 0xff)):
                        for card in (False, True):
                            for d1, a0 in (((1, 0),) if quick else ((0, 0), (1, 0), (0, ALT))):
                                pr = {key: bytes([val, val ^ 3]), PM: bytes([mode]), PM6: bytes([m6]), COL: bytes([col])}
                                f0, r0, ab0, _ = run(stock, site, pr, b, card, d1, a0, key, off)
                                f1, r1, ab1, dp = run(new, site, pr, b, card, d1, a0, key, off)
                                on = (m6 if mode == 6 else mode) == 11 and 1 <= col <= 4
                                hit = on and (b[col - 1] == 1 if off == 49 else b[col - 1] in NR_VAL)
                                want = r0['d0'] if not hit else 0 if off == 49 else NR_VAL[b[col - 1]] & 0xffffffff
                                offs += hit; n += 1; mx = max(mx, dp)
                                if f0 or f1 or r1['d0'] != want or ab0 != ab1 or any(r0[k] != r1[k] for k in REG if not (hit and k == 'psw')):
                                    bad.append((hex(site), mode, m6, col, b, val, card, d1, a0, f1, hex(r1['d0']), hex(want), [k for k in REG if r0[k] != r1[k]]))
    return n, bad, mx, offs


def t_nowrite(im):
    """Sector-1 write and the Film pick tail: a settings call has nothing to land on, so it would fault."""
    bad, n = [], 0
    U2B = [0, 6, 1, 2]
    code = [Region('c1', 0x601e1b00, im[0x601e1b00 - BASE:0x601e1c40 - BASE], 'rx'), Region('c2', 0x601e2000, im[0x601e2000 - BASE:0x601e3b3c - BASE], 'rx')]
    STK, BUF = 0x18000000, 0x19000000
    for v in range(-7, 9):
        r = execute(code + [Region('buf', BUF, b'\xee' * 64, 'rw', True), Region('stk', STK, bytes(0x200), 'rw', True)],
                    dict(pc=0x601e33bc, sp=STK + 0x100, d0=1234, d1=v & 0xffffffff, d3=0, a0=0xa0a0, a1=0xa1a1, a2=BUF, mdr=0x601e9999), 0x601e3428, limit=2000)
        m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}; rr = r['registers']; u = min(max(v, 0), 3); n += 1
        if r['fault'] or rr['pc'] != 0x601e3428 or m['buf'][56] != U2B[u] or (rr['d0'], rr['d1'], rr['a0'], rr['a1'], rr['sp']) != (1234, u, 0xa0a0, 0xa1a1, STK + 0x100):
            bad.append(('set', v, r['fault'], m['buf'][56]))
    for k in range(5):
        for g in range(8):
            P = bytearray(0x400); P[32 + 64 * min(k, 3) + 24] = g
            r = execute(code + [Region('buf', BUF, bytes(P), 'rw', True), Region('stk', STK, bytes(0x200), 'rw', True)],
                        dict(pc=0x601e2341, sp=STK + 0x100, d2=0x2222, d3=k, a2=BUF, a3=0x3333), 0x601e37b4, limit=2000)
            rr = r['registers']; n += 1
            if r['fault'] or rr['pc'] != 0x601e37b4 or (rr['d2'], rr['d3'], rr['a2'], rr['a3'], rr['sp']) != (0x2222, k, BUF, 0x3333, STK + 0x100):
                bad.append(('pick', k, g, r['fault']))
    return n, bad


def t_picks(base_p, new_p):
    LT = _load('ep7_lt25', ROOT / 'tools/ep7_verify_look_tone.py')
    FV, EV, LE, G, O = LT.FV, LT.EV, LT.LE, LT.G, LT.O
    LT.init(base_p, new_p)
    G['new_looks'] = (ROOT / 'releases/v0.24/card/EP7MOD/LOOKS.BIN').read_bytes()
    base_regions = LT.code_regions
    FV.code_regions = lambda im: base_regions(im) + [LT.img(im, 0x601e1b00, 0x601e1c40, 'ng2'), LT.img(im, 0x601e3890, 0x601e3b3c, 'ng1')]
    SAT = (927, 939, 951, 1655)
    bad, steps = [], 0
    looks = bytearray(G['new_looks'])
    for j in (1, 4):                                       # two colour looks keep the camera's correction
        looks[64 + 64 * j + 46] |= 4
    looks = bytes(LT.refile(looks, 0, 0, looks[64])) if hasattr(LT, 'refile') else bytes(looks)
    G['new_looks'] = looks
    for key, d in [(k, 1) for k in LT.KEYS] + [(0x13b4, -1)]:
        blk = FV.film_block()
        k = LT.KEYS.index(key)
        blk[32 + 64 * k + 47], blk[32 + 64 * k + 48] = 2, 0xfd
        blk[32 + 64 * k + 49] = 1
        L = FV.loaded_L(looks, blk)
        mb, mL = bytearray(blk), bytearray(L)
        for i in range(FV.n_of(looks) + 3):
            pos, sets = LT.step_model(mb, mL, k, d)
            if 0 < pos <= mL[O['n']]:
                mb[32 + 64 * k + 49] = 0 if mL[64 * pos + 46] & 4 else 1
            extra = []
            if 0 < pos <= mL[O['n']]:
                r = bytes(mL[64 * pos:64 * pos + 64])
                if r[32] == 1 and r[44] == 1:
                    for c in range(12):
                        v = (r[38 + c // 2] >> (4 * (c & 1))) & 15
                        extra.append((2, SAT[k] + c, 0, (v - 16 if v > 7 else v) & 0xffffffff))
            q, sy = FV.hit_run(key, d, blk, L)
            steps += 1
            if q['fault'] or q['registers']['pc'] != sy['done']:
                bad.append((hex(key), i, q['fault'])); break
            fc = [x[:2] if x[0] == 1 else tuple(x) for x in EV.fac_log(q)]
            want = sets + extra + [(1, LT.CUR[key]), (2, LT.CUR[key], 0, 7)]
            if fc != want:
                bad.append((hex(key), i, pos, 'facade', [x for x in fc if x not in want], [x for x in want if x not in fc])); break
            blk, L = bytearray(LT.mem(q, 'heap')), bytearray(LT.mem(q, 'L'))
            if blk != mb:
                bad.append((hex(key), i, pos, 'heap', [j for j in range(len(blk)) if blk[j] != mb[j]][:12])); break
    mod = []
    for j in (0, 6, 13, 26):
        for off, want in ((None, 0), (49, 0), (47, 1), (48, 1), (0, 1), (33, 1), (50, 0)):
            lab, e = LT.m_case((f'look {j} +{off}', 'new_looks', j, off, 'look', want))
            if e:
                mod.append((lab, e))
    for j, mask, want in ((0, 1, True), (0, 3, True), (0, 5, True), (0, 7, True), (0, 2, False), (0, 4, False), (0, 6, False), (0, 9, False), (0, 0, False)):
        d = bytearray(LT.refile(G['new_looks'], 2, 46, mask))
        d[64 + 64 * 2 + 45] = 0
        d = LT.refile(d, 2, 45, 0)
        e = LT.check_run(bytes(d))
        if (e == 0) != want:
            mod.append(('fm_check mask', mask, e))
    return steps, bad, mod


def main():
    base_p, new_p = sys.argv[1], sys.argv[2]
    spec, bsp = json.loads(Path(new_p).read_text()), json.loads(Path(base_p).read_text())
    stock = (ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes()
    new, base = image(spec), image(bsp)
    fails = []
    n, bad, mx, offs = check_sites(stock, new)
    print(f'U shading: {n - len(bad)}/{n} (override in {offs} runs), peak stack {mx} B')
    for x in bad[:8]:
        print('  ', x)
    fails += ['U'] * bool(bad)
    n, bad, mx, offs = check_sites(stock, new, sites=NSITES, key=NKEY, off=24)
    print(f'U NR: {n - len(bad)}/{n} (override in {offs} runs), peak stack {mx} B')
    for x in bad[:8]:
        print('  ', x)
    fails += ['UN'] * bool(bad)
    n, bad = t_nowrite(new)
    print(f'W no settings call: {n - len(bad)}/{n}', bad[:6]); fails += ['W'] * bool(bad)
    steps, bad, mod = t_picks(base_p, new_p)
    print(f'P picks: {steps} steps, {len(bad)} bad; modified flag: {len(mod)} bad', bad[:4], mod[:4]); fails += ['P'] * bool(bad or mod)
    # R: loader range
    B = BASE
    lo, sp = new[0x605b7721 - 64 + 49 - B], new[0x605b7721 + 49 - B]
    print('R loader +49 lo/span', lo, sp); fails += ['R'] * (lo != 0 or sp != 1)
    # D: image diff vs v0.24
    allowed = [(AT, AT + spec['v025']['code_len']), (0x601e1263, 0x601e1268), (0x601e128b, 0x601e1290), (0x601e12ea, 0x601e12ef),
               (0x601e3713, 0x601e3724), (0x601e2e46, 0x601e2e47), (0x601e247f, 0x601e2480), (0x605b7752, 0x605b7753), (0x601e38ae, 0x601e38af), (0x601e2341, 0x601e2346), (0x6143a410, 0x6143a75d), (0x601e1c40, 0x601e1c64)] + [(s, s + 7) for s in SITES + NSITES]
    diff = [i + B for i in range(len(new)) if new[i] != base[i]]
    rest = [hex(a) for a in diff if not any(x <= a < y for x, y in allowed)]
    print('D', len(diff), 'bytes differ; outside v0.25 sites:', rest); fails += ['D'] * bool(rest)
    # K: anti-brick
    pkg, rst, _ = BP.build(spec, BP.STOCK.read_bytes())
    parts = oc.parse(pkg)
    k = dict(reparses=[b.kind for b in parts] == [int(x, 16) for x in spec['components']],
             restore_is_stock=hashlib.sha256(oc.parse(rst)[0].payload).hexdigest() == hashlib.sha256(stock).hexdigest(),
             decoded_is_emulated=bytes(parts[0].payload) == new)
    print('K', k); fails += ['K'] * (not all(k.values()))
    if fails:
        sys.exit(f'VERIFY FAILED {fails}')
    print('ALL OK')


if __name__ == '__main__':
    main()
