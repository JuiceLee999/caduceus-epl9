#!/usr/bin/env python3
"""Emulator checks of the v0.19 look tone on a Film pick (patches/v019/look_tone.s.in). Offline only.

  .venv/bin/python -I tools/ep7_verify_look_tone.py --base BASE.json --new releases/v0.19/edits.json [--jobs 12]

BASE = v0.19 without the look-tone layer (git show 33f46f5:releases/v0.19/edits.json). Our code runs natively from
the NEW image (fm_up through the real COLOR record +12/+16 words, fm_ui, lt_post, lv_art_refresh fm_post, up to
ed_poke's facade poke), with the look-editor facade stub logging GetValue/SetValue. Image regions read-only.
  P  picks, full Up wrap on each COLOR key (Down on COLOR2) with the card LOOKS.BIN (tone records): slot entry ==
     place() incl. +47/+48 = the look's Blacks/Whites; SetValue(HL/MID/SH id of COLOR k+1, 0, H/M/S) exactly once
     each, in that order, before the cursor poke; own restores the snapshot (+47/+48 kept), Stock = all zero, no
     SetValue for own/Stock; the v0.18 LOOKS.BIN (no tone): no SetValue, +47/+48 = 0, heap == BASE's run
  M  lt_mod via the editor's ed_cfg_fm word: 0 on place(), 1 after +47 / +48 / +49 / hue changes; v0.18 record:
     +47 != 0 -> 1; own / Stock -> 0
  C  fm_check (fm_core range table): card LOOKS.BIN and v0.18 LOOKS.BIN accepted; H/M/S -7 and +7 accepted, -8 / +8
     and B/W +-6 rejected (tools/ep7_looks_bin.check_file agrees on every case)
  K  anti-brick: package builds, re-parses, restore == stock, decoded main == the emulated image; NEW differs from
     BASE only in the look-tone region, the fm_ui jump, ed_cfg_fm and fm_core's 6 range bytes
"""
import argparse, hashlib, importlib.util, json, struct, sys, zlib
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


FV = _load('ep7_fmv2_verify_lt', ROOT / 'patches/film_menu_v2/verify.py')
EV, FB, LB, LE = FV.EV, FV.FB, FV.LB, FV.LE
Region, run, asm, img, mem = FV.Region, FV.run, FV.asm, FV.img, FV.mem
O, L_AT, P_OK, H_OK, SENT, SP0, DRV, NMAGIC = FV.O, FV.L_AT, FV.P_OK, FV.H_OK, FV.SENT, FV.SP0, FV.DRV, FV.NMAGIC
LT_AT, LT_END = 0x601e233c, 0x601e253c
IDS = (963, 966, 969, 1672)
KEYS = list(LE.RECORDS)
CUR = {0x13b3: 1091, 0x13b4: 1096, 0x13b5: 1097, 0x140c: 1686}
G = FV.G


def init(base, new):
    G['spec'] = json.loads(Path(new).read_text())
    G['base_spec'] = json.loads(Path(base).read_text())
    G['stock'], G['lay'] = EV.images(G['spec'])
    _, G['base'] = EV.images(G['base_spec'])
    G['es'] = {k: int(v, 16) for k, v in G['spec']['look_editor']['symbols'].items()}
    G['new_looks'] = (ROOT / 'releases/v0.19/card/EP7MOD/LOOKS.BIN').read_bytes()
    G['old_looks'] = (ROOT / 'releases/v0.18/card/EP7MOD/LOOKS.BIN').read_bytes()


def code_regions(im):
    return [img(im, FB.CODE[0], FB.CODE[1], 'fmcore'), img(im, FB.UI[0], FB.UI[1], 'fmui'),
            img(im, 0x61185b00, 0x61185d00, 'rec', 'r'), img(im, LE.UI[0], LE.UI[1], 'ui'),
            img(im, LE.KEYS[0], LE.KEYS[1], 'keys'), img(im, 0x601e3758, 0x601e383c, 'artrf'),
            img(im, LT_AT, LT_END, 'lt')]


FV.code_regions = code_regions          # hit_run maps these


