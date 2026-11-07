#!/usr/bin/env python3
"""v0.26 movie colour checks (emulator only, offline). Tests what this patch could break, plus anti-brick.
  .venv/bin/python -I patches/v026_movie/verify.py releases/v0.25/edits.json generated/v026_movie/wheel/edits.json
K key via real 0x60316bc7/0x60324d6b/mapper, M message +20, S effective S via the real getter, B WB via wb_get, P lv/tone profile, C constructor + lv_art:
  v0.25 byte-for-byte unless movie + Vivid + card table. W wheel spoofs. L the real Live Control handler. D image diff only at our sites (loader / save / look code untouched). A anti-brick.
"""
import os, hashlib, importlib.util, json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
W = _load('ep7_wb_v', ROOT / 'tools/ep7_verify_wb.py')
Bd = _load('ep7_v026_movie_build', ROOT / 'patches/v026_movie/build.py')
Region, execute, BP, oc = W.Region, W.execute, W.BP, W.oc
BASE = 0x60020020
SB3 = Bd.SB3
HANDLE, POOL, FS = 0x41, 0xa1f8d800, 0x18000000
REC, MSG, OUT, JOB = 0x19000000, 0x1a000000, 0x1b000000, 0x1c000000
MODES = (1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 100)
STATES = ('none', 'tried', 'card', 'badmagic')


def image(spec):
    m = bytearray((ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes())
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16) - BASE; n = bytes.fromhex(e['new']); m[a:a + len(n)] = n
    return bytes(m)


def img(m, lo, hi, name, perm='rx'):
    return Region(name, lo, m[lo - BASE:hi - BASE], perm)


P_AT, P2_AT = POOL + HANDLE - 1, POOL + HANDLE - 1 + 0x800
SLOT = bytearray(64)
SLOT[:24] = bytes(i % 8 for i in range(24)); SLOT[25:28] = bytes([1, 3, 0xfd]); SLOT[33:45] = bytes(x & 255 for x in (5, -5, 4, -4, 3, -3, 2, -2, 1, -1, 0, 1))
SLOT = bytes(SLOT)
MARKS = False                     # wheel build: 'card' carries a Movie slot; 'nofile' doesn't


def block(tab, h, p2):
    b = bytearray(1024); b[:4] = b'EP7B'; b[32:32 + len(tab)] = tab
    if p2:
        struct.pack_into('<3I', b, Bd.VM, Bd.VMAGIC, P2_AT, h)
    return bytes(b)


def st(m, state, table=None, swapped=False):
    h = HANDLE if state in ('card', 'badmagic', 'nofile') else 0xffff if state == 'tried' else 0
    if swapped:
        h = HANDLE + 0x800
    r = [Region('state', 0x622cbcc0, struct.pack('<HHI', 0, h, 0), 'rw' if MARKS else 'r')]
    if state in ('card', 'badmagic', 'nofile'):
        t = bytes(table or bytes(512)); magic = b'EP7B' if state != 'badmagic' else b'XXXX'
        if not MARKS:
            r.append(Region('pool', P_AT, magic + bytes(28) + t, 'r'))
        else:
            has = state == 'card'
            r.append(Region('pool', P_AT, magic + block(t, HANDLE, has)[4:], 'rw'))
            if has:
                q = bytearray(block(t, HANDLE, True)); q[224:288] = SLOT
                r.append(Region('pool2', P2_AT, bytes(q), 'rw'))
    return r


def code(m):
    return [img(m, 0x601e25ec, 0x601e283c, 'mv'), img(m, 0x601e0e3c, 0x601e103c, 'lv'), img(m, 0x601e103c, 0x601e113c, 'toneA'), img(m, 0x601e113c, 0x601e123c, 'lvart'),
            img(m, 0x6055e700, 0x6055e7f0, 'sec2'), img(m, 0x60210900, 0x60210b00, 'flash', 'r')]


def getter(m, props):
    return [img(m, *W.GETTER_CODE, 'getter'), img(m, *W.XLATE, 'xlate', 'r'), Region('cpuid', W.CPUID, bytes(4), 'r'), *W.registry(props)]


def t_key(new, base):
    bad, n, on = [], 0, 0
    for pm in MODES:
        for mv in (0, 1, 2):
            for state in STATES:
                for v925 in (0, 2):
                    res = []
                    for m in (base, new):
                        rec = bytearray(980); rec[294] = pm; rec[925] = v925; struct.pack_into('<I', rec, 176, mv)
                        stack = bytearray(0x1000); struct.pack_into('<I', stack, 0x804, OUT)
                        call = Region('call', FS, b'\xdd' + struct.pack('<i', 0x60316bc7 - FS) + b'\xb0\x18', 'rx')
                        rg = [call, img(m, 0x60316bc7, 0x60316c4d, 'f1'), img(m, 0x60324d6b, 0x60324dc1, 'f2'), img(m, 0x60349297, 0x603494d7, 'map'),
                              img(m, 0x604f8a78 - 0x1000, 0x604f8a78, 'tbl', 'r'), img(m, 0x601e25ec, 0x601e283c, 'mv'), Region('ms', 0x4700115e, bytes.fromhex('dea008'), 'rx'),
                              Region('stack', 0x18010000, bytes(stack), 'rw'), Region('rec', REC, bytes(rec), 'rw', True), Region('out', OUT, bytes(8), 'rw', True), *st(m, state)]
                        r = execute(rg, dict(pc=FS, sp=0x18010800, a0=REC + 292, a1=REC, d0=0, d1=0), FS + 7, limit=20000)
                        mem = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
                        res.append((r['fault'], mem['out'], mem['rec'], {k: r['registers'][k] for k in ('sp', 'd2', 'd3', 'a2', 'a3')}))
                    n += 1
                    active = pm == 1 and mv == 1 and state == 'card' and v925 == 0
                    on += active
                    want = bytes.fromhex('00000b00') + res[0][1][4:] if active else res[0][1]
                    if res[1][0] or res[1][1] != want or res[1][2] != res[0][2]:
                        bad.append((pm, mv, state, v925, res[1][0], res[1][1].hex(), res[0][1].hex()))
    return n, on, bad


