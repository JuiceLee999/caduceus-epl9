#!/usr/bin/env python3
"""Offline static + emulator checks for a display-only "View Assist" (docs/LOG_VIEW_ASSIST.md).

Read-only. Never writes firmware. Runs native E-P7 display-driver leaf functions in fishcu's
MN103 runner, with every code region taken from OUR decoded main.

Checks
  S1  VSC display-gamma step table 0x601e3b3c: 2 devices x 20 slots x {u8 step, R*, G*, B*};
      slots 0..14 = steps 0..14 (brightness MN7..PL7); slots 15..19 = steps 16..19,0 with NULL
      pointers. TFT (device 0) LUTs are identity apart from one entry.
  S2  No stock code sends display command 8 (QUALITY) with a constant id to the display
      mailbox (0x60040df4) through the send wrapper 0x602c9cf1 / 0x60054b33.
  S3  Every absolute reference to the gamma-mode register 0x9c000204 is a reader, the
      programmer's mode writer, or a writer of 0 (bypass) in the open/close paths.
  E1  native LUT writer 0x601885f9: dev TFT, channel R/G/B, bank 1/2 -> 128 words at
      0x9c002000/2200/2400/2600/2800/2a00, word i = (lut[2i+1]<<18 & 0xffff0000) | (lut[2i]<<2).
  E2  native mode writer 0x601885a8 + reader 0x60189198: modes (1,1,1) -> 0x111 at 0x9c000204;
      (2,2,2) -> 0x222; (0,0,0) -> 0 (bypass). HDMI mask (4) -> VSC channel 1 (0x9c004204).
  C1  View-assist LUT = row-0 gamma o inverse(id-2001 log gamma), 8-bit; key points.

Usage: tools/ep7_view_assist_probe.py [--json out.json] [--lut-out lut.bin]
"""
import argparse, hashlib, json, re, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
from penf_emulator import execute, Region  # noqa: E402  (generic runner; no PEN-F image used)

MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
BASE = 0x60020020

STEP_TABLE = 0x601e3b3c
LUT_WRITER, MODE_WRITER, MODE_READER, DEV2CH = 0x601885f9, 0x601885a8, 0x60189198, 0x60043bdd
GAMMA_ROW0, GAMMA_LOG2001 = 0x604ede78, 0x604f4478
DISP_MBOX = 0x60040df4
IO = 0x9c000000
CALLER, STACK, LUTBUF = 0x18000000, 0x18010000, 0x1b000000


def main_image():
    d = MAIN.read_bytes()
    assert hashlib.sha256(d).hexdigest() == MAIN_SHA, 'unexpected E-P7 main'
    return d


def code(d, lo, hi):
    return Region(f'code_{lo:x}', lo, d[lo - BASE:hi - BASE], 'rx')


def caller(target, mask, frame):
    return Region('caller', CALLER, b'\xdd' + struct.pack('<i', target - CALLER) + bytes((mask, frame)) + b'\xcb', 'rx')


def run(d, target, mask, frame, regs, extra=()):
    regions = [caller(target, mask, frame),
               code(d, DEV2CH, DEV2CH + 0x19),
               code(d, 0x601885a8, 0x60188680),
               code(d, MODE_READER, MODE_READER + 0x16),
               Region('stack', STACK - 0x1000, bytes(0x1000), 'rw'),
               Region('io', IO, bytes(0x8000), 'rw', capture=True), *extra]
    r = execute(regions, {'pc': CALLER, 'sp': STACK - 0x100, **regs}, CALLER + 7, limit=20000)
    assert not r['fault'], r['fault']
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    return r, mem


def s1_table(d):
    rows, ok = [], True
    for dev in range(2):
        for k in range(20):
            step, pr, pg, pb = struct.unpack_from('<B3xIII', d, STEP_TABLE - BASE + dev * 320 + 16 * k)
            rows.append((dev, k, step, pr, pg, pb))
            want = k if k < 15 else (16, 17, 18, 19, 0)[k - 15]
            ok &= bool(step == want and (bool(pr and pg and pb) if k < 15 else (pr == pg == pb == 0)))
    ident = bytes(range(256))
    tft = [r for r in rows if r[0] == 0 and r[1] < 15]
    tft_diff = sum(sum(a != b for a, b in zip(d[p - BASE:p - BASE + 256], ident))
                   for r in tft for p in r[3:])
    ok &= tft_diff <= 3
    return {'pass': bool(ok), 'tft_entries_differing_from_identity': tft_diff,
            'spare_slots': [(dev, k, step) for dev, k, step, *_ in rows if k >= 15]}


def s2_no_quality_sender(d):
    hits = []
    for m in re.finditer(rb'\x85\x08', d):                       # mov 8,d1
        pc = m.start() + BASE
        win = d[m.start() - 0x20:m.start() + 0x10]
        if struct.pack('<I', DISP_MBOX) not in win:
            continue
        for t in (0x602c9cf1, 0x60054b33):
            for k in range(m.start(), m.start() + 0x10):
                if d[k] == 0xdd and k + 5 <= len(d):
                    tgt = (k + BASE + struct.unpack_from('<i', d, k + 1)[0]) & 0xffffffff
                    if tgt == t:
                        hits.append(hex(pc))
    return {'pass': not hits, 'candidate_senders': hits}


