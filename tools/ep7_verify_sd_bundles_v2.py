#!/usr/bin/env python3
"""Emulator verification of a BUILT SD look loader v2 package (offline; emulator only; no camera).

Takes an edits spec with the sd_bundles_v2 patch (patches/sd_bundles_v2/build.py) merged with the v0.2
bundles table (tools/merge_specs.py). Builds the package in memory (tools/build_package.build()), decodes
the patched and the restore (= stock) main payloads, and runs code from THOSE payloads in the fishcu
emulator. Every run starts at the REAL UPSTREAM EVENT, not at the hook:

  caller    `call 0x602c7f5a,[d2,d3,a2,a3],88` (the exact instruction of the sole caller 0x60770224,
            HLS_EVENT's get-event method) -> the REAL appevent get function: its real prologue runs;
            at 0x602c7f6d (blocking queue receive + pre-filter) an injector puts ONE event word pair in
            (16,sp)/(20,sp) as the receive would and continues at 0x602c8045; everything after that is
            REAL stock code: the low16 0x100/0x101 gate, the hook site 0x602c805f, the real TRIG tracker
            0x602c818c with its real state byte 0x61f9f1c8, key-class handling, 0x602c815c, 0x602c88a6,
            0x602c899c and the function's own `ret [d2,d3,a2,a3],88`. If the event is swallowed the real
            code loops back to 0x602c7f6d; the injector then records that and returns with the same ret.
  loader    the section-3 tail 0x605b7400..0x605b7800 (rwx: sd_state is written).
  get_tid   REAL 0x600317ac (reads (0x8050), 0x8ff00004 -> TCB chain; fixture kernel memory).
  guards    section bits 0xa272e420, HLS_EVENT tid 0x622cbcc0, media status 0x61fa8fb8/c0/c8/d0.
Stubs (ours, gas): the v1 file-service stubs (malloc/free/fopen/fclose/fread/ftell/fseek with an
in-memory file, hostile register/arg clobbering, call log) plus logging stubs for the three appevent
leaf callees outside the window (0x602fcb69 key filter -> 1, 0x602c96f3 -> 0, 0x602e9f1e).
The same fixture runs on the stock payload as the reference.

  S  static: site 0x602c805f = jmp sd_hook (stock: call16 0x602c818c), loader bytes == spec, FF to the
     section end, service call frames == the dominant frame of all stock call sites (incl. get_tid and
     the replayed tracker call), no v1 edits in the spec.
  P  call path (byte-checked): USRSTART2 wait(6) -> 0x60767db2 -> 0x607688e3 -> 0x6076fd56 creates task
     "HLS_EVENT" (entry 0x6076fdb6) -> 0x6076fe04 loop -> 0x60770217 -> 0x602c7f5a (blocking receive,
     timeout -1, queue (0x60040ce8)) -> 0x602c805f; 0x602c7f5a has exactly one caller; mgr+172 = tid.
  E  every run, vs stock: no fault; returns to the caller; ALL registers (d0-d3, a0-a3, sp, pc, mdr, psw,
     lir, lar) equal; live stack equal; tracker state byte, 0xa26999xx, 0x6224xxxx equal; the event the
     dispatcher returns (d0) equal; swallowed/returned equal; leaf-stub calls and arguments equal.
  F  one half-press per fresh power-on with each of the v1 file cases (valid / reject / missing /
     I/O errors / malloc failure): exact table replacement iff valid, call sequence and arguments as
     specified, fclose exactly once, free iff malloc, heap outside the buffer untouched, loader region
     changes only at sd_state, sd_state 0 after the attempt; desktop check_file() agrees.
  Q  power-on sequences: boot windows (sections 8/9 not copied, HLS_EVENT not created, wrong task,
     non-task context, no medium mounted) -> zero file calls and the attempt is NOT consumed; then a
     press loads. Load once; missing file consumes the single attempt; release/trig2/repeat/non-shutter
     events never load; source-B press 0x02040100 (canonicalised by the real tracker) loads.
  M  mutations of the patched loader: each must make the core suite fail.

Usage: tools/ep7_verify_sd_bundles_v2.py SPEC.json [--json out.json] [--no-mutations]
"""
import argparse, importlib.util, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V1 = _load('ep7_verify_sd_bundles', ROOT / 'tools/ep7_verify_sd_bundles.py')   # stubs, file cases, helpers
S2 = _load('ep7_sd_bundles_v2_build', ROOT / 'patches/sd_bundles_v2/build.py')
SB, BIN = V1.SB, V1.BIN