def t_msg(new, base):
    bad, n = [], 0
    for pm in MODES:
        for mv in (0, 1):
            for state in STATES:
                for raw in (0, 3):
                    res = []
                    for m in (base, new):
                        rec = bytearray(980); rec[294] = pm; struct.pack_into('<I', rec, 176, mv); rec[944] = raw
                        rg = [img(m, 0x60315900, 0x60315918, 'site'), img(m, 0x601e25ec, 0x601e283c, 'mv'), Region('rec', REC, bytes(rec), 'r'), Region('msg', MSG, bytes(64), 'rw', True), *st(m, state)]
                        r = execute(rg, dict(pc=0x60315900, sp=FS + 0x100, a0=REC + 941, a1=MSG, d3=REC + 941, d1=0, d2=0, a2=0x2222, a3=0x3333), 0x60315908, limit=2000)
                        res.append((r['fault'], bytes.fromhex(r['memory'][0]['hex'])[20], {k: r['registers'][k] for k in ('a0', 'a1', 'a2', 'a3', 'd1', 'd2', 'd3', 'sp')}))
                    n += 1
                    want = 4 if pm == 1 and mv == 1 and state == 'card' else raw
                    if res[1][0] or res[1][1] != want or res[1][2] != res[0][2]:
                        bad.append((pm, mv, state, raw, res[1]))
    return n, bad


def t_s(new, base):
    bad, n = [], 0
    S4 = struct.pack('<48h', *[i - 40 for i in range(48)])
    eff = struct.pack('<12h', *range(0x10, 0x1c))
    for pm in MODES:
        for mv in (0, 1):
            for state in STATES:
                for i in (0, 5, 11):
                    res = []
                    for m in (base, new):
                        rec = bytearray(980); rec[294] = pm; struct.pack_into('<I', rec, 176, mv)
                        s = 0x6030bd5d
                        rg = [img(m, s - 16, s + 16, 'site'), img(m, 0x601e25ec, 0x601e283c, 'mv'), *getter(m, {0xf6ea: eff, 0xf6fa: S4}), Region('rec', REC, bytes(rec), 'r'),
                              Region('stack', W.STACK, bytes([W.STACK_FILL] * 0x2000), 'rw', True), *st(m, state)]
                        r = execute(rg, dict(pc=s, sp=W.SP0, d0=0xf6ea, d1=i, a0=0, a2=0x2222, a3=REC + 704, d2=0x1111, d3=0x3333), s + 7, limit=8000)
                        res.append((r['fault'], r['registers']))
                    n += 1
                    want = (36 + i - 40) & 0xffffffff if pm == 1 and mv == 1 and state == 'card' else 0x10 + i
                    rr = res[1][1]
                    if res[1][0] or rr['d0'] != want or any(rr[k] != res[0][1][k] for k in ('d2', 'd3', 'a2', 'a3', 'sp')):
                        bad.append((pm, mv, state, i, res[1][0], hex(rr['d0'])))
    return n, bad


def slot3():
    t = bytearray(512)
    t[64 * 3 + 25], t[64 * 3 + 26], t[64 * 3 + 27] = 1, 4, 0xfd
    return t


def t_wb(new, base):
    bad, n = [], 0
    for pm in (1, 3, 11):
        for mv in (0, 1):
            for state in STATES:
                for s, key, val in ((0x6030bb5b, 0x84f9, 4), (0x6030bb6e, 0x9679, -3)):
                    for cat in (1, 3):
                        res = []
                        for m in (base, new):
                            rec = bytearray(980); rec[294] = pm; struct.pack_into('<I', rec, 176, mv)
                            pr = {key: bytes([2, 2]), 0x9481: bytes([pm]), 0x9d11: bytes([0]), 0xf6b1: bytes([0]), 33057 & 0xffff: bytes([cat]), 0xf731: bytes([0])}
                            rg = [img(m, s - 16, s + 16, 'site'), *code(m), *getter(m, pr), Region('rec', REC, bytes(rec), 'r'), Region('stack', W.STACK, bytes([W.STACK_FILL] * 0x2000), 'rw', True), *st(m, state, slot3())]
                            r = execute(rg, dict(pc=s, sp=W.SP0, d0=key, d1=0, a0=0, a2=REC + 698, a3=0x3333, d2=0x1111, d3=0x2222), s + 7, limit=20000)
                            res.append((r['fault'], r['registers']))
                        n += 1
                        active = pm == 1 and mv == 1 and state == 'card' and cat != 3
                        rr = res[1][1]
                        wrong = (rr['d0'] & 0xffffffff != val & 0xffffffff) if active else rr['d0'] != res[0][1]['d0']
                        if res[1][0] or wrong or any(rr[k] != res[0][1][k] for k in ('d2', 'd3', 'a2', 'a3', 'sp')):
                            bad.append((pm, mv, state, hex(s), cat, res[1][0], hex(rr['d0']), hex(res[0][1]['d0'])))
    return n, bad


def t_prof(new, base):
    bad, n = [], 0
    for s in (Bd.LV_GET, Bd.TONE_GET):
        for pm in (1, 2, 11):
            for prof in (0, 2, 4):
                for typ in (0x30, 0x42, 0x00, 0x120):
                    res = []
                    for m in (base, new):
                        jb = bytearray(0x3000); struct.pack_into('<H', jb, 20, typ)
                        rg = [img(m, s - 16, s + 16, 'site'), img(m, 0x601e25ec, 0x601e283c, 'mv'), *getter(m, {0xf6b1: bytes([prof]), 0x9481: bytes([pm])}),
                              Region('ctx', OUT, struct.pack('<II', 0, JOB + 11364), 'r'), Region('job', JOB, bytes(jb), 'r'), Region('stack', W.STACK, bytes([W.STACK_FILL] * 0x2000), 'rw', True)]
                        r = execute(rg, dict(pc=s, sp=W.SP0, d0=0xf6b1, d1=0, a0=0, a2=OUT, d2=0x1111, d3=0x2222, a3=0x3333), s + 7, limit=8000)
                        res.append((r['fault'], r['registers']))
                    n += 1
                    want = 4 if prof == 0 and pm == 1 and typ & 0xf0 in (0x30, 0x40) else prof
                    rr = res[1][1]
                    if res[1][0] or rr['d0'] != want or any(rr[k] != res[0][1][k] for k in ('d2', 'd3', 'a2', 'a3', 'sp')):
                        bad.append((hex(s), pm, prof, hex(typ), res[1][0], hex(rr['d0'])))
    return n, bad


