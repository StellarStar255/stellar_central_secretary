"""Release only orphaned WebEngine processes from this installation before updates."""
import ctypes,os,time
from ctypes import wintypes
from pathlib import Path

class Entry(ctypes.Structure):
    _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('pid',wintypes.DWORD),('heap',ctypes.c_size_t),('module',wintypes.DWORD),('threads',wintypes.DWORD),('parent',wintypes.DWORD),('priority',wintypes.LONG),('flags',wintypes.DWORD),('name',wintypes.WCHAR*260)]

def kernel():
    value=ctypes.WinDLL('kernel32',use_last_error=True)
    declarations={
      'CreateToolhelp32Snapshot':([wintypes.DWORD,wintypes.DWORD],wintypes.HANDLE),
      'Process32FirstW':([wintypes.HANDLE,ctypes.POINTER(Entry)],wintypes.BOOL),
      'Process32NextW':([wintypes.HANDLE,ctypes.POINTER(Entry)],wintypes.BOOL),
      'OpenProcess':([wintypes.DWORD,wintypes.BOOL,wintypes.DWORD],wintypes.HANDLE),
      'QueryFullProcessImageNameW':([wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL),
      'WaitForSingleObject':([wintypes.HANDLE,wintypes.DWORD],wintypes.DWORD),
      'TerminateProcess':([wintypes.HANDLE,wintypes.UINT],wintypes.BOOL),
      'CloseHandle':([wintypes.HANDLE],wintypes.BOOL),
      'CreateFileW':([wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE],wintypes.HANDLE)}
    for name,(args,result) in declarations.items():getattr(value,name).argtypes=args;getattr(value,name).restype=result
    return value

def image(api,handle):
    buffer=ctypes.create_unicode_buffer(32768);size=wintypes.DWORD(len(buffer))
    return Path(buffer.value) if api.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)) else None

def processes(api,root):
    handles=[];snapshot=api.CreateToolhelp32Snapshot(2,0)
    if snapshot==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry=Entry();entry.dwSize=ctypes.sizeof(entry);more=api.Process32FirstW(snapshot,ctypes.byref(entry))
        while more:
            name=entry.name.casefold()
            if entry.pid!=os.getpid() and name in ('qtwebengineprocess.exe','stellar secretary.exe'):
                handle=api.OpenProcess(0x1000|0x100000|1,False,entry.pid)
                if handle:
                    path=image(api,handle)
                    if path and (path==root/'Stellar Secretary.exe' or path.name.casefold()=='qtwebengineprocess.exe' and path.is_relative_to(root/'_internal')):handles.append((handle,path))
                    else:api.CloseHandle(handle)
            more=api.Process32NextW(snapshot,ctypes.byref(entry))
        return handles
    except BaseException:
        for handle,_ in handles:api.CloseHandle(handle)
        raise
    finally:api.CloseHandle(snapshot)

def release(root,grace=10,timeout=15):
    """Parent must already have exited. Never terminate another app or browser."""
    root=Path(root).resolve();api=kernel();handles=processes(api,root)
    try:
        if any(path.name.casefold()=='stellar secretary.exe' and api.WaitForSingleObject(handle,0)==258 for handle,path in handles):raise RuntimeError('另一个知识秘书实例仍在运行，未修改程序文件。请退出后重试更新。')
        deadline=time.monotonic()+grace
        for handle,path in handles:
            if path.name.casefold()!='qtwebengineprocess.exe':continue
            result=api.WaitForSingleObject(handle,max(0,int((deadline-time.monotonic())*1000)))
            if result==258:
                # A retained handle and rechecked image prevent PID-reuse mistakes.
                if image(api,handle)!=path or not api.TerminateProcess(handle,0):raise RuntimeError('无法结束本程序残留的浏览器进程，未开始安装。')
                if api.WaitForSingleObject(handle,5000)!=0:raise RuntimeError('本程序浏览器进程尚未退出，未开始安装。')
    finally:
        for handle,_ in handles:api.CloseHandle(handle)
    resources=root/'_internal'/'PySide6'/'resources'
    targets=[path for path in resources.glob('*') if path.is_file() and path.suffix.lower() in ('.bin','.pak','.dat')]
    deadline=time.monotonic()+timeout
    for path in targets:
        while True:
            handle=api.CreateFileW(str(path),0x80000000|0x10000,7,None,3,128,None)
            if handle!=ctypes.c_void_p(-1).value:api.CloseHandle(handle);break
            error=ctypes.get_last_error()
            if error in (2,3):break
            if error not in (32,33) or time.monotonic()>=deadline:raise RuntimeError('更新文件仍被占用，未开始安装：'+path.name+'（Windows 错误 '+str(error)+'）')
            time.sleep(.2)
