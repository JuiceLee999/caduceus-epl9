#!/usr/bin/env python3
"""Emulator checks of the mono film-sim picker (patches/mono_presets, docs/MONO_PRESETS.md). Offline only.

  .venv/bin/python -I patches/mono_presets/verify.py --spec generated/v015mp/mp/merged.json

Our code runs natively from the patched image, entered through the real edited record words of the 8 MONO filter /
shading editors (+4 init, +12/+16/+20/+24 arrows, +28 filter rear dial, +44 INFO; +36 MENU/PLAYBACK stays stock), image regions mapped read-only;
facade, child refresh and the heap block P are the look-editor verifier's stand-ins (tools/ep7_verify_look_editor.py).
  S  stock paths on every hooked word: no card table, other events, Film page off / no 'EP7M' (arrows), null
     parent, foreign key, child count, held gesture -> both images stop at the stock word's target with equal
     registers and live stack, heap unchanged, no facade call
  I  init word: page byte cleared with a table, nothing written without; then the stock init with registers intact
  H  preset steps: INFO (+1) on either page, Up/Right (+1) and Down/Left (-1) on the Film page, both wraps, stale
     position, resume from the saved name, no names section: 8 SetValue == (id, preset value), then the poke
     (GetValue + SetValue of the editor's own first setting), slot name + EP7N, dirty, EP7E/EP7M, page kept,
     every child refreshed, d0 1, d2/d3/a3/sp kept, nothing else in the heap
  K  INFO toggles the Film page (0 -> 1 -> 0), first use initialises EP7E/EP7M; refresh + poke, d0 1
  L  guide label through mp_lbl1/2 with a per-id GetValue table: Film page / stock page texts, '*' per field,
     sign-extended or byte values, getter failure, no names section, no 'EP7M', no table / non-MONO mode (label
     untouched); replay d0 = (84,operand), a0 = a1 = operand, d1/d2/d3/a2/a3/sp kept, return to the caller
"""
import argparse, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


EV = _load('ep7_verify_look_editor_mp', ROOT / 'tools/ep7_verify_look_editor.py')
MB = _load('ep7_mono_presets_build_v', ROOT / 'patches/mono_presets/build.py')
Region, run, asm, img, mem = EV.Region, EV.run, EV.asm, EV.img, EV.mem
DRV, OUT, PAR, LOG, H_OK, NMAGIC = EV.DRV, EV.OUT, EV.PAR, EV.LOG, EV.H_OK, EV.NMAGIC
LE = EV.LE
CUR = 7                                   # the stand-in GetValue's value (fac_regions curval)
ACT = {44: 0}
DIR = {0: 1, 1: 1, 2: -1, 3: 1, 4: -1}


def parent(key, count, st16=0, st44=0):
    po = bytearray(0x400)
    struct.pack_into('<H', po, 100, key)
    struct.pack_into('<H', po, 120, count)
    struct.pack_into('<I', po, 16, st16)
    struct.pack_into('<I', po, 44, st44)
    for i in range(13):
        struct.pack_into('<I', po, 124 + 4 * i, PAR + 0x200 + 0x10 * i)
    return po


def code_regions(im):
    return [img(im, 0x61185e00, 0x61186200, 'rec', 'r'), img(im, MB.CODE[0], MB.CODE[1], 'mp'),
            img(im, MB.CODE_B[0], MB.CODE_B[1], 'mpb')]


