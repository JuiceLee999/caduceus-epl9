#!/usr/bin/env python3
"""Build the E-P7 1.1 SD-crash diagnostic probes P1 / P2 / P2b (offline, no camera).

  .venv/bin/python -I patches/sd_probe/build.py --probe P1 --out generated/sd_probe/P1

Writes <out>/edits.json (for tools/merge_specs.py, tools/build_package.py, tools/ep7_verify_sd_probe.py),
routine.s, routine.lst, routine.bin, symbols.json.

Plan and reasoning: docs/SD_V2_CRASH.md section 4. Every probe reuses the SD loader v2 hook (0x602c805f
`call 0x602c818c,[d2,d3,a2,a3],36` -> `jmp 0x605b7400`), its replay of that call on the same frame, its
TRIG1-press event test, and its gate (section bits, HLS_EVENT task id, MOUNT OK), copied verbatim from
patches/sd_bundles_v2/sd_bundles_v2.s.in. They differ only in what happens after the gate passes:
  P1   movbu 0,(0x605b7692)      the v2 section-3 store (same instruction form, same byte), then return
  P2   movhu 0xffff,(0x622cbcc2) event-manager padding instead (SD_V2_CRASH 3.1), nothing to section RAM
  P2b  nothing                   P1 minus the store (the flag stays 0xFF: gates run every half-press)
No malloc, no file calls in any probe. The placement / site / guard checks are v2's check_image().
"""
import argparse, hashlib, importlib.util, json, re, struct, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V2 = _load('ep7_sd_bundles_v2_build', ROOT / 'patches/sd_bundles_v2/build.py')
BASE, MAIN, MAIN_SHA = V2.BASE, V2.MAIN, V2.MAIN_SHA
CODE_AT = V2.CODE_AT

SEC3_STATE = 0x605b7692        # v2's sd_state byte (erased 0xFF in stock; v2 wrote it at 0x605b7484)
EVM_PAD = 0x622cbcc2           # OlyHfwEventManager 0x622cbc14 +174 (u16 padding between +172 u16 and +176 u32)
BSS = (0x621caf00, 0x62796888)  # cleared at boot by 0x6002046d (call at 0x60020074)

PROBES = {
    'P1':  dict(src='p1.s.in',  state=SEC3_STATE, width=1, init=0xff, store=0x00,
                tests='the section-3 RAM byte store that v2 makes at 0x605b7484 (to 0x605b7692)'),
    'P2':  dict(src='p2.s.in',  state=EVM_PAD,    width=2, init=0x0000, store=0xffff,
                tests='the same gate path with the store moved to 0x622cbcc2 (event-manager padding, .bss)'),
    'P2b': dict(src='p2b.s.in', state=SEC3_STATE, width=1, init=0xff, store=None,
                tests='hook + replay + event test + gates only (no store at all)'),
}
SERVICES = {k: V2.SERVICES[k] for k in ('ep7_trig', 'ep7_trig_ret', 'ep7_get_tid', 'ep7_secbits', 'ep7_hls_tid',
                                        'ep7_ms_a', 'ep7_ms_b', 'ep7_ms_c', 'ep7_ms_d')}


def v2_gate():
    """The v2 gate, verbatim: from `sd_gate:` up to (not including) `sd_go:`."""
    s = (ROOT / 'patches/sd_bundles_v2/sd_bundles_v2.s.in').read_text()
    a, b = s.index('\nsd_gate:'), s.index('\nsd_go:')
    return s[a + 1:b].rstrip('\n')


def source(name):
    p = PROBES[name]
    src = (HERE / p['src']).read_text()
    for k, v in dict(gate=v2_gate(), state=hex(p['state']), ev_press=hex(V2.EV_PRESS)).items():
        src = src.replace('{' + k + '}', v)
    if '{' in src or '}' in src:
        raise ValueError('unsubstituted template field')
    return src


def assemble(src):
    sv = V2.SERVICES
    V2.SERVICES = SERVICES     # same toolchain call as v2, only the symbols the probe uses
    try:
        return V2.assemble(src)
    finally:
        V2.SERVICES = sv


