#!/usr/bin/env python3
"""Offline emulator probe of the E-P7 1.1 firmware-update validator/writer (section 6).

Runs the NATIVE routine 0x60c964c1 (shared by the SD client path, kind 1 = E142????BIN,
and by the USB check/commit path) on small synthetic `OE` containers held only in
emulator RAM. Nothing is written to disk except an optional JSON report; no file with
an SD-update name is ever created.

Mode argument (d1) as used by FIRMUP_SRV 0x60c96030:
  0 = SD request (validate every component, then write)   -- kinds 1, 0x14, ...
  2 = USB FirmwareCheck (validate only)                     -- kind 3
  1 = USB commit (skip checksum, write)                     -- kind 4

Stubs (emulator RAM only):
  0x6002247c / 0x6002266d  debug log -> plain `ret` with the callee's frame.
  0x600c4f35               flash write -> logs (dst a0, src a1, size d0, mode d1), returns 0.

Checks: valid main-only package accepted; version/build field ignored (same, older, newer);
checksum, model and header/trailer failures rejected with the native error code; duplicate
'E' kinds are NOT rejected (last copy wins); in mode 0 a corrupt second component causes zero flash writes; a valid
two-component package is written as two whole-component writes (header..trailer) at the
header address, OSD before USR.

Usage: tools/ep7_sd_update_probe.py [--json out.json]
"""
import argparse, hashlib, json, os, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
from penf_emulator import execute, Region  # noqa: E402  (generic runner only)

MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
STOCK = ROOT / 'stock_firmware/OLY_E_142_1100_0000_0000.BIN'
BASE = 0x60020020
TC = Path(os.environ.get('MN10300_BIN', Path.home() / 'ep7fw-toolchains/mn10300/bin'))

VALIDATE = 0x60c964c1
CODE_LO, CODE_HI = 0x60c95a00, 0x60c97300        # validator, checksum, descramble, writer wrapper
HDR_LO, HDR_HI = 0x600fa450, 0x600fa560          # header field helpers + splitter
STRCMP_LO, STRCMP_HI = 0x600daf1c, 0x600daf40
ADDR_LO, ADDR_HI = 0x60067102, 0x60067150        # 0x4xxxxxxx -> flash alias mapping
DATA_LO, DATA_HI = 0x60f2d000, 0x60f2d900
OSTR = 0x601a47b0
FLASH_WRITE = 0x600c4f35

CALLER, STACK, BUF, LOG = 0x18000000, 0x18100000, 0x20000000, 0x1c000000
PERM = [1, 3, 0, 2, 6, 4, 7, 5, 11, 10, 9, 8, 13, 14, 12, 15]   # decoded[i] = ~enc[PERM[i]]

WRITE_STUB = r"""
 .am33_2
 .text
 .global _start
_start:
 mov {log},a3
 mov (a3),d2
 mov d2,d3
 asl 4,d3
 mov a3,a2
 add d3,a2
 mov a0,(4,a2)
 mov a1,(8,a2)
 mov d0,(12,a2)
 mov d1,(16,a2)
 inc d2
 mov d2,(a3)
 clr d0
 ret [d2,d3,a2,a3],36
"""


def main_image():
    d = MAIN.read_bytes()
    assert hashlib.sha256(d).hexdigest() == MAIN_SHA, 'unexpected E-P7 main'
    return d


def encode(dec):
    out = bytearray(len(dec))
    for g in range(0, len(dec), 16):
        for i, p in enumerate(PERM):
            out[g + p] = dec[g + i] ^ 0xff
    return bytes(out)


def decode(enc):
    out = bytearray(len(enc))
    for g in range(0, len(enc), 16):
        for i, p in enumerate(PERM):
            out[g + i] = enc[g + p] ^ 0xff
    return bytes(out)


def component(kind=0x100, version=0x1100, model=b'\x14\x20', sig=b'OE', payload=None,
              address=0x406a0000, break_sum=False, break_trailer=False):
    payload = payload if payload is not None else bytes((i * 7 + 3) & 0xff for i in range(0x400))
    assert len(payload) % 16 == 0
    hdr = bytearray(32)
    hdr[0:2], hdr[2:4] = sig, model
    struct.pack_into('<IIHHH', hdr, 8, address, len(payload), version, 0, kind)
    trl = bytearray(hdr)
    words = struct.unpack(f'<{(32 + len(payload) + 28) // 4}I', bytes(hdr) + payload + bytes(trl[:28]))
    struct.pack_into('<I', trl, 28, (-sum(words)) & 0xffffffff)
    if break_sum:
        trl[28] ^= 1
    if break_trailer:
        trl[16] ^= 1                                      # build field differs header vs trailer
    return bytes(hdr) + encode(payload) + bytes(trl)


