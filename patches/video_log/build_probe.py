#!/usr/bin/env python3
"""E-P7 1.1 video log + on-camera probe (test13 diagnosis: movie + Muted not log on test13).

Moves vlog_hook from the sec-1 tail stub 0x60210c90 (edit dropped -> FF again) to the dead EVF gamma step-8 R table
0x601e203c (only ref: EVF step-table word 0x601e3d00) and adds a probe record in the loader's heap block P
(video_log_probe.s.in). The +925 decision is unchanged. The probe text is shown by look_extras: its
`mov ex_t_other,a2` (inside the 0x601e323c blob) becomes `calls vlog_txt`, so the Extras page, sectors 6-12,
shows "Vnn ppp m? t? r?" instead of "Extras: 1-5 only" once the hook has run with P loaded.

  python3 -I patches/video_log/build_probe.py SPEC [--write]   (SPEC = merged edits.json, e.g. releases/test13)
Checks (emulator, native code from the merged image): D decision == the video_log case matrix, with and without
a valid P; T probe text and flags; X vlog_txt with/without P/magic; image regions read-only throughout.
"""
import argparse, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
sys.path.insert(0, str(ROOT / 'patches/sd_bundles_v3'))
import ep7_video_log_probe as VP  # noqa: E402
from penf_emulator import Region  # noqa: E402
import build as B3  # noqa: E402  (sd_bundles_v3: STATE, POOL, LIM, MAGIC)

TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE = 0x60020020
HOOK, STOCK5 = 0x6030df3d, bytes.fromhex('266001f172')
FN_END = 0x6030df6c
OLD_AT = 0x60210c90
CODE_AT, CODE_END = 0x601e203c, 0x601e223c       # dead EVF step-8 R+G tables (refs: step-table words 0x601e3d00/04 only)
SYMS = dict(ep7_stock_body=0x6030df42, ep7_store_ret=0x6030df67)
EX_BLOB, EX_MOV = 0x601e323c, 0x601e3551         # look_extras blob; `mov ex_t_other,a2` (fc de imm32)
VMAGIC = struct.unpack('<I', b'VLGP')[0]
W = [struct.unpack('<I', s)[0] for s in (b'Vnn ', b'pxx ', b'mx t', b'x rx')]
MSG, REC = 0x1b000000, 0x1c000000


def assemble(trig, ex_t_other):
    sub = dict(trig_log=trig, state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL), bmagic=hex(B3.MAGIC),
               vmagic=hex(VMAGIC), w0=hex(W[0]), w1=hex(W[1]), w2=hex(W[2]), w3=hex(W[3]), ex_t_other=hex(ex_t_other))
    src = (Path(__file__).parent / 'video_log_probe.s.in').read_text()
    for k, v in sub.items():
        src = src.replace('{' + k + '}', str(v))
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in SYMS.items()], '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        syms = {l.split()[2]: int(l.split()[0], 16) for l in nm.splitlines() if len(l.split()) == 3}
        return (t / 'p.bin').read_bytes(), syms, dis


def apply(spec, stock, trig):
    edits = [e for e in spec['edits'] if e['addr'] not in (hex(HOOK), hex(OLD_AT), hex(CODE_AT))]
    ex = next(e for e in edits if e['addr'] == hex(EX_BLOB))
    blob = bytearray.fromhex(ex['new'])
    o = EX_MOV - EX_BLOB
    if blob[o:o + 2] == b'\xfc\xde':
        ex_t_other = struct.unpack_from('<I', blob, o + 2)[0]
    else:                                              # already patched: recover the text address from vlog_txt
        raise SystemExit('look_extras blob already patched; rebuild from a spec without the probe')
    assert blob[ex_t_other - EX_BLOB:ex_t_other - EX_BLOB + 16] == b'Extras: 1-5 only'
    code, syms, dis = assemble(trig, ex_t_other)
    assert syms['vlog_hook'] == CODE_AT and CODE_AT + len(code) <= CODE_END, (hex(CODE_AT + len(code)))
    blob[o:o + 6] = b'\xfc\xff' + struct.pack('<i', syms['vlog_txt'] - EX_MOV)
    edits[edits.index(ex)] = dict(ex, new=blob.hex(), why=ex['why'] + ' + video_log probe: Extras 6-12 -> calls vlog_txt')
    s0 = stock[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    edits += [dict(kind='0x100', addr=hex(HOOK), expect=STOCK5.hex(),
                   new=(b'\xdc' + struct.pack('<i', CODE_AT - HOOK)).hex(),
                   why='movie-picture-mode derivation entry: mov 352,a2; add a0,a2 -> jmp vlog_hook (probe build)'),
              dict(kind='0x100', addr=hex(CODE_AT), expect=s0.hex(), new=code.hex(),
                   why=f'vlog_hook + probe + vlog_txt ({len(code)} B, dead EVF step-8 R/G tables): movie && pm=={trig} '
                       '-> +925=2; probe text in heap P+960..999')]
    out = dict(spec, edits=edits)
    out['video_log'] = dict(trig_log=trig, code_at=hex(CODE_AT), code_len=len(code), probe='P+960 VLGP, +964 n, '
                            '+965 seen, +980 text', syms={k: hex(v) for k, v in syms.items() if not k.startswith('.')})
    return out, code, syms, dis


def image(spec, stock):
    d = bytearray(stock)
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16) - BASE
            n = bytes.fromhex(e['new'])
            d[a:a + len(n)] = n
    return bytes(d)


