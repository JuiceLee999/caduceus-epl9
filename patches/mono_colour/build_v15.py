#!/usr/bin/env python3
"""v0.15: MONO-colour capture path + MONO-slot colour editor / Film page (`mc`) on top of a v0.15 base spec. Offline.

  .venv/bin/python -I patches/mono_colour/build_v15.py --base releases/v0.15/edits.json --out generated/v015/mcui

Re-runnable on a spec that already holds a previous build: the previous mono_colour edits are stripped and the chain
words it re-pointed are put back (meta 'mono_colour_ui'.words) before rebuilding. Writes OUT/merged.json.
Edits (docs/MONO_COLOUR.md "v0.15"; docs/CODE_SPACE_MAP.md):
  - capture: patches/mono_colour/build.py --sd-v3 (selector / chroma / packer hooks, sec-7 tail)
  - mc_ui at 0x601e1e3c (dead EVF step-9 G/B, 8, 7, 6 R/G tables) + data at 0x601e383c (step-0 R)
  - words: facade GetValue / GetDefault, type-7 dispatcher 0x61140398, COLOR1-4 records +12/+16, Color Profile view
    part 3 init word 0x6025aa98 (all chained: the old word becomes the miss target)
  - call targets: GUI setter 0x607fa355, polygon sector read 0x609330f9 (chained), polygon profile read 0x609330bf
  - jmp: screen lookups 0x60e4cea8 (6 B) and 0x60e4cf21 (7 B)
"""
import argparse, copy, hashlib, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


B3 = _load('ep7_sd_bundles_v3_build_mc', ROOT / 'patches/sd_bundles_v3/build.py')
FM = _load('ep7_film_menu_v2_build_mc', ROOT / 'patches/film_menu_v2/build.py')
MC = _load('ep7_mono_colour_build_mc', HERE / 'build.py')
BASE, MAIN, MAIN_SHA = B3.BASE, B3.MAIN, B3.MAIN_SHA

UI = (0x601e1e3c, 0x601e283c)            # EVF gamma step-9 G/B, step-8 R/G/B, step-7 R/G/B, step-6 R/G (2560 B)
UI_REFS = {0x601e1e3c: 0x601e3d14, 0x601e1f3c: 0x601e3d18,
           0x601e203c: 0x601e3d00, 0x601e213c: 0x601e3d04, 0x601e223c: 0x601e3d08,
           0x601e233c: 0x601e3cf0, 0x601e243c: 0x601e3cf4, 0x601e253c: 0x601e3cf8,
           0x601e263c: 0x601e3ce0, 0x601e273c: 0x601e3ce4}
DATA = (0x601e383c, 0x601e3a3c)          # data: dead EVF gamma step-0 R + G tables (only refs: step-table words 0x601e3c80/84)
DATA_REFS = {0x601e383c: 0x601e3c80, 0x601e393c: 0x601e3c84}
W_GET, W_DEF, W_OPEN, W_GUIDE = 0x60acb0e4, 0x60acb174, 0x61140398, 0x6025aa98
RECORDS = {0x13b3: 0x61185bdc, 0x13b4: 0x61185c14, 0x13b5: 0x61185c4c, 0x140c: 0x61185c84}
SET_SITE, POLY_SITE, PROF_SITE = 0x607fa355, 0x609330f9, 0x609330bf
PROF_STOCK = 'ddc2c997ff0004'            # call 0x602afa81,[],4 (setting 1648)
SCR, SCR_STOCK, SCR_RESUME = 0x60e4cea8, 'f8972004461c', 0x60e4ceae
SCR2, SCR2_STOCK, SCR2_RESUME = 0x60e4cf21, '431cf1d6f89b22', 0x60e4cf28
OPEN = 0x60e2054e
SD_BACK, SD_BACK_JMP = 0x605b7420, 'dc20ffffff'      # loader sd_back -> jmp ed_trig 0x605b7340 (must stay)
# GetValue(111) sites: return addresses after `calls (a2)` (COLOR editor handlers, Color Profile view parts)
RA = [0x60e20e25, 0x60e21095, 0x60e21224, 0x60e213d4, 0x60e216b6, 0x60e2186c, 0x60e22594,
      0x60dec52f, 0x60dec5ad, 0x60dec6b6, 0x60dec85c, 0x60decad6, 0x60decc18]