def s8(v):
    return v - 256 if v >= 128 else v


def step_model(blk, L, k, d):
    """film_menu_v2 verify step_model + the tone rule. -> (pos, expected SetValue log)."""
    n = L[O['n']]
    pos = L[O['pos'] + k]
    while True:
        pos += d
        if pos < 0:
            pos = n + 1
        if pos > n + 1:
            pos = 0
        if pos in (0, n + 1) or L[64 * pos + 46] & 1:
            break
    L[O['pos'] + k] = pos
    if not L[O['snap'] + k]:
        L[O['snap'] + k] = 1
        L[O['snaps'] + 80 * k:O['snaps'] + 80 * k + 80] = bytes(blk[32 + 64 * k:96 + 64 * k]) + bytes(blk[544 + 16 * k:560 + 16 * k])
    sets = []
    if pos == 0:
        T = bytearray(L[O['snaps'] + 80 * k:O['snaps'] + 80 * k + 80])
    elif pos == n + 1:
        T = bytearray(80)
    else:
        r = bytes(L[64 * pos:64 * pos + 64])
        T = bytearray(r[:32] + bytes(13) + r[47:48] + bytes(18) + r[48:64])
        if r[32] == 1:
            T[47], T[48] = r[33], r[34]
            sets = [(2, IDS[k] + i, 0, s8(r[35 + i]) & 0xffffffff) for i in range(3)]
        if bytes(T[:64]) != LB.place(r, k):
            raise AssertionError(f'model entry != place() for look {pos - 1} slot {k}')
    L[O['stage']:O['stage'] + 64] = T[:64] if pos else T[:64]
    L[O['stage'] + 64:O['stage'] + 80] = T[64:80]
    if pos and pos != n + 1 and T[47:49] != bytes(2):
        L[O['stage'] + 47:O['stage'] + 49] = bytes(2)       # staging T has 0 there; lt_post writes the entry
    L[O['stage'] + 80] = blk[32 + 64 * k + 46]
    blk[32 + 64 * k:96 + 64 * k] = T[:64]
    blk[544 + 16 * k:560 + 16 * k] = T[64:]
    struct.pack_into('<I', blk, 672, NMAGIC)
    blk[LE.DIRTY] = 1
    return pos, sets


def p_case(args):
    label, key, d, which = args
    looks = G[which]
    blk = FV.film_block()
    k = KEYS.index(key)
    blk[32 + 64 * k + 47], blk[32 + 64 * k + 48] = 2, 0xfd          # own entry with Blacks +2 / Whites -3
    L = FV.loaded_L(looks, blk)
    mb, mL = bytearray(blk), bytearray(L)
    bb, bL = bytearray(blk), bytearray(L)
    n = FV.n_of(looks)
    seen, tone_hits = [], 0
    for i in range(n + 3):
        pos, sets = step_model(mb, mL, k, d)
        r, sy = FV.hit_run(key, d, blk, L)
        rg = r['registers']
        if r['fault'] or rg['pc'] != sy['done']:
            return label, f'step {i}: run {r["fault"]} pc {rg["pc"]:#x}'
        if rg['d0'] != 1 or rg['sp'] != SP0 or any(rg[x] != SENT[x] for x in ('d2', 'd3', 'a3')):
            return label, f'step {i}: return state'
        fc = [x[:2] if x[0] == 1 else tuple(x) for x in EV.fac_log(r)]
        want = sets + [(1, CUR[key]), (2, CUR[key], 0, 7)]
        if fc != want:
            return label, f'step {i} pos {pos}: facade log {fc} != {want}'
        tone_hits += bool(sets)
        blk, L = bytearray(mem(r, 'heap')), bytearray(mem(r, 'L'))
        if blk != mb:
            return label, f'step {i} pos {pos}: heap differs at {[j for j in range(len(blk)) if blk[j] != mb[j]][:8]}'
        if L != mL:
            return label, f'step {i} pos {pos}: L differs at {[j for j in range(len(L)) if L[j] != mL[j]][:8]}'
        if which == 'old_looks':                                  # v0.18 file: same heap as BASE (no tone layer)
            G2 = G['lay']
            G['lay'] = G['base']
            try:
                rb, _ = FV.hit_run(key, d, bb, bL)
            finally:
                G['lay'] = G2
            bb, bL = bytearray(mem(rb, 'heap')), bytearray(mem(rb, 'L'))
            if bb != blk or bL != L:
                return label, f'step {i}: heap/L != BASE run'
        seen.append(pos)
    if 0 not in seen or n + 1 not in seen:
        return label, f'wrap {seen}'
    if which == 'new_looks' and tone_hits < 20:
        return label, f'only {tone_hits} tone picks'
    return label, None


