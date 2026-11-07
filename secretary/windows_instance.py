"""Hold a Windows desktop slot before probing HTTP or constructing Qt objects."""
import ctypes
from ctypes import wintypes
import time


class DesktopSlot:
    def __init__(self, port):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel.ReleaseMutex.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel = kernel
        self.handle = kernel.CreateMutexW(None, False, 'Local\\Stellar.Secretary.Desktop.'+str(port))
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.owned = False

    def acquire(self):
        result = self.kernel.WaitForSingleObject(self.handle, 0)
        if result in (0, 0x80):  # acquired, or previous owner crashed
            self.owned = True
            return True
        if result == 0x102:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            if self.owned:
                self.kernel.ReleaseMutex(self.handle)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def acquire_or_activate(slot, activate, timeout=60):
    """Wait through startup/shutdown without creating a second tray or profile."""
    deadline = time.monotonic()+timeout
    while True:
        if slot.acquire():
            return True
        if activate():
            return False
        if time.monotonic() >= deadline:
            raise RuntimeError('桌面实例尚未就绪，请查看 app.log；未创建重复窗口。')
        time.sleep(.2)