TC, BASE = V1.TC, V1.BASE
STACK, SP0, STACK_FILL = V1.STACK, V1.SP0, V1.STACK_FILL
CTL, LOG, LOG_N, LOG_SZ = V1.CTL, V1.LOG, V1.LOG_N, V1.LOG_SZ
FILE_AT, HEAP, HEAP_LEN, HEAP_FILL, BUF, HANDLE = V1.FILE_AT, V1.HEAP, V1.HEAP_LEN, V1.HEAP_FILL, V1.BUF, V1.HANDLE
STUBS = 0x1c300000
INJ_PASS, INJ_EV, INJ_EV2, KF_RET = CTL + 0x60, CTL + 0x64, CTL + 0x68, CTL + 0x6c
CALLER = 0x18000000
KERN = 0x1c400000
TAB_LO, TAB_HI = V1.TAB_LO, V1.TAB_HI
CODE_LO, CODE_HI = 0x602c7f00, 0x602c8a00          # appevent get + tracker + helpers (real)
RECV_AT, POST_RECV = 0x602c7f6d, 0x602c8045        # receive/pre-filter (replaced by the injector) / resume
TID_LO, TID_HI = 0x600317ac, 0x600317f0
SEC_LO, SEC_HI = S2.CODE_AT - 0x400, 0x605b7800     # section-3 tail incl. guards (0x605b7400-0x400 = 0x605b7000)
ALL_REGS = V1.ALL_REGS
INIT = dict(V1.INIT, d2=0x22222222)
IDS = {**V1.IDS, 9: 'keyfilt', 10: 'c96f3', 11: 'e9f1e'}
LEAF = ('keyfilt', 'c96f3', 'e9f1e')
HLS = 0x0042                                         # fixture HLS_EVENT tid
PRESS, RELEASE, T2_PRESS, T2_RELEASE = 0x02000100, 0x02010100, 0x02000101, 0x02010101
B_PRESS, B_RELEASE = 0x02040100, 0x02050100

EXTRA_SRC = r"""
s_keyfilt:
 ENTER 9,8
 mov (CTL+0x6c),d0
 mov 0xbad0d100,d1
 mov 0xbad0a000,a0
 mov 0xbad0a100,a1
 LEAVE 8,1
 ret [d2],8
s_c96f3:
 ENTER 10,0
 clr d0
 LEAVE 0,0
 ret [],0
s_e9f1e:
 ENTER 11,76
 clr d0
 LEAVE 76,0
 ret [d2,d3,a2],76
s_inject:
 mov (CTL+0x60),d0
 cmp 0,d0
 bne 1f
 mov 1,d0
 mov d0,(CTL+0x60)
 mov (CTL+0x64),d0
 mov d0,(16,sp)
 mov (CTL+0x68),d0
 mov d0,(20,sp)
 jmp post_recv
1:
 mov 2,d0
 mov d0,(CTL+0x60)
 ret [d2,d3,a2,a3],88
"""
TRAMPS = dict(V1.TRAMPS)
TRAMPS.pop('log')
TRAMPS.update(keyfilt=0x602fcb69, c96f3=0x602c96f3, e9f1e=0x602e9f1e)


def assemble_stubs():
    src = V1.STUB_SRC.split('s_log:')[0] + EXTRA_SRC
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 's.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 's.o', t / 's.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(STUBS), '-e', '_start', f'--defsym=post_recv={POST_RECV:#x}', '-o', t / 's.elf', t / 's.o'],
                       check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 's.elf', t / 's.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 's.elf'], check=True,
                            capture_output=True, text=True).stdout
        syms = {n: int(a, 16) for a, ty, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3)}
        return (t / 's.bin').read_bytes(), {k: syms['s_' + k] for k in list(TRAMPS) + ['inject']}


STUB_BIN, STUB_SYMS = assemble_stubs()


def jmp_to(at, target):
    return b'\xdc' + struct.pack('<i', target - at)


def stub_regions():
    regs = [Region('stubs', STUBS, STUB_BIN, 'rx')]
    for k, a in TRAMPS.items():
        regs.append(Region('t_' + k, a, jmp_to(a, STUB_SYMS[k]), 'rx'))
    return regs


sl = V1.sl


# ------------------------------------------------------------------ fixture
class Env:
    """Power-on environment around one event."""
    def __init__(self, secbits=0x1ff, hls=HLS, cur=HLS, nontask=False, media=(0, 0xF000, 0, 0), keyfilt=1):
        self.secbits, self.hls, self.cur, self.nontask, self.media, self.keyfilt = secbits, hls, cur, nontask, media, keyfilt

    def gate_ok(self):
        return ((self.secbits & 0x1ff) == 0x1ff and not self.nontask and 0 < self.hls < 0x8000 and self.cur == self.hls
                and 0xF000 in self.media)


OK = Env()


def kern(env):
    """Kernel memory for the REAL get_tid 0x600317ac: (0x8050)=cpu 0; (0x8ff00004)->P;
    (P+28)->Q with Q[0]==0 and Q[1]!=1 (else -25 = not a task); (P+96)->R; (R)->S; (S+16) = tid."""
    k = bytearray(0x100)
    P, Q, R, S = KERN, KERN + 0x40, KERN + 0x80, KERN + 0xa0
    struct.pack_into('<I', k, 28, Q)
    struct.pack_into('<I', k, 96, R)
    k[0x40], k[0x41] = (1 if env.nontask else 0), 0
    struct.pack_into('<I', k, 0x80, S)
    struct.pack_into('<H', k, 0xa0 + 16, env.cur)
    return bytes(k), P


def ctl_block(case, ev, ev2, env):
    c = bytearray(V1.ctl_block(case))
    struct.pack_into('<4I', c, 0x60, 0, ev, ev2, env.keyfilt)
    return bytes(c)


def media_data(env):
    d = bytearray((0x11 * i) & 0xff for i in range(0x100))
    for w, v in zip(S2.MEDIA_STATUS, env.media):
        struct.pack_into('<I', d, w - 0x61fa8f00, v)
    return bytes(d)