def p_cases():
    out = [(f'Up wrap key {key:#x} card LOOKS.BIN', key, 1, 'new_looks') for key in KEYS]
    out.append(('Down wrap COLOR2 card LOOKS.BIN', 0x13b4, -1, 'new_looks'))
    out += [(f'Up wrap key {key:#x} v0.18 LOOKS.BIN', key, 1, 'old_looks') for key in (0x13b3, 0x140c)]
    return out


def m_case(args):
    label, which, j, off, pos_mode, want = args
    looks = G[which]
    r = FV.rec(looks, j)
    blk = FV.film_block()
    for k in range(4):
        blk[32 + 64 * k:96 + 64 * k] = LB.place(r, k)
        blk[544 + 16 * k:560 + 16 * k] = r[48:64]
        if off is not None:
            blk[32 + 64 * k + off] ^= 1
    L = FV.loaded_L(looks, FV.film_block())
    n = FV.n_of(looks)
    for k in range(4):
        L[O['pos'] + k] = {'look': j + 1, 'own': 0, 'stock': n + 1}[pos_mode]
    res = []
    for k in range(4):
        src = f' mov {G["es"]["ed_cfg_fm"]:#x},a1\n mov (a1),a1\n mov {P_OK:#x},a2\n mov {k},d1\n calls (a1)\n'
        code, sy = asm(src, DRV)
        regions = [Region('drv', DRV, code, 'rx'), Region('L', L_AT, bytes(L), 'r')] + code_regions(G['lay']) + \
            EV.state_regions(H_OK, blk, 'r')
        q = run(regions, {'pc': DRV}, sy['done'])
        rg = q['registers']
        if q['fault'] or rg['pc'] != sy['done'] or rg['a2'] != P_OK or rg['sp'] != SP0 or \
                any(rg[x] != SENT[x] for x in ('d2', 'd3', 'a3')):
            return label, f'k{k}: run {q["fault"]} / registers'
        res.append(rg['d0'])
    return (label, None) if res == [want] * 4 else (label, f'd0 {res} want {want}')


def m_cases():
    out = []
    for j in (0, 6, 13, 26):
        out.append((f'tone look {j} placed', 'new_looks', j, None, 'look', 0))
        for off in (47, 48, 49, 0, 33):
            out.append((f'tone look {j} entry +{off} changed', 'new_looks', j, off, 'look', 1))
        out.append((f'tone look {j} own', 'new_looks', j, 47, 'own', 0))
        out.append((f'tone look {j} Stock', 'new_looks', j, 47, 'stock', 0))
    for j in (0, 9):
        out.append((f'v0.18 look {j} placed', 'old_looks', j, None, 'look', 0))
        out.append((f'v0.18 look {j} +47 set', 'old_looks', j, 47, 'look', 1))
        out.append((f'v0.18 look {j} +45 changed', 'old_looks', j, 45, 'look', 1))
    return out


def check_run(data):
    """fm_check natively: a3 = L (the file), d3 = size -> d0."""
    sym = 0x6143a5a6                                   # fm_check (fm_core layout unchanged; checked in K)
    src = f' mov {L_AT:#x},a3\n mov {len(data)},d3\n call fmc,[d2,d3,a2,a3],20\n'
    code, sy = asm(src, DRV, dict(fmc=sym))
    regions = [Region('drv', DRV, code, 'rx'), Region('L', L_AT, bytes(data) + bytes(FB.L_SIZE - len(data)), 'r')] + \
        code_regions(G['lay']) + EV.state_regions(H_OK, FV.film_block(), 'r')
    q = run(regions, {'pc': DRV}, sy['done'])
    if q['fault'] or q['registers']['pc'] != sy['done']:
        return None
    return q['registers']['d0']


