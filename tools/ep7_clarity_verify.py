#!/usr/bin/env python3
"""Emulator verification of COLOR clarity (bundle effect_id 3; patches/bloom --clarity) on the EXACT package bytes.
Offline, emulator only, no camera. docs/CLARITY.md.

  tools/ep7_clarity_verify.py SPEC.json --base releases/test7b-sdloader-v3/edits.json [--part P,C,D,S,L,M] [--json out]

Builds the package from SPEC (tools/build_package.build), decodes the patched and restore (= stock) main payloads,
and also builds the BASE package (the camera-proven test 7b) for differential checks. Runs native code from the
images with the bloom verifier's fixtures (tools/ep7_bloom_verify.py). In every run the image segments are mapped
read-only ('r'/'rx'), so any store into 0x60020020..0x6191ffe0 (or anywhere unmapped) faults and fails the run.

  P  package: base package == the base release's recorded sha256; SPEC vs BASE payload differences lie only in
     the changed edit spans; the retired section-1 bloom block is back to stock FF.
  C  clarity: converter 0x603eab39 sets job flag 0x80 exactly for key 11 + mode 11 + profile 1..4 + slot effect_id
     1 or 3 + strength 1..5 (every other key/mode/profile/effect/strength/erased case == stock). Combiner config
     0x603a013b: clarity slot -> combiner 11 bank weights w = W[s] > 1024 on A and 1024-w (negative) on B, packed
     exactly as stock combiner 6 packs its -1024 B gain; combiner 12 -> w = 1024 (A 0, B 1024, no negative);
     mode word and every other bank byte == stock key 11; bloom slot in the same table unchanged; 14 guard
     failures with clarity slots -> bank == stock (w 600); live caller stack == stock.
  D  differential vs BASE (bloom still works, stock when off): for tables without effect 3 (bloom fixtures,
     halation, off, erased, the real flashed table) converter flags/params and full combiner banks are
     byte-identical to the camera-proven base; all-off tables == stock.
  S  store audit: every store instruction in the new routine is the stock-pattern job-flag store or
     stack-relative; no store instruction added versus the base bloom routine.
  L  SD loader v3 (real loader run from the upstream event, v3 verifier fixture): a BUNDLES.BIN whose COLOR1 slot
     is clarity 5 is LOADED by SPEC's loader (and the accessor then feeds the clarity weight) and REJECTED by the
     base loader (old effect_id range 0..2); effect_id 4 is rejected by both.
  M  mutations of the new bytes: each must make C, D or L fail.
"""
import argparse, hashlib, importlib.util, json, struct, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import build_package as BP  # noqa: E402
import oly_container as oc  # noqa: E402
import ep7_bloom_verify as BV  # noqa: E402
from penf_emulator import Region  # noqa: E402

BASE = BV.BASE
SLOT, F_EFF, F_STR = BV.SLOT, BV.F_EFF, BV.F_STR
SF_KEY, MAGIC, TABLE = BV.SF_KEY, BV.MAGIC, BV.TABLE
OLD_BLOOM = (0x60210e10, 0x60210ef0)
IMAGE = (0x60020020, 0x6191ffe0)


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


def ft(slots):
    return BV.fixture_table(slots)


# COLOR1 clarity 1, COLOR2 bloom 5, COLOR3 clarity 5, COLOR4 off; MONO slots hostile (clarity 3)
CL_TABLE = ft({0: (3, 1), 1: (1, 5), 2: (3, 5), 4: (3, 3), 5: (3, 3), 6: (3, 3), 7: (3, 3)})


def slot_of(table, prof):
    e = table[(prof - 1) * SLOT:prof * SLOT]
    return e[F_EFF], e[F_STR]


def flag_on(table, key, mode, prof):
    if key != 11 or mode != 11 or not 1 <= prof <= 4:
        return False
    eff, s = slot_of(table, prof)
    return eff in (1, 3) and 1 <= s <= 5


def pk(x):
    """the stock combiner packing: halfword pair at +92/+136, sign-extended word at +96/+140"""
    return (x & 0xffff) * 0x10001, x & 0xffffffff


