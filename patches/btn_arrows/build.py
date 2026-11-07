#!/usr/bin/env python3
"""Arrow rows in Custom Menu > Button Function (data only). Offline. docs/BUTTONS.md §4c/§4d.

Key -> sid (event table 0x60f3928c + SEND_KEY ids: keycode 4 up, 5 down, 6 left, 7 right; key table 0x60f389a8):
  50 = UP (fixed, Exp comp), 51 = DOWN (Drive), 52 = LEFT (fixed, AF point), 53 = RIGHT (Flash).
Arrow press: dispatcher 0x60cc872f -> sid value (0x60cc8979, no override for 51/53) -> kind 0 (no 0x60cc8ad3 filter)
-> function table 0x60f38af8 -> action. Same codes and table as REC/Fn. Labels: item records point every button sid at
the shared 44-entry value label list 0x611baf8c (by value). Picker (Cursor_Move_Set_Mode default 0x60de3670) keeps
greyed entries in its arrays, so the shown label, the stored code and the action stay index-consistent.

Edits:
  rows   Cursor_Move mode-42 list (record 0x61150568) -> [47, 48, 53, 51] at 0x61242fe8 (Fn, REC, right, down)
  list   arrow list (sids 51/53, shared, 0x604cb00e) = stock 8 + ISO/WB, WB/ISO, Peaking, Level, tele-con, RAW (14);
         Magnify (frame move) and Multi Function (hold + dial) left out. Replaces the omc_buttons arrow edits in place.
  title  right row (sid 53, item records 0x611bf7c4 / 0x611ccf30): kind 4 '@A027@Function' (another body's key icon)
         -> kind 5 text "Right Fn" at 0x61242ff0. Down row keeps its stock drive-icon title.
Stored values are untouched: right = Flash, down = Drive until the user changes them.

  .venv/bin/python -I patches/btn_arrows/build.py generated/aspect_scp/t1/edits.json --out generated/combo/b5/edits.json --version 0.28b5
  .venv/bin/python -I tools/build_package.py generated/combo/b5/edits.json --out generated/combo/b5/pkg
  .venv/bin/python -I patches/btn_arrows/verify.py generated/aspect_scp/t1/edits.json generated/combo/b5/edits.json generated/combo/b5/pkg
"""
import argparse, copy, importlib.util, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
SRC = 'patches/btn_arrows'
REC, OLD_LIST = 0x61150568, 0x611500f2
ROWS = [47, 48, 53, 51]
AT = 0x61242fe8                     # row list (u16 x 4)
TEXT_AT, TEXT = 0x61242ff0, b'Right Fn\0'
TAIL = (0x61242fe0, 0x61243000)     # sec-6 FF tail after the fw_version label; section load end 0x61243000
DPAD_AT, DPAD_ROOM = 0x604cb00e, 32
DPAD_RECS = {51: 0x604cdad0, 53: 0x604cdae4}
STOCK_DPAD = [3461, 16, 3281, 426, 3558, 15130, 88, 3200]
DPAD = [3461, 16, 3281, 426, 3558, 15130, 88, 3552, 3553, 568, 3557, 34, 22, 3200]
TITLES = (0x611bf7c4, 0x611ccf30)   # sid 53 item records (tree 1, tree 2): {u32 id, u16 kind, u16 str, u32 text}
FUNC_TAB, LABELS = 0x60f38af8, 0x611baf8c
AVOID = (0x601e1d80, 0x601e1e00)    # aspect_scp


