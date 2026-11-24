"""Keep unpublished backup data separate from snapshots and other libraries."""
from contextlib import contextmanager
import hashlib
import os
import re
import stat

from .library_location import lease

PREFIX = '.stellar-backup-work-v1-'
DATABASE = 'archive.sqlite3'
PART = 'snapshot.part'
FILES = (PART, DATABASE, DATABASE+'-journal', DATABASE+'-wal', DATABASE+'-shm')


def _plain(path, predicate):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return predicate(info.st_mode) and not (
        getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _slot(folder, library):
    identity = os.fsencode(os.path.normcase(str(library.resolve())))
    return folder / (PREFIX + hashlib.sha256(identity).hexdigest())


def _clear(slot):
    for name in FILES:
        path = slot / name
        if _plain(path, stat.S_ISREG):
            path.unlink(missing_ok=True)
        elif os.path.lexists(path):
            raise ValueError('备份工作目录包含异常文件。')


def _valid_slot(slot):
    lock = slot / '.stellar-library.lock'
    return _plain(slot, stat.S_ISDIR) and (
        not os.path.lexists(lock) or _plain(lock, stat.S_ISREG)
    )


@contextmanager
def workspace(folder, library):
    slot = _slot(folder, library)
    slot.mkdir(mode=0o700, exist_ok=True)
    if not _valid_slot(slot):
        raise ValueError('备份工作目录不可用。')
    with lease(slot):
        _clear(slot)
        try:
            yield slot
        finally:
            _clear(slot)


def recover(folder, library):
    slot = _slot(folder, library)
    try:
        if _valid_slot(slot):
            with lease(slot):
                _clear(slot)
    except (OSError, ValueError):
        # An active writer or disconnected drive can be retried later.
        return


def temporary_bytes(folder):
    total = 0
    try:
        entries = list(folder.iterdir())
    except OSError:
        return 0
    for path in entries:
        try:
            if re.fullmatch(r'[0-9a-f]{32}\.part', path.name):
                candidates = [path]
            elif re.fullmatch(PREFIX+r'[0-9a-f]{64}', path.name) and _plain(path, stat.S_ISDIR):
                candidates = [path / name for name in FILES]
            elif re.fullmatch(r'tmp[a-z0-9_]{8}', path.name) and _plain(path, stat.S_ISDIR):
                candidates = [path / name for name in FILES if name != PART]
            else:
                continue
            for candidate in candidates:
                if _plain(candidate, stat.S_ISREG):
                    total += candidate.lstat().st_size
        except OSError:
            continue
    return total