def exp_weights(table, prof, comb, bloom_w, clar_w):
    """-> {offset: word} or None (stock w 600 path)."""
    if not 1 <= prof <= 4:
        return None
    eff, s = slot_of(table, prof)
    if not 1 <= s <= 5 or eff not in (1, 3):
        return None
    w = bloom_w[s - 1] if eff == 1 else (clar_w[s - 1] if comb == 11 else 1024)
    a, b = (w, 1024 - w) if comb == 11 else (1024 - w, w)
    (pa, wa), (pb, wb) = pk(a), pk(b)
    return {92: pa, 96: wa, 136: pb, 140: wb}


# ------------------------------------------------------------------ bank run with the live stack
def bank_run(main, table, key, eff, level=0, **jk):
    ctx = bytearray(128)
    struct.pack_into('<I', ctx, 4, BV.REQ)
    struct.pack_into('<I', ctx, 8, BV.BANKB)
    struct.pack_into('<I', ctx, 52, key)
    job = BV.job_with_request(key, eff, level, **jk)
    r = BV.execute(BV.regions(main, table, [BV.stack(), BV.PR.caller(0x603a013b, 0xf0, 20),
                                            Region('ctx', BV.CTX, bytes(ctx), 'rw', True),
                                            Region('job', BV.JOB, bytes(job), 'rw', True),
                                            Region('bank', BV.BANKB, bytes(7364 + 256), 'rw', True)]),
                   {'pc': BV.CALLER, 'sp': BV.STACK + 0x1800, 'a0': BV.CTX, **BV.REGS0}, BV.CALLER + 7, limit=20000)
    m = BV.mem(r)
    return BV.regs_ok(r, BV.CALLER + 7) and m['job'] == bytes(job), m['bank'][7364:7364 + 184], m['stack']


_live = {}


def live_from(stock):
    """stack offset of the getter's return word (sp at 0x6039fee8 entry) in the stock run: bytes from there up are
    the caller's live frame."""
    if 'off' not in _live:
        ctx = bytearray(128)
        struct.pack_into('<I', ctx, 4, BV.REQ)
        struct.pack_into('<I', ctx, 8, BV.BANKB)
        struct.pack_into('<I', ctx, 52, 11)
        job = BV.job_with_request(11, 0x0402)
        r = BV.execute(BV.regions(stock, CL_TABLE, [BV.stack(), BV.PR.caller(0x603a013b, 0xf0, 20),
                                                    Region('ctx', BV.CTX, bytes(ctx), 'rw', True),
                                                    Region('job', BV.JOB, bytes(job), 'rw', True),
                                                    Region('bank', BV.BANKB, bytes(7364 + 256), 'rw', True)]),
                       {'pc': BV.CALLER, 'sp': BV.STACK + 0x1800, 'a0': BV.CTX, **BV.REGS0}, 0x6039fee8, limit=20000)
        assert not r['fault'] and r['registers']['pc'] == 0x6039fee8
        _live['off'] = r['registers']['sp'] - BV.STACK
    return _live['off']


def stock_combiner6_bank(stock):
    """Run the stock combiner-6 handler (Dramatic Tone, the stock negative-B-gain combiner) directly."""
    CTX, REQ, BANK = 0x1a000000, 0x1a001000, 0x1c000000
    ctx = bytearray(256)
    struct.pack_into('<I', ctx, 4, REQ)
    struct.pack_into('<I', ctx, 8, BANK)
    struct.pack_into('<I', ctx, 52, 0x0102006d)
    s = lambda lo, hi: stock[lo - BASE:hi - BASE]
    r = BV.execute([Region('code', 0x60340000, s(0x60340000, 0x603c0000), 'rx'),
                    Region('tbl', 0x604e0000, s(0x604e0000, 0x60540000), 'r'),
                    Region('stack', BV.STACK, bytes(0x2000), 'rw'), BV.PR.caller(0x603a0174, 0xf0, 20),
                    Region('ctx', CTX, bytes(ctx), 'rw'), Region('req', REQ, bytes(4096), 'rw'),
                    Region('bank', BANK, bytes(7364 + 256), 'rw', True)],
                   {'pc': BV.CALLER, 'sp': BV.STACK + 0x1800, 'd0': 6, 'd3': 1024, 'a0': CTX, 'a2': CTX},
                   BV.CALLER + 7, limit=20000)
    assert not r['fault'], r['fault']
    b = BV.mem(r)['bank'][7364:]
    return struct.unpack_from('<I', b, 4)[0], struct.unpack_from('<I', b, 136)[0], struct.unpack_from('<I', b, 140)[0]


