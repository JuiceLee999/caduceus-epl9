#!/usr/bin/env python3
"""Emulator verification of the per-profile Blacks / Whites layer (patches/tone_ends; offline; emulator only).

Builds the packages for MERGED (base + tone, generated/tone_ends/merged.json) and BASE (the same spec without the
tone edits = releases/v0.18) with tools/build_package.build, decodes the main payloads (merged, base, stock =
restore) and runs the REAL stage-list span 0x603b14f8 -> 0x603b1506 natively: `mov d3,a0; call 0x603b0a70`
(the luminance-LUT builder with its real selector 0x603b092f/0x603b039b, art splines and tone-control bender
0x6034ff93), then the hook site 0x603b14ff (tone -> real 0x603b0c66) up to the stage list's resume 0x603b1506.
Live-view profiles come from the real getter 0x6005e971 on a fixture registry (as tools/ep7_verify_lv_bundles.py).
The bundle table is read through the real SD loader v3 accessor tbl_idx. Every image region is read-only.

  S  static: hook = call tone,[d2,d3,a2,a3],72 (d32, return 0x603b1506), stock bytes, no branch into the hook
     interior, only the EVF step-14/13 B table words reference the placements, store audit, changed bytes only
     in the 3 tone edits (merged vs v0.18), package builds, restore == stock, decoded package == emulated image.
  N  byte-identical to v0.18 (output, job, context, live stack, all registers): B=W=0 (stills, LV), no tone byte
     set (registry unmapped: a getter call would fault), out-of-range values, no LUT (O+2608 = 0), key 12 and
     keys that share the low halfword 11, MONO profiles 5..8, profile 0 / 255, wrong callback, foreign parent, capture mode != 11.
  A  active: LUT at O+2612 == tools/ep7_tone.remap(base LUT, B, W) bit-exact, O+2608 = O+2612, O+4 bit 8 clear,
     every other byte of output/job/context/stack/registers == v0.18; monotone; y[0] = 8B (B > 0), y[255] =
     1023 - 10|W| (W < 0). Stills (marker) == LV (getter) LUTs. Contrast -2/0/+2, tone block on, art LUT.
  D  SD loader v3 loaded mode (table in a pool buffer, flashed copy poisoned): active + inactive.

Usage: tools/ep7_verify_tone_ends.py [generated/tone_ends/merged.json] [--json out.json] [--jobs N] [--full]
"""
import argparse, hashlib, json, struct, subprocess, sys, tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'patches/bundles'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
from penf_emulator import Region, execute as _execute  # noqa: E402
import ep7_sdv3_env as SDV3  # noqa: E402
import ep7_verify_bundles as VB  # noqa: E402  (branch_refs, spans_check)
import ep7_verify_lv_bundles as LVV  # noqa: E402  (getter fixtures)
import ep7_tone as TONE  # noqa: E402
from ep7_video_log_probe import request  # noqa: E402

execute = SDV3.wrap(_execute)
BASE = 0x60020020
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
STACK, CTX, JOB, OUT, BLK, ART = 0x18000000, 0x1a000000, 0x1b000000, 0x1c000000, 0x1d000000, 0x1e000000
SP0 = STACK + 0x1800
START, STOP = 0x603b14f8, 0x603b1506
HOOK = 0x603b14ff
REQ_IN_JOB, RECORDS_IN_JOB, REC_STRIDE, CALLBACK = 11364, 14576, 56, 0x60355fd4
JOB_SIZE = 15512
EXT_PROFILE, EXT_MODE, EXT_MAGIC = 15488, 15489, 15490
TONE_BIT = 0x80000000          # C+60: in the builder's tone mask 0x8268063e, not in 0x603b0c66's 0x006024ae
O_LEN = 4096
O4_INIT = 0x5a5a015a           # O+4 with bit 8 set (the stock LUT steps clear it)
REGS = VB.REGS_ALL
SAMPLE = (0, 1, 4, 8, 16, 32, 64, 96, 128, 160, 192, 224, 240, 250, 254, 255)


def sl(m, lo, hi):
    return m[lo - BASE:hi - BASE]


def table_with(t0, slot_bytes):
    """slot_bytes: {slot: (B, W)} (raw s8 values) on top of table t0."""
    t = bytearray(t0)
    for s, (b, w) in slot_bytes.items():
        t[64 * s + 47] = b & 0xff
        t[64 * s + 48] = w & 0xff
    return bytes(t)


