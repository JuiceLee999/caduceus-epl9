#!/usr/bin/env python3
"""Build the E-P7 1.1 live-view look preview, phase 1 (offline; never contacts a camera). docs/LV_ART_PREVIEW.md

  .venv/bin/python -I patches/lv_art/build.py --base releases/test12c-editor/edits.json --out generated/lv_art
  (--features hl,bloom[,grain]; default hl,bloom)

The base spec must contain the bundles v0.2 reader with the SD loader v3 accessor (patches/bundles --sd-v3) and
the bloom/clarity weight getter (patches/bloom --sd-v3 --clarity), as test 9 and later do.

Edits (main, component 0x100):
  0x60353c6f  6 B  mov a3,a0; call 0x60354709,[d2,a2,a3],16  ->  jmp lv_art; nop   (job constructor, pre-dispatch)
  0x601e113c  n B  lv_art in the dead EVF step-13 R gamma table (section 1; only reference 0x601e3d50)

Writes <out>/edits.json (lv_art edits + metadata), <out>/merged.json (base + lv_art), routine.s/.lst/.bin.
"""
import argparse, hashlib, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'patches/bundles'))
import build as BB  # noqa: E402  (patches/bundles/build.py: constants, layout)

TC = BB.TC
MAIN, MAIN_SHA, BASE = BB.MAIN, BB.MAIN_SHA, BB.BASE

HOOK, HOOK_STOCK = 0x60353c6f, bytes.fromhex('9ccd990ab010')    # mov a3,a0; call 0x60354709,[d2,a2,a3],16
RESUME = 0x60353c75
DISPATCH = 0x60354709
LV_RET = 0x60321eaf                                             # after `call 0x603537eb` at 0x60321ea8 (IPCR dev handler)
LV_CALL, LV_CALL_STOCK = 0x60321ea8, bytes.fromhex('dd43190300f02c')
CTOR = 0x603537eb
GETTER = 0x6005e971
GETTER_STOCK = bytes.fromhex('8782b000c9121c')
PROP_PROFILE = 0xF6B1
KEY_OFF, TYPE_OFF, FLAGS_OFF = 11308, 20, 16
F_GRAIN, F_EFFECT, F_STRENGTH, F_FLAGS = 24, 28, 29, 31
CODE_AT, CODE_END = 0x601e113c, 0x601e123c                      # EVF step-13 R LUT (256 B)
STEP_TABLE = 0x601e3b3c
EVF_SLOT13 = STEP_TABLE + 320 + 13 * 16                        # {u8 step, R*, G*, B*}
SEC1_START, SEC1_END = BB.SEC1_START, BB.SEC1_END
TAKEN = [(0x601e0e3c, 0x601e103c, 'lv_bundles'), (0x601e323c, 0x601e383c, 'look_extras'),
         (0x601e383c, 0x601e3a3c, 'view_assist')]
FEATURES = ('hl', 'bloom', 'grain', 'art')
F_ART = 46
# v0.14 Art Effect in LV (slot +46, patches/bloom --art): only the effects whose stages exist in stock LV job classes
# 5-8 (work-list builder run natively, tools/ep7_lv_art_effect_verify.py): 2 Pin Hole 0x400, 3 Blur 0x100 (Diorama V),
# 4 White Edge 0x2000, 5 Frame 0x8000. 1 Star Light has no stage in classes 5-7 and stock LV gates it: not previewed.
LV_ART_FLAGS = {2: 0x400, 3: 0x100, 4: 0x2000, 5: 0x8000}

TBL_SLOT_SDV3 = ' call ep7_tbl_idx,[d2,d3],8          /* a0 = slot d0 of the active table (d0 preserved) */'
FEAT_HL = ''' movbu ({f_flags},a0),d0               /* H/L enabled (bundles `hl` reads it) */
 btst 2,d0
 beq 1f
 or 1,d2
1:'''
FEAT_BLOOM = ''' movbu ({f_effect},a0),d0              /* effect 1 bloom / 2 red bloom (luma glow; clarity 3 is not previewed: c12 w = 1024) */
 add -1,d0
 cmp 2,d0
 bcc 2f
 movbu ({f_strength},a0),d0
 add -1,d0
 cmp 5,d0
 bcc 2f
 or 3,d2
2:'''
GRAIN_ON = ''' movbu ({f_grain},a0),d0               /* grain 1..3 previewed too */
 add -1,d0
 cmp 3,d0
 bcc 3f
 or 1,d2
3:'''
GRAIN_OFF = ''' movbu ({f_grain},a0),d0               /* grain slot: the transport would enable LV grain -> stock */
 cmp 0,d0
 beq 3f
 clr d2
3:'''


