"""Enumerate managed snapshots independently of the health of their sidecar files."""
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

REASONS = ('manual', 'upgrade', 'before-restore', 'daily', 'recovered')


def directory_key(path):
    try:
        info = path.stat()
        if info.st_ino:
            return info.st_dev, info.st_ino
    except OSError:
        pass
    # Keep disconnected drives and paths on filesystems without file IDs usable.
    return os.path.normcase(os.path.realpath(path))


def same_folder(saved, folder):
    if saved == str(folder):
        return True
    return (isinstance(saved, str) and Path(saved).is_absolute()
            and directory_key(Path(saved)) == directory_key(folder))


def previous_folders(history, departed, *, current, default):
    """Keep the last five distinct old folders, oldest first on disk."""
    seen = {directory_key(current), directory_key(default)}
    recent = []
    for value in reversed([*history, str(departed)]):
        if not isinstance(value, str) or not Path(value).is_absolute():
            continue
        key = directory_key(Path(value))
        if key not in seen:
            recent.append(value)
            seen.add(key)
            if len(recent) == 5:
                break
    return recent[::-1]


def valid_date(value):
    try:
        return isinstance(value, str) and datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def valid_verification(value):
    return isinstance(value, dict) and value.get('state') in ('verified', 'failed', 'inconsistent') and valid_date(value.get('checked_at')) and isinstance(value.get('error', ''), str)


def entries(folder):
    result = []
    try:
        names = {p.stem for p in folder.iterdir() if p.suffix in ('.json', '.zip')
                 and re.fullmatch('[0-9a-f]{32}', p.stem)}
    except OSError:
        return result
    for key in names:
        entry = read_entry(folder, key)
        if entry is not None:
            result.append(entry)
    return result


def read_entry(folder, key):
    source = folder / (key + '.zip')
    meta = source.with_suffix('.json')
    try:
        if source.is_symlink():
            return None
        present = source.is_file()
        stat = (source if present else meta).stat()
    except OSError:
        return None
    index = {}
    issue = ''
    try:
        if meta.is_symlink():
            raise OSError('unsafe metadata')
        index = json.loads(meta.read_text(encoding='utf-8'))
    except FileNotFoundError:
        issue = 'missing_index'
    except (ValueError, RecursionError):
        issue = 'invalid_index'
    except OSError:
        issue = 'unreadable_index'
    if not isinstance(index, dict):
        index = {}
    digest = index.get('sha256')
    has_digest = isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest)
    created = index.get('created')
    reason = index.get('reason')
    verification = index.get('verification')
    if not present:
        issue = 'missing_zip'
    elif not (index.get('id') == key and valid_date(created) and reason in REASONS and has_digest
              and ('verification' not in index or valid_verification(verification))):
        issue = issue or 'invalid_index'
    entry = {'id': key, 'folder': str(folder), 'size': stat.st_size if present else 0,
             'created': created if valid_date(created) else datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
             'reason': reason if reason in REASONS else 'recovered'}
    if isinstance(index.get('library_id'), str) and re.fullmatch(r'[0-9a-f]{32}', index['library_id']):
        entry['library_id'] = index['library_id']
    if has_digest:
        entry['sha256'] = digest
    if issue:
        entry['index_issue'] = issue
    elif verification:
        entry['verification'] = verification
    return entry


def save(meta, value):
    temporary = meta.with_suffix('.'+uuid.uuid4().hex+'.index-part')
    try:
        temporary.write_text(json.dumps(value), encoding='utf-8')
        temporary.replace(meta)
    finally:
        temporary.unlink(missing_ok=True)
