"""Bundle TkDND's native arm64 / Tcl 8 library and companion scripts."""
from pathlib import Path
from PyInstaller.utils.hooks import get_package_paths

_, package_dir = get_package_paths('tkinterdnd2')
source = Path(package_dir) / 'tkdnd' / 'osx-arm64'
if not source.is_dir():
    raise RuntimeError('Required Apple Silicon TkDND native library is missing')
destination = 'tkinterdnd2/tkdnd/osx-arm64'
binaries = [(str(path), destination) for path in source.glob('*.dylib')]
datas = [(str(path), destination) for path in source.glob('*.tcl')]
if not binaries:
    raise RuntimeError('No Apple Silicon TkDND dylib was found')