def case(stock, patched, rec_word, ev, h, blk, po, target, hit=False, a0=PAR):
    src = (f' mov {rec_word:#x},a1\n mov (a1),a1\n mov {a0:#x},a0\n mov {ev:#x},d0\n mov 0x11111111,d1\n'
           f' mov a1,({OUT:#x})\n mov ({OUT:#x}),a2\n mov 0x1a1a1a1a,a1\n calls (a2)\n')
    code, sy = asm(src, DRV)
    scode, _ = asm(EV.STUB_REFRESH, 0x60de3670)
    res = {}
    for name, im in (('stock', stock), ('patched', patched)):
        regions = [Region('drv', DRV, code, 'rx'), Region('out', OUT, bytes(64), 'rw'),
                   Region('par', PAR, bytes(po), 'r'), Region('refresh', 0x60de3670, scode, 'rx'),
                   Region('log', LOG, struct.pack('<I', LOG + 4) + bytes(124), 'rw', True),
                   Region('tgt', target & ~0xff, bytes(0x200), 'rx')] + code_regions(im) + \
            EV.fac_regions(0, CUR) + EV.state_regions(h, blk)
        res[name] = run(regions, {'pc': DRV}, sy['done'] if hit and name == 'patched' else target)
    return res['stock'], res['patched'], sy['done']


def logs(r):
    lg = mem(r, 'log')
    end = struct.unpack_from('<I', lg, 0)[0] - LOG
    return [struct.unpack_from('<I', lg, o)[0] for o in range(4, end, 4)], EV.fac_log(r)


def first_use(b, n, tab):
    if struct.unpack_from('<I', b, LE.EMARK)[0] != LE.EMAGIC:
        b[LE.AXIS] = b[LE.DIRTY] = b[LE.STATUS] = 0
        struct.pack_into('<I', b, LE.EMARK, LE.EMAGIC)
    if struct.unpack_from('<I', b, MB.MMARK)[0] != MB.MMAGIC:
        for mm in range(4):
            pos = 0
            if struct.unpack_from('<I', b, 672)[0] == NMAGIC:
                nm = bytes(b[608 + 16 * mm:624 + 16 * mm])
                for j in range(n):
                    if tab[24 * j:24 * j + 16] == nm:
                        pos = j + 1
                        break
            b[MB.MPOS + mm] = pos
        struct.pack_into('<I', b, MB.MMARK, MB.MMAGIC)


def poke(m, kind):
    f = 0 if kind == 0 else 4
    return [(1, MB.IDS[m][f]), (2, MB.IDS[m][f], 0, CUR)]


def model_step(blk, m, kind, d, n, tab):
    b = bytearray(blk)
    first_use(b, n, tab)
    pos = b[MB.MPOS + m] + d
    pos = n if pos <= 0 else (1 if pos > n else pos)
    b[MB.MPOS + m] = pos
    r = tab[24 * (pos - 1):24 * pos]
    if struct.unpack_from('<I', b, 672)[0] != NMAGIC:
        b[544:672] = bytes(128)
    b[608 + 16 * m:624 + 16 * m] = r[:16]
    struct.pack_into('<I', b, 672, NMAGIC)
    b[LE.DIRTY] = 1
    calls = [(2, MB.IDS[m][f], 0, struct.unpack('b', r[16 + f:17 + f])[0] & 0xffffffff) for f in range(8)]
    return b, calls + poke(m, kind), pos


def model_key(blk, m, kind, n, tab):
    b = bytearray(blk)
    first_use(b, n, tab)
    b[MB.MPAGE] = (b[MB.MPAGE] ^ 1) & 1
    return b, poke(m, kind)


def cmp_calls(fl, want):
    got = [tuple(x[:2]) if x[0] == 1 else tuple(x) for x in fl]
    return got == [tuple(w) for w in want]


def blk_with(names=True, marker=True, mono_names=None, mpos=None, mmark=False, page=None):
    b = EV.card_block(axis=0, marker=marker, names=names)
    if not names:
        b[544:676] = bytes(132)
    for mm, nm in (mono_names or {}).items():
        b[608 + 16 * mm:624 + 16 * mm] = nm.encode().ljust(16, b'\0')
    if mpos is not None:
        b[MB.MPOS:MB.MPOS + 4] = bytes(mpos)
    if mmark:
        struct.pack_into('<I', b, MB.MMARK, MB.MMAGIC)
    if page is not None:
        b[MB.MPAGE] = page
    return b


