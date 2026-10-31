#!/usr/bin/env bash
# Decode stock E-P7 1.1 into analysis/ep7_1100 (offline; verifies input + every component hash).
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf analysis/ep7_1100
python3 -I external/oly_fw_analysis/tools/oly_container.py stock_firmware/OLY_E_142_1100_0000_0000.BIN \
  --expect-sha256 9d1610124ad98f6edae4540182205f06c9c703d9033ef0c4f19847193f95eaeb \
  --code-base 0x60020020 --out analysis/ep7_1100 >/dev/null
cd analysis/ep7_1100 && sha256sum -c ../../docs/ep7_1100_components.sha256
