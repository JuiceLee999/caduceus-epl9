#!/usr/bin/env python3
"""Emulator verification of a BUILT film-menu phase 2a package (offline; emulator only; no camera).

Takes a merged spec with patches/film_menu + patches/sd_bundles_v3 --names (tools/merge_specs.py). Builds the
package in memory (tools/build_package.build()), decodes the patched and restore (= stock) main payloads and runs
the REAL label builders A 0x60df250b / B 0x60df25b5 from them, natively, through a small driver that calls a
builder once per label source and records the label plus d0/d1/a0/a1/sp/d2 after each call. Mapped: section 6
(builders, lists, strings, markers, hooks) READ-ONLY, strlen 0x600daed9 read-only, our memset stub at 0x4700115e
(the one the stock text path calls), the handle halfword 0x622cbcc2 and the heap block READ-ONLY. Writable: only
the output records and the stack. So any store into image RAM (0x60020020-0x6191ffe0), the heap block or the
state faults the run.

  S  static: edits == spec; markers NUL; hook bytes; site `jmp hookX; nop`; FF guards around markers/hooks;
     exactly the 40 phase-2a entries point at the markers (no other word in the image does); no other byte in
     section 6 differs from stock; hook store audit (only the label at a3).
  L  labels, every label source in section 6 (4-aligned {kind 1..12, id, text}: kind 4 with any text, other
     kinds whose text is in section 6 and NUL-terminated within 64 B), both builders, patched vs stock:
       a  h = 0                  b  h = 0xFFFF               c  names loaded (mixed: empty, 1 and 15 characters)
       d  valid h, no 'EP7N'     d2 'EP7N' but no 'EP7B'      d3 misaligned h      d4 h = lim + 1
       f  'EP7N', all names empty                            e  corrupt heap names (16 B no NUL, bytes >= 0x80,
                                                                bytes after a NUL)
     Expected: every record (label 8+66 B and its spill area, d0, d1, a0, a1, sp, d2) and the final registers and
     stack == stock, except in c/e for the marked entries with a non-empty name: label == stock's label for a
     kind-5 entry whose text is the name cut at 15 bytes (bytes +4..+5 = the entry's string id, as written by
     stock before the hook point), d0/d1 = character count, sp/d2 == stock, 15 characters max + NUL.
       d5 aligned h past the pool (block with names there)    d6 names present but no 'EP7N'
     Plus 18 synthetic boundary entries (kind 4 with text MARK-1, MARK+8, MARK+9, ...; kinds 1-3, 5-12 pointing
     at the markers): always stock.
     Full candidate set for a, b, c, d; marked + all kind-4 sources for the other states.
  X  integration: the REAL --names loader (tools/ep7_verify_sd_bundles_v3.py fixture) reads the card file, its
     state + kept block feed the label run: the 40 entries show the card names; a 544-byte file -> stock labels.
  M  mutations of the hook code: each must make L (reduced) fail.

Usage: tools/ep7_verify_film_menu.py SPEC.json [--part S,L,X,M] [--card FILE] [--json out.json]
"""
import argparse, importlib.util, json, struct, subprocess, sys, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
from penf_emulator import Region, execute  # noqa: E402
import numpy as np  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


