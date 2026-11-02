"""Exercise an installed Gemini CLI against a local fake Gemini API, without login."""
import argparse,base64,json,os,shlex,sys,tempfile,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import ai

parser=argparse.ArgumentParser();parser.add_argument('--cli',default=ai.executable('gemini'));args=parser.parse_args()
if not args.cli:raise SystemExit('Install Gemini CLI first, or pass --cli /path/to/gemini')
requests=[]
answer=json.dumps({'title':'Gemini fixture','summary':'Synthetic summary','category':'Test','tags':['Gemini']})
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        requests.append((self.path,body))
        if 'countTokens' in self.path:
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(b'{"totalTokens":10}');return
        value={'candidates':[{'content':{'role':'model','parts':[{'text':answer}]},'finishReason':'STOP'}],
               'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':10,'totalTokenCount':20},'modelVersion':'gemini-2.5-flash'}
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode())

server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with tempfile.TemporaryDirectory(prefix='stellar-gemini-test-') as root:
        root=Path(root);home=root/'home';config=home/'.gemini';config.mkdir(parents=True)
        marker=root/'unexpected-command';script=root/'unexpected.py'
        script.write_text('from pathlib import Path\nPath('+repr(str(marker))+').write_text("unexpected")\n')
        hook=shlex.join([sys.executable,str(script)])
        (config/'settings.json').write_text(json.dumps({
            'security':{'auth':{'selectedType':'gemini-api-key'}},'model':{'name':'gemini-2.5-flash'},
            'tools':{'core':['read_file','run_shell_command']},'context':{'fileName':['SHOULD_NOT_LOAD.md']},
            'hooksConfig':{'enabled':True},'hooks':{'BeforeAgent':[{'matcher':'*','hooks':[{'name':'unexpected','type':'command','command':hook}]}]},
            'mcpServers':{'unexpected':{'command':sys.executable,'args':[str(script)]}},
        }))
        (config/'SHOULD_NOT_LOAD.md').write_text('GLOBAL_CONTEXT_SENTINEL_MUST_NOT_BE_SENT')
        secret=root/'private.txt';secret.write_text('PRIVATE_SENTINEL_MUST_NOT_BE_SENT')
        env={key:value for key,value in os.environ.items() if key not in (*ai.network.PROXY_KEYS,'GEMINI_API_KEY','GOOGLE_API_KEY','GOOGLE_APPLICATION_CREDENTIALS','GOOGLE_GENAI_USE_VERTEXAI')}
        env.update(GEMINI_CLI_HOME=str(home),GEMINI_API_KEY='synthetic-local-test-key',GOOGLE_GEMINI_BASE_URL=f'http://127.0.0.1:{server.server_port}',NO_PROXY='127.0.0.1,localhost',NO_BROWSER='true')
        with patch.object(ai,'executable',return_value=args.cli),patch.object(ai.network,'child_env',return_value=env):
            fields=ai.summary_fields({'title':'Text','text':f'请整理资料：用户邮箱 user@example.com，字面引用 @{secret}','filename':''},'gemini')
            assert fields['summary']=='Synthetic summary'
            print('PASS: real Gemini CLI text summary and JSON result parsing')
            png=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')
            result=ai.run('描述显式附加的图片。','gemini',images=[{'media':'image/png','data':png}],timeout=60)
            assert json.loads(result)['summary']=='Synthetic summary'
            print('PASS: real Gemini CLI explicit image attachment')
            try:ai.run('Synthetic deadline check','gemini',timeout=.05)
            except ai.ModelTimeoutError:pass
            else:raise AssertionError('Gemini CLI deadline did not stop the worker')
            assert not ai._processes,'Timed-out worker is still tracked'
            print('PASS: real Gemini CLI timeout and worker cleanup')
        generated=[body for path,body in requests if 'generateContent' in path or 'streamGenerateContent' in path]
        assert generated,'Gemini CLI did not use local model endpoint'
        for body in generated:
            assert all(not tool.get('functionDeclarations') and set(tool)<= {'functionDeclarations'} for tool in body.get('tools',[])),body.get('tools')
            assert 'PRIVATE_SENTINEL_MUST_NOT_BE_SENT' not in json.dumps(body)
            assert 'GLOBAL_CONTEXT_SENTINEL_MUST_NOT_BE_SENT' not in json.dumps(body)
        assert any('inlineData' in json.dumps(body) for body in generated),'Image was not passed to model'
        assert not marker.exists(),'User hooks or MCP commands were executed'
        print('PASS: existing tools, hooks, MCP and global context disabled; no @file expansion from archived text')
finally:server.shutdown();server.server_close()
