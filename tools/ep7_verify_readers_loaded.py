#!/usr/bin/env python3
"""Run an existing bundle-table reader verifier as if SD loader v3 had loaded the table (offline; emulator only).

  tools/ep7_verify_readers_loaded.py tools/ep7_verify_bundles.py SPEC.json [verifier args...]

Switches tools/ep7_sdv3_env.py to loaded mode (table moved into a pool buffer with the handle at 0x622cbcc2,
flashed copy replaced by a poison table), then runs the verifier's own main() unchanged. Passing means every
--sd-v3 reader read the loaded copy through the accessor and produced exactly what the verifier expects from
the real table. Prints how many emulator runs had their table relocated.
"""
import importlib.util, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import ep7_sdv3_env as SDV3  # noqa: E402

path = Path(sys.argv[1]).resolve()
SDV3.set_loaded(True)
s = importlib.util.spec_from_file_location(path.stem, path)
m = importlib.util.module_from_spec(s)
sys.modules[path.stem] = m
s.loader.exec_module(m)
sys.argv = [str(path)] + sys.argv[2:]
code = 0
try:
    m.main()
except SystemExit as e:
    code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
st = SDV3.stats()
print(f"LOADED-MODE  {path.name}: {st['relocated']} of {st['runs']} emulator runs had the table relocated "
      f"(handle {SDV3.handle(SDV3.LOADED_BUF):#x}); verifier exit {code}")
sys.exit(code if st['relocated'] else 2)
