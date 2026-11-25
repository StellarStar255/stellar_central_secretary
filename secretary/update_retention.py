"""Remove completed update payloads while preserving logs and any requested rollback."""
import logging
import re
import shutil
from pathlib import Path


def version_key(value):
    if re.fullmatch(r'\d+\.\d+\.\d+', value):
        return tuple(map(int, value.split('.')))
    return ()


def _linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def cache_artifacts(data, version, *, keep_backup=None):
    """Only select recognized installer and rollback payloads at or below version."""
    limit = version_key(version)
    updates = Path(data) / 'updates'
    if not limit or _linked(updates) or not updates.is_dir():
        return []
    if keep_backup is not None:
        keep_backup = Path(keep_backup)
    candidates = []
    for folder in updates.iterdir():
        key = version_key(folder.name)
        if not key or key > limit or _linked(folder) or not folder.is_dir():
            continue
        installer = re.compile(r'Stellar-Secretary-' + re.escape(folder.name) +
                               r'-(?:macos-arm64\.dmg|windows-x64-setup\.exe|linux-x64\.(?:deb|tar\.gz))')
        for path in folder.iterdir():
            if _linked(path):
                continue
            if path.is_file() and installer.fullmatch(path.name):
                candidates.append(path)
            elif (path != keep_backup and path.is_dir() and
                  re.fullmatch(r'previous-program-[a-f0-9]{32}(?:\.app)?', path.name)):
                candidates.append(path)
    return candidates


def remove_artifacts(paths):
    removed = []
    for path in paths:
        if _linked(path):
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(path)
        except OSError as error:
            logging.warning('Could not remove old release artifact %s: %s', path, error)
    return removed