def run(img, table, *, live=False, profile=1, mode=11, key=11, contrast=0, tone=(0, 0, 0, 0, 0), art=None,
        callback=CALLBACK, foreign_parent=False, reg=True, bloom=False, ctx60=TONE_BIT, cpu=0):
    """Real stage-list span 0x603b14f8..0x603b1506 on a fixture job. art = (LUT address, strength) -> R+1524."""
    m = bytearray(img)
    m[0x60210900 - BASE:0x60210b00 - BASE] = table
    img = bytes(m)
    q = bytearray(request(key, contrast=contrast))
    if bloom:
        struct.pack_into('<H', q, 1838, 257)              # bloom pass: the builder leaves no LUT
    if any(tone):
        struct.pack_into('<I', q, 1512, BLK)
    if art:
        struct.pack_into('<I', q, 1524, ART)
        struct.pack_into('<h', q, 1832, art[1])
    job = bytearray(JOB_SIZE)
    job[REQ_IN_JOB:REQ_IN_JOB + len(q)] = q
    rec = RECORDS_IN_JOB + REC_STRIDE * 5
    struct.pack_into('<I', job, REQ_IN_JOB, callback)
    struct.pack_into('<I', job, REQ_IN_JOB + 4, JOB + rec)
    struct.pack_into('<I', job, rec, JOB + (64 if foreign_parent else 0))
    if not live:
        job[EXT_PROFILE], job[EXT_MODE], job[EXT_MAGIC] = profile & 0xff, mode, 0xB2
    ctx = bytearray(256)
    struct.pack_into('<I', ctx, 4, JOB + REQ_IN_JOB)
    struct.pack_into('<I', ctx, 12, OUT)
    struct.pack_into('<I', ctx, 60, ctx60)
    struct.pack_into('<5h', ctx, 64, *tone)
    out = bytearray(O_LEN)
    struct.pack_into('<I', out, 4, O4_INIT)
    blk = bytearray(64)
    struct.pack_into('<5h', blk, 0, *tone)
    regions = [Region('code', 0x60330000, sl(img, 0x60330000, 0x603c0000), 'rx'),
               Region('data', 0x604e0000, sl(img, 0x604e0000, 0x60540000), 'r'),
               Region('tone', 0x601e0e3c, sl(img, 0x601e0e3c, 0x601e143c), 'rx'),
               Region('table', 0x60210900, sl(img, 0x60210900, 0x60210b00), 'r'),
               VB.tail2(img),
               Region('getter', LVV.GETTER_LO, sl(img, LVV.GETTER_LO, LVV.GETTER_HI), 'rx'),
               Region('xlate', LVV.XLATE_LO, sl(img, LVV.XLATE_LO, LVV.XLATE_HI), 'rx'),
               Region('xtab', LVV.XTAB, sl(img, LVV.XTAB, LVV.XTAB + 32), 'r'),
               Region('logger', LVV.LOGGER, bytes.fromhex('dff070'), 'rx'),
               LVV.cpu_region(cpu),
               Region('stack', STACK, bytes(0x2000), 'rw', True),
               Region('ctx', CTX, bytes(ctx), 'rw', True), Region('job', JOB, bytes(job), 'rw', True),
               Region('out', OUT, bytes(out), 'rw', True), Region('blk', BLK, bytes(blk), 'r')]
    if art:
        regions.append(Region('art', ART, struct.pack('<III', 0, 0, art[0]) + bytes(20), 'r'))
    if reg:
        regions += LVV.registry(profile)
    regs = {'pc': START, 'sp': SP0, 'd3': CTX, 'a0': 0xa0a0, 'd0': 0xd0d0, 'd1': 0xd1d1, 'a1': 0xa1a1,
            'd2': 0x2222, 'a2': 0xa2a2, 'a3': 0xa3a3, 'mdr': 0x5a5a5a5a}
    r = execute(regions, regs, STOP, limit=400000)
    mem = {x['name']: bytes.fromhex(x['hex']) for x in r['memory']}
    ok = not r['fault'] and r['registers']['pc'] == STOP and r['registers']['sp'] == SP0
    return dict(ok=ok, fault=r['fault'], status=r.get('status'), mem=mem, regs={k: r['registers'][k] for k in REGS},
                insns=r.get('completed'), img=img)


