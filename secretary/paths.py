"""Keep installed application data outside the replaceable application bundle."""
import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, 'frozen', False))


def data_dir():
    if os.environ.get('SECRETARY_DATA_DIR'):
        return Path(os.environ['SECRETARY_DATA_DIR']).expanduser().resolve()
    if not FROZEN:
        return Path(__file__).resolve().parent.parent / 'data'
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/Stellar Secretary'
    if sys.platform.startswith('linux'):
        return Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share') / 'stellar-secretary'
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Stellar Secretary'


DATA_DIR = data_dir()


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
