#!/usr/bin/env python3
"""Emulator checks for the v0.15 MONO-colour UI `mc` (patches/mono_colour/mc_ui.s.in) on a merged spec. Offline.

  .venv/bin/python -I tools/ep7_mc_ui_verify.py generated/v015/mcui/merged.json [--json out.json]

Images: patched = the spec; base = the same spec with the mono_colour / mc edits stripped (build_v15.strip).
Fixture heap block P (card_block of the editor verifier: COLOR1-4 H/L, names, stale 0xa5 from +688) with
MONO1 = colour look (Velvia), MONO2 = colour look (Portra), MONO3/MONO4 = B&W (all zero). The real picture mode
comes from a stand-in of the stock getter 0x602af887 (setting 111 = PM, other ids -> a fixed S formula).
Every image region is read-only (a store into the image faults the run).

  R  routing: screen lookups 0x60e4cea8 / 0x60e4cf21 and the type-7 dispatcher word, every MONO / COLOR /
     shading key x picture modes x heap states -> the key at the resume point == model (COLOR m only for a colour
     MONO m in MONO m mode with a valid table); everything else byte-identical to the base build (registers, live
     stack); session byte cleared on MONO filter keys; group != 0x12 untouched
  G  facade GetValue: 111 from each listed return address / Profile view page 1 -> COLOR m mode under pred, else
     the chained routine is entered with every register and the stack as at entry; COLOR m sector ids x pages
     -> the MONO slot byte (clamped), other profiles / modes / states -> chain
  D  GetDefault: hit -> 0, else chain
  S  GUI setter site: hit -> slot byte / flags / dirty, then the stock manager with (id, its S value, a0, a1) and
     the setter's return address in MDR; out-of-range / Extras -> refused (0); misses -> chain, registers intact
  P  polygon: profile read (1648) -> m+1 under pred; sector reads -> slot value (Film / Extras 0); else stock / chain
  U  Film page: full wraps both ways on MONO1 / MONO2 / MONO3 (session): entry == ep7_looks_bin.place(look, 4+m) for
     the MONO-capable colour looks, all zero for presets / B&W; name; 'EP7N'; dirty; session; the 8 SetValue calls
     (id, value) of a preset; ed_poke; misses (other page, COLOR mode, other key, no LOOKS.BIN) -> chain
  L  Film label on a MONO slot (chain: ex_guide -> ed_guide -> stock part stand-in)
  T  round trip: picks -> the real half-press save (ed_trig -> ed_save) writes BUNDLES.BIN == heap image, the
     loader rules accept it; the reloaded table then routes (colour slot -> COLOR key, B&W -> stock) and the capture
     selector renders it (colour slot == mode-11 reference, B&W == stock), i.e. the power-cycle round trip
"""
import argparse, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


EV = _load('ep7_verify_look_editor_mc', ROOT / 'tools/ep7_verify_look_editor.py')
BV = _load('ep7_mono_colour_build_v15_mc', ROOT / 'patches/mono_colour/build_v15.py')
FB = BV.FM
LB = FB.LB
Region, run, asm, img, mem, execute = EV.Region, EV.run, EV.asm, EV.img, EV.mem, EV.execute
BASE, H_OK, P_OK, NMAGIC = EV.BASE, EV.H_OK, EV.P_OK, EV.NMAGIC
DRV, OUT, PAR, SENT, SP0, STK = EV.DRV, EV.OUT, EV.PAR, EV.SENT, EV.SP0, EV.STK
O = FB.OFF
L_AT = EV.POOL + 0x8000
SG_AT = 0x18f00000                       # stand-in stock getter 0x602af887 (+ control word: picture mode)
MAN_AT = 0x18f10000                      # stand-in settings manager 0x60827440 (stop point only)
MONO_PM, COLOR_PM = [57, 58, 59, 65], [54, 55, 56, 64]
CKEYS, MKEYS = [0x13b3, 0x13b4, 0x13b5, 0x140c], [0x13b6, 0x13b7, 0x13b8, 0x140d]
SKEYS = [0x13b9, 0x13ba, 0x13bb, 0x140e]
G = {}


def sgv(idv):
    return ((idv & 0xffff) & 7) - 3


SG_STUB = f"""
 exthu d0
 cmp 111,d0
 bne 1f
 mov ({SG_AT + 0x100:#x}),d0
 bra 2f
1:
 and 7,d0
 add -3,d0
2:
 mov 0xbad0d1d1,d1
 mov 0xbad0a0a0,a0
 mov 0xbad0a1a1,a1
 ret [],4
"""


def sg_regions(pm):
    code, _ = asm(SG_STUB, SG_AT)
    return [Region('sg', SG_AT, code, 'rx'), Region('sgc', SG_AT + 0x100, struct.pack('<I', pm), 'r'),
            Region('t_sg', 0x602af887, b'\xdc' + struct.pack('<i', SG_AT - 0x602af887), 'rx')]


