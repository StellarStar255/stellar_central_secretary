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
               'Categories=Office;Utility;\nStartupNotify=true\n')
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        portable = stage/'Stellar-Secretary'
        shutil.copytree(source, portable, symlinks=True)
        start = portable/'start.sh'
        start.write_text('#!/bin/sh\nAPP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\nexec "$APP_DIR/Stellar Secretary" "$@"\n')
        start.chmod(0o755)
        (portable/'README.txt').write_text(
            f'Stellar Secretary {__version__} — Linux x64\n\n'
            'Requires glibc 2.35+ (Ubuntu 22.04+, Debian 12+), a graphical session and a default browser.\n'
            'Run ./start.sh to open the local browser interface at http://127.0.0.1:8768.\n'
            'For a headless server: ./start.sh --no-browser --port 8768\n'
            'To stop: close the terminal with Ctrl+C (when launched there), or use the authenticated local shutdown API.\n'
            'Data: ${XDG_DATA_HOME:-~/.local/share}/stellar-secretary. Updates and uninstall retain it.\n'
            'Linux uses browser mode; native desktop/tray switching and automatic installer updates are not supported.\n'
            'Install Google Chrome separately for browser capture, and a model CLI or configure a compatible API for AI.\n'
            'Upgrade by replacing the application directory or installing a newer .deb.\n', encoding='utf-8')
        with tarfile.open(dist/f'Stellar-Secretary-{__version__}-linux-x64.tar.gz', 'w:gz') as archive:
            archive.add(portable, arcname=portable.name)
        package = stage/'deb'
        app = package/'opt/stellar-secretary'
        app.parent.mkdir(parents=True)
        shutil.copytree(source, app, symlinks=True)
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
            'Depends: libc6 (>= 2.35), libstdc++6, zlib1g\nRecommends: xdg-utils\n'
            'Homepage: https://github.com/StellarStar255/stellar_central_secretary\n'
            'Description: Local knowledge library and AI summaries\n'
            ' Archive webpages, AI conversations, documents, images and notes.\n'
            ' Includes Python and opens the interface in your default browser.\n')
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(package),
                        str(dist/f'Stellar-Secretary-{__version__}-linux-x64.deb')], check=True)


if __name__ == '__main__':
    main()
