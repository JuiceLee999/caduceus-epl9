#!/usr/bin/env python3
"""E-P7 1.1 video log: v0.14 fix (trigger = movie picture mode A+354) + probe + LOGDBG.TXT dump.

Sources: video_log_probe.s.in (vlog_hook + vlog_txt, dead EVF step-8 R/G/B 0x601e203c..0x601e233c; refs: step-table
words 0x601e3d00/04/08 only; two unaligned hits 0x6002084b/0x606d9029 are call instructions), vlog_dump.s.in (dead EVF step-7 R/G/B 0x601e233c..0x601e263c; refs: step-table words
0x601e3cf0/f4/f8 only). Edits applied to a merged spec (idempotent):
  0x6030df3d  jmp vlog_hook (the old 0x60210c90 stub edit is dropped -> FF)
  0x601e323c  look_extras blob: `mov ex_t_other,a2` at 0x601e3551 -> `calls vlog_txt` (label on Extras 6-12)
  0x605b7400  loader blob: sd_back 0x605b7420 `jmp ed_trig` -> `jmp vlog_dump` (which ends in `jmp ed_trig`)

  python3 -I patches/video_log/build_probe.py SPEC [--write]
Checks (emulator, code from the merged image): D decision matrix vs stock (movie/stills x Muted/COLOR/MONO/Natural,
stock MovPicMode cases, the fix case movie pm 3 with 0x9481 pm 17, and its converse) with and without P;
T probe ring + label; X vlog_txt; W dump: file text, missing card (fopen 0), no pending, not a half-press,
registers/sp intact at ed_trig.
"""
import argparse, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
sys.path.insert(0, str(ROOT / 'patches/sd_bundles_v3'))
import ep7_video_log_probe as VP  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402
import build as B3  # noqa: E402  (sd_bundles_v3: STATE, POOL, LIM, MAGIC, EV_PRESS)

TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE = 0x60020020
HOOK, STOCK5 = 0x6030df3d, bytes.fromhex('266001f172')
FN_END = 0x6030df6c
OLD_AT = 0x60210c90
CODE_AT, CODE_END = 0x601e203c, 0x601e233c
DUMP_AT, DUMP_END = 0x601e233c, 0x601e263c
EX_BLOB, EX_MOV, EX_T_OTHER = 0x601e323c, 0x601e3551, 0x601e3736
LD_BLOB, SD_BACK, ED_TRIG = 0x605b7400, 0x605b7420, 0x605b7340
LIB = dict(ep7_malloc=0x60022782, ep7_free=0x600227b4, ep7_fopen=0x60634fbc, ep7_fclose=0x60634fc5,
           ep7_fwrite=0x60635041, ep7_ed_trig=ED_TRIG, ep7_stock_body=0x6030df42, ep7_store_ret=0x6030df67)
VMAGIC = struct.unpack('<I', b'VLGP')[0]
W = [0x56] + [struct.unpack('<I', s)[0] for s in (b'xx/x', b'x mx', b'tx x')]
MSG, REC = 0x1b000000, 0x1c000000


def asm(src, at, syms=LIB):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in syms.items()], '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        syms = {l.split()[2]: int(l.split()[0], 16) for l in nm.splitlines() if len(l.split()) == 3}
        return (t / 'p.bin').read_bytes(), syms, dis


def source(name, trig):
    sub = dict(trig_log=trig, state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL), bmagic=hex(B3.MAGIC),
               vmagic=hex(VMAGIC), w0=hex(W[0]), w1=hex(W[1]), w2=hex(W[2]), w3=hex(W[3]), ex_t_other=hex(EX_T_OTHER),
               ev_press=hex(B3.EV_PRESS))
    src = (Path(__file__).parent / name).read_text()
    for k, v in sub.items():
        src = src.replace('{' + k + '}', str(v))
    return src


BQ = {}                                           # ep7_bq_gate / ep7_bq_dump (patches/bloom --blur-probe), from the spec


