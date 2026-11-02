"""Launch system applications without inheriting the frozen Linux library paths."""
import os,subprocess,sys,webbrowser


def external_env(source=None):
    env=dict(os.environ if source is None else source)
    if sys.platform.startswith('linux') and getattr(sys,'frozen',False):
        original=env.get('LD_LIBRARY_PATH_ORIG')
        if original:env['LD_LIBRARY_PATH']=original
        else:env.pop('LD_LIBRARY_PATH',None)
        root=str(getattr(sys,'_MEIPASS',''))
        for key in ('QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','QTWEBENGINEPROCESS_PATH'):
            if root and root in env.get(key,''):env.pop(key,None)
    return env


def open_browser(url):
    if not sys.platform.startswith('linux'):return webbrowser.open(url)
    try:
        subprocess.Popen(['xdg-open',str(url)],env=external_env(),stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,stderr=sys.stderr,start_new_session=True)
        return True
    except OSError as error:
        print('Unable to open system application:',error,file=sys.stderr,flush=True)
        return False
