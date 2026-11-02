#!/usr/bin/env python3
"""Build the E-P7 1.1 per-profile Blacks / Whites layer (offline; never contacts a camera). docs/TONE_ENDS.md §6

  .venv/bin/python -I patches/tone_ends/build.py [--base releases/v0.18/edits.json] [--out generated/tone_ends]

The base spec must be a released spec with the bundles v0.2 reader (labels hl/out/code_start/code_end/bundle_table)
and, for the --sd-v3 table, the loader v3 accessor (found from the reader's own bytes, as patches/lv_bundles does).
Nothing of the base is rebuilt: tone is a byte-level layer on top of it.

Edits (main, component 0x100):
  0x603b14ff  7 B  mov d3,a0; call 0x603b0c66,[d2,d3,a2,a3],72  ->  call tone,[d2,d3,a2,a3],72 (d32 form)
  0x601e103c  n B  tone piece A (gate) in the dead EVF gamma step-14 B table (section 1)
  0x601e133c  n B  tone piece B (remap) in the dead EVF gamma step-13 B table (section 1)

Writes <out>/edits.json (tone edits + metadata), <out>/merged.json (base + tone), routine.s/.lst/.bin (.bin = piece A + piece B, concatenated).
"""
import argparse, hashlib, importlib.util, json, struct, subprocess, sys, tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('lv_bundles_build', ROOT / 'patches/lv_bundles/build.py')
LB = importlib.util.module_from_spec(_spec)   # EditImage, reader_sd_v3: generic spec readers (unchanged since v0.16)
_spec.loader.exec_module(LB)

TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
BASE = 0x60020020
DEFAULT_BASE = ROOT / 'releases/v0.18/edits.json'

HOOK, HOOK_STOCK = 0x603b14ff, bytes.fromhex('f1eccd65f7f048')   # mov d3,a0; call 0x603b0c66,[d2,d3,a2,a3],72
RESUME, NEXT = 0x603b1506, 0x603b0c66                            # stock return address; next stage
BUILDER_CALL, BUILDER_CALL_STOCK = 0x603b14f8, bytes.fromhex('f1eccd76f5f0b0')   # mov d3,a0; call 0x603b0a70,..,176
NEXT_STOCK = bytes.fromhex('430cf8003c')                          # 0x603b0c66: mov a0,(12,sp); mov (60,a0),d0
GETTER = 0x6005e971
GETTER_STOCK = bytes.fromhex('8782b000c9121c')
PROP_PROFILE = 0xF6B1                                             # setting 908: effective COLOR profile 1..4
# bundles v0.2 job ABI (patches/bundles/layout.json job_extension; checked against the base's own `hl` bytes)
CALLBACK, REQ_IN_JOB, RECORDS_IN_JOB, REC_STRIDE, N_REC = 0x60355fd4, 11364, 14576, 56, 16
JOB_SIZE = 15488
EXT_PROFILE, EXT_MODE, EXT_MAGIC, MAGIC = JOB_SIZE, JOB_SIZE + 1, JOB_SIZE + 2, 0xB2
SLOT_BLACKS, SLOT_WHITES = 47, 48
# Placement: EVF (device index 1) display-gamma step-14 B LUT (256 B). Only reference: the step-table word
# 0x601e3d5c + 12 (entry {14, R, G, B}). R/G of step 14 hold patches/lv_bundles, step-13 R holds lv_art.
CODE_AT, CODE_END = 0x601e103c, 0x601e113c                       # piece A: gate (EVF step-14 B table)
STEP14 = 0x601e3d5c
REF_WORD = STEP14 + 12
CODE_B, CODE_B_END = 0x601e133c, 0x601e143c                       # piece B: remap (EVF step-13 B table)
STEP13 = 0x601e3d4c
REF_WORD_B = STEP13 + 12
PIECES = ((CODE_AT, CODE_END, STEP14, REF_WORD, (14, 0x601e0e3c, 0x601e0f3c, CODE_AT)),
          (CODE_B, CODE_B_END, STEP13, REF_WORD_B, (13, 0x601e113c, 0x601e123c, CODE_B)))
SEC1_START, SEC1_END = 0x600d7800, 0x60211000
LUT_BLOCK = (0x601de13c, 0x601e3b3c)
# abs32 brute-force hits that are instruction bytes, not pointers (dis-checked; bytes pinned here):
#   0x606209a4 `dd 10 1e a0 ff 00 04` call 0x600227b4,[],4 (rel32 reads as 0xa01e10dd)
#   0x6064475d `5c 10 1e 60` mov (16,sp),a0; exthu d2; mov d0,(a0) (reads as 0x601e105c)
FALSE_POS = {0x606209a4: bytes.fromhex('dd101ea0ff0004'), 0x6064475d: bytes.fromhex('5c101e60')}                              # display gamma LUT data (TFT + EVF)