def run(img, case, ev, env, *, code=None, table=None, trig_state=0, ev2=0x11223344, appram=None):
    getfn = bytearray(sl(img, CODE_LO, CODE_HI))
    getfn[RECV_AT - CODE_LO:RECV_AT - CODE_LO + 5] = jmp_to(RECV_AT, STUB_SYMS['inject'])   # instrumentation
    k, P = kern(env)
    sec = bytearray(code if code is not None else sl(img, SEC_LO, SEC_HI))
    tri = bytearray(0x10)
    tri[0x61f9f1c8 - 0x61f9f1c0] = trig_state
    regions = [Region('caller', CALLER, b'\xdd' + struct.pack('<i', S2.GET_FN - CALLER) + b'\xf0\x58\xcb', 'rx'),
               Region('getfn', CODE_LO, bytes(getfn), 'rx'),
               Region('loader', SEC_LO, bytes(sec), 'rwx', True),
               Region('get_tid', TID_LO, sl(img, TID_LO, TID_HI), 'rx'),
               Region('cpuid', 0x8050, bytes(4), 'r'),
               Region('tcbtab', 0x8ff00000, bytes(4) + struct.pack('<I', P) + bytes(8), 'r'),
               Region('kern', KERN, k, 'r'),
               Region('secbits', 0xa272e400, bytes(0x20) + struct.pack('<I', env.secbits) + bytes(0x1c), 'r'),
               Region('hls', 0x622cbc00, bytes(0xc0) + struct.pack('<H', env.hls & 0xffff) + bytes(0x3e), 'r'),
               Region('media', 0x61fa8f00, media_data(env), 'r'),
               Region('trig', 0x61f9f1c0, bytes(tri), 'rw', True),
               Region('appram', 0x6224b400, appram or bytes(0x2800), 'rw', True),
               Region('a2699', 0xa2699900, bytes(0x80), 'rw', True),
               Region('table', TAB_LO, bytes(table) if table is not None else sl(img, TAB_LO, TAB_HI), 'rw', True),
               Region('ctl', CTL, ctl_block(case, ev, ev2, env), 'rw', True),
               Region('heap', HEAP, V1.heap_init(case), 'rw', True),
               Region('stack', STACK, bytes([STACK_FILL]) * 0x2000, 'rw', True)] + stub_regions()
    if case.file:
        regions.append(Region('file', FILE_AT, bytes(case.file)))
    r = execute(regions, dict(INIT, pc=CALLER, sp=SP0), CALLER + 7, limit=3_000_000, timeout=120)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    ctl = m['ctl']
    n = (struct.unpack_from('<I', ctl, V1.C_LOGP)[0] - LOG) // LOG_SZ
    log = []
    for i in range(max(0, min(n, LOG_N))):
        v = struct.unpack_from('<11I', ctl, 0x100 + i * LOG_SZ)
        log.append(dict(fn=IDS.get(v[0], v[0]), d0=v[1], d1=v[2], a0=v[3], a1=v[4], sp=v[5], ret=v[6],
                        arg4=v[7], arg8=v[8], arg12=v[9], mdr=v[10]))
    stk = m['stack']
    lo = next((i for i, b in enumerate(stk) if b != STACK_FILL), len(stk))
    return dict(fault=r['fault'], regs={k: r['registers'][k] for k in ALL_REGS}, log=log, mem=m,
                inj=struct.unpack_from('<I', ctl, 0x60)[0], live=stk[SP0 - STACK:], frame=stk[SP0 - 88 - STACK:SP0 - STACK],
                depth=SP0 - STACK - lo)


# ------------------------------------------------------------------ independent models
def tracker(state, ev):
    """Python model of 0x602c818c (bit map / canonicalisation / no-change suppression / nibble shift)."""
    tab = {PRESS: (1, 1, None), RELEASE: (1, 0, None), T2_PRESS: (2, 1, None), T2_RELEASE: (2, 0, None),
           B_PRESS: (4, 1, PRESS), B_RELEASE: (4, 0, RELEASE), 0x02040101: (8, 1, T2_PRESS), 0x02050101: (8, 0, T2_RELEASE)}
    if ev not in tab:
        return state, ev
    bit, on, canon = tab[ev]
    s = (state | bit) if on else (state & ~bit & 0xff)
    if canon:
        ev = canon
    prev = ((s & 0xc0) >> 6) | ((s & 0x30) >> 4)
    cur = ((s & 0x0c) >> 2) | (s & 3)
    if prev ^ cur == 0:
        ev = 0
    s = ((s & 0x0f) << 4) | (s & 0x0f)
    return s, ev


def routed(ev):
    return (ev & 0xffff) in (0x100, 0x101)


def model(case, ev, env, state, trig_state):
    """-> (expected file calls, load?, new sd_state, new trig state)."""
    ts, canon = tracker(trig_state, ev) if routed(ev) else (trig_state, ev)
    if not routed(ev) or canon != PRESS or state == 0 or not env.gate_ok():
        return [], False, state, ts
    c = V1.Case(case.name, case.file, malloc_ok=case.malloc_ok, fopen_ok=case.fopen_ok, tell_fail=case.tell_fail,
                seek_end=case.seek_end, seek_set=case.seek_set, readmax=case.readmax, expect=case.expect)
    seq, load, _ = V1.model(c, 0xff)
    return seq, load, 0, ts


