#!/usr/bin/env python3
"""v0.18 Film-page labels: the look name alone (no "Film: " / "Film " prefix). Offline; emulator only.

  .venv/bin/python -I tools/ep7_verify_film_label.py releases/v0.17/edits.json releases/v0.18/edits.json

  C  colour editor guide (real .data guide word -> ex_guide -> ed_guide, fm_mod stubbed to give the '*'): Film page
     for short / 10 / 11 / 12 / 15-char names, Stock / Custom, with and without '*', COLOR modes 54/55/56/64:
     NEW == the name alone (+ '*'), OLD == the v0.17 prefix rules; non-COLOR mode, facade error and every other page
     (axis 0/1/2/4/5, ALL on/off, foreign label ids, no table / bad handle) byte-identical to OLD.
  M  mono picker label (mp_lbl1/2 both slots, mp_lbl3 SCP route): presets of 5 / 11 / 12 chars (12 by renaming a
     table entry in both images), with and without '*': NEW == "<name>[*]", OLD == "Film: <name>[*]"; "Film[INFO]"
     (no preset), no table and non-MONO modes byte-identical to OLD.
  D  NEW differs from OLD only at the 3 prefix bytes + the fw_version label.
"""
import importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


EV = _load('ep7_vle_fl', ROOT / 'tools/ep7_verify_look_editor.py')
MV = _load('ep7_vmp_fl', ROOT / 'patches/mono_presets/verify.py')
MB = MV.MB
FMSTUB = 0x18e00000
PREFIX_BYTES = {0x60b9dee3, 0x60b9deea, 0x601e1928}
fails, runs = {'C': [], 'M': [], 'D': []}, {'C': 0, 'M': 0, 'D': 0}


def check(part, lab, err):
    runs[part] += 1
    if err:
        fails[part].append(f'{lab}: {err}')


def extra_for(spec, star):
    cfg = int(spec['look_editor']['symbols']['ed_cfg_fm'], 16)
    code, _ = EV.asm(f' mov {star},d0\n rets\n', FMSTUB)

    def extra(im):
        im2 = bytearray(im)
        struct.pack_into('<I', im2, cfg - EV.BASE, FMSTUB)
        return [EV.img(bytes(im2), EV.LE.KEYS[0], EV.LE.KEYS[1], 'keys'),
                EV.img(im, 0x601e323c, 0x601e383c, 'extras'), EV.Region('fmstub', FMSTUB, code, 'rx')]
    return extra


def old_film(nm, star):
    ln = len(nm) + star
    pre = 'Film: ' if ln <= 10 else 'Film ' if ln == 11 else ''
    return (pre + nm)[:16 - star] + ('*' if star else '')