# ------------------------------------------------------------------ C
def t_converter(stock, img, quick=False):
    ok, rows, n_on = True, [], 0
    cases = []
    for key in ((11, 12, SF_KEY) if quick else (0, 11, 12, SF_KEY, 0x01010078, 0x000b0000)):
        for prof in ((0, 1, 2, 3, 4, 5, 255) if key == 11 else (1, 3)):
            for mode in ((11, 12) if key == 11 else (11,)):
                for art, f in (((0, 0),) if quick else ((0, 0), (1, 0), (5, 1))):
                    cases.append((CL_TABLE, 'CL', key, mode, prof, art, f))
    edge = [('clarity strength 0', ft({0: (3, 0)})), ('clarity strength 6', ft({0: (3, 6)})),
            ('clarity strength 255', ft({0: (3, 255)})), ('effect 4 strength 3', ft({0: (4, 3)})),
            ('effect 0x83 strength 3', ft({0: (0x83, 3)})), ('effect 0xff strength 3', ft({0: (0xff, 3)})),
            ('effect 2 (halation) strength 3', ft({0: (2, 3)})), ('erased table', b'\xff' * 512)]
    for label, tb in edge:
        cases.append((tb, label, 11, 11, 1, 0, 0))
    for tb, label, key, mode, prof, art, f in cases:
        (sg, sf, sp_, sc), (pg, pf, pp, pc) = [BV.conv_run(m, tb, key, mode, prof, art, f) for m in (stock, img)]
        on = flag_on(tb, key, mode, prof)
        n_on += on
        want = sf | (0x80 if on else 0)
        good = sg and pg and sc and pc and pf == want and sp_[:12] == pp[:12] and sp_[16:] == pp[16:]
        ok &= good
        if not good or label != 'CL' or (on and prof in (1, 3)):
            rows.append(dict(table=label, key=hex(key), mode=mode, profile=prof, art=art, stock=hex(sf), patched=hex(pf),
                             flag_expected=on, ok=good))
    return ok and n_on > 0, rows


