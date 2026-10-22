#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-.venv/bin/python}"
VERSION="$($PYTHON -c 'from secretary import __version__; print(__version__)')"
ARCH="$(uname -m)"
if [[ "$ARCH" == x86_64 ]]; then ARCH=x64; fi
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$PWD/build/pyinstaller-cache}"
"$PYTHON" -m PyInstaller packaging/stellar-secretary.spec --noconfirm
"$PYTHON" packaging/smoke.py
bash packaging/macos_sign_notarize.sh "dist/Stellar Secretary.app" "dist/Stellar-Secretary-$VERSION-macos-$ARCH.dmg"
"$PYTHON" -c 'import hashlib,pathlib; p=next(pathlib.Path("dist").glob("Stellar-Secretary-"+__import__("secretary").__version__+"-macos-*.dmg")); (p.parent/"SHA256SUMS.txt").write_text(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name+"\n")'
