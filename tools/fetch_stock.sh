#!/usr/bin/env bash
# Fetch stock E-P7 firmware from OM's public update catalog (same request OM Workspace makes,
# with zeroed placeholder MAC/serial). Downloads only; never touches a camera.
set -euo pipefail
cd "$(dirname "$0")/../stock_firmware"
EXPECT=9d1610124ad98f6edae4540182205f06c9c703d9033ef0c4f19847193f95eaeb
F=OLY_E_142_1100_0000_0000.BIN
T=$(date -u +%Y%m%d%H%M%S)
REQ="<?xml version='1.0' encoding='utf-8'?><firmware_demand><revision>0001</revision><mac_address>00-00-00-00-00-00</mac_address><time>$T</time><language>ENU</language><application>FWUT</application><type>0000</type><version>00005000</version><os>WIN</os><country_code>0001</country_code><hardwares><firmup_mode>0</firmup_mode><hardware_info><hard_code>OLYE142000000000</hard_code><firmware_version>00001000</firmware_version><serial_no>000000000</serial_no></hardware_info></hardwares></firmware_demand>"
URL=$(curl -sS -A Olympus -H 'Content-Type: text/xml; Charset=UTF-8' --data-binary "$REQ" \
  https://fw01.om-digitalsolutions.net/ww_inform/fcache.do |
  python3 -I -c "import sys,xml.etree.ElementTree as E;r=E.fromstring(sys.stdin.read());i=r.find('.//firmware_info');assert i.findtext('model_id')=='1420' and i.findtext('file_name')=='$F', 'catalog offers a different file';print(i.findtext('url'))")
curl -sS -A Olympus -o "$F.part" "$URL"
echo "$EXPECT  $F.part" | sha256sum -c - && mv "$F.part" "$F"