# ------------------------------------------------------------------ checks
FILE_OPS = V1.FILE_OPS


def check(case, ev, env, s, p, state_in, trig_in, table_in, code_in, code_len):
    probs = []
    seq, load, st_exp, ts_exp = model(case, ev, env, state_in, trig_in)
    if s['fault'] or p['fault']:
        return False, [f"fault stock={s['fault']} patched={p['fault']}"], None, None
    if p['regs']['pc'] != CALLER + 7 or s['regs']['pc'] != CALLER + 7:
        probs.append('did not return to the HLS_EVENT caller')
    d = [k for k in ALL_REGS if s['regs'][k] != p['regs'][k]]
    if d:
        probs.append(f'registers != stock: {d}')
    if s['live'] != p['live']:
        probs.append('live stack != stock')
    for k in ('trig', 'appram', 'a2699'):
        if s['mem'][k] != p['mem'][k]:
            probs.append(f'{k} memory != stock')
    if s['inj'] != p['inj']:
        probs.append(f"event swallowed/returned differs ({s['inj']}/{p['inj']})")
    if s['mem']['trig'][8] != ts_exp:
        probs.append(f"tracker state {s['mem']['trig'][8]:#x} != model {ts_exp:#x} (model wrong)")
    # d1/a0/a1 at the leaf entry are dead leftovers of the previous call (tracker in stock, our loader's
    # last service call when it ran): 0x602fcb69 writes d1 (mov 1,d1) and a0 (mov imm,a0) before reading
    # them. Compared: argument d0, sp, return address, the caller's stack words (4/8/12,sp).
    LK = ('fn', 'd0', 'sp', 'ret', 'arg4', 'arg8', 'arg12')
    sl_ = [{k: e[k] for k in LK} for e in s['log'] if e['fn'] in LEAF]
    pl_ = [{k: e[k] for k in LK} for e in p['log'] if e['fn'] in LEAF]
    if sl_ != pl_:
        probs.append('appevent leaf calls != stock')
    calls = [e for e in p['log'] if e['fn'] not in LEAF]
    if any(e['fn'] not in LEAF for e in s['log']):
        probs.append('stock run made a file-service call (fixture wrong)')
    if [e['fn'] for e in calls] != seq:
        probs.append(f"calls {[e['fn'] for e in calls]} != expected {seq}")
    for e in calls:
        if not S2.CODE_AT <= e['ret'] < S2.CODE_AT + code_len:
            probs.append(f"{e['fn']} returns to {e['ret']:#x}, outside the loader")
        if e['fn'] == 'malloc' and e['d0'] != SB.BUF_SIZE:
            probs.append(f"malloc({e['d0']})")
        if e['fn'] == 'fopen':
            o0, o1 = e['a0'] - SEC_LO, e['a1'] - SEC_LO
            path = bytes(code_in[o0:code_in.index(0, o0)]) if 0 <= o0 < len(code_in) else None
            mode = bytes(code_in[o1:code_in.index(0, o1)]) if 0 <= o1 < len(code_in) else None
            if (path, mode) != (SB.PATH.encode(), b'r'):
                probs.append(f'fopen({path}, {mode})')
        if e['fn'] in FILE_OPS and (e['a1'] if e['fn'] == 'fread' else e['a0']) != HANDLE:
            probs.append(f"{e['fn']} on a wrong handle")
        if e['fn'] == 'free' and e['a0'] != BUF:
            probs.append(f"free({e['a0']:#x})")
        if e['fn'] == 'fread' and (e['a0'], e['d0'], e['d1']) != (BUF, 1, SB.FILE_LEN):
            probs.append(f"fread(a0={e['a0']:#x}, {e['d0']}, {e['d1']})")
    seeks = [(V1.sx(e['d0']), e['d1']) for e in calls if e['fn'] == 'fseek']
    if seeks and seeks != [(0, 1), (0, 2)][:len(seeks)]:
        probs.append(f'fseek args {seeks}')
    names = [e['fn'] for e in calls]
    if 'fopen' in names and case.fopen_ok:
        if names.count('fclose') != 1 or any(x in FILE_OPS for x in names[names.index('fclose') + 1:]):
            probs.append('file not closed exactly once / used after fclose')
    elif 'fclose' in names:
        probs.append('fclose without a successful fopen')
    if ('free' in names) != (case.malloc_ok and 'malloc' in names):
        probs.append('free mismatch')
    tab_out = p['mem']['table']
    want = bytearray(table_in)
    if load:
        want[0x60210900 - TAB_LO:0x60210900 - TAB_LO + SB.PAYLOAD_LEN] = case.file[SB.HDR_LEN:]
    if tab_out != bytes(want):
        diff = [i for i in range(len(want)) if tab_out[i] != want[i]]
        probs.append(f"table {'not replaced exactly' if load else 'changed'} ({len(diff)} bytes)")
    if s['mem']['table'] != bytes(table_in):
        probs.append('stock run changed the table (fixture wrong)')
    heap, h0 = p['mem']['heap'], V1.heap_init(case)
    if heap[:BUF - HEAP] != h0[:BUF - HEAP] or heap[BUF - HEAP + SB.BUF_SIZE:] != h0[BUF - HEAP + SB.BUF_SIZE:]:
        probs.append('heap written outside the buffer')
    cout = p['mem']['loader']
    so = STATE - SEC_LO
    if cout[:so] + cout[so + 1:] != bytes(code_in[:so] + code_in[so + 1:]):
        probs.append('loader region changed outside sd_state')
    if cout[so] != st_exp:
        probs.append(f'sd_state {cout[so]:#x} != {st_exp:#x}')
    return not probs, probs, cout[so], p['mem']['trig'][8]


