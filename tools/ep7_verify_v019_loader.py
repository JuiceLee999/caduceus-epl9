#!/usr/bin/env python3
"""v0.19 SD loader check (emulator only): runs tools/ep7_verify_sd_bundles_v3.py against a v0.19 spec with its
fixture switched to the v0.19 range rule (patches/sd_bundles range_table(tone=True): slot +47 blacks / +48 whites
-5..5) and its file model switched to the camera rule (no MONO-zero rule: the v0.19 loader accepts tone bytes in
MONO slots, which nothing reads). So the E part's per-byte boundary cases include +47/+48 = -6/-5/5/6 and
+49..63 = 1, and every other case is the released suite.

  .venv/bin/python -I tools/ep7_verify_v019_loader.py releases/v0.19/edits.json --part S,E,A,R [--json out]
"""
import functools, importlib.util, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
s = importlib.util.spec_from_file_location('ep7_verify_sd_bundles_v3', ROOT / 'tools/ep7_verify_sd_bundles_v3.py')
V3 = importlib.util.module_from_spec(s)
sys.modules['ep7_verify_sd_bundles_v3'] = V3
s.loader.exec_module(V3)
SB, BIN = V3.V1.SB, V3.V1.BIN
_rt = SB.range_table
SB.range_table = functools.wraps(_rt)(lambda lay, ranges=None, tone=True: _rt(lay, ranges, tone))
BIN.check_file = functools.partial(BIN.check_file, tone=True, mono_rule=False)
lo, span, _ = SB.range_table(SB.layout())
assert (lo[47], span[47], lo[48], span[48]) == (-5, 10, -5, 10) and all(span[k] == 0 for k in range(49, 64))
# The v3 suite predates the look editor, whose sd_back retarget (0x605b7420 jmp ed_trig 0x605b7340, v0.12+) runs the
# editor after a load; this fixture does not map the editor. For this loader-only check the test image gets the
# legacy v3 sd_back back (jmp 0x602c8064, patches/look_editor SD_BACK_STOCK); the range table and every other loader
# byte are the release's. (Applied identically to a v0.18 run, which is the baseline.)
SD_BACK, LEGACY, EDITOR = 0x605b7420 - 0x60020020, bytes.fromhex('dc440cd1ff'), bytes.fromhex('dc20ffffff')


def _legacy(img):
    b = bytearray(img)
    assert bytes(b[SD_BACK:SD_BACK + 5]) == EDITOR, 'sd_back is not jmp ed_trig'
    b[SD_BACK:SD_BACK + 5] = LEGACY
    return bytes(b)


for name in ('single', 'sequence'):
    f = getattr(V3.Runner, name)
    setattr(V3.Runner, name, functools.wraps(f)(lambda self, img, *a, _f=f, **k: _f(self, _legacy(img), *a, **k)))
V3.main()
