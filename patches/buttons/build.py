#!/usr/bin/env python3
"""E-P7 1.1 button-function widening (data-only). OFFLINE; emulator only; no camera.

What the firmware does (docs/BUTTONS.md has the evidence):
  * Every assignable button is a setting (sid). Its value is a FUNCTION CODE (e.g. 568 Peaking,
    3474 Magnify, 3552 ISO/WB). The menu, the dial stepping and value validation all read the
    allowed codes from the static per-sid validator list: records of 20 bytes at 0x604cc98c
    ({u16 sid, u16 attr, u32 list, u32 alt, u16 bytes, u16 elem, u8 sub, u8 type, u16 0}, 1333
    records hashed by sid&127 by 0x602ba4cc). No availability filter exists for these sids
    (0x602b2fad only filters sid 1716) and their registry objects have no dynamic list (+20 == 0).
  * The press dispatcher 0x60cc872f: key -> sid (table 0x60f389a8, 21 x 16 B, flag 0 = arrow pad)
    -> value (0x60cc8979) -> [flag 1 only: 0x60cc8ad3 AEL/movie filter] -> action via the
    55-entry function table 0x60f38af8. It never checks which key a function came from.

Edits (component 0x100, all in section 2, in place, no new code space):
  F  sids 47/48/49 (12-entry lists 0x604cae3c/54/6c, contiguous 72 B): one shared 23-entry list
     written at 0x604cae3c; records 0x604cda08/1c/30 -> ptr 0x604cae3c, bytes 46.
  D  sids 51/53 = arrow right/down (8-entry lists 0x604cb00e/1e, contiguous 32 B): one shared
     16-entry list at 0x604cb00e; records 0x604cdad0/e4 -> ptr 0x604cb00e, bytes 32.
Every added code already exists in a stock list of another E-P7 button sid, has an action in the
function table and a label/icon/help entry in the Button Function label table 0x611d78cc.

Usage: patches/buttons/build.py            (emit patches/buttons/edits.json + run checks)
       tools/ep7_buttons_verify.py SPEC     (re-run the emulator checks on any spec / merge)
"""
import json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
B = 0x60020020
VT, VT_N, VT_SZ = 0x604cc98c, 1333, 20          # validator records
FUNC_TAB, FUNC_N = 0x60f38af8, 55               # {u32 code, u32 action, u32 alt}
KEY_TAB, KEY_N = 0x60f389a8, 21                 # {u32 keycode, u32 sid, u32 sid_alt, u32 full}
LABELS = (0x611d78cc, 0x611d7da0)               # Button Function label/icon/help entries (12 B)

STOCK_FULL = [3453, 44, 106, 84, 85, 88, 3461, 34, 3474, 568, 426, 3200]
STOCK_DPAD = [3461, 16, 3281, 426, 3558, 15130, 88, 3200]
# sid -> (record addr, stock list addr, stock list)
FULL_RECS = {47: (0x604cda08, 0x604cae3c), 49: (0x604cda1c, 0x604cae54), 48: (0x604cda30, 0x604cae6c)}
DPAD_RECS = {51: (0x604cdad0, 0x604cb00e), 53: (0x604cdae4, 0x604cb01e)}
FULL_AT, FULL_ROOM = 0x604cae3c, 72
DPAD_AT, DPAD_ROOM = 0x604cb00e, 32

NEW_FULL = [3453, 44, 106, 84, 85, 3340, 88, 22, 3317, 3461, 34, 686, 3474, 473, 605,
            3552, 3553, 437, 568, 3557, 426, 157, 3200]
NEW_DPAD = [3461, 16, 3281, 426, 3558, 15130, 88,
            3552, 3553, 568, 3474, 3557, 34, 437, 22, 3200]
