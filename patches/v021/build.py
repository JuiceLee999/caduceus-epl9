#!/usr/bin/env python3
"""v0.21 = releases/v0.20 (byte level) + 5 COLOR grain levels + Blur Art Effect off (issue #20). Offline.

  python3 -I patches/v021/build.py releases/v0.20/edits.json --out releases/v0.21/edits.json

Slot grain byte +24 is 0..5 (was 0..3). Gains (patches/grain_boost, own table): 1..5 = 220/600/1200/1500/1800.
Levels 1..3 keep the v0.16..v0.20 gains, so old cards (bytes 0..3) look exactly as before; 4/5 are new.
Edits on top of the v0.20 spec (every old byte is asserted):
  grain stub (sec 1)   GLEVEL bound `add -1; cmp 3; bcc` -> cmp 5 in wl_hook and grain_mod (0x60210d3c, 0x60210dd3)
  grain boost          rebuilt: 5-entry table + hook C 0x603a06ed (combiner 32, level not 1..3 -> key 11 levels 4/5)
  SD loader v3 range   span byte +24 3 -> 5 (0x605b7739); LOOKS.BIN fm_check span +24 3 -> 5 (0x6143a7cd)
  look extras sector 1 ex_get bound cmp 4 -> 6 (0x601e32cc); ex_set clamp 0..3 -> 0..5 (0x601e33d2/d6);
                       label bound cmp 4 -> 6 (0x601e3565); label table ptr 0x601e35f0 -> new 6-entry table at
                       0x601e3840 (dead EVF step-0 R table; only ref: step-table word 0x601e3c80): "1 Grain Off"
                       (the old string) and "1 Grain 1".."1 Grain 5". Value clamps at 0 and 5 (no wrap), as before.
  Blur off (issue #20) COLOR Art stub bound 1..3 -> 1..2 and its Blur entry -> no-op (0x601e1d42/71/75); lv_art LV
                       bound -> Pin Hole only, Blur entry -> 0 (0x601e11c3/0x601e1215); look extras art read 3 -> Off
                       (0x601e331c) and ex_set wrap modulo 3 (Off / Star Light / Pin Hole; 0x601e33a0..b6).
                       A stored Blur byte (old cards) is kept on the card but does nothing. docs/ISSUES_19_20.md.
  fw_version           value "0.21" (run patches/fw_version/build.py afterwards, --mod-version 0.21)
"""
import argparse, copy, importlib.util, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
SRC = 'patches/v021'
BYTES = [  # (addr, old, new, what)
    (0x60210d3c, 0x03, 0x05, 'grain wl_hook GLEVEL bound 1..3 -> 1..5'),
    (0x60210dd3, 0x03, 0x05, 'grain grain_mod GLEVEL bound 1..3 -> 1..5'),
    (0x605b7739, 0x03, 0x05, 'SD loader v3 range: grain span 3 -> 5 (0..5)'),
    (0x6143a7cd, 0x03, 0x05, 'LOOKS.BIN fm_check range: grain span 3 -> 5 (0..5)'),
    (0x601e32cc, 0x04, 0x06, 'look extras ex_get: grain read bound < 6'),
    (0x601e33d2, 0x03, 0x05, 'look extras ex_set: grain clamp max 5 (cmp)'),
    (0x601e33d6, 0x03, 0x05, 'look extras ex_set: grain clamp max 5 (mov)'),
    (0x601e3565, 0x04, 0x06, 'look extras label: grain index < 6'),
    # issue #20 (COLOR + Blur restarts the camera without saving): Blur (art 3) is mapped to Off everywhere
    (0x601e1d42, 0x03, 0x02, 'COLOR Art stub: art bound 1..3 -> 1..2 (Blur = Off, issue #20)'),
    (0x601e1d71, 0xfc, 0xff, 'COLOR Art stub: Blur entry AND mask ~0x300 -> ~0 (dead entry, no-op)'),
    (0x601e1d75, 0x01, 0x00, 'COLOR Art stub: Blur entry OR 0x100 -> 0 (dead entry, no-op)'),
    (0x601e11c3, 0x02, 0x01, 'lv_art: LV art bound 2..3 -> 2 (Pin Hole only; Blur not previewed)'),
    (0x601e1215, 0x01, 0x00, 'lv_art: LV Blur flag 0x100 -> 0 (dead entry, no-op)'),
    (0x601e331c, 0x04, 0x03, 'look extras ex_get: art byte 3 (Blur) reads Off'),
    (0x601e33a0, 0xfc, 0xfd, 'look extras ex_set: art pre-clamp low -4 -> -3 (cmp)'),
    (0x601e33a4, 0xfc, 0xfd, 'look extras ex_set: art pre-clamp low -4 -> -3 (mov)'),
    (0x601e33a6, 0x07, 0x05, 'look extras ex_set: art pre-clamp high 7 -> 5 (cmp)'),
    (0x601e33aa, 0x07, 0x05, 'look extras ex_set: art pre-clamp high 7 -> 5 (mov)'),
    (0x601e33b0, 0x04, 0x03, 'look extras ex_set: art wrap modulo 3 (negative: +3)'),
    (0x601e33b2, 0x04, 0x03, 'look extras ex_set: art wrap modulo 3 (>= 3)'),
    (0x601e33b6, 0xfc, 0xfd, 'look extras ex_set: art wrap modulo 3 (-3)'),
]
LBL_PTR, LBL_OLD = 0x601e356e, 0x601e35f0          # `mov ex_tg,a2` imm32 in ex_ui
TAB_AT, TAB_END = 0x601e3840, 0x601e38a0           # claim 0x601e383c..0x601e38a0 (rest of step-0 R stays stock)


