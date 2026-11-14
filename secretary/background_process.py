"""Launch background helpers without a Windows console or console flash."""
import subprocess
import sys


def hidden_console():
    if sys.platform!='win32':return {}
    startup=subprocess.STARTUPINFO()
    startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow=subprocess.SW_HIDE
    return {'creationflags':subprocess.CREATE_NO_WINDOW,'startupinfo':startup}
