#!/usr/bin/env python3
"""Checks for aspect_scp t1 (docs/ASPECT.md 1j). Offline. Runs on the given base/new pair, and again on releases/v0.28 with
apply() done in memory, so the layer is shown to apply on both bases.

  .venv/bin/python -I patches/aspect_scp/verify.py generated/combo/b1/edits.json generated/aspect_scp/t1/edits.json [generated/aspect_scp/t1/pkg]

  C  cell lookup, native: both builder sites (0x60e00bd7.. / 0x60e071dc.., real list pointer, count and 0x60df24d7) for
     values 0..12: 1-4/9/10 == base, 6 -> 7, 7 -> 8, others untouched (cell keeps the 0 it was cleared to); no fault
  W  widget: record count/parts/u16 array; index i draws part i-2 when 0 <= i-2 < count (setPart 0x60d48b5e ignores the rest):
     1-4/9 same bitmap as base, 6 -> 5866 (XP), 7 -> 5889 (21:9); u16 array zero
  S  strip and v0.25 lists unchanged: record 0x61176fc0, lists A/B, row 16, info lists/records, OSD 3732/3725/5528/5535
  O  OSD: patched component reparses, every bitmap decodes strictly, all but 5866/5889 identical to base, directory and
     bitmap table identical, the two decode to the build's pixels (mode 11, 106x31, key 7, stream <= original payload)
  Y  alignment of the new data (part block 16, u16 array 4, list 4, record words 4)
  P  anti-brick: package reparses, decoded == stock + edits, restore == stock (sha == v0.28 restore), only our sites and
     fw_version differ from the base (main and OSD); on-disk package == rebuilt
"""
import importlib.util, json, struct, sys, tempfile
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'external/oly_fw_analysis/tools')]
from penf_emulator import Region, execute  # noqa: E402
import build_package as BP, oly_container as oc  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


B = _load('aspect_scp_build', ROOT / 'patches/aspect_scp/build.py')
X, OI = B.X, B.OI
BASE = 0x60020020
STK, OUT = 0x18010000, 0x1a000000
RUNS = {  # start, stop (after the call)
    0x60e00bdf: (0x60e00bd7, 0x60e00bec),
    0x60e071e4: (0x60e071dc, 0x60e071f1),
}
SENT = 0x5a5a5a5a


def build(spec):
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    comp = {b.kind: b.payload for b in oc.parse(pkg)}
    return comp, pkg, rst, info


def R(q, lo, hi, perm='rx'):
    return Region(f'r{lo:x}', lo, q[lo - BASE:hi - BASE], perm)


def cell(q, site, v):
    start, stop = RUNS[site]
    stk = bytearray(struct.pack('<I', SENT) * 0x800)
    struct.pack_into('<I', stk, 0x1000 + 8, v)
    rg = [R(q, 0x60df2000, 0x60df3000), R(q, 0x60e00000, 0x60e08000), R(q, 0x610a0000, 0x610a1000, 'r'),
          R(q, 0x6116e000, 0x61172000, 'r'), Region('stk', STK, bytes(stk), 'rw', True), Region('out', OUT, bytes(8), 'rw', True)]
    r = execute(rg, {'pc': start, 'sp': STK + 0x1000, 'a3': OUT, 'd2': 0x1234}, 0xfffffff0, limit=2000, breakpoints=[stop])
    if r['status'] != 'breakpoint' or r['fault']:
        return ('fault', r['status'], r['fault'])
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    return struct.unpack_from('<H', m['out'], 0)[0]


def t_cell(old, new):
    bad, n = [], 0
    for site in RUNS:
        for v in range(13):
            a, b = cell(old, site, v), cell(new, site, v)
            n += 1
            exp = {6: 7, 7: 8}.get(v, a)
            if b != exp or isinstance(a, tuple) or (v in (6, 7) and a != 0) or (v in (1, 2, 3, 4, 9, 10) and a == 0):
                bad.append((hex(site), v, a, b))
    return bad, n


