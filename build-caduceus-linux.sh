#!/bin/sh
# Run from a file manager ("Run in Terminal") or: ./build-caduceus-linux.sh
cd "$(dirname "$0")" || exit 1
export CADUCEUS_LAUNCHER=1
echo "Caduceus - E-P7 firmware builder"; echo
if command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; sys.exit(sys.version_info < (3,10))' 2>/dev/null; then
  python3 -u caduceus.py
else
  echo "Python 3.10 or newer is needed: install python3 with your package manager (e.g. sudo apt install python3)."
fi
echo; printf "Press Enter to close..."; read -r _