def lut_of(res):
    o = res['mem']['out']
    p = struct.unpack_from('<I', o, 2608)[0]
    if p == 0:
        return p, None
    if p == OUT + 2612:
        return p, list(struct.unpack_from('<256H', o, 2612))
    if p == ART + 0 or not (0x604e0000 <= p < 0x60540000):
        raise ValueError(f'LUT pointer {p:#x} outside fixtures')
    return p, list(struct.unpack_from('<256H', res['img'], p - BASE))


def identical(a, b):
    return dict(ok=a['ok'] and b['ok'], out=a['mem']['out'] == b['mem']['out'], job=a['mem']['job'] == b['mem']['job'],
                ctx=a['mem']['ctx'] == b['mem']['ctx'],
                stack=a['mem']['stack'][SP0 - STACK:] == b['mem']['stack'][SP0 - STACK:], regs=a['regs'] == b['regs'])


def active_check(m, b, B, W):
    """m = merged run, b = base run of the same fixture."""
    _, base_lut = lut_of(b)
    want = TONE.remap(base_lut, B, W)
    o = m['mem']['out']
    p = struct.unpack_from('<I', o, 2608)[0]
    got = list(struct.unpack_from('<256H', o, 2612))
    rest_m, rest_b = bytearray(o), bytearray(b['mem']['out'])
    for x in (rest_m, rest_b):
        x[2608:2612 + 512] = bytes(516)
        x[4:8] = bytes(4)
    o4m, o4b = struct.unpack_from('<I', o, 4)[0], struct.unpack_from('<I', b['mem']['out'], 4)[0]
    sm = identical(m, b)
    sm.pop('out')
    c = dict(**sm, ptr=p == OUT + 2612, lut=got == want, o4=o4m == o4b & ~0x100, rest=rest_m == rest_b,
             mono=all(got[i] <= got[i + 1] for i in range(255)), rng=max(got) <= 1023)
    if base_lut[0] == 0 and B > 0:
        c['lift'] = got[0] == 8 * B
    if base_lut[255] == 1023 and W < 0:
        c['roll'] = got[255] == 1023 + 10 * W
    if B <= 0 and base_lut[0] == 0:
        c['black0'] = got[0] == 0
    if W >= 0 and base_lut[255] == 1023:
        c['white'] = got[255] == 1023
    return c, got


# ------------------------------------------------------------------ case lists (picklable work items)
def n_cases(t0):
    z = t0
    on = table_with(t0, {0: (3, -2), 1: (-4, 5), 2: (5, 0), 3: (0, -5)})
    mono = table_with(t0, {4: (5, -5), 5: (-5, 5), 6: (2, 2), 7: (-1, -1)})
    oor = table_with(t0, {0: (6, -6), 1: (-128, 127), 2: (6, 0), 3: (0, -6)})
    return [
        ('B=W=0 stills COLOR1', dict(table=z, profile=1)),
        ('B=W=0 stills COLOR4 contrast +2', dict(table=z, profile=4, contrast=2)),
        ('B=W=0 LV, registry unmapped (no getter call)', dict(table=z, live=True, profile=2, reg=False)),
        ('B=W=0 LV, tone block on', dict(table=z, live=True, profile=3, reg=False, tone=(0, 0, 5, 0, 0))),
        ('only MONO slots set, LV, registry unmapped', dict(table=mono, live=True, profile=1, reg=False)),
        ('out of range (6/-6/-128/127) stills COLOR1', dict(table=oor, profile=1)),
        ('out of range LV COLOR2', dict(table=oor, live=True, profile=2)),
        ('out of range B=6, W=0 COLOR3', dict(table=oor, profile=3)),
        ('no LUT (C+60 tone bit clear, O+2608 = 0)', dict(table=on, profile=1, ctx60=0)),
        ('request key 12 (MONO)', dict(table=on, profile=1, key=12)),
        ('request key 0x0100000b (high byte set)', dict(table=on, profile=1, key=0x0100000b)),
        ('request key 0x000b0000', dict(table=on, profile=1, key=0x000b0000)),
        ('stills MONO profile 5', dict(table=mono, profile=5)), ('stills MONO profile 8', dict(table=mono, profile=8)),
        ('LV MONO profile 6', dict(table=mono, live=True, profile=6)),
        ('LV profile 5 with COLOR slots set', dict(table=on, live=True, profile=5)),
        ('stills profile 0', dict(table=on, profile=0)), ('stills profile 255', dict(table=on, profile=255)),
        ('LV profile 0', dict(table=on, live=True, profile=0)), ('LV profile 255', dict(table=on, live=True, profile=255)),
        ('capture picture mode 12', dict(table=on, profile=1, mode=12)),
        ('wrong callback', dict(table=on, profile=1, callback=CALLBACK + 1)),
        ('foreign parent', dict(table=on, profile=1, foreign_parent=True)),
    ]


