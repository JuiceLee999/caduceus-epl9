#!/usr/bin/env python3
"""E-P7 1.1 still-aspect patch: repurpose hidden ids 6 (7:6) -> XPan 65:24 and 7 (6:5) -> 21:9.

OFFLINE. Reads the decoded main, emits patches/aspect/edits.json for tools/build_package.py and
runs emulator checks (stock vs patched) on the consumers that can be isolated. Writes nothing else.
See docs/ASPECT.md for the evidence behind every site.

Edits (all in main, component 0x100):
  T  every per-aspect size/geometry table found by scan_tables.py: rows for ids 6 and 7
     (u32 (id,w,h) lists, u16 (id,0,w,h) lists, u16 (w,h,ratio-code) tables, u16 (w,h) arrays,
     u16 (x,y,w,h,x0,y0,x1,y1) display rects). New dims: width = max(4:3 row, 16:9 row) width,
     height rounded to the table's own alignment (2-power gcd of its stock dims, clamped 2..8).
  M  Image Aspect option list (setting 270): relocated to the sec-6 FF tail with 8 entries
     [4:3,16:9,3:2,1:1,3:4,"Panorama"(id 6),"Wide"(id 7),17:9]; descriptor count 6->8 + pointer.
  C  hard-coded consumers in sec 5: four 640-class size switches, the ratio switch and the
     fit-group switch get new jump-table targets; new case blocks live in the sec-1 FF tail.
"""
import argparse, json, struct, sys
from math import gcd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import ep7_color_probe as PR  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402

B = 0x60020020
NEW = {6: ('XPan 65:24', 65, 24), 7: ('21:9', 21, 9)}
STR_LABEL = {6: 241, 7: 2661}          # existing strings 'Panorama', 'Wide'
CODE = {i: (h << 8) | w for i, (_, w, h) in NEW.items()}   # ratio code = (H<<8)|W (0x304 = 4:3 ...)

# ---- T: tables (address of the id-1 row, layout); from scan_tables.py, re-verified below
TABLES = [
    # u16 (w,h) arrays, index = id (display boxes and .data-initialised size arrays)
    *[(a, 'u16wh') for a in (0x601e5fd0, 0x601e6004, 0x601e6038, 0x6024804c, 0x60248074, 0x6024809c,
                             0x602480c4, 0x602480ec, 0x6024813c, 0x60248164, 0x6024818c, 0x602481b4,
                             0x602481dc, 0x60248204, 0x605223e8)],
    (0x60533880, 'rect16'), (0x60533930, 'rect16'),
    *[(a, 'u16id0wh') for a in (0x602434e4, 0x6024353c, 0x60b0a1f8, 0x60b0a250, 0x60b0a2a0, 0x60b0a2f0,
                                0x60b0a390, 0x60b0a430, 0x60b0a520, 0x60b0a5c0, 0x60b0a610, 0x60b0a660)],
    (0x604e92c6, 'u16whcode'), (0x6052219e, 'u16whcode'),
    *[(a, 'u32idwh') for a in (0x60b8c6b0, 0x60b8c728, 0x60b8c7a0, 0x60b8c908, 0x60b8c9f8, 0x60b8cb60,
                               0x60b8cc50, 0x60b8ccc8, 0x60b8cd40, 0x60b8cdb8, 0x60b8ced0, 0x60b8cf48)],
]
LAY = {'u16wh': (4, '<HH', 0, 1), 'rect16': (16, '<8H', 2, 3), 'u16id0wh': (8, '<4H', 2, 3),
       'u16whcode': (6, '<3H', 0, 1), 'u32idwh': (12, '<3I', 1, 2)}

# ---- M: menu option list
MENU_DESC = 0x6117af14            # {u16 setting=270, u16 count=6, u32 list=0x6117a834}
MENU_LIST = 0x6117a834            # 12-byte entries {u32 value, u16 type=4, u16 string, u32 cond}
MENU_NEW = 0x61242f00             # sec-6 FF tail (CODE_SPACE_MAP claim 0x61242f00-0x61242f60)

# ---- C: switch sites (jump-table entry address, stock target, new block kind)
BLOCKS_AT = 0x60210f00            # sec-1 FF tail (claim 0x60210f00-0x60210f80); sec 1 loads before sec 5
SW640 = [  # name, getter call site (mov 270,d0), table base (index=id), join, w reg, h reg
    ('S1', 0x6088b2b2, 0x60b04410, 0x6088b309, 2, 3), ('S2', 0x6088b385, 0x60b0443c, 0x6088b3dc, 3, 2),
    ('S3', 0x60899a41, 0x60b0dae0, 0x60899a98, 1, 0), ('S4', 0x6089b877, 0x60b0e0d4, 0x6089b8ce, 0, 1)]