def t_cons(new, base):
    """Constructor pre-dispatch. Bloom slot so lv_art would act; dispatch stub returns at once."""
    bad, n, s, tab = [], 0, 0x60353c6f, bytearray(512)
    for k in range(4):
        tab[64 * k + 28], tab[64 * k + 29], tab[64 * k + 31] = 1, 3, 3
    for ret in (0x60321eaf, 0x60000000):
        for key in (11, 1):
            for pm in (1, 11):
                for typ in (0x31, 0x40, 0x131):
                    res = []
                    for m in (base, new):
                        jb = bytearray(15600); struct.pack_into('<I', jb, 11308, key); struct.pack_into('<H', jb, 20, typ); struct.pack_into('<I', jb, 16, 0x80000)
                        stk = bytearray([W.STACK_FILL] * 0x2000); struct.pack_into('<I', stk, 0x1800 + 44, ret)
                        rg = [img(m, s, s + 6, 'site'), *code(m), Region('disp', Bd.DISPATCH, bytes.fromhex('dfb010'), 'rx'), *getter(m, {0xf6b1: bytes([0 if pm == 1 else 2]), 0x9481: bytes([pm])}),
                              Region('job', JOB, bytes(jb), 'rw', True), Region('stack', W.STACK, bytes(stk), 'rw', True), Region('resume', 0x60353c75, b'\xcb\xcb', 'rx'), *st(m, 'card', tab)]
                        r = execute(rg, dict(pc=s, sp=W.SP0, a3=JOB, d2=0x1111, d3=0x2222, a2=0x3333), 0x60353c75, limit=20000)
                        mem = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
                        res.append((r['fault'], mem['job'], r['registers']))
                    n += 1
                    act = ret == 0x60321eaf and key == 11 and pm == 1
                    want = bytearray(res[0][1])
                    if act:
                        struct.pack_into('<I', want, 16, 0)
                    rr = res[1][2]
                    if res[1][0] or res[1][1] != bytes(want) or any(rr[k] != res[0][2][k] for k in ('d2', 'd3', 'a2', 'a3', 'sp')):
                        bad.append((hex(ret), key, pm, hex(typ), res[1][0], [i for i in range(len(want)) if res[1][1][i] != want[i]][:8]))
    return n, bad


def stub(addr, text, name):
    c, _, _, _ = SB3.assemble(' .am33_2\n .text\n .global _start\n_start:\n' + text + '\n', addr, {})
    return Region(name, addr, c, 'rx')


def sget(sid44, pm):
    return stub(0x602af887, f' cmp 44,d0\n bne 1f\n mov {sid44},d0\n ret [],4\n1:\n mov {pm},d0\n ret [],4', 'sget')


GLOB = 0x61fc4300
FAC = 0x18020000
STK = 0x18010800


def lc_run(m, row, value, s44, s1337, state, wcode):
    """The real Live Control handler 0x60e593be on an INFO release (0x9015), screen rc 2. Stubs for the screen, facade and 281."""
    VT = FAC + 0x10; val = {44: s44, 1337: s1337, 9: 0, 111: value}
    fac = struct.pack('<I', VT) + bytes(12) + struct.pack('<4I', FAC + 0x180, 0, FAC + 0x100, 0)
    get = stub(FAC + 0x100, ''.join(f' cmp {k},d0\n bne 1f\n mov {v},d0\n mov d0,(a1)\n clr d0\n rets\n1:\n' for k, v in val.items()) + ' clr d0\n mov d0,(a1)\n rets', 'fget')
    rg = [img(m, 0x60e593be, 0x60e5990a, 'lc'), wcode, sget(s44, value), *st(m, state),
          stub(0x60e4d032, ' mov 2,d0\n ret [d2,d3,a2,a3],60', 'scr'), stub(0x4700115e, ' ret [d2,a2],8', 'ms'), stub(0x60cfec91, ' ret [],4', 'c1'),
          stub(0x60cfeca9, ' ret [d2,a2],16', 'c2'), stub(0x60e4d144, ' clr d0\n ret [],4', 'idx'), stub(0x60e4d157, f' mov {row},d0\n ret [d2],8', 'row'),
          stub(0x607f9062, f' mov {FAC},a0\n ret [],4', 'facg'), stub(0x607b3c32, f' mov {FAC},a0\n ret [],4', 'capg'),
          stub(0x60ee01a1, ' ret [d2,d3,a2,a3],20', 'c281'), stub(0x60ee015f, ' mov 1,d0\n ret [d2,d3,a2,a3],20', 'g281'), stub(0x60e9debc, ' ret [a2,a3],8', 'log'),
          stub(0x60ea3a84, ' ret [],0', 'a84'), stub(0x60e4cea8, ' mov 0,a0\n ret [d2,d3,a2,a3],52', 'scrl'), stub(0x60ea114b, ' ret [d2,d3,a2,a3],56', 'ev'), stub(0x60ea12ca, ' ret [d2,d3,a2,a3],100', 'ca'),
          Region('fac', FAC, fac, 'r'), get, stub(FAC + 0x180, ' clr d0\n rets', 'cap'), Region('glob', GLOB, bytes(0x100), 'rw', True), Region('stack', 0x18010000, bytes(0x1000), 'rw')]
    if MARKS:
        rg[3] = Region('state', 0x622cbcc0, rg[3].data, 'rw', True)
    r = execute(rg, dict(pc=0x60e593be, sp=STK, d0=0x9015, a1=0, d2=0x1111, d3=0x2222, a2=0x3333, a3=0x4444), 0x60e59907, limit=20000)
    mem = {x.get('name', i): bytes.fromhex(x['hex']) for i, x in enumerate(r['memory'])}
    vals = list(mem.values())
    s_ = struct.unpack_from('<H', vals[0], 2)[0]; g = vals[-1]
    return r['fault'], r['registers']['d0'] & 0xffff, struct.unpack_from('<H', g, 0x70)[0], struct.unpack_from('<I', g, 0x84)[0], s_


def t_lc(new, base):
    global MARKS
    bad, n = [], 0
    wn, wb = img(new, Bd.W_AT, Bd.W_END, 'mvw'), img(base, Bd.W_AT, Bd.W_END, 'mvw')
    for state in STATES:
        for s44 in (0, 1):
            for s1337 in (0, 1):
                for row in (111, 9):
                    for value in (0, 1, 54, 64, 21, 8):
                        on = state == 'card' and s44 == 1 and s1337 == 0 and row == 111 and value == 0
                        a = lc_run(new, row, value, s44, s1337, state, wn); b = lc_run(base, row, value, s44, s1337, state, wb); n += 1
                        want = (None, 0x0407, Bd.CKEY, 1, HANDLE + 0x800) if on else b
                        if a[0] or b[0] or a != want:
                            bad.append((state, s44, s1337, row, value, a, b))
    return n, bad