FM = _load('ep7_film_menu_build', ROOT / 'patches/film_menu/build.py')
B3 = FM.B3
BIN = _load('ep7_bundles_bin', ROOT / 'tools/ep7_bundles_bin.py')
BASE = B3.BASE
SEC6 = FM.SEC6
MARK = FM.MARK
STATE, POOL, LIM = B3.STATE, B3.POOL, B3.LIM
NAMES_LO, MARK_OFF = B3.NAMES_LO, B3.MARK_OFF
MEMSET_AT = 0x4700115e
MEMSET_CODE = bytes.fromhex('a500c809f0504129ffc9fbdfa008')   # tools/ep7_verify_bundles.py (self-tested there and below)
STRLEN = (0x600daed0, 0x600daf00)
DRV, TBL, OUT, STK, REF = 0x18100000, 0x18400000, 0x19000000, 0x18300000, 0x18600000
SP0 = STK + 0x1000
REC = 192                         # +0 d0 +4 d1 +8 a0 +12 a1 +16 sp +20 d2, +24..31 guard, +32 label (8+66, spill to +192)
LBL = 32
FILL = 0xee
BLK = POOL + 0x2400               # heap block P (the v3 verifier's BUF_IN), h = BLK - POOL + 1
H_OK = BLK - POOL + 1
CHUNK = 6000
SYN = 0x18700000                  # synthetic boundary entries (mapped read-only in every run, stock and patched)
SYN_ENTRIES = [(4, MARK - 1), (4, MARK + 8), (4, MARK + 9), (4, MARK + 0x100), (4, MARK - 0x100), (4, 0),
               (4, 0xffffffff), (1, MARK), (2, MARK + 3), (5, MARK + 7), (10, MARK + 1), (11, MARK + 2), (9, MARK + 4),
               (12, MARK + 5), (6, MARK + 6), (3, MARK), (7, MARK + 1), (8, MARK + 2)]
SYN_DATA = b''.join(struct.pack('<IHHI', 54, k, 2749, t) for k, t in SYN_ENTRIES)
SYN_SRCS = [SYN + 12 * i + 4 for i in range(len(SYN_ENTRIES))]


def sl(img, lo, hi):
    return bytes(img[lo - BASE:hi - BASE])


# ------------------------------------------------------------------ driver
DRIVER = r"""
 .am33_2
 .text
 .global _start
_start:
 mov {tbl},a2
 mov {out},a3
 mov {n},d3
 mov 0xd2d2d2d2,d2
loop:
{body}
 mov d0,(a3)
 mov d1,(4,a3)
 mov a0,(8,a3)
 mov a1,(12,a3)
 mov sp,a0
 mov a0,(16,a3)
 mov d2,(20,a3)
 add 4,a2
 add {rec},a3
 add -1,d3
 bne loop
done:
 nop
 nop
"""
BODY_A = """ mov (a2),a1                      /* entry = list base, count 1, value = entry value */
 mov (a1),d0
 mov 1,d1
 mov a3,a0
 add {lbl},a0
 mov a0,(4,sp)                    /* label pointer: caller's (4,sp) */
 mov 0x0a0a0a0a,a0
 call builder_a,[d2,d3,a2,a3],24"""
BODY_B = """ mov (a2),a1                      /* label source */
 mov a3,d0
 add {lbl},d0                     /* label pointer */
 mov 0x0a0a0a0a,a0
 mov 0x1d1d1d1d,d1
 call builder_b,[d2,a2,a3],20"""
_drv_cache = {}


def driver(which, n):
    key = (which, n)
    if key in _drv_cache:
        return _drv_cache[key]
    body = (BODY_A if which == 'A' else BODY_B).replace('{lbl}', str(LBL))
    src = DRIVER.replace('{body}', body).replace('{tbl}', hex(TBL)).replace('{out}', hex(OUT)).replace('{n}', str(n)) \
        .replace('{rec}', str(REC))
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'd.s').write_text(src)
        TC = B3.TC
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'd.o', t / 'd.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(DRV), '-e', '_start', f'--defsym=builder_a={FM.BUILDER_A:#x}',
                        f'--defsym=builder_b={FM.BUILDER_B:#x}', '-o', t / 'd.elf', t / 'd.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'd.elf', t / 'd.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'd.elf'], check=True, capture_output=True, text=True).stdout
        done = next(int(l.split()[0], 16) for l in nm.splitlines() if l.endswith(' done'))
        code = (t / 'd.bin').read_bytes()
    _drv_cache[key] = (code, done)
    return code, done


