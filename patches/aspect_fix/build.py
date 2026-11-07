#!/usr/bin/env python3
"""Aspect fix t1 for issue #23 (Panorama 65:24 = id 6, Wide 21:9 = id 7), layered on v0.28. Offline. docs/ASPECT.md 1i.

  .venv/bin/python -I patches/aspect_fix/build.py releases/v0.28/edits.json --out generated/aspect_fix/t1/edits.json
  .venv/bin/python -I tools/build_package.py generated/aspect_fix/t1/edits.json --out generated/aspect_fix/t1/pkg
  .venv/bin/python -I patches/aspect_fix/verify.py releases/v0.28/edits.json generated/aspect_fix/t1/edits.json generated/aspect_fix/t1/pkg

apply(spec, version='0.28a1') -> spec:
  - af.s.in (13 stubs) in the dead EVF gamma tables 0x601de33c..0x601de53c, entered from 12 hook sites (see af.s.in);
  - AF window size table rows for ids 6/7 (stock (0,0)) = the 16:9 rows, in place (0x607175cc/d0, 0x607175f8/fc);
  - the v2 boot clamp is removed (its hook 0x601929a4 and stub 0x60210e90 go back to stock), so Panorama/Wide
    survives a power cycle like every other aspect.
Site list and approach informed by flickering-star's fork of oly_fw_analysis (ep7-aperture-ar), confirmed here.
"""
import argparse, copy, importlib.util, json, re, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


SH = _load('sharp_off_build_af', ROOT / 'patches/sharp_off/build.py')
SB3, STOCK, FV = SH.SB3, SH.STOCK, SH.FV
BASE, SRC = 0x60020020, 'patches/aspect_fix'
AT, END = 0x601de33c, 0x601de53c          # dead EVF gamma tables 3 and 4 (above sharp_off's 0x601de13c..0x601de33c)
REFS = (0x601e3c28, 0x601e3c10)           # their step-table words
FALSE_POS = {0x606d9c34: 'dde41da0', 0x609dd8dd: 'cde31da0', 0x608ebd5f: 'b4e41da0'}   # inside call / mov encodings, dis-checked
BAD = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}
GLOBALS = (0xa276f955, 0xa276f956)        # the only absolute store targets allowed

# hook site -> (stock bytes, stub symbol); replaced by jmp stub (+ nop padding)
HOOKS = {
    0x60dd5ce5: ('2c0e01f0f2', 'af_sel'),
    0x6066389a: ('800342042ca50d', 'af_dim1'),
    0x60663906: ('800342042cc80d', 'af_dim2'),
    0x605d529b: ('fc8256f976a2', 'pr_w1'),
    0x605e278f: ('fc8656f976a2', 'pr_w2'),
    0x605e6658: ('fc8256f976a2', 'pr_w3'),
    0x605d267a: ('800342042cfe03', 'au_mask'),
    0x605d2830: ('800342042c6707', 'au_thr'),
    0x60df798a: ('0cfa23e400', 'ag1'),
    0x60df7b55: ('0cfa23e400', 'ag2'),
    0x60e32899: ('9500085834', 'mt'),
    0x60e3bde8: ('5d0804f80904', 'sv'),
}
# AF window (w,h) u16 pairs indexed by aspect id (read at 0x60664d06); ids 6/7 are (0,0) in stock -> 16:9 row (id 3)
AFWIN = (0x607175b4, 0x607175e0)
CLAMP_HOOK, CLAMP_AT = 0x601929a4, 0x60210e90


def img_of(spec, stock):
    return SH.img_of(spec, stock)