def main():
    old_spec, new_spec = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
    stock, old = EV.images(old_spec)
    assert not EV.FILM_NAME_ONLY
    _, new = EV.images(new_spec)
    assert EV.FILM_NAME_ONLY, 'NEW spec lacks look_editor.film_label = name'

    # ---- D
    d = {i + EV.BASE for i in range(len(old)) if old[i] != new[i]}
    fwv = set()
    for e in new_spec['edits']:
        if e.get('source') == 'patches/fw_version':
            a = int(e['addr'], 16)
            fwv |= set(range(a, a + len(bytes.fromhex(e['new']))))
    check('D', 'old/new diff', None if PREFIX_BYTES <= d and d - PREFIX_BYTES <= fwv else
          f'{sorted(hex(x) for x in d - fwv)}')
    for a in PREFIX_BYTES:
        check('D', f'{a:#x}', None if old[a - EV.BASE] == ord('F') and new[a - EV.BASE] == 0 else 'not F -> NUL')

    # ---- C: literal expectations of the model, then the emulator against it
    for nm, st, want in (('Velvia', 0, 'Velvia'), ('Velvia', 1, 'Velvia*'), ('Classic Neg', 0, 'Classic Neg'),
                         ('Classic Neg', 1, 'Classic Neg*'), ('Kodachrome64', 0, 'Kodachrome64'),
                         ('Kodachrome64', 1, 'Kodachrome64*'), ('Fifteen chars!!', 1, 'Fifteen chars!!*')):
        b = EV.card_block(axis=3)
        b[544:560] = nm.encode().ljust(16, b'\0')
        EV.FILM_NAME_ONLY = True
        got = EV.film_text(b, 0, bool(st))
        EV.FILM_NAME_ONLY = False
        got_old = EV.film_text(b, 0, bool(st))
        check('C', f'model {nm!r} *{st}', None if got == want and got_old == old_film(nm, st) else f'{got!r} / {got_old!r}')
    blocks = EV.film_blocks()
    for nm in ('Cl. Chrome', 'Classic Neg', 'Kodachrome64'):     # 10 / 11 / 12 (with '*': 11 / 12 / 13)
        b = EV.card_block(axis=3)
        for k in range(4):
            b[544 + 16 * k:560 + 16 * k] = nm.encode().ljust(16, b'\0')
        blocks.append((f'name {nm!r} (again)', b))
    for star in (0, 1):
        ex = extra_for(new_spec, star)
        for lab, blk in blocks:
            for pm in (54, 55, 56, 64, 7, 0):
                for gid in (2755, 2756):
                    for flag, im in ((False, old), (True, new)):
                        EV.FILM_NAME_ONLY = flag
                        e = EV.guide_case(stock, im, 4, gid, EV.H_OK, blk, 3, pm=pm, extra=ex, star=bool(star))
                        check('C', f'{"new" if flag else "old"} film {lab} pm {pm} id {gid} *{star}', e)
        for getret in (0xf0000016, 1):
            e = EV.guide_case(old, new, 4, 2755, EV.H_OK, blocks[0][1], None, pm=54, getret=getret, extra=ex, star=bool(star))
            check('C', f'film getret {getret:#x} *{star} == old', e)
        # every other page / label: NEW byte-identical to OLD
        labels = [(4, 2755), (4, 2756), (4, 2055), (4, 1259), (0, 0), (5, 2756), (4, 2757), (4, 2754), (1, 2756)]
        states = [(label, h, blk) for label, h, blk, _ in EV.heap_states()[:5]]
        states.append(('no EP7E', EV.H_OK, EV.card_block(axis=2, marker=False)))
        states += [(f'axis {ax}', EV.H_OK, EV.card_block(axis=ax)) for ax in (0, 1, 2, 4, 5, 255)]
        for label, h, blk in states:
            for kind, gid in labels:
                e = EV.guide_case(old, new, kind, gid, h, blk, None, extra=ex)
                check('C', f'other {label} kind {kind} id {gid} *{star} == old', e)
        for lab, blk in blocks[:3]:
            for kind, gid in labels[2:]:
                e = EV.guide_case(old, new, kind, gid, EV.H_OK, blk, None, pm=54, extra=ex)
                check('C', f'film page foreign label {lab} kind {kind} id {gid} *{star} == old', e)

    # ---- M
    ms = new_spec['mono_presets']
    syms = ms['symbols']
    tab = int(syms['mp_tab'], 16)
    ps = [dict(p) for p in ms['presets']]
    j12 = 2
    ps[j12]['name'] = 'Ilford Delta'
    imgs = {}
    for k, im in (('old', old), ('new', new)):
        b = bytearray(im)
        o = tab + 24 * j12 - EV.BASE
        b[o:o + 16] = ps[j12]['name'].encode().ljust(16, b'\0')
        imgs[k] = bytes(b)
    pm_of = [57, 58, 59, 65]

    def vals(m, pre, change=None):
        return {MB.IDS[m][f]: x + (1 if change == f else 0) for f, x in enumerate(pre['values'])}

    def text(v, slot):
        return MV.label_text(v, slot)[1]
    for j in (1, 7, j12, 0):                               # Acros (5), Sepia Print (11), Ilford Delta (12), Pan F 50
        pre = ps[j]
        nm = pre['name']
        for m in range(4):
            named = MV.blk_with(mono_names={m: nm})
            for ch, st in ((None, ''), (3, '*'), (7, '*')):
                for site in (1, 2):
                    for slot404, slot in ((1, 186), (0, 260)):
                        r0, _ = MV.label_run(imgs['old'], syms, site, pm_of[m], slot404, named, EV.H_OK, vals(m, pre, ch))
                        r1, v1 = MV.label_run(imgs['new'], syms, site, pm_of[m], slot404, named, EV.H_OK, vals(m, pre, ch))
                        e = MV.l_err(r1, v1, slot, nm + st)
                        if not e and text(EV.mem(r0, 'view'), slot) != 'Film: ' + nm + st:
                            e = f'old {text(EV.mem(r0, "view"), slot)!r}'
                        check('M', f'{nm!r} m{m} site {site} slot {slot} {st or "-"}', e)
                r1, v1 = MV.label_run3(imgs['new'], syms, pm_of[m], named, EV.H_OK, vals(m, pre, ch))
                r0, _ = MV.label_run3(imgs['old'], syms, pm_of[m], named, EV.H_OK, vals(m, pre, ch))
                e = MV.l3_err(r1, v1, nm + st)
                if not e and text(EV.mem(r0, 'view'), 20) != 'Film: ' + nm + st:
                    e = f'old {text(EV.mem(r0, "view"), 20)!r}'
                check('M', f'SCP {nm!r} m{m} {st or "-"}', e)
    # unchanged cases: NEW view == OLD view
    for lab, pm, h, blk in (('no preset', 57, EV.H_OK, MV.blk_with(mono_names={0: 'Something'})),
                            ('no names', 58, EV.H_OK, MV.blk_with(names=False)),
                            ('no table', 57, 0, MV.blk_with(mono_names={0: ps[0]['name']})),
                            ('COLOR mode 54', 54, EV.H_OK, MV.blk_with(mono_names={0: ps[0]['name']})),
                            ('mode 66', 66, EV.H_OK, MV.blk_with(mono_names={0: ps[0]['name']}))):
        for site in (1, 2, 3):
            for slot404 in (1, 0):
                if site == 3:
                    if slot404:
                        continue
                    r0, _ = MV.label_run3(imgs['old'], syms, pm, blk, h, {})
                    r1, _ = MV.label_run3(imgs['new'], syms, pm, blk, h, {})
                else:
                    r0, _ = MV.label_run(imgs['old'], syms, site, pm, slot404, blk, h, {})
                    r1, _ = MV.label_run(imgs['new'], syms, site, pm, slot404, blk, h, {})
                same = (EV.mem(r0, 'view') == EV.mem(r1, 'view') and r0['registers'] == r1['registers']
                        and not r0['fault'] and not r1['fault'])
                txt = text(EV.mem(r1, 'view'), 20 if site == 3 else 186 if slot404 else 260)
                check('M', f'{lab} site {site} slot404 {slot404} == old ({txt!r})', None if same else 'differs')
                if lab.startswith('no preset') or lab == 'no names':
                    check('M', f'{lab} site {site} text', None if txt == 'Film[INFO]' else repr(txt))

    ok = True
    for p in 'DCM':
        print(f'{p}: {runs[p] - len(fails[p])}/{runs[p]} {"PASS" if not fails[p] else "FAIL"}' +
              ''.join('\n   ' + f for f in fails[p][:12]))
        ok &= not fails[p]
    print('ALL PASS' if ok else 'FAILURES')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
