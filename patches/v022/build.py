#!/usr/bin/env python3
"""v0.22 "natural grain" = releases/v0.21 (byte level) + COLOR grain through the stock Noise Filter. Offline.

  python3 -I patches/v022/build.py releases/v0.21/edits.json --out releases/v0.22/edits.json
  python3 -I patches/fw_version/build.py releases/v0.22/edits.json --mod-version 0.22

Camera tests v0.16..v0.22 probe: the ISP grain combiners add nothing visible to COLOR stills. So the slot grain byte
(+24) now drives the camera's own Noise Filter (setting 1334, values -2..1 = Off/Low/Standard/High, validator list
0x604cb4ed; one global setting, not per profile):
  byte 0     Global -> Noise Filter untouched (the camera's own setting)   "1 Noise Global"  (old cards' 0)
  byte 6     Off    -> Noise Filter Standard (0)                           "1 Noise Std"     (new byte; loaders 0..6)
  byte 1     Fine   -> Noise Filter Low (-1)                               "1 Noise Low"     (old low)
  byte 2..5  Film   -> Noise Filter Off (-2)                               "1 Noise Off"     (old medium/high/heavy/extreme)
The editor shows a value u = 0 Global, 1 Off, 2 Fine, 3 Film (clamped 0..3): ex_get maps byte -> u (ng_get, hook
0x601e32c8), ex_set maps u -> byte 0/6/1/2 (ng_set).
Applied (only then; a profile switch does not re-apply, the setting stays at the last value):
  - Extras sector-1 edit: ex_set's grain write (0x601e33d7) -> ng_set: store, then settings manager 0x60827440
    (1334, nf) with ex_set's own a0/a1, as ex_art does (lv_art_refresh), then s_dirty
  - Film pick: lt_post's `jmp fm_post` (0x601e2341) -> ng_pick: facade SetValue(1334, 0, nf), the lt_tone path
The combiner-32 COLOR grain is made inert: both GLEVEL bounds (0x60210d3c, 0x60210dd3) -> 0, so wl_hook / grain_mod
never attach or set grain (hooks stay; MONO and other keys were already stock there).
"""
import argparse, copy, json, struct, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STOCK = ROOT / 'analysis/ep7_1100/00_0100_406a0020.decoded.bin'
TC = Path.home() / 'ep7fw-toolchains/mn10300/bin'
BASE, SRC = 0x60020020, 'patches/v022'
NF_SID, NF_VALUES = 1334, {1: -1, 2: -2}
BYTES = [(0x605b7739, 0x05, 0x06, 'SD loader v3 range: grain 0..6'), (0x6143a7cd, 0x05, 0x06, 'LOOKS.BIN fm_check range: grain 0..6'),
         (0x60210d3c, 0x05, 0x00, 'COLOR combiner grain off: wl_hook GLEVEL bound 0'),
         (0x60210dd3, 0x05, 0x00, 'COLOR combiner grain off: grain_mod GLEVEL bound 0'),
         (0x601e33d2, 0x05, 0x03, 'Extras grain value clamp 0..3 (cmp)'),
         (0x601e33d6, 0x05, 0x03, 'Extras grain value clamp 0..3 (mov)')]
GET_SITE, GET_OLD, G_VAL = 0x601e32c8, bytes.fromhex('f84238a006'), 0x601e3322
SET_SITE, SET_OLD, S_DIRTY = 0x601e33d7, bytes.fromhex('f85638ca4e'), 0x601e3428
PICK_SITE, FM_POST = 0x601e2341, 0x601e37b4
TAB_AT, OFF_STR = 0x601e3840, 0x601e3634
CODE_AT, CODE_END = 0x601e3890, 0x601e393c   # to the end of the dead EVF step-0 R table
CODE2_AT, CODE2_END = 0x601e1b90, 0x601e1c30   # rest of the dead EVF step-10 R table after ex_rs (ref only 0x601e3d24 -> 0x601e1b3c)
SYMS = dict(ep7_manager=0x60827440, ep7_facade=0x607f9062, ep7_s_dirty=S_DIRTY, ep7_fm_post=FM_POST, ep7_g_val=G_VAL)