def t_combiner(stock, img, bloom_w, clar_w, quick=False):
    ok, rows = True, []
    off = live_from(stock)
    c6_mode, c6_136, c6_140 = stock_combiner6_bank(stock)
    enc_ok = (c6_136, c6_140) == pk(-1024)
    rows.append(dict(check='stock combiner 6 (Dramatic Tone) B gain encoding', mode=hex(c6_mode), b136=hex(c6_136),
                     b140=hex(c6_140), equals_pack_of_minus_1024=enc_ok, ok=enc_ok))
    ok &= enc_ok
    for eff, comb in ((0x0402, 11), (0x0403, 12)):
        sg, sb, sstk = bank_run(stock, CL_TABLE, 11, eff)
        ok &= sg
        mode_stock = struct.unpack_from('<I', sb, 4)[0]
        for prof in (1, 2, 3):               # clarity 1, bloom 5, clarity 5
            for rec in ((3,) if quick else (0, 3, 15)):
                pg, pb, pstk = bank_run(img, CL_TABLE, 11, eff, ext=(prof, 11, MAGIC), rec=rec)
                exp = exp_weights(CL_TABLE, prof, comb, bloom_w, clar_w)
                got = BV.weights_of(pb)
                good = (pg and got == exp and BV.mask_w(pb) == BV.mask_w(sb) and pstk[off:] == sstk[off:]
                        and struct.unpack_from('<I', pb, 4)[0] == mode_stock)
                ok &= good
                if rec == 3 or not good:
                    eid, s = slot_of(CL_TABLE, prof)
                    sh = struct.unpack_from('<hh', pb, 136) + struct.unpack_from('<i', pb, 140)
                    rows.append(dict(combiner=comb, profile=prof, effect_id=eid, strength=s, record=rec,
                                     patched={k: hex(v) for k, v in got.items()},
                                     expected={k: hex(v) for k, v in exp.items()}, b_signed=sh,
                                     mode=hex(struct.unpack_from('<I', pb, 4)[0]), rest_of_bank_identical=BV.mask_w(pb) == BV.mask_w(sb),
                                     live_stack_identical=pstk[off:] == sstk[off:], ok=good))
        for s in range(1, 6):                # every clarity strength on both combiners
            tb = ft({1: (3, s)})
            pg, pb, pstk = bank_run(img, tb, 11, eff, ext=(2, 11, MAGIC))
            exp = exp_weights(tb, 2, comb, bloom_w, clar_w)
            good = pg and BV.weights_of(pb) == exp and BV.mask_w(pb) == BV.mask_w(sb) and pstk[off:] == sstk[off:]
            ok &= good
            rows.append(dict(combiner=comb, clarity_strength=s, w96=struct.unpack_from('<i', pb, 96)[0],
                             b140=struct.unpack_from('<i', pb, 140)[0], ok=good))
        fails = [('wrong callback', CL_TABLE, dict(callback=BV.CALLBACK + 1)), ('record not in list', CL_TABLE, dict(rec=16)),
                 ('request+4 = 0', CL_TABLE, dict(rec=None)), ('foreign parent', CL_TABLE, dict(parent=BV.JOB + 0x40)),
                 ('no marker', CL_TABLE, dict(ext=None)), ('wrong marker', CL_TABLE, dict(ext=(1, 11, 0xB3))),
                 ('mode 12', CL_TABLE, dict(ext=(1, 12, MAGIC))), ('profile 0', CL_TABLE, dict(ext=(0, 11, MAGIC))),
                 ('profile 5 (MONO1 clarity)', CL_TABLE, dict(ext=(5, 11, MAGIC))), ('COLOR4 off', CL_TABLE, dict(ext=(4, 11, MAGIC))),
                 ('clarity strength 0', ft({0: (3, 0)}), {}), ('clarity strength 6', ft({0: (3, 6)}), {}),
                 ('effect 4', ft({0: (4, 3)}), {}), ('erased table', b'\xff' * 512, {})]
        for label, tb, jk in fails:
            pg, pb, _ = bank_run(img, tb, 11, eff, **jk)
            good = pg and pb == sb
            ok &= good
            rows.append(dict(combiner=comb, case=label, identical_to_stock_w600=pb == sb, ok=good))
    for key, eff, lv in ((SF_KEY, 0x0402, 0), (SF_KEY, 0x0402, 5), (SF_KEY, 0x0403, -5), (0x01010078, 0x0402, 0),
                         (12, 0x0402, 0), (11, 0x0c00, 0), (11, 0x0400, 0)):
        sg, sb, _ = bank_run(stock, CL_TABLE, key, eff, lv)
        pg, pb, _ = bank_run(img, CL_TABLE, key, eff, lv, ext=(1, 11, MAGIC))
        good = sg and pg and sb == pb
        ok &= good
        rows.append(dict(key=hex(key), effect=hex(eff), level=lv, identical_to_stock=sb == pb, ok=good))
    return ok, rows


# ------------------------------------------------------------------ D
def d_tables():
    t = [('bloom fixture (bloom verifier MAIN_TABLE)', BV.MAIN_TABLE), ('real flashed table', None),
         ('all off', bytes(512)), ('erased', b'\xff' * 512), ('halation 1..4', ft({i: (2, i + 1) for i in range(4)})),
         ('poison (SD env)', BV.SDV3.poison_table())]
    for s in range(1, 6):
        t.append((f'bloom {s} all COLOR', ft({i: (1, s) for i in range(4)})))
    return t