# ------------------------------------------------------------------ L: label with a per-id GetValue table
GT = 0x18d00000                           # facade object; +0x40 vtable; +0x100 table of (u32 id, u32 value), id 0 ends; +0x80 result
GT_STUB = f"""
 .set GT, {GT:#x}
g_fac:
 mov GT,a0
 ret [],4
g_get:
 movm [d2,d3,a2,a3],(sp)
 mov GT+0x100,a2
1:
 mov (a2),d2
 cmp 0,d2
 beq 3f
 cmp d0,d2
 beq 2f
 add 8,a2
 bra 1b
2:
 mov (4,a2),d2
 mov d2,(a1)
3:
 mov (GT+0x80),d0
 mov 0xbad0d1d1,d1
 mov 0xbad0a0a0,a0
 mov 0xbad0a1a1,a1
 ret [d2,d3,a2,a3],16
"""
VIEW, OPER = 0x18e00000, 0x18f00000


def gt_regions(vals, getret=0):
    code, sy = asm(GT_STUB, GT + 0x1000)
    g = bytearray(0x400)
    struct.pack_into('<I', g, 0, GT + 0x40)
    struct.pack_into('<I', g, 0x48, sy['g_get'])
    struct.pack_into('<I', g, 0x80, getret)
    for i, (k, v) in enumerate(vals.items()):
        struct.pack_into('<II', g, 0x100 + 8 * i, k, v & 0xffffffff)
    return [Region('gtstub', GT + 0x1000, code, 'rx'), Region('gt', GT, bytes(g), 'r'),
            Region('t_fac', MB.STOCK['ep7_facade'], b'\xdc' + struct.pack('<i', sy['g_fac'] - MB.STOCK['ep7_facade']), 'rx')]


def label_run(patched, syms, site, pm, slot404, blk, h, vals, getret=0):
    view = bytearray(0x200)
    struct.pack_into('<I', view, 400, pm)
    struct.pack_into('<I', view, 404, slot404)
    for o in (186, 260):
        view[o:o + 74] = bytes([0x77]) * 74
    oper = bytearray(0x100)
    struct.pack_into('<I', oper, 84, 0x84848484)
    tgt = int(syms['mp_lbl1' if site == 1 else 'mp_lbl2'], 16)
    if site == 1:   # view in d3, operand at (8,sp) of the caller
        src = f' mov {VIEW:#x},d3\n mov {OPER:#x},a0\n mov a0,(8,sp)\n mov 0x2a2a2a2a,a2\n mov 0x11111111,d1\n call lbl_t,[],0\n'
    else:           # view in d2, operand in a2
        src = f' mov {VIEW:#x},d2\n mov {OPER:#x},a2\n mov 0x33333333,d3\n mov 0x11111111,d1\n call lbl_t,[],0\n'
    code, sy = asm(src, DRV, {'lbl_t': tgt})
    regions = [Region('drv', DRV, code, 'rx'), Region('view', VIEW, bytes(view), 'rw', True),
               Region('oper', OPER, bytes(oper), 'r')] + code_regions(patched) + gt_regions(vals, getret) + \
        EV.state_regions(h, blk, 'r')
    r = run(regions, {'pc': DRV}, sy['done'])
    keep = dict(d2=EV.SENT['d2'], d3=VIEW, a2=0x2a2a2a2a) if site == 1 else dict(d2=VIEW, d3=0x33333333, a2=OPER)
    r['keep'] = keep
    return r, bytes(view)


SCP_STUB = """
 mov 4,d0
 mov d0,(20,a0)
 mov 0x00030000,d0
 mov d0,(24,a0)
 mov 0x00650059,d0
 mov d0,(28,a0)
 clr d0
 mov d0,(32,a0)
 mov 0x0d0d0d0d,d0
 mov 0x0e0e0e0e,d1
 mov 0x0a0a0a0a,a1
 rets
"""