FEAT_ART = ''' movbu ({f_art},a0),d0                 /* v0.14 Art Effect: 2 Pin Hole, 3 Blur, 4 White Edge, 5 Frame (Star Light: no LV stage) */
 add -2,d0
 cmp 4,d0
 bcc 4f
 asl2 d0
 mov lv_art_tab,a1
 add d0,a1
 mov (a1),d1
 mov ({flags_off},a3),d0
 or d1,d0
 mov d0,({flags_off},a3)              /* the stock job flag the LV converter sets for that Art Effect in ART mode */
4:'''


def source(features):
    fs = dict(f_flags=F_FLAGS, f_effect=F_EFFECT, f_strength=F_STRENGTH, f_grain=F_GRAIN, f_art=F_ART, flags_off=FLAGS_OFF)
    blocks = []
    if 'hl' in features:
        blocks.append(FEAT_HL)
    if 'bloom' in features:
        blocks.append(FEAT_BLOOM)
    blocks.append(GRAIN_ON if 'grain' in features else GRAIN_OFF)
    if 'art' in features:
        blocks.append(FEAT_ART)
    code = '\n'.join(b.format(**fs) for b in blocks)
    doc = [' *       ' + s for s in (
        ['H/L flag (+31 bit 1)'] if 'hl' in features else []) + (
        ['bloom (effect_id 1 or 2, strength 1..5) -> also job flag 0x80'] if 'bloom' in features else []) + (
        ['grain 1..3'] if 'grain' in features else ['and NO grain (a grain slot stays stock: grain is not previewed)']) + (
        ['art effect +46: 2/3/4/5 -> job flag 0x400/0x100/0x2000/0x8000 (no transport needed)'] if 'art' in features else [])]
    sub = dict(lv_ret=hex(LV_RET), key_off=KEY_OFF, type_off=TYPE_OFF, flags_off=FLAGS_OFF, prop_profile=hex(PROP_PROFILE),
               tbl_slot=TBL_SLOT_SDV3, feat_code=code, feat_doc='\n'.join(doc), ext_profile=BB.EXT_PROFILE,
               ext_mode=BB.EXT_MODE, ext_magic=BB.EXT_MAGIC, magic=hex(BB.MAGIC))
    sub['art_tab'] = ('\n .balign 4\nlv_art_tab:\n .long ' + ', '.join(hex(LV_ART_FLAGS[k]) for k in (2, 3, 4, 5))) if 'art' in features else ''
    src = (Path(__file__).parent / 'lv_art.s.in').read_text()
    for k, v in sub.items():
        src = src.replace('{' + k + '}', str(v))
    if '{' in src or '}' in src:
        raise ValueError('unsubstituted template field')
    return src


def assemble(src, syms):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in syms.items()], '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        labels = {}
        for line in nm.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] in 'tT':
                labels[parts[2]] = int(parts[0], 16)
        return (t / 'p.bin').read_bytes(), (t / 'p.lst').read_text(), labels


def base_info(base):
    lab = {k: int(v, 16) for k, v in base.get('labels', {}).items()}
    if 'bundle_table' not in lab or 'hl' not in lab:
        raise ValueError('base spec lacks the bundles v0.2 reader')
    meta = base.get('meta', {})
    acc = None
    for v in meta.values():
        if isinstance(v, dict) and isinstance(v.get('sd_v3'), dict) and 'accessor' in v['sd_v3']:
            acc = int(v['sd_v3']['accessor']['tbl_idx'], 16)
    if acc is None:
        raise ValueError('base spec has no SD loader v3 accessor (build bundles/bloom with --sd-v3)')
    bloom = next((v['bloom'] for v in meta.values() if isinstance(v, dict) and 'bloom' in v
                  and isinstance(v['bloom'], dict) and 'symbols' in v['bloom']), None)
    if bloom is None or 'clarity' not in bloom:
        raise ValueError('base spec has no bloom/clarity weight getter (patches/bloom --sd-v3 --clarity)')
    ext = bloom['ext']
    if (ext['profile'], ext['mode'], ext['marker'], ext['magic']) != (BB.EXT_PROFILE, BB.EXT_MODE, BB.EXT_MAGIC, BB.MAGIC):
        raise ValueError('bloom transport layout differs from patches/bundles')
    for e in base['edits']:
        a, n = int(e['addr'], 16), len(bytes.fromhex(e['new']))
        if e['kind'] == '0x100' and a < HOOK + 6 and HOOK < a + n:
            raise ValueError('base spec already edits the hook')
        if e['kind'] == '0x100' and a < CODE_END + 16 and CODE_AT - 16 < a + n:
            raise ValueError('base spec edits the lv_art placement or its guards')
    if not any(int(e['addr'], 16) == BB.ALLOC for e in base['edits']):
        raise ValueError('base spec does not extend the job (bundles 0x603537f0)')
    return dict(labels=lab, tbl_idx=acc, bloom=bloom)


