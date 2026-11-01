#!/usr/bin/env python3
"""E-P7 1.1 video log, option A (unhide hidden movie picture mode 2001 / optional 2000).

Offline. No camera. Never writes SD-update-named files. Emits patches/video_log/edits.json
(input for tools/build_package.py) and verifies natively in fishcu's MN103 runner.

Design (docs/VIDEO_LOG.md, "Option A design"):
  0x6030df3d is the ONLY writer of settings-record +925 (via rec68[13] -> 8-slot ring 0x62039f4c ->
  memcpy into rec980+912 at 0x6030cc4f). Stock: +925 = 1 if MovPicModeType(A+352)==1 && MovPicMode
  (A+353)==254, = 2 if ==255 && A+8==0, else 0. The E-P7 UI never sets A+352.
  Patch: the 5 bytes at 0x6030df3d (`mov 352,a2; add a0,a2`) become `jmp vlog_hook` (section-1 FF
  tail). vlog_hook returns 2 (1) when A+352==0, A+332==1 (movie) and the picture mode
  rec68[29] == --trig-log (--trig-flat); otherwise it replays the displaced instructions and
  rejoins the untouched stock body at 0x6030df42.

Verification (native code, stock vs patched):
  H  0x6030df3d with synthetic message/record over a case matrix: +925 changes ONLY in the
     intended case; stock precedence preserved; a2/sp/return intact.
  M  0x60316bc7 -> 0x60324d6b -> 0x60349297 (record +925 -> effect id) natively: 0/1/2 -> pm/2000/2001.
  G/L gamma selector 0x603ae354 and luma selector 0x603b039b for the resulting effect id.

  python3 -I patches/video_log/build_and_verify.py [--trig-log 3] [--trig-flat N]
"""
import argparse, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import ep7_video_log_probe as VP  # noqa: E402
from penf_emulator import Region  # noqa: E402

TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE = 0x60020020
HOOK, STOCK5 = 0x6030df3d, bytes.fromhex('266001f172')
FN_END = 0x6030df6c                      # after `retf [a2],4`
SYMS = dict(ep7_stock_body=0x6030df42, ep7_store_ret=0x6030df67)
CODE_AT, CODE_LIMIT = 0x60210c90, 0x60210cd0   # sec-1 FF tail (loads before sec 2); v0.2 guard ends 0x60210c80
MSG, REC, OUT = 0x1b000000, 0x1c000000, 0x1d000000


def assemble(trig_log, trig_flat):
    flat = '' if trig_flat is None else (f' cmp {trig_flat},d0\n bne stock\n mov 1,d0\n jmp ep7_store_ret')
    src = (Path(__file__).parent / 'video_log.s.in').read_text().replace('{flat_code}', flat)
    src = src.replace('{trig_log}', str(trig_log)).replace('{trig_flat}', str(trig_flat))
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in SYMS.items()], '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        return (t / 'p.bin').read_bytes(), src, dis


def patched_image(stock, code):
    d = bytearray(stock)
    o = HOOK - BASE
    assert d[o:o + 5] == STOCK5, 'stock hook bytes differ'
    t = CODE_AT - BASE
    assert set(d[t:t + len(code) + 16]) == {0xff}, 'tail not erased'
    jmp = b'\xdc' + struct.pack('<i', CODE_AT - HOOK)
    d[o:o + 5] = jmp
    d[t:t + len(code)] = code
    return bytes(d), jmp


# ---------------------------------------------------------------- H: derivation 0x6030df3d
def run_derive(img, msg_fields, pm, stills_pm=11):
    msg = bytearray(0x200 + 400)
    for off, val, size in msg_fields:
        struct.pack_into({1: '<B', 4: '<I'}[size], msg, off, val)
    msg[354] = pm                                      # v0.14: movie picture mode A+354 decides
    rec = bytearray(68)
    rec[13] = 0xee                                     # sentinel: must be overwritten
    rec[29] = stills_pm                                # stills picture mode (property 0x9481): ignored
    regions = [VP.caller(HOOK, 0x20, 4),               # same form as stock caller 0x6032641f
               VP.img(img, 'fn', HOOK, FN_END, 'rx'),
               VP.img(img, 'tail', CODE_AT, CODE_LIMIT, 'rx'),
               Region('stack', VP.STACK, bytes(0x1000), 'rw'),
               Region('msg', MSG, bytes(msg), 'rw'), Region('rec', REC, bytes(rec), 'rw', True)]
    r, mem = VP.run(regions, {'pc': VP.CALLER, 'sp': VP.STACK + 0x800, 'a0': MSG, 'a1': REC + 13, 'a2': 0x2a2a2a2a})
    ok = (r['registers']['pc'] == VP.CALLER + 7 and r['registers']['sp'] == VP.STACK + 0x800
          and r['registers']['a2'] == 0x2a2a2a2a and not r['fault'])
    return mem['rec'][13], ok, r