PV_RA = 0x60e26b33                       # Profile view: view+400 = GetValue(111) (page 1 only)
SESS, MPOS, CMARK = 928, 932, 956         # heap P: session byte, Film positions [4], 'EP7C'
CMAGIC = struct.unpack('<I', b'EP7C')[0]
STOCK = dict(ep7_sget=0x602af887, ep7_manager=0x60827440, ep7_aget=0x602afa81, ep7_facade=0x607f9062,
             ep7_open=OPEN, ep7_scr_resume=SCR_RESUME, ep7_scr2_resume=SCR2_RESUME)
OWNER = 'mono_colour_ui'
# dis-checked: `call 0x600dae4b,[a2],4` whose rel32 bytes read as 0xa01e22dd (uncached alias of 0x601e22dd)
FALSE_POS = {0x606d9029: 'dd221ea0ff2004', 0x6002084b: 'cd221ea018', 0x603e8ae2: 'cd271ea00c',
             0x608ec4b7: 'b4381ea001'}   # mov (7736,sp),d0; cmp 1,d0 (step-0 data range)   # + call 0x6002266d,[d2,a2],24


def u32(d, a):
    return struct.unpack_from('<I', d, a - BASE)[0]


def call_target(d, a):
    if d[a - BASE] != 0xdd:
        raise ValueError(f'{a:#x} is not a call d32')
    return a + struct.unpack_from('<i', d, a + 1 - BASE)[0]


def image(spec):
    d = bytearray(MAIN.read_bytes())
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    stock = bytes(d)
    for e in _main(spec['edits']):
        a, exp, new = int(e['addr'], 16), bytes.fromhex(e['expect']), bytes.fromhex(e['new'])
        if stock[a - BASE:a - BASE + len(exp)] != exp:
            raise ValueError(f'edit {a:#x}: stock bytes differ')
        d[a - BASE:a - BASE + len(new)] = new
    return stock, bytes(d)


def set_bytes(spec, addr, new, why):
    """Patch `new` into the edit that covers addr (keeping its other bytes), else add an edit of our own."""
    n = len(new)
    for e in _main(spec['edits']):
        a = int(e['addr'], 16)
        b = bytearray.fromhex(e['new'])
        if a <= addr and addr + n <= a + len(b):
            old = bytes(b[addr - a:addr - a + n])
            b[addr - a:addr - a + n] = new
            e['new'] = b.hex()
            return old, False
        if a < addr + n and addr < a + len(b):
            raise ValueError(f'{addr:#x}+{n} straddles edit {a:#x}')
    stock = MAIN.read_bytes()[addr - BASE:addr - BASE + n]
    spec['edits'].append(dict(kind='0x100', addr=hex(addr), expect=stock.hex(), new=new.hex(), owner=OWNER, why=why))
    return stock, True


def _main(edits):
    """Main-component (0x100) edits only; OSD (0x101) edits use 'off:' addresses."""
    return [e for e in edits if not str(e['addr']).startswith('off:')]


