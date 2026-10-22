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
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Stellar Secretary'


DATA_DIR = data_dir()