def widget(q):
    r = B.REC - BASE
    kind, cnt = q[r + 0x34], q[r + 0x35]
    parts, u16 = struct.unpack_from('<2I', q, r + 0x38)
    ids = [struct.unpack_from('<4I', q, parts - BASE + 16 * k) for k in range(cnt)]
    arr = q[u16 - BASE:u16 - BASE + 2 * cnt]
    return kind, cnt, ids, arr


def t_widget(old, new):
    bad, n = [], 0
    ko, co, io, ao = widget(old)
    kn, cn, inn, an = widget(new)
    n += 1
    if (ko, co, kn, cn) != (2, 5, 2, 7) or ao != bytes(10) or an != bytes(14) or any(p[:3] != (0xffff, 7, 7) for p in inn):
        bad.append(('record', ko, co, kn, cn))
    draw = lambda ids, i: ids[i - 2][3] if 0 <= i - 2 < len(ids) else None
    for v, i_old, i_new in [(1, 2, 2), (2, 3, 3), (3, 6, 6), (4, 5, 5), (9, 4, 4), (6, 0, 7), (7, 0, 8), (10, 7, 7), (5, 0, 0)]:
        n += 1
        a, b = draw(io, i_old), draw(inn, i_new)
        exp = {6: B.XP_ID, 7: B.W219_ID, 10: B.XP_ID, 5: None}.get(v, a)
        if b != exp or (v in (1, 2, 3, 4, 9) and a is None):
            bad.append((v, a, b))
    return bad, n


STRIP = [(0x61176fc0, 12), (0x61175d78, 84), (0x61242f60, 84), (0x6116b190, 16), (0x601e15f0, 112), (0x6123dd04, 16),
         (0x6123ddb4, 16), (0x6123f17c, 16), (0x6123f438, 16), (0x6117af14, 8), (0x61242f00, 96)]


def osd(data):
    with tempfile.NamedTemporaryFile(suffix='.bin') as f:
        f.write(data); f.flush()
        o = X.OSD(component=Path(f.name), check_hash=False)
        rows = {}
        for i in range(o.bitmap_count):
            d = o.descriptor(i)
            px = None
            if d['kind'] == 'rle':
                try:
                    px = o.decode_bitmap(d)[0]
                except Exception as e:      # noqa: BLE001
                    px = ('bad', str(e))
            rows[i] = (d, px)
        t = o.bitmap_table - o.base0 + o.resources[0]['offset']
        return rows, data[:0x800], data[t:t + 4 * o.bitmap_count]


def t_strip(old, new, ob, on):
    bad = [hex(a) for a, k in STRIP if old[a - BASE:a - BASE + k] != new[a - BASE:a - BASE + k]]
    bad += [i for i in (3732, 3725, 5528, 5535) if ob[0][i] != on[0][i]]
    return bad, len(STRIP) + 4


def t_osd(ob, on, imgs):
    bad = []
    rb, db, tb = ob
    rn, dn, tn = on
    n = len(rn) + 3
    for i, (d, px) in rn.items():
        if isinstance(px, tuple):
            bad.append(('decode', i, px))
        elif i not in imgs and (d, px) != rb[i]:
            bad.append(('changed', i))
    if db != dn or tb != tn:
        bad.append('directory/table')
    for i, a in imgs.items():
        d, px = rn[i]
        if (px != a.tobytes() or (d['width'], d['height']) != (106, 31) or d['extra'] != 7 or d['fmt'] != 14 or d['field6'] != 8
                or d['encoded_bytes'] > rb[i][0]['encoded_bytes'] or d['payload'] != rb[i][0]['payload'] or d['descriptor'] != rb[i][0]['descriptor']):
            bad.append(('new', i))
    return bad, n


