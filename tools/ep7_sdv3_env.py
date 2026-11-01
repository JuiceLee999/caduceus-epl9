"""SD look loader v3 emulator environment for the bundle-table reader verifiers (offline; emulator only).

Readers built with --sd-v3 (patches/bundles, wb, grain, bloom, mono_colour) read the u16 loader state at
0x622cbcc2 through the accessor tbl_idx / tbl_off (patches/sd_bundles_v3, section-2 tail 0x6055e7b0). The
reader verifiers' fixtures do not map that RAM, so they wrap penf_emulator.execute with wrap():

  default    a read-only 8-byte region at 0x622cbcc0 holding 0 (= loader not run; a write to it faults) is added
             to every run that does not map that address already. Readers then use the flashed table, i.e.
             the verifier checks exactly what it checked before. Runs of builds without --sd-v3 never read it.
  loaded     (set by tools/ep7_verify_sd_bundles_v3.py via set_loaded()) every run is rewritten as if the v3
             loader had loaded the table: the 512 bytes at 0x60210900 in whatever region holds them are moved
             into a pool buffer (file header magic + table at +32, the layout the loader keeps), the flashed
             copy is overwritten with a POISON table (valid ranges, every slot enabled with values that differ
             from any real/fixture table), and 0x622cbcc2 holds the handle. A reader that still read the
             flashed address would see the poison and fail the verifier's own expectations.
Nothing here changes what a verifier expects; it only supplies RAM the new code reads.
"""
import struct

from penf_emulator import Region

STATE_LO = 0x622cbcc0            # event-manager +172 (HLS tid, u16) / +174 (loader state, u16) / +176
STATE = 0x622cbcc2
TABLE, TABLE_LEN = 0x60210900, 512
POOL, POOL_END = 0xa1f8d800, 0xa1f98540
HDR_LEN, MAGIC = 32, b'EP7B'
LOADED_BUF = POOL + 0x2400       # where the loaded-mode buffer sits (4-aligned, inside the pool)

_mode = {'loaded': False, 'poison': None, 'buf': LOADED_BUF, 'stats': None}


def poison_table():
    """A valid bundle table (every byte inside the loader's per-field ranges, patches/sd_bundles RANGES) that
    enables everything with extreme values: H/L +7/-7 alternating, grain 3, WB override +7/-7, bloom 5,
    vignette 5, flags 3, MONO colour 1, sat -5."""
    s = bytearray(64)
    for i in range(12):
        s[i] = 7 if i % 2 else 0xf9          # hue
        s[12 + i] = 0xf9 if i % 2 else 7     # light
    s[24] = 3                                # grain
    s[25], s[26], s[27] = 1, 7, 0xf9         # wb_flags, wb_ab, wb_gm
    s[28], s[29] = 1, 5                      # effect_id bloom, strength
    s[30] = 5                                # vignette
    s[31] = 3                                # flags (render colour + H/L)
    s[32] = 1                                # colour
    for i in range(12):
        s[33 + i] = 0xfb                     # sat -5
    return bytes(s) * 8


def set_loaded(on=True, buf=LOADED_BUF):
    _mode.update(loaded=on, poison=poison_table(), buf=buf, stats={'runs': 0, 'relocated': 0})


def stats():
    return dict(_mode['stats'] or {})


def handle(buf):
    return buf - POOL + 1


def _overlaps(r, lo, hi):
    return r.address < hi and lo < r.address + len(r.data)


def augment(regions):
    regions = list(regions)
    state = bytes(8)
    if _mode['loaded']:
        _mode['stats']['runs'] += 1
        table, out = None, []
        for r in regions:
            if _overlaps(r, TABLE, TABLE + TABLE_LEN):
                if r.address > TABLE or r.address + len(r.data) < TABLE + TABLE_LEN:
                    raise ValueError(f'loaded mode: region {r.name} holds only part of the table')
                o = TABLE - r.address
                table = r.data[o:o + TABLE_LEN]
                data = r.data[:o] + _mode['poison'] + r.data[o + TABLE_LEN:]
                r = Region(r.name, r.address, data, r.permissions, r.capture, r.alias_of)
            out.append(r)
        regions = out
        if table is not None:
            buf = _mode['buf']
            if any(_overlaps(r, buf, buf + HDR_LEN + TABLE_LEN) for r in regions):
                raise ValueError('loaded mode: pool buffer address already mapped')
            regions.append(Region('sdv3_pool', buf, MAGIC + bytes(HDR_LEN - 4) + bytes(table), 'r'))
            state = struct.pack('<HHI', 0, handle(buf), 0)
            _mode['stats']['relocated'] += 1
    if not any(_overlaps(r, STATE_LO, STATE_LO + 8) for r in regions):
        regions.append(Region('sdv3_state', STATE_LO, state, 'r'))
    return regions


def wrap(execute):
    if getattr(execute, '_sdv3', False):
        return execute

    def run(regions, registers, stop_pc, **kw):
        return execute(augment(regions), registers, stop_pc, **kw)
    run._sdv3 = True
    run.__wrapped__ = execute
    return run
