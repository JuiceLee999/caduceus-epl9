#!/usr/bin/env python3
"""Emulator verification of a BUILT SD-crash probe package P1 / P2 / P2b (offline; emulator only; no camera).

Takes a merged spec (test-6 base + patches/sd_probe/build.py output, tools/merge_specs.py). Builds the package in
memory (tools/build_package.build()), decodes the patched and the restore (= stock) main payloads and runs them in
the fishcu emulator with the SAME fixture as tools/ep7_verify_sd_bundles_v2.py: every run starts at the real
upstream event (HLS_EVENT's `call 0x602c7f5a,[d2,d3,a2,a3],88`, the real appevent get function, an injected event
word at the blocking receive, the real low16 gate, hook site, real TRIG tracker, real get_tid, real stock code to
the function's own ret). Differences from the v2 verifier fixture: EVERY data region the code can reach is
writable and captured (section-3 tail, event manager 0x622cbc00..0x622cbd00, section bits, media status, kernel
blocks, tracker byte, app RAM, table, heap, stub control block), so any stray write shows up as a diff vs stock;
an instruction trace is recorded so the store instruction's executions are counted.

  S  static: site = jmp 0x605b7400; probe bytes == spec; FF from the end of the probe to the section end; exactly
     one absolute store (P2b: none), no other store instruction except call/ret frames; branches forward only (no
     loops); the replayed tracker call == the stock call (0xf0 mask, frame 36); the gate is byte-identical to v2's
     apart from branch displacements; for P2, 0x622cbcc2 is unreferenced and inside the runtime-written
     event-manager object (see check_pad()).
  E  every run, vs stock: no fault; returns to the caller; all registers equal (d0-d3, a0-a3, sp, pc, mdr, psw,
     lir, lar); live stack equal (the caller's frame and above); event returned / swallowed equal; tracker state
     byte equal; leaf-call arguments equal; zero file-service calls; every captured region equal to stock except
     the probe's state address, which changes only on the expected press, to the expected value; the store
     instruction executes exactly that many times (0 or 1) per run.
  Q  power-on sequences: boot windows (sections not copied, HLS_EVENT not created, wrong task, non-task, no
     medium) -> no store, retried later; first gated press stores; later presses do not (P1/P2); P2b never stores
     and runs the gate on every press.
  M  mutations (store removed / retargeted / doubled, replay removed, jmp-back +2): each must fail E/Q.

Usage: tools/ep7_verify_sd_probe.py SPEC.json [--json out.json]
"""
import argparse, importlib.util, json, re, struct, subprocess, sys
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


W2 = _load('ep7_verify_sd_bundles_v2', ROOT / 'tools/ep7_verify_sd_bundles_v2.py')   # fixture, stubs, models
PB = _load('ep7_sd_probe_build', ROOT / 'patches/sd_probe/build.py')
V1, S2 = W2.V1, W2.S2
BASE, sl = W2.BASE, W2.sl
CALLER, SP0, STACK, STACK_FILL = W2.CALLER, W2.SP0, W2.STACK, W2.STACK_FILL
Env, OK = W2.Env, W2.OK
PRESS, RELEASE, T2_PRESS, T2_RELEASE, B_PRESS, B_RELEASE = (W2.PRESS, W2.RELEASE, W2.T2_PRESS, W2.T2_RELEASE,
                                                            W2.B_PRESS, W2.B_RELEASE)
SEC_LO, SEC_HI = W2.SEC_LO, W2.SEC_HI
EVM_LO, EVM_HI = 0x622cbc00, 0x622cbd00
NOFILE = V1.Case('no file', None)
CAPTURED = ('loader', 'evm', 'secbits', 'media', 'kern', 'cpuid', 'tcbtab', 'trig', 'appram', 'a2699', 'table',
            'heap', 'ctl')


def evm_block(env, pad):
    b = bytearray(EVM_HI - EVM_LO)
    for i in range(len(b)):            # recognisable non-zero background (the object's other fields)
        b[i] = (0x37 + 13 * i) & 0xff
    struct.pack_into('<H', b, 0xc0, env.hls & 0xffff)
    struct.pack_into('<H', b, 0xc2, pad)
    return bytes(b)


