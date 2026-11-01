#!/usr/bin/env python3
"""Build the E-P7 1.1 film-menu phase 2a edit spec (offline, no camera): card-loaded names on the Picture Mode
COLOR/MONO profile entries. Design: docs/FILM_LIBRARY.md section 8 (8.3 chosen design, 8.7 as built).

  .venv/bin/python -I patches/film_menu/build.py --out generated/film_menu/menu

Edits (all build time; nothing is written into the image at run time):
  - 8 marker bytes (NUL) at 0x61242e00 (section-6 FF tail), one per slot k = COLOR1-4, MONO1-4
  - hookA / hookB at 0x61242e10 (film_menu.s.in)
  - 0x60df255f / 0x60df25dc: 6 stock bytes `movhu (a3),d0; cmp 1,d0; beq` -> `jmp hookX; nop`
  - 40 profile entries (phase 2a lists, consumers traced in 8.1): text word "" -> 0x61242e00 + k
Requires the SD look loader v3 built with --names (patches/sd_bundles_v3) for names to appear; with any other
loader (or none) the hook replays stock on every entry.
"""
import argparse, hashlib, importlib.util, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


B3 = _load('ep7_sd_bundles_v3_build', ROOT / 'patches/sd_bundles_v3/build.py')
TC, BASE, MAIN, MAIN_SHA = B3.TC, B3.BASE, B3.MAIN, B3.MAIN_SHA

SEC6 = (0x60ba7000, 0x61243000)                # section 6 (loaded in place), stock data ends 0x612429af
STOCK_END = 0x612429af
MARK = 0x61242e00                              # 8 NUL marker cells
# one copy per builder (about 160 B each, more than 8.3's estimate: the hook also checks the 'EP7B' magic and
# handle alignment like tbl_idx, and restores a0 on replay): hookA below the markers, hookB above them.
HOOKS = {'A': (0x61242d10, 0x61242df0), 'B': (0x61242e10, 0x61242ef0)}   # FF guards: d00-d10, df0-e00, e08-e10, ef0-f00
CLAIM = (0x61242d00, 0x61242f00)               # whole claim incl. guards (aspect list 0x61242f00 untouched)
# abs32 false positives (instruction bytes, not pointers): addr -> 8 context bytes starting 3 B before
FALSE_ABS = {0x607a21ea: None,                 # middle of `call` at 0x607a21e7 (FILM_LIBRARY 8.1)
             0x60e5836a: '0480 04ca2d8c81'.replace(' ', '')}   # `mov 4,d0; bra; mov d3,d0; mov d0,d1` (flash alias of 0x61242dca)

SITES = {  # site: (stock 6 bytes, RET, T1, NEXT)
    'A': (0x60df255f, 'f063a001c826', 0x60df25b2, 0x60df2589, 0x60df2565),
    'B': (0x60df25dc, 'f063a001c812', 0x60df2615, 0x60df25f2, 0x60df25e2),
}
BUILDER_A, BUILDER_B = 0x60df250b, 0x60df25b5

# slot index k by option value (54/55/56/64 = COLOR1-4, 57/58/59/65 = MONO1-4; FILM_LIBRARY 8.1)
VALUE_SLOT = {54: 0, 55: 1, 56: 2, 64: 3, 57: 4, 58: 5, 59: 6, 65: 7}
# phase 2a: the 40 selection entries (label-source addresses; value at -4). The bare 8-B sources
# 0x611c1b44/0x611cf2b0 and the mixed list 0x611df788 wait until their consumers are traced.
LISTS = [(0x61168750, 12, 8), (0x61169128, 12, 1), (0x61169134, 12, 1), (0x61169344, 12, 4),
         (0x6116992c, 12, 1), (0x61169938, 12, 1), (0x611895cc, 12, 8), (0x611bdb1c, 36, 8), (0x611cb288, 36, 8)]
DEFERRED = [(0x611c1b44, 8, 8), (0x611cf2b0, 8, 8), (0x611df788, 12, 3)]
EMPTY_TEXTS = {0x61163e78, 0x611b6f68, 0x611c465c, 0x611895c4, 0x611df608}   # per-tree "" (FILM_LIBRARY 8.1)
NAMES_LO, MARK_OFF, NMAGIC = B3.NAMES_LO, B3.MARK_OFF, B3.NMAGIC


