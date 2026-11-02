#!/usr/bin/env python3
"""v0.17 extended hue/light: rewrite a merged release spec so H/L UI values -15..15 render (offline, no camera).

  .venv/bin/python -I patches/hl_ext/build.py releases/v0.16/edits.json --out releases/v0.17/edits.json

docs/V02_BUNDLES.md "Extended H/L (v0.17)". Every change is in place; no other edit moves:
  0x60210900  bundles reader: add 7/cmp 15 -> add 15/cmp 31 (validate), add 7 -> add 15 (index), the two LUT bases
              -> the extended LUTs. Same size, same labels; the table, legacy LUTs and perm bytes are unchanged.
  0x601e123c  NEW: hue[31] + light[31] (124 B) in the dead EVF step-13 G gamma table (patches/bundles HLX_AT).
  0x601e0e3c  lv (live view): the same three changes (patches/lv_bundles, follows the base reader).
  loader v3 (0x605b7400) and film menu v2 fm_core: only their per-byte range tables (sd_lo/sd_span, fm_lo/fm_span)
              widen hue/light to -15..15 (patches/sd_bundles RANGES). Code bytes, sd_back and every label unchanged.
Each replaced edit is first rebuilt from source in its legacy form and must equal the base bytes exactly.
"""
import argparse, importlib.util, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'patches/bundles'))
import build as BB  # noqa: E402


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


LV = _load('ep7_lv_bundles_build', ROOT / 'patches/lv_bundles/build.py')
SB = _load('ep7_sd_bundles_build', ROOT / 'patches/sd_bundles/build.py')
LE = _load('ep7_look_editor_build', ROOT / 'patches/look_editor/build.py')
VIEW_V016 = ROOT / 'patches/look_editor/ed_view_v016.s.in'    # the v0.16 source, for the base-equality check
LOADER_AT, SD_BACK, SD_BACK_JMP = 0x605b7400, 0x605b7420, 'dc20ffffff'      # jmp ed_trig 0x605b7340 (must stay)


def edit_at(spec, addr):
    hits = [e for e in spec['edits'] if e['kind'] == '0x100' and int(e['addr'], 16) == addr]
    if len(hits) != 1:
        raise ValueError(f'expected one edit at {addr:#x}, found {len(hits)}')
    return hits[0]


def swap_once(blob, old, new, what):
    if blob.count(old) != 1:
        raise ValueError(f'{what}: legacy range bytes found {blob.count(old)} times (want 1)')
    return blob.replace(old, new)