def run(img, ev, env, *, code=None, evm=None, trig_state=0, table=None):
    getfn = bytearray(sl(img, W2.CODE_LO, W2.CODE_HI))
    getfn[W2.RECV_AT - W2.CODE_LO:W2.RECV_AT - W2.CODE_LO + 5] = W2.jmp_to(W2.RECV_AT, W2.STUB_SYMS['inject'])
    k, P = W2.kern(env)
    sec = bytes(code if code is not None else sl(img, SEC_LO, SEC_HI))
    tri = bytearray(0x10)
    tri[8] = trig_state
    regions = [Region('caller', CALLER, b'\xdd' + struct.pack('<i', S2.GET_FN - CALLER) + b'\xf0\x58\xcb', 'rx'),
               Region('getfn', W2.CODE_LO, bytes(getfn), 'rx'),
               Region('loader', SEC_LO, sec, 'rwx', True),
               Region('get_tid', W2.TID_LO, sl(img, W2.TID_LO, W2.TID_HI), 'rx'),
               Region('cpuid', 0x8050, bytes(4), 'rw', True),
               Region('tcbtab', 0x8ff00000, bytes(4) + struct.pack('<I', P) + bytes(8), 'rw', True),
               Region('kern', W2.KERN, k, 'rw', True),
               Region('secbits', 0xa272e400, bytes(0x20) + struct.pack('<I', env.secbits) + bytes(0x1c), 'rw', True),
               Region('evm', EVM_LO, evm if evm is not None else evm_block(env, 0), 'rw', True),
               Region('media', 0x61fa8f00, W2.media_data(env), 'rw', True),
               Region('trig', 0x61f9f1c0, bytes(tri), 'rw', True),
               Region('appram', 0x6224b400, bytes(0x2800), 'rw', True),
               Region('a2699', 0xa2699900, bytes(0x80), 'rw', True),
               Region('table', W2.TAB_LO, table if table is not None else sl(img, W2.TAB_LO, W2.TAB_HI), 'rw', True),
               Region('ctl', W2.CTL, W2.ctl_block(NOFILE, ev, 0x11223344, env), 'rw', True),
               Region('heap', W2.HEAP, V1.heap_init(NOFILE), 'rw', True),
               Region('stack', STACK, bytes([STACK_FILL]) * 0x2000, 'rw', True)] + W2.stub_regions()
    r = execute(regions, dict(W2.INIT, pc=CALLER, sp=SP0), CALLER + 7, limit=200_000, trace_limit=100_000, timeout=120)
    m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    ctl = m['ctl']
    n = (struct.unpack_from('<I', ctl, V1.C_LOGP)[0] - W2.LOG) // W2.LOG_SZ
    log = []
    for i in range(max(0, min(n, W2.LOG_N))):
        v = struct.unpack_from('<11I', ctl, 0x100 + i * W2.LOG_SZ)
        log.append(dict(fn=W2.IDS.get(v[0], v[0]), d0=v[1], sp=v[5], ret=v[6], arg4=v[7], arg8=v[8], arg12=v[9]))
    pcs = [t['pc'] for t in r['trace']]
    return dict(fault=r['fault'], regs={k: r['registers'][k] for k in W2.ALL_REGS}, log=log, mem=m, pcs=pcs,
                inj=struct.unpack_from('<I', ctl, 0x60)[0], live=m['stack'][SP0 - STACK:])


def ctl_mask(c):
    c = bytearray(c)
    for i in range(W2.LOG_N):
        for f in (8, 12, 16, 40):
            o = 0x100 + i * W2.LOG_SZ + f
            if o + 4 <= len(c):
                c[o:o + 4] = bytes(4)
    return bytes(c)


class Probe:
    def __init__(self, meta, patched):
        self.name = meta['probe']
        self.state, self.width = int(meta['state'], 16), meta['state_width']
        self.init, self.store = meta['state_init'], meta['store_value']
        self.code_len = meta['code_len']
        self.syms = {k: int(v, 16) for k, v in meta['symbols'].items()}
        self.store_pc = None
        if self.store is not None:
            self.store_pc = self.syms['sd_gout'] - 6   # the abs32 store is the last instruction before sd_gout
            assert patched[self.store_pc - BASE:self.store_pc - BASE + 2] in (b'\xfc\x82', b'\xfc\x83')
        self.region = 'loader' if SEC_LO <= self.state < SEC_HI else 'evm'
        self.rlo = SEC_LO if self.region == 'loader' else EVM_LO

    def get(self, mem):
        o = self.state - self.rlo
        return int.from_bytes(mem[self.region][o:o + self.width], 'little')

    def strip(self, b):
        o = self.state - self.rlo
        return b[:o] + b[o + self.width:]

    def fires(self, ev, env, st, trig):
        ts, canon = W2.tracker(trig, ev) if W2.routed(ev) else (trig, ev)
        if not W2.routed(ev) or canon != PRESS or not env.gate_ok():
            return False, ts, canon == PRESS and W2.routed(ev)
        armed = st == self.init
        return (armed and self.store is not None), ts, armed


