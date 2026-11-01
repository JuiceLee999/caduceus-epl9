#!/usr/bin/env python3
"""Build the E-P7 1.1 v0.2 "profile bundle" edit spec (offline; never contacts a camera).

  .venv/bin/python -I patches/bundles/build.py bundles/example.json --out generated/bundles-example

Reads bundles/<name>.json (slot keys COLOR1-4, MONO1-4; each slot names a recipe from
sim/recipes/fuji_like.json or film_look.json and may override wb / grain / effect / vignette),
builds the 8 x 64-byte bundle table, assembles patches/bundles/bundles.s.in at the section-1
FF tail and emits <out>/edits.json for tools/build_package.py with exact stock-byte
expectations. Also writes routine.s / routine.lst / routine.bin / symbols.json.

v0.2 consumes hue/light of COLOR1-4. The WB fields (wb_flags bit0, wb_ab, wb_gm) of all 8 slots are
read by the per-profile WB patch (patches/wb, merged separately). A slot's "wb": {"a_b": n, "g_m": n}
sets the override (else the recipe's wb_shift; "wb": null disables an inherited one).
A MONO slot with "render_colour": true also gets colour = 1 (+32), sat[12] (+33; slot "sat" or the
recipe's, stock range -5..5) and flags bit1 (H/L); patches/mono_colour reads them.
grain (+24, slot "grain": low|medium|high; recipe grain is NOT inherited) is read by patches/grain v0.4 and
effect_id/effect_strength (+28/+29, slot "effect": {"type": "bloom", "strength": 1-5}) by patches/bloom v0.4;
both are off unless the slot sets them. Vignette and halation are stored only. Saturation is NOT part of the patch: the
user's per-profile saturation setting still applies (the recipe value is reported as advice).

Edits (all in main, component 0x100):
  0x603537f0  mov 15488,d0 -> mov 15512,d0      job allocation (+24-byte extension)
  0x6035390c  mov 16,d1    -> mov 40,d1         tail memset covers job+15472..15511
  0x603b02d9  call builder -> jmp hl            COLOR builder hook (replaces v0.1)
  0x603e66ab  movbu/cmp/bne -> jmp conv1; nop   converter 0x603e62d1 transport
  0x603e91f0  mov/movbu/cmp -> jmp conv2; nop   converter 0x603e8af1 transport
  0x60210900  FF tail -> code + tables
"""
import argparse, json, struct, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
MAIN = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
MAIN_SHA = '5dd9af164b4590c7e82f6905c919b3cc450bb58f2d5742ab2a0e3a4eb2e26190'
BASE = 0x60020020
RECIPE_FILES = [ROOT / 'sim/recipes/fuji_like.json', ROOT / 'sim/recipes/film_look.json',
                ROOT / 'sim/recipes/library_v1.json', ROOT / 'sim/recipes/library_v2.json',
                ROOT / 'sim/recipes/library_v3.json']

# --- verified sites (stock bytes checked below against the decoded main)
ALLOC, ALLOC_STOCK, JOB_SIZE, EXT = 0x603537f0, bytes.fromhex('2c803c'), 15488, 24
MEMSET, MEMSET_STOCK = 0x6035390c, bytes.fromhex('8510')      # mov 16,d1 (memset job+15472)
HOOK, HOOK_STOCK, RESUME, BUILDER = 0x603b02d9, bytes.fromhex('cd8ffdf060'), 0x603b02de, 0x603b0068
CONV1, CONV1_STOCK = 0x603e66ab, bytes.fromhex('f043a00cc926')  # movbu (a3),d0; cmp 12,d0; bne 0x603e66d5
CONV1_MONO, CONV1_NEXT = 0x603e66b1, 0x603e66d5
CONV2, CONV2_STOCK = 0x603e91f0, bytes.fromhex('5c24f040a00c')  # mov (36,sp),a0; movbu (a0),d0; cmp 12,d0
CONV2_RESUME = 0x603e91f6                                      # bne 0x603e921c
CODE_AT = 0x60210900                       # section-1 FF tail 0x602108ec..0x60211000 (16-byte guard)
BUNDLE_TABLE = CODE_AT                     # fixed: 8 x 64-byte table is the first thing in the placement
                                           # (exported in patches/bundles/layout.json for other patches)