def check_derive(stock, patched, trig_log, trig_flat):
    T, M, P = (352, 1), (353, 1), (332, 4)      # (offset, size)
    def f(t=0, m=254, a8=0, mov=1):
        return [(352, t, 1), (353, m, 1), (8, a8, 1), (332, mov, 4)]
    cases = [  # name, fields, pm, expected stock, expected patched (pm = movie picture mode A+354; stills pm 11)
        ('movie + trigger pm -> log', f(mov=1), trig_log, 0, 2),
        ('movie pm COLOR, stills pm = trigger (v0.14: not log)', f(mov=1), 11, 0, 0),
        ('stills (A+332=0) + trigger pm', f(mov=0), trig_log, 0, 0),
        ('movie + Natural(2)', f(), 2, 0, 0),
        ('movie + COLOR(11)', f(), 11, 0, 0),
        ('movie + MONO(12)', f(), 12, 0, 0),
        ('movie + art filter pm 0x65', f(), 0x65, 0, 0),
        ('A+332=2 (not 1) + trigger', f(mov=2), trig_log, 0, 0),
        ('stock type1/254 + trigger (stock wins)', f(t=1, m=254), trig_log, 1, 1),
        ('stock type1/255,A8=0', f(t=1, m=255), 2, 2, 2),
        ('stock type1/255,A8=1 + trigger', f(t=1, m=255, a8=1), trig_log, 0, 0),
        ('stock type1/7 (invalid)', f(t=1, m=7), trig_log, 0, 0),
    ]
    if trig_flat is not None:
        cases.insert(1, ('movie + flat trigger pm -> flat', f(), trig_flat, 0, 1))
    res = []
    for name, fields, pm, es, ep in cases:
        sp_ = trig_log if 'stills pm = trigger' in name else 11
        vs, oks, _ = run_derive(stock, fields, pm, sp_)
        vp, okp, _ = run_derive(patched, fields, pm, sp_)
        good = oks and okp and (vs, vp) == (es, ep)
        res.append(dict(case=name, pm=pm, stock=vs, patched=vp, expected=[es, ep], passed=bool(good)))
    return dict(check='H 0x6030df3d (+925 source) stock vs patched', passed=all(x['passed'] for x in res), cases=res)


# ---------------------------------------------------------------- M: record +925 -> effect id
def run_record_to_effect(img, v925, pm=2):
    rec = bytearray(980)
    rec[817] = 0                     # != 143 (special case)
    rec[292 + 2] = pm                # movpic block copy: picture mode (A+354)
    rec[292 + 3] = 0
    rec[925] = v925
    stack = bytearray(0x1000)
    struct.pack_into('<I', stack, 0x804, OUT)      # caller (4,sp) = output pointer, as at 0x60311641
    regions = [VP.caller(0x60316bc7, 0xb0, 24),     # stock: call 0x60316bc7,[d2,a2,a3],24
               VP.img(img, 'f1', 0x60316bc7, 0x60316c4d, 'rx'), VP.img(img, 'f2', 0x60324d6b, 0x60324dc1, 'rx'),
               VP.img(img, 'map', 0x60349297, 0x603494d7, 'rx'),
               VP.img(img, 'tbl', 0x604f8a78 - 0x1000, 0x604f8a78),
               Region('memset', 0x4700115e, bytes.fromhex('dea008'), 'rx'),   # retf [d2,a2],8 (8 B fully rewritten after)
               Region('stack', VP.STACK, bytes(stack), 'rw'),
               Region('rec', REC, bytes(rec), 'rw'), Region('out', OUT, bytes(8), 'rw', True)]
    r, mem = VP.run(regions, {'pc': VP.CALLER, 'sp': VP.STACK + 0x800, 'a0': REC + 292, 'a1': REC, 'd0': 0, 'd1': 0})
    o = mem['out']
    eid = (o[0] << 24) | (o[1] << 16) | struct.unpack_from('<H', o, 2)[0]
    return eid, r['registers']['pc'] == VP.CALLER + 7 and not r['fault']


