import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from secretary import __version__

MAC = sys.platform == 'darwin'
APP = 'Stellar Secretary'
driver = Path(__import__('playwright').__file__).parent / 'driver'
node = driver / ('node.exe' if sys.platform == 'win32' else 'node')
datas = [(str(ROOT/'secretary/static'), 'secretary/static'),
         (str(ROOT/'browser-extension'), 'browser-extension'), (str(ROOT/'LICENSE'), '.')]
datas += [item for item in collect_data_files('playwright') if Path(item[0]) != node]
if not MAC:
    datas.append((str(ROOT/'packaging/THIRD_PARTY_NOTICES.md'),'.'))
    for package in ('PySide6','PySide6_Essentials','PySide6_Addons','shiboken6'):datas+=copy_metadata(package)
a = Analysis([str(ROOT/'packaging/entry_gui.py')], pathex=[str(ROOT)],
             binaries=[(str(node), 'playwright/driver')], datas=datas,
             hiddenimports=collect_submodules('secretary') + collect_submodules('pypdf')
                           + ['cryptography.hazmat.primitives.ciphers', 'fontTools.t1Lib'],
             excludes=['tkinter', 'matplotlib', 'numpy', 'IPython']+(['PySide6'] if MAC else []))
exe = EXE(PYZ(a.pure), a.scripts, [('X utf8', None, 'OPTION')],
          name=APP, exclude_binaries=True, console=False,
          icon=str(ROOT/'secretary/static/icons'/('app.icns' if MAC else 'app.ico')))
coll = COLLECT(exe, a.binaries, a.datas, name=APP)
if MAC:
    app = BUNDLE(coll, name=APP+'.app', version=__version__,
                 icon=str(ROOT/'secretary/static/icons/app.icns'),
                 bundle_identifier='io.github.stellarstar255.stellar-secretary',
                 info_plist={'CFBundleDisplayName': '知识秘书', 'NSHighResolutionCapable': True,
                             'CFBundleShortVersionString': __version__})