def init(path):
    G['spec'] = json.loads(Path(path).read_text())
    G['base_spec'] = BV.strip(G['spec'])
    G['stock'], G['pat'] = EV.images(G['spec'])
    _, G['base'] = EV.images(G['base_spec'])
    G['sym'] = {k: int(v, 16) for k, v in G['spec']['mono_colour_ui']['symbols'].items()}
    G['chain'] = {k: int(v, 16) for k, v in G['spec']['mono_colour_ui']['chain'].items()}
    G['looks'] = (ROOT / 'releases/v0.14/card/EP7MOD/LOOKS.BIN').read_bytes()
    G['ps'] = G['spec']['mono_presets']['presets']
    G['ids'] = G['spec']['mono_presets']['ids']


def n_looks():
    return len(G['looks']) // 64 - 1


def rec(j):
    return G['looks'][64 + 64 * j:128 + 64 * j]


def name_of(j):
    return rec(j)[48:64]


def look_index(nm):
    return [bytes(name_of(j)).split(b'\0')[0].decode() for j in range(n_looks())].index(nm)


def block(axis=0, mono=('Velvia', 'Portra 400', None, None), sess=None, cmark=True):
    b = EV.card_block(axis=axis)
    for m, nm in enumerate(mono):
        e = 32 + 64 * (4 + m)
        if nm:
            b[e:e + 64] = LB.place(rec(look_index(nm)), 4 + m)
            b[544 + 16 * (4 + m):560 + 16 * (4 + m)] = name_of(look_index(nm))
        else:
            b[e:e + 64] = bytes(64)
    if cmark:
        struct.pack_into('<I', b, BV.CMARK, BV.CMAGIC)
        b[BV.SESS:BV.SESS + 28] = bytes(28)
    if sess is not None:
        b[BV.SESS] = sess
    struct.pack_into('<II', b, O['lptr'], L_AT, FB.FMAGIC)
    return b


def L_block(blk):
    L = bytearray([0xee]) * 2048
    L[:len(G['looks'])] = G['looks']
    struct.pack_into('<II', L, O['ltag'], FB.LMAGIC, P_OK)
    L[O['n']] = n_looks()
    return L


def regions_common(im, pm, blk, h=H_OK, L=None):
    ui = BV.UI
    rg = [img(im, ui[0], ui[1], 'mc'), img(im, 0x601e2c3c, 0x601e3a3c, 'evf'), img(im, 0x605b7180, 0x605b7800, 'sec3'),
          img(im, 0x61242900, 0x61243000, 'sec6'), img(im, 0x6143a400, 0x6143a800, 'sec9'),
          img(im, 0x61185b00, 0x61186100, 'rec', 'r'), img(im, 0x60acb0d0, 0x60acb180, 'fvt', 'r')]
    rg += sg_regions(pm) + EV.state_regions(h, blk)
    if L is not None:
        rg.append(Region('L', L_AT, bytes(L), 'rw', True))
    return rg


def model_div(key, pm, blk, h=H_OK):
    if h != H_OK or blk[:4] != b'EP7B' or key not in MKEYS:
        return key
    m = MKEYS.index(key)
    if pm != MONO_PM[m] or blk[32 + 64 * (4 + m) + 32] != 1:
        return key
    return CKEYS[m]


# ------------------------------------------------------------------ R routing
def scr_run(im, which, key, pm, blk, group=0x12, h=H_OK):
    at, resume = (BV.SCR, BV.SCR_RESUME) if which == 1 else (BV.SCR2, BV.SCR2_RESUME)
    regs = dict(SENT, pc=at, sp=SP0, d0=group, d1=key | 0x77770000, a0=0x1a0a0a0a, a1=0x1a1a1a1a, mdr=0x3d3d3d3d)
    rg = [img(im, at - 16, at + 32, 'site')] + regions_common(im, pm, blk, h)
    return execute([Region('stack', STK, bytes([0x5c]) * 0x2000, 'rw', True)] + rg, regs, resume, limit=200000)


def open_run(im, key, pm, blk, h=H_OK):
    po = bytearray(16)
    struct.pack_into('<H', po, 0, key)
    src = (f' mov {BV.W_OPEN:#x},a1\n mov (a1),a2\n mov {PAR:#x},a0\n mov 0x0d0d0d0d,d0\n mov 0x11111111,d1\n'
           f' mov 0x1a1a1a1a,a1\n calls (a2)\n')
    code, sy = asm(src, DRV)
    rg = [Region('drv', DRV, code, 'rx'), Region('par', PAR, bytes(po), 'r'), img(im, BV.W_OPEN, BV.W_OPEN + 4, 'w7', 'r'),
          Region('open', BV.OPEN, b'\xcb\xcb', 'rx')] + regions_common(im, pm, blk, h)
    return run(rg, {'pc': DRV}, BV.OPEN), sy


def r_cases():
    out = []
    good = block()
    bad = block()
    bad[0] ^= 1
    sess = block(mono=(None, 'Portra 400', None, None), sess=0x81)
    states = [('table', good, H_OK), ('no table', good, 0), ('h 0xffff', good, 0xffff), ('no EP7B', bad, H_OK),
              ('session MONO1 (B&W)', sess, H_OK)]
    for key in MKEYS + CKEYS + SKEYS + [0x13a9]:
        for pm in MONO_PM + COLOR_PM + [0, 12]:
            for lab, b, h in states:
                if key not in MKEYS and lab != 'table':
                    continue
                if key in MKEYS and pm not in MONO_PM + [54] and lab != 'table':
                    continue
                out.append((f'{key:#x} pm {pm} {lab}', key, pm, b, h))
    return out


