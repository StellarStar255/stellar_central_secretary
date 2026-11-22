"""Keep installed application data outside the replaceable application bundle."""
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, 'frozen', False))

def _windows_metadata():
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Stellar Secretary'


def _windows_fixed_drives():
    import ctypes
    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    system = os.environ.get('SystemDrive', 'C:').upper()
    for index, letter in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
        drive = letter + ':'
        if mask & (1 << index) and drive != system and kernel.GetDriveTypeW(ctypes.c_wchar_p(drive + '\\')) == 3:
            yield Path(drive + '\\')


def remembered_windows_data_dir():
    preference = _windows_metadata()/'data-location.txt'
    try:
        saved = Path(preference.read_text(encoding='utf-8').strip())
    except FileNotFoundError:
        saved = None
    return saved if saved is not None and saved.is_absolute() else None


def _windows_data_dir():
    import tempfile
    legacy = _windows_metadata()
    if saved := remembered_windows_data_dir():
        return saved
    if (legacy/'archive.sqlite3').is_file():
        return legacy
    for drive in _windows_fixed_drives():
        candidate = drive/'Stellar Secretary Data'/Path.home().name
        if candidate.is_relative_to(Path(sys.executable).resolve().parent):
            continue
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=candidate):
                pass
        except OSError:
            continue
        return candidate
    return legacy


def remember_windows_data_dir(directory):
    if sys.platform != 'win32' or not FROZEN:
        return
    import tempfile
    metadata = _windows_metadata()
    metadata.mkdir(parents=True, exist_ok=True)
    preference = metadata/'data-location.txt'
    directory = str(Path(directory).resolve())
    try:
        if preference.read_text(encoding='utf-8').strip() == directory:
            return
    except FileNotFoundError:
        pass
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=metadata, delete=False) as stream:
        stream.write(directory+'\n')
    temporary = Path(stream.name)
    try:
        temporary.replace(preference)
    finally:
        temporary.unlink(missing_ok=True)


def data_dir():
    if os.environ.get('SECRETARY_DATA_DIR'):
        return Path(os.environ['SECRETARY_DATA_DIR']).expanduser().resolve()
    if not FROZEN:
        return Path(__file__).resolve().parent.parent / 'data'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/Stellar Secretary'
    if sys.platform.startswith('linux'):
        return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share') / 'stellar-secretary'
    if sys.platform == 'win32':
        return _windows_data_dir()
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Stellar Secretary'


DATA_DIR = data_dir()


def inside_program(directory):
    if not FROZEN:
        return False
    executable = Path(sys.executable).resolve()
    program = next((parent for parent in executable.parents if parent.suffix == '.app'), executable.parent)
    return directory.is_relative_to(program)


def configure_tls():
    """Frozen OpenSSL cannot use the build machine's CA path on another Mac."""
    if FROZEN and sys.platform == 'darwin' and 'SSL_CERT_FILE' not in os.environ:
        system_roots = Path('/etc/ssl/cert.pem')
        if system_roots.is_file():
            os.environ['SSL_CERT_FILE'] = str(system_roots)
    if FROZEN and sys.platform.startswith('linux') and 'SSL_CERT_FILE' not in os.environ:
        system_roots = Path('/etc/ssl/certs/ca-certificates.crt')
        if system_roots.is_file():
            os.environ['SSL_CERT_FILE'] = str(system_roots)