STATE = None


class Runner:
    def __init__(self, stock, code_len):
        self.stock, self.code_len = stock, code_len

    def step(self, img, case, ev, env, code, table, state, trig):
        code = bytearray(code)
        code[STATE - SEC_LO] = state
        if case.table_fill is not None:
            table = bytearray(table)
            table[0x60210900 - TAB_LO:0x60210b00 - TAB_LO] = bytes([case.table_fill]) * SB.PAYLOAD_LEN
            table = bytes(table)
        p = run(img, case, ev, env, code=code, table=table, trig_state=trig)
        s = run(self.stock, case, ev, env, table=table, trig_state=trig)
        ok, probs, st, tr = check(case, ev, env, s, p, state, trig, table, code, self.code_len)
        return ok, probs, p, st, tr, table

    def single(self, img, case, ev=PRESS, env=OK):
        code, table = sl(img, SEC_LO, SEC_HI), sl(img, TAB_LO, TAB_HI)
        ok, probs, p, st, tr, _ = self.step(img, case, ev, env, code, table, 0xff, 0)
        return ok, probs, p

    def sequence(self, img, steps):
        """One power-on: events in order, loader/table/tracker state carried across."""
        code, table, rows, ok = sl(img, SEC_LO, SEC_HI), sl(img, TAB_LO, TAB_HI), [], True
        state, trig = code[STATE - SEC_LO], 0
        for label, case, ev, env in steps:
            g, probs, p, st, tr, table = self.step(img, case, ev, env, code, table, state, trig)
            rows.append(dict(step=label, ev=hex(ev), ok=g, problems=probs, sd_state=st, trig=tr))
            ok &= g
            if p['fault']:
                break
            code, table, state, trig = p['mem']['loader'], p['mem']['table'], st, tr
        return ok, rows


def sequences(F):
    v, x = F['mono'], F['all_hi']
    C = V1.Case
    nofile = C('no file', None)
    vf = C('valid', v, expect='load')
    xf = C('other valid', x, expect='load')
    return [
        ('boot: sections 8/9 not copied yet -> no file call, not consumed; later press loads',
         [('press, secbits 0x07f', vf, PRESS, Env(secbits=0x07f)), ('release', vf, RELEASE, OK), ('press', vf, PRESS, OK)]),
        ('HLS_EVENT not created (tid -1 / 0) -> none; later press loads',
         [('press, hls -1', vf, PRESS, Env(hls=0xffff)), ('release', vf, RELEASE, OK),
          ('press, hls -1 and a tid that reads 0xffff (sign guard alone)', vf, PRESS, Env(hls=0xffff, cur=0xffff)),
          ('release', vf, RELEASE, OK),
          ('press, hls 0', vf, PRESS, Env(hls=0, cur=0)), ('release', vf, RELEASE, OK), ('press', vf, PRESS, OK)]),
        ('wrong task (FILECLBK 16, HIGHLEVEL_MAIN 61) / non-task context -> none; later press loads',
         [('press as tid 16', vf, PRESS, Env(cur=16)), ('release', vf, RELEASE, OK),
          ('press as tid 61', vf, PRESS, Env(cur=61)), ('release', vf, RELEASE, OK),
          ('press, get_tid -25', vf, PRESS, Env(nontask=True)), ('release', vf, RELEASE, OK), ('press', vf, PRESS, OK)]),
        ('no medium mounted -> none, not consumed; mount -> next press loads',
         [('press, no MOUNT OK', vf, PRESS, Env(media=(0, 0x1000, 0, 0))), ('release', vf, RELEASE, OK),
          ('press, media type 32 slot OK', vf, PRESS, Env(media=(0xF000, 0, 0, 0)))]),
        ('load once per power-on',
         [('press valid', vf, PRESS, OK), ('release', xf, RELEASE, OK), ('press, other valid file', xf, PRESS, OK),
          ('trig2', xf, T2_PRESS, OK)]),
        ('missing file consumes the single attempt',
         [('press, no file', nofile, PRESS, OK), ('release', vf, RELEASE, OK), ('press, valid now', vf, PRESS, OK)]),
        ('rejected file consumes the single attempt',
         [('press, bad CRC', C('bad CRC', v[:16] + bytes(4) + v[20:], expect='reject'), PRESS, OK),
          ('release', vf, RELEASE, OK), ('press, valid', vf, PRESS, OK)]),
        ('release / trig2 / repeat / non-shutter events never load; then press loads',
         [('release first (swallowed)', vf, RELEASE, OK), ('trig2 release', vf, T2_RELEASE, OK),
          ('non-shutter key 0x02000102', vf, 0x02000102, OK), ('other class 0x01000100', vf, 0x01000100, OK),
          ('press, key filter rejects', vf, PRESS, Env(keyfilt=0)), ('repeat press (swallowed)', vf, PRESS, OK),
          ('release', vf, RELEASE, OK), ('press', vf, PRESS, OK)]),
        ('source-B press 0x02040100 is canonicalised by the real tracker and loads',
         [('B press', vf, B_PRESS, OK), ('B release', vf, B_RELEASE, OK)]),
        ('A pressed while B held: combined state unchanged -> swallowed, no load',
         [('B press, no medium', vf, B_PRESS, Env(media=(0, 0, 0, 0))), ('A press (swallowed)', vf, PRESS, OK),
          ('B release (swallowed)', vf, B_RELEASE, OK), ('A release', vf, RELEASE, OK), ('A press', vf, PRESS, OK)]),
    ]


