"""Tie the file swap to the SQLite backup transaction across process exits."""
from contextlib import closing, contextmanager
import logging
import re
import shutil
import sqlite3
import uuid

JOURNAL = '.stellar-restore-transaction'
COMMIT_KEY = 'local_restore_transaction'


def _write_progress(journal, progress):
    temporary = journal.with_suffix('.tmp')
    temporary.write_text(progress, encoding='ascii')
    temporary.replace(journal)


def recover(root):
    journal = root / JOURNAL
    if not journal.exists():
        return
    progress = journal.read_text(encoding='ascii')
    finished = progress.startswith('done ')
    transaction = progress.removeprefix('done ')
    if not re.fullmatch('[0-9a-f]{32}', transaction):
        raise ValueError('恢复进度文件损坏，请保留当前知识库目录。')
    stage = root / ('.stellar-restore-' + transaction)
    if stage.is_symlink():
        raise ValueError('恢复工作目录无效。')
    previous = stage / 'previous-files'
    if not finished and previous.exists():
        database = (root / 'archive.sqlite3').resolve().as_uri() + '?mode=rw'
        with closing(sqlite3.connect(database, uri=True)) as db:
            committed = db.execute('SELECT value FROM settings WHERE key=?', (COMMIT_KEY,)).fetchone()
        if committed != (transaction,):
            chats = root / 'conversations.json'
            saved = stage / 'previous-chats'
            if saved.exists():
                # Keep the rollback copy until the original files are back. A
                # second interruption can then repeat this entire step.
                replacement = stage / 'rollback-chats'
                with saved.open('rb') as src, replacement.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
                replacement.replace(chats)
            else:
                chats.unlink(missing_ok=True)
            current = root / 'files'
            if current.exists():
                current.replace(stage / 'discarded-files')
            previous.replace(current)
    # The live library is already consistent. A locked old file may defer
    # disposal on Windows; keep the journal so startup can retry cleanup.
    if not finished:
        _write_progress(journal, 'done ' + transaction)
    try:
        if stage.exists():
            shutil.rmtree(stage)
        journal.unlink()
    except OSError as error:
        warning = '资料已就绪，恢复临时文件尚未清理：' + str(error)
        logging.getLogger(__name__).warning(warning)
        return warning


@contextmanager
def workspace(root, warn):
    warning = recover(root)
    if warning:
        raise ValueError(warning)
    transaction = uuid.uuid4().hex
    stage = root / ('.stellar-restore-' + transaction)
    journal = root / JOURNAL
    _write_progress(journal, transaction)
    try:
        stage.mkdir()
        yield stage, transaction
    finally:
        warning = recover(root)
        if warning:
            warn(warning=warning)


def install(root, stage, transaction):
    database = stage / 'archive.sqlite3'
    with closing(sqlite3.connect(database)) as src:
        # SQLite publishes the restored records and this commit marker together.
        with src:
            src.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)', (COMMIT_KEY, transaction))
        chats = root / 'conversations.json'
        if chats.exists():
            (stage / 'previous-chats').write_bytes(chats.read_bytes())
        (root / 'files').replace(stage / 'previous-files')
        (stage / 'files').replace(root / 'files')
        if (stage / 'conversations.json').exists():
            shutil.copyfile(stage / 'conversations.json', chats)
        else:
            chats.unlink(missing_ok=True)
        with closing(sqlite3.connect(root / 'archive.sqlite3')) as dst:
            src.backup(dst)
