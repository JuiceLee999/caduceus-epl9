#!/usr/bin/env python3
"""v0.19 Extras sectors 6 Blacks / 7 Whites (patches/v019/tone_x) - emulator check (offline, no camera).

Runs the look-extras verifier (patches/look_extras/verify.py, differential vs the base spec, every run entering
through the real facade / setter / view words of the image, image RAM read-only) with its model extended by the
v0.19 rule:
  get   sector 5 -> slot +47, sector 6 -> +48 (s8; outside -5..5 reads 0); sectors 7..11 read 0
  set   sector 5/6 (not ALL) -> clamp -5..5 into +47/+48, dirty = 1; 7..11 write nothing
  guide sectors 6/7: "6 Blacks -3" / "6 Blacks 0" / "7 Whites +2"; 8..12: "Extras: 1-7 only"; a stock-blanked
        guide (id 0) on the Extras page is labelled like 2755 (the v0.17 label lesson)
Fixture blocks carry +47/+48 values in and out of range in every COLOR slot.

  .venv/bin/python -I tools/ep7_verify_v019_extras.py --editor releases/v0.18/edits.json \
      --layered releases/v0.19/edits.json --part G,W,E,V --jobs 16
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'patches/look_extras/verify.py'

REPL = [
    ("           img(im, LE.VIEW[0], LE.VIEW[1], 'view'), img(im, LE.KEYS[0], LE.KEYS[1], 'keys')]",
     "           img(im, LE.VIEW[0], LE.VIEW[1], 'view'), img(im, LE.KEYS[0], LE.KEYS[1], 'keys'),\n"
     "           img(im, 0x601e123c, 0x601e133c, 'tone_x')]   # v0.19 (stock EVF bytes in the base image)"),
    ("    return 0                                      # v0.14: sector 5 (bloom colour) hidden",
     "    if sec in (5, 6):                             # v0.19: +47 blacks / +48 whites\n"
     "        v = s8(b[42 + sec])\n        return v if -5 <= v <= 5 else 0\n    return 0"),
    ("    if all_on or sec >= 5:\n        return e\n    o = 32 + 64 * slot\n",
     "    if all_on or sec >= 7:\n        return e\n    o = 32 + 64 * slot\n"
     "    if sec in (5, 6):\n        e[o + 42 + sec] = clamp(v, -5, 5) & 0xff\n        e[DIRTY] = 1\n        return e\n"),
    ("    neg, zero, pos = SIGNED[sec]",
     "    if sec in (5, 6):\n        t = ('6 Blacks ', '7 Whites ')[sec - 5]\n"
     "        return t + ('0' if v == 0 else ('+%d' % v) if v > 0 else ('-%d' % -v))\n    neg, zero, pos = SIGNED[sec]"),
    ("TXT = {'o': 'Extras: 1-5 only',", "TXT = {'o': 'Extras: 1-7 only',"),
    ("if 1 <= cursor <= 5 else TXT['o']", "if 1 <= cursor <= 7 else TXT['o']"),
    ("    elif is_x and kind == 4 and gid == 2755 and mode in",
     "    elif is_x and (kind == 4 and gid == 2755 or gid == 0) and mode in"),
    ("ARTS = {", "TONEB = {id(FIELDS): ((0xfb, 5), (3, 0xfa), (0, 0xff), (0x7f, 2)),\n"
               "         id(FIELDS2): ((5, 0xfb), (0x80, 1), (0xfe, 0), (1, 6))}   # v0.19 +47/+48 per slot\nARTS = {"),
    ("        b[o + 46] = ARTS.get(id(fields), (0, 0, 0, 0))[k]\n",
     "        b[o + 46] = ARTS.get(id(fields), (0, 0, 0, 0))[k]\n"
     "        b[o + 47], b[o + 48] = TONEB.get(id(fields), ((0, 0),) * 4)[k]\n"),
    ("932, 943, 944, 956, 1659, 1660, 933]", "932, 943, 944, 956, 1659, 1660, 933, 934, 945, 957, 1661]"),
    ("(64, 12), (54, 0), (11, 1), (0, 2), (55, 5), (56, 5), (64, 6)]",
     "(64, 12), (54, 0), (11, 1), (0, 2), (55, 5), (56, 5), (64, 6), (54, 6), (55, 7), (56, 7), (64, 7), (54, 8), (56, 6)]"),
]


def load():
    s = SRC.read_text()
    for old, new in REPL:
        if s.count(old) != 1:
            raise SystemExit(f'verify.py anchor not found once: {old[:60]!r}')
        s = s.replace(old, new)
    mod = type(sys)('ep7_look_extras_verify_v019')
    mod.__file__ = str(SRC)
    sys.modules[mod.__name__] = mod
    exec(compile(s, str(SRC), 'exec'), mod.__dict__)
    return mod


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.set_start_method('fork')      # the patched module exists only in this process
    load().main()