def check_free(spec, stock):
    import numpy as np
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a < END and AT < a + n:
                raise SystemExit(f'overlap with edit {e["addr"]}')
    for off in range(4):
        w = np.frombuffer(stock[off:off + (len(stock) - off) // 4 * 4], dtype='<u4')
        for k in np.nonzero(((w >= AT) & (w < END)) | ((w >= AT + 0x40000000) & (w < END + 0x40000000)))[0]:
            at = BASE + off + 4 * int(k)
            if at in FALSE_POS and stock[at - BASE:at - BASE + 4].hex() == FALSE_POS[at]:
                continue
            if at not in REFS:
                raise SystemExit(f'reference into {AT:#x}..{END:#x} at {at:#x}')


def drop_clamp(spec, stock):
    keep, gone = [], []
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:') and int(e['addr'], 16) in (CLAMP_HOOK, CLAMP_AT):
            gone.append(e['addr'])
            continue
        keep.append(e)
    if sorted(gone) != sorted([hex(CLAMP_HOOK), hex(CLAMP_AT)]):
        raise SystemExit(f'boot clamp edits not found as expected: {gone}')
    spec['edits'] = keep
    for e in keep:   # nothing else may cover the two ranges
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            for lo, ln in ((CLAMP_HOOK, 6), (CLAMP_AT, 56)):
                if a < lo + ln and lo < a + n:
                    raise SystemExit(f'edit {e["addr"]} overlaps the clamp at {lo:#x}')


def edit(spec, stock, addr, new, why):
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a < addr + len(new) and addr < a + n:
                raise SystemExit(f'{addr:#x}: already edited by {e["addr"]}')
    spec['edits'].append(dict(kind='0x100', addr=hex(addr), expect=stock[addr - BASE:addr - BASE + len(new)].hex(),
                              new=new.hex(), source=SRC, why=f'aspect_fix {why}'))


def assemble():
    """Literal `jmp 0x...` targets become --defsym symbols (a literal address assembles as a section-relative value)."""
    src = (HERE / 'af.s.in').read_text()
    targets = sorted(set(re.findall(r'\bjmp (0x[0-9a-f]{8})\b', src)))
    syms = {f'T_{t[2:]}': int(t, 16) for t in targets}
    src = re.sub(r'\bjmp 0x([0-9a-f]{8})\b', r'jmp T_\1', src)
    code, lst, s, _ = SB3.assemble(src, AT, syms)
    s = {k: v for k, v in s.items() if not k.startswith('.')}
    return src, code, s, syms


def apply(spec, version='0.28a1'):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    if spec.get('sharp_off', {}).get('version') != '0.28':
        raise SystemExit('base is not v0.28')
    spec = FV.apply(spec, version)
    drop_clamp(spec, stock)
    check_free(spec, stock)
    im = img_of(spec, stock)
    src, code, s, _ = assemble()
    if AT + len(code) > END:
        raise SystemExit(f'{len(code)} B does not fit {END - AT}')
    ins = SB3.disasm(code, AT, s['af_end'])
    if any(op in BAD for _, op, _ in ins) or any(code[a - AT] == 0xfb for a, _, _ in ins):
        raise SystemExit('forbidden instruction or fb-prefixed form')
    for a, t, kind, tgt in SB3.store_audit(ins):
        if kind == 'abs' and tgt not in GLOBALS:
            raise SystemExit(f'absolute store {t} at {a:#x}')
    if AT % 4 or s['af_sel'] % 4:
        raise SystemExit('stub block misaligned')
    edit(spec, stock, AT, code, f't1 stubs ({len(code)} B, dead EVF gamma tables 3/4)')
    for site, (old, sym) in HOOKS.items():
        old = bytes.fromhex(old)
        if im[site - BASE:site - BASE + len(old)] != old:
            raise SystemExit(f'{site:#x}: {im[site - BASE:site - BASE + len(old)].hex()} != {old.hex()}')
        new = b'\xdc' + struct.pack('<i', s[sym] - site) + b'\xcb' * (len(old) - 5)
        edit(spec, stock, site, new, f'hook -> {sym}')
    for t in AFWIN:
        row3 = im[t + 12 - BASE:t + 16 - BASE]
        if im[t + 24 - BASE:t + 32 - BASE] != bytes(8) or row3 == bytes(4):
            raise SystemExit(f'AF window table {t:#x} differs')
        edit(spec, stock, t + 24, row3 * 2, f'AF window table {t:#x}: ids 6/7 = 16:9 row')
    spec['aspect_fix'] = dict(built_by=SRC, test='t1', version=version, code_at=hex(AT), code_len=len(code),
                              symbols={k: hex(v) for k, v in s.items() if not k.startswith('_')},
                              hooks={hex(k): v[1] for k, v in HOOKS.items()}, afwin=[hex(t + 24) for t in AFWIN],
                              clamp_removed=[hex(CLAMP_HOOK), hex(CLAMP_AT)])
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--version', default='0.28a1')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()), a.version)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps({k: v for k, v in spec['aspect_fix'].items() if k != 'symbols'}))
