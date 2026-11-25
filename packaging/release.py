"""Repeatable Stellar Secretary release operations; credentials stay in existing stores."""
import socket
import argparse,hashlib,json,os,plistlib,re,shutil,sqlite3,subprocess,sys,tempfile,time,urllib.request,uuid
from contextlib import closing
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
REPO='StellarStar255/stellar_central_secretary'
sys.path.insert(0,str(ROOT))
from secretary import library_location
from secretary.update_retention import remove_artifacts, version_key


def old_build_artifacts(root, current, released):
    limit=version_key(current)
    for folder in ('build', 'dist'):
        parent=root/folder
        if parent.is_symlink() or not parent.is_dir():
            continue
        for path in parent.iterdir():
            if path.is_symlink():
                continue
            if path.is_dir():
                match=re.fullmatch(r'release-v(\d+(?:\.\d+\.\d+)?)',path.name)
            elif folder=='dist' and path.is_file():
                match=re.fullmatch(r'Stellar-Secretary-(\d+\.\d+\.\d+)-(?:macos-arm64\.dmg|browser-extension\.zip)',path.name)
            else:
                continue
            if match:
                version=match[1] if '.' in match[1] else '0.1.'+match[1]
                if version_key(version)<limit and version in released:
                    yield path


def mac_rollback_copies(target):
    copies=[]
    for path in target.parent.glob('.Stellar Secretary.backup-*.app'):
        if path.is_symlink() or not re.fullmatch(r'\.Stellar Secretary\.backup-[a-f0-9]{10}\.app',path.name):
            continue
        try:
            identifier=plistlib.loads((path/'Contents/Info.plist').read_bytes())['CFBundleIdentifier']
            if identifier=='io.github.stellarstar255.stellar-secretary' and (path/'Contents/MacOS/Stellar Secretary').is_file():
                copies.append(path)
        except (OSError, ValueError, KeyError) as error:
            print(f'Skipping unreadable rollback copy {path}: {error}',file=sys.stderr)
    return copies


def unused_mac_rollbacks(target):
    copies=mac_rollback_copies(target)
    commands=output('/bin/ps','-axo','command=').splitlines()
    return [path for path in copies if not any(str(path)+'/' in line for line in commands)]

def require(value,message):
    if not value:raise RuntimeError(message)
def run(*args,**kwargs):return subprocess.run([str(arg) for arg in args],cwd=ROOT,check=True,**kwargs)
def output(*args):return subprocess.check_output([str(arg) for arg in args],cwd=ROOT,text=True)
def gh(*args):return json.loads(output('gh',*args))
def digest(path):
    with path.open('rb') as stream:
        return 'sha256:'+hashlib.file_digest(stream,'sha256').hexdigest()
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

def require_install_idle(status):
    require(status.get('application') == 'stellar-central-secretary', 'Unexpected application')
    require(not any(status['runtime'].values()), 'Active tasks; installation deferred')
    require(status['update'].get('phase') not in ('downloading', 'verifying', 'installing'), 'Another update is active')
    require(status['backup'].get('state') != 'creating' and not status['library_location'].get('pending'),
            'Backup or library migration pending; installation deferred')


def listener_pid(port):
    listeners=output('/usr/sbin/lsof','-t',f'-iTCP:{port}','-sTCP:LISTEN').split()
    require(len(listeners)==1, 'Expected one listening process')
    return int(listeners[0])


def verify_install_process(pid, target, status):
    binary=target/'Contents/MacOS/Stellar Secretary'
    executable=output('/bin/ps','-p',str(pid),'-o','comm=').strip()
    if executable==str(binary):
        return
    # macOS framework Python may report Python.app as its executable.
    python=output('/bin/ps','-p',str(os.getpid()),'-o','comm=').strip()
    command=output('/bin/ps','-ww','-p',str(pid),'-o','command=').strip()
    interpreter, separator, arguments=command.partition(' -m ')
    allowed={Path(python).resolve(), (ROOT/'.venv/bin/python').resolve()}
    cwd=output('/usr/sbin/lsof','-a','-p',str(pid),'-d','cwd','-Fn').splitlines()
    require(Path(executable).resolve() in allowed and separator and
            Path(interpreter).resolve() in allowed and
            arguments.partition(' ')[0] in ('secretary.launcher','secretary.server') and
            'n'+str(ROOT) in cwd and status.get('source_service')=={'pid':pid,'root':str(ROOT)},
            'Unexpected application process; installation deferred')