def check_r():
    fails, n = [], 0
    for lab, key, pm, b, h in r_cases():
        want = model_div(key, pm, b, h)
        for which in (1, 2):
            n += 1
            rb, rp = scr_run(G['base'], which, key, pm, b, h=h), scr_run(G['pat'], which, key, pm, b, h=h)
            stop = BV.SCR_RESUME if which == 1 else BV.SCR2_RESUME
            if rb['fault'] or rp['fault'] or rp['registers']['pc'] != stop:
                fails.append(f'R scr{which} {lab}: {rp["fault"]} {rb["fault"]}')
                continue
            sb, sp_ = EV.live_stack(rb), bytearray(EV.live_stack(rp))
            if which == 1:              # scr: the key is stored at (32,sp) by the replayed instruction
                got = struct.unpack_from('<H', sp_, 32)[0]
                struct.pack_into('<H', sp_, 32, struct.unpack_from('<H', sb, 32)[0])
            else:                       # scr2: the key is still in d1 at 0x60e4cf28 (movhu d1,(32,sp) is next)
                got = rp['registers']['d1'] & 0xffff
            e = None
            for k in ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'mdr'):
                if k == 'd1' and which == 2 and got != key:
                    if rp['registers']['d1'] != want:
                        e = f'd1 {rp["registers"]["d1"]:#x}'
                    continue
                if rb['registers'][k] != rp['registers'][k]:
                    e = f'{k} {rp["registers"][k]:#x} != base {rb["registers"][k]:#x}'
            if e or bytes(sp_) != sb or got != want:
                fails.append(f'R scr{which} {lab}: key {got:#x} want {want:#x} {e or ""}')
                continue
            hp = mem(rp, 'heap')
            exp = bytearray(b)
            if key in MKEYS and h == H_OK and b[:4] == b'EP7B':
                exp[BV.SESS] = 0
            if hp != bytes(exp):
                fails.append(f'R scr{which} {lab}: heap {[i for i in range(1024) if hp[i] != exp[i]][:6]}')
        # group != 0x12: untouched
    for key in MKEYS:
        n += 1
        b = block(mono=('Velvia', 'Velvia', 'Velvia', 'Velvia'))
        rp = scr_run(G['pat'], 1, key, MONO_PM[MKEYS.index(key)], b, group=0x11)
        if struct.unpack_from('<H', EV.live_stack(rp), 32)[0] != key or mem(rp, 'heap') != bytes(b):
            fails.append(f'R group 0x11 {key:#x} changed')
    for lab, key, pm, b, h in r_cases():
        n += 1
        want = model_div(key, pm, b, h)
        (rb, _), (rp, _) = open_run(G['base'], key, pm, b, h), open_run(G['pat'], key, pm, b, h)
        if rp['fault'] or rp['registers']['pc'] != BV.OPEN:
            fails.append(f'R open {lab}: {rp["fault"]}')
            continue
        a0 = rp['registers']['a0']
        if want == key:
            e = EV.same_state(rb, rp, skip=('a2',))
            if e or a0 != PAR:
                fails.append(f'R open {lab}: {e} a0 {a0:#x}')
        else:
            got = struct.unpack_from('<H', G['pat'], a0 - BASE)[0] if BV.DATA[0] <= a0 < BV.DATA[1] else None
            e = EV.same_state(rb, rp, skip=('a0', 'a2'))
            if got != want or e:
                fails.append(f'R open {lab}: key {got} want {want:#x} {e}')
    return n, fails


# ------------------------------------------------------------------ G / D get, default
def get_run(im, word, idv, ra, pm, blk, view_page=1):
    """CALLS entry at the facade word's target with (sp) = mdr = ra; stops at ra (hit) or the chained target."""
    target = struct.unpack_from('<I', im, word - BASE)[0]
    vo = bytearray(0x400)
    vo[396] = view_page
    stack = bytearray([0x5c]) * 0x2000
    struct.pack_into('<I', stack, SP0 - STK, ra)
    regs = dict(SENT, pc=target, sp=SP0, d0=idv, d1=0x11111111, a0=0x1a0a0a0a, a1=OUT, a3=PAR, mdr=ra)
    rg = [Region('stack', STK, bytes(stack), 'rw', True), Region('out', OUT, b'\x99' * 16, 'rw', True),
          Region('vobj', PAR, bytes(vo), 'r'), Region('ra', ra & ~0xfff, b'\xcb' * 0x1000, 'rx')] + \
        regions_common(im, pm, blk)
    chain = G['chain']['ep7_get_next'] if word == BV.W_GET else G['chain']['ep7_def_next']
    for stop in (chain, ra):
        r = execute(rg, regs, stop, limit=200000)
        if not r['fault'] and r['registers']['pc'] == stop:
            break
    return r, regs, chain


def slot_val(blk, m, s, axis):
    if axis == 4:
        return 0
    off = {0: 33, 3: 33, 1: 12, 2: 0}.get(axis, 33)
    v = blk[32 + 64 * (4 + m) + off + s]
    v = v - 256 if v >= 128 else v
    return max(-5, min(5, v))


