# One-file desktop application; intentionally unsigned on every platform.
import importlib.util
import os
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
required = ('numpy', 'scipy', 'PIL', 'av', 'sounddevice', 'serial', 'tkinter')
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit('Missing build dependencies: ' + ', '.join(missing))
assets = Path(os.environ['OPENKGSTV_BUILD_ASSETS'])
if not (assets / 'THIRD-PARTY-NOTICES.txt').is_file():
    raise SystemExit('Use python tools/build_standalone.py to collect licences first.')
datas = collect_data_files('kgstv', includes=['assets/*'])
datas += [(str(assets), 'distribution'), (str(root / 'LICENSE'), 'distribution')]
for package in ('numpy', 'scipy', 'Pillow', 'av', 'sounddevice', 'pyserial', 'cffi'):
    datas += copy_metadata(package)
hidden = collect_submodules('av') + ['serial.tools.list_ports', 'encodings.cp932']
if sys.platform.startswith('linux'):
    # Pillow 12 loads this bridge dynamically from its native ImageTk module.
    hidden.append('PIL._tkinter_finder')
# Linux sounddevice locates PortAudio with ctypes at runtime; bundle the SONAME
# explicitly. Windows' sounddevice hook collects its own vendor DLLs.
binaries = []
if sys.platform.startswith('linux'):
    from ctypes.util import find_library
    from PyInstaller.depend.bindepend import resolve_library_path
    portaudio = resolve_library_path(find_library('portaudio') or 'libportaudio.so.2')
    if not portaudio:
        raise SystemExit('Install libportaudio2 in the Linux build image.')
    binaries.append((portaudio, '.'))
a = Analysis([str(root / 'packaging' / 'entry.py')], pathex=[str(root)],
             binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['pytest', 'matplotlib', 'pandas', 'IPython', 'torch', 'PyQt5', 'PyQt6'],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='OpenKGSTV',
          console=sys.platform != 'win32', debug=False, strip=False, upx=False,
          icon=str(assets / 'openkgstv.ico') if sys.platform == 'win32' else None,
          codesign_identity=None, entitlements_file=None)
