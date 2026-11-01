#!/usr/bin/env python3
"""Film Simulation library compiler: EP7MOD/LIBRARY.BIN, format v2 (offline desktop tool, no camera).

  .venv/bin/python -I tools/ep7_library.py bundles/library_example.json --out generated/library
      -> generated/library/EP7MOD/LIBRARY.BIN (copy the EP7MOD folder to the card root by hand)
  .venv/bin/python -I tools/ep7_library.py --check path/to/LIBRARY.BIN [--list]
  .venv/bin/python -I tools/ep7_library.py bundles/library_example.json --dry-run --list

The file holds N named looks (each a full 64-byte bundle in the patches/bundles/layout.json ABI plus a
<=12-char ASCII name and optional notes) and a slot assignment (COLOR1-4, MONO1-4 -> look index). It
also carries the resolved 8 x 64-byte table, byte-identical to what patches/bundles/build.py
build_table() makes for the same assignment, so a phase-1 camera loader is the v1 loader plus a name
copy. Format, placement rule and loader rules: docs/FILM_LIBRARY.md.

Bundles are made by patches/bundles/build.py slot_entry() (same recipes, same validation); per-byte
ranges come from patches/sd_bundles/build.py (same constants the v1 loader is assembled from).
Never writes an SD-update name (E142*.BIN etc.); the updater only scans DCOLYMP/.
"""
import argparse, importlib.util, json, re, struct, sys, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BB = _load('ep7_bundles_build', ROOT / 'patches/bundles/build.py')
SB = _load('ep7_sd_bundles_build', ROOT / 'patches/sd_bundles/build.py')

# ---- format v2 constants (docs/FILM_LIBRARY.md §2)
MAGIC = SB.MAGIC                       # b'EP7B', same family as v1; version tells them apart
VERSION, HDR_LEN, FW_BUILD = 2, 64, SB.FW_BUILD
SHA_PREFIX = SB.SHA_PREFIX
SLOT_OFF, SLOT_LEN = 64, 16            # assign[8] u8 + 8 reserved zero
TABLE_OFF, TABLE_LEN = 80, 512         # resolved 8 x 64 table (== v1 payload)
LOOKS_OFF, LOOK_LEN = 592, 96          # look records
NAME_OFF, NAME_LEN, NAME_MAX = 64, 16, 12
CLASS_OFF, MASK_OFF = 80, 81
EMPTY = 0xFF                           # slot assignment: no look -> all-zero entry -> stock rendering
MAX_LOOKS = 64
MAX_FILE = 16384                       # largest firmware fixed-block pool class (docs/SD_BUNDLES.md)
NOTE_MAX = 200
CLASS_COLOUR, CLASS_MONO = 0, 1
MASK_COLOR_SLOT, MASK_MONO_SLOT = 1, 2
SLOTS = BB.SLOTS
SAT = slice(BB.SAT_OFF, BB.SAT_OFF + 12)
NAME_RE = re.compile(r'^[\x20-\x3f\x41-\x7e]{1,12}$')   # printable ASCII except '@' (OSD symbol escape)
LOOK_KEYS = {'name', 'recipe', 'notes', 'wb', 'grain', 'effect', 'vignette', 'sat'}

# Default menu names for the shipped recipes (<= 12 chars). A look may override with "name".
DEFAULT_NAMES = {
    'provia': 'Provia', 'velvia': 'Velvia', 'classic_chrome': 'Cl. Chrome', 'classic_neg': 'Classic Neg',
    'nostalgic_neg': 'Nostalgic', 'reala_ace': 'Reala Ace', 'eterna': 'Eterna',
    'eterna_bleach_bypass': 'Bleach Byp.', 'acros': 'Acros', 'kodachrome_64': 'Kodachrome',
    'cinestill_800t': 'CineStill', 'portra_400_bloom': 'Portra Bloom', 'classic_neg_halation': 'Neg Halation',
}


# Fields added in a backward-compatible way (0 = the old meaning) stay out of the ABI CRC, so files written before them
# still load: bloom_tint (+45, test13b; 0 = neutral bloom).
COMPAT_FIELDS = ('bloom_tint', 'art_effect')   # added later; zero in older files, kept out of the CRC


