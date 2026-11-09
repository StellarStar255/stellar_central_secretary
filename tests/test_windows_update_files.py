import os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from secretary import windows_update_files

@unittest.skipUnless(sys.platform=='win32','Requires real Windows file sharing and process handles')
class WindowsResourceLockTest(unittest.TestCase):
 def test_orphaned_owned_engine_releases_snapshot_but_other_engine_survives(self):
  with tempfile.TemporaryDirectory() as temp:
   base=Path(temp);root=base/'安装 with spaces';engine=root/'_internal'/'PySide6';resources=engine/'resources';resources.mkdir(parents=True)
   snapshot=resources/'v8_context_snapshot.bin';snapshot.write_bytes(b'original snapshot')
   outside=base/'other application';outside.mkdir();otherfile=outside/'other.bin';otherfile.write_bytes(b'keep')
   source=base/'Holder.cs';source.write_text('''using System;using System.IO;using System.Threading;
class Holder {static void Main(string[] args) {using(var stream=new FileStream(args[0],FileMode.Open,FileAccess.Read,FileShare.Read)){File.WriteAllText(args[1],"ready");Thread.Sleep(Timeout.Infinite);}}}''')
   compiler=Path(os.environ['SystemRoot'])/'Microsoft.NET'/'Framework64'/'v4.0.30319'/'csc.exe'
   target=engine/'QtWebEngineProcess.exe';subprocess.run([str(compiler),'/nologo','/out:'+str(target),str(source)],check=True,capture_output=True)
   import shutil
   other=outside/'QtWebEngineProcess.exe';shutil.copyfile(target,other)
   ready=base/'ready';ready_other=base/'ready-other';owned=subprocess.Popen([str(target),str(snapshot),str(ready)]);unrelated=subprocess.Popen([str(other),str(otherfile),str(ready_other)])
   try:
    deadline=time.monotonic()+15
    while not (ready.exists() and ready_other.exists()):
     if time.monotonic()>deadline:self.fail('lock fixtures did not start')
     time.sleep(.05)
    # Reproduce the exact user failure: snapshot replacement denied with error 32.
    with self.assertRaises(PermissionError):snapshot.unlink()
    api=windows_update_files.kernel();handle=api.OpenProcess(0x1000,False,owned.pid)
    try:self.assertEqual(windows_update_files.image(api,handle),target.resolve())
    finally:api.CloseHandle(handle)
    windows_update_files.release(root,grace=.1,timeout=2)
    owned.wait(timeout=5);self.assertIsNone(unrelated.poll());snapshot.unlink();snapshot.write_bytes(b'new snapshot')
    self.assertEqual(snapshot.read_bytes(),b'new snapshot')
    print('PASS: real Windows snapshot file-lock reproduced and cleared; unrelated same-named engine untouched')
   finally:
    for process in (owned,unrelated):
     if process.poll() is None:process.terminate()
     process.wait(timeout=10)
