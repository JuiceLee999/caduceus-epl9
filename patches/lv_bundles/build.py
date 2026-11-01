#!/usr/bin/env python3
"""Build the E-P7 1.1 live-view bundle H/L edit spec (offline; never contacts a camera). docs/LV_BUNDLES.md

  .venv/bin/python -I patches/lv_bundles/build.py --base releases/test12c-editor/edits.json --out generated/lv_bundles

The base spec must contain the bundles v0.2 reader (patches/bundles; `hue_lut`/`light_lut`/`perm` labels and
the `hl` hook at 0x603b02d9). If its bundles reader was built with --sd-v3, lv reads the table through the
SD loader v3 accessor `tbl_idx` (same table the capture reader uses); otherwise the flashed table 0x60210900.

Edits (main, component 0x100):
  0x603b02de  6 B  mov (60,a2),d0; btst 2,d0  ->  jmp lv; nop      (COLOR selector, after the builder)
  0x601e0e3c  n B  lv routine in the dead EVF step-14 R/G gamma tables (section 1; docs/LV_BUNDLES.md §4)

Writes <out>/edits.json (lv edits only, with metadata for tools/ep7_verify_lv_bundles.py), <out>/merged.json
(base + lv, through tools/merge_specs.py semantics), routine.s/.lst/.bin.
"""
import argparse, hashlib, json, re, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'patches/bundles'))
import build as BB  # noqa: E402  (patches/bundles/build.py: constants, LUTs, layout)

TC = BB.TC
MAIN, MAIN_SHA, BASE = BB.MAIN, BB.MAIN_SHA, BB.BASE

HOOK, HOOK_STOCK = 0x603b02de, bytes.fromhex('f8023cf8ec02')     # mov (60,a2),d0; btst 2,d0
RESUME, RESUME_STOCK = 0x603b02e4, bytes.fromhex('c854')         # beq 0x603b0338
GETTER = 0x6005e971                                              # property getter (d0 key, d1 index, a0 0 = global)
GETTER_STOCK = bytes.fromhex('87 82 b0 00 c9 12 1c'.replace(' ', ''))
PROP_PROFILE = 0xF6B1                                            # 63153: setting 908, effective COLOR profile 1..4
# Placement: EVF (device index 1) gamma step-14 R and G LUTs, 2 x 256 B contiguous. Only references: the display
# step table entry 0x601e3b3c + 320 + 14*16 (+4 R pointer, +8 G pointer). EVF tables are dead on the E-P7 (no EVF; same argument and same
# table block as patches/view_assist, which uses EVF step 0 R/G at 0x601e383c..0x601e3a3c, camera-run in test 11).
CODE_AT, CODE_END = 0x601e0e3c, 0x601e103c
STEP_TABLE, EVF_SLOT14_R = 0x601e3b3c, 0x601e3b3c + 320 + 14 * 16 + 4
SEC1_START, SEC1_END = BB.SEC1_START, BB.SEC1_END
VA_CLAIM = (0x601e383c, 0x601e3a3c)

TBL_BASE_SDV3 = ' call ep7_tbl_idx,[d2,d3],8          /* d0 = 0 -> a0 = slot 0 of the active table */'
TBL_SLOT_SDV3 = ' call ep7_tbl_idx,[d2,d3],8          /* a0 = slot d0 (d0 preserved) */'
TBL_BASE_FLASH = ' mov ep7_table,a0'
TBL_SLOT_FLASH = ''' mov d0,d1
 asl 6,d1
 mov ep7_table,a0
 add d1,a0'''


def source(sd_v3, hl_ext=False):
    vb = BB.HL_MAX if hl_ext else BB.HL_MAX_LEGACY
    sub = dict(val_bias=vb, val_n=2 * vb + 1, hue_ref='ep7_hue_lut', light_ref='ep7_light_lut',callback=hex(BB.CALLBACK), rec_off=BB.RECORDS_IN_JOB - BB.REQ_IN_JOB, n_rec=BB.N_REC,
               stride=BB.REC_STRIDE, req_in_job=BB.REQ_IN_JOB, ext_magic=BB.EXT_MAGIC, magic=hex(BB.MAGIC),
               hue_off=BB.OUT_RECORDS + 18, prop_profile=PROP_PROFILE,
               tbl_base=TBL_BASE_SDV3 if sd_v3 else TBL_BASE_FLASH,
               tbl_slot=TBL_SLOT_SDV3 if sd_v3 else TBL_SLOT_FLASH)
    src = (Path(__file__).parent / 'lv_bundles.s.in').read_text()
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
    """Bundles reader facts from the base spec (labels, sd-v3 accessor) -> dict; raises if unusable."""
    lab = {k: int(v, 16) for k, v in base.get('labels', {}).items()}
    for k in ('hl', 'hue_lut', 'light_lut', 'perm', 'bundle_table'):
        if k not in lab:
            raise ValueError(f'base spec lacks bundles label {k!r} (merge patches/bundles into the base)')
    edits = {(e['kind'], int(e['addr'], 16)): e for e in base['edits']}
    hl_edit = edits.get(('0x100', BB.HOOK))
    if not hl_edit or bytes.fromhex(hl_edit['new'])[:1] != b'\xdc':
        raise ValueError('base spec has no bundles hook at 0x603b02d9')
    if any(a <= HOOK + 5 and HOOK < a + len(bytes.fromhex(e['new'])) for (_, a), e in edits.items()):
        raise ValueError('base spec already edits 0x603b02de..0x603b02e3')
    if any(a < CODE_END + 16 and CODE_AT - 16 < a + len(bytes.fromhex(e['new'])) for (_, a), e in edits.items()):
        raise ValueError('base spec edits the lv placement or its guards')
    img = EditImage(base['edits'])
    sd_v3, acc = reader_sd_v3(base, lab, img)
    # v0.17 extended H/L: the base bundles reader was built with --hl-ext (its LUTs at BB.HLX_AT); lv follows it.
    hl_ext = img.get(BB.HLX_AT, len(BB.hl_ext_bytes())) == BB.hl_ext_bytes()
    return dict(labels=lab, sd_v3=sd_v3, tbl_idx=acc, image=img, hl_ext=hl_ext)


