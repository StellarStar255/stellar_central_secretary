"""Exercise the native opaque relay against an isolated real mobile TLS gateway."""
import json,os,secrets,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from secretary.server import Service
from secretary.mobile import digest

with tempfile.TemporaryDirectory(prefix='stellar-wifi-tls-') as folder:
    service=Service(folder)
    gateway=service.mobile;gateway.enable(advertise=False,bind='127.0.0.1')
    credential=secrets.token_urlsafe(48)
    gateway.state['devices']['fixture']={'hash':digest(credential),'name':'Fixture phone','created':'fixture'}
    env={**os.environ,'DEVELOPER_DIR':'/Applications/Xcode.app/Contents/Developer','STELLAR_TLS_FIXTURE_PORT':str(gateway.server.server_port),'STELLAR_TLS_FIXTURE_PIN':gateway.fingerprint,'STELLAR_TLS_FIXTURE_CREDENTIAL':credential}
    try:
        subprocess.run(['swift','test','--package-path','ios','--scratch-path','/tmp/stellar-pairing-network-tests'],env=env,check=True)
        print('PASS: real TLS, certificate pinning and three authenticated gateway requests over one reused native-relay TLS connection')
    finally:service.close()