def archive_fingerprint(database, preserved_columns):
    columns=','.join('"'+name.replace('"','""')+'"' for name in preserved_columns)
    checksum=hashlib.sha256(b'[')
    count=0
    with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
        for row in db.execute('SELECT '+columns+' FROM items ORDER BY id'):
            if count:
                checksum.update(b', ')
            # SQLite BLOBs are distinguished from text and numeric values.
            values=[{'blob':value.hex()} if isinstance(value,bytes) else value for value in row]
            checksum.update(json.dumps(values,ensure_ascii=False).encode())
            count+=1
    checksum.update(b']')
    return checksum.hexdigest(), count


def launch_mac(target):
    # Keep Launch Services' completion handle. A missing HTTP response alone
    # cannot distinguish a crashed application from a slow, live one.
    return subprocess.Popen(['/usr/bin/open','-W',str(target)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def wait_mac_status(get, launch, version):
    for _ in range(100):
        if launch.poll() is not None:
            break
        try:
            current=json.loads(get('/api/status'))
        except OSError:
            time.sleep(.2)
            continue
        require(current.get('application')=='stellar-central-secretary' and current.get('version')==version,
                'Unexpected service after launch; inspect the installation')
        return current
    return None


def library_file_state(data):
    # Even a settings/schema change outside the items table warrants inspection.
    state=[]
    for name in ('archive.sqlite3','archive.sqlite3-wal','conversations.json'):
        path=data/name
        try:
            info=path.stat()
        except FileNotFoundError:
            state.append(None)
        else:
            state.append((info.st_ino,info.st_size,info.st_mtime_ns))
    return state


def recover_mac_launch(target,backup,port,data,get,baseline,columns,mode):
    previous_version=plistlib.loads((backup/'Contents/Info.plist').read_bytes())['CFBundleShortVersionString']
    failed=target.with_name(backup.name.replace('.backup-','.failed-',1))
    binary=target/'Contents/MacOS/Stellar Secretary'
    with library_location.lease(data),socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        probe.bind(('127.0.0.1',port))
        probe.listen(1)
        require(str(binary) not in {line.strip() for line in output('/bin/ps','-axo','comm=').splitlines()},
                'New application is still running')
        require(library_file_state(data)==baseline[0] and archive_fingerprint(data/'archive.sqlite3',columns)==baseline[1],
                'Library changed after launch; inspect the library before recovery')
        require(not library_location.status(data).get('pending'), 'Library migration pending')
        require(not failed.exists(), 'Failed application destination already exists')
        target.rename(failed)
        try:
            backup.rename(target)
        except OSError:
            failed.rename(target)
            raise
    restored=wait_mac_status(get,launch_mac(target),previous_version)
    require(restored is not None and restored['data_dir']==str(data)
            and restored['settings'].get('company_mode',False)==mode, 'Previous app did not reopen the original library')
    require(output('/bin/ps','-p',str(listener_pid(port)),'-o','comm=').strip()==str(binary),
            'Previous app does not own the listening port')
    require(archive_fingerprint(data/'archive.sqlite3',columns)==baseline[1], 'Library verification after recovery failed')
    return failed


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
        try:
            released={path.name for path in self.state.parent.iterdir() if (path/'published.json').is_file()}
            for path in remove_artifacts(old_build_artifacts(ROOT,self.version,released)):
                print('Removed old build artifact:',path)
        except OSError as error:
            print(f'Could not finish old build cleanup: {error}',file=sys.stderr)
    def install(self,args):
        self.install_mac(Path('/Applications/Stellar Secretary.app'),8768)

    def install_mac(self,target,port):
        # This helper only upgrades the known running macOS installation.
        mac=self.load('signed-mac.json');require(digest(self.app/'Contents/MacOS/Stellar Secretary')==mac['app_digest'],'App differs from verified DMG');require(digest(self.dmg)==mac['digest'],'Verified DMG changed')
        run('codesign','--verify','--deep','--strict',self.app)
        signature=run('codesign','-dvv',self.app,capture_output=True,text=True)
        require('TeamIdentifier='+mac['team_id'] in signature.stderr,'App signing team changed')
        base=f'http://127.0.0.1:{port}'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def get(path):
            with opener.open(base+path,timeout=3) as response:return response.read()
        status=json.loads(get('/api/status'))
        require_install_idle(status)
        data=Path(status['data_dir']).resolve()
        default_library=Path.home()/'Library/Application Support/Stellar Secretary'
        preferences=library_location.read()
        configured_library=Path(preferences.get('active') or preferences.get('source') or default_library)
        require(data==configured_library.resolve(),
                'Running library differs from the configured installation library')
        require(target.is_dir() and not target.is_symlink(), 'Expected an existing installed application')
        database=data/'archive.sqlite3'
        with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
            preserved_columns=[row[1] for row in db.execute('PRAGMA table_info(items)')]
        require(preserved_columns,'Missing archive schema')
        pid=listener_pid(port)
        verify_install_process(pid,target,status)
        nonce=uuid.uuid4().hex[:10];staging=target.with_name('.Stellar Secretary.staging-'+nonce+'.app');backup=target.with_name('.Stellar Secretary.backup-'+nonce+'.app')
        try:
            shutil.copytree(self.app,staging,symlinks=True)
            run('codesign','--verify','--deep','--strict',staging)
            require(listener_pid(port)==pid, 'Listening process changed during staging')
            latest=json.loads(get('/api/status'))
            require_install_idle(latest)
            require(latest['token']==status['token'] and latest['data_dir']==status['data_dir'],
                    'Running library or service changed during staging')
            # Older installations only support the original shutdown endpoint.
            endpoint='/api/update/shutdown' if latest.get('capabilities',{}).get('guarded_upgrade_shutdown') else '/api/shutdown'
            request=urllib.request.Request(base+endpoint,data=b'{}',headers={'Content-Type':'application/json','X-Knowledge-Token':latest['token']})
            try:
                with opener.open(request,timeout=5) as response:require(response.status==200,'Shutdown failed')
            except urllib.error.HTTPError as error:
                if error.code!=409:raise
                error.close()
                raise RuntimeError('Service became busy; installation deferred') from None
        except BaseException:
            if staging.exists():shutil.rmtree(staging)
            raise
        for _ in range(100):
            try:os.kill(pid,0)
            except ProcessLookupError:break
            time.sleep(.2)
        else:raise RuntimeError('Old application still running; replacement deferred')
        # Include any completed edits made while the signed app was staged.
        before,count=archive_fingerprint(database,preserved_columns)
        file_state=library_file_state(data)
        mode=latest['settings'].get('company_mode',False)
        target.rename(backup)
        try:staging.rename(target)
        except BaseException:backup.rename(target);raise
        try:
            launch=launch_mac(target)
        except OSError:
            launch=None
        current=wait_mac_status(get,launch,self.version) if launch is not None else None
        if current is None:
            require(launch is None or launch.poll() is not None,
                    f'New application is still starting; previous app preserved at {backup}')
            try:
                failed=recover_mac_launch(target,backup,port,data,get,(file_state,(before,count)),preserved_columns,mode)
            except (OSError,ValueError,RuntimeError,KeyError,sqlite3.Error,subprocess.SubprocessError) as error:
                raise RuntimeError(f'Upgrade recovery incomplete: {error}. Inspect {target} and {backup}') from error
            raise RuntimeError(f'Upgrade failed; restored the previous app and verified its library. Failed build: {failed}')
        installed_pid=listener_pid(port)
        require(output('/bin/ps','-p',str(installed_pid),'-o','comm=').strip()==str(target/'Contents/MacOS/Stellar Secretary'),
                'Updated installation does not own the listening port')
        require(current['data_dir']==str(data) and current['settings'].get('company_mode',False)==mode,'Data directory or company mode changed')
        require(archive_fingerprint(database,preserved_columns)==(before,count),'Archived data changed during installation')
        require(digest(target/'Contents/MacOS/Stellar Secretary')==digest(self.app/'Contents/MacOS/Stellar Secretary'),'Installed binary differs')
        for name in ('bundle-ui.js','library-preview.js','image-viewer.js'):
            require(get('/'+name)==(self.app/'Contents/Resources/secretary/static'/name).read_bytes(),'Running UI differs: '+name)
        print(f'PASS: installed {self.tag}; all columns of {count} records preserved')
        try:
            for path in remove_artifacts(unused_mac_rollbacks(target)):
                print('Removed old program rollback:',path)
        except (OSError,subprocess.CalledProcessError) as error:
            print(f'Could not finish old program rollback cleanup: {error}',file=sys.stderr)

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