def p_block(h_ok=True, vlgp=False):
    p = bytearray(1024)
    if h_ok:
        p[0:4] = struct.pack('<I', B3.MAGIC)
    if vlgp:
        struct.pack_into('<I', p, 960, VMAGIC)
        p[980:997] = b'V07 p03 m1 t0 rL\0'
    return p


def run_hook(img, fields, pm, h=1, p=None):
    msg = bytearray(0x200 + 400)
    for off, val, size in fields:
        struct.pack_into({1: '<B', 4: '<I'}[size], msg, off, val)
    rec = bytearray(68)
    rec[13] = 0xee
    rec[29] = pm
    st = bytearray(8)
    struct.pack_into('<H', st, 2, h)
    P = B3.POOL                                        # h = 1 -> P = pool
    regions = [VP.caller(HOOK, 0x20, 4), VP.img(img, 'fn', HOOK, FN_END, 'rx'),
               VP.img(img, 'code', CODE_AT, CODE_END, 'rx'),
               Region('stack', VP.STACK, bytes(0x1000), 'rw'),
               Region('msg', MSG, bytes(msg), 'r'), Region('rec', REC, bytes(rec), 'rw', True),
               Region('state', B3.STATE - 2, bytes(st), 'r')]
    if p is not None:
        regions.append(Region('P', P, bytes(p), 'rw', True))
    r, mem = VP.run(regions, {'pc': VP.CALLER, 'sp': VP.STACK + 0x800, 'a0': MSG, 'a1': REC + 13, 'a2': 0x2a2a2a2a})
    ok = (r['registers']['pc'] == VP.CALLER + 7 and r['registers']['sp'] == VP.STACK + 0x800
          and r['registers']['a2'] == 0x2a2a2a2a and r['registers']['a0'] == MSG
          and r['registers']['a1'] == REC + 13 and not r['fault'])
    return mem['rec'][13], ok, mem.get('P'), r


def f(t=0, m=254, a8=0, mov=1):
    return [(352, t, 1), (353, m, 1), (8, a8, 1), (332, mov, 4)]


CASES = [('movie + Muted -> log', f(), 3, 2), ('stills + Muted', f(mov=0), 3, 0), ('movie + Natural', f(), 2, 0),
         ('movie + COLOR', f(), 11, 0), ('movie + art 0x65', f(), 0x65, 0), ('A+332=2', f(mov=2), 3, 0),
         ('type1/254 (stock)', f(t=1, m=254), 3, 1), ('type1/255 A8=0', f(t=1, m=255), 2, 2),
         ('type1/255 A8=1', f(t=1, m=255, a8=1), 3, 0), ('type1/7 invalid', f(t=1, m=7), 3, 0)]