def strip(spec):
    """Remove a previous mono_colour / mc build: own edits out, re-pointed words back."""
    spec = copy.deepcopy(spec)
    prev = spec.get('mono_colour_ui', {})
    spec['edits'] = [e for e in spec['edits'] if e.get('owner') not in ('mono_colour', OWNER)]
    for a, old in prev.get('words', {}).items():
        a = int(a, 16)
        for e in _main(spec['edits']):
            ea = int(e['addr'], 16)
            b = bytearray.fromhex(e['new'])
            if ea <= a < ea + len(b):
                b[a - ea:a - ea + len(old) // 2] = bytes.fromhex(old)
                e['new'] = b.hex()
    for k in ('mono_colour', 'mono_colour_ui'):
        spec.pop(k, None)
        spec.get('meta', {}).pop(k, None)
        spec.get('meta', {}).pop('mono_colour_sdv3', None)
    return spec


G_DATA = []


def mc_data(ra, ids, vals, names):
    """the data blob at DATA[0] -> (bytes, symbols)."""
    parts = [('mc_ra', b''.join(struct.pack('<I', x) for x in ra)),
             ('mc_ckeys', struct.pack('<4H', 0x13b3, 0x13b4, 0x13b5, 0x140c)), ('mc_cmode', bytes([54, 55, 56, 64])),
             ('mc_ids', b''.join(struct.pack('<H', i) for row in ids for i in row)), ('mc_pvals', vals),
             ('mc_pnames', names), ('mc_zero', bytes(16)), ('mc_t_film', b'Film: \0'), ('mc_t_nul', b'\0'),
             ('mc_t_bw', b'B&W\0'), ('mc_t_custom', b'Custom\0')]
    out, sym = bytearray(), {}
    for k, b in parts:
        while len(out) % 4:
            out.append(0)
        sym[k] = DATA[0] + len(out)
        out += b
    if len(out) > DATA[1] - DATA[0]:
        raise ValueError(f'mc data {len(out)} B does not fit')
    return bytes(out), sym


def fmt_words(vals, d='.long'):
    return '\n'.join(f' {d} ' + ','.join(hex(v) for v in vals[i:i + 8]) for i in range(0, len(vals), 8))


def fmt_bytes(b):
    return '\n'.join(' .byte ' + ','.join(str(x) for x in b[i:i + 16]) for i in range(0, len(b), 16))


def build(base, out):
    spec = strip(base)
    stock, img = image(spec)
    # ---- guards on the base
    if img[SD_BACK - BASE:SD_BACK - BASE + 5].hex() != SD_BACK_JMP:
        raise ValueError('loader sd_back is not jmp ed_trig (0x605b7340)')
    for a, s in ((SCR, SCR_STOCK), (SCR2, SCR2_STOCK), (PROF_SITE, PROF_STOCK)):
        if img[a - BASE:a - BASE + len(s) // 2].hex() != s:
            raise ValueError(f'{a:#x} not stock in the base')
    if u32(img, W_OPEN) != OPEN or u32(stock, W_OPEN) != OPEN:
        raise ValueError('type-7 dispatcher word differs')
    if stock[POLY_SITE - BASE:POLY_SITE - BASE + 7].hex() != 'dd88c997ff0004' or stock[SET_SITE - BASE:SET_SITE - BASE + 7].hex() != 'ddebd00200e010':
        raise ValueError('polygon / setter site stock bytes differ')
    for ra in RA + [PV_RA]:                # each: `mov 111,d0` then `calls (a2)` ending at ra
        if stock[ra - 2 - BASE:ra - BASE] != b'\xf0\xf2' or b'\x80\x6f' not in stock[ra - 12 - BASE:ra - 2 - BASE]:
            raise ValueError(f'GetValue(111) site {ra:#x} differs')
    for k, r in RECORDS.items():
        if struct.unpack_from('<H', img, r - BASE)[0] != k:
            raise ValueError(f'record {k:#x} differs')
    import numpy as np
    for (lo, hi), refs in ((UI, UI_REFS), (DATA, DATA_REFS)):
        if img[lo - BASE:hi - BASE] != stock[lo - BASE:hi - BASE]:
            raise ValueError(f'mc placement {lo:#x} is not stock in the base')
        for off in range(4):
            w = np.frombuffer(img[off:off + (len(img) - off) // 4 * 4], dtype='<u4')
            for kk in np.nonzero(((w >= lo) & (w < hi)) | ((w >= lo + 0x40000000) & (w < hi + 0x40000000)))[0]:
                at = BASE + off + 4 * int(kk)
                if at in FALSE_POS and img[at - BASE:at - BASE + len(FALSE_POS[at]) // 2].hex() == FALSE_POS[at]:
                    continue
                if refs.get(int(w[kk])) != at:
                    raise ValueError(f'abs32 into the mc placement at {at:#x}')
    # ---- chain targets from the base image
    le = spec['look_editor']['symbols']
    chain = dict(ep7_get_next=u32(img, W_GET), ep7_def_next=u32(img, W_DEF), ep7_guide_next=u32(img, W_GUIDE),
                 ep7_set_next=call_target(img, SET_SITE), ep7_poly_next=call_target(img, POLY_SITE),
                 ep7_up_next=u32(img, RECORDS[0x13b3] + 12), ep7_down_next=u32(img, RECORDS[0x13b3] + 16),
                 ed_poke=int(le['ed_poke'], 16))
    for k, r in RECORDS.items():
        if (u32(img, r + 12), u32(img, r + 16)) != (chain['ep7_up_next'], chain['ep7_down_next']):
            raise ValueError('COLOR records +12/+16 differ between keys')
    xaxis = img[int(le['ed_cfg_x'], 16) - BASE]
    if xaxis != 4:
        raise ValueError(f'extras page value {xaxis} (expected 4: S H L F X)')
    mp = spec['mono_presets']
    ps, ids = mp['presets'], mp['ids']
    if mp['fields'] != ['filter', 'strength', 'toning', 'grain', 'shading', 'highlights', 'shadows', 'midtones']:
        raise ValueError('mono presets field order changed')
    names = b''.join(p['name'].encode('ascii').ljust(16, b'\0')[:15] + b'\0' for p in ps)
    vals = bytes(v & 0xff for p in ps for v in p['values'])
    if mp['heap'].get('mpos') in range(SESS, CMARK + 4):
        raise ValueError('heap overlap with mono presets')
    sub = dict(state=hex(B3.STATE), lim=hex(B3.LIM), pool=hex(B3.POOL), bmagic=hex(B3.MAGIC), nmagic=hex(B3.NMAGIC),
               emark=FM.EMARK, emagic=hex(FM.EMAGIC), axis=FM.AXIS, dirty=FM.DIRTY, sess=SESS, mpos=MPOS,
               cmark=CMARK, cmagic=hex(CMAGIC), xaxis=xaxis, nra=len(RA), pv_ra=hex(PV_RA), np=len(ps),
               np1=len(ps) + 1, fmagic=hex(FM.FMAGIC), lmagic=hex(FM.LMAGIC), npool=hex(-B3.POOL & 0xffffffff),
               llim=hex(FM.LLIM), ra_words=fmt_words(RA), id_words=fmt_words([i for row in ids for i in row], '.hword'),
               pval_bytes=fmt_bytes(vals), pname_bytes=fmt_bytes(names))
    src = B3.subst((HERE / 'mc_ui.s.in').read_text(), sub)
    data, dsym = mc_data(RA, ids, vals, names)
    code, lst, syms, _ = B3.assemble(src, UI[0], dict(STOCK, **chain, **dsym))
    syms.update(dsym)
    G_DATA[:] = [data]
    if UI[0] + len(code) > UI[1]:
        lay = ', '.join(f'{k} {v - UI[0]}' for k, v in sorted(syms.items(), key=lambda x: x[1]) if not k.startswith(('.', '_')))
        raise ValueError(f'mc_ui {len(code)} B does not fit {UI[1] - UI[0]}: {lay}')
    ins = B3.disasm(code, UI[0], syms['mc_end'])
    if any(op in {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'} for _, op, _ in ins):
        raise ValueError('forbidden instruction')
    for a, t, kind, tgt in B3.store_audit(ins):
        if kind == 'abs':
            raise ValueError(f'absolute store at {a:#x}: {t}')
    return spec, code, lst, syms, chain, img


def jmp(at, target, n):
    b = b'\xdc' + struct.pack('<i', target - at)
    return b + b'\xcb' * (n - len(b))


def callrel(at, target):
    return b'\xdd' + struct.pack('<i', target - at)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    base = json.loads(a.base.read_text())
    spec, code, lst, syms, chain, img = build(base, a.out)
    words = {}

    def put(addr, new, why):
        old, added = set_bytes(spec, addr, new, why)
        if not added:
            words[hex(addr)] = old.hex()
    data = G_DATA[0]
    spec['edits'].append(dict(kind='0x100', addr=hex(DATA[0]), expect=MAIN.read_bytes()[DATA[0] - BASE:DATA[0] - BASE + len(data)].hex(),
                              new=data.hex(), owner=OWNER, why=f'v0.15 MONO-colour UI data ({len(data)} B: GetValue(111) return '
                              'addresses, keys, MONO preset ids/values/names, label texts) in the dead EVF step-0 R/G gamma tables'))
    spec['edits'].append(dict(kind='0x100', addr=hex(UI[0]), expect=MAIN.read_bytes()[UI[0] - BASE:UI[0] - BASE + len(code)].hex(),
                              new=code.hex(), owner=OWNER,
                              why=f'v0.15 MONO-colour UI mc ({len(code)} B) in the dead EVF step-9 G/B .. step-6 R/G gamma tables'))
    p = struct.pack
    put(W_GET, p('<I', syms['mc_get']), 'facade GetValue -> mc_get (MONO-slot colour editor; chain ex_get)')
    put(W_DEF, p('<I', syms['mc_def']), 'facade GetDefault -> mc_def (chain ex_default)')
    put(W_OPEN, p('<I', syms['mc_open1']), 'type-7 dispatcher 0x60e2054e -> mc_open1 (colour MONO slot -> COLOR m key)')
    put(W_GUIDE, p('<I', syms['mc_guide']), 'Color Profile view part 3 -> mc_guide (Film label of a MONO slot; chain ex_guide)')
    for k, r in RECORDS.items():
        put(r + 12, p('<I', syms['mc_up']), f'record {k:#x} +12 Up -> mc_up (chain fm_up)')
        put(r + 16, p('<I', syms['mc_down']), f'record {k:#x} +16 Down -> mc_down (chain fm_down)')
    put(SET_SITE + 1, p('<i', syms['mc_set'] - SET_SITE), 'GUI setter call -> mc_set (chain ex_set)')
    put(POLY_SITE + 1, p('<i', syms['mc_poly'] - POLY_SITE), 'polygon sector read -> mc_poly (chain ed_poly)')
    put(PROF_SITE, callrel(PROF_SITE, syms['mc_prof']) + bytes.fromhex(PROF_STOCK)[5:],
        'polygon profile read (setting 1648) -> mc_prof')
    put(SCR, jmp(SCR, syms['mc_scr'], 6), 'screen lookup 0x60e4cea8 entry -> mc_scr (group 0x12 colour MONO key -> COLOR key)')
    put(SCR2, jmp(SCR2, syms['mc_scr2'], 7), 'screen lookup 0x60e4cf21 entry -> mc_scr2')
    # capture path
    MC.reserved = lambda: [(int(e['addr'], 16), int(e['addr'], 16) + len(e['new']) // 2, e.get('source', '?'))
                           for e in _main(spec['edits'])]
    cap, src_c, lst_c, ccode = MC.make_spec(sd_v3=True)
    for e in cap['edits']:
        spec['edits'].append(dict(e))
    spec['mono_colour'] = cap['mono_colour']
    spec['mono_colour_ui'] = dict(code_at=hex(UI[0]), code_len=len(code), words=words,
                                  symbols={k: hex(v) for k, v in syms.items() if not k.startswith('.')},
                                  chain={k: hex(v) for k, v in chain.items()}, ra=[hex(x) for x in RA],
                                  heap=dict(sess=SESS, mpos=MPOS, cmark=CMARK))
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'mc_ui.lst').write_text(lst)
    (a.out / 'merged.json').write_text(json.dumps(spec, indent=1) + '\n')
    _, img2 = image(spec)               # stock-byte check of the whole merged spec
    print(f'mc_ui {len(code)} B at {UI[0]:#x}; capture {ccode and len(ccode)} B; {len(spec["edits"])} edits -> {a.out}/merged.json')


if __name__ == '__main__':
    main()
