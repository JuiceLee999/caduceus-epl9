#!/usr/bin/env bash
# Disassemble E-P7 main by CPU address: tools/dis.sh 0x603b0068 0x603b0250
set -euo pipefail
cd "$(dirname "$0")/.."
OBJDUMP=${OBJDUMP:-$HOME/ep7fw-toolchains/mn10300/bin/mn10300-elf-objdump}
"$OBJDUMP" -b binary -m am33-2 -D --adjust-vma=0x60020020 \
  --start-address="$1" --stop-address="$2" analysis/ep7_1100/00_0100_406a0020.decoded.bin | tail -n +8