def caller(t, regs='[d2,d3,a2,a3],24'):
    c, _, _, _ = SB3.assemble(f' .am33_2\n .text\n .global _start\n_start:\n call tgt,{regs}\n nop\n nop\n', 0x18040000, dict(tgt=t))
    return Region('caller', 0x18040000, c, 'rx')


def t_ui(new, base, sym):
    bad, n = [], 0
    u32 = lambda m, a: struct.unpack_from('<I', m, a - BASE)[0]
    code = img(new, Bd.W_AT, Bd.W_END, 'mvw')
    sm = lambda a: a + struct.unpack_from('<i', base, a + 1 - BASE)[0]
    new_spec = json.loads(Path(sys.argv[2]).read_text())
    nget = int(new_spec['v026_movie']['get_next'], 16)
    bim = new
    nset, npoly = sm(Bd.SET_SITE), sm(Bd.POLY2)
    RET = 0x60e99998
    retr = Region('ret', RET, b'\xcb\xcb', 'rx')
    def stack_with(ra):
        stk = bytearray(0x1000); struct.pack_into('<I', stk, 0x800, ra); return Region('stack', 0x18010000, bytes(stk), 'rw')
    for sw in (False, True):
        for gid, ra, val in ((1655, RET, SLOT[33]), (1660, RET, 0xfffffffd), (1666, RET, SLOT[44]), (1654, RET, None), (1667, RET, None), (111, Bd.RA[0], 64), (111, Bd.RA_G[0], 64), (111, Bd.RA_G[1], 64), (111, RET, None), (15272, Bd.CC_RA[1], 1646), (15272, RET, None), (1686, RET, 0), (927, RET, None)):
            hit = sw and val is not None
            rr_ = Region('ra', ra & ~3, b'\xcb' * 8, 'rx') if ra != RET else retr
            rg = [code, sget(1, 0), *st(new, 'card', swapped=sw), Region('out', OUT, bytes(4), 'rw', True), Region('view', 0x18030000, bytes(0x200), 'r'), stack_with(ra), rr_, Region('n', nget, b'\xcb', 'rx')]
            r = execute(rg, dict(pc=int(sym['mv_get'], 16), sp=STK, d0=gid, a0=0xa0a0, a1=OUT, d2=0x1111, d3=0x2222, a2=0x3333, a3=0x18030000), ra if hit else nget, limit=6000); n += 1
            v = struct.unpack('<I', bytes.fromhex(r['memory'][0]['hex']))[0]; rr = r['registers']
            if r['fault'] or (hit and (v != val or rr['d0'] != 0 or rr['sp'] != STK or rr['a3'] != 0x18030000)) or (not hit and (v != 0 or rr['d0'] != gid or rr['a1'] != OUT or rr['sp'] != STK)):
                bad.append(('get', sw, gid, hex(ra), r['fault'], v, hex(rr['pc'])))
        mgr = int(new_spec['look_editor']['stock']['ep7_manager'], 16)
        for gid, val, out in ((1657, 4, 'm'), (1657, 6, 'r'), (1686, 255, 'm'), (927, 1, 'n')):
            if not sw:
                out = 'n'
            q = bytearray(block(bytes(512), HANDLE, True)); q[224:288] = SLOT
            rg = [code, caller(int(sym['mv_set'], 16), '[d2,d3,a2],16'), stub(0x602af887, ' mov 7,d0\n ret [],4', 'sg'), Region('state', 0x622cbcc0, struct.pack('<HHI', 0, HANDLE + 0x800 if sw else HANDLE, 0), 'r'),
                  Region('pool', P_AT, block(bytes(512), HANDLE, True), 'r'), Region('pool2', P2_AT, bytes(q), 'rw', True), Region('stack', 0x18010000, bytes(0x1000), 'rw'), Region('m', mgr, b'\xcb', 'rx'), Region('n', nset, b'\xcb', 'rx')]
            stop = dict(m=mgr, n=nset, r=0x18040007)[out]
            r = execute(rg, dict(pc=0x18040000, sp=STK, d0=gid, d1=val, a0=0xa0a0, a1=0x77, d2=0x1111, d3=0x2222, a2=0x3333), stop, limit=6000); n += 1
            m = bytes.fromhex(r['memory'][0]['hex']); rr = r['registers']
            good = not r['fault'] and rr['pc'] == stop
            if out == 'm' and gid == 1657:
                good = good and m[257 + 2] == 4 and m[Bd.DIRTY] == 1 and rr['d0'] == gid and rr['d1'] == 7
            if out == 'm' and gid == 1686:
                good = good and struct.unpack_from('<I', m, Bd.VA)[0] == 255 and m[Bd.DIRTY] == 0
            if out in 'nr':
                good = good and m[257 + 2] == SLOT[35] and m[Bd.DIRTY] == 0
            if out == 'n':
                good = good and rr['d0'] == gid and rr['d1'] == val
            if not good:
                bad.append(('set', sw, gid, val, out, r['fault'], hex(rr['pc'])))
        for gid, val in ((1656, SLOT[34]), (927, None)):
            hit = sw and val is not None
            rg = [code, *st(new, 'card', swapped=sw), stack_with(RET), retr, Region('n', npoly, b'\xcb', 'rx'), caller(int(sym['mv_poly2'], 16), '[],4')]
            r = execute(rg, dict(pc=0x18040000, sp=STK, d0=gid), 0x18040007 if hit else npoly, limit=4000); n += 1
            if r['fault'] or (hit and r['registers']['d0'] & 255 != val):
                bad.append(('poly', sw, gid, r['fault'], r['registers']['d0']))
        rg = [code, *st(new, 'card', swapped=sw), Region('stack', 0x18010000, bytes(0x1000), 'rw'), Region('x', Bd.EXIT, b'\xcb', 'rx')]
        rg[1] = Region('state', 0x622cbcc0, rg[1].data, 'rw', True)
        r = execute(rg, dict(pc=int(sym['mv_exit'], 16), sp=STK, d0=1, a1=2), Bd.EXIT, limit=2000); n += 1
        if r['fault'] or struct.unpack_from('<H', bytes.fromhex(r['memory'][0]['hex']), 2)[0] != HANDLE or r['registers']['a1'] != 2:
            bad.append(('exit', sw, r['fault']))
    return n, bad


