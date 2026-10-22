"""Local durable archive, document extraction and bilingual passage retrieval."""
import hashlib
from contextlib import contextmanager
import io
import json
import re
import sqlite3
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET
from html.parser import HTMLParser
from .rich_text import searchable_text


class PageText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'): self.hidden += 1
        if tag in ('p', 'div', 'br', 'article', 'h1', 'h2', 'li'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'): self.hidden = max(0, self.hidden - 1)
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)
    @classmethod
    def parse(cls, html):
        p = cls(); p.feed(html)
        return re.sub(r'\n[ \t]*\n+', '\n\n', ''.join(p.parts)).strip()


def extract(name, data):
    suffix = Path(name).suffix.lower()
    if suffix == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError:
            return '', 'PDF 解析组件未安装，请运行启动脚本安装依赖。'
        reader = PdfReader(io.BytesIO(data))
        text = '\n\n'.join(f'[第 {i+1} 页]\n{page.extract_text() or ""}' for i, page in enumerate(reader.pages))
        return (text, '') if len(text.strip()) > 20 else ('', '此 PDF 没有可读取文字，扫描件需先做 OCR。')
    if suffix in ('.docx', '.pptx', '.xlsx', '.odt'):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > 100_000_000: raise ValueError('解压内容超过 100 MB')
            if suffix == '.xlsx':
                ns = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                shared = []
                if 'xl/sharedStrings.xml' in z.namelist():
                    shared = [''.join(node.itertext()) for node in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si', ns)]
                sheets = []
                for name in sorted(n for n in z.namelist() if re.match(r'xl/worksheets/sheet\d+\.xml$', n)):
                    rows = []
                    for row in ET.fromstring(z.read(name)).findall('.//s:row', ns):
                        cells = []
                        for cell in row.findall('s:c', ns):
                            value = cell.findtext('s:v', default='', namespaces=ns)
                            if cell.get('t') == 's': value = shared[int(value)] if value else ''
                            elif cell.get('t') == 'inlineStr': value = ''.join(cell.find('s:is', ns).itertext())
                            cells.append(cell.get('r', '')+': '+value)
                        rows.append(' | '.join(cells))
                    sheets.append(name+'\n'+'\n'.join(rows))
                return '\n\n'.join(sheets), ''
            names = [n for n in z.namelist() if n == 'word/document.xml' or re.match(r'ppt/slides/slide\d+\.xml$', n) or re.match(r'xl/(sharedStrings|worksheets/sheet\d+)\.xml$', n) or n == 'content.xml']
            names.sort(key=lambda n: [int(v) if v.isdigit() else v for v in re.split(r'(\d+)', n)])
            return '\n\n'.join(' '.join(ET.fromstring(z.read(n)).itertext()) for n in names), ''
    if suffix in ('.txt', '.md', '.csv', '.tsv', '.json', '.html', '.htm', '.py', '.js', '.log', '.yaml', '.yml', '.xml', '.rtf'):
        text = None
        for encoding in ('utf-8-sig', 'gb18030', 'utf-16'):
            try: text = data.decode(encoding); break
            except UnicodeError: pass
        if text is None: raise ValueError('无法识别文件文字编码')
        return (PageText.parse(text) if suffix in ('.html', '.htm') else text), ''
    return '', '原文件已保存；此格式暂不支持正文解析，可手动补充文字。'


def terms(text):
    result = re.findall(r'[a-z0-9_]{2,}', text.lower())
    for run in re.findall(r'[\u3400-\u9fff]+', text):
        result.extend(run[i:i+2] for i in range(len(run)-1))
        if len(run) == 1: result.append(run)
    return result


def search_aliases(text):
    """Resolve an ambiguous surname only with supporting historical context."""
    if re.search(r'四人帮|华国锋|文革|文化大革命|中央文革', text) and re.search(r'反对毛|对毛|毛的|毛需要|毛主席|毛泽东|毛澤東', text):
        return '毛泽东 毛主席 毛澤東'
    return ''


class Archive:
    def __init__(self, root, recover=True):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'files').mkdir(exist_ok=True)
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, title TEXT, kind TEXT, url TEXT,
            filename TEXT, digest TEXT UNIQUE, text TEXT, summary TEXT DEFAULT '', tags TEXT DEFAULT '[]',
            category TEXT DEFAULT '未分类', state TEXT, error TEXT DEFAULT '', created TEXT, updated TEXT);
            CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, item_id TEXT, position INTEGER, text TEXT);
            CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(tokens, chunk_id UNINDEXED, item_id UNINDEXED);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);''')
            if recover:
                db.execute("UPDATE items SET state='pending',error='上次处理被中断，等待重新处理' WHERE state='processing'")
                db.execute("UPDATE items SET state='needs_content',error='上次登录读取已中断，请点击登录并读取重试。' WHERE state IN ('opening_browser','waiting_login','confirming_login','waiting_browser_close','reading')")
    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / 'archive.sqlite3', timeout=30); db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def settings(self):
        with self.db() as db: values = dict(db.execute('SELECT key,value FROM settings').fetchall())
        return {'backend': values.get('backend', 'codex'), 'auto_ai': values.get('auto_ai', 'true') == 'true',
                'capture_background': values.get('capture_background', 'true') == 'true',
                'capture_close_tabs': values.get('capture_close_tabs', 'true') == 'true'}
    def configure(self, backend, auto_ai, capture_background=None, capture_close_tabs=None):
        if backend not in ('codex', 'claude'): raise ValueError('未知模型后端')
        with self.db() as db:
            pairs=[('backend', backend), ('auto_ai', str(bool(auto_ai)).lower())]
            for key,value in (('capture_background',capture_background),('capture_close_tabs',capture_close_tabs)):
                if value is not None:
                    if not isinstance(value,bool): raise ValueError('浏览器选项格式无效')
                    pairs.append((key,str(value).lower()))
            db.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)', pairs)
    def _index(self, db, item_id, text):
        text = searchable_text(text)
        db.execute('DELETE FROM search WHERE item_id=?', (item_id,)); db.execute('DELETE FROM chunks WHERE item_id=?', (item_id,))
        for pos, offset in enumerate(range(0, len(text), 1000)):
            chunk = text[offset:offset+1200]
            cursor = db.execute('INSERT INTO chunks(item_id,position,text) VALUES (?,?,?)', (item_id, pos, chunk))
            db.execute('INSERT INTO search VALUES (?,?,?)', (' '.join(terms(chunk)), cursor.lastrowid, item_id))
    def add(self, title='', text='', url='', filename='', data=None, warning=''):
        digest = hashlib.sha256(data if data is not None else (url or text).encode()).hexdigest()
        now = datetime.now(timezone.utc).isoformat(); item_id = uuid.uuid4().hex
        with self.lock, self.db() as db:
            old = db.execute("SELECT id,text FROM items WHERE digest=? OR (url=? AND ?!='') ORDER BY created LIMIT 1", (digest, url, url)).fetchone()
            if old:
                if text.strip() and not old['text'].strip():
                    db.execute("UPDATE items SET text=?,title=?,state='pending',error='',updated=? WHERE id=?", (text, title or filename or url, now, old['id']))
                    if data is not None:
                        (self.root / 'files' / old['id']).write_bytes(data)
                        db.execute("UPDATE items SET filename=? WHERE id=?", (filename, old['id']))
                    self._index(db, old['id'], text)
                return old['id'], False
            if data is not None: (self.root / 'files' / item_id).write_bytes(data)
            state = 'pending' if text.strip() else 'needs_content'
            db.execute('INSERT INTO items(id,title,kind,url,filename,digest,text,state,error,created,updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (item_id, title or filename or url or '未命名笔记', 'file' if filename else ('link' if url else 'note'), url, filename, digest, text, state, warning, now, now))
            self._index(db, item_id, text)
        return item_id, True
    def get(self, item_id):
        with self.db() as db: row = db.execute('SELECT * FROM items WHERE id=?', (item_id,)).fetchone()
        if not row: raise KeyError('资料不存在')
        item = dict(row); item['tags'] = json.loads(item['tags']); return item
    def update(self, item_id, **values):
        allowed = {'title','text','summary','tags','category','state','error'}
        if not values or not set(values) <= allowed: raise ValueError('无效更新')
        if 'tags' in values: values['tags'] = json.dumps(values['tags'], ensure_ascii=False)
        values['updated'] = datetime.now(timezone.utc).isoformat()
        with self.lock, self.db() as db:
            db.execute('UPDATE items SET '+','.join(k+'=?' for k in values)+' WHERE id=?', (*values.values(), item_id))
            if 'text' in values: self._index(db, item_id, values['text'])
    def replace_capture(self, item_id, title, text):
        previous = self.get(item_id)
        if not text.strip(): raise ValueError('新采集正文为空，原正文已保留。')
        if previous['text'] and len(searchable_text(text))<len(searchable_text(previous['text']))*.85:
            raise ValueError('新采集正文显著短于原正文，可能仍有消息未加载；原正文已保留。')
        if text==previous['text']: return False
        if previous['text']:
            history=self.root/'capture-history';history.mkdir(exist_ok=True)
            (history/(item_id+'-'+uuid.uuid4().hex+'.json')).write_text(json.dumps(previous,ensure_ascii=False))
        self.update(item_id,text=text,title=title or previous['title'],summary='',tags=[],category='未分类',state='pending',error='')
        return True
    def list(self, q='', category='', kind=''):
        with self.db() as db:
            rows = [dict(r) for r in db.execute('SELECT id,title,kind,url,filename,summary,tags,category,state,error,created,updated,length(text) AS text_length FROM items ORDER BY created DESC')]
            ids = set()
            if q:
                # Literal substring preserves filenames, URLs and short Chinese queries.
                ids = {r['id'] for r in db.execute('SELECT id,text FROM items') if q.lower() in searchable_text(r['text']).lower()}
                ids.update(p['item_id'] for p in self.retrieve(q, 100))
                # Search derived aliases for existing archives as well as new ones.
                ids.update(r['id'] for r in db.execute('SELECT id,text,summary,tags,title FROM items') if q.lower() in search_aliases(' '.join(searchable_text(str(r[k] or '')) if k=='text' else str(r[k] or '') for k in ('text','summary','tags','title'))).lower())
        for r in rows: r['tags'] = json.loads(r['tags'])
        return [r for r in rows if (not q or r['id'] in ids or q.lower() in json.dumps(r, ensure_ascii=False).lower()) and (not category or r['category']==category) and (not kind or r['kind']==kind)]
    def retrieve(self, query, limit=8):
        tokens = list(dict.fromkeys(terms(query)))[:80]
        if not tokens: return []
        match = ' OR '.join('"'+t+'"' for t in tokens)
        with self.db() as db:
            return [dict(r) for r in db.execute('''SELECT c.id,c.item_id,c.position,c.text,i.title,i.url,i.filename,bm25(search) AS score
            FROM search JOIN chunks c ON c.id=search.chunk_id JOIN items i ON i.id=c.item_id
            WHERE search MATCH ? ORDER BY score LIMIT ?''', (match, limit))]
    def export(self):
        with self.db() as db: return [self.get(r['id']) for r in db.execute('SELECT id FROM items')]