def check_static(d):
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    g = lambda a, n: d[a - BASE:a - BASE + n]
    if g(HOOK, 6) != HOOK_STOCK:
        raise ValueError('stock bytes differ at the hook')
    if g(LV_CALL, 7) != LV_CALL_STOCK or LV_CALL + 7 != LV_RET:
        raise ValueError('IPCR handler constructor call differs')
    if g(GETTER, len(GETTER_STOCK)) != GETTER_STOCK:
        raise ValueError('getter entry bytes differ')
    if d[EVF_SLOT13 - BASE] != 13 or struct.unpack_from('<I', d, EVF_SLOT13 + 4 - BASE)[0] != CODE_AT:
        raise ValueError('EVF step-13 slot R does not point at the placement')
    if not (SEC1_START <= CODE_AT and CODE_END <= SEC1_END):
        raise ValueError('placement outside section 1')
    for lo, hi, who in TAKEN:
        if CODE_AT < hi and lo < CODE_END:
            raise ValueError(f'placement overlaps {who}')
    return g(CODE_AT, CODE_END - CODE_AT)


def make_spec(base_path, features):
    base = json.loads(Path(base_path).read_text())
    info = base_info(base)
    d = MAIN.read_bytes()
    stock_tail = check_static(d)
    syms = dict(ep7_getter=GETTER, ep7_resume=RESUME, ep7_dispatch=DISPATCH, ep7_tbl_idx=info['tbl_idx'])
    src = source(features)
    code, lst, labels = assemble(src, syms)
    if labels['lv_art'] != CODE_AT or CODE_AT + len(code) > CODE_END:
        raise ValueError(f'lv_art {len(code)} B does not fit {CODE_END - CODE_AT} B')
    hook = BB.jmp_d32(HOOK, labels['lv_art'], 6)
    edits = [
        dict(kind='0x100', addr=hex(HOOK), expect=HOOK_STOCK.hex(), new=hook.hex(),
             why='job constructor pre-dispatch: mov a3,a0; call 0x60354709 -> jmp lv_art (live-view look preview)'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=stock_tail[:len(code)].hex(), new=code.hex(),
             why=f'lv_art ({len(code)} B) in the dead EVF step-13 R gamma table (section 1)'),
    ]
    meta = dict(labels={k: hex(v) for k, v in labels.items()}, code_at=hex(CODE_AT), code_len=len(code),
                hook=hex(HOOK), resume=hex(RESUME), dispatch=hex(DISPATCH), lv_ret=hex(LV_RET), getter=hex(GETTER),
                prop_profile=hex(PROP_PROFILE), tbl_idx=hex(info['tbl_idx']), features=sorted(features),
                job=dict(key=KEY_OFF, type=TYPE_OFF, flags=FLAGS_OFF, ext_profile=BB.EXT_PROFILE,
                         ext_mode=BB.EXT_MODE, ext_magic=BB.EXT_MAGIC, magic=BB.MAGIC),
                slot=dict(grain=F_GRAIN, effect=F_EFFECT, strength=F_STRENGTH, flags=F_FLAGS),
                syms={k: hex(v) for k, v in syms.items()})
    spec = dict(components=['0x100'], patch='lv_art', base=str(base_path), lv_art=meta, edits=edits)
    merged = dict(base)
    merged['edits'] = base['edits'] + [dict(e, source='patches/lv_art') for e in edits]
    merged['sources'] = list(base.get('sources', [])) + ['patches/lv_art']
    merged['meta'] = dict(base.get('meta', {}), lv_art=meta)
    merged['lv_art'] = meta
    return spec, merged, src, lst, code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--features', default='hl,bloom')
    a = ap.parse_args()
    feats = {f for f in a.features.split(',') if f}
    if not feats <= set(FEATURES) or not feats & {'hl', 'bloom', 'grain'}:
        sys.exit(f'error: --features from {FEATURES}')
    try:
        spec, merged, src, lst, code = make_spec(a.base, feats)
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'merged.json').write_text(json.dumps(merged, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    print(f'lv_art {len(code)} B at {CODE_AT:#x} features={sorted(feats)}; hook {HOOK:#x}; '
          f'{len(merged["edits"])} merged edits -> {a.out}')


if __name__ == '__main__':
    main()