def check_chain(img):
    res = []
    for v, want in ((0, 2), (1, 2000), (2, 2001)):
        eid, ok = run_record_to_effect(img, v)
        g = gamma_for(img, eid)
        l = luma_for(img, eid)
        exp_g = {2: VP.GAMMA_ROW0, 2000: VP.GAMMA_LOG2000, 2001: VP.GAMMA_LOG2001}[want]
        good = ok and eid == want and g in ((exp_g,) if want != 2 else (VP.GAMMA_ROW0, VP.GAMMA_ROW0_FLAG)) \
            and (want == 2 or l == VP.LUM_NORMAL)
        res.append(dict(rec925=v, effect_id=eid, gamma=hex(g), luma=hex(l), passed=bool(good)))
    return dict(check='M/G/L +925 -> 0x60316bc7/0x60324d6b/0x60349297 -> gamma/luma selectors',
                passed=all(x['passed'] for x in res), cases=res)


def gamma_for(img, eid):
    regions = [VP.caller(0x603ae354, 0xf0, 28), Region('stack', VP.STACK, bytes(0x1000), 'rw'),
               Region('req', VP.REQ, VP.request(eid), 'rw'), Region('out', VP.OUTS, bytes(16), 'rw', True)] + VP.gamma_regions(img)
    r, mem = VP.run(regions, {'pc': VP.CALLER, 'sp': VP.STACK + 0x800, 'a0': VP.REQ, 'd0': VP.OUTS, 'd1': VP.OUTS + 4, 'a1': VP.OUTS + 8})
    p = struct.unpack_from('<3I', mem['out'])
    return p[0] if len(set(p)) == 1 else -1


def luma_for(img, eid, contrast=2):
    regions = [VP.caller(0x603b039b, 0xf0, 24), VP.img(img, 'lsel', 0x603b039b, 0x603b07f7, 'rx'),
               VP.img(img, 'helpers', 0x603b55e3, 0x603b5675, 'rx'), VP.img(img, 'switch', 0x60532738, 0x60532b38),
               VP.img(img, 'ctab', 0x60500db0, 0x60500db6), Region('stack', VP.STACK, bytes(0x1000), 'rw'),
               Region('req', VP.REQ, VP.request(eid, contrast=contrast), 'rw'), Region('flag', VP.OUTS, bytes(4), 'rw', True)]
    r, _ = VP.run(regions, {'pc': VP.CALLER, 'sp': VP.STACK + 0x800, 'a0': VP.REQ, 'a1': VP.OUTS})
    return r['registers']['a0']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trig-log', type=int, default=3, help='hw picture mode that selects id 2001 in movie (default 3 = Muted, inferred)')
    ap.add_argument('--trig-flat', type=int, default=None, help='optional hw picture mode that selects id 2000')
    a = ap.parse_args()
    assert 0 <= a.trig_log < 128 and (a.trig_flat is None or (0 <= a.trig_flat < 128 and a.trig_flat != a.trig_log))
    stock = VP.main_image()
    code, src, dis = assemble(a.trig_log, a.trig_flat)
    if CODE_AT + len(code) > CODE_LIMIT:
        raise SystemExit('code too large for claimed range')
    patched, jmp = patched_image(stock, code)
    checks = [check_derive(stock, patched, a.trig_log, a.trig_flat), check_chain(stock), check_chain(patched)]
    for c in checks:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['check'])
        for k in c['cases']:
            print('     ', k)
    tail = stock[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    edits = [dict(kind='0x100', addr=hex(HOOK), expect=STOCK5.hex(), new=jmp.hex(),
                  why='movie-picture-mode derivation entry: mov 352,a2; add a0,a2 -> jmp vlog_hook'),
             dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
                  why=f'vlog_hook ({len(code)} B, section-1 FF tail): movie && pm=={a.trig_log} -> +925=2 (id 2001)'
                      + ('' if a.trig_flat is None else f'; pm=={a.trig_flat} -> +925=1 (id 2000)'))]
    out = Path(__file__).parent
    spec = dict(components=['0x100'], patch='video_log_A', trig_log=a.trig_log, trig_flat=a.trig_flat,
                code_at=hex(CODE_AT), code_len=len(code), edits=edits)
    (out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (out / 'routine.lst').write_text(dis)
    (out / 'verify.json').write_text(json.dumps(checks, indent=1) + '\n')
    print(f'code {len(code)} B at {CODE_AT:#x}..{CODE_AT + len(code):#x}; wrote {out / "edits.json"}')
    sys.exit(0 if all(c['passed'] for c in checks) else 1)


if __name__ == '__main__':
    main()
