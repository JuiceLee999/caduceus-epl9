#!/usr/bin/env python3
"""Emulator checks of the mono film presets (patches/mono_presets, docs/MONO_PRESETS.md). Offline only.

  .venv/bin/python -I patches/mono_presets/verify.py --spec generated/test13r/mp/merged.json

Our code runs natively from the patched image, entered through the real edited record words (MONO filter /
shading editors +44), image regions mapped read-only; facade, child refresh and the heap block P are the look-editor
verifier's stand-ins (tools/ep7_verify_look_editor.py).
  S  stock path: no card table (h 0, misaligned, no EP7B), other events (MENU, Up, OK), null parent, foreign key,
     child count 0 / 3, held gesture -> both images stop at the stock word target (0x60e22d8b / 0x60e22fae) with
     equal registers and live stack, heap unchanged, no facade call
  H  INFO on each of the 8 records: preset pos steps (fresh heap: resume from the saved MONO name; wrap n -> 1; stale
     pos -> 1), the 8 SetValue calls == (id of MONO m, preset value) in order, then (test13b) the editor's own child again, slot name + EP7N (names zeroed first
     when the table had none), dirty 1, EP7E block initialised on first use, EP7M; every child refreshed; d0 1;
     d2/d3/a2/a3/sp kept; nothing else in the heap written
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
DRV, OUT, PAR, LOG, H_OK, P_OK, NMAGIC = EV.DRV, EV.OUT, EV.PAR, EV.LOG, EV.H_OK, EV.P_OK, EV.NMAGIC
LE = EV.LE


def parent(key, count, st16=0, st44=0):
    po = bytearray(0x400)
    struct.pack_into('<H', po, 100, key)
    struct.pack_into('<H', po, 120, count)
    struct.pack_into('<I', po, 16, st16)
    struct.pack_into('<I', po, 44, st44)
    for i in range(13):
        struct.pack_into('<I', po, 124 + 4 * i, PAR + 0x200 + 0x10 * i)
    return po


def case(stock, patched, rec_word, ev, h, blk, po, target, hit=False, a0=PAR):
    src = (f' mov {rec_word:#x},a1\n mov (a1),a1\n mov {a0:#x},a0\n mov {ev:#x},d0\n mov 0x11111111,d1\n'
           f' mov a1,({OUT:#x})\n mov ({OUT:#x}),a2\n mov 0x1a1a1a1a,a1\n calls (a2)\n')
    code, sy = asm(src, DRV)
    scode, _ = asm(EV.STUB_REFRESH, 0x60de3670)
    res = {}
    for name, im in (('stock', stock), ('patched', patched)):
        regions = [Region('drv', DRV, code, 'rx'), Region('out', OUT, bytes(64), 'rw'),
                   img(im, 0x61185e00, 0x61186200, 'rec', 'r'), img(im, MB.CODE[0], MB.CODE[1], 'mp'),
                   Region('par', PAR, bytes(po), 'r'), Region('refresh', 0x60de3670, scode, 'rx'),
                   Region('log', LOG, struct.pack('<I', LOG + 4) + bytes(124), 'rw', True),
                   Region('tgt', target & ~0xff, bytes(0x200), 'rx')] + EV.fac_regions() + EV.state_regions(h, blk)
        res[name] = run(regions, {'pc': DRV}, sy['done'] if hit and name == 'patched' else target)
    return res['stock'], res['patched'], sy['done']


def logs(r):
    lg = mem(r, 'log')
    end = struct.unpack_from('<I', lg, 0)[0] - LOG
    return [struct.unpack_from('<I', lg, o)[0] for o in range(4, end, 4)], EV.fac_log(r)


def model(blk, m, n, tab):
    b = bytearray(blk)
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
    pos = b[MB.MPOS + m] + 1
    pos = pos if pos <= n else 1
    b[MB.MPOS + m] = pos
    r = tab[24 * (pos - 1):24 * pos]
    if struct.unpack_from('<I', b, 672)[0] != NMAGIC:
        b[544:672] = bytes(128)
    b[608 + 16 * m:624 + 16 * m] = r[:16]
    struct.pack_into('<I', b, 672, NMAGIC)
    b[LE.DIRTY] = 1
    return b, [(2, MB.IDS[m][f], 0, struct.unpack('b', r[16 + f:17 + f])[0] & 0xffffffff) for f in range(8)], pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--spec', required=True)
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text())
    stock, patched = EV.images(spec)
    meta = spec['mono_presets']
    recs = {int(k, 16): int(v, 16) for k, v in meta['records'].items()}
    ps = meta['presets']
    n = len(ps)
    tab = b''.join(p['name'].encode().ljust(16, b'\0') + struct.pack('<8b', *p['values']) for p in ps)
    fails, cnt = {'S': [], 'H': []}, {'S': 0, 'H': 0}

    def blk_with(names=True, marker=True, mono_names=None, mpos=None, mmark=False):
        b = EV.card_block(axis=0, marker=marker, names=names)
        if not names:
            b[544:676] = bytes(132)
        if mono_names:
            for mm, nm in mono_names.items():
                b[608 + 16 * mm:624 + 16 * mm] = nm.encode().ljust(16, b'\0')
        if mpos is not None:
            b[MB.MPOS:MB.MPOS + 4] = bytes(mpos)
        if mmark:
            struct.pack_into('<I', b, MB.MMARK, MB.MMAGIC)
        return b
    # S
    bad = bytearray(blk_with())
    bad[0] ^= 1
    for k, rec in recs.items():
        kind_f = k in MB.KEYS_F
        tgt = MB.INFO_F if kind_f else MB.INFO_S
        cnt_ok = 2 if kind_f else 1
        cases = [('h 0', 0x9014, 0, blk_with(), parent(k, cnt_ok)),
                 ('misaligned h', 0x9014, H_OK + 1, blk_with(), parent(k, cnt_ok)),
                 ('no EP7B', 0x9014, H_OK, bad, parent(k, cnt_ok)),
                 ('MENU', 0x900e, H_OK, blk_with(), parent(k, cnt_ok)),
                 ('Up', 0x9004, H_OK, blk_with(), parent(k, cnt_ok)),
                 ('OK', 0x900d, H_OK, blk_with(), parent(k, cnt_ok)),
                 ('foreign key', 0x9014, H_OK, blk_with(), parent(0x13b3 if kind_f else 0x140f, cnt_ok)),
                 ('other kind key', 0x9014, H_OK, blk_with(), parent(MB.KEYS_S[0] if kind_f else MB.KEYS_F[0], cnt_ok)),
                 ('count 0', 0x9014, H_OK, blk_with(), parent(k, 0)),
                 ('count 3', 0x9014, H_OK, blk_with(), parent(k, 3)),
                 ('gesture +16', 0x9014, H_OK, blk_with(), parent(k, cnt_ok, st16=1)),
                 ('gesture +44', 0x9014, H_OK, blk_with(), parent(k, cnt_ok, st44=5))]
        for lab, ev, h, b, po in cases:
            cnt['S'] += 1
            s, p, _ = case(stock, patched, rec + 44, ev, h, b, po, tgt)
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
            if err:
                fails['S'].append(f'{k:#x} {lab}: {err}')
    for k, rec in list(recs.items())[::4]:        # null parent (a0 = 0)
        cnt['S'] += 1
        tgt = MB.INFO_F if k in MB.KEYS_F else MB.INFO_S
        s, p, _ = case(stock, patched, rec + 44, 0x9014, H_OK, blk_with(), parent(k, 2), tgt, a0=0)
        if s['fault'] or p['fault'] or p['registers']['pc'] != tgt or EV.same_state(s, p):
            fails['S'].append(f'{k:#x} null parent: {p["fault"]} {EV.same_state(s, p)}')
    # H
    for k, rec in recs.items():
        kind_f = k in MB.KEYS_F
        m = (MB.KEYS_F if kind_f else MB.KEYS_S).index(k)
        cnt_ok = 2 if kind_f else 1
        states = [('fresh, MONO name Tri-X 400', blk_with(marker=False, mono_names={m: 'Tri-X 400'})),
                  ('fresh, no names section', blk_with(names=False)),
                  ('fresh, unknown name', blk_with(mono_names={m: 'Something'})),
                  ('EP7M, pos n (wrap)', blk_with(mpos=[n] * 4, mmark=True)),
                  ('EP7M, stale pos 200', blk_with(mpos=[200] * 4, mmark=True)),
                  ('EP7M, pos 1', blk_with(mpos=[1, 2, 3, 4], mmark=True))]
        for lab, b in states:
            cnt['H'] += 1
            s, p, done = case(stock, patched, rec + 44, 0x9014, H_OK, b, parent(k, cnt_ok), MB.INFO_F if kind_f else MB.INFO_S, hit=True)
            if p['fault'] or p['registers']['pc'] != done:
                fails['H'].append(f'{k:#x} {lab}: pc {p["registers"]["pc"]:#x} {p["fault"]}')
                continue
            want, calls, pos = model(b, m, n, tab)
            calls = calls + [calls[0 if kind_f else 4]]      # test13b: the editor's own child re-written after the refresh
            rl, fl = logs(p)
            rg = p['registers']
            err = []
            if mem(p, 'heap') != bytes(want):
                d = [i for i in range(len(want)) if mem(p, 'heap')[i] != want[i]]
                err.append(f'heap differs at {d[:10]}')
            if [tuple(x) for x in fl] != calls:
                err.append(f'SetValue log {fl} != {calls}')
            if rl != [PAR + 0x200 + 0x10 * i for i in range(cnt_ok)]:
                err.append(f'refresh {[hex(x) for x in rl]}')
            if rg['d0'] != 1 or rg['sp'] != EV.SP0 or any(rg[x] != EV.SENT[x] for x in ('d2', 'd3', 'a3')):
                err.append('registers')
            if err:
                fails['H'].append(f'{k:#x} {lab} (pos {pos}): ' + '; '.join(err))
    ok = True
    for part in ('S', 'H'):
        f = fails[part]
        print(f'{part}: {cnt[part] - len(f)}/{cnt[part]} {"PASS" if not f else "FAIL"}')
        for x in f[:10]:
            print('   ', x)
        ok &= not f
    print('presets:', ', '.join(f'{p["name"]} {p["values"]}' for p in ps))
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