def state_regions(st):
    """st = dict(h=int, block=bytes|None, at=int)."""
    regs = [Region('state', STATE - 2, struct.pack('<HHI', 0x4242, st['h'], 0x5a5a5a5a), 'r')]
    if st.get('block') is not None:
        regs.append(Region('heap', st.get('at', BLK), st['block'], 'r'))
    return regs


def render(img, which, sources, st, extra=()):
    """Run builder `which` over `sources` (label-source addresses; entry = source - 4 for A).
    -> (records list of bytes, final regs, stack bytes, fault)."""
    out_recs, regs_all, stk_all = [], [], []
    sec6 = sl(img, SEC6[0], SEC6[1])
    m0 = MARK - SEC6[0]
    if sec6[m0:m0 + 8] == b'\xff' * 8:            # stock reference: give it the 8 NUL marker cells (pure data,
        sec6 = sec6[:m0] + bytes(8) + sec6[m0 + 8:]  # referenced only by the 40 entry edits, see S)
    strl = sl(img, *STRLEN)
    for i in range(0, len(sources), CHUNK):
        part = sources[i:i + CHUNK]
        code, done = driver(which, len(part))
        tbl = b''.join(struct.pack('<I', s - 4 if which == 'A' else s) for s in part)
        regions = [Region('drv', DRV, code, 'rx'), Region('tbl', TBL, tbl, 'r'),
                   Region('out', OUT, bytes([FILL]) * (REC * len(part) + 64), 'rw', True),
                   Region('stack', STK, bytes([0x5c]) * 0x2000, 'rw', True),
                   Region('sec6', SEC6[0], sec6, 'rx'), Region('strlen', STRLEN[0], strl, 'rx'),
                   Region('memset', MEMSET_AT, MEMSET_CODE, 'rx'), Region('syn', SYN, SYN_DATA, 'r')] + \
            state_regions(st) + list(extra)
        r = execute(regions, dict(pc=DRV, sp=SP0, d0=0, d1=0, a0=0, a1=0, mdr=0x3d3d3d3d), done,
                    limit=60_000_000, timeout=170)
        if r['fault'] or r['registers']['pc'] != done:
            return None, None, None, dict(fault=r['fault'], pc=hex(r['registers']['pc']), chunk=i)
        m = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
        o = m['out']
        out_recs += [o[k * REC:(k + 1) * REC] for k in range(len(part))]
        if o[REC * len(part):] != bytes([FILL]) * 64:
            return None, None, None, dict(fault='write past the last record', chunk=i)
        regs_all.append({k: r['registers'][k] for k in ('d2', 'd3', 'a2', 'a3', 'sp', 'mdr', 'lir', 'lar')})
        stk_all.append(m['stack'])
    return out_recs, regs_all, stk_all, None


# ------------------------------------------------------------------ candidates
def candidates(stock):
    lo, hi = SEC6[0], FM.STOCK_END + 1
    n = (hi - lo) // 4
    w = np.frombuffer(stock[lo - BASE:lo - BASE + 4 * (n + 1)], np.uint32)
    kind, text = w[:n] & 0xffff, w[1:n + 1]
    ink = (kind >= 1) & (kind <= 12)
    ins6 = (text >= SEC6[0]) & (text < SEC6[1])
    k4 = kind == 4
    out = []
    for i in np.nonzero(ink & (k4 | ins6))[0]:
        s = lo + 4 * int(i)
        if s - 4 < SEC6[0]:
            continue
        if not k4[i]:
            t = int(text[i])
            if b'\0' not in stock[t - BASE:t - BASE + 64]:
                continue
        out.append(s)
    return out + SYN_SRCS


