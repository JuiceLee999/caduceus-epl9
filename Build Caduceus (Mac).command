#!/bin/bash
# Double-click in Finder. First time: right-click > Open (macOS asks once for downloaded scripts).
cd "$(dirname "$0")" || exit 1
export CADUCEUS_LAUNCHER=1
echo "Caduceus - E-P7 firmware builder"; echo
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3,10))' 2>/dev/null; then
  python3 -u caduceus.py
else
  echo "Python 3.10 or newer is needed. Opening https://www.python.org/downloads/ ..."
  echo "Install it (then run 'Install Certificates.command' in the Python folder) and double-click this file again."
  open https://www.python.org/downloads/
fi
echo; read -r -p "Press Enter to close..."
