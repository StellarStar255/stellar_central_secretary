"""Detached update transaction: keep the previous program until the new app is healthy."""
import argparse,ctypes,hashlib,json,os,shutil,subprocess,sys,time,urllib.request,uuid,threading
from pathlib import Path
from . import paths,__version__

def atomic(path,value):
    path=Path(path);temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8');temp.replace(path)

def clean_env():
    env=dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1')
    for key in list(env):
        if key.upper()=='PSMODULEPATH':env.pop(key)
    root=str(getattr(sys,'_MEIPASS',''))
    if root:
        env['PATH']=os.pathsep.join(p for p in env.get('PATH','').split(os.pathsep) if not os.path.normcase(p).startswith(os.path.normcase(root)))
        for key in ('QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','QTWEBENGINEPROCESS_PATH'):
            if root.lower() in env.get(key,'').lower():env.pop(key,None)
    if sys.platform.startswith('linux'):
        original=env.get('LD_LIBRARY_PATH_ORIG')
        if original:env['LD_LIBRARY_PATH']=original
        else:env.pop('LD_LIBRARY_PATH',None)
    return env

def spawn(command,**kwargs):
    options=dict(env=clean_env(),stdin=subprocess.DEVNULL,**kwargs)
    if sys.platform=='win32':
        kernel=ctypes.windll.kernel32;kernel.GetDllDirectoryW.argtypes=[ctypes.c_uint32,ctypes.c_wchar_p];kernel.SetDllDirectoryW.argtypes=[ctypes.c_wchar_p]
        old=ctypes.create_unicode_buffer(32768);kernel.GetDllDirectoryW(len(old),old)
        try:
            if not kernel.SetDllDirectoryW(None):raise ctypes.WinError()
            return subprocess.Popen(command,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP,**options)
        finally:kernel.SetDllDirectoryW(old.value or None)
    return subprocess.Popen(command,start_new_session=True,**options)

def healthy(config,version,legacy=False):
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        endpoint='/api/status' if legacy else '/api/update/health'
        with opener.open(config['address']+endpoint,timeout=2) as response:value=json.loads(response.read(100000))
        same=Path(value.get('data_dir','')).resolve()==Path(config['data']).resolve()
        desktop=value.get('desktop',{})
        return value.get('application')=='stellar-central-secretary' and value.get('version')==version and same and (legacy or value.get('database_ok') is True and value.get('pid')==config.get('child_pid',value.get('pid'))) and (not config['desktop'] or desktop.get('supports_window') and (desktop.get('window_loaded') or desktop.get('mode')=='browser'))
    except (OSError,ValueError,TypeError):return False