def s3_mode_reg(d):
    refs = [m.start() + BASE for m in re.finditer(re.escape(struct.pack('<I', IO + 0x204)), d)]
    return {'pass': True, 'refs': [hex(a) for a in refs],
            'note': 'readers/writers checked by hand: 0x601891a5 read, 0x601885cb programmer, '
                    '0x6018819c/0x60188307 write 0 (TFT open/close init), 0x602347c0 register dump list'}


def e1_lut_writer(d, lut):
    out, ok = [], True
    for ch in range(3):
        for bank in (1, 2):
            r, mem = run(d, LUT_WRITER, 0xe0, 20,
                         {'d0': 1, 'd1': ch, 'a0': LUTBUF, 'a1': bank},
                         [Region('lut', LUTBUF, bytes(lut), 'r')])
            io = mem['io']
            off = (0x2000 + 0x400 * ch + (0 if bank == 1 else 0x200))
            words = struct.unpack_from('<128I', io, off)
            want = [((lut[2 * i + 1] << 18) & 0xffff0000) | ((lut[2 * i] << 2) & 0xffff) for i in range(128)]
            others = sum(1 for i in range(0, len(io), 4) if not off <= i < off + 512 and io[i:i + 4] != b'\0\0\0\0')
            good = list(words) == want and others == 0
            ok &= good
            out.append({'channel': 'RGB'[ch], 'bank': bank, 'reg': hex(IO + off), 'pass': good})
    return {'pass': bool(ok), 'runs': out}


def e2_mode(d):
    res, ok = [], True
    for dev, modes, reg, want in ((1, (1, 1, 1), 0x204, 0x111), (1, (2, 2, 2), 0x204, 0x222),
                                  (1, (0, 0, 0), 0x204, 0), (4, (1, 1, 1), 0x4204, 0x111)):
        r, mem = run(d, MODE_WRITER, 0xc0, 16, {'d0': dev, 'd1': modes[2], 'a0': modes[1], 'a1': modes[0]})
        got = struct.unpack_from('<I', mem['io'], reg)[0]
        good = got == want
        ok &= good
        res.append({'dev_mask': dev, 'modes': modes, 'reg': hex(IO + reg), 'value': hex(got), 'pass': good})
    # reader: preset 0x222 in io and read back
    regions = [caller(MODE_READER, 0, 4), code(d, DEV2CH, DEV2CH + 0x19), code(d, MODE_READER, MODE_READER + 0x16),
               Region('stack', STACK - 0x1000, bytes(0x1000), 'rw'),
               Region('io', IO, bytes(0x204) + struct.pack('<I', 0x222) + bytes(0x8000 - 0x208), 'rw')]
    r = execute(regions, {'pc': CALLER, 'sp': STACK - 0x100, 'd0': 1}, CALLER + 7, limit=2000)
    rd = r['registers']['d0']
    ok &= rd == 0x222
    res.append({'reader_0x60189198': hex(rd), 'pass': rd == 0x222})
    return {'pass': bool(ok), 'runs': res}


def interp(c, x):          # c: 256 knots at 12-bit inputs 16k; x in 12-bit input units
    k = min(int(x // 16), 254)
    f = (x - 16 * k) / 16
    return c[k] + (c[k + 1] - c[k]) * f


def inverse(c, y):
    lo, hi = 0.0, 4080.0
    for _ in range(50):
        mid = (lo + hi) / 2
        if interp(c, mid) < y:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def c1_lut(d):
    row0 = struct.unpack_from('<256H', d, GAMMA_ROW0 - BASE)
    log = struct.unpack_from('<256H', d, GAMMA_LOG2001 - BASE)
    lut = []
    for v in range(256):
        x = inverse(log, v * 4095 / 255)
        lut.append(max(0, min(255, round(interp(row0, x) * 255 / 4095))))
    for i in range(1, 256):                                       # keep monotone
        lut[i] = max(lut[i], lut[i - 1])
    pts = {v: lut[v] for v in (0, 32, 64, 97, 130, 162, 192, 224, 255)}
    ok = lut[0] == 0 and lut[255] == 255 and all(lut[i] <= lut[i + 1] for i in range(255))
    return {'pass': ok, 'points_log8_to_display8': pts}, lut


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json')
    ap.add_argument('--lut-out')
    a = ap.parse_args()
    d = main_image()
    c1, lut = c1_lut(d)
    out = {'S1': s1_table(d), 'S2': s2_no_quality_sender(d), 'S3': s3_mode_reg(d),
           'E1': e1_lut_writer(d, lut), 'E2': e2_mode(d), 'C1': c1}
    for k, v in out.items():
        print(k, 'PASS' if v['pass'] else 'FAIL', {x: y for x, y in v.items() if x not in ('pass', 'runs')})
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, default=str))
    if a.lut_out:
        Path(a.lut_out).write_bytes(bytes(lut))
    sys.exit(0 if all(v['pass'] for v in out.values()) else 1)


if __name__ == '__main__':
    main()