def apply(spec, stock, trig):
    bq = spec['bloom']['blur_probe']['symbols']
    BQ.update(ep7_bq_gate=int(bq['bq_gate'], 16), ep7_bq_dump=int(bq['bq_dump'], 16))
    edits = [e for e in spec['edits'] if e['addr'] not in (hex(HOOK), hex(OLD_AT), hex(CODE_AT), hex(DUMP_AT))]
    code, syms, dis = asm(source('video_log_probe.s.in', trig), CODE_AT)
    dump, dsyms, ddis = asm(source('vlog_dump.s.in', trig), DUMP_AT, dict(LIB, **BQ))
    assert syms['vlog_hook'] == CODE_AT and CODE_AT + len(code) <= CODE_END, hex(CODE_AT + len(code))
    assert dsyms['vlog_dump'] == DUMP_AT and DUMP_AT + len(dump) <= DUMP_END, hex(DUMP_AT + len(dump))
    ex = next(e for e in edits if e['addr'] == hex(EX_BLOB))
    blob = bytearray.fromhex(ex['new'])
    o = EX_MOV - EX_BLOB
    assert blob[EX_T_OTHER - EX_BLOB:EX_T_OTHER - EX_BLOB + 16] == b'Extras: 1-5 only'
    assert blob[o:o + 6] == b'\xfc\xde' + struct.pack('<I', EX_T_OTHER) or blob[o:o + 2] == b'\xfc\xff'
    blob[o:o + 6] = b'\xfc\xff' + struct.pack('<i', syms['vlog_txt'] - EX_MOV)
    why = ex['why'].split(' + video_log probe')[0]
    edits[edits.index(ex)] = dict(ex, new=blob.hex(), why=why + ' + video_log probe: Extras 6-12 -> calls vlog_txt')
    ld = next(e for e in edits if e['addr'] == hex(LD_BLOB))
    lb = bytearray.fromhex(ld['new'])
    o = SD_BACK - LD_BLOB
    cur = LD_BLOB + o + struct.unpack_from('<i', lb, o + 1)[0]
    assert lb[o] == 0xdc and cur in (ED_TRIG, DUMP_AT), hex(cur)
    lb[o + 1:o + 5] = struct.pack('<i', DUMP_AT - SD_BACK)
    why = ld['why'].split(' + video_log: sd_back')[0]
    edits[edits.index(ld)] = dict(ld, new=lb.hex(), why=why + ' + video_log: sd_back -> vlog_dump (-> ed_trig)')
    edits += [dict(kind='0x100', addr=hex(HOOK), expect=STOCK5.hex(),
                   new=(b'\xdc' + struct.pack('<i', CODE_AT - HOOK)).hex(),
                   why='movie-picture-mode derivation entry: mov 352,a2; add a0,a2 -> jmp vlog_hook'),
              dict(kind='0x100', addr=hex(CODE_AT), expect=stock[CODE_AT - BASE:CODE_AT - BASE + len(code)].hex(),
                   new=code.hex(), why=f'vlog_hook (movie && A+354 movie pm=={trig} -> +925=2) + probe ring/label in '
                   f'heap P + vlog_txt ({len(code)} B, dead EVF step-8 R/G/B)'),
              dict(kind='0x100', addr=hex(DUMP_AT), expect=stock[DUMP_AT - BASE:DUMP_AT - BASE + len(dump)].hex(),
                   new=dump.hex(), why=f'vlog_dump: half-press after a movie call -> EP7MOD/LOGDBG.TXT ({len(dump)} B, '
                   'dead EVF step-7 R/G/B)')]
    out = dict(spec, edits=edits)
    out['video_log'] = dict(trig_log=trig, trigger='A+354 (movie picture mode)', code_at=hex(CODE_AT),
                            code_len=len(code), dump_at=hex(DUMP_AT), dump_len=len(dump),
                            syms={k: hex(v) for k, v in {**syms, **dsyms}.items() if not k.startswith(('.', 'L'))})
    return out, syms, dsyms, dis + ddis


def image(spec, stock):
    d = bytearray(stock)
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16) - BASE
            n = bytes.fromhex(e['new'])
            d[a:a + len(n)] = n
    return bytes(d)


def p_block(magic=True, vlgp=False):
    p = bytearray(1024)
    if magic:
        p[0:4] = struct.pack('<I', B3.MAGIC)
    if vlgp:
        struct.pack_into('<I', p, 960, VMAGIC)
        p[980:997] = b'V07 03/17 m1t0 L\0'
    return p