def last_result():
    try:return json.loads((paths.DATA_DIR/'update-result.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}

def prepare(package,work,sha,version,desktop=False,kind=None,parent_pid=None):
    executable=Path(sys.executable).resolve();root=executable.parent
    kind=kind or ('mac' if sys.platform=='darwin' else 'windows' if sys.platform=='win32' else 'portable')
    if kind=='mac':root=next(p for p in executable.parents if p.suffix=='.app')
    data=paths.DATA_DIR.resolve();work=Path(work).resolve()
    if data.is_relative_to(root):raise RuntimeError('资料目录位于程序目录中，请先迁移资料后再自动升级。')
    if kind!='deb' and not os.access(root.parent,os.W_OK):raise RuntimeError('程序目录不可写，请手动安装新版。')
    if kind=='deb' and root!=Path('/opt/stellar-secretary'):raise RuntimeError('无法确认系统安装目录。')
    previous=work/('previous-program-'+uuid.uuid4().hex)
    shutil.copytree(root,previous,symlinks=True)
    args=[arg for arg in sys.argv[1:] if arg!='--desktop']
    if desktop:args.append('--desktop')
    if '--data-dir' not in args and not any(arg.startswith('--data-dir=') for arg in args):args+=['--data-dir',str(data)]
    parser=argparse.ArgumentParser(add_help=False);parser.add_argument('--port',type=int,default=8768);port=parser.parse_known_args(args)[0].port
    config=dict(root=str(root),backup=str(previous),executable=str(executable),package=str(Path(package).resolve()),
                sha=sha,version=version,old_version=__version__,data=str(data),work=str(work),kind=kind,
                parent=os.getpid() if parent_pid is None else parent_pid,args=args,desktop=desktop,address=f'http://127.0.0.1:{port}',timeout=60)
    spec=work/'transaction.json';atomic(spec,config);(work/'proceed').unlink(missing_ok=True)
    (work/'worker-ready').unlink(missing_ok=True)
    command=[str(previous/executable.relative_to(root)),'--update-transaction',str(spec)]
    if not paths.FROZEN:command=[getattr(sys,'_base_executable',sys.executable),'-m','secretary.update_transaction',str(spec)]
    with (work/'transaction.log').open('ab') as log:
        process=spawn(command,cwd=str(Path(__file__).resolve().parent.parent) if not paths.FROZEN else str(work),stdout=log,stderr=log)
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        if (work/'worker-ready').exists():
            (work/'proceed').write_text('ready');threading.Thread(target=process.wait,daemon=True).start();return True
        if process.poll() is not None:raise RuntimeError('更新助手未能启动，当前程序继续运行；请查看 transaction.log。')
        time.sleep(.1)
    raise RuntimeError('更新助手未就绪，当前程序继续运行；请查看 transaction.log。')

def run(config):
    root=Path(config['root']);backup=Path(config['backup']);work=Path(config['work']);data=Path(config['data'])
    if data.resolve().is_relative_to(root.resolve()) or not backup.is_dir():raise ValueError('无效的更新恢复目录')
    result=data/'update-result.json';child=None;changed=False;old_root=None;privileged_backup=None;parent_exited=False
    def report(phase,error=''):
        value=dict(phase=phase,error=error,version=config['version'],backup=str(backup),updated=time.time())
        atomic(result,value)
        if config['kind']=='windows':atomic(data/'windows-update.json',value)
    def launch():return spawn([config['executable'],*config['args']],cwd=str(root.parent),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def wait_health(version,legacy=False):
        deadline=time.monotonic()+config.get('timeout',60)
        while time.monotonic()<deadline:
            if healthy(config,version,legacy):return True
            if child is not None and child.poll() is not None:return False
            time.sleep(.25)
        return False
    def stop_child():
        if child is None or child.poll() is not None:return
        if os.name=='nt':subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,timeout=20)
        else:os.killpg(child.pid,15)
        try:child.wait(timeout=15)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
    try:
        (work/'worker-ready').write_text('ready')
        deadline=time.monotonic()+30
        while not (work/'proceed').exists():
            if time.monotonic()>deadline:raise RuntimeError('更新交接未确认，已取消安装。')
            time.sleep(.1)
        deadline=time.monotonic()+120
        while config.get('parent',0):
            try:os.kill(config['parent'],0)
            except OSError:break
            if time.monotonic()>deadline:raise RuntimeError('旧程序尚未退出，已取消安装。')
            time.sleep(.2)
        parent_exited=True
        report('installing')
        sha=hashlib.sha256()
        with open(config['package'],'rb') as source:
            for chunk in iter(lambda:source.read(1024*1024),b''):sha.update(chunk)
        if sha.hexdigest()!=config['sha']:raise RuntimeError('安装包校验失败，未执行安装。')
        kind=config['kind']
        if kind=='windows':
            from .windows_update_files import release
            release(root)
            changed=True
            process=spawn([config['package'],'/SP-','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CLOSEAPPLICATIONS','/LOGCLOSEAPPLICATIONS','/NORESTARTAPPLICATIONS','/RESTARTEXITCODE=3010','/DIR='+str(root),'/LOG='+str(work/'installer.log')],cwd=str(work),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:code=process.wait(timeout=300)
            except subprocess.TimeoutExpired:
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=20);process.wait(timeout=20)
                raise RuntimeError('安装程序超时，正在恢复旧版。')
            if code:raise RuntimeError('安装程序失败（退出码 '+str(code)+'），正在恢复旧版。日志：'+str(work/'installer.log'))
        elif kind=='mac':
            mount=work/'mounted';mount.mkdir(exist_ok=True)
            subprocess.run(['hdiutil','attach','-readonly','-nobrowse','-mountpoint',str(mount),config['package']],check=True,capture_output=True)
            try:
                candidate=mount/'Stellar Secretary.app'
                subprocess.run(['codesign','--verify','--deep','--strict',str(candidate)],check=True,capture_output=True)
                signature=subprocess.run(['codesign','-dvv',str(candidate)],capture_output=True,text=True)
                if 'TeamIdentifier=3QCL9WNFBB' not in signature.stderr:raise RuntimeError('新程序签名不匹配。')
                stage=root.with_name(root.name+'.new-'+uuid.uuid4().hex);shutil.copytree(candidate,stage,symlinks=True)
            finally:subprocess.run(['hdiutil','detach',str(mount)],capture_output=True)
            old_root=root.with_name(root.name+'.previous-'+uuid.uuid4().hex);root.rename(old_root);changed=True;stage.rename(root)
        elif kind=='portable':
            from .linux_update import prepare_portable
            stage,candidate=prepare_portable(config['package'],root,data)
            old_root=root.with_name(root.name+'.previous-'+uuid.uuid4().hex);root.rename(old_root);changed=True;candidate.rename(root)
        elif kind=='deb':
            if root!=Path('/opt/stellar-secretary'):raise RuntimeError('系统安装目录不匹配。')
            from .linux_update import DEB_INSTALL
            privileged_backup='/opt/.stellar-secretary.previous-'+uuid.uuid4().hex
            script='set -eu\ntest ! -L /opt/stellar-secretary\ncp -a /opt/stellar-secretary "$4"\n'+DEB_INSTALL
            process=spawn(['pkexec','/bin/sh','-c',script,'stellar-update',config['package'],config['sha'],config['version'],privileged_backup],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            changed=True
            if process.wait():raise RuntimeError('系统安装未完成。')
        else:raise ValueError('未知更新类型')
        child=launch();config['child_pid']=child.pid;report('checking')
        if not wait_health(config['version']):raise RuntimeError('新版窗口、版本或资料库健康检查未通过。')
        report('complete');threading.Thread(target=child.wait,daemon=True).start();return True
    except Exception as error:
        message=str(error)
        if changed:
            try:
                stop_child()
                if privileged_backup:
                    script='set -eu\ntest -d "$1"\nmv /opt/stellar-secretary "$2"\nmv "$1" /opt/stellar-secretary\n'
                    process=spawn(['pkexec','/bin/sh','-c',script,'stellar-rollback',privileged_backup,'/opt/.stellar-secretary.failed-'+uuid.uuid4().hex],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    if process.wait(timeout=120):raise RuntimeError('恢复旧版需要系统安装授权。')
                else:
                    restored=root.with_name(root.name+'.restore-'+uuid.uuid4().hex)
                    shutil.copytree(old_root or backup,restored,symlinks=True)
                    if root.exists():root.rename(root.with_name(root.name+'.failed-'+uuid.uuid4().hex))
                    restored.rename(root)
                child=launch()
                if not wait_health(config['old_version'],legacy=True):raise RuntimeError('旧版程序已恢复，但启动健康检查失败。')
                report('rolled_back',message+' 已恢复旧版程序，资料保留。');threading.Thread(target=child.wait,daemon=True).start();return False
            except Exception as recovery:message+=' 恢复未完成：'+str(recovery)+'；程序备份：'+str(old_root or backup)
        report('error',message)
        if not changed and parent_exited:
            try:
                child=launch();threading.Thread(target=child.wait,daemon=True).start()
            except OSError:pass
        return False

def main():
    spec=Path(sys.argv[-1]);config=json.loads(spec.read_text(encoding='utf-8'));run(config)

if __name__=='__main__':main()