def _dis(lo, hi):
    out = subprocess.run([str(V2.TC / 'mn10300-elf-objdump'), '-b', 'binary', '-m', 'am33-2', '-D', f'--adjust-vma={BASE:#x}',
                          f'--start-address={lo:#x}', f'--stop-address={hi:#x}', str(MAIN)],
                         capture_output=True, text=True, check=True).stdout
    return [(int(m.group(1), 16), m.group(2).strip()) for m in re.finditer(r'^([0-9a-f]{8}):\t[0-9a-f ]+\t(.*)$', out, re.M)]


def _body(start, n=600):
    out = []
    for a, t in _dis(start, start + 0x800)[:n]:
        out.append((a, t))
        if re.match(r'(ret|retf|rets|rti)\b', t):
            break
    return out


def pad_evidence(d=None):
    """Static proof items for 0x622cbcc2 (SD_V2_CRASH 3.1), re-derived from the decoded main."""
    d = d if d is not None else MAIN.read_bytes()
    r = {}
    u = lambda a, n: d[a - BASE:a - BASE + n]
    mgr = 0x622cbc14
    # 1 no 32-bit word at any byte offset equals 0x622cbcc0..c7 in either alias (no abs reference near the pad)
    import numpy as np
    arr = np.frombuffer(d, dtype=np.uint8).astype(np.uint32)
    w = arr[:-3] | (arr[1:-2] << 8) | (arr[2:-1] << 16) | (arr[3:] << 24)
    hits = np.nonzero(((w & 0xbffffff8) == 0x222cbcc0))[0]
    r['abs32_hits_0x[6a]22cbcc0_7'] = [hex(BASE + int(i)) for i in hits]
    # 2 object identity and layout: singleton ctor call, vtable store, +172 u16 and +176 u32 initialisers
    r['singleton_ctor'] = u(0x6076fc20, 6) == b'\xfc\xdc' + struct.pack('<I', mgr) and \
        0x6076fc28 + struct.unpack_from('<h', d, 0x6076fc28 - BASE + 1)[0] == 0x6076fa1f and u(0x6076fc28, 1) == b'\xcd'
    r['ctor_vtable_0x60a69794'] = u(0x6076fa2b, 6) == b'\xfc\xcc' + struct.pack('<I', 0x60a69794) and u(0x6076fa31, 1) == b'\x62'
    r['ctor_movhu_172_movw_176'] = u(0x6076fa6a, 4).hex() == 'fa72ac00' and u(0x6076fa6f, 4).hex() == 'fa12b000'
    # 3 runtime writes by stock into the same object / cache line 0x622cbcc0..df
    r['task_create_writes_mgr172'] = u(0x6076fd57, 4).hex() == 'fad2ac00' and u(0x6076fd95, 2).hex() == 'f072'
    r['next_object_bytes_written_0x622cbcc8_cf'] = all(
        u(0x607707b1 + o, 6) == b'\xfc\x82' + struct.pack('<I', 0x622cbcc8 + i)
        for i, o in enumerate((0, 6, 12, 18, 26, 32, 38, 46)))
    # 4 .bss (boot clear 0x6002046d(0x621caf00, 0xa2796888), call at 0x60020074)
    r['in_bss'] = BSS[0] <= EVM_PAD < BSS[1] and \
        0x60020074 + struct.unpack_from('<h', d, 0x60020074 - BASE + 1)[0] == 0x6002046d
    # 5 every class method (36 vtable slots) and every function after a call to the getter 0x6076fbed touches
    #   +172..+175 only as `movhu (172,aN)`
    slots = []
    for i in range(64):
        v = struct.unpack_from('<I', d, 0x60a69794 - BASE + 4 * i)[0]
        if not 0x60020020 <= v < 0x6143a800:
            break
        slots.append(v)
    XR = V2._load('ep7_xref', ROOT / 'tools/ep7_xref.py')
    calls = sorted(a for k, a in XR.scan(np.frombuffer(d, dtype=np.uint8), [0x6076fbed], short=False)[0x6076fbed]
                   if k.startswith('call'))
    disp = re.compile(r'\((17[2-5]),a\d\)')
    bad = []
    for start in slots:
        bad += [(hex(start), hex(a), t) for a, t in _body(start) if disp.search(t) and not
                (t.startswith('movhu') and '(172,' in t)]
    for c in calls:
        seg = []
        for a, t in _dis(c, c + 0x400)[:200]:
            if re.match(r'(ret|retf)\b', t):
                break
            seg.append((a, t))
        bad += [(hex(c), hex(a), t) for a, t in seg if disp.search(t) and not (t.startswith('movhu') and '(172,' in t)]
    r['vtable_slots'], r['getter_calls'] = len(slots), len(calls)
    r['pad_accesses_in_class_methods_or_getter_users'] = bad
    r['ok'] = (not r['abs32_hits_0x[6a]22cbcc0_7'] and not bad and len(slots) == 36 and len(calls) > 0 and
               all(v for k, v in r.items() if isinstance(v, bool)))
    return r


