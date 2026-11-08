"""Package the tested frozen Linux application without needing root access."""
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from secretary import __version__


def main():
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        raise SystemExit('Build on Linux x86_64')
    dist = ROOT/'dist'
    source = dist/'Stellar Secretary'
    if not (source/'Stellar Secretary').is_file():
        raise SystemExit('Build the frozen application first')
    desktop = ('[Desktop Entry]\nType=Application\nName=Stellar Secretary\n'
               'Comment=Local knowledge library and AI summaries\n'
               'Exec=stellar-secretary\nIcon=stellar-secretary\nTerminal=false\n'
               'Categories=Office;Utility;\nStartupNotify=true\nStartupWMClass=stellar-secretary\n')
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        portable = stage/'Stellar-Secretary'
        shutil.copytree(source, portable, symlinks=True)
        (portable/'.stellar-install-kind').write_text('portable\n')
        start = portable/'start.sh'
        start.write_text('#!/bin/sh\nAPP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\nexec "$APP_DIR/Stellar Secretary" "$@"\n')
        start.chmod(0o755)
        (portable/'README.txt').write_text(
            f'Stellar Secretary {__version__} — Linux x64\n\n'
            'Requires glibc 2.35+ (Ubuntu 22.04+, Debian 12+) and a graphical session.\n'
            'Run ./start.sh for the desktop window and tray. Settings can switch to your default browser.\n'
            'For a headless server: ./start.sh --no-browser --port 8768\n'
            'To stop: close the terminal with Ctrl+C (when launched there), or use the authenticated local shutdown API.\n'
            'Data: ${XDG_DATA_HOME:-~/.local/share}/stellar-secretary. Updates and uninstall retain it.\n'
            'Closing the window minimizes it to the dock. The tray and application menu can reopen settings or check updates.\n'
            'GNOME needs AppIndicator support to display tray icons; the dock remains available without a tray.\n'
            'Portable automatic updates require a writable program directory and system Python 3.\n'
            'Install Google Chrome separately for browser capture, and a model CLI or configure a compatible API for AI.\n'
            'Upgrade by replacing the application directory or installing a newer .deb.\n', encoding='utf-8')
        with tarfile.open(dist/f'Stellar-Secretary-{__version__}-linux-x64.tar.gz', 'w:gz') as archive:
            archive.add(portable, arcname=portable.name)
        package = stage/'deb'
        app = package/'opt/stellar-secretary'
        app.parent.mkdir(parents=True)
        shutil.copytree(source, app, symlinks=True)
        (app/'.stellar-install-kind').write_text('deb\n')
        (package/'usr/bin').mkdir(parents=True)
        launcher = package/'usr/bin/stellar-secretary'
        launcher.write_text('#!/bin/sh\nexec "/opt/stellar-secretary/Stellar Secretary" "$@"\n')
        launcher.chmod(0o755)
        (package/'usr/share/applications').mkdir(parents=True)
        (package/'usr/share/applications/stellar-secretary.desktop').write_text(desktop)
        icons = package/'usr/share/icons/hicolor/256x256/apps'
        icons.mkdir(parents=True)
        shutil.copyfile(ROOT/'secretary/static/icons/app.png', icons/'stellar-secretary.png')
        doc = package/'usr/share/doc/stellar-secretary'
        doc.mkdir(parents=True)
        shutil.copyfile(ROOT/'LICENSE', doc/'copyright')
        shutil.copyfile(portable/'README.txt', doc/'README')
        control = package/'DEBIAN'
        control.mkdir()
        size = sum(p.stat().st_size for p in package.rglob('*') if p.is_file())//1024
        (control/'control').write_text(
            f'Package: stellar-secretary\nVersion: {__version__}\nArchitecture: amd64\n'
            'Maintainer: StellarStar255 <17609819+StellarStar255@users.noreply.github.com>\n'
            f'Installed-Size: {size}\nSection: utils\nPriority: optional\n'
            'Depends: libc6 (>= 2.35), libstdc++6, zlib1g, libegl1, libgl1, libopengl0, '
            'libnss3, libnspr4, libgbm1, libdrm2, libwayland-client0, libwayland-cursor0, libwayland-egl1, '
            'libasound2t64 | libasound2, libpulse0, libpulse-mainloop-glib0, libdbus-1-3, libfontconfig1, '
            'libxkbcommon0, libxkbcommon-x11-0, libx11-xcb1, libxcb-cursor0, libxcb-icccm4, '
            'libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-xinerama0, libxcb-randr0, '
            'libxcb-shape0, libxcb-xfixes0, libxcb-sync1, libxcb-xkb1, libxcomposite1, '
            'libxdamage1, libxrandr2, libxtst6, libxrender1, libxi6, libxext6, libxfixes3, '
            'libxss1, libsm6, libice6, libglib2.0-0t64 | libglib2.0-0, libcups2t64 | libcups2, '
            'xdg-utils, policykit-1, python3\nRecommends: fonts-noto-cjk, tesseract-ocr, tesseract-ocr-eng, tesseract-ocr-chi-sim\nSuggests: gnome-shell-extension-appindicator\n'
            'Homepage: https://github.com/StellarStar255/stellar_central_secretary\n'
            'Description: Local knowledge library and AI summaries\n'
            ' Archive webpages, AI conversations, documents, images and notes.\n'
            ' Includes Python, a desktop window, a system tray and a browser display mode.\n')
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(package),
                        str(dist/f'Stellar-Secretary-{__version__}-linux-x64.deb')], check=True)


if __name__ == '__main__':
    main()
