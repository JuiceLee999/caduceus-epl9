#!/usr/bin/env python3
"""v0.26 piece: vertical video rotation (docs/VIDEO_ROTATION.md). A layer: apply(spec) -> spec. Offline, no camera.

  .venv/bin/python -I patches/v026_rot/build.py releases/v0.25/edits.json --out generated/v026_rot/edits.json

Build fails on: any overlap with the incoming spec, a code reference into the claim other than the dead EVF step-table word,
any evidence change for the latch byte, an absolute store other than the latch, or a store through a register other than the matrix.
"""
import argparse, copy, importlib.util, json, re, struct
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


SB3 = _load('ep7_sd_bundles_v3_build', ROOT / 'patches/sd_bundles_v3/build.py')
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE = 0x60020020
AT, END = 0x601e24ec, 0x601e25ec
SRC = 'patches/v026_rot'
LATCH = 0x6203c8ba
ORIENT, STATE, MUTE, TABLE = 0x6006d157, 0x6203c8a0, 0x6203c89c, 0x61b21858
START, START_CALL, START_RET = 0x603d4027, 0x603d421e, 0x603d402c
FREE, FREE_CALL, FREE_RET = 0x603d4053, 0x603d43af, 0x603d4058
MAT, MAT_RET = 0x61308ad0, 0x61308ad6
SITES = {START: 'cdf701f020', FREE: 'cd5c03f020', MAT: 'fad0900043' + '04'}
STEP_WORDS = {0x601e3cf8: 0x601e253c}              # dead EVF step-7 B table start, the only pointer into the claim
STEP_G = (0x601e3cf4, 0x601e243c)                  # step-7 G table runs into the claim: its start word is before AT
ALIASES = (0, 0x40000000, 0x80000000, 0xc0000000)
SEC1_LOGICAL = 0x40757800 - 0x600d7800            # section-1 descriptor (loader 0x60027068): flash-logical alias of the claim
CLEAR = (0x62038100, 0x6203c934)                   # boot clear 0x6002046d(d0, d1), call at 0x60020059


def image(spec):
    b = bytearray(STOCK.read_bytes())
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16) - BASE
            n = bytes.fromhex(e['new'])
            b[a:a + len(n)] = n
    return bytes(b)


def words(d):
    a = np.frombuffer(d, np.uint8).astype(np.int64)
    return a[:-3] | (a[1:-2] << 8) | (a[2:-1] << 16) | (a[3:] << 24)


def jmp(at, dst):
    return b'\xdc' + struct.pack('<i', dst - at)


def code_refs(d):
    """Every byte offset: an absolute word (any alias) or a call / jmp displacement into the claim, other than the step-table word."""
    w = words(d)
    hits = set()
    for off in ALIASES + (SEC1_LOGICAL & 0xffffffff,):
        lo = (AT + off) & 0xffffffff
        hits |= {int(i) + BASE for i in np.nonzero((w >= lo) & (w < lo + (END - AT)))[0]}
    bad = sorted(h for h in hits if h not in STEP_WORDS)
    for k, v in STEP_WORDS.items():
        if struct.unpack_from('<I', d, k - BASE)[0] != v or k not in hits:
            raise SystemExit(f'step-table word {k:#x} moved')
    if struct.unpack_from('<I', d, STEP_G[0] - BASE)[0] != STEP_G[1]:
        raise SystemExit('step-7 G word moved')
    rel = []
    i = np.frombuffer(d, np.uint8).astype(np.int64)
    n = len(i) - 8
    pc = np.arange(n, dtype=np.int64) + BASE
    def s16(o):
        v = i[o:n + o] | (i[o + 1:n + o + 1] << 8)
        return np.where(v >= 0x8000, v - 0x10000, v)
    def s32(o):
        v = i[o:n + o] | (i[o + 1:n + o + 1] << 8) | (i[o + 2:n + o + 2] << 16) | (i[o + 3:n + o + 3] << 24)
        return np.where(v >= 0x80000000, v - 0x100000000, v)
    b0, b1 = i[:n], i[1:n + 1]
    for name, m, t in (('call16', b0 == 0xcd, pc + s16(1)), ('call32', b0 == 0xdd, pc + s32(1)), ('jmp16', b0 == 0xcc, pc + s16(1)), ('jmp32', b0 == 0xdc, pc + s32(1)),
                       ('calls16', (b0 == 0xfa) & (b1 == 0xff), pc + s16(2)), ('calls32', (b0 == 0xfc) & (b1 == 0xff), pc + s32(2))):
        rel += [(name, int(x) + BASE, int(t[x])) for x in np.nonzero(m & (t >= AT) & (t < END))[0]]
    return bad, rel


def _decode(d, site):
    """The one instruction holding the 4-byte word at `site`, or None if no decode of it fits (not an instruction word)."""
    for back in (2, 1, 3):
        s = site - back
        ins = SB3.disasm(d[s - BASE:s - BASE + 12], s)
        if ins and ins[0][0] == s and len(ins) > 1 and ins[1][0] - s >= back + 4:
            return f'{ins[0][1]} {ins[0][2]}'
    return None