def layout_crc():
    """CRC-32 of the canonical layout.json ABI (slot size, slot names, field offsets/lengths)."""
    lay = SB.layout()
    canon = json.dumps({'slot_bytes': lay['slot_bytes'], 'slots': lay['slots'],
                        'fields': {k: v[:2] for k, v in sorted(lay['fields'].items()) if k not in COMPAT_FIELDS}},
                       sort_keys=True, separators=(',', ':'))
    return zlib.crc32(canon.encode()) & 0xffffffff


def is_mono_recipe(rc):
    return bool(rc.get('mono_filter')) or str(rc.get('base', '')).lower().startswith('monochrome')


# ---- placement rule P(look, slot) (docs/FILM_LIBRARY.md §3)
def place(rec, slot):
    """Look record (96 B) + slot name -> the 64-byte table entry the slot gets."""
    b, cls, mask = bytearray(rec[:64]), rec[CLASS_OFF], rec[MASK_OFF]
    if slot.startswith('COLOR'):
        if not mask & MASK_COLOR_SLOT:
            raise ValueError(f'{slot}: look cannot go in a COLOR slot')
        b[SAT] = bytes(12)
        b[BB.COLOUR_OFF] = 0
        b[31] = BB.FLAG_HL
    else:
        if not mask & MASK_MONO_SLOT:
            raise ValueError(f'{slot}: look cannot go in a MONO slot')
        if cls == CLASS_COLOUR:
            b[BB.COLOUR_OFF] = 1
            b[31] = BB.FLAG_HL | BB.FLAG_RENDER_COLOUR
        else:
            b[31] = 0
    return bytes(b)


def look_record(key, look, recipes):
    """-> (96-byte record, meta). The canonical bundle is the COLOR-slot entry with sat[12] kept at +33
    (colour byte 0) for colour looks, or the MONO stock entry for mono looks."""
    if not isinstance(look, dict):
        raise ValueError(f'look {key}: must be an object')
    unknown = set(look) - LOOK_KEYS
    if unknown:
        raise ValueError(f'look {key}: unknown keys {sorted(unknown)}')
    rname = look.get('recipe', key)
    if rname not in recipes:
        raise ValueError(f'look {key}: unknown recipe {rname!r}')
    name = look.get('name', DEFAULT_NAMES.get(rname, rname.replace('_', ' ').title()[:NAME_MAX]))
    if not isinstance(name, str) or not NAME_RE.match(name) or name != name.strip():
        raise ValueError(f'look {key}: name {name!r} must be 1-12 printable ASCII chars, no "@", '
                         'no leading/trailing spaces')
    notes = look.get('notes', '')
    if not isinstance(notes, str) or len(notes.encode()) > NOTE_MAX:
        raise ValueError(f'look {key}: notes must be a string of at most {NOTE_MAX} UTF-8 bytes')
    rc = recipes[rname]
    slot = {k: look[k] for k in ('wb', 'grain', 'effect', 'vignette') if k in look}
    slot['recipe'] = rname
    if is_mono_recipe(rc):
        if 'sat' in look:
            raise ValueError(f'look {key}: "sat" is meaningless for a mono look')
        mono, _ = BB.slot_entry('MONO1', slot, recipes)
        bundle, cls, mask = mono, CLASS_MONO, MASK_MONO_SLOT
    else:
        color, _ = BB.slot_entry('COLOR1', slot, recipes)
        bundle, cls, mask = bytearray(color), CLASS_COLOUR, MASK_COLOR_SLOT
        sat = look.get('sat', rc.get('sat', [0] * 12))
        if isinstance(sat, list) and len(sat) == 12 and all(isinstance(v, int) and not isinstance(v, bool)
                                                            and -5 <= v <= 5 for v in sat):
            bundle[SAT] = struct.pack('<12b', *sat)
            mask |= MASK_MONO_SLOT
        elif 'sat' in look:
            raise ValueError(f'look {key}: sat must be 12 integers in -5..5')
        bundle = bytes(bundle)
    rec = bytearray(LOOK_LEN)
    rec[:64] = bundle
    rec[NAME_OFF:NAME_OFF + len(name)] = name.encode('ascii')
    rec[CLASS_OFF], rec[MASK_OFF] = cls, mask
    # Self-check: P(record, slot) must equal what patches/bundles/build.py makes for that slot.
    for s in ('COLOR1', 'MONO1'):
        if not mask & (MASK_COLOR_SLOT if s == 'COLOR1' else MASK_MONO_SLOT):
            continue
        ref_slot = dict(slot)
        if s == 'MONO1' and cls == CLASS_COLOUR:
            ref_slot.update(render_colour=True, sat=list(struct.unpack('<12b', bundle[SAT])))
        ref, _ = BB.slot_entry(s, ref_slot, recipes)
        if place(bytes(rec), s) != ref:
            raise AssertionError(f'look {key}: placement rule disagrees with build.py for {s}')
    return bytes(rec), dict(key=key, name=name, recipe=rname, cls='mono' if cls else 'colour',
                            slots=('COLOR ' if mask & 1 else '') + ('MONO' if mask & 2 else ''), notes=notes)


