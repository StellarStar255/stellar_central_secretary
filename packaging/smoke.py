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
import threading
import uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'tests'))
from pdf_fixture import pdf_bytes

with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
binary = Path(os.environ.get('SECRETARY_SMOKE_BINARY') or (
    'dist/Stellar Secretary.app/Contents/MacOS/Stellar Secretary' if sys.platform == 'darwin'
    else 'dist/Stellar Secretary/Stellar Secretary.exe' if sys.platform == 'win32'
    else 'dist/Stellar Secretary/Stellar Secretary')).resolve()
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
with tempfile.TemporaryDirectory() as data:
    proc = subprocess.Popen([str(binary), '--no-browser', '--port', str(port), '--data-dir', data],
                            env={**os.environ, 'SECRETARY_DATA_DIR': data})
    def request(path, body=None, token=None, headers=None):
        req = urllib.request.Request(f'http://127.0.0.1:{port}'+path,
                                     data=body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type':'application/json', 'X-Knowledge-Token':token or '',**(headers or {})})
        with opener.open(req, timeout=60 if path.endswith('/pdf-read') else 30 if path in ('/api/update/check','/api/model-api/test','/api/ask','/api/ingest') else 3) as response:
            return response.read()
    try:
        for _ in range(60):
            if proc.poll() is not None: raise RuntimeError('Frozen app exited before startup')
            try:
                status = json.loads(request('/api/status'))
                break
            except OSError: time.sleep(.5)
        else: raise RuntimeError('Frozen app did not start')
        assert status['settings']['company_mode'] is False
        for path in ('/', '/app.js', '/style.css', '/tutorial', '/tutorial.js', '/tutorial.css', '/i18n.js', '/i18n-data.js','/notes-ui.js','/note-attachments.js','/image-viewer.js','/extension-ui.js','/library-preview.js','/company-ai.js','/local-paths.js','/archive-actions.js','/bundle-ui.js','/attachment-order-ui.js','/additions-ui.js','/model-proxy-ui.js','/semantic-ui.js','/drafts.js','/uploads.js','/video-viewer.js'):
            assert request(path), path
        assert b'value="library"' in request('/') and b'semantic-settings' in request('/')
        semantic=json.loads(request('/api/semantic'))
        assert semantic['config']['enabled'] is False and semantic['indexed']==0
        assert json.loads(request('/api/ask',{'question':'Empty library question','library_chat':True,'history':[]},status['token']))['sources']==[]
        assert json.loads(request('/api/semantic/settings',semantic['config'],status['token']))['config']['enabled'] is False
        print('PASS: frozen library chat, semantic module and UI assets, empty-library answer and embedding settings without external model calls')
        extension=json.loads(request('/api/browser-extension/prepare',{},status['token']))
        extension_path=Path(extension['path'])
        assert extension_path.parent.resolve()==Path(data).resolve() and (extension_path/'manifest.json').is_file()
        with zipfile.ZipFile(io.BytesIO(request('/api/browser-extension/download'))) as extension_zip:
            assert extension_zip.read('Stellar-Capture-Extension/manifest.json')==(extension_path/'manifest.json').read_bytes()
        print('PASS: frozen bundled extension exported to stable folder and downloadable as loadable ZIP')
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
        assert request('/api/items/'+pdf['id']+'/thumbnail').startswith(b'\x89PNG')
        assert json.loads(request('/api/items/'+pdf['id']+'/quick-preview'))['all_attachments'][0]['name']=='aes-fixture.pdf'
        print('PASS: frozen PDFium first-page thumbnail and standalone attachment catalog')
        assert 'Encrypted PDF extraction fixture' in pdf['text'] and not pdf['error'], pdf
        for query in ('Encrypted%20readable','readable%20Encrypted'):
            matches=json.loads(request('/api/items?q='+query+'&kind=file'))
            assert [item['id'] for item in matches]==[pdf['id']], matches
        assert json.loads(request('/api/items?q=Encrypted%20nonexistent'))==[]
        group=json.loads(request('/api/ingest',{'text':'Combined synthetic context','attachments':[{'name':'sample.png','data':base64.b64encode(image.getvalue()).decode()},{'name':'context.txt','data':base64.b64encode(b'Attachment context').decode()}],'defer_summary':True},status['token']))['item']
        assert status['capabilities']['grouped_materials'] and len(group['attachments'])==2
        assert request('/api/items/'+group['id']+'/attachments/'+group['attachments'][0]['id']+'/preview')==image.getvalue()
        heic_original=(Path(__file__).resolve().parent.parent/'tests/fixtures/synthetic.heic').read_bytes()
        live_clip=(Path(__file__).resolve().parent.parent/'tests/fixtures/live-photo.mov').read_bytes()
        heic=json.loads(request('/api/ingest',{'attachments':[{'name':'synthetic.HEIC','data':base64.b64encode(heic_original).decode()},{'name':'synthetic.MOV','data':base64.b64encode(live_clip).decode()}],'defer_summary':True},status['token']))['item']
        photo=heic['all_attachments'][0];assert photo['media']=='image/heic'
        movie=heic['all_attachments'][1];assert photo['live_video']['preview_url']==movie['preview_url']
        assert request(movie['download_url'])==live_clip
        assert request(movie['preview_url'],headers={'Range':'bytes=0-63'})==live_clip[:64]
        assert request(photo['download_url'])==heic_original
        for url in (photo['preview_url'],photo['thumbnail_url']):
            with Image.open(io.BytesIO(request(url))) as decoded:
                decoded.load();assert decoded.size==(64,96)
        print('PASS: frozen HEIC native decoder, JPEG viewer preview, PNG thumbnail, paired Live Photo MOV with byte ranges and exact original downloads')
        request('/api/items/'+heic['id']+'/delete',{'confirmed':True,'expected_updated':heic['updated']},status['token'])
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
        grouped=json.loads(request('/api/ingest',{'text':'Related sources','attachments':[],'links':[f'http://127.0.0.1:{port}/first',f'http://127.0.0.1:{port}/second']},status['token']))['item']
        group_deadline=time.monotonic()+30
        while time.monotonic()<group_deadline:
            grouped=json.loads(request('/api/items/'+grouped['id']))
            if not grouped['append_busy']:break
            time.sleep(.1)
        assert not grouped['append_busy'], 'Grouped-link reading did not finish within 30 seconds'
        assert len(grouped['group_links'])==2 and all(link['state']=='unread' for link in grouped['group_links']), [(link['state'],link['warning']) for link in grouped['group_links']]
        request('/api/items/'+grouped['id']+'/delete',{'confirmed':True,'expected_updated':grouped['updated']},status['token'])
        print('PASS: frozen grouped links retain both unavailable sources in one archive')
        reparsed = json.loads(request('/api/items/'+pdf['id']+'/reextract', {}, status['token']))
        assert reparsed['parsed'] and reparsed['item']['id'] == pdf['id'], reparsed
        extra=json.loads(request('/api/items/'+pdf['id']+'/additions',{'text':'New supporting materials','attachments':[{'name':'new.png','data':base64.b64encode(image.getvalue()).decode()}],'expected_updated':reparsed['item']['updated'],'summarize':False},status['token']))
        batch=extra['item']['additions'][0]
        assert request('/api/items/'+pdf['id']+'/additions/'+batch['id']+'/attachments/'+batch['attachments'][0]['id']+'/preview')==image.getvalue()
        assert request('/api/items/'+pdf['id']+'/preview')==request('/api/items/'+pdf['id']+'/file')
        assert json.loads(request('/api/items?q=supporting'))[0]['id']==pdf['id']
        print('PASS: frozen append-to-PDF archive, appended-image preview, search and original PDF retained')
        removal=json.loads(request('/api/items/'+pdf['id']+'/additions/'+batch['id']+'/attachments/'+batch['attachments'][0]['id']+'/delete-attachment',{'confirmed':True,'expected_updated':extra['item']['updated']},status['token']))
        assert removal['ok'] and removal['recovery_saved']
        after_removal=json.loads(request('/api/items/'+pdf['id']))
        assert len(after_removal['additions'])==1 and after_removal['additions'][0]['attachments']==[] and len(after_removal['all_attachments'])==1
        assert request('/api/items/'+pdf['id']+'/preview')==request('/api/items/'+pdf['id']+'/file')
        print('PASS: frozen single attachment deletion preserves parent PDF, record and batch history with local recovery')
        if os.environ.get('SECRETARY_TLS_TEST') == '1':
            update = json.loads(request('/api/update/check', {}, status['token']))
            assert not update.get('error'), update
            print('PASS: frozen HTTPS update check with certificate verification enabled')
        stale=json.loads(request('/api/items/'+fixture['id']))
        request('/api/items/'+fixture['id']+'/title',{'title':'Changed while confirmation was open'},status['token'])
        request('/api/items/'+fixture['id']+'/trash',{'expected_updated':stale['updated']},status['token'])
        trashed=next(item for item in json.loads(request('/api/trash'))['items'] if item['id']==fixture['id'])
        assert trashed['title']=='Changed while confirmation was open'
        request('/api/trash/'+fixture['id']+'/restore',{},status['token'])
        assert json.loads(request('/api/items/'+fixture['id']))['note']==stale['note']
        print('PASS: frozen recycle-bin removal accepts completed background revisions and restore retains latest content')
        current=json.loads(request('/api/items/'+fixture['id']))
        deleted=json.loads(request('/api/items/'+fixture['id']+'/delete',{'confirmed':True,'expected_updated':current['updated']},status['token']))
        assert deleted['ok'] and not deleted['warning']
        assert [item['id'] for item in json.loads(request('/api/items'))]==[pdf['id']]
        with zipfile.ZipFile(io.BytesIO(request('/api/backup'))) as clean_backup:
            assert 'files/'+saved['note_images'][0]['id'] not in clean_backup.namelist()
        print('PASS: frozen confirmed archive deletion, attachment cleanup and unrelated PDF preserved')
        api_key=uuid.uuid4().hex;provider_calls=[];stream_release=threading.Event()
        class LocalAPI(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if self.path=='/api/embed':
                    assert body['model']=='synthetic-embedding' and body['truncate'] is False
                    vectors=[[1.,0.,0.] if 'battery' in value or '省电' in value else [0.,1.,0.] for value in body['input']]
                    raw=json.dumps({'embeddings':vectors}).encode()
                    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
                assert self.headers.get('Authorization')=='Bearer '+api_key and body['model']=='synthetic-model'
                provider_calls.append(True)
                prompt=str(body['messages'][-1]['content'])
                content='OK' if 'Reply with exactly OK' in prompt else json.dumps({'title':'Synthetic commands','summary':'Creates a synthetic compressed archive.','category':'Test','tags':['commands']})
                if prompt.startswith('为个人知识库生成全文检索词'):content=json.dumps({'queries':['省电']})
                if prompt.startswith(('请仅依据本次检索到的资料回答当前问题','先用一两句话直接回答当前问题')):content='Close background applications to improve battery life. [1]'
                if body.get('stream'):
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                    self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':content[:20]},'finish_reason':None}]})+'\n\n').encode());self.wfile.flush()
                    assert stream_release.wait(15),'Frozen stream was not observed'
                    self.wfile.write(('data: '+json.dumps({'choices':[{'delta':{'content':content[20:]},'finish_reason':'stop'}]})+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush();return
                raw=json.dumps({'choices':[{'message':{'content':content},'finish_reason':'stop'}]}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        provider=ThreadingHTTPServer(('127.0.0.1',0),LocalAPI);threading.Thread(target=provider.serve_forever,daemon=True).start()
        try:
            request('/api/settings',{'backend':'api','auto_ai':False,'model_api':{'base_url':f'http://127.0.0.1:{provider.server_port}/v1','model':'synthetic-model','api_key':api_key}},status['token'])
            assert json.loads(request('/api/model-api/test',{},status['token']))['ok']
            request('/api/settings',{'backend':'api','auto_ai':True},status['token'])
            archived=json.loads(request('/api/ingest',{'text':'tar -czf synthetic.tar.gz samples/','archive_only':True},status['token']))['item']
            assert archived['state']=='saved' and len(provider_calls)==1
            assert json.loads(request('/api/status'))['runtime']['processing']==0
            request('/api/items/'+archived['id'],{},status['token'])
            for _ in range(60):
                current=json.loads(request('/api/items/'+archived['id']))
                if current['state']=='ready' and current.get('summary_progress',{}).get('stage')=='done':break
                time.sleep(.2)
            else:raise AssertionError('Frozen manual summary did not complete')
            assert len(provider_calls)==2 and current['summary_progress']['lane']=='short'
            assert current['summary_progress']['stages_seconds'] and current['text']==archived['text']
            assert b'archive-only' in request('/') and b'summaryProgress' in request('/app.js')
            print('PASS: frozen archive-only skips enabled AI; manual summary uses short lane, retains original and reports stage timings')
            api_status=json.loads(request('/api/status'));assert api_status['model_api']['has_key'] and api_key not in json.dumps(api_status)
            with zipfile.ZipFile(io.BytesIO(request('/api/backup'))) as backup:assert all(api_key.encode() not in backup.read(name) for name in backup.namelist())
            request('/api/company-mode',{'enabled':True},status['token'])
            protected=json.loads(request('/api/ingest',{'url':'https://intranet.fixture.test/policy','text':'CompanyGuardFixture confidential synthetic source. '*10,'captured_at':'fixture','archive_only':True},status['token']))['item']
            assert protected['company_data'] and len(provider_calls)==2
            try:request('/api/items/'+protected['id'],{},status['token'])
            except urllib.error.HTTPError as error:
                assert error.code==409
                policy=json.loads(error.read())['company_model']
            else:raise AssertionError('Unconfirmed company material reached a model')
            assert len(provider_calls)==2
            request('/api/company-model/approve',{'fingerprint':policy['fingerprint'],'acknowledged':True},status['token'])
            request('/api/items/'+protected['id'],{},status['token'])
            for _ in range(60):
                current=json.loads(request('/api/items/'+protected['id']))
                if current['state']=='ready' and current.get('summary_progress',{}).get('stage')=='done':break
                time.sleep(.2)
            else:raise AssertionError('Confirmed company summary did not complete')
            assert len(provider_calls)==3 and current['text']==protected['text']
            request('/api/company-model/revoke',{},status['token'])
            try:request('/api/ask',{'question':'CompanyGuardFixture'},status['token'])
            except urllib.error.HTTPError as error:assert error.code==409
            else:raise AssertionError('Revoked company material reached library Q&A')
            assert len(provider_calls)==3
            request('/api/company-mode',{'enabled':False},status['token'])
            request('/api/ask',{'question':'CompanyGuardFixture'},status['token'])
            assert len(provider_calls)==4
            print('PASS: company mode defaults off; off mode has no extra approval; frozen company material blocked before confirmation; confirmed destination enables summary; revocation blocks retrieved company passages; no unapproved provider call')
            power=json.loads(request('/api/ingest',{'text':'Improve battery life by closing background applications.','archive_only':True},status['token']))['item']
            semantic_config={'enabled':True,'base_url':f'http://127.0.0.1:{provider.server_port}','model':'synthetic-embedding','min_score':0.45}
            assert json.loads(request('/api/semantic/test',semantic_config,status['token']))['dimensions']==3
            request('/api/semantic/settings',semantic_config,status['token'])
            for _ in range(100):
                index=json.loads(request('/api/semantic'))
                if index['indexed']==index['total'] and index['indexed']>0:break
                time.sleep(.1)
            else:raise AssertionError('Frozen semantic backfill did not complete')
            grounded=json.loads(request('/api/ask',{'question':'如何省电','library_chat':True,'history':[]},status['token']))
            assert '[1]' in grounded['answer'] and [source['item_id'] for source in grounded['sources']]==[power['id']],grounded
            request('/api/settings',{'backend':'api','auto_ai':False,'model_api':{'streaming':True}},status['token'])
            progress_id=uuid.uuid4().hex;streamed=[];stream_errors=[]
            def stream_question():
                try:streamed.append(json.loads(request('/api/ask',{'question':'如何省电','library_chat':True,'history':[],'force_refresh':True,'progress_id':progress_id},status['token'])))
                except Exception as error:stream_errors.append(error)
            streaming_thread=threading.Thread(target=stream_question,daemon=True);streaming_thread.start()
            try:
                for _ in range(80):
                    progress=json.loads(request('/api/ask/progress',{'progress_id':progress_id},status['token']))
                    if progress.get('partial'):break
                    if stream_errors:raise stream_errors[0]
                    time.sleep(.1)
                else:raise AssertionError('Frozen API worker did not expose streaming progress')
                assert not streamed,'The partial text must precede the final answer'
            finally:stream_release.set();streaming_thread.join(15)
            assert not stream_errors and streamed and streamed[0]['sources'][0]['item_id']==power['id'],stream_errors
            # Verify the frozen reconnectable API, including persistence without
            # a live browser/long HTTP request and idempotent start retries.
            stream_release.clear();chat_id=uuid.uuid4().hex;qid=uuid.uuid4().hex;mid=uuid.uuid4().hex;job_id=uuid.uuid4().hex
            chat={'id':chat_id,'title':'Frozen recovery fixture','updated':1,'messages':[{'id':qid,'role':'user','text':'如何省电','knowledgeQuestion':True},{'id':mid,'role':'assistant','text':'','pending':True,'questionId':qid}]}
            request('/api/conversations',{'activeId':chat_id,'conversations':[chat]},status['token'])
            payload={'progress_id':job_id,'chat_id':chat_id,'question_id':qid,'message_id':mid,'question':'如何省电','history':[],'force_refresh':True}
            before=len(provider_calls)
            request('/api/ask/start',payload,status['token']);request('/api/ask/start',payload,status['token'])
            try:
                for _ in range(80):
                    if json.loads(request('/api/ask/progress',{'progress_id':job_id},status['token'])).get('partial'):break
                    time.sleep(.1)
                else:raise AssertionError('Frozen background question did not stream')
            finally:stream_release.set()
            for _ in range(100):
                chats=json.loads((Path(data)/'conversations.json').read_text(encoding='utf-8'))['conversations']
                answer=next(c for c in chats if c['id']==chat_id)['messages'][-1]
                if answer.get('requestState')=='done':break
                time.sleep(.1)
            else:raise AssertionError('Frozen answer did not persist without a browser')
            assert answer['sources'][0]['item_id']==power['id'] and len(provider_calls)==before+2
            stale={**chat,'updated':int(time.time()*1000)+1000}
            request('/api/conversations',{'activeId':chat_id,'conversations':[stale]},status['token'])
            restored=json.loads(request('/api/ask/job',{'progress_id':job_id,'chat_id':chat_id,'message_id':mid},status['token']))
            assert restored['message']['text']==answer['text'] and restored['message']['requestState']=='done'
            print('PASS: frozen background question, idempotent start, streamed progress, closed-page result persistence and stale-client fencing')
            catalog=json.loads(request('/api/library/catalog',{'queries':['battery'],'offset':0},status['token']))
            assert power['id'] in [source['item_id'] for source in catalog['sources']]
            print('PASS: frozen API-worker SSE text before completion, authenticated partial progress, checked final citations and complete catalog endpoint')
            request('/api/semantic/settings',{**semantic_config,'enabled':False},status['token'])
            print('PASS: frozen embedding worker, SQLite vector cache and semantic-only library answer with source; local deterministic API/embedding fixtures')
            request('/api/settings',{'backend':'codex','auto_ai':False},status['token'])
            print('PASS: frozen custom API worker, local HTTP request, masked status and credential-free backup')
        finally:stream_release.set();provider.shutdown();provider.server_close()
        # Prepare an isolated working copy without launching an external GUI app.
        sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
        from secretary.core import Archive
        from secretary.attachment_editor import local_copy
        editable=json.loads(request('/api/ingest',{'filename':'editable.txt','data':base64.b64encode(b'Old frozen attachment content').decode(),'archive_only':True},status['token']))['item']
        working,_,_=local_copy(Archive(data,recover=False),editable['id']);working.write_bytes(b'NewFrozenEditorKeyword')
        changed=json.loads(request('/api/items/'+editable['id']+'/editor/save',{},status['token']))
        assert changed['changed'] and request('/api/items/'+editable['id']+'/file')==b'NewFrozenEditorKeyword'
        assert json.loads(request('/api/items?q=NewFrozenEditorKeyword'))[0]['id']==editable['id']
        assert b'data-editor-action' in request('/bundle-ui.js')
        print('PASS: frozen external-edit save-back, updated original bytes, searchable text and editor controls')
        from test_large_pdf_preview import fixture as large_pdf_fixture
        source=Path(data)/'large-preview.pdf';large_pdf_fixture(source,padding=51*1024*1024)
        upload=json.loads(request('/api/uploads/start',{'name':'large-preview.pdf','size':source.stat().st_size},status['token']))
        with source.open('rb') as stream:
            offset=0
            while chunk:=stream.read(4*1024*1024):
                value=json.loads(request('/api/uploads/'+upload['id']+'/chunk',chunk,status['token'],{'X-Upload-Offset':str(offset)}));offset=value['offset']
        large=json.loads(request('/api/ingest',{'attachments':[{'name':'large-preview.pdf','upload_id':upload['id']}],'archive_only':True},status['token']))['item']
        assert 'PAGETOKEN5' in large['text'] and 'PAGETOKEN6' not in large['text'] and '共 6 页' in large['text']
        leaf=large['all_attachments'][0];assert request(leaf['thumbnail_url']).startswith(b'\x89PNG')
        assert request(leaf['preview_url'],headers={'Range':'bytes=0-4'})==b'%PDF-'
        request('/api/uploads/'+upload['id']+'/cancel',{},status['token'])
        print('PASS: frozen 51 MB chunked PDF, disk-backed first-five-page extraction, native PDFium thumbnail, original byte range, partial scope and no sixth-page indexing')
        if json.loads(request('/api/status')).get('ocr',{}).get('available'):
            from PIL import ImageDraw,ImageFont
            image=Image.new('RGB',(1400,300),'white');ImageDraw.Draw(image).text((30,80),'STELLAR LOCAL SCAN 58319',fill='black',font=ImageFont.load_default(size=60))
            document=io.BytesIO();image.save(document,'PDF')
            scan=json.loads(request('/api/ingest',{'filename':'local-scan.pdf','data':base64.b64encode(document.getvalue()).decode(),'archive_only':True},status['token']))['item']
            recognized=json.loads(request('/api/items/'+scan['id']+'/pdf-read',{'start':1,'end':1,'ocr':True},status['token']))
            assert '58319' in recognized['pages'][0]['text'],recognized
            assert json.loads(request('/api/items?q=58319'))
            print('PASS: frozen native local OCR, searchable scanned page and zero cloud/model calls')
        request('/api/shutdown', {}, status['token'])
        assert proc.wait(timeout=15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        log = Path(data)/'app.log'
        if log.exists(): print(log.read_text(encoding='utf-8'))