def latch_evidence(d):
    """0x6203c8ba: 2 bytes of padding between the sensor module's u16 at 0x6203c8b8 and its u32 at 0x6203c8bc."""
    w = words(d)
    m = w & 0x3fffffff
    r = {}
    r['abs_hits_latch_pair'] = [hex(int(i) + BASE) for i in np.nonzero((m == (LATCH & 0x3fffffff)) | (m == ((LATCH + 1) & 0x3fffffff)))[0]]
    uses = {}
    for t in range(MUTE, LATCH + 6):
        for i in np.nonzero(m == (t & 0x3fffffff))[0]:
            uses.setdefault(t, []).append(_decode(d, int(i) + BASE))
    r['u16_only_movhu'] = bool(uses.get(0x6203c8b8)) and all(x and re.match(r'movhu\b', x) for x in uses[0x6203c8b8])
    r['next_u32'] = bool(uses.get(0x6203c8bc)) and all(x and x.startswith('mov ') and '(0x6203c8bc)' in x for x in uses[0x6203c8bc])
    r['no_address_taken'] = all(x and re.search(r'\(0x[0-9a-f]{8}\)', x) for v in uses.values() for x in v)
    r['module_addrs'] = sorted(hex(k) for k in uses)
    r['stock_writes_same_line'] = any(x == 'mov a2,(0x6203c8a0)' for x in uses.get(STATE, []))
    r['same_line_as_state'] = LATCH & ~31 == STATE & ~31
    boot = (struct.unpack_from('<I', d, 0x6002004d + 2 - BASE)[0], struct.unpack_from('<I', d, 0x60020053 + 2 - BASE)[0])
    r['boot_clear_range'] = boot == (CLEAR[1], CLEAR[0]) and CLEAR[0] <= LATCH < CLEAR[1]
    r['boot_clear_call'] = 0x60020059 + struct.unpack_from('<h', d, 0x60020059 + 1 - BASE)[0] == 0x6002046d
    r['not_in_image'] = not SB3.in_image(LATCH)
    r['ok'] = (not r['abs_hits_latch_pair'] and all(v for k, v in r.items() if isinstance(v, bool)))
    return r


def audit(code, syms):
    ins = SB3.disasm(code, AT, syms['rot_end'])
    if any(op in {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap', 'calls', 'rets', 'rti'} for _, op, _ in ins):
        raise SystemExit('forbidden instruction')
    n = dict(abs=0, ind=0, sp=0)
    for a, t, k, tgt in SB3.store_audit(ins):
        n[k] += 1
        if k == 'abs' and (tgt != LATCH or SB3.in_image(tgt)):
            raise SystemExit(f'{a:#x} absolute store {t}')
        if k == 'ind' and not re.fullmatch(r'mov d0,\((48|52|56|60|64|68|72|76|80),a0\)', t):
            raise SystemExit(f'{a:#x} store {t}')
    if n['abs'] != 2 or not 9 <= n['ind'] <= 45:
        raise SystemExit(f'store counts {n}')
    return n


def apply(spec):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    if 'v026_rot' in spec:
        raise SystemExit('already applied')
    for s, h in SITES.items():
        if stock[s - BASE:s - BASE + len(h) // 2].hex() != h:
            raise SystemExit(f'site {s:#x} stock bytes differ')
    if stock[0x613714d8 - BASE:0x613714d8 - BASE + 36] != struct.pack('<9I', 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000):
        raise SystemExit('video identity constant differs')
    d = image(spec)
    bad, rel = code_refs(d)
    if bad or rel:
        raise SystemExit(f'references into {AT:#x}..{END:#x}: abs {[hex(x) for x in bad]} rel {rel}')
    ev = latch_evidence(d)
    if not ev['ok']:
        raise SystemExit(f'latch evidence failed: {ev}')
    code, _, syms, _ = SB3.assemble((ROOT / SRC / 'rot.s.in').read_text(), AT, dict(
        ep7_orient=ORIENT, ep7_latch=LATCH, ep7_rec_start=START_CALL, ep7_start_ret=START_RET, ep7_rec_free=FREE_CALL, ep7_free_ret=FREE_RET, ep7_mat_ret=MAT_RET))
    if syms['rot_start'] != AT or AT + len(code) > END:
        raise SystemExit(f'code {len(code)} B does not fit')
    stores = audit(code, syms)
    want = {AT: code, START: jmp(START, syms['rot_start']), FREE: jmp(FREE, syms['rot_free']), MAT: jmp(MAT, syms['rot_mat']) + b'\xcb'}
    for x in spec['edits']:
        if x['kind'] == '0x100' and not x['addr'].startswith('off:'):
            a, n = int(x['addr'], 16), len(x['new']) // 2
            for s, c in [(AT, END - AT)] + [(k, len(v)) for k, v in want.items() if k != AT]:
                if a < s + c and s < a + n:
                    raise SystemExit(f'overlap {x["addr"]} with {s:#x}')
    for a, b in want.items():
        spec['edits'].append(dict(kind='0x100', addr=hex(a), expect=stock[a - BASE:a - BASE + len(b)].hex(), new=b.hex(), source=SRC,
                                  why=f'v0.26 video rotation: {"stubs (dead EVF step-7 tables)" if a == AT else "hook"}'))
    spec['v026_rot'] = dict(built_by=SRC, code_at=hex(AT), code_end=hex(END), code_len=len(code), latch=hex(LATCH), stores=stores,
                            symbols={k: hex(v) for k, v in syms.items() if k.startswith('rot_')}, sites=[hex(s) for s in SITES], latch_evidence=ev)
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['v026_rot'], indent=1))