def run_hook(img, fields, pm354, pm29, h=1, p=None, old=0):
    msg = bytearray(0x200 + 400)
    for off, val, size in fields:
        struct.pack_into({1: '<B', 4: '<I'}[size], msg, off, val)
    msg[354] = pm354
    rec = bytearray(68)
    rec[13] = old
    rec[29] = pm29
    st = bytearray(8)
    struct.pack_into('<H', st, 2, h)
    regions = [VP.caller(HOOK, 0x20, 4), VP.img(img, 'fn', HOOK, FN_END, 'rx'),
               VP.img(img, 'code', CODE_AT, CODE_END, 'rx'), Region('stack', VP.STACK, bytes(0x1000), 'rw'),
               Region('msg', MSG, bytes(msg), 'r'), Region('rec', REC, bytes(rec), 'rw', True),
               Region('state', B3.STATE - 2, bytes(st), 'r')]
    if p is not None:
        regions.append(Region('P', B3.POOL, bytes(p), 'rw', True))
    regs = {'pc': VP.CALLER, 'sp': VP.STACK + 0x800, 'a0': MSG, 'a1': REC + 13, 'a2': 0x2a2a2a2a,
            'd2': 0x22, 'd3': 0x33, 'a3': 0x44}
    r, mem = VP.run(regions, regs)
    g = r['registers']
    ok = (g['pc'] == VP.CALLER + 7 and g['sp'] == VP.STACK + 0x800 and g['a2'] == 0x2a2a2a2a and g['a0'] == MSG
          and g['a1'] == REC + 13 and g['d2'] == 0x22 and g['d3'] == 0x33 and g['a3'] == 0x44 and not r['fault'])
    return mem['rec'][13], ok, mem.get('P')


def f(t=0, m=254, a8=0, mov=1):
    return [(352, t, 1), (353, m, 1), (8, a8, 1), (332, mov, 4)]


# name, fields, A+354, rec68[29], expected stock-image value, expected patched value
CASES = [('movie Muted', f(), 3, 3, 0, 2), ('FIX movie Muted, stills COLOR4 (0x9481 = 17)', f(), 3, 17, 0, 2),
         ('movie COLOR4, stills Muted', f(), 17, 3, 0, 0), ('stills Muted', f(mov=0), 3, 3, 0, 0),
         ('movie COLOR', f(), 11, 11, 0, 0), ('movie MONO', f(), 12, 12, 0, 0), ('stills COLOR', f(mov=0), 11, 11, 0, 0),
         ('stills MONO', f(mov=0), 12, 12, 0, 0), ('movie Natural', f(), 2, 2, 0, 0), ('A+332=2 Muted', f(mov=2), 3, 3, 0, 0),
         ('stock type1/254', f(t=1, m=254), 3, 3, 1, 1), ('stock type1/255', f(t=1, m=255), 2, 2, 2, 2),
         ('stock type1/255 A8=1', f(t=1, m=255, a8=1), 3, 3, 0, 0), ('stock type1/7', f(t=1, m=7), 3, 3, 0, 0)]


