"""Rediscover only Chrome instances using the app's exact dedicated profile."""
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit


def argument(command,name):
    match=re.search(r'(?:^|\s)"?--'+re.escape(name)+r'=(?:"([^"]*)"|(.*?))(?=\s--|$)',command)
    return (match.group(1) if match and match.group(1) is not None else match.group(2).rstrip('"') if match else None)


def owned_processes(profile,chrome):
    if not chrome:return []
    profile=os.path.normcase(str(Path(profile).resolve()))
    try:
        if os.name=='nt':
            script="$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new();Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | Select-Object ProcessId,CommandLine,ExecutablePath | ConvertTo-Json -Compress"
            result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
            raw=json.loads(result.stdout or '[]');raw=raw if isinstance(raw,list) else [raw]
            rows=[(str(row.get('ProcessId','')),row.get('CommandLine') or '') for row in raw if row.get('ExecutablePath') and os.path.normcase(str(Path(row['ExecutablePath']).resolve()))==os.path.normcase(str(Path(chrome).resolve()))]
        else:
            matched=subprocess.run(['pgrep','-f','^'+re.escape(chrome)+'( |$)'],capture_output=True,text=True,timeout=3)
            pids=[line.strip() for line in matched.stdout.splitlines() if line.strip().isdigit()]
            if not pids:return []
            result=subprocess.run(['ps','-p',','.join(pids),'-o','uid=,pid=,command='],capture_output=True,text=True,timeout=3)
            rows=[]
            for line in result.stdout.splitlines():
                parts=line.strip().split(None,2)
                if len(parts)==3 and parts[0]==str(os.getuid()) and parts[2].startswith(chrome+' '):rows.append((parts[1],parts[2]))
        owned=[]
        for pid,command in rows:
            directory=argument(command,'user-data-dir')
            if not directory or os.path.normcase(str(Path(directory).resolve()))!=profile:continue
            if argument(command,'remote-debugging-address')!='127.0.0.1':continue
            port=argument(command,'remote-debugging-port')
            if port and port.isdigit() and 0<int(port)<65536:owned.append({'pid':int(pid),'endpoint':'http://127.0.0.1:'+port})
        return owned
    except (OSError,ValueError,TypeError,subprocess.TimeoutExpired):return []


def active_port_session(profile,probe):
    try:
        path=Path(profile)/'DevToolsActivePort'
        if path.stat().st_size>4096:return None
        port,websocket_path,*_=path.read_text().splitlines()
        if not port.isdigit() or not 0<int(port)<65536 or not re.fullmatch(r'/devtools/browser/[A-Za-z0-9-]+',websocket_path):return None
        session=probe('http://127.0.0.1:'+port)
        if urlsplit(session['websocket']).path==websocket_path:return session
    except (OSError,ValueError,KeyError):pass
    return None


def discover(profile,chrome,probe):
    current=active_port_session(profile,probe)
    if current:return current
    for process in owned_processes(profile,chrome):
        try:return probe(process['endpoint'])
        except (OSError,ValueError):pass
    return None
