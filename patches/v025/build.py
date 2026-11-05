#!/usr/bin/env python3
"""v0.25 = releases/v0.24 + per-profile lens shading off + NR that reaches stills. Offline.

  .venv/bin/python -I patches/v025/build.py releases/v0.24/edits.json --out releases/v0.25/edits.json
  .venv/bin/python -I patches/fw_version/build.py releases/v0.25/edits.json --mod-version 0.25

Slot byte +49: 0 follow the camera, 1 off. A Film pick on a library look sets 1 unless the record's slot mask has bit 2 (the look keeps the
camera's correction; fm_check accepts it from this build). Stock is 0, own restores its snapshot, and Extras sector 8 can change it.
+49 does not count as "modified". BUNDLES.BIN +49 accepts 0..1, so a file saved with Shading Off is rejected by v0.24 and older.

NR: v0.22 writes setting 1334, whose reader is the LV / movie builder; stills read key 0x9719 (sid 143). nr_get overrides those
reads per shot from slot +24 and the 1334 writes go, so a look no longer changes a camera setting.
"""
import argparse, copy, importlib.util, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V19 = _load('ep7_v019_build', ROOT / 'patches/v019/build.py')
SB3, FB, LB = V19.SB3, V19.FB, V19.LB
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE, SRC = 0x60020020, 'patches/v025'
FM_CORE_AT = 0x6143a410
AT, END, REFS = 0x601e393c, 0x601e3b3c, [0x601e3c84, 0x601e3c88]   # dead EVF step-0 G, B tables; only references are the step-table words
GETTER, KEY = 0x6005e971, 0x8c21
SITES = (0x60303093, 0x602ab488, 0x60299b75, 0x6029fe64, 0x605554bc)
NR_KEY, NR_SITES = 0x9719, (0x602a8095, 0x6028d08a)     # capture, MakerNote; 0x60c67053 (playback RAW) stays stock
NO_WRITE = 0x601e38ae                                   # ng_set: beq -> bra past the 1334 settings call
PICK_SITE, NG_PICK, FM_POST = 0x601e2341, 0x601e1b90, 0x601e37b4     # lt_post's jump -> sl_pick (replaces ng_pick)
TONE_X = dict(g_zero=(0x601e1263, 'sg'), s_refresh=(0x601e128b, 'ss'), q_put0=(0x601e12ea, 'su'))
SYMS = dict(ep7_getter=GETTER, ep7_tbl_idx=0x6055e7b0, ep7_g_val=0x601e3322, ep7_g_zero=0x601e3321, ep7_s_dirty=0x601e3428,
            ep7_s_refresh=0x601e343e, ep7_fm_post=FM_POST, ep7_ex_get=0x601e32a3, ep7_q_put0=0x601e35b4, ep7_q_out=0x601e35ea)
T_OTHER, T_OLD, T_NEW = 0x601e3713, b'Extras: 1-7 only\0', b'Extras: 1-8 only\0'
LOADER_SPAN_49 = 0x605b7721 + 49                        # SD loader v3 range span table (0x605b7739 is +24, v0.22)
LOADER_LO_49 = LOADER_SPAN_49 - 64
PICK_BOUND, MOD_BOUND = 0x601e2e46, 0x601e247f          # `cmp 64,d1` (u_apply), `cmp 64,d2` (lt_mod)


def covering(spec, addr, n=1):
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16)
            if a <= addr and addr + n <= a + len(e['new']) // 2:
                return e, addr - a
    raise SystemExit(f'{addr:#x}: no covering edit')


def put(spec, addr, old, new, what):
    e, o = covering(spec, addr, len(old))
    b = bytearray.fromhex(e['new'])
    if bytes(b[o:o + len(old)]) != old:
        raise SystemExit(f'{addr:#x}: {b[o:o + len(old)].hex()} != {old.hex()} ({what})')
    b[o:o + len(new)] = new
    e['new'] = b.hex(); e['why'] += f' [v0.25: {what}]'


def img_of(spec, stock):
    im = bytearray(stock)
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16) - BASE; n = bytes.fromhex(e['new']); im[a:a + len(n)] = n
    return bytes(im)


def jmp(at, dst):
    return b'\xdc' + struct.pack('<i', dst - at)