def t_diff(stock, img, base, quick=False):
    ok, rows = True, []
    for label, tb in d_tables():
        n = 0
        good = True
        for key in ((11, SF_KEY) if quick else (11, 12, SF_KEY)):
            for prof in (0, 1, 2, 3, 4, 5):
                for mode in ((11, 12) if key == 11 else (11,)):
                    a, b = BV.conv_run(base, tb, key, mode, prof), BV.conv_run(img, tb, key, mode, prof)
                    g = a[0] and b[0] and a[1:] == b[1:]
                    if label == 'all off':
                        s_ = BV.conv_run(stock, tb, key, mode, prof)
                        g &= s_[1:] == b[1:]
                    good &= g
                    n += 1
        for eff in (0x0402, 0x0403):
            for prof in (0, 1, 2, 3, 4, 5):
                for rec in ((3,) if quick else (0, 3)):
                    a, b = bank_run(base, tb, 11, eff, ext=(prof, 11, MAGIC), rec=rec), bank_run(img, tb, 11, eff, ext=(prof, 11, MAGIC), rec=rec)
                    g = a[0] and b[0] and a[1] == b[1] and a[2] == b[2]
                    if label == 'all off':
                        s_ = bank_run(stock, tb, 11, eff, ext=(prof, 11, MAGIC), rec=rec)
                        g &= s_[1] == b[1]
                    good &= g
                    n += 1
        ok &= good
        rows.append(dict(table=label, runs=n, identical_to_base=good, ok=good))
    return ok, rows


# ------------------------------------------------------------------ S
def t_store(spec, base_spec):
    B3 = _load('ep7_sd_bundles_v3_build_c', ROOT / 'patches/sd_bundles_v3/build.py')
    import collections

    def audit(sp):
        bl = sp['bloom']
        a = int(bl['code_at'], 16)
        e = [x for x in sp['edits'] if int(x['addr'], 16) == a][0]
        code = bytes.fromhex(e['new'])
        stop = int(bl['symbols']['w_lut'], 16)
        ins = B3.disasm(code[:stop - a], a)
        return ins, B3.store_audit(ins)
    ins, st = audit(spec)
    _, st0 = audit(base_spec)
    new = collections.Counter((t, k) for _, t, k, _ in st)
    old = collections.Counter((t, k) for _, t, k, _ in st0)
    added = new - old
    allowed = {('mov d0,(a2)', 'ind'), ('mov d1,(sp)', 'sp')}     # job-flag word (params block) / return word
    bad = [f'{t} ({k})' for (t, k) in new if (t, k) not in allowed]
    absimg = [hex(tg) for _, _, k, tg in st if k == 'abs' and B3.in_image(tg)]
    ok = not added and not bad and not absimg and len(ins) > 40
    return ok, dict(instructions=len(ins), stores=[f'{hex(a)} {t} ({k})' for a, t, k, _ in st],
                    added_vs_base_bloom=[f'{t} x{n}' for (t, _), n in added.items()], unexpected=bad, abs_into_image=absimg)