TBL_SLOT_SDV3 = ' call ep7_tbl_idx,[d2,d3],8          /* a0 = slot d0 of the active table (d0 kept) */'
TBL_SLOT_FLASH = ''' mov d0,d1
 asl 6,d1
 mov ep7_table,a0
 add d1,a0'''


def source(sd_v3):
    sub = dict(callback=hex(CALLBACK), rec_off=RECORDS_IN_JOB - REQ_IN_JOB, n_rec=N_REC, stride=REC_STRIDE,
               req_in_job=REQ_IN_JOB, ext_magic=EXT_MAGIC, ext_mode=EXT_MODE, ext_profile=EXT_PROFILE,
               magic=hex(MAGIC), prop_profile=hex(PROP_PROFILE),
               tbl_note='SD loader v3 accessor tbl_idx' if sd_v3 else 'flashed table 0x60210900',
               tbl_slot=TBL_SLOT_SDV3 if sd_v3 else TBL_SLOT_FLASH)
    src = (Path(__file__).parent / 'tone.s.in').read_text()
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
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), f'--section-start=.tone_b={CODE_B:#x}', '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in syms.items()], '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.tone_b', t / 'p.elf', t / 'b.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        labels = {}
        for line in nm.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] in 'tT':
                labels[parts[2]] = int(parts[0], 16)
        return ((t / 'p.bin').read_bytes(), (t / 'b.bin').read_bytes()), (t / 'p.lst').read_text(), labels


def call_d32(at, target, regs=0xf0, frame=72):
    """dd rel32 regs imm8: call target,[regs],frame (7 B, return address at+7)."""
    return b'\xdd' + struct.pack('<i', target - at) + bytes((regs, frame))


def abs32_refs(d, lo, hi):
    a = np.frombuffer(d, np.uint8).astype(np.int64)
    w = a[:-3] | (a[1:-2] << 8) | (a[2:-1] << 16) | (a[3:] << 24)
    out = []
    for off in (0, 0x40000000):          # 0x6... and its uncached 0xA... alias
        out += [int(h) + BASE for h in np.nonzero((w >= lo + off) & (w < hi + off))[0]]
    return sorted(out)


def base_info(base):
    lab = {k: int(v, 16) for k, v in base.get('labels', {}).items()}
    for k in ('hl', 'out', 'code_start', 'code_end', 'bundle_table'):
        if k not in lab:
            raise ValueError(f'base spec lacks bundles label {k!r}')
    img = LB.EditImage(base['edits'])
    for kind_addr, n in ((HOOK, len(HOOK_STOCK)), (CODE_AT, CODE_END - CODE_AT), (CODE_B, CODE_B_END - CODE_B)):
        for e in base['edits']:
            if e['kind'] != '0x100' or e['addr'].startswith('off'):
                continue
            a = int(e['addr'], 16)
            if a < kind_addr + n and kind_addr < a + len(bytes.fromhex(e['new'])):
                raise ValueError(f'base spec already edits {kind_addr:#x}..{kind_addr + n:#x} ({e["addr"]})')
    sd_v3, acc = LB.reader_sd_v3(base, lab, img)
    # The job ABI constants must be the ones the base's own capture reader uses.
    hl = img.get(lab['hl'], lab['out'] - lab['hl'])
    if hl is None:
        raise ValueError('base edits do not hold the bundles hl routine')
    for what, pat in (('callback', struct.pack('<I', CALLBACK)), ('marker', bytes((MAGIC,))),
                      ('ext_magic', struct.pack('<H', EXT_MAGIC)), ('ext_mode', struct.pack('<H', EXT_MODE)),
                      ('ext_profile', struct.pack('<H', EXT_PROFILE)),
                      ('rec_off', struct.pack('<H', RECORDS_IN_JOB - REQ_IN_JOB))):
        if pat not in hl:
            raise ValueError(f'base hl routine does not contain the {what} constant')
    return dict(labels=lab, sd_v3=sd_v3, tbl_idx=acc, image=img)