ASM1 = f"""
 .am33_2
 .text
 .global _start
_start:
ng_set:                          /* ex_set grain write: d1 = u 0..3, a2 = P + 64*slot, d0 = id, a0/a1 = ex_set args */
 add -24,sp
 mov d0,(4,sp)
 mov d1,(8,sp)
 mov a0,(12,sp)
 mov a1,(16,sp)
 mov mdr,d0
 mov d0,(20,sp)
 mov ng_u2b,a0
 add d1,a0
 movbu (a0),d0
 movbu d0,(56,a2)                /* byte for u: 0 Global, 6 Off, 1 Fine, 2 Film */
 cmp 0,d1
 beq 8f                          /* Global: Noise Filter untouched */
 mov ng_u2nf,a0
 add d1,a0
 movbu (a0),d1
 extb d1                         /* Off 0 (Standard), Fine -1 (Low), Film -2 (Off) */
 mov {NF_SID},d0
 mov (12,sp),a0
 mov (16,sp),a1
 call ep7_manager,[d2,d3,a2],16  /* stock settings manager (as ex_art) */
8:
 mov (20,sp),d0
 mov d0,mdr
 mov (4,sp),d0
 mov (8,sp),d1
 mov (12,sp),a0
 mov (16,sp),a1
 add 24,sp
 jmp ep7_s_dirty
ng_get:                          /* ex_get grain read: a2 = P + 64*slot, a1 = OUT pointer (g_val stores to it) -> d0 = u */
 movbu (56,a2),d0
 cmp 7,d0
 bcc 1f
 mov a1,d1                       /* keep the output pointer (v0.22 first build clobbered a1: reboot on Extras) */
 mov ng_b2u,a1
 movbu (d0,a1),d0
 mov d1,a1
 jmp ep7_g_val
1:
 clr d0
 jmp ep7_g_val

"""
ASM2 = f"""
 .am33_2
 .text
 .global _start
_start:
ng_pick:                         /* after lt_tone: a2 = P, d3 = slot k */
 cmp 4,d3
 bcc 9f
 mov d3,d0
 asl 6,d0
 add a2,d0
 mov d0,a0
 movbu (56,a0),d0                /* slot entry +24 = grain byte */
 cmp 7,d0
 bcc 9f
 mov ng_b2u,a0
 add d0,a0
 movbu (a0),d0                   /* u */
 cmp 0,d0
 beq 9f                          /* Global: untouched */
 mov ng_u2nf,a0
 add d0,a0
 movbu (a0),d1
 extb d1
 call ng_put,[d2,d3,a2,a3],32   /* 16 B regs + 16 B locals: calls writes its return word at (sp), as lt_tone */
9:
 jmp ep7_fm_post

ng_u2b:
 .byte 0,6,1,2
ng_b2u:
 .byte 0,2,3,3,3,3,1
ng_u2nf:
 .byte 0,0,0xff,0xfe
ng_put:                          /* d1 = Noise Filter value: facade SetValue(1334, 0, v) (lt_tone's call) */
 mov d1,d2
 call ep7_facade,[],4
 mov (a0),a2
 mov (a2),a2
 mov d2,a1
 clr d1
 mov {NF_SID},d0
 calls (a2)
 ret [d2,d3,a2,a3],32
"""


def assemble_one(src, at, syms):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'a.s').write_text(src)
        subprocess.run([TC / 'mn10300-elf-as', '-o', t / 'a.o', t / 'a.s'], check=True)
        subprocess.run([TC / 'mn10300-elf-ld', '-Ttext', hex(at), '-e', '_start',
                        *[f'--defsym={k}={v:#x}' for k, v in syms.items()], '-o', t / 'a.elf', t / 'a.o'], check=True)
        subprocess.run([TC / 'mn10300-elf-objcopy', '-O', 'binary', '-j', '.text', t / 'a.elf', t / 'a.bin'], check=True)
        nm = subprocess.run([TC / 'mn10300-elf-nm', t / 'a.elf'], check=True, capture_output=True, text=True).stdout
        return (t / 'a.bin').read_bytes(), {n: int(a, 16) for a, _, n in (l.split() for l in nm.splitlines() if len(l.split()) == 3)}


def assemble():
    c2, s2 = assemble_one(ASM2, CODE2_AT, SYMS)
    c1, s1 = assemble_one(ASM1, CODE_AT, dict(SYMS, ng_u2b=s2['ng_u2b'], ng_u2nf=s2['ng_u2nf'], ng_b2u=s2['ng_b2u']))
    return (c1, c2), {**s2, **{k: v for k, v in s1.items() if k.startswith('ng_') and k not in s2}}


def covering(spec, addr, n=1):
    for e in spec['edits']:
        if e['kind'] == '0x100' and not e['addr'].startswith('off:'):
            a = int(e['addr'], 16)
            if a <= addr and addr + n <= a + len(e['new']) // 2:
                return e, addr - a
    raise SystemExit(f'{addr:#x}: no covering edit')