def t_align(new):
    _, cnt, _, _ = widget(new)
    parts, u16 = struct.unpack_from('<2I', new, B.REC - BASE + 0x38)
    lst = [struct.unpack_from('<I', new, s - BASE)[0] for s in RUNS]
    bad = [x for x in (parts % 16, u16 % 4, (B.REC + 0x34) % 4) if x] + [hex(x) for x in lst if x % 4 or x != B.LIST_AT]
    if u16 + 2 * cnt > B.PARTS_END:
        bad.append('u16 array overflows the claim')
    return bad, 5


def ours(spec):
    out = {0x100: [], 0x101: []}
    for e in spec['edits']:
        if e.get('source') in (B.SRC, 'patches/fw_version'):
            k = int(e['kind'], 16)
            a = int(e['addr'][4:], 16) if e['addr'].startswith('off:') else int(e['addr'], 16) - BASE
            out[k].append((a, len(e['new']) // 2))
    return out


def t_pkg(base_s, new_s, cb, cn, pkg, rst, info, disk):
    sb = {b.kind: b for b in oc.parse(BP.STOCK.read_bytes())}
    good = [b.kind for b in oc.parse(pkg)] == [0x100, 0x101]
    for b in oc.parse(pkg):
        exp = bytearray(sb[b.kind].payload)
        for e in new_s['edits']:
            if int(e['kind'], 16) == b.kind:
                o = BP.resolve(b.kind, e['addr']); nb = bytes.fromhex(e['new']); exp[o:o + len(nb)] = nb
        good &= bytes(exp) == b.payload
    for b in oc.parse(rst):
        good &= b.payload == sb[b.kind].payload
    rel = json.loads((ROOT / 'releases/v0.28/build.json').read_text())
    good &= BP.sha(rst) == rel['restore_sha256']
    mine, stray, nd = ours(new_s), [], 0
    # fw_version sites of the base are replaced by the new ones: count them as ours too
    for k, v in ours(base_s).items():
        mine[k] += [x for x in v if x not in mine[k]]
    for k in (0x100, 0x101):
        a, b = np.frombuffer(cb[k], np.uint8), np.frombuffer(cn[k], np.uint8)
        diff = np.nonzero(a != b)[0]
        nd += len(diff)
        stray += [(hex(k), hex(int(d))) for d in diff if not any(s <= d < s + m for s, m in mine[k])]
    good &= not stray
    if disk:
        good &= (disk / 'patched.pkg.bin').read_bytes() == pkg and (disk / 'restore-stock.pkg.bin').read_bytes() == rst
    return good, f'{info["edits"]} edits, {info["changed_payload_bytes"]} B; {nd} B differ from base; stray {stray[:6]}; sha {BP.sha(pkg)[:16]}'


def run(label, base_s, new_s, disk, o, imgs):
    print(f'== {label}', flush=True)
    cb, *_ = build(base_s)
    cn, pkg, rst, info = build(new_s)
    old, new = cb[0x100], cn[0x100]
    ob, on = osd(cb[0x101]), osd(cn[0x101])
    ok = True
    for name, fn in (('C cell lookup (native)', lambda: t_cell(old, new)), ('W widget parts', lambda: t_widget(old, new)),
                     ('S strip/info lists unchanged', lambda: t_strip(old, new, ob, on)), ('O OSD strict', lambda: t_osd(ob, on, imgs)),
                     ('Y alignment', lambda: t_align(new))):
        bad, n = fn(); ok &= not bad
        print(f"{'PASS' if not bad else 'FAIL'} {name}: {n - len(bad)}/{n}", bad[:3] if bad else '', flush=True)
    good, txt = t_pkg(base_s, new_s, cb, cn, pkg, rst, info, disk); ok &= good
    print(f"{'PASS' if good else 'FAIL'} P anti-brick: {txt}")
    return ok


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    o = X.OSD()
    imgs = B.images(o)
    ok = run(sys.argv[1], base_s, new_s, disk, o, imgs)
    v28 = json.loads((ROOT / 'releases/v0.28/edits.json').read_text())
    ok &= run('releases/v0.28/edits.json (apply in memory)', v28, B.apply(v28, '0.28c1', o), None, o, imgs)
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