def compile_library(cfg, recipes=None):
    """User JSON dict -> (file bytes, info). Looks keep JSON order; "include_recipes" ones follow."""
    recipes = recipes or BB.load_recipes()
    unknown = set(cfg) - {'_comment', 'looks', 'include_recipes', 'slots'}
    if unknown:
        raise ValueError(f'unknown top-level keys {sorted(unknown)}')
    looks = dict(cfg.get('looks', {}))
    inc = cfg.get('include_recipes', [])
    inc = list(recipes) if inc == 'all' else inc
    if not isinstance(inc, list):
        raise ValueError('include_recipes must be "all" or a list of recipe names')
    for r in inc:
        if r not in recipes:
            raise ValueError(f'include_recipes: unknown recipe {r!r}')
        looks.setdefault(r, {'recipe': r})
    if not 1 <= len(looks) <= MAX_LOOKS:
        raise ValueError(f'need 1..{MAX_LOOKS} looks, got {len(looks)}')
    recs, metas = [], []
    for k, v in looks.items():
        r, m = look_record(k, v, recipes)
        recs.append(r)
        metas.append(m)
    names = [m['name'].lower() for m in metas]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ValueError(f'duplicate look names (case-insensitive): {dup}')
    keys = [m['key'] for m in metas]
    slots = cfg.get('slots', {})
    if set(slots) - set(SLOTS):
        raise ValueError(f'unknown slot keys {sorted(set(slots) - set(SLOTS))}')
    assign = []
    for s in SLOTS:
        k = slots.get(s)
        if k is None:
            assign.append(EMPTY)
            continue
        if k not in keys:
            raise ValueError(f'{s}: unknown look {k!r}')
        assign.append(keys.index(k))
    table = b''.join(bytes(64) if a == EMPTY else place(recs[a], s) for s, a in zip(SLOTS, assign))
    notes = b''.join(struct.pack('<BB', i, len(m['notes'].encode())) + m['notes'].encode()
                     for i, m in enumerate(metas) if m['notes'])
    data = make_file(assign, table, recs, notes)
    probs = check_file(data)
    if probs:
        raise ValueError(f'built file fails the loader rules: {probs}')
    return data, dict(looks=metas, assign=assign)


def header(n_looks, notes_off, notes_len, file_len, crc=0):
    h = MAGIC + struct.pack('<HHII', VERSION, HDR_LEN, FW_BUILD, file_len - HDR_LEN) + struct.pack('<I', crc)
    h += SHA_PREFIX + struct.pack('<HHHHHHHHI', n_looks, LOOK_LEN, SLOT_OFF, TABLE_OFF, LOOKS_OFF,
                                  notes_off, notes_len, 64, layout_crc())
    return h + bytes(HDR_LEN - len(h))


def make_file(assign, table, recs, notes=b''):
    n = len(recs)
    notes_off = LOOKS_OFF + n * LOOK_LEN if notes else 0
    file_len = LOOKS_OFF + n * LOOK_LEN + len(notes)
    if file_len > MAX_FILE:
        raise ValueError(f'file would be {file_len} B (> {MAX_FILE}); drop looks or notes')
    body = bytes(assign) + bytes(SLOT_LEN - 8) + table + b''.join(recs) + notes
    raw = header(n, notes_off, len(notes), file_len) + body
    crc = zlib.crc32(raw[:16] + raw[20:]) & 0xffffffff
    return header(n, notes_off, len(notes), file_len, crc) + body