def flash_alias(a):
    """Python model of 0x60067102 (checked against the emulator output)."""
    if 0x40000000 <= a < 0x41000000 or 0x60000000 <= a < 0x80000000:
        return (a & 0x3fffffff) | 0x80000000
    return a


def asm_stub():
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 's.s').write_text(WRITE_STUB.format(log=hex(LOG)))
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 's.o', t / 's.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(FLASH_WRITE), '-e', '_start',
                        '-o', t / 's.elf', t / 's.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 's.elf', t / 's.bin'], check=True)
        return (t / 's.bin').read_bytes()


def run(d, stub, pkg, mode):
    img = lambda n, lo, hi, p='rx': Region(n, lo, d[lo - BASE:hi - BASE], p)
    regions = [
        Region('caller', CALLER, b'\xdd' + struct.pack('<i', VALIDATE - CALLER) + b'\xf0\x10\xcb', 'rx'),
        img('validator', CODE_LO, CODE_HI), img('hdr', HDR_LO, HDR_HI), img('strcmp', STRCMP_LO, STRCMP_HI),
        img('addr', ADDR_LO, ADDR_HI), img('data', DATA_LO, DATA_HI, 'r'), img('ostr', OSTR, OSTR + 8, 'r'),
        Region('log_a', 0x6002247c, b'\xdf\x30\x1c', 'rx'),      # ret [a2,a3],28
        Region('log_b', 0x6002266d, b'\xdf\xa0\x18', 'rx'),      # ret [d2,a2],24
        Region('flash_write', FLASH_WRITE, stub, 'rx'),
        Region('stack', STACK - 0x4000, bytes(0x4000), 'rw'),
        Region('buf', BUF, pkg, 'rw', True),
        Region('log', LOG, bytes(0x400), 'rw', True),
    ]
    regs = {'pc': CALLER, 'sp': STACK - 0x100, 'a0': BUF, 'd0': len(pkg), 'd1': mode, 'a1': 0,
            'd2': 0x2222, 'd3': 0x3333, 'a2': 0xa2a2, 'a3': 0xa3a3}
    r = execute(regions, regs, CALLER + 7, limit=5_000_000, timeout=120)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    n = struct.unpack_from('<I', mem['log'], 0)[0]
    writes = [dict(zip(('dst', 'src', 'size', 'mode'), struct.unpack_from('<4I', mem['log'], 4 + 16 * i)))
              for i in range(n)]
    rr = r['registers']
    return dict(returned=rr['pc'] == CALLER + 7, status=rr['d0'] & 0xffff, fault=r['fault'],
                instructions=r['completed'], writes=writes, buf=mem['buf'],
                callee_saved=(rr['d2'], rr['d3'], rr['a2'], rr['a3']) == (0x2222, 0x3333, 0xa2a2, 0xa3a3))


SUFFIX = 0x60c95fd8                                     # 4-char hex parser used by the dir callback


