#!/usr/bin/env python3
"""Refresh / verify the machine-readable PEN-F -> E-P7 HSL port map.

patches/hsl/ep7/port_map.json holds the curated mapping (addresses, roles, confidence,
evidence). This tool fills the derived fields so that no byte is ever hand-typed:

  ep7_stock_hex / ep7_stock_sha256   read from OUR decoded E-P7 main at ep7_addr..+ep7_bytes
  penf_before_sha256 / penf_before_hex   copied from fishcu's PEN-F patch.json (read-only)
  ep7_identical_to_penf_before        True when the E-P7 bytes hash to the PEN-F stock hash
                                       (exact-byte match; meaningful for FF padding and
                                       PC-relative-free instruction sequences)

--check     verifies the stored derived fields against the inputs and exits non-zero on drift.
--markdown  prints the site table used in docs/HSL_PORT.md.
Never writes anything except port_map.json; never produces firmware images.
"""
import argparse, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
BASE = 0x60020020
PENF = ROOT / 'external/oly_fw_analysis/patches/hsl/pen-f/patch.json'
MAP = ROOT / 'patches/hsl/ep7/port_map.json'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def derive(site, d, penf_ranges, penf_edits):
    out = {}
    key = (site['name'], int(site['penf_addr'], 16)) if site.get('penf_addr') else None
    if key and key in penf_ranges:
        r = penf_ranges[key]
        out['penf_bytes'] = r['bytes']
        out['penf_before_sha256'] = r['before_sha256']
    if key and key in penf_edits:
        out['penf_before_hex'] = penf_edits[key]['before']
        out['penf_after_hex'] = penf_edits[key]['after']
    if site.get('ep7_addr') and site.get('ep7_bytes'):
        a, n = int(site['ep7_addr'], 16), int(site['ep7_bytes'])
        if not (BASE <= a and a + n <= BASE + len(d)):
            raise ValueError(f"{site['name']}: E-P7 address outside main")
        b = d[a - BASE:a - BASE + n]
        out['ep7_stock_hex'] = b.hex()
        out['ep7_stock_sha256'] = sha(b)
        if 'penf_before_sha256' in out and out.get('penf_bytes') == n:
            out['ep7_identical_to_penf_before'] = sha(b) == out['penf_before_sha256']
        if site.get('ep7_expect_hex') and site['ep7_expect_hex'] != b.hex():
            raise ValueError(f"{site['name']}: expected E-P7 bytes {site['ep7_expect_hex']} but main has {b.hex()}")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--markdown', action='store_true', help='print the mapping table as Markdown')
    a = ap.parse_args()
    if a.markdown:
        m = json.loads(MAP.read_text())
        print('| Group | PEN-F site | PEN-F addr | E-P7 addr | Len | Role | Conf. | E-P7 stock bytes |')
        print('|---|---|---|---|---:|---|---|---|')
        for s in m['sites']:
            hx = s.get('ep7_stock_hex', '')
            hx = hx if len(hx) <= 16 else f"{hx[:12]}… (sha {s.get('ep7_stock_sha256', '')[:8]})"
            role = s.get('role', '').replace('|', '/')
            role = role if len(role) <= 90 else role[:87] + '...'
            print(f"| {s['group']} | {s['name']} | `{s.get('penf_addr')}` | `{s.get('ep7_addr') or '-'}` | "
                  f"{s.get('ep7_bytes') or s.get('penf_bytes') or ''} | {role} | {s['confidence']} | `{hx}` |")
        return
    d = MAIN.read_bytes()
    assert sha(d) == MAIN_SHA, 'unexpected E-P7 main'
    penf = json.loads(PENF.read_text())
    penf_ranges = {(r['name'], int(r['address'], 16)): r for r in penf['main_ranges']}
    penf_edits = {(r['name'], int(r['address'], 16)): r for r in penf['data_edits']}
    m = json.loads(MAP.read_text())
    m['inputs'] = dict(ep7_main_sha256=MAIN_SHA, penf_patch_json_sha256=sha(PENF.read_bytes()))
    drift = []
    for s in m['sites']:
        new = derive(s, d, penf_ranges, penf_edits)
        for k, v in new.items():
            if a.check and s.get(k) != v:
                drift.append((s['name'], k, s.get(k), v))
            s[k] = v
    covered = {(s['name'], int(s['penf_addr'], 16)) for s in m['sites'] if s.get('penf_addr')}
    missing = sorted(set(penf_ranges) - covered)
    m['coverage'] = dict(penf_main_ranges=len(penf_ranges), mapped_entries=len(covered & set(penf_ranges)),
                         missing=[f'{n}@{x:#x}' for n, x in missing])
    counts = {}
    for s in m['sites']:
        counts[s['confidence']] = counts.get(s['confidence'], 0) + 1
    m['confidence_counts'] = counts
    if a.check:
        if drift or missing:
            for x in drift:
                print('DRIFT', x)
            print('MISSING', missing)
            sys.exit(1)
        print('port_map.json consistent;', counts)
        return
    MAP.write_text(json.dumps(m, indent=1) + '\n')
    print('refreshed', MAP.relative_to(ROOT), counts, 'missing:', len(missing))


if __name__ == '__main__':
    main()