def a_cases(t0, full):
    vals = range(-5, 6) if full else (-5, -3, -1, 0, 1, 3, 5)
    out = []
    for B in range(-5, 6):                                 # all 121 on stills, contrast 0, COLOR2
        for W in range(-5, 6):
            if B or W:
                out.append((f'stills COLOR2 c0 B={B:+d} W={W:+d}', dict(table=table_with(t0, {1: (B, W)}), profile=2), B, W))
    for c in (-2, 2):
        for B in vals:
            for W in vals:
                if B or W:
                    out.append((f'stills COLOR3 c{c:+d} B={B:+d} W={W:+d}',
                                dict(table=table_with(t0, {2: (B, W)}), profile=3, contrast=c), B, W))
    for B, W in ((5, 0), (-5, 0), (0, 5), (0, -5), (3, -2), (-4, 4), (5, -5), (-5, 5), (1, 1)):
        out.append((f'stills COLOR1 tone block (2,-3,5,4,-6) B={B:+d} W={W:+d}',
                    dict(table=table_with(t0, {0: (B, W)}), profile=1, tone=(2, -3, 5, 4, -6)), B, W))
        out.append((f'stills COLOR4 art LUT 0x604fb482 str -3 B={B:+d} W={W:+d}',
                    dict(table=table_with(t0, {3: (B, W)}), profile=4, art=(0x604fb482, -3)), B, W))
    return out


def lv_cases(t0):
    tb = table_with(t0, {0: (3, -2), 1: (-4, 5), 2: (5, 0), 3: (0, -5)})
    out = []
    for p, (B, W) in zip((1, 2, 3, 4), ((3, -2), (-4, 5), (5, 0), (0, -5))):
        for c in (-2, 0, 2):
            out.append((f'LV==stills COLOR{p} c{c:+d}', dict(table=tb, profile=p, contrast=c), B, W))
        out.append((f'LV==stills COLOR{p} tone block', dict(table=tb, profile=p, tone=(0, 0, -7, 7, 3)), B, W))
    out.append(('LV==stills COLOR1 cpu 1 (translator)', dict(table=tb, profile=1, cpu=1), 3, -2))
    return out


IMGS = {}


def _init(img, base_img):
    IMGS.update(img=img, base=base_img)


def _work(item):
    kind, name, kw, B, W, loaded = item
    img, base_img = IMGS['img'], IMGS['base']
    SDV3.set_loaded(loaded) if loaded else None
    try:
        if kind == 'N':
            m, b = run(img, **kw), run(base_img, **kw)
            c = identical(m, b)
            return dict(test=f'N {name} == v0.18', passed=all(c.values()), **c, fault=m['fault'])
        if kind == 'A':
            m, b = run(img, **kw), run(base_img, **kw)
            c, got = active_check(m, b, B, W)
            return dict(test=f'A {name}', passed=all(c.values()), **c, y=[got[i] for i in SAMPLE],
                        insns=m['insns'], fault=m['fault'])
        if kind == 'L':
            kw_l = dict(kw, live=True)
            st, lv = run(img, **kw), run(img, **kw_l)
            bs, bl = run(base_img, **kw), run(base_img, **kw_l)
            c1, g1 = active_check(st, bs, B, W)
            c2, g2 = active_check(lv, bl, B, W)
            c = dict(stills=all(c1.values()), lv=all(c2.values()), same_lut=g1 == g2,
                     same_out=st['mem']['out'] == lv['mem']['out'], same_ctx=st['mem']['ctx'] == lv['mem']['ctx'],
                     same_regs=st['regs'] == lv['regs'])
            return dict(test=f'L {name}', passed=all(c.values()), **c)
    finally:
        SDV3.set_loaded(False) if loaded else None


# ------------------------------------------------------------------ static
def objdump(code, at):
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / 'c.bin'
        p.write_bytes(code)
        out = subprocess.run([VB.BB.TC / 'mn10300-elf-objdump', '-b', 'binary', '-m', 'am33-2', '-D',
                              f'--adjust-vma={at:#x}', p], check=True, capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if ':\t' in l]