# ------------------------------------------------------------------ heap blocks
def block(names=None, raw=None, ep7b=True, ep7n=True):
    b = bytearray(b'\xc3' * 1024)
    b[:32] = B3.V1.header(0) if ep7b else b'EP7C' + B3.V1.header(0)[4:]
    b[32:544] = bytes(range(256)) * 2
    b[NAMES_LO:NAMES_LO + 136] = bytes(136)
    if names is not None:
        for k, nm in enumerate(names):
            b[NAMES_LO + 16 * k:NAMES_LO + 16 * k + 16] = (nm or '').encode().ljust(16, b'\0')
    if raw is not None:
        b[NAMES_LO:NAMES_LO + 128] = raw
    if ep7n:
        b[MARK_OFF:MARK_OFF + 4] = b'EP7N'
    return bytes(b)


NAMES_C = ['Classic Neg', None, 'W' * 15, 'Portra', 'x', 'Acros 100', None, 'Mono ~ #4!']
RAW_E = bytearray(128)
RAW_E[0:16] = b'ABCDEFGHIJKLMNOP'                    # 16 bytes, no NUL -> 15
RAW_E[16:32] = b'\x80\xff\xa9\x7f\x01Z' + bytes(10)  # high / control bytes: sign-extended like stock widen
RAW_E[48:64] = b'AB\0CD\0EF' + bytes(8)            # bytes after a NUL are not shown
RAW_E[112:128] = b'\xff' * 16                       # MONO4: 16 x 0xFF, no NUL
RAW_E = bytes(RAW_E)


def states():
    return {
        'a h=0': dict(h=0, block=block(NAMES_C)),
        'b h=0xFFFF': dict(h=0xffff, block=block(NAMES_C)),
        'c names': dict(h=H_OK, block=block(NAMES_C)),
        'd no EP7N': dict(h=H_OK, block=block(None, ep7n=False)),
        'd2 no EP7B': dict(h=H_OK, block=block(NAMES_C, ep7b=False)),
        'd3 misaligned h': dict(h=H_OK + 1, block=b'\0' + block(NAMES_C)[:-1]),
        'd4 h=lim+1': dict(h=LIM + 1, block=block(NAMES_C)),
        'd5 aligned h past the pool': dict(h=LIM + 4, block=block(NAMES_C), at=POOL + LIM + 3),
        'd6 names but no EP7N': dict(h=H_OK, block=block(NAMES_C, ep7n=False)),
        'f empty names': dict(h=H_OK, block=block([None] * 8)),
        'e corrupt names': dict(h=H_OK, block=block(raw=RAW_E)),
    }


def shown(st):
    """-> per slot: bytes the hook should show (<= 15, cut at NUL), or None (stock)."""
    b = st['block']
    if not (1 <= st['h'] <= LIM and (st['h'] - 1) % 4 == 0):
        return [None] * 8
    if st.get('at', BLK) != BLK or b[:4] != b'EP7B' or b[MARK_OFF:MARK_OFF + 4] != b'EP7N':
        return [None] * 8
    out = []
    for k in range(8):
        nm = b[NAMES_LO + 16 * k:NAMES_LO + 16 * k + 15].split(b'\0')[0]
        out.append(nm or None)
    return out


def ref_records(stock, which, texts, ids):
    """Stock builder over synthetic kind-5 entries whose text is each name: the expected kind-5 labels."""
    data = bytearray()
    strs = bytearray()
    STRS = REF + 0x1000
    for k, t in enumerate(texts):
        ptr = STRS + len(strs)
        strs += t + b'\0'
        data += struct.pack('<IHHI', 0x77 + k, 5, ids[k], ptr)
    srcs = [REF + 12 * k + 4 for k in range(len(texts))]
    recs, regs, stk, f = render(stock, which, srcs, dict(h=0), extra=[Region('ref', REF, bytes(data), 'r'),
                                                                       Region('strs', STRS, bytes(strs) + b'\0', 'r')])
    return recs, f


