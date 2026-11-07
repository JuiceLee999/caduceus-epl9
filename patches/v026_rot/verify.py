#!/usr/bin/env python3
"""v0.26 rotation checks (emulator + ffmpeg on a scratch copy). Offline, no camera, no card.
  .venv/bin/python -I patches/v026_rot/verify.py releases/v0.25/edits.json generated/v026_rot/edits.json --scratch DIR [--pkg generated/v026_rot/pkg]
S  REC_START: real site, real getter, real table lookup, stock vs patched: latch == 3/6/8 or 0 for anything else (mute on: 0); neighbours untouched;
   every register at the stock callee's entry and after return, and the caller stack, == stock (fake callee records and trashes them)
M  tkhd: real caller 0x61308869 through the real serialiser, stock vs patched: bytes == stock outside the matrix, matrix == expected; identity == stock bytes
   for 0, 1 and unknown latches, also over a stale rotated struct; registers and stack == stock; rewrites are idempotent
F  REC_FREE: as S; latch 0 afterwards; d0 (the return value) kept
Q  sequence: start 6, tkhd, tkhd (chapter), free, tkhd == identity; start 6 then start 1 == identity
X  ffprobe / ffmpeg on a scratch copy of a real clip: rotation, and the upright frame == the same frame through PIL's EXIF transpose for that code
D  image diff vs the base only at the claimed bytes
K  anti-brick: package parses, components match, restore == stock, decoded main == the emulated image (and == --pkg if given)
"""
import argparse, hashlib, importlib.util, io, json, shutil, struct, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools')); sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m


