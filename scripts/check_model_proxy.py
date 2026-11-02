"""Verify real model transports through a local CONNECT proxy, with a temporary CA."""
import argparse,json,os,ssl,subprocess,sys,tempfile,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary import ai,model_api

parser=argparse.ArgumentParser();parser.add_argument('--gemini-cli',default=ai.executable('gemini'));args=parser.parse_args()
requests=[]
class Proxy(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def do_CONNECT(self):
        if self.path not in ('api.proxy.invalid:443','gemini.proxy.invalid:443'):
            self.send_error(403);return
        target=self.path;self.connection.settimeout(20)
        self.send_response(200,'Connection established');self.end_headers();self.wfile.flush()
        secured=self.server.tls.wrap_socket(self.connection,server_side=True)
        try:
            reader=secured.makefile('rb');line=reader.readline().decode();headers={}
            while True:
                raw=reader.readline()
                if raw in (b'\r\n',b'\n',b''):break
                key,value=raw.decode().split(':',1);headers[key.lower()]=value.strip()
            body=json.loads(reader.read(int(headers.get('content-length','0'))))
            requests.append((target,line,body))
            if target.startswith('api.'):
                value={'choices':[{'message':{'content':'Proxy fixture OK'},'finish_reason':'stop'}]};content_type='application/json';payload=json.dumps(value).encode()
            elif 'countTokens' in line:
                content_type='application/json';payload=b'{"totalTokens":10}'
            else:
                value={'candidates':[{'content':{'role':'model','parts':[{'text':'Proxy fixture OK'}]},'finishReason':'STOP'}],
                       'usageMetadata':{'promptTokenCount':10,'candidatesTokenCount':10,'totalTokenCount':20}}
                content_type='text/event-stream';payload=('data: '+json.dumps(value)+'\n\n').encode()
            secured.sendall(f'HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n'.encode()+payload)
            reader.close()
        finally:secured.close();self.close_connection=True

with tempfile.TemporaryDirectory(prefix='stellar-proxy-test-') as root:
    root=Path(root);cert=root/'ca.pem';key=root/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(cert),
                    '-subj','/CN=api.proxy.invalid','-addext','subjectAltName=DNS:api.proxy.invalid,DNS:gemini.proxy.invalid'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);tls.load_cert_chain(cert,key)
    server=ThreadingHTTPServer(('127.0.0.1',0),Proxy);server.tls=tls
    threading.Thread(target=server.serve_forever,daemon=True).start()
    proxy={'mode':'custom','url':f'http://127.0.0.1:{server.server_port}'}
    env={key:value for key,value in os.environ.items() if key not in (*ai.network.PROXY_KEYS,'GOOGLE_API_KEY','GOOGLE_APPLICATION_CREDENTIALS','GOOGLE_GENAI_USE_VERTEXAI')}
    env.update(SSL_CERT_FILE=str(cert),NODE_EXTRA_CA_CERTS=str(cert))
    try:
        with patch.dict(os.environ,env,clear=True):
            config={**model_api.DEFAULT,'base_url':'https://api.proxy.invalid/v1','use_key':False,'_proxy':proxy}
            assert ai.run('Synthetic connection test',config)=='Proxy fixture OK'
            print('PASS: real API worker HTTPS request tunneled through configured HTTP proxy with TLS verification')
            if args.gemini_cli:
                home=root/'gemini-home';settings=home/'.gemini/settings.json';settings.parent.mkdir(parents=True)
                settings.write_text(json.dumps({'security':{'auth':{'selectedType':'gemini-api-key'}},'model':{'name':'gemini-2.5-flash'}}))
                with patch.dict(os.environ,{'GEMINI_CLI_HOME':str(home),'GEMINI_API_KEY':'synthetic-local-test-key','GOOGLE_GEMINI_BASE_URL':'https://gemini.proxy.invalid'}),patch.object(ai,'executable',return_value=args.gemini_cli):
                    assert ai.run('Synthetic connection test',ai.CLIBackend('gemini',proxy),timeout=60)=='Proxy fixture OK'
                assert any(target.startswith('gemini.') for target,_,_ in requests)
                print('PASS: real Gemini CLI HTTPS request tunneled through the same configured HTTP proxy')
            assert any(target.startswith('api.') for target,_,_ in requests)
            print('PASS: proxy recorded synthetic requests; no cloud model, real account or global proxy changes used')
    finally:server.shutdown();server.server_close()
