#!/usr/bin/env python3
"""Colour-wheel page order with Film first (layer on v0.29). Offline. docs/LOOK_EDITOR.md "Page order (0.29p1)".

Old INFO order: Saturation -> Saturation - All (stock ALL toggle) -> Hue -> Light -> Film -> Extras -> Saturation.
New INFO order: Film -> Saturation -> Saturation - All -> Hue -> Light -> Extras -> Film. Film is a stop only while
the film layer's fm_valid says LOOKS.BIN is loaded (else Extras -> Saturation, as before). The build requires the
extras layer (ed_cfg_x = 4): the in-place k_step has no room for an Extras-less test, so Light -> Extras always. Axis values are unchanged (0 S, 1 L, 2 H, 3 F, 4 X), so ed_poly, ed_guide, ed_get/ed_set, fm_up/down
and the Movie slot's mv_si read the same bytes. The Movie slot runs the same ed_info / init on P2.

Edits (on the look_editor edits, in place, plus one new code block):
  k_step  ed_keys 0x601e3059..0x601e308a (49 B, flashed by look_editor): the next-page table rewritten in place,
          k_set and everything else in ed_keys unchanged (the old bytes are pinned).
  po_init COLOR1-4 records +4 (ed_init today) -> po_init, in the rest of ed_keys' own claim (dead EVF step-3 B
          table, 0x601e3168.., only ref the step-table word 0x601e3cb8 -> 0x601e313c; build-checked). On open:
          P valid, ALL off and fm_valid -> marker 'EP7E' (dirty/status cleared on a first use, as ed_info does) and
          axis Film. Otherwise ed_init's behaviour: marker set -> axis Saturation; no marker -> nothing. Then stock
          init 0x60e20a54 with every register and mdr as at entry. ALL on (closed on Saturation - All) keeps
          opening on Saturation - All. ed_init (sec 6) stays in place, unreferenced.

  .venv/bin/python -I patches/page_order/build.py releases/v0.29/edits.json --out generated/page_order/t1/edits.json
  .venv/bin/python -I tools/build_package.py generated/page_order/t1/edits.json --out generated/page_order/t1/pkg
  .venv/bin/python -I patches/page_order/verify.py releases/v0.29/edits.json generated/page_order/t1/edits.json generated/page_order/t1/pkg

0.29p2 (--film-poly, on t1): the Film page polygon shows the slot's saturation (see apply_film_poly).
  .venv/bin/python -I patches/page_order/build.py generated/page_order/t1/edits.json --film-poly --out generated/page_order/t2/edits.json
  .venv/bin/python -I tools/build_package.py generated/page_order/t2/edits.json --out generated/page_order/t2/pkg
  .venv/bin/python -I patches/page_order/verify.py generated/page_order/t1/edits.json generated/page_order/t2/edits.json generated/page_order/t2/pkg
"""
import argparse, copy, importlib.util, json, struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = 'patches/page_order'


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


LE = _load('ep7_look_editor_build', ROOT / 'patches/look_editor/build.py')
B3, BASE = LE.B3, LE.BASE
KEYS_AT = LE.KEYS[0]
K_STEP, K_SET = 0x601e3059, 0x601e308a
PO_AT, PO_END = 0x601e3168, LE.KEYS[1]          # after ed_keys (ends 0x601e3165, edit to 0x601e3168)
ALL0, ALL1 = 0x61fc3800, 0x61fc3804

HDR = ' .am33_2\n .text\n .global _start\n_start:\n'
PVAL = """
 movhu ({state}),d3
 add -1,d3
 cmp {lim},d3
 bcc {miss}
 btst 3,d3
 bne {miss}
 mov d3,a2
 add {pool},a2
 mov (a2),d3
 cmp {bmagic},d3
 bne {miss}
"""

OLD_STEP = """
 movbu ({axis},a2),d0
 mov 2,d1
 cmp 0,d0
 beq k_set
 mov 1,d1
 cmp 2,d0
 beq k_set
 cmp 1,d0
 bne k_afterf
 mov (ed_cfg_fv),a0
 calls (a0)
 mov 3,d1
 cmp 0,d0
 bne k_set
 bra k_x
k_afterf:
 clr d1
 cmp 3,d0
 bne k_set
k_x:
 mov ed_cfg_x,a0
 movbu (a0),d1
"""

NEW_STEP = """
 movbu ({axis},a2),d0             /* F -> S -> (S-All, stock) -> H -> L -> (X) -> (F) -> S */
 mov 2,d1
 cmp 0,d0
 beq k_set                        /* Saturation (- All) -> Hue */
 mov 1,d1
 cmp 2,d0
 beq k_set                        /* Hue -> Light */
 clr d1
 cmp 3,d0
 beq k_set                        /* Film -> Saturation */
 cmp 1,d0
 bne k_f                          /* Extras and anything else -> Film / Saturation */
 movbu (ed_cfg_x),d1              /* Light -> Extras (extras layer's page value; the build requires it != 0) */
 beq k_set                        /* Z still set from cmp 1,d0 (loads leave the flags) */
k_f:
 mov (ed_cfg_fv),a0               /* film layer: fm_valid (CALLS, a2 = P) -> d0 1 = LOOKS.BIN loaded */
 calls (a0)
 clr d1
 cmp 0,d0
 beq k_set
 mov 3,d1
"""

