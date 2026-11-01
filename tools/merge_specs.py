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
        edits.append(dict(e, source=e.get('source', p)))
merged = dict(components=comps, edits=edits, sources=sys.argv[2:], meta={})
for p_, s in zip(sys.argv[2:], specs):   # full per-patch metadata, namespaced (never conflicts)
    merged['meta'][s.get('patch', p_)] = {k: v for k, v in s.items() if k not in ('edits', 'components')}
for s in specs:   # keep verification metadata (e.g. native_rows) if present
    for k in ('native_rows', 'recipe', 'hue_ui', 'light_ui',
              'bundle', 'labels', 'table_hex', 'slots', 'layout',   # v0.2 bundle verifier metadata
              'symbols', 'level', 'code_at',                        # grain verifier metadata
              'bloom',                                              # bloom verifier metadata
              'wb',                                                 # WB verifier metadata
              'mono_colour',                                        # MONO-colour verifier metadata
              'sd_bundles',                                         # SD bundle loader verifier metadata
              'sd_bundles_v2'):                                     # SD look loader v2 verifier metadata
        if k in s:
            if k in merged and merged[k] != s[k]:
                continue   # top-level keeps the first patch's value (verifiers read it); all copies are in meta
            merged[k] = s[k]
out.write_text(json.dumps(merged, indent=1) + '\n')
print(f'{len(edits)} edits, components {comps} -> {out}')
