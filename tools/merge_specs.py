#!/usr/bin/env python3
"""Merge several edits specs into one (for tools/build_package.py). Overlaps are rejected later by the
packager's stock-byte/overlap checks; this tool also rejects duplicate addresses up front.
Usage: tools/merge_specs.py OUT.json SPEC1.json SPEC2.json ...
"""
import json, sys
from pathlib import Path
out, specs = Path(sys.argv[1]), [json.loads(Path(p).read_text()) for p in sys.argv[2:]]
comps, edits, seen = ['0x100'], [], set()
for p, s in zip(sys.argv[2:], specs):
    for c in s['components']:
        if c not in comps:
            comps.append(c)
    for e in s['edits']:
        key = (e['kind'], e['addr'])
        if key in seen:
            sys.exit(f'duplicate edit {key} from {p}')
        seen.add(key)
        edits.append(dict(e, source=p))
merged = dict(components=comps, edits=edits, sources=sys.argv[2:])
for s in specs:   # keep verification metadata (e.g. native_rows) if present
    for k in ('native_rows', 'recipe', 'hue_ui', 'light_ui'):
        if k in s:
            merged[k] = s[k]
out.write_text(json.dumps(merged, indent=1) + '\n')
print(f'{len(edits)} edits, components {comps} -> {out}')
