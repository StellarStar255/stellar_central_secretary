"""Persist the library location outside the library and the installed program."""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from contextlib import closing, contextmanager
from pathlib import Path

from . import paths


class Unavailable(ValueError):
    pass


_DATABASE = 'archive.sqlite3'
_COPY_SKIP = {_DATABASE, _DATABASE+'-wal', _DATABASE+'-shm', _DATABASE+'-journal',
              'local-backups', 'updates', '.stellar-library.lock', '.stellar-migration'}


def preference_file():
    if sys.platform == 'win32':
        directory = paths._windows_metadata().with_name('Stellar Secretary Settings')
    elif sys.platform == 'darwin':
        directory = Path.home() / 'Library/Application Support/Stellar Secretary Settings'
    else:
        directory = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config') / 'stellar-secretary'
    return directory/'library-location.json'


def read():
    try:
        return json.loads(preference_file().read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}


def write(value):
    location = preference_file()
    location.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=location.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(location)
    finally:
        temporary.unlink(missing_ok=True)


def selected(value, override):
    current = value.get('active') or value.get('source')
    if current and (not override or str(Path(override).expanduser().resolve()) in (
            current, *value.get('previous', []))):
        return Path(current)
    return Path(override or paths.DATA_DIR).expanduser().resolve()


@contextmanager
def lease(root):
    """Prevent separate server processes from writing to the same library."""
    with (root/'.stellar-library.lock').open('a+b') as stream:
        try:
            if sys.platform == 'win32':
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError('该记忆目录正在使用，请先退出另一个知识秘书实例。') from error
        yield


def status(root):
    value = read()
    if value.get('source') == str(root):
        return {'pending': value.get('target', ''), 'error': value.get('error', '')}
    return {}


def _target_path(root, requested, backup_folder):
    if not isinstance(requested, str) or not requested.strip():
        raise ValueError('请输入记忆目录的完整路径。')
    target = Path(requested.strip()).expanduser()
    if not target.is_absolute():
        raise ValueError('请输入记忆目录的完整路径。')
    target = target.resolve()
    backup = backup_folder.resolve()
    if (target.is_relative_to(root) or root.is_relative_to(target) or
            target.is_relative_to(backup) or backup.is_relative_to(target) or
            preference_file().resolve().is_relative_to(target)):
        raise ValueError('请选择独立于现有记忆和备份目录的文件夹。')
    if paths.inside_program(target):
        raise ValueError('记忆目录不能位于程序安装目录中。')
    return target


def _copy_ignore(root, directory, names):
    transient = {name for name in names if name in ('SingletonLock', 'SingletonCookie', 'SingletonSocket')
                 or (directory/name).is_socket()}
    return transient | _COPY_SKIP if directory == root else transient


def _estimate_bytes(root):
    def fail(error):
        raise error

    total = 0
    for path, directories, files in os.walk(root, onerror=fail):
        directory = Path(path)
        ignored = _copy_ignore(root, directory, directories + files)
        directories[:] = [name for name in directories if name not in ignored]
        files.extend(name for name in directories if (directory/name).is_symlink())
        for name in files:
            if name in ignored and not (directory == root and name in (_DATABASE, _DATABASE+'-wal')):
                continue
            try:
                total += (directory/name).lstat().st_size
            except FileNotFoundError:
                # A live browser or SQLite may remove a transient file during the scan.
                continue
    return total


def _check_destination(target, required_bytes):
    result = {'estimated_bytes': required_bytes, 'free_bytes': None, 'empty': None, 'writable': None}
    if not target.is_dir():
        return {**result, 'error': '请选择一个已存在的空文件夹作为记忆目录。'}
    try:
        result['empty'] = next(target.iterdir(), None) is None
        result['free_bytes'] = shutil.disk_usage(target).free
    except OSError:
        return {**result, 'error': '无法读取目标文件夹或磁盘空间。'}
    try:
        with tempfile.TemporaryFile(dir=target):
            pass
        result['writable'] = True
        if target.is_mount():
            return {**result, 'error': '请在目标磁盘中选择一个空的子文件夹。'}
        with tempfile.TemporaryFile(dir=target.parent):
            pass
    except OSError:
        error = '目标文件夹不可写。' if result['writable'] is None else '无法在目标文件夹的上一级创建迁移副本。'
        if result['writable'] is None:
            result['writable'] = False
        return {**result, 'error': error}
    if not result['empty']:
        return {**result, 'error': '请选择一个已存在的空文件夹作为记忆目录。'}
    if result['free_bytes'] < required_bytes:
        return {**result, 'error': '目标磁盘可用空间不足。'}
    return result


def preflight(root, requested, backup_folder):
    target = _target_path(root, requested, backup_folder)
    return _check_destination(target, _estimate_bytes(root))


def schedule(root, requested, backup_folder):
    value = read()
    if value.get('active') not in (None, str(root)) or value.get('source') not in (None, str(root)):
        raise ValueError('请在主知识库实例中更改记忆目录。')
    if not isinstance(requested, str):
        raise ValueError('请输入记忆目录的完整路径。')
    if not requested.strip():
        value = {key: val for key, val in value.items() if key in ('active', 'previous')}
    else:
        target = _target_path(root, requested, backup_folder)
        if error := _check_destination(target, _estimate_bytes(root)).get('error'):
            raise ValueError(error)
        value.update(source=str(root), target=str(target), migration=uuid.uuid4().hex)
        value.pop('error', None)
    write(value)
    return status(root)


def _copy(root, stage):
    # Keep the previous default backups discoverable without duplicating their ZIP files.
    shutil.copytree(root, stage, symlinks=True,
                    ignore=lambda directory, names: _copy_ignore(root, Path(directory), names),
                    dirs_exist_ok=True)
    with closing(sqlite3.connect((root/_DATABASE).as_uri()+'?mode=rw', uri=True)) as source:
        with closing(sqlite3.connect(stage/_DATABASE)) as destination:
            source.backup(destination)
            if destination.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('新目录中的记忆数据库未通过核验。')
    config = stage/'backup-settings.json'
    previous = root/'local-backups'
    if previous.is_dir():
        settings = json.loads(config.read_text()) if config.is_file() else {}
        settings['previous_folders'] = list(dict.fromkeys([*settings.get('previous_folders', []), str(previous)]))
        config.write_text(json.dumps(settings))


def migrate(root, value):
    """Called during startup with the source lease held, before creating any workers."""
    if value.get('source') != str(root) or not value.get('target'):
        return root
    target = Path(value['target'])
    marker = target/'.stellar-migration'
    stage = None
    try:
        if not (marker.is_file() and marker.read_text() == value['migration']):
            if error := _check_destination(target, _estimate_bytes(root)).get('error'):
                raise ValueError(error)
            stage = Path(tempfile.mkdtemp(prefix='.stellar-move-', dir=target.parent))
            _copy(root, stage)
            (stage/marker.name).write_text(value['migration'])
            # Keep the staging directory on the destination disk so publication is atomic.
            if sys.platform == 'win32':
                target.rmdir()
            try:
                stage.rename(target)
            except OSError:
                if sys.platform == 'win32' and target.parent.is_dir():
                    target.mkdir(exist_ok=True)
                raise
    except (OSError, ValueError, sqlite3.Error) as error:
        write({**value, 'error': str(error)})
        return root
    finally:
        if stage and stage.exists():
            shutil.rmtree(stage)
    write({'active': str(target), 'previous': list(dict.fromkeys([*value.get('previous', []), str(root)]))})
    return target