def u16(d, a):
    return struct.unpack_from('<H', d, a - BASE)[0]


def u32(d, a):
    return struct.unpack_from('<I', d, a - BASE)[0]


def entries(d):
    """-> [(source addr, slot k, string id, stock text)] for the 40 phase-2a entries, checked against stock."""
    out = []
    for base, stride, n in LISTS:
        for i in range(n):
            s = base + stride * i
            val, kind, sid, text = u32(d, s - 4), u16(d, s), u16(d, s + 2), u32(d, s + 4)
            if kind != 4 or val not in VALUE_SLOT or text not in EMPTY_TEXTS or d[text - BASE] != 0:
                raise ValueError(f'entry {s:#x}: value {val} kind {kind} text {text:#x} not a stock profile entry')
            out.append((s, VALUE_SLOT[val], sid, text))
    if len(out) != 40 or len({s for s, *_ in out}) != 40:
        raise ValueError('expected 40 distinct entries')
    return out


def subst(text, sub):
    for k, v in sub.items():
        text = text.replace('{' + k + '}', str(v))
    if '{' in text or '}' in text:
        raise ValueError('unsubstituted template field')
    return text


def source():
    sub = dict(mark=hex(MARK), neg_mark=hex(-MARK), state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL),
               bmagic=hex(B3.MAGIC), nmagic=hex(NMAGIC), mark_off=MARK_OFF, names_lo=NAMES_LO)
    for p, (_, _, ret, t1, nxt) in SITES.items():
        sub.update({f'{n}_{p.lower()}': f'ep7_{n}_{p.lower()}' for n in ('ret', 't1', 'next')})
    return subst((HERE / 'film_menu.s.in').read_text(), sub)


def defsyms():
    """Branch targets as linker symbols (a numeric jmp operand would be taken as a raw displacement)."""
    out = {}
    for p, (_, _, ret, t1, nxt) in SITES.items():
        out.update({f'ep7_ret_{p.lower()}': ret, f'ep7_t1_{p.lower()}': t1, f'ep7_next_{p.lower()}': nxt})
    return out


def one(src, p):
    """Template text -> the source of hook p alone (the other HOOK line dropped)."""
    other = 'B' if p == 'A' else 'A'
    lines = [l for l in src.splitlines() if not l.startswith(f' HOOK {other},')]
    if sum(l.startswith(' HOOK ') for l in lines) != 1:
        raise ValueError('template HOOK lines')
    return '\n'.join(lines) + '\n'


def assemble(src, at):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in defsyms().items()], '-o', t / 'p.elf', t / 'p.o'],
                       check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        syms = {n: int(a, 16) for a, ty, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3) if ty in 'tT'}
        dis = subprocess.run([TC / 'mn10300-elf-objdump', '-d', t / 'p.elf'], check=True, capture_output=True,
                             text=True).stdout
        return (t / 'p.bin').read_bytes(), (t / 'p.lst').read_text() + '\n' + dis, syms


def sec6_desc(d):
    for i in range(9):
        s, src, dst = struct.unpack_from('<3I', d, 0x60027068 + 12 * i - BASE)
        if s == SEC6[0]:
            stub = struct.unpack_from('<I', d, 0x60046780 + 4 * i - BASE)[0]
            if d[stub - BASE:stub - BASE + 6] != b'\xfc\xcc' + struct.pack('<I', SEC6[1]) or dst != s:
                raise ValueError('section-6 end constant / in-place load differs')
            return src
    raise ValueError('section-6 descriptor not found')


def abs32_into(d, lo, hi, logical):
    import numpy as np
    a = np.frombuffer(d, np.uint8).astype(np.int64)
    w = a[:-3] | (a[1:-2] << 8) | (a[2:-1] << 16) | (a[3:] << 24)
    out = []
    for off in (0, 0x40000000, logical, logical + 0x40000000):
        out += [int(i) + BASE for i in np.nonzero((w >= lo + off) & (w < hi + off))[0]]
    return sorted(out)


