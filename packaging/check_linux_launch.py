"""Check released Linux packages through their default graphical launch paths."""
import argparse,json,os,shlex,shutil,socket,subprocess,tempfile,time,urllib.request
from pathlib import Path

parser=argparse.ArgumentParser();parser.add_argument('--installed',action='store_true');parser.add_argument('--portable');parser.add_argument('--browser',choices=['chrome','firefox'],default='chrome');args=parser.parse_args()
result=Path('test-results/linux-launch').resolve();result.mkdir(parents=True,exist_ok=True)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));checks=[]
def get(url):
    with opener.open(url,timeout=2) as response:return json.load(response)
def wait(check,seconds=40):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        try:
            value=check()
            if value:return value
        except (OSError,ValueError):pass
        time.sleep(.25)
    return None
def free_port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]

with tempfile.TemporaryDirectory(prefix='stellar-linux-launch-',ignore_cleanup_errors=True) as root:
    root=Path(root);data_home=root/'data';config_home=root/'config'
    applications=data_home/'applications';applications.mkdir(parents=True);config_home.mkdir()
    browser=(shutil.which('google-chrome') or shutil.which('chromium')) if args.browser=='chrome' else shutil.which('firefox')
    if not browser:raise SystemExit('Install the selected browser for the graphical launch check')
    modes=[]
    if args.installed:modes.append(('installed-desktop',['gtk-launch','stellar-secretary'],8768))
    if args.portable:modes.append(('portable-default',[str(Path(args.portable).resolve())],free_port()))
    for name,command,port in modes:
        browser_port=free_port();profile=root/(name+'-'+args.browser);data=root/(name+'-data')
        profile.mkdir()
        screenshot=result/(name+'-browser.png')
        browser_command=([browser,'--no-sandbox','--disable-dev-shm-usage','--no-first-run',f'--user-data-dir={profile}',f'--remote-debugging-port={browser_port}'] if args.browser=='chrome'
                         else [browser,'--no-remote','--profile',str(profile),'--headless','--screenshot',str(screenshot),'--window-size','1280,900'])
        wrapper=root/(name+'-browser')
        wrapper.write_text('#!/bin/sh\nprintf "%s\\n" "LD_LIBRARY_PATH=$LD_LIBRARY_PATH" "LD_LIBRARY_PATH_ORIG=$LD_LIBRARY_PATH_ORIG" "$@" >> '+shlex.quote(str(result/(name+'-browser-env.log')))+'\n'+shlex.join(browser_command)+' "$@" > '+shlex.quote(str(result/(name+'-browser.log')))+' 2>&1 &\n')
        wrapper.chmod(0o755)
        desktop=applications/'stellar-browser-probe.desktop'
        desktop.write_text('[Desktop Entry]\nType=Application\nName=Stellar browser launch probe\nExec='+str(wrapper)+' %U\nMimeType=x-scheme-handler/http;x-scheme-handler/https;\n')
        env={**os.environ,'XDG_DATA_HOME':str(data_home),'XDG_CONFIG_HOME':str(config_home),'SECRETARY_DATA_DIR':str(data)}
        env.pop('BROWSER',None)
        subprocess.run(['xdg-mime','default',desktop.name,'x-scheme-handler/http'],env=env,check=True)
        subprocess.run(['xdg-mime','default',desktop.name,'x-scheme-handler/https'],env=env,check=True)
        if name=='portable-default':command+=['--port',str(port)]
        capture=(result/(name+'-launcher.log')).open('w')
        process=subprocess.Popen(command,cwd='/tmp',env=env,stdout=capture,stderr=subprocess.STDOUT)
        address=f'http://127.0.0.1:{port}'
        status=wait(lambda:get(address+'/api/status'))
        browser_check=(lambda:[tab for tab in get(f'http://127.0.0.1:{browser_port}/json/list') if tab.get('url','').startswith(address)]) if args.browser=='chrome' else screenshot.exists
        opened=wait(browser_check,seconds=20) if status else None
        checks.append({'case':name,'browser':args.browser,'service_started':bool(status),'browser_opened':bool(opened),'launcher_exit':process.poll()})
        if status:
            request=urllib.request.Request(address+'/api/shutdown',data=b'{"force":true}',headers={'Content-Type':'application/json','X-Knowledge-Token':status['token']})
            try:opener.open(request,timeout=3).close()
            except OSError:pass
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
        capture.close()
        if (data/'app.log').exists():shutil.copy2(data/'app.log',result/(name+'-app.log'))
        subprocess.run(['pkill','-f',str(profile)],check=False)
        gone=lambda:subprocess.run(['pgrep','-f',str(profile)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
        if not wait(gone,seconds=5):
            subprocess.run(['pkill','-KILL','-f',str(profile)],check=False)
            wait(gone,seconds=3)
        print(json.dumps(checks[-1]),flush=True)
    (result/'result.json').write_text(json.dumps(checks,indent=2))
    if not all(check['service_started'] and check['browser_opened'] for check in checks):raise SystemExit('Default Linux launch failed; see uploaded diagnostics')
    print('PASS: installed desktop entry and portable default launch start the service and open the browser')