def check_g():
    fails, n = [], 0
    ras = [int(x, 16) for x in G['spec']['mono_colour_ui']['ra']]
    for m in range(4):
        b = block(mono=('Velvia', 'Portra 400', 'Eterna', None), sess=0x84 if m == 3 else None)
        for pm in (MONO_PM[m], COLOR_PM[m], MONO_PM[(m + 1) % 4]):
            k = MONO_PM.index(pm) if pm in MONO_PM else None          # the slot of the current MONO mode
            hit = k is not None and (b[32 + 64 * (4 + k) + 32] == 1 or (b[BV.SESS] == 0x81 + k))
            for ra in ras[:3] + [ras[-1], BV.PV_RA, 0x60e20123]:
                for page in ((1, 0) if ra == BV.PV_RA else (1,)):
                    n += 1
                    want = hit and (ra in ras or page == 1) and ra != 0x60e20123
                    r, regs, chain = get_run(G['pat'], BV.W_GET, 111, ra, pm, b, page)
                    pc = r['registers']['pc']
                    if want:
                        v = struct.unpack_from('<i', mem(r, 'out'), 0)[0]
                        if r['fault'] or pc != ra or v != COLOR_PM[k] or r['registers']['d0'] != 0 or \
                                r['registers']['sp'] != SP0 or any(r['registers'][k] != SENT[k] for k in ('d2', 'd3', 'a2')):
                            fails.append(f'G 111 m{m} pm {pm} ra {ra:#x}: pc {pc:#x} v {v} {r["fault"]}')
                    else:
                        if r['fault'] or pc != chain or any(r['registers'][k] != regs[k] for k in regs if k != 'pc') or \
                                mem(r, 'out') != b'\x99' * 16:
                            fails.append(f'G 111 m{m} pm {pm} ra {ra:#x} page {page}: miss not transparent pc {pc:#x}')
        for axis in (0, 1, 2, 3, 4, 9):
            for c in range(4):
                for s in (0, 5, 11):
                    idv = [927, 939, 951, 1655][c] + s
                    for pm in (MONO_PM[m], COLOR_PM[c]):
                        bb = bytearray(b)
                        bb[EV.AXIS] = axis
                        e = 32 + 64 * (4 + m)
                        bb[e + 33 + s], bb[e + 12 + s], bb[e + s] = 0x7f, 0xfa, 3     # clamp both ways
                        hit = (c == m and pm == MONO_PM[m])
                        for word in (BV.W_GET, BV.W_DEF):
                            n += 1
                            r, regs, chain = get_run(G['pat'], word, idv, 0x60e20e25, pm, bytes(bb))
                            pc = r['registers']['pc']
                            if hit:
                                want = 0 if word == BV.W_DEF else slot_val(bb, m, s, axis if axis < 5 else 0)
                                v = struct.unpack_from('<i', mem(r, 'out'), 0)[0]
                                if r['fault'] or pc != 0x60e20e25 or v != want or mem(r, 'heap') != bytes(bb):
                                    fails.append(f'{"G" if word == BV.W_GET else "D"} id {idv} m{m} ax {axis}: v {v} want {want} pc {pc:#x}')
                            elif r['fault'] or pc != chain or any(r['registers'][k] != regs[k] for k in regs if k != 'pc'):
                                fails.append(f'{"G" if word == BV.W_GET else "D"} id {idv} m{m} pm {pm} ax {axis}: miss pc {pc:#x}')
    # stale heap: no 'EP7C', session garbage -> MONO slot B&W is not a hit
    b = block(mono=(None, None, None, None), cmark=False)
    b[BV.SESS] = 0x81
    n += 1
    r, regs, chain = get_run(G['pat'], BV.W_GET, 927, 0x60e20e25, 57, b)
    if r['registers']['pc'] != chain:
        fails.append('G stale session without EP7C taken as a hit')
    return n, fails


# ------------------------------------------------------------------ S setter
def set_run(im, idv, val, pm, blk):
    site = BV.SET_SITE
    regs = dict(SENT, pc=site, sp=SP0, d0=idv, d1=val & 0xffffffff, a0=0x1a0a0a0a, a1=0x1a1a1a1a)
    man = Region('man', 0x60827440, b'\xcb\xcb', 'rx')
    rg = [img(im, site, site + 16, 'site'), man] + regions_common(im, pm, blk)
    stops = (G['chain']['ep7_set_next'], 0x60827440, site + 7)
    r = None
    for stop in stops:          # the emulator stops at one pc: run once per candidate, keep the one that stopped
        r = run(rg, regs, stop, limit=300000)
        if r['registers']['pc'] == stop and not r['fault']:
            return r, stop
    return r, None