# ------------------------------------------------------------------ static + call path
def check_static(spec, stock, patched, code_len):
    r = {}
    site = S2.SITE
    r['site_jmp_to_sd_hook'] = patched[site - BASE] == 0xdc and site + struct.unpack_from('<i', patched, site + 1 - BASE)[0] == S2.CODE_AT
    r['site_stock'] = sl(stock, site, site + 5).hex() == S2.SITE_STOCK
    r['site_neighbours_stock'] = sl(patched, site - 32, site) == sl(stock, site - 32, site) and \
        sl(patched, site + 5, site + 37) == sl(stock, site + 5, site + 37)
    code_edit = next(e for e in spec['edits'] if int(e['addr'], 16) == S2.CODE_AT)
    r['loader_bytes_eq_spec'] = sl(patched, S2.CODE_AT, S2.CODE_AT + code_len) == bytes.fromhex(code_edit['new'])
    r['ff_to_section_end'] = set(sl(patched, S2.CODE_AT + code_len, 0x605b7800)) == {0xff}
    r['stock_ff_at_placement'] = set(sl(stock, S2.CODE_AT - 16, 0x605b7800)) == {0xff}
    r['no_v1_edits'] = not any(int(e['addr'], 16) in (0x60863e91, 0x61242a00) for e in spec['edits'])
    svc = {v: k for k, v in S2.SERVICES.items() if k in ('ep7_malloc', 'ep7_free', 'ep7_fopen', 'ep7_fclose',
                                                         'ep7_fseek', 'ep7_ftell', 'ep7_fread', 'ep7_get_tid')}
    st = V1.calls_to(stock, list(svc))
    mine = V1.calls_to(patched, list(svc), S2.CODE_AT, S2.CODE_AT + code_len)
    frames, ok = {}, True
    for t, name in svc.items():
        dom = max(st[t].items(), key=lambda kv: kv[1])[0]
        used = set(mine[t])
        good = bool(used) and used == {dom}
        ok &= good
        frames[name] = dict(loader=[f'{m:#04x},{f}' for m, f in used], stock=f'{dom[0]:#04x},{dom[1]}',
                            stock_sites=st[t].get(dom, 0), stock_all=sum(st[t].values()), ok=good)
    trig = V1.calls_to(patched, [S2.TRIG], S2.CODE_AT, S2.CODE_AT + code_len)[S2.TRIG]
    frames['replayed tracker call'] = dict(loader=[f'{m:#04x},{f}' for m, f in trig], stock_site='0xf0,36')
    ok &= set(trig) == {(0xf0, 36)}
    r['service_frames_match_stock'] = ok
    return all(r.values()), dict(r, frames=frames)


