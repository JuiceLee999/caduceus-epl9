#!/usr/bin/env python3
"""v0.26 movie colour: movie Vivid renders COLOR4 and (wheel=True) opens COLOR4's wheel. docs/MOVIE_COLOUR.md "As built". Offline.

  .venv/bin/python -I patches/v026_movie/build.py releases/v0.25/edits.json --out generated/v026_movie/wheel/edits.json
  .venv/bin/python -I patches/v026_movie/build.py releases/v0.25/edits.json --no-wheel --out generated/v026_movie/nowheel/edits.json

apply(spec, wheel=True) -> spec. Composable with the rotation layer (other code range, fails on overlap).
"""
import argparse, copy, importlib.util, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


V19 = _load('ep7_v019_build', ROOT / 'patches/v019/build.py')
SB3, FB = V19.SB3, V19.FB
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
BASE, SRC = 0x60020020, 'patches/v026_movie'
AT, END = 0x601e25ec, 0x601e283c          # dead EVF step-7 B, step-6 R/G
W_AT, W_END = 0x601e1e3c, 0x601e233c      # dead EVF step-9 G/B, step-8 R/G/B (mc's old claim; 0x601e1e01 has a byte-table false positive, so start past it)
L_AT, L_END = 0x601e0b3c, 0x601e0e3c      # dead EVF step-15 R/G/B
S_AT, S_END = 0x601e2a98, 0x601e2c3c      # dead EVF step-5 tail (unclaimed part)
ROTATION = (0x601e24ec, 0x601e25ec)       # the rotation agent's
GRANGES = {(0x601e1d3c, 0x601e233c): (0x601e3d14, 0x601e3d18, 0x601e3d00, 0x601e3d04, 0x601e3d08),
           (0x601e253c, 0x601e283c): (0x601e3cf8, 0x601e3ce0, 0x601e3ce4),
           (0x601e2a98, 0x601e2c3c): (0x601e3cd8,),
           (0x601e0b3c, 0x601e0e3c): (0x601e3b40, 0x601e3b44, 0x601e3b48)}
FALSE_POS = {0x60d37d59: '082c1e60', 0x60996fdc: 'cd2b1ea0', 0x606c0846: 'cc2a1ea0', 0x608ebdbc: 'b40c1ea0', 0x6059bdaa: 'fa0b1e60', 0x605a477a: 'ec0b1e60', 0x606d9029: 'dd221ea0ff2004', 0x6002084b: 'cd221ea018', 0x603e8ae2: 'cd271ea00c'}   # call rel32 bytes, dis-checked in build_v15
GETTER, LV_RET, DISPATCH = 0x6005e971, 0x60321eaf, 0x60354709
KEY_SITE, KEY_RET, KEY_OLD = 0x60316bfb, 0x60316c02, 'f84002fad19d03'
MSG_SITE, MSG_RET, MSG_OLD = 0x60315900, 0x60315908, 'f840039015f85114'
S_SITE, WB_SITES = 0x6030bd5d, (0x6030bb5b, 0x6030bb6e)
LV_GET, TONE_GET = 0x601e0ed5, 0x601e10fd
CONS, CONS_RET, LV_ART = 0x60353c6f, 0x60353c75, 0x601e113c
WB_GET, WB_PASS, WB_SLOT, WB_PROP = 0x6055e700, 0x6055e70f, 0x6055e761, 0x6055e797
KEY_WBCAT, CWB = 33057, 3
CKEY = 0x140c                             # COLOR4's editor key
W_GETV = 0x60acb0e4
LC, LC_OLD, LC_NO, LC_YES, LC_OPEN = 0x60e5951c, 'af6fc9415924', 0x60e5955f, 0x60e59522, 0x60e59703   # Live Control INFO release, row 111 test; stock art-variation tail
RA_G = [0x60b9ddba, 0x601e34ee]            # our GetValue(111): ed_guide Film label, ex_guide Extras label
PV_RA = 0x60e26b33                        # Profile view: view+400 = GetValue(111), page 1 only
CC_RA = [0x60e22249, 0x60e223da, 0x60dec546]   # GetValue(15272) before stock "1645 := 21" (Color Creator)
POLY, POLY_OLD = 0x609330bf, 'ddc2c997ff0004'
RA = [0x60e20e25, 0x60e21095, 0x60e21224, 0x60e213d4, 0x60e216b6, 0x60e2186c, 0x60e22594,
      0x60dec52f, 0x60dec5ad, 0x60dec6b6, 0x60dec85c, 0x60decad6, 0x60decc18]