NAMES = {3453: 'AEL/AFL', 44: 'REC', 106: 'Preview', 84: 'One-touch WB', 85: 'AF area select',
         3340: 'AF Home', 88: 'MF', 22: 'RAW', 3317: 'Test picture', 3461: 'Exposure comp',
         34: 'Digital tele-converter', 686: 'Keystone comp', 3474: 'Magnify', 473: 'HDR', 605: 'BKT',
         3552: 'ISO/WB', 3553: 'WB/ISO', 437: 'Multi Function', 568: 'Peaking', 3557: 'Level display',
         426: 'Touch lock', 157: 'IS mode', 3200: 'Off', 16: 'Flash mode', 3281: 'Drive/self-timer',
         3558: 'Electronic zoom', 15130: 'LV-C/LV-SCP switch'}


def img():
    return (ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes()


def rd(d, a, n):
    return d[a - B:a - B + n]


def record(d, a):
    sid, attr, p, p2, size, el, sub, typ, z = struct.unpack('<HHIIHHBBH', rd(d, a, 20))
    return dict(sid=sid, attr=attr, ptr=p, alt=p2, size=size, el=el, sub=sub, typ=typ)


def u16list(d, a, n):
    return list(struct.unpack('<%dH' % n, rd(d, a, 2 * n)))


def abs32_refs(d, target):
    pat, out, i = struct.pack('<I', target), [], d.find(struct.pack('<I', target))
    while i >= 0:
        out.append(i + B)
        i = d.find(pat, i + 1)
    return out


def func_actions(d):
    return {struct.unpack('<I', rd(d, FUNC_TAB + 12 * i, 4))[0]: struct.unpack('<I', rd(d, FUNC_TAB + 12 * i + 4, 4))[0]
            for i in range(FUNC_N - 1, -1, -1)}   # first match wins in 0x60cc885c


def label_codes(d):
    out = set()
    for a in range(LABELS[0], LABELS[1], 12):
        v, t, s, c = struct.unpack('<IHHI', rd(d, a, 12))
        if t == 4:
            out.add(v)
    return out


def static_checks(d):
    """Stock preconditions; returns list of (name, ok, detail)."""
    res = []
    recs = {}
    for sid, (ra, la) in {**FULL_RECS, **DPAD_RECS}.items():
        r = record(d, ra)
        stock = STOCK_FULL if sid in FULL_RECS else STOCK_DPAD
        ok = (r['sid'] == sid and r['ptr'] == la and r['size'] == 2 * len(stock) and r['el'] == 2 and r['typ'] == 5
              and r['sub'] == 0 and r['alt'] == 0 and (ra - VT) % VT_SZ == 0 and u16list(d, la, len(stock)) == stock)
        recs[sid] = r
        res.append((f'stock record sid {sid} @{ra:#x} -> {la:#x} n={len(stock)}', ok, r))
        refs = abs32_refs(d, la)
        res.append((f'list {la:#x} referenced only by its record', refs == [ra + 4], [hex(x) for x in refs]))
    res.append(('full lists contiguous (72 B)', FULL_RECS[49][1] == FULL_AT + 24 and FULL_RECS[48][1] == FULL_AT + 48, ''))
    res.append(('d-pad lists contiguous (32 B)', DPAD_RECS[53][1] == DPAD_AT + 16, ''))
    res.append(('new lists fit', 2 * len(NEW_FULL) <= FULL_ROOM and 2 * len(NEW_DPAD) <= DPAD_ROOM, ''))
    # no other record points into the rewritten ranges
    bad = []
    for i in range(VT_N):
        r = record(d, VT + VT_SZ * i)
        for lo, n in ((FULL_AT, FULL_ROOM), (DPAD_AT, DPAD_ROOM)):
            if lo <= r['ptr'] < lo + n and r['sid'] not in FULL_RECS and r['sid'] not in DPAD_RECS:
                bad.append((r['sid'], hex(r['ptr'])))
    res.append(('no other validator record uses the rewritten bytes', not bad, bad))
    fa, lab = func_actions(d), label_codes(d)
    # every code: has an action, a Button-Function label, and is allowed on some stock button sid
    stock_any = set()
    for i in range(VT_N):
        r = record(d, VT + VT_SZ * i)
        if r['typ'] == 5 and r['el'] == 2 and r['ptr'] and 600 < r['ptr'] - 0x604c0000 < 0x10000 and r['sid'] in (
                47, 48, 49, 51, 53, 54, 55, 56, 571, 572, 573, 1266, 1269, 1271):
            stock_any |= set(u16list(d, r['ptr'], r['size'] // 2))
    for code in sorted(set(NEW_FULL + NEW_DPAD)):
        ok = code in fa and code in lab and code in stock_any
        res.append((f'code {code} {NAMES.get(code, "")}: action {fa.get(code)}, label, in a stock button list', ok, ''))
    res.append(('lists end with Off(3200), no duplicates',
                NEW_FULL[-1] == NEW_DPAD[-1] == 3200 and len(set(NEW_FULL)) == len(NEW_FULL) and len(set(NEW_DPAD)) == len(NEW_DPAD), ''))
    res.append(('stock codes kept', set(STOCK_FULL) <= set(NEW_FULL) and set(STOCK_DPAD) <= set(NEW_DPAD), ''))
    # key table: arrow pad sids are flag 0, full buttons flag 1
    keys = [struct.unpack('<4I', rd(d, KEY_TAB + 16 * i, 16)) for i in range(KEY_N)]
    flags = {k[1]: k[3] for k in keys}
    res.append(('key table: sids 50-53 arrow pad (flag 0), 47/48/49 full (flag 1)',
                all(flags.get(s) == 0 for s in (50, 51, 52, 53)) and all(flags.get(s) == 1 for s in (47, 48, 49)),
                {s: flags.get(s) for s in (47, 48, 49, 50, 51, 52, 53)}))
    return res


def edits(d):
    e = []
    def add(addr, new, why):
        old = rd(d, addr, len(new))
        if old != new:
            e.append(dict(kind='0x100', addr=hex(addr), expect=old.hex(), new=new.hex(), why=why))
    add(FULL_AT, struct.pack('<%dH' % len(NEW_FULL), *NEW_FULL),
        f'buttons: shared full-button function list ({len(NEW_FULL)} codes) for sids 47/48/49')
    add(DPAD_AT, struct.pack('<%dH' % len(NEW_DPAD), *NEW_DPAD),
        f'buttons: shared arrow right/down function list ({len(NEW_DPAD)} codes) for sids 51/53')
    for sid, (ra, _) in FULL_RECS.items():
        add(ra + 4, struct.pack('<I', FULL_AT), f'buttons: sid {sid} list ptr -> {FULL_AT:#x}')
        add(ra + 12, struct.pack('<H', 2 * len(NEW_FULL)), f'buttons: sid {sid} list bytes 24 -> {2 * len(NEW_FULL)}')
    for sid, (ra, _) in DPAD_RECS.items():
        add(ra + 4, struct.pack('<I', DPAD_AT), f'buttons: sid {sid} list ptr -> {DPAD_AT:#x}')
        add(ra + 12, struct.pack('<H', 2 * len(NEW_DPAD)), f'buttons: sid {sid} list bytes 16 -> {2 * len(NEW_DPAD)}')
    return e


def spec():
    d = img()
    return dict(patch='buttons', components=['0x100'], edits=edits(d),
                buttons=dict(full_sids=sorted(FULL_RECS), dpad_sids=sorted(DPAD_RECS),
                             full=NEW_FULL, dpad=NEW_DPAD, full_at=hex(FULL_AT), dpad_at=hex(DPAD_AT)))


def main():
    d = img()
    ok = True
    for name, good, detail in static_checks(d):
        ok &= bool(good)
        print(f"{'PASS' if good else 'FAIL'} {name}" + (f'  {detail}' if not good and detail else ''))
    s = spec()
    out = ROOT / 'patches/buttons/edits.json'
    out.write_text(json.dumps(s, indent=1) + '\n')
    print(f"wrote {out}: {len(s['edits'])} edits, {sum(len(x['new']) // 2 for x in s['edits'])} bytes")
    sys.path.insert(0, str(ROOT / 'tools'))
    import ep7_buttons_verify as V
    ok &= V.verify(s)
    print('OVERALL', 'PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