def check_static(d, info):
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    for at, want, what in ((HOOK, HOOK_STOCK, 'hook'), (BUILDER_CALL, BUILDER_CALL_STOCK, 'builder call'),
                           (NEXT, NEXT_STOCK, 'next stage entry'), (GETTER, GETTER_STOCK, 'getter entry')):
        if d[at - BASE:at - BASE + len(want)] != want:
            raise ValueError(f'stock bytes differ at the {what} {at:#x}')
    for lo, hi, step, ref, want in PIECES:
        ent = struct.unpack_from('<4I', d, step - BASE)
        if ent != want:
            raise ValueError(f'EVF step-{want[0]} entry {[hex(x) for x in ent]} does not point B at {lo:#x}')
        if not (SEC1_START <= lo and hi <= SEC1_END and LUT_BLOCK[0] <= lo and hi <= LUT_BLOCK[1]):
            raise ValueError('placement outside section 1 / the gamma LUT block')
        refs = abs32_refs(d, lo, hi)
        for a, b in FALSE_POS.items():
            if d[a - BASE:a - BASE + len(b)] != b:
                raise ValueError(f'false-positive site {a:#x} bytes changed')
        if sorted(set(refs) - set(FALSE_POS)) != [ref]:
            raise ValueError(f'unexpected abs32 references into {lo:#x}: {[hex(r) for r in refs]}')
    return d[CODE_AT - BASE:CODE_END - BASE], d[CODE_B - BASE:CODE_B_END - BASE]


def make_spec(base_path):
    base = json.loads(Path(base_path).read_text())
    info = base_info(base)
    d = MAIN.read_bytes()
    stock_a, stock_b = check_static(d, info)
    syms = dict(ep7_getter=GETTER, ep7_next=NEXT, ep7_table=info['labels']['bundle_table'])
    if info['sd_v3']:
        syms['ep7_tbl_idx'] = info['tbl_idx']
    src = source(info['sd_v3'])
    (code, code_b), lst, labels = assemble(src, syms)
    if labels['tone'] != CODE_AT or CODE_AT + len(code) > CODE_END:
        raise ValueError(f'tone piece A {len(code)} B does not fit {CODE_END - CODE_AT} B')
    if labels['remap'] != CODE_B or CODE_B + len(code_b) > CODE_B_END:
        raise ValueError(f'tone piece B {len(code_b)} B does not fit {CODE_B_END - CODE_B} B')
    hook = call_d32(HOOK, labels['tone'])
    edits = [
        dict(kind='0x100', addr=hex(HOOK), expect=HOOK_STOCK.hex(), new=hook.hex(),
             why='stage list after the luminance-LUT builder: mov d3,a0; call 0x603b0c66,[d2,d3,a2,a3],72 -> '
                 'call tone,[d2,d3,a2,a3],72 (per-profile Blacks/Whites; tone replays mov d3,a0 and jumps to 0x603b0c66)'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=stock_a[:len(code)].hex(), new=code.hex(),
             why=f'tone piece A, gate ({len(code)} B) in the dead EVF gamma step-14 B table (section 1)'),
        dict(kind='0x100', addr=hex(CODE_B), expect=stock_b[:len(code_b)].hex(), new=code_b.hex(),
             why=f'tone piece B, remap ({len(code_b)} B) in the dead EVF gamma step-13 B table (section 1)'),
    ]
    meta = dict(labels={k: hex(v) for k, v in labels.items()}, code_at=hex(CODE_AT), code_end=hex(CODE_END),
                code_len=len(code), code_b=hex(CODE_B), code_b_end=hex(CODE_B_END), code_b_len=len(code_b),
                ref_word_b=hex(REF_WORD_B), hook=hex(HOOK), resume=hex(RESUME), next=hex(NEXT), getter=hex(GETTER),
                prop_profile=hex(PROP_PROFILE), ref_word=hex(REF_WORD), sd_v3=info['sd_v3'],
                tbl_idx=hex(info['tbl_idx']) if info['tbl_idx'] else None,
                slot_bytes=dict(blacks=SLOT_BLACKS, whites=SLOT_WHITES, range=[-5, 5]),
                reference='tools/ep7_tone.py remap(lut, B, W)', syms={k: hex(v) for k, v in syms.items()},
                base=str(base_path), base_sha256=hashlib.sha256(Path(base_path).read_bytes()).hexdigest())
    spec = dict(components=['0x100'], patch='tone_ends', tone_ends=meta, edits=edits)
    merged = dict(base)
    merged['edits'] = base['edits'] + [dict(e, source='patches/tone_ends') for e in edits]
    merged['sources'] = list(base.get('sources', [])) + ['patches/tone_ends']
    merged['meta'] = dict(base.get('meta', {}), tone_ends=meta)
    merged['tone_ends'] = meta
    return spec, merged, src, lst, code + code_b


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--base', type=Path, default=DEFAULT_BASE)
    ap.add_argument('--out', type=Path, default=ROOT / 'generated/tone_ends')
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
    m = spec['tone_ends']
    print(f'tone A {m["code_len"]} B at {CODE_AT:#x}, B {m["code_b_len"]} B at {CODE_B:#x} (sd_v3={spec["tone_ends"]["sd_v3"]}); hook {HOOK:#x}; '
          f'{len(merged["edits"])} merged edits -> {a.out}')


if __name__ == '__main__':
    main()