# ------------------------------------------------------------------ checks
def compare_state(stock, patched, which, srcs, marked, st, stock_run, label):
    """-> (ok, problems, n_named)."""
    probs = []
    recs, regs, stk, f = render(patched, which, srcs, st)
    if f:
        return False, [f'{label}: fault {f}'], 0
    s_recs, s_regs, s_stk = stock_run
    want = shown(st)
    named_idx = [(i, marked[s]) for i, s in enumerate(srcs) if s in marked and want[marked[s][0]] is not None]
    named = {i for i, _ in named_idx}
    bad = [i for i in range(len(srcs)) if i not in named and recs[i] != s_recs[i]]
    if bad:
        i = bad[0]
        probs.append(f'{label}: {len(bad)} records != stock, first source {srcs[i]:#x}: '
                     f'{recs[i][:48].hex()} vs {s_recs[i][:48].hex()}')
    if regs != s_regs:
        probs.append(f'{label}: final registers != stock {regs} {s_regs}')
    if stk != s_stk and not named:
        probs.append(f'{label}: stack != stock')
    live = [x[SP0 - STK + 8:] for x in stk]
    if any(l != bytes([0x5c]) * len(l) for l in live):
        probs.append(f'{label}: live stack above the driver sp changed')
    if named:
        texts = [want[k] for _, (k, sid) in named_idx]
        ids = [sid for _, (k, sid) in named_idx]
        r_recs, f2 = ref_records(stock, which, texts, ids)
        if f2:
            return False, probs + [f'{label}: reference run fault {f2}'], len(named)
        for (i, (k, sid)), rr in zip(named_idx, r_recs):
            p = recs[i]
            exp = bytearray(rr)
            exp[LBL + 4:LBL + 6] = struct.pack('<H', sid)        # string id written by stock before the hook point
            exp[8:16] = p[8:16]                                  # a0/a1: scratch, not compared for name labels
            n = len(want[k])
            txt = p[LBL + 8:LBL + 8 + 66]
            if bytes(exp) != p:
                probs.append(f'{label}: source {srcs[i]:#x} slot {k}: {p[:16].hex()} {p[LBL:LBL + 48].hex()} != '
                             f'{bytes(exp)[:16].hex()} {bytes(exp)[LBL:LBL + 48].hex()}')
            elif not (struct.unpack_from('<H', p, LBL)[0] == 5 and n <= 15 and txt[2 * n:] == bytes(66 - 2 * n)
                      and struct.unpack_from('<I', p, 0)[0] == n):
                probs.append(f'{label}: source {srcs[i]:#x}: label not kind 5 / not terminated / d0 != {n}')
    return not probs, probs, len(named)


def marked_map(patched, spec):
    out = {}
    for e in spec['film_menu']['entries']:
        s = int(e['source'], 16)
        out[s] = (e['slot'], e['string_id'])
        if struct.unpack_from('<I', patched, s + 4 - BASE)[0] != MARK + e['slot']:
            raise AssertionError('entry edit missing in the package')
    return out


def t_labels(stock, patched, cands, marked, which_states, *, full=('a h=0', 'b h=0xFFFF', 'c names', 'd no EP7N'),
             log=print):
    rows, ok = [], True
    k4 = [s for s in cands if s in SYN_SRCS or struct.unpack_from('<H', stock, s - BASE)[0] == 4]
    for which in ('A', 'B'):
        sets = {}
        for st_name in which_states:
            srcs = cands if st_name in full else sorted(set(k4) | set(marked))
            key = len(srcs)
            if key not in sets:
                t0 = time.time()
                sr = render(stock, which, srcs, dict(h=0))
                if sr[3]:
                    return False, [dict(builder=which, state='stock', ok=False, problems=[f'stock fault {sr[3]}'])]
                sets[key] = sr[:3]
                log(f'      stock builder {which}: {len(srcs)} sources in {time.time() - t0:.1f}s')
            st = states()[st_name]
            t0 = time.time()
            g, probs, nn = compare_state(stock, patched, which, srcs, marked, st, sets[key], st_name)
            ok &= g
            rows.append(dict(builder=which, state=st_name, sources=len(srcs), named=nn, ok=g, problems=probs[:5],
                             secs=round(time.time() - t0, 1)))
            log(f"   {'PASS' if g else 'FAIL'} builder {which} state '{st_name}': {len(srcs)} sources, {nn} name labels")
            for p in probs[:3]:
                log('        ' + p[:400])
    return ok, rows