PO_INIT = """
po_init:                          /* CALLS entry (record +4): a0 parent, d0 key */
 movm [d2,d3,a2,a3],(sp)
 add -24,sp                       /* (0,sp) = CALLS return slot of fm_valid */
 mov d0,(4,sp)
 mov d1,(8,sp)
 mov a0,(12,sp)
 mov a1,(16,sp)
 mov mdr,d0
 mov d0,(20,sp)
{pval}
 clr d2                           /* page to open: Saturation */
 mov ({all0}),d0                  /* ALL state (read only) */
 mov ({all1}),d1
 or d1,d0
 bne 1f                           /* ALL on: Saturation - All, as before */
 mov (ed_cfg_fv),a0
 calls (a0)                       /* a2 = P -> d0 1 = LOOKS.BIN loaded */
 cmp 0,d0
 beq 1f
 mov 3,d2                         /* Film */
1:
 mov ({emark},a2),d0
 cmp {emagic},d0
 beq 2f
 cmp 0,d2
 beq i_out                        /* no marker, Saturation: untouched (stock until the first INFO), as ed_init */
 clr d0                           /* first use since the load, as ed_info's marker block */
 movbu d0,({dirty},a2)
 movbu d0,({status},a2)
 mov {emagic},d0
 mov d0,({emark},a2)
2:
 movbu d2,({axis},a2)
i_out:
 mov (20,sp),d0
 mov d0,mdr
 mov (4,sp),d0
 mov (8,sp),d1
 mov (12,sp),a0
 mov (16,sp),a1
 add 24,sp
 movm (sp),[d2,d3,a2,a3]
 jmp ep7_init
po_end:
"""


def sub():
    s = LE.sub(probe=False)
    return dict(s, all0=hex(ALL0), all1=hex(ALL1))


def asm(body, at, syms):
    code, lst, out, dis = B3.assemble(HDR + B3.subst(body, sub()) + '\n', at, syms)
    return code, out, dis


def step_code(src, syms):
    code, _, _ = asm(src, K_STEP, syms)
    return code


def po_code(syms):
    body = PO_INIT.replace('{pval}', PVAL.replace('{miss}', 'i_out'))
    code, out, dis = asm(body, PO_AT, syms)
    ins = B3.disasm(code, PO_AT)
    if any(op in {'mul', 'mulu', 'div', 'divu', 'setlb', 'trap'} for _, op, _ in ins):
        raise SystemExit('po_init: forbidden instruction')
    if any(k == 'abs' for _, _, k, _ in B3.store_audit(ins)):
        raise SystemExit('po_init: absolute store')
    return code, out


