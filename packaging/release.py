"""Repeatable Stellar Secretary release operations; credentials stay in existing stores."""
import argparse,hashlib,json,os,plistlib,re,shutil,sqlite3,subprocess,sys,tempfile,time,urllib.request,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
REPO='StellarStar255/stellar_central_secretary'

def require(value,message):
    if not value:raise RuntimeError(message)
def run(*args,**kwargs):return subprocess.run([str(arg) for arg in args],cwd=ROOT,check=True,**kwargs)
def output(*args):return subprocess.check_output([str(arg) for arg in args],cwd=ROOT,text=True)
def gh(*args):return json.loads(output('gh',*args))
def digest(path):return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()
def verify_assets(release,expected):
    assets={asset['name']:asset for asset in release['assets']}
    require(set(assets)==set(expected),'Release asset set differs')
    for name,value in expected.items():
        actual=assets[name]
        require(actual['state']=='uploaded' and all(actual.get(k)==v for k,v in value.items()),'Asset mismatch: '+name)
def manifest_entries(text):
    entries={}
    for line in text.splitlines():
        parts=line.split(None,1)
        require(len(parts)==2 and re.fullmatch('[a-f0-9]{64}',parts[0]),'Invalid checksum line')
        name=parts[1].strip()
        require(name==Path(name).name and name not in entries,'Invalid or duplicate asset name')
        entries[name]=parts[0]
    return entries