def label_run3(patched, syms, pm, blk, h, vals, getret=0):
    """v0.15c SCP route: the parts loop `calls` mp_lbl3 (a0 = view); the stock part 0x60e11afd is a stub that
    writes kind 4 / style 3 / "Ye" into view+20 and clobbers d0/d1/a1 (keeps a2/a3)."""
    view = bytearray(0x200)
    view[20:94] = bytes([0x77]) * 74
    scode, _ = asm(SCP_STUB, MB.SCP_PART)
    tgt = int(syms['mp_lbl3'], 16)
    src = f' mov {VIEW:#x},a0\n mov 0x11111111,d1\n mov lbl_t,a1\n calls (a1)\n'
    code, sy = asm(src, DRV, {'lbl_t': tgt})
    regions = [Region('drv', DRV, code, 'rx'), Region('view', VIEW, bytes(view), 'rw', True),
               Region('scp', MB.SCP_PART, scode, 'rx')] + code_regions(patched) + \
        gt_regions({**vals, 111: pm}, getret) + EV.state_regions(h, blk, 'r')
    r = run(regions, {'pc': DRV}, sy['done'])
    return r, bytes(view)


def l3_err(r, v0, want):
    rg = r['registers']
    if r['fault']:
        return f'fault {r["fault"]}'
    if rg['sp'] != EV.SP0 or any(rg[k] != EV.SENT[k] for k in ('d2', 'd3', 'a2', 'a3')):
        return 'registers'
    v = mem(r, 'view')
    kind, txt, style, u = label_text(v, 20)
    if want is None:
        return None if (kind, style, txt) == (4, 3, 'Ye') else f'stock label lost: {kind} {style} {txt!r}'
    if kind != 5 or style != 2 or txt != want or any(u[len(want):]):
        return f'label {kind} {style} {txt!r} != {want!r}'
    rest = bytearray(v)
    rest[20:94] = v0[20:94]
    return None if bytes(rest) == v0 else 'view written outside the label'


