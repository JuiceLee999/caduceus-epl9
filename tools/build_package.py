#!/usr/bin/env python3
"""Build an E-P7 component-selective update package + matching stock restore.

OFFLINE. Never contacts a camera. Output names are deliberately NOT SD-loadable
(`*.pkg.bin`); copying to DCOLYMP/E142xxxx.BIN is a separate, manual,
human-approved step.

Edits file (JSON):
  {"components": ["0x100"],            # kinds to include (main always first)
   "edits": [{"kind": "0x100", "addr": "0x603b0250", "expect": "aabb", "new": "ccdd",
              "why": "..."}]}
  addr is a CPU address for main (base 0x60020020) or "off:0x..." decoded offset.

Checks (all must pass, else nothing is written):
  - stock input SHA-256 exact; container parse + exact round trip
  - every edit's stock bytes match `expect`; no overlapping edits
  - same payload length; metadata (header, trailer[:28]) unchanged
  - output re-parses; every component checksum valid; untouched components
    byte-identical to stock; changed-byte count == sum of edit lengths
  - restore package == exact byte slices of the stock file
"""
import argparse, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'external/oly_fw_analysis/tools'))
import oly_container as oc  # noqa: E402  (fishcu; imported, not copied)

STOCK = ROOT / 'stock_firmware/OLY_E_142_1100_0000_0000.BIN'
STOCK_SHA = '9d1610124ad98f6edae4540182205f06c9c703d9033ef0c4f19847193f95eaeb'
MAIN_BASE = 0x60020020


def sha(b):
    return hashlib.sha256(b).hexdigest()


def resolve(kind, addr):
    if addr.startswith('off:'):
        return int(addr[4:], 16)
    a = int(addr, 16)
    if kind != 0x100:
        raise ValueError('CPU addresses only valid for main (0x100); use off:')
    return a - MAIN_BASE


def build(spec, stock_bytes):
    if sha(stock_bytes) != STOCK_SHA:
        raise ValueError('stock firmware hash mismatch')
    blocks = oc.parse(stock_bytes)
    if oc.reconstruct(blocks) != stock_bytes:
        raise ValueError('stock round trip failed')
    by_kind = {b.kind: b for b in blocks}
    kinds = [int(k, 16) for k in spec['components']]
    if kinds[0] != 0x100 or len(set(kinds)) != len(kinds) or any(k not in by_kind for k in kinds):
        raise ValueError('components must start with 0x100, be unique and exist')
    payloads = {k: bytearray(by_kind[k].payload) for k in kinds}
    spans, total = {}, 0
    for e in spec['edits']:
        k = int(e['kind'], 16)
        if k not in payloads:
            raise ValueError(f'edit for component {e["kind"]} not included')
        off = resolve(k, e['addr'])
        exp, new = bytes.fromhex(e['expect']), bytes.fromhex(e['new'])
        if len(exp) != len(new) or not new:
            raise ValueError(f'edit {e["addr"]}: expect/new length mismatch')
        if not 0 <= off <= len(payloads[k]) - len(new):
            raise ValueError(f'edit {e["addr"]}: out of range')
        for (a, b) in spans.get(k, []):
            if off < b and a < off + len(new):
                raise ValueError(f'edit {e["addr"]}: overlaps another edit')
        if bytes(by_kind[k].payload[off:off + len(exp)]) != exp:
            raise ValueError(f'edit {e["addr"]}: stock bytes differ from expect')
        spans.setdefault(k, []).append((off, off + len(new)))
        payloads[k][off:off + len(new)] = new
        total += sum(x != y for x, y in zip(exp, new))
    out_blocks = []
    for k in kinds:
        b = by_kind[k]
        nb = oc.replace_payload(b, bytes(payloads[k])) if payloads[k] != b.payload else b
        if nb.header != b.header or nb.trailer[:28] != b.trailer[:28]:
            raise ValueError('metadata changed')
        out_blocks.append(nb)
    pkg = b''.join(x.header + oc.encode(x.payload) + x.trailer for x in out_blocks)
    restore = b''.join(stock_bytes[b.offset:b.offset + 64 + len(b.payload)] for b in (by_kind[k] for k in kinds))
    # ---- verification of outputs
    re_pkg, re_rst = oc.parse(pkg), oc.parse(restore)
    if [b.kind for b in re_pkg] != kinds or [b.kind for b in re_rst] != kinds:
        raise ValueError('output component list wrong')
    changed = 0
    for nb, sb in zip(re_pkg, (by_kind[k] for k in kinds)):
        if nb.header != sb.header or nb.trailer[:28] != sb.trailer[:28]:
            raise ValueError('output metadata differs from stock')
        changed += sum(x != y for x, y in zip(nb.payload, sb.payload))
    if changed != total:
        raise ValueError(f'changed bytes {changed} != edited bytes {total}')
    for rb, sb in zip(re_rst, (by_kind[k] for k in kinds)):
        if rb.payload != sb.payload:
            raise ValueError('restore payload differs from stock')
    return pkg, restore, dict(components=[hex(k) for k in kinds], edits=len(spec['edits']),
                              changed_payload_bytes=changed)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('spec', type=Path)
    ap.add_argument('--out', type=Path, required=True, help='new directory')
    a = ap.parse_args()
    if a.out.exists():
        sys.exit('output directory must not exist')
    spec = json.loads(a.spec.read_text())
    pkg, restore, info = build(spec, STOCK.read_bytes())
    a.out.mkdir(parents=True)
    (a.out / 'patched.pkg.bin').write_bytes(pkg)
    (a.out / 'restore-stock.pkg.bin').write_bytes(restore)
    info.update(spec=str(a.spec), spec_sha256=sha(a.spec.read_bytes()), stock_sha256=STOCK_SHA,
                patched_sha256=sha(pkg), restore_sha256=sha(restore), bytes=len(pkg),
                camera_contacted=False,
                note='Not SD-loadable by name. Container validity != bootability.')
    (a.out / 'build.json').write_text(json.dumps(info, indent=2) + '\n')
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    try:
        main()
    except ValueError as e:
        sys.exit(f'error: {e}')