def make_spec(name):
    p = PROBES[name]
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    src = source(name)
    code, lst, syms, dis = assemble(src)
    if syms['sd_hook'] != CODE_AT:
        raise ValueError('sd_hook must be the first instruction')
    ins = [l.split('\t')[2].split()[0] for l in dis.splitlines() if l.count('\t') >= 2 and l.split('\t')[2].strip()]
    for bad in ('mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'retf'):
        if bad in ins:
            raise ValueError(f'{bad} in probe code')
    # exactly one store to an absolute address (none for P2b), and it targets the probe address
    stores = re.findall(r'\tmov(bu|hu|)\s+[da]\d,\(([0-9a-f]{8})(?: <[^>]*>)?\)', dis)
    want = [] if p['store'] is None else [('bu' if p['width'] == 1 else 'hu', f"{p['state']:08x}")]
    if stores != want:
        raise ValueError(f'absolute stores {stores} != {want}')
    if any(re.search(r'\tmov(bu|hu|)\s+[da]\d,\(\d+,(sp|a\d)\)', l) for l in dis.splitlines()):
        raise ValueError('register-relative store in probe code')
    V2.check_image(d, len(code))
    if p['state'] == SEC3_STATE:
        if not (CODE_AT + len(code) <= SEC3_STATE < V2.SEC3[2]) or d[SEC3_STATE - BASE] != 0xff:
            raise ValueError('section-3 state byte not an erased byte beyond the code')
    else:
        if not BSS[0] <= p['state'] < BSS[1] or p['state'] & 1:
            raise ValueError('event-manager pad not in .bss / not 2-aligned')
        ev = pad_evidence(d)
        if not ev['ok']:
            raise ValueError(f'0x622cbcc2 evidence failed: {ev}')
    tail = d[CODE_AT - BASE:CODE_AT - BASE + len(code)]
    rel = struct.pack('<i', CODE_AT - V2.SITE)
    edits = [dict(kind='0x100', addr=hex(V2.SITE), expect=V2.SITE_STOCK, new='dc' + rel.hex(),
                  why=f'appevent TRIG tracker call {V2.SITE:#x} (call {V2.TRIG:#x},[d2,d3,a2,a3],36) -> jmp sd_hook'),
             dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
                  why=f'SD-crash probe {name} ({len(code)} B) in section-3 FF tail: {p["tests"]}')]
    for e in edits:
        a, n = int(e['addr'], 16), len(bytes.fromhex(e['new']))
        for lo_, hi_, who in V2.RESERVED:
            if a < hi_ and lo_ < a + n:
                raise ValueError(f'edit {e["addr"]} overlaps {who} {lo_:#x}..{hi_:#x}')
    meta = dict(probe=name, tests=p['tests'], code_at=hex(CODE_AT), code_len=len(code), site=hex(V2.SITE),
                site_ret=hex(V2.SITE_RET), trig=hex(V2.TRIG), ev_press=hex(V2.EV_PRESS), state=hex(p['state']),
                state_width=p['width'], state_init=p['init'], store_value=p['store'],
                services={k: hex(v) for k, v in SERVICES.items()}, symbols={k: hex(v) for k, v in syms.items()},
                conflicts='sd_bundles (v1), sd_bundles_v2, other sd_probe builds')
    spec = dict(components=['0x100'], patch=f'sd_probe_{name}', sd_probe=meta, edits=edits)
    return spec, src, lst, code, syms


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--probe', choices=sorted(PROBES), required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    try:
        spec, src, lst, code, syms = make_spec(a.probe)
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    (a.out / 'symbols.json').write_text(json.dumps({k: hex(v) for k, v in syms.items()}, indent=1) + '\n')
    print(f'probe {a.probe}: {len(code)} B at {CODE_AT:#x}; hook {V2.SITE:#x} -> jmp; state {PROBES[a.probe]["state"]:#x}; wrote {a.out}')


if __name__ == '__main__':
    main()
