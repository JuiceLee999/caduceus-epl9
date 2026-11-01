#!/usr/bin/env python3
"""Caduceus user-side builder for the Olympus E-P7 firmware 1.1 patches.

We do not redistribute OM Digital Solutions firmware. This script downloads the
stock 1.1 update from OM's own server (or uses a copy you already have), checks
its SHA-256, applies a release's edit list (releases/<ver>/edits.json) and
writes the update files for your SD card. Every output hash must match the
release's SHA256SUMS exactly, otherwise nothing is written.

  python3 caduceus.py build --release v0.15 [--out DIR] [--stock FILE]
  python3 caduceus.py verify DIR
  python3 caduceus.py list

Python 3.10+, standard library only. Never talks to a camera.

Container format (scrambled "OE" blocks: byte inversion + 16-byte lane
permutation, additive 32-bit checksum) as documented publicly by Altsoph and
mx3 in CHDK forum thread 2471
(https://chdk.setepontos.com/d/2471-olympus-emjustylus-series-fw-analysis).
This is a small independent implementation; it was cross-checked against
fishcu's oly_container.py (https://github.com/fishcu/oly_fw_analysis), which the
Caduceus project used during development.
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RELEASES = ROOT / 'releases'

STOCK_NAME = 'OLY_E_142_1100_0000_0000.BIN'
STOCK_SHA = '9d1610124ad98f6edae4540182205f06c9c703d9033ef0c4f19847193f95eaeb'
STOCK_SIZE = 111017984
CATALOG = 'https://fw01.om-digitalsolutions.net/ww_inform/fcache.do'
MAIN_BASE = 0x60020020          # CPU address of main-component payload byte 0
CARD_NAME = 'E1429999.BIN'      # E-P7 SD-update file name
# release SHA256SUMS name -> output path (relative to the output directory)
OUTPUTS = {
    'patched.pkg.bin': f'DCOLYMP/{CARD_NAME}',
    'restore-stock.pkg.bin': f'restore/{CARD_NAME}',
}


class Refuse(Exception):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- container
LANES = (1, 3, 0, 2, 6, 4, 7, 5, 11, 10, 9, 8, 13, 14, 12, 15)
INV = bytes(i ^ 0xFF for i in range(256))


def decode(data):
    out = bytearray(len(data))
    for o, i in enumerate(LANES):
        out[o::16] = data[i::16].translate(INV)
    return bytes(out)


def encode(data):
    out = bytearray(len(data))
    for i, o in enumerate(LANES):
        out[o::16] = data[i::16].translate(INV)
    return bytes(out)


def sum32(data):
    w = array('I')
    if w.itemsize != 4:
        return sum(x for (x,) in struct.iter_unpack('<I', data)) & 0xFFFFFFFF
    w.frombytes(data)
    if sys.byteorder != 'little':
        w.byteswap()
    return sum(w) & 0xFFFFFFFF


def parse(data):
    """-> list of (offset, header, payload, trailer); payload decoded."""
    blocks, off, model = [], 0, None
    while off < len(data):
        if len(data) - off < 64:
            raise Refuse(f'container: truncated block at {off:#x}')
        hdr = data[off:off + 32]
        if hdr[:2] != b'OE' or struct.unpack_from('<I', hdr, 20)[0] == 0:
            raise Refuse(f'container: unsupported block at {off:#x}')
        model = model or hdr[2:4]
        size = struct.unpack_from('<I', hdr, 12)[0]
        end = off + size + 64
        if hdr[2:4] != model or not size or size % 16 or end > len(data):
            raise Refuse(f'container: bad block header at {off:#x}')
        trl = data[end - 32:end]
        if hdr[:28] != trl[:28] or hdr[28:] != b'\0' * 4:
            raise Refuse(f'container: header/trailer mismatch at {off:#x}')
        pay = decode(data[off + 32:end - 32])
        if (sum32(hdr) + sum32(pay) + sum32(trl)) & 0xFFFFFFFF:
            raise Refuse(f'container: checksum mismatch at {off:#x}')
        blocks.append((off, hdr, pay, trl))
        off = end
    return blocks


def kind(hdr):
    return struct.unpack_from('<H', hdr, 20)[0]


def reseal(hdr, pay, trl):
    t = bytearray(trl)
    t[28:] = b'\0' * 4
    struct.pack_into('<I', t, 28, -(sum32(hdr) + sum32(pay) + sum32(t)) & 0xFFFFFFFF)
    return bytes(t)


# ---------------------------------------------------------------- build
def apply_edits(spec, stock):
    """Same rules and checks as tools/build_package.py. -> (patched, restore)."""
    blocks = parse(stock)
    by_kind = {kind(h): (o, h, p, t) for o, h, p, t in blocks}
    kinds = [int(k, 16) for k in spec['components']]
    if (0x100 in kinds and kinds[0] != 0x100) or len(set(kinds)) != len(kinds) \
            or any(k not in by_kind for k in kinds):
        raise Refuse('edits.json: bad component list')
    pays = {k: bytearray(by_kind[k][2]) for k in kinds}
    spans, total = {}, 0
    for e in spec['edits']:
        k = int(e['kind'], 16)
        a = e['addr']
        if k not in pays:
            raise Refuse(f'edits.json: edit {a} targets a component not in the package')
        if a.startswith('off:'):
            off = int(a[4:], 16)
        elif k == 0x100:
            off = int(a, 16) - MAIN_BASE
        else:
            raise Refuse(f'edits.json: edit {a}: CPU address on a non-main component')
        exp, new = bytes.fromhex(e['expect']), bytes.fromhex(e['new'])
        if len(exp) != len(new) or not new or not 0 <= off <= len(pays[k]) - len(new):
            raise Refuse(f'edits.json: edit {a}: bad length or range')
        if any(off < y and x < off + len(new) for x, y in spans.get(k, [])):
            raise Refuse(f'edits.json: edit {a}: overlaps another edit')
        if by_kind[k][2][off:off + len(exp)] != exp:
            raise Refuse(f'edits.json: edit {a}: stock bytes differ from expected')
        spans.setdefault(k, []).append((off, off + len(new)))
        pays[k][off:off + len(new)] = new
        total += sum(x != y for x, y in zip(exp, new))
    parts = []
    for k in kinds:
        _, h, p, t = by_kind[k]
        np_ = bytes(pays[k])
        parts.append(h + encode(np_) + (reseal(h, np_, t) if np_ != p else t))
    patched = b''.join(parts)
    restore = b''.join(stock[o:o + 64 + len(p)] for o, h, p, t in (by_kind[k] for k in kinds))
    # re-verify outputs from scratch
    rp, rr = parse(patched), parse(restore)
    if [kind(b[1]) for b in rp] != kinds or [kind(b[1]) for b in rr] != kinds:
        raise Refuse('internal: output component list wrong')
    changed = 0
    for (_, h, p, t), (_, sh, sp, st), (_, rh, rpay, rt) in zip(rp, (by_kind[k] for k in kinds), rr):
        if h != sh or t[:28] != st[:28] or rh != sh or rpay != sp:
            raise Refuse('internal: output metadata/restore differs from stock')
        changed += sum(x != y for x, y in zip(p, sp))
    if changed != total:
        raise Refuse(f'internal: changed bytes {changed} != edited bytes {total}')
    return patched, restore


# ---------------------------------------------------------------- download
def fetch_stock():
    t = time.strftime('%Y%m%d%H%M%S', time.gmtime())
    req = ("<?xml version='1.0' encoding='utf-8'?><firmware_demand><revision>0001</revision>"
           "<mac_address>00-00-00-00-00-00</mac_address><time>" + t + "</time><language>ENU</language>"
           "<application>FWUT</application><type>0000</type><version>00005000</version><os>WIN</os>"
           "<country_code>0001</country_code><hardwares><firmup_mode>0</firmup_mode><hardware_info>"
           "<hard_code>OLYE142000000000</hard_code><firmware_version>00001000</firmware_version>"
           "<serial_no>000000000</serial_no></hardware_info></hardwares></firmware_demand>")
    hdrs = {'User-Agent': 'Olympus', 'Content-Type': 'text/xml; Charset=UTF-8'}
    print('Asking OM Digital Solutions for the E-P7 1.1 firmware ...')
    try:
        with urllib.request.urlopen(urllib.request.Request(CATALOG, req.encode(), hdrs), timeout=60) as r:
            info = ET.fromstring(r.read()).find('.//firmware_info')
        if info is None or info.findtext('model_id') != '1420' or info.findtext('file_name') != STOCK_NAME:
            raise Refuse('OM server did not offer E-P7 firmware 1.1 (it may have moved). '
                         f'Download {STOCK_NAME} yourself and use --stock FILE.')
        url = info.findtext('url')
        print(f'Downloading {STOCK_NAME} from {url.split("/")[2]}')
        buf = bytearray()
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Olympus'}),
                                    timeout=120) as r:
            while chunk := r.read(1 << 20):
                buf += chunk
                print(f'\r  {len(buf) >> 20} / {STOCK_SIZE >> 20} MiB', end='', flush=True)
        print()
        return bytes(buf)
    except (OSError, ET.ParseError) as e:
        raise Refuse(f'download failed: {e}\nIf this keeps happening, download {STOCK_NAME} '
                     'another way and pass --stock FILE (see docs/INSTALL.md).')


# ---------------------------------------------------------------- releases
def read_sums(path):
    sums = {}
    for line in path.read_text().splitlines():
        if line.strip():
            h, name = line.split(maxsplit=1)
            sums[name.lstrip('*')] = h.lower()
    return sums


def releases():
    if not RELEASES.is_dir():
        return []
    return sorted(d.name for d in RELEASES.iterdir()
                  if (d / 'edits.json').is_file() and (d / 'SHA256SUMS').is_file()
                  and 'patched.pkg.bin' in read_sums(d / 'SHA256SUMS'))


def load_release(name):
    d = RELEASES / name
    if name not in releases():
        avail = ', '.join(r for r in releases() if r.startswith('v')) or 'none'
        raise Refuse(f'unknown release {name!r}. Available: {avail}')
    sums = read_sums(d / 'SHA256SUMS')
    spec_bytes = (d / 'edits.json').read_bytes()
    if 'edits.json' in sums and sha(spec_bytes) != sums['edits.json']:
        raise Refuse(f'releases/{name}/edits.json does not match releases/{name}/SHA256SUMS '
                     '(repository out of sync; update your copy).')
    # card files ship in the repository (our own data, not OM firmware)
    card = {}
    for n, h in sums.items():
        if n.startswith('card/'):
            f = d / n
            if not f.is_file():
                raise Refuse(f'missing releases/{name}/{n}')
            b = f.read_bytes()
            if sha(b) != h:
                raise Refuse(f'releases/{name}/{n} does not match SHA256SUMS')
            card[n[len('card/'):]] = b
    return json.loads(spec_bytes), sums, card


def cmd_build(a):
    out = Path(a.out)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise Refuse(f'{out} already exists and is not empty; choose another --out or remove it.')
    spec, sums, card = load_release(a.release)
    if a.stock:
        p = Path(a.stock)
        if not p.is_file():
            raise Refuse(f'--stock: no such file {p}')
        stock = p.read_bytes()
    else:
        stock = fetch_stock()
    if sha(stock) != STOCK_SHA:
        raise Refuse(f'stock firmware SHA-256 is {sha(stock)}\nexpected {STOCK_SHA}\n'
                     f'This is not the official E-P7 1.1 file {STOCK_NAME} ({STOCK_SIZE} bytes). Nothing written.')
    print(f'Stock firmware OK. Applying {len(spec["edits"])} edits from releases/{a.release}/edits.json ...')
    patched, restore = apply_edits(spec, stock)
    files = {OUTPUTS['patched.pkg.bin']: patched, OUTPUTS['restore-stock.pkg.bin']: restore}
    files.update(card)
    for rel_name, data in (('patched.pkg.bin', patched), ('restore-stock.pkg.bin', restore)):
        if sha(data) != sums[rel_name]:
            raise Refuse(f'{rel_name}: built hash {sha(data)} != release {sums[rel_name]}. Nothing written.')
    # write into a temp dir next to the target, then move into place
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix='.caduceus-', dir=out.parent))
    try:
        for rel, data in files.items():
            f = tmp / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        (tmp / 'SHA256SUMS').write_text(''.join(f'{sha(d)}  {r}\n' for r, d in sorted(files.items())))
        (tmp / 'RELEASE').write_text(a.release + '\n')
        if out.exists():
            out.rmdir()
        os.replace(tmp, out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    print(f'\nCaduceus {a.release} written to {out}:')
    for r in sorted(files):
        print(f'  {r}')
    print('  SHA256SUMS\nAll hashes match the release. Next: docs/INSTALL.md (copy DCOLYMP/ and EP7MOD/ to the card;'
          ' keep restore/ on your computer).')
    return 0


def cmd_verify(a):
    d = Path(a.dir)
    man = d / 'SHA256SUMS'
    if not man.is_file():
        raise Refuse(f'{man} not found; is {d} a caduceus build directory?')
    sums, bad = read_sums(man), 0
    for rel, h in sorted(sums.items()):
        f = d / rel
        ok = f.is_file() and sha(f.read_bytes()) == h
        bad += not ok
        print(f'  {"OK  " if ok else "FAIL"}  {rel}')
    rel_name = (d / 'RELEASE').read_text().strip() if (d / 'RELEASE').is_file() else None
    if rel_name and rel_name in releases():
        rs = read_sums(RELEASES / rel_name / 'SHA256SUMS')
        want = {OUTPUTS[n]: h for n, h in rs.items() if n in OUTPUTS}
        want.update({n[len('card/'):]: h for n, h in rs.items() if n.startswith('card/')})
        if want != sums:
            bad += 1
            print(f'  FAIL  file list/hashes differ from releases/{rel_name}/SHA256SUMS')
        else:
            print(f'  OK    matches releases/{rel_name}/SHA256SUMS')
    else:
        print(f'  note: release {rel_name!r} not found here; checked the local manifest only')
    if bad:
        raise Refuse(f'{bad} problem(s). Do not flash these files; rebuild them.')
    print('All good.')
    return 0


def cmd_list(a):
    for r in releases():
        if r.startswith('v'):
            print(r)
    return 0


def main(argv=None):
    if sys.version_info < (3, 10):
        sys.exit('Python 3.10 or newer is required.')
    ap = argparse.ArgumentParser(prog='caduceus.py', description='Build Caduceus E-P7 firmware files locally.')
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build', help='download stock 1.1, apply a release, write card files')
    b.add_argument('--release', required=True, help='e.g. v0.15 (see: caduceus.py list)')
    b.add_argument('--out', default='out', help='new or empty output directory (default: out)')
    b.add_argument('--stock', help=f'use an already downloaded {STOCK_NAME} instead of downloading')
    b.set_defaults(fn=cmd_build)
    v = sub.add_parser('verify', help='re-check a build directory')
    v.add_argument('dir')
    v.set_defaults(fn=cmd_verify)
    sub.add_parser('list', help='list available releases').set_defaults(fn=cmd_list)
    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except Refuse as e:
        sys.exit(f'refused: {e}')
    except KeyboardInterrupt:
        sys.exit('interrupted; nothing written.')


if __name__ == '__main__':
    sys.exit(main())