def _meta_accessors(o, found=None):
    """Every SD loader v3 accessor address recorded anywhere in the spec (merges nest metadata arbitrarily)."""
    found = set() if found is None else found
    if isinstance(o, dict):
        a = o.get('accessor')
        if isinstance(a, dict) and isinstance(a.get('tbl_idx'), str):
            found.add(int(a['tbl_idx'], 16))
        for v in o.values():
            _meta_accessors(v, found)
    elif isinstance(o, list):
        for v in o:
            _meta_accessors(v, found)
    return found


def _meta_says_bundles_sdv3(o):
    """Old metadata rule (a 'bundles*' meta entry carrying sd_v3), searched at any nesting depth."""
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(k, str) and k.startswith('bundles') and isinstance(v, dict) and 'sd_v3' in v:
                return True
            if _meta_says_bundles_sdv3(v):
                return True
    elif isinstance(o, list):
        return any(_meta_says_bundles_sdv3(v) for v in o)
    return False


def reader_sd_v3(base, lab, img):
    """Decide from the bundles reader's own bytes whether it reads the table through the SD loader v3 accessor.

    The reader (labels code_start..code_end, as written by the base edits) is disassembled; a `call` to code that
    another base edit placed (outside the reader) is the accessor. Metadata is only a cross-check, since merges
    (tools/merge_specs.py) nest or drop it. Returns (sd_v3, accessor address or None); raises on any disagreement."""
    lo, hi = lab.get('code_start'), lab.get('code_end')
    if lo is None or hi is None or not lo < hi:
        raise ValueError('base spec lacks bundles labels code_start/code_end')
    code = img.get(lo, hi - lo)
    if code is None:
        raise ValueError(f'base edits do not cover the bundles reader {lo:#x}..{hi:#x} in one edit')
    with tempfile.TemporaryDirectory() as t:
        f = Path(t) / 'r.bin'
        f.write_bytes(code)
        out = subprocess.run([TC / 'mn10300-elf-objdump', '-b', 'binary', '-m', 'am33-2', '-D', f'--adjust-vma={lo:#x}',
                              f], check=True, capture_output=True, text=True).stdout
    calls = {int(m.group(1), 16) for m in re.finditer(r'\tcall\t0x([0-9a-f]+)', out)}
    patched = {c for c in calls if not lo <= c < hi and img.covers(c)}
    meta_acc = _meta_accessors(base)
    if len(patched) > 1:
        raise ValueError(f'bundles reader calls several patched routines {sorted(map(hex, patched))}; cannot tell the accessor')
    if patched:
        acc = patched.pop()
        if meta_acc and acc not in meta_acc:
            raise ValueError(f'reader calls {acc:#x} but metadata names accessor(s) {sorted(map(hex, meta_acc))}')
        if not img.starts(acc):
            raise ValueError(f'accessor {acc:#x} is not the start of a base edit')
        return True, acc
    if _meta_says_bundles_sdv3(base) or base.get('sd_v3'):
        raise ValueError('metadata says the bundles reader is sd-v3 but its bytes call no patched accessor')
    if lab['bundle_table'].to_bytes(4, 'little') not in code:
        raise ValueError('flash bundles reader does not reference bundle_table')
    return False, None


class EditImage:
    """Bytes the base spec writes (main), for reading the bundles LUTs it placed."""
    def __init__(self, edits):
        self.e = [(int(e['addr'], 16), bytes.fromhex(e['new'])) for e in edits if e['kind'] == '0x100']

    def get(self, a, n):
        for s, b in self.e:
            if s <= a and a + n <= s + len(b):
                return b[a - s:a - s + n]
        return None

    def covers(self, a):
        return any(s <= a < s + len(b) for s, b in self.e)

    def starts(self, a):
        return any(s == a for s, _ in self.e)