S5 = dict(site=0x6086279a, base=0x60af4a04, join=0x608627fd, stock={6: 0x608627d3, 7: 0x608627db})  # index id-1
S6 = dict(site=0x60879e42, base=0x60b01530, stock=0x60879e65, wide=0x60879e70)                     # index id
GETTER = 0x602cbc0a


def u16s(d, a, n):
    return list(struct.unpack_from(f'<{n}H', d, a - B))


def align_of(rows, iw, ih):
    g = 0
    for r in rows:
        g = gcd(g, gcd(r[iw], r[ih]))
    a = 1
    while g % (a * 2) == 0 and a < 8:
        a *= 2
    return a


def new_rows(d):
    """Return list of (addr, stock_bytes, new_bytes, why) for table rows of ids 6/7."""
    out = []
    for a1, lay in TABLES:
        st, fmt, iw, ih = LAY[lay]
        rows = [list(struct.unpack_from(fmt, d, a1 + k * st - B)) for k in range(9)]
        assert abs(rows[5][iw] / rows[5][ih] - 7 / 6) < 0.035 and abs(rows[6][iw] / rows[6][ih] - 6 / 5) < 0.035, hex(a1)
        al = max(2, align_of(rows, iw, ih))          # never odd
        W = max(rows[0][iw], rows[2][iw])             # widest of 4:3 / 16:9 = panel or sensor width
        for i, (name, rw, rh) in NEW.items():
            r = list(rows[i - 1])
            h = round(W * rh / rw / al) * al
            r[iw], r[ih] = W, h
            if lay == 'u16whcode':
                r[2] = CODE[i]
            if lay == 'u32idwh' or lay == 'u16id0wh':
                assert r[0] == i
            if lay == 'rect16':
                x0, y0r = rows[0][0], rows[0][1]
                r[0] = x0
                r[1] = y0r + (rows[0][3] - h) // 2
                # second rect = first rect relative to the window origin (row-1 x,y), inclusive
                # corners, clipped to row-1's vertical band (stock: 640 window 34..445, 320 window 17..222)
                orgx = rows[0][0] - rows[0][4]
                orgy = rows[0][1]
                c0, c1 = rows[0][5], rows[0][7]
                r[4] = r[0] - orgx
                r[5] = max(r[1] - orgy, c0)
                r[6] = r[0] + W - 1 - orgx
                r[7] = min(r[1] + h - 1 - orgy, c1)
            addr = a1 + (i - 1) * st
            old = struct.pack(fmt, *rows[i - 1])
            new = struct.pack(fmt, *r)
            if old != new:
                out.append((addr, old, new, f'{lay}@{a1:#x} id{i} {tuple(rows[i-1])} -> {tuple(r)} ({name}, align {al})'))
    return out


def jmp32(src, dst):
    return b'\xdc' + struct.pack('<i', dst - src)


def mov16(reg, v):
    return bytes((0x2c + reg,)) + struct.pack('<h', v)


def blocks(heights640):
    """Assemble case blocks; return (bytes, {key: addr})."""
    code, where = bytearray(), {}
    for name, _, _, join, rw, rh in SW640:
        for i in (6, 7):
            a = BLOCKS_AT + len(code)
            where[(name, i)] = a
            code += mov16(rw, 640) + mov16(rh, heights640[i])
            code += jmp32(BLOCKS_AT + len(code), join)
    for i, (_, rw, rh) in NEW.items():
        a = BLOCKS_AT + len(code)
        where[('S5', i)] = a
        code += bytes((0x80, rw, 0x42, 0x18, 0x80, rh))     # mov W,d0; mov d0,(24,sp); mov H,d0
        code += jmp32(BLOCKS_AT + len(code), S5['join'])
    assert len(code) <= 0x80
    return bytes(code), where