SEC1_START, SEC1_END = 0x600d7800, 0x60211000
SECTION_TABLE, END_GETTER_SEC1 = 0x60027068, 0x6004579c   # descriptor table; `mov 0x60211000,d0` in end getter
CALLBACK, REQ_IN_JOB, RECORDS_IN_JOB, REC_STRIDE, N_REC = 0x60355fd4, 11364, 14576, 56, 16
OUT_RECORDS = 688
CAP_PROFILE, CAP_MODE = 24083, 24053
EXT_PROFILE, EXT_MODE, EXT_MAGIC, MAGIC = JOB_SIZE, JOB_SIZE + 1, JOB_SIZE + 2, 0xB2
HUE_LUT = [-1000 * u for u in range(-7, 8)]
L_LUT = [-300, -250, -200, -150, -100, -50, -25, 0, 25, 50, 100, 150, 200, 250, 300]
PERM = [2 * (r % 6) + r // 6 for r in range(12)]
SLOTS = ['COLOR1', 'COLOR2', 'COLOR3', 'COLOR4', 'MONO1', 'MONO2', 'MONO3', 'MONO4']
GRAIN = {'off': 0, 'low': 1, 'medium': 2, 'med': 2, 'high': 3}
EFFECT = {'none': 0, 'bloom': 1, 'halation': 2, 'clarity': 3}   # clarity: patches/bloom --clarity
TINT = {'neutral': 0, 'red': 1, 'amber': 2, 'warm': 3, 'cool': 4}   # bloom_tint +45 (layout.json; test13b)
TINT_OFF = 45
ART = {'off': 0, 'star_light': 1, 'pin_hole': 2, 'blur': 3, 'white_edge': 4, 'frame': 5}   # art_effect +46 (v0.14); v0.15 camera treats 4/5 as Off (accepted, legacy)
ART_OFF = 46
FLAG_RENDER_COLOUR, FLAG_HL = 1, 2
COLOUR_OFF, SAT_OFF = 32, 33               # MONO colour rendering (patches/mono_colour): u8 == 1, s8 x12
WB_OVERRIDE = 1                            # wb_flags bit0 (layout.json); bit7 must stay 0
ENTRY = 64
# Grain (0x6055e680..0x6055e6fa, hooks 0x6035749f+7, 0x603b5249+7) and rec_limit
# (0x60319157+2, 0x6031915c+2) reservations: never overlap them.
RESERVED = [(0x6055e680, 0x6055e6fa), (0x6035749f, 0x603574a6), (0x603b5249, 0x603b5250),
            (0x60319157, 0x60319159), (0x6031915c, 0x6031915e),
            (0x60210ce0, 0x60210e00), (0x60210e10, 0x60210ef0),   # v0.4 grain / bloom code (sec 1)
            (0x603eabd7, 0x603eabdd), (0x6039fee8, 0x6039feee)]   # v0.4 bloom hooks
# Per-profile WB (patches/wb): stub reservation + the rel32 of each redirected getter call.
WB_STUB = (0x6055e700, 0x6055e7a6)


def wb_reserved():
    import importlib.util
    spec = importlib.util.spec_from_file_location('ep7_wb_build', ROOT / 'patches/wb/build.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if (m.CODE_AT, m.CODE_END) != WB_STUB:
        raise ValueError('WB reservation disagrees with patches/wb/build.py')
    return [WB_STUB] + [(s + 1, s + 5) for s, *_ in m.SITES]


def ival(v, lo, hi, what):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ValueError(f'{what}: {v!r} must be an integer in {lo}..{hi}')
    return v


def load_recipes():
    out = {}
    for f in RECIPE_FILES:
        for k, v in json.loads(f.read_text())['recipes'].items():
            if k in out:
                raise ValueError(f'recipe {k} defined twice')
            out[k] = dict(v, _file=f.name)
    return out


def slot_entry(name, slot, recipes):
    """-> (64-byte entry, metadata dict). Missing slot -> all zero (H/L disabled -> stock)."""
    e = bytearray(ENTRY)
    if slot is None:
        return bytes(e), dict(slot=name, enabled=False)
    unknown = set(slot) - {'recipe', 'wb', 'grain', 'effect', 'vignette', 'render_colour', 'sat'}
    if unknown:
        raise ValueError(f'{name}: unknown keys {sorted(unknown)}')
    rname = slot.get('recipe')
    if rname not in recipes:
        raise ValueError(f'{name}: unknown recipe {rname!r}')
    rc = recipes[rname]
    hue, light = rc.get('hue', [0] * 12), rc.get('light', [0] * 12)
    if len(hue) != 12 or len(light) != 12:
        raise ValueError(f'{name}: hue/light need 12 values')
    hue = [ival(v, -7, 7, f'{name} hue') for v in hue]
    light = [ival(v, -7, 7, f'{name} light') for v in light]
    e[0:12] = struct.pack('<12b', *hue)
    e[12:24] = struct.pack('<12b', *light)
    # Grain (consumed by patches/grain v0.4): per slot and OFF by default. Only the slot's own
    # "grain": "low|medium|high" enables it; a recipe's grain is NOT inherited (reported as advice),
    # so no profile gets the extra grain pass unless the bundle asks for it (review v0.3 H2).
    grain = slot.get('grain', 'off')
    if not isinstance(grain, str) or grain not in GRAIN:
        raise ValueError(f'{name}: grain {grain!r} (use one of {sorted(GRAIN)})')
    e[24] = GRAIN[grain]
    # WB fine-tune override (consumed by patches/wb): slot "wb" wins over the recipe's wb_shift;
    # "wb": null explicitly disables an inherited recipe wb_shift. Present -> wb_flags bit0 + values.
    wb_src = 'slot' if 'wb' in slot else ('recipe' if rc.get('wb_shift') is not None else None)
    wb = slot['wb'] if 'wb' in slot else rc.get('wb_shift')
    if wb is not None:
        if not isinstance(wb, dict) or not wb or set(wb) - {'a_b', 'g_m'}:
            raise ValueError(f'{name}: wb ({wb_src}) must be {{"a_b": n, "g_m": n}} (-7..7), got {wb!r}')
        e[25] = WB_OVERRIDE
        e[26:28] = struct.pack('<2b', ival(wb.get('a_b', 0), -7, 7, f'{name} wb a_b'),
                               ival(wb.get('g_m', 0), -7, 7, f'{name} wb g_m'))
    else:
        wb_src = None
    # Effect (bloom consumed by patches/bloom v0.4; halation stored only): {"type": "bloom", "strength": 1-5}.
    eff = slot.get('effect')
    if eff is not None:
        if not isinstance(eff, dict) or set(eff) - {'type', 'strength', 'tint'} or eff.get('type') not in EFFECT:
            raise ValueError(f'{name}: effect must be {{"type": "bloom|clarity|halation|none", "strength": 1-5'
                             f'[, "tint": "neutral|red|amber|warm|cool"]}}, got {eff!r}')
        if 'tint' in eff:
            if eff['type'] not in ('bloom', 'halation') or eff['tint'] not in TINT:
                raise ValueError(f'{name}: "tint" ({sorted(TINT)}) only with bloom/halation, got {eff!r}')
            e[TINT_OFF] = TINT[eff['tint']]
        e[28] = EFFECT[eff['type']]
        if e[28]:
            if 'strength' not in eff:
                raise ValueError(f'{name}: effect {eff["type"]} needs "strength": 1-5')
            e[29] = ival(eff['strength'], 1, 5, f'{name} effect strength')
        elif eff.get('strength', 0) != 0:
            raise ValueError(f'{name}: effect none takes no strength')
    art = slot.get('art_effect', 'off')
    if not isinstance(art, str) or art not in ART:
        raise ValueError(f'{name}: art_effect {art!r} (use one of {sorted(ART)})')
    if art != 'off' and not name.startswith('COLOR'):
        raise ValueError(f'{name}: art_effect is a COLOR-slot field')
    e[ART_OFF] = ART[art]
    e[30] = struct.pack('<b', ival(slot.get('vignette', rc.get('vignette') or 0), -5, 5, f'{name} vignette'))[0]
    flags = FLAG_HL if name.startswith('COLOR') else 0      # v0.2 consumes COLOR H/L
    sat = None
    if 'render_colour' in slot and not isinstance(slot['render_colour'], bool):
        raise ValueError(f'{name}: render_colour must be true/false')
    if 'sat' in slot and not slot.get('render_colour'):
        raise ValueError(f'{name}: "sat" is only used by a MONO slot with render_colour')
    if slot.get('render_colour'):
        if not name.startswith('MONO'):
            raise ValueError(f'{name}: render_colour is a MONO-slot flag')
        # patches/mono_colour: colour byte (+32) == 1, sat[12] (+33, request+1816 order, -5..5) and the
        # slot's H/L (flags bit1) replace MONO's grey rendering. Saturation comes from the slot ("sat")
        # or the recipe; a value outside the stock -5..5 is an error (no silent clamping).
        sat = slot.get('sat', rc.get('sat', [0] * 12))
        if not isinstance(sat, list) or len(sat) != 12:
            raise ValueError(f'{name}: sat needs 12 values')
        sat = [ival(v, -5, 5, f'{name} sat (stock range; give an explicit "sat")') for v in sat]
        flags |= FLAG_RENDER_COLOUR | FLAG_HL
        e[COLOUR_OFF] = 1
        e[SAT_OFF:SAT_OFF + 12] = struct.pack('<12b', *sat)
    e[31] = flags
    return bytes(e), dict(slot=name, enabled=bool(flags & FLAG_HL), recipe=rname, recipe_file=rc['_file'],
                          hue_ui=hue, light_ui=light, grain=e[24], wb_override=bool(e[25]), wb_source=wb_src,
                          wb=list(struct.unpack('<2b', e[26:28])), effect=[e[28], e[29]], bloom_tint=e[TINT_OFF], art_effect=e[ART_OFF],
                          vignette=struct.unpack('<b', e[30:31])[0], flags=flags,
                          advice_sat_ui=rc.get('sat'), advice_grain=rc.get('grain'), colour=e[COLOUR_OFF], sat_ui=sat,
                          native_rows=native_rows(hue, light))


def native_rows(hue, light):
    return [(HUE_LUT[hue[w] + 7], L_LUT[light[w] + 7]) for w in PERM]


def build_table(bundle, recipes):
    unknown = set(bundle) - set(SLOTS) - {'_comment', 'name'}
    if unknown:
        raise ValueError(f'unknown slot keys {sorted(unknown)} (use {SLOTS})')
    table, meta = bytearray(), []
    for name in SLOTS:
        e, m = slot_entry(name, bundle.get(name), recipes)
        table += e
        meta.append(m)
    assert len(table) == 8 * ENTRY
    return bytes(table), meta


def fmt_words(vals):
    return '\n'.join(' .hword ' + ','.join(str(v) for v in vals[i:i + 8]) for i in range(0, len(vals), 8))


def fmt_bytes(b):
    return '\n'.join(' .byte ' + ','.join(f'0x{x:02x}' for x in b[i:i + 16]) for i in range(0, len(b), 16))


TBL_HL_FLASH = """ asl 6,d0                            /* slot * 64 */
 mov bundle_table,a0
 add d0,a0                           /* a0 = slot entry */"""
# --sd-v3 (docs/SD_BUNDLES_V3.md): same 11 bytes, so every label / branch / verifier pattern is unchanged.
# The call writes its return address to (0,sp) = the saved d0: d0 is dead at the resume point
# (0x603b02de mov (60,a2),d0, checked in make_spec). MDR is kept because the stock path from the resume
# point to the selector's ret may make no call (0x603b02ed).
TBL_HL_SDV3 = """ mov mdr,d1                          /* sd v3: keep MDR (d1 is reloaded below / restored at out) */
 call ep7_tbl_idx,[d2,d3],8          /* a0 = slot d0 of the active table (SD-loaded or flashed) */
 mov d1,mdr"""


def source(table, sd_v3=False):
    sub = dict(tbl_hl=TBL_HL_SDV3 if sd_v3 else TBL_HL_FLASH, cap_profile=CAP_PROFILE, ext_profile_p=EXT_PROFILE - 36, ext_mode_p=EXT_MODE - 36,
               ext_magic_p=EXT_MAGIC - 36, ext_profile=EXT_PROFILE, ext_mode=EXT_MODE, ext_magic=EXT_MAGIC,
               magic=hex(MAGIC), callback=hex(CALLBACK), rec_off=RECORDS_IN_JOB - REQ_IN_JOB, n_rec=N_REC,
               stride=REC_STRIDE, req_in_job=REQ_IN_JOB, hue_off=OUT_RECORDS + 18,
               hue_lut=fmt_words(HUE_LUT), light_lut=fmt_words(L_LUT), perm=fmt_bytes(bytes(PERM)),
               table=fmt_bytes(table))
    src = (Path(__file__).parent / 'bundles.s.in').read_text()
    for k, v in sub.items():
        src = src.replace('{' + k + '}', str(v))
    if '{' in src or '}' in src:
        raise ValueError('unsubstituted template field')
    return src


def assemble(src, extra=None):
    syms = dict(ep7_builder=BUILDER, ep7_resume=RESUME, ep7_conv1_mono=CONV1_MONO,
                ep7_conv1_next=CONV1_NEXT, ep7_conv2_resume=CONV2_RESUME, **(extra or {}))
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'p.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-a=' + str(t / 'p.lst'), '-o', t / 'p.o', t / 'p.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(CODE_AT), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in syms.items()],
                        '-o', t / 'p.elf', t / 'p.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'p.elf', t / 'p.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'p.elf'], check=True, capture_output=True, text=True).stdout
        labels = {}
        for line in nm.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] in 'tT':
                labels[parts[2]] = int(parts[0], 16)
        return (t / 'p.bin').read_bytes(), (t / 'p.lst').read_text(), labels


