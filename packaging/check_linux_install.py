"""Exercise the privileged Debian update helper on a disposable Ubuntu CI runner."""
import hashlib,os,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from secretary.linux_update import DEB_INSTALL


def main():
    if sys.platform!='linux' or os.environ.get('GITHUB_ACTIONS')!='true':
        raise SystemExit('Run only on the disposable Linux CI runner')
    with tempfile.TemporaryDirectory(prefix='stellar-deb-helper-') as folder:
        root=Path(folder);package=root/'fixture';control=package/'DEBIAN';control.mkdir(parents=True)
        (control/'control').write_text('Package: stellar-secretary\nVersion: 0.0.0\nArchitecture: amd64\nMaintainer: CI <ci@example.invalid>\nDescription: Disposable updater validation fixture\n')
        doc=package/'usr/share/doc/stellar-secretary';doc.mkdir(parents=True);(doc/'update-fixture').write_text('verified root helper')
        archive=root/'fixture.deb';subprocess.run(['dpkg-deb','--root-owner-group','--build',str(package),str(archive)],check=True)
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        for checksum,version,success in [('0'*64,'0.0.0',False),(digest,'99.0.0',False),(digest,'0.0.0',True)]:
            result=subprocess.run(['sudo','-n','/bin/sh','-c',DEB_INSTALL,'stellar-secretary-update',str(archive),checksum,version],capture_output=True,text=True)
            assert (result.returncode==0)==success,result.stdout+result.stderr
        assert Path('/usr/share/doc/stellar-secretary/update-fixture').read_text()=='verified root helper'
        subprocess.run(['sudo','-n','apt-get','remove','--yes','stellar-secretary'],check=True)
    print('PASS: privileged Debian helper rejects checksum/version mismatches and installs the verified package')

if __name__=='__main__':main()