def _ranges_ok(entry, lo, span):
    for k, b in enumerate(entry):
        v = b - 256 if b >= 128 else b
        if not 0 <= v - lo[k] <= span[k]:
            return k, v
    return None


def check_file(data):
    """-> list of problems (empty = a v2 loader following docs/FILM_LIBRARY.md §4 would accept it)."""
    p = []
    if len(data) < LOOKS_OFF or len(data) > MAX_FILE:
        return [f'size {len(data)} outside {LOOKS_OFF}..{MAX_FILE}']
    if data[:4] != MAGIC:
        return [f'magic {data[:4]!r}']
    ver, hl, build, plen = struct.unpack_from('<HHII', data, 4)
    if ver != VERSION:
        return [f'version {ver} (this tool reads v2; a v1 file is checked by tools/ep7_bundles_bin.py)']
    if hl != HDR_LEN or build != FW_BUILD or plen != len(data) - HDR_LEN:
        p.append(f'header: len {hl}, build {build}, payload {plen} vs file {len(data)}')
    crc = zlib.crc32(data[:16] + data[20:]) & 0xffffffff
    if struct.unpack_from('<I', data, 16)[0] != crc:
        p.append(f'crc32 {struct.unpack_from("<I", data, 16)[0]:#010x} != {crc:#010x}')
    if data[20:24] != SHA_PREFIX:
        p.append(f'main SHA prefix {data[20:24].hex()} != {SHA_PREFIX.hex()}')
    n, ll, so, to, lo_, no, nl, sb, lcrc = struct.unpack_from('<HHHHHHHHI', data, 24)
    if (ll, so, to, lo_, sb) != (LOOK_LEN, SLOT_OFF, TABLE_OFF, LOOKS_OFF, 64):
        p.append(f'layout words {(ll, so, to, lo_, sb)}')
    if lcrc != layout_crc():
        p.append(f'layout.json ABI crc {lcrc:#010x} != {layout_crc():#010x} (file built for another ABI)')
    if any(data[44:HDR_LEN]) or any(data[SLOT_OFF + 8:SLOT_OFF + SLOT_LEN]):
        p.append('reserved header/slot bytes not zero')
    if not 1 <= n <= MAX_LOOKS:
        return p + [f'n_looks {n}']
    end = LOOKS_OFF + n * LOOK_LEN
    if (no, nl) == (0, 0):
        if len(data) != end:
            p.append(f'file length {len(data)} != {end} (no notes)')
    elif no != end or end + nl != len(data):
        p.append(f'notes block {no}+{nl} does not end the file at {len(data)}')
    if p:
        return p
    lo, span, who = SB.range_table(SB.layout())
    recs = [data[LOOKS_OFF + i * LOOK_LEN:LOOKS_OFF + (i + 1) * LOOK_LEN] for i in range(n)]
    for i, r in enumerate(recs):
        bad = _ranges_ok(r[:64], lo, span)
        if bad:
            p.append(f'look {i} byte {bad[0]} ({who[bad[0]]}) = {bad[1]} out of range')
        nm = r[NAME_OFF:NAME_OFF + NAME_LEN]
        txt = nm.split(b'\0')[0]
        if not NAME_RE.match(txt.decode('latin1')) or any(nm[len(txt):]) or len(txt) > NAME_MAX:
            p.append(f'look {i} name {nm!r}: 1-12 printable ASCII, no "@", NUL padded')
        if r[CLASS_OFF] not in (CLASS_COLOUR, CLASS_MONO) or r[MASK_OFF] not in (1, 2, 3) or any(r[82:]):
            p.append(f'look {i}: class/mask/reserved bytes')
        elif r[CLASS_OFF] == CLASS_MONO and r[MASK_OFF] != MASK_MONO_SLOT:
            p.append(f'look {i}: a mono look may only go in MONO slots')
    assign = data[SLOT_OFF:SLOT_OFF + 8]
    for s, a in zip(SLOTS, assign):
        if a != EMPTY and a >= n:
            p.append(f'{s}: look index {a} >= {n}')
    if p:
        return p
    table = data[TABLE_OFF:TABLE_OFF + TABLE_LEN]
    if not SB.table_ok(table, lo, span):
        p.append('resolved table fails the v1 per-byte ranges')
    for k, (s, a) in enumerate(zip(SLOTS, assign)):
        try:
            want = bytes(64) if a == EMPTY else place(recs[a], s)
        except ValueError as e:
            p.append(str(e))
            continue
        if table[64 * k:64 * k + 64] != want:
            p.append(f'{s}: resolved table entry != P(look {a}, {s})')
    if nl:
        q, seen = no, set()
        while q < no + nl:
            if q + 2 > no + nl:
                p.append('notes block truncated')
                break
            i, ln = data[q], data[q + 1]
            if i >= n or i in seen or q + 2 + ln > no + nl:
                p.append(f'notes entry at {q} invalid')
                break
            try:
                data[q + 2:q + 2 + ln].decode('utf-8')
            except UnicodeDecodeError:
                p.append(f'notes for look {i} not UTF-8')
            seen.add(i)
            q += 2 + ln
    return p