def suffix(d, name):
    regions = [Region('caller', CALLER, b'\xdd' + struct.pack('<i', SUFFIX - CALLER) + b'\xf0\x10\xcb', 'rx'),
               Region('code', SUFFIX, d[SUFFIX - BASE:0x60c9602d - BASE], 'rx'),
               Region('stack', STACK - 0x1000, bytes(0x1000), 'rw'), Region('name', BUF, name)]
    r = execute(regions, {'pc': CALLER, 'sp': STACK - 0x100, 'a0': BUF + 4, 'd0': 4}, CALLER + 7, limit=2000)
    return r['registers']['d0']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    a = ap.parse_args()
    d = main_image()
    if STOCK.is_file():                                   # self-check of our encoder against stock
        with STOCK.open('rb') as f:
            f.seek(0x20)
            assert decode(f.read(0x1000)) == d[:0x1000], 'scramble model does not match stock'
    stub = asm_stub()
    main_c = component(0x100)
    osd_c = component(0x101, version=0x0100, address=0x421a0000)
    cases = [
        # name, package, mode, expected status, expected write count (mode 0/1 only)
        ('main-only valid, same build 0x1100', main_c, 2, 0, 0),
        ('main-only, build 0x1000 (downgrade)', component(0x100, version=0x1000), 2, 0, 0),
        ('main-only, build 0x0000', component(0x100, version=0x0000), 2, 0, 0),
        ('main-only, build 0xffff', component(0x100, version=0xffff), 2, 0, 0),
        ('bad checksum', component(0x100, break_sum=True), 2, 0x3211, 0),
        ('header/trailer mismatch', component(0x100, break_trailer=True), 2, 0x3202, 0),
        ('PEN-F model 0x1220', component(0x100, model=b'\x12\x20'), 2, 0x3202, 0),
        ('duplicate main component (no dup check for E kinds)', main_c + main_c, 2, 0, 0),
        ('SD mode: duplicate main -> only LAST copy written', main_c + main_c, 0, 0, 1),
        ('OSD+main valid', osd_c + main_c, 2, 0, 0),
        ('SD mode: OSD+main valid -> writes', osd_c + main_c, 0, 0, 2),
        ('SD mode: main + corrupt OSD -> no write', main_c + component(0x101, version=0x0100, address=0x421a0000,
                                                                         break_sum=True), 0, 0x3211, 0),
        ('SD mode: main-only, build 0x0000 -> writes', component(0x100, version=0x0000), 0, 0, 1),
    ]
    results, ok_all = [], True
    for name, pkg, mode, want, nwrites in cases:
        r = run(d, stub, pkg, mode)
        ok = r['returned'] and r['callee_saved'] and r['status'] == want and len(r['writes']) == nwrites
        detail = ''
        if r['writes']:
            # each write must cover a whole component (header..trailer) at its header address
            exp, off = [], 0
            while off < len(pkg):
                ln = struct.unpack_from('<I', pkg, off + 12)[0]
                exp.append((struct.unpack_from('<I', pkg, off + 8)[0], BUF + off, ln + 64,
                            struct.unpack_from('<H', pkg, off + 20)[0]))
                off += ln + 64
            order = {0x101: 0, 0x100: 1}                  # firmware order: OSD (bit 2) before USR (bit 1)
            exp.sort(key=lambda e: order[e[3]])
            got = [(w['dst'], w['src'], w['size']) for w in r['writes']]
            if len(exp) == 2 and exp[0][3] == exp[1][3]:
                exp = exp[1:]                             # duplicate kind: last instance wins
            want_w = [(flash_alias(e[0]), e[1], e[2]) for e in exp]
            ok &= got == want_w
            # the buffer handed to flash is header + DESCRAMBLED payload + trailer
            src = r['writes'][-1]['src'] - BUF
            ok &= r['buf'][src + 32:src + 32 + 0x400] == decode(pkg[src + 32:src + 32 + 0x400])
            detail = ', '.join(f"dst={w['dst']:#x} size={w['size']:#x} mode={w['mode']}" for w in r['writes'])
        ok_all &= bool(ok)
        results.append(dict(case=name, mode=mode, passed=bool(ok), status=hex(r['status']), want=hex(want),
                            writes=len(r['writes']), detail=detail, instructions=r['instructions'],
                            fault=r['fault']))
        print(f"{'PASS' if ok else 'FAIL'}  mode={mode} status={r['status']:#06x} writes={len(r['writes'])}  {name}"
              + (f'  [{detail}]' if detail else ''))
    # file-name suffix: chars 4..7 parsed as hex; dir callback 0x60c95f05 keeps the largest value > 0
    for nm, want in ((b'E1429999BIN', 0x9999), (b'E1420000BIN', 0), (b'E14200A1BIN', 0xa1),
                     (b'E142ffffBIN', 0xffff), (b'E142G001BIN', 0x001), (b'E142 999BIN', 0)):
        got = suffix(d, nm)
        ok = got == want
        ok_all &= ok
        results.append(dict(case=f'suffix {nm.decode()}', passed=ok, value=hex(got)))
        print(f"{'PASS' if ok else 'FAIL'}  suffix {nm.decode()!r} -> {got:#x}")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1))
    print('ALL PASS' if ok_all else 'SOME FAILED')
    return 0 if ok_all else 1


if __name__ == '__main__':
    sys.exit(main())
