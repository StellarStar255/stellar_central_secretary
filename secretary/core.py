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
            from pypdf.errors import DependencyError, FileNotDecryptedError, PdfReadError
        except ImportError:
            return '', 'PDF 解析组件未安装，请运行启动脚本安装依赖。'
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted and not reader.decrypt(''):
                return '', '此 PDF 需要打开密码，请先使用密码打开并导出可读取版本，再重新导入。'
            pages = [(page.extract_text() or '').strip() for page in reader.pages]
        except DependencyError:
            return '', 'PDF 加密读取组件不完整，请升级程序后点击「重新解析原文件」。'
        except FileNotDecryptedError:
            return '', '此 PDF 需要打开密码，请先使用密码打开并导出可读取版本，再重新导入。'
        except PdfReadError:
            return '', 'PDF 文件损坏或结构无法读取，请确认原文件能正常打开后重试。'
        if sum(len(text) for text in pages)<20:
            return '', '此 PDF 没有足够的可读取文字，可能是扫描件，需要先做 OCR。'
        return '\n\n'.join(f'[第 {i+1} 页]\n{text}' for i,text in enumerate(pages) if text), ''
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
            if 'tags_manual' not in {row[1] for row in db.execute('PRAGMA table_info(items)')}:
                db.execute('ALTER TABLE items ADD COLUMN tags_manual INTEGER NOT NULL DEFAULT 0')
                for row in db.execute('SELECT id,text FROM items').fetchall():self._index(db,row['id'],row['text'])
            columns={row[1] for row in db.execute('PRAGMA table_info(items)')}
            for name,definition in [('note',"TEXT NOT NULL DEFAULT ''"),('note_images',"TEXT NOT NULL DEFAULT '[]'"),('note_version','INTEGER NOT NULL DEFAULT 0')]:
                if name not in columns:db.execute('ALTER TABLE items ADD COLUMN '+name+' '+definition)
            if recover:
                db.execute("UPDATE items SET state='pending',error='上次处理被中断，等待重新处理' WHERE state='processing'")
                db.execute("UPDATE items SET state='needs_content',error='上次登录读取已中断，请点击登录并读取重试。' WHERE state IN ('queued_capture','opening_browser','waiting_login','confirming_login','waiting_browser_close','reading')")
    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / 'archive.sqlite3', timeout=30); db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def settings(self):
        with self.db() as db: values = dict(db.execute('SELECT key,value FROM settings').fetchall())
        try:font_size=int(values.get('ui_font_size','14'))
        except (TypeError,ValueError):font_size=14
        if not 12<=font_size<=24:font_size=14
        try:content_scale=int(values.get('content_font_scale','100'))
        except (TypeError,ValueError):content_scale=100
        if not 70<=content_scale<=200:content_scale=100
        return {'backend': values.get('backend', 'codex'), 'auto_ai': values.get('auto_ai', 'true') == 'true',
                'capture_background': values.get('capture_background', 'true') == 'true',
                'capture_close_tabs': values.get('capture_close_tabs', 'true') == 'true',
                'capture_scope': values.get('capture_scope', 'recent'), 'interface_mode':values.get('interface_mode','browser'), 'ui_language':values.get('ui_language','zh'), 'ui_font_size':font_size, 'content_font_scale':content_scale}
    def configure(self, backend, auto_ai, capture_background=None, capture_close_tabs=None, capture_scope=None):
        if backend not in ('codex', 'claude'): raise ValueError('未知模型后端')
        with self.db() as db:
            pairs=[('backend', backend), ('auto_ai', str(bool(auto_ai)).lower())]
            if capture_scope is not None:
                if capture_scope not in ('recent','loaded','full'):raise ValueError('无效的会话读取范围')
                pairs.append(('capture_scope',capture_scope))
            for key,value in (('capture_background',capture_background),('capture_close_tabs',capture_close_tabs)):
                if value is not None:
                    if not isinstance(value,bool): raise ValueError('浏览器选项格式无效')
                    pairs.append((key,str(value).lower()))
            db.executemany('INSERT OR REPLACE INTO settings VALUES (?,?)', pairs)
    def set_language(self,language):
        if language not in ('zh','en'):raise ValueError('Unsupported display language')
        with self.db() as db:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('ui_language',language))
    def set_font_size(self,size):
        if type(size) is not int or not 12<=size<=24:raise ValueError('界面字号必须是 12–24 之间的整数')
        with self.db() as db:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('ui_font_size',str(size)))
    def set_content_font_scale(self,scale):
        if type(scale) is not int or not 70<=scale<=200:raise ValueError('正文缩放必须是 70–200 之间的整数')
        with self.db() as db:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('content_font_scale',str(scale)))
    def set_interface_mode(self,mode):
        if mode not in ('desktop','browser'):raise ValueError('未知的使用方式')
        with self.db() as db:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('interface_mode',mode))
    def _index(self, db, item_id, text):
        text = searchable_text(text)
        metadata=db.execute('SELECT title,tags FROM items WHERE id=?',(item_id,)).fetchone()
        keywords=(metadata['title']+' '+' '.join(json.loads(metadata['tags']))) if metadata else ''
        db.execute('DELETE FROM search WHERE item_id=?', (item_id,)); db.execute('DELETE FROM chunks WHERE item_id=?', (item_id,))
        for pos, offset in enumerate(range(0, len(text), 1000)):
            chunk = text[offset:offset+1200]
            cursor = db.execute('INSERT INTO chunks(item_id,position,text) VALUES (?,?,?)', (item_id, pos, chunk))
            db.execute('INSERT INTO search VALUES (?,?,?)', (' '.join(terms(keywords+' '+chunk)), cursor.lastrowid, item_id))
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
        item = dict(row); item['tags'] = json.loads(item['tags']);item['note_images']=json.loads(item['note_images']); return item
    def update(self, item_id, **values):
        allowed = {'title','text','summary','tags','category','state','error'}
        if not values or not set(values) <= allowed: raise ValueError('无效更新')
        values['updated'] = datetime.now(timezone.utc).isoformat()
        with self.lock, self.db() as db:
            if 'tags' in values:
                current=db.execute('SELECT tags_manual FROM items WHERE id=?',(item_id,)).fetchone()
                if not current:raise KeyError('资料不存在')
                if current['tags_manual']:values.pop('tags')
                else:values['tags']=json.dumps(values['tags'],ensure_ascii=False)
            db.execute('UPDATE items SET '+','.join(k+'=?' for k in values)+' WHERE id=?', (*values.values(), item_id))
            if {'text','title','tags'} & values.keys():
                row=db.execute('SELECT text FROM items WHERE id=?',(item_id,)).fetchone()
                if row:self._index(db,item_id,row['text'])
    def set_tags(self,item_id,tags,expected=None):
        if not isinstance(tags,list) or len(tags)>50 or any(not isinstance(tag,str) or not tag.strip() or len(tag.strip())>60 for tag in tags):
            raise ValueError('最多添加 50 个标签，每个标签为 1–60 个字符。')
        clean=[];seen=set()
        for tag in tags:
            tag=tag.strip()
            if tag.casefold() not in seen:clean.append(tag);seen.add(tag.casefold())
        with self.lock,self.db() as db:
            row=db.execute('SELECT tags,text FROM items WHERE id=?',(item_id,)).fetchone()
            if not row:raise KeyError('资料不存在')
            if expected is not None and json.loads(row['tags'])!=expected:raise ValueError('标签已变化，请刷新资料后重试。')
            db.execute('UPDATE items SET tags=?,tags_manual=1,updated=? WHERE id=?',
                       (json.dumps(clean,ensure_ascii=False),datetime.now(timezone.utc).isoformat(),item_id))
            self._index(db,item_id,row['text'])
        return self.get(item_id)

    def replace_capture(self, item_id, title, text, partial=False):
        previous = self.get(item_id)
        if not text.strip(): raise ValueError('新采集正文为空，原正文已保留。')
        if partial and (not text.startswith('【部分对话归档】') or previous['text'] and not previous['text'].startswith('【部分对话归档】')):
            raise ValueError('部分采集不能覆盖已有完整正文。')
        if not partial and previous['text'] and len(searchable_text(text))<len(searchable_text(previous['text']))*.85:
            raise ValueError('新采集正文显著短于原正文，可能仍有消息未加载；原正文已保留。')
        if text==previous['text']: return False
        if previous['text']:
            history=self.root/'capture-history';history.mkdir(exist_ok=True)
            (history/(item_id+'-'+uuid.uuid4().hex+'.json')).write_text(json.dumps(previous,ensure_ascii=False))
        self.update(item_id,text=text,title=title or previous['title'],summary='',tags=[],category='未分类',state='pending',error='')
        return True
    def list(self, q='', category='', kind=''):
        # Library filters require every whitespace-separated keyword, across fields.
        # Conversational retrieval below keeps its broader relevance ranking.
        keywords=list(dict.fromkeys(q.casefold().split()))
        columns='id,title,kind,url,filename,summary,tags,category,state,error,created,updated,length(text) AS text_length,note'
        with self.db() as db:
            rows=[dict(r) for r in db.execute('SELECT '+columns+(',text' if keywords else '')+' FROM items ORDER BY created DESC')]
        result=[]
        for row in rows:
            body=row.pop('text','')
            row['tags']=json.loads(row['tags'])
            if category and row['category']!=category or kind and row['kind']!=kind:continue
            if keywords:
                fields=[str(row.get(key) or '') for key in ('title','summary','filename','url','category','note')]
                fields.extend(row['tags']);fields.append(searchable_text(body))
                source='\n'.join(fields)
                haystack=(source+'\n'+search_aliases(source)).casefold()
                if not all(keyword in haystack for keyword in keywords):continue
            result.append(row)
        return result
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