# ------------------------------------------------------------------ L
def t_loader(spec, base_spec, img, base_img, stock, clar_w, card=None):
    V3 = _load('ep7_verify_sd_bundles_v3_c', ROOT / 'tools/ep7_verify_sd_bundles_v3.py')
    SB = V3.SB
    flashed = bytes.fromhex(spec['table_hex'])
    t = bytearray(flashed)
    if any(t[0:64]):
        raise SystemExit('COLOR1 not empty in the flashed table')
    t[F_EFF], t[F_STR] = 3, 5
    clar = bytes(t)
    t4 = bytearray(flashed)
    t4[F_EFF], t4[F_STR] = 4, 3
    rows, ok = [], True
    f_cl = SB.make_file(clar)
    # make_file only formats; the range rule is the loader's (and table_ok, its Python mirror)
    lo, span, _ = SB.range_table(SB.layout())
    rows.append(dict(check='python mirror accepts clarity file, rejects effect 4', ok=SB.table_ok(clar, lo, span) and not SB.table_ok(bytes(t4), lo, span)))
    ok &= rows[-1]['ok']
    runs = [('spec loader, clarity file', img, spec, f_cl, 'load'),
            ('base loader, clarity file', base_img, base_spec, f_cl, 'reject'),
            ('spec loader, effect-4 file', img, spec, SB.make_file(bytes(t4)), 'reject')]
    if card is not None:
        runs.append((f'spec loader, release card file {card.name}', img, spec, card.read_bytes(), 'load'))
    for name, im, sp, f, expect in runs:
        R = V3.Runner(stock, sp['sd_bundles_v3']['code_len'])
        base_run = im is base_img
        # the v3 fixture's model uses the NEW ranges; the base loader (old range 0..2) is judged by its outcome only
        case = V3.V1.Case(name, f, expect=None if base_run else expect)
        g, probs, p = R.single(im, case)
        st = struct.unpack_from('<H', p['mem']['evm'], V3.ST_OFF)[0]
        if base_run:
            good = not p['fault'] and st == 0xffff
        else:
            good = g and ((1 <= st <= V3.LIM) if expect == 'load' else st == 0xffff)
        row = dict(check=name, expect=expect, state=hex(st), ok=good, problems=probs[:3])
        if expect == 'load' and good:
            buf = p['mem']['heap'][0x400:0x400 + SB.BUF_SIZE]
            syms = {k: int(v, 16) for k, v in sp['sd_bundles_v3']['accessor'].items()}
            r, _, _ = V3.acc_run(im, syms['tbl_idx'], 0, st, buf)
            a0 = r['registers']['a0']
            got = buf[a0 - V3.BUF_IN:a0 - V3.BUF_IN + 64] if V3.BUF_IN <= a0 < V3.BUF_IN + SB.BUF_SIZE else None
            want = f[32:32 + 64]
            row['accessor_slot0_is_file_slot0'] = got == want
            row['slot0_effect_strength'] = (want[F_EFF], want[F_STR])
            good &= got == want and want[F_EFF] == 3
            row['ok'] = good
        ok &= good
        rows.append(row)
    return ok, rows


# ------------------------------------------------------------------ M
def mutations(img, spec, base_spec):
    bl = spec['bloom']
    sy = {k: int(v, 16) for k, v in bl['symbols'].items()}
    flag, w, wl, c11, c12 = sy['bloom_flag'], sy['bloom_w'], sy['w_lut'], sy['c11_lut'], sy['c12_lut']
    out = []

    def find(pat, a, b):
        d = img[a - BASE:b - BASE]
        i = d.find(pat)
        if i < 0 or d.find(pat, i + 1) >= 0:
            raise SystemExit(f'mutation pattern {pat.hex()} not unique in {a:#x}..{b:#x}')
        return a + i

    def mut(name, at, new):
        m = bytearray(img)
        m[at - BASE:at - BASE + len(new)] = new
        out.append((name, bytes(m), 'img'))
    mut('clarity LUT s3 +1', c11 + 4, struct.pack('<H', struct.unpack_from('<H', img, c11 + 4 - BASE)[0] + 1))
    mut('clarity LUT s5 -> 1024', c11 + 8, struct.pack('<H', 1024))
    mut('combiner-12 LUT s1 1024 -> 1100', c12, struct.pack('<H', 1100))
    mut('bloom LUT s2 +1', wl + 2, struct.pack('<H', struct.unpack_from('<H', img, wl + 2 - BASE)[0] + 1))
    ret = struct.pack('<I', int(bl['clarity']['c11_ret'], 16))
    mut('combiner-11 return address -> combiner 12', find(b'\xfc\xc9' + ret, w, wl) + 2, struct.pack('<I', 0x603a0501))
    i = find(b'\xfc\xc9' + ret, w, wl)
    mut('combiner-11 test inverted (beq -> bne)', i + 6, b'\xc9')
    mut('combiner-11 test skipped (beq -> bra)', i + 6, b'\xca')
    mut('bloom_w: clarity id 3 -> 2', find(b'\xa0\x03', w, wl), b'\xa0\x02')
    mut('bloom_w: bloom id test 1 -> 3', find(b'\xa0\x01\xc8', w, wl), b'\xa0\x03\xc8')
    mut('bloom_flag: clarity id 3 -> 2', find(b'\xa0\x03', flag, w), b'\xa0\x02')
    mut('bloom_flag: clarity id 3 -> 4', find(b'\xa0\x03', flag, w), b'\xa0\x04')
    mut('bloom_w: strength bound 5 -> 6', find(b'\xa0\x05', w, wl), b'\xa0\x06')
    # (not used: removing bloom_w's `mov d1,(sp)` is an equivalent mutant here: retf returns through MDR and the
    #  dead return word is overwritten by combiner 11's next call at 0x603a04af in stock too)
    mut('bloom_flag: flag 0x80 -> 0x40', find(b'\xf8\xe4\x80', flag, w), b'\xf8\xe4\x40')
    mut('bloom_w: clarity LUT pointer -> bloom LUT', find(b'\xfc\xdd' + struct.pack('<I', c11), w, wl) + 2, struct.pack('<I', wl))
    mut('bloom_w: c12 select removed (6 B nop)', find(b'\xfc\xdd' + struct.pack('<I', c12), w, wl), b'\xcb' * 6)
    return out