def check(pr, ev, env, s, p, st_in, trig_in):
    probs = []
    fire, ts_exp, gate_runs = pr.fires(ev, env, st_in, trig_in)
    if s['fault'] or p['fault']:
        return False, [f"fault stock={s['fault']} patched={p['fault']}"], fire
    if p['regs']['pc'] != CALLER + 7 or s['regs']['pc'] != CALLER + 7:
        probs.append('did not return to the HLS_EVENT caller')
    d = [k for k in W2.ALL_REGS if s['regs'][k] != p['regs'][k]]
    if d:
        probs.append(f'registers != stock: {d}')
    if s['live'] != p['live']:
        probs.append('live stack != stock')
    if s['inj'] != p['inj']:
        probs.append('event swallowed/returned differs')
    if s['mem']['trig'][8] != ts_exp:
        probs.append('tracker model disagrees with stock (fixture/model wrong)')
    LK = ('fn', 'd0', 'sp', 'ret', 'arg4', 'arg8', 'arg12')
    if [{k: e[k] for k in LK} for e in s['log']] != [{k: e[k] for k in LK} for e in p['log'] if e['fn'] in W2.LEAF]:
        probs.append('appevent leaf calls != stock')
    if any(e['fn'] not in W2.LEAF for e in p['log']):
        probs.append(f"service calls made: {[e['fn'] for e in p['log'] if e['fn'] not in W2.LEAF]}")
    for k in CAPTURED:
        a, b = s['mem'][k], p['mem'][k]
        if k == 'loader':
            a = None   # stock run sees the stock tail; compare the patched tail with its own input below
            continue
        if k == pr.region:
            a, b = pr.strip(a), pr.strip(b)
        if k == 'ctl':      # leaf-stub log entries: d1/a0/a1/mdr at leaf entry are dead leftovers (as in the v2 verifier)
            a, b = ctl_mask(a), ctl_mask(b)
        if a != b:
            probs.append(f'{k} memory != stock')
    want = pr.store if fire else st_in
    if pr.get(p['mem']) != want:
        probs.append(f'state {pr.get(p["mem"]):#x} != {want:#x}')
    n_store = p['pcs'].count(pr.store_pc) if pr.store_pc else 0
    if n_store != int(fire):
        probs.append(f'store instruction executed {n_store}x, expected {int(fire)}')
    if len(p['pcs']) >= 100_000:
        probs.append('trace truncated')
    gate_seen = S2.CODE_AT + 0x25 in p['pcs']          # sd_gate entry
    if gate_seen != gate_runs:
        probs.append(f'gate ran={gate_seen}, expected {gate_runs}')
    return not probs, probs, fire


def sequences():
    return [
        ('first gated press stores; repeat presses do not',
         [('press', PRESS, OK), ('release', RELEASE, OK), ('press', PRESS, OK), ('release', RELEASE, OK),
          ('press', PRESS, OK)]),
        ('boot windows: no store, not consumed; then a press stores',
         [('press, secbits 0x07f', PRESS, Env(secbits=0x07f)), ('release', RELEASE, OK),
          ('press, hls -1', PRESS, Env(hls=0xffff)), ('release', RELEASE, OK),
          ('press, hls 0', PRESS, Env(hls=0, cur=0)), ('release', RELEASE, OK),
          ('press as tid 16', PRESS, Env(cur=16)), ('release', RELEASE, OK),
          ('press, get_tid -25', PRESS, Env(nontask=True)), ('release', RELEASE, OK),
          ('press, no MOUNT OK', PRESS, Env(media=(0, 0x1000, 0, 0))), ('release', RELEASE, OK),
          ('press', PRESS, OK)]),
        ('non-press events never store; source-B press stores',
         [('release first', RELEASE, OK), ('trig2 press', T2_PRESS, OK), ('trig2 release', T2_RELEASE, OK),
          ('key 0x02000102', 0x02000102, OK), ('class 0x01000100', 0x01000100, OK),
          ('press, key filter rejects', PRESS, Env(keyfilt=0)), ('repeat press (swallowed)', PRESS, OK),
          ('release', RELEASE, OK), ('B press', B_PRESS, OK), ('B release', B_RELEASE, OK), ('press', PRESS, OK)]),
    ]