def check(img):
    res = []
    for name, fl, pm, want in CASES:
        for label, h, p in (('noP', 0, None), ('badmagic', 1, p_block(False)), ('P', 1, p_block())):
            v, ok, P, r = run_hook(img, fl, pm, h, p)
            good = ok and v == want
            if label == 'badmagic':
                good = good and P == bytes(p_block(False))
            res.append(dict(case=name, p=label, v=v, want=want, passed=bool(good)))
    # probe text: one Muted movie call, then a COLOR stills call (snapshot must stick), counter 2
    p = p_block()
    _, ok1, p, _ = run_hook(img, f(), 3, 1, p)
    t1 = p[980:997]
    _, ok2, p, _ = run_hook(img, f(mov=0), 11, 1, bytearray(p))
    t2 = p[980:997]
    text_ok = (ok1 and ok2 and t1 == b'V01 p03 m1 t0 rL\0' and t2 == b'V02 p03 m1 t0 rL\0'
               and struct.unpack_from('<I', p, 960)[0] == VMAGIC and p[965] == 1 and p[964] == 2
               and p[:960] == bytes(p_block()[:960]) and p[1000:] == bytes(24))
    res.append(dict(case='T text Muted then COLOR', t1=t1.decode('latin1'), t2=t2.decode('latin1'), passed=bool(text_ok)))
    p = p_block()
    _, ok3, p, _ = run_hook(img, f(mov=0, t=1, m=7), 0x65, 1, p)   # no trigger call yet: last call shown
    t3 = p[980:997]
    res.append(dict(case='T text art stills type1', t3=t3.decode('latin1'),
                    passed=bool(ok3 and t3 == b'V01 p?1 m0 t1 rS\0' and p[965] == 0)))
    return res


def run_txt(img, syms, h, p, ex_t_other):
    st = bytearray(8)
    struct.pack_into('<H', st, 2, h)
    caller = Region('caller', VP.CALLER, b'\xfc\xff' + struct.pack('<i', syms['vlog_txt'] - VP.CALLER) + b'\xcb', 'rx')
    regions = [caller, VP.img(img, 'code', CODE_AT, CODE_END, 'rx'), Region('stack', VP.STACK, bytes(0x100), 'rw'),
               Region('state', B3.STATE - 2, bytes(st), 'r')]
    if p is not None:
        regions.append(Region('P', B3.POOL, bytes(p), 'r'))
    from penf_emulator import execute
    r = execute(regions, {'pc': VP.CALLER, 'sp': VP.STACK + 0x80, 'd3': 0x33, 'd1': 0x11, 'a3': 0x44}, VP.CALLER + 6,
                limit=2000)
    g = r['registers']
    return (not r['fault'] and g['pc'] == VP.CALLER + 6 and g['sp'] == VP.STACK + 0x80 and g['d3'] == 0x33
            and g['d1'] == 0x11 and g['a3'] == 0x44), g['a2']


def check_txt(img, syms, ex_t_other):
    res = []
    for name, h, p, want in (('noP', 0, None, ex_t_other), ('P no magic', 1, p_block(), ex_t_other),
                             ('P bad', 1, p_block(False, True), ex_t_other), ('P + VLGP', 1, p_block(True, True), B3.POOL + 980),
                             ('h misaligned', 2, None, ex_t_other)):
        ok, a2 = run_txt(img, syms, h, p, ex_t_other)
        res.append(dict(case='X ' + name, a2=hex(a2), passed=bool(ok and a2 == want)))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--trig-log', type=int, default=3)
    ap.add_argument('--write', action='store_true', help='rewrite SPEC in place')
    a = ap.parse_args()
    spec = json.loads(a.spec.read_text())
    stock = VP.main_image()
    out, code, syms, dis = apply(spec, stock, a.trig_log)
    img = image(out, stock)
    assert img[OLD_AT - BASE:OLD_AT - BASE + 48] == b'\xff' * 48
    ex_t_other = 0x601e3736
    res = check(img) + check_txt(img, syms, ex_t_other)
    for x in res:
        print(('PASS ' if x['passed'] else 'FAIL ') + json.dumps(x))
    ok = all(x['passed'] for x in res)
    print(f'code {len(code)} B at {CODE_AT:#x}; vlog_txt {syms["vlog_txt"]:#x}; edits {len(out["edits"])}; '
          f'{"ALL PASS" if ok else "FAIL"}')
    (Path(__file__).parent / 'routine_probe.lst').write_text(dis)
    if ok and a.write:
        a.spec.write_text(json.dumps(out, indent=1) + '\n')
        print('wrote', a.spec)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