def jmp_d32(at, target, length):
    b = b'\xdc' + struct.pack('<i', target - at)
    return b + b'\xcb' * (length - len(b))          # pad with nop (never executed)


def check_section1(d, code_len):
    """Section 1 loads in place and its load end covers the placement; placement is erased FF."""
    s, src, dst = struct.unpack_from('<3I', d, SECTION_TABLE - BASE)
    if (s, dst) != (SEC1_START, SEC1_START) or src != SEC1_START - 0x60020020 + 0x406a0020:
        raise ValueError('section-1 descriptor differs')
    if d[END_GETTER_SEC1 - BASE:END_GETTER_SEC1 - BASE + 2] != b'\xfc\xcc' or \
            struct.unpack_from('<I', d, END_GETTER_SEC1 + 2 - BASE)[0] != SEC1_END or \
            struct.unpack_from('<I', d, 0x60046780 - BASE)[0] != END_GETTER_SEC1:   # end-getter jump table, id 1
        raise ValueError('section-1 end constant differs')
    lo, hi = CODE_AT - 16, CODE_AT + code_len + 16          # 16-byte guard each side
    if hi > SEC1_END:
        raise ValueError('code does not fit the section-1 tail (with guard)')
    if set(d[lo - BASE:hi - BASE]) != {0xff}:
        raise ValueError('section-1 placement (+guard) not erased')
    return d[CODE_AT - BASE:CODE_AT - BASE + code_len]


