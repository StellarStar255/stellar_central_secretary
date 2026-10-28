#!/usr/bin/env bash
# Build Linux x64 installers on Ubuntu 22.04 (glibc 2.35 or newer).
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
VERSION="$($PYTHON -c 'from secretary import __version__; print(__version__)')"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || { echo 'Requires Linux x86_64'; exit 1; }
"$PYTHON" -m PyInstaller packaging/stellar-secretary.spec --noconfirm --clean
"$PYTHON" packaging/smoke.py
"$PYTHON" packaging/package_linux.py