def check(img, stock):
    res = []
    for name, fl, p354, p29, es, ep in CASES:
        vs, oks, _ = run_hook(stock, fl, p354, p29) if False else (None, True, None)
        for label, h, p in (('noP', 0, None), ('P no magic', 1, p_block(False)), ('P', 1, p_block())):
            v, ok, P = run_hook(img, fl, p354, p29, h, p)
            good = ok and v == ep and (label != 'P no magic' or P == bytes(p_block(False)))
            res.append(dict(case='D ' + name, p=label, v=v, want=ep, passed=bool(good)))
    # T: Muted movie call x2 (one ring record), then a COLOR stills call (new record, label sticks)
    p = p_block()
    _, ok1, p = run_hook(img, f(), 3, 17, 1, p)
    _, ok2, p = run_hook(img, f(), 3, 17, 1, bytearray(p), old=2)
    _, ok3, p = run_hook(img, f(), 3, 17, 1, bytearray(p), old=2)
    _, ok4, p = run_hook(img, f(mov=0), 11, 11, 1, bytearray(p), old=2)
    rec = lambda i: p[704 + 12 * i:716 + 12 * i]
    good = (ok1 and ok2 and ok3 and ok4 and p[980:997] == b'V04 03/17 m1t0 L\0' and p[966] == 3
            and rec(1)[:10] == bytes([0, 254, 3, 17, 0, 1, 0, 2, 1, 0]) and rec(2)[:9] == bytes([0, 254, 3, 17, 0, 1, 2, 2, 3])
            and rec(3)[:9] == bytes([0, 254, 11, 11, 0, 0, 2, 0, 4]) and p[967] == 1 and p[965] == 1
            and struct.unpack_from('<I', p, 960)[0] == VMAGIC and p[:704] == bytes(p_block()[:704]) and p[1000:] == bytes(24))
    res.append(dict(case='T ring + label', label=p[980:996].decode('latin1'), idx=p[966],
                    recs=[rec(i).hex() for i in range(1, 4)], passed=bool(good)))
    return res, p


def run_txt(img, syms, h, p):
    st = bytearray(8)
    struct.pack_into('<H', st, 2, h)
    caller = Region('caller', VP.CALLER, b'\xfc\xff' + struct.pack('<i', syms['vlog_txt'] - VP.CALLER) + b'\xcb', 'rx')
    regions = [caller, VP.img(img, 'code', CODE_AT, CODE_END, 'rx'), Region('stack', VP.STACK, bytes(0x100), 'rw'),
               Region('state', B3.STATE - 2, bytes(st), 'r')]
    if p is not None:
        regions.append(Region('P', B3.POOL, bytes(p), 'r'))
    r = execute(regions, {'pc': VP.CALLER, 'sp': VP.STACK + 0x80, 'd3': 0x33, 'd1': 0x11, 'a3': 0x44}, VP.CALLER + 6,
                limit=2000)
    g = r['registers']
    return (not r['fault'] and g['pc'] == VP.CALLER + 6 and g['sp'] == VP.STACK + 0x80 and g['d3'] == 0x33
            and g['d1'] == 0x11 and g['a3'] == 0x44), g['a2']


def check_txt(img, syms):
    res = []
    for name, h, p, want in (('noP', 0, None, EX_T_OTHER), ('P no VLGP', 1, p_block(), EX_T_OTHER),
                             ('VLGP no P magic', 1, p_block(False, True), EX_T_OTHER),
                             ('P + VLGP', 1, p_block(True, True), B3.POOL + 980), ('h misaligned', 2, None, EX_T_OTHER)):
        ok, a2 = run_txt(img, syms, h, p)
        res.append(dict(case='X ' + name, a2=hex(a2), passed=bool(ok and a2 == want)))
    return res


BUF, HANDLE, SPY = 0x1e000000, 0x1f000000, 0x1d000000


def stubs(handle):
    out = []
    for name, src in (('malloc', f' mov {BUF:#x},a0\n ret [],4\n'), ('free', f' mov a0,({SPY + 8:#x})\n ret [],4\n'),
                      ('fopen', f' mov {handle:#x},a0\n ret [],4\n'),
                      ('fclose', f' mov a0,({SPY + 12:#x})\n clr d0\n ret [d2,a2,a3],16\n'),
                      ('fwrite', f' mov a0,({SPY:#x})\n mov d1,({SPY + 4:#x})\n mov a1,({SPY + 16:#x})\n mov d1,d0\n'
                                 ' ret [d2,d3,a2,a3],24\n')):
        at = LIB['ep7_' + name]
        code, _, _ = asm(' .am33_2\n .text\n .global _start\n_start:\n' + src, at, {})
        out.append(Region('s_' + name, at, code, 'rx'))
    return out