def check_static(d, info):
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    if d[HOOK - BASE:HOOK - BASE + 6] != HOOK_STOCK or d[RESUME - BASE:RESUME - BASE + 2] != RESUME_STOCK:
        raise ValueError('stock bytes differ at the hook / resume')
    if d[GETTER - BASE:GETTER - BASE + len(GETTER_STOCK)] != GETTER_STOCK:
        raise ValueError('getter entry bytes differ')
    if struct.unpack_from('<2I', d, EVF_SLOT14_R - BASE) != (CODE_AT, CODE_AT + 256) or d[EVF_SLOT14_R - 4 - BASE] != 14:
        raise ValueError('EVF step-14 slot R/G do not point at the placement')
    if not (SEC1_START <= CODE_AT and CODE_END <= SEC1_END):
        raise ValueError('placement outside section 1')
    if CODE_AT < VA_CLAIM[1] and VA_CLAIM[0] < CODE_END:
        raise ValueError('placement overlaps the View Assist claim')
    lab, img = info['labels'], info['image']
    want = {'hue_lut': struct.pack('<15h', *BB.HUE_LUT), 'light_lut': struct.pack('<15h', *BB.L_LUT),
            'perm': bytes(BB.PERM)}
    for k, v in want.items():
        if img.get(lab[k], len(v)) != v:
            raise ValueError(f'base image {k} at {lab[k]:#x} != patches/bundles {k}')
    if info['hl_ext']:
        hl = img.get(lab['hl'], lab['out'] - lab['hl']) if 'out' in lab else None
        if hl is None or struct.pack('<I', BB.HLX_AT) not in hl:
            raise ValueError('base has the extended LUTs but its bundles reader does not use them')
    return d[CODE_AT - BASE:CODE_END - BASE]


def make_spec(base_path):
    base = json.loads(Path(base_path).read_text())
    info = base_info(base)
    d = MAIN.read_bytes()
    stock_tail = check_static(d, info)
    lab = info['labels']
    syms = dict(ep7_getter=GETTER, ep7_resume=RESUME, ep7_hue_lut=lab['hue_lut'], ep7_light_lut=lab['light_lut'],
                ep7_perm=lab['perm'], ep7_table=lab['bundle_table'])
    if info['hl_ext']:
        syms.update(ep7_hue_lut=BB.HLX_AT, ep7_light_lut=BB.HLX_AT + 62)
    if info['sd_v3']:
        syms['ep7_tbl_idx'] = info['tbl_idx']
    src = source(info['sd_v3'], info['hl_ext'])
    code, lst, labels = assemble(src, syms)
    if labels['lv'] != CODE_AT or CODE_AT + len(code) > CODE_END:
        raise ValueError(f'lv routine {len(code)} B does not fit {CODE_END - CODE_AT} B')
    new_tail = code + stock_tail[len(code):]            # rest of the dead LUT stays stock
    hook = BB.jmp_d32(HOOK, labels['lv'], 6)
    edits = [
        dict(kind='0x100', addr=hex(HOOK), expect=HOOK_STOCK.hex(), new=hook.hex(),
             why='COLOR selector after the colour builder: mov (60,a2),d0; btst 2,d0 -> jmp lv (live-view bundle H/L)'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=stock_tail[:len(code)].hex(), new=code.hex(),
             why=f'lv routine ({len(code)} B) in the dead EVF step-14 R/G gamma tables (section 1)'),
    ]
    spec = dict(components=['0x100'], patch='lv_bundles', base=str(base_path),
                lv_bundles=dict(labels={k: hex(v) for k, v in labels.items()}, code_at=hex(CODE_AT),
                                code_len=len(code), hook=hex(HOOK), resume=hex(RESUME), getter=hex(GETTER),
                                prop_profile=hex(PROP_PROFILE), sd_v3=info['sd_v3'], hl_ext=info['hl_ext'],
                                tbl_idx=hex(info['tbl_idx']) if info['tbl_idx'] else None,
                                syms={k: hex(v) for k, v in syms.items()}),
                edits=edits)
    merged = dict(base)
    merged['edits'] = base['edits'] + [dict(e, source='patches/lv_bundles') for e in edits]
    merged['sources'] = list(base.get('sources', [])) + ['patches/lv_bundles']
    merged['meta'] = dict(base.get('meta', {}), lv_bundles={k: v for k, v in spec.items() if k != 'edits'})
    merged['lv_bundles'] = spec['lv_bundles']
    return spec, merged, src, lst, code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    try:
        spec, merged, src, lst, code = make_spec(a.base)
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'merged.json').write_text(json.dumps(merged, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    print(f'lv {len(code)} B at {CODE_AT:#x} (sd_v3={spec["lv_bundles"]["sd_v3"]}); hook {HOOK:#x}; '
          f'{len(merged["edits"])} merged edits -> {a.out}')


if __name__ == '__main__':
    main()