def check_s():
    fails, n = [], 0
    for m in range(4):
        b = block(mono=('Velvia', 'Portra 400', None, None), sess=0x83 if m == 2 else None)
        colour_or_sess = m in (0, 1, 2)
        for axis in (0, 1, 2, 3, 4):
            for c in (m, (m + 1) % 4):
                for val in (-5, 3, 5, 6, -6):
                    s = 7
                    idv = [927, 939, 951, 1655][c] + s
                    bb = bytearray(b)
                    bb[EV.AXIS] = axis
                    bb[EV.DIRTY] = 0
                    n += 1
                    r, stop = set_run(G['pat'], idv, val, MONO_PM[m], bytes(bb))
                    hit = c == m and colour_or_sess
                    if not hit:
                        if stop != G['chain']['ep7_set_next'] or mem(r, 'heap') != bytes(bb) or \
                                (r['registers']['d0'], r['registers']['d1']) != (idv, val & 0xffffffff):
                            fails.append(f'S miss id {idv} m{m} ax {axis}: stop {stop}')
                        continue
                    exp = bytearray(bb)
                    if axis == 4 or not -5 <= val <= 5:
                        if stop != BV.SET_SITE + 7 or r['registers']['d0'] != 0 or mem(r, 'heap') != bytes(exp):
                            fails.append(f'S refuse id {idv} m{m} ax {axis} val {val}: stop {stop}')
                        continue
                    e = 32 + 64 * (4 + m)
                    exp[e + {0: 33, 3: 33, 1: 12, 2: 0}[axis] + s] = val & 0xff
                    if axis in (1, 2):
                        exp[e + 31] |= 2
                    exp[EV.DIRTY] = 1
                    rg = r['registers']
                    if stop != 0x60827440 or mem(r, 'heap') != bytes(exp) or rg['d0'] != idv or rg['d1'] != sgv(idv) & 0xffffffff \
                            or rg['a0'] != 0x1a0a0a0a or rg['a1'] != 0x1a1a1a1a or rg['mdr'] != BV.SET_SITE + 7:
                        fails.append(f'S hit id {idv} m{m} ax {axis} val {val}: stop {stop} d1 {rg["d1"]:#x} mdr {rg["mdr"]:#x}')
    # COLOR mode: every COLOR id is the chain (editor stock / H/L as v0.14)
    for c in range(4):
        n += 1
        r, stop = set_run(G['pat'], 927 + 12 * c if c < 3 else 1655, 2, COLOR_PM[c], block())
        if stop != G['chain']['ep7_set_next']:
            fails.append(f'S COLOR{c + 1} mode not chained')
    return n, fails


# ------------------------------------------------------------------ P polygon
def poly_run(im, site, idv, pm, blk):
    regs = dict(SENT, pc=site, sp=SP0, d0=idv, d1=0x11111111, a0=0x1a0a0a0a, a1=0x1a1a1a1a)
    rg = [img(im, site, site + 16, 'site')] + regions_common(im, pm, blk)
    out = {}
    for stop in (G['chain']['ep7_poly_next'] if site == BV.POLY_SITE else 0x602afa81, site + 7):
        r = run(rg + ([Region('aget', 0x602afa81, b'\xcb\xcb', 'rx')] if stop == 0x602afa81 else []), regs, stop)
        if not r['fault'] and r['registers']['pc'] == stop:
            return r, stop
    return r, None


def check_p():
    fails, n = [], 0
    for m in range(4):
        b = block(mono=('Velvia', 'Portra 400', 'Eterna', None), sess=0x84 if m == 3 else None)
        for pm in (MONO_PM[m], COLOR_PM[m]):
            n += 1
            r, stop = poly_run(G['pat'], BV.PROF_SITE, 1648, pm, b)
            if pm == MONO_PM[m]:
                if stop != BV.PROF_SITE + 7 or r['registers']['d0'] != m + 1:
                    fails.append(f'P prof m{m}: {stop} d0 {r["registers"]["d0"]}')
            elif stop != 0x602afa81 or r['registers']['d0'] != 1648:
                fails.append(f'P prof m{m} COLOR mode: {stop}')
            for axis in (0, 1, 2, 3, 4):
                bb = bytearray(b)
                bb[EV.AXIS] = axis
                n += 1
                idv = [927, 939, 951, 1655][m] + 4
                r, stop = poly_run(G['pat'], BV.POLY_SITE, idv, pm, bytes(bb))
                if pm == MONO_PM[m]:
                    want = 0 if axis in (3, 4) else slot_val(bb, m, 4, axis)
                    got = r['registers']['d0']
                    got = got - (1 << 32) if got >= 1 << 31 else got
                    if stop != BV.POLY_SITE + 7 or got != want or any(r['registers'][k] != SENT[k] for k in ('d2', 'd3', 'a2', 'a3')):
                        fails.append(f'P sector m{m} ax {axis}: {stop} {got} want {want}')
                elif stop != G['chain']['ep7_poly_next'] or r['registers']['d0'] != idv:
                    fails.append(f'P sector m{m} COLOR mode ax {axis}: {stop}')
    return n, fails


# ------------------------------------------------------------------ U Film page
def ud_run(im, key, d, pm, blk, L, getret=0, stop=None):
    word = 12 if d > 0 else 16
    rec_a = BV.RECORDS[key] + word
    po = EV.parent_obj2(key=key)
    src = (f' mov {rec_a:#x},a1\n mov (a1),a2\n mov {PAR:#x},a0\n mov {0x9004 if d > 0 else 0x9006:#x},d0\n'
           f' mov 0x11111111,d1\n mov 0x1a1a1a1a,a1\n calls (a2)\n')
    code, sy = asm(src, DRV)
    rg = [Region('drv', DRV, code, 'rx'), Region('par', PAR, bytes(po), 'r')] + \
        regions_common(im, pm, blk, L=L) + EV.fac_regions(getret)
    chain = G['chain']['ep7_up_next'] if d > 0 else G['chain']['ep7_down_next']
    r = run(rg, {'pc': DRV}, chain if stop == 'chain' else sy['done'], limit=3_000_000)
    return r, sy, chain