def describe(data):
    n = struct.unpack_from('<H', data, 24)[0]
    no, nl = struct.unpack_from('<HH', data, 34)
    notes = {}
    q = no
    while nl and q < no + nl:
        i, ln = data[q], data[q + 1]
        notes[i] = data[q + 2:q + 2 + ln].decode()
        q += 2 + ln
    lines = [f'{len(data)} B, v{VERSION}, {n} looks, crc32 {struct.unpack_from("<I", data, 16)[0]:#010x}']
    for i in range(n):
        r = data[LOOKS_OFF + i * LOOK_LEN:LOOKS_OFF + (i + 1) * LOOK_LEN]
        nm = r[NAME_OFF:NAME_OFF + NAME_LEN].split(b'\0')[0].decode()
        cls = 'mono' if r[CLASS_OFF] else 'colour'
        sl = ('C' if r[MASK_OFF] & 1 else '-') + ('M' if r[MASK_OFF] & 2 else '-')
        lines.append(f'  [{i:2}] {nm:<12} {cls:<6} {sl}  {notes.get(i, "")[:60]}')
    lines.append('  slot assignment:')
    for s, a in zip(SLOTS, data[SLOT_OFF:SLOT_OFF + 8]):
        nm = '(empty: stock)' if a == EMPTY else \
            data[LOOKS_OFF + a * LOOK_LEN + NAME_OFF:LOOKS_OFF + a * LOOK_LEN + NAME_OFF + NAME_LEN].split(b'\0')[0].decode()
        lines.append(f'    {s:<6} -> {nm}')
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('library', nargs='?', type=Path, help='user library JSON')
    ap.add_argument('--out', type=Path, help='card-root folder to write EP7MOD/LIBRARY.BIN into')
    ap.add_argument('--check', type=Path, help='validate an existing LIBRARY.BIN')
    ap.add_argument('--dry-run', action='store_true', help='compile and check, write nothing')
    ap.add_argument('--list', action='store_true', help='print looks and slot assignment')
    a = ap.parse_args()
    if a.check:
        data = a.check.read_bytes()
        probs = check_file(data)
        print('OK: a v2 loader would accept this file' if not probs else 'REJECT: ' + '; '.join(probs))
        if not probs and a.list:
            print(describe(data))
        sys.exit(1 if probs else 0)
    if not a.library or not (a.out or a.dry_run):
        ap.error('need LIBRARY.json and --out DIR (or --dry-run), or --check FILE')
    try:
        data, info = compile_library(json.loads(a.library.read_text()))
    except (ValueError, json.JSONDecodeError) as e:
        sys.exit(f'error: {e}')
    if a.list or a.dry_run:
        print(describe(data))
    if a.dry_run:
        return
    dst = a.out / 'EP7MOD' / 'LIBRARY.BIN'
    if dst.name.upper()[:4] in ('E142', 'G142', 'H142', 'W142', 'S142') or 'DCOLYMP' in str(dst).upper():
        sys.exit('refusing an SD-update-like name or folder')
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    print(f'wrote {dst} ({len(data)} B, {len(info["looks"])} looks, crc32 {struct.unpack_from("<I", data, 16)[0]:#010x})')


if __name__ == '__main__':
    main()