def t_pipe(new, sym):
    bad, n = [], 0
    code = [img(new, Bd.W_AT, Bd.W_END, 'mvw'), img(new, Bd.AT, Bd.END, 'mv')]
    syms = json.loads(Path(sys.argv[2]).read_text())['v026_movie']['symbols']
    for state in ('card', 'nofile', 'none'):
        on = state == 'card'
        rec = bytearray(0x400); struct.pack_into('<I', rec, 0x400 - 528, 1); rec[0x400 - 410] = 1
        for i in range(12):
            rg = [*code, *st(new, state), Region('rec', REC, bytes(rec), 'r'), Region('stack', 0x18010000, bytes(0x1000), 'rw'), Region('g', Bd.GETTER, b'\xcb', 'rx'), caller(int(syms['mv_s'], 16), '[d2,d3],12')]
            r = execute(rg, dict(pc=0x18040000, sp=STK, d0=0xF6EA, d1=i, a3=REC + 0x400, a2=0x3333), 0x18040007 if on else Bd.GETTER, limit=2000); n += 1
            rr = r['registers']
            if r['fault'] or (on and rr['d0'] & 255 != SLOT[33 + i]) or (not on and (rr['d0'], rr['d1']) != (0xF6EA, i)):
                bad.append(('s', state, i, r['fault'], rr['d0'], rr['d1']))
        for d1, want in ((Bd.PMARK, P2_AT + 224), (0, None)):
            hit = want and on
            rg = [*code, *st(new, state), Region('stack', 0x18010000, bytes(0x1000), 'rw'), Region('t', Bd.TBL, b'\xcb', 'rx'), caller(int(sym['mv_tbl'], 16), '[d2,d3],8')]
            r = execute(rg, dict(pc=0x18040000, sp=STK, d0=3, d1=d1, d2=0x1111, d3=0x2222), 0x18040007 if hit else Bd.TBL, limit=2000); n += 1
            rr = r['registers']
            if r['fault'] or (hit and (rr['a0'] != want or rr['d2'] != 0x1111)):
                bad.append(('tbl', state, hex(d1), r['fault'], hex(rr['a0'])))
        rec = bytearray(0x400); struct.pack_into('<I', rec, 0x400 - 522, 1); rec[0x400 - 404] = 1
        wbp = stub(Bd.WB_PROP, ' mov 9,d0\n ret [],4', 'wbp')
        rg = [*code, wbp, *st(new, state), Region('rec', REC, bytes(rec), 'r'), Region('stack', 0x18010000, bytes(0x1000), 'rw'), Region('w', Bd.WB_READ, b'\xcb', 'rx'), Region('wg', Bd.WB_SLOT, b'\xcb', 'rx'), Region('wn', Bd.WB_GET, b'\xcb', 'rx')]
        r = execute(rg, dict(pc=int(syms['mv_wb'], 16), sp=STK, d0=1, d1=2, a2=REC + 0x400), Bd.WB_READ if on else Bd.WB_GET, limit=2000); n += 1
        if r['fault'] or (on and r['registers']['a0'] != P2_AT + 224):
            bad.append(('wb', state, r['fault'], hex(r['registers']['a0'])))
    return n, bad


def movie_file(slot=None, name=b'Movie', crc_bad=False, ver=1):
    import zlib
    body = bytes(SLOT if slot is None else slot) + name.ljust(16, b'\0')
    return b'EP7V' + struct.pack('<III', ver, 80, zlib.crc32(body) ^ (1 if crc_bad else 0)) + body