def apply(spec, version='0.29p1'):
    spec = copy.deepcopy(spec)
    stock = LE.MAIN.read_bytes()
    rd = lambda a, n: stock[a - BASE:a - BASE + n]
    m = spec['look_editor']
    sy = {k: int(v, 16) for k, v in m['symbols'].items()}
    if m.get('probe'):
        raise SystemExit('look editor built with the key probe: po_init does not clear the probe slots')
    for k, want in (('k_step', K_STEP), ('k_set', K_SET), ('ed_info', KEYS_AT), ('ed_init', LE.UI[0])):
        if sy[k] != want:
            raise SystemExit(f'{k} at {sy[k]:#x}, expected {want:#x}')
    keys = [e for e in spec['edits'] if e['addr'] == hex(KEYS_AT) and e.get('source') == 'patches/look_editor']
    if len(keys) != 1:
        raise SystemExit('ed_keys edit not found')
    ke = keys[0]
    kb = bytearray.fromhex(ke['new'])
    if KEYS_AT + len(kb) > PO_AT:
        raise SystemExit(f'ed_keys ends {KEYS_AT + len(kb):#x} past {PO_AT:#x}')
    cfg_x = kb[sy['ed_cfg_x'] - KEYS_AT]
    if cfg_x != 4:
        raise SystemExit(f'ed_cfg_x = {cfg_x}: page order needs the extras layer (Extras = 4); k_step has no room for an Extras-less test')
    syms = dict(k_set=K_SET, ed_cfg_x=sy['ed_cfg_x'], ed_cfg_fv=sy['ed_cfg_fv'])
    o, n = K_STEP - KEYS_AT, K_SET - K_STEP
    old = step_code(OLD_STEP, syms)
    if bytes(kb[o:o + n]) != old:
        raise SystemExit('k_step bytes in the spec are not the look_editor source')
    new = step_code(NEW_STEP, syms)
    if len(new) > n:
        raise SystemExit(f'new k_step {len(new)} B > {n}')
    kb[o:o + n] = new + b'\xcb' * (n - len(new))     # nop to k_set
    ke['new'] = kb.hex()
    ke['why'] += f' [page_order: k_step Film first (S -> H -> L -> X -> F -> S), {len(new)} B in place]'

    # po_init in ed_keys' own claim after ed_keys
    for e in spec['edits']:
        if e['addr'].startswith('off:'):
            continue
        a, ln = int(e['addr'], 16), len(e['new']) // 2
        if a < PO_END and PO_AT < a + ln:
            raise SystemExit(f'po_init range overlaps edit {e["addr"]}')
    words = memoryview(stock)[:len(stock) // 4 * 4].cast('I')
    hits = [i * 4 for i, w in enumerate(words) if PO_AT <= w < PO_END]
    if hits:
        raise SystemExit(f'stock words point into the po_init range: {[hex(BASE + h) for h in hits]}')
    if struct.unpack_from('<I', stock, 0x601e3cb8 - BASE)[0] != 0x601e313c:
        raise SystemExit('step-3 B table ref word not stock')
    code, po_syms = po_code(dict(ed_cfg_fv=sy['ed_cfg_fv'], ep7_init=LE.STOCK['ep7_init']))
    if po_syms['po_init'] != PO_AT or po_syms['po_end'] > PO_END:
        raise SystemExit(f'po_init {len(code)} B does not fit {PO_END - PO_AT}')
    spec['edits'].append(dict(kind='0x100', addr=hex(PO_AT), expect=rd(PO_AT, len(code)).hex(), new=code.hex(), source=SRC,
                              why=f'page_order: po_init ({len(code)} B, dead EVF step-3 B table after ed_keys): open on Film '
                                  'when LOOKS.BIN is loaded and ALL is off'))
    ed_init = struct.pack('<I', sy['ed_init']).hex()
    for k, r in LE.RECORDS.items():
        hit = [e for e in spec['edits'] if e['addr'] == hex(r + 4)]
        if len(hit) != 1 or hit[0]['new'] != ed_init:
            raise SystemExit(f'record {k:#x} +4 is not ed_init')
        hit[0].update(new=struct.pack('<I', PO_AT).hex(), source=SRC, why=f'page_order: record {k:#x} init -> po_init')
    if version:
        FV = _load('fw_version_build', ROOT / 'patches/fw_version/build.py')
        spec = FV.apply(spec, version)
    spec['page_order'] = dict(built_by=SRC, version=version, order='F S S-All H L X F', k_step=[hex(K_STEP), len(new)],
                              po_init=[hex(PO_AT), len(code)], symbols={k: hex(po_syms[k]) for k in ('po_init', 'i_out', 'po_end')},
                              cfg_x=cfg_x)
    return spec


# 0.29p2: Film page polygon = the slot's 12 saturation values (as Saturation, and as the Movie slot's mv_poly2 shows
# P2's S values on Film). A stills Film pick writes the stock saturation settings (v0.24 sp_tail), so ed_poly's stock
# read 0x602afa81 shows the picked look. ed_poly `cmp 3,d3; bne p_stock; clr d0; bra p_ret` (neutral circle) ->
# `bra p_stock` (same rel8): every page other than Light/Hue/Extras takes the stock read; `clr d0; bra p_ret` is dead.
FP_AT, FP_OLD, FP_NEW = 0x601e311d, bytes.fromhex('af03c92a00ca1f'), bytes.fromhex('af03ca2a00ca1f')


def apply_film_poly(spec, version='0.29p2'):
    spec = copy.deepcopy(spec)
    if 'page_order' not in spec:
        raise SystemExit('film_poly layers on page_order t1')
    sy = {k: int(v, 16) for k, v in spec['look_editor']['symbols'].items()}
    if (sy['p_stock'], sy['p_ret'], sy['p_chain']) != (0x601e3149, 0x601e3141, 0x601e3124):
        raise SystemExit('ed_poly layout differs')
    ke = [e for e in spec['edits'] if e['addr'] == hex(KEYS_AT) and e.get('source') == 'patches/look_editor'][0]
    kb = bytearray.fromhex(ke['new'])
    o = FP_AT - KEYS_AT
    if bytes(kb[o:o + len(FP_OLD)]) != FP_OLD:
        raise SystemExit('ed_poly Film branch bytes not as expected')
    kb[o:o + len(FP_NEW)] = FP_NEW
    ke['new'] = kb.hex()
    ke['why'] += ' [page_order p2: ed_poly Film -> stock saturation read (bra p_stock)]'
    if version:
        FV = _load('fw_version_build', ROOT / 'patches/fw_version/build.py')
        spec = FV.apply(spec, version)
    spec['page_order'] = dict(spec['page_order'], version=version, film_poly=dict(at=hex(FP_AT + 2), old='c9', new='ca'))
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--version', default=None)
    ap.add_argument('--film-poly', action='store_true', help='0.29p2 step on a t1 spec')
    a = ap.parse_args()
    spec = json.loads(a.spec.read_text())
    spec = apply_film_poly(spec, a.version or '0.29p2') if a.film_poly else apply(spec, a.version or '0.29p1')
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['page_order']))