def items(m_mask_ok=True):
    """position list of a MONO slot: colour looks with the MONO mask (pos j+1), presets, B&W."""
    n = n_looks()
    looks = [j + 1 for j in range(n) if rec(j)[45] == 0 and rec(j)[46] & 2]
    return looks, n, len(G['ps'])


def check_u():
    fails, n = [], 0
    looks, nl, npre = items()
    N = nl + npre + 1
    for m, mono, sess in ((0, ('Velvia', None, None, None), None), (1, (None, 'Portra 400', None, None), None),
                          (2, (None, None, None, None), 0x83)):
        for d in (1, -1):
            blk = block(axis=3, mono=mono, sess=sess)
            L = L_block(blk)
            pos = 0
            seq = [p for p in range(1, N + 1) if p in looks or p > nl]
            for step in range(len(seq) + 2):
                n += 1
                r, sy, chain = ud_run(G['pat'], CKEYS[m], d, MONO_PM[m], bytes(blk), bytes(L))
                if r['fault'] or r['registers']['pc'] != sy['done'] or r['registers']['d0'] != 1:
                    fails.append(f'U m{m} d{d} step {step}: {r["fault"]} pc {r["registers"]["pc"]:#x}')
                    break
                # model
                i = seq.index(pos) if pos in seq else (-1 if d > 0 else len(seq))
                pos = seq[(i + d) % len(seq)]
                hp = mem(r, 'heap')
                e = 32 + 64 * (4 + m)
                nm = hp[544 + 16 * (4 + m):560 + 16 * (4 + m)]
                log = EV.fac_log(r)
                sets = [(x[1], x[3]) for x in log if x[0] == 2]
                if pos <= nl:
                    want_e, want_n = LB.place(rec(pos - 1), 4 + m), bytes(name_of(pos - 1))
                    want_s, want_sets = 0, 0
                elif pos <= nl + npre:
                    p = G['ps'][pos - nl - 1]
                    want_e, want_n = bytes(64), p['name'].encode().ljust(16, b'\0')
                    want_s = 0x81 + m
                    want_sets = [(G['ids'][m][f], p['values'][f] & 0xffffffff) for f in range(8)]
                else:
                    want_e, want_n, want_s, want_sets = bytes(64), bytes(16), 0x81 + m, []
                ok = hp[e:e + 64] == want_e and nm == want_n and hp[BV.SESS] == want_s and hp[EV.DIRTY] == 1 and \
                    hp[BV.MPOS + m] == pos and struct.unpack_from('<I', hp, 672)[0] == NMAGIC
                if want_sets:
                    ok &= sets[:8] == want_sets
                else:
                    ok &= len(sets) <= 1               # ed_poke's cursor re-write only
                others = bytearray(hp)
                ref = bytearray(blk)
                for a, z in ((e, 64), (544 + 16 * (4 + m), 16), (BV.SESS, 1), (BV.MPOS + m, 1), (EV.DIRTY, 1), (672, 4)):
                    others[a:a + z] = ref[a:a + z] = bytes(z)
                ok &= bytes(others) == bytes(ref) and mem(r, 'L') == bytes(L)
                if not ok:
                    fails.append(f'U m{m} d{d} step {step} pos {pos}: entry {hp[e:e + 64] == want_e} name {nm} '
                                 f'sess {hp[BV.SESS]:#x} sets {sets[:3]} others {bytes(others) == bytes(ref)}')
                    break
                blk = bytearray(hp)
            G.setdefault('picked', {})[(m, d)] = bytes(blk)
    # misses -> chain (fm_up / fm_down) with registers intact
    for lab, key, pm, b in (('page S', CKEYS[0], 57, block(axis=0)), ('COLOR mode', CKEYS[0], 54, block(axis=3)),
                            ('other key', CKEYS[1], 57, block(axis=3)), ('MONO3 B&W no session', CKEYS[2], 59, block(axis=3)),
                            ('no LOOKS.BIN', CKEYS[0], 57, _nofilm())):
        for d in (1, -1):
            n += 1
            r, sy, chain = ud_run(G['pat'], key, d, pm, bytes(b), bytes(L_block(b)), stop='chain')
            rb, _, _ = ud_run(G['base'], key, d, pm, bytes(b), bytes(L_block(b)), stop='chain')
            e = EV.same_state(rb, r)
            if r['fault'] or rb['fault'] or r['registers']['pc'] != chain or e or mem(r, 'heap') != bytes(b) or EV.fac_log(r):
                fails.append(f'U miss {lab} d{d}: not transparent ({r["fault"]} {e})')
    return n, fails


def _nofilm():
    b = block(axis=3)
    struct.pack_into('<I', b, O['fmark'], FB.XMAGIC)
    return b


