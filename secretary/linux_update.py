"""Verified Linux package installation and rollback-capable portable replacement."""
import argparse,os,shlex,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path,PurePosixPath
from . import paths
from .system_integration import external_env


class ManualInstall(RuntimeError):pass


def install_kind(executable=None):
    root=Path(executable or sys.executable).resolve().parent
    try:
        value=(root/'.stellar-install-kind').read_text(encoding='utf-8').strip()
        if value in ('deb','portable'):return value
    except OSError:pass
    return 'deb' if root==Path('/opt/stellar-secretary').resolve() else 'portable'


DEB_INSTALL=r'''set -eu
WORK=$(mktemp -d /tmp/stellar-secretary-install.XXXXXX)
trap 'rm -rf -- "$WORK"' EXIT
cp -- "$1" "$WORK/package.deb"
printf '%s  %s\n' "$2" "$WORK/package.deb" | /usr/bin/sha256sum --check --status
test "$(/usr/bin/dpkg-deb -f "$WORK/package.deb" Package)" = stellar-secretary
test "$(/usr/bin/dpkg-deb -f "$WORK/package.deb" Version)" = "$3"
test "$(/usr/bin/dpkg-deb -f "$WORK/package.deb" Architecture)" = "$(/usr/bin/dpkg --print-architecture)"
/usr/bin/apt-get install --yes --no-remove "$WORK/package.deb"
'''


def _relaunch(work,replacement=None):
    executable=Path(sys.executable).resolve();current=executable.parent
    arguments=[argument for argument in sys.argv[1:] if argument not in ('--desktop','--no-browser')]
    command=shlex.join([str(executable),*arguments]);q=shlex.quote
    probe=argparse.ArgumentParser(add_help=False);probe.add_argument('--port',type=int,default=8768)
    port=probe.parse_known_args(arguments)[0].port
    script=work/'relaunch-linux.sh'
    header=f'''#!/bin/sh
exec >>{q(str(paths.DATA_DIR/'update.log'))} 2>&1
set -eu
PID={os.getpid()}
for i in $(seq 1 120); do kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
if kill -0 "$PID" 2>/dev/null; then echo 'Application still running; update cancelled'; exit 1; fi
'''
    if replacement is None:body=f'exec {command}\n'
    else:
        stage,new=replacement;backup=stage/'previous'
        # Keep the previous distribution until the replacement serves its local API.
        health='import json,urllib.request; o=urllib.request.build_opener(urllib.request.ProxyHandler({})); r=o.open('+repr(f'http://127.0.0.1:{port}/api/status')+',timeout=1); assert json.load(r)["application"]=="stellar-central-secretary"'
        body=f'''CURRENT={q(str(current))}
NEW={q(str(new))}
BACKUP={q(str(backup))}
mv -- "$CURRENT" "$BACKUP"
if ! mv -- "$NEW" "$CURRENT"; then mv -- "$BACKUP" "$CURRENT"; {command} & exit 1; fi
{command} &
CHILD=$!
OK=0
for i in $(seq 1 40); do
  if ! kill -0 "$CHILD" 2>/dev/null; then break; fi
  if python3 -I -c {q(health)} >/dev/null 2>&1; then OK=1; break; fi
  sleep 0.5
done
if [ "$OK" = 1 ]; then
  rm -rf -- {q(str(stage))}
  echo 'Portable update completed'
else
  kill "$CHILD" 2>/dev/null || true
  mv -- "$CURRENT" {q(str(stage/'failed'))}
  mv -- "$BACKUP" "$CURRENT"
  echo 'Replacement did not start; previous version restored'
  {command} &
fi
'''
    script.write_text(header+body,encoding='utf-8');script.chmod(0o700)
    env=external_env();env['PYINSTALLER_RESET_ENVIRONMENT']='1'
    subprocess.Popen(['/bin/sh',str(script)],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,close_fds=True,start_new_session=True)


def prepare_portable(archive,current,data_root):
    current=Path(current).resolve();data_root=Path(data_root).resolve()
    if data_root.is_relative_to(current):raise ManualInstall('资料目录位于程序目录中，请手动升级并保留资料目录。')
    if not os.access(current.parent,os.W_OK):raise ManualInstall('程序目录不可写，安装包已下载并校验，请手动升级。')
    if not (current/'_internal').is_dir() or not (current/'Stellar Secretary').is_file():raise ManualInstall('无法确认便携程序目录，请使用已下载的安装包手动升级。')
    if not shutil.which('python3'):raise ManualInstall('自动升级需要系统 Python 3；安装包已下载并校验，可手动替换程序目录。')
    stage=Path(tempfile.mkdtemp(prefix='.stellar-update-',dir=current.parent))
    try:
        with tarfile.open(archive,'r:gz') as source:
            members=source.getmembers()
            if len(members)>30000 or sum(member.size for member in members)>4*1024**3:raise ValueError('升级归档过大')
            for member in members:
                parts=PurePosixPath(member.name).parts
                if not parts or parts[0]!='Stellar-Secretary' or '..' in parts:raise ValueError('升级归档路径无效')
            source.extractall(stage,filter='data')
        new=stage/'Stellar-Secretary'
        if not (new/'Stellar Secretary').is_file() or (new/'Stellar Secretary').is_symlink() or not (new/'_internal').is_dir() or not (new/'start.sh').is_file():raise ValueError('升级归档缺少完整程序')
        if not os.access(new/'Stellar Secretary',os.X_OK):raise ValueError('升级程序缺少执行权限')
        return stage,new
    except BaseException:
        shutil.rmtree(stage);raise


def install(package,work,expected_sha,version):
    package=Path(package);work=Path(work)
    if install_kind()=='deb':
        pkexec=shutil.which('pkexec')
        if not pkexec:raise ManualInstall('系统未提供图形授权工具。安装包已下载并校验，请手动安装。')
        process=subprocess.run([pkexec,'/bin/sh','-c',DEB_INSTALL,'stellar-secretary-update',str(package),expected_sha,version],
                               env=external_env(),capture_output=True,text=True,timeout=300)
        with (paths.DATA_DIR/'update.log').open('a',encoding='utf-8') as log:log.write(process.stdout+process.stderr)
        if process.returncode:raise RuntimeError('系统安装未完成或授权已取消；程序继续运行，可查看升级日志后重试。')
        _relaunch(work)
    else:
        replacement=prepare_portable(package,Path(sys.executable).resolve().parent,paths.DATA_DIR)
        try:_relaunch(work,replacement)
        except BaseException:shutil.rmtree(replacement[0]);raise
    return True