def memset_selftest():
    C = 0x18100000
    r = execute([Region('ms', MEMSET_AT, MEMSET_CODE, 'rx'), Region('buf', 0x18200000, b'\xaa' * 96, 'rw', True),
                 Region('c', C, b'\xdd' + struct.pack('<i', MEMSET_AT - C) + b'\xa0\x08\xcb', 'rx'),
                 Region('stack', STK, bytes(0x2000), 'rw')],
                {'pc': C, 'sp': SP0, 'a0': 0x18200008, 'd0': 0, 'd1': 66}, C + 7)
    b = bytes.fromhex(r['memory'][0]['hex'])
    return not r['fault'] and b == b'\xaa' * 8 + bytes(66) + b'\xaa' * 22


# ------------------------------------------------------------------ static
def check_static(spec, stock, patched):
    r = {}
    meta = spec['film_menu']
    ed = {int(e['addr'], 16): bytes.fromhex(e['new']) for e in spec['edits']}
    fm = [e for e in spec['edits'] if e.get('source', '').endswith('menu/edits.json') or 'film menu' in e['why']]
    r['edits_eq_spec'] = all(sl(patched, a, a + len(ed[a])) == ed[a] for a in ed)
    r['markers_nul'] = sl(patched, MARK, MARK + 8) == bytes(8)
    hooks = {p: (int(v['at'], 16), v['len']) for p, v in meta['hooks'].items()}
    guards = [(FM.CLAIM[0], hooks['A'][0]), (hooks['A'][0] + hooks['A'][1], MARK), (MARK + 8, hooks['B'][0]),
              (hooks['B'][0] + hooks['B'][1], FM.CLAIM[1])]
    r['guards_ff'] = all(set(sl(patched, a, b)) == {0xff} for a, b in guards)
    r['sites_jmp_nop'] = all(patched[s - BASE] == 0xdc and s + struct.unpack_from('<i', patched, s + 1 - BASE)[0] == hooks[p][0]
                             and patched[s + 5 - BASE] == 0xcb for p, (s, *_r) in FM.SITES.items())
    # changed bytes in section 6 == exactly the film-menu edit spans
    a = np.frombuffer(stock, np.uint8)
    b = np.frombuffer(patched, np.uint8)
    diff = set(int(i) + BASE for i in np.nonzero(a != b)[0] if SEC6[0] <= int(i) + BASE < SEC6[1])
    spans = set()
    for e in fm:
        x = int(e['addr'], 16)
        spans |= set(range(x, x + len(bytes.fromhex(e['new']))))
    r['sec6_diff_only_film_menu'] = diff <= spans and all(SEC6[0] <= x < SEC6[1] for x in spans)
    # words pointing at the markers: exactly the 40 entry text words
    w = [b[i:len(b) - 3 + i] for i in range(4)]
    n = len(b) - 3
    word = w[0].astype(np.int64) | w[1].astype(np.int64) << 8 | w[2].astype(np.int64) << 16 | w[3].astype(np.int64) << 24
    hits = set(int(i) + BASE for i in np.nonzero((word >= MARK) & (word < MARK + 8))[0])
    want = {int(e['source'], 16) + 4 for e in meta['entries']}
    r['marker_refs_exactly_40_entries'] = hits == want and len(want) == 40
    st = []
    for p, (at, ln) in hooks.items():
        st += B3.store_audit(B3.disasm(sl(patched, at, at + ln), at))
    r['hook_stores_label_only'] = [t for _, t, _, _ in st] == ['movhu d0,(a3)', 'movhu d0,(a1)', 'movhu d0,(a1)'] * 2
    r['memset_stub_selftest'] = memset_selftest()
    return all(r.values()), r


