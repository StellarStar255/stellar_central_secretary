import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata,collect_dynamic_libs

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT))
from secretary import __version__

MAC = sys.platform == 'darwin'
WINDOWS = sys.platform == 'win32'
QT_DESKTOP = WINDOWS or sys.platform.startswith('linux')
APP = 'Stellar Secretary'
driver = Path(__import__('playwright').__file__).parent / 'driver'
node = driver / ('node.exe' if sys.platform == 'win32' else 'node')
datas = [(str(ROOT/'secretary/static'), 'secretary/static'),
         (str(ROOT/'browser-extension'), 'browser-extension'), (str(ROOT/'LICENSE'), '.'),
         (str(ROOT/'packaging/THIRD_PARTY_NOTICES.md'),'.')]
datas += collect_data_files('pypdfium2_raw') + collect_data_files('pypdfium2') + copy_metadata('pypdfium2')
datas += copy_metadata('pillow-heif')
datas += [item for item in collect_data_files('playwright') if Path(item[0]) != node]
if QT_DESKTOP:
    for package in ('PySide6','PySide6_Essentials','PySide6_Addons','shiboken6'):datas+=copy_metadata(package)
a = Analysis([str(ROOT/'packaging/entry_gui.py')], pathex=[str(ROOT)],
             binaries=[(str(node), 'playwright/driver')]+collect_dynamic_libs('pillow_heif'), datas=datas,
             hiddenimports=collect_submodules('qrcode') + collect_submodules('zeroconf') + collect_submodules('ifaddr') + collect_submodules('secretary') + collect_submodules('pypdf')
                           + collect_submodules('pillow_heif') + ['_pillow_heif','cryptography.hazmat.primitives.ciphers', 'fontTools.t1Lib'],
             excludes=['tkinter', 'matplotlib', 'numpy', 'IPython']+(['PySide6'] if not QT_DESKTOP else []))
if WINDOWS:
    # Qt >= 6.10 imports Windows' unversioned ICU API (Windows 10+). A conda
    # installation on the build machine's PATH can supply same-named DLLs with
    # incompatible, version-suffixed exports. Let Windows load its own ICU.
    system_icu = {'icu.dll', 'icuuc.dll', 'icuin.dll'}
    a.binaries = [item for item in a.binaries if Path(item[0]).name.lower() not in system_icu]
exe = EXE(PYZ(a.pure), a.scripts, [('X utf8', None, 'OPTION')],
          name=APP, exclude_binaries=True, console=False,
          icon=str(ROOT/'secretary/static/icons'/('app.icns' if MAC else 'app.ico')))
coll = COLLECT(exe, a.binaries, a.datas, name=APP)
if MAC:
    app = BUNDLE(coll, name=APP+'.app', version=__version__,
                 icon=str(ROOT/'secretary/static/icons/app.icns'),
                 bundle_identifier='io.github.stellarstar255.stellar-secretary',
                 info_plist={'CFBundleDisplayName': '知识秘书', 'NSHighResolutionCapable': True,
                             'CFBundleShortVersionString': __version__, 'NSLocalNetworkUsageDescription':'连接已配对的手机，共用本机知识库。', 'NSBonjourServices':['_stellar-sec._tcp']})