def loader_span_mutation(img, spec):
    """span byte of field effect_id (byte 28) in the loader's range table: 3 -> 2."""
    B3 = _load('ep7_sd_bundles_v3_build_m', ROOT / 'patches/sd_bundles_v3/build.py')
    V1 = B3.V1
    lo, span, _ = V1.range_table(V1.layout())
    a = B3.CODE_AT
    n = spec['sd_bundles_v3']['code_len']
    d = img[a - BASE:a + n - BASE]
    pat = bytes(span)
    i = d.find(pat)
    if i < 0 or d.find(pat, i + 1) >= 0 or span[F_EFF] != 3:
        raise SystemExit('loader span table not found once / effect span != 3')
    m = bytearray(img)
    m[a + i + F_EFF - BASE] = 2
    return a + i + F_EFF, bytes(m)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('edits', type=Path)
    ap.add_argument('--base', type=Path, default=ROOT / 'releases/test7b-sdloader-v3/edits.json')
    ap.add_argument('--base-sha', default='d6a85f20abbd1b2871cd4b20e3be22d1722a3ab3a2af9559c27681fb7a48ea42')
    ap.add_argument('--part', default='P,C,D,S,L,M')
    ap.add_argument('--card', type=Path, help='release card file EP7MOD/BUNDLES.BIN to run through the loader (part L)')
    ap.add_argument('--expect-sha', help='sha256 the built package must have (the release patched.pkg.bin)')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    parts = set(a.part.split(','))
    spec, base_spec = json.loads(a.edits.read_text()), json.loads(a.base.read_text())
    stock_pkg = BP.STOCK.read_bytes()
    pkg, restore, info = BP.build(spec, stock_pkg)
    bpkg, brestore, binfo = BP.build(base_spec, stock_pkg)
    img, stock = oc.parse(pkg)[0].payload, oc.parse(restore)[0].payload
    base_img = oc.parse(bpkg)[0].payload
    bl = spec['bloom']
    bloom_w, clar_w = bl['strength_w'], bl['clarity']['strength_w']
    res = []

    def report(name, ok, detail):
        res.append(dict(test=name, passed=bool(ok), detail=detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}", flush=True)
        if isinstance(detail, list):
            for r in detail:
                if not r.get('ok', True):
                    print('      BAD', json.dumps(r, default=str)[:400])
        elif not ok:
            print('      ', json.dumps(detail, default=str)[:1500])

    if 'P' in parts:
        import numpy as np
        bsha = hashlib.sha256(bpkg).hexdigest()
        diff = np.nonzero(np.frombuffer(img, np.uint8) != np.frombuffer(base_img, np.uint8))[0] + BASE
        A = {e['addr']: e for e in spec['edits']}
        B = {e['addr']: e for e in base_spec['edits']}
        changed = [k for k in sorted(set(A) | set(B)) if A.get(k, {}).get('new') != B.get(k, {}).get('new')]
        spans = [(int(k, 16), int(k, 16) + len(bytes.fromhex((A.get(k) or B.get(k))['new']))) for k in changed]
        in_sp = all(any(s <= x < t for s, t in spans) for x in diff)
        old_ff = img[OLD_BLOOM[0] - BASE:OLD_BLOOM[1] - BASE] == stock[OLD_BLOOM[0] - BASE:OLD_BLOOM[1] - BASE] == b'\xff' * (OLD_BLOOM[1] - OLD_BLOOM[0])
        sdiff = np.nonzero(np.frombuffer(img, np.uint8) != np.frombuffer(stock, np.uint8))[0] + BASE
        allsp = [(int(e['addr'], 16), int(e['addr'], 16) + len(bytes.fromhex(e['new']))) for e in spec['edits']]
        in_all = all(any(s <= x < t for s, t in allsp) for x in sdiff)
        ok = bsha == a.base_sha and in_sp and old_ff and in_all and (not a.expect_sha or hashlib.sha256(pkg).hexdigest() == a.expect_sha)
        report('P package: base == camera-proven release bytes; spec-vs-base and spec-vs-stock diffs only inside edit spans; old bloom block FF',
               ok, dict(base_sha256=bsha, base_matches=bsha == a.base_sha, package_sha256=hashlib.sha256(pkg).hexdigest(),
                        restore_sha256=hashlib.sha256(restore).hexdigest(), changed_edits=changed, bytes_changed_vs_base=len(diff),
                        bytes_changed_vs_stock=len(sdiff), old_bloom_block_ff=old_ff, info=info))
    if 'C' in parts:
        ok, rows = t_converter(stock, img)
        report(f'C converter flag (effect 1/3, {len(rows)} rows shown)', ok, rows)
        ok, rows = t_combiner(stock, img, bloom_w, clar_w)
        report(f'C combiner banks (clarity w > 1024 on combiner 11, 1024 on 12; guards; stack) ({len(rows)} rows)', ok, rows)
    if 'D' in parts:
        ok, rows = t_diff(stock, img, base_img)
        report('D differential vs camera-proven base (no effect 3 in table) + all-off == stock', ok, rows)
    if 'S' in parts:
        ok, det = t_store(spec, base_spec)
        report('S store audit of the new routine (no store into the image; none added vs base bloom)', ok, det)
    if 'L' in parts:
        ok, rows = t_loader(spec, base_spec, img, base_img, stock, clar_w, a.card)
        report('L SD loader v3: clarity file loaded by spec loader, rejected by base loader; effect 4 rejected', ok, rows)
    if 'M' in parts:
        mres = []
        muts = mutations(img, spec, base_spec)
        at, limg = loader_span_mutation(img, spec)
        for name, m, _ in muts:
            try:
                g = (t_converter(stock, m, quick=True)[0] and t_combiner(stock, m, bloom_w, clar_w, quick=True)[0]
                     and t_diff(stock, m, base_img, quick=True)[0])
            except Exception as e:      # noqa: BLE001  a mutation that breaks a fixture counts as detected
                g = False
            mres.append(dict(mutation=name, detected=not g))
            print(f"{'PASS' if not g else 'FAIL'}  M '{name}' detected", flush=True)
        try:
            g = t_loader(spec, base_spec, limg, base_img, stock, clar_w)[0]
        except Exception:               # noqa: BLE001
            g = False
        mres.append(dict(mutation=f'loader effect_id span 3 -> 2 at {at:#x}', detected=not g))
        print(f"{'PASS' if not g else 'FAIL'}  M 'loader effect_id span 3 -> 2' detected", flush=True)
        report(f'M {sum(m["detected"] for m in mres)}/{len(mres)} mutations detected', all(m['detected'] for m in mres), mres)
    allok = all(r['passed'] for r in res)
    print(f"{'PASS' if allok else 'FAIL'}  overall (parts {a.part}); package {info}")
    if a.json:
        a.json.write_text(json.dumps(dict(spec=str(a.edits), base=str(a.base), parts=a.part, passed=allok, results=res,
                                          scope='emulator only; CPU-side bank programming; no ISP pixels; no camera contacted'),
                                     indent=1, default=str))
    sys.exit(0 if allok else 1)


if __name__ == '__main__':
    main()