def run_dump(img, p, ev=None, handle=HANDLE, h=1):
    st = bytearray(8)
    struct.pack_into('<H', st, 2, h)
    stack = bytearray(0x400)
    struct.pack_into('<I', stack, 0x200 + 16, B3.EV_PRESS if ev is None else ev)
    regions = [VP.img(img, 'dump', DUMP_AT, DUMP_END, 'rx'), VP.img(img, 'bq', 0x601e1d3c, 0x601e203c, 'rx'),
               Region('stack', VP.STACK, bytes(stack), 'rw'),
               Region('state', B3.STATE - 2, bytes(st), 'r'), Region('P', B3.POOL, bytes(p), 'rw', True),
               Region('buf', BUF, bytes(512), 'rw', True), Region('spy', SPY, bytes(32), 'rw', True),
               Region('trig', ED_TRIG, b'\xcb', 'rx')] + stubs(handle)
    regs = {'pc': DUMP_AT, 'sp': VP.STACK + 0x200, 'd0': 0x10, 'd1': 0x11, 'd2': 0x22, 'd3': 0x33, 'a0': 0x40,
            'a1': 0x41, 'a2': 0x42, 'a3': 0x43}
    r = execute(regions, regs, ED_TRIG, limit=200000)
    mem = {m['name']: bytes.fromhex(m['hex']) for m in r['memory']}
    g = r['registers']
    ok = not r['fault'] and g['pc'] == ED_TRIG and all(g[k] == v for k, v in regs.items() if k != 'pc')
    return ok, mem


def check_dump(img, p):
    res = []
    ok, mem = run_dump(img, p)
    spy = mem['spy']
    n = struct.unpack_from('<I', spy, 4)[0]
    text = mem['buf'][:n].decode('latin1')
    lines = text.split('\r\n')
    good = (ok and struct.unpack_from('<I', spy, 0)[0] == BUF and struct.unpack_from('<I', spy, 16)[0] == HANDLE
            and struct.unpack_from('<I', spy, 12)[0] == HANDLE and struct.unpack_from('<I', spy, 8)[0] == BUF
            and lines[0] == 'V04 03/17 m1t0 L' and len(lines) == 10 and lines[9] == ''
            and lines[2] == ' 1: 00 FE 03 11 00 01 00 02 01 00 00 00' and lines[4].startswith('*3:')
            and mem['P'][967] == 0)
    res.append(dict(case='W dump writes LOGDBG.TXT', n=n, head=lines[:3], passed=bool(good)))
    ok, mem = run_dump(img, p, handle=0)
    res.append(dict(case='W missing card (fopen 0)', passed=bool(ok and mem['spy'] == bytes(8) + struct.pack('<I', BUF)
                                                                 + bytes(20) and mem['P'][967] == 0)))
    q = bytearray(p)
    q[967] = 0
    ok, mem = run_dump(img, q)
    res.append(dict(case='W nothing pending', passed=bool(ok and mem['spy'] == bytes(32) and mem['P'] == bytes(q))))
    ok, mem = run_dump(img, p, ev=B3.EV_PRESS + 1)
    res.append(dict(case='W not a half-press', passed=bool(ok and mem['spy'] == bytes(32) and mem['P'] == bytes(p))))
    ok, mem = run_dump(img, p, h=0)
    res.append(dict(case='W no P', passed=bool(ok and mem['spy'] == bytes(32) and mem['P'] == bytes(p))))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--trig-log', type=int, default=3)
    ap.add_argument('--write', action='store_true', help='rewrite SPEC in place')
    a = ap.parse_args()
    spec = json.loads(a.spec.read_text())
    stock = VP.main_image()
    out, syms, dsyms, dis = apply(spec, stock, a.trig_log)
    img = image(out, stock)
    assert img[OLD_AT - BASE:OLD_AT - BASE + 48] == b'\xff' * 48
    r1, p = check(img, stock)
    res = r1 + check_txt(img, syms) + check_dump(img, p)
    for x in res:
        print(('PASS ' if x['passed'] else 'FAIL ') + json.dumps(x))
    ok = all(x['passed'] for x in res)
    print(f'hook {syms["code_end"] - CODE_AT} B, dump {dsyms["code_end"] - DUMP_AT} B; edits {len(out["edits"])}; '
          f'{"ALL PASS" if ok else "FAIL"}')
    (Path(__file__).parent / 'routine_probe.lst').write_text(dis)
    if ok and a.write:
        a.spec.write_text(json.dumps(out, indent=1) + '\n')
        print('wrote', a.spec)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