def store_audit(code, at):
    """Every store: destination must be our frame (n,sp), output fields (n,a3) / (d1,a0) / (a0)."""
    stores, bad = [], []
    for l in objdump(code, at):
        f = l.split('\t')
        if len(f) < 4:
            continue
        op, args = f[2].strip(), f[3].strip()
        if op not in ('mov', 'movbu', 'movhu'):
            continue
        src, _, dst = args.partition(',')
        if src.startswith('(') or not dst.strip().startswith('(') or dst.strip() == 'mdr':
            continue
        if src.strip() == 'mdr':
            continue
        stores.append(f'{f[0].strip()} {op} {args}')
        if not (dst.endswith(',sp)') or dst in ('(sp)', '(2608,a3)', '(4,a3)', '(d1,a0)', '(a0)')):
            bad.append(stores[-1])
    return stores, bad


def check_static(stock, img, base_img, spec, base_spec):
    t = spec['tone_ends']
    ca, cb = int(t['code_at'], 16), int(t['code_b'], 16)
    la, lb = t['code_len'], t['code_b_len']
    hook = sl(img, HOOK, HOOK + 7)
    want = b'\xdd' + struct.pack('<i', ca - HOOK) + b'\xf0\x48'
    s = dict(hook=hook == want, stock_hook=sl(stock, HOOK, HOOK + 7) == bytes.fromhex('f1eccd65f7f048'),
             base_hook_stock=sl(base_img, HOOK, HOOK + 7) == sl(stock, HOOK, HOOK + 7),
             ref_words=(struct.unpack_from('<I', img, int(t['ref_word'], 16) - BASE)[0] == ca and
                        struct.unpack_from('<I', img, int(t['ref_word_b'], 16) - BASE)[0] == cb),
             tails_stock=(sl(img, ca + la, int(t['code_end'], 16)) == sl(stock, ca + la, int(t['code_end'], 16)) and
                          sl(img, cb + lb, int(t['code_b_end'], 16)) == sl(stock, cb + lb, int(t['code_b_end'], 16))))
    hits = VB.branch_refs(stock, set(range(HOOK + 1, HOOK + 7)))
    # A brute-force hit whose source byte lies inside the stage list but is not an instruction start (linear
    # disassembly of 0x603b1466..0x603b1517) is operand bytes, not a branch (e.g. 0x603b1511 inside the call at
    # 0x603b150f).
    starts = {int(l.split(':')[0], 16) for l in objdump(sl(stock, 0x603b1466, 0x603b1517), 0x603b1466)}
    real = [h for h in hits if not (0x603b1466 <= int(h[1], 16) < 0x603b1517 and int(h[1], 16) not in starts)]
    s['no_refs_into_hook_interior'] = not real and 0x603b150f in starts
    allowed = {t['ref_word'], t['ref_word_b']}
    others = []
    for lo, hi in ((ca, int(t['code_end'], 16)), (cb, int(t['code_b_end'], 16))):
        into = VB.branch_refs(stock, set(range(lo, hi)))
        others += [h for h in into if not (h[0] == 'abs32' and h[1] in allowed)
                   and not (0x601de13c <= int(h[1], 16) < 0x601e3b3c)]
    # Brute-force hits outside the LUT block are listed; the build pins and dis-checks the known instruction-byte
    # false positives (patches/tone_ends/build.py FALSE_POS).
    fp = {'0x606209a4', '0x6064475d'}
    s['only_step_words_reference_placements'] = all(h[1] in fp for h in others)
    st_a, bad_a = store_audit(sl(img, ca, ca + la), ca)
    st_b, bad_b = store_audit(sl(img, cb, cb + lb), cb)
    s['store_audit'] = not bad_a and not bad_b and len(st_a) + len(st_b) > 0
    in_spans, nchg = VB.spans_check(spec, stock, img)
    s['changed_bytes_in_spans'] = in_spans
    import numpy as np
    diff = np.nonzero(np.frombuffer(img, np.uint8) != np.frombuffer(base_img, np.uint8))[0] + BASE
    tone_spans = [(int(e['addr'], 16), int(e['addr'], 16) + len(e['new']) // 2) for e in spec['edits']
                  if e.get('source') == 'patches/tone_ends']
    s['merged_vs_v018_only_tone_edits'] = len(tone_spans) == 3 and all(any(a <= x < b for a, b in tone_spans) for x in diff)
    s['other_edits_equal_base'] = [e for e in spec['edits'] if e.get('source') != 'patches/tone_ends'] == base_spec['edits']
    return [dict(test='S static', passed=all(s.values()), **s, interior_hits=hits, placement_refs=others,
                 stores=st_a + st_b, bad_stores=bad_a + bad_b, changed=nchg, diff_vs_v018=len(diff))]


def payload(spec):
    pkg, restore, info = BP.build(spec, BP.STOCK.read_bytes())
    return pkg, restore, info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('merged', type=Path, nargs='?', default=ROOT / 'generated/tone_ends/merged.json')
    ap.add_argument('--json', type=Path)
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--full', action='store_true', help='all 121 B/W combos also at contrast -2/+2')
    a = ap.parse_args()
    spec = json.loads(a.merged.read_text())
    if 'tone_ends' not in spec:
        sys.exit('spec lacks tone_ends metadata (use generated/tone_ends/merged.json)')
    base_spec = dict(spec, edits=[e for e in spec['edits'] if e.get('source') != 'patches/tone_ends'])
    rel = json.loads((ROOT / 'releases/v0.18/edits.json').read_text())
    pkg, restore, info = payload(spec)
    bpkg, brestore, _ = payload(base_spec)
    img, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    base_img = oc.parse(bpkg)[0].payload
    results = []
    pk = dict(restore_main_is_stock=hashlib.sha256(stock).hexdigest() == MAIN_SHA,
              restores_equal=restore == brestore,
              base_is_v018=base_spec['edits'] == rel['edits'],
              v018_package_reproduced=hashlib.sha256(bpkg).hexdigest() ==
              hashlib.sha256((ROOT / 'releases/v0.18/patched.pkg.bin').read_bytes()).hexdigest(),
              package_reparses=[b.kind for b in oc.parse(pkg)] == [int(k, 16) for k in spec['components']],
              changed_bytes=info['changed_payload_bytes'])
    pk_ok = all(v for k, v in pk.items() if k != 'changed_bytes')
    results.append(dict(test='P package: builds, decodes to the emulated image, restore == stock, base == v0.18',
                        passed=pk_ok, **pk))
    results += check_static(stock, img, base_img, spec, base_spec)
    t0 = bytes.fromhex(rel['table_hex'])
    items = [('N', n, kw, 0, 0, False) for n, kw in n_cases(t0)]
    items += [('A', n, kw, B, W, False) for n, kw, B, W in a_cases(t0, a.full)]
    items += [('L', n, kw, B, W, False) for n, kw, B, W in lv_cases(t0)]
    items += [('A', 'SD-loaded ' + n, kw, B, W, True) for n, kw, B, W in lv_cases(t0)[:4]]
    items += [('N', 'SD-loaded ' + n, kw, 0, 0, True) for n, kw in n_cases(t0)[:3] + n_cases(t0)[5:6]]
    if a.jobs > 1:
        with ProcessPoolExecutor(a.jobs, initializer=_init, initargs=(img, base_img)) as ex:
            results += list(ex.map(_work, items, chunksize=4))
    else:
        _init(img, base_img)
        results += [_work(i) for i in items]
    ok = all(x['passed'] for x in results)
    for x in results:
        if x['test'].startswith('A ') and x['passed'] and not any(k in x['test'] for k in ('B=+5 W=-5', 'B=-5 W=+5')):
            continue
        print(f"{'PASS' if x['passed'] else 'FAIL'}  {x['test']}" +
              ('' if x['passed'] else '  ' + json.dumps({k: v for k, v in x.items() if k not in ('test', 'passed')},
                                                         default=str)[:900]))
    groups = {}
    for x in results:
        g = x['test'][0]
        groups.setdefault(g, [0, 0])
        groups[g][0] += x['passed']
        groups[g][1] += 1
    print('  '.join(f'{g}: {p}/{n}' for g, (p, n) in groups.items()))
    print(f"{sum(x['passed'] for x in results)}/{len(results)} checks pass; {'PASS' if ok else 'FAIL'} overall; package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.merged), package=info, passed=ok, results=results,
                                          scope='emulator only; synthetic fixtures; CPU code, not ISP/pixels; '
                                                'no camera contacted'), indent=1, default=str))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