# ------------------------------------------------------------------ integration with the real loader
def t_integration(stock, patched, spec, card, marked, log=print):
    W3 = _load('ep7_verify_sd_bundles_v3', ROOT / 'tools/ep7_verify_sd_bundles_v3.py')
    W3.NAMES = True
    R = W3.Runner(stock, spec['sd_bundles_v3']['code_len'])
    rows, ok = [], True
    F, _ = W3.V1.files()
    for label, data in (('card file', card), ('544-byte file (no names)', F['mono'])):
        c = W3.V1.Case(label, data, expect='load')
        g, probs, p = R.single(patched, c)
        st = struct.unpack_from('<H', p['mem']['evm'], W3.ST_OFF)[0]
        blk = p['mem']['heap'][0x400:0x800]
        names = BIN.names_of(data) if len(data) == BIN.FILE_LEN_N else None
        ok &= g and st == W3.BUF_IN - POOL + 1 and W3.BUF_IN == BLK
        rows.append(dict(step=f'loader run: {label}', ok=g and st == H_OK, state=hex(st), problems=probs))
        srcs = sorted(marked)
        stt = dict(h=st, block=blk)
        exp = shown(stt)
        want = [(n.encode() if n else None) for n in names] if names else [None] * 8
        good = exp == want
        for which in ('A', 'B'):
            sr = render(stock, which, srcs, dict(h=0))
            g2, probs2, nn = compare_state(stock, patched, which, srcs, marked, stt, sr[:3], f'{label} {which}')
            good &= g2 and nn == sum(1 for s in srcs if want[marked[s][0]])
            rows.append(dict(step=f'labels {which}: {label}', ok=g2, named=nn, problems=probs2[:3]))
        ok &= good
        log(f"   {'PASS' if good else 'FAIL'} {label}: state {st:#x}, names {[n for n in (names or []) if n]}")
    return ok, rows