def make(base):
    spec = json.loads(json.dumps(base))
    if any(int(e['addr'], 16) == BB.HLX_AT for e in spec['edits']):
        raise ValueError('base already has the extended LUTs')
    # 1. capture reader
    e = edit_at(spec, BB.CODE_AT)
    table = bytes.fromhex(e['new'])[:8 * BB.ENTRY]
    sd_v3 = next((v for v in (True, False) if BB.reader(table, v, False)[1].hex() == e['new']), None)
    if sd_v3 is None:
        raise ValueError('base bundles reader != patches/bundles legacy rebuild (sd-v3 or flash)')
    _, code, _, labels = BB.reader(table, sd_v3, True)
    e['new'] = code.hex()
    e['why'] += ' [v0.17: extended H/L -15..15 via the LUTs at 0x601e123c]'
    # 2. extended LUTs
    d = BB.MAIN.read_bytes()
    lv_i = spec['edits'].index(edit_at(spec, LV.CODE_AT))
    spec['edits'].insert(spec['edits'].index(e) + 1, dict(
        kind='0x100', addr=hex(BB.HLX_AT), expect=BB.check_hlx(d).hex(), new=BB.hl_ext_bytes().hex(),
        why='v0.17 extended H/L LUTs: hue[31] (-1000/step, |max| 15000) + light[31] for UI -15..15 '
            '(dead EVF step-13 G gamma table, section 1)', source='patches/hl_ext'))
    # 3. live-view reader: legacy rebuild on the base without lv must equal the base lv; then rebuild on the new spec
    def lv_code(s):
        b = dict(s, edits=[x for x in s['edits'] if int(x['addr'], 16) not in (LV.HOOK, LV.CODE_AT)])
        info = LV.base_info(b)
        lab = info['labels']
        syms = dict(ep7_getter=LV.GETTER, ep7_resume=LV.RESUME, ep7_hue_lut=lab['hue_lut'],
                    ep7_light_lut=lab['light_lut'], ep7_perm=lab['perm'], ep7_table=lab['bundle_table'])
        if info['hl_ext']:
            syms.update(ep7_hue_lut=BB.HLX_AT, ep7_light_lut=BB.HLX_AT + 62)
        if info['sd_v3']:
            syms['ep7_tbl_idx'] = info['tbl_idx']
        LV.check_static(d, info)
        return LV.assemble(LV.source(info['sd_v3'], info['hl_ext']), syms)[0], info['hl_ext']
    old_lv, x0 = lv_code(base)
    if x0 or old_lv.hex() != base['edits'][lv_i]['new']:
        raise ValueError('base lv != patches/lv_bundles legacy rebuild')
    new_lv, x1 = lv_code(spec)
    if not x1 or len(new_lv) != len(old_lv):
        raise ValueError('lv extended rebuild: not extended or size changed')
    le = edit_at(spec, LV.CODE_AT)
    le['new'] = new_lv.hex()
    le['why'] += ' [v0.17: extended H/L -15..15]'
    # 4. range tables (data only)
    lay = SB.layout()
    lo0, sp0, _ = SB.range_table(lay, SB.RANGES_LEGACY)
    lo1, sp1, _ = SB.range_table(lay, SB.RANGES_HLX)
    b8 = lambda v: bytes(x & 0xff for x in v)                   # noqa: E731
    ld = edit_at(spec, LOADER_AT)
    blob = bytes.fromhex(ld['new'])
    blob = swap_once(blob, b8(lo0) + b8(sp0), b8(lo1) + b8(sp1), 'loader sd_lo/sd_span')
    o = SD_BACK - LOADER_AT
    if blob[o:o + 5].hex() != SD_BACK_JMP:
        raise ValueError('loader sd_back is not jmp ed_trig 0x605b7340')
    ld['new'] = blob.hex()
    ld['why'] += ' [v0.17: hue/light ranges -15..15]'
    fm = [x for x in spec['edits'] if b8(lo0[:45]) in bytes.fromhex(x['new']) and int(x['addr'], 16) != LOADER_AT]
    if len(fm) != 1:
        raise ValueError(f'film menu fm_lo: {len(fm)} candidate edits')
    blob = bytes.fromhex(fm[0]['new'])
    blob = swap_once(blob, b8(lo0[:45]), b8(lo1[:45]), 'fm_lo')
    blob = swap_once(blob, b8(sp0[:45]), b8(sp1[:45]), 'fm_span')
    fm[0]['new'] = blob.hex()
    fm[0]['why'] += ' [v0.17: hue/light ranges -15..15]'
    # 5. editor guide label (v0.17 camera bug): with extended values the clamped (+-5) page can sit at both -5 and +5;
    #    the stock guide part then blanks the ALL-off label (id 0) and ed_guide used to leave it blank. ed_view is
    #    rebuilt with the fix; only its entry ed_guide (0x60b9dd10) is referenced from outside (checked).
    ve = edit_at(spec, LE.VIEW[0])
    sy = spec['look_editor']['symbols']
    extra = dict(LE.STOCK, ed_poke=int(sy['ed_poke'], 16), ed_cfg_fm=int(sy['ed_cfg_fm'], 16),
                 ed_cfg_x=int(sy['ed_cfg_x'], 16))
    v_old = LE.B3.assemble(LE.B3.subst(VIEW_V016.read_text(), LE.sub(False)), LE.VIEW[0], extra)[0]
    if v_old.hex() != ve['new']:
        raise ValueError('base ed_view != the v0.16 source rebuild')
    v_new, _, vs, _ = LE.B3.assemble(LE.source('ed_view.s.in', False), LE.VIEW[0], extra)
    if vs['ed_guide'] != LE.VIEW[0] or LE.VIEW[0] + len(v_new) > LE.VIEW[1]:
        raise ValueError('fixed ed_view does not fit')
    for x in spec['edits']:
        a, b = int(x['addr'], 16), bytes.fromhex(x['new'])
        if a != LE.VIEW[0] and any(LE.VIEW[0] < w < LE.VIEW[1] for w in
                                   (int.from_bytes(b[i:i + 4], 'little') for i in range(len(b) - 3))):
            raise ValueError(f'edit {x["addr"]} references inside ed_view')
    ve['expect'] = BB.MAIN.read_bytes()[LE.VIEW[0] - BB.BASE:LE.VIEW[0] - BB.BASE + len(v_new)].hex()
    ve['new'] = v_new.hex()
    ve['why'] += ' [v0.17: ed_guide labels the page when the stock part blanked the ALL-off guide]'
    spec['look_editor']['symbols'].update({k: hex(v) for k, v in vs.items() if k in sy})
    spec['hl_ext'] = dict(hue_lut=hex(BB.HLX_AT), light_lut=hex(BB.HLX_AT + 62), ui_max=BB.HL_MAX,
                          hue_lut_x=BB.HUE_LUT_X, light_lut_x=BB.L_LUT_X, sd_v3=sd_v3, film_menu_edit=fm[0]['addr'],
                          built_by='patches/hl_ext/build.py')
    for a, b in ((e, base['edits'][[x['addr'] for x in base['edits']].index(e['addr'])]),):
        if len(a['new']) != len(b['new']):
            raise ValueError('reader size changed')
    return spec


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('base', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    try:
        spec = make(json.loads(a.base.read_text()))
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.write_text(json.dumps(spec, indent=1) + '\n')
    print(f'{len(spec["edits"])} edits -> {a.out}')


if __name__ == '__main__':
    main()
