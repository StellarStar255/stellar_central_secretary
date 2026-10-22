"""Check prospective Git files and reachable history without printing secrets.

Run from any directory: python3 scripts/check_public_files.py
This is a pattern-based publication check, not a complete security audit.
"""
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    'personal-home-path': re.compile(r'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
    'private-conversation-url': re.compile(r'https://(?:chatgpt\.com|chat\.openai\.com|claude\.ai)/(?:c|chat)/[a-f0-9-]{20,}'),
    'api-token': re.compile(r'\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b'),
    'private-key': re.compile(r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----'),
    'jwt': re.compile(r'eyJ[A-Za-z0-9_-]{12,}\.eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{15,}'),
    'credential-assignment': re.compile(r'''(?:api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|password)\s*[=:]\s*["'][^"'\n]{8,}["']''', re.I),
    'authenticated-url': re.compile(r'https?://[^/\s:@]+:[^/\s@]+@'),
}
PRIVATE_DIRS = {'data', '.images', '.aws', '.ssh', '.codex', 'capture-history', 'browser-profile', 'browser-live-profile'}
PRIVATE_SUFFIXES = {'.sqlite', '.sqlite3', '.db', '.pem', '.key', '.p12', '.pfx', '.har'}
PRIVATE_NAMES = {'auth.json', 'credentials.json', 'storage-state.json', 'storage_state.json'}


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, stderr=subprocess.DEVNULL)


def scan(name, data, label):
    findings = []
    path = PurePosixPath(name)
    if (PRIVATE_DIRS.intersection(path.parts) or path.suffix in PRIVATE_SUFFIXES or
            path.name in PRIVATE_NAMES or path.name == '.env' or
            path.name.startswith('.env.') and path.name != '.env.example' or
            path.name.endswith('.knowledge.json') or path.name.startswith('.reader-session.')):
        findings.append(f'{label}:{name}: private runtime/credential file')
    try:
        source = data.decode('utf-8')
    except UnicodeDecodeError:
        findings.append(f'{label}:{name}: binary file requires manual review')
        return findings
    for line_number, line in enumerate(source.splitlines(), 1):
        for kind, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append(f'{label}:{name}:{line_number}: {kind}')
    return findings


def main():
    findings = []
    names = set(filter(None, git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')))
    for name in sorted(names):
        path = ROOT / name
        if path.is_symlink():
            findings.append(f'working:{name}: symbolic link requires manual review')
        elif path.is_file():
            findings.extend(scan(name, path.read_bytes(), 'working'))
    # Include staged bytes, which can differ from the working copy.
    trees = [('index', git('ls-files', '--stage', '-z'))]
    commits = git('rev-list', '--all').decode().split()
    trees += [(commit[:8], git('ls-tree', '-r', '-z', commit)) for commit in commits]
    checked = set()
    for label, tree in trees:
        for entry in filter(None, tree.decode().split('\0')):
            meta, name = entry.split('\t', 1)
            blob = meta.split()[1 if label == 'index' else 2]
            if (name, blob) in checked:
                continue
            checked.add((name, blob))
            findings.extend(scan(name, git('cat-file', 'blob', blob), label))
    if findings:
        print('\n'.join(findings))
        print(f'FAIL: {len(findings)} finding(s); values are intentionally hidden.')
        return 1
    print(f'PASS: {len(names)} prospective files, staged blobs and {len(commits)} reachable commit(s).')
    print('Pattern-based check only; review images and exports separately before publishing.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