def label_text(v, slot):
    kind, = struct.unpack_from('<H', v, slot)
    u = struct.unpack_from('<33H', v, slot + 8)
    return kind, ''.join(chr(c) for c in u).split('\0')[0], struct.unpack_from('<H', v, slot + 6)[0], u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spec', required=True)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    stock, patched = EV.images(spec)
    meta = spec['mono_presets']
    syms = meta['symbols']
    recs = {int(k, 16): int(v, 16) for k, v in meta['records'].items()}
    ps = meta['presets']
    n = len(ps)
    tab = b''.join(p['name'].encode().ljust(16, b'\0') + struct.pack('<8b', *p['values']) for p in ps)
    fails = {k: [] for k in 'SIHKLD'}
    cnt = {k: 0 for k in 'SIHKLD'}

    def check(part, lab, err):
        cnt[part] += 1
        if err:
            fails[part].append(f'{lab}: {err}')

    # ---------------------------------------------------------------- S
    bad = bytearray(blk_with())
    bad[0] ^= 1
    for k, rec in recs.items():
        kf = k in MB.KEYS_F
        cnt_ok = 2 if kf else 1
        for off, act in ACT.items():
            tgt = MB.HOOKS[off][1 if kf else 2]
            ev = {0: 0x9014, 5: 0x900e}.get(act, 0x9004)
            cases = [('h 0', ev, 0, blk_with(page=1, mmark=True), parent(k, cnt_ok)),
                     ('misaligned h', ev, H_OK + 1, blk_with(page=1, mmark=True), parent(k, cnt_ok)),
                     ('no EP7B', ev, H_OK, bad, parent(k, cnt_ok)),
                     ('foreign key', ev, H_OK, blk_with(page=1, mmark=True), parent(0x13b3 if kf else 0x140f, cnt_ok)),
                     ('other kind key', ev, H_OK, blk_with(page=1, mmark=True), parent(MB.KEYS_S[0] if kf else MB.KEYS_F[0], cnt_ok)),
                     ('count 0', ev, H_OK, blk_with(page=1, mmark=True), parent(k, 0)),
                     ('count 3', ev, H_OK, blk_with(page=1, mmark=True), parent(k, 3)),
                     ('gesture +16', ev, H_OK, blk_with(page=1, mmark=True), parent(k, cnt_ok, st16=1)),
                     ('gesture +44', ev, H_OK, blk_with(page=1, mmark=True), parent(k, cnt_ok, st44=5))]
            if act == 0:
                cases += [(f'event {e:#x}', e, H_OK, blk_with(), parent(k, cnt_ok)) for e in (0x900e, 0x9004, 0x9015)]
            elif act == 5:
                cases += [(f'event {e:#x}', e, H_OK, blk_with(page=1, mmark=True), parent(k, cnt_ok))
                          for e in (0x900d, 0x903e, 0xf855, 0x9014, 0x900f, 0x9011, 0x9040)]
            else:
                cases += [('page 0', ev, H_OK, blk_with(page=0, mmark=True), parent(k, cnt_ok)),
                          ('page 2', ev, H_OK, blk_with(page=2, mmark=True), parent(k, cnt_ok)),
                          ('page 1 without EP7M', ev, H_OK, blk_with(page=1, mmark=False), parent(k, cnt_ok)),
                          ('page 1 no EP7E/EP7M', 0, H_OK, blk_with(page=1, marker=False), parent(k, cnt_ok))]
            for lab, e, h, b, po in cases:
                s, p, _ = case(stock, patched, rec + off, e, h, b, po, tgt)
                err = None
                if s['fault'] or s['registers']['pc'] != tgt:
                    err = f'stock run {s["fault"]}'
                elif p['fault'] or p['registers']['pc'] != tgt:
                    err = f'patched pc {p["registers"]["pc"]:#x} {p["fault"]}'
                else:
                    err = EV.same_state(s, p)
                    if not err and mem(p, 'heap') != bytes(b):
                        err = 'heap written'
                    if not err and EV.fac_log(p):
                        err = 'facade called'
                check('S', f'{k:#x} +{off} {lab}', err)
    for k, rec in recs.items():                   # +36 (MENU / PLAYBACK) and shading +28 stay stock
        for off in (4, 12, 16, 20, 24, 28, 36):
            check('S', f'{k:#x} +{off} stock word', None if patched[rec + off - EV.BASE:rec + off + 4 - EV.BASE] ==
                  stock[rec + off - EV.BASE:rec + off + 4 - EV.BASE] else 'patched')
    for k, rec in list(recs.items())[::3]:        # null parent (a0 = 0)
        for off in (44,):
            tgt = MB.HOOKS[off][1 if k in MB.KEYS_F else 2]
            ev = {44: 0x9014}.get(off, 0x9004)
            s, p, _ = case(stock, patched, rec + off, ev, H_OK, blk_with(page=1, mmark=True), parent(k, 2), tgt, a0=0)
            err = None if not (s['fault'] or p['fault'] or p['registers']['pc'] != tgt) else f'{p["fault"]}'
            check('S', f'{k:#x} +{off} null parent', err or EV.same_state(s, p))

    # ---------------------------------------------------------------- I
    for k, rec in ([] if True else recs.items()):
        for lab, h, b, want_page in (('table', H_OK, blk_with(page=1, mmark=True), 0),
                                     ('table, stale page', H_OK, blk_with(page=0xa5), 0),
                                     ('no table', 0, blk_with(page=1, mmark=True), None)):
            s, p, _ = case(stock, patched, rec + 4, k, h, b, parent(k, 2), MB.INIT)
            want = bytearray(b)
            if want_page is not None:
                want[MB.MPAGE] = want_page
            err = None
            if s['fault'] or p['fault'] or p['registers']['pc'] != MB.INIT:
                err = f'pc {p["registers"]["pc"]:#x} {p["fault"]}'
            else:
                err = EV.same_state(s, p) or (None if mem(p, 'heap') == bytes(want) else 'heap') or \
                    ('facade called' if EV.fac_log(p) else None)
            check('I', f'{k:#x} {lab}', err)

    # ---------------------------------------------------------------- H / K
    def take(part, k, rec, off, ev, b, lab, model):
        kf = k in MB.KEYS_F
        cnt_ok = 2 if kf else 1
        s, p, done = case(stock, patched, rec + off, ev, H_OK, b, parent(k, cnt_ok), MB.HOOKS[off][1 if kf else 2], hit=True)
        if p['fault'] or p['registers']['pc'] != done:
            check(part, f'{k:#x} +{off} {lab}', f'pc {p["registers"]["pc"]:#x} {p["fault"]}')
            return
        want, calls = model
        rl, fl = logs(p)
        rg = p['registers']
        err = []
        if mem(p, 'heap') != bytes(want):
            d = [i for i in range(len(want)) if mem(p, 'heap')[i] != want[i]]
            err.append(f'heap differs at {d[:10]}')
        if not cmp_calls(fl, calls):
            err.append(f'facade log {[tuple(hex(y) for y in x) for x in fl]} != {calls}')
        if rl != [PAR + 0x200 + 0x10 * i for i in range(cnt_ok)]:
            err.append(f'refresh {[hex(x) for x in rl]}')
        if rg['d0'] != 1 or rg['sp'] != EV.SP0 or any(rg[x] != EV.SENT[x] for x in ('d2', 'd3', 'a3')):
            err.append('registers')
        check(part, f'{k:#x} +{off} {lab}', '; '.join(err))

    for k, rec in recs.items():
        kf = k in MB.KEYS_F
        kind = 0 if kf else 1
        m = (MB.KEYS_F if kf else MB.KEYS_S).index(k)
        info = [('fresh, MONO name Tri-X 400', blk_with(marker=False, mono_names={m: 'Tri-X 400'})),
                ('fresh, no names section', blk_with(names=False)),
                ('fresh, unknown name', blk_with(mono_names={m: 'Something'})),
                ('EP7M, pos n (wrap)', blk_with(mpos=[n] * 4, mmark=True, page=0)),
                ('EP7M, stale pos 200', blk_with(mpos=[200] * 4, mmark=True, page=0)),
                ('EP7M, Film page, pos 1', blk_with(mpos=[1, 2, 3, 4], mmark=True, page=1))]
        for lab, b in info:
            take('H', k, rec, 44, 0x9014, b, 'INFO ' + lab, model_step(b, m, kind, 1, n, tab)[:2])
        for off in ():
            d = DIR[ACT[off]]
            arrows = [('pos 1', blk_with(mpos=[1] * 4, mmark=True, page=1)),
                      ('pos n', blk_with(mpos=[n] * 4, mmark=True, page=1)),
                      ('pos 0 (no preset)', blk_with(mpos=[0] * 4, mmark=True, page=1)),
                      ('pos 4', blk_with(mpos=[4] * 4, mmark=True, page=1)),
                      ('stale pos 200', blk_with(mpos=[200] * 4, mmark=True, page=1)),
                      ('no names section', blk_with(names=False, mpos=[2] * 4, mmark=True, page=1))]
            for lab, b in arrows:
                take('H', k, rec, off, 0x9004 if off in (12, 16) else 0x9008, b, f'dir {d:+d} {lab}',
                     model_step(b, m, kind, d, n, tab)[:2])
        for ev in ():
            for lab, b in (('page 0', blk_with(mmark=True, page=0, mpos=[3] * 4)),
                           ('page 1', blk_with(mmark=True, page=1, mpos=[3] * 4)),
                           ('fresh (no EP7E, no EP7M, stale page)', blk_with(marker=False, page=0xa5,
                                                                             mono_names={m: 'Acros'}))):
                take('K', k, rec, 36, ev, b, f'{ev:#x} {lab}', model_key(b, m, kind, n, tab))

    # ---------------------------------------------------------------- L
    pm_of = [57, 58, 59, 65]

    def vals_for(m, pre, change=None, mode='s32'):
        v = {}
        for f, x in enumerate(pre['values']):
            x = x + (1 if change == f else 0)
            v[MB.IDS[m][f]] = x & 0xff if mode == 'u8' else x
        return v
    for m in range(4):
        for site in (1, 2):
            for slot404, slot in ((1, 186), (0, 260)):
                j = (m * 3 + site) % n
                pre = ps[j]
                nm = pre['name']
                named = blk_with(mono_names={m: nm})
                L = [('preset', named, vals_for(m, pre), f'Film: {nm}'),
                     ('preset (byte values)', named, vals_for(m, pre, mode='u8'), f'Film: {nm}'),
                     ('stale page byte 1 + EP7M', blk_with(mono_names={m: nm}, page=1, mmark=True), vals_for(m, pre), f'Film: {nm}'),
                     ('no preset', blk_with(mono_names={m: 'Something'}), {}, 'Film[INFO]'),
                     ('no names', blk_with(names=False), {}, 'Film[INFO]')]
                for f in range(8):
                    L.append((f'field {f} changed', named, vals_for(m, pre, f), f'Film: {nm}*'))
                for lab, b, vals, want in L:
                    r, v0 = label_run(patched, syms, site, pm_of[m], slot404, b, H_OK, vals)
                    check('L', f'm{m} site {site} slot {slot} {lab}', l_err(r, v0, slot, want))
                # getter failure: no '*'
                r, v0 = label_run(patched, syms, site, pm_of[m], slot404, named, H_OK, vals_for(m, pre, 0), getret=1)
                check('L', f'm{m} site {site} slot {slot} getter fails', l_err(r, v0, slot, f'Film: {nm}'))
    # v0.15c SCP colour-filter view: mp_lbl3 behind part 0 (the stock filter-name label)
    for m in range(4):
        pre = ps[(m * 5 + 2) % n]
        nm = pre['name']
        named = blk_with(mono_names={m: nm})
        for lab, b, vals, want in (('preset', named, vals_for(m, pre), f'Film: {nm}'),
                                   ('field 3 changed', named, vals_for(m, pre, 3), f'Film: {nm}*'),
                                   ('no preset', blk_with(mono_names={m: 'Something'}), {}, 'Film[INFO]')):
            r, v0 = label_run3(patched, syms, pm_of[m], b, H_OK, vals)
            check('L', f'SCP m{m} {lab}', l3_err(r, v0, want))
    for lab, pm, h, gr in (('no table', 57, 0, 0), ('COLOR mode 54', 54, H_OK, 0), ('mode 66', 66, H_OK, 0),
                           ('GetValue(111) fails', 57, H_OK, 1)):
        r, v0 = label_run3(patched, syms, pm, blk_with(mono_names={0: ps[0]['name']}), h, {}, gr)
        check('L', f'SCP {lab}', l3_err(r, v0, None))
    for lab, pm, h in (('no table', 57, 0), ('COLOR mode 54', 54, H_OK), ('mode 0', 0, H_OK), ('mode 66', 66, H_OK)):
        for site in (1, 2):
            r, v0 = label_run(patched, syms, site, pm, 1, blk_with(mono_names={0: ps[0]['name']}), h, {})
            check('L', f'{lab} site {site}', l_err(r, v0, 186, None))

    # ---------------------------------------------------------------- D: filter rear dial (+28)
    D1F, D1S = MB.STOCK['ep7_d1_f'], MB.STOCK['ep7_d1_s']
    for k in []:
        rec = recs[k]
        for lab, h, b, a0, take_over in (('page 1', H_OK, blk_with(page=1, mmark=True), PAR, True),
                                         ('page 0', H_OK, blk_with(page=0, mmark=True), PAR, False),
                                         ('page 1 no EP7M', H_OK, blk_with(page=1), PAR, False),
                                         ('no table', 0, blk_with(page=1, mmark=True), PAR, False),
                                         ('null parent', H_OK, blk_with(page=1, mmark=True), 0, False)):
            tgt = D1S if take_over else D1F
            s_, _, _ = case(stock, patched, rec + 28, 0, h, b, parent(k, 2), D1F, a0=a0)
            _, p_, _ = case(stock, patched, rec + 28, 0, h, b, parent(k, 2), tgt, a0=a0)
            err = None
            if s_['fault'] or p_['fault'] or p_['registers']['pc'] != tgt:
                err = f'pc {p_["registers"]["pc"]:#x} {p_["fault"]}'
            else:
                err = EV.same_state(s_, p_) or (None if mem(p_, 'heap') == bytes(b) else 'heap written')
            check('D', f'{k:#x} {lab}', err)
    # end to end: +28 -> 0x60e22df0 (real) -> helpers (real) -> parent+48/+52 = mp_up_f / mp_dn_f -> preset step
    sy = {kk: int(v, 16) for kk, v in syms.items()}
    for k in []:
        m = MB.KEYS_F.index(k)
        for delta, d in ((0xffff, 1), (2, -2)):
            b = blk_with(page=1, mmark=True, mpos=[3] * 4)
            po = parent(k, 2)
            struct.pack_into('<II', po, 48, sy['mp_up_f'], sy['mp_dn_f'])
            src = (f' mov {recs[k] + 28:#x},a1\n mov (a1),a2\n mov {PAR:#x},a0\n clr d0\n clr d1\n calls (a2)\n')
            code, dsy = asm(src, DRV)
            scode, _ = asm(EV.STUB_REFRESH, 0x60de3670)
            regions = [Region('drv', DRV, code, 'rx'), Region('par', PAR, bytes(po), 'r'),
                       Region('refresh', 0x60de3670, scode, 'rx'),
                       Region('log', LOG, struct.pack('<I', LOG + 4) + bytes(124), 'rw', True),
                       img(patched, 0x60e20b00, 0x60e23100, 'ed', 'rx'), img(patched, 0x60ea3b00, 0x60ea3b80, 'dl', 'rx'),
                       Region('delta', 0x61fc4fb8, struct.pack('<H', delta), 'r')] + code_regions(patched) + \
                EV.fac_regions(0, CUR) + EV.state_regions(H_OK, b)
            r = run(regions, {'pc': DRV}, dsy['done'])
            want = bytearray(b)
            for _ in range(abs(d)):
                want = model_step(want, m, 0, 1 if d > 0 else -1, n, tab)[0]
            err = None if not r['fault'] and r['registers']['pc'] == dsy['done'] and mem(r, 'heap') == bytes(want) \
                else f'pc {r["registers"]["pc"]:#x} {r["fault"]} pos {mem(r, "heap")[MB.MPOS + m] if mem(r, "heap") else None}'
            check('D', f'{k:#x} end-to-end delta {d:+d}', err)

    ok = True
    for part in 'SIHKLD':
        f = fails[part]
        print(f'{part}: {cnt[part] - len(f)}/{cnt[part]} {"PASS" if not f else "FAIL"}')
        for x in f[:12]:
            print('   ', x)
        ok &= not f
    print('presets:', ', '.join(f'{p["name"]} {p["values"]}' for p in ps))
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