def t_file(new, sym, spec):
    bad, n = [], 0
    le = spec['look_editor']['symbols']; stock = spec['look_editor']['stock']
    u = lambda k: int(le[k], 16); Sk = lambda k: int(stock[k], 16)
    lcode = [img(new, Bd.L_AT, Bd.L_END, 'mvl'), img(new, Bd.S_AT, Bd.S_END, 'mvs'), img(new, u('ed_crc'), u('ed_crc') + 110, 'crc', 'r' if False else 'rx')]
    FREED, FS2 = 0x18060000, 0x18070000; RET = 0x18040007
    def io(present, short=False):
        fo = f' mov 0x41,d0\n mov d0,a0\n ret [],4\n' if present else ' mov 0,a0\n ret [],4\n'
        rd = f' mov {FREED + 4},a1\n mov (a1),d2\n cmp d1,d2\n bls 1f\n mov d1,d2\n1:\n mov d2,d3\n mov {FS2},a1\n cmp 0,d2\n beq 3f\n2:\n movbu (a1),d0\n movbu d0,(a0)\n inc a0\n inc a1\n add -1,d2\n bne 2b\n3:\n mov d3,d0\n ret [d2,d3,a2,a3],24'
        wr = f' mov {FREED + 4},a1\n mov d1,(a1)\n mov d1,d2\n mov d1,d3\n mov {FS2},a1\n1:\n movbu (a0),d0\n movbu d0,(a1)\n inc a0\n inc a1\n add -1,d2\n bne 1b\n mov d3,d0\n' + (' add -1,d0\n' if short else '') + ' ret [d2,d3,a2,a3],24'
        return [stub(Sk('ep7_fopen'), fo, 'fo'), stub(Sk('ep7_fclose'), ' clr d0\n ret [d2,a2,a3],16', 'fc'), stub(Sk('ep7_free'), f' mov {FREED},a1\n mov 1,d0\n mov d0,(a1)\n ret [],4', 'frs'),
                stub(0x602af887, ' mov 3,d0\n ret [],4', 'sg'), stub(Sk('ep7_fread'), rd, 'fr2'), stub(Sk('ep7_fwrite'), wr, 'fw')]
    badhue = bytearray(SLOT); badhue[3] = 9
    badtail = bytearray(SLOT); badtail[50] = 1
    picked = bytearray(SLOT); picked[49] = 1
    card = Path(os.environ['EP7_MOVIE_CARD']).read_bytes() if os.environ.get('EP7_MOVIE_CARD') else movie_file(bytes(picked), name=b'Bleach Byp.')
    cases = [('good', movie_file(), True), ('filmpick', movie_file(bytes(picked)), True), ('card', card, True), ('nofile', None, False), ('crc', movie_file(crc_bad=True), False), ('ver', movie_file(ver=2), False), ('short', movie_file()[:95], False), ('long', movie_file() + b'x', False),
             ('hue', movie_file(bytes(badhue)), False), ('tail', movie_file(bytes(badtail)), False), ('name', movie_file(name=b'A' * 16), False)]
    for name, f, ok in cases:
        pb = bytearray(block(bytes(512), HANDLE, False)); pb[560:565] = b'Other'
        rg = [*lcode, caller(int(sym['mv_load'], 16)), *io(f is not None), stub(Sk('ep7_malloc'), f' mov {P2_AT},a0\n ret [],4', 'ma'), Region('state', 0x622cbcc0, struct.pack('<HHI', 0, HANDLE, 0), 'r'),
              Region('pool', P_AT, bytes(pb), 'rw', True), Region('pool2', P2_AT, bytes(1024), 'rw', True), Region('fr', FREED, bytes(4) + struct.pack('<I', len(f or b'')), 'rw', True), Region('fs', FS2, (f or b'').ljust(0x100, b'\0'), 'rw'),
              Region('stack', 0x18010000, bytes(0x1000), 'rw')]
        r = execute(rg, dict(pc=0x18040000, sp=STK, a2=P_AT, a3=0x4444, d2=0x1111, d3=0x2222), RET, limit=300000); n += 1
        p, q, fr = [bytes.fromhex(x['hex']) for x in r['memory'][:3]]
        marked = p[Bd.VM:Bd.VM + 4] == b'EP7V'
        good = not r['fault'] and marked == ok and (fr[0] == 1) == (not ok) and r['registers']['a2'] == P_AT
        if ok:
            good = good and q[224:288] == f[16:80] and q[592:608] == f[80:96] and q[560:565] == b'Other' and q[Bd.VM:Bd.VM + 4] == b'EP7V' and struct.unpack_from('<I', q, Bd.VP)[0] == P2_AT == struct.unpack_from('<I', p, Bd.VP)[0] and struct.unpack_from('<I', q, Bd.VH)[0] == HANDLE and p[224:288] == bytes(64) and p[592:597] == bytes(5)
        if not good:
            bad.append(('load', name, r['fault'], marked, fr[:4].hex(), hex(r['registers']['pc'])))
    q = bytearray(block(bytes(512), HANDLE, True)); q[224:288] = SLOT; q[592:597] = b'Movie'
    wf = img(new, u('ed_wfile'), u('ed_crc'), 'wf')
    heap = 0x18080000
    for short in (False, True):
        rg = [*lcode, wf, caller(int(sym['mv_save'], 16)), *io(True, short), stub(Sk('ep7_malloc'), f' mov {heap},a0\n ret [],4', 'ma'),
              Region('fr', FREED, bytes(8), 'rw'), Region('fs', FS2, bytes(0x400), 'rw', True), Region('p2', P2_AT, bytes(q), 'r'), Region('heap', heap, bytes(2048), 'rw'), Region('stack', 0x18010000, bytes(0x1000), 'rw')]
        r = execute(rg, dict(pc=0x18040000, sp=STK, a2=P2_AT), RET, limit=500000); n += 1
        fs = bytes.fromhex(r['memory'][0]['hex']); d0 = r['registers']['d0']
        if r['fault'] or d0 != (3 if short else 1) or (not short and fs[:96] != movie_file()):
            bad.append(('save', short, r['fault'], d0, fs[:20].hex()))
    # mv_trig end to end: other event; first press loads after the film load; dirty P2 saves as MOVIE.BIN only
    FL = 0x18090000
    for name, ev, tried, dirty, f in (('other', 0, False, 0, None), ('first', Bd.SB3.EV_PRESS, False, 0, movie_file()), ('nofile', Bd.SB3.EV_PRESS, False, 0, None), ('dirty', Bd.SB3.EV_PRESS, True, 1, None), ('clean', Bd.SB3.EV_PRESS, True, 0, None)):
        pb = bytearray(block(bytes(512), HANDLE, tried)); qb = bytearray(block(bytes(512), HANDLE, True)); qb[224:288] = SLOT; qb[592:597] = b'Movie'; qb[Bd.DIRTY] = dirty
        if tried:
            pb[Bd.VT:Bd.VT + 4] = b'EP7T'
        stk = bytearray(0x1000); struct.pack_into('<I', stk, 0x800 + 16, ev)
        rg = [*lcode, wf, *io(f is not None or tried), stub(Sk('ep7_malloc'), f' mov {P2_AT if not tried else heap},a0\n ret [],4', 'ma'), Region('state', 0x622cbcc0, struct.pack('<HHI', 0, HANDLE, 0), 'r'),
              Region('pool', P_AT, bytes(pb), 'rw', True), Region('pool2', P2_AT, bytes(qb) if tried else bytes(1024), 'rw', True), Region('fs', FS2, (f or bytes(0x400)).ljust(0x400, b'\0'), 'rw', True),
              Region('fr', FREED, bytes(4) + struct.pack('<I', len(f or b'')), 'rw'), Region('heap', heap, bytes(2048), 'rw'), Region('stack', 0x18010000, bytes(stk), 'rw'),
              Region('cfg', u('ed_cfg_fl') & ~3, struct.pack('<I', FL), 'r') , stub(FL, ' mov 0x5a,d0\n rets', 'fl'), Region('t', u('ed_trig'), b'\xcb', 'rx')]
        r = execute(rg, dict(pc=int(sym['mv_trig'], 16), sp=STK, d0=1, d1=2, a0=3, a1=4, a2=0x3333, a3=0x4444, d2=0x1111, d3=0x2222), u('ed_trig'), limit=500000); n += 1
        p_, q_, fs = [bytes.fromhex(x['hex']) for x in r['memory'][:3]]; rr = r['registers']
        good = not r['fault'] and rr['sp'] == STK and (rr['d0'], rr['d1'], rr['a0'], rr['a1'], rr['a2'], rr['a3'], rr['d2'], rr['d3']) == (1, 2, 3, 4, 0x3333, 0x4444, 0x1111, 0x2222)
        good = good and {'other': p_[Bd.VM:Bd.VM + 4] == bytes(4), 'first': p_[Bd.VM:Bd.VM + 4] == b'EP7V' and p_[Bd.VT:Bd.VT + 4] == b'EP7T', 'nofile': p_[Bd.VM:Bd.VM + 4] == bytes(4) and p_[Bd.VT:Bd.VT + 4] == b'EP7T',
                         'dirty': fs[:96] == movie_file() and q_[Bd.DIRTY] == 0 and q_[Bd.STATUS] == 1, 'clean': fs[:4] == bytes(4)}[name]
        if not good:
            bad.append(('trig', name, r['fault'], hex(rr['pc']), hex(rr['sp'])))
    for a2, stop, want in ((P2_AT, RET, 2), (P_AT, u('ed_save'), None)):
        rg = [img(new, Bd.W_AT, Bd.W_END, 'mvw'), caller(int(sym['mv_gsave'], 16)), *st(new, 'card'), Region('s', u('ed_save'), b'\xcb', 'rx'), Region('stack', 0x18010000, bytes(0x1000), 'rw')]
        if a2 == P2_AT:
            rg[3] = Region('pool', P_AT, block(bytes(512), HANDLE, True), 'r')
        r = execute(rg, dict(pc=0x18040000, sp=STK, a2=a2 if a2 == P2_AT else P_AT), stop, limit=2000); n += 1
        if a2 == P_AT:
            pass
        if r['fault'] or (want and r['registers']['d0'] != want):
            bad.append(('gsave', hex(a2), r['fault'], r['registers']['d0']))
    return n, bad


