#!/usr/bin/env python3
"""Anti-brick checks for btn_arrows (b5). Offline.

  .venv/bin/python -I patches/btn_arrows/verify.py BASE.json NEW.json [PKG_DIR]

  P  package reparses; decoded == stock + edits; restore == stock; only btn_arrows + version-label sites differ from BASE
  Y  alignment: row list 4-aligned, record ptr 4 / count 2, title text ptr 4, arrow list 2-aligned and within its room
  R  rows record {42, list, 4} -> 47 48 53 51; arrow records 51/53 -> shared list, bytes 2n; titles kind 5 -> "Right Fn";
     no stock word points into the sec-6 tail
  T  table: every arrow code -> label (shared list) -> action (function table), from the patched image
"""
import importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'external/oly_fw_analysis/tools')]
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402

s = importlib.util.spec_from_file_location('btn_arrows_build', ROOT / 'patches/btn_arrows/build.py')
BA = importlib.util.module_from_spec(s); s.loader.exec_module(BA)
B = BA.BASE
ACT = {0: 'NONE', 12: 'MF_CHANGE', 13: 'RAW_CHANGE', 19: 'ACCESSORIES', 20: 'TOUCH_PANEL_LOCK', 29: 'DIGITAL_ZOOM',
       30: 'PEAKING', 31: 'FINDER_WATER_LEVEL', 43: 'SELECT_MODE_ISO_WB', 44: 'SELECT_MODE_WB_ISO',
       52: 'SELECT_MODE_EXPREV', 53: 'SELECT_MODE_STROBE', 54: 'SELECT_MODE_TAKE_DRIVE', 61: 'SELECT_MODE_POWER_ZOOM'}


def main():
    base_s, new_s = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    disk = Path(sys.argv[3]) if len(sys.argv) > 3 else None
    strings = json.loads((ROOT / 'generated/osd/strings_en.json').read_text())
    pkg0, _, _ = BP.build(base_s, BP.STOCK.read_bytes())
    pkg, rst, info = BP.build(new_s, BP.STOCK.read_bytes())
    pl = lambda p: [b for b in oc.parse(p) if b.kind == 0x100][0].payload
    old, new = pl(pkg0), pl(pkg)
    rd = lambda a, n: new[a - B:a - B + n]
    sb = {b.kind: b for b in oc.parse(BP.STOCK.read_bytes())}
    ok = good = True
    for b in oc.parse(pkg):
        exp = bytearray(sb[b.kind].payload)
        for e in new_s['edits']:
            if int(e['kind'], 16) == b.kind:
                o = BP.resolve(b.kind, e['addr']); nb = bytes.fromhex(e['new']); exp[o:o + len(nb)] = nb
        good &= bytes(exp) == b.payload
    for b in oc.parse(rst):
        good &= b.payload == sb[b.kind].payload
    ours = [(int(e['addr'], 16), len(e['new']) // 2) for e in new_s['edits'] if e.get('source') in (BA.SRC, 'patches/fw_version')]
    diff = [B + i for i in range(len(old)) if old[i] != new[i]]
    stray = [hex(a) for a in diff if not any(x <= a < x + n for x, n in ours)]
    good &= not stray
    if disk:
        good &= (disk / 'patched.pkg.bin').read_bytes() == pkg and (disk / 'restore-stock.pkg.bin').read_bytes() == rst
    ok &= good
    print(f"{'PASS' if good else 'FAIL'} P package: {info['edits']} edits; {len(diff)} B differ from base; stray {stray[:6]}")

    y = (BA.AT % 4 == 0 and (BA.REC + 4) % 4 == 0 and (BA.REC + 8) % 2 == 0 and BA.DPAD_AT % 2 == 0
         and 2 * len(BA.DPAD) <= BA.DPAD_ROOM and all((t + 8) % 4 == 0 and (t + 4) % 2 == 0 for t in BA.TITLES)
         and all((ra + 4) % 4 == 0 and (ra + 12) % 2 == 0 for ra in BA.DPAD_RECS.values()))
    ok &= y
    print(f"{'PASS' if y else 'FAIL'} Y alignment")

    rec = struct.unpack('<IIH', rd(BA.REC, 10))
    rows = list(struct.unpack('<4H', rd(BA.AT, 8)))
    dl = list(struct.unpack('<%dH' % len(BA.DPAD), rd(BA.DPAD_AT, 2 * len(BA.DPAD))))
    recs = [struct.unpack('<HHIIHH', rd(ra, 16)) for ra in BA.DPAD_RECS.values()]
    titles = [struct.unpack('<IHHI', rd(t, 12)) for t in BA.TITLES]
    txt = rd(BA.TEXT_AT, len(BA.TEXT))
    st = [b for b in oc.parse(BP.STOCK.read_bytes()) if b.kind == 0x100][0].payload
    refs = [hex(B + i) for i in range(0, len(st) - 3) if BA.TAIL[0] <= struct.unpack_from('<I', st, i)[0] < BA.TAIL[1]]
    r = (rec == (42, BA.AT, 4) and rows == BA.ROWS and dl == BA.DPAD and not refs and txt == BA.TEXT
         and all(x[0] == sid and x[2] == BA.DPAD_AT and x[4] == 2 * len(BA.DPAD) for x, sid in zip(recs, BA.DPAD_RECS))
         and all(t[:3] == (53, 5, 381) and t[3] == BA.TEXT_AT for t in titles))
    ok &= r
    print(f"{'PASS' if r else 'FAIL'} R rows {rows}, arrow list {len(dl)}, titles {[t[1:] for t in titles]}, tail refs {refs[:3]}")

    fa = {}
    for i in range(54, -1, -1):
        c, a, _ = struct.unpack('<III', rd(BA.FUNC_TAB + 12 * i, 12)); fa[c] = a
    lab = {}
    for i in range(44):
        v, k, sid, _ = struct.unpack('<IHHI', rd(BA.LABELS + 12 * i, 12)); lab.setdefault(v, (k, sid))
    t_ok = True
    print('T code | label (kind, string) | action')
    for c in BA.DPAD:
        k, sid = lab.get(c, (None, None))
        name = strings[sid] if k == 4 and sid is not None and sid < len(strings) else f'icon {sid}' if k == 3 else None
        a = fa.get(c)
        t_ok &= a is not None and k is not None and (a != 0 or c == 3200)
        print(f'  {c:5d} | {name!s:22} | {a} {ACT.get(a, "?")}')
    ok &= t_ok
    print(f"{'PASS' if t_ok else 'FAIL'} T every arrow code has a label and an action")
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
