# Reproducible Apple Silicon / Tcl 8 test build. Run from the project root.
from pathlib import Path
root = Path(SPECPATH).resolve().parents[1]
mac = root / 'packaging' / 'macos'
a = Analysis(
    [str(mac / 'launcher.py')],
    pathex=[str(root / 'src'), str(mac)],
    hookspath=[str(mac / 'hooks')],
    datas=[(str(root / 'LICENSE'), 'licenses/scg-stereorejoin'),
           (str(mac / 'licenses'), 'licenses/third-party')],
    hiddenimports=['tkinterdnd2'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='SCG StereoRejoin',
          debug=False, strip=False, upx=False, console=False,
          target_arch='arm64', codesign_identity=None, entitlements_file=None)
collect = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='SCG StereoRejoin')
app = BUNDLE(collect, name='SCG StereoRejoin.app',
             bundle_identifier='com.umikado.scg-stereorejoin', version='1.0.2',
             info_plist={
                 'CFBundleDisplayName': 'SCG StereoRejoin',
                 'CFBundleShortVersionString': '1.0.2',
                 'CFBundleVersion': '20261107.3',
                 'LSMinimumSystemVersion': '14.0',
                 'NSHighResolutionCapable': True,
                 'NSHumanReadableCopyright': 'MIT license; SCG StereoRejoin contributors',
             })