# ------------------------------------------------------------------ L label
def check_l():
    fails, n = [], 0
    gcode, _ = asm(EV.GUIDE_STUB, EV.LE.STOCK['ep7_guide'])
    for m, mono, sess, want in ((0, ('Velvia', None, None, None), None, 'Film: Velvia'),
                                (1, (None, 'Portra 400', None, None), None, 'Film: Portra 400'),
                                (2, (None, None, None, None), 0x83, 'Film: B&W'),
                                (0, ('Kodachrome64', None, None, None), None, 'Kodachrome64')):
        for axis, pm in ((3, MONO_PM[m]), (0, MONO_PM[m]), (3, COLOR_PM[m])):
            n += 1
            b = block(axis=axis, mono=mono, sess=sess)
            if m == 2 and sess:
                pass
            src = (f' mov {BV.W_GUIDE:#x},a1\n mov (a1),a1\n mov {EV.VOBJ:#x},a0\n mov 0x0d0d0d0d,d0\n calls (a1)\n')
            code, sy = asm(src, DRV)
            vo = bytearray([0xa5]) * 0x200 + struct.pack('<3I', 4, 2755, 0x600d) + bytes(0x1f4)
            res = {}
            for nm_, im in (('base', G['base']), ('pat', G['pat'])):
                rg = [Region('drv', DRV, code, 'rx'), img(im, EV.LE.PARTS_IMG, EV.LE.PARTS_IMG + 24, 'parts', 'r'),
                      img(im, EV.LE.VIEW[0], EV.LE.VIEW[1], 'view'), Region('guide', EV.LE.STOCK['ep7_guide'], gcode, 'rx'),
                      Region('vobj', EV.VOBJ, bytes(vo), 'rw', True)] + regions_common(im, pm, b, L=L_block(b)) + \
                    EV.fac_regions(0, pm)
                res[nm_] = run(rg, {'pc': DRV}, sy['done'])
            rb, rp = res['base'], res['pat']
            if rp['fault'] or rp['registers']['pc'] != sy['done']:
                fails.append(f'L m{m} ax {axis}: {rp["fault"]}')
                continue
            pv = mem(rp, 'vobj')
            txt = ''.join(chr(struct.unpack_from('<H', pv, 52 + 2 * i)[0]) for i in range(33)).split('\0')[0]
            if axis == 3 and pm == MONO_PM[m]:
                if struct.unpack_from('<H', pv, 44)[0] != 5 or txt != want or rp['registers']['d0'] != rb['registers']['d0']:
                    fails.append(f'L m{m}: {txt!r} want {want!r}')
            elif pv != mem(rb, 'vobj') or rp['registers']['d0'] != rb['registers']['d0']:
                fails.append(f'L m{m} ax {axis} pm {pm}: label differs from base ({txt!r})')
    return n, fails


# ------------------------------------------------------------------ T save / reload round trip
def save_run(blk):
    old = (ROOT / 'releases/v0.14/card/EP7MOD/BUNDLES.BIN').read_bytes()
    fs = EV.fs_image({2: old})
    stack = bytearray([0x5c]) * 0x2000
    struct.pack_into('<I', stack, SP0 - STK + 16, EV.B3.EV_PRESS)
    im = G['pat']
    rg = [Region('stack', STK, bytes(stack), 'rw', True), img(im, 0x605b7180, 0x605b7800, 'sec3'),
          img(im, 0x61242900, 0x61243000, 'sec6'), img(im, 0x601e2c3c, 0x601e383c, 'evf'),
          img(im, 0x6143a400, 0x6143a800, 'sec9'), Region('L', L_AT, bytes(L_block(blk)), 'rw', True),
          Region('fs', EV.FS, bytes(fs), 'rw', True), Region('sbuf', EV.S_BUF, b'\xcc' * 2048, 'rw', True)] + \
        EV.fs_regions() + EV.state_regions(H_OK, blk)
    regs = dict(SENT, sp=SP0, pc=EV.LE.SD_BACK, d0=0xd0d0d0d0, d1=0xd1d1d1d1, a0=0xa0a0a0a0, a1=0xa1a1a1a1)
    return execute(rg, regs, EV.B3.SITE_RET, limit=5_000_000, timeout=120), old