def check_image(d):
    if set(d[CLAIM[0] - BASE:SEC6[1] - BASE]) != {0xff} or d[STOCK_END - BASE] == 0xff or \
            set(d[STOCK_END + 1 - BASE:CLAIM[0] - BASE]) - {0xff}:
        raise ValueError('section-6 tail not erased FF / stock data end moved')
    logical = sec6_desc(d) - SEC6[0]
    hits = [a for a in abs32_into(d, CLAIM[0], CLAIM[1], logical)
            if a not in FALSE_ABS or FALSE_ABS[a] and d[a - 3 - BASE:a + 4 - BASE].hex() != FALSE_ABS[a]]
    if hits:
        raise ValueError(f'abs32 references into the claim: {[hex(h) for h in hits[:8]]}')
    if d[0x607a21e7 - BASE] != 0xdd:
        raise ValueError('0x607a21ea false-positive context changed')
    XR = _load('ep7_xref', ROOT / 'tools/ep7_xref.py')
    import numpy as np
    arr = np.frombuffer(d, dtype=np.uint8)
    for p, (site, stock, ret, t1, nxt) in SITES.items():
        if d[site - BASE:site - BASE + 6].hex() != stock:
            raise ValueError(f'site {p} {site:#x} stock bytes differ')
        if site + 4 + struct.unpack_from('<b', d, site + 5 - BASE)[0] != t1 or nxt != site + 6:
            raise ValueError(f'site {p}: beq target / fall-through differ')
        inner = XR.scan(arr, list(range(site + 1, site + 6)), short=True)
        if any(inner.values()):
            raise ValueError(f'branch into hook span {p}: {inner}')
    # the replay contract: kind-4 path falls to the builder's ret, a0 stored at (4,sp) at entry
    if d[BUILDER_A - BASE:BUILDER_A + 2 - BASE].hex() != '4304' or d[BUILDER_B + 1 - BASE:BUILDER_B + 3 - BASE].hex() != '4304':
        raise ValueError('builder a0 store differs')
    if d[0x60df25b2 - BASE:0x60df25b5 - BASE].hex() != 'dff018' or d[0x60df2615 - BASE:0x60df2618 - BASE].hex() != 'dfb014':
        raise ValueError('builder ret differs')