def _overlaps(spec, lo, hi, allow=()):
    return [e['addr'] for e in spec['edits'] if not e['addr'].startswith('off:') and e.get('source') not in allow
            and int(e['addr'], 16) < hi and lo < int(e['addr'], 16) + len(e['new']) // 2]


def table(stock):
    """code -> (action, label kind, string id) for every arrow code, from the stock tables."""
    rd = lambda a, n: stock[a - BASE:a - BASE + n]
    fa = {}
    for i in range(54, -1, -1):
        c, a, _ = struct.unpack('<III', rd(FUNC_TAB + 12 * i, 12)); fa[c] = a
    lab = {}
    for i in range(44):
        v, k, s, _ = struct.unpack('<IHHI', rd(LABELS + 12 * i, 12)); lab.setdefault(v, (k, s))
    return {c: (fa.get(c), lab.get(c)) for c in DPAD}


def apply(spec, version='0.28b5'):
    stock = STOCK.read_bytes()
    rd = lambda a, n: stock[a - BASE:a - BASE + n]
    spec = copy.deepcopy(spec)
    if 'btn_arrows' in spec or 'btn_probe' in spec:
        raise SystemExit('base already has btn_arrows / btn_probe')
    if spec.get('buttons', {}).get('dpad_at') != hex(DPAD_AT):
        raise SystemExit('base lacks the omc_buttons arrow list')
    m, p, n = struct.unpack('<IIH', rd(REC, 10))
    if (m, p, n) != (42, OLD_LIST, 2) or list(struct.unpack('<2H', rd(OLD_LIST, 4))) != [47, 48]:
        raise SystemExit('mode-42 record differs from stock')
    if [BASE + i for i in range(len(stock) - 3) if stock[i:i + 4] == struct.pack('<I', OLD_LIST)] != [REC + 4]:
        raise SystemExit('old row list has other references')
    if set(rd(TAIL[0], TAIL[1] - TAIL[0])) != {0xff}:
        raise SystemExit('sec-6 tail not FF')
    for t in TITLES:
        if struct.unpack('<IHH', rd(t, 8)) != (53, 4, 381) or rd(struct.unpack('<I', rd(t + 8, 4))[0], 1) != b'\0':
            raise SystemExit(f'title record {t:#x} differs')
    tab = table(stock)
    bad = [c for c, (a, l) in tab.items() if a is None or l is None or (a == 0 and c != 3200)]
    if bad:
        raise SystemExit(f'codes without action/label: {bad}')
    for lo, hi in (TAIL, (REC + 4, REC + 10)) + tuple((t + 4, t + 12) for t in TITLES):
        if _overlaps(spec, lo, hi):
            raise SystemExit(f'{lo:#x}: overlaps {_overlaps(spec, lo, hi)}')
    if 2 * len(DPAD) > DPAD_ROOM or DPAD[-1] != 3200 or not set(STOCK_DPAD) <= set(DPAD) or len(set(DPAD)) != len(DPAD):
        raise SystemExit('arrow list')
    if AT % 4 or TEXT_AT + len(TEXT) > TAIL[1] or AT + 8 > TEXT_AT or AVOID[0] <= AT < AVOID[1]:
        raise SystemExit('placement')

    def add(addr, new, why):
        spec['edits'].append(dict(kind='0x100', addr=hex(addr), expect=rd(addr, len(new)).hex(), new=new.hex(), source=SRC,
                                  why=f'btn_arrows: {why}'))

    def replace(addr, new, why):     # an omc_buttons edit at exactly this address
        hits = [e for e in spec['edits'] if e['addr'] == hex(addr) and e.get('source') == 'patches/omc_buttons']
        if len(hits) != 1:
            raise SystemExit(f'{addr:#x}: omc_buttons edit not found')
        e = hits[0]
        full = bytearray(rd(addr, len(e['new']) // 2)); full[:len(new)] = new
        e.update(new=bytes(full).hex(), source=SRC, why=f'btn_arrows: {why}')

    replace(DPAD_AT, struct.pack('<%dH' % len(DPAD), *DPAD), f'arrow function list sids 51/53 ({len(DPAD)} codes)')
    for sid, ra in DPAD_RECS.items():
        replace(ra + 12, struct.pack('<H', 2 * len(DPAD)), f'sid {sid} list bytes -> {2 * len(DPAD)}')
    add(AT, struct.pack('<%dH' % len(ROWS), *ROWS), f'Button Function rows {ROWS} (mode 42 list, sec-6 tail)')
    add(REC + 4, struct.pack('<IH', AT, len(ROWS)), f'mode-42 record list -> {AT:#x}, count 2 -> {len(ROWS)}')
    add(TEXT_AT, TEXT, 'right-row title text "Right Fn"')
    for t in TITLES:
        add(t + 4, struct.pack('<H', 5), f'sid 53 item {t:#x} label kind 4 -> 5')
        add(t + 8, struct.pack('<I', TEXT_AT), f'sid 53 item {t:#x} label text -> {TEXT_AT:#x}')
    if version:
        fv = importlib.util.spec_from_file_location('fw_version_build', ROOT / 'patches/fw_version/build.py')
        FV = importlib.util.module_from_spec(fv); fv.loader.exec_module(FV)
        spec = FV.apply(spec, version)
    spec['buttons'] = dict(spec['buttons'], dpad=DPAD)
    spec['btn_arrows'] = dict(built_by=SRC, version=version, rows=ROWS, list_at=hex(AT), record=hex(REC), dpad=DPAD,
                              text_at=hex(TEXT_AT), titles=[hex(t) for t in TITLES],
                              table={c: dict(action=a, label=list(l)) for c, (a, l) in tab.items()})
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--version', default='0.28b5')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()), a.version)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps({k: v for k, v in spec['btn_arrows'].items() if k != 'table'}))