def put(spec, addr, old, new, what):
    e, o = covering(spec, addr, len(old))
    b = bytearray.fromhex(e['new'])
    if bytes(b[o:o + len(old)]) != old:
        raise SystemExit(f'{addr:#x}: {b[o:o + len(old)].hex()} != {old.hex()} ({what})')
    b[o:o + len(new)] = new
    e['new'] = b.hex(); e['why'] += f' [v0.22: {what}]'


def jmp(at, dst):
    return b'\xdc' + struct.pack('<i', dst - at)


def apply(spec):
    stock = STOCK.read_bytes()
    spec = copy.deepcopy(spec)
    (code, code2), syms = assemble()
    if CODE_AT + len(code) > CODE_END or CODE2_AT + len(code2) > CODE2_END:
        raise SystemExit(f'code too big ({len(code)}, {len(code2)})')
    for e in spec['edits']:
        if not e['addr'].startswith('off:'):
            a, n = int(e['addr'], 16), len(e['new']) // 2
            if (a < CODE_END and CODE_AT - 6 < a + n) or (a < CODE2_END and CODE2_AT - 8 < a + n):
                raise SystemExit(f'overlap {e["addr"]}')
    for a, o, n, w in BYTES:
        put(spec, a, bytes([o]), bytes([n]), w)
    put(spec, SET_SITE, SET_OLD, jmp(SET_SITE, syms['ng_set']), 'grain write -> ng_set (u -> byte, Noise Filter)')
    put(spec, GET_SITE, GET_OLD, jmp(GET_SITE, syms['ng_get']), 'grain read -> ng_get (byte -> u)')
    put(spec, PICK_SITE, jmp(PICK_SITE, FM_POST), jmp(PICK_SITE, syms['ng_pick']), 'lt_post -> ng_pick (Noise Filter)')
    # label table (v0.21 edit at 0x601e3840): Off (old string), Fine, Film, Film x3 (old bytes 3..5)
    e, o = covering(spec, TAB_AT, 24)
    if o != 0:
        raise SystemExit('label table edit moved')
    strs = [b'1 Noise Global\0', b'1 Noise Std\0', b'1 Noise Low\0', b'1 Noise Off\0']     # u 0..3 (4/5 = Off)
    ptr, at = [], TAB_AT + 24
    for x in strs:
        ptr.append(at); at += len(x)
    data = struct.pack('<6I', *ptr, ptr[3], ptr[3]) + b''.join(strs)
    if TAB_AT + len(data) > CODE_AT:
        raise SystemExit('label table overflow')
    n = len(e['new']) // 2
    data += stock[TAB_AT - BASE + len(data):TAB_AT - BASE + n]     # rest of the old 74-B span back to stock bytes
    e['expect'] = stock[TAB_AT - BASE:TAB_AT - BASE + len(data)].hex()
    e['new'] = data.hex(); e['why'] = 'v0.22 look extras: sector-1 labels by u: Noise Global / Std / Low / Off, dead EVF step-0 R'
    spec['edits'].append(dict(kind='0x100', addr=hex(CODE_AT), expect=stock[CODE_AT - BASE:CODE_AT - BASE + len(code)].hex(),
                              new=code.hex(), source=SRC, why=f'v0.22 natural grain: ng_set / ng_get ({len(code)} B, dead EVF step-0 R)'))
    spec['edits'].append(dict(kind='0x100', addr=hex(CODE2_AT), expect=stock[CODE2_AT - BASE:CODE2_AT - BASE + len(code2)].hex(),
                              new=code2.hex(), source=SRC, why=f'v0.22 natural grain: ng_pick / ng_put + maps ({len(code2)} B, dead EVF step-10 R)'))
    gb = spec.get('grain_boost', {})
    gb['inert'] = 'v0.22: COLOR grain never attached (GLEVEL bounds 0); hooks kept'
    spec['v022'] = dict(built_by=SRC, base='releases/v0.21/edits.json', noise_filter_sid=NF_SID,
                        grain_bytes={0: 'Global (Noise Filter untouched)', 6: 'Off (Noise Filter Standard, 0)', 1: 'Fine (Low, -1)',
                                     2: 'Film (Off, -2)'}, old_values='3..5 -> Film', editor_order='Noise Global, Std, Low, Off', symbols={k: hex(v) for k, v in syms.items() if k.startswith('ng_')},
                        sites=[hex(SET_SITE), hex(GET_SITE), hex(PICK_SITE)], code_at=hex(CODE_AT), code_len=len(code), code2_at=hex(CODE2_AT), code2_len=len(code2))
    return spec


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    spec = apply(json.loads(a.spec.read_text()))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(spec, indent=1))
    print(json.dumps(spec['v022']))