def make_spec():
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    check_image(d)
    ents = entries(d)
    src = source()
    codes, lsts, syms, ins = {}, [], {}, []
    for p, (at, end) in HOOKS.items():
        c, l, sy = assemble(one(src, p), at)
        if sy[f'hook{p}'] != at or at + len(c) > end:
            raise ValueError(f'hook{p} layout: {len(c)} B does not fit {at:#x}..{end:#x}')
        codes[p], syms = c, dict(syms, **{k: v for k, v in sy.items() if k != '_start'})
        lsts.append(l)
        ins += B3.disasm(c, at)
    lst = '\n'.join(lsts)
    bad_ops = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'lgt', 'lge', 'lle',
               'lhi', 'lls', 'call', 'calls', 'ret', 'retf', 'rets', 'movm', 'trap'}
    if any(op in bad_ops for _, op, _ in ins):
        raise ValueError('forbidden instruction in hook code')
    # every jmp leaves to the builder's own RET / T1 / NEXT; every other branch stays inside its hook
    targets = set(defsyms().values())
    for x, op, args in ins:
        if op in ('jmp',) or op.startswith('b') and op not in ('btst',):
            o = x - BASE
            t = None
            for p, (at, end) in HOOKS.items():
                if at <= x < end:
                    c, base_ = codes[p], at
            b = c[x - base_:]
            if b[0] == 0xdc:
                t = x + struct.unpack_from('<i', b, 1)[0]
            elif b[0] == 0xcc:
                t = x + struct.unpack_from('<h', b, 1)[0]
            elif 0xc0 <= b[0] <= 0xca:
                t = x + struct.unpack_from('<b', b, 1)[0]
            else:
                raise ValueError(f'unexpected branch encoding at {x:#x}: {op} {args}')
            inside = any(a_ <= t < a_ + len(codes[q]) for q, (a_, _) in HOOKS.items() if a_ == base_)
            if not inside and t not in targets:
                raise ValueError(f'branch at {x:#x} leaves to {t:#x}')
    exits = {}
    for p, (at, _) in HOOKS.items():
        c = codes[p]
        exits[p] = sorted(at + i + struct.unpack_from('<i', c, i + 1)[0] for i in range(len(c) - 4) if c[i] == 0xdc
                          and at + i + struct.unpack_from('<i', c, i + 1)[0] in targets)
        want_ex = sorted(SITES[p][2:5])
        if exits[p] != want_ex:
            raise ValueError(f'hook{p} exits {[hex(e) for e in exits[p]]} != {[hex(e) for e in want_ex]}')
    st = B3.store_audit(ins)
    want = ['movhu d0,(a3)', 'movhu d0,(a1)', 'movhu d0,(a1)'] * len(HOOKS)
    if [t for _, t, _, _ in st] != want or any(k != 'ind' for _, _, k, _ in st):
        raise ValueError(f'hook stores: {st}')
    # registers: written only d0, d1, a0, a1; a2 read only as (4,a2); a3 only as the label base; sp only (4,sp)
    import re
    for x, op, args in ins:
        regs = re.findall(r'\b(d[0-3]|a[0-3]|sp|mdr|lir|lar|e?r\d+)\b', args)
        extra = [r for r in regs if r not in ('d0', 'd1', 'a0', 'a1')]
        ok = all(r == 'a2' for r in extra) and args == '(4,a2),d0' or \
            all(r == 'a3' for r in extra) and args in ('(a3),d0', 'd0,(a3)', 'a3,a1') or \
            all(r == 'sp' for r in extra) and args == '(4,sp),a0' or not extra
        if not ok:
            raise ValueError(f'hook register use at {x:#x}: {op} {args}')
    edits = [dict(kind='0x100', addr=hex(MARK), expect=d[MARK - BASE:MARK + 8 - BASE].hex(), new='00' * 8,
                  why='film menu: 8 NUL marker cells (k = COLOR1-4, MONO1-4) in section-6 FF tail')]
    for p, (at, _) in HOOKS.items():
        edits.append(dict(kind='0x100', addr=hex(at), expect=d[at - BASE:at + len(codes[p]) - BASE].hex(),
                          new=codes[p].hex(), why=f'film menu: label hook{p} ({len(codes[p])} B) in section-6 FF tail'))
    for p, (site, stock, *_ ) in SITES.items():
        tgt = syms[f'hook{p}']
        edits.append(dict(kind='0x100', addr=hex(site), expect=stock, new='dc' + struct.pack('<i', tgt - site).hex() + 'cb',
                          why=f'film menu: label builder {p} kind-4 point -> jmp hook{p}; nop'))
    for s, k, sid, text in ents:
        edits.append(dict(kind='0x100', addr=hex(s + 4), expect=struct.pack('<I', text).hex(),
                          new=struct.pack('<I', MARK + k).hex(),
                          why=f'film menu: entry {s:#x} (string {sid}) text "" {text:#x} -> marker {MARK + k:#x} (slot {k})'))
    for e in edits:
        a, n = int(e['addr'], 16), len(bytes.fromhex(e['new']))
        for lo_, hi_, who in B3.RESERVED:
            if a < hi_ and lo_ < a + n:
                raise ValueError(f'edit {e["addr"]} overlaps {who}')
    meta = dict(mark=hex(MARK), hooks={p: dict(at=hex(a), end=hex(e), len=len(codes[p])) for p, (a, e) in HOOKS.items()},
                claim=[hex(x) for x in CLAIM],
                symbols={k: hex(v) for k, v in syms.items()},
                sites={p: dict(site=hex(v[0]), stock=v[1], ret=hex(v[2]), t1=hex(v[3]), next=hex(v[4])) for p, v in SITES.items()},
                builders=dict(A=hex(BUILDER_A), B=hex(BUILDER_B)),
                entries=[dict(source=hex(s), slot=k, string_id=sid, stock_text=hex(t)) for s, k, sid, t in ents],
                deferred=[hex(b) for b, _, _ in DEFERRED], state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL),
                names_lo=NAMES_LO, mark_off=MARK_OFF, nmagic=hex(NMAGIC), bmagic=hex(B3.MAGIC),
                requires='sd_bundles_v3 --names for names to show; without it every label is stock')
    spec = dict(components=['0x100'], patch='film_menu', film_menu=meta, edits=edits)
    return spec, src, lst, b''.join(codes.values())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    try:
        spec, src, lst, code = make_spec()
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'film_menu.s').write_text(src)
    (a.out / 'film_menu.lst').write_text(lst)
    (a.out / 'film_menu.bin').write_bytes(code)
    m = spec['film_menu']
    print(f"film menu hooks {m['hooks']}; markers {MARK:#x}; "
          f"{len(m['entries'])} entries; {len(spec['edits'])} edits; wrote {a.out}")


if __name__ == '__main__':
    main()
