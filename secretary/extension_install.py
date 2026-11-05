"""Export the bundled browser extension to a persistent, user-visible directory."""
import argparse,io,json,os,subprocess,sys,threading,zipfile
from pathlib import Path
from .attachment_editor import atomic

_lock=threading.Lock()

def source_dir():
    return Path(__file__).resolve().parent.parent/'browser-extension'

def payload(source=None):
    source=Path(source or source_dir()).resolve()
    if not (source/'manifest.json').is_file():raise ValueError('安装包中缺少浏览器扩展文件，请重新安装应用。')
    files={};total=0
    for path in sorted(source.rglob('*')):
        if path.is_symlink():raise ValueError('浏览器扩展文件无效。')
        if not path.is_file():continue
        if len(files)>=128 or path.stat().st_size>2*1024*1024:raise ValueError('浏览器扩展文件过大。')
        data=path.read_bytes();total+=len(data)
        if total>10*1024*1024:raise ValueError('浏览器扩展文件过大。')
        files[path.relative_to(source).as_posix()]=data
    manifest=json.loads(files['manifest.json'])
    if manifest.get('manifest_version')!=3 or manifest.get('action',{}).get('default_popup') not in files:raise ValueError('浏览器扩展清单无效。')
    return files,manifest

def prepare(root,source=None):
    files,manifest=payload(source)
    root=Path(root).resolve();target=root/'browser-extension';changed=0
    with _lock:
        if target.is_symlink():raise ValueError('浏览器扩展安装目录无效。')
        target.mkdir(parents=True,exist_ok=True)
        # Write the manifest last; keep the selected directory stable across app updates.
        for name in sorted(files,key=lambda name:name=='manifest.json'):
            path=target/name
            parent=target
            for part in path.relative_to(target).parts:
                parent=parent/part
                if parent.is_symlink():raise ValueError('浏览器扩展安装目录无效。')
            path.parent.mkdir(parents=True,exist_ok=True)
            if not path.is_file() or path.read_bytes()!=files[name]:atomic(path,files[name]);changed+=1
    return {'path':str(target),'version':manifest['version'],'updated':bool(changed),'platform':sys.platform}

def open_folder(root):
    result=prepare(root);target=Path(result['path'])
    if sys.platform=='darwin':subprocess.run(['/usr/bin/open',str(target)],check=True,timeout=15)
    elif os.name=='nt':os.startfile(str(target))
    else:
        from .system_integration import external_env
        subprocess.run(['xdg-open',str(target)],env=external_env(),check=True,timeout=15)
    return result

def download():
    files,_=payload();output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr('Stellar-Capture-Extension/'+name,data)
    return output.getvalue()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--data-dir',required=True);parser.add_argument('--source')
    args=parser.parse_args();print(json.dumps(prepare(args.data_dir,args.source),ensure_ascii=False))