def check_t():
    fails, n = [], 0
    MV = _load('ep7_mono_colour_v15_verify_mc', ROOT / 'tools/ep7_mono_colour_v15_verify.py')
    # picks: MONO1 -> colour (Velvia step), MONO2 -> preset, MONO3 -> B&W, via the Film page model state
    blk = block(axis=3, mono=('Velvia', 'Portra 400', None, None))
    L = L_block(blk)
    for m, steps in ((0, 2), (1, n_looks() + 2), (2, 0)):
        for _ in range(steps):
            r, sy, _ = ud_run(G['pat'], CKEYS[m], 1, MONO_PM[m], bytes(blk), bytes(L))
            blk = bytearray(mem(r, 'heap'))
    blk[EV.DIRTY] = 1
    n += 1
    r, old = save_run(bytes(blk))
    if r['fault'] or r['registers']['pc'] != EV.B3.SITE_RET:
        return n, [f'T save: {r["fault"]} pc {r["registers"]["pc"]:#x}']
    files = EV.fs_files(mem(r, 'fs'))
    want = EV.expected_image(blk)
    if files.get('BIN') != want or files.get('NEW') != want or files.get('BAK') != old:
        fails.append(f'T saved files {sorted(files)} != heap image')
    probs = EV.BIN.check_file(want) + EV.BIN.check_names(want[544:])
    if probs:
        fails.append(f'T loader rules reject the saved file: {probs}')
    # power cycle: the loader publishes bytes 0..679 at P (names, EP7N); editor state starts fresh
    rb = bytearray(1024)
    rb[:680] = want
    rb[680:] = bytes([0xa5]) * 344                       # stale heap past the file
    for m in range(4):
        key = MKEYS[m]
        n += 1
        exp = model_div(key, MONO_PM[m], rb)
        rp = scr_run(G['pat'], 1, key, MONO_PM[m], bytes(rb))
        got = struct.unpack_from('<H', EV.live_stack(rp), 32)[0]
        if rp['fault'] or got != exp:
            fails.append(f'T reload MONO{m + 1}: key {got:#x} want {exp:#x}')
    # capture after reload: the reloaded table through the real selector (flashed position = what tbl_idx returns)
    tab = bytes(want[32:544])
    pat = MV.MV.with_table(MV.oc.parse(MV.BP.build(G['spec'], MV.BP.STOCK.read_bytes())[0])[0].payload, tab)
    stock = MV.oc.parse(MV.BP.build(G['spec'], MV.BP.STOCK.read_bytes())[1])[0].payload
    for p in (1, 2, 3, 4):
        n += 1
        e = tab[64 * (3 + p):64 * (4 + p)]
        okp, mp, _ = MV.MV.sel_run(pat, mode=12, profile=p)
        oks, ms, _ = MV.MV.sel_run(stock, mode=12, profile=p)
        if e[32] == 1:
            v = dict(colour=1, sat=list(struct.unpack('<12b', e[33:45])), hue=list(struct.unpack('<12b', e[:12])),
                     light=list(struct.unpack('<12b', e[12:24])), hl=bool(e[31] & 2))
            ref = MV.MV.with_table(pat, MV.MV.ref_table(tab, {3 + p: v}))
            okr, mr, _ = MV.MV.sel_run(ref, mode=11, profile=p, sat=v['sat'])
            good = okp and okr and mp['out'] == mr['out'] and mp['out'] != ms['out']
        else:
            good = okp and oks and mp['out'] == ms['out']
        if not good:
            fails.append(f'T reload capture MONO{p}: colour {e[32]}')
    G['t_table'] = tab
    return n, fails



# ------------------------------------------------------------------ K mc_pick (API for the mono picker)
def check_k():
    fails, n = [], 0
    src = (f' mov {G["sym"]["mc_pick"]:#x},a2\n mov ({OUT:#x}),d0\n mov ({OUT + 4:#x}),d1\n mov 0x1a0a0a0a,a0\n'
           f' mov 0x1a1a1a1a,a1\n calls (a2)\n')
    code, sy = asm(src, DRV)
    for m in range(4):
        for j in (0, 5, n_looks() - 1, n_looks(), 255, -1):
            for lab, b in (('B&W slot', block(axis=0, mono=(None, None, None, None))), ('no table', None)):
                n += 1
                b = b if b is not None else block(axis=0)
                h = H_OK if lab != 'no table' else 0
                mm = m if j != -1 else 7
                rg = [Region('drv', DRV, code, 'rx'), Region('out', OUT, struct.pack('<ii', mm, j if j != -1 else 0), 'r')] + \
                    regions_common(G['pat'], 57, b, h=h, L=L_block(b))
                r = run(rg, {'pc': DRV, 'mdr': 0x3d3d3d3d}, sy['done'])
                ok_in = h == H_OK and 0 <= j < n_looks() and mm < 4 and rec(j)[45] == 0 and rec(j)[46] & 2
                hp = mem(r, 'heap')
                exp = bytearray(b)
                if ok_in:
                    e = 32 + 64 * (4 + m)
                    exp[e:e + 64] = LB.place(rec(j), 4 + m)
                    exp[544 + 16 * (4 + m):560 + 16 * (4 + m)] = name_of(j)
                    exp[EV.DIRTY] = 1
                    exp[BV.MPOS + m] = j + 1
                    exp[BV.SESS] = 0
                    struct.pack_into('<I', exp, 672, NMAGIC)
                bad = r['fault'] or r['registers']['pc'] != sy['done'] or r['registers']['d0'] != int(bool(ok_in)) or \
                    hp != bytes(exp) or any(r['registers'][k] != SENT[k] for k in ('d2', 'd3', 'a3')) or \
                    r['registers']['mdr'] != sy['done']
                if bad:
                    fails.append(f'K m{m} j{j} {lab}: d0 {r["registers"]["d0"]} heap {hp == bytes(exp)} {r["fault"]}')
    return n, fails

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spec', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--parts', default='RGSPULTK')
    a = ap.parse_args()
    init(a.spec)
    res, allf = {}, []
    for p, f in (('R', check_r), ('G', check_g), ('S', check_s), ('P', check_p), ('U', check_u), ('L', check_l),
                 ('T', check_t), ('K', check_k)):
        if p not in a.parts:
            continue
        n, fails = f()
        res[p] = dict(n=n, failed=len(fails), fails=fails[:40])
        allf += fails
        print(f'{p} {n - len(fails)}/{n}' + ''.join('\n  FAIL ' + x for x in fails[:12]), flush=True)
    print('PASS' if not allf else 'FAIL')
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.spec), parts=res, passed=not allf,
                                          scope='emulator only; stand-ins for the stock getter, facade, manager, '
                                                'file service; no camera'), indent=1))
    sys.exit(0 if not allf else 1)


if __name__ == '__main__':
    main()