def check_path(d):
    """Byte-level proof of the call path from boot to the hook (each item: address, expected bytes/target)."""
    def call_tgt(a):
        o = a - BASE
        if d[o] == 0xdd:
            return a + struct.unpack_from('<i', d, o + 1)[0]
        if d[o] == 0xcd:
            return a + struct.unpack_from('<h', d, o + 1)[0]
        return None
    items = [
        ('USRSTART2 wait(6) then HIGHLEVEL setup', d[0x60191af9 - BASE:0x60191afb - BASE] == b'\x80\x06'
         and call_tgt(0x60191afb) == 0x6004586c and call_tgt(0x60191b02) == 0x60767d20 and call_tgt(0x60191b17) == 0x60767db2),
        ('0x60767db2 -> 0x607688e3 (HIGHLEVEL run init)', call_tgt(0x60767db8) == 0x607688e3),
        ('0x607688ae: mgr = 0x6076fbed(); stored at (4,obj) by 0x60768a05', call_tgt(0x607688ae) == 0x6076fbed
         and call_tgt(0x607688b5) == 0x60768a05 and d[0x60768a05 - BASE:0x60768a08 - BASE].hex() == 'f83404'),
        ('0x60768948: a0 = (4,obj); call 0x6076fd56', d[0x60768948 - BASE:0x6076894b - BASE].hex() == 'f82204'
         and call_tgt(0x6076894b) == 0x6076fd56),
        ('0x6076fd56 creates task HLS_EVENT (entry 0x6076fdb6, prio 54, stack 16360), tid -> mgr+172',
         d[0x6076fd80 - BASE:0x6076fd86 - BASE] == b'\xfc\xdc' + struct.pack('<I', 0x60a696f0)
         and d[0x60a696f0 - BASE:0x60a696fa - BASE] == b'HLS_EVENT\0'
         and d[0x6076fd88 - BASE:0x6076fd8e - BASE] == b'\xfc\xdd' + struct.pack('<I', 0x6076fdb6)
         and call_tgt(0x6076fd8e) == 0x60051d66 and d[0x6076fd95 - BASE:0x6076fd97 - BASE] == b'\xf0\x72'
         and call_tgt(0x6076fd9f) == 0x6003071f),
        ('HLS_EVENT entry: mgr = 0x6076fbed(); 0x6076fe04(mgr)', call_tgt(0x6076fdb9) == 0x6076fbed and call_tgt(0x6076fdbe) == 0x6076fe04),
        ('0x6076fe04 loop: get-event 0x60770217 (timeout -1) at 0x6076fe12 and 0x6076feae, jmp back 0x6076feb7',
         call_tgt(0x6076fe12) == 0x60770217 and call_tgt(0x6076feae) == 0x60770217
         and d[0x6076fe10 - BASE:0x6076fe12 - BASE] == b'\x80\xff' and d[0x6076feb7 - BASE] == 0xcc
         and 0x6076feb7 + struct.unpack_from('<h', d, 0x6076feb7 - BASE + 1)[0] == 0x6076fe1e),
        ('0x60770224 calls the appevent get 0x602c7f5a,[d2,d3,a2,a3],88', call_tgt(0x60770224) == 0x602c7f5a
         and d[0x60770229 - BASE:0x6077022b - BASE] == b'\xf0\x58'),
        ('0x602c7f5a: blocking receive (queue (0x60040ce8), timeout -1)', call_tgt(0x602c7fb7) == 0x602c9b6a
         and d[0x602c7fa0 - BASE:0x602c7fa6 - BASE] == b'\xfc\xac' + struct.pack('<I', 0x60040ce8)
         and d[0x602c7faf - BASE:0x602c7fb2 - BASE].hex() == '80ff42'),
        ('hook site 0x602c805f = call 0x602c818c (low16 0x100/0x101 only)', call_tgt(S2.SITE) == S2.TRIG),
    ]
    xr = _load('ep7_xref', ROOT / 'tools/ep7_xref.py')
    import numpy as np
    arr = np.frombuffer(d, dtype=np.uint8)
    refs = xr.scan(arr, [0x602c7f5a, 0x60770212, 0x60770217, 0x6076fdb6], short=False)
    at = {t: sorted((k, a) for k, a in v) for t, v in refs.items()}
    items.append(('0x602c7f5a has exactly one caller (call32 at 0x60770224); its loop jmp16 0x602c811b is internal',
                  at[0x602c7f5a] == [('call32', 0x60770224)]))
    items.append(('0x60770217 (get-event body) called only from the HLS_EVENT loop (0x6076fe12, 0x6076feae)',
                  at[0x60770217] == [('call16', 0x6076fe12), ('call16', 0x6076feae)]))
    items.append(('0x60770212 (virtual entry) only in vtable 0x60a69794 slot 35 (0x60a69820)',
                  at[0x60770212] == [('abs32', 0x60a69820)]))
    items.append(('task entry 0x6076fdb6 referenced only by the create call (0x6076fd8a)',
                  at[0x6076fdb6] == [('abs32', 0x6076fd8a)]))
    return all(ok for _, ok in items), [dict(item=n, ok=bool(ok)) for n, ok in items], {hex(k): [f'{a}@{b:#x}' for a, b in v] for k, v in refs.items()}


# ------------------------------------------------------------------ mutations
def mutations(patched, code_len):
    lo, hi = S2.CODE_AT, S2.CODE_AT + code_len
    out = []

    def mut(name, pat, new, off=0):
        m = bytearray(patched)
        i = V1.find_once(m, pat, lo, hi) + off
        m[i:i + len(new)] = new
        out.append((name, bytes(m)))
    st = struct.pack('<I', STATE)
    mut('event compare bne -> beq', bytes.fromhex('fcc800010002c9'), b'\xc8', 6)
    mut('event compare removed', bytes.fromhex('fcc800010002c9'), b'\xcb\xcb', 6)
    mut('displaced tracker call removed', patched[lo - BASE:lo - BASE + 7], b'\xcb' * 7)
    mut('jmp back to 0x602c8066', b'\xdc' + struct.pack('<i', S2.SITE_RET - (lo + 0x20)), b'\xdc' + struct.pack('<i', S2.SITE_RET + 2 - (lo + 0x20)))
    mut('section-bit guard removed', bytes.fromhex('fac8ff01c9'), b'\xcb\xcb', 4)
    mut('get_tid status check removed', bytes.fromhex('ff2004a000c9'), b'\xcb\xcb', 6)
    mut('HLS tid -1 check removed', bytes.fromhex('faed0080c9'), b'\xcb\xcb', 4)
    mut('task compare removed', bytes.fromhex('f8bc0ca4c9'), b'\xcb\xcb', 4)
    mut('mount check removed', bytes.fromhex('fca4d08ffa61a4c9'), b'\xcb\xcb', 7)
    mut('sd_state store removed', bytes.fromhex('fc82') + st, b'\xcb' * 6)
    mut('state test removed (beq)', bytes.fromhex('fca8') + st + bytes.fromhex('a000c8'), b'\xcb\xcb', 9)
    mut('CRC compare flipped', bytes.fromhex('adc9'), b'\xc8', 1)
    mut('file size check removed', bytes.fromhex('facb2002c9'), b'\xcb\xcb', 4)
    mut('range check removed', bytes.fromhex('acc5'), b'\xcb\xcb', 1)
    mut('table address +1', b'\xfc\xdd' + struct.pack('<I', 0x60210900), b'\xfc\xdd' + struct.pack('<I', 0x60210901))
    return out


