#!/usr/bin/env python3
"""E-P7 1.1 still-aspect patch: repurpose hidden ids 6 (7:6) -> XPan 65:24 and 7 (6:5) -> 21:9.

OFFLINE. Reads the decoded main, emits patches/aspect/edits.json for tools/build_package.py and
runs emulator checks (stock vs patched) on the consumers that can be isolated. Writes nothing else.
See docs/ASPECT.md for the evidence behind every site.

Edits (all in main, component 0x100):
  T  every per-aspect size/geometry table found by scan_tables.py: rows for ids 6 and 7
     (u32 (id,w,h) lists, u16 (id,0,w,h) lists, u16 (w,h,ratio-code) tables, u16 (w,h) arrays,
     u16 (x,y,w,h,x0,y0,x1,y1) display rects). New dims: width = max(4:3 row, 16:9 row) width,
     height rounded to the nearest multiple of 16 (review v0.3 M1). 16 is the alignment of every
     UI-reachable stock row in the 1024/1280/2560/320/1600/4032 classes and a multiple of every other
     table's stock alignment (2/4/8), so each new height stays inside its table's stock size class.
  M  Image Aspect option list (setting 270): relocated to the sec-6 FF tail with 8 entries
     [4:3,16:9,3:2,1:1,3:4,"Panorama"(id 6),"Wide"(id 7),17:9]; descriptor count 6->8 + pointer.
  P  SCP / Live Control option strip (v3, camera test 12d: Panorama/Wide missing from the SCP): the
     Lv_Control select array (0x61177140 -> 30 x 24-B records at 0x61176e70) has its own setting-270
     record 0x61176fc0 {270, 5, listA (white 50x38 icons), listB (green 64x48 icons)} with values
     1,3,2,4,9 only. Both lists grow to 7 entries; ids 6/7 use type-4 (string) entries 241 "Panorama" /
     2661 "Wide" (no aspect bitmap exists for them; the shared resolver 0x60df250b fills the string slot
     for type 4). List A is rewritten in place over the stock A+B block (only this record points there),
     list B moves to the sec-6 tail 0x61242f60; record count 5 -> 7.
  C  hard-coded consumers in sec 5: four 640-class size switches, the ratio switch and the
     fit-group switch get new jump-table targets; new case blocks live in the sec-1 FF tail.
  B  boot clamp (review v0.3 H3 / v0.4 M4): at power-on, if setting 270 holds 6 or 7, it is reset to its
     stock default (1 = 4:3) with the stock boot-reset primitive 0x602b972b, so no boot ever starts live view
     in Panorama/Wide. Hook: boot phase "MCS..MCE" (0x60192961, between trace marks 2_l and 2_o), at the
     common tail 0x601929a4 after the stock per-boot resets (0x602af9e1 / 0x602af9f9). Same gate as stock
     (byte 0x62257b04 != 1). Values 1..5, 8..10 are untouched.
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

# ---- P: SCP / Live Control option strip (Lv_Control select records {u16 setting, u16 count, listA, listB, 12 B 0})
SCP_DESC = 0x61176fc0             # {270, 5, 0x61175d78, 0x61175db4}
SCP_A, SCP_B, SCP_END = 0x61175d78, 0x61175db4, 0x61175df0   # stock lists, contiguous; referenced only by SCP_DESC
SCP_NEWB = 0x61242f60             # sec-6 FF tail after the menu list; 7 x 12 B = 84 B -> 0x61242fb4
SCP_COND = 0x611744e4             # zero word = unconditional (as the main menu's 0x611799dc)
SCP_ICONS = {1: (477, 472), 3: (476, 471), 2: (478, 473), 4: (2422, 2421), 9: (479, 475)}   # white, green
SEC6_END = 0x61243000             # section 6 load end
RESOLVE = 0x60df250b              # shared entry resolver: d0 value, d1 count, a1 list, caller (4,sp) = out

# ---- C: switch sites (jump-table entry address, stock target, new block kind)
BLOCKS_AT = 0x60210f00            # sec-1 FF tail (claim 0x60210f00-0x60210f80); sec 1 loads before sec 5
SW640 = [  # name, getter call site (mov 270,d0), table base (index=id), join, w reg, h reg
    ('S1', 0x6088b2b2, 0x60b04410, 0x6088b309, 2, 3), ('S2', 0x6088b385, 0x60b0443c, 0x6088b3dc, 3, 2),
    ('S3', 0x60899a41, 0x60b0dae0, 0x60899a98, 1, 0), ('S4', 0x6089b877, 0x60b0e0d4, 0x6089b8ce, 0, 1)]
S5 = dict(site=0x6086279a, base=0x60af4a04, join=0x608627fd, stock={6: 0x608627d3, 7: 0x608627db})  # index id-1
S6 = dict(site=0x60879e42, base=0x60b01530, stock=0x60879e65, wide=0x60879e70)                     # index id
GETTER = 0x602cbc0a
HEIGHT_ALIGN = 16                 # review v0.3 M1

# ---- B: boot clamp (review H3)
BOOT_SITE = 0x601929a4            # mov 0x601e7090,a0 ("MCE" trace string), then call 0x60023079 (trace; d0/d1 dead)
BOOT_EXPECT = bytes.fromhex('fcdc90701e60')
BOOT_RESUME = 0x601929aa
BOOT_AT = 0x60210e90              # sec-1 FF tail, inside the retired v0.4 sec-1 bloom block (clarity builds: stock FF)
BOOT_CLAIM = (0x60210e80, 0x60210ef0)   # guards 0x60210e80-e90 and stub end-0x60210ef0 stay FF
RESET_LIST = 0x602b972b           # stock boot reset: d0 = count, a0 = u16 id list -> each id := its default
RESET_GATE = 0x62257b04           # byte; stock skips its boot resets when == 1 (0x602cc6cf, 0x602af9e1)
SETTING = 270

# ---- V: static setting validator (v4, camera test 12e: Panorama/Wide in neither the menu nor the SCP).
# 0x604cc98c = 1333 x 20-B records {u16 sid, u16 attr, u32 list, u32 alt, u16 bytes, u16 elem, u8 sub, u8 type, u16 0}
# (docs/BUTTONS.md §2). It is the allowed-value list behind count 0x602b9f70 / value 0x602b9fdb, i.e. the GUI facade
# 0x607f9062 vt+24/+28 (0x60826d53 -> 0x602af8dc -> 0x602b1776; 0x60826d5f -> 0x602af8a3) and the menu builder
# 0x60886900, and the SCP strip / dial stepping (0x602b9cda). Sid 270: u8 list 0x604cb744 = 1,3,2,4,9 (5 B) -> 6/7
# (and 17:9 = 10) are filtered out. No registry record (0x604317ac, 439 x 60 B) for 270, so no dynamic list hook.
VAL_REC = 0x604cec14              # record 442 {270, 0x80, 0x604cb744, 0, 5, 1, 0, 1, 0}
VAL_LIST = 0x604cb744             # stock u8 list 01 03 02 04 09; the next list follows directly (cannot grow in place)
VAL_NEW = 0x60210f70              # sec-1 FF tail inside the aspect claim 0x60210f00-0x60210f80 (blocks end 0x60210f6e);
VAL_VALUES = (1, 3, 2, 4, 9, 6, 7)  # sec 1 loads first (order 1,7,2,...), before the sec-2 validator records
VAL_API = (0x602b9c00, 0x602ba600)   # hash init 0x602ba4cc, count 0x602b9f70, value 0x602b9fdb, step 0x602b9cda
VAL_RAM = (0x62248000, 0x6224c000)   # hash buckets 0x62248528, nodes 0x62248728

# ---- W (v5, camera test 13: capture and LV still used the stock 7:6 / 6:5 geometry).
# The capture pipeline does not read any of the TABLES above for the recorded size. It reads the split per-aspect
# size tables 0x6053de1c (u16 widths) / 0x6053dfcc (u16 heights), 9 ids x 24 size classes (48 B per id), through
# the getters 0x603f0a04 (W) / 0x603f0a18 (H) (d0 = id, d1 = class; ~80 call sites in the job builder
# 0x603e3000-0x603f1200 + RAW develop 0x60c65fb0). id 6 class 0 = 4544x3888, class 6 = 896x768, id 7 = 4672x3888 /
# 912x760: exactly what test 13 wrote (JPEG main + embedded preview). scan_tables.py missed them (w and h in separate arrays).
WH_W, WH_H, WH_CLASSES = 0x6053de1c, 0x6053dfcc, 24
# The ORF AspectFrame builder 0x603ebe95 dispatches by id (jump table 0x6053dd28, index id-1) into a "width-limited"
# case 0x603ebeac (ids 2,3,8: frame h = H(id)*W(1)/W(id)) and a "height-limited" case 0x603ebed5 (ids 4,5,6,7,9:
# frame w = W(id)*H(1)/H(id)). Ids 6/7 become wider than 4:3, so they move to the width-limited case (as S6).
FRAME_JT, FRAME_WIDE, FRAME_TALL = 0x6053dd28, 0x603ebeac, 0x603ebed5
# Ratio pairs (u8 W,H per id) sent to the AF / LV driver: .data table, flash 0x60236e14 (index id), copied at boot
# (0x600201fe: flash 0x60230800.. -> RAM 0x61f98540.., +0x1d67d40) and read by 0x60552d75 from RAM 0x61f9eb54
# (callers 0x6029457e/0x60294637 message +72/+73, 0x60552651 -> LV/AF globals 0xa276f955/6). Stock: 1:1 is 6:6.
RATIO_U8, RATIO_RAM, RATIO_FN = 0x60236e14, 0x61f9eb54, 0x60552d75
DATA_FLASH, DATA_RAM, DATA_END = 0x60230800, 0x61f98540, 0x6025eb50   # .data copy (end from 0x6218d984 init)
RATIO_U16 = 0x604e06ea            # same ratios as u16 pairs (index id); no static reference found, patched for consistency
GRID320 = 0x604d9cd2              # per-id (x0,x1,y0,y1) bounds in a 320x240 grid (read at 0x602ef370 via 0x602e82a8)


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
        al_stock = max(2, align_of(rows, iw, ih))    # stock class (2-power gcd, clamped 2..8): reported only
        al = HEIGHT_ALIGN                             # M1: every new height is a multiple of 16
        assert al % al_stock == 0
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
                out.append((addr, old, new, f'{lay}@{a1:#x} id{i} {tuple(rows[i-1])} -> {tuple(r)} ({name}, align {al}, stock class {al_stock})'))
    return out


def wh_row(d, i, k):
    """New 24-class row (k=0 widths, k=1 heights) for id i: class width = max(4:3, 16:9 width), height to 16."""
    w1 = struct.unpack_from('<24H', d, WH_W - B)
    w3 = struct.unpack_from('<24H', d, WH_W + 96 - B)
    old = struct.unpack_from('<24H', d, (WH_W, WH_H)[k] + 48 * (i - 1) - B)
    ow = struct.unpack_from('<24H', d, WH_W + 48 * (i - 1) - B)
    _, rw, rh = NEW[i]
    out = []
    for c in range(WH_CLASSES):
        if ow[c] == 0:                      # class not offered for this id in stock: keep 0
            out.append(old[c])
            continue
        W = max(w1[c], w3[c])
        out.append(W if k == 0 else round(W * rh / rw / HEIGHT_ALIGN) * HEIGHT_ALIGN)
    return struct.pack('<24H', *out)


def grid_row(i):
    _, rw, rh = NEW[i]
    h = 2 * round(320 * rh / rw / 2)
    return (0, 320, (240 - h) // 2, (240 - h) // 2 + h)


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


def boot_stub():
    """Assemble the boot clamp; return bytes (code + u16 id list)."""
    c = bytearray()
    a = lambda: BOOT_AT + len(c)
    c += b'\xfc\xa8' + struct.pack('<I', RESET_GATE)          # movbu (RESET_GATE),d0
    c += b'\xa0\x01'                                            # cmp 1,d0
    i_beq = len(c); c += b'\xc8\x00'                            # beq out
    c += mov16(0, SETTING)                                       # mov 270,d0
    c += b'\xdd' + struct.pack('<i', GETTER - a()) + b'\x00\x04'  # call 0x602cbc0a,[],4  (getter by ID)
    c += b'\x1c'                                                 # exthu d0
    c += b'\x28\xfa'                                            # add -6,d0
    c += b'\xa0\x01'                                            # cmp 1,d0
    i_bhi = len(c); c += b'\xc5\x00'                            # bhi out  (unsigned: only 6, 7 fall through)
    c += b'\x80\x01'                                            # mov 1,d0       (count)
    i_lst = len(c); c += b'\xfc\xdc' + b'\0' * 4                # mov LIST,a0
    c += b'\xdd' + struct.pack('<i', RESET_LIST - a()) + b'\xf0\x1c'  # call 0x602b972b,[d2,d3,a2,a3],28
    out = len(c)
    c += BOOT_EXPECT                                             # replayed: mov 0x601e7090,a0
    c += b'\xdc' + struct.pack('<i', BOOT_RESUME - a())          # jmp 0x601929aa
    c[i_beq + 1] = out - (i_beq)
    c[i_bhi + 1] = out - (i_bhi)
    if len(c) % 2:
        c += b'\xff'
    lst = BOOT_AT + len(c)
    c[i_lst + 2:i_lst + 6] = struct.pack('<I', lst)
    c += struct.pack('<H', SETTING)
    assert BOOT_AT + len(c) <= BOOT_CLAIM[1] - 16
    return bytes(c), lst


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
    # P: SCP / Live Control strip
    sdesc = d[SCP_DESC - B:SCP_DESC - B + 24]
    assert struct.unpack_from('<HHII', sdesc) == (270, 5, SCP_A, SCP_B) and sdesc[12:] == bytes(12)
    for base, k in ((SCP_A, 0), (SCP_B, 1)):
        ents = [struct.unpack_from('<IHHI', d, base + 12 * j - B) for j in range(5)]
        assert ents == [(v, 3, SCP_ICONS[v][k], SCP_COND) for v in (1, 3, 2, 4, 9)], hex(base)
    assert SCP_B == SCP_A + 60 and SCP_END == SCP_B + 60
    extra = b''.join(struct.pack('<IHHI', i, 4, STR_LABEL[i], SCP_COND) for i in (6, 7))
    new_a = d[SCP_A - B:SCP_B - B] + extra
    new_b = d[SCP_B - B:SCP_END - B] + extra
    assert len(new_a) == len(new_b) == 84 and SCP_A + 84 <= SCP_END
    assert d[SCP_NEWB - B:SEC6_END - B] == b'\xff' * (SEC6_END - SCP_NEWB)
    assert MENU_NEW + len(newlist) <= SCP_NEWB
    edit(SCP_A, d[SCP_A - B:SCP_A - B + 84], new_a, 'SCP/Live Control 270 list A (white) in place: 7 entries, +Panorama/Wide (type-4 text)')
    edit(SCP_NEWB, b'\xff' * 84, new_b, 'SCP/Live Control 270 list B (green) relocated to sec-6 tail: 7 entries')
    edit(SCP_DESC, sdesc[:12], struct.pack('<HHII', 270, 7, SCP_A, SCP_NEWB), 'SCP/Live Control 270 record: count 5->7, list B ptr')
    # V: validator list for sid 270 (relocated, 5 -> 7 values)
    rec = d[VAL_REC - B:VAL_REC - B + 20]
    assert struct.unpack('<HHIIHHBBH', rec) == (270, 0x80, VAL_LIST, 0, 5, 1, 0, 1, 0), rec.hex()
    assert d[VAL_LIST - B:VAL_LIST - B + 5] == bytes([1, 3, 2, 4, 9])
    vl = bytes(VAL_VALUES)
    edit(VAL_NEW, b'\xff' * len(vl), vl, 'setting 270 validator list relocated: 1,3,2,4,9 + 6 (Panorama), 7 (Wide)')
    edit(VAL_REC + 4, rec[4:14], struct.pack('<IIH', VAL_NEW, 0, len(vl)),
         'setting 270 validator record: list ptr -> sec-1 tail, bytes 5 -> 7')
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
    # B: boot clamp
    stub, _ = boot_stub()
    edit(BOOT_AT, b'\xff' * len(stub), stub, 'H3 boot clamp: setting 270 in {6,7} -> stock default (4:3) at power-on')
    edit(BOOT_SITE, BOOT_EXPECT, jmp32(BOOT_SITE, BOOT_AT) + b'\xcb',
         'H3 boot clamp hook: boot tail mov 0x601e7090,a0 -> jmp boot clamp; nop')
    assert d[BOOT_CLAIM[0] - B:BOOT_CLAIM[1] - B] == b'\xff' * (BOOT_CLAIM[1] - BOOT_CLAIM[0])
    # W (v5): split capture size tables, ORF frame fit group, ratio pairs, 320 grid
    for base, k in ((WH_W, 0), (WH_H, 1)):
        for i in (6, 7):
            old = d[base + 48 * (i - 1) - B:base + 48 * i - B]
            new = bytes(wh_row(d, i, k))
            edit(base + 48 * (i - 1), old, new, f'capture size table {"WH"[k]}@{base:#x} id{i}: '
                 f'{struct.unpack("<24H", old)} -> {struct.unpack("<24H", new)}')
    for i in (6, 7):
        ea = FRAME_JT + 4 * (i - 1)
        old = d[ea - B:ea - B + 4]
        assert struct.unpack('<I', old)[0] == FRAME_TALL
        edit(ea, old, struct.pack('<I', FRAME_WIDE), f'ORF frame fit entry id{i}: height-limited -> width-limited case')
    old = d[RATIO_U8 + 12 - B:RATIO_U8 + 16 - B]
    assert old == bytes((7, 6, 6, 5))
    assert DATA_FLASH <= RATIO_U8 < DATA_END and RATIO_U8 - DATA_FLASH == RATIO_RAM - DATA_RAM
    edit(RATIO_U8 + 12, old, bytes((65, 24, 21, 9)), 'LV/AF ratio pair (u8, .data -> RAM 0x61f9eb60) ids 6/7: 7:6, 6:5 -> 65:24, 21:9')
    old = d[RATIO_U16 + 24 - B:RATIO_U16 + 32 - B]
    assert old == struct.pack('<4H', 7, 6, 6, 5)
    edit(RATIO_U16 + 24, old, struct.pack('<4H', 65, 24, 21, 9), 'ratio pair (u16) ids 6/7: 7:6, 6:5 -> 65:24, 21:9')
    old = d[GRID320 + 48 - B:GRID320 + 64 - B]
    assert struct.unpack('<8H', old) == (20, 300, 0, 240, 16, 304, 0, 240)
    edit(GRID320 + 48, old, struct.pack('<8H', *grid_row(6), *grid_row(7)), '320x240 per-aspect bounds ids 6/7 -> full width, centred band')
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


class Val:
    """Native static validator: hash init, then count/value-by-index/step (stock code from the image)."""
    CALLER, STACK, SP0 = 0x18000000, 0x18010000, 0x18011800

    def _run(self, target, regs, mask, frame, ram=None, extra=()):
        call = Region('caller', self.CALLER, b'\xdd' + struct.pack('<i', target - self.CALLER) + bytes([mask, frame]), 'rx')
        regions = [call, Region('stack', self.STACK, bytes(0x2000), 'rw'), img(self.d, 'code', *VAL_API, 'rx'),
                   img(self.d, 'vt', 0x604c0000, 0x604d4000), img(self.d, 'sec1', 0x60210e00, 0x60211000),
                   Region('ram', VAL_RAM[0], ram if ram is not None else self.ram, 'rw', True), *extra]
        r = execute(regions, {'pc': self.CALLER, 'sp': self.SP0, **regs}, self.CALLER + 7, limit=2_000_000)
        assert not r['fault'] and r['registers']['pc'] == self.CALLER + 7 and r['registers']['sp'] == self.SP0, \
            (hex(target), r['fault'])
        return r

    def __init__(self, d):
        self.d = d
        r = self._run(0x602ba4cc, {}, 0xb0, 12, ram=bytes(VAL_RAM[1] - VAL_RAM[0]))
        self.ram = bytes.fromhex(next(x for x in r['memory'] if x['name'] == 'ram')['hex'])

    def count(self, sid):
        return self._run(0x602b9f70, {'d0': sid}, 0x80, 8)['registers']['d0'] & 0xffff

    def value(self, sid, i):
        return self._run(0x602b9fdb, {'d0': sid, 'd1': i}, 0x80, 8)['registers']['d0'] & 0xffff

    def listed(self, sid):
        return [self.value(sid, i) for i in range(self.count(sid))]

    def step(self, sid, cur):
        buf = 0x19000000
        r = self._run(0x602b9cda, {'d0': sid, 'a0': buf}, 0xa0, 24,
                      extra=[Region('cur', buf, struct.pack('<I', cur), 'rw')])
        return r['registers']['d0'] & 0xffff


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


LOG = 0x19300000


def recorder(addr, ret, extra=b''):
    """Stub at addr: log d0 -> LOG, a0 (or d1) -> LOG+4, then the matching ret."""
    return Region(f'rec{addr:x}', addr, b'\xfc\x81' + struct.pack('<I', LOG) + extra +
                  b'\xfc\x81' + struct.pack('<I', LOG + 4) + ret, 'rx')


def chk_boot(d, v, gate):
    """Run the boot tail 0x601929a4 -> 0x601929aa with getter(270) = v and gate byte = gate.
    0x602b972b is a recorder (d0, a0). Returns (ok, called, (d0, a0), a0_at_resume)."""
    regs = [img(d, 'site', BOOT_SITE, BOOT_RESUME + 7, 'rx'), img(d, 'stub', BOOT_CLAIM[0], BOOT_CLAIM[1], 'rx'),
            getter_stub(v), recorder(RESET_LIST, b'\xdf\xf0\x1c', b'\xf1\xd0'),
            Region('gate', RESET_GATE & ~0xf, bytes([gate if i == RESET_GATE & 0xf else 0 for i in range(16)]), 'r'),
            Region('log', LOG, b'\xee' * 16, 'rw', True), Region('stack', STACK, bytes(0x2000), 'rw')]
    init = dict(pc=BOOT_SITE, sp=STACK + 0x1800, d2=0x2222, d3=0x3333, a2=0x4444, a3=0x5555, a0=0x1234, mdr=0)
    r, m = run(regs, init, BOOT_RESUME)
    R = r['registers']
    ok = (R['pc'] == BOOT_RESUME and not r['fault'] and R['sp'] == init['sp'] and
          all(R[k] == init[k] for k in ('d2', 'd3', 'a2', 'a3')))
    lg = struct.unpack_from('<II', m['log'], 0)
    return ok, lg != (0xeeeeeeee, 0xeeeeeeee), lg, R['a0']


def chk_reset_primitive(d, lst):
    """Native 0x602b972b(d0=1, a0=lst) with its callees stubbed: default getter 0x602b9bad returns 0x77, setter
    0x602cbc5d is a recorder. Returns (ok, (id, value) given to the setter, default-getter id)."""
    regs = [PR.caller(RESET_LIST, 0xf0, 28), img(d, 'fn', RESET_LIST, 0x602b9778, 'rx'), img(d, 'lst', lst & ~0xf, (lst & ~0xf) + 16),
            Region('dflt', 0x602b9bad, b'\xfc\x81' + struct.pack('<I', LOG + 8) + b'\x80\x77\xdf\xf0\x14', 'rx'),
            recorder(0x602cbc5d, b'\xdf\xc0\x0c', b'\x84'),
            Region('c122', 0x602cc122, b'\xdf\x00\x04', 'rx'), Region('c0d0', 0x602cc0d0, b'\xdf\x80\x08', 'rx'),
            Region('log', LOG, b'\xee' * 16, 'rw', True), Region('stack', STACK, bytes(0x2000), 'rw')]
    r, m = run(regs, {'pc': PR.CALLER, 'sp': STACK + 0x1800, 'd0': 1, 'a0': lst, 'd2': 0x2222}, PR.CALLER + 7)
    ok = r['registers']['pc'] == PR.CALLER + 7 and not r['fault'] and r['registers']['d2'] == 0x2222
    lg = struct.unpack_from('<III', m['log'], 0)
    return ok, (lg[0], lg[1]), lg[2]


def scp_lists(d):
    """Parse the SCP/Live Control 270 record -> (count, [(value, type, id)] for list A, same for list B)."""
    s, c, pa, pb = struct.unpack_from('<HHII', d, SCP_DESC - B)
    assert s == 270
    ent = lambda p: [struct.unpack_from('<IHHI', d, p + 12 * k - B)[:3] for k in range(c)]
    return c, ent(pa), ent(pb)


def chk_resolve(d, value, which):
    """Native 0x60df250b(d0 = value, d1 = record count, a1 = list A/B from the 270 record, out = (4,sp)).
    Stubs: memset 0x4700115e, strlen 0x600daed9 (-> 0, the cond word is 0). Returns (ok, (type, bitmap, string))
    with type 0xeeee when the value is not in the list (out untouched)."""
    _, c, pa, pb = struct.unpack_from('<HHII', d, SCP_DESC - B)
    lst = (pa, pb)[which]
    OUT = 0x19400000
    stack = bytearray(0x2000)
    struct.pack_into('<I', stack, 0x1800 + 4, OUT)
    regs = [PR.caller(RESOLVE, 0xf0, 24), img(d, 'fn', RESOLVE, 0x60df2632, 'rx'),
            img(d, 'la', 0x61175d70, 0x61175e00), img(d, 'cond', 0x611744e0, 0x611744f0),
            # sec-6 tail incl. list B; with a film-menu base this also maps its resolver hooks (0x61242d10/0x61242e10,
            # jumped to from the kind-4 point 0x60df255f/0x60df25dc) and their marker cells 0x61242e00..
            img(d, 'sec6tail', 0x61242d00, SEC6_END, 'rx'),
            Region('memset', 0x4700115e, b'\xdf\xa0\x08', 'rx'), Region('strlen', 0x600daed9, b'\x00\xdf\x00\x00', 'rx'),
            Region('out', OUT, b'\xee' * 0x60, 'rw', True), Region('stack', STACK, bytes(stack), 'rw')]
    r, m = run(regs, {'pc': PR.CALLER, 'sp': STACK + 0x1800, 'd0': value, 'd1': c, 'a1': lst, 'a0': 0x19500000,
                      'd2': 0x2222, 'a2': 0x3333}, PR.CALLER + 7)
    R = r['registers']
    ok = R['pc'] == PR.CALLER + 7 and not r['fault'] and R['d2'] == 0x2222 and R['a2'] == 0x3333 and R['sp'] == STACK + 0x1800
    return ok, struct.unpack_from('<3H', m['out'], 0)


def chk_wh(d, aid, cls, k):
    """Native size getter 0x603f0a04 (k=0, width) / 0x603f0a18 (k=1, height): d0 = id, d1 = class."""
    f = (0x603f0a04, 0x603f0a18)[k]
    regs = [PR.caller(f, 0, 0), img(d, 'fn', f, f + 20, 'rx'), img(d, 'tab', WH_W, WH_H + 9 * 48),
            Region('stack', STACK, bytes(0x2000), 'rw')]
    r, _ = run(regs, {'pc': PR.CALLER, 'sp': STACK + 0x1800, 'd0': aid, 'd1': cls}, PR.CALLER + 7)
    return r['registers']['pc'] == PR.CALLER + 7 and not r['fault'], r['registers']['d0'] & 0xffff


def chk_frame(d, aid, cls):
    """Native ORF AspectFrame builder 0x603ebe95..0x603ebf84 (id dispatch, both fit cases, size getters).
    Job J: +5202 id, +5204..5210 frame (x0, y0, x1, y1)."""
    J = 0x19400000
    job = bytearray(0x2000)
    job[5202] = aid
    job[5203] = 1
    stack = bytearray(0x2000)
    sp = STACK + 0x1000
    struct.pack_into('<II', stack, 0x1000 + 8, J, cls)
    regs = [img(d, 'code', 0x603ebe95, 0x603ebf88, 'rx'), img(d, 'get', 0x603f0a04, 0x603f0a2c, 'rx'),
            img(d, 'jt', FRAME_JT, FRAME_JT + 36), img(d, 'tab', WH_W, WH_H + 9 * 48),
            Region('stack', STACK, bytes(stack), 'rw'), Region('job', J, bytes(job), 'rw', True)]
    r, m = run(regs, {'pc': 0x603ebe95, 'sp': sp, 'a2': J + 5202, 'a3': J + 5203}, 0x603ebf84)
    ok = r['registers']['pc'] == 0x603ebf84 and not r['fault']
    fr = struct.unpack_from('<4H', m['job'], 5204)
    return ok, fr


def chk_ratio(d, aid):
    """Native 0x60552d75 (still path, d0 = 0, id = stack arg) reading the RAM copy of the .data ratio table."""
    O = 0x19500000
    stack = bytearray(0x2000)
    sp = STACK + 0x1800
    struct.pack_into('<I', stack, 0x1800 + 4, aid)
    lo = RATIO_RAM - 0x20
    ramtab = d[lo - (DATA_RAM - DATA_FLASH) - B:lo - (DATA_RAM - DATA_FLASH) - B + 0x40]   # boot copy: flash -> RAM
    regs = [PR.caller(RATIO_FN, 0x30, 0x1c), img(d, 'fn', RATIO_FN, RATIO_FN + 0x78, 'rx'),
            Region('ram', lo, ramtab, 'r'), Region('stack', STACK, bytes(stack), 'rw'),
            Region('out', O, b'\xee' * 4, 'rw', True)]
    r, m = run(regs, {'pc': PR.CALLER, 'sp': sp, 'd0': 0, 'd1': 0, 'a0': O, 'a1': O + 1}, PR.CALLER + 7)
    ok = r['registers']['pc'] == PR.CALLER + 7 and not r['fault'] and r['registers']['sp'] == sp
    return ok, tuple(m['out'][:2])


def lean_checks(d, p, rep):
    """v5 checks (W/F/R/G): ids 6/7 get the new geometry, ids 1-4/9 stay stock."""
    exp_w = {i: wh_row(d, i, 0) for i in (6, 7)}
    exp_h = {i: wh_row(d, i, 1) for i in (6, 7)}
    for aid in (1, 2, 3, 4, 6, 7, 9):
        for cls in (0, 2, 6):
            s = (chk_wh(d, aid, cls, 0), chk_wh(d, aid, cls, 1))
            q = (chk_wh(p, aid, cls, 0), chk_wh(p, aid, cls, 1))
            good = all(x[0] for x in s + q)
            sv, qv = (s[0][1], s[1][1]), (q[0][1], q[1][1])
            if aid in (6, 7):
                good &= qv == (struct.unpack_from('<H', exp_w[aid], 2 * cls)[0], struct.unpack_from('<H', exp_h[aid], 2 * cls)[0])
            else:
                good &= qv == sv
            rep(f'W size getters id{aid} class{cls}', good, sv, qv)
    for aid in (1, 2, 3, 4, 6, 7, 9):
        s_ok, s = chk_frame(d, aid, 0)
        p_ok, q = chk_frame(p, aid, 0)
        if aid in (6, 7):
            h = struct.unpack_from('<H', exp_h[aid], 0)[0]
            y0 = (3888 - h) // 2
            want = (0, y0, 5183, y0 + h - 1)
        else:
            want = s
        rep(f'F ORF AspectFrame id{aid} (5184x3888 sensor)', s_ok and p_ok and q == want, s, q)
    for aid in (1, 2, 3, 4, 6, 7, 9):
        s_ok, s = chk_ratio(d, aid)
        p_ok, q = chk_ratio(p, aid)
        want = {6: (65, 24), 7: (21, 9)}.get(aid, s)
        rep(f'R2 LV/AF ratio 0x60552d75 id{aid}', s_ok and p_ok and q == want, s, q)
    g = [struct.unpack_from('<4H', p, GRID320 + 8 * i - B) for i in (6, 7)]
    rep('G 320-grid bounds ids 6/7', g == [grid_row(6), grid_row(7)], [struct.unpack_from('<4H', d, GRID320 + 8 * i - B) for i in (6, 7)], g)


def menu_list(d):
    s, c, p = struct.unpack_from('<HHI', d, MENU_DESC - B)
    return [struct.unpack_from('<IHHI', d, p + 12 * k - B)[:3:2] for k in range(c)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', type=Path, help='write check results here')
    ap.add_argument('--base', type=Path, help='run every check on this spec + aspect (e.g. a merged release spec); '
                    'the "stock" side of each check is then stock + base')
    ap.add_argument('--out', type=Path, default=ROOT / 'patches/aspect/edits.json', help='standalone spec to write')
    ap.add_argument('--lean', action='store_true', help='v5 checks only (W/F/R2/G); skip the v1-v4 suite')
    a = ap.parse_args()
    stock = PR.main_image()
    edits, where, h640 = build(stock)          # standalone: every expect is a stock byte
    d = stock
    if a.base:
        bspec = json.loads(a.base.read_text())
        bsp = sorted((int(e['addr'], 16), int(e['addr'], 16) + len(e['new']) // 2) for e in bspec['edits'])
        asp = sorted((int(e['addr'], 16), int(e['addr'], 16) + len(e['new']) // 2) for e in edits)
        clash = [(hex(x[0]), hex(y[0])) for x in asp for y in bsp if x[0] < y[1] and y[0] < x[1]]
        assert not clash, f'aspect overlaps base: {clash[:5]}'
        for e in bspec['edits']:
            a_ = int(e['addr'], 16) - B
            assert stock[a_:a_ + len(e['expect']) // 2].hex() == e['expect'], e['addr']
        d = apply(stock, bspec['edits'])
        print(f'base {a.base}: {len(bspec["edits"])} edits, no overlap with the {len(edits)} aspect edits')
    p = apply(d, edits)
    res, ok = [], True
    L_H = {i: round(5184 * rh / rw / HEIGHT_ALIGN) * HEIGHT_ALIGN for i, (_, rw, rh) in NEW.items()}

    def rep(name, good, stock, patched, want=None):
        nonlocal ok
        ok &= bool(good)
        res.append(dict(check=name, passed=bool(good), stock=stock, patched=patched))
        print(f"{'PASS' if good else 'FAIL'} {name}: stock {stock} -> patched {patched}")

    lean_checks(d, p, rep)
    if a.lean:
        a.out.write_text(json.dumps(dict(components=['0x100'], edits=edits), indent=1) + '\n')
        print(f'{len(edits)} edits, {sum(len(e["new"]) // 2 for e in edits)} bytes; wrote {a.out} (lean: v5 checks only)')
        if a.json:
            a.json.write_text(json.dumps(dict(passed=bool(ok), checks=res), indent=1))
        sys.exit(0 if ok else 1)
    # table lookup + scale (crop) for all ids
    for aid in range(1, 11):
        s_ok, s = chk_table_lookup(d, aid)
        p_ok, q = chk_table_lookup(p, aid)
        exp = {6: (5184, L_H[6], 0x1841), 7: (5184, L_H[7], 0x0915)}.get(aid, s)
        rep(f'T 0x6034ee0b id{aid}', s_ok and p_ok and tuple(q) == tuple(exp), s, q)
    for aid in range(1, 10):
        s_ok, s = chk_scale(d, aid)
        p_ok, q = chk_scale(p, aid)
        exp = {6: (5184, L_H[6]), 7: (5184, L_H[7])}.get(aid, s)
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
            else:                                           # full 4:3 width, 16-aligned height, nearest 16-px step
                good = (q[0] == w1[0] and q[1] % HEIGHT_ALIGN == 0 and
                        abs(q[1] - q[0] * NEW[aid][2] / NEW[aid][1]) <= HEIGHT_ALIGN / 2)
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
    hs = []
    for a1, lay in TABLES:
        st, fmt, iw, ih = LAY[lay]
        for i in (6, 7):
            hs.append(struct.unpack_from(fmt, p, a1 + (i - 1) * st - B)[ih])
    hs += [h640[6], h640[7]]
    rep('M1 every new id-6/7 height is a multiple of 16', all(h % HEIGHT_ALIGN == 0 for h in hs),
        f'{len(hs)} heights', sorted(set(hs)))
    rep('M menu list', menu_list(p) == [(1, 292), (3, 291), (2, 293), (4, 1786), (9, 295), (6, 241), (7, 2661), (10, 3261)],
        menu_list(d), menu_list(p))
    # P: SCP / Live Control option strip
    want_a = [(v, 3, SCP_ICONS[v][0]) for v in (1, 3, 2, 4, 9)] + [(6, 4, 241), (7, 4, 2661)]
    want_b = [(v, 3, SCP_ICONS[v][1]) for v in (1, 3, 2, 4, 9)] + [(6, 4, 241), (7, 4, 2661)]
    pc_, pa_, pb_ = scp_lists(p)
    rep('P1 SCP/Live Control 270 record: 7 entries, lists A/B', (pc_, pa_, pb_) == (7, want_a, want_b),
        scp_lists(d)[0], (pc_, [e[0] for e in pa_]))
    rep('P2 SCP list B lives in the sec-6 tail, rest of the tail FF',
        struct.unpack_from('<I', p, SCP_DESC + 8 - B)[0] == SCP_NEWB and
        p[SCP_NEWB + 84 - B:SEC6_END - B] == b'\xff' * (SEC6_END - SCP_NEWB - 84), 'n/a', hex(SCP_NEWB))
    for which in (0, 1):
        for v in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10):
            s_ok, s = chk_resolve(d, v, which)
            p_ok, q = chk_resolve(p, v, which)
            if v in (6, 7):
                good = s[0] == 0xeeee and q[0] == 4 and q[2] == STR_LABEL[v]
            else:
                good = q == s and (q[0] == 0xeeee) == (v not in SCP_ICONS)
            rep(f'R resolver 0x60df250b list {"AB"[which]} value {v}', s_ok and p_ok and good, s, q)
    # V: static validator (the allowed-value list the menu, the SCP strip and dial stepping enumerate)
    VS, VP = Val(d), Val(p)
    sl, pl = VS.listed(SETTING), VP.listed(SETTING)
    rep('V1 validator 270 enumeration (count + value-by-index 0x602b9f70/0x602b9fdb)',
        sl == [1, 3, 2, 4, 9] and pl == list(VAL_VALUES), sl, pl)
    for v in (6, 7):
        rep(f'V2 value {v} is in the enumerated set', v not in sl and v in pl, v in sl, v in pl)
    rep('V3 17:9 (10) still filtered out (stock behaviour)', 10 not in pl, 10 in sl, 10 in pl)
    # step 0x602b9cda (a0 = &current; returns the previous list value, wrapping at the first) walks the new list
    prv = [VP.step(SETTING, v) for v in VAL_VALUES]
    spv = [VS.step(SETTING, v) for v in (1, 3, 2, 4, 9)]
    rep('V4 dial step 0x602b9cda walks the patched list (previous, wrap) like stock walks its list',
        prv == [VAL_VALUES[-1]] + list(VAL_VALUES[:-1]) and spv == [9, 1, 3, 2, 4], spv, prv)
    others = [s_ for s_ in (1, 2, 6, 9, 26, 34, 44, 47, 51, 175, 176, 177, 269, 271, 478, 563, 652, 776, 777, 987, 1110, 1716)]
    diff = [s_ for s_ in others if (VS.count(s_), VS.listed(s_)) != (VP.count(s_), VP.listed(s_))]
    rep(f'V5 {len(others)} other sids enumerate as before', not diff, 'n/a', diff)
    rep('V6 no registry record (dynamic list hook) for 270',
        all(struct.unpack_from('<H', p, 0x604317ac + 60 * i - B)[0] != SETTING for i in range(439)), 'n/a', 'none')
    # B: boot clamp (H3)
    _, lst = boot_stub()
    s_ok, s_called, _, s_a0 = chk_boot(d, 6, 0)
    rep('B0 stock boot tail reaches 0x601929aa with a0 = "MCE" string, no reset call', s_ok and not s_called and s_a0 == 0x601e7090,
        'stock', (s_ok, s_called, hex(s_a0)))
    rep('B1 id list word', struct.unpack_from('<H', p, lst - B)[0] == SETTING and lst % 2 == 0, hex(lst), SETTING)
    for gate in (0, 1, 2):
        for v in range(0, 11):
            ok_, called, lg, a0 = chk_boot(p, v, gate)
            want = v in (6, 7) and gate != 1
            good = ok_ and a0 == s_a0 and called == want and (not want or lg == (1, lst))
            rep(f'B2 boot clamp setting270={v} gate={gate}', good, 'no reset', ('reset' if called else 'no reset', lg if called else ''))
    ok_, sv, did = chk_reset_primitive(p, lst)
    rep('B3 stock 0x602b972b on [270]: default lookup id 270, setter(270, default)', ok_ and did == SETTING and sv == (SETTING, 0x77),
        'n/a', (did, sv))
    dflt = p[0x60097044 - B:0x60097044 - B + 6]
    rep('B4 defaults record for key 0x3081 is 1 (4:3)', dflt == bytes.fromhex('813001000100'), 'n/a', dflt.hex())
    out = a.out
    out.write_text(json.dumps(dict(components=['0x100'], edits=edits), indent=1) + '\n')
    nbytes = sum(len(e['new']) // 2 for e in edits)
    print(f'{len(edits)} edits, {nbytes} bytes; blocks {min(where.values()):#x}..; wrote {out}')
    if a.json:
        a.json.write_text(json.dumps(dict(passed=bool(ok), checks=res), indent=1))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