def load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
    return m


def covering(spec, addr, n=1):
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16)
            if a <= addr and addr + n <= a + len(e['new']) // 2:
                return e, addr - a
    raise SystemExit(f'{addr:#x}: no edit covers it')


def put(spec, addr, old, new, what):
    e, o = covering(spec, addr, len(old))
    b = bytearray.fromhex(e['new'])
    if b[o:o + len(old)] != old:
        raise SystemExit(f'{addr:#x}: {b[o:o + len(old)].hex()} != expected {old.hex()} ({what})')
    b[o:o + len(new)] = new
    e['new'] = b.hex()
    e['why'] += f' [v0.21: {what}]'


def apply(spec):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    for a, o, n, w in BYTES:
        put(spec, a, bytes([o]), bytes([n]), w)
    # label table: entry 0 = the existing "1 Grain Off" pointer of the old table
    e, o = covering(spec, LBL_OLD, 16)
    old0 = struct.unpack_from('<I', bytes.fromhex(e['new']), o)[0]
    strs = [f'1 Grain {i}'.encode() + b'\0' for i in range(1, 6)]
    blob, ptrs, at = b'', [old0], TAB_AT + 24
    for s_ in strs:
        ptrs.append(at); blob += s_; at += len(s_)
    data = struct.pack('<6I', *ptrs) + blob
    if TAB_AT + len(data) > TAB_END:
        raise SystemExit('label table overflow')
    for x in spec['edits']:
        if not x['addr'].startswith('off:'):
            a, n = int(x['addr'], 16), len(x['new']) // 2
            if a < TAB_END and 0x601e383c < a + n:
                raise SystemExit(f'label table overlaps {x["addr"]}')
    e0, o0 = covering(spec, old0, 12)
    if bytes.fromhex(e0['new'])[o0:o0 + 12] != b'1 Grain Off\0':
        raise SystemExit('old Off label not found')
    put(spec, LBL_PTR, struct.pack('<I', LBL_OLD), struct.pack('<I', TAB_AT), 'grain label table -> 0x601e3840 (6 entries)')
    spec['edits'].append(dict(kind='0x100', addr=hex(TAB_AT), expect=stock[TAB_AT - BASE:TAB_AT - BASE + len(data)].hex(),
                              new=data.hex(), source=SRC,
                              why='v0.21 look extras: grain label table (Off + "1 Grain 1".."1 Grain 5") in the dead EVF step-0 R table'))
    GB = load('gb', 'patches/grain_boost/build.py')
    spec = GB.apply(spec)                                   # strips the v0.20 boost edits, adds the 5-level ones
    spec['v021'] = dict(built_by=SRC, base='releases/v0.20/edits.json', grain_levels=5, grain_gains=list(GB.GAINS),
                        byte_edits=[dict(addr=hex(a), old=o, new=n, what=w) for a, o, n, w in BYTES],
                        label_table=hex(TAB_AT), label_ptr=hex(LBL_PTR))
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['v021'], indent=1))
    print(json.dumps(spec['grain_boost']))