def sdv3_accessor():
    import importlib.util
    spec = importlib.util.spec_from_file_location('ep7_sd_bundles_v3_build', ROOT / 'patches/sd_bundles_v3/build.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.accessor_symbols()


def make_spec(bundle_path, sd_v3=False):
    import hashlib
    d = MAIN.read_bytes()
    if hashlib.sha256(d).hexdigest() != MAIN_SHA:
        raise ValueError('decoded main hash mismatch')
    bundle = json.loads(Path(bundle_path).read_text())
    table, meta = build_table(bundle, load_recipes())
    src = source(table, sd_v3)
    acc = sdv3_accessor() if sd_v3 else {}
    code, lst, labels = assemble(src, {'ep7_tbl_idx': acc['tbl_idx']} if sd_v3 else None)
    if sd_v3:
        c0, _, l0 = assemble(source(table))
        if len(c0) != len(code) or l0 != labels:
            raise ValueError('--sd-v3 must not change the routine size or any label')
        if d[RESUME - BASE:RESUME - BASE + 3] != bytes.fromhex('f8023c'):
            raise ValueError('resume point no longer reloads d0 (the --sd-v3 call clobbers the saved d0)')
    if labels['bundle_table'] != BUNDLE_TABLE or labels['bundle_table_end'] - labels['bundle_table'] != len(table) \
            or labels['bundle_table'] % 4:
        raise ValueError('table placement/alignment wrong')
    if code[labels['bundle_table'] - CODE_AT:labels['bundle_table_end'] - CODE_AT] != table:
        raise ValueError('table bytes not found at bundle_table')
    lay = json.loads((Path(__file__).parent / 'layout.json').read_text())
    if [lay['fields'][k][0] for k in ('wb_flags', 'wb_ab', 'wb_gm', 'colour', 'sat')] != \
            [25, 26, 27, COLOUR_OFF, SAT_OFF]:
        raise ValueError('layout.json wb/colour/sat field offsets disagree with slot_entry()')
    if (int(lay['bundle_table'], 16), lay['slot_bytes'], lay['slots'], lay['job_extension']['job_size'],
            lay['job_extension']['marker'], int(lay['job_extension']['marker_value'], 16)) != \
            (BUNDLE_TABLE, ENTRY, SLOTS, JOB_SIZE + EXT, EXT_MAGIC, MAGIC):
        raise ValueError('layout.json disagrees with build.py constants')
    tail = check_section1(d, len(code))
    for at, stock in ((ALLOC, ALLOC_STOCK), (MEMSET, MEMSET_STOCK), (HOOK, HOOK_STOCK),
                      (CONV1, CONV1_STOCK), (CONV2, CONV2_STOCK)):
        if d[at - BASE:at - BASE + len(stock)] != stock:
            raise ValueError(f'stock bytes differ at {at:#x}')
    new_size = JOB_SIZE + EXT
    if new_size > 16384:
        raise ValueError('job would leave heap class 2 (<=16384)')
    edits = [
        dict(kind='0x100', addr=hex(ALLOC), expect=ALLOC_STOCK.hex(), new=(b'\x2c' + struct.pack('<H', new_size)).hex(),
             why=f'job allocation {JOB_SIZE} -> {new_size} (+{EXT}-byte bundle extension at job+{JOB_SIZE})'),
        dict(kind='0x100', addr=hex(MEMSET), expect=MEMSET_STOCK.hex(), new=bytes([0x85, 16 + EXT]).hex(),
             why=f'tail memset job+15472: 16 -> {16 + EXT} bytes (zeroes the extension)'),
        dict(kind='0x100', addr=hex(HOOK), expect=HOOK_STOCK.hex(), new=jmp_d32(HOOK, labels['hl'], 5).hex(),
             why='COLOR builder call -> jmp v0.2 bundle H/L routine (replaces v0.1)'),
        dict(kind='0x100', addr=hex(CONV1), expect=CONV1_STOCK.hex(), new=jmp_d32(CONV1, labels['conv1'], 6).hex(),
             why='converter 0x603e62d1: copy capture profile/mode into job extension'),
        dict(kind='0x100', addr=hex(CONV2), expect=CONV2_STOCK.hex(), new=jmp_d32(CONV2, labels['conv2'], 6).hex(),
             why='converter 0x603e8af1: copy capture profile/mode into job extension'),
        dict(kind='0x100', addr=hex(CODE_AT), expect=tail.hex(), new=code.hex(),
             why=f'v0.2 code + LUTs + 8x64 bundle table ({len(code)} B) in section-1 FF tail'),
    ]
    reserved = RESERVED + wb_reserved()
    for e in edits:
        a = int(e['addr'], 16)
        n = len(bytes.fromhex(e['new']))
        for lo, hi in reserved:
            if a < hi and lo < a + n:
                raise ValueError(f'edit {e["addr"]} overlaps reserved {lo:#x}..{hi:#x}')
    bp = Path(bundle_path).resolve()
    spec = dict(components=['0x100'], patch='bundles-v0.2-sdv3' if sd_v3 else 'bundles-v0.2',
                bundle=str(bp.relative_to(ROOT)) if bp.is_relative_to(ROOT) else str(bp),
                labels={k: hex(v) for k, v in labels.items()},
                layout=dict(job_size=new_size, ext_profile=EXT_PROFILE, ext_mode=EXT_MODE, ext_magic=EXT_MAGIC,
                            magic=MAGIC, entry_bytes=ENTRY, slots=SLOTS),
                slots=meta, table_hex=table.hex(), edits=edits)
    if sd_v3:
        spec['sd_v3'] = dict(accessor={k: hex(v) for k, v in acc.items()}, requires='sd_bundles_v3 (accessor edit)')
    return spec, src, lst, code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('bundle', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--sd-v3', action='store_true', help='read the table through the SD loader v3 accessor')
    a = ap.parse_args()
    try:
        spec, src, lst, code = make_spec(a.bundle, a.sd_v3)
    except ValueError as e:
        sys.exit(f'error: {e}')
    a.out.mkdir(parents=True, exist_ok=False)
    (a.out / 'edits.json').write_text(json.dumps(spec, indent=1) + '\n')
    (a.out / 'routine.s').write_text(src)
    (a.out / 'routine.lst').write_text(lst)
    (a.out / 'routine.bin').write_bytes(code)
    print(f'{len(code)} B at {CODE_AT:#x}; hl={spec["labels"]["hl"]} conv1={spec["labels"]["conv1"]} '
          f'conv2={spec["labels"]["conv2"]} table={spec["labels"]["bundle_table"]}; wrote {a.out}')
    for m in spec['slots']:
        print(f"  {m['slot']:6} {'H/L on ' if m['enabled'] else 'stock  '} {m.get('recipe', '-')}")


if __name__ == '__main__':
    main()
