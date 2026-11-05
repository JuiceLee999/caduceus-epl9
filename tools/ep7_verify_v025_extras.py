#!/usr/bin/env python3
"""v0.25 Extras sector 8 "Shading" - emulator check through the real facade / setter / view words (offline, no camera).

The look-extras verifier with the v0.19 model (tools/ep7_verify_v019_extras.py) and the rules added since: sector 1 reads the
NR byte map (v0.22), Art bytes 3+ read Off (v0.21), plus v0.25:
  get   sector 7 -> 1 when slot +49 == 1, else 0
  set   sector 7 (not ALL) -> +49 = 1 if v >= 1 else 0, dirty = 1; sectors 8..11 write nothing
  guide "8 VigFix Camera" / "8 VigFix Off"; 9..12: "Extras: 1-8 only"
Sectors 1 and 5 writes (v0.21 / v0.22 managers) have their own verifiers, so W runs the other sectors.

  .venv/bin/python -I tools/ep7_verify_v025_extras.py --editor releases/v0.24/edits.json --layered releases/v0.25/edits.json --part G,W,V --jobs 8
"""
import importlib.util, multiprocessing, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
s = importlib.util.spec_from_file_location('v019x', ROOT / 'tools/ep7_verify_v019_extras.py'); V = importlib.util.module_from_spec(s); s.loader.exec_module(V)
REPL = [
    ("           img(im, 0x601e123c, 0x601e133c, 'tone_x')]   # v0.19 (stock EVF bytes in the base image)",
     "           img(im, 0x601e123c, 0x601e133c, 'tone_x'), img(im, 0x601e3840, 0x601e3b3c, 'v2x'), img(im, 0x601e1b00, 0x601e1c40, 'ng2')]"),
    ("        return b[24] if b[24] < 4 else 0\n", "        return [0, 2, 3, 3, 3, 3, 1][b[24]] if b[24] < 7 else 0\n"),
    ("        return b[46] if b[46] <= 3 else 0\n", "        return b[46] if b[46] <= 2 else 0\n"),
    ("        v = s8(b[42 + sec])\n        return v if -5 <= v <= 5 else 0\n    return 0",
     "        v = s8(b[42 + sec])\n        return v if -5 <= v <= 5 else 0\n    if sec == 7:\n        return 1 if b[49] == 1 else 0\n    return 0"),
    ("    if all_on or sec >= 7:\n        return e\n    o = 32 + 64 * slot\n",
     "    o = 32 + 64 * slot\n    if sec == 7 and not all_on:\n        e[o + 49] = 1 if v >= 1 else 0\n        e[DIRTY] = 1\n        return e\n"
     "    if all_on or sec >= 7:\n        return e\n"),
    ("    if sec == 0:\n        return GRAIN[v]\n", "    if sec == 0:\n        return NR[v]\n    if sec == 7:\n        return '8 VigFix Off' if v else '8 VigFix Camera'\n"),
    ("TXT = {'o': 'Extras: 1-7 only',", "NR = ['1 NR Camera', '1 NR Std', '1 NR Low', '1 NR Off']\nTXT = {'o': 'Extras: 1-8 only',"),
    ("pr['a1'] != OUT or pr['d1'] != 0x11111111:", "pr['a1'] != OUT or (pr['d1'] != 0x11111111 and hit[1] != 0):"),   # ng_get (v0.22) uses d1, caller-saved
    ("    tag = f'W {label} id {idv} v {val} all {all_on}'\n",
     "    tag = f'W {label} id {idv} v {val} all {all_on}'\n    if is_x and not all_on and any(i == idv & 0xffff and c in (0, 4) for i, _, c in IDS_ALL):\n        return tag, None\n"),
    ("if 1 <= cursor <= 7 else TXT['o']", "if 1 <= cursor <= 8 else TXT['o']"),
    ("        b[o + 47], b[o + 48] = TONEB.get(id(fields), ((0, 0),) * 4)[k]\n",
     "        b[o + 47], b[o + 48] = TONEB.get(id(fields), ((0, 0),) * 4)[k]\n        b[o + 49] = ({id(FIELDS): (1, 0, 1, 2), id(FIELDS2): (0, 1, 0xff, 1)}).get(id(fields), (0, 0, 0, 0))[k]\n"),
    ("(54, 6), (55, 7), (56, 7), (64, 7), (54, 8), (56, 6)]", "(54, 6), (55, 7), (56, 7), (64, 7), (54, 8), (55, 8), (56, 8), (64, 8), (54, 9), (64, 12), (56, 6)]"),
]
SRC = V.SRC.read_text()
for old, new in V.REPL + REPL:
    if SRC.count(old) != 1:
        raise SystemExit(f'anchor not found once: {old[:70]!r}')
    SRC = SRC.replace(old, new)
mod = type(sys)('ep7_look_extras_verify_v025'); mod.__file__ = str(V.SRC); sys.modules[mod.__name__] = mod
exec(compile(SRC, str(V.SRC), 'exec'), mod.__dict__)
if __name__ == '__main__':
    multiprocessing.set_start_method('fork')
    mod.main()
