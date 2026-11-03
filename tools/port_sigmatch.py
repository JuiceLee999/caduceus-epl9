#!/usr/bin/env python3
"""Static check: how many Caduceus main-image (0x100) edits can be located in another body's stock main.

Read-only. For each edit in an edits.json it takes the E-P7 stock bytes around the edit, then looks in the
target's decoded main for the same bytes:
  same     the 'expect' bytes sit at the same address in the target
  shifted  expect plus context (32, then 16, then 8 bytes each side of the E-P7 bytes) occurs exactly once
  ambig    the context occurs more than once
  absent   not found
FF free-space claims count as 'same' when the target is also FF there.
PC-relative operands inside the context are not masked, so this UNDERCOUNTS shifted matches. A match only
says the surrounding bytes are alike; it does not prove the edit is correct or safe on that body.

Usage: tools/port_sigmatch.py TARGET_MAIN.decoded.bin [edits.json]
Example: tools/port_sigmatch.py analysis/em5iii/00_0100_40780020.decoded.bin
"""
import json, sys, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = 0x60020020
EP7 = (ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes()


def classify(e, tgt):
    a = int(e['addr'], 16) - BASE
    exp = bytes.fromhex(e['expect'])
    n = len(exp)
    if EP7[a:a + n] != exp:
        return 'bad-base'  # edit does not apply to stock E-P7 1.1 main (sanity)
    if tgt[a:a + n] == exp:
        return 'same'
    if all(b == 0xFF for b in exp):
        return 'absent'
    for c in (32, 16, 8):
        sig = EP7[max(0, a - c):a + n + c]
        i = tgt.find(sig)
        if i < 0:
            continue
        return 'shifted' if tgt.find(sig, i + 1) < 0 else 'ambig'
    return 'absent'


def main():
    tgt = Path(sys.argv[1]).read_bytes()
    edits = json.load(open(sys.argv[2] if len(sys.argv) > 2 else ROOT / 'releases/v0.20/edits.json'))['edits']
    edits = [e for e in edits if e['kind'] == '0x100']
    res = [(classify(e, tgt), e) for e in edits]
    c = collections.Counter(r for r, _ in res)
    tot = len(res)
    print('target', sys.argv[1], 'size', len(tgt))
    for k in ('same', 'shifted', 'ambig', 'absent', 'bad-base'):
        if c[k]:
            print('%-9s %4d  %5.1f%%' % (k, c[k], 100.0 * c[k] / tot))
    print('auto (same+shifted): %d / %d = %.0f%%' % (c['same'] + c['shifted'], tot, 100.0 * (c['same'] + c['shifted']) / tot))
    g = collections.defaultdict(collections.Counter)
    for r, e in res:
        g[e['why'].split()[0].lower().strip(':,')][r] += 1
    print('\nby first word of "why" (same+shifted / total):')
    for k, v in sorted(g.items(), key=lambda kv: -sum(kv[1].values()))[:14]:
        print('  %-14s %3d / %3d' % (k, v['same'] + v['shifted'], sum(v.values())))


if __name__ == '__main__':
    main()