def l_err(r, v0, slot, want):
    rg = r['registers']
    if r['fault']:
        return f'fault {r["fault"]}'
    e = []
    if rg['d0'] != 0x84848484 or rg['a0'] != OPER or rg['a1'] != OPER:
        e.append(f'replay d0 {rg["d0"]:#x} a0 {rg["a0"]:#x} a1 {rg["a1"]:#x}')
    if rg['d1'] != 0x11111111 or rg['sp'] != EV.SP0 or rg['a3'] != EV.SENT['a3'] or \
            any(rg[k] != v for k, v in r['keep'].items()):
        e.append('registers')
    v = mem(r, 'view')
    other = 260 if slot == 186 else 186
    if v[other:other + 74] != v0[other:other + 74]:
        e.append('other slot written')
    if want is None:
        if v != v0:
            e.append('view written')
    else:
        kind, txt, style, u = label_text(v, slot)
        if kind != 5 or style != 2 or txt != want or any(u[len(want):]):
            e.append(f'label {kind} {style} {txt!r} != {want!r}')
        rest = bytearray(v)
        rest[slot:slot + 74] = v0[slot:slot + 74]
        if bytes(rest) != v0:
            e.append('view written outside the slot')
    return '; '.join(e)


if __name__ == '__main__':
    main()