def run_seq(pr, img, stock, steps):
    code = sl(img, SEC_LO, SEC_HI)
    evm, trig, st, rows, ok, stores = None, 0, pr.init, [], True, 0
    for label, ev, env in steps:
        evm = evm if evm is not None else evm_block(env, 0)
        evm = evm[:0xc0] + struct.pack('<H', env.hls & 0xffff) + evm[0xc2:]   # env tid; pad carried
        p = run(img, ev, env, code=code, evm=evm, trig_state=trig)
        s = run(stock, ev, env, evm=evm, trig_state=trig, table=sl(img, W2.TAB_LO, W2.TAB_HI))
        g, probs, fire = check(pr, ev, env, s, p, st, trig)
        if p['mem']['loader'] != code if pr.region != 'loader' else pr.strip(p['mem']['loader']) != pr.strip(code):
            g, probs = False, probs + ['section-3 tail changed outside the state byte']
        rows.append(dict(step=label, ev=hex(ev), ok=g, problems=probs, stored=fire))
        ok &= g
        stores += fire
        if p['fault']:
            break
        code, evm, trig, st = p['mem']['loader'], p['mem']['evm'], p['mem']['trig'][8], pr.get(p['mem'])
    return ok, rows, stores


def suite(pr, img, stock):
    out, ok = [], True
    for name, steps in sequences():
        g, rows, stores = run_seq(pr, img, stock, steps)
        exp = 0 if pr.store is None else 1
        if stores != exp:
            g = False
            rows.append(dict(step='total', ok=False, problems=[f'{stores} stores in the power-on, expected {exp}']))
        out.append(dict(sequence=name, ok=g, rows=rows))
        ok &= g
    return ok, out