def refile(data, j, off, v):
    d = bytearray(data)
    d[64 + 64 * j + off] = v & 0xff
    raw = bytes(d)
    struct.pack_into('<I', d, 16, zlib.crc32(raw[:16] + raw[20:]) & 0xffffffff)
    return bytes(d)


def c_case(args):
    label, which, j, off, v = args
    data = G[which] if off is None else refile(G[which], j, off, v)
    got = check_run(data)
    py = 0 if not LB.check_file(data) else 1
    if got is None:
        return label, 'run fault'
    want = 0 if (off is None or (off in (35, 36, 37) and -7 <= v <= 7) or (off in (33, 34) and -5 <= v <= 5)) else 1
    return (label, None) if got == py == want else (label, f'camera {got} python {py} want {want}')


def c_cases():
    out = [('card LOOKS.BIN', 'new_looks', 0, None, 0), ('v0.18 LOOKS.BIN', 'old_looks', 0, None, 0)]
    for off in (35, 36, 37):
        for v in (-8, -7, 7, 8):
            out.append((f'+{off} = {v}', 'new_looks', 3, off, v))
    for off in (33, 34):
        for v in (-6, -5, 5, 6):
            out.append((f'+{off} = {v}', 'new_looks', 3, off, v))
    return out


def k_check():
    sys.path.insert(0, str(ROOT / 'tools'))
    sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
    import build_package as BP
    import oly_container as oc
    pkg, restore, info = BP.build(G['spec'], BP.STOCK.read_bytes())
    parts = oc.parse(pkg)
    main = parts[0].payload
    st = oc.parse(restore)[0].payload
    lay = G['lay']
    base = G['base']
    import numpy as np
    diff = [int(i) for i in np.nonzero(np.frombuffer(bytes(lay), np.uint8) != np.frombuffer(bytes(base), np.uint8))[0]] \
        if len(lay) == len(base) else None
    allowed = [(LT_AT, LT_END), (0x601e2e93, 0x601e2e98), (0x601e3160, 0x601e3164),
               (0x6143a788 + 35, 0x6143a788 + 38), (0x6143a7b5 + 35, 0x6143a7b5 + 38)]
    B = 0x60020020
    c = dict(reparses=[b.kind for b in parts] == [int(k, 16) for k in G['spec']['components']],
             restore_is_stock=hashlib.sha256(st).hexdigest() == FB.MAIN_SHA,
             decoded_is_emulated=bytes(main) == bytes(lay),
             diff_only_allowed=diff is not None and all(any(a <= i + B < b for a, b in allowed) for i in diff),
             fm_check_addr=G['spec']['look_tone']['symbols']['lt_post'] == hex(LT_AT))
    return [('K anti-brick ' + json.dumps(c), None if all(c.values()) else 'fail')]


PARTS = dict(P=(p_cases, p_case), M=(m_cases, m_case), C=(c_cases, c_case))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', required=True)
    ap.add_argument('--new', required=True)
    ap.add_argument('--part', default='P,M,C,K')
    ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()
    init(a.base, a.new)
    res = []
    parts = a.part.split(',')
    with ProcessPoolExecutor(a.jobs, initializer=init, initargs=(a.base, a.new)) as ex:
        futs = []
        for p in parts:
            if p in PARTS:
                cases, fn = PARTS[p]
                futs.append((p, ex.map(fn, cases())))
        for p, f in futs:
            res += [(p, x) for x in f]
    if 'K' in parts:
        res += [('K', x) for x in k_check()]
    groups = {}
    for p, (label, err) in res:
        groups.setdefault(p, [0, 0])
        groups[p][0] += err is None
        groups[p][1] += 1
        if err:
            print(f'FAIL {p} {label}: {err}')
        elif p == 'K':
            print(f'PASS {label}')
    print('  '.join(f'{p}: {x}/{n}' for p, (x, n) in groups.items()))
    ok = all(err is None for _, (_, err) in res)
    print('PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