def apply(spec):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    src = FB.source(str(ROOT / 'patches/v025/shade.s.in'))
    code, _, syms, _ = SB3.assemble(src, AT, SYMS)
    if syms['sc_get'] != AT or AT + len(code) > END:
        raise SystemExit(f'code {len(code)} B does not fit')
    bad = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}
    ins = SB3.disasm(code, AT, syms['su_cam'])
    if any(op in bad for _, op, _ in ins) or any(k == 'abs' for _, _, k, _ in SB3.store_audit(ins)):
        raise SystemExit('forbidden instruction or absolute store')
    if [struct.unpack_from('<I', stock, r - BASE)[0] for r in REFS] != [AT, AT + 256]:
        raise SystemExit('step-0 G/B words are not the placement')
    hits = [i + BASE for i in range(len(stock) - 3) if AT <= struct.unpack_from('<I', stock, i)[0] < END]
    if hits != REFS:
        raise SystemExit(f'references into the placement: {[hex(h) for h in hits]}')
    for x in spec['edits']:
        if not x['addr'].startswith('off:'):
            a, n = int(x['addr'], 16), len(x['new']) // 2
            if a < END and AT < a + n:
                raise SystemExit(f'overlap {x["addr"]}')
    # the four reads: each is `mov key,d0 ... call getter,[d2,d3],12`, only the rel32 changes
    edits = []
    for sites, key, entry in ((SITES, KEY, 'sc_get'), (NR_SITES, NR_KEY, 'nr_get')):
        for s in sites:
            old = stock[s - BASE:s - BASE + 7]
            if old[0] != 0xdd or s + struct.unpack('<i', old[1:5])[0] != GETTER or old[5:] != b'\xc0\x0c':
                raise SystemExit(f'{s:#x}: not the getter call: {old.hex()}')
            if struct.pack('<H', key) not in stock[s - BASE - 16:s - BASE]:
                raise SystemExit(f'{s:#x}: key {key:#x} not loaded just before')
            new = bytes([0xdd]) + struct.pack('<i', syms[entry] - s) + old[5:]
            edits.append(dict(kind='0x100', addr=hex(s), expect=old.hex(), new=new.hex(), source=SRC,
                              why=f'v0.25 key {key:#x} read {s:#x}: getter -> {entry}'))
    put(spec, NO_WRITE, b'\xc8', b'\xca', 'NR: no Noise Filter 1334 write (bra)')
    put(spec, PICK_SITE, jmp(PICK_SITE, NG_PICK), jmp(PICK_SITE, syms['sl_pick']), 'lt_post -> sl_pick (Shading byte, no 1334 write)')
    # fm_check: colour mask 1 or 3, either with bit 2. Same span: and 0xf9,d1; cmp 1,d1; beq 7f; bra c_bad; nop
    i = next(k for k in range(FM_CORE_AT, FM_CORE_AT + 845) if img_of(spec, stock)[k - BASE:k - BASE + 4] == bytes.fromhex('a501c8') + bytes([img_of(spec, stock)[k - BASE + 3]]) and img_of(spec, stock)[k - BASE + 4:k - BASE + 6] == bytes.fromhex('a503'))
    old = img_of(spec, stock)[i - BASE:i - BASE + 10]
    if old[6] != 0xc8 or old[8] != 0xca:
        raise SystemExit(f'fm_check mask bytes {old.hex()}')
    t7, tbad = i + 2 + struct.unpack('b', old[3:4])[0], i + 8 + struct.unpack('b', old[9:10])[0]
    if i + 6 + struct.unpack('b', old[7:8])[0] != t7:
        raise SystemExit('fm_check mask branches differ')
    new = bytes.fromhex('f8e1f9a501') + b'\xc8' + struct.pack('b', t7 - (i + 5)) + b'\xca' + struct.pack('b', tbad - (i + 7)) + b'\xcb'
    put(spec, i, old, new, 'fm_check: colour mask may carry bit 2 (keep lens correction)')
    # Extras sector 8: three tone_x jumps, the "1-8 only" text
    for name, (at, entry) in TONE_X.items():
        dst = SYMS['ep7_' + name]
        put(spec, at, jmp(at, dst), jmp(at, syms[entry]), f'tone_x {name} -> {entry} (Extras sector 8)')
    put(spec, T_OTHER, T_OLD, T_NEW, 'Extras: 1-8 only')
    # +49 is not a change of look
    put(spec, PICK_BOUND, b'\x40', bytes([50]), 'u_apply writes slot bytes 0..49 (+50..63 stay 0)')
    put(spec, MOD_BOUND, b'\x40', bytes([49]), 'lt_mod compares slot bytes 0..48 only')
    # BUNDLES.BIN: +49 accepts 0..1
    e, o = covering(spec, LOADER_LO_49); lo = bytes.fromhex(e['new'])[o]
    if lo != 0:
        raise SystemExit(f'loader lo[49] = {lo}')
    put(spec, LOADER_SPAN_49, b'\x00', b'\x01', 'SD loader v3 range: slot +49 0..1')
    spec['edits'] += edits
    spec['edits'].append(dict(kind='0x100', addr=hex(AT), expect=stock[AT - BASE:AT - BASE + len(code)].hex(), new=code.hex(),
                              source=SRC, why=f'v0.25 shading off: sc_get + Extras sector 8 ({len(code)} B, dead EVF step-0 G)'))
    spec['v025'] = dict(built_by=SRC, base='releases/v0.24/edits.json', code_at=hex(AT), code_len=len(code), slot_byte=49, sector=8,
                        symbols={k: hex(v) for k, v in syms.items() if k[:2] in ('sc', 'sg', 'ss', 'su', 'nr', 'sl')}, sites=[hex(s) for s in SITES], nr_sites=[hex(s) for s in NR_SITES])
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['v025']))