# ------------------------------------------------------------------ static
def check_static(spec, pr, stock, patched):
    r = {}
    site = S2.SITE
    r['site_jmp_0x605b7400'] = patched[site - BASE] == 0xdc and site + struct.unpack_from('<i', patched, site + 1 - BASE)[0] == S2.CODE_AT
    r['site_stock_was_tracker_call'] = sl(stock, site, site + 5).hex() == S2.SITE_STOCK
    r['site_neighbours_stock'] = sl(patched, site - 32, site) == sl(stock, site - 32, site) and \
        sl(patched, site + 5, site + 37) == sl(stock, site + 5, site + 37)
    code = sl(patched, S2.CODE_AT, S2.CODE_AT + pr.code_len)
    edit = next(e for e in spec['edits'] if int(e['addr'], 16) == S2.CODE_AT)
    r['probe_bytes_eq_spec'] = code == bytes.fromhex(edit['new'])
    r['ff_to_section_end'] = set(sl(patched, S2.CODE_AT + pr.code_len, 0x605b7800)) == {0xff}
    r['no_v1_v2_other_edits_in_tail'] = sum(1 for e in spec['edits'] if 0x605b7000 <= int(e['addr'], 16) < 0x605b7800) == 1
    r['replayed_call_eq_stock'] = code[:7] == b'\xdd' + struct.pack('<i', S2.TRIG - S2.CODE_AT) + b'\xf0\x24'
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.bin') as tf:
        tf.write(code)
        tf.flush()
        dis = subprocess.run([W2.TC / 'mn10300-elf-objdump', '-b', 'binary', '-m', 'am33-2', '-D',
                              f'--adjust-vma={S2.CODE_AT:#x}', tf.name], capture_output=True, check=True).stdout.decode()
    ins = [(int(m.group(1), 16), m.group(2).strip()) for m in re.finditer(r'^\s*([0-9a-f]+):\t[0-9a-f ]+\t(.*)$', dis, re.M)]
    stores = [(a, t) for a, t in ins if re.match(r'mov(bu|hu)?\s+[da]\d,\(', t)]
    want = [] if pr.store is None else [pr.state]
    tgts = [int(m.group(1), 16) for _, t in stores for m in [re.search(r'\(0x([0-9a-f]+)\)', t)] if m]
    r['exactly_the_probe_store'] = len(stores) == len(want) and tgts == want
    r['store_at_expected_pc'] = (pr.store_pc is None) or (stores and stores[0][0] == pr.store_pc)
    br = [(a, int(m.group(1), 16)) for a, t in ins for m in [re.match(r'(?:b\w+|jmp|bra)\s+0x([0-9a-f]+)', t)] if m]
    r['branches_forward_only'] = all(t > a for a, t in br if S2.CODE_AT <= t < S2.CODE_AT + pr.code_len)
    r['only_exit_is_jmp_0x602c8064'] = [t for a, t in br if not S2.CODE_AT <= t < S2.CODE_AT + pr.code_len] == [S2.SITE_RET]
    r['no_movm_inc_add_sp'] = not any(re.match(r'(movm|add\s+-?\d+,sp|inc4?\s+sp)', t) for _, t in ins)
    # gate == v2 gate bytes (0x605b7425 .. sd_go) apart from bne/beq displacements to sd_gout
    v2 = PB.V2
    vcode, _, vsyms, _ = v2.assemble(v2.source())
    g0, g1 = pr.syms['sd_gate'] - S2.CODE_AT, pr.syms['sd_go'] - S2.CODE_AT
    vg0, vg1 = vsyms['sd_gate'] - S2.CODE_AT, vsyms['sd_go'] - S2.CODE_AT
    a_, b_ = bytearray(code[g0:g1]), bytearray(vcode[vg0:vg1])
    same_len = (g0, g1) == (vg0, vg1)
    diff = [i for i in range(len(a_)) if same_len and a_[i] != b_[i]]
    r['gate_eq_v2_except_branch_disp'] = same_len and all(a_[i - 1] in (0xc8, 0xc9) for i in diff)
    r['hook_head_eq_v2'] = code[:0x11] == vcode[:0x11]   # replay, event reload/compare
    return all(r.values()), r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edits', type=Path)
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    spec = json.loads(a.edits.read_text())
    meta = spec.get('sd_probe') or next((v['sd_probe'] for v in spec.get('meta', {}).values() if 'sd_probe' in v), None)
    if not meta:
        sys.exit('spec lacks sd_probe metadata')
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    pr = Probe(meta, patched)
    results = []
    ok, st = check_static(spec, pr, stock, patched)
    results.append(dict(test='S static (site, bytes, single store, forward branches, gate == v2)', passed=ok, detail=st))
    if pr.region == 'evm':
        pad = PB.pad_evidence(bytes(stock))
        results.append(dict(test='S 0x622cbcc2 unreferenced, inside the runtime-written event manager', passed=pad['ok'], detail=pad))
    ok, rows = suite(pr, patched, stock)
    results.append(dict(test=f'E/Q {len(rows)} power-on sequences from the upstream event, vs stock', passed=ok, rows=rows))
    allok = all(r['passed'] for r in results)
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['test']}")
        if not r['passed']:
            print('      ', json.dumps(r.get('detail', ''), default=str)[:1500])
        for x in r.get('rows', []):
            for y in x['rows']:
                if not y['ok']:
                    print('      BAD', x['sequence'], json.dumps(y, default=str)[:400])
    # mutations
    mres = []
    if allok:
        for name, img in mutations(pr, patched):
            try:
                g, _ = suite(pr, img, stock)
            except Exception as e:  # a mutation that breaks the fixture counts as detected
                g = False
            mres.append(dict(mutation=name, detected=not g))
            print(f"{'PASS' if not g else 'FAIL'}  M mutation '{name}' detected")
        allok &= all(m['detected'] for m in mres)
    print(f"{'PASS' if allok else 'FAIL'}  overall {pr.name}; package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.edits), probe=pr.name, package=info, passed=allok, results=results,
                                          mutations=mres, scope='emulator only; no camera contacted'), indent=1, default=str))
    sys.exit(0 if allok else 1)


def mutations(pr, patched):
    lo = S2.CODE_AT - BASE
    out = []

    def mut(name, off, new):
        m = bytearray(patched)
        m[lo + off:lo + off + len(new)] = new
        out.append((name, bytes(m)))
    mut('replayed tracker call removed', 0, b'\xcb' * 7)
    mut('jmp back to 0x602c8066', 0x20, b'\xdc' + struct.pack('<i', S2.SITE_RET + 2 - (S2.CODE_AT + 0x20)))
    if pr.store_pc is not None:
        so = pr.store_pc - S2.CODE_AT
        mut('store removed', so, b'\xcb' * 6)
        mut('store address +2', so + 2, struct.pack('<I', pr.state + 2))
        mut('state test removed (stores every press)', 0x19, b'\xcb\xcb')
    else:
        mut('event compare removed (gate on every event)', 0x0f, b'\xcb\xcb')
        mut('gate call removed', 0x1b, b'\xcb' * 5)
    return out


if __name__ == '__main__':
    main()