def core(F, rng):
    pick = ('valid mono_colour_example.json (ep7_bundles_bin)', 'CRC value +1', 'file size 545', 'missing file (fopen -> 0)')
    cl = [c for c in V1.cases(F, rng) if c.name in pick]
    lo, span, who = rng
    v = F['mono']
    k = next(o for o in range(64) if span[o] > 0 and lo[o] < 0)
    cl.append(V1.Case('range lo-1', V1.poke(v, 32 + k, lo[k] - 1), expect='reject'))
    return cl, sequences(F)


def suite(R, img, case_list, seqs):
    rows, ok, depth = [], True, 0
    for c in case_list:
        g, probs, p = R.single(img, c)
        depth = max(depth, p['depth']) if not p['fault'] else depth
        rows.append(dict(case=c.name, ok=g, problems=probs, depth=p['depth']))
        ok &= g
    srows = []
    for name, steps in seqs:
        g, r = R.sequence(img, steps)
        srows.append(dict(sequence=name, ok=g, steps=r))
        ok &= g
    return ok, rows, srows, depth


# ------------------------------------------------------------------ main
def main():
    global STATE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    ap.add_argument('--no-mutations', action='store_true')
    ap.add_argument('--quick', action='store_true', help='only a subset of the file cases')
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    meta = spec.get('sd_bundles_v2') or spec.get('meta', {}).get('sd_bundles_v2', {}).get('sd_bundles_v2')
    if not meta:
        sys.exit("spec lacks 'sd_bundles_v2' (build with patches/sd_bundles_v2/build.py; merge with tools/merge_specs.py)")
    if int(meta['code_at'], 16) != S2.CODE_AT or meta['site'] != hex(S2.SITE):
        sys.exit('spec metadata does not match patches/sd_bundles_v2/build.py')
    STATE = int(meta['state'], 16)
    code_len = meta['code_len']
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    F, rng = V1.files()
    results = []
    ok, st = check_static(spec, stock, patched, code_len)
    results.append(dict(test='S static: site jmp, loader bytes, FF tail, call frames == stock, no v1 edits', passed=ok, detail=st))
    ok, items, refs = check_path(bytes(stock))
    results.append(dict(test='P call path boot -> HLS_EVENT task -> appevent get -> hook (byte-checked)', passed=ok,
                        detail=dict(items=items, refs=refs)))
    flashed = sl(patched, 0x60210900, 0x60210b00)
    results.append(dict(test='S bundles table present (flashed table is a valid table != mono test payload)',
                        passed=flashed != F['mono'][32:] and SB.table_ok(flashed, rng[0], rng[1])))
    R = Runner(stock, code_len)
    cl = V1.cases(F, rng)
    if a.quick:
        cl = cl[:12] + cl[-16:]
    ok, rows, srows, depth = suite(R, patched, cl, sequences(F))
    nv = sum(1 for c in cl if c.expect == 'load')
    results.append(dict(test=f'E/F {len(cl)} one-press power-ons ({nv} valid, {len(cl) - nv} reject/no-file/error), '
                             'from the upstream event, vs stock', passed=all(r['ok'] for r in rows),
                        detail=f'peak stack below the HLS_EVENT caller sp {depth} B', rows=rows))
    results.append(dict(test=f'E/Q {len(srows)} power-on event sequences (boot windows, once, event kinds)',
                        passed=all(r['ok'] for r in srows), rows=srows))
    allok = all(r['passed'] for r in results)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['test']}" + (f"  {r['detail']}" if 'detail' in r and
                                                                   isinstance(r['detail'], str) else ''))
        if isinstance(r.get('detail'), dict) and not r['passed']:
            print('      ', json.dumps(r['detail'], default=str)[:1500])
        for x in r.get('rows', []):
            if not x['ok']:
                print('      BAD', json.dumps(x, default=str)[:600])
    mres = []
    if not a.no_mutations:
        if not allok:
            print('skipping mutations: base suite failed')
        else:
            ccl, cseq = core(F, rng)
            for name, img in mutations(patched, code_len):
                g, rws, srw, _ = suite(R, img, ccl, cseq)
                failing = [x['case'] for x in rws if not x['ok']] + [x['sequence'] for x in srw if not x['ok']]
                mres.append(dict(mutation=name, detected=not g, failing=failing))
                print(f"{'PASS' if not g else 'FAIL'}  M mutation '{name}' detected by {len(failing)}: {failing[:2]}")
            allok &= all(m['detected'] for m in mres)
    print(f"{'PASS' if allok else 'FAIL'}  overall; package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.edits), package=info, passed=allok, results=results, mutations=mres,
                                          scope='emulator only; runs start at the appevent get function (real code from '
                                                'the event word on); stub file service at the real entries; real get_tid; '
                                                'no camera contacted'), indent=1, default=str))
    sys.exit(0 if allok else 1)


if __name__ == '__main__':
    main()
