"""Recognize archived local paths and open their location without executing files."""
import re
import subprocess
import sys
from pathlib import Path
from . import attachment_editor

START = r'(?:[A-Za-z]:[\\/]|~[/\\]|/(?!/))'
QUOTED = re.compile(r'(["\'`])(' + START + r'[^\r\n]+?)\1')
BARE = re.compile(r'(?<![\w/:\\<])' + START + r'[^\s<>"\'`|，。；！？]*')


def extract(text):
    result = []
    for line in text.splitlines():
        quoted = list(QUOTED.finditer(line))
        candidates = [(m.start(2), m.group(2)) for m in quoted]
        for match in BARE.finditer(line):
            if any(q.start() <= match.start() < q.end() for q in quoted):
                continue
            prefix = line[:match.start()].strip()
            # A path on its own line (or following a label) may contain spaces.
            value = line[match.start():].strip() if not prefix or prefix.endswith(('：', ':')) else match.group()
            candidates.append((match.start(), value.rstrip('.,;，。；')))
            if value != match.group():
                break
        for _, value in sorted(candidates):
            if len(value) > 1 and len(value) <= 4096 and value not in result:
                result.append(value)
                if len(result) >= 200:
                    return result
    return result


def shortcut(text):
    """A path alone or a short label plus one path is a location bookmark."""
    if not isinstance(text,str) or len(text)>8192:return None
    lines=[line.strip() for line in text.splitlines() if line.strip()]
    if not 1<=len(lines)<=2:return None
    if re.search(r'[?？]|(?:是什么|在哪里|怎么办|吗|呢)|^(?:请问|为什么|怎么|如何|解释|分析|比较|查找|what\b|how\b|why\b|compare\b)',lines[0],re.I):return None
    paths=extract(text)
    if len(paths)!=1:return None
    value=paths[0];line=lines[-1]
    if value not in line:return None
    prefix,suffix=line.split(value,1)
    if suffix.strip('"\'` 。；;.,') or (prefix.strip('"\'` ') and not prefix.rstrip('"\'` ').endswith(('：',':'))):return None
    label=lines[0] if len(lines)==2 else prefix.strip('"\'` ：:')
    if len(label)>100:return None
    return {'path':value,'title':label.rstrip('：:') or Path(value.replace('\\','/').rstrip('/')).name or value}

def target(text):
    value=shortcut(text)
    return value['path'] if value else ''

def open_location(archive, item_id, value, open_file=False):
    item = archive.get(item_id)
    if not isinstance(value, str) or value not in extract(item.get('text', '')):
        raise ValueError('请选择正文中记录的本地路径。')
    if any(ord(c) < 32 for c in value):
        raise ValueError('本地路径无效。')
    target = Path(value).expanduser()
    if not target.is_absolute():
        raise ValueError('此路径不适用于当前电脑。')
    try:
        if not target.exists():
            raise ValueError('本地路径不存在，可能已移动或属于另一台电脑。')
        directory = target.is_dir()
        if directory and sys.platform == 'darwin':
            subprocess.run(['/usr/bin/open', '-a', 'Finder', str(target.resolve())], check=True, timeout=15)
        else:
            attachment_editor.launch(target, reveal=not directory and not (open_file and attachment_editor.can_open(target.resolve().name)))
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError('无法打开本地路径，请检查访问权限或系统文件管理器。') from error
    return {'ok': True, 'directory': directory, 'opened_file':not directory and open_file and attachment_editor.can_open(target.resolve().name)}