class Release:
    def __init__(self):
        self.version=re.search(r"__version__ = '([^']+)'",(ROOT/'secretary/__init__.py').read_text())[1]
        require(re.fullmatch(r'\d+\.\d+\.\d+',self.version),'Invalid version')
        self.tag='v'+self.version
        self.state=ROOT/'build/release-state'/self.version;self.state.mkdir(parents=True,exist_ok=True)
        self.app=ROOT/'dist'/('release-'+self.tag)/'Stellar Secretary.app'
        self.dmg=ROOT/'dist'/f'Stellar-Secretary-{self.version}-macos-arm64.dmg'
    def save(self,name,value):(self.state/name).write_text(json.dumps(value,indent=2))
    def load(self,name):return json.loads((self.state/name).read_text())
    def view(self):
        result=gh('release','view',self.tag,'--repo',REPO,'--json','tagName,isDraft,url,assets')
        require(result['tagName']==self.tag,'Unexpected release tag');return result
    def ci(self):
        sha=output('git','rev-parse',self.tag+'^{commit}').strip()
        runs=gh('run','list','--repo',REPO,'--workflow','release.yml','--commit',sha,'--json','databaseId,headSha,status,conclusion','--limit','10')
        matches=[r for r in runs if r['headSha']==sha]
        require(matches,'No CI run for tagged source')
        result=gh('run','view',str(matches[0]['databaseId']),'--repo',REPO,'--json','databaseId,status,conclusion,headSha,jobs')
        return result
    def require_ci(self):
        ci=self.ci();require(ci['status']=='completed' and ci['conclusion']=='success','CI has not completed successfully')
        names=[job['name'].lower() for job in ci['jobs'] if job['conclusion']=='success']
        require(all(any(platform in name for name in names) for platform in ('macos','windows','linux','release')),'Missing successful platform/release job')
        return ci
    def build(self):
        for name in ('signed-mac.json','expected.json'):(self.state/name).unlink(missing_ok=True)
        run(sys.executable,'-m','PyInstaller','packaging/stellar-secretary.spec','--noconfirm','--distpath',self.app.parent,'--workpath',ROOT/'build'/('release-'+self.tag),env={**os.environ,'PYINSTALLER_CONFIG_DIR':str(ROOT/'build/pyinstaller-cache')})
    def smoke(self):
        run(sys.executable,'packaging/smoke.py',env={**os.environ,'SECRETARY_SMOKE_BINARY':str(self.app/'Contents/MacOS/Stellar Secretary')})
    def sign(self,args):
        require(args.identity and args.profile,'Signing identity and keychain profile are required')
        run('bash','packaging/macos_sign_notarize.sh',self.app,self.dmg,env={**os.environ,'MACOS_SIGN_IDENTITY':args.identity,'NOTARY_PROFILE':args.profile})
    def verify_mac(self,args):
        require(args.team_id,'Expected Developer ID team is required')
        run('xcrun','stapler','validate',self.dmg)
        run('spctl','-a','-t','open','--context','context:primary-signature',self.dmg)
        with tempfile.TemporaryDirectory(prefix='stellar-release-dmg-') as folder:
            mount=Path(folder)/'mounted';mount.mkdir()
            run('hdiutil','attach','-readonly','-nobrowse','-mountpoint',mount,self.dmg,stdout=subprocess.DEVNULL)
            try:
                app=mount/'Stellar Secretary.app'
                require(plistlib.loads((app/'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']==self.version,'Wrong DMG version')
                run('codesign','--verify','--deep','--strict',app)
                result=run('codesign','-dvv',app,capture_output=True,text=True)
                require('TeamIdentifier='+args.team_id in result.stderr,'Unexpected signing team')
                files=[Path('Contents/MacOS/Stellar Secretary')]+[p.relative_to(self.app) for p in (self.app/'Contents/Resources/secretary/static').rglob('*') if p.is_file()]
                for name in files:require(digest(app/name)==digest(self.app/name),'DMG differs from tested app: '+str(name))
            finally:run('hdiutil','detach',mount,stdout=subprocess.DEVNULL)
        self.save('signed-mac.json',{'name':self.dmg.name,'size':self.dmg.stat().st_size,'digest':digest(self.dmg),'team_id':args.team_id,'app_digest':digest(self.app/'Contents/MacOS/Stellar Secretary')})
        print('PASS: notarized DMG, expected signature, version, executable and all UI assets')
    def prepare(self):
        self.require_ci();release=self.view();require(release['isDraft'],'Only prepare an unpublished draft')
        run('gh','release','download',self.tag,'--repo',REPO,'--pattern','SHA256SUMS.txt','--dir',self.state,'--clobber')
        manifest=self.state/'SHA256SUMS.txt';assets={a['name']:a for a in release['assets']};entries=manifest_entries(manifest.read_text())
        names={'demo.gif','demo-en.gif','tutorial.html',self.dmg.name,f'Stellar-Secretary-{self.version}-windows-x64-setup.exe',f'Stellar-Secretary-{self.version}-linux-x64.deb',f'Stellar-Secretary-{self.version}-linux-x64.tar.gz'}
        require(set(entries)==names and set(assets)==names|{'SHA256SUMS.txt'},'Unexpected CI installer set')
        require(digest(manifest)==assets['SHA256SUMS.txt']['digest'],'CI manifest digest mismatch')
        for name,sha in entries.items():require(assets[name]['state']=='uploaded' and assets[name]['digest']=='sha256:'+sha,'CI asset digest mismatch: '+name)
        mac=self.load('signed-mac.json');require(mac['app_digest']==digest(self.app/'Contents/MacOS/Stellar Secretary'),'Built app changed after verification');require(mac['name']==self.dmg.name and mac['digest']==digest(self.dmg) and mac['size']==self.dmg.stat().st_size,'Signed Mac package changed')
        entries[mac['name']]=mac['digest'].split(':')[1]
        manifest.write_text(''.join(sha+'  '+name+'\n' for name,sha in sorted(entries.items())))
        expected={name:{key:a[key] for key in ('size','digest')} for name,a in assets.items()}
        expected[mac['name']]={key:mac[key] for key in ('size','digest')};expected['SHA256SUMS.txt']={'size':manifest.stat().st_size,'digest':digest(manifest)}
        self.save('expected.json',expected);self.save('baseline.json',release)
        print('PASS: 8 CI assets verified; signed Mac replacement and checksums prepared')
    def upload(self):
        require(self.view()['isDraft'],'Refuse to overwrite a public release')
        expected=self.load('expected.json')
        for path in (self.dmg,self.state/'SHA256SUMS.txt'):require(digest(path)==expected[path.name]['digest'],'Local upload changed')
        run('gh','release','upload',self.tag,self.dmg,self.state/'SHA256SUMS.txt','--repo',REPO,'--clobber')
        verify_assets(self.view(),expected);print('PASS: all 8 remote assets verified')
    def publish(self):
        self.require_ci();release=self.view();verify_assets(release,self.load('expected.json'))
        if release['isDraft']:run('gh','release','edit',self.tag,'--repo',REPO,'--draft=false','--latest')
        release=self.view();verify_assets(release,self.load('expected.json'));require(not release['isDraft'],'Release remains a draft')
        self.save('published.json',release);print('PASS: published '+release['url'])
    def install(self,args):
        # This helper only upgrades the known running macOS installation.
        mac=self.load('signed-mac.json');require(digest(self.app/'Contents/MacOS/Stellar Secretary')==mac['app_digest'],'App differs from verified DMG');require(digest(self.dmg)==mac['digest'],'Verified DMG changed')
        run('codesign','--verify','--deep','--strict',self.app)
        signature=run('codesign','-dvv',self.app,capture_output=True,text=True)
        require('TeamIdentifier='+mac['team_id'] in signature.stderr,'App signing team changed')
        target=Path('/Applications/Stellar Secretary.app');base='http://127.0.0.1:8768'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def get(path):
            with opener.open(base+path,timeout=3) as response:return response.read()
        status=json.loads(get('/api/status'))
        require(status.get('application')=='stellar-central-secretary' and not any(status.get('runtime',{}).values()),'Wrong application or active tasks; installation deferred')
        require(status.get('update',{}).get('phase') not in ('downloading','verifying','installing'),'Another update is active')
        data=Path(status['data_dir']).resolve();require(data==Path.home()/'Library/Application Support/Stellar Secretary','Unexpected data directory')
        def fingerprint():
            with sqlite3.connect('file:'+str(data/'archive.sqlite3')+'?mode=ro',uri=True) as db:
                # Every persisted column, including additions, is compared.
                rows=db.execute('SELECT * FROM items ORDER BY id').fetchall()
            return hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest(),len(rows)
        before,count=fingerprint();mode=status['settings'].get('company_mode',False)
        pid_text=output('/usr/sbin/lsof','-t','-iTCP:8768','-sTCP:LISTEN').split();require(len(pid_text)==1,'Unexpected listening processes');pid=int(pid_text[0])
        require(output('/bin/ps','-p',str(pid),'-o','comm=').strip()==str(target/'Contents/MacOS/Stellar Secretary'),'Unexpected application process')
        nonce=uuid.uuid4().hex[:10];staging=target.with_name('.Stellar Secretary.staging-'+nonce+'.app');backup=target.with_name('.Stellar Secretary.backup-'+nonce+'.app')
        shutil.copytree(self.app,staging,symlinks=True);run('codesign','--verify','--deep','--strict',staging)
        request=urllib.request.Request(base+'/api/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-Knowledge-Token':status['token']})
        with opener.open(request,timeout=5) as response:require(response.status==200,'Shutdown failed')
        for _ in range(100):
            try:os.kill(pid,0)
            except ProcessLookupError:break
            time.sleep(.2)
        else:raise RuntimeError('Old application still running; replacement deferred')
        target.rename(backup)
        try:staging.rename(target)
        except BaseException:backup.rename(target);raise
        run('/usr/bin/open',target)
        for _ in range(100):
            try:
                current=json.loads(get('/api/status'))
                if current.get('version')==self.version:break
            except OSError:pass
            time.sleep(.2)
        else:raise RuntimeError('Updated app failed to start; previous app preserved at '+str(backup))
        require(current['data_dir']==str(data) and current['settings'].get('company_mode',False)==mode,'Data directory or company mode changed')
        require(fingerprint()==(before,count),'Archived data changed during installation')
        require(digest(target/'Contents/MacOS/Stellar Secretary')==digest(self.app/'Contents/MacOS/Stellar Secretary'),'Installed binary differs')
        for name in ('bundle-ui.js','library-preview.js','image-viewer.js'):
            require(get('/'+name)==(self.app/'Contents/Resources/secretary/static'/name).read_bytes(),'Running UI differs: '+name)
        print(f'PASS: installed {self.tag}; all columns of {count} records preserved; backup: {backup}')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('ci','build-mac','smoke-mac','sign-mac','verify-mac','prepare','upload','publish','install-local'))
    parser.add_argument('--identity',default=os.environ.get('MACOS_SIGN_IDENTITY'))
    parser.add_argument('--profile',default=os.environ.get('NOTARY_PROFILE'))
    parser.add_argument('--team-id')
    args=parser.parse_args();release=Release()
    if args.action=='ci':print(json.dumps(release.ci(),indent=2));return
    actions={'build-mac':release.build,'smoke-mac':release.smoke,'prepare':release.prepare,'upload':release.upload,'publish':release.publish}
    if args.action in actions:actions[args.action]()
    else:{'sign-mac':release.sign,'verify-mac':release.verify_mac,'install-local':release.install}[args.action](args)
if __name__=='__main__':main()