def build(d):
    d = bytes(d)
    edits = []

    def edit(addr, old, new, why):
        assert d[addr - B:addr - B + len(old)] == old, (hex(addr), why)
        edits.append(dict(kind='0x100', addr=hex(addr), expect=old.hex(), new=new.hex(), why=why))

    for addr, old, new, why in new_rows(d):
        edit(addr, old, new, why)
    # 640-class heights from the patched 640 image-size row (u32 table 0x60b8ced0)
    h640 = {}
    for addr, old, new, why in new_rows(d):
        if why.startswith('u32idwh@0x60b8ced0'):
            i = struct.unpack('<3I', new)[0]
            h640[i] = struct.unpack('<3I', new)[2]
    # M: menu
    desc = d[MENU_DESC - B:MENU_DESC - B + 8]
    setting, count, lst = struct.unpack('<HHI', desc)
    assert (setting, count, lst) == (270, 6, MENU_LIST)
    ents = [d[MENU_LIST - B + 12 * k:MENU_LIST - B + 12 * k + 12] for k in range(6)]
    vals = [struct.unpack('<IHHI', e) for e in ents]
    assert [v[0] for v in vals] == [1, 3, 2, 4, 9, 10] and [v[2] for v in vals] == [292, 291, 293, 1786, 295, 3261]
    cond = vals[0][3]
    newlist = b''.join(ents[:5]) + b''.join(struct.pack('<IHHI', i, 4, STR_LABEL[i], cond) for i in (6, 7)) + ents[5]
    assert d[MENU_NEW - B:MENU_NEW - B + len(newlist)] == b'\xff' * len(newlist)
    edit(MENU_NEW, b'\xff' * len(newlist), newlist, 'Image Aspect option list (8 entries) relocated to sec-6 tail')
    edit(MENU_DESC, desc, struct.pack('<HHI', 270, 8, MENU_NEW), 'setting 270 option descriptor: count 6->8, list ptr')
    # C: blocks + jump tables
    code, where = blocks(h640)
    edit(BLOCKS_AT, b'\xff' * len(code), code, 'aspect case blocks (S1-S5) in sec-1 tail')
    for name, _, base, _, _, _ in SW640:
        for i in (6, 7):
            ea = base + 4 * i
            old = d[ea - B:ea - B + 4]
            edit(ea, old, struct.pack('<I', where[(name, i)]), f'{name} jump entry id{i} {struct.unpack("<I", old)[0]:#x} -> block')
    for i in (6, 7):
        ea = S5['base'] + 4 * (i - 1)
        old = d[ea - B:ea - B + 4]
        assert struct.unpack('<I', old)[0] == S5['stock'][i]
        edit(ea, old, struct.pack('<I', where[('S5', i)]), f'S5 ratio jump entry id{i} -> block')
        ea = S6['base'] + 4 * i
        old = d[ea - B:ea - B + 4]
        assert struct.unpack('<I', old)[0] == S6['stock']
        edit(ea, old, struct.pack('<I', S6['wide']), f'S6 fit-group entry id{i}: height-limited -> width-limited group')
    # no overlaps
    spans = sorted((int(e['addr'], 16), int(e['addr'], 16) + len(e['new']) // 2) for e in edits)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), 'overlap'
    return edits, where, h640


def apply(d, edits):
    p = bytearray(d)
    for e in edits:
        a = int(e['addr'], 16) - B
        n = bytes.fromhex(e['new'])
        p[a:a + len(n)] = n
    return bytes(p)


# ------------------------------------------------------------------ emulator checks
STACK = PR.STACK


def img(d, name, lo, hi, perm='r'):
    return Region(name, lo, d[lo - B:hi - B], perm)


def run(regions, regs, stop, limit=5000):
    r = execute(regions, regs, stop, limit=limit)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return r, mem


def getter_stub(v):
    return Region('getter', GETTER, bytes((0x80, v, 0xdf, 0x00, 0x04)), 'rx')   # mov v,d0 ; ret [],4


def chk_table_lookup(d, aid):
    """0x6034ee0b(d0=id, d1=0) -> a0 = &(w,h,code)[id] in table 0x604e92c0 (native)."""
    regs = [PR.caller(0x6034ee0b, 0, 0), img(d, 'fn', 0x6034ee0b, 0x6034ee43, 'rx'),
            img(d, 'tab', 0x604e92b0, 0x604e9310), Region('stack', STACK, bytes(0x2000), 'rw')]
    r, _ = run(regs, {'pc': PR.CALLER, 'sp': STACK + 0x1800, 'd0': aid, 'd1': 0}, PR.CALLER + 7)
    a0 = r['registers']['a0']
    ok = r['registers']['pc'] == PR.CALLER + 7 and not r['fault']
    return ok, (struct.unpack_from('<3H', d, a0 - B) if a0 else None)


def chk_scale(d, aid, w=5184, h=3888):
    """0x6035585e: w' = w*T[id].w/T[1].w, h' = h*T[id].h/T[1].h (native, with 0x6034ee0b + table)."""
    S = 0x19000000
    st = bytearray(0x3000)
    st[23] = aid
    io = bytearray(8)
    struct.pack_into('<HH', io, 0, w, h)
    regs = [PR.caller(0x6035585e, 0xf0, 20), img(d, 'fn', 0x6035585e, 0x603558ce, 'rx'),
            img(d, 'lk', 0x6034ee0b, 0x6034ee43, 'rx'), img(d, 'tab', 0x604e92b0, 0x604e9310),
            Region('stack', STACK, bytes(0x2000), 'rw'), Region('st', S, bytes(st), 'rw'),
            Region('io', 0x19100000, bytes(io), 'rw', True)]
    r, mem = run(regs, {'pc': PR.CALLER, 'sp': STACK + 0x1800, 'a0': S, 'a1': 0x19100000, 'd0': 0x19100002,
                        'd2': 0x2222, 'a2': 0x3333}, PR.CALLER + 7)
    ok = r['registers']['pc'] == PR.CALLER + 7 and not r['fault'] and r['registers']['d2'] == 0x2222
    return ok, struct.unpack_from('<HH', mem['io'], 0)


def chk_size_lookup(d, key, aid):
    """Native loop 0x60a38c85..0x60a38ce1: walk the u32 list table 0x60b8ce30 for (size key, aspect)."""
    M = 0x19200000
    mem = bytearray(0x40)
    struct.pack_into('<I', mem, 0, key)
    stack = bytearray(0x2000)
    sp = STACK + 0x1000
    struct.pack_into('<I', stack, 0x1000 + 16, M + 0x10)   # (16,sp) -> width out
    struct.pack_into('<I', stack, 0x1000 + 12, M + 0x12)   # (12,sp) -> height out
    struct.pack_into('<HH', mem, 0x10, 5184, 3888)         # function pre-sets 5184x3888
    regs = [img(d, 'fn', 0x60a38c85, 0x60a38ce4, 'rx'), img(d, 'tabs', 0x60b8c600, 0x60b8cfd0),
            Region('stack', STACK, bytes(stack), 'rw'), Region('m', M, bytes(mem), 'rw', True)]
    r, m = run(regs, {'pc': 0x60a38c85, 'sp': sp, 'a2': M, 'a3': aid}, 0x60a38ce1, limit=20000)
    ok = r['registers']['pc'] == 0x60a38ce1 and not r['fault']
    return ok, struct.unpack_from('<HH', m['m'], 0x10)


def chk_sw640(d, sw, aid):
    name, site, base, join, rw, rh = sw
    regs = [getter_stub(aid), img(d, 'code', site, join + 1, 'rx'), img(d, 'jt', base, base + 48),
            img(d, 'blk', BLOCKS_AT, BLOCKS_AT + 0x80, 'rx'), Region('stack', STACK, bytes(0x2000), 'rw')]
    r, _ = run(regs, {'pc': site, 'sp': STACK + 0x1800}, join)
    R = r['registers']
    ok = R['pc'] == join and not r['fault'] and R['sp'] == STACK + 0x1800
    return ok, (R[f'd{rw}'] & 0xffff, R[f'd{rh}'] & 0xffff)


def chk_s5(d, aid):
    join = S5['join']
    regs = [getter_stub(aid), img(d, 'code', S5['site'], join + 1, 'rx'), img(d, 'jt', S5['base'], S5['base'] + 40),
            img(d, 'blk', BLOCKS_AT, BLOCKS_AT + 0x80, 'rx'), Region('stack', STACK, bytes(0x2000), 'rw', True)]
    r, m = run(regs, {'pc': S5['site'], 'sp': STACK + 0x1800}, join)
    R = r['registers']
    ok = R['pc'] == join and not r['fault']
    return ok, (struct.unpack_from('<I', m['stack'], 0x1800 + 24)[0], R['d0'])


def chk_s6(d, aid):
    end = 0x60879ef0
    regs = [getter_stub(aid), img(d, 'code', S6['site'], end, 'rx'), img(d, 'jt', S6['base'], S6['base'] + 44),
            Region('stack', STACK, bytes(0x2000), 'rw')]
    r, _ = run(regs, {'pc': S6['site'], 'sp': STACK + 0x1800}, S6['wide'])
    return r['registers']['pc'] == S6['wide'] and not r['fault']


def menu_list(d):
    s, c, p = struct.unpack_from('<HHI', d, MENU_DESC - B)
    return [struct.unpack_from('<IHHI', d, p + 12 * k - B)[:3:2] for k in range(c)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path, help='write check results here')
    a = ap.parse_args()
    d = PR.main_image()
    edits, where, h640 = build(d)
    p = apply(d, edits)
    res, ok = [], True

    def rep(name, good, stock, patched, want=None):
        nonlocal ok
        ok &= bool(good)
        res.append(dict(check=name, passed=bool(good), stock=stock, patched=patched))
        print(f"{'PASS' if good else 'FAIL'} {name}: stock {stock} -> patched {patched}")

    # table lookup + scale (crop) for all ids
    for aid in range(1, 11):
        s_ok, s = chk_table_lookup(d, aid)
        p_ok, q = chk_table_lookup(p, aid)
        exp = {6: (5184, 1912, 0x1841), 7: (5184, 2224, 0x0915)}.get(aid, s)
        rep(f'T 0x6034ee0b id{aid}', s_ok and p_ok and tuple(q) == tuple(exp), s, q)
    for aid in range(1, 10):
        s_ok, s = chk_scale(d, aid)
        p_ok, q = chk_scale(p, aid)
        exp = {6: (5184, 1912), 7: (5184, 2224)}.get(aid, s)
        rep(f'X crop-scale 0x6035585e id{aid} from 5184x3888', s_ok and p_ok and q == exp, s, q)
    # size lookup across every size key for ids 6/7 (others unchanged)
    keys = [struct.unpack_from('<I', d, 0x60b8ce30 + 8 * k - B)[0] for k in range(19)]
    for key in keys:
        for aid in (1, 6, 7, 9):
            s_ok, s = chk_size_lookup(d, key, aid)
            p_ok, q = chk_size_lookup(p, key, aid)
            _, w1 = chk_size_lookup(p, key, 1)
            if aid in (1, 9) or s == (0, 0) or key == 1:     # unchanged rows (4:3-only sizes, HDMI list)
                good = q == s
            else:                                           # full 4:3 width, height within one 8-px step
                good = q[0] == w1[0] and abs(q[1] - q[0] * NEW[aid][2] / NEW[aid][1]) <= 4
            good = s_ok and p_ok and good
            rep(f'L size key {key:#x} id{aid}', good, s, q)
    for sw in SW640:
        for aid in (1, 3, 5, 6, 7, 8, 9):
            s_ok, s = chk_sw640(d, sw, aid)
            p_ok, q = chk_sw640(p, sw, aid)
            exp = {6: (640, h640[6]), 7: (640, h640[7])}.get(aid, s)
            rep(f'{sw[0]} 640-class switch id{aid}', s_ok and p_ok and q == exp, s, q)
    for aid in (1, 2, 3, 6, 7, 8, 10):
        s_ok, s = chk_s5(d, aid)
        p_ok, q = chk_s5(p, aid)
        exp = {6: (65, 24), 7: (21, 9)}.get(aid, s)
        rep(f'S5 ratio switch id{aid}', s_ok and p_ok and q == exp, s, q)
    for aid in (6, 7):
        rep(f'S6 fit-group id{aid} reaches width-limited case', (not chk_s6(d, aid)) and chk_s6(p, aid), 'height group', 'width group')
    for aid in (2, 3, 10):
        rep(f'S6 control id{aid}', chk_s6(d, aid) and chk_s6(p, aid), 'width group', 'width group')
    rep('M menu list', menu_list(p) == [(1, 292), (3, 291), (2, 293), (4, 1786), (9, 295), (6, 241), (7, 2661), (10, 3261)],
        menu_list(d), menu_list(p))
    out = ROOT / 'patches/aspect/edits.json'
    out.write_text(json.dumps(dict(components=['0x100'], edits=edits), indent=1) + '\n')
    nbytes = sum(len(e['new']) // 2 for e in edits)
    print(f'{len(edits)} edits, {nbytes} bytes; blocks {min(where.values()):#x}..; wrote {out}')
    if a.json:
        a.json.write_text(json.dumps(dict(passed=bool(ok), checks=res), indent=1))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