VM, VP, VH, VA, VT, FB = 960, 964, 968, 972, 980, 800     # heap P / P2 offsets (nothing else uses +688..+999); FB = file buffer in P2
VMAGIC, VTMAGIC, VFILE = struct.unpack('<3I', b'EP7VEP7TEP7V')
PMARK = 0x4d565032
FMAGIC, LSIZE = struct.unpack('<I', b'EP7F')[0], 2560   # film_menu_v2 'EP7F', L_SIZE
ALL0, ALL1 = 1686, 1687
EM, AXIS, DIRTY, STATUS, OLD = 680, 684, 685, 686, 688
EXIT_WORD, EXIT = 0x611a3b6c, 0x60e591ba
SD_BACK, GSAVE_SITE = 0x605b7420, 0x605b73a1
SET_SITE, POLY2, DEF_WORD = 0x607fa355, 0x609330f9, 0x60acb174
TBL, TBL_SITES = 0x6055e7b0, (0x601e0ee2, 0x601e110a)
WB_READ = 0x6055e76d
BAD = {'mul', 'mulu', 'div', 'divu', 'setlb', 'llt', 'lne', 'leq', 'lra', 'lcc', 'lcs', 'trap'}
STATE, LIM, POOL, BMAGIC = SB3.STATE, SB3.LIM, SB3.POOL, SB3.MAGIC


def img_of(spec, stock):
    im = bytearray(stock)
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16) - BASE; n = bytes.fromhex(e['new']); im[a:a + len(n)] = n
    return bytes(im)


def put(spec, stock, addr, old, new, why):
    """Into the edit that covers addr, else a new edit. old is the byte string now there."""
    im = img_of(spec, stock)
    if im[addr - BASE:addr - BASE + len(old)] != old:
        raise SystemExit(f'{addr:#x}: {im[addr - BASE:addr - BASE + len(old)].hex()} != {old.hex()} ({why})')
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if a <= addr and addr + len(new) <= a + n:
                b = bytearray.fromhex(e['new']); b[addr - a:addr - a + len(new)] = new; e['new'] = b.hex()
                e['why'] += f' [v0.26: {why}]'
                return
            if a < addr + len(new) and addr < a + n:
                raise SystemExit(f'{addr:#x}: straddles edit {e["addr"]}')
    spec['edits'].append(dict(kind='0x100', addr=hex(addr), expect=stock[addr - BASE:addr - BASE + len(new)].hex(), new=new.hex(), source=SRC, why=f'v0.26 {why}'))


def jmp(at, dst, n=5):
    return (b'\xdc' + struct.pack('<i', dst - at)).ljust(n, b'\xcb')


