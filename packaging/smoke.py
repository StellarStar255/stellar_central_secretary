"""Exercise the frozen server, static assets, archive and authenticated shutdown."""
import json
import zipfile
import io
from PIL import Image
import base64
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'tests'))
from pdf_fixture import pdf_bytes

with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
binary = (Path('dist/Stellar Secretary.app/Contents/MacOS/Stellar Secretary') if sys.platform == 'darwin'
          else Path('dist/Stellar Secretary/Stellar Secretary.exe')).resolve()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with tempfile.TemporaryDirectory() as data:
    proc = subprocess.Popen([str(binary), '--no-browser', '--port', str(port), '--data-dir', data],
                            env={**os.environ, 'SECRETARY_DATA_DIR': data})
    def request(path, body=None, token=None):
        req = urllib.request.Request(f'http://127.0.0.1:{port}'+path,
                                     data=body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type':'application/json', 'X-Knowledge-Token':token or ''})
        with opener.open(req, timeout=30 if path=='/api/update/check' else 3) as response:
            return response.read()
    try:
        for _ in range(60):
            if proc.poll() is not None: raise RuntimeError('Frozen app exited before startup')
            try:
                status = json.loads(request('/api/status'))
                break
            except OSError: time.sleep(.5)
        else: raise RuntimeError('Frozen app did not start')
        for path in ('/', '/app.js', '/style.css', '/tutorial', '/tutorial.js', '/tutorial.css', '/i18n.js', '/i18n-data.js','/notes-ui.js','/archive-actions.js','/bundle-ui.js','/additions-ui.js'):
            assert request(path), path
        assert b'tutorial-open' in request('/')
        assert b'ui-font-size' in request('/')
        request('/api/appearance',{'ui_font_size':18},status['token'])
        assert json.loads(request('/api/status'))['settings']['ui_font_size']==18
        request('/api/appearance',{'ui_font_size':14},status['token'])
        request('/api/appearance',{'content_font_scale':120},status['token'])
        appearance=json.loads(request('/api/status'))['settings']
        assert appearance['content_font_scale']==120 and appearance['ui_font_size']==14
        request('/api/appearance',{'content_font_scale':100},status['token'])
        assert b'content-font-reset' in request('/')
        print('PASS: frozen interface font-size setting and GUI control')
        request('/api/language',{'language':'en'},status['token'])
        assert json.loads(request('/api/status'))['settings']['ui_language']=='en'
        request('/api/language',{'language':'zh'},status['token'])
        request('/api/settings', {'backend':'codex', 'auto_ai':False, 'capture_scope':'loaded'}, status['token'])
        assert json.loads(request('/api/status'))['settings']['capture_scope'] == 'loaded'
        fixture=json.loads(request('/api/ingest', {'text':'安装包测试资料，可供检索。'}, status['token']))['item']
        request('/api/items/'+fixture['id']+'/tags',{'tags':['CustomSearchTag'],'expected_tags':[]},status['token'])
        assert json.loads(request('/api/items?q=CustomSearchTag'))[0]['id']==fixture['id']
        image=io.BytesIO();Image.new('RGB',(8,8),'#77aacc').save(image,format='PNG')
        saved=json.loads(request('/api/items/'+fixture['id']+'/notes',{'text':'Private quick note','images':[{'name':'example.png','data':base64.b64encode(image.getvalue()).decode()}],'version':0},status['token']))['item']
        assert saved['note']=='Private quick note' and saved['note_version']==1
        assert request('/api/items/'+fixture['id']+'/note-images/'+saved['note_images'][0]['id'])==image.getvalue()
        print('PASS: frozen manual tags, tag search, quick-note text and local PNG image storage')
        assert len(json.loads(request('/api/items'))) == 1
        backup = request('/api/backup')
        imported = json.loads(request('/api/import', backup, status['token']))
        assert imported == {'imported': 0, 'skipped': 1, 'total': 1}, imported
        assert b'import-backup' in request('/')
        pdf = json.loads(request('/api/ingest', {'filename':'aes-fixture.pdf', 'data':base64.b64encode(pdf_bytes(password='')).decode()}, status['token']))['item']
        assert 'Encrypted PDF extraction fixture' in pdf['text'] and not pdf['error'], pdf
        for query in ('Encrypted%20readable','readable%20Encrypted'):
            matches=json.loads(request('/api/items?q='+query+'&kind=file'))
            assert [item['id'] for item in matches]==[pdf['id']], matches
        assert json.loads(request('/api/items?q=Encrypted%20nonexistent'))==[]
        group=json.loads(request('/api/ingest',{'text':'Combined synthetic context','attachments':[{'name':'sample.png','data':base64.b64encode(image.getvalue()).decode()},{'name':'context.txt','data':base64.b64encode(b'Attachment context').decode()}],'defer_summary':True},status['token']))['item']
        assert status['capabilities']['grouped_materials'] and len(group['attachments'])==2
        assert request('/api/items/'+group['id']+'/attachments/'+group['attachments'][0]['id']+'/preview')==image.getvalue()
        with zipfile.ZipFile(io.BytesIO(request('/api/items/'+group['id']+'/file'))) as original:
            assert original.read('files/01-sample.png')==image.getvalue()
        request('/api/items/'+group['id']+'/delete',{'confirmed':True,'expected_updated':group['updated']},status['token'])
        print('PASS: frozen grouped image/text/file archive, original image preview and grouped deletion')
        annotated=json.loads(request('/api/ingest',{'url':f'http://127.0.0.1:{port}/unavailable-page','context':'Synthetic machine inventory link:'},status['token']))['item']
        assert annotated['user_context']=='Synthetic machine inventory link:' and not annotated['text']
        assert annotated['title']=='Synthetic machine inventory link'
        assert json.loads(request('/api/items?q=inventory%20machine'))[0]['id']==annotated['id']
        request('/api/items/'+annotated['id']+'/delete',{'confirmed':True,'expected_updated':annotated['updated']},status['token'])
        print('PASS: frozen unavailable link retains annotation, descriptive title and search index')
        reparsed = json.loads(request('/api/items/'+pdf['id']+'/reextract', {}, status['token']))
        assert reparsed['parsed'] and reparsed['item']['id'] == pdf['id'], reparsed
        extra=json.loads(request('/api/items/'+pdf['id']+'/additions',{'text':'New supporting materials','attachments':[{'name':'new.png','data':base64.b64encode(image.getvalue()).decode()}],'expected_updated':reparsed['item']['updated'],'summarize':False},status['token']))
        batch=extra['item']['additions'][0]
        assert request('/api/items/'+pdf['id']+'/additions/'+batch['id']+'/attachments/'+batch['attachments'][0]['id']+'/preview')==image.getvalue()
        assert request('/api/items/'+pdf['id']+'/preview')==request('/api/items/'+pdf['id']+'/file')
        assert json.loads(request('/api/items?q=supporting'))[0]['id']==pdf['id']
        print('PASS: frozen append-to-PDF archive, appended-image preview, search and original PDF retained')
        if os.environ.get('SECRETARY_TLS_TEST') == '1':
            update = json.loads(request('/api/update/check', {}, status['token']))
            assert not update.get('error'), update
            print('PASS: frozen HTTPS update check with certificate verification enabled')
        current=json.loads(request('/api/items/'+fixture['id']))
        deleted=json.loads(request('/api/items/'+fixture['id']+'/delete',{'confirmed':True,'expected_updated':current['updated']},status['token']))
        assert deleted['ok'] and not deleted['warning']
        assert [item['id'] for item in json.loads(request('/api/items'))]==[pdf['id']]
        with zipfile.ZipFile(io.BytesIO(request('/api/backup'))) as clean_backup:
            assert 'files/'+saved['note_images'][0]['id'] not in clean_backup.namelist()
        print('PASS: frozen confirmed archive deletion, attachment cleanup and unrelated PDF preserved')
        request('/api/shutdown', {}, status['token'])
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log = Path(data)/'app.log'
        if log.exists(): print(log.read_text(encoding='utf-8'))