R = _load('ep7_v026_rot_build', ROOT / 'patches/v026_rot/build.py')
SB3, BASE = R.SB3, R.BASE
SP0, STACK, FILL = 0x18011800, 0x18010000, 0xa5
RAM0, RAM1 = 0x6203c880, 0x6203c8c0            # sensor statics around the latch
REC, THIS, DESC, OUT = 0x17000000, 0x16000000, 0x16001000, 0x16002000
OUT_LEN, TAB_N = 0x16003000, 16
FAKE = dict(d0=0x1234, d1=0x5678, a0=0x9abc, a1=0xdef0)
REGS0 = dict(d0=0xd0d0d0d0, d1=0xd1d1d1d1, d2=0xd2d2, d3=0xd3d3, a0=0xa0a0a0a0, a1=0xa1a1a1a1, a2=0x15000000, a3=0xa3a3)
REG = ('d0', 'd1', 'd2', 'd3', 'a0', 'a1', 'a2', 'a3', 'sp', 'pc')
ID = (0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
UNKNOWN = (0, 2, 4, 5, 7, 9, 0x103, 0x106, 0x108, 0xff03, 0xffff)


def expect_matrix(code, w, h):
    return {6: (0, 0x10000, 0, -0x10000 & 0xffffffff, 0, 0, h, 0, 0x40000000),
            8: (0, -0x10000 & 0xffffffff, 0, 0x10000, 0, 0, 0, w, 0x40000000),
            3: (-0x10000 & 0xffffffff, 0, 0, 0, -0x10000 & 0xffffffff, 0, w, h, 0x40000000)}.get(code, ID)


def image(spec):
    return R.image(spec)


def fake(at, ret_val):
    src = f""" .am33_2
 .text
 .global _start
_start:
 mov d0,({REC:#x})
 mov d1,({REC + 4:#x})
 mov a0,({REC + 8:#x})
 mov a1,({REC + 12:#x})
 mov d2,({REC + 16:#x})
 mov d3,({REC + 20:#x})
 mov a2,({REC + 24:#x})
 mov a3,({REC + 28:#x})
 mov sp,a0
 mov a0,({REC + 32:#x})
 mov {ret_val:#x},d0
 mov {FAKE['d1']:#x},d1
 mov {FAKE['a0']:#x},a0
 mov {FAKE['a1']:#x},a1
 mov 0x77,d2
 mov 0x88,d3
 mov 0x99,a2
 mov 0xaa,a3
 ret [d2,d3,a2,a3],32
"""
    return SB3.assemble(src, at, {})[0]


def statics(latch, mute, state):
    b = bytearray(bytes((i * 7 + 3) & 0xff for i in range(RAM1 - RAM0)))
    struct.pack_into('<I', b, R.MUTE - RAM0, mute); struct.pack_into('<I', b, R.STATE - RAM0, state)
    b[R.LATCH - RAM0], b[R.LATCH + 1 - RAM0] = latch, 0x5a
    return bytes(b)


def dispatch(im, entry, stop, callee, ret_val, ram, table):
    code = [Region('site', 0x603d4020, im[0x603d4020 - BASE:0x603d4060 - BASE], 'rx'), Region('fake', callee, fake(callee, ret_val), 'rx'),
            Region('stub', R.AT, im[R.AT - BASE:R.END - BASE], 'rx'), Region('getter', R.ORIENT, im[R.ORIENT - BASE:0x6006d180 - BASE], 'rx')]
    r = execute(code + [Region('table', R.TABLE, table), Region('ram', RAM0, ram, 'rw', True), Region('rec', REC, bytes(64), 'rw', True),
                        Region('stack', STACK, bytes([FILL] * 0x2000), 'rw', True)],
                dict(pc=entry, sp=SP0, **REGS0), stop, limit=4000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    return r['fault'], r['registers'], m


def table(code):
    return struct.pack('<8H', 0xbad, code, code, code, code, code, code, 0xbad)


def same(a, b, keys=REG):
    return [k for k in keys if a[k] != b[k]]


def t_start(stock, new):
    n, bad = 0, []
    for mute in (0, 1):
        for code in (1, 3, 6, 8) + UNKNOWN:
            for st in (1, 4):
                for old in (0, 6):
                    ram = statics(old, mute, st)
                    f0, r0, m0 = dispatch(stock, 0x603d4026, R.START_RET, R.START_CALL, 0x4242, ram, table(code))
                    f1, r1, m1 = dispatch(new, 0x603d4026, R.START_RET, R.START_CALL, 0x4242, ram, table(code))
                    want = 0 if mute == 1 else code if code in (3, 6, 8) else 0
                    ramw = bytearray(ram); ramw[R.LATCH - RAM0] = want
                    d = same(r0, r1); n += 1
                    if f0 or f1 or d or m1['rec'] != m0['rec'] or m1['ram'] != bytes(ramw) or m1['stack'][0x1804:] != m0['stack'][0x1804:]:
                        bad.append((mute, code, st, old, f1, d, m1['ram'][R.LATCH - RAM0]))
    return n, bad


def t_free(stock, new):
    n, bad = 0, []
    for old in (0, 1, 3, 6, 8, 0xff):
        ram = statics(old, 0, 2)
        f0, r0, m0 = dispatch(stock, 0x603d4052, R.FREE_RET, R.FREE_CALL, 0x4242, ram, table(1))
        f1, r1, m1 = dispatch(new, 0x603d4052, R.FREE_RET, R.FREE_CALL, 0x4242, ram, table(1))
        ramw = bytearray(ram); ramw[R.LATCH - RAM0] = 0
        d = same(r0, r1); n += 1
        if f0 or f1 or d or r1['d0'] != 0x4242 or m1['rec'] != m0['rec'] or m1['ram'] != bytes(ramw) or m1['stack'][0x1804:] != m0['stack'][0x1804:]:
            bad.append((old, f1, d, hex(r1['d0'])))
    return n, bad


def obj(w, h, mat=ID):
    b = bytearray(bytes((i * 11 + 5) & 0xff for i in range(0x400)))
    struct.pack_into('<9I', b, 144 + 48, *mat); struct.pack_into('<II', b, 144 + 84, w, h)
    return bytes(b)


def tkhd(im, o, latch, start_off=0x40):
    d = bytearray(32); struct.pack_into('<I', d, 8, OUT); struct.pack_into('<I', d, 12, 0x1000); struct.pack_into('<I', d, 20, start_off)
    rg = [Region('call', 0x61308860, im[0x61308860 - BASE:0x61308870 - BASE], 'rx'), Region('ser', 0x61308ab6, im[0x61308ab6 - BASE:0x61308d47 - BASE], 'rx'),
          Region('helper', 0x600dad00, im[0x600dad00 - BASE:0x600db000 - BASE], 'rx'),
          Region('stub', R.AT, im[R.AT - BASE:R.END - BASE], 'rx'), Region('ram', RAM0, statics(latch, 0, 2), 'r'), Region('obj', THIS, o, 'rw', True),
          Region('desc', DESC, bytes(d), 'rw', True), Region('out', OUT, bytes(0x1000), 'rw', True), Region('len', OUT_LEN, bytes(16), 'rw', True),
          Region('stack', STACK, bytes([FILL] * 0x2000), 'rw', True)]
    r = execute(rg, dict(pc=0x61308869, sp=SP0, d0=DESC, d1=0xd1, d2=0xd2, d3=0xd3, a0=THIS, a1=OUT_LEN, a2=0xa2, a3=0xa3), 0x6130886e, limit=6000)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    return r['fault'], r['registers'], m


SIZES = ((3840 << 16, 2160 << 16), (1920 << 16, 1080 << 16), (4096 << 16, 2160 << 16))
REG_M = ('d0', 'd2', 'd3', 'a2', 'a3', 'sp', 'pc')


def box_matrix(out, start=0x40):
    """Matrix file bytes: 36 bytes before the big-endian width word, located from the identity run's layout."""
    return struct.unpack('>9I', out[start + 48:start + 84])


def t_mat(stock, new):
    n, bad, seen = 0, [], {}
    stale = expect_matrix(6, 1 << 16, 1 << 16)
    for w, h in SIZES[:2]:
        for latch in (0, 1, 3, 6, 8, 2, 7, 0x86, 0xff):
            for pre in (ID, stale):
                o = obj(w, h, pre)
                f0, r0, m0 = tkhd(stock, obj(w, h), latch)         # stock always sees the identity it built
                f1, r1, m1 = tkhd(new, o, latch)
                want = expect_matrix(latch, w, h)
                got = box_matrix(m1['out'])
                wb = bytearray(m0['out']); wb[0x40 + 48:0x40 + 84] = struct.pack('>9I', *want)
                wo = bytearray(obj(w, h)); struct.pack_into('<9I', wo, 144 + 48, *want)
                d = same(r0, r1, REG_M); n += 1
                if f0 or f1 or d or got != want or m1['out'] != bytes(wb) or m1['desc'] != m0['desc'] or m1['len'] != m0['len'] or m1['obj'] != bytes(wo) or m1['stack'][0x1804:] != m0['stack'][0x1804:]:
                    bad.append((w >> 16, h >> 16, latch, pre is stale, f0 or f1, d, got))
                if latch not in (3, 6, 8) and m1['out'] != m0['out']:
                    bad.append(('identity != stock bytes', latch))
                if latch in (1, 3, 6, 8) and w == SIZES[0][0] and pre is ID:
                    seen[latch] = (struct.pack('>9I', *got), m0['out'][0x40 + 84:0x40 + 92])
    return n, bad, seen


def t_seq(new):
    bad = []
    w, h = SIZES[0]
    ram = statics(0, 0, 2)
    _, _, m = dispatch(new, 0x603d4026, R.START_RET, R.START_CALL, 0, ram, table(6)); l1 = m['ram'][R.LATCH - RAM0]
    o = obj(w, h)
    for label in ('first moov', 'second write', 'chapter'):
        _, _, mm = tkhd(new, o, l1); o = mm['obj']
        if box_matrix(mm['out']) != expect_matrix(6, w, h):
            bad.append(label)
    _, _, m = dispatch(new, 0x603d4052, R.FREE_RET, R.FREE_CALL, 0, m['ram'], table(6)); l2 = m['ram'][R.LATCH - RAM0]
    _, _, mm = tkhd(new, o, l2)
    if l1 != 6 or l2 != 0 or box_matrix(mm['out']) != ID:
        bad.append(('after free', l1, l2, box_matrix(mm['out'])))
    _, _, m = dispatch(new, 0x603d4026, R.START_RET, R.START_CALL, 0, statics(6, 0, 2), table(1))
    _, _, mm = tkhd(new, o, m['ram'][R.LATCH - RAM0])
    if box_matrix(mm['out']) != ID:
        bad.append('re-latch to level')
    return bad


def rms(a, b):
    import numpy as np
    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return float(np.sqrt(((x - y) ** 2).mean()))


def t_ff(scratch, seen):
    from PIL import Image, ImageOps
    bad, rows = [], {}
    scratch = Path(scratch); scratch.mkdir(parents=True, exist_ok=True)
    src = ROOT / 'testdata/camera_t5/PB010042.MOV'
    base = scratch / 'rot_0.MOV'
    shutil.copyfile(src, base)
    head = base.read_bytes()[:0x100]
    if head[0x98:0x9c] != b'tkhd' or head[0xc4:0xe8] != seen[1][0] or head[0xe8:0xf0] != seen[1][1]:
        bad.append(('sample tkhd != emulator identity output', head[0xc4:0xf0].hex()))
    w, h = struct.unpack('>II', head[0xe8:0xf0])
    def frame(p, *fl):
        png = subprocess.run(['ffmpeg', '-v', 'error', '-threads', '2', *fl, '-i', str(p), '-frames:v', '1', '-f', 'image2pipe', '-c:v', 'png', '-'], capture_output=True, check=True).stdout
        return Image.open(io.BytesIO(png)).convert('L')
    ref = frame(base)
    for code, want in ((1, None), (6, -90), (8, 90), (3, 180)):
        p = scratch / f'rot_{code}.MOV'
        shutil.copyfile(src, p)
        with open(p, 'r+b') as f:
            f.seek(0xc4); f.write(seen[code][0])
        j = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-of', 'json', str(p)], capture_output=True, text=True, check=True).stdout)
        st = j['streams'][0]; rot = next((x.get('rotation') for x in st.get('side_data_list', []) if 'rotation' in x), None)
        got = frame(p)
        buf = io.BytesIO(); ex = Image.Exif(); ex[274] = code; ref.save(buf, 'JPEG', quality=98, exif=ex); buf.seek(0)
        exif_up = ImageOps.exif_transpose(Image.open(buf)).convert('L')
        size_ok = got.size == exif_up.size == ((h >> 16, w >> 16) if code in (6, 8) else (w >> 16, h >> 16))
        e = rms(got, exif_up) if got.size == exif_up.size else 1e9
        wrong = rms(got, exif_up.transpose(Image.ROTATE_180)) if size_ok else 0
        rows[code] = dict(ffprobe=rot, frame=got.size, rms_vs_exif=round(e, 2), rms_vs_opposite=round(wrong, 2))
        rot_ok = abs(rot or 0) == 180 if code == 3 else (rot or 0) == (want or 0)
        if not rot_ok or not size_ok or e > 3 or wrong < 5:
            bad.append((code, rows[code]))
        p.unlink()
    base.unlink()
    return rows, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('base'); ap.add_argument('new'); ap.add_argument('--scratch', required=True); ap.add_argument('--pkg', type=Path)
    a = ap.parse_args()
    bsp, spec = json.loads(Path(a.base).read_text()), json.loads(Path(a.new).read_text())
    raw = R.STOCK.read_bytes()
    base, new = image(bsp), image(spec)
    fails = []
    # both directions of the replay are against the v0.25 image (the stubs' callers are stock there)
    n, bad = t_start(base, new); print(f'S REC_START: {n - len(bad)}/{n}', bad[:6]); fails += ['S'] * bool(bad)
    n, bad, seen = t_mat(base, new); print(f'M tkhd: {n - len(bad)}/{n}', bad[:6]); fails += ['M'] * bool(bad)
    n, bad = t_free(base, new); print(f'F REC_FREE: {n - len(bad)}/{n}', bad[:6]); fails += ['F'] * bool(bad)
    bad = t_seq(new); print('Q sequence:', bad or 'ok'); fails += ['Q'] * bool(bad)
    rows, bad = t_ff(a.scratch, seen); print('X', json.dumps(rows), bad or 'ok'); fails += ['X'] * bool(bad)
    allowed = [(R.AT, R.END), (R.START, R.START + 5), (R.FREE, R.FREE + 5), (R.MAT, R.MAT + 6)]
    diff = [i + BASE for i in range(len(new)) if new[i] != base[i]]
    rest = [hex(x) for x in diff if not any(l <= x < h for l, h in allowed)]
    print('D', len(diff), 'bytes differ; outside the claim:', rest); fails += ['D'] * bool(rest)
    pkg, rst, info = BP.build(spec, BP.STOCK.read_bytes())
    parts = oc.parse(pkg)
    k = dict(reparses=[b.kind for b in parts] == [int(x, 16) for x in spec['components']],
             restore_is_stock=hashlib.sha256(oc.parse(rst)[0].payload).hexdigest() == hashlib.sha256(raw).hexdigest(),
             restore_slices_stock=rst == b''.join(BP.STOCK.read_bytes()[b.offset:b.offset + 64 + len(b.payload)] for b in oc.parse(BP.STOCK.read_bytes()) if hex(b.kind) in spec['components']),
             decoded_is_emulated=bytes(parts[0].payload) == new)
    if a.pkg:
        k['pkg_matches'] = (a.pkg / 'patched.pkg.bin').read_bytes() == pkg and (a.pkg / 'restore-stock.pkg.bin').read_bytes() == rst
    print('K', k, info); fails += ['K'] * (not all(k.values()))
    if fails:
        sys.exit(f'VERIFY FAILED {fails}')
    print('ALL OK')


if __name__ == '__main__':
    main()