# ------------------------------------------------------------------ mutations
def mutations(patched, spec):
    meta = spec['film_menu']
    hooks = {p: (int(v['at'], 16), v['len']) for p, v in meta['hooks'].items()}
    out = []

    def mut(name, p, pat, new, off=0, nth=0):
        at, ln = hooks[p]
        seg = sl(patched, at, at + ln)
        idx, k = [], -1
        while True:
            k = seg.find(pat, k + 1)
            if k < 0:
                break
            idx.append(k)
        if len(idx) <= nth:
            raise AssertionError(f'mutation {name}: pattern not found')
        m = bytearray(patched)
        i = at + idx[nth] + off - BASE
        m[i:i + len(new)] = new
        out.append((name, bytes(m)))
    mut('A: marker range 8 -> 9', 'A', b'\xa0\x08\xc6', b'\xa0\x09')
    mut('B: kind test 4 -> 5', 'B', b'\xa0\x04\xc8', b'\xa0\x05')
    mut('A: EP7N check skipped', 'A', b'\xfc\xc8' + b'EP7N', b'\xfc\xc8' + b'EP7N\xc9\x02')
    mut('B: EP7B check skipped', 'B', b'\xfc\xc8' + b'EP7B', b'\xfc\xc8' + b'EP7B\xc9\x02')
    mut('A: alignment test removed', 'A', b'\xf8\xec\x03', b'\xf8\xec\x00')
    mut('B: handle bound lim -> lim+4', 'B', b'\xfc\xc8' + struct.pack('<I', LIM), b'\xfc\xc8' + struct.pack('<I', LIM + 4))
    mut('A: copy limit 15 -> 16', 'A', b'\xa5\x0f', b'\xa5\x10')
    mut('B: clear 33 -> 32 halfwords', 'B', b'\x85\x21', b'\x85\x20')
    mut('A: extb removed', 'A', b'\x10\xf0\x71', b'\xcb')
    mut('B: a0 not restored on replay', 'B', b'\x5c\x04', b'\xcb\xcb')
    mut('A: replay cmp 1 -> 2', 'A', b'\xf0\x63\xa0\x01', b'\xf0\x63\xa0\x02', nth=0)
    mut('B: slot shift 4 -> 3', 'B', b'\xf8\xc0\x04', b'\xf8\xc0\x03')
    mut('A: count not returned in d0', 'A', b'\x84\xdc', b'\xcb')
    mut('B: empty-slot test removed', 'B', b'\xa0\x00\xc8', b'\xa0\x00\xc8\x02', nth=0)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edits', type=Path)
    ap.add_argument('--part', default='S,L,X,M')
    ap.add_argument('--states', help='comma list of L states (default all)')
    ap.add_argument('--card', type=Path, help='680-byte card file for X (default: built from bundles/lachlan_v3_names.json)')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    parts = set(a.part.split(','))
    spec = json.loads(a.edits.read_text())
    if 'film_menu' not in spec:
        sys.exit("spec lacks 'film_menu'")
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    patched, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    marked = marked_map(patched, spec)
    res = []

    def report(test, passed, **kw):
        res.append(dict(test=test, passed=passed, **kw))
        print(f"{'PASS' if passed else 'FAIL'}  {test}", flush=True)
        if not passed and 'detail' in kw:
            print('      ', json.dumps(kw['detail'], default=str)[:1500])
    if 'S' in parts:
        g, det = check_static(spec, stock, patched)
        report('S static: edits, markers, guards, sites, section-6 diff, marker references, hook stores, memset stub', g, detail=det)
    cands = candidates(stock) if parts & {'L', 'M'} else []
    if cands:
        print(f'      {len(cands)} label sources in section 6 ({sum(1 for s in cands if s in marked)} marked)', flush=True)
        if not set(marked) <= set(cands):
            report('L candidate set contains the 40 marked entries', False)
    if 'L' in parts:
        sts = a.states.split(',') if a.states else list(states())
        g, rows = t_labels(stock, patched, cands, marked, sts)
        report(f'L labels: {len(rows)} builder x state runs, patched vs stock ({len(cands)} sources)', g, rows=rows)
    if 'X' in parts:
        card = a.card.read_bytes() if a.card else BIN.build(ROOT / 'bundles/lachlan_v3_names.json')[0]
        g, rows = t_integration(stock, patched, spec, card, marked)
        report('X real --names loader -> label hook (card file names; 544-byte file stock)', g, rows=rows)
    if 'M' in parts:
        k4 = [s for s in cands if s not in SYN_SRCS and struct.unpack_from('<H', stock, s - BASE)[0] == 4]
        sample = sorted(set(marked) | set(k4[::25]) | set(cands[::400]) | set(SYN_SRCS))
        mres = []
        for name, img in mutations(patched, spec):
            try:
                g, _ = t_labels(stock, img, sample, marked, ['a h=0', 'c names', 'd no EP7N', 'e corrupt names', 'd3 misaligned h',
                                                               'd4 h=lim+1', 'd2 no EP7B', 'f empty names',
                                                               'd5 aligned h past the pool', 'd6 names but no EP7N'],
                                full=('a h=0', 'c names'), log=lambda *x: None)
            except Exception:
                g = False
            mres.append(dict(mutation=name, detected=not g))
            print(f"{'PASS' if not g else 'FAIL'}  M mutation '{name}' detected", flush=True)
        report(f'M {sum(m["detected"] for m in mres)}/{len(mres)} hook mutations detected', all(m['detected'] for m in mres), rows=mres)
    allok = all(r['passed'] for r in res)
    print(f"{'PASS' if allok else 'FAIL'}  overall (parts {a.part}); package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.edits), parts=a.part, package=info, passed=allok, results=res,
                                          scope='emulator only; no camera contacted'), indent=1, default=str))
    sys.exit(0 if allok else 1)


if __name__ == '__main__':
    main()
