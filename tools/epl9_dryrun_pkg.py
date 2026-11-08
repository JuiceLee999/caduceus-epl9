#!/usr/bin/env python3
"""Make the E-PL9 trigger-discovery dry-run file from a restore package (offline, no camera).

  py -I tools/epl9_dryrun_pkg.py generated/epl9_look/pkg/restore-stock.pkg.bin

Writes <same dir>/dryrun-badsum.pkg.bin: the restore package with one bit flipped in the last byte of the trailer
checksum word. The camera's validator refuses such a file with 0x3211 before any erase or write
(tools/epl9_sd_update_probe.py, case "main-only, bad checksum (dry run) -> no write"). The output name is deliberately
not SD-loadable; renaming it to DCOLYMP/E1339999.BIN is a manual step (docs/EPL9_RECOVERY.md).
"""
import hashlib, struct, sys
from pathlib import Path

STOCK_MAIN_DECODED = '8e39c335d54fd8ddea189db82fe708159f43f9995bba42c2cd47dd22b8814267'


def main():
    src = Path(sys.argv[1])
    pkg = bytearray(src.read_bytes())
    ln = struct.unpack_from('<I', pkg, 12)[0]
    if pkg[0:4] != b'OE\x13\x30' or ln + 64 != len(pkg) or struct.unpack_from('<H', pkg, 20)[0] != 0x100:
        sys.exit('expected a single E-PL9 main component (OE 1330, kind 0x100)')
    out = bytearray(pkg)
    out[-1] ^= 0x01                                   # trailer word 7 = checksum; header is untouched
    diff = [i for i in range(len(pkg)) if pkg[i] != out[i]]
    assert diff == [len(pkg) - 1] and out[:32] == pkg[:32] and out[-32:-4] == pkg[-32:-4]
    dst = src.parent / 'dryrun-badsum.pkg.bin'
    dst.write_bytes(bytes(out))
    print(f'{dst}: {len(out)} B, 1 byte changed at offset {len(out) - 1:#x} (checksum), sha256 {hashlib.sha256(out).hexdigest()}')


if __name__ == '__main__':
    main()