def t_l2(new, sym, spec):
    """Film page on the Movie slot: mv_load gives P2 its own L; the real fm_valid accepts it; P's L is untouched."""
    bad, n = [], 0
    le = spec['look_editor']['symbols']; stock = spec['look_editor']['stock']; fm = dict(fm_valid='0x601e2c3c')   # film_menu_v2 UI[0], fixed
    Sk = lambda k: int(stock[k], 16)
    L, L2, CNT = 0xa1dd8d40, 0xa1dd8d40 + 0x4040, 0x18060100
    lb = bytearray(2560); lb[2112:2116] = b'EP7L'; struct.pack_into('<I', lb, 2116, P_AT); lb[2120] = 2; lb[2124] = 2; lb[2128] = 1
    for j, nm in enumerate((b'Other', b'Movie')):
        lb[64 + 64 * j + 46] = 1; lb[64 + 64 * j + 48:64 + 64 * j + 48 + len(nm)] = nm
    lcode = [img(new, Bd.L_AT, Bd.L_END, 'mvl'), img(new, Bd.S_AT, Bd.S_END, 'mvs'), img(new, int(le['ed_crc'], 16), int(le['ed_crc'], 16) + 110, 'crc')]
    RET = 0x18040007; FREED, FS2 = 0x18060000, 0x18070000
    f = movie_file()
    for name, second, want in (('l2', L2, 2), ('nomem', 0, None)):
        pb = bytearray(block(bytes(512), HANDLE, False)); pb[1016:1020] = struct.pack('<I', L); pb[1020:1024] = b'EP7F'
        ma = f' mov {CNT},a0\n mov (a0),d0\n inc d0\n mov d0,(a0)\n cmp 1,d0\n bne 1f\n mov {P2_AT},a0\n ret [],4\n1:\n mov {second},a0\n ret [],4'
        rd = f' mov {FS2},a1\n mov {len(f)},d2\n mov d2,d3\n2:\n movbu (a1),d0\n movbu d0,(a0)\n inc a0\n inc a1\n add -1,d2\n bne 2b\n mov d3,d0\n ret [d2,d3,a2,a3],24'
        rg = [*lcode, caller(int(sym['mv_load'], 16)), stub(Sk('ep7_fopen'), ' mov 0x41,d0\n mov d0,a0\n ret [],4', 'fo'), stub(Sk('ep7_fclose'), ' clr d0\n ret [d2,a2,a3],16', 'fc'), stub(Sk('ep7_free'), ' ret [],4', 'frs'),
              stub(0x602af887, ' mov 3,d0\n ret [],4', 'sg'), stub(Sk('ep7_fread'), rd, 'fr2'), stub(Sk('ep7_malloc'), ma, 'ma'), Region('state', 0x622cbcc0, struct.pack('<HHI', 0, HANDLE, 0), 'r'),
              Region('pool', P_AT, bytes(pb), 'rw', True), Region('pool2', P2_AT, bytes(1024), 'rw', True), Region('l', L, bytes(lb), 'rw', True), Region('l2', L2, bytes(2560), 'rw', True),
              Region('cnt', CNT, bytes(4), 'rw'), Region('fs', FS2, f.ljust(0x100, b'\0'), 'r'), Region('stack', 0x18010000, bytes(0x1000), 'rw')]
        r = execute(rg, dict(pc=0x18040000, sp=STK, a2=P_AT, a3=0x4444, d2=0x1111, d3=0x2222), RET, limit=500000); n += 1
        p, q, l, l2 = [bytes.fromhex(x['hex']) for x in r['memory'][:4]]
        ok = not r['fault'] and p[Bd.VM:Bd.VM + 4] == b'EP7V' and l == bytes(lb) and p[1016:1024] == bytes(pb[1016:1024])
        if want:
            ok = ok and struct.unpack_from('<I', q, 1016)[0] == L2 and q[1020:1024] == b'EP7F' and struct.unpack_from('<I', l2, 2116)[0] == P2_AT and l2[2124] == want and l2[2128] == 0 and l2[:2116] == l[:2116]
        else:
            ok = ok and q[1020:1024] == bytes(4)
        if not ok:
            bad.append((name, r['fault'], hex(r['registers']['pc'])))
        if want:
            fvr = execute([img(new, int(fm['fm_valid'], 16), int(fm['fm_valid'], 16) + 96, 'fv'), Region('pool2', P2_AT, q, 'r'), Region('l2', L2, l2, 'r'), Region('stack', 0x18010000, struct.pack('<I', 0x18040007).rjust(0x1000, b'\0'), 'rw'), Region('ret', 0x18040000, b'\xcb' * 16, 'rx')],
                          dict(pc=int(fm['fm_valid'], 16), sp=0x18010ffc, a2=P2_AT), 0x18040007, limit=2000); n += 1
            if fvr['fault'] or fvr['registers']['d0'] != 1:
                bad.append(('fm_valid', fvr['fault'], fvr['registers']['d0']))
    return n, bad