def check_free(spec, stock, lo, hi):
    if lo < ROTATION[1] and ROTATION[0] < hi:
        raise SystemExit('range overlaps rotation')
    for x in spec['edits']:
        if not x['addr'].startswith('off:'):
            a, n = int(x['addr'], 16), len(x['new']) // 2
            if a < hi and lo < a + n:
                raise SystemExit(f'overlap {lo:#x}: edit {x["addr"]}')
    import numpy as np
    rng, refs = next((r, w) for r, w in GRANGES.items() if r[0] <= lo and hi <= r[1])
    for off in range(4):
        w = np.frombuffer(stock[off:off + (len(stock) - off) // 4 * 4], dtype='<u4')
        for k in np.nonzero(((w >= lo) & (w < hi)) | ((w >= lo + 0x40000000) & (w < hi + 0x40000000)))[0]:
            at = BASE + off + 4 * int(k)
            if at in refs:
                continue
            if at in FALSE_POS and stock[at - BASE:at - BASE + len(FALSE_POS[at]) // 2].hex() == FALSE_POS[at]:
                continue
            raise SystemExit(f'reference into {lo:#x}..{hi:#x} at {at:#x}')


def asm(name, at, end, last, sub, syms):
    code, lst, s, _ = SB3.assemble(SB3.subst((HERE / name).read_text(), sub), at, syms)
    if at + len(code) > end:
        raise SystemExit(f'{name}: {len(code)} B does not fit {end - at}')
    ins = SB3.disasm(code, at, s[last])
    if any(op in BAD for _, op, _ in ins) or any(k == 'abs' for _, _, k, _ in SB3.store_audit(ins)):
        raise SystemExit(f'{name}: forbidden instruction or absolute store')
    return code, lst, s


def rel(at, dst):
    return struct.pack('<i', dst - at)


def apply(spec, wheel=True):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    im = img_of(spec, stock)
    if bytes.fromhex(KEY_OLD) != im[KEY_SITE - BASE:KEY_SITE - BASE + 7] or bytes.fromhex(MSG_OLD) != im[MSG_SITE - BASE:MSG_SITE - BASE + 8]:
        raise SystemExit('key / message site not stock')
    wb = spec['wb']['symbols']
    if (int(wb['wb_get'], 16), int(wb['wb_pass'], 16), int(wb['wb_slot'], 16), int(wb['wb_prop'], 16)) != (WB_GET, WB_PASS, WB_SLOT, WB_PROP):
        raise SystemExit('wb_get moved')
    for s in (LV_GET, TONE_GET):
        if im[s - BASE] != 0xdd or s + struct.unpack_from('<i', im, s + 1 - BASE)[0] != GETTER:
            raise SystemExit(f'{s:#x}: not the getter call')
    check_free(spec, stock, AT, END)
    sub = dict(state=hex(STATE), lim=hex(LIM), pool=hex(POOL), bmagic=hex(BMAGIC), k_wbcat=KEY_WBCAT, cwb=CWB, lv_ret=hex(LV_RET),
               tab2='', s_hit='', w_hit='', p_hit='')
    extra = {}
    if wheel:
        check_free(spec, stock, W_AT, W_END)
        check_free(spec, stock, L_AT, L_END)
        check_free(spec, stock, S_AT, S_END)
        for ra in RA:
            if stock[ra - 2 - BASE:ra - BASE] != b'\xf0\xf2' or b'\x80\x6f' not in stock[ra - 12 - BASE:ra - 2 - BASE]:
                raise SystemExit(f'GetValue(111) site {ra:#x} differs')
        for ra in CC_RA:
            if stock[ra - 2 - BASE:ra - BASE] != b'\xf0\xf2' or struct.pack('<H', 15272) not in stock[ra - 6 - BASE:ra - 2 - BASE]:
                raise SystemExit(f'GetValue(15272) site {ra:#x} differs')
        for ra in RA_G:
            if im[ra - 4 - BASE:ra - BASE] != b'\x80\x6f\xf0\xf2':
                raise SystemExit(f'guide GetValue(111) site {ra:#x} differs')
        le = spec['look_editor']['symbols']
        u32 = lambda a: struct.unpack_from('<I', im, a - BASE)[0]
        tgt = lambda a: a + struct.unpack_from('<i', im, a + 1 - BASE)[0]
        if tgt(SD_BACK) != int(le['ed_trig'], 16) or tgt(GSAVE_SITE) != int(le['ed_save'], 16) or u32(EXIT_WORD) != EXIT or any(tgt(t) != TBL for t in TBL_SITES):
            raise SystemExit('slot hook sites differ')
        next_get, next_def, next_set, next_poly = u32(W_GETV), u32(DEF_WORD), tgt(SET_SITE), tgt(POLY2)
        sub2 = dict(sub, ckey=hex(CKEY), nra=len(RA) + len(RA_G), nra2=len(CC_RA), pv_ra=hex(PV_RA), ra_words='\n'.join(f' .long {x:#x}' for x in RA + RA_G), ra2_words='\n'.join(f' .long {x:#x}' for x in CC_RA),
                    vm=VM, vp=VP, vh=VH, va=VA, vt=VT, fb=FB, vmagic=hex(VMAGIC), vtmagic=hex(VTMAGIC), vfile=hex(VFILE), pmark=hex(PMARK), all0=ALL0, all1=ALL1, em=EM, emagic=hex(struct.unpack('<I', b'EP7E')[0]),
                    axis=AXIS, dirty=DIRTY, status=STATUS, old=OLD, neg_pool=hex((-POOL) & 0xffffffff), nmagic=hex(struct.unpack('<I', b'EP7N')[0]), ev_press=hex(SB3.EV_PRESS), cfg_fl=le['ed_cfg_fl'], fmagic=hex(FMAGIC), lsize=LSIZE)
        st_ = spec['look_editor']['stock']
        c2, lst2, s2 = asm('mvw.s.in', W_AT, W_END, 'mvw_end', sub2, dict(ep7_sget=0x602af887, ep7_get_next=next_get, ep7_def_next=next_def, ep7_set_next=next_set, ep7_poly_next=next_poly, ep7_aget=0x602afa81, ep7_lc_no=LC_NO, ep7_lc_yes=LC_YES, ep7_lc_open=LC_OPEN,
                           ep7_exit=EXIT, ep7_tbl=TBL, ep7_save=int(le['ed_save'], 16), ep7_manager=int(st_['ep7_manager'], 16)))
        c4, lst4, s4 = asm('mvs.s.in', S_AT, S_END, 'mvs_end', sub2, dict(ep7_crc=int(le['ed_crc'], 16), ep7_wfile=int(le['ed_wfile'], 16), ep7_m_r=int(le['ed_m_r'], 16),
                           ep7_malloc=int(st_['ep7_malloc'], 16), ep7_free=int(st_['ep7_free'], 16), ep7_fopen=int(st_['ep7_fopen'], 16), ep7_fclose=int(st_['ep7_fclose'], 16), ep7_fread=int(st_['ep7_fread'], 16)))
        c3, lst3, s3 = asm('mvl.s.in', L_AT, L_END, 'mvl_end', sub2, dict(mv_save=s4['mv_save'], mv_pbin=s4['mv_pbin'], ep7_sget=0x602af887, ep7_trig=int(le['ed_trig'], 16), ep7_crc=int(le['ed_crc'], 16), ep7_wfile=int(le['ed_wfile'], 16), ep7_m_r=int(le['ed_m_r'], 16),
                           ep7_malloc=int(st_['ep7_malloc'], 16), ep7_free=int(st_['ep7_free'], 16), ep7_fopen=int(st_['ep7_fopen'], 16), ep7_fclose=int(st_['ep7_fclose'], 16), ep7_fread=int(st_['ep7_fread'], 16)))
        s2.update(s3); s2.update(s4)
        sub.update(tab2=f' mov ({VM},\\a),\\d\n cmp {VMAGIC:#x},\\d\n bne \\miss', s_hit='jmp ep7_mv_sv', p_hit=f'mov {PMARK:#x},d1',
                   w_hit=f'TAB d0,a0,8f\n mov ({VP},a0),a0\n add 224,a0\n jmp ep7_wb_read\n8:')
        extra = dict(ep7_mv_sv=s2['mv_sv'], ep7_wb_read=WB_READ)
    code, lst, s = asm('mv.s.in', AT, END, 'mv_end', sub, dict(ep7_getter=GETTER, ep7_key_ret=KEY_RET, ep7_msg_ret=MSG_RET, ep7_wb_prop=WB_PROP, ep7_wb_pass=WB_PASS,
                       ep7_wb_slot=WB_SLOT, ep7_wb_get=WB_GET, ep7_dispatch=DISPATCH, ep7_cons_ret=CONS_RET, ep7_lv_art=LV_ART, **extra))
    spec['edits'].append(dict(kind='0x100', addr=hex(AT), expect=stock[AT - BASE:AT - BASE + len(code)].hex(), new=code.hex(), source=SRC,
                              why=f'v0.26 movie colour stage 1 ({len(code)} B, dead EVF step-7 B / step-6 R,G)'))
    put(spec, stock, KEY_SITE, bytes.fromhex(KEY_OLD), jmp(KEY_SITE, s['mv_key'], 7), 'record -> job key: jmp mv_key')
    put(spec, stock, MSG_SITE, bytes.fromhex(MSG_OLD), jmp(MSG_SITE, s['mv_msg'], 8), 'message +20: jmp mv_msg')
    put(spec, stock, S_SITE + 1, rel(S_SITE, GETTER), rel(S_SITE, s['mv_s']), 'effective S read -> mv_s')
    for w in WB_SITES:
        put(spec, stock, w + 1, rel(w, WB_GET), rel(w, s['mv_wb']), 'compact WB read -> mv_wb')
    for g, n in ((LV_GET, 'lv'), (TONE_GET, 'tone')):
        put(spec, stock, g + 1, rel(g, GETTER), rel(g, s['mv_prof']), f'{n} profile read -> mv_prof')
    put(spec, stock, CONS + 1, rel(CONS, LV_ART), rel(CONS, s['mv_cons']), 'constructor pre-dispatch jmp -> mv_cons (miss: lv_art)')
    syms = {k: hex(v) for k, v in s.items() if k.startswith('mv_')}
    meta = dict(built_by=SRC, code_at=hex(AT), code_len=len(code), wheel=wheel, symbols=syms)
    if wheel:
        spec['edits'].append(dict(kind='0x100', addr=hex(W_AT), expect=stock[W_AT - BASE:W_AT - BASE + len(c2)].hex(), new=c2.hex(), source=SRC,
                                  why=f'v0.26 Movie slot + wheel ({len(c2)} B, dead EVF step-9 G,B / step-8)'))
        spec['edits'].append(dict(kind='0x100', addr=hex(L_AT), expect=stock[L_AT - BASE:L_AT - BASE + len(c3)].hex(), new=c3.hex(), source=SRC, why=f'v0.26 Movie slot loader + save ({len(c3)} B, dead EVF step-15)'))
        spec['edits'].append(dict(kind='0x100', addr=hex(S_AT), expect=stock[S_AT - BASE:S_AT - BASE + len(c4)].hex(), new=c4.hex(), source=SRC, why=f'v0.26 Movie slot save ({len(c4)} B, dead EVF step-5 tail)'))
        wd = lambda a, old, sym, why: put(spec, stock, a, struct.pack('<I', old), struct.pack('<I', s2[sym]), why)
        wd(W_GETV, next_get, 'mv_get', 'facade GetValue -> mv_get')
        wd(DEF_WORD, next_def, 'mv_def', 'facade GetDefault -> mv_def')
        wd(EXIT_WORD, EXIT, 'mv_exit', 'state 7 exit -> mv_exit')
        put(spec, stock, LC, bytes.fromhex(LC_OLD), jmp(LC, s2['mv_lc'], 6), 'Live Control INFO, row 111 -> mv_lc')
        put(spec, stock, POLY, bytes.fromhex(POLY_OLD), b'\xdd' + rel(POLY, s2['mv_poly']) + bytes.fromhex(POLY_OLD)[5:], 'polygon profile read -> mv_poly')
        for at, sym, old, why in ((POLY2 + 1, 'mv_poly2', next_poly, 'polygon sector read'), (SET_SITE + 1, 'mv_set', next_set, 'GUI setter'), (GSAVE_SITE + 1, 'mv_gsave', int(le['ed_save'], 16), 'ed_trig save'), (SD_BACK + 1, 'mv_trig', int(le['ed_trig'], 16), 'sd_back')):
            put(spec, stock, at, rel(at - 1, old), rel(at - 1, s2[sym]), f'{why} -> {sym}')
        for t in TBL_SITES:
            put(spec, stock, t + 1, rel(t, TBL), rel(t, s2['mv_tbl']), 'lv / tone slot read -> mv_tbl')
        meta.update(wheel_at=hex(W_AT), wheel_len=len(c2), load_at=hex(L_AT), load_len=len(c3), save_at=hex(S_AT), save_len=len(c4), wheel_symbols={k: hex(v) for k, v in s2.items() if k.startswith('mv')}, get_next=hex(next_get))
    spec['v026_movie'] = meta
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--no-wheel', action='store_true')
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()), wheel=not a.no_wheel)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps({k: v for k, v in spec['v026_movie'].items() if 'symbols' not in k}))
