#!/usr/bin/env python3
"""E-P7 1.1 video recording-duration limit patch (port of the published PEN-F/E-M5 II pattern).

Routine 0x60319139 (mode in d0, output ptr in a0): modes 3/6/8/9 -> 1740 s, mode 4 -> 7200 s,
others -> logged error. Patch: both `mov imm16,d0` operands -> 32400 s (9 h). Same as PEN-F patch.
Emits edits.json and verifies the patched routine natively in the emulator vs stock.
Separate file-size/chapter/thermal limits are NOT changed.
"""
import json, struct, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import ep7_color_probe as PR  # noqa: E402
from penf_emulator import Region  # noqa: E402

FN, FN_END = 0x60319139, 0x60319193
SITES = [(0x60319157, 1740), (0x6031915c, 7200)]   # imm16 operand addresses (after opcode 2c)
NEW = 32400


def run(main, mode):
    out = 0x19000000
    # routine pushes its own frame (movm [d2]; ret [d2],28) -> enter with `calls d32` (fc ff d32), stop after it
    calls = Region('caller', PR.CALLER, b'\xfc\xff' + struct.pack('<i', FN - PR.CALLER) + b'\xcb', 'rx')
    regions = [calls, Region('stack', PR.STACK, bytes(0x2000), 'rw'),
               Region('code', FN, main[FN - 0x60020020:FN_END - 0x60020020], 'rx'),
               Region('out', out, bytes(16), 'rw', True)]
    r, mem = PR.run(regions, {'pc': PR.CALLER, 'sp': PR.STACK + 0x1800, 'd0': mode, 'a0': out, 'd2': 0x2222}, PR.CALLER + 6)
    return r, struct.unpack_from('<I', mem['out'], 0)[0]


def main():
    d = bytearray((ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin').read_bytes())
    edits = []
    for addr, old in SITES:
        o = addr - 0x60020020
        assert d[o - 1] == 0x2c and struct.unpack_from('<h', d, o)[0] == old, hex(addr)
        edits.append(dict(kind='0x100', addr=hex(addr), expect=struct.pack('<h', old).hex(),
                          new=struct.pack('<h', NEW).hex(), why=f'record limit {old}s -> {NEW}s'))
    stock = bytes(d)
    for addr, _ in SITES:
        struct.pack_into('<h', d, addr - 0x60020020, NEW)
    ok = True
    for mode, exp_s, exp_p in ((3, 1740, NEW), (6, 1740, NEW), (8, 1740, NEW), (9, 1740, NEW), (4, 7200, NEW)):
        rs, vs = run(stock, mode); rp, vp = run(bytes(d), mode)
        good = (vs, vp) == (exp_s, exp_p) and rs['registers']['d0'] == rp['registers']['d0'] == 0 \
            and rp['registers']['pc'] == PR.CALLER + 6 and rp['registers']['sp'] == PR.STACK + 0x1800 \
            and rp['registers']['d2'] == 0x2222 and not rp['fault']
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} mode {mode}: stock {vs}s -> patched {vp}s, ret {rp['registers']['d0']}")
    out = ROOT / 'patches/rec_limit/edits.json'
    out.write_text(json.dumps(dict(components=['0x100'], edits=edits), indent=1) + '\n')
    print('wrote', out)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