def t_label(new, base, spec):
    """Real builder A and B, real film-menu hook: Vivid -> our text only in movie with the slot loaded; else identical to base."""
    bad, n = [], 0
    A, B_ = 0x60df250b, 0x60df25b5
    LBL, LIST, SRC_, STKS = 0x18060000, 0x18061000, 0x18061100, 0x18010000
    want = b'INFO Custom'
    def run(im, build_a, sid, loaded, sid_id):
        ent = struct.pack('<IHHI', 0, 4, sid_id, 0x61163e78)
        code = [img(im, 0x60df2400, 0x60df2700, 'bld'), img(im, 0x61242d00, 0x61242f00, 'fh'), img(im, Bd.H_AT, Bd.H_END, 'h'), stub(0x602af887, f' mov {sid},d0\n ret [],4', 'sg')]
        pb = bytearray(block(bytes(512), HANDLE, loaded))
        cl = (f' .am33_2\n .text\n .global _start\n_start:\n mov {LBL},d0\n mov d0,(4,sp)\n mov 0,d0\n mov 1,d1\n mov {LIST},a1\n call tgt,[d2,d3,a2,a3],24\n nop\n nop\n'
              if build_a else f' .am33_2\n .text\n .global _start\n_start:\n mov {LBL},d0\n mov {SRC_},a1\n call tgt,[d2,a2,a3],20\n nop\n nop\n')
        c, _, _, _ = SB3.assemble(cl, 0x18040000, dict(tgt=A if build_a else B_))
        rg = [*code, Region('caller', 0x18040000, c, 'rx'), Region('label', LBL, bytes(80), 'rw', True), Region('list', LIST, ent + bytes(4), 'r'), Region('src', SRC_, ent[4:], 'r'),
              Region('state', 0x622cbcc0, struct.pack('<HHI', 0, HANDLE, 0), 'r'), Region('pool', P_AT, bytes(pb), 'r'), Region('stack', STKS, bytes(0x1000), 'rw')]
        return execute(rg, dict(pc=0x18040000, sp=STK, a0=0x77, d2=0x1111, d3=0x2222, a3=0x3333), 0x18040000 + len(c) - 2, limit=5000)
    for build_a in (True, False):
        for sid, loaded, sid_id, hit in ((1, True, 1657, True), (0, True, 1657, False), (1, False, 1657, False), (1, True, 1658, False), (0, False, 1657, False)):
            r = run(new, build_a, sid, loaded, sid_id); n += 1
            l = bytes.fromhex(r['memory'][0]['hex'])
            if hit:
                ok = not r['fault'] and l[0] == 5 and l[8:8 + 2 * len(want)] == b''.join(bytes([c, 0]) for c in want) and l[8 + 2 * len(want):74] == bytes(74 - 8 - 2 * len(want)) and r['registers']['d0'] == len(want)
            else:
                b = run(base, build_a, sid, loaded, sid_id)
                ok = not r['fault'] and not b['fault'] and l == bytes.fromhex(b['memory'][0]['hex']) and l[0] == 4 and {k: r['registers'][k] for k in ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'pc')} == {k: b['registers'][k] for k in ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'pc')}
            if not ok:
                bad.append(('AB'[not build_a], sid, loaded, sid_id, r['fault'], hex(r['registers']['pc']), l[:12].hex()))
    return n, bad


def main():
    base_p, new_p = sys.argv[1:3]
    bsp, spec = json.loads(Path(base_p).read_text()), json.loads(Path(new_p).read_text())
    base, new = image(bsp), image(spec)
    wheel = spec['v026_movie']['wheel']
    if wheel:
        global MARKS, STATES
        MARKS, STATES = True, STATES + ('nofile',)
    fails = []
    def rep(tag, n, bad, extra=''):
        print(f'{tag}: {n - len(bad)}/{n} {extra}', bad[:6]); fails.extend([tag] * bool(bad))
    n, on, bad = t_key(new, base); rep('K key', n, bad, f'({on} active)')
    n, bad = t_msg(new, base); rep('M msg+20', n, bad)
    if not wheel:
        n, bad = t_s(new, base); rep('S saturation', n, bad)
        n, bad = t_wb(new, base); rep('B WB', n, bad)
        n, bad = t_prof(new, base); rep('P profile', n, bad)
    n, bad = t_cons(new, base); rep('C constructor', n, bad)
    if wheel:
        sym = spec['v026_movie']['wheel_symbols']
        n, bad = t_pipe(new, sym); rep('Y pipeline slot reads', n, bad)
        n, bad = t_ui(new, base, sym); rep('U wheel get/set/poly/exit', n, bad)
        n, bad = t_lc(new, base); rep('L Live Control INFO (real handler)', n, bad)
        n, bad = t_file(new, sym, spec); rep('F MOVIE.BIN load/save', n, bad)
        n, bad = t_l2(new, sym, spec); rep('T Film table for the Movie slot', n, bad)
        n, bad = t_label(new, base, spec); rep('N label builders', n, bad)
    # D: only our sites differ
    m = spec['v026_movie']
    al = [(Bd.AT, Bd.AT + m['code_len']), (Bd.KEY_SITE, Bd.KEY_SITE + 7), (Bd.MSG_SITE, Bd.MSG_SITE + 8), (Bd.S_SITE + 1, Bd.S_SITE + 5), (Bd.LV_GET + 1, Bd.LV_GET + 5), (Bd.TONE_GET + 1, Bd.TONE_GET + 5),
          (Bd.CONS + 1, Bd.CONS + 5), (0x601e1c40, 0x601e1c64)] + [(w + 1, w + 5) for w in Bd.WB_SITES]
    if wheel:
        al += [(Bd.W_AT, Bd.W_AT + m['wheel_len']), (Bd.L_AT, Bd.L_AT + m['load_len']), (Bd.S_AT, Bd.S_AT + m['save_len']), (Bd.W_GETV, Bd.W_GETV + 4), (Bd.DEF_WORD, Bd.DEF_WORD + 4), (Bd.EXIT_WORD, Bd.EXIT_WORD + 4), (Bd.LC, Bd.LC + 6), (Bd.POLY, Bd.POLY + 5)]
        al += [(Bd.H_AT, Bd.H_AT + m['label_len']), (Bd.LB_A + 1, Bd.LB_A + 5), (Bd.LB_B + 1, Bd.LB_B + 5)]
        al += [(x + 1, x + 5) for x in (Bd.POLY2, Bd.SET_SITE, Bd.GSAVE_SITE, Bd.SD_BACK, *Bd.TBL_SITES)]
    diff = [i + BASE for i in range(len(new)) if new[i] != base[i]]
    rest = [hex(a) for a in diff if not any(x <= a < y for x, y in al)]
    print('D', len(diff), 'bytes differ; outside our sites:', rest[:10]); fails += ['D'] * bool(rest)
    # A: anti-brick
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    parts = oc.parse(pkg)
    stock = (ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes()
    k = dict(reparses=[b.kind for b in parts] == [int(x, 16) for x in spec['components']],
             restore_is_stock=hashlib.sha256(oc.parse(rst)[0].payload).hexdigest() == hashlib.sha256(stock).hexdigest(),
             decoded_is_emulated=bytes(parts[0].payload) == new)
    print('A', k, info['changed_payload_bytes']); fails += ['A'] * (not all(k.values()))
    if fails:
        sys.exit(f'VERIFY FAILED {fails}')
    print('ALL OK')


if __name__ == '__main__':
    main()
