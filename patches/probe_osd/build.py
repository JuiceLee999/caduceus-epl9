#!/usr/bin/env python3
"""Update-path probe: OSD-only package (component 0x101). Changes the English Setup-menu label
"Firmware" (string 134) to "FIRMWARE" (same UTF-16 length). No code changes.
Purpose: prove on camera that an SD update is actually written. Restore = stock OSD component.
Usage: .venv/bin/python -I patches/probe_osd/build.py  -> patches/probe_osd/edits.json
"""
import json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import osd_extract as O  # noqa: E402

osd = O.OSD()
EN, SID = 8, 134
base, blob, p0, p1 = osd._solve_string_base(EN)
e, = struct.unpack_from('<I', blob, p0 - base + 4 * SID)
q = e - base
old, new = 'Firmware'.encode('utf-16le'), 'FIRMWARE'.encode('utf-16le')
assert blob[q:q + len(old)] == old and blob[q + len(old):q + len(old) + 2] == b'\0\0', 'string 134 mismatch'
off = osd.resources[EN]['offset'] + q
comp = (ROOT / 'analysis/ep7_1100/01_0101_421a0020.decoded.bin').read_bytes()
assert comp[off:off + len(old)] == old
spec = dict(components=['0x101'], patch='probe_osd', edits=[dict(kind='0x101', addr=f'off:{off:#x}', expect=old.hex(),
            new=new.hex(), why='English string 134 Firmware -> FIRMWARE (update-path probe)')])
(Path(__file__).parent / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
print('string 134 at component offset', hex(off), '->', Path(__file__).parent / 'edits.json')
